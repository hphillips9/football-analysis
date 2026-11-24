"""
Tests for the betting-research harness (src/betting/): settlement,
staking, betting weeks, de-margining, and that oos_predictions matches
backtest.py's walk-forward without training on its own season.

    python tests/test_betting.py     (or pytest tests/)
"""

import itertools
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import backtest
import model
from betting import oos as oos_module
from betting.market import market_probabilities, proportional, shin
from betting.simulate import Bet, bet_week, flat_argmax, load_oos, simulate, single, summarise
from load_data import add_gameweek


# ============================================================
# A tiny hand-made oos frame
# ============================================================

def _match(key, when, ftr, hg, ag, odds=(2.0, 3.0, 4.0), season="22-23", **extra):
    row = {
        "Season": season, "Div": "E0", "MatchDateTime": pd.Timestamp(when),
        "MatchKey": key, "HomeTeam": key + "h", "AwayTeam": key + "a",
        "FTR": ftr, "FTHG": hg, "FTAG": ag,
        "pH": 0.5, "pD": 0.3, "pA": 0.2,
        "AvgH": odds[0], "AvgD": odds[1], "AvgA": odds[2],
        "AvgCH": odds[0], "AvgCD": odds[1], "AvgCA": odds[2],
        "Avg>2.5": 1.9, "Avg<2.5": 1.9, "AvgC>2.5": 1.9, "AvgC<2.5": 1.9,
        "AHh": -0.25, "AHCh": -0.25, "AvgAHH": 1.9, "AvgAHA": 1.9,
        "AvgCAHH": 1.9, "AvgCAHA": 1.9,
    }
    row.update(extra)
    return row


def _frame(rows):
    frame = pd.DataFrame(rows)
    frame["BetWeek"] = bet_week(frame["MatchDateTime"])
    return frame


# Tue 2022-08-16 .. Mon 2022-08-22 is one week; Tue 2022-08-23 the next
WEEK = _frame([
    _match("a", "2022-08-20 15:00", "H", 2, 0),            # home win
    _match("b", "2022-08-21 15:00", "D", 1, 1),            # draw
    _match("c", "2022-08-22 20:00", np.nan, np.nan, np.nan),  # postponed (Monday)
    _match("d", "2022-08-23 19:45", "A", 0, 3),            # next week
])


def _run(bets_by_week, frame=WEEK, **kwargs):
    """Simulate a strategy that places ``bets_by_week[i]`` in week i."""

    weeks = iter(bets_by_week)
    return simulate(frame, lambda week, bankroll: next(weeks, []), **kwargs)


# ============================================================
# SETTLEMENT
# ============================================================

def test_single_win_lose_and_void():
    r = _run([[single("a", "H", 1), single("b", "H", 1), single("c", "H", 1)]])

    assert r.bets["profit"].round(10).tolist() == [1.0, -1.0, 0.0]
    assert r.bets["won"].tolist() == [True, False, False]
    assert r.bets["lost"].tolist() == [False, True, False]


def test_acca_wins_only_if_every_leg_does():
    win = _run([[Bet([("a", "H"), ("b", "D")], 2)]])
    assert win.bets["odds"].iloc[0] == 2.0 * 3.0
    assert win.bets["profit"].iloc[0] == 2 * (6.0 - 1)

    lose = _run([[Bet([("a", "H"), ("b", "A")], 2)]])
    assert lose.bets["profit"].iloc[0] == -2


def test_void_leg_counts_as_odds_one():
    r = _run([[Bet([("a", "H"), ("c", "A")], 1)]])  # c postponed

    assert r.bets["payout"].iloc[0] == 2.0
    assert r.legs["return"].tolist() == [2.0, 1.0]


def test_over_under_and_asian_handicap():
    # a: 2-0, b: 1-1; AH line -0.25 for the home side
    r = _run([[
        single("a", "U", 1, market="OU25"),   # 2 goals: under wins
        single("b", "O", 1, market="OU25"),   # 2 goals: over loses
        single("a", "H", 1, market="AH"),     # +2 on -0.25: full win
        single("b", "H", 1, market="AH"),     # draw on -0.25: half lost
        single("b", "A", 1, market="AH"),     # draw on +0.25: half won
    ]])

    assert np.allclose(r.bets["payout"], [1.9, 0.0, 1.9, 0.5, (1.9 + 1) / 2])


