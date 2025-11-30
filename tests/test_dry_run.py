"""Tests for dry_run functionality in delete() and restore()."""

import pytest

from softdelete import ROW_STATUS_ACTIVE, ROW_STATUS_DELETE, SoftDeleteResult
from tests.models import Author, Book, Chapter, Page, Publisher, ProtectedBook


@pytest.mark.django_db
class TestDryRunDelete:
    """Tests for delete() with dry_run=True."""

    def test_dry_run_single_object_returns_result(self):
        """Test that dry_run delete returns SoftDeleteResult."""
        author = Author.objects.create(name='John Doe')

        result = author.delete(dry_run=True)

        assert isinstance(result, SoftDeleteResult)
        assert result.would_succeed is True
        assert result.total_count == 1
        assert result.affected_count == 1
        assert result.blocked_count == 0

        # Verify object is NOT actually deleted.
        author.refresh_from_db()
        assert author.row_status == ROW_STATUS_ACTIVE

    def test_dry_run_cascade_two_levels(self):
        """Test dry_run with 2-level cascade."""
        author = Author.objects.create(name='John Doe')
        book = Book.objects.create(title='Python Guide', author=author)

        result = author.delete(dry_run=True)

        assert result.would_succeed is True
        assert result.total_count == 2
        assert result.affected_count == 2

        # Check affected objects contain both author and book.
        model_labels = [ref.model_label for ref in result.affected_objects]
        assert 'tests.Author' in model_labels
        assert 'tests.Book' in model_labels

        # Verify nothing is actually deleted.
        author.refresh_from_db()
        book.refresh_from_db()
        assert author.row_status == ROW_STATUS_ACTIVE
        assert book.row_status == ROW_STATUS_ACTIVE

    def test_dry_run_cascade_four_levels(self):
        """Test dry_run with 4-level cascade."""
        author = Author.objects.create(name='John Doe')
        book = Book.objects.create(title='Python Guide', author=author)
        chapter1 = Chapter.objects.create(title='Intro', book=book)
        chapter2 = Chapter.objects.create(title='Advanced', book=book)
        page1 = Page.objects.create(number=1, chapter=chapter1)
        page2 = Page.objects.create(number=2, chapter=chapter1)
        page3 = Page.objects.create(number=1, chapter=chapter2)

        result = author.delete(dry_run=True)

        assert result.would_succeed is True
        assert result.total_count == 7  # author + book + 2 chapters + 3 pages
        assert result.affected_count == 7

        # Check model_counts breakdown.
        assert result.model_counts['tests.Author'] == 1
        assert result.model_counts['tests.Book'] == 1
        assert result.model_counts['tests.Chapter'] == 2
        assert result.model_counts['tests.Page'] == 3

        # Verify nothing is actually deleted.
        author.refresh_from_db()
        book.refresh_from_db()
        chapter1.refresh_from_db()
        chapter2.refresh_from_db()
        page1.refresh_from_db()
        page2.refresh_from_db()
        page3.refresh_from_db()
        assert author.row_status == ROW_STATUS_ACTIVE
        assert book.row_status == ROW_STATUS_ACTIVE
        assert chapter1.row_status == ROW_STATUS_ACTIVE
        assert chapter2.row_status == ROW_STATUS_ACTIVE
        assert page1.row_status == ROW_STATUS_ACTIVE
        assert page2.row_status == ROW_STATUS_ACTIVE
        assert page3.row_status == ROW_STATUS_ACTIVE

    def test_dry_run_already_deleted(self):
        """Test dry_run on already deleted object skips via early return."""
        author = Author.objects.create(name='John Doe')
        author.delete()  # Real delete.

        # Refresh from DB to get the updated row_status.
        author.refresh_from_db()

        # Now the early short-circuit should return empty result.
        result = author.delete(dry_run=True)

        assert result.would_succeed is True
        assert result.total_count == 0
        assert result.affected_count == 0
        assert len(result.affected_objects) == 0

    def test_dry_run_protect_blocked(self):
        """Test dry_run detects PROTECT constraint blocking deletion."""
        publisher = Publisher.objects.create(name='Acme Publishing')
        book = ProtectedBook.objects.create(title='Protected Book', publisher=publisher)

        result = publisher.delete(dry_run=True)

        assert result.would_succeed is False
        assert result.blocked_count == 1
        assert result.affected_count == 1  # Only publisher would be affected.

        # Check blocked_objects contains the book.
        assert len(result.blocked_objects) == 1
        blocked_ref = result.blocked_objects[0]
        assert blocked_ref.model_label == 'tests.ProtectedBook'
        assert blocked_ref.pk == book.pk

        # Verify nothing is actually deleted.
        publisher.refresh_from_db()
        book.refresh_from_db()
        assert publisher.row_status == ROW_STATUS_ACTIVE
        assert book.row_status == ROW_STATUS_ACTIVE

    def test_dry_run_protect_after_child_deleted(self):
        """Test dry_run succeeds after blocking child is deleted."""
        publisher = Publisher.objects.create(name='Acme Publishing')
        book = ProtectedBook.objects.create(title='Protected Book', publisher=publisher)

        # First dry_run should be blocked.
        result = publisher.delete(dry_run=True)
        assert result.would_succeed is False
        assert result.blocked_count == 1

        # Delete the book.
        book.delete()

        # Second dry_run should succeed.
        result = publisher.delete(dry_run=True)
        assert result.would_succeed is True
        assert result.blocked_count == 0
        assert result.affected_count == 1

        # Publisher should still be active.
        publisher.refresh_from_db()
        assert publisher.row_status == ROW_STATUS_ACTIVE

    def test_dry_run_to_tuple_conversion(self):
        """Test SoftDeleteResult.to_tuple() provides Django-compatible format."""
        author = Author.objects.create(name='John Doe')
        book = Book.objects.create(title='Python Guide', author=author)

        result = author.delete(dry_run=True)
        count, models_dict = result.to_tuple()

        assert count == 2
        assert isinstance(models_dict, dict)
        assert models_dict['tests.Author'] == 1
        assert models_dict['tests.Book'] == 1


