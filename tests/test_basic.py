"""Basic soft-delete cases."""

import pytest

from softdelete import ROW_STATUS_ACTIVE, ROW_STATUS_DELETE

from .factories import AuthorFactory, BookFactory
from .models import Author, Book


@pytest.mark.django_db
class TestBasicSoftDelete:
    """Validate single-object soft-delete behavior."""

    def test_single_object_soft_delete(self):
        """Soft delete marks one object as deleted without removing it."""
        # Create an author
        author = AuthorFactory()
        author_pk = author.pk

        # Author starts as active
        assert author.row_status == ROW_STATUS_ACTIVE

        # Delete the author
        deleted_count, deleted_models = author.delete()

        # One row is reported as deleted
        assert deleted_count == 1
        assert "tests.Author" in deleted_models
        assert deleted_models["tests.Author"] == 1

        # Status is updated to deleted
        author.refresh_from_db()
        assert author.row_status == ROW_STATUS_DELETE

        # Row still exists in the database (use all_objects to see deleted objects)
        assert Author.all_objects.filter(pk=author_pk).exists()
        # But not visible via default manager
        assert not Author.objects.filter(pk=author_pk).exists()

    def test_objects_manager_filters_deleted(self):
        """objects manager returns only active instances."""
        # Create several authors
        author1 = AuthorFactory()
        author2 = AuthorFactory()
        author3 = AuthorFactory()

        # Delete one of them
        author2.delete()

        # objects manager should exclude the deleted author
        active_authors = Author.objects.all()
        assert active_authors.count() == 2
        assert author1 in active_authors
        assert author2 not in active_authors
        assert author3 in active_authors

    def test_soft_delete_returns_correct_format(self):
        """delete returns a (count, model_dict) tuple."""
        author = AuthorFactory()
        result = author.delete()

        # The outer type is a 2-tuple
        assert isinstance(result, tuple)
        assert len(result) == 2

        # Containing an int and a dict
        deleted_count, deleted_models = result
        assert isinstance(deleted_count, int)
        assert isinstance(deleted_models, dict)

    def test_soft_delete_updates_update_date(self):
        """Soft delete updates the update_date timestamp."""
        author = AuthorFactory()
        original_update_date = author.update_date

        # Delete the author
        author.delete()

        # Reload from the database
        author.refresh_from_db()

        # update_date should have advanced
        assert author.update_date > original_update_date

    def test_multiple_objects_soft_delete(self):
        """Multiple objects can be soft-deleted independently."""
        # Create several authors
        author1 = AuthorFactory()
        author2 = AuthorFactory()
        author3 = AuthorFactory()

        # Delete each author
        author1.delete()
        author2.delete()
        author3.delete()

        # All should now be marked as deleted
        assert Author.all_objects.filter(row_status=ROW_STATUS_DELETE).count() == 3
        assert Author.objects.count() == 0

    def test_already_deleted_object(self):
        """Deleting an already deleted object should be idempotent."""
        author = AuthorFactory()

        # First deletion marks the row
        deleted_count1, _ = author.delete()
        assert deleted_count1 == 1

        # Second deletion should be a no-op
        author.refresh_from_db()
        deleted_count2, _ = author.delete()

        # Nothing new is marked deleted because row_status is already DELETE
        assert deleted_count2 == 0

    def test_soft_delete_with_no_related_objects(self):
        """Soft delete without relations returns only the current object."""
        # Create a standalone author
        author = AuthorFactory()

        deleted_count, deleted_models = author.delete()

        # Only the author should be reported
        assert deleted_count == 1
        assert len(deleted_models) == 1
        assert "tests.Author" in deleted_models
