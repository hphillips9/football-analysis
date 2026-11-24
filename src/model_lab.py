"""
Model lab (P9-01): one scorer for every Phase 9 candidate, with the
market as the yardstick.

    python src/model_lab.py            # score + log the baselines on the tune seasons

A candidate is a function ``make_proba(train, test)`` that returns H/D/A
probabilities for ``test`` (an (n, 3) array in H, D, A order, or a frame
with H/D/A or pH/pD/pA columns), having seen only ``train``. It doesn't
have to be an sklearn estimator. Then one call:

    import model_lab as lab

    result = lab.run(make_proba, name="dc-xg", ticket="P9-06",
                     description="time-decayed Dixon-Coles on xG", params={"xi": 0.002})
    result["scores"]            # one row per league + "all"

``run`` = ``candidate_oos`` (walk-forward: train on every season before
``s``, predict ``s``) + ``score`` + ``log_variant`` (a row in
data/processed/model_variants.csv, which P9-10 counts).

What ``score`` reports, per league and overall: log loss, accuracy,
Brier score, the gap to the market (de-margined Pinnacle opening with
the Avg fallback - ``qH/qD/qA`` from P8-01 - and Avg opening alone),
calibration slope/intercept per outcome, the share of draws priced
above 0.30, mean predicted vs actual rate per outcome, and two
information tests, both fitted on the tune seasons:

- **log-pool blend** ``p ∝ q^b · p_model^a`` (P8-02's): the model's share
  a/(a+b) and blend - market;
- **market-residual model**: a multinomial logit with the market's
  log-probabilities as a fixed offset, plus intercepts, a market power
  term and ``w · (log p_model - log q)``. ``w`` is the weight on what the
  model says beyond the price; the gain is its log loss minus the same
  fit without the model term (the market recalibrated on its own, so the
  favourite-longshot correction isn't credited to the model). ``w`` > 0
  with gain CI upper < 0 = the model has information the market lacks.

The report seasons are sealed: ``score``/``compare``/``run`` refuse
``period="report"`` or ``"2627"`` unless called with ``unseal="P9-10"``.

Research only; not part of run_week.
"""

import argparse
import json
import sys
import warnings
from datetime import datetime, timezone
from functools import cache
from pathlib import Path

SRC = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

warnings.simplefilter("ignore", pd.errors.PerformanceWarning)

from betting.market import proportional
from betting.simulate import OOS_PATH, load_oos
from evaluate import N_BOOT, SEED, per_match_log_loss, seasons_better

ROOT = SRC.parent
VARIANTS_PATH = ROOT / "data" / "processed" / "model_variants.csv"

OUTCOMES = ["H", "D", "A"]
PROB = ["pH", "pD", "pA"]
MARKET = ["qH", "qD", "qA"]
AVG_ODDS = ["AvgH", "AvgD", "AvgA"]

# README "Phase 9". If the owner approves D9-1 the tune seasons widen to
# every eligible season 15-16..23-24 (COVID 19-20/20-21 still out).
PERIODS = {
    "tune": ["22-23", "23-24"],
    # D9-1 (approved 2026-11-07): the widened tune set, scored on the
    # longer history (history_matches / history_frame, P9-03)
    "tune_wide": ["15-16", "16-17", "17-18", "18-19", "21-22", "22-23", "23-24"],
    "report": ["24-25", "25-26"],
    "2627": ["26-27"],
}
SEALED = {"report", "2627"}
UNSEAL_TOKEN = "P9-10"

# The information tests are always fitted here
FIT_PERIOD = "tune"

DRAW_FLAT = 0.30
MIN_DISTINCT = 10  # distinct predicted values needed for a calibration slope
EPS = 1e-15

VARIANT_COLUMNS = [
    "ticket", "name", "description", "params", "period", "n",
    "log_loss", "accuracy", "brier",
    "market_log_loss", "gap", "gap_ci_low", "gap_ci_high", "gap_avg",
    "draw_slope", "model_share", "blend_gap",
    "residual_weight", "residual_weight_ci_low", "residual_weight_ci_high",
    "residual_gain", "residual_gain_ci_low", "residual_gain_ci_high",
    "timestamp",
]


