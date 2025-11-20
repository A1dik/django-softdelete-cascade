# Django SoftDelete Cascade

[![PyPI version](https://badge.fury.io/py/django-softdelete-cascade.svg)](https://badge.fury.io/py/django-softdelete-cascade)
[![Python versions](https://img.shields.io/pypi/pyversions/django-softdelete-cascade.svg)](https://pypi.org/project/django-softdelete-cascade/)
[![Django versions](https://img.shields.io/pypi/djversions/django-softdelete-cascade.svg)](https://pypi.org/project/django-softdelete-cascade/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Robust soft-delete utilities for Django models with cascade traversal, PROTECT/RESTRICT awareness, and multi-table inheritance support. `SoftDeleteModel` replaces destructive deletes with status-driven bulk updates while keeping the ORM API familiar.

## Features

- `SoftDeleteModel` base class with `row_status` tracking, helper managers, and timestamp updates.
- Breadth-first cascade traversal that respects `ForeignKey(..., on_delete=CASCADE)` relationships without issuing per-object deletes.
- PROTECT/RESTRICT detection with helpful exceptions that list blocking rows via `format_blocking_info`.
- Seamless multi-table inheritance support: parents are soft-deleted automatically unless `keep_parents=True`.
- Bulk updates wrapped in `transaction.atomic`, chunked iterators, and multi-database routing support.

## Installation

```bash
pip install django-softdelete-cascade
```

Requirements: Python 3.10+, Django 3.2-5.0, and a `row_status` integer field on each participating model (use `ROW_STATUS_CHOICES` and `ROW_STATUS_ACTIVE` for defaults).

## Quickstart

```python
from django.db import models
from softdelete import (
    ROW_STATUS_ACTIVE,
    ROW_STATUS_CHOICES,
    SoftDeleteModel,
)


class Author(SoftDeleteModel):
    name = models.CharField(max_length=255)
    row_status = models.SmallIntegerField(
        choices=ROW_STATUS_CHOICES,
        default=ROW_STATUS_ACTIVE,
    )


class Book(SoftDeleteModel):
    title = models.CharField(max_length=255)
    author = models.ForeignKey(
        Author,
        on_delete=models.CASCADE,
        related_name='books',
    )
    row_status = models.SmallIntegerField(
        choices=ROW_STATUS_CHOICES,
        default=ROW_STATUS_ACTIVE,
    )


author = Author.objects.create(name='Jane Doe')
Book.objects.create(title='First Novel', author=author)
Book.objects.create(title='Second Novel', author=author)

deleted_count, deleted_models = author.delete()
# deleted_count == 3
# deleted_models == {'tests.Author': 1, 'tests.Book': 2}

active_authors = Author.get_active()
```

## How it Works

1. `.delete()` queues the target instance and uses BFS to discover related objects via `on_delete=CASCADE` relations that also expose `row_status`.
2. Before touching the queue, `_check_protected_relations` ensures no PROTECT/RESTRICT rows remain active; if they do, a Django `ProtectedError` or `RestrictedError` is raised with contextual details.
3. Parent models in multi-table inheritance hierarchies are soft-deleted automatically unless `keep_parents=True`.
4. Once traversal finishes, each model is bulk-updated (single query per model) to set `row_status=ROW_STATUS_DELETE` and refresh `update_date`, all inside an atomic transaction.

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
