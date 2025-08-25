import json
from datetime import date, timedelta
from os import path
from pathlib import Path
import tempfile
import unittest

from input_loader import load_items_arrays


class TestItemsLoaderDueDateBoosts(unittest.TestCase):
    def _make_items_file(self, due_dates: list[str]) -> Path:
        orders = []
        for i, d in enumerate(due_dates):
            orders.append({
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
            })

        tmpdir = tempfile.TemporaryDirectory()
        p = Path(tmpdir.name) / "items.json"
        p.write_text(json.dumps({"orders": orders}), encoding="utf-8")
        # Keep reference to directory to ensure it's not GC'd early
        self._tmpdir = tmpdir
        return p

    def test_due_date_boost_linear_mapping(self):
        today = date.today()
        fmt = lambda d: d.strftime("%Y-%m-%d")
        d_over_100 = fmt(today - timedelta(days=100))
        d_today = fmt(today)
        d_ahead_100 = fmt(today + timedelta(days=100))
        d_over_150 = fmt(today - timedelta(days=150))
        d_ahead_150 = fmt(today + timedelta(days=150))

        path = self._make_items_file([
            d_over_100,  # expect 100
            d_today,     # expect 50
            d_ahead_100, # expect 0
            d_over_150,  # clamp -> 100
            d_ahead_150, # clamp -> 0
        ])

        _, _, _, boosts, _ = load_items_arrays(path)
        self.assertEqual(boosts, [100, 50, 0, 100, 0])


if __name__ == "__main__":
    unittest.main()
