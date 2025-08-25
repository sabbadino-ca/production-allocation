"""Unit tests for due date boost mapping via load_items_arrays.

This file validates the linear mapping implemented in input_loader._boost_for_due:
- 100 when due date is now - 100 days (overdue by 100)
- 50 when due date is today
- 0 when due date is now + 100 days (ahead by 100)
Values are clamped beyond +/-100 days.
"""
from __future__ import annotations

import json
import unittest
from datetime import date, timedelta
from pathlib import Path
from typing import List
import tempfile

from input_loader import load_items_arrays


def _write_items_file(due_dates: List[str]) -> tuple[Path, tempfile.TemporaryDirectory]:
    """Create a temporary items JSON file with the provided due dates.

    Each order will contain a single item with quantity=1. Returns the file path and the
    TemporaryDirectory context so the caller can keep it alive for the test's duration.
    """
    orders = []
    for i, d in enumerate(due_dates):
        orders.append(
            {
                "order": str(i + 1),
                "dueDate": d,
                "items": [
                    {
                        "modelFamily": "fam",
                        "model": "mod",
                        "submodel": "sub",
                        "quantity": 1,
                    }
                ],
            }
        )

    tmpdir = tempfile.TemporaryDirectory()
    p = Path(tmpdir.name) / "items.json"
    p.write_text(json.dumps({"orders": orders}), encoding="utf-8")
    return p, tmpdir


class TestDueDateBoost(unittest.TestCase):
    def test_linear_mapping_and_clamping(self) -> None:
        today = date.today()
        fmt = lambda d: d.strftime("%Y-%m-%d")
        dates = [
            fmt(today - timedelta(days=100)),  # expect 100
            fmt(today),                        # expect 50
            fmt(today + timedelta(days=100)),  # expect 0
            fmt(today - timedelta(days=150)),  # clamp -> 100
            fmt(today + timedelta(days=150)),  # clamp -> 0
        ]

        path, tmpctx = _write_items_file(dates)
        try:
            _, _, _, boosts = load_items_arrays(path)
            self.assertEqual(boosts, [100, 50, 0, 100, 0])
        finally:
            tmpctx.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)
