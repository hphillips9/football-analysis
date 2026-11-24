"""
Tests for the longer-history research path (P9-03): older football-data
files, load_data's history_start, the shots-based xG proxy and
backtest.prepare_matches' train_start.

    python tests/test_history.py     (or pytest tests/)
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
import load_data

OLD_FILE = (
    "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HS,AS,HST,AST,BbAvH,BbAvD,BbAvA,BbMxH,BbMxD,BbMxA\n"
    "E0,14/08/10,Aston Villa,West Ham,3,0,H,23,12,11,2,1.7,3.6,5.2,1.8,3.8,5.6\n"
    "E0,15/08/10,Wigan ,Blackpool,0,4,A,10,11,5,7,1.6,3.8,6.0,1.7,4.0,6.5\n"
    ",,,,,,,,,,,,,,,,\n"
)
LIVE_FILE = (
    "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,AvgH,AvgD,AvgA\n"
    "E0,13/08/2021,20:00,Brentford,Arsenal,2,0,H,4.0,3.5,1.9\n"
)


def _raw_dir(tmp):
    raw = Path(tmp)
    (raw / "E0" / "history").mkdir(parents=True)
    (raw / "E0" / "results_21-22.csv").write_text(LIVE_FILE)
    (raw / "E0" / "history" / "results_10-11.csv").write_text(OLD_FILE)
    (raw / "E0" / "history" / "results_09-10.csv").write_text(OLD_FILE.replace("/10,", "/09,"))
    # A season in both places: the live copy wins
    (raw / "E0" / "history" / "results_21-22.csv").write_text(OLD_FILE)
    return raw


def test_old_file_takes_the_live_shape():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "results_10-11.csv"
        path.write_text(OLD_FILE)
        df = load_data._read_history_results(path, "E0")

    assert len(df) == 2  # the blank row is gone
    assert df["Date"].tolist() == ["14/08/2010", "15/08/2010"]
    assert df["Time"].tolist() == [load_data.HISTORY_KICKOFF] * 2
    assert df["HomeTeam"].tolist() == ["Aston Villa", "Wigan"]
    assert df["AvgH"].tolist() == [1.7, 1.6] and df["MaxA"].tolist() == [5.6, 6.5]


def test_history_only_when_asked_and_live_wins():
    with tempfile.TemporaryDirectory() as tmp:
        raw = _raw_dir(tmp)
        live = load_data.load_result_files(["E0"], raw)
        longer = load_data.load_result_files(["E0"], raw, history_start="10-11")

    assert live["Season"].unique().tolist() == ["21-22"]
    assert sorted(longer["Season"].unique()) == ["10-11", "21-22"]  # 09-10 is before the start
    assert longer.loc[longer["Season"] == "21-22", "HomeTeam"].tolist() == ["Brentford"]
    assert longer["Gameweek"].tolist() == [1, 1, 1]


def test_shots_proxy_fits_and_fills_only_gaps():
    rng = np.random.default_rng(0)
    n = 200
    shots = rng.integers(3, 25, size=(n, 2))
    on_target = np.minimum(shots, rng.integers(0, 10, size=(n, 2)))
    xg = 0.05 + 0.06 * shots + 0.12 * on_target
    matches = pd.DataFrame({
        "HS": shots[:, 0], "AS": shots[:, 1], "HST": on_target[:, 0], "AST": on_target[:, 1],
        "HomeXG": xg[:, 0], "AwayXG": xg[:, 1], "XGSource": "FotMob",
    })

    coef, r2 = load_data.fit_xg_proxy(matches)
    assert np.allclose(coef, [0.05, 0.06, 0.12]) and r2 > 0.999

    matches.loc[[0, 1], ["HomeXG", "AwayXG", "XGSource"]] = [np.nan, np.nan, None]
    matches.loc[1, "HS"] = np.nan  # no shots either: stays missing
    filled = load_data.fill_xg_proxy(matches, coef)

    assert filled.loc[0, "XGSource"] == load_data.XG_PROXY_SOURCE
    assert np.isclose(filled.loc[0, "HomeXG"], xg[0, 0])
    assert pd.isna(filled.loc[1, "HomeXG"]) and pd.isna(filled.loc[1, "XGSource"])
    assert (filled.loc[2:, "XGSource"] == "FotMob").all()


def test_stats_proxy_first_then_shots_and_proxies_never_fit_on_proxies():
    rng = np.random.default_rng(2)
    n = 300
    frame = {}
    for side in ("Home", "Away"):
        inside, outside = rng.integers(2, 15, n), rng.integers(1, 10, n)
        on_target, chances = rng.integers(0, 8, n), rng.integers(0, 4, n)
        frame.update({
            f"{side}_shots_inside_box": inside, f"{side}_shots_outside_box": outside,
            f"{side}_ShotsOnTarget": on_target, f"{side}_big_chance": chances,
            f"{side}XG": 0.03 + 0.07 * inside + 0.02 * outside + 0.02 * on_target + 0.3 * chances,
        })
    matches = pd.DataFrame(frame)
    matches["HS"] = matches["Home_shots_inside_box"] + matches["Home_shots_outside_box"]
    matches["AS"] = matches["Away_shots_inside_box"] + matches["Away_shots_outside_box"]
    matches["HST"], matches["AST"] = matches["Home_ShotsOnTarget"], matches["Away_ShotsOnTarget"]
    matches["XGSource"] = "FotMob"
    truth = matches[["HomeXG", "AwayXG"]].copy()

    # Rows 0-9: no xG but stats; rows 10-19: no xG, shots only
    matches.loc[0:19, ["HomeXG", "AwayXG"]] = np.nan
    matches.loc[0:19, "XGSource"] = None
    matches.loc[10:19, [c for pair in load_data.STATS_FEATURES for c in pair]] = np.nan

    for features, source in (
        (load_data.STATS_FEATURES, load_data.STATS_PROXY_SOURCE),
        (load_data.SHOTS_FEATURES, load_data.XG_PROXY_SOURCE),
    ):
        coef, _ = load_data.fit_xg_proxy(matches, features)
        matches = load_data.fill_xg_proxy(matches, coef, features, source)

    assert (matches.loc[0:9, "XGSource"] == load_data.STATS_PROXY_SOURCE).all()
    assert np.allclose(matches.loc[0:9, "HomeXG"], truth.loc[0:9, "HomeXG"])
    assert (matches.loc[10:19, "XGSource"] == load_data.XG_PROXY_SOURCE).all()
    # The shots fit used only real-xG rows, not the stats-proxy ones
    assert (matches.loc[20:, "XGSource"] == "FotMob").all()


def _matches(seasons):
    rng = np.random.default_rng(1)
    teams = list("ABCDEF")
    rows = []
    for season in seasons:
        start = pd.Timestamp(f"20{season[:2]}-08-10")
        for week, (home, away) in enumerate(itertools.permutations(teams, 2)):
            goals = rng.integers(0, 4, size=2)
            rows.append({
                "Div": "E0", "Season": season, "Gameweek": week // 3 + 1,
                "MatchDateTime": start + pd.Timedelta(days=3 * week),
                "HomeTeam": home, "AwayTeam": away, "FTHG": goals[0], "FTAG": goals[1],
                "FTR": "H" if goals[0] > goals[1] else "A" if goals[0] < goals[1] else "D",
                "HomeXG": 1.2, "AwayXG": 1.0,
            })
    return pd.DataFrame(rows)


def test_train_start_drops_warm_up_and_covid_but_keeps_their_ratings():
    seasons = ["17-18", "18-19", "19-20", "20-21", "21-22", "22-23"]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "all_matches.csv"
        _matches(seasons).to_csv(path, index=False)

        minimum, backtest.MIN_SEASON_MATCHES = backtest.MIN_SEASON_MATCHES, 1
        try:
            full, all_seasons, _ = backtest.prepare_matches(path)
            cut, cut_seasons, tests = backtest.prepare_matches(path, train_start="18-19")
        finally:
            backtest.MIN_SEASON_MATCHES = minimum

    assert all_seasons == seasons
    assert cut_seasons == ["18-19", "21-22", "22-23"] and tests == ["21-22", "22-23"]

    # Features were built over the whole history before the cut
    kept = full[full["Season"].isin(cut_seasons)].reset_index(drop=True)
    assert np.allclose(cut["EloDiff"], kept["EloDiff"])
    assert cut.loc[cut["Season"] == "18-19", "EloDiff"].abs().sum() > 0


if __name__ == "__main__":
    for name, test in list(globals().items()):
        if name.startswith("test_"):
            test()
            print(f"ok  {name}")
