"""Comprehensive tests for restore() functionality."""

import pytest

from softdelete import ROW_STATUS_ACTIVE, ROW_STATUS_DELETE

from .factories import (
    AuthorFactory,
    BookFactory,
    ChapterFactory,
    PageFactory,
    RestaurantFactory,
    WaiterFactory,
)
from .models import Author, Book, Chapter, Page, Place, Restaurant, Waiter


@pytest.mark.django_db
class TestBasicRestore:
    """Test basic restore() functionality for single objects."""

    def test_single_object_restore(self):
        """Restore a single soft-deleted object."""
        # Create and delete an author.
        author = AuthorFactory()
        author_pk = author.pk
        author.delete()

        # Verify deletion.
        author.refresh_from_db()
        assert author.row_status == ROW_STATUS_DELETE

        # Restore the author.
        restored_count, restored_models = author.restore()

        # Verify restoration.
        assert restored_count == 1
        assert "tests.Author" in restored_models
        assert restored_models["tests.Author"] == 1

        author.refresh_from_db()
        assert author.row_status == ROW_STATUS_ACTIVE

        # Verify author is visible via default manager.
        assert Author.objects.filter(pk=author_pk).exists()

    def test_restore_already_active_object(self):
        """Restoring an already active object is idempotent."""
        # Create an active author.
        author = AuthorFactory()
        assert author.row_status == ROW_STATUS_ACTIVE

        # Attempt to restore an already active object.
        restored_count, restored_models = author.restore()

        # Should return zero updates.
        assert restored_count == 0
        assert restored_models == {}

        # Object should remain active.
        author.refresh_from_db()
        assert author.row_status == ROW_STATUS_ACTIVE

    def test_restore_updates_update_date(self):
        """Restore updates the update_date timestamp."""
        # Create and delete an author.
        author = AuthorFactory()
        author.delete()

        author.refresh_from_db()
        original_update_date = author.update_date

        # Restore the author.
        author.restore()

        # Reload from database.
        author.refresh_from_db()

        # update_date should have advanced.
        assert author.update_date > original_update_date

    def test_restore_returns_correct_format(self):
        """restore() returns a (count, model_dict) tuple."""
        author = AuthorFactory()
        author.delete()

        result = author.restore()

        # The outer type is a 2-tuple.
        assert isinstance(result, tuple)
        assert len(result) == 2

        # Containing an int and a dict.
        restored_count, restored_models = result
        assert isinstance(restored_count, int)
        assert isinstance(restored_models, dict)


@pytest.mark.django_db
class TestCascadeRestore:
    """Test cascade restore for multi-level relationships."""

    def test_restore_with_two_level_cascade(self):
        """Restore author cascades to restore books."""
        # Create author with books.
        author = AuthorFactory()
        book1 = BookFactory(author=author)
        book2 = BookFactory(author=author)

        # Delete author (cascades to books).
        author.delete()

        # Verify all are deleted.
        author.refresh_from_db()
        book1.refresh_from_db()
        book2.refresh_from_db()

        assert author.row_status == ROW_STATUS_DELETE
        assert book1.row_status == ROW_STATUS_DELETE
        assert book2.row_status == ROW_STATUS_DELETE

        # Restore author (should restore books).
        restored_count, restored_models = author.restore()

        # Verify restoration counts.
        assert restored_count == 3
        assert "tests.Author" in restored_models
        assert "tests.Book" in restored_models
        assert restored_models["tests.Author"] == 1
        assert restored_models["tests.Book"] == 2

        # Verify all objects are active.
        author.refresh_from_db()
        book1.refresh_from_db()
        book2.refresh_from_db()

        assert author.row_status == ROW_STATUS_ACTIVE
        assert book1.row_status == ROW_STATUS_ACTIVE
        assert book2.row_status == ROW_STATUS_ACTIVE

    def test_restore_with_three_level_cascade(self):
        """Restore author cascades through books to chapters."""
        # Create 3-level hierarchy.
        author = AuthorFactory()
        book = BookFactory(author=author)
        chapter1 = ChapterFactory(book=book)
        chapter2 = ChapterFactory(book=book)

        # Delete author (cascades through all levels).
        author.delete()

        # Verify all are deleted.
        author.refresh_from_db()
        book.refresh_from_db()
        chapter1.refresh_from_db()
        chapter2.refresh_from_db()

        assert author.row_status == ROW_STATUS_DELETE
        assert book.row_status == ROW_STATUS_DELETE
        assert chapter1.row_status == ROW_STATUS_DELETE
        assert chapter2.row_status == ROW_STATUS_DELETE

        # Restore author (should restore entire tree).
        restored_count, restored_models = author.restore()

        # Verify restoration counts.
        assert restored_count == 4
        assert restored_models["tests.Author"] == 1
        assert restored_models["tests.Book"] == 1
        assert restored_models["tests.Chapter"] == 2

        # Verify all objects are active.
        author.refresh_from_db()
        book.refresh_from_db()
        chapter1.refresh_from_db()
        chapter2.refresh_from_db()

        assert author.row_status == ROW_STATUS_ACTIVE
        assert book.row_status == ROW_STATUS_ACTIVE
        assert chapter1.row_status == ROW_STATUS_ACTIVE
        assert chapter2.row_status == ROW_STATUS_ACTIVE

    def test_restore_with_four_level_cascade(self):
        """Restore author cascades through books, chapters, to pages."""
        # Create 4-level hierarchy.
        author = AuthorFactory()
        book = BookFactory(author=author)
        chapter = ChapterFactory(book=book)
        page1 = PageFactory(chapter=chapter)
        page2 = PageFactory(chapter=chapter)
        page3 = PageFactory(chapter=chapter)

        # Delete author (cascades through all 4 levels).
        author.delete()

        # Verify all are deleted.
        for obj in [author, book, chapter, page1, page2, page3]:
            obj.refresh_from_db()
            assert obj.row_status == ROW_STATUS_DELETE

        # Restore author (should restore entire tree).
        restored_count, restored_models = author.restore()

        # Verify restoration counts.
        assert restored_count == 6
        assert restored_models["tests.Author"] == 1
        assert restored_models["tests.Book"] == 1
        assert restored_models["tests.Chapter"] == 1
        assert restored_models["tests.Page"] == 3

        # Verify all objects are active.
        for obj in [author, book, chapter, page1, page2, page3]:
            obj.refresh_from_db()
            assert obj.row_status == ROW_STATUS_ACTIVE


