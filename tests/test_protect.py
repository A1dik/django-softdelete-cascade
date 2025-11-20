"""Tests for PROTECT constraint handling."""

import pytest
from django.db.models.deletion import ProtectedError

from softdelete import ROW_STATUS_ACTIVE, ROW_STATUS_DELETE

from .factories import ProtectedBookFactory, PublisherFactory
from .models import ProtectedBook, Publisher


@pytest.mark.django_db
class TestProtectConstraint:
    """Ensure PROTECT prevents deleting referenced parents."""

    def test_protect_blocks_deletion(self):
        """Deleting a protected parent raises ProtectedError."""
        # Create publisher with a book that uses PROTECT
        publisher = PublisherFactory()
        book = ProtectedBookFactory(publisher=publisher)

        # Deleting the publisher should fail
        with pytest.raises(ProtectedError) as exc_info:
            publisher.delete()

        # Message should reference PROTECT constraint
        error_message = str(exc_info.value)
        assert 'PROTECT' in error_message

        # Both rows remain active
        publisher.refresh_from_db()
        book.refresh_from_db()
        assert publisher.row_status == ROW_STATUS_ACTIVE
        assert book.row_status == ROW_STATUS_ACTIVE

    def test_protect_with_multiple_books(self):
        """PROTECT blocks deletion when multiple related rows exist."""
        # Create publisher with several protected books
        publisher = PublisherFactory()
        book1 = ProtectedBookFactory(publisher=publisher)
        book2 = ProtectedBookFactory(publisher=publisher)
        book3 = ProtectedBookFactory(publisher=publisher)

        # Deleting the publisher should still fail
        with pytest.raises(ProtectedError):
            publisher.delete()

        # All rows stay active
        for obj in [publisher, book1, book2, book3]:
            obj.refresh_from_db()
            assert obj.row_status == ROW_STATUS_ACTIVE

    def test_protect_allows_deletion_after_removing_references(self):
        """Parent can delete after removing protected references."""
        # Create publisher and book
        publisher = PublisherFactory()
        book = ProtectedBookFactory(publisher=publisher)

        # Initial delete should fail
        with pytest.raises(ProtectedError):
            publisher.delete()

        # Remove dependent
        book.delete()

        # Delete now succeeds
        deleted_count, deleted_models = publisher.delete()

        assert deleted_count == 1
        assert 'tests.Publisher' in deleted_models

        # Publisher is marked deleted
        publisher.refresh_from_db()
        assert publisher.row_status == ROW_STATUS_DELETE

    def test_protect_with_already_deleted_reference(self):
        """Deletion works when related objects are already soft-deleted."""
        # Create publisher and book
        publisher = PublisherFactory()
        book = ProtectedBookFactory(publisher=publisher)

        # Delete the book first
        book.delete()

        # Publisher delete should now pass
        deleted_count, deleted_models = publisher.delete()

        assert deleted_count == 1
        publisher.refresh_from_db()
        assert publisher.row_status == ROW_STATUS_DELETE

    def test_protect_error_message_format(self):
        """Error message should include model label and PROTECT keyword."""
        publisher = PublisherFactory()
        book1 = ProtectedBookFactory(publisher=publisher)
        book2 = ProtectedBookFactory(publisher=publisher)

        with pytest.raises(ProtectedError) as exc_info:
            publisher.delete()

        error_message = str(exc_info.value)

        # Model label and guard type should appear
        assert 'tests.Publisher' in error_message
        assert 'PROTECT' in error_message

    def test_protect_with_mixed_active_and_deleted(self):
        """Mixed active/deleted children still block via PROTECT."""
        publisher = PublisherFactory()
        active_book = ProtectedBookFactory(publisher=publisher)
        deleted_book = ProtectedBookFactory(publisher=publisher)

        # Soft-delete one child
        deleted_book.delete()

        # Active child still blocks deletion
        with pytest.raises(ProtectedError):
            publisher.delete()

        # Remove final child
        active_book.delete()

        # Now publisher can be deleted
        deleted_count, _ = publisher.delete()
        assert deleted_count == 1

    def test_protect_does_not_affect_cascade(self):
        """Unrelated cascade paths should still work."""
        # Publisher without dependents can delete fine
        publisher = PublisherFactory()

        # Delete succeeds and returns count/dict
        deleted_count, deleted_models = publisher.delete()

        assert deleted_count == 1
        assert 'tests.Publisher' in deleted_models

        publisher.refresh_from_db()
        assert publisher.row_status == ROW_STATUS_DELETE

    def test_protect_blocking_objects_in_exception(self):
        """Exception exposes blocking objects via protected_objects."""
        publisher = PublisherFactory()
        book = ProtectedBookFactory(publisher=publisher)

        with pytest.raises(ProtectedError) as exc_info:
            publisher.delete()

        # protected_objects should contain related rows
        exception = exc_info.value
        assert hasattr(exception, 'protected_objects')
        assert len(exception.protected_objects) > 0
