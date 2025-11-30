"""Tests for RESTRICT constraint handling."""

import pytest
from django.db.models.deletion import RestrictedError

from softdelete import ROW_STATUS_ACTIVE, ROW_STATUS_DELETE

from .factories import CategoryFactory, RestrictedBookFactory
from .models import Category, RestrictedBook


@pytest.mark.django_db
class TestRestrictConstraint:
    """Ensure RESTRICT prevents deleting referenced parents."""

    def test_restrict_blocks_deletion(self):
        """Deleting a restricted parent raises RestrictedError."""
        # Create category with a restricted book
        category = CategoryFactory()
        book = RestrictedBookFactory(category=category)

        # Deleting the category should fail
        with pytest.raises(RestrictedError) as exc_info:
            category.delete()

        # Message should reference RESTRICT
        error_message = str(exc_info.value)
        assert "RESTRICT" in error_message

        # Both rows remain active
        category.refresh_from_db()
        book.refresh_from_db()
        assert category.row_status == ROW_STATUS_ACTIVE
        assert book.row_status == ROW_STATUS_ACTIVE

    def test_restrict_with_multiple_books(self):
        """RESTRICT blocks deletion when multiple dependents exist."""
        # Create category with several books
        category = CategoryFactory()
        book1 = RestrictedBookFactory(category=category)
        book2 = RestrictedBookFactory(category=category)
        book3 = RestrictedBookFactory(category=category)

        # Delete should fail while dependents remain
        with pytest.raises(RestrictedError):
            category.delete()

        # All rows stay active
        for obj in [category, book1, book2, book3]:
            obj.refresh_from_db()
            assert obj.row_status == ROW_STATUS_ACTIVE

    def test_restrict_allows_deletion_after_removing_references(self):
        """Parent can delete once restricted references are gone."""
        # Create category and book
        category = CategoryFactory()
        book = RestrictedBookFactory(category=category)

        # Initial delete should fail
        with pytest.raises(RestrictedError):
            category.delete()

        # Remove dependent
        book.delete()

        # Delete now succeeds
        deleted_count, deleted_models = category.delete()

        assert deleted_count == 1
        assert "tests.Category" in deleted_models

        category.refresh_from_db()
        assert category.row_status == ROW_STATUS_DELETE

    def test_restrict_with_already_deleted_reference(self):
        """Deletion succeeds when references are already deleted."""
        # Create category and book
        category = CategoryFactory()
        book = RestrictedBookFactory(category=category)

        # Delete the book first
        book.delete()

        # Category delete should now work
        deleted_count, deleted_models = category.delete()

        assert deleted_count == 1
        category.refresh_from_db()
        assert category.row_status == ROW_STATUS_DELETE

    def test_restrict_error_message_format(self):
        """Error message should include model label and RESTRICT keyword."""
        category = CategoryFactory()
        book1 = RestrictedBookFactory(category=category)
        book2 = RestrictedBookFactory(category=category)

        with pytest.raises(RestrictedError) as exc_info:
            category.delete()

        error_message = str(exc_info.value)

        # Model label and guard type should appear
        assert "tests.Category" in error_message
        assert "RESTRICT" in error_message

    def test_restrict_with_mixed_active_and_deleted(self):
        """Mixed active/deleted children still block via RESTRICT."""
        category = CategoryFactory()
        active_book = RestrictedBookFactory(category=category)
        deleted_book = RestrictedBookFactory(category=category)

        # Soft-delete one child
        deleted_book.delete()

        # Active child still blocks deletion
        with pytest.raises(RestrictedError):
            category.delete()

        # Remove final child
        active_book.delete()

        # Now category can be deleted
        deleted_count, _ = category.delete()
        assert deleted_count == 1

    def test_restrict_does_not_affect_cascade(self):
        """Unrelated cascade paths should still work."""
        # Category without dependents can delete fine
        category = CategoryFactory()

        # Delete succeeds and returns count/dict
        deleted_count, deleted_models = category.delete()

        assert deleted_count == 1
        assert "tests.Category" in deleted_models

        category.refresh_from_db()
        assert category.row_status == ROW_STATUS_DELETE

    def test_restrict_blocking_objects_in_exception(self):
        """Exception exposes blocking objects via restricted_objects."""
        category = CategoryFactory()
        book = RestrictedBookFactory(category=category)

        with pytest.raises(RestrictedError) as exc_info:
            category.delete()

        # restricted_objects should contain related rows
        exception = exc_info.value
        assert hasattr(exception, "restricted_objects")
        assert len(exception.restricted_objects) > 0

    def test_difference_between_protect_and_restrict(self):
        """Ensure RESTRICT is raised instead of ProtectedError."""
        # Set up a restricted relationship
        category = CategoryFactory()
        book = RestrictedBookFactory(category=category)

        # First delete should raise RestrictedError
        with pytest.raises(RestrictedError):
            category.delete()

        # Confirm the raised error type
        try:
            category.delete()
        except Exception as e:
            assert type(e).__name__ == "RestrictedError"

    def test_restrict_with_multiple_references_same_object(self):
        """Multiple references to the same parent still block deletion."""
        category = CategoryFactory()

        # Create several books pointing to the same category
        for _ in range(5):
            RestrictedBookFactory(category=category)

        # Delete should raise because references exist
        with pytest.raises(RestrictedError):
            category.delete()

        # Category remains active
        category.refresh_from_db()
        assert category.row_status == ROW_STATUS_ACTIVE