def test_unpriced_bet_is_not_placed():
    frame = _frame([_match("a", "2022-08-20 15:00", "H", 2, 0, odds=(np.nan, 3.0, 4.0))])
    r = _run([[single("a", "H", 1), single("a", "D", 1)]], frame=frame)

    assert r.unpriced == 1
    assert len(r.bets) == 1


def test_strategy_never_sees_the_result():
    seen = []
    simulate(WEEK, lambda week, bankroll: seen.append(set(week.columns)) or [])

    assert seen and all(not ({"FTR", "FTHG", "FTAG"} & cols) for cols in seen)
    assert all({"oH", "oD", "oA", "oO", "oU", "oAHH", "oAHA"} <= cols for cols in seen)


def test_odds_source_picks_the_columns():
    frame = _frame([_match("a", "2022-08-20 15:00", "H", 2, 0, MaxH=2.5, MaxCH=2.4)])

    assert _run([[single("a", "H", 1)]], frame=frame, source="max").bets["profit"].iloc[0] == 1.5
    r = _run([[single("a", "H", 1)]], frame=frame, source="avg")
    assert r.bets["profit"].iloc[0] == 1.0
    assert r.legs["clv"].iloc[0] == 0.0  # took the closing price


# ============================================================
# STAKING
# ============================================================

def test_bankroll_updates_weekly_and_caps_stakes():
    # Week 1: 60 + 60 staked from a bankroll of 100 -> scaled to 50 + 50
    r = _run(
        [[single("a", "H", 60), single("b", "H", 60)], [single("d", "A", 10)]],
        bankroll=100,
    )

    assert r.bets["stake"].tolist() == [50, 50, 10]
    week1 = 50 * (2.0 - 1) - 50
    assert r.weeks["bankroll_end"].tolist() == [100 + week1, 100 + week1 + 10 * 3.0]


def test_ruin_stops_betting():
    r = _run([[single("b", "H", 100)], [single("d", "A", 10)]], bankroll=100)

    assert r.weeks["bankroll_end"].iloc[0] == 0
    assert len(r.bets) == 1
    assert summarise(r).loc["overall", "final_bankroll"] == 0


def test_summary_metrics():
    r = _run([[single("a", "H", 1), single("b", "H", 1), single("c", "H", 1)], [single("d", "H", 1)]])
    s = summarise(r).loc["overall"]

    assert s["bets"] == 4 and s["staked"] == 4
    assert s["profit"] == -1
    assert s["roi"] == -25
    assert s["longest_losing_run"] == 1  # b lost, c void, d lost: the void breaks the run
    assert s["max_drawdown"] == 1
    assert s["weeks"] == 2 and s["weeks_in_profit"] == 0


# ============================================================
# BETTING WEEKS
# ============================================================

def test_bet_week_runs_tuesday_to_monday():
    dates = ["2022-08-15 20:00", "2022-08-16 19:45", "2022-08-20 15:00", "2022-08-22 20:00"]

    assert list(bet_week(dates)) == ["2022-08-09", "2022-08-16", "2022-08-16", "2022-08-16"]


def test_bet_week_can_split_midweek_and_weekend():
    dates = ["2022-08-16 19:45", "2022-08-18 19:45", "2022-08-19 20:00", "2022-08-22 20:00"]

    assert list(bet_week(dates, (1, 4))) == ["2022-08-16", "2022-08-16", "2022-08-19", "2022-08-19"]


# ============================================================
# MARKET PROBABILITIES
# ============================================================

def test_demargining():
    odds = np.array([[1.5, 4.0, 7.0], [2.5, 3.2, 2.9]])

    for method in (proportional, shin):
        assert np.allclose(method(odds).sum(axis=1), 1)

    # Shin takes more margin off the longshot than the favourite
    assert shin(odds)[0, 0] > proportional(odds)[0, 0]
    assert shin(odds)[0, 2] < proportional(odds)[0, 2]