# ============================================================
# DATA
# ============================================================

def match_key(frame):
    """Season|Div|HomeTeam|AwayTeam - the key oos_predictions.csv uses."""

    return frame["Season"] + "|" + frame["Div"] + "|" + frame["HomeTeam"] + "|" + frame["AwayTeam"]


@cache
def _prepared():

    from backtest import prepare_matches

    matches, _, _ = prepare_matches()
    matches["MatchKey"] = match_key(matches)

    return matches


def lab_matches():
    """
    Every domestic league match with the production features and league
    columns, in walk-forward order (backtest.prepare_matches), plus a
    MatchKey column. What candidates train and predict on. Built once
    per process (~30 s); treat it as read-only.
    """

    return _prepared()


# The longer history (P9-03, D9-1): features from 10-11, training rows
# from 12-13, COVID seasons out
HISTORY_TRAIN_START = "12-13"


@cache
def _history_prepared():

    from backtest import prepare_matches
    from load_data import HISTORY_OUTPUT_PATH

    matches, _, _ = prepare_matches(HISTORY_OUTPUT_PATH, train_start=HISTORY_TRAIN_START)
    matches["MatchKey"] = match_key(matches)

    return matches


def history_matches():
    """
    lab_matches() on the longer history (all_matches_history.csv): the
    production features built from 10-11, rows from HISTORY_TRAIN_START
    on, minus 19-20/20-21. Pass as ``matches=`` to candidate_oos.
    """

    return _history_prepared()


@cache
def _history_frame():

    from betting.market import market_probabilities, odds_columns

    matches = history_matches()
    rows = matches[matches["FTR"].isin(OUTCOMES)]
    odds = [c for c in odds_columns() if c in rows.columns]
    rows = rows.assign(**{c: pd.to_numeric(rows[c], errors="coerce") for c in odds})

    frame = pd.concat(
        [rows[["Season", "Div", "MatchDateTime", "HomeTeam", "AwayTeam", "FTR", "FTHG", "FTAG",
               "MatchKey"]], market_probabilities(rows), rows[odds]],
        axis=1,
    )
    frame["Avg_qH"], frame["Avg_qD"], frame["Avg_qA"] = proportional(
        frame[AVG_ODDS].to_numpy()
    ).T

    # A match with no prices at all can't be scored against the market
    # (one: 21-22 I1 Torino-Fiorentina)
    frame = frame[frame[MARKET].notna().all(axis=1)]

    return frame.set_index("MatchKey", verify_integrity=True)


def history_frame():
    """
    lab_frame() for the longer history: every played match of
    history_matches() that has prices, with the result and the same market columns
    (qH/qD/qA: de-margined Pinnacle opening, Avg fallback; Avg_q*), but
    no production pH/pD/pA. Pass as ``frame=`` to score / compare.
    """

    return _history_frame()


@cache
def _frame(path):

    oos = load_oos(path)
    oos = oos[oos["FTR"].notna()].copy()
    oos["Avg_qH"], oos["Avg_qD"], oos["Avg_qA"] = proportional(oos[AVG_ODDS].to_numpy()).T

    return oos.set_index("MatchKey", verify_integrity=True)


def lab_frame(path=OOS_PATH):
    """
    The matches every candidate is scored on: the played rows of
    oos_predictions.csv (P8-01), indexed by MatchKey, with the result,
    the production model's pH/pD/pA, the market's qH/qD/qA (Pinnacle
    opening, Avg fallback) and Avg_qH/Avg_qD/Avg_qA (Avg opening alone).
    """

    return _frame(str(path))


def check_period(period, unseal=None):
    """The seasons of ``period``; refuses a sealed one without the token."""

    if period not in PERIODS:
        raise ValueError(f"Unknown period {period!r}; one of {sorted(PERIODS)}")

    if period in SEALED and unseal != UNSEAL_TOKEN:
        raise PermissionError(
            f"Period {period!r} is sealed until P9-10 (README 'Phase 9'). "
            f"Choose on the tune seasons."
        )

    return PERIODS[period]


