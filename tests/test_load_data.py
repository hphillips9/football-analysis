"""
Tests for load_data's xG cascade and FotMob rate-limit handling.

    python tests/test_load_data.py     (or pytest tests/)
"""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import load_data
from load_data import XG_COLUMNS, merge_xg

ALIASES = {"Arsenal": "Arsenal", "Chelsea": "Chelsea", "Spurs": "Tottenham", "Tottenham": "Tottenham"}


def _matches():
    # Every row has football-data xG except the last
    return pd.DataFrame({
        "Div": "E0",
        "Season": "26-27",
        "HomeTeam": ["Arsenal", "Chelsea", "Tottenham", "Arsenal"],
        "AwayTeam": ["Chelsea", "Tottenham", "Arsenal", "Tottenham"],
        "HxG": [1.0, 2.0, 3.0, None],
        "AxG": [0.1, 0.2, 0.3, None],
    })


def _xg(rows):
    return pd.DataFrame(
        [("E0", "26-27", *row) for row in rows], columns=XG_COLUMNS
    )


def test_cascade_prefers_fotmob_then_football_data_then_understat():
    fotmob = _xg([("Arsenal", "Chelsea", 1.1, 0.15)])
    understat = _xg([
        ("Arsenal", "Chelsea", 9.0, 9.0),
        ("Chelsea", "Spurs", 9.0, 9.0),
        ("Arsenal", "Spurs", 1.4, 0.4),
    ])

    merged = merge_xg(_matches(), fotmob, understat, ALIASES)

    assert merged["XGSource"].tolist() == ["FotMob", "football-data", "football-data", "Understat"]
    assert merged["HomeXG"].tolist() == [1.1, 2.0, 3.0, 1.4]
    assert merged["AwayXG"].tolist() == [0.15, 0.2, 0.3, 0.4]
    # The raw football-data columns are kept as they were
    assert merged["HxG"].tolist()[:3] == [1.0, 2.0, 3.0]


def test_cascade_without_football_data_columns_or_any_source():
    matches = _matches().drop(columns=["HxG", "AxG"])
    empty = pd.DataFrame(columns=XG_COLUMNS)

    merged = merge_xg(matches, _xg([("Chelsea", "Tottenham", 1.0, 1.0)]), empty, ALIASES)

    assert merged["XGSource"].tolist() == [None, "FotMob", None, None]
    assert merged["HomeXG"].isna().tolist() == [True, False, True, True]


class _Response:

    def __init__(self, status_code):
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return {"ok": True}


class _Session:

    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        return _Response(self.statuses.pop(0))


def test_fotmob_backs_off_on_429_then_gives_up():
    waits = []
    sleep, load_data.time.sleep = load_data.time.sleep, waits.append

    try:
        session = _Session([429, 429, 200])
        assert load_data._fotmob_get(session, "leagues", {}) == {"ok": True}
        assert waits == [load_data.FOTMOB_BACKOFF, load_data.FOTMOB_BACKOFF * 2]

        waits.clear()
        session = _Session([429] * (load_data.FOTMOB_MAX_RETRIES + 1))
        try:
            load_data._fotmob_get(session, "leagues", {})
            raise AssertionError("expected the final 429 to raise")
        except RuntimeError:
            pass
        assert session.calls == load_data.FOTMOB_MAX_RETRIES + 1
        assert len(waits) == load_data.FOTMOB_MAX_RETRIES
    finally:
        load_data.time.sleep = sleep


if __name__ == "__main__":
    for name, test in list(globals().items()):
        if name.startswith("test_"):
            test()
            print(f"ok  {name}")
