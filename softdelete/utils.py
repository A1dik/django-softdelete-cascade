"""Utility helpers shared across django-softdelete-cascade."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.db import models


def deduplicate_objects(blocking_objects: list[models.Model]) -> list[models.Model]:
    """Return a stable list of unique blocking objects.

    Args:
        blocking_objects: Sequence of model instances collected during traversal.

    Returns:
        Unique objects preserving the last instance encountered for each model/pk pair.
    """
    unique_objects: dict[tuple[type[models.Model], int], models.Model] = {}
    for blocking_object in blocking_objects:
        if blocking_object.pk is None:
            continue

        key = (type(blocking_object), blocking_object.pk)
        if key not in unique_objects:
            unique_objects[key] = blocking_object

    return list(unique_objects.values())


def format_blocking_info(blocking_objects: list[models.Model]) -> str:
    """Build a compact human-readable description of blocking objects.

    Args:
        blocking_objects: Objects that prevented the delete operation.

    Returns:
        Description string suitable for ``ProtectedError`` or ``RestrictedError``.
    """
    if not blocking_objects:
        return ""

    blocking_by_model: dict[str, int] = defaultdict(int)
    for obj in blocking_objects:
        model_label = f"{obj._meta.app_label}.{obj._meta.object_name}"
        blocking_by_model[model_label] += 1

    info_parts = []
    for model_label, count in blocking_by_model.items():
        info_parts.append(f"{model_label}: {count}")

    return f'Blocking objects: {", ".join(info_parts)}'