@pytest.mark.django_db
class TestRestoreWithoutChildren:
    """Test restore_children=False parameter."""

    def test_restore_without_children_single_object(self):
        """restore_children=False only restores the target object."""
        # Create author with books.
        author = AuthorFactory()
        book1 = BookFactory(author=author)
        book2 = BookFactory(author=author)

        # Delete author (cascades to books).
        author.delete()

        # Verify all are deleted.
        author.refresh_from_db()
        book1.refresh_from_db()
        book2.refresh_from_db()

        assert author.row_status == ROW_STATUS_DELETE
        assert book1.row_status == ROW_STATUS_DELETE
        assert book2.row_status == ROW_STATUS_DELETE

        # Restore author without children.
        restored_count, restored_models = author.restore(restore_children=False)

        # Only author should be restored.
        assert restored_count == 1
        assert "tests.Author" in restored_models
        assert "tests.Book" not in restored_models
        assert restored_models["tests.Author"] == 1

        # Verify author is active, books remain deleted.
        author.refresh_from_db()
        book1.refresh_from_db()
        book2.refresh_from_db()

        assert author.row_status == ROW_STATUS_ACTIVE
        assert book1.row_status == ROW_STATUS_DELETE
        assert book2.row_status == ROW_STATUS_DELETE

    def test_restore_without_children_multi_level(self):
        """restore_children=False on middle object doesn't restore descendants."""
        # Create 3-level hierarchy.
        author = AuthorFactory()
        book = BookFactory(author=author)
        chapter1 = ChapterFactory(book=book)
        chapter2 = ChapterFactory(book=book)

        # Delete author (cascades through all).
        author.delete()

        # Verify all are deleted.
        for obj in [author, book, chapter1, chapter2]:
            obj.refresh_from_db()
            assert obj.row_status == ROW_STATUS_DELETE

        # Restore book without children.
        restored_count, restored_models = book.restore(restore_children=False)

        # Only book and its parent (author) should be restored.
        # Parent models are always restored due to multi-table inheritance logic.
        assert restored_count == 2
        assert "tests.Book" in restored_models
        assert "tests.Author" in restored_models
        assert "tests.Chapter" not in restored_models

        # Verify book and author are active, chapters remain deleted.
        author.refresh_from_db()
        book.refresh_from_db()
        chapter1.refresh_from_db()
        chapter2.refresh_from_db()

        assert author.row_status == ROW_STATUS_ACTIVE
        assert book.row_status == ROW_STATUS_ACTIVE
        assert chapter1.row_status == ROW_STATUS_DELETE
        assert chapter2.row_status == ROW_STATUS_DELETE


