"""Django Admin integration for soft delete models.

Provides mixins and utilities for managing soft-deleted objects in Django Admin:
- SoftDeleteAdminMixin: Admin class mixin with soft delete/restore actions
- Custom queryset filtering to show/hide deleted objects
- Admin actions for bulk soft delete and restore operations
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.contrib import admin, messages
from django.db.models import QuerySet
from django.http import HttpRequest

from .constants import ROW_STATUS_ACTIVE, ROW_STATUS_DELETE

if TYPE_CHECKING:
    from django.contrib.admin import ModelAdmin


class SoftDeleteAdminMixin:
    """Admin mixin that adds soft delete/restore functionality to ModelAdmin.

    Features:
        - Custom queryset that includes deleted objects with visual indicators
        - Admin actions for soft deleting and restoring objects
        - Read-only display of row_status field
        - Optional filtering by deletion status

    Usage:
        class MyModelAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
            list_display = ['name', 'row_status', ...]
            list_filter = ['row_status', ...]
    """

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        """Return queryset including soft-deleted objects for admin visibility.

        Override default queryset to use all_objects manager, which includes
        deleted records. This allows admins to see and restore deleted objects.

        Args:
            request: HTTP request object.

        Returns:
            QuerySet including both active and deleted objects.
        """
        qs = self.model.all_objects.get_queryset()  # type: ignore[attr-defined]
        # Respect ordering if set
        ordering = self.get_ordering(request)  # type: ignore[attr-defined]
        if ordering:
            qs = qs.order_by(*ordering)
        return qs

    def get_list_display(self, request: HttpRequest) -> tuple[str, ...]:
        """Add row_status to list_display if not already present.

        Args:
            request: HTTP request object.

        Returns:
            Tuple of field names to display in the admin list view.
        """
        list_display = super().get_list_display(request)  # type: ignore[misc]
        if "row_status" not in list_display:
            # Add row_status at the end
            return tuple(list_display) + ("row_status",)
        return tuple(list_display)

    def get_readonly_fields(
        self, request: HttpRequest, obj: Any = None
    ) -> tuple[str, ...]:
        """Make row_status, create_date, update_date read-only.

        These fields are managed automatically by the soft delete system.

        Args:
            request: HTTP request object.
            obj: Object being edited (None for add form).

        Returns:
            Tuple of read-only field names.
        """
        readonly_fields = super().get_readonly_fields(request, obj)  # type: ignore[misc]
        auto_fields = ("row_status", "create_date", "update_date")
        # Add fields that aren't already readonly
        return tuple(readonly_fields) + tuple(
            field for field in auto_fields if field not in readonly_fields
        )

    @admin.action(description="Soft delete selected %(verbose_name_plural)s")
    def soft_delete_selected(
        self,
        request: HttpRequest,
        queryset: QuerySet,
    ) -> None:
        """Admin action to soft delete selected objects.

        Performs cascade soft delete on all selected objects and displays
        a success message with the count of deleted objects.

        Args:
            request: HTTP request object.
            queryset: QuerySet of selected objects.
        """
        total_deleted = 0
        deleted_models: dict[str, int] = {}

        for obj in queryset:
            # Skip already deleted objects
            if hasattr(obj, "row_status") and obj.row_status == ROW_STATUS_DELETE:
                continue

            count, models_dict = obj.delete()
            total_deleted += count

            # Merge per-model counts
            for model_label, model_count in models_dict.items():
                deleted_models[model_label] = (
                    deleted_models.get(model_label, 0) + model_count
                )

        if total_deleted > 0:
            # Format success message
            model_breakdown = ", ".join(
                f"{count} {label}" for label, count in deleted_models.items()
            )
            self.message_user(  # type: ignore[attr-defined]
                request,
                f"Successfully soft deleted {total_deleted} object(s): {model_breakdown}",
                messages.SUCCESS,
            )
        else:
            self.message_user(  # type: ignore[attr-defined]
                request,
                "No objects were soft deleted (already deleted or empty selection)",
                messages.WARNING,
            )

    @admin.action(description="Restore selected %(verbose_name_plural)s")
    def restore_selected(
        self,
        request: HttpRequest,
        queryset: QuerySet,
    ) -> None:
        """Admin action to restore soft-deleted objects.

        Performs cascade restore on all selected deleted objects and displays
        a success message with the count of restored objects.

        Args:
            request: HTTP request object.
            queryset: QuerySet of selected objects.
        """
        total_restored = 0
        restored_models: dict[str, int] = {}

        for obj in queryset:
            # Skip already active objects
            if hasattr(obj, "row_status") and obj.row_status == ROW_STATUS_ACTIVE:
                continue

            count, models_dict = obj.restore()
            total_restored += count

            # Merge per-model counts
            for model_label, model_count in models_dict.items():
                restored_models[model_label] = (
                    restored_models.get(model_label, 0) + model_count
                )

        if total_restored > 0:
            # Format success message
            model_breakdown = ", ".join(
                f"{count} {label}" for label, count in restored_models.items()
            )
            self.message_user(  # type: ignore[attr-defined]
                request,
                f"Successfully restored {total_restored} object(s): {model_breakdown}",
                messages.SUCCESS,
            )
        else:
            self.message_user(  # type: ignore[attr-defined]
                request,
                "No objects were restored (already active or empty selection)",
                messages.WARNING,
            )

    def get_actions(self, request: HttpRequest) -> dict[str, tuple]:
        """Register soft delete and restore actions.

        Removes the default delete action and adds soft delete/restore actions.

        Args:
            request: HTTP request object.

        Returns:
            Dictionary of action name -> (function, name, description) tuples.
        """
        actions = super().get_actions(request)  # type: ignore[misc]

        # Remove default delete action (use soft_delete instead)
        if "delete_selected" in actions:
            del actions["delete_selected"]

        # Add soft delete and restore actions
        actions["soft_delete_selected"] = (
            self.soft_delete_selected,
            "soft_delete_selected",
            self.soft_delete_selected.short_description,  # type: ignore[attr-defined]
        )
        actions["restore_selected"] = (
            self.restore_selected,
            "restore_selected",
            self.restore_selected.short_description,  # type: ignore[attr-defined]
        )

        return actions


class SoftDeleteAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    """Pre-configured ModelAdmin with soft delete support.

    Convenience class that combines SoftDeleteAdminMixin with ModelAdmin.
    Use this if you don't need custom admin configuration beyond soft delete.

    Usage:
        admin.site.register(MyModel, SoftDeleteAdmin)
    """

    pass
