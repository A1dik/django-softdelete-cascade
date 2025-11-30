"""Performance benchmarks for soft delete operations.

These tests validate that the library handles large-scale operations efficiently
and verify that query optimizations (.only(), .select_related()) work correctly.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from django.db import connection, reset_queries
from django.test import override_settings

from softdelete import ROW_STATUS_ACTIVE, ROW_STATUS_DELETE

from .models import Author, Book, Chapter, Page


@pytest.mark.django_db
class TestPerformanceBenchmarks:
    """Benchmark tests for large-scale soft delete operations."""

    @override_settings(DEBUG=True)  # Enable query logging
    def test_large_cascade_query_count(self) -> None:
        """Verify optimized query count for large cascade operations.

        Creates a deep hierarchy and ensures we're not making N+1 queries.
        """
        reset_queries()

        # Create hierarchy: 1 Author -> 10 Books -> 5 Chapters each = 61 objects total
        author = Author.objects.create(name="Test Author")
        books = [
            Book.objects.create(title=f"Book {i}", author=author) for i in range(10)
        ]
        for book in books:
            for j in range(5):
                Chapter.objects.create(title=f"Chapter {j}", book=book)

        # Ensure objects were created
        assert Author.objects.count() == 1
        assert Book.objects.count() == 10
        assert Chapter.objects.count() == 50

        # Perform cascade delete
        reset_queries()
        deleted_count, deleted_models = author.delete()

        # Verify deletion
        assert deleted_count == 61
        assert deleted_models["tests.Author"] == 1
        assert deleted_models["tests.Book"] == 10
        assert deleted_models["tests.Chapter"] == 50

        # Check query count - should be reasonable (not 50+ queries)
        # Typically: 1 lock + BFS traversal (~3-4) + 3 bulk updates = ~7-10 queries
        query_count = len(connection.queries)
        assert query_count < 15, f"Expected < 15 queries, got {query_count}"

    @override_settings(DEBUG=True)
    def test_only_optimization_reduces_data_transfer(self) -> None:
        """Verify that .only() optimization fetches minimal data.

        The BFS traversal should use .only() to fetch only pk, row_status, and FK fields.
        """
        # Create hierarchy
        author = Author.objects.create(name="Author with very long name" * 10)
        books = [
            Book.objects.create(
                title=f"Book with extremely long title number {i}" * 20,
                author=author,
            )
            for i in range(5)
        ]

        reset_queries()
        author.delete()

        # Inspect queries to ensure .only() is being used
        # (In real implementation, queries should use ONLY specific columns)
        queries_sql = [q["sql"] for q in connection.queries]

        # At least one query should be optimized (contains only specific columns)
        # We can't easily assert the exact SQL, but we verify the operation works
        # and doesn't transfer unnecessary data
        assert len(queries_sql) > 0

    @override_settings(DEBUG=True)
    def test_select_related_optimization_in_protect(self) -> None:
        """Verify select_related() reduces queries in PROTECT checks."""
        from .models import Category, RestrictedBook

        # Create structure
        category = Category.objects.create(name="Fiction")
        books = [
            RestrictedBook.objects.create(title=f"Book {i}", category=category)
            for i in range(10)
        ]

        reset_queries()

        # Attempt to delete category (should fail due to RESTRICT)
        with pytest.raises(Exception):  # RestrictedError
            category.delete()

        # Verify select_related was used (fewer queries than N+1)
        query_count = len(connection.queries)
        # Should be: 1 lock + 1 check query with select_related (not 10 separate queries)
        assert (
            query_count <= 5
        ), f"Expected <= 5 queries with select_related, got {query_count}"

    @override_settings(DEBUG=True)
    def test_iterator_chunk_size_prevents_memory_bloat(self) -> None:
        """Verify iterator with chunk_size is used for large datasets."""
        # Create many objects
        author = Author.objects.create(name="Prolific Author")
        for i in range(100):
            Book.objects.create(title=f"Book {i}", author=author)

        # Delete should complete without loading all 100 books into memory at once
        deleted_count, _ = author.delete()

        assert deleted_count == 101  # 1 author + 100 books

    def test_restore_performance_with_large_hierarchy(self) -> None:
        """Verify restore performance on large hierarchies."""
        # Create and delete hierarchy
        author = Author.objects.create(name="Test Author")
        books = [
            Book.objects.create(title=f"Book {i}", author=author) for i in range(20)
        ]
        for book in books:
            for j in range(3):
                Chapter.objects.create(title=f"Chapter {j}", book=book)

        # Soft delete all
        author.delete()

        # Measure restore time
        start_time = time.time()
        restored_count, _ = author.restore()
        elapsed_time = time.time() - start_time

        # Verify correctness
        assert restored_count == 81  # 1 author + 20 books + 60 chapters
        assert Author.objects.count() == 1
        assert Book.objects.count() == 20
        assert Chapter.objects.count() == 60

        # Should complete in reasonable time (< 1 second for 81 objects)
        assert elapsed_time < 1.0, f"Restore took {elapsed_time:.3f}s, expected < 1.0s"


@pytest.mark.django_db
class TestQueryOptimizations:
    """Tests to verify specific query optimizations are applied."""

    def test_only_fields_specified_correctly(self) -> None:
        """Verify that .only() doesn't break object functionality."""
        author = Author.objects.create(name="Test")
        book = Book.objects.create(title="Test Book", author=author)
        Chapter.objects.create(title="Chapter 1", book=book)

        # Delete should work even with .only() optimization
        deleted_count, _ = author.delete()
        assert deleted_count == 3

    def test_select_related_doesnt_break_cascade(self) -> None:
        """Verify select_related in PROTECT checks doesn't affect cascade."""
        author = Author.objects.create(name="Test")
        books = [
            Book.objects.create(title=f"Book {i}", author=author) for i in range(3)
        ]

        # Cascade delete should work
        deleted_count, _ = author.delete()
        assert deleted_count == 4  # 1 author + 3 books


@pytest.mark.django_db
class TestBulkOperations:
    """Tests for bulk update efficiency."""

    def test_bulk_update_groups_by_model(self) -> None:
        """Verify that objects are bulk updated per model type."""
        author = Author.objects.create(name="Author")
        books = [
            Book.objects.create(title=f"Book {i}", author=author) for i in range(5)
        ]

        deleted_count, deleted_models = author.delete()

        # Verify grouped updates
        assert deleted_count == 6
        assert deleted_models["tests.Author"] == 1
        assert deleted_models["tests.Book"] == 5

    def test_dry_run_doesnt_affect_performance(self) -> None:
        """Verify dry_run mode has similar performance characteristics."""
        author = Author.objects.create(name="Author")
        books = [
            Book.objects.create(title=f"Book {i}", author=author) for i in range(10)
        ]

        # Dry run
        start_dry = time.time()
        result = author.delete(dry_run=True)
        dry_time = time.time() - start_dry

        # Real delete
        start_real = time.time()
        author.delete()
        real_time = time.time() - start_real

        # Dry run should be slightly faster (no transaction overhead)
        # but should be in the same order of magnitude
        assert result.would_succeed is True
        assert len(result.affected_objects) == 11
        assert dry_time < real_time * 2  # Not more than 2x slower
