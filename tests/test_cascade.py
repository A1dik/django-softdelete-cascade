"""Cascade soft-delete scenarios."""

import pytest

from softdelete import ROW_STATUS_DELETE

from .factories import AuthorFactory, BookFactory, ChapterFactory, PageFactory
from .models import Author, Book, Chapter, Page


@pytest.mark.django_db
class TestCascadeSoftDelete:
    """Ensure cascade traversal covers multi-level hierarchies."""

    def test_cascade_two_levels(self):
        """Cascade from author to books (two levels)."""
        # Create an author and three books
        author = AuthorFactory()
        book1 = BookFactory(author=author)
        book2 = BookFactory(author=author)
        book3 = BookFactory(author=author)

        # Delete the author
        deleted_count, deleted_models = author.delete()

        # Author plus three books are marked deleted
        assert deleted_count == 4  # 1 author + 3 books
        assert 'tests.Author' in deleted_models
        assert 'tests.Book' in deleted_models
        assert deleted_models['tests.Author'] == 1
        assert deleted_models['tests.Book'] == 3

        # All objects should now have delete status
        author.refresh_from_db()
        book1.refresh_from_db()
        book2.refresh_from_db()
        book3.refresh_from_db()

        assert author.row_status == ROW_STATUS_DELETE
        assert book1.row_status == ROW_STATUS_DELETE
        assert book2.row_status == ROW_STATUS_DELETE
        assert book3.row_status == ROW_STATUS_DELETE

    def test_cascade_three_levels(self):
        """Cascade across author -> book -> chapters."""
        # Build author with one book and two chapters
        author = AuthorFactory()
        book = BookFactory(author=author)
        chapter1 = ChapterFactory(book=book)
        chapter2 = ChapterFactory(book=book)

        # Delete the author
        deleted_count, deleted_models = author.delete()

        # Author, book, and both chapters are deleted
        assert deleted_count == 4  # 1 author + 1 book + 2 chapters
        assert 'tests.Author' in deleted_models
        assert 'tests.Book' in deleted_models
        assert 'tests.Chapter' in deleted_models

        # Verify statuses
        for obj in [author, book, chapter1, chapter2]:
            obj.refresh_from_db()
            assert obj.row_status == ROW_STATUS_DELETE

    def test_cascade_four_levels(self):
        """Cascade across author -> book -> chapter -> pages."""
        # Create a full depth chain
        author = AuthorFactory()
        book = BookFactory(author=author)
        chapter = ChapterFactory(book=book)
        page1 = PageFactory(chapter=chapter)
        page2 = PageFactory(chapter=chapter)
        page3 = PageFactory(chapter=chapter)

        # Delete the author and walk the tree
        deleted_count, deleted_models = author.delete()

        # Count includes all four levels
        assert deleted_count == 6  # 1 + 1 + 1 + 3
        assert 'tests.Author' in deleted_models
        assert 'tests.Book' in deleted_models
        assert 'tests.Chapter' in deleted_models
        assert 'tests.Page' in deleted_models

        # Everything should be marked deleted
        for obj in [author, book, chapter, page1, page2, page3]:
            obj.refresh_from_db()
            assert obj.row_status == ROW_STATUS_DELETE

    def test_cascade_complex_hierarchy(self):
        """Cascade handles uneven branch shapes."""
        # Create an author with uneven tree
        author = AuthorFactory()

        # Two books
        book1 = BookFactory(author=author)
        book2 = BookFactory(author=author)

        # Chapters for the first book
        chapter1_1 = ChapterFactory(book=book1)
        chapter1_2 = ChapterFactory(book=book1)

        # Chapter for the second book
        chapter2_1 = ChapterFactory(book=book2)

        # Pages for the first book's chapters
        page1_1_1 = PageFactory(chapter=chapter1_1)
        page1_1_2 = PageFactory(chapter=chapter1_1)
        page1_2_1 = PageFactory(chapter=chapter1_2)

        # Pages for the second book's chapter
        page2_1_1 = PageFactory(chapter=chapter2_1)

        # Delete the author
        deleted_count, deleted_models = author.delete()

        # Ensure every object in the tree is deleted
        assert deleted_count == 10  # 1 author + 2 books + 3 chapters + 4 pages

        # Verify status on all objects
        all_objects = [
            author,
            book1,
            book2,
            chapter1_1,
            chapter1_2,
            chapter2_1,
            page1_1_1,
            page1_1_2,
            page1_2_1,
            page2_1_1,
        ]

        for obj in all_objects:
            obj.refresh_from_db()
            assert obj.row_status == ROW_STATUS_DELETE

    def test_cascade_from_middle_level(self):
        """Cascade from a middle node should not delete parents."""
        # Build the chain
        author = AuthorFactory()
        book = BookFactory(author=author)
        chapter1 = ChapterFactory(book=book)
        chapter2 = ChapterFactory(book=book)
        page1 = PageFactory(chapter=chapter1)
        page2 = PageFactory(chapter=chapter2)

        # Delete the book (middle level)
        deleted_count, deleted_models = book.delete()

        # Book, chapters, and pages are deleted; author remains
        assert deleted_count == 5  # 1 book + 2 chapters + 2 pages
        assert 'tests.Book' in deleted_models
        assert 'tests.Chapter' in deleted_models
        assert 'tests.Page' in deleted_models

        # Author should stay active
        author.refresh_from_db()
        assert author.row_status != ROW_STATUS_DELETE

        # Deleted nodes should show delete status
        for obj in [book, chapter1, chapter2, page1, page2]:
            obj.refresh_from_db()
            assert obj.row_status == ROW_STATUS_DELETE

    def test_cascade_multiple_branches(self):
        """Cascade handles multiple sibling branches."""
        # Author with two books and nested pages
        author = AuthorFactory()

        # First branch
        book1 = BookFactory(author=author)
        chapter1 = ChapterFactory(book=book1)
        PageFactory(chapter=chapter1)
        PageFactory(chapter=chapter1)

        # Second branch
        book2 = BookFactory(author=author)
        chapter2 = ChapterFactory(book=book2)
        PageFactory(chapter=chapter2)

        # Delete the author
        deleted_count, deleted_models = author.delete()

        # All objects across branches are included
        assert deleted_count == 8  # 1 + 2 + 2 + 3

    def test_no_duplicate_deletion(self):
        """Objects already deleted should not be double counted."""
        # Create author and book
        author = AuthorFactory()
        book = BookFactory(author=author)

        # Delete the book first via its own delete
        book.delete()

        # Now delete the author
        deleted_count, deleted_models = author.delete()

        # Only the author should be counted this time
        assert deleted_count == 1
        assert 'tests.Author' in deleted_models
        assert deleted_models['tests.Author'] == 1
