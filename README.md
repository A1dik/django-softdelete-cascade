# Django SoftDelete Cascade

[![PyPI version](https://badge.fury.io/py/django-softdelete-cascade.svg)](https://badge.fury.io/py/django-softdelete-cascade)
[![Python versions](https://img.shields.io/pypi/pyversions/django-softdelete-cascade.svg)](https://pypi.org/project/django-softdelete-cascade/)
[![Django versions](https://img.shields.io/pypi/djversions/django-softdelete-cascade.svg)](https://pypi.org/project/django-softdelete-cascade/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Robust soft-delete utilities for Django models with cascade traversal, PROTECT/RESTRICT awareness, and multi-table inheritance support. `SoftDeleteModel` replaces destructive deletes with status-driven bulk updates while keeping the ORM API familiar.

## Features

- **Dry-run mode**: Preview delete/restore operations before committing with `dry_run=True` parameter - get detailed impact analysis without database changes (v0.4.0+).
- **Built-in `row_status` field**: No need to manually define `row_status`, `create_date`, or `update_date` - they're included automatically (v0.2.0+).
- **Smart managers**: Default `.objects` manager filters out soft-deleted objects automatically; use `.all_objects` to include deleted ones (v0.2.0+).
- **QuerySet methods**: `.alive()`, `.deleted()`, `.soft_delete()`, and `.restore()` for convenient filtering and bulk operations (v0.2.0+).
- **Cascade restore**: Restore soft-deleted objects and all their CASCADE-related children with a single `.restore()` call (v0.3.0+).
- Breadth-first cascade traversal that respects `ForeignKey(..., on_delete=CASCADE)` relationships without issuing per-object deletes.
- PROTECT/RESTRICT detection with helpful exceptions that list blocking rows via `format_blocking_info`.
- Seamless multi-table inheritance support: parents are soft-deleted/restored automatically.
- Bulk updates wrapped in `transaction.atomic`, chunked iterators, and multi-database routing support.
- **Concurrency-safe operations** via `select_for_update()` locking mechanism (v0.1.1+).
- **Built-in logging** for observability with debug and info level messages (v0.1.1+).

## Installation

```bash
pip install django-softdelete-cascade
```

Requirements: Python 3.10+, Django 3.2-5.0.

## Quickstart

```python
from django.db import models
from softdelete import SoftDeleteModel


class Author(SoftDeleteModel):
    """Author model with automatic soft-delete support.

    SoftDeleteModel automatically provides:
    - row_status field (indexed, with choices)
    - create_date and update_date timestamps
    - Smart managers (objects, all_objects)
    """
    name = models.CharField(max_length=255)


class Book(SoftDeleteModel):
    """Book model linked to Author."""
    title = models.CharField(max_length=255)
    author = models.ForeignKey(
        Author,
        on_delete=models.CASCADE,
        related_name='books',
    )


# Create test data
author = Author.objects.create(name='Jane Doe')
Book.objects.create(title='First Novel', author=author)
Book.objects.create(title='Second Novel', author=author)

# Soft-delete cascades to related books
deleted_count, deleted_models = author.delete()
# deleted_count == 3
# deleted_models == {'myapp.Author': 1, 'myapp.Book': 2}

# Default manager filters out deleted objects
Author.objects.count()  # 0 (soft-deleted objects are hidden)
Book.objects.count()    # 0

# Use all_objects to include deleted objects
Author.all_objects.count()  # 1 (includes soft-deleted)
Book.all_objects.count()    # 2

# Filter by status explicitly
active_authors = Author.objects.alive()      # same as .all()
deleted_authors = Author.all_objects.deleted()
```

## How it Works

1. `.delete()` queues the target instance and uses BFS to discover related objects via `on_delete=CASCADE` relations that also expose `row_status`.
2. Before touching the queue, `_check_protected_relations` ensures no PROTECT/RESTRICT rows remain active; if they do, a Django `ProtectedError` or `RestrictedError` is raised with contextual details.
3. Parent models in multi-table inheritance hierarchies are soft-deleted automatically unless `keep_parents=True`.
4. Once traversal finishes, each model is bulk-updated (single query per model) to set `row_status=ROW_STATUS_DELETE` and refresh `update_date`, all inside an atomic transaction.
5. **Concurrency safety**: The root object is locked using `select_for_update(nowait=False)` at the start of the transaction to prevent race conditions during concurrent delete operations.

## Logging

The library includes built-in logging using Python's standard logging module. Configure it in your Django settings:

```python
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'softdelete': {
            'handlers': ['console'],
            'level': 'INFO',  # or 'DEBUG' for more detailed logs
        },
    },
}
```

Log messages include:
- **DEBUG**: Operation start notifications with object details
- **INFO**: Operation completion with affected object counts

## Restore Functionality (v0.3.0+)

Soft-deleted objects can be restored using the `.restore()` method, which mirrors the delete behavior:

```python
# Create and delete an author with books
author = Author.objects.create(name='Jane Doe')
book1 = Book.objects.create(title='First Novel', author=author)
book2 = Book.objects.create(title='Second Novel', author=author)

# Soft-delete cascades to books
author.delete()  # Author and both books are now soft-deleted

# Restore the author and all cascade-related objects
restored_count, restored_models = author.restore()
# restored_count == 3
# restored_models == {'myapp.Author': 1, 'myapp.Book': 2}

# All objects are now active again
Author.objects.count()  # 1
Book.objects.count()    # 2
```

### Restore Features

- **Cascade Restore**: By default, restoring an object also restores all CASCADE-related children
- **Parent Restoration**: When restoring a child object, deleted parent objects (via ForeignKey) are also restored to maintain referential integrity
- **Multi-table Inheritance**: Parent models in MTI hierarchies are automatically restored
- **Selective Restore**: Use `restore_children=False` to restore only the target object
- **Idempotent**: Restoring an already-active object has no side effects
- **Concurrency-Safe**: Uses `select_for_update()` locking like delete operations
- **Bulk Operations**: Use QuerySet `.restore()` to restore multiple objects at once

### Restore Examples

```python
# Restore a single object with all children
author.restore()  # Restores author and all related books

# Restore without children
author.restore(restore_children=False)  # Only restores the author

# Bulk restore via QuerySet
deleted_authors = Author.all_objects.deleted()
count, models = deleted_authors.restore()  # Restores all deleted authors

# Restore a child object (parent will be restored too)
book = Book.all_objects.deleted().first()
book.restore()  # Restores both the book and its author (if deleted)
```

## Dry-Run Mode (v0.4.0+)

Preview the impact of delete and restore operations before committing changes to the database. The `dry_run=True` parameter performs a read-only traversal and returns a detailed `SoftDeleteResult` object instead of modifying data.

### Why Use Dry-Run?

- **Preview cascades**: See exactly which objects would be affected before deletion
- **Validate constraints**: Check if PROTECT/RESTRICT relations would block the operation
- **Build confirmations**: Show users what will be deleted/restored before proceeding
- **Debug complex hierarchies**: Understand CASCADE traversal without side effects

### Dry-Run with Delete

```python
from softdelete import SoftDeleteResult

# Create test data
author = Author.objects.create(name='Jane Doe')
book1 = Book.objects.create(title='First Novel', author=author)
book2 = Book.objects.create(title='Second Novel', author=author)

# Preview the deletion impact
result = author.delete(dry_run=True)

# Inspect the result
print(f"Would delete {result.total_count} objects")
print(f"Operation would {'succeed' if result.would_succeed else 'fail'}")

# Check affected objects
for ref in result.affected_objects:
    print(f"  - {ref.model_label}: {ref.str_repr} (pk={ref.pk})")

# Breakdown by model
print(result.model_counts)
# {'myapp.Author': 1, 'myapp.Book': 2}

# No database changes were made!
Author.objects.count()  # Still 1
Book.objects.count()    # Still 2
```

### Dry-Run with Restore

```python
# Delete the author and books
author.delete()

# Preview the restore impact
result = author.restore(dry_run=True)

print(f"Would restore {result.total_count} objects")
print(f"Breakdown: {result.model_counts}")

# Database is still unchanged
Author.objects.count()  # Still 0 (not restored yet)

# Proceed with actual restore
author.restore()
Author.objects.count()  # Now 1 (restored)
```

### Dry-Run with PROTECT Constraints

```python
from django.db import models

class Publisher(SoftDeleteModel):
    name = models.CharField(max_length=255)

class ProtectedBook(SoftDeleteModel):
    title = models.CharField(max_length=255)
    publisher = models.ForeignKey(
        Publisher,
        on_delete=models.PROTECT,  # Blocks deletion
        related_name='books'
    )

# Create data
publisher = Publisher.objects.create(name='Acme Publishing')
book = ProtectedBook.objects.create(title='Protected Book', publisher=publisher)

# Dry-run detects the blocking constraint
result = publisher.delete(dry_run=True)

print(result.would_succeed)  # False
print(f"Blocked by {result.blocked_count} objects:")
for ref in result.blocked_objects:
    print(f"  - {ref.model_label}: {ref.str_repr}")

# No exception raised in dry-run mode!
# In normal mode, this would raise ProtectedError
```

### SoftDeleteResult API

The `SoftDeleteResult` dataclass provides detailed information about a dry-run operation:

```python
@dataclass(frozen=True)
class SoftDeleteResult:
    # Objects that would be modified
    affected_objects: tuple[SoftDeleteRef, ...]

    # Objects blocking the operation (PROTECT/RESTRICT)
    blocked_objects: tuple[SoftDeleteRef, ...]

    # Whether the operation can proceed
    would_succeed: bool

    # Total count of affected objects
    total_count: int

    # Per-model breakdown: {'app.Model': count}
    model_counts: dict[str, int]

    # Properties
    affected_count: int  # len(affected_objects)
    blocked_count: int   # len(blocked_objects)

    # Convert to Django-style tuple
    def to_tuple() -> tuple[int, dict[str, int]]
```

Each `SoftDeleteRef` contains:

```python
@dataclass(frozen=True)
class SoftDeleteRef:
    app_label: str      # 'myapp'
    model_name: str     # 'Author'
    pk: int | str       # Primary key value
    str_repr: str       # str(instance) representation

    @property
    def model_label(self) -> str:  # 'myapp.Author'
```

### Dry-Run Use Cases

**1. User Confirmation Dialog**
```python
def delete_with_confirmation(author_id):
    author = Author.objects.get(pk=author_id)
    result = author.delete(dry_run=True)

    if not result.would_succeed:
        return JsonResponse({
            'error': 'Cannot delete',
            'blocked_by': [
                ref.str_repr for ref in result.blocked_objects
            ]
        }, status=400)

    # Show confirmation to user
    return JsonResponse({
        'message': f'This will delete {result.total_count} objects',
        'breakdown': result.model_counts,
        'objects': [ref.str_repr for ref in result.affected_objects]
    })
```

**2. Audit Log Preview**
```python
def preview_cascade(obj):
    result = obj.delete(dry_run=True)

    log_entry = {
        'action': 'delete',
        'target': str(obj),
        'would_affect': result.total_count,
        'models': list(result.model_counts.keys()),
        'would_succeed': result.would_succeed,
    }

    return log_entry
```

**3. Testing Complex Hierarchies**
```python
def test_cascade_depth():
    author = create_author_with_nested_books()
    result = author.delete(dry_run=True)

    # Verify cascade depth without database changes
    assert result.total_count == 15
    assert 'myapp.Author' in result.model_counts
    assert 'myapp.Book' in result.model_counts
    assert 'myapp.Chapter' in result.model_counts
```

## Manager and QuerySet API (v0.2.0+)

`SoftDeleteModel` provides two managers and a custom QuerySet with convenient methods:

### Managers

- **`Model.objects`** - Default manager that **filters out soft-deleted objects automatically**
  - `Model.objects.all()` returns only active objects
  - `Model.objects.filter(...)` operates on active objects only

- **`Model.all_objects`** - Manager that **includes both active and deleted objects**
  - `Model.all_objects.all()` returns all objects (active + deleted)
  - Use this when you need to work with soft-deleted objects

### QuerySet Methods

- **`.alive()`** - Filter to only active (non-deleted) objects
  ```python
  Author.all_objects.alive()  # Same as Author.objects.all()
  ```

- **`.deleted()`** - Filter to only soft-deleted objects
  ```python
  Author.all_objects.deleted()  # Returns soft-deleted authors
  ```

- **`.soft_delete()`** - Bulk soft-delete all objects in the queryset
  ```python
  # Soft-delete all authors whose name starts with 'J'
  count, models_dict = Author.objects.filter(name__startswith='J').soft_delete()
  ```

- **`.restore(restore_children=True)`** - Restore soft-deleted objects with CASCADE support (v0.3.0+)
  ```python
  # Restore a single object and all its CASCADE-related children
  author = Author.all_objects.deleted().first()
  restored_count, models_dict = author.restore()

  # Restore multiple objects via QuerySet
  count, models_dict = Author.all_objects.deleted().restore()

  # Restore without children (only the object itself)
  author.restore(restore_children=False)
  ```

### Manager Examples

```python
# Create test data
author1 = Author.objects.create(name='Active Author')
author2 = Author.objects.create(name='Deleted Author')
author2.delete()

# Default manager hides deleted objects
Author.objects.count()  # 1 (only active)
Author.objects.all()    # QuerySet with author1 only

# all_objects includes deleted objects
Author.all_objects.count()  # 2 (active + deleted)

# Manager methods
Author.objects.all_with_deleted()  # Same as Author.all_objects.all()
Author.objects.deleted_only()      # Only soft-deleted objects

# QuerySet chaining
Author.all_objects.filter(name__contains='Author').alive()
Author.all_objects.deleted().filter(name__startswith='D')
```

### Migration from v0.1.x

**Breaking Changes in v0.2.0:**

1. **Remove manual field definitions**: Delete `row_status`, `create_date`, and `update_date` from your models - they're now provided automatically:
   ```python
   # Before (v0.1.x)
   class Author(SoftDeleteModel):
       name = models.CharField(max_length=255)
       row_status = models.SmallIntegerField(choices=ROW_STATUS_CHOICES, default=ROW_STATUS_ACTIVE)
       create_date = models.DateTimeField(auto_now_add=True)
       update_date = models.DateTimeField(auto_now=True)

   # After (v0.2.0+)
   class Author(SoftDeleteModel):
       name = models.CharField(max_length=255)
       # row_status, create_date, update_date are automatic!
   ```

2. **Update manager usage**: Replace `Model.get_active()` with `Model.objects.all()`:
   ```python
   # Before (v0.1.x)
   active_authors = Author.get_active()

   # After (v0.2.0+)
   active_authors = Author.objects.all()  # or .alive()
   ```

3. **Access deleted objects**: Use `all_objects` instead of `objects` when you need to include deleted objects:
   ```python
   # Before (v0.1.x)
   all_authors = Author.objects.all()  # Included deleted

   # After (v0.2.0+)
   all_authors = Author.all_objects.all()  # Includes deleted
   active_only = Author.objects.all()       # Only active
   ```

## Development

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
pytest              # run the entire suite
pytest --cov=softdelete --cov-report=html
black softdelete tests && isort .
flake8 softdelete tests
python -m build     # produce wheel + sdist into dist/
```

- Tests live under `tests/` and cover cascade paths (`tests/test_cascade.py`), PROTECT/RESTRICT (`tests/test_protect.py`, `tests/test_restrict.py`), and multi-table inheritance (`tests/test_parents.py`).
- Packaging metadata is defined via `pyproject.toml` and `setup.cfg`; `MANIFEST.in` ensures all assets ship to PyPI.

## Contributing

All documentation, code comments, docstrings, commit messages, and issue/PR discussions must be written in English. Follow the docstring template in `softdelete/base.py` (Google style) and keep examples concise. Before opening a pull request, run pytest, flake8, black, isort, and mypy locally, then describe the behavioral change, tests, and compatibility considerations. Additional contributor instructions live in [AGENTS.md](AGENTS.md) and [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Released under the [MIT License](LICENSE).