@pytest.mark.django_db
class TestPartialRestore:
    """Test restoring partially deleted hierarchies."""

    def test_restore_child_when_parent_active(self):
        """Restore child object when parent is still active."""
        # Create author with books.
        author = AuthorFactory()
        book1 = BookFactory(author=author)
        book2 = BookFactory(author=author)

        # Delete only one book (not cascade from author).
        book1.delete()

        # Verify states.
        author.refresh_from_db()
        book1.refresh_from_db()
        book2.refresh_from_db()

        assert author.row_status == ROW_STATUS_ACTIVE
        assert book1.row_status == ROW_STATUS_DELETE
        assert book2.row_status == ROW_STATUS_ACTIVE

        # Restore the deleted book.
        restored_count, restored_models = book1.restore()

        # Only book1 should be restored.
        assert restored_count == 1
        assert restored_models["tests.Book"] == 1

        # Verify all are now active.
        author.refresh_from_db()
        book1.refresh_from_db()
        book2.refresh_from_db()

        assert author.row_status == ROW_STATUS_ACTIVE
        assert book1.row_status == ROW_STATUS_ACTIVE
        assert book2.row_status == ROW_STATUS_ACTIVE

    def test_restore_middle_level_restores_parents(self):
        """Restoring a middle-level object also restores parents."""
        # Create 3-level hierarchy.
        author = AuthorFactory()
        book = BookFactory(author=author)
        chapter = ChapterFactory(book=book)

        # Delete author (cascades through all).
        author.delete()

        # Verify all are deleted.
        for obj in [author, book, chapter]:
            obj.refresh_from_db()
            assert obj.row_status == ROW_STATUS_DELETE

        # Restore chapter (should restore parents).
        restored_count, restored_models = chapter.restore()

        # All should be restored.
        assert restored_count == 3

        # Verify all are active.
        author.refresh_from_db()
        book.refresh_from_db()
        chapter.refresh_from_db()

        assert author.row_status == ROW_STATUS_ACTIVE
        assert book.row_status == ROW_STATUS_ACTIVE
        assert chapter.row_status == ROW_STATUS_ACTIVE


@pytest.mark.django_db
class TestQuerySetRestore:
    """Test QuerySet.restore() method."""

    def test_queryset_restore_multiple_objects(self):
        """QuerySet.restore() restores multiple objects."""
        # Create multiple authors.
        author1 = AuthorFactory()
        author2 = AuthorFactory()
        author3 = AuthorFactory()

        # Delete all authors.
        author1.delete()
        author2.delete()
        author3.delete()

        # Verify all are deleted.
        assert Author.objects.count() == 0
        assert Author.all_objects.filter(row_status=ROW_STATUS_DELETE).count() == 3

        # Restore all deleted authors via queryset.
        deleted_authors = Author.all_objects.deleted()
        restored_count, restored_models = deleted_authors.restore(
            restore_children=False
        )

        # Verify restoration.
        assert restored_count == 3
        assert restored_models["tests.Author"] == 3

        # All should now be visible via default manager.
        assert Author.objects.count() == 3

    def test_queryset_restore_with_cascade(self):
        """QuerySet.restore() with cascade restores children."""
        # Create authors with books.
        author1 = AuthorFactory()
        book1 = BookFactory(author=author1)
        book2 = BookFactory(author=author1)

        author2 = AuthorFactory()
        book3 = BookFactory(author=author2)

        # Delete both authors (cascades to books).
        author1.delete()
        author2.delete()

        # Verify all are deleted.
        assert Author.objects.count() == 0
        assert Book.objects.count() == 0

        # Restore all authors via queryset with cascade.
        deleted_authors = Author.all_objects.deleted()
        restored_count, restored_models = deleted_authors.restore(restore_children=True)

        # Verify restoration.
        assert restored_count == 5  # 2 authors + 3 books
        assert restored_models["tests.Author"] == 2
        assert restored_models["tests.Book"] == 3

        # All should be visible.
        assert Author.objects.count() == 2
        assert Book.objects.count() == 3

    def test_queryset_restore_without_children(self):
        """QuerySet.restore() with restore_children=False."""
        # Create authors with books.
        author1 = AuthorFactory()
        book1 = BookFactory(author=author1)

        author2 = AuthorFactory()
        book2 = BookFactory(author=author2)

        # Delete both authors.
        author1.delete()
        author2.delete()

        # Restore authors without children.
        deleted_authors = Author.all_objects.deleted()
        restored_count, restored_models = deleted_authors.restore(
            restore_children=False
        )

        # Only authors should be restored.
        assert restored_count == 2
        assert "tests.Author" in restored_models
        assert "tests.Book" not in restored_models

        # Authors visible, books still deleted.
        assert Author.objects.count() == 2
        assert Book.objects.count() == 0


