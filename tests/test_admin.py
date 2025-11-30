"""Tests for Django Admin integration with soft delete models."""

from __future__ import annotations

import pytest
from django.contrib import admin
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory

from softdelete import (
    ROW_STATUS_ACTIVE,
    ROW_STATUS_DELETE,
    SoftDeleteAdmin,
    SoftDeleteAdminMixin,
)

from .models import Author, Book, Chapter


# Custom Admin classes for testing
class AuthorAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    """Test admin for Author model."""

    list_display = ["name"]
    list_filter = ["row_status"]


class BookAdmin(SoftDeleteAdmin):
    """Test admin using SoftDeleteAdmin base class."""

    list_display = ["title", "author"]


@pytest.fixture
def admin_site():
    """Create a test admin site."""
    return AdminSite()


@pytest.fixture
def request_factory():
    """Create a request factory."""
    return RequestFactory()


@pytest.fixture
def admin_user(db):
    """Create a superuser for testing."""
    return User.objects.create_superuser(
        username="admin",
        email="admin@example.com",
        password="password123",
    )


@pytest.fixture
def mock_request(request_factory, admin_user):
    """Create a mock admin request."""
    request = request_factory.get("/admin/tests/author/")
    request.user = admin_user
    return request


@pytest.mark.django_db
class TestSoftDeleteAdminMixin:
    """Tests for SoftDeleteAdminMixin functionality."""

    def test_get_queryset_includes_deleted_objects(
        self, admin_site, mock_request
    ) -> None:
        """Admin queryset should include soft-deleted objects."""
        author_admin = AuthorAdmin(Author, admin_site)

        # Create active and deleted authors
        active_author = Author.objects.create(name="Active Author")
        deleted_author = Author.objects.create(name="Deleted Author")
        deleted_author.delete()

        # Get admin queryset
        queryset = author_admin.get_queryset(mock_request)

        # Should include both active and deleted
        assert queryset.count() == 2
        assert active_author in queryset
        assert Author.all_objects.get(pk=deleted_author.pk) in queryset

    def test_get_list_display_includes_row_status(
        self, admin_site, mock_request
    ) -> None:
        """row_status should be automatically added to list_display."""
        author_admin = AuthorAdmin(Author, admin_site)

        list_display = author_admin.get_list_display(mock_request)

        assert "row_status" in list_display
        assert "name" in list_display

    def test_row_status_already_in_list_display(self, admin_site, mock_request) -> None:
        """Don't duplicate row_status if already in list_display."""

        class CustomAuthorAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
            list_display = ["name", "row_status"]

        author_admin = CustomAuthorAdmin(Author, admin_site)
        list_display = author_admin.get_list_display(mock_request)

        # Count occurrences of row_status
        row_status_count = list_display.count("row_status")
        assert row_status_count == 1

    def test_readonly_fields_includes_auto_fields(
        self, admin_site, mock_request
    ) -> None:
        """Auto-managed fields should be read-only."""
        author_admin = AuthorAdmin(Author, admin_site)

        readonly_fields = author_admin.get_readonly_fields(mock_request)

        assert "row_status" in readonly_fields
        assert "create_date" in readonly_fields
        assert "update_date" in readonly_fields

    def test_soft_delete_selected_action_exists(self, admin_site) -> None:
        """Soft delete action should be registered."""
        author_admin = AuthorAdmin(Author, admin_site)

        # Check action exists
        assert hasattr(author_admin, "soft_delete_selected")
        assert author_admin.soft_delete_selected.short_description  # type: ignore[attr-defined]

    def test_restore_selected_action_exists(self, admin_site) -> None:
        """Restore action should be registered."""
        author_admin = AuthorAdmin(Author, admin_site)

        # Check action exists
        assert hasattr(author_admin, "restore_selected")
        assert author_admin.restore_selected.short_description  # type: ignore[attr-defined]