# ============================================================
# WALK-FORWARD
# ============================================================

def _as_proba(out, index):
    """A candidate's output as an (n, 3) H/D/A array."""

    if isinstance(out, pd.DataFrame):
        if set(PROB) <= set(out.columns):
            out = out[PROB]
        elif set(OUTCOMES) <= set(out.columns):
            out = out[OUTCOMES]
        else:
            raise ValueError(f"Candidate frame needs H/D/A or pH/pD/pA columns, has {list(out.columns)}")
        out = out.to_numpy(dtype=float)

    out = np.asarray(out, dtype=float)

    if out.shape != (len(index), 3):
        raise ValueError(f"Candidate returned shape {out.shape}, expected ({len(index)}, 3)")
    if not np.isfinite(out).all() or (out < 0).any():
        raise ValueError("Candidate returned NaN, inf or negative probabilities")
    if not np.allclose(out.sum(axis=1), 1, atol=1e-6):
        raise ValueError("Candidate probabilities don't sum to 1")

    return out


def candidate_oos(make_proba, seasons=None, matches=None):
    """
    Out-of-sample probabilities from ``make_proba(train, test)`` for
    every match in ``seasons`` (default: the tune seasons): ``train`` is
    every match before season ``s``, ``test`` is season ``s``'s matches
    (played or not). Returns a frame indexed by MatchKey with pH/pD/pA,
    Season and TrainedThrough (the last season the candidate saw).
    """

    matches = lab_matches() if matches is None else matches
    seasons = PERIODS["tune"] if seasons is None else seasons

    parts = []
    for season in sorted(seasons):

        train = matches[matches["Season"] < season]
        test = matches[matches["Season"] == season]
        if test.empty:
            continue

        proba = _as_proba(make_proba(train, test), test.index)
        part = pd.DataFrame(proba, columns=PROB, index=test["MatchKey"].to_numpy())
        part["Season"] = season
        part["TrainedThrough"] = train["Season"].max() if not train.empty else None
        parts.append(part)

    out = pd.concat(parts)
    out.index.name = "MatchKey"

    if not (out["TrainedThrough"].fillna("") < out["Season"]).all():
        raise AssertionError("A candidate row was trained on its own season")

    return out


# ============================================================
# BASELINES
# ============================================================

def production(train, test):
    """Today's model: pooled LR + league indicators, E0 on its own model."""

    from model import walk_forward_models

    season = test["Season"].iloc[0]
    proba = walk_forward_models(pd.concat([train, test]), [season])

    return proba.loc[test.index, OUTCOMES]


def climatology(train, test):
    """The floor: each league's H/D/A rates over the training seasons."""

    played = train[train["FTR"].isin(OUTCOMES)]
    overall = played["FTR"].value_counts(normalize=True).reindex(OUTCOMES, fill_value=0)
    rates = (
        played.groupby("Div")["FTR"].value_counts(normalize=True)
        .unstack(fill_value=0).reindex(columns=OUTCOMES, fill_value=0)
    )
    out = rates.reindex(test["Div"]).fillna(overall).to_numpy()

    return out


def market_proba(frame=None):
    """The market itself as a candidate (qH/qD/qA), indexed by MatchKey."""

    frame = lab_frame() if frame is None else frame
    out = frame[MARKET].set_axis(PROB, axis=1)
    out["Season"] = frame["Season"]

    return out


# ============================================================
# MATHS
# ============================================================

def _softmax(eta):

    eta = eta - eta.max(axis=1, keepdims=True)
    e = np.exp(eta)

    return e / e.sum(axis=1, keepdims=True)


def _onehot(y):

    return np.eye(3)[y]