def test_market_probabilities_fall_back_to_the_average():
    frame = pd.DataFrame({
        "PSH": [2.0, np.nan], "PSD": [3.5, np.nan], "PSA": [4.0, np.nan],
        "AvgH": [1.9, 2.0], "AvgD": [3.4, 3.4], "AvgA": [3.9, 3.8],
        "PSCH": [2.0, np.nan], "PSCD": [3.5, np.nan], "PSCA": [4.0, np.nan],
        "AvgCH": [1.9, 2.0], "AvgCD": [3.4, 3.4], "AvgCA": [3.9, 3.8],
    })
    q = market_probabilities(frame)

    assert q["qSource"].tolist() == ["pinnacle", "avg"]
    assert np.allclose(q[["qH", "qD", "qA"]].sum(axis=1), 1)
    assert np.isclose(q.loc[0, "qH"], proportional([[2.0, 3.5, 4.0]])[0, 0])


# ============================================================
# OOS PREDICTIONS vs BACKTEST (synthetic leagues)
# ============================================================

SEASONS = [("21-22", "2021-08-14"), ("22-23", "2022-08-13"), ("23-24", "2023-08-12"), ("24-25", "2024-08-10")]


def _league(div, seed):
    """Three full seasons of a six-team league, then 6 games of a fourth."""

    rng = np.random.default_rng(seed)
    teams = [f"{div} {name}" for name in "ABCDEF"]
    rows = []

    for season, start in SEASONS:
        pairs = list(itertools.permutations(teams, 2))
        if season == "24-25":
            pairs = pairs[:6]
        for week, (home, away) in enumerate(pairs):
            goals = rng.integers(0, 4, size=2)
            kickoff = pd.Timestamp(start) + pd.Timedelta(days=3 * week)
            rows.append({
                "Div": div, "Season": season,
                "Date": kickoff.strftime("%d/%m/%Y"), "Time": "15:00", "MatchDateTime": kickoff,
                "HomeTeam": home, "AwayTeam": away, "FTHG": goals[0], "FTAG": goals[1],
                "FTR": "H" if goals[0] > goals[1] else "A" if goals[0] < goals[1] else "D",
                "HomeXG": round(rng.uniform(0.3, 2.5), 2), "AwayXG": round(rng.uniform(0.3, 2.5), 2),
                "AvgH": round(rng.uniform(1.5, 3.5), 2), "AvgD": 3.3, "AvgA": round(rng.uniform(2.0, 5.0), 2),
                "AvgCH": 2.2, "AvgCD": 3.3, "AvgCA": 3.4,
            })

    return pd.DataFrame(rows)


class _Synthetic:
    """all_matches.csv with two synthetic leagues, MIN_SEASON_MATCHES lowered."""

    def __enter__(self):
        self.saved = backtest.MIN_SEASON_MATCHES
        backtest.MIN_SEASON_MATCHES = 20
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "all_matches.csv"
        add_gameweek(pd.concat([_league("E0", 1), _league("SP1", 2)], ignore_index=True)).to_csv(
            self.path, index=False
        )
        return self.path

    def __exit__(self, *exc):
        backtest.MIN_SEASON_MATCHES = self.saved
        self.tmp.cleanup()


def test_oos_matches_backtest_and_adds_the_season_in_progress():
    with _Synthetic() as path:
        matches, seasons, test_seasons = backtest.prepare_matches(path)
        proba = model.walk_forward_models(matches, test_seasons)
        oos = oos_module.build_oos(path)

    assert test_seasons == ["22-23", "23-24"]
    assert sorted(oos["Season"].unique()) == ["22-23", "23-24", "24-25"]
    assert (oos["Season"] == "24-25").sum() == 12

    # Same rows, same probabilities, after a CSV round trip
    with tempfile.TemporaryDirectory() as tmp:
        csv = Path(tmp) / "oos.csv"
        oos_module.write_oos(oos, csv)
        oos = load_oos(csv)

    expected = matches.loc[proba.index]
    tested = oos[oos["Season"].isin(test_seasons)].reset_index(drop=True)
    assert tested["MatchKey"].tolist() == oos_module.match_key(expected).tolist()
    for cls in "HDA":
        assert np.array_equal(tested[f"p{cls}"].to_numpy(), proba[cls].to_numpy())

    # Flat argmax through the simulator = backtest.py's profit
    tested["MatchDateTime"] = pd.to_datetime(tested["MatchDateTime"])
    _, overall = backtest.score(matches, proba, seasons, test_seasons)
    sim = simulate(tested, flat_argmax, source="live")
    assert round(sim.bets["profit"].sum(), 2) == overall["profit"]


