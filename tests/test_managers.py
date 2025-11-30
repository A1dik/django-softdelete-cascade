"""Tests for SoftDeleteManager and SoftDeleteQuerySet."""

import pytest
from django.db.models.deletion import ProtectedError

from softdelete import ROW_STATUS_ACTIVE, ROW_STATUS_DELETE
from tests.models import Author, Book, Chapter, Page, ProtectedBook, Publisher


@pytest.mark.django_db
class TestSoftDeleteManager:
    """Test the SoftDeleteManager default filtering behavior."""

    def test_objects_returns_only_active_by_default(self):
        """Test that Model.objects.all() returns only active objects."""
        # Create an author and soft-delete it.
        author = Author.objects.create(name="Active Author")
        deleted_author = Author.objects.create(name="Deleted Author")
        deleted_author.delete()

        # Default manager should only return active objects.
        active_authors = Author.objects.all()
        assert active_authors.count() == 1
        assert active_authors.first() == author

    def test_objects_filter_operates_on_active_only(self):
        """Test that Model.objects.filter() operates on active objects only."""
        Author.objects.create(name="John Doe")
        deleted_author = Author.objects.create(name="Jane Doe")
        deleted_author.delete()

        # Filter should only search within active objects.
        results = Author.objects.filter(name__contains="Doe")
        assert results.count() == 1
        assert results.first().name == "John Doe"

    def test_all_with_deleted_returns_all_objects(self):
        """Test that all_with_deleted() includes both active and deleted."""
        Author.objects.create(name="Active")
        deleted = Author.objects.create(name="Deleted")
        deleted.delete()

        all_authors = Author.objects.all_with_deleted()
        assert all_authors.count() == 2

    def test_deleted_only_returns_soft_deleted_objects(self):
        """Test that deleted_only() returns only soft-deleted objects."""
        Author.objects.create(name="Active")
        deleted = Author.objects.create(name="Deleted")
        deleted.delete()

        deleted_authors = Author.objects.deleted_only()
        assert deleted_authors.count() == 1
        assert deleted_authors.first() == deleted

    def test_all_objects_manager_includes_deleted(self):
        """Test that all_objects manager returns all objects."""
        Author.objects.create(name="Active")
        deleted = Author.objects.create(name="Deleted")
        deleted.delete()

        all_authors = Author.all_objects.all()
        assert all_authors.count() == 2


@pytest.mark.django_db
class TestSoftDeleteQuerySet:
    """Test the SoftDeleteQuerySet custom methods."""

    def test_alive_filters_active_objects(self):
        """Test that .alive() returns only active objects."""
        Author.objects.create(name="Active")
        deleted = Author.objects.create(name="Deleted")
        deleted.delete()

        alive_authors = Author.all_objects.alive()
        assert alive_authors.count() == 1
        assert alive_authors.first().name == "Active"

    def test_deleted_filters_soft_deleted_objects(self):
        """Test that .deleted() returns only soft-deleted objects."""
        Author.objects.create(name="Active")
        deleted = Author.objects.create(name="Deleted")
        deleted.delete()

        deleted_authors = Author.all_objects.deleted()
        assert deleted_authors.count() == 1
        assert deleted_authors.first().name == "Deleted"

    def test_soft_delete_on_queryset(self):
        """Test that .soft_delete() soft-deletes all objects in queryset."""
        author1 = Author.objects.create(name="Author 1")
        author2 = Author.objects.create(name="Author 2")
        Author.objects.create(name="Author 3")

        # Soft-delete two authors using queryset.
        qs = Author.objects.filter(name__in=["Author 1", "Author 2"])
        count, models_dict = qs.soft_delete()

        assert count == 2
        assert "tests.Author" in models_dict

        # Verify they are marked as deleted.
        author1.refresh_from_db()
        author2.refresh_from_db()
        assert author1.row_status == ROW_STATUS_DELETE
        assert author2.row_status == ROW_STATUS_DELETE

        # Verify only one active author remains.
        assert Author.objects.count() == 1

    def test_soft_delete_cascade_via_queryset(self):
        """Test that .soft_delete() cascades to related objects."""
        author = Author.objects.create(name="Author")
        Book.objects.create(title="Book 1", author=author)
        Book.objects.create(title="Book 2", author=author)

        # Soft-delete all authors.
        count, models_dict = Author.objects.all().soft_delete()

        # Should delete 1 author + 2 books = 3 objects.
        assert count == 3
        assert "tests.Author" in models_dict
        assert "tests.Book" in models_dict

        # Verify all are deleted.
        assert Author.objects.count() == 0
        assert Book.objects.count() == 0