@pytest.mark.django_db
class TestMultiTableInheritanceRestore:
    """Test restore() with multi-table inheritance."""

    def test_restore_child_restores_parent(self):
        """Restoring a child also restores its parent."""
        # Create and delete a restaurant.
        restaurant = RestaurantFactory()
        place_pk = restaurant.place_ptr_id

        restaurant.delete()

        # Verify both are deleted.
        restaurant.refresh_from_db()
        place = Place.all_objects.get(pk=place_pk)

        assert restaurant.row_status == ROW_STATUS_DELETE
        assert place.row_status == ROW_STATUS_DELETE

        # Restore restaurant (should restore place).
        restored_count, restored_models = restaurant.restore()

        # Both should be restored.
        assert restored_count == 2
        assert "tests.Restaurant" in restored_models
        assert "tests.Place" in restored_models

        # Verify both are active.
        restaurant.refresh_from_db()
        place = Place.all_objects.get(pk=place_pk)

        assert restaurant.row_status == ROW_STATUS_ACTIVE
        assert place.row_status == ROW_STATUS_ACTIVE

    def test_restore_with_cascade_and_inheritance(self):
        """Restore with both cascade and multi-table inheritance."""
        # Create restaurant with waiters.
        restaurant = RestaurantFactory()
        waiter1 = WaiterFactory(restaurant=restaurant)
        waiter2 = WaiterFactory(restaurant=restaurant)
        place_pk = restaurant.place_ptr_id

        # Delete restaurant (cascades to waiters, includes parent).
        restaurant.delete()

        # Verify all are deleted.
        restaurant.refresh_from_db()
        place = Place.all_objects.get(pk=place_pk)
        waiter1.refresh_from_db()
        waiter2.refresh_from_db()

        for obj in [restaurant, place, waiter1, waiter2]:
            assert obj.row_status == ROW_STATUS_DELETE

        # Restore restaurant.
        restored_count, restored_models = restaurant.restore()

        # All should be restored (restaurant + place + 2 waiters).
        assert restored_count == 4
        assert restored_models["tests.Restaurant"] == 1
        assert restored_models["tests.Place"] == 1
        assert restored_models["tests.Waiter"] == 2

        # Verify all are active.
        restaurant.refresh_from_db()
        place = Place.all_objects.get(pk=place_pk)
        waiter1.refresh_from_db()
        waiter2.refresh_from_db()

        for obj in [restaurant, place, waiter1, waiter2]:
            assert obj.row_status == ROW_STATUS_ACTIVE


@pytest.mark.django_db
class TestRestoreIdempotency:
    """Test that restore is idempotent and handles edge cases."""

    def test_restore_twice_is_idempotent(self):
        """Calling restore() twice has no side effects."""
        # Create and delete author with books.
        author = AuthorFactory()
        book = BookFactory(author=author)

        author.delete()

        # First restore.
        count1, models1 = author.restore()
        assert count1 == 2

        # Second restore should be no-op.
        count2, models2 = author.restore()
        assert count2 == 0
        assert models2 == {}

        # Objects should remain active.
        author.refresh_from_db()
        book.refresh_from_db()

        assert author.row_status == ROW_STATUS_ACTIVE
        assert book.row_status == ROW_STATUS_ACTIVE

    def test_restore_mixed_states(self):
        """Restore handles mixed active/deleted states gracefully."""
        # Create author with books.
        author = AuthorFactory()
        book1 = BookFactory(author=author)
        book2 = BookFactory(author=author)

        # Delete entire tree.
        author.delete()

        # Manually restore one book.
        Book.all_objects.filter(pk=book1.pk).update(row_status=ROW_STATUS_ACTIVE)

        # Restore author (book1 already active, book2 deleted).
        restored_count, restored_models = author.restore()

        # Should restore author and book2 (book1 already active).
        # Due to idempotency, book1 won't be counted but will remain active.
        assert restored_count == 2
        assert restored_models["tests.Author"] == 1
        assert restored_models["tests.Book"] == 1

        # All should be active.
        author.refresh_from_db()
        book1.refresh_from_db()
        book2.refresh_from_db()

        assert author.row_status == ROW_STATUS_ACTIVE
        assert book1.row_status == ROW_STATUS_ACTIVE
        assert book2.row_status == ROW_STATUS_ACTIVE
