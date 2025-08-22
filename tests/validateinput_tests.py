"""
Unit tests for data_loader.py input parsing and validation.
"""
import unittest
import os
from datetime import datetime
from typing import List

from data_loader import *
from input_Validations import *
from prod_allocation import *
from domain_types import Plant, Order, Item  # TypedDicts for static typing (Pylance)

TEST_PLANTS = os.path.join(os.path.dirname(__file__), 'plants-info-1.json')
TEST_ORDERS = os.path.join(os.path.dirname(__file__), 'to_be_allocated-1.json')

import tempfile

class TestDataLoader(unittest.TestCase):
    def test_load_plants_valid(self):
        plants = load_plants(TEST_PLANTS)
        self.assertIsInstance(plants, list)
        self.assertGreater(len(plants), 0)
        for plant in plants:
            self.assertIn('plantid', plant)
            self.assertIn('allowedModels', plant)
            self.assertIsInstance(plant['allowedModels'], list)
            self.assertGreaterEqual(len(plant['allowedModels']), 1)

    def test_load_orders_valid(self):
        orders = load_orders(TEST_ORDERS)
        self.assertIsInstance(orders, list)
        self.assertGreater(len(orders), 0)
        for order in orders:
            self.assertIn('order', order)
            self.assertIn('dueDate', order)
            self.assertIn('items', order)
            self.assertIsInstance(order['items'], list)
            self.assertGreaterEqual(len(order['items']), 1)

    def test_load_plants_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            load_plants('nonexistent.json')

    def test_load_orders_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            load_orders('nonexistent.json')

    def test_load_plants_not_list(self):
        with tempfile.NamedTemporaryFile('w+', delete=False, suffix='.json') as tf:
            tf.write('{"plantid": 1}')
            tf.flush()
            with self.assertRaises(ValueError):
                plants = load_plants(tf.name)
                validate_plants(plants)
        os.remove(tf.name)

    def test_load_plants_missing_fields(self):
        bad_data = '[{"plantid": 1, "capacity": 100, "allowedModels": ["model1"]}]'  # missing plantfamily
        with tempfile.NamedTemporaryFile('w+', delete=False, suffix='.json') as tf:
            tf.write(bad_data)
            tf.flush()
            with self.assertRaises(ValueError):
                plants = load_plants(tf.name)
                validate_plants(plants)
        os.remove(tf.name)

    def test_load_plants_empty_allowed_models(self):
        bad_data = '[{"plantid": 1, "plantfamily": "family1", "capacity": 100, "allowedModels": []}]'
        with tempfile.NamedTemporaryFile('w+', delete=False, suffix='.json') as tf:
            tf.write(bad_data)
            tf.flush()
            with self.assertRaises(ValueError):
                plants = load_plants(tf.name)
                validate_plants(plants)
        os.remove(tf.name)

    def test_load_orders_missing_orders_key(self):
        bad_data = '{"foo": []}'
        with tempfile.NamedTemporaryFile('w+', delete=False, suffix='.json') as tf:
            tf.write(bad_data)
            tf.flush()
            with self.assertRaises(ValueError):
                orders = load_orders(tf.name)
                validate_orders(orders)
        os.remove(tf.name)

    def test_load_orders_orders_not_list(self):
        bad_data = '{"orders": {}}'
        with tempfile.NamedTemporaryFile('w+', delete=False, suffix='.json') as tf:
            tf.write(bad_data)
            tf.flush()
            with self.assertRaises(ValueError):
                orders = load_orders(tf.name)
                validate_orders(orders)
        os.remove(tf.name)

    def test_load_orders_missing_order_fields(self):
        bad_data = '{"orders": [{"order": "1", "dueDate": "2023-10-15"}]}'  # missing items
        with tempfile.NamedTemporaryFile('w+', delete=False, suffix='.json') as tf:
            tf.write(bad_data)
            tf.flush()
            with self.assertRaises(ValueError):
                orders = load_orders(tf.name)
                validate_orders(orders)
        os.remove(tf.name)

    def test_load_orders_bad_due_date_format(self):
        bad_data = '{"orders": [{"order": "1", "dueDate": "15-10-2023", "items": []}]}'
        with tempfile.NamedTemporaryFile('w+', delete=False, suffix='.json') as tf:
            tf.write(bad_data)
            tf.flush()
            with self.assertRaises(ValueError):
                orders = load_orders(tf.name)
                validate_orders(orders)
        os.remove(tf.name)

    def test_load_orders_items_not_list(self):
        bad_data = '{"orders": [{"order": "1", "dueDate": "2023-10-15", "items": {}}]}'
        with tempfile.NamedTemporaryFile('w+', delete=False, suffix='.json') as tf:
            tf.write(bad_data)
            tf.flush()
            with self.assertRaises(ValueError):
                orders = load_orders(tf.name)
                validate_orders(orders)
        os.remove(tf.name)

    def test_load_orders_item_missing_fields(self):
        bad_data = '{"orders": [{"order": "1", "dueDate": "2023-10-15", "items": [{"modelFamily": "family1"}]}]}'
        with tempfile.NamedTemporaryFile('w+', delete=False, suffix='.json') as tf:
            tf.write(bad_data)
            tf.flush()
            with self.assertRaises(ValueError):
                orders = load_orders(tf.name)
                validate_orders(orders)
        os.remove(tf.name)

    def test_negative_quantity_validation(self) -> None:
        """Negative quantities should be rejected during validation.

        Pylance note: Explicit List[Plant] and List[Order] annotations ensure the
        call to allocate() matches its signature (List[Plant], List[Order], ...).
        """
        plants: List[Plant] = [
            {"plantid": 1, "plantfamily": "F1", "capacity": 100, "allowedModels": ["M1"]},
        ]
        # Create order with negative quantity to test validation
        items: List[Item] = [
            {"modelFamily": "F1", "model": "M1", "submodel": "S1", "quantity": -5},
        ]
        orders: List[Order] = [
            {
                "order": "O1",
                "dueDate": "2025-01-01",
                "items": items,
            }
        ]
        with self.assertRaises(ValueError) as context:
            settings: WeightsConfig = {"w_quantity": 5.0, "w_due": 1.0}
            validate_input_data(plants, orders, settings)

        self.assertIn("Item quantity must be >= 0", str(context.exception))
        self.assertIn("got -5", str(context.exception))

if __name__ == '__main__':
    unittest.main()