def fit_softmax(X, y, offset=None, max_iter=100, tol=1e-10):
    """
    Maximum-likelihood ``theta`` for a multinomial logit with per-outcome
    features: logit_ik = offset_ik + X_ik . theta (X is (n, 3, j)).
    Newton's method with step halving. Returns theta and its covariance
    (inverse observed information); columns of X that are constant within
    every row carry no information and get theta 0, variance NaN.
    """

    n, _, j = X.shape
    offset = np.zeros((n, 3)) if offset is None else offset
    Y = _onehot(y)

    # Only within-row differences matter (softmax ignores a per-row
    # constant). A column that adds nothing to the earlier ones there -
    # constant across H/D/A, or a copy of an earlier column - is
    # unidentified: dropped, so earlier columns take precedence.
    centred = (X - X.mean(axis=1, keepdims=True)).reshape(n * 3, j)
    keep = np.zeros(j, dtype=bool)
    for col in range(j):
        trial = keep.copy()
        trial[col] = True
        sub = centred[:, trial]
        sv = np.linalg.svd(sub, compute_uv=False)
        if sv.min() > 1e-7 * max(sv.max(), 1e-12) and np.abs(centred[:, col]).max() > 1e-9:
            keep = trial
    Xk = X[:, :, keep]

    def nll(theta):
        p = _softmax(offset + Xk @ theta)
        return -np.log(np.clip(p[np.arange(n), y], EPS, 1)).sum()

    theta = np.zeros(keep.sum())
    hess = np.eye(len(theta))
    current = nll(theta)

    for _ in range(max_iter):
        if not len(theta):
            break
        p = _softmax(offset + Xk @ theta)
        grad = np.einsum("nk,nkj->j", p - Y, Xk)
        xbar = np.einsum("nk,nkj->nj", p, Xk)
        hess = np.einsum("nk,nkj,nkl->jl", p, Xk, Xk) - xbar.T @ xbar
        step = np.linalg.solve(hess, grad)

        size = 1.0
        while nll(theta - size * step) > current + 1e-12 and size > 1e-6:
            size /= 2
        theta = theta - size * step
        new = nll(theta)
        done = np.abs(size * step).max() < tol or current - new < tol
        current = new
        if done:
            break

    if len(theta):
        p = _softmax(offset + Xk @ theta)
        xbar = np.einsum("nk,nkj->nj", p, Xk)
        hess = np.einsum("nk,nkj,nkl->jl", p, Xk, Xk) - xbar.T @ xbar

    full = np.zeros(j)
    full[keep] = theta
    cov = np.full((j, j), np.nan)
    if len(theta):
        cov[np.ix_(keep, keep)] = np.linalg.inv(hess)

    return full, cov


def _logs(proba):

    return np.log(np.clip(proba, EPS, 1))


def _intercepts(n):
    """Per-outcome 0/1 columns for D and A (H is the reference)."""

    X = np.zeros((n, 3, 2))
    X[:, 1, 0] = 1
    X[:, 2, 1] = 1

    return X


def blend_design(p, q):
    """
    Log pool p ∝ q^b · p_model^a: features [log q, log p], no offset.
    The market comes first, so a candidate that is the market gets a = 0.
    """

    return np.stack([_logs(q), _logs(p)], axis=2), None


def residual_design(p, q, with_model=True):
    """
    Market-residual model: offset log q, features [D, A intercepts,
    log q (power), log p - log q (the model's residual)]. Without the
    model it's the market recalibrated on its own.
    """

    lq = _logs(q)
    cols = [_intercepts(len(q)), lq[:, :, None]]
    if with_model:
        cols.append((_logs(p) - lq)[:, :, None])

    return np.concatenate(cols, axis=2), lq


def predict_softmax(theta, X, offset=None):

    eta = X @ theta
    if offset is not None:
        eta = eta + offset

    return _softmax(eta)


def calibration(p, hit):
    """Calibration slope and intercept: logistic regression of hit on logit(p)."""

    # Needs spread in p: a near-constant forecast (climatology) has no slope
    if len(np.unique(hit)) < 2 or len(np.unique(np.round(p, 6))) < MIN_DISTINCT:
        return np.nan, np.nan

    z = np.log(np.clip(p, 1e-6, 1 - 1e-6) / np.clip(1 - p, 1e-6, 1))
    fit = LogisticRegression(C=1e6, max_iter=1000).fit(z.reshape(-1, 1), hit)

    return float(fit.coef_[0, 0]), float(fit.intercept_[0])


