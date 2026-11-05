"""
How each competition fared in the last pipeline run, written to
data/processed/run_status.json for the website's "data stale" badge:

    {"E0": {"results": "ok", "xg": "ok", "predicted": 10, "error": null}, ...}

    results    ok (fetched) | stale (couldn't update - the results already
               on file were used) | failed (needs fixing, e.g. an unknown
               team name)
    xg         ok (every match has xG) | partial | failed
    predicted  new bets added this run
    error      what went wrong, or null
"""

import json
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATUS_PATH = ROOT / "data" / "processed" / "run_status.json"


class RunStatus:

    def __init__(self, divs):

        self.competitions = {
            div: {"results": None, "xg": None, "predicted": 0, "error": None}
            for div in divs
        }

    def set(self, div, **fields):

        self.competitions.setdefault(
            div, {"results": None, "xg": None, "predicted": 0, "error": None}
        ).update(fields)

    def fail(self, div, exc, **fields):
        """Record ``exc`` against ``div`` (and any outcome fields), and
        print it - the run carries on with the other competitions."""

        self.set(div, **fields)

        message = f"{type(exc).__name__}: {exc}"
        previous = self.competitions[div]["error"]
        self.competitions[div]["error"] = f"{previous}; {message}" if previous else message

        print(f"{div}: FAILED - {message}")
        traceback.print_exc()

    def failed(self):
        """Divs that recorded an error this run."""

        return [div for div, s in self.competitions.items() if s["error"]]

    def write(self, path=STATUS_PATH):

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.competitions, indent=2) + "\n", encoding="utf-8")

        print(f"Saved {path}")