@pytest.mark.django_db
class TestDryRunRestore:
    """Tests for restore() with dry_run=True."""

    def test_dry_run_restore_single_object(self):
        """Test dry_run restore returns SoftDeleteResult."""
        author = Author.objects.create(name='John Doe')
        author.delete()  # Soft delete it.

        result = author.restore(dry_run=True)

        assert isinstance(result, SoftDeleteResult)
        assert result.would_succeed is True
        assert result.total_count == 1
        assert result.affected_count == 1
        assert result.blocked_count == 0

        # Verify object is NOT actually restored.
        author.refresh_from_db()
        assert author.row_status == ROW_STATUS_DELETE

    def test_dry_run_restore_cascade(self):
        """Test dry_run restore with cascade."""
        author = Author.objects.create(name='John Doe')
        book = Book.objects.create(title='Python Guide', author=author)
        chapter = Chapter.objects.create(title='Intro', book=book)

        # Delete all via cascade.
        author.delete()

        # Dry-run restore.
        result = author.restore(dry_run=True)

        assert result.would_succeed is True
        assert result.total_count == 3
        assert result.affected_count == 3

        # Check affected objects.
        model_labels = [ref.model_label for ref in result.affected_objects]
        assert 'tests.Author' in model_labels
        assert 'tests.Book' in model_labels
        assert 'tests.Chapter' in model_labels

        # Verify nothing is actually restored.
        author.refresh_from_db()
        book.refresh_from_db()
        chapter.refresh_from_db()
        assert author.row_status == ROW_STATUS_DELETE
        assert book.row_status == ROW_STATUS_DELETE
        assert chapter.row_status == ROW_STATUS_DELETE

    def test_dry_run_restore_already_active(self):
        """Test dry_run restore on already active object returns empty result."""
        author = Author.objects.create(name='John Doe')

        result = author.restore(dry_run=True)

        assert result.would_succeed is True
        assert result.total_count == 0
        assert result.affected_count == 0
        assert len(result.affected_objects) == 0

    def test_dry_run_restore_without_children(self):
        """Test dry_run restore with restore_children=False."""
        author = Author.objects.create(name='John Doe')
        book = Book.objects.create(title='Python Guide', author=author)

        author.delete()  # Cascades to book.

        result = author.restore(dry_run=True, restore_children=False)

        assert result.would_succeed is True
        assert result.total_count == 1  # Only author.
        assert result.affected_count == 1

        # Book should not be in affected_objects.
        model_labels = [ref.model_label for ref in result.affected_objects]
        assert 'tests.Author' in model_labels
        assert 'tests.Book' not in model_labels

        # Verify nothing is actually restored.
        author.refresh_from_db()
        book.refresh_from_db()
        assert author.row_status == ROW_STATUS_DELETE
        assert book.row_status == ROW_STATUS_DELETE

    def test_dry_run_restore_partial_deletion(self):
        """Test dry_run restore when some objects are already active."""
        author = Author.objects.create(name='John Doe')
        book1 = Book.objects.create(title='Python Guide', author=author)
        book2 = Book.objects.create(title='Django Guide', author=author)

        # Delete only book1.
        book1.delete()

        # Dry-run restore on book1.
        result = book1.restore(dry_run=True)

        assert result.would_succeed is True
        assert result.total_count == 1  # Only book1.
        assert result.affected_count == 1

        # Verify book1 is still deleted.
        book1.refresh_from_db()
        assert book1.row_status == ROW_STATUS_DELETE