def bootstrap_many(diffs, n=N_BOOT, seed=SEED):
    """
    evaluate.paired_bootstrap for several per-match differences on the
    same matches (the same resampled indices for each, so each result
    equals a separate paired_bootstrap call). Returns (mean, low, high)
    per diff.
    """

    diffs = [np.asarray(d, dtype=float) for d in diffs]
    m = len(diffs[0])
    rng = np.random.default_rng(seed)
    index = rng.integers(0, m, size=(n, m))

    out = []
    for d in diffs:
        boot = d[index].mean(axis=1)
        low, high = np.percentile(boot, [2.5, 97.5])
        out.append((float(d.mean()), float(low), float(high)))

    return out


# ============================================================
# SCORING
# ============================================================

def _aligned(proba, frame, seasons):
    """(frame rows, candidate (n, 3)) for the played matches in ``seasons``."""

    rows = frame[frame["Season"].isin(seasons)]
    if isinstance(proba, pd.DataFrame):
        missing = rows.index.difference(proba.index)
        if len(missing):
            raise ValueError(
                f"Candidate has no probabilities for {len(missing)} of {len(rows)} matches "
                f"in {seasons} (e.g. {missing[0]})"
            )
        cols = PROB if set(PROB) <= set(proba.columns) else OUTCOMES
        p = proba.loc[rows.index, cols].to_numpy(dtype=float)
    else:
        raise TypeError("proba must be a frame indexed by MatchKey (candidate_oos output)")

    return rows, p


def information_fit(proba, frame=None):
    """Blend and residual parameters, fitted on the tune seasons."""

    frame = lab_frame() if frame is None else frame
    rows, p = _aligned(proba, frame, PERIODS[FIT_PERIOD])
    q = rows[MARKET].to_numpy()
    y = rows["FTR"].map({"H": 0, "D": 1, "A": 2}).to_numpy()

    blend, _ = fit_softmax(blend_design(p, q)[0], y)
    X, off = residual_design(p, q)
    residual, cov = fit_softmax(X, y, offset=off)
    X0, off0 = residual_design(p, q, with_model=False)
    market_only, _ = fit_softmax(X0, y, offset=off0)

    se = float(np.sqrt(cov[-1, -1])) if np.isfinite(cov[-1, -1]) else np.nan
    b, a = blend
    share = a / (a + b) if abs(a) > 0 else 0.0

    return {
        "blend": blend, "model_share": float(share),
        "residual": residual, "market_only": market_only,
        "residual_weight": float(residual[-1]),
        "residual_weight_ci": (float(residual[-1] - 1.96 * se), float(residual[-1] + 1.96 * se)),
        "n_fit": len(rows),
    }


