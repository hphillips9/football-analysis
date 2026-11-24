"""
Tests for the P9-01 model lab (src/model_lab.py) on synthetic frames, no
data files needed: scoring maths, the information tests (no weight for
the market itself or for noise, a planted signal found), the
walk-forward never training on its own season, and the report-season seal.

    python tests/test_model_lab.py     (or pytest tests/)
"""

import sys
import tempfile
from functools import cache
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import model_lab as lab

DIRECTION = np.array([1.0, 0.0, -1.0])  # a home-strength shift
BASE = np.array([0.35, 0.0, -0.15])


def close(a, b, tol=1e-9):
    return np.allclose(a, b, atol=tol, rtol=0)


def raises(exc, match, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc as error:
        assert match in str(error), str(error)
        return
    raise AssertionError(f"didn't raise {exc.__name__}")


def softmax(eta):
    e = np.exp(eta - eta.max(axis=1, keepdims=True))
    return e / e.sum(axis=1, keepdims=True)


@cache
def world(n_per_season=4000, seed=0):
    """
    Outcomes from true logits BASE + (s1 + s2) * DIRECTION over 22-23..24-25.
    The market sees s1 only. Candidates: the market itself, the market
    plus noise unrelated to the outcome, and the truth (s1 + s2: a
    planted signal the market lacks).
    """

    rng = np.random.default_rng(seed)
    seasons = ["22-23", "23-24", "24-25"]
    n = n_per_season * len(seasons)

    s1 = rng.normal(0, 0.6, n)
    s2 = rng.normal(0, 0.4, n)
    noise = rng.normal(0, 0.4, n)

    truth = softmax(BASE + np.outer(s1 + s2, DIRECTION))
    y = (rng.random(n)[:, None] > truth.cumsum(axis=1)).sum(axis=1)
    market = softmax(BASE + np.outer(s1, DIRECTION))

    frame = pd.DataFrame({
        "Season": np.repeat(seasons, n_per_season),
        "Div": np.tile(["E0", "SP1"], n // 2),
        "FTR": np.array(["H", "D", "A"])[y],
        "qH": market[:, 0], "qD": market[:, 1], "qA": market[:, 2],
        "Avg_qH": market[:, 0], "Avg_qD": market[:, 1], "Avg_qA": market[:, 2],
    }, index=pd.Index([f"k{i}" for i in range(n)], name="MatchKey"))

    def candidate(p):
        return pd.DataFrame(p, index=frame.index, columns=lab.PROB)

    return frame, {
        "market": candidate(market),
        "noisy": candidate(softmax(BASE + np.outer(s1 + noise, DIRECTION))),
        "planted": candidate(truth),
    }


# ============================================================
# SCORING MATHS
# ============================================================

def test_scoring_maths_on_toy_frame():

    frame = pd.DataFrame({
        "Season": ["22-23"] * 4,
        "Div": ["E0", "E0", "SP1", "SP1"],
        "FTR": ["H", "D", "A", "H"],
        "qH": [0.5, 0.3, 0.2, 0.6], "qD": [0.3, 0.4, 0.3, 0.2], "qA": [0.2, 0.3, 0.5, 0.2],
    }, index=pd.Index(["a", "b", "c", "d"], name="MatchKey"))
    frame[["Avg_qH", "Avg_qD", "Avg_qA"]] = frame[lab.MARKET].to_numpy()

    p = np.array([[0.6, 0.2, 0.2], [0.4, 0.3, 0.3], [0.3, 0.3, 0.4], [0.2, 0.3, 0.5]])
    y = np.array([0, 1, 2, 0])
    q = frame[lab.MARKET].to_numpy()

    # Blend and residual parameters that reproduce the market exactly
    info = {"blend": np.array([1.0, 0.0]), "model_share": 0.0,
            "residual": np.zeros(4), "market_only": np.zeros(3),
            "residual_weight": 0.0, "residual_weight_ci": (0.0, 0.0)}
    out = lab._group_scores(frame, p, info, boot=False)

    ll = -np.log(p[np.arange(4), y])
    ll_q = -np.log(q[np.arange(4), y])
    assert close(out["log_loss"], ll.mean())
    assert close(out["market_log_loss"], ll_q.mean())
    assert close(out["gap"], (ll - ll_q).mean())
    assert close(out["gap_avg"], (ll - ll_q).mean())
    assert close(out["accuracy"], 0.5)                     # picks H, H, A, A vs H, D, A, H
    assert close(out["brier"], ((p - np.eye(3)[y]) ** 2).sum(axis=1).mean())
    assert close(out["mean_pD"], p[:, 1].mean())
    assert close(out["actual_H"], 0.5)
    assert close(out["share_draw_gt_030"], 0.0)
    assert close(out["blend_gap"], 0.0)
    assert close(out["residual_gain"], 0.0)
    assert np.isnan(out["slope_H"])                        # too few distinct values for a slope


def test_bootstrap_many_matches_paired_bootstrap():

    from evaluate import paired_bootstrap

    rng = np.random.default_rng(1)
    diffs = [rng.normal(size=300), rng.normal(0.1, 1, 300)]

    for (mean, low, high), d in zip(lab.bootstrap_many(diffs), diffs):
        ref = paired_bootstrap(d)
        assert close(mean, ref["mean"])
        assert close((low, high), ref["ci"])


def test_market_scores_zero_gap():

    frame, candidates = world()
    scores = lab.score(candidates["market"], frame=frame, boot=False)

    assert list(scores.index) == ["all", "E0", "SP1"]
    assert scores.loc["all", "n"] == 8000                  # tune seasons only
    assert close(scores.loc["all", "gap"], 0.0)


def test_calibration_slope_flags_flat_draws():

    rng = np.random.default_rng(2)
    p = rng.uniform(0.2, 0.35, 20000)
    centre = p.mean()
    # True probabilities twice as spread as the forecast: slope ~2
    truth = centre + 2 * (p - centre)
    hit = (rng.random(len(p)) < truth).astype(int)

    slope, _ = lab.calibration(p, hit)

    assert 1.7 < slope < 2.3


# ============================================================
# INFORMATION TESTS
# ============================================================

def test_no_weight_for_the_market_itself():

    frame, candidates = world()
    info = lab.information_fit(candidates["market"], frame)

    assert info["residual_weight"] == 0.0
    assert info["model_share"] == 0.0


def test_near_zero_weight_for_noise():

    frame, candidates = world()
    info = lab.information_fit(candidates["noisy"], frame)

    low, high = info["residual_weight_ci"]
    assert abs(info["residual_weight"]) < 0.15, info["residual_weight"]
    assert low < 0 < high


def test_residual_finds_a_planted_signal():

    frame, candidates = world()
    scores = lab.score(candidates["planted"], frame=frame, period="report", unseal="P9-10",
                       by_league=False)
    overall = scores.loc["all"]

    # The candidate is the truth: weight ~1 on its residual, clearly > 0
    assert overall["residual_weight_ci_low"] > 0.5, overall["residual_weight_ci_low"]
    assert abs(overall["residual_weight"] - 1) < 0.25, overall["residual_weight"]
    # ...and out of sample (fitted on tune, scored on report) it beats the market
    assert overall["residual_gain_ci_high"] < 0
    assert overall["blend_gap_ci_high"] < 0
    assert overall["model_share"] > 0.3


def test_fit_softmax_recovers_coefficients():

    rng = np.random.default_rng(3)
    n = 20000
    x = rng.normal(size=n)
    X = np.zeros((n, 3, 3))
    X[:, 1, 0] = 1                          # draw intercept
    X[:, 2, 1] = 1                          # away intercept
    X[:, :, 2] = np.outer(x, DIRECTION)
    theta = np.array([-0.3, -0.5, 0.8])
    p = softmax(X @ theta)
    y = (rng.random(n)[:, None] > p.cumsum(axis=1)).sum(axis=1)

    fit, cov = lab.fit_softmax(X, y)

    se = np.sqrt(np.diag(cov))
    assert np.all(np.abs(fit - theta) < 4 * se), (fit, se)


def test_fit_softmax_drops_unidentified_columns():

    rng = np.random.default_rng(4)
    n = 2000
    x = rng.normal(size=n)
    X = np.stack([np.outer(x, DIRECTION), np.outer(x, DIRECTION), np.ones((n, 3))], axis=2)
    y = rng.integers(0, 3, n)

    fit, cov = lab.fit_softmax(X, y)

    # The copy and the constant column get 0 and no variance
    assert fit[1] == 0 and fit[2] == 0
    assert np.isnan(cov[1, 1]) and np.isnan(cov[2, 2]) and np.isfinite(cov[0, 0])


# ============================================================
# WALK-FORWARD AND SEAL
# ============================================================

def test_candidate_never_trained_on_its_own_season():

    matches = pd.DataFrame({
        "Season": ["21-22"] * 3 + ["22-23"] * 3 + ["23-24"] * 3,
        "Div": "E0",
        "FTR": list("HDA" * 3),
        "MatchKey": [f"m{i}" for i in range(9)],
    })
    seen = []

    def spy(train, test):
        seen.append((set(train["Season"]), set(test["Season"])))
        return np.full((len(test), 3), 1 / 3)

    out = lab.candidate_oos(spy, ["22-23", "23-24"], matches=matches)

    assert seen == [({"21-22"}, {"22-23"}), ({"21-22", "22-23"}, {"23-24"})]
    assert (out["TrainedThrough"] < out["Season"]).all()
    assert list(out.index) == [f"m{i}" for i in range(3, 9)]


def test_candidate_output_is_validated():

    matches = pd.DataFrame({"Season": ["21-22", "22-23"], "Div": "E0", "FTR": ["H", "D"],
                            "MatchKey": ["a", "b"]})

    raises(ValueError, "sum to 1", lab.candidate_oos,
           lambda tr, te: np.full((len(te), 3), 0.5), ["22-23"], matches=matches)
    raises(ValueError, "shape", lab.candidate_oos,
           lambda tr, te: np.full((len(te), 2), 0.5), ["22-23"], matches=matches)


def test_report_seasons_are_sealed():

    frame, candidates = world()

    for period in ["report", "2627"]:
        raises(PermissionError, "sealed", lab.score, candidates["market"], frame=frame, period=period)
        raises(PermissionError, "sealed", lab.score, candidates["market"], frame=frame,
               period=period, unseal="please")
        raises(PermissionError, "sealed", lab.compare, candidates["noisy"], candidates["market"],
               frame=frame, period=period)
        raises(PermissionError, "sealed", lab.run, candidates["market"], name="x", ticket="T",
               period=period, log=False)

    # The tune seasons are open; the token unseals the rest
    lab.score(candidates["market"], frame=frame, period="tune", boot=False)
    lab.score(candidates["market"], frame=frame, period="report", unseal="P9-10", boot=False)


def test_compare_planted_beats_market():

    frame, candidates = world()
    result = lab.compare(candidates["planted"], candidates["market"], frame=frame)

    assert result["ci"][1] < 0
    assert result["seasons_better"] == result["n_seasons"] == 2


# ============================================================
# CLIMATOLOGY + VARIANT LOG
# ============================================================

def test_climatology_uses_training_rates_per_league():

    train = pd.DataFrame({"Season": "21-22", "Div": ["E0"] * 4 + ["SP1"] * 2,
                          "FTR": ["H", "H", "D", "A", "A", "A"]})
    test = pd.DataFrame({"Season": "22-23", "Div": ["SP1", "E0", "N1"]})

    out = lab.climatology(train, test)

    assert close(out[0], [0, 0, 1])
    assert close(out[1], [0.5, 0.25, 0.25])
    assert close(out[2], [2 / 6, 1 / 6, 3 / 6])            # unseen league: overall rates


def test_log_variant_replaces_same_name():

    frame, candidates = world()
    scores = lab.score(candidates["noisy"], frame=frame, boot=False, by_league=False)

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "variants.csv"
        lab.log_variant(scores, "P9-02", "noisy", "test", {"a": 1}, path=path)
        lab.log_variant(scores, "P9-02", "noisy", "test again", {"a": 2}, path=path)
        log = lab.log_variant(scores, "P9-02", "other", "", None, path=path)

    assert len(log) == 2
    assert list(log.columns) == lab.VARIANT_COLUMNS
    row = log[log["name"] == "noisy"].iloc[0]
    assert row["description"] == "test again"
    assert row["params"] == '{"a": 2}'
    assert row["period"] == "tune"
    assert row["n"] == 8000


if __name__ == "__main__":
    for name, test in list(globals().items()):
        if name.startswith("test_"):
            test()
            print(f"ok  {name}")