def setup_admin_request(request_factory, admin_user, url="/admin/tests/author/"):
    """Helper to create a properly configured admin request with messages."""
    request = request_factory.post(url)
    request.user = admin_user
    setattr(request, "session", "session")
    messages = FallbackStorage(request)
    setattr(request, "_messages", messages)
    return request


@pytest.mark.django_db
class TestSoftDeleteAdminActions:
    """Tests for admin actions (soft delete and restore)."""

    def test_soft_delete_selected_deletes_objects(
        self,
        admin_site,
        request_factory,
        admin_user,
    ) -> None:
        """Soft delete action should mark objects as deleted."""
        author_admin = AuthorAdmin(Author, admin_site)

        # Create authors
        author1 = Author.objects.create(name="Author 1")
        author2 = Author.objects.create(name="Author 2")

        # Create mock request
        request = setup_admin_request(request_factory, admin_user)

        # Execute action
        queryset = Author.objects.filter(pk__in=[author1.pk, author2.pk])
        author_admin.soft_delete_selected(request, queryset)

        # Verify deletion
        author1.refresh_from_db()
        author2.refresh_from_db()
        assert author1.row_status == ROW_STATUS_DELETE
        assert author2.row_status == ROW_STATUS_DELETE
        assert Author.objects.count() == 0  # Filtered to active only
        assert Author.all_objects.count() == 2  # Both still exist

    def test_soft_delete_selected_with_cascade(
        self,
        admin_site,
        request_factory,
        admin_user,
    ) -> None:
        """Soft delete action should cascade to related objects."""
        author_admin = AuthorAdmin(Author, admin_site)

        # Create hierarchy
        author = Author.objects.create(name="Author")
        book = Book.objects.create(title="Book", author=author)
        chapter = Chapter.objects.create(title="Chapter", book=book)

        # Create mock request
        request = setup_admin_request(request_factory, admin_user)

        # Execute action
        queryset = Author.objects.filter(pk=author.pk)
        author_admin.soft_delete_selected(request, queryset)

        # Verify cascade deletion
        author.refresh_from_db()
        book.refresh_from_db()
        chapter.refresh_from_db()
        assert author.row_status == ROW_STATUS_DELETE
        assert book.row_status == ROW_STATUS_DELETE
        assert chapter.row_status == ROW_STATUS_DELETE

    def test_soft_delete_already_deleted_is_skipped(
        self,
        admin_site,
        request_factory,
        admin_user,
    ) -> None:
        """Soft deleting already deleted objects should be skipped."""
        author_admin = AuthorAdmin(Author, admin_site)

        # Create and delete author
        author = Author.objects.create(name="Author")
        author.delete()

        # Create mock request
        request = setup_admin_request(request_factory, admin_user)

        # Execute action on already deleted object
        queryset = Author.all_objects.filter(pk=author.pk)
        author_admin.soft_delete_selected(request, queryset)

        # Should not error, but also no new deletions

    def test_restore_selected_restores_objects(
        self,
        admin_site,
        request_factory,
        admin_user,
    ) -> None:
        """Restore action should reactivate deleted objects."""
        author_admin = AuthorAdmin(Author, admin_site)

        # Create and delete authors
        author1 = Author.objects.create(name="Author 1")
        author2 = Author.objects.create(name="Author 2")
        author1.delete()
        author2.delete()

        # Create mock request
        request = setup_admin_request(request_factory, admin_user)

        # Execute action
        queryset = Author.all_objects.filter(pk__in=[author1.pk, author2.pk])
        author_admin.restore_selected(request, queryset)

        # Verify restoration
        author1.refresh_from_db()
        author2.refresh_from_db()
        assert author1.row_status == ROW_STATUS_ACTIVE
        assert author2.row_status == ROW_STATUS_ACTIVE
        assert Author.objects.count() == 2

    def test_restore_selected_with_cascade(
        self,
        admin_site,
        request_factory,
        admin_user,
    ) -> None:
        """Restore action should cascade to related objects."""
        author_admin = AuthorAdmin(Author, admin_site)

        # Create hierarchy and delete all
        author = Author.objects.create(name="Author")
        book = Book.objects.create(title="Book", author=author)
        chapter = Chapter.objects.create(title="Chapter", book=book)
        author.delete()

        # Create mock request
        request = setup_admin_request(request_factory, admin_user)

        # Execute action
        queryset = Author.all_objects.filter(pk=author.pk)
        author_admin.restore_selected(request, queryset)

        # Verify cascade restoration
        author.refresh_from_db()
        book.refresh_from_db()
        chapter.refresh_from_db()
        assert author.row_status == ROW_STATUS_ACTIVE
        assert book.row_status == ROW_STATUS_ACTIVE
        assert chapter.row_status == ROW_STATUS_ACTIVE

    def test_restore_already_active_is_skipped(
        self,
        admin_site,
        request_factory,
        admin_user,
    ) -> None:
        """Restoring already active objects should be skipped."""
        author_admin = AuthorAdmin(Author, admin_site)

        # Create active author
        author = Author.objects.create(name="Author")

        # Create mock request
        request = setup_admin_request(request_factory, admin_user)

        # Execute action
        queryset = Author.objects.filter(pk=author.pk)
        author_admin.restore_selected(request, queryset)

        # Should not error, author remains active
        author.refresh_from_db()
        assert author.row_status == ROW_STATUS_ACTIVE


