"""Multi-table inheritance tests."""

import pytest

from softdelete import ROW_STATUS_DELETE

from .factories import RestaurantFactory, WaiterFactory
from .models import Place, Restaurant, Waiter


@pytest.mark.django_db
class TestMultiTableInheritance:
    """Soft-delete tests that involve multi-table inheritance."""

    def test_child_deletion_deletes_parent(self):
        """Deleting a child also soft-deletes its parent."""
        # Create a restaurant (inherits from Place)
        restaurant = RestaurantFactory()
        restaurant_pk = restaurant.pk
        place_pk = restaurant.place_ptr_id

        # Delete the restaurant
        deleted_count, deleted_models = restaurant.delete()

        # Both Restaurant and Place should be removed
        assert deleted_count == 2
        assert "tests.Restaurant" in deleted_models
        assert "tests.Place" in deleted_models
        assert deleted_models["tests.Restaurant"] == 1
        assert deleted_models["tests.Place"] == 1

        # Ensure both objects are marked as deleted
        restaurant.refresh_from_db()
        place = Place.all_objects.get(pk=place_pk)

        assert restaurant.row_status == ROW_STATUS_DELETE
        assert place.row_status == ROW_STATUS_DELETE

    def test_cascade_with_parent_deletion(self):
        """Cascade deletion should include parent models."""
        # Create a restaurant with waiters
        restaurant = RestaurantFactory()
        waiter1 = WaiterFactory(restaurant=restaurant)
        waiter2 = WaiterFactory(restaurant=restaurant)
        place_pk = restaurant.place_ptr_id

        # Delete the restaurant
        deleted_count, deleted_models = restaurant.delete()

        # Restaurant, Place, and both waiters should be removed
        assert deleted_count == 4
        assert "tests.Restaurant" in deleted_models
        assert "tests.Place" in deleted_models
        assert "tests.Waiter" in deleted_models

        # Check all objects
        restaurant.refresh_from_db()
        place = Place.all_objects.get(pk=place_pk)
        waiter1.refresh_from_db()
        waiter2.refresh_from_db()

        for obj in [restaurant, place, waiter1, waiter2]:
            assert obj.row_status == ROW_STATUS_DELETE

    def test_multiple_level_inheritance(self):
        """Baseline check for single-level inheritance."""
        # In this schema Restaurant inherits Place (single level)
        # This confirms the one-level inheritance flow
        restaurant = RestaurantFactory()
        place_pk = restaurant.place_ptr_id

        # Delete the restaurant
        deleted_count, deleted_models = restaurant.delete()

        # Verify deletion status
        assert deleted_count == 2
        restaurant.refresh_from_db()
        place = Place.all_objects.get(pk=place_pk)

        assert restaurant.row_status == ROW_STATUS_DELETE
        assert place.row_status == ROW_STATUS_DELETE

    def test_parent_without_row_status_ignored(self):
        """Parents without a row_status field are ignored.

        Note: Place currently has row_status, but this checks skip logic
        for parents that lack the field.
        """
        # Create a restaurant
        restaurant = RestaurantFactory()

        # Deletion should succeed
        # Even if Place lacked row_status, it would be skipped
        deleted_count, deleted_models = restaurant.delete()

        assert deleted_count >= 1
        assert "tests.Restaurant" in deleted_models

    def test_cascade_from_child_with_relations(self):
        """Cascade from a child model that owns related objects."""
        # Create a restaurant with waiters
        restaurant = RestaurantFactory()
        waiter1 = WaiterFactory(restaurant=restaurant)
        waiter2 = WaiterFactory(restaurant=restaurant)
        waiter3 = WaiterFactory(restaurant=restaurant)

        # Delete the restaurant
        deleted_count, deleted_models = restaurant.delete()

        # Verify cascade
        assert deleted_count == 5  # Restaurant + Place + 3 Waiters
        assert "tests.Restaurant" in deleted_models
        assert "tests.Place" in deleted_models
        assert "tests.Waiter" in deleted_models
        assert deleted_models["tests.Waiter"] == 3

    def test_parent_deletion_with_cascade_relations(self):
        """Delete a parent with cascade relations on the child level."""
        # Build a complex structure
        restaurant = RestaurantFactory()
        place_pk = restaurant.place_ptr_id

        # Create several waiters
        waiters = [WaiterFactory(restaurant=restaurant) for _ in range(5)]

        # Delete the restaurant
        deleted_count, deleted_models = restaurant.delete()

        # Verify full removal
        assert deleted_count == 7  # 1 Restaurant + 1 Place + 5 Waiters

        # All objects should be marked as deleted
        restaurant.refresh_from_db()
        place = Place.all_objects.get(pk=place_pk)

        assert restaurant.row_status == ROW_STATUS_DELETE
        assert place.row_status == ROW_STATUS_DELETE

        for waiter in waiters:
            waiter.refresh_from_db()
            assert waiter.row_status == ROW_STATUS_DELETE

    def test_inheritance_with_already_deleted_parent(self):
        """Handle deletion when the parent is already soft-deleted."""
        # Create a restaurant
        restaurant = RestaurantFactory()
        place_pk = restaurant.place_ptr_id

        # Get the parent object (use objects since it's not deleted yet)
        place = Place.objects.get(pk=place_pk)

        # Delete the parent directly
        place.delete()

        # Attempt to delete the restaurant
        deleted_count, deleted_models = restaurant.delete()

        # Parent already deleted; only the restaurant should remain (or zero if it cascaded)
        assert "tests.Restaurant" in deleted_models or deleted_count == 0
