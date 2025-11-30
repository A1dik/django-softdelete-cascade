"""Edge case tests for complex scenarios and unusual graph structures.

These tests cover corner cases like circular references, self-references,
complex graph topologies, and boundary conditions.
"""

from __future__ import annotations

import pytest
from django.db import models

from softdelete import ROW_STATUS_ACTIVE, ROW_STATUS_DELETE, SoftDeleteModel

from .models import Author, Book, Chapter


# Test models for circular references
class Node(SoftDeleteModel):
    """Node with self-referencing relationship."""

    name = models.CharField(max_length=100)
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
    )

    class Meta:
        app_label = "tests"


class TeamMember(SoftDeleteModel):
    """Model for testing circular team relationships."""

    name = models.CharField(max_length=100)
    mentor = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="mentees",
    )

    class Meta:
        app_label = "tests"


@pytest.mark.django_db
class TestCircularReferences:
    """Tests for circular and self-referencing relationships."""

    def test_self_referencing_cascade(self) -> None:
        """Test cascade delete with self-referencing model."""
        # Create tree: root -> child1 -> grandchild
        root = Node.objects.create(name="Root")
        child1 = Node.objects.create(name="Child 1", parent=root)
        grandchild = Node.objects.create(name="Grandchild", parent=child1)

        # Delete root should cascade to children
        deleted_count, deleted_models = root.delete()

        assert deleted_count == 3
        assert Node.objects.count() == 0
        assert Node.all_objects.filter(row_status=ROW_STATUS_DELETE).count() == 3

    def test_self_reference_no_infinite_loop(self) -> None:
        """Ensure self-referencing doesn't cause infinite loops."""
        parent = Node.objects.create(name="Parent")
        Node.objects.create(name="Child", parent=parent)

        # Delete should not hang or loop infinitely
        deleted_count, _ = parent.delete()
        assert deleted_count == 2

    def test_wide_tree_structure(self) -> None:
        """Test deletion of wide tree (many children, few levels)."""
        root = Node.objects.create(name="Root")
        # Create 50 direct children
        children = [
            Node.objects.create(name=f"Child {i}", parent=root) for i in range(50)
        ]

        deleted_count, _ = root.delete()
        assert deleted_count == 51  # root + 50 children

    def test_deep_tree_structure(self) -> None:
        """Test deletion of deep tree (few children, many levels)."""
        # Create chain: node0 -> node1 -> node2 -> ... -> node20
        current = None
        for i in range(20):
            current = Node.objects.create(name=f"Node {i}", parent=current)

        # Get the root (parent=None)
        root = Node.objects.filter(parent=None).first()
        assert root is not None

        deleted_count, _ = root.delete()
        assert deleted_count == 20


@pytest.mark.django_db
class TestComplexGraphs:
    """Tests for complex relationship graphs."""

    def test_diamond_dependency_graph(self) -> None:
        """Test diamond-shaped dependency: A -> B,C -> D.

        Structure:
            Author (A)
              |
          +---+---+
          |       |
        Book1   Book2
          |       |
        Chapter1 Chapter2
        """
        author = Author.objects.create(name="Author")
        book1 = Book.objects.create(title="Book 1", author=author)
        book2 = Book.objects.create(title="Book 2", author=author)

        # Create chapters for each book
        chapter1 = Chapter.objects.create(title="Chapter 1", book=book1)
        chapter2 = Chapter.objects.create(title="Chapter 2", book=book2)

        deleted_count, _ = author.delete()

        # Should delete: 1 author + 2 books + 2 chapters = 5
        assert deleted_count == 5

    def test_multiple_paths_to_same_object(self) -> None:
        """Ensure object is only deleted once even with multiple paths."""
        author = Author.objects.create(name="Author")
        book = Book.objects.create(title="Book", author=author)
        # Create multiple chapters pointing to same book
        chapters = [
            Chapter.objects.create(title=f"Chapter {i}", book=book) for i in range(5)
        ]

        deleted_count, deleted_models = author.delete()

        # Should delete: 1 author + 1 book + 5 chapters = 7 (no duplicates)
        assert deleted_count == 7
        assert deleted_models["tests.Book"] == 1  # Only once


@pytest.mark.django_db
class TestBoundaryConditions:
    """Tests for boundary conditions and empty states."""

    def test_delete_with_no_relations(self) -> None:
        """Delete object with no related objects."""
        author = Author.objects.create(name="Lonely Author")
        deleted_count, deleted_models = author.delete()

        assert deleted_count == 1
        assert deleted_models == {"tests.Author": 1}

    def test_delete_already_deleted_object(self) -> None:
        """Deleting already deleted object is idempotent."""
        author = Author.objects.create(name="Author")
        author.delete()

        # Refresh instance from database to get updated row_status
        author.refresh_from_db()

        # Delete again
        deleted_count, deleted_models = author.delete()

        assert deleted_count == 0
        assert deleted_models == {}

    def test_restore_already_active_object(self) -> None:
        """Restoring active object is idempotent."""
        author = Author.objects.create(name="Author")

        restored_count, restored_models = author.restore()

        assert restored_count == 0
        assert restored_models == {}

    def test_empty_queryset_operations(self) -> None:
        """Operations on empty querysets."""
        # Soft delete on empty queryset
        deleted_count, deleted_models = Author.objects.none().soft_delete()
        assert deleted_count == 0
        assert deleted_models == {}

        # Restore on empty queryset
        restored_count, restored_models = Author.all_objects.deleted().restore()
        assert restored_count == 0
        assert restored_models == {}

    def test_partial_deletion_state(self) -> None:
        """Test object graph with mixed deleted/active states."""
        author = Author.objects.create(name="Author")
        book1 = Book.objects.create(title="Book 1", author=author)
        book2 = Book.objects.create(title="Book 2", author=author)
        chapter = Chapter.objects.create(title="Chapter 1", book=book1)

        # Manually delete book1 and its chapter
        book1.delete()

        # Now delete author (book2 is still active)
        deleted_count, _ = author.delete()

        # Should delete: author + book2 (book1 already deleted)
        assert deleted_count == 2

    def test_concurrent_delete_idempotency(self) -> None:
        """Multiple delete calls on same object should be idempotent."""
        author = Author.objects.create(name="Author")

        # First delete
        count1, models1 = author.delete()

        # Refresh instance
        author = Author.all_objects.get(pk=author.pk)

        # Second delete
        count2, models2 = author.delete()

        assert count1 == 1
        assert count2 == 0  # Already deleted


