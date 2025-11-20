"""Shared configuration constants for django-softdelete-cascade."""

# Row-status values used by every SoftDeleteModel.
ROW_STATUS_ACTIVE = 0
ROW_STATUS_UPDATED = 1
ROW_STATUS_DELETE = 2
ROW_STATUS_BANNED = 3

# Human-readable labels for admin forms and choices.
ROW_STATUS_CHOICES = [
    (ROW_STATUS_ACTIVE, 'Active'),
    (ROW_STATUS_UPDATED, 'Updated'),
    (ROW_STATUS_DELETE, 'Deleted'),
    (ROW_STATUS_BANNED, 'Banned'),
]

# Chunk size for queryset iterators while walking cascades.
DELETE_ITERATOR_CHUNK_SIZE = 500
