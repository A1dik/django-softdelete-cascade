"""Exception helpers for django-softdelete-cascade.

This module intentionally re-exports Django's native deletion exceptions
(`ProtectedError`, `RestrictedError`) via ``softdelete.base`` without adding new
types. Keeping a dedicated module documents the behavior and serves as a hook
if project-specific exceptions are needed later.
"""

# Built-in Django deletion exceptions referenced throughout the project:
# - django.db.models.deletion.ProtectedError
# - django.db.models.deletion.RestrictedError
#
# We rely on Django's implementations rather than redefining wrappers.