@pytest.mark.django_db
class TestDryRunEdgeCases:
    """Edge case tests for dry_run functionality."""

    def test_dry_run_ref_attributes(self):
        """Test SoftDeleteRef captures correct metadata."""
        author = Author.objects.create(name='John Doe')

        result = author.delete(dry_run=True)
        ref = result.affected_objects[0]

        assert ref.app_label == 'tests'
        assert ref.model_name == 'Author'
        assert ref.pk == author.pk
        assert ref.str_repr == str(author)
        assert ref.model_label == 'tests.Author'

    def test_dry_run_multiple_objects_same_model(self):
        """Test dry_run with multiple objects of the same model."""
        author = Author.objects.create(name='John Doe')
        book1 = Book.objects.create(title='Python Guide', author=author)
        book2 = Book.objects.create(title='Django Guide', author=author)
        book3 = Book.objects.create(title='Flask Guide', author=author)

        result = author.delete(dry_run=True)

        assert result.total_count == 4  # 1 author + 3 books
        assert result.model_counts['tests.Author'] == 1
        assert result.model_counts['tests.Book'] == 3

        # All objects should still be active.
        assert Author.objects.filter(row_status=ROW_STATUS_ACTIVE).count() == 1
        assert Book.objects.filter(row_status=ROW_STATUS_ACTIVE).count() == 3

    def test_real_delete_after_dry_run(self):
        """Test that real delete works correctly after dry_run."""
        author = Author.objects.create(name='John Doe')
        book = Book.objects.create(title='Python Guide', author=author)

        # First, dry-run.
        dry_result = author.delete(dry_run=True)
        assert dry_result.total_count == 2

        # Verify still active.
        author.refresh_from_db()
        book.refresh_from_db()
        assert author.row_status == ROW_STATUS_ACTIVE
        assert book.row_status == ROW_STATUS_ACTIVE

        # Now do real delete.
        count, models_dict = author.delete()
        assert count == 2
        assert models_dict['tests.Author'] == 1
        assert models_dict['tests.Book'] == 1

        # Verify actually deleted.
        author.refresh_from_db()
        book.refresh_from_db()
        assert author.row_status == ROW_STATUS_DELETE
        assert book.row_status == ROW_STATUS_DELETE

    def test_real_restore_after_dry_run(self):
        """Test that real restore works correctly after dry_run."""
        author = Author.objects.create(name='John Doe')
        book = Book.objects.create(title='Python Guide', author=author)

        # Delete them.
        author.delete()

        # First, dry-run restore.
        dry_result = author.restore(dry_run=True)
        assert dry_result.total_count == 2

        # Verify still deleted.
        author.refresh_from_db()
        book.refresh_from_db()
        assert author.row_status == ROW_STATUS_DELETE
        assert book.row_status == ROW_STATUS_DELETE

        # Now do real restore.
        count, models_dict = author.restore()
        assert count == 2
        assert models_dict['tests.Author'] == 1
        assert models_dict['tests.Book'] == 1

        # Verify actually restored.
        author.refresh_from_db()
        book.refresh_from_db()
        assert author.row_status == ROW_STATUS_ACTIVE
        assert book.row_status == ROW_STATUS_ACTIVE

    def test_dry_run_multiple_iterations(self):
        """Test dry_run can be called multiple times without side effects."""
        author = Author.objects.create(name='John Doe')
        book = Book.objects.create(title='Python Guide', author=author)

        # Call dry_run multiple times.
        result1 = author.delete(dry_run=True)
        result2 = author.delete(dry_run=True)
        result3 = author.delete(dry_run=True)

        # All results should be identical.
        assert result1.total_count == result2.total_count == result3.total_count == 2
        assert result1.would_succeed == result2.would_succeed == result3.would_succeed is True

        # Objects should still be active.
        author.refresh_from_db()
        book.refresh_from_db()
        assert author.row_status == ROW_STATUS_ACTIVE
        assert book.row_status == ROW_STATUS_ACTIVE
