"""Core SoftDeleteModel implementation."""

from __future__ import annotations

import logging
from collections import defaultdict
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Iterator

from django.db import models, router, transaction
from django.db.models import CASCADE, PROTECT, RESTRICT
from django.db.models.deletion import ProtectedError, RestrictedError
from django.utils import timezone

from .constants import (
    DELETE_ITERATOR_CHUNK_SIZE,
    ROW_STATUS_ACTIVE,
    ROW_STATUS_CHOICES,
    ROW_STATUS_DELETE,
    SOFTDELETE_LOGGER_NAME,
)
from .result import SoftDeleteRef, SoftDeleteResult
from .utils import deduplicate_objects, format_blocking_info

logger = logging.getLogger(SOFTDELETE_LOGGER_NAME)

if TYPE_CHECKING:
    from collections.abc import Iterable


@contextmanager
def _no_op_context() -> Iterator[None]:
    """No-operation context manager for dry-run mode.

    Provides a context manager that does nothing, used as a replacement
    for transaction.atomic() when dry_run=True.

    Yields:
        None
    """
    yield


class SoftDeleteQuerySet(models.QuerySet):
    """Custom QuerySet with soft-delete filtering and operations.

    Provides convenient methods for working with soft-deleted objects:
        * .alive() - filter only active objects
        * .deleted() - filter only soft-deleted objects
        * .soft_delete() - soft delete all objects in the queryset
        * .restore() - restore soft-deleted objects with cascade support
    """

    def alive(self) -> models.QuerySet:
        """Return only active (non-deleted) objects.

        Returns:
            QuerySet filtered to row_status=ROW_STATUS_ACTIVE.
        """
        return self.filter(row_status=ROW_STATUS_ACTIVE)

    def deleted(self) -> models.QuerySet:
        """Return only soft-deleted objects.

        Returns:
            QuerySet filtered to row_status=ROW_STATUS_DELETE.
        """
        return self.filter(row_status=ROW_STATUS_DELETE)

    def soft_delete(self) -> tuple[int, dict[str, int]]:
        """Soft-delete all objects in the queryset.

        Iterates through the queryset and calls delete() on each object,
        which triggers the cascade soft-delete logic.

        Returns:
            tuple[int, dict[str, int]]: Total deleted count and per-model breakdown.
        """
        total_deleted = 0
        deleted_models: dict[str, int] = {}

        for obj in self.iterator(chunk_size=DELETE_ITERATOR_CHUNK_SIZE):
            count, models_dict = obj.delete()
            total_deleted += count

            # Merge per-model counts.
            for model_label, model_count in models_dict.items():
                deleted_models[model_label] = deleted_models.get(model_label, 0) + model_count

        return total_deleted, deleted_models

    def restore(self, restore_children: bool = True) -> tuple[int, dict[str, int]]:
        """Restore soft-deleted objects in the queryset.

        Iterates through the queryset and calls restore() on each object,
        which triggers the cascade restore logic.

        Args:
            restore_children: When True (default), recursively restore all
                CASCADE-related deleted objects. When False, only restore
                the objects in the queryset.

        Returns:
            tuple[int, dict[str, int]]: Total restored count and per-model breakdown.
        """
        total_restored = 0
        restored_models: dict[str, int] = {}

        for obj in self.iterator(chunk_size=DELETE_ITERATOR_CHUNK_SIZE):
            count, models_dict = obj.restore(restore_children=restore_children)
            total_restored += count

            # Merge per-model counts.
            for model_label, model_count in models_dict.items():
                restored_models[model_label] = restored_models.get(model_label, 0) + model_count

        return total_restored, restored_models