def _group_scores(rows, p, info, boot=True):

    y = rows["FTR"].map({"H": 0, "D": 1, "A": 2}).to_numpy()
    q = rows[MARKET].to_numpy()
    q_avg = rows[["Avg_qH", "Avg_qD", "Avg_qA"]].to_numpy()
    Y = _onehot(y)

    ll = per_match_log_loss(y, p)
    ll_q = per_match_log_loss(y, q)
    avg_ok = np.isfinite(q_avg).all(axis=1)
    ll_avg = per_match_log_loss(y[avg_ok], q_avg[avg_ok])

    blend = predict_softmax(info["blend"], blend_design(p, q)[0])
    X, off = residual_design(p, q)
    resid = predict_softmax(info["residual"], X, off)
    X0, off0 = residual_design(p, q, with_model=False)
    market_recal = predict_softmax(info["market_only"], X0, off0)
    ll_blend, ll_resid, ll_recal = (per_match_log_loss(y, x) for x in (blend, resid, market_recal))

    out = {
        "n": len(rows),
        "log_loss": ll.mean(),
        "accuracy": (p.argmax(axis=1) == y).mean(),
        "brier": ((p - Y) ** 2).sum(axis=1).mean(),
        "market_log_loss": ll_q.mean(),
        "avg_log_loss": ll_avg.mean(),
    }

    if boot:
        (gap, gap_lo, gap_hi), (blend_gap, blend_lo, blend_hi), (gain, gain_lo, gain_hi) = bootstrap_many(
            [ll - ll_q, ll_blend - ll_q, ll_resid - ll_recal]
        )
        (gap_avg, gap_avg_lo, gap_avg_hi), = bootstrap_many([ll[avg_ok] - ll_avg])
    else:
        gap, blend_gap, gain = (ll - ll_q).mean(), (ll_blend - ll_q).mean(), (ll_resid - ll_recal).mean()
        gap_avg = (ll[avg_ok] - ll_avg).mean()
        gap_lo = gap_hi = blend_lo = blend_hi = gain_lo = gain_hi = gap_avg_lo = gap_avg_hi = np.nan

    out.update({
        "gap": gap, "gap_ci_low": gap_lo, "gap_ci_high": gap_hi,
        "gap_avg": gap_avg, "gap_avg_ci_low": gap_avg_lo, "gap_avg_ci_high": gap_avg_hi,
    })

    for k, o in enumerate(OUTCOMES):
        hit = (y == k).astype(int)
        slope, intercept = calibration(p[:, k], hit)
        out[f"slope_{o}"] = slope
        out[f"intercept_{o}"] = intercept
        out[f"mean_p{o}"] = p[:, k].mean()
        out[f"actual_{o}"] = hit.mean()

    out["share_draw_gt_030"] = (p[:, 1] > DRAW_FLAT).mean()

    out.update({
        "model_share": info["model_share"],
        "blend_gap": blend_gap, "blend_gap_ci_low": blend_lo, "blend_gap_ci_high": blend_hi,
        "residual_weight": info["residual_weight"],
        "residual_weight_ci_low": info["residual_weight_ci"][0],
        "residual_weight_ci_high": info["residual_weight_ci"][1],
        "residual_gain": gain, "residual_gain_ci_low": gain_lo, "residual_gain_ci_high": gain_hi,
    })

    return out


def score(proba, frame=None, period="tune", unseal=None, by_league=True, boot=True):
    """
    Score a candidate (candidate_oos output, indexed by MatchKey) on the
    played matches of ``period``: one row for "all" and, with
    ``by_league``, one per league. Gaps and gains are candidate minus
    market (negative = candidate better), with paired-bootstrap 95% CIs
    (5,000, seed 42). Blend/residual parameters are fitted on the tune
    seasons whatever ``period`` is, so the candidate needs tune rows too.
    """

    seasons = check_period(period, unseal)
    frame = lab_frame() if frame is None else frame

    info = information_fit(proba, frame)
    rows, p = _aligned(proba, frame, seasons)

    groups = [("all", np.ones(len(rows), dtype=bool))]
    if by_league:
        groups += [(div, (rows["Div"] == div).to_numpy()) for div in sorted(rows["Div"].unique())]

    out = pd.DataFrame({
        name: _group_scores(rows[mask], p[mask], info, boot=boot) for name, mask in groups
    }).T
    out.index.name = "league"
    out.insert(0, "period", period)
    out["n"] = out["n"].astype(int)

    return out


def compare(candidate, reference, frame=None, period="tune", unseal=None):
    """
    Paired bootstrap (5,000, seed 42) of per-match log loss, candidate -
    reference, on ``period``'s played matches; plus the number of seasons
    the candidate is better in.
    """

    seasons = check_period(period, unseal)
    frame = lab_frame() if frame is None else frame

    rows, p = _aligned(candidate, frame, seasons)
    _, r = _aligned(reference, frame, seasons)
    y = rows["FTR"].map({"H": 0, "D": 1, "A": 2}).to_numpy()

    ll_c, ll_r = per_match_log_loss(y, p), per_match_log_loss(y, r)
    (diff, low, high), = bootstrap_many([ll_c - ll_r])

    return {
        "period": period,
        "n": len(rows),
        "candidate": float(ll_c.mean()),
        "reference": float(ll_r.mean()),
        "diff": diff,
        "ci": (low, high),
        "seasons_better": seasons_better(y, p, r, rows["Season"].to_numpy()),
        "n_seasons": int(rows["Season"].nunique()),
    }


# ============================================================
# VARIANT LOG
# ============================================================

