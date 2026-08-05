from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from typing import Any


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class OlistRepository:
    """Loads only the four tables required by the assessment workflow."""

    def __init__(self, data_dir: Path) -> None:
        self.orders = {
            row["order_id"]: row
            for row in _read_csv(data_dir / "olist_orders_dataset.csv")
        }
        self.items: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in _read_csv(data_dir / "olist_order_items_dataset.csv"):
            self.items[row["order_id"]].append(row)
        self.payments: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in _read_csv(data_dir / "olist_order_payments_dataset.csv"):
            self.payments[row["order_id"]].append(row)
        self.sellers = {
            row["seller_id"]: row
            for row in _read_csv(data_dir / "olist_sellers_dataset.csv")
        }

    def order(self, order_id: str) -> dict[str, Any]:
        if order_id not in self.orders:
            raise KeyError(f"Order not found: {order_id}")
        return dict(self.orders[order_id])

    def order_items(self, order_id: str) -> list[dict[str, Any]]:
        return [dict(row) for row in self.items.get(order_id, [])]

    def order_payments(self, order_id: str) -> list[dict[str, Any]]:
        return [dict(row) for row in self.payments.get(order_id, [])]

