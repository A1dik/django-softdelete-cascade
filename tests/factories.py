"""Factory Boy factories for integration tests."""

import factory
from factory.django import DjangoModelFactory

from softdelete import ROW_STATUS_ACTIVE

from .models import (
    Author,
    Book,
    Category,
    Chapter,
    Page,
    Place,
    ProtectedBook,
    Publisher,
    Restaurant,
    RestrictedBook,
    Waiter,
)


class AuthorFactory(DjangoModelFactory):
    """Factory for ``Author`` instances."""

    class Meta:
        model = Author

    name = factory.Sequence(lambda n: f'Author {n}')
    row_status = ROW_STATUS_ACTIVE


class BookFactory(DjangoModelFactory):
    """Factory for ``Book`` instances."""

    class Meta:
        model = Book

    title = factory.Sequence(lambda n: f'Book {n}')
    author = factory.SubFactory(AuthorFactory)
    row_status = ROW_STATUS_ACTIVE


class ChapterFactory(DjangoModelFactory):
    """Factory for ``Chapter`` instances."""

    class Meta:
        model = Chapter

    title = factory.Sequence(lambda n: f'Chapter {n}')
    book = factory.SubFactory(BookFactory)
    row_status = ROW_STATUS_ACTIVE


class PageFactory(DjangoModelFactory):
    """Factory for ``Page`` instances."""

    class Meta:
        model = Page

    number = factory.Sequence(lambda n: n)
    chapter = factory.SubFactory(ChapterFactory)
    row_status = ROW_STATUS_ACTIVE


class PublisherFactory(DjangoModelFactory):
    """Factory for ``Publisher`` instances."""

    class Meta:
        model = Publisher

    name = factory.Sequence(lambda n: f'Publisher {n}')
    row_status = ROW_STATUS_ACTIVE


class ProtectedBookFactory(DjangoModelFactory):
    """Factory for books protected by PROTECT relations."""

    class Meta:
        model = ProtectedBook

    title = factory.Sequence(lambda n: f'Protected Book {n}')
    publisher = factory.SubFactory(PublisherFactory)
    row_status = ROW_STATUS_ACTIVE


class CategoryFactory(DjangoModelFactory):
    """Factory for ``Category`` instances."""

    class Meta:
        model = Category

    name = factory.Sequence(lambda n: f'Category {n}')
    row_status = ROW_STATUS_ACTIVE


class RestrictedBookFactory(DjangoModelFactory):
    """Factory for books guarded by RESTRICT relations."""

    class Meta:
        model = RestrictedBook

    title = factory.Sequence(lambda n: f'Restricted Book {n}')
    category = factory.SubFactory(CategoryFactory)
    row_status = ROW_STATUS_ACTIVE


class PlaceFactory(DjangoModelFactory):
    """Factory for ``Place`` instances."""

    class Meta:
        model = Place

    name = factory.Sequence(lambda n: f'Place {n}')
    address = factory.Sequence(lambda n: f'{n} Main Street')
    row_status = ROW_STATUS_ACTIVE


class RestaurantFactory(DjangoModelFactory):
    """Factory for ``Restaurant`` instances."""

    class Meta:
        model = Restaurant

    name = factory.Sequence(lambda n: f'Restaurant {n}')
    address = factory.Sequence(lambda n: f'{n} Restaurant Avenue')
    cuisine = factory.Iterator(['Italian', 'Japanese', 'French', 'Chinese'])
    rating = factory.Faker('random_int', min=1, max=5)
    row_status = ROW_STATUS_ACTIVE


class WaiterFactory(DjangoModelFactory):
    """Factory for ``Waiter`` instances."""

    class Meta:
        model = Waiter

    name = factory.Sequence(lambda n: f'Waiter {n}')
    restaurant = factory.SubFactory(RestaurantFactory)
    row_status = ROW_STATUS_ACTIVE
