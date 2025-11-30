"""Public package interface for django-softdelete-cascade.

Soft-delete functionality is exposed through ``SoftDeleteModel`` plus
``ROW_STATUS_*`` constants. The library performs breadth-first cascade
traversal, respects PROTECT/RESTRICT constraints, and handles multi-table
inheritance without issuing hard deletes.

Simple usage::

    from django.db import models
    from softdelete import ROW_STATUS_ACTIVE, SoftDeleteModel

    class Product(SoftDeleteModel):
        name = models.CharField(max_length=255)
        row_status = models.SmallIntegerField(default=ROW_STATUS_ACTIVE)

    product = Product.objects.create(name='Example')
    product.delete()  # marks the row as deleted and cascades to dependents
"""

from .admin import SoftDeleteAdmin, SoftDeleteAdminMixin
from .base import SoftDeleteManager, SoftDeleteModel, SoftDeleteQuerySet
from .constants import (
    DELETE_ITERATOR_CHUNK_SIZE,
    ROW_STATUS_ACTIVE,
    ROW_STATUS_BANNED,
    ROW_STATUS_CHOICES,
    ROW_STATUS_DELETE,
    ROW_STATUS_UPDATED,
    SOFTDELETE_LOGGER_NAME,
)
from .result import SoftDeleteRef, SoftDeleteResult

__version__ = "1.0.0"

__all__ = [
    "SoftDeleteModel",
    "SoftDeleteManager",
    "SoftDeleteQuerySet",
    "SoftDeleteRef",
    "SoftDeleteResult",
    "SoftDeleteAdmin",
    "SoftDeleteAdminMixin",
    "ROW_STATUS_ACTIVE",
    "ROW_STATUS_UPDATED",
    "ROW_STATUS_DELETE",
    "ROW_STATUS_BANNED",
    "ROW_STATUS_CHOICES",
    "DELETE_ITERATOR_CHUNK_SIZE",
    "SOFTDELETE_LOGGER_NAME",
]