def load_variants(path=VARIANTS_PATH):

    if not Path(path).exists():
        return pd.DataFrame(columns=VARIANT_COLUMNS)

    return pd.read_csv(path)


def log_variant(scores, ticket, name, description="", params=None, path=VARIANTS_PATH):
    """
    Record a scored variant: one row in model_variants.csv from
    ``scores``' "all" row. Re-scoring the same (ticket, name, period)
    replaces its row, so a re-run notebook doesn't double-count.
    """

    overall = scores.loc["all"]
    row = {
        "ticket": ticket,
        "name": name,
        "description": description,
        "params": json.dumps(params or {}, sort_keys=True, default=str),
        "period": overall["period"],
        "draw_slope": overall["slope_D"],
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    for col in VARIANT_COLUMNS:
        if col not in row:
            row[col] = overall[col]

    log = load_variants(path)
    same = (log["ticket"] == ticket) & (log["name"] == name) & (log["period"] == row["period"])
    log = pd.concat([log[~same], pd.DataFrame([row])[VARIANT_COLUMNS]], ignore_index=True)

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    log.to_csv(path, index=False)

    return log


def run(make_proba, name, ticket, description="", params=None, period="tune", unseal=None,
        log=True, path=VARIANTS_PATH):
    """
    candidate_oos + score + log_variant in one call. Returns
    {"proba": the OOS frame, "scores": score's table}.
    """

    seasons = check_period(period, unseal)
    needed = sorted(set(PERIODS[FIT_PERIOD]) | set(seasons))

    if make_proba is None or isinstance(make_proba, pd.DataFrame):
        proba = make_proba if make_proba is not None else market_proba()
    else:
        proba = candidate_oos(make_proba, needed)

    scores = score(proba, period=period, unseal=unseal)
    if log:
        log_variant(scores, ticket, name, description, params, path)

    return {"proba": proba, "scores": scores}


# ============================================================
# BASELINES (CLI)
# ============================================================

def check_production(proba, frame=None):
    """Max |difference| between the production baseline and oos_predictions.csv."""

    frame = lab_frame() if frame is None else frame
    common = proba.index.intersection(frame.index)

    return float(np.abs(proba.loc[common, PROB].to_numpy() - frame.loc[common, PROB].to_numpy()).max())


BASELINES = {
    "production": (production, "today's model: pooled LR + league indicators, E0 own (CalibratedClassifierCV sigmoid)"),
    "market": (None, "de-margined Pinnacle opening, Avg fallback (qH/qD/qA)"),
    "climatology": (climatology, "each league's H/D/A base rates over the training seasons"),
}


def main(argv=None):

    parser = argparse.ArgumentParser(description="Score and log the P9-01 baselines.")
    parser.add_argument("--period", default="tune", choices=sorted(PERIODS))
    parser.add_argument("--unseal", default=None)
    parser.add_argument("--no-log", action="store_true")
    args = parser.parse_args(argv)

    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 40)

    summary = {}
    for name, (fn, description) in BASELINES.items():
        result = run(fn, name=name, ticket="P9-01", description=description, period=args.period,
                     unseal=args.unseal, log=not args.no_log)
        scores = result["scores"]
        summary[name] = scores.loc["all"]

        if name == "production":
            print(f"production vs oos_predictions.csv: max |diff| = {check_production(result['proba']):.2e}")

        cols = ["n", "log_loss", "accuracy", "brier", "gap", "gap_ci_low", "gap_ci_high", "gap_avg",
                "slope_H", "slope_D", "slope_A", "share_draw_gt_030", "residual_weight", "residual_gain"]
        print(f"\n== {name} ({args.period}) ==")
        print(scores[cols].astype(float).round(4).to_string())

    cols = ["n", "log_loss", "market_log_loss", "gap", "gap_ci_low", "gap_ci_high", "gap_avg", "model_share",
            "blend_gap", "residual_weight", "residual_weight_ci_low", "residual_weight_ci_high",
            "residual_gain", "residual_gain_ci_low", "residual_gain_ci_high"]
    print("\n== summary ==")
    print(pd.DataFrame(summary).T[cols].astype(float).round(4).to_string())


if __name__ == "__main__":
    main()
