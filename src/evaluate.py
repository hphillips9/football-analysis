"""
Shared model evaluation: walk-forward by season, per-match log loss and
a paired bootstrap. Used by backtest.py and the notebooks so every
comparison is scored the same way.

    from evaluate import walk_forward, per_match_log_loss, paired_bootstrap

    proba = walk_forward(matches, make_model, FEATURES, ["22-23", "23-24"])
    diff = (per_match_log_loss(y, candidate, labels)
            - per_match_log_loss(y, reference, labels))
    result = paired_bootstrap(diff)
    better(result["ci"])

A candidate is *better* than the reference when the 95% CI of the mean
log-loss difference (candidate - reference) is entirely below 0, and
*non-inferior* when its upper bound is below +0.002.
"""

import numpy as np
import pandas as pd
from sklearn.metrics import log_loss


N_BOOT = 5000
SEED = 42
NON_INFERIOR_MARGIN = 0.002


# ============================================================
# WALK-FORWARD
# ============================================================

def walk_forward(data, make_model, features, test_seasons, group_by=None,
                 target="FTR"):
    """
    Out-of-sample probabilities for every match in ``test_seasons``.

    For each test season a fresh ``make_model()`` is fitted on every
    earlier season and predicts that season. With ``group_by`` (e.g.
    "Div") one model is fitted per group instead of one pooled model.

    Returns a frame with one probability column per class (sorted, like
    ``model.classes_``), indexed and ordered like the test rows of
    ``data``.
    """

    predictions = []

    for season in test_seasons:

        train_all = data[data["Season"] < season]
        test_all = data[data["Season"] == season]

        if group_by is None:
            groups = [(train_all, test_all)]
        else:
            groups = [
                (train_all[train_all[group_by] == key], held_out)
                for key, held_out in test_all.groupby(group_by, sort=False)
            ]

        for train, held_out in groups:
            model = make_model().fit(train[features], train[target])
            predictions.append(pd.DataFrame(
                model.predict_proba(held_out[features]),
                index=held_out.index,
                columns=model.classes_,
            ))

    test_index = data.index[data["Season"].isin(test_seasons)]

    # A group whose training data lacks a class gives it probability 0
    return (
        pd.concat(predictions)
        .sort_index(axis=1)
        .fillna(0.0)
        .loc[test_index]
    )


# ============================================================
# SCORING
# ============================================================

def per_match_log_loss(y_true, proba, labels=None):
    """
    Log loss of each match. ``y_true`` holds column indices into
    ``proba``, or class labels when ``labels`` gives the column order.
    """

    y_true = np.asarray(y_true)
    proba = np.asarray(proba)

    if labels is not None:
        y_true = pd.Index(labels).get_indexer(y_true)

    return -np.log(np.clip(proba[np.arange(len(y_true)), y_true], 1e-15, 1))


def paired_bootstrap(diff, n=N_BOOT, seed=SEED):
    """
    Bootstrap the mean of per-match differences (candidate - reference;
    negative = candidate better). Returns the mean, the 95% CI and
    P(better), the share of resamples below 0.
    """

    diff = np.asarray(diff)

    rng = np.random.default_rng(seed)
    boot_index = rng.integers(0, len(diff), size=(n, len(diff)))
    boot = diff[boot_index].mean(axis=1)

    low, high = np.percentile(boot, [2.5, 97.5])

    return {
        "mean": float(diff.mean()),
        "ci": (float(low), float(high)),
        "p_better": float((boot < 0).mean()),
    }


def seasons_better(y_true, candidate, reference, seasons, labels=None):
    """Number of seasons where ``candidate`` has the lower log loss."""

    y_true = np.asarray(y_true)
    seasons = np.asarray(seasons)
    candidate = np.asarray(candidate)
    reference = np.asarray(reference)

    if labels is None:
        labels = list(range(candidate.shape[1]))

    wins = 0
    for season in pd.unique(seasons):
        mask = seasons == season
        wins += (
            log_loss(y_true[mask], candidate[mask], labels=labels)
            < log_loss(y_true[mask], reference[mask], labels=labels)
        )

    return int(wins)


def better(ci):
    """95% CI of (candidate - reference) entirely below 0."""

    return ci[1] < 0


def non_inferior(ci, margin=NON_INFERIOR_MARGIN):
    """Candidate is at most ``margin`` worse, with 95% confidence."""

    return ci[1] < margin
