"""Pytest configuration for django-softdelete-cascade."""

import os
import sys
from pathlib import Path

import django
from django.conf import settings

# Ensure the project root is on PYTHONPATH
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))


def pytest_configure():
    """Configure Django for the test suite."""
    if not settings.configured:
        settings.configure(
            DEBUG=True,
            DATABASES={
                'default': {
                    'ENGINE': 'django.db.backends.sqlite3',
                    'NAME': ':memory:',
                }
            },
            INSTALLED_APPS=[
                'django.contrib.contenttypes',
                'django.contrib.auth',
                'tests',
            ],
            SECRET_KEY='test-secret-key-for-django-softdelete-cascade',
            USE_TZ=True,
        )
        django.setup()

        # Apply migrations for the in-memory database
        from django.core.management import call_command

        call_command('migrate', '--run-syncdb', verbosity=0)
