"""
Tie progression (P6-02, plan §4B.9): each side's chance of winning a cup
knockout tie. Display only - never a bet, never a model feature.

Each leg's H/D/A probabilities become a pair of independent Poisson goal
rates (λh, λa) that reproduce P(H) and P(A) (so P(D) too). The tie is
then worked out exactly over the score grid, which is what a Monte Carlo
of the legs converges to, without the sampling noise:

    90 minutes of each leg; a level aggregate goes to extra time in the
    last leg (rates λ/3), then penalties at 50/50. The final is one leg,
    already scored at a neutral venue (model.predict_fixtures averages
    both orientations). No away-goals rule: UEFA dropped it from 2021-22,
    the first season on record.

Probabilities for played legs come from a walk-forward European model
(trained on the seasons before the tie's), so a completed tie's
probability, and the Brier score over them, is out of sample.
"""

import numpy as np
import pandas as pd
from scipy.optimize import least_squares
from scipy.stats import poisson

from champions_league import KNOCKOUT, TWO_LEGGED, neutral_probabilities
from elo import is_cup
from model import FEATURES, _predict, train_european_model

# Goals per side per leg the score grid runs to (P(> 12) is ~1e-6 at λ = 3)
MAX_GOALS = 12

OUTCOMES = ["H", "D", "A"]


# ============================================================
# H/D/A -> POISSON RATES
# ============================================================

def _goal_pmf(rate):
    return poisson.pmf(np.arange(MAX_GOALS + 1), rate)


def _difference_pmf(home_rate, away_rate):
    """
    P(home goals - away goals = d) for d = -MAX_GOALS..MAX_GOALS (index
    d + MAX_GOALS), the two sides' goals independent Poisson.
    """

    # Convolving home goals with negated away goals
    return np.convolve(_goal_pmf(home_rate), _goal_pmf(away_rate)[::-1])


def _hda(home_rate, away_rate):
    diff = _difference_pmf(home_rate, away_rate)
    return diff[MAX_GOALS + 1:].sum(), diff[MAX_GOALS], diff[:MAX_GOALS].sum()


def poisson_rates(p_home, p_away):
    """
    The Poisson goal rates (λh, λa) whose H and A probabilities are
    ``p_home`` and ``p_away`` (the closest pair, by least squares, if no
    pair hits them exactly).
    """

    def residuals(log_rates):
        h, _, a = _hda(*np.exp(log_rates))
        return [h - p_home, a - p_away]

    fit = least_squares(residuals, x0=np.log([1.4, 1.1]), bounds=(np.log(0.01), np.log(8)))

    return tuple(float(rate) for rate in np.exp(fit.x))


# ============================================================
# THE TIE
# ============================================================

def advance_probability(legs, first_leg_score=None):
    """
    P(the first leg's home side wins the tie). ``legs``: each leg's H/D/A
    probabilities in that leg's own home/away order - two for a
    two-legged tie (the second with the sides swapped), one for a final.
    ``first_leg_score`` (home, away) fixes the first leg's result.
    """

    if len(legs) not in (1, 2):
        raise ValueError(f"A tie has one or two legs, not {len(legs)}")

    rates = [poisson_rates(p[0], p[2]) for p in legs]
    zero = MAX_GOALS * len(legs)  # index of an aggregate margin of 0

    if first_leg_score is not None:
        first = np.zeros(2 * MAX_GOALS + 1)
        first[first_leg_score[0] - first_leg_score[1] + MAX_GOALS] = 1.0
    else:
        first = _difference_pmf(*rates[0])

    if len(legs) == 2:
        # The first leg's home side is away in the second: its margin there
        # is minus the home side's
        aggregate = np.convolve(first, _difference_pmf(*rates[1])[::-1])
    else:
        aggregate = first

    # Extra time at the last leg's venue, a third of its rates
    last_home, last_away = rates[-1]
    extra = _difference_pmf(last_home / 3, last_away / 3)
    if len(legs) == 2:
        extra = extra[::-1]

    wins_extra_time = extra[MAX_GOALS + 1:].sum() + 0.5 * extra[MAX_GOALS]

    return float(aggregate[zero + 1:].sum() + aggregate[zero] * wins_extra_time)


# ============================================================
# LEG PROBABILITIES FROM THE MODEL
# ============================================================

def leg_probabilities(model, legs, swap=False):
    """
    The European ``model``'s H/D/A for each of ``legs`` (build_history
    rows: FEATURES, Div, Stage, Neutral) as an (n, 3) array. ``swap``
    scores each leg with the sides swapped (FEATURES are home-minus-away
    differences, so negated). A neutral-venue leg is the average of both
    orientations, as model.predict_fixtures does.
    """

    frame = legs[["Div", "Stage", *FEATURES]].copy()
    flipped = frame.copy()
    flipped[FEATURES] = -flipped[FEATURES]

    if swap:
        frame, flipped = flipped, frame

    forward = _predict(model, frame)[OUTCOMES]
    reverse = _predict(model, flipped)[OUTCOMES]

    neutral = legs["Neutral"].fillna(0).astype(int).eq(1).to_numpy()
    if neutral.any():
        forward.loc[neutral] = neutral_probabilities(
            forward.loc[neutral], reverse.loc[neutral]
        ).to_numpy()

    return forward.to_numpy()


