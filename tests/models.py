"""Test models used across django-softdelete-cascade suites."""

from django.db import models

from softdelete import SoftDeleteModel


class Author(SoftDeleteModel):
    """Author model."""

    name = models.CharField(max_length=255)

    class Meta:
        app_label = 'tests'

    def __str__(self):
        return self.name


class Book(SoftDeleteModel):
    """Book model linked to an author."""

    title = models.CharField(max_length=255)
    author = models.ForeignKey(
        Author, on_delete=models.CASCADE, related_name='books'
    )

    class Meta:
        app_label = 'tests'

    def __str__(self):
        return self.title


class Chapter(SoftDeleteModel):
    """Chapter model linked to a book."""

    title = models.CharField(max_length=255)
    book = models.ForeignKey(
        Book, on_delete=models.CASCADE, related_name='chapters'
    )

    class Meta:
        app_label = 'tests'

    def __str__(self):
        return self.title


class Page(SoftDeleteModel):
    """Page model linked to a chapter."""

    number = models.IntegerField()
    chapter = models.ForeignKey(
        Chapter, on_delete=models.CASCADE, related_name='pages'
    )

    class Meta:
        app_label = 'tests'

    def __str__(self):
        return f'Page {self.number}'


class Publisher(SoftDeleteModel):
    """Publisher protected by PROTECT relations."""

    name = models.CharField(max_length=255)

    class Meta:
        app_label = 'tests'

    def __str__(self):
        return self.name


class ProtectedBook(SoftDeleteModel):
    """Book referencing a publisher via PROTECT."""

    title = models.CharField(max_length=255)
    publisher = models.ForeignKey(
        Publisher, on_delete=models.PROTECT, related_name='protected_books'
    )

    class Meta:
        app_label = 'tests'

    def __str__(self):
        return self.title


class Category(SoftDeleteModel):
    """Category guarded by RESTRICT relations."""

    name = models.CharField(max_length=255)

    class Meta:
        app_label = 'tests'

    def __str__(self):
        return self.name


class RestrictedBook(SoftDeleteModel):
    """Book referencing a category via RESTRICT."""

    title = models.CharField(max_length=255)
    category = models.ForeignKey(
        Category, on_delete=models.RESTRICT, related_name='restricted_books'
    )

    class Meta:
        app_label = 'tests'

    def __str__(self):
        return self.title


# Models for multi-table inheritance scenarios.


class Place(SoftDeleteModel):
    """Base place model."""

    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)

    class Meta:
        app_label = 'tests'

    def __str__(self):
        return self.name


class Restaurant(Place):
    """Restaurant that inherits from Place."""

    cuisine = models.CharField(max_length=100)
    rating = models.IntegerField(default=0)

    class Meta:
        app_label = 'tests'

    def __str__(self):
        return f'{self.name} - {self.cuisine}'


class Waiter(SoftDeleteModel):
    """Waiter linked to a restaurant."""

    name = models.CharField(max_length=255)
    restaurant = models.ForeignKey(
        Restaurant, on_delete=models.CASCADE, related_name='waiters'
    )

    class Meta:
        app_label = 'tests'

    def __str__(self):
        return self.name