def test_no_row_is_predicted_by_a_model_trained_on_its_own_season():
    fits = []  # (train seasons, predict seasons) per fitted model

    real = model.make_model

    with _Synthetic() as path:
        matches, _, _ = backtest.prepare_matches(path)

        class Recorder:
            def __init__(self):
                self.inner = real()

            def fit(self, X, y):
                self.train = set(matches.loc[X.index, "Season"])
                self.inner.fit(X, y)
                return self

            @property
            def classes_(self):
                return self.inner.classes_

            def predict_proba(self, X):
                fits.append((self.train, set(matches.loc[X.index, "Season"])))
                return self.inner.predict_proba(X)

        model.make_model = Recorder
        try:
            oos = oos_module.build_oos(path)
        finally:
            model.make_model = real

    assert fits
    for train, predict in fits:
        assert len(predict) == 1 and max(train) < min(predict)

    first = sorted(matches["Season"].unique())[0]
    assert (oos["TrainedOn"].str[:5] == first).all()
    assert (oos["TrainedOn"].str[-5:] < oos["Season"]).all()


def test_variant_weeks_log():

    from betting.variants import load_variant_weeks, log_variant_weeks, weekly_pnl

    pnl = weekly_pnl(["w2", "w1", "w2"], [1.0, -1.0, 0.5])
    assert pnl.set_index("Week").to_dict() == {"profit": {"w2": 1.5, "w1": -1.0}, "staked": {"w2": 2.0, "w1": 1.0}}

    def rows(variant, frame):
        return frame.assign(family="f", variant=variant, source="avg")

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "weeks.csv.gz"
        log_variant_weeks(rows("a", pnl), "P8-03", path)
        log_variant_weeks(rows("b", pnl), "P8-04", path)
        zero = pd.DataFrame({"Week": ["w3"], "profit": [0.0], "staked": [0.0]})
        log = log_variant_weeks(pd.concat([rows("c", pnl), rows("c", zero)]), "P8-03", path)  # replaces P8-03

        assert sorted(set(zip(log["ticket"], log["variant"]))) == [("P8-03", "c"), ("P8-04", "b")]
        assert "w3" not in set(load_variant_weeks(path)["Week"])  # weeks without a stake are dropped
        try:
            log_variant_weeks(rows("a", pd.concat([pnl, pnl])), "P8-03", path)
        except ValueError:
            pass
        else:
            raise AssertionError("duplicate weeks should be rejected")


def test_variant_log_replaces_a_tickets_rows():

    from betting.variants import COLUMNS, load_variants, log_variants

    def rows(ticket_variants):
        return pd.DataFrame([
            {c: 0 for c in COLUMNS if c != "ticket"} | {"family": "f", "variant": v, "source": "avg", "period": "tune"}
            for v in ticket_variants
        ])

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "variants.csv"
        assert load_variants(path).empty
        log_variants(rows(["a", "b"]), "P8-03", path)
        log_variants(rows(["c"]), "P8-04", path)
        log = log_variants(rows(["a"]), "P8-03", path)  # re-run replaces P8-03 only

        assert sorted(zip(log["ticket"], log["variant"])) == [("P8-03", "a"), ("P8-04", "c")]
        assert len(load_variants(path)) == 2

        try:
            log_variants(rows(["a", "a"]), "P8-03", path)
        except ValueError:
            pass
        else:
            raise AssertionError("duplicate variants should be refused")


# ============================================================
# VALUE BETS AND STAKING (P8-04)
# ============================================================

