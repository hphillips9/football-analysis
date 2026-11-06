"""
Tests for the per-competition run loop: one competition failing leaves
the others completing, and run_status.json is written every run.

    python tests/test_run_week.py     (or pytest tests/)
"""

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import run_week
from run_status import RunStatus

DIVS = ["E0", "SP1"]


class _Fakes:
    """Stand-ins for every step run_week calls. SP1 hits an unknown team
    name in each per-competition step; E0 always works."""

    def __init__(self):
        self.calls = []
        self.bets_added = {}

    def fetch_all_new_results(self, divs, status):
        for div in divs:
            if div == "SP1":
                try:
                    raise ValueError("Unrecognised team name(s) in new results: ['Real Mardid']")
                except ValueError as exc:
                    status.fail(div, exc, results="failed")
            else:
                status.set(div, results="ok")

    def fetch_european_results(self, status):
        # FotMob down for the CL: its cache is used, the run carries on
        try:
            raise ConnectionError("fotmob.com unreachable")
        except ConnectionError as exc:
            status.fail("CL", exc, results="stale")
        status.set("EL", results="ok")
        status.set("ECL", results="ok")

    def complete_bets(self, divs):
        self.calls.append("complete_bets")

    def build_dataset(self, divs, refresh_current, verbose, status):
        for div in divs:
            if div == "SP1":
                try:
                    raise ValueError("Unknown team name(s) from football-data.co.uk: ['Real Mardid']")
                except ValueError as exc:
                    status.fail(div, exc, xg="failed")
            else:
                status.set(div, xg="ok")

    def backfill(self):
        self.calls.append("backfill")

    def api_key(self):
        return "key"

    def fetch_next_fixtures(self, divs, status):
        return pd.DataFrame({
            "Gameweek": [11, 11, 12],
            "Div": ["E0", "E0", "SP1"],
            "Date": ["08/11/2026"] * 3,
            "Time": ["15:00"] * 3,
            "HomeTeam": ["Arsenal", "Chelsea", "Real Mardid"],
            "AwayTeam": ["Everton", "Fulham", "Getafe"],
        })

    def load_model(self):
        return "trained"

    def predict_round(self, fixtures, trained):
        if (fixtures["Div"] == "SP1").any():
            raise ValueError("Unknown team name(s) from Future_Fixtures.csv: ['Real Mardid']")
        return fixtures.assign(Prediction="H", HomeProb=50.0, DrawProb=25.0, AwayProb=25.0)

    def add_bets(self, predictions):
        div = predictions["Div"].iloc[0]
        self.bets_added[div] = len(predictions)
        return len(predictions)

    def print_predictions(self, results):
        pass

    def export_web(self, status=None):
        self.calls.append("export_web")


def _run(fakes, **kwargs):
    """
    run_week with every step faked and the status file in a temp dir.
    Returns (the run_status.json written, the exception raised or None).
    """

    names = [
        "fetch_all_new_results", "fetch_european_results", "complete_bets", "build_dataset", "backfill",
        "api_key", "fetch_next_fixtures", "load_model", "predict_round",
        "add_bets", "print_predictions", "export_web",
    ]
    saved = {name: getattr(run_week, name) for name in names}
    saved_default = RunStatus.write.__defaults__

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "run_status.json"
        RunStatus.write.__defaults__ = (path,)
        error = None

        try:
            for name in names:
                setattr(run_week, name, getattr(fakes, name))
            run_week.run_week(divs=DIVS, **kwargs)
        except Exception as exc:
            error = exc
        finally:
            for name, value in saved.items():
                setattr(run_week, name, value)
            RunStatus.write.__defaults__ = saved_default

        written = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    return written, error


def test_one_league_failing_leaves_the_others_completing():
    fakes = _Fakes()

    status, error = _run(fakes)

    assert error is None
    assert status["E0"] == {"results": "ok", "xg": "ok", "predicted": 2, "error": None}

    assert status["SP1"]["results"] == "failed"
    assert status["SP1"]["xg"] == "failed"
    assert status["SP1"]["predicted"] == 0
    # Every step's error is kept, not just the last
    assert status["SP1"]["error"].count("Real Mardid") == 3

    assert fakes.bets_added == {"E0": 2}
    assert fakes.calls == ["complete_bets", "backfill", "export_web"]

    # A European outage is recorded, not fatal
    assert status["CL"]["results"] == "stale" and "unreachable" in status["CL"]["error"]
    assert status["EL"]["results"] == "ok"


def test_status_is_written_even_when_a_shared_step_fails():
    fakes = _Fakes()

    def broken_export(status=None):
        raise OSError("disk full")

    fakes.export_web = broken_export

    status, error = _run(fakes, predict=False)

    assert isinstance(error, OSError)
    assert status["E0"] == {"results": "ok", "xg": "ok", "predicted": 0, "error": None}
    assert status["SP1"]["results"] == "failed"


def test_run_status_records_and_joins_errors():
    status = RunStatus(["E0"])

    for message in ["first", "second"]:
        try:
            raise ConnectionError(message)
        except ConnectionError as exc:
            status.fail("E0", exc, results="stale")

    assert status.competitions["E0"]["results"] == "stale"
    assert status.competitions["E0"]["error"] == "ConnectionError: first; ConnectionError: second"
    assert status.failed() == ["E0"]


if __name__ == "__main__":
    for name, test in list(globals().items()):
        if name.startswith("test_"):
            test()
            print(f"ok  {name}")
