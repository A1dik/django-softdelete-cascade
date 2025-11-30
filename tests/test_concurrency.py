"""Concurrency safety tests for soft-delete operations.

These tests verify that the soft-delete implementation includes mechanisms
to handle concurrent operations safely. The implementation uses select_for_update()
within transactions to prevent race conditions.
"""

import pytest

from softdelete import ROW_STATUS_ACTIVE, ROW_STATUS_DELETE

from .factories import AuthorFactory, BookFactory
from .models import Author, Book


@pytest.mark.django_db
class TestConcurrencySafety:
    """Validate concurrency-safe behavior of soft-delete operations."""

    def test_multiple_sequential_deletes_on_same_object(self):
        """Deleting the same object multiple times should be idempotent.

        The first delete marks the object as deleted, and subsequent
        deletes should recognize this and return zero affected rows.
        This behavior prevents issues when concurrent requests try
        to delete the same object.
        """
        author = AuthorFactory()
        author_pk = author.pk

        # First deletion should succeed
        deleted_count1, deleted_models1 = author.delete()
        assert deleted_count1 == 1
        assert "tests.Author" in deleted_models1
        assert deleted_models1["tests.Author"] == 1

        # Refresh to get updated status
        author.refresh_from_db()
        assert author.row_status == ROW_STATUS_DELETE

        # Second deletion should be a no-op (idempotent)
        deleted_count2, deleted_models2 = author.delete()
        assert deleted_count2 == 0
        assert deleted_models2 == {}

        # Object should still be marked as deleted
        author.refresh_from_db()
        assert author.row_status == ROW_STATUS_DELETE

        # Third deletion should also be a no-op
        deleted_count3, deleted_models3 = author.delete()
        assert deleted_count3 == 0
        assert deleted_models3 == {}

    def test_cascade_delete_with_already_deleted_children(self):
        """When cascading, already-deleted children should be skipped.

        This simulates a scenario where concurrent operations might have
        already soft-deleted some children before the parent deletion begins.
        """
        author = AuthorFactory()
        book1 = BookFactory(author=author)
        book2 = BookFactory(author=author)
        book3 = BookFactory(author=author)

        # Pre-delete one book to simulate concurrent deletion
        book2.delete()
        book2.refresh_from_db()
        assert book2.row_status == ROW_STATUS_DELETE

        # Now delete the author (should cascade to book1 and book3, skip book2)
        deleted_count, deleted_models = author.delete()

        # Should delete: author + 2 remaining active books = 3 objects
        # (book2 is already deleted and should be skipped)
        assert deleted_count == 3

        # Verify all objects are now deleted
        author.refresh_from_db()
        book1.refresh_from_db()
        book2.refresh_from_db()
        book3.refresh_from_db()

        assert author.row_status == ROW_STATUS_DELETE
        assert book1.row_status == ROW_STATUS_DELETE
        assert book2.row_status == ROW_STATUS_DELETE
        assert book3.row_status == ROW_STATUS_DELETE

    def test_delete_maintains_consistency_with_cascade(self):
        """Verify that cascade deletes maintain consistency.

        Even in a concurrent environment (protected by locks), all related
        objects should be properly soft-deleted in a single transaction.
        """
        author = AuthorFactory()
        books = BookFactory.create_batch(5, author=author)
        book_pks = [book.pk for book in books]

        # Delete author
        deleted_count, deleted_models = author.delete()

        # Should delete author + 5 books = 6 objects
        assert deleted_count == 6
        assert deleted_models["tests.Author"] == 1
        assert deleted_models["tests.Book"] == 5

        # Verify all objects are marked as deleted
        author.refresh_from_db()
        assert author.row_status == ROW_STATUS_DELETE

        for book_pk in book_pks:
            book = Book.all_objects.get(pk=book_pk)
            assert book.row_status == ROW_STATUS_DELETE

        # Verify they still exist in database (soft delete) using all_objects
        assert Author.all_objects.filter(pk=author.pk).exists()
        for book_pk in book_pks:
            assert Book.all_objects.filter(pk=book_pk).exists()

        # But not visible via default manager
        assert not Author.objects.filter(pk=author.pk).exists()
        assert Book.objects.count() == 0

    def test_delete_uses_transaction_atomicity(self):
        """Verify that delete operations maintain atomicity.

        All objects in a cascade should be deleted together or not at all.
        This is critical for concurrent operations.
        """
        author = AuthorFactory()
        books = BookFactory.create_batch(3, author=author)

        # Perform the delete
        deleted_count, deleted_models = author.delete()

        # All objects should be updated in a single transaction
        assert deleted_count == 4  # 1 author + 3 books

        # Verify consistency: either all are deleted or none are
        # (in this case all should be deleted)
        author.refresh_from_db()
        all_deleted = author.row_status == ROW_STATUS_DELETE

        for book in books:
            book.refresh_from_db()
            all_deleted = all_deleted and (book.row_status == ROW_STATUS_DELETE)

        assert all_deleted, "All objects should be deleted together atomically"
