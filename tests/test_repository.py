from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
from src.repository.olist import OlistRepository


class TestOlistRepository(unittest.TestCase):
    def setUp(self) -> None:
        # Mock CSV contents
        self.mock_orders = [
            {"order_id": "order_1", "customer_id": "cust_1", "order_status": "delivered"},
            {"order_id": "order_2", "customer_id": "cust_2", "order_status": "canceled"},
        ]
        self.mock_items = [
            {"order_id": "order_1", "order_item_id": "2", "price": "50.0", "freight_value": "10.0", "seller_id": "seller_A"},
            {"order_id": "order_1", "order_item_id": "1", "price": "100.0", "freight_value": "15.0", "seller_id": "seller_A"},
            {"order_id": "order_2", "order_item_id": "1", "price": "200.0", "freight_value": "20.0", "seller_id": "seller_B"},
        ]
        self.mock_payments = [
            {"order_id": "order_1", "payment_sequential": "2", "payment_value": "65.0"},
            {"order_id": "order_1", "payment_sequential": "1", "payment_value": "110.0"},
        ]
        self.mock_sellers = [
            {"seller_id": "seller_A", "seller_zip_code_prefix": "12345"},
            {"seller_id": "seller_B", "seller_zip_code_prefix": "67890"},
        ]

        # Patch _read_csv to return our mocked CSV contents depending on path
        self.read_csv_patcher = patch("src.repository.olist._read_csv")
        self.mock_read_csv = self.read_csv_patcher.start()
        
        def side_effect(path: Path) -> list[dict[str, str]]:
            filename = path.name
            if filename == "olist_orders_dataset.csv":
                return self.mock_orders
            elif filename == "olist_order_items_dataset.csv":
                return self.mock_items
            elif filename == "olist_order_payments_dataset.csv":
                return self.mock_payments
            elif filename == "olist_sellers_dataset.csv":
                return self.mock_sellers
            return []

        self.mock_read_csv.side_effect = side_effect
        self.repo = OlistRepository(Path("/fake/data/dir"))

    def tearDown(self) -> None:
        self.read_csv_patcher.stop()

    def test_init_loads_data_correctly(self) -> None:
        self.assertEqual(len(self.repo.orders), 2)
        self.assertEqual(self.repo.orders["order_1"]["order_status"], "delivered")
        self.assertEqual(len(self.repo.items["order_1"]), 2)
        self.assertEqual(len(self.repo.items["order_2"]), 1)
        self.assertEqual(len(self.repo.payments["order_1"]), 2)
        self.assertEqual(len(self.repo.sellers), 2)

    def test_order_success(self) -> None:
        order = self.repo.order("order_1")
        self.assertEqual(order["customer_id"], "cust_1")
        # Ensure a copy is returned
        order["customer_id"] = "modified"
        self.assertEqual(self.repo.orders["order_1"]["customer_id"], "cust_1")

    def test_order_not_found(self) -> None:
        with self.assertRaises(KeyError):
            self.repo.order("non_existent")

    def test_order_items_sorted(self) -> None:
        items = self.repo.order_items("order_1")
        self.assertEqual(len(items), 2)
        # Check sorting by order_item_id (integer sorting: 1 comes before 2)
        self.assertEqual(items[0]["order_item_id"], "1")
        self.assertEqual(items[1]["order_item_id"], "2")

    def test_order_payments_sorted(self) -> None:
        payments = self.repo.order_payments("order_1")
        self.assertEqual(len(payments), 2)
        # Check sorting by payment_sequential
        self.assertEqual(payments[0]["payment_sequential"], "1")
        self.assertEqual(payments[1]["payment_sequential"], "2")


if __name__ == "__main__":
    unittest.main()