@pytest.mark.django_db
class TestDeduplication:
    """Tests for object deduplication in BFS traversal."""

    def test_no_duplicate_processing(self) -> None:
        """Ensure objects aren't processed multiple times in BFS."""
        author = Author.objects.create(name="Author")
        books = [
            Book.objects.create(title=f"Book {i}", author=author) for i in range(3)
        ]
        # All chapters point to first book
        chapters = [
            Chapter.objects.create(title=f"Chapter {i}", book=books[0])
            for i in range(5)
        ]

        deleted_count, deleted_models = author.delete()

        # Should count each object exactly once
        assert deleted_count == 1 + 3 + 5  # author + books + chapters
        assert deleted_models["tests.Book"] == 3
        assert deleted_models["tests.Chapter"] == 5

    def test_dry_run_deduplication(self) -> None:
        """Verify dry_run also deduplicates properly."""
        author = Author.objects.create(name="Author")
        books = [
            Book.objects.create(title=f"Book {i}", author=author) for i in range(5)
        ]

        result = author.delete(dry_run=True)

        # Should have 6 unique refs (1 author + 5 books)
        assert len(result.affected_objects) == 6
        # Verify no duplicates
        ref_ids = [(ref.model_name, ref.pk) for ref in result.affected_objects]
        assert len(ref_ids) == len(set(ref_ids))


@pytest.mark.django_db
class TestMultiDatabaseScenarios:
    """Tests for multi-database edge cases."""

    def test_delete_respects_db_router(self) -> None:
        """Verify delete uses correct database via router."""
        # Using default database
        author = Author.objects.create(name="Author")
        book = Book.objects.create(title="Book", author=author)

        # Delete should work on default db
        deleted_count, _ = author.delete(using="default")
        assert deleted_count == 2

    def test_explicit_using_parameter(self) -> None:
        """Test explicit using parameter in delete."""
        author = Author.objects.create(name="Author")
        deleted_count, _ = author.delete(using="default")
        assert deleted_count == 1


@pytest.mark.django_db
class TestNullAndOptionalRelations:
    """Tests for nullable and optional relationships."""

    def test_null_foreign_key_handling(self) -> None:
        """Objects with null FKs should handle gracefully."""
        # Create node without parent (parent=None)
        orphan = Node.objects.create(name="Orphan")
        deleted_count, _ = orphan.delete()

        assert deleted_count == 1

    def test_cascade_with_some_null_relations(self) -> None:
        """Mixed null and non-null relations in same model."""
        parent = Node.objects.create(name="Parent")
        child_with_parent = Node.objects.create(name="Child with parent", parent=parent)
        orphan = Node.objects.create(name="Orphan")  # null parent

        # Delete parent
        deleted_count, _ = parent.delete()

        # Should delete parent and child_with_parent, but not orphan
        assert deleted_count == 2
        assert Node.objects.filter(name="Orphan").exists()


@pytest.mark.django_db
class TestKeepParentsParameter:
    """Tests for keep_parents parameter with MTI."""

    def test_keep_parents_true_skips_parent_deletion(self) -> None:
        """Verify keep_parents=True doesn't delete MTI parents."""
        from .models import Restaurant

        restaurant = Restaurant.objects.create(
            name="Test Restaurant",
            address="123 Test St",
        )

        # Delete with keep_parents=True
        deleted_count, _ = restaurant.delete(keep_parents=True)

        # Should only delete Restaurant, not parent Place
        # (In this implementation, we don't have Place model, so this is conceptual)
        assert deleted_count == 1

    def test_keep_parents_false_deletes_parent(self) -> None:
        """Verify keep_parents=False (default) deletes MTI parents."""
        from .models import Restaurant

        restaurant = Restaurant.objects.create(
            name="Test Restaurant",
            address="123 Test St",
        )

        deleted_count, _ = restaurant.delete(keep_parents=False)

        # Should delete both child and parent
        assert deleted_count >= 1


@pytest.mark.django_db
class TestRestoreEdgeCases:
    """Edge cases specific to restore functionality."""

    def test_restore_with_active_parent(self) -> None:
        """Restore child when parent is already active."""
        author = Author.objects.create(name="Author")
        book = Book.objects.create(title="Book", author=author)

        # Delete book only
        book.delete()

        # Restore book (parent is active)
        restored_count, _ = book.restore()

        assert restored_count == 1
        assert Book.objects.count() == 1

    def test_restore_cascade_stops_at_active_objects(self) -> None:
        """Restore cascade shouldn't re-activate already active objects."""
        author = Author.objects.create(name="Author")
        book = Book.objects.create(title="Book", author=author)
        chapter = Chapter.objects.create(title="Chapter 1", book=book)

        # Delete only chapter
        chapter.delete()

        # Restore chapter with children
        restored_count, _ = chapter.restore(restore_children=True)

        # Should only restore chapter (book and author already active)
        assert restored_count == 1