class SoftDeleteManager(models.Manager):
    """Custom Manager that filters out soft-deleted objects by default.

    Default queryset behavior:
        * Model.objects.all() - returns only active objects
        * Model.objects.filter(...) - operates on active objects

    Additional methods:
        * .all_with_deleted() - include both active and deleted objects
        * .deleted_only() - return only deleted objects
    """

    def get_queryset(self) -> models.QuerySet:
        """Return queryset filtered to active objects by default.

        Returns:
            SoftDeleteQuerySet filtered to row_status=ROW_STATUS_ACTIVE.
        """
        return SoftDeleteQuerySet(self.model, using=self._db).alive()

    def all_with_deleted(self) -> models.QuerySet:
        """Return all objects including soft-deleted ones.

        Returns:
            SoftDeleteQuerySet without any row_status filtering.
        """
        return SoftDeleteQuerySet(self.model, using=self._db)

    def deleted_only(self) -> models.QuerySet:
        """Return only soft-deleted objects.

        Returns:
            SoftDeleteQuerySet filtered to row_status=ROW_STATUS_DELETE.
        """
        return SoftDeleteQuerySet(self.model, using=self._db).deleted()


class SoftDeleteModel(models.Model):
    """Abstract base class that implements BFS-driven soft deletes.

    Key capabilities:
        * tracks state via a built-in ``row_status`` column
        * traverses ``on_delete=CASCADE`` relations to mark dependents
        * inspects PROTECT/RESTRICT relations before updating rows
        * handles multi-table inheritance hierarchies
        * performs all updates inside a single atomic transaction
        * coalesces updates into bulk ``UPDATE`` statements per model
        * provides smart managers that filter deleted objects by default

    Managers:
        * objects - default manager, filters to active objects
        * all_objects - returns all objects including deleted ones
    """

    row_status = models.SmallIntegerField(
        choices=ROW_STATUS_CHOICES,
        default=ROW_STATUS_ACTIVE,
        db_index=True,
        help_text='Object lifecycle status (0=Active, 1=Updated, 2=Deleted, 3=Banned)',
    )
    create_date = models.DateTimeField(auto_now_add=True)
    update_date = models.DateTimeField(auto_now=True)

    # Default manager filters out deleted objects.
    objects = SoftDeleteManager()

    # Manager that includes deleted objects.
    all_objects = SoftDeleteQuerySet.as_manager()

    class Meta:
        """Mark the base model as abstract."""

        abstract = True

    def delete(
        self,
        using: str | None = None,
        keep_parents: bool = False,
        dry_run: bool = False,
    ) -> tuple[int, dict[str, int]] | SoftDeleteResult:
        """Soft-delete the instance and all CASCADE-related objects.

        The algorithm walks the relationship graph breadth-first, ensuring every
        processed model owns a ``row_status`` column before adding it to the
        update queue. PROTECT/RESTRICT dependencies are checked ahead of time to
        surface actionable exceptions.

        Args:
            using: Database alias to operate on; defaults to Django's router.
            keep_parents: Skip soft-deleting parent models in multi-table
                inheritance hierarchies when True.
            dry_run: When True, perform a read-only preview without database
                modifications. Returns SoftDeleteResult instead of tuple.

        Returns:
            tuple[int, dict[str, int]]: Total number of updated rows and a map
            of model labels to the number of affected rows (when dry_run=False).
            SoftDeleteResult: Detailed preview of the operation (when dry_run=True).

        Raises:
            ProtectedError: A PROTECT relation blocked deletion (when dry_run=False).
            RestrictedError: A RESTRICT relation blocked deletion (when dry_run=False).
        """
        if using is None:
            using = router.db_for_write(self.__class__, instance=self)

        model_label = f'{self._meta.app_label}.{self._meta.object_name}'
        operation_mode = 'dry-run' if dry_run else 'soft-delete'
        logger.debug(
            'Starting %s for %s (pk=%s)',
            operation_mode,
            model_label,
            self.pk,
        )

        # Short-circuit when the instance was previously soft-deleted.
        if hasattr(self, 'row_status') and self.row_status == ROW_STATUS_DELETE:
            logger.debug(
                'Skipping %s for %s (pk=%s) - already deleted',
                operation_mode,
                model_label,
                self.pk,
            )
            if dry_run:
                return SoftDeleteResult(
                    affected_objects=tuple(),
                    blocked_objects=tuple(),
                    would_succeed=True,
                    total_count=0,
                    model_counts={},
                )
            return 0, {}

        # Collect affected objects and blocking constraints.
        affected_refs: list[SoftDeleteRef] = []
        blocked_refs: list[SoftDeleteRef] = []
        deleted_counter = 0
        deleted_models: dict[str, int] = {}

        # Define transaction context - use atomic only when not in dry_run.
        # In dry_run mode, we still want to read from DB but not lock or modify.
        transaction_context = transaction.atomic(using=using) if not dry_run else _no_op_context()

        with transaction_context:
            # Lock the root object to prevent concurrent modifications (only in real mode).
            if not dry_run:
                type(self).all_objects.using(using).filter(pk=self.pk).select_for_update(nowait=False).first()

            # Track model -> primary key set for every object to soft-delete.
            to_delete: dict[type[models.Model], set[Any]] = defaultdict(set)
            to_delete[type(self)].add(self.pk)

            # Guard against traversing the same instance multiple times.
            processed: set[tuple[type[models.Model], Any]] = set()

            # Seed the BFS queue with the current object.
            current_level: list[models.Model] = [self]

            # Track if operation would be blocked by PROTECT/RESTRICT.
            would_succeed = True

            while current_level:
                next_level: list[models.Model] = []

                # Group objects by model to reduce database hits.
                objects_by_model: dict[type[models.Model], list[models.Model]] = defaultdict(list)
                for obj in current_level:
                    obj_key = (type(obj), obj.pk)
                    if obj_key not in processed:
                        processed.add(obj_key)
                        objects_by_model[type(obj)].append(obj)

                for current_model, objects in objects_by_model.items():
                    # Check PROTECT/RESTRICT constraints.
                    # In dry_run mode, catch exceptions and collect blocking objects.
                    if dry_run:
                        blocking_objects = self._collect_blocking_objects(current_model, objects, using)
                        if blocking_objects:
                            would_succeed = False
                            blocked_refs.extend([SoftDeleteRef.from_instance(obj) for obj in blocking_objects])
                    else:
                        # In real mode, raise exceptions immediately.
                        self._check_protected_relations(current_model, objects, using)

                    # Optionally push parent models from multi-table inheritance.
                    if not keep_parents:
                        self._handle_parent_models(objects, to_delete, next_level, processed)

                    # Locate related objects that rely on CASCADE semantics.
                    related_objects_list = getattr(current_model._meta, 'related_objects', [])
                    for related_object in related_objects_list:
                        if related_object.on_delete != CASCADE:
                            continue

                        related_model: type[models.Model] = related_object.related_model

                        # Only traverse models that participate in row_status updates.
                        if not hasattr(related_model, 'row_status'):
                            continue

                        field_name = related_object.field.name

                        # Gather active related objects in manageable chunks.
                        related_queryset = related_model.objects.using(using).filter(
                            **{f'{field_name}__in': objects},
                            row_status=ROW_STATUS_ACTIVE,
                        )

                        # Add discovered instances to the BFS frontier.
                        for related_instance in related_queryset.iterator(
                            chunk_size=DELETE_ITERATOR_CHUNK_SIZE
                        ):
                            obj_key = (type(related_instance), related_instance.pk)
                            if obj_key not in processed:
                                to_delete[type(related_instance)].add(related_instance.pk)
                                next_level.append(related_instance)

                current_level = next_level

            # In dry_run mode, collect affected object references.
            if dry_run:
                for model, pks in to_delete.items():
                    if not pks:
                        continue

                    # Fetch actual instances to create refs.
                    instances = model.all_objects.using(using).filter(pk__in=pks)
                    for instance in instances.iterator(chunk_size=DELETE_ITERATOR_CHUNK_SIZE):
                        affected_refs.append(SoftDeleteRef.from_instance(instance))

                return SoftDeleteResult(
                    affected_objects=tuple(affected_refs),
                    blocked_objects=tuple(blocked_refs),
                    would_succeed=would_succeed,
                )

            # Apply bulk updates grouped by model once traversal ends (real mode only).
            for model, pks in to_delete.items():
                if not pks:
                    continue

                updated_count = (
                    model.all_objects.using(using)
                    .filter(pk__in=pks)
                    .update(
                        row_status=ROW_STATUS_DELETE,
                        update_date=timezone.now(),
                    )
                )

                deleted_counter += updated_count
                model_label = f'{model._meta.app_label}.{model._meta.object_name}'
                deleted_models[model_label] = updated_count

        logger.info(
            'Completed %s for %s (pk=%s): %d object(s) affected across %d model(s)',
            operation_mode,
            f'{self._meta.app_label}.{self._meta.object_name}',
            self.pk,
            deleted_counter,
            len(deleted_models),
        )

        return deleted_counter, deleted_models

    def _collect_blocking_objects(
        self,
        current_model: type[models.Model],
        objects: list[models.Model],
        using: str,
    ) -> list[models.Model]:
        """Collect objects that would block deletion via PROTECT/RESTRICT constraints.

        Similar to _check_protected_relations, but returns blocking objects
        instead of raising exceptions. Used in dry_run mode.

        Args:
            current_model: Model being processed during the current BFS step.
            objects: Instances scheduled for deletion on the model.
            using: Database alias for queryset execution.

        Returns:
            List of model instances that would block the deletion.
        """
        blocking_objects: list[models.Model] = []

        related_objects_list = getattr(current_model._meta, 'related_objects', [])
        for related_object in related_objects_list:
            # Only check PROTECT and RESTRICT relations.
            if related_object.on_delete not in (PROTECT, RESTRICT):
                continue

            field_name = related_object.field.name
            related_model: type[models.Model] = related_object.related_model

            # Build queryset for blocking objects.
            if hasattr(related_model, 'row_status'):
                blocking_queryset = (
                    related_model.all_objects.using(using)
                    .filter(
                        **{f'{field_name}__in': objects},
                        row_status=ROW_STATUS_ACTIVE,
                    )
                )
            else:
                blocking_queryset = (
                    related_model.all_objects.using(using)
                    .filter(
                        **{f'{field_name}__in': objects},
                    )
                )

            # Collect blocking instances.
            for blocking_obj in blocking_queryset.iterator(chunk_size=DELETE_ITERATOR_CHUNK_SIZE):
                blocking_objects.append(blocking_obj)

        return deduplicate_objects(blocking_objects)

    def _check_protected_relations(
        self,
        current_model: type[models.Model],
        objects: list[models.Model],
        using: str,
    ) -> None:
        """Validate that PROTECT/RESTRICT relations allow the delete.

        Args:
            current_model: Model being processed during the current BFS step.
            objects: Instances scheduled for deletion on the model.
            using: Database alias for queryset execution.

        Raises:
            ProtectedError: A PROTECT relation still has active objects.
            RestrictedError: A RESTRICT relation still has active objects.
        """
        protected_pks: set[int] = set()
        restricted_pks: set[int] = set()
        protected_blocking_objects: list[models.Model] = []
        restricted_blocking_objects: list[models.Model] = []

        related_objects_list = getattr(current_model._meta, 'related_objects', [])
        for related_object in related_objects_list:
            field_name = related_object.field.name
            related_model: type[models.Model] = related_object.related_model

            # Inspect PROTECT relations.
            if related_object.on_delete == PROTECT:
                if hasattr(related_model, 'row_status'):
                    blocking_queryset = (
                        related_model.all_objects.using(using)
                        .filter(
                            **{f'{field_name}__in': objects},
                            row_status=ROW_STATUS_ACTIVE,
                        )
                        .select_related(field_name)
                    )
                else:
                    blocking_queryset = (
                        related_model.all_objects.using(using)
                        .filter(
                            **{f'{field_name}__in': objects},
                        )
                        .select_related(field_name)
                    )

                for blocking_obj in blocking_queryset.iterator(
                    chunk_size=DELETE_ITERATOR_CHUNK_SIZE
                ):
                    parent_obj = getattr(blocking_obj, field_name)
                    if parent_obj and parent_obj.pk:
                        protected_pks.add(parent_obj.pk)
                        protected_blocking_objects.append(blocking_obj)

            # Inspect RESTRICT relations.
            elif related_object.on_delete == RESTRICT:
                if hasattr(related_model, 'row_status'):
                    blocking_queryset = (
                        related_model.all_objects.using(using)
                        .filter(
                            **{f'{field_name}__in': objects},
                            row_status=ROW_STATUS_ACTIVE,
                        )
                        .select_related(field_name)
                    )
                else:
                    blocking_queryset = (
                        related_model.all_objects.using(using)
                        .filter(
                            **{f'{field_name}__in': objects},
                        )
                        .select_related(field_name)
                    )

                for blocking_obj in blocking_queryset.iterator(
                    chunk_size=DELETE_ITERATOR_CHUNK_SIZE
                ):
                    parent_obj = getattr(blocking_obj, field_name)
                    if parent_obj and parent_obj.pk:
                        restricted_pks.add(parent_obj.pk)
                        restricted_blocking_objects.append(blocking_obj)

        if protected_pks:
            unique_blocking_objects = deduplicate_objects(protected_blocking_objects)
            blocking_info = format_blocking_info(unique_blocking_objects)
            message = (
                f'Deletion blocked for {len(protected_pks)} {current_model._meta.label} '
                'object(s) by PROTECT relations.'
            )
            if blocking_info:
                message = f'{message} {blocking_info}'
            raise ProtectedError(message, set(unique_blocking_objects))

        if restricted_pks:
            unique_blocking_objects = deduplicate_objects(restricted_blocking_objects)
            blocking_info = format_blocking_info(unique_blocking_objects)
            message = (
                f'Deletion blocked for {len(restricted_pks)} {current_model._meta.label} '
                'object(s) by RESTRICT relations.'
            )
            if blocking_info:
                message = f'{message} {blocking_info}'
            raise RestrictedError(message, set(unique_blocking_objects))

    def _handle_parent_models(
        self,
        objects: list[models.Model],
        to_delete: dict[type[models.Model], set[Any]],
        next_level: list[models.Model],
        processed: set[tuple[type[models.Model], Any]],
    ) -> None:
        """Queue parent models when using multi-table inheritance.

        Args:
            objects: Child instances currently being processed.
            to_delete: Aggregate map of model -> primary key sets queued for update.
            next_level: BFS queue used for subsequent traversal passes.
            processed: Cache used to avoid revisiting the same instances.
        """
        if not objects:
            return

        model = type(objects[0])
        parent_links = model._meta.parents

        for parent_model, parent_link in parent_links.items():
            # Skip parents that do not implement ``row_status``.
            if not hasattr(parent_model, 'row_status'):
                continue

            for obj in objects:
                parent_instance = getattr(obj, parent_link.name)
                if parent_instance:
                    obj_key = (parent_model, parent_instance.pk)
                    if obj_key not in processed:
                        to_delete[parent_model].add(parent_instance.pk)
                        next_level.append(parent_instance)

    def restore(
        self,
        using: str | None = None,
        restore_children: bool = True,
        dry_run: bool = False,
    ) -> tuple[int, dict[str, int]] | SoftDeleteResult:
        """Restore a soft-deleted instance and optionally its CASCADE-related children.

        The algorithm uses breadth-first traversal to discover all related deleted
        objects. It restores:
        1. The target object itself
        2. Parent models in multi-table inheritance hierarchies
        3. Parent objects via ForeignKey relationships (to maintain referential integrity)
        4. Child objects via CASCADE relationships (if restore_children=True)

        Args:
            using: Database alias to operate on; defaults to Django's router.
            restore_children: When True (default), recursively restore all
                CASCADE-related deleted objects. When False, only restore this instance
                and its parents (both via inheritance and ForeignKey).
            dry_run: When True, perform a read-only preview without database
                modifications. Returns SoftDeleteResult instead of tuple.

        Returns:
            tuple[int, dict[str, int]]: Total number of restored rows and a map
            of model labels to the number of affected rows (when dry_run=False).
            SoftDeleteResult: Detailed preview of the operation (when dry_run=True).
        """
        if using is None:
            using = router.db_for_write(self.__class__, instance=self)

        model_label = f'{self._meta.app_label}.{self._meta.object_name}'
        logger.debug(
            'Starting restore for %s (pk=%s, restore_children=%s)',
            model_label,
            self.pk,
            restore_children,
        )

        # Get fresh instance from DB to check current status.
        fresh_instance = type(self).all_objects.using(using).filter(pk=self.pk).first()
        if fresh_instance and fresh_instance.row_status == ROW_STATUS_ACTIVE:
            logger.debug(
                'Skipping restore for %s (pk=%s) - already active',
                model_label,
                self.pk,
            )
            if dry_run:
                return SoftDeleteResult(
                    affected_objects=tuple(),
                    blocked_objects=tuple(),
                    would_succeed=True,
                    total_count=0,
                    model_counts={},
                )
            return 0, {}

        # Collect affected objects for dry_run mode.
        affected_refs: list[SoftDeleteRef] = []
        restored_counter = 0
        restored_models: dict[str, int] = {}

        # Define transaction context - use atomic only when not in dry_run.
        transaction_context = transaction.atomic(using=using) if not dry_run else _no_op_context()

        with transaction_context:
            # Lock the root object to prevent concurrent modifications (only in real mode).
            if not dry_run:
                type(self).all_objects.using(using).filter(pk=self.pk).select_for_update(nowait=False).first()

            # Track model -> primary key set for every object to restore.
            to_restore: dict[type[models.Model], set[Any]] = defaultdict(set)
            to_restore[type(self)].add(self.pk)

            # Guard against traversing the same instance multiple times.
            processed: set[tuple[type[models.Model], Any]] = set()

            # Track parent models that will be implicitly restored through MTI.
            implicit_mti_restores: dict[type[models.Model], set[Any]] = defaultdict(set)

            # Seed the BFS queue with the current object.
            current_level: list[models.Model] = [self]

            while current_level:
                next_level: list[models.Model] = []

                # Group objects by model to reduce database hits.
                objects_by_model: dict[type[models.Model], list[models.Model]] = defaultdict(list)
                for obj in current_level:
                    obj_key = (type(obj), obj.pk)
                    if obj_key not in processed:
                        processed.add(obj_key)
                        objects_by_model[type(obj)].append(obj)

                for current_model, objects in objects_by_model.items():
                    # Track MTI parents that will be implicitly restored.
                    parent_links = current_model._meta.parents
                    for parent_model, parent_link in parent_links.items():
                        if not hasattr(parent_model, 'row_status') or not parent_link:
                            continue

                        # Collect child PKs.
                        child_pks = [obj.pk for obj in objects]

                        # Get parent PKs from DB.
                        parent_pk_values = (
                            current_model.all_objects.using(using)
                            .filter(pk__in=child_pks)
                            .values_list(parent_link.attname, flat=True)
                        )

                        parent_pks = set(pk for pk in parent_pk_values if pk)
                        if parent_pks:
                            # Mark these parents as implicitly restored.
                            implicit_mti_restores[parent_model].update(parent_pks)

                    # Restore parent objects via ForeignKey relationships.
                    self._restore_parent_objects(objects, to_restore, next_level, processed, using)

                    # Only traverse children if restore_children is True.
                    if not restore_children:
                        continue

                    # Locate related objects that rely on CASCADE semantics.
                    related_objects_list = getattr(current_model._meta, 'related_objects', [])
                    for related_object in related_objects_list:
                        if related_object.on_delete != CASCADE:
                            continue

                        related_model: type[models.Model] = related_object.related_model

                        # Only traverse models that participate in row_status updates.
                        if not hasattr(related_model, 'row_status'):
                            continue

                        field_name = related_object.field.name

                        # Gather deleted related objects in manageable chunks.
                        related_queryset = (
                            related_model.all_objects.using(using)
                            .filter(
                                **{f'{field_name}__in': objects},
                                row_status=ROW_STATUS_DELETE,
                            )
                        )

                        # Add discovered instances to the BFS frontier.
                        for related_instance in related_queryset.iterator(
                            chunk_size=DELETE_ITERATOR_CHUNK_SIZE
                        ):
                            obj_key = (type(related_instance), related_instance.pk)
                            if obj_key not in processed:
                                to_restore[type(related_instance)].add(related_instance.pk)
                                next_level.append(related_instance)

                current_level = next_level

            # In dry_run mode, collect affected object references before updates.
            if dry_run:
                for model, pks in to_restore.items():
                    if not pks:
                        continue

                    # Fetch actual deleted instances to create refs.
                    instances = (
                        model.all_objects.using(using)
                        .filter(pk__in=pks, row_status=ROW_STATUS_DELETE)
                    )
                    for instance in instances.iterator(chunk_size=DELETE_ITERATOR_CHUNK_SIZE):
                        affected_refs.append(SoftDeleteRef.from_instance(instance))

                # Also include MTI parents in affected list for dry_run.
                for parent_model, parent_pks in implicit_mti_restores.items():
                    if not parent_pks:
                        continue

                    # Fetch actual deleted parent instances.
                    parent_instances = (
                        parent_model.all_objects.using(using)
                        .filter(pk__in=parent_pks, row_status=ROW_STATUS_DELETE)
                    )
                    for instance in parent_instances.iterator(chunk_size=DELETE_ITERATOR_CHUNK_SIZE):
                        # Check if not already in affected_refs (avoid duplicates).
                        ref = SoftDeleteRef.from_instance(instance)
                        if ref not in affected_refs:
                            affected_refs.append(ref)

                return SoftDeleteResult(
                    affected_objects=tuple(affected_refs),
                    blocked_objects=tuple(),  # Restore never has blocking objects.
                    would_succeed=True,  # Restore always succeeds.
                )

            # Check MTI parent status BEFORE updates (real mode only).
            mti_parent_deleted_counts: dict[str, int] = {}
            for parent_model, parent_pks in implicit_mti_restores.items():
                if not parent_pks:
                    continue

                # Count how many are currently deleted (will be implicitly restored).
                deleted_count = (
                    parent_model.all_objects.using(using)
                    .filter(pk__in=parent_pks, row_status=ROW_STATUS_DELETE)
                    .count()
                )

                if deleted_count > 0:
                    parent_label = f'{parent_model._meta.app_label}.{parent_model._meta.object_name}'
                    mti_parent_deleted_counts[parent_label] = deleted_count

            # Apply bulk updates grouped by model once traversal ends (real mode only).
            for model, pks in to_restore.items():
                if not pks:
                    continue

                # Count how many are currently deleted (will be restored).
                deleted_pks = set(
                    model.all_objects.using(using)
                    .filter(pk__in=pks, row_status=ROW_STATUS_DELETE)
                    .values_list('pk', flat=True)
                )

                updated_count = (
                    model.all_objects.using(using)
                    .filter(pk__in=deleted_pks)
                    .update(
                        row_status=ROW_STATUS_ACTIVE,
                        update_date=timezone.now(),
                    )
                )

                if updated_count > 0:
                    model_label = f'{model._meta.app_label}.{model._meta.object_name}'
                    restored_counter += updated_count
                    restored_models[model_label] = updated_count

            # Add MTI parent counts (checked before updates).
            for parent_label, deleted_count in mti_parent_deleted_counts.items():
                if parent_label not in restored_models:
                    restored_counter += deleted_count
                    restored_models[parent_label] = deleted_count

        logger.info(
            'Completed restore for %s (pk=%s): %d object(s) restored across %d model(s)',
            f'{self._meta.app_label}.{self._meta.object_name}',
            self.pk,
            restored_counter,
            len(restored_models),
        )

        return restored_counter, restored_models

    def _handle_parent_models_for_restore(
        self,
        objects: list[models.Model],
        to_restore: dict[type[models.Model], set[Any]],
        next_level: list[models.Model],
        processed: set[tuple[type[models.Model], Any]],
        using: str,
    ) -> None:
        """Queue parent models when using multi-table inheritance for restore.

        Similar to _handle_parent_models but for restore operations. We need to
        fetch parent instances from DB since they may be deleted.

        Args:
            objects: Child instances currently being processed.
            to_restore: Aggregate map of model -> primary key sets queued for restore.
            next_level: BFS queue used for subsequent traversal passes.
            processed: Cache used to avoid revisiting the same instances.
            using: Database alias for queryset execution.
        """
        if not objects:
            return

        model = type(objects[0])
        parent_links = model._meta.parents

        for parent_model, parent_link in parent_links.items():
            # Skip parents that do not implement ``row_status``.
            if not hasattr(parent_model, 'row_status'):
                continue

            # Skip if parent_link is None.
            if not parent_link:
                continue

            # Collect child PKs first.
            child_pks = [obj.pk for obj in objects]

            # Query DB to get parent PKs via the parent link field.
            # Use values() to get only the parent FK values we need.
            parent_pk_values = (
                model.all_objects.using(using)
                .filter(pk__in=child_pks)
                .values_list(parent_link.attname, flat=True)
            )

            parent_pks = set(pk for pk in parent_pk_values if pk)

            if not parent_pks:
                continue

            # Fetch deleted parent objects from database.
            deleted_parents_qs = (
                parent_model.all_objects.using(using)
                .filter(pk__in=parent_pks, row_status=ROW_STATUS_DELETE)
            )

            for parent_instance in deleted_parents_qs.iterator(chunk_size=DELETE_ITERATOR_CHUNK_SIZE):
                obj_key = (type(parent_instance), parent_instance.pk)
                if obj_key not in processed:
                    to_restore[type(parent_instance)].add(parent_instance.pk)
                    next_level.append(parent_instance)

    def _restore_parent_objects(
        self,
        objects: list[models.Model],
        to_restore: dict[type[models.Model], set[Any]],
        next_level: list[models.Model],
        processed: set[tuple[type[models.Model], Any]],
        using: str,
    ) -> None:
        """Queue parent objects referenced via ForeignKey fields for restoration.

        When restoring an object, we also need to restore any deleted parent objects
        it references to maintain referential integrity.

        Args:
            objects: Child instances currently being processed.
            to_restore: Aggregate map of model -> primary key sets queued for restore.
            next_level: BFS queue used for subsequent traversal passes.
            processed: Cache used to avoid revisiting the same instances.
            using: Database alias for queryset execution.
        """
        if not objects:
            return

        model = type(objects[0])

        # Iterate through all fields on the model.
        for field in model._meta.get_fields():
            # Only process ForeignKey fields (exclude OneToOneField used for MTI).
            if not isinstance(field, models.ForeignKey):
                continue

            # Skip fields that are part of multi-table inheritance (handled separately).
            if field.name in [link.name for link in model._meta.parents.values() if link]:
                continue

            related_model = field.related_model

            # Skip if related model doesn't have row_status.
            if not hasattr(related_model, 'row_status'):
                continue

            # Collect parent PKs from the current objects.
            parent_pks = set()
            for obj in objects:
                parent_pk = getattr(obj, field.attname)  # Use attname to get the FK id directly
                if parent_pk:
                    parent_pks.add(parent_pk)

            if not parent_pks:
                continue

            # Fetch deleted parent objects.
            deleted_parents = (
                related_model.all_objects.using(using)
                .filter(pk__in=parent_pks, row_status=ROW_STATUS_DELETE)
            )

            for parent_instance in deleted_parents.iterator(chunk_size=DELETE_ITERATOR_CHUNK_SIZE):
                obj_key = (type(parent_instance), parent_instance.pk)
                if obj_key not in processed:
                    to_restore[type(parent_instance)].add(parent_instance.pk)
                    next_level.append(parent_instance)
