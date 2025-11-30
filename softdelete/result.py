"""Result types for soft-delete and restore operations.

Provides immutable dataclasses that represent the outcome of dry-run operations,
allowing users to preview changes before committing them to the database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.db import models


@dataclass(frozen=True)
class SoftDeleteRef:
    """Immutable reference to a single database object.

    Captures identifying information about an object without holding
    a reference to the actual model instance, preventing memory leaks
    and stale data issues.

    Attributes:
        app_label: Application label (e.g., 'auth', 'myapp').
        model_name: Model class name (e.g., 'User', 'Product').
        pk: Primary key value (can be int, str, UUID, etc.).
        str_repr: Human-readable string representation of the object.
    """

    app_label: str
    model_name: str
    pk: int | str
    str_repr: str

    @classmethod
    def from_instance(cls, instance: models.Model) -> SoftDeleteRef:
        """Create a reference from a model instance.

        Args:
            instance: Django model instance to reference.

        Returns:
            SoftDeleteRef containing the instance's metadata.
        """
        return cls(
            app_label=instance._meta.app_label,
            model_name=instance._meta.object_name,
            pk=instance.pk,
            str_repr=str(instance),
        )

    @property
    def model_label(self) -> str:
        """Return the full model label in 'app_label.ModelName' format.

        Returns:
            Dotted model label suitable for Django admin and error messages.
        """
        return f"{self.app_label}.{self.model_name}"


@dataclass(frozen=True)
class SoftDeleteResult:
    """Result of a soft-delete or restore dry-run operation.

    Provides detailed information about what would be affected by an operation
    without actually modifying the database. Useful for previewing cascades,
    validating constraints, and building user confirmations.

    Attributes:
        affected_objects: Objects that would be modified by the operation.
            Ordered by dependency level (root objects first, then children).
        blocked_objects: Objects that prevent the operation due to PROTECT
            or RESTRICT constraints. Only populated for delete operations.
        would_succeed: True if the operation can proceed, False if blocked.
        total_count: Total number of objects that would be affected.
        model_counts: Per-model breakdown of affected object counts.
    """

    affected_objects: tuple[SoftDeleteRef, ...] = field(default_factory=tuple)
    blocked_objects: tuple[SoftDeleteRef, ...] = field(default_factory=tuple)
    would_succeed: bool = True
    total_count: int = 0
    model_counts: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate invariants after initialization.

        Ensures that total_count and model_counts are consistent with
        affected_objects. This helps catch bugs during development.
        """
        # Frozen dataclass requires object.__setattr__ for validation adjustments.
        if self.total_count == 0 and self.affected_objects:
            object.__setattr__(self, "total_count", len(self.affected_objects))

        if not self.model_counts and self.affected_objects:
            counts: dict[str, int] = {}
            for ref in self.affected_objects:
                counts[ref.model_label] = counts.get(ref.model_label, 0) + 1
            object.__setattr__(self, "model_counts", counts)

    @property
    def affected_count(self) -> int:
        """Return count of objects that would be modified.

        Returns:
            Number of objects in affected_objects.
        """
        return len(self.affected_objects)

    @property
    def blocked_count(self) -> int:
        """Return count of objects blocking the operation.

        Returns:
            Number of objects in blocked_objects.
        """
        return len(self.blocked_objects)

    def to_tuple(self) -> tuple[int, dict[str, int]]:
        """Convert to Django-style delete return format.

        Provides compatibility with existing code that expects
        the standard (count, models_dict) tuple.

        Returns:
            Tuple of (total_count, model_counts) matching Django's delete() API.
        """
        return self.total_count, dict(self.model_counts)
