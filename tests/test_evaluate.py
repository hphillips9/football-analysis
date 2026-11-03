"""
Tests for src/evaluate.py.

    python tests/test_evaluate.py     (or pytest tests/)
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from evaluate import (
    better,
    non_inferior,
    paired_bootstrap,
    per_match_log_loss,
    walk_forward,
)


def test_paired_bootstrap_is_deterministic():
    diff = np.random.default_rng(0).normal(-0.003, 0.05, size=1500)

    first = paired_bootstrap(diff)
    second = paired_bootstrap(diff)

    assert first == second
    assert first["mean"] == diff.mean()
    assert first["ci"][0] < first["mean"] < first["ci"][1]


def test_paired_bootstrap_matches_notebook_recipe():
    # nb 17/18: default_rng(42), one (5000, n) index draw, 2.5/97.5 percentiles
    diff = np.linspace(-0.2, 0.15, 400)

    rng = np.random.default_rng(42)
    boot = diff[rng.integers(0, len(diff), size=(5000, len(diff)))].mean(axis=1)

    result = paired_bootstrap(diff)

    assert result["ci"] == tuple(np.percentile(boot, [2.5, 97.5]))
    assert result["p_better"] == (boot < 0).mean()


def test_better_and_non_inferior():
    assert better((-0.004, -0.001))
    assert not better((-0.004, 0.0))
    assert non_inferior((-0.003, 0.0019))
    assert not non_inferior((-0.003, 0.002))
    assert non_inferior((-0.003, 0.004), margin=0.005)


def test_per_match_log_loss_labels_and_indices_agree():
    proba = np.array([[0.2, 0.3, 0.5], [0.6, 0.3, 0.1]])

    by_index = per_match_log_loss([2, 1], proba)
    by_label = per_match_log_loss(["H", "D"], proba, labels=["A", "D", "H"])

    assert np.allclose(by_index, -np.log([0.5, 0.3]))
    assert (by_index == by_label).all()


class _ClassRates:
    """Predicts the training class frequencies for every row."""

    def fit(self, X, y):
        counts = pd.Series(y).value_counts(normalize=True).sort_index()
        self.classes_ = counts.index.to_numpy()
        self.rates_ = counts.to_numpy()
        return self

    def predict_proba(self, X):
        return np.tile(self.rates_, (len(X), 1))


def test_walk_forward_trains_only_on_earlier_seasons():
    data = pd.DataFrame({
        "Season": ["21-22"] * 4 + ["22-23"] * 4 + ["23-24"] * 2,
        "Div": ["E0", "SP1"] * 5,
        "x": 0.0,
        "FTR": ["H", "H", "A", "D",  "D", "D", "H", "A",  "H", "A"],
    })

    proba = walk_forward(data, _ClassRates, ["x"], ["22-23", "23-24"])

    assert list(proba.index) == list(range(4, 10))
    assert list(proba.columns) == ["A", "D", "H"]
    assert np.allclose(proba.loc[4], [0.25, 0.25, 0.5])    # 21-22 only
    assert np.allclose(proba.loc[8], [0.25, 0.375, 0.375])  # 21-22 + 22-23

    per_league = walk_forward(
        data, _ClassRates, ["x"], ["22-23"], group_by="Div"
    )
    assert np.allclose(per_league.loc[4], [0.5, 0.0, 0.5])  # E0: H, A
    assert np.allclose(per_league.loc[5], [0.0, 0.5, 0.5])  # SP1: H, D


if __name__ == "__main__":
    for name, test in list(globals().items()):
        if name.startswith("test_"):
            test()
            print(f"ok  {name}")
