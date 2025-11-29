"""Core SoftDeleteModel implementation."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any

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
from .utils import deduplicate_objects, format_blocking_info

logger = logging.getLogger(SOFTDELETE_LOGGER_NAME)

if TYPE_CHECKING:
    from collections.abc import Iterable


class SoftDeleteQuerySet(models.QuerySet):
    """Custom QuerySet with soft-delete filtering and operations.

    Provides convenient methods for working with soft-deleted objects:
        * .alive() - filter only active objects
        * .deleted() - filter only soft-deleted objects
        * .soft_delete() - soft delete all objects in the queryset
        * .restore() - restore soft-deleted objects (stub for Stage 3)
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

    def restore(self) -> None:
        """Restore soft-deleted objects (stub for Stage 3).

        Raises:
            NotImplementedError: Will be implemented in Stage 3.
        """
        raise NotImplementedError('restore() will be implemented in Stage 3')


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
        self, using: str | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        """Soft-delete the instance and all CASCADE-related objects.

        The algorithm walks the relationship graph breadth-first, ensuring every
        processed model owns a ``row_status`` column before adding it to the
        update queue. PROTECT/RESTRICT dependencies are checked ahead of time to
        surface actionable exceptions.

        Args:
            using: Database alias to operate on; defaults to Django's router.
            keep_parents: Skip soft-deleting parent models in multi-table
                inheritance hierarchies when True.

        Returns:
            tuple[int, dict[str, int]]: Total number of updated rows and a map
            of model labels to the number of affected rows.

        Raises:
            ProtectedError: A PROTECT relation blocked deletion.
            RestrictedError: A RESTRICT relation blocked deletion.
        """
        if using is None:
            using = router.db_for_write(self.__class__, instance=self)

        model_label = f'{self._meta.app_label}.{self._meta.object_name}'
        logger.debug(
            'Starting soft-delete for %s (pk=%s)',
            model_label,
            self.pk,
        )

        # Short-circuit when the instance was previously soft-deleted.
        if hasattr(self, 'row_status') and self.row_status == ROW_STATUS_DELETE:
            logger.debug(
                'Skipping soft-delete for %s (pk=%s) - already deleted',
                model_label,
                self.pk,
            )
            return 0, {}

        deleted_counter = 0
        deleted_models: dict[str, int] = {}

        with transaction.atomic(using=using):
            # Lock the root object to prevent concurrent modifications.
            type(self).all_objects.using(using).filter(pk=self.pk).select_for_update(nowait=False).first()

            # Track model -> primary key set for every object to soft-delete.
            to_delete: dict[type[models.Model], set[Any]] = defaultdict(set)
            to_delete[type(self)].add(self.pk)

            # Guard against traversing the same instance multiple times.
            processed: set[tuple[type[models.Model], Any]] = set()

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
                    # Fail fast if PROTECT or RESTRICT constraints block delete.
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

            # Apply bulk updates grouped by model once traversal ends.
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
            'Completed soft-delete for %s (pk=%s): %d object(s) affected across %d model(s)',
            f'{self._meta.app_label}.{self._meta.object_name}',
            self.pk,
            deleted_counter,
            len(deleted_models),
        )

        return deleted_counter, deleted_models

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