@pytest.mark.django_db
class TestSoftDeleteAdmin:
    """Tests for SoftDeleteAdmin convenience class."""

    def test_soft_delete_admin_inherits_mixin(self, admin_site) -> None:
        """SoftDeleteAdmin should inherit from SoftDeleteAdminMixin."""
        book_admin = BookAdmin(Book, admin_site)

        # Should have mixin methods
        assert hasattr(book_admin, "soft_delete_selected")
        assert hasattr(book_admin, "restore_selected")
        assert hasattr(book_admin, "get_queryset")

    def test_soft_delete_admin_includes_deleted_objects(
        self,
        admin_site,
        mock_request,
    ) -> None:
        """SoftDeleteAdmin queryset should include deleted objects."""
        book_admin = BookAdmin(Book, admin_site)

        # Create active and deleted books
        author = Author.objects.create(name="Author")
        active_book = Book.objects.create(title="Active Book", author=author)
        deleted_book = Book.objects.create(title="Deleted Book", author=author)
        deleted_book.delete()

        # Get admin queryset
        queryset = book_admin.get_queryset(mock_request)

        # Should include both
        assert queryset.count() == 2


@pytest.mark.django_db
class TestAdminActionsIntegration:
    """Integration tests for admin actions."""

    def test_get_actions_removes_default_delete(self, admin_site, mock_request) -> None:
        """Default delete action should be removed."""
        author_admin = AuthorAdmin(Author, admin_site)

        actions = author_admin.get_actions(mock_request)

        # Default delete_selected should be removed
        assert "delete_selected" not in actions

    def test_get_actions_includes_custom_actions(
        self, admin_site, mock_request
    ) -> None:
        """Custom soft delete/restore actions should be included."""
        author_admin = AuthorAdmin(Author, admin_site)

        actions = author_admin.get_actions(mock_request)

        # Custom actions should be present
        assert "soft_delete_selected" in actions
        assert "restore_selected" in actions

    def test_action_descriptions_are_set(self, admin_site, mock_request) -> None:
        """Action descriptions should be properly set."""
        author_admin = AuthorAdmin(Author, admin_site)

        actions = author_admin.get_actions(mock_request)

        # Check descriptions exist
        _, _, delete_desc = actions["soft_delete_selected"]
        _, _, restore_desc = actions["restore_selected"]

        assert delete_desc is not None
        assert restore_desc is not None
        assert "Soft delete" in str(delete_desc)
        assert "Restore" in str(restore_desc)