def season_models(rows, seasons):
    """
    ``{season: European model trained on the European rows of the
    seasons before it}``, for each of ``seasons`` that has any before it.
    """

    european = rows[rows["Div"].map(is_cup)]

    return {
        season: train_european_model(european[european["Season"] < season])
        for season in seasons
        if (european["Season"] < season).any()
    }


# ============================================================
# COMPLETED TIES
# ============================================================

def knockout_ties(rows, div="CL"):
    """
    ``div``'s knockout ties in build_history ``rows``: one entry per tie
    with its legs (rows, kick-off order), the first leg's home side first
    in ``teams``, and ``winner`` (None until decided).
    """

    cup = rows[(rows["Div"] == div) & rows["Stage"].isin(KNOCKOUT)]
    cup = cup.sort_values(["MatchDateTime", "MatchId"])

    ties = {}
    for index, leg in cup.iterrows():
        key = (leg["Season"], leg["Stage"], frozenset((leg["HomeTeam"], leg["AwayTeam"])))
        ties.setdefault(key, []).append(index)

    out = []
    for (season, stage, _), indexes in ties.items():
        legs = cup.loc[indexes]
        winners = legs["TieWinner"].dropna()
        out.append({
            "season": season,
            "stage": stage,
            "teams": [legs["HomeTeam"].iloc[0], legs["AwayTeam"].iloc[0]],
            "legs": legs,
            "winner": winners.iloc[-1] if len(winners) else None,
        })

    return out


def tie_probabilities(tie, model):
    """
    ``(before, after_first_leg)``: P(teams[0] goes through) before the
    first leg (both legs scored on pre-tie information, the second as the
    first with the sides swapped) and, for a two-legged tie whose second
    leg is on record, given the first leg's score. None where it can't
    be worked out.
    """

    legs = tie["legs"]
    two_legged = tie["stage"] in TWO_LEGGED

    if two_legged and len(legs) != 2:
        return None, None

    first = leg_probabilities(model, legs.iloc[[0]])[0]

    if not two_legged:
        return advance_probability([first]), None

    # The second leg seen from before the tie: the first, sides swapped
    second_before = leg_probabilities(model, legs.iloc[[0]], swap=True)[0]
    before = advance_probability([first, second_before])

    second = leg_probabilities(model, legs.iloc[[1]])[0]
    score = legs.iloc[0][["FTHG", "FTAG"]]
    after = (
        advance_probability([first, second], first_leg_score=(int(score["FTHG"]), int(score["FTAG"])))
        if score.notna().all() else None
    )

    return before, after


def backtest_ties(rows, div="CL"):
    """
    Every completed ``div`` knockout tie with a season before it on
    record, scored walk-forward: Season, Stage, Home (first-leg home
    side), Away, Before, AfterFirstLeg, HomeWent (1/0).
    """

    ties = [t for t in knockout_ties(rows, div) if t["winner"] is not None]
    models = season_models(rows, sorted({t["season"] for t in ties}))

    records = []
    for tie in ties:
        model = models.get(tie["season"])
        if model is None:
            continue
        before, after = tie_probabilities(tie, model)
        if before is None:
            continue
        records.append({
            "Season": tie["season"],
            "Stage": tie["stage"],
            "Home": tie["teams"][0],
            "Away": tie["teams"][1],
            "Before": before,
            "AfterFirstLeg": after,
            "HomeWent": int(tie["winner"] == tie["teams"][0]),
        })

    return pd.DataFrame(records)


def brier(probabilities, outcomes):
    probabilities = np.asarray(probabilities, dtype=float)
    outcomes = np.asarray(outcomes, dtype=float)
    return float(np.mean((probabilities - outcomes) ** 2))


def bootstrap_against_coin(probabilities, outcomes, resamples=5000, seed=42):
    """
    Brier minus a coin flip's (0.25) with a paired bootstrap 95% CI
    (plan §5: 5,000 resamples, seed 42). Negative = better than 50/50.
    """

    probabilities = np.asarray(probabilities, dtype=float)
    outcomes = np.asarray(outcomes, dtype=float)
    diffs = (probabilities - outcomes) ** 2 - 0.25

    rng = np.random.default_rng(seed)
    means = diffs[rng.integers(0, len(diffs), size=(resamples, len(diffs)))].mean(axis=1)

    return float(diffs.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))
