"""
Tests for the tie-progression probabilities (P6-02, plan §4B.9).

    python tests/test_tie_progression.py     (or pytest tests/)
"""

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tie_progression import (
    _hda,
    advance_probability,
    bootstrap_against_coin,
    brier,
    poisson_rates,
)


def test_poisson_rates_reproduce_the_probabilities():

    for p_home, p_away in [(0.45, 0.30), (0.70, 0.12), (0.20, 0.55)]:
        h, d, a = _hda(*poisson_rates(p_home, p_away))
        assert abs(h - p_home) < 1e-6 and abs(a - p_away) < 1e-6
        assert abs(h + d + a - 1) < 1e-6


def test_a_neutral_even_final_is_a_coin_flip():

    assert abs(advance_probability([(0.36, 0.28, 0.36)]) - 0.5) < 1e-6


def test_mirrored_legs_slightly_favour_the_side_at_home_in_extra_time():

    even = (0.45, 0.27, 0.28)
    p = advance_probability([even, even])

    assert 0.48 < p < 0.5


def test_first_leg_score_conditions_the_tie():

    legs = [(0.45, 0.27, 0.28), (0.45, 0.27, 0.28)]

    assert advance_probability(legs, first_leg_score=(3, 0)) > 0.9
    assert advance_probability(legs, first_leg_score=(0, 3)) < 0.1
    # Level after leg 1: decided at the other side's ground
    assert advance_probability(legs, first_leg_score=(1, 1)) < 0.5


def test_exact_answer_matches_a_monte_carlo():

    legs = [(0.50, 0.25, 0.25), (0.40, 0.27, 0.33)]
    rates = [poisson_rates(p[0], p[2]) for p in legs]

    rng = np.random.default_rng(1)
    n = 200_000
    aggregate = (
        rng.poisson(rates[0][0], n) - rng.poisson(rates[0][1], n)
        + rng.poisson(rates[1][1], n) - rng.poisson(rates[1][0], n)
    )
    extra = rng.poisson(rates[1][1] / 3, n) - rng.poisson(rates[1][0] / 3, n)
    through = (aggregate > 0) | (
        (aggregate == 0) & ((extra > 0) | ((extra == 0) & (rng.random(n) < 0.5)))
    )

    assert abs(through.mean() - advance_probability(legs)) < 0.005


def test_brier_and_bootstrap():

    assert brier([1.0, 0.0], [1, 0]) == 0
    assert brier([0.5, 0.5], [1, 0]) == 0.25

    mean, low, high = bootstrap_against_coin([0.9, 0.1, 0.8, 0.2], [1, 0, 1, 0])
    assert mean < 0 and low <= mean <= high < 0


if __name__ == "__main__":
    for name, test in list(globals().items()):
        if name.startswith("test_"):
            test()
            print(f"ok  {name}")