@pytest.mark.django_db
class TestManagerWithCascadeRelations:
    """Test manager behavior with cascade soft-delete."""

    def test_deleting_parent_hides_children_from_default_manager(self):
        """Test that deleting parent also hides children from default manager."""
        author = Author.objects.create(name="Author")
        book = Book.objects.create(title="Book", author=author)
        chapter = Chapter.objects.create(title="Chapter", book=book)

        # Delete author (cascades to book and chapter).
        author.delete()

        # Default managers should return empty querysets.
        assert Author.objects.count() == 0
        assert Book.objects.count() == 0
        assert Chapter.objects.count() == 0

        # all_objects manager should show all.
        assert Author.all_objects.count() == 1
        assert Book.all_objects.count() == 1
        assert Chapter.all_objects.count() == 1

    def test_deep_cascade_with_managers(self):
        """Test 4-level cascade: Author -> Book -> Chapter -> Page."""
        author = Author.objects.create(name="Author")
        book = Book.objects.create(title="Book", author=author)
        chapter = Chapter.objects.create(title="Chapter", book=book)
        Page.objects.create(number=1, chapter=chapter)

        # Delete author.
        author.delete()

        # All objects should be hidden from default manager.
        assert Author.objects.count() == 0
        assert Book.objects.count() == 0
        assert Chapter.objects.count() == 0
        assert Page.objects.count() == 0

        # But visible via all_objects.
        assert Author.all_objects.count() == 1
        assert Book.all_objects.count() == 1
        assert Chapter.all_objects.count() == 1
        assert Page.all_objects.count() == 1

        # Verify all have correct row_status.
        assert Author.all_objects.first().row_status == ROW_STATUS_DELETE
        assert Book.all_objects.first().row_status == ROW_STATUS_DELETE
        assert Chapter.all_objects.first().row_status == ROW_STATUS_DELETE
        assert Page.all_objects.first().row_status == ROW_STATUS_DELETE


@pytest.mark.django_db
class TestManagerWithProtectRelations:
    """Test manager behavior with PROTECT relations."""

    def test_protect_blocks_deletion_with_managers(self):
        """Test that PROTECT constraint prevents deletion."""
        publisher = Publisher.objects.create(name="Publisher")
        ProtectedBook.objects.create(title="Book", publisher=publisher)

        # Attempting to delete publisher should raise ProtectedError.
        with pytest.raises(ProtectedError):
            publisher.delete()

        # Both should still be active.
        assert Publisher.objects.count() == 1
        assert ProtectedBook.objects.count() == 1

    def test_protect_allows_deletion_after_removing_dependents(self):
        """Test that deletion succeeds after removing protected dependents."""
        publisher = Publisher.objects.create(name="Publisher")
        book = ProtectedBook.objects.create(title="Book", publisher=publisher)

        # Delete the protected book first.
        book.delete()

        # Now publisher can be deleted.
        publisher.delete()

        assert Publisher.objects.count() == 0
        assert ProtectedBook.objects.count() == 0


@pytest.mark.django_db
class TestManagerChaining:
    """Test chaining queryset methods."""

    def test_alive_then_filter(self):
        """Test chaining .alive() with .filter()."""
        Author.objects.create(name="John Active")
        deleted = Author.objects.create(name="John Deleted")
        deleted.delete()
        Author.objects.create(name="Jane Active")

        # Chain alive() then filter().
        results = Author.all_objects.alive().filter(name__startswith="John")
        assert results.count() == 1
        assert results.first().name == "John Active"

    def test_filter_then_alive(self):
        """Test chaining .filter() then .alive()."""
        Author.objects.create(name="John Active")
        deleted = Author.objects.create(name="John Deleted")
        deleted.delete()
        Author.objects.create(name="Jane Active")

        # Chain filter() then alive().
        results = Author.all_objects.filter(name__startswith="John").alive()
        assert results.count() == 1
        assert results.first().name == "John Active"

    def test_deleted_then_filter(self):
        """Test chaining .deleted() with .filter()."""
        active = Author.objects.create(name="John Active")
        deleted1 = Author.objects.create(name="John Deleted")
        deleted2 = Author.objects.create(name="Jane Deleted")
        deleted1.delete()
        deleted2.delete()

        # Chain deleted() then filter().
        results = Author.all_objects.deleted().filter(name__startswith="John")
        assert results.count() == 1
        assert results.first().name == "John Deleted"


@pytest.mark.django_db
class TestManagerEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_queryset_soft_delete(self):
        """Test .soft_delete() on empty queryset."""
        count, models_dict = Author.objects.filter(name="Nonexistent").soft_delete()
        assert count == 0
        assert models_dict == {}

    def test_already_deleted_objects_via_manager(self):
        """Test that already-deleted objects are idempotent."""
        author = Author.objects.create(name="Author")
        author.delete()

        # Refresh to get the updated row_status.
        author.refresh_from_db()

        # Delete again (should be idempotent).
        count, models_dict = author.delete()
        assert count == 0
        assert models_dict == {}

        # Still only one deleted author.
        assert Author.all_objects.deleted().count() == 1

    def test_all_objects_respects_other_filters(self):
        """Test that all_objects can be filtered like a normal queryset."""
        Author.objects.create(name="John")
        deleted = Author.objects.create(name="Jane")
        deleted.delete()

        # Filter all_objects by name.
        results = Author.all_objects.filter(name="Jane")
        assert results.count() == 1
        assert results.first().row_status == ROW_STATUS_DELETE
