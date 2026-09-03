import pandas as pd

from team_names import load_alias_map

SEASON_URL = "https://www.football-data.co.uk/mmz4281/2627/E0.csv"
LOCAL_PATH = "data/raw/EPL26-27.csv"
BETS_PATH = "data/raw/Bets.csv"
KEY_COLUMNS = ["HomeTeam", "AwayTeam"]

STAKE = 1
ODDS_COLUMN = {"H": "SKBH", "D": "SKBD", "A": "SKBA"}
FALLBACK_ODDS_COLUMN = {"H": "AvgH", "D": "AvgD", "A": "AvgA"}


def fetch_new_results(season_url=SEASON_URL, local_path=LOCAL_PATH):

    remote = pd.read_csv(season_url)
    local = pd.read_csv(local_path)

    existing_keys = set(
        local[KEY_COLUMNS].itertuples(index=False, name=None)
    )

    remote_keys = remote[KEY_COLUMNS].apply(tuple, axis=1)

    new_rows = remote[~remote_keys.isin(existing_keys)]

    if new_rows.empty:
        print("No new results - local file is already up to date.")
        return new_rows

    alias_map = load_alias_map()

    unknown = sorted(
        (set(new_rows["HomeTeam"]) | set(new_rows["AwayTeam"]))
        - set(alias_map)
    )

    if unknown:
        raise ValueError(
            f"Unrecognised team name(s) in new results: {unknown}. "
            f"Add them to data/reference/team_names.csv before continuing."
        )

    updated = pd.concat([local, new_rows], ignore_index=True)
    updated.to_csv(local_path, index=False)

    print(f"Added {len(new_rows)} new result(s):")
    print(
        new_rows[["Date", "HomeTeam", "AwayTeam", "FTR"]]
        .to_string(index=False)
    )

    return new_rows

def settle_profit(predicted, actual, odds):

    if pd.isna(actual):
        return None

    if predicted == actual:
        return round(STAKE * (odds - 1), 2)

    return float(-STAKE)


def complete_bets(bets_path=BETS_PATH, local_path=LOCAL_PATH):

    bets = pd.read_csv(bets_path)
    results = pd.read_csv(local_path)

    alias_map = load_alias_map()

    result_keys = zip(
        results["HomeTeam"].replace(alias_map),
        results["AwayTeam"].replace(alias_map)
    )

    results_by_fixture = {
        key: row
        for key, (_, row) in zip(result_keys, results.iterrows())
    }

    pending = bets.index[bets["ActualResult"].isna()]

    settled = []

    for i in pending:

        key = (
            alias_map.get(bets.at[i, "HomeTeam"], bets.at[i, "HomeTeam"]),
            alias_map.get(bets.at[i, "AwayTeam"], bets.at[i, "AwayTeam"])
        )

        match = results_by_fixture.get(key)

        if match is None:
            continue

        predicted = bets.at[i, "PredictedResult"]
        actual = match["FTR"]

        odds = match[ODDS_COLUMN[predicted]]

        if pd.isna(odds):
            odds = match[FALLBACK_ODDS_COLUMN[predicted]]

        bets.at[i, "ActualResult"] = actual
        bets.at[i, "Bet"] = STAKE
        bets.at[i, "Profit"] = settle_profit(predicted, actual, odds)

        settled.append(i)

    if not settled:
        print("No pending bets have results yet.")
        return bets

    bets["Bet"] = bets["Bet"].astype("Int64")
    bets.to_csv(bets_path, index=False)

    total = bets.loc[settled, "Profit"].sum()

    print(f"Settled {len(settled)} bet(s) ({total:+.2f} units):")
    print(
        bets.loc[
            settled,
            ["Date", "HomeTeam", "AwayTeam",
             "PredictedResult", "ActualResult", "Profit"]
        ].to_string(index=False)
    )

    return bets


if __name__ == "__main__":
    fetch_new_results()
    complete_bets()