def test_value_selection_picks_largest_edge_within_filters():
    from betting.staking import value_selection

    p = np.array([[0.50, 0.30, 0.20],    # edges 0.0, -0.1, +0.2 -> A
                  [0.40, 0.30, 0.30],    # edges -0.2, -0.1, -0.1 -> none
                  [0.60, 0.25, 0.15]])   # edges +0.2, 0.0, NaN -> H
    odds = np.array([[2.0, 3.0, 6.0], [2.0, 3.0, 3.0], [2.0, 4.0, np.nan]])

    sel, edge = value_selection(p, odds)
    assert sel.tolist() == [2, -1, 0]
    assert np.allclose(edge[[0, 2]], [0.2, 0.2]) and np.isnan(edge[1])

    # Odds cap drops the 6.0 away price; the home edge of 0 still qualifies at e = 0
    sel, _ = value_selection(p, odds, odds_range=(1.5, 5.0))
    assert sel.tolist() == [0, -1, 0]
    sel, _ = value_selection(p, odds, min_edge=0.05, odds_range=(1.5, 5.0))
    assert sel.tolist() == [-1, -1, 0]

    # Sharp-line filter
    sharp = np.array([[True, True, False], [True] * 3, [False, True, True]])
    sel, _ = value_selection(p, odds, sharp=sharp)
    assert sel.tolist() == [0, -1, 1]


def test_kelly_and_plans():
    from betting.staking import edge_plan, flat_plan, kelly_fraction, kelly_plan, percent_plan

    assert np.isclose(kelly_fraction(0.5, 3.0), 0.25)       # (1.5 - 1) / 2
    assert kelly_fraction(0.3, 3.0) == 0                     # negative edge -> no bet

    p, odds = np.array([0.5, 0.5]), np.array([3.0, 3.0])
    edge = p * odds - 1
    assert flat_plan(1)(p, odds, edge, None).tolist() == [1, 1]
    assert np.allclose(edge_plan(10)(p, odds, edge, None), [5, 5])
    assert np.allclose(percent_plan(0.01)(p, odds, edge, 200), [2, 2])
    # quarter Kelly = 6.25% each, capped to 5% per bet; week total 10% is under 20%
    assert np.allclose(kelly_plan(0.25)(p, odds, edge, 100), [5, 5])
    # full Kelly 25% each -> 5% cap each; with a 6% week cap, 3% each
    assert np.allclose(kelly_plan(1.0, bet_cap=0.05, week_cap=0.06)(p, odds, edge, 100), [3, 3])


def test_value_strategy_in_simulator():
    from betting.staking import bankroll_stats, kelly_plan, value_selection, value_strategy

    # a: p(H) = 0.5 at 3.0 -> edge 0.5, wins. b: no value (p = 0.5/0.3/0.2 at 2/3/4: edges 0, -0.1, -0.2)
    frame = _frame([
        _match("a", "2022-08-20 15:00", "H", 2, 0, odds=(3.0, 3.0, 4.0)),
        _match("b", "2022-08-21 15:00", "D", 1, 1),
    ])

    def rule(week):
        p = week[["pH", "pD", "pA"]].to_numpy()
        return value_selection(p, week[["oH", "oD", "oA"]].to_numpy(), min_edge=0.01)

    r = simulate(frame, value_strategy(rule))
    assert r.bets["stake"].tolist() == [1.0] and np.isclose(r.bets["profit"].sum(), 2.0)

    # Quarter Kelly: 0.25 * 0.25 = 6.25% -> capped at 5 of 100; wins 10
    r = simulate(frame, value_strategy(rule, kelly_plan(0.25)), bankroll=100)
    assert np.isclose(r.bets["stake"].iloc[0], 5.0)
    stats = bankroll_stats(r)
    assert np.isclose(stats["final_bankroll"], 110.0) and stats["max_drawdown"] == 0


def test_ruin_probability():
    from betting.staking import ruin_probability

    losing = pd.DataFrame({"profit": [-10.0] * 10, "bankroll_start": np.linspace(100, 10, 10),
                           "bankroll_end": np.linspace(90, 0, 10)})
    assert ruin_probability(losing, 100, multiplicative=False) == 1.0
    flat = pd.DataFrame({"profit": [0.0] * 5, "bankroll_start": [100.0] * 5, "bankroll_end": [100.0] * 5})
    assert ruin_probability(flat, 100) == 0.0
    assert ruin_probability(flat, 100, multiplicative=False) == 0.0


# ============================================================
# Goals markets (P8-06)
# ============================================================

def test_goals_grid_and_rates():
    from betting.goals import hda, p_over, poisson_grid, rates_from_hda
    from tie_progression import poisson_rates

    grid = poisson_grid([1.5], [1.0])
    assert np.isclose(grid.sum(), 1.0)
    # P(total > 2.5) for Poisson(2.5) total
    from scipy.stats import poisson
    assert np.isclose(p_over(grid)[0], 1 - poisson.cdf(2, 2.5), atol=1e-9)

    p_home, p_away = np.array([0.45, 0.62, 0.15]), np.array([0.28, 0.14, 0.62])
    lh, la = rates_from_hda(p_home, p_away)
    probs = hda(poisson_grid(lh, la))
    assert np.allclose(probs[:, 0], p_home, atol=1e-9) and np.allclose(probs[:, 2], p_away, atol=1e-9)
    for i in range(3):
        assert np.allclose((lh[i], la[i]), poisson_rates(p_home[i], p_away[i]), atol=1e-4)


def test_ah_expected_return_matches_settlement():
    from betting.goals import (
        MARGINS, ah_expected_return, ah_fair_probability, margin_pmf, poisson_grid,
    )
    from betting.simulate import Leg, leg_return

    pmf = margin_pmf(poisson_grid([1.6, 0.9], [1.1, 1.4]))
    for line in [-1.75, -1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 1.25]:
        lines = np.full(2, line)
        for side in "HA":
            ev = ah_expected_return(pmf, lines, 1.93, side)
            for i in range(2):
                brute = sum(
                    p * leg_return({"FTR": "?", "FTHG": max(d, 0), "FTAG": max(-d, 0), "AHh": line},
                                   Leg("m", side, "AH"), 1.93)
                    for d, p in zip(MARGINS, pmf[i])
                )
                assert np.isclose(ev[i], brute), (line, side)
            # at fair odds the bet breaks even
            fair = 1 / ah_fair_probability(pmf, lines, side)
            assert np.allclose(ah_expected_return(pmf, lines, fair, side), 1.0)
        both = ah_fair_probability(pmf, lines, "H") + ah_fair_probability(pmf, lines, "A")
        assert np.allclose(both, 1.0)


def test_ah_log_loss_quarter_and_push():
    from betting.goals import ah_log_loss

    p = np.full(4, 0.6)
    # margins: draw on -0.25 (half pushed, half lost), win by 1 on -1 (push),
    # win by 1 on -0.75 (half won, half pushed), away win on -0.5 (lost)
    loss, weight = ah_log_loss(p, np.array([0, 1, 1, -1]), np.array([-0.25, -1.0, -0.75, -0.5]))
    assert np.allclose(weight, [0.5, 0.0, 0.5, 1.0])
    assert np.allclose(loss, [-np.log(0.4) / 2, 0.0, -np.log(0.6) / 2, -np.log(0.4)])


def test_clean_two_way():
    from betting.goals import clean_two_way

    frame = pd.DataFrame({
        "AvgAHH": [1.90, 1.82, 1.95], "AvgAHA": [1.95, 4.10, 1.90],      # row 1: booksum 0.79
        "Max>2.5": [2.10, 2.00, 1.60], "Max<2.5": [1.95, 1.90, -0.25],   # row 0: 0.99 is fine for max
    })
    out, removed = clean_two_way(frame)
    assert out["AvgAHH"].isna().tolist() == [False, True, False]
    assert out["Max>2.5"].isna().tolist() == [False, False, True]
    assert removed["AvgAHH/AvgAHA"] == 1 and removed["Max>2.5/Max<2.5"] == 1


if __name__ == "__main__":
    for name, test in list(globals().items()):
        if name.startswith("test_"):
            test()
            print(f"ok  {name}")
