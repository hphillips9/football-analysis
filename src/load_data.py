import pandas as pd
import os
import glob
import penaltyblog as pb


# ============================================================
# LOAD EXISTING MATCH DATA
# ============================================================

csv_files = glob.glob(os.path.join("data/raw", "*.csv"))

all_dfs = []

for f in csv_files:

    # Don't accidentally load an Understat CSV
    if "understat" in os.path.basename(f).lower():
        continue

    df = pd.read_csv(f)

    filename = (
        os.path.basename(f)
        .replace(".csv", "")
        .replace("EPL", "")
    )

    # Add season
    df.insert(0, "Season", filename)

    all_dfs.append(df)


matches = pd.concat(
    all_dfs,
    ignore_index=True
)


# ============================================================
# CREATE DATETIME
# ============================================================

matches["MatchDateTime"] = pd.to_datetime(
    matches["Date"] + " " + matches["Time"],
    dayfirst=True
)

matches = (
    matches
    .sort_values("MatchDateTime")
    .reset_index(drop=True)
)


# ============================================================
# TEAM NAME NORMALISATION
# ============================================================

team_name_map = {

    # Manchester
    "Man United": "Manchester United",
    "Manchester Utd": "Manchester United",
    "Man Utd": "Manchester United",

    "Man City": "Manchester City",
    "Manchester City": "Manchester City",

    # Nottingham Forest
    "Nott'm Forest": "Nottingham Forest",
    "Nott'm Forest": "Nottingham Forest",
    "Nottingham Forest": "Nottingham Forest",

    # Wolves
    "Wolves": "Wolverhampton Wanderers",
    "Wolverhampton": "Wolverhampton Wanderers",
    "Wolverhampton Wanderers": "Wolverhampton Wanderers",

    # Newcastle
    "Newcastle": "Newcastle United",
    "Newcastle Utd": "Newcastle United",
    "Newcastle United": "Newcastle United",

    # West Ham
    "West Ham": "West Ham United",
    "West Ham United": "West Ham United",

    # Brighton
    "Brighton": "Brighton and Hove Albion",
    "Brighton & Hove Albion": "Brighton and Hove Albion",
    "Brighton and Hove Albion": "Brighton and Hove Albion",

    # Leeds
    "Leeds": "Leeds United",
    "Leeds United": "Leeds United",

    # Leicester
    "Leicester": "Leicester City",
    "Leicester City": "Leicester City",

    # Norwich
    "Norwich": "Norwich City",
    "Norwich City": "Norwich City",

    # Tottenham
    "Tottenham": "Tottenham Hotspur",
    "Tottenham Hotspur": "Tottenham Hotspur",

    # Other teams
    "Arsenal": "Arsenal",
    "Aston Villa": "Aston Villa",
    "Bournemouth": "Bournemouth",
    "Brentford": "Brentford",
    "Burnley": "Burnley",
    "Chelsea": "Chelsea",
    "Crystal Palace": "Crystal Palace",
    "Everton": "Everton",
    "Fulham": "Fulham",
    "Liverpool": "Liverpool",
    "Sunderland": "Sunderland",
}


# Keep original names for debugging
matches["OriginalHomeTeam"] = matches["HomeTeam"]
matches["OriginalAwayTeam"] = matches["AwayTeam"]

matches["HomeTeam"] = matches["HomeTeam"].replace(team_name_map)
matches["AwayTeam"] = matches["AwayTeam"].replace(team_name_map)


# ============================================================
# UNDERSTAT SEASONS
# ============================================================

seasons = {
    "21-22": "2021-2022",
    "22-23": "2022-2023",
    "23-24": "2023-2024",
    "24-25": "2024-2025",
    "25-26": "2025-2026"
}


# ============================================================
# DOWNLOAD UNDERSTAT DATA
# ============================================================

understat_matches = []

for season_name, understat_season in seasons.items():

    print(f"Downloading Understat {season_name}...")

    under = pb.scrapers.Understat(
        "ENG Premier League",
        understat_season
    )

    fixtures = under.get_fixtures()

    fixtures["Season"] = season_name

    understat_matches.append(fixtures)


understat = pd.concat(
    understat_matches,
    ignore_index=True
)


# ============================================================
# SELECT XG COLUMNS
# ============================================================

understat = understat[
    [
        "Season",
        "team_home",
        "team_away",
        "xg_home",
        "xg_away"
    ]
].copy()


# ============================================================
# RENAME UNDERSTAT COLUMNS
# ============================================================

understat = understat.rename(columns={
    "team_home": "HomeTeam",
    "team_away": "AwayTeam",
    "xg_home": "HomeXG",
    "xg_away": "AwayXG"
})


# ============================================================
# NORMALISE UNDERSTAT TEAM NAMES TOO
# ============================================================

understat["HomeTeam"] = understat["HomeTeam"].replace(team_name_map)
understat["AwayTeam"] = understat["AwayTeam"].replace(team_name_map)


# ============================================================
# CHECK TEAM NAMES
# ============================================================

print()
print("=" * 70)
print("TEAM NAME CHECK")
print("=" * 70)

your_teams = set(matches["HomeTeam"].unique())
understat_teams = set(understat["HomeTeam"].unique())

print("Teams in your data but NOT Understat:")
print(sorted(your_teams - understat_teams))

print()

print("Teams in Understat but NOT your data:")
print(sorted(understat_teams - your_teams))


# ============================================================
# CHECK UNDERSTAT DATA
# ============================================================

print()
print("=" * 70)
print("UNDERSTAT DATA")
print("=" * 70)

print("Understat matches:", len(understat))
print("Missing HomeXG:", understat["HomeXG"].isna().sum())
print("Missing AwayXG:", understat["AwayXG"].isna().sum())


# ============================================================
# REMOVE DUPLICATE UNDERSTAT FIXTURES
# ============================================================

understat = understat.drop_duplicates(
    subset=[
        "Season",
        "HomeTeam",
        "AwayTeam"
    ]
)


# ============================================================
# MERGE XG
# ============================================================

matches = matches.merge(
    understat[
        [
            "Season",
            "HomeTeam",
            "AwayTeam",
            "HomeXG",
            "AwayXG"
        ]
    ],
    on=[
        "Season",
        "HomeTeam",
        "AwayTeam"
    ],
    how="left"
)


# ============================================================
# CHECK MISSING XG
# ============================================================

missing_xg = matches[
    matches["HomeXG"].isna() |
    matches["AwayXG"].isna()
].copy()


print()
print("=" * 70)
print("XG COVERAGE")
print("=" * 70)

print("Total matches:", len(matches))
print("Matches with xG:", len(matches) - len(missing_xg))
print("Missing xG:", len(missing_xg))

print(
    "Coverage:",
    f"{((len(matches) - len(missing_xg)) / len(matches) * 100):.2f}%"
)


# ============================================================
# COVERAGE BY SEASON
# ============================================================

coverage = (
    matches
    .assign(
        HasXG=(
            matches["HomeXG"].notna() &
            matches["AwayXG"].notna()
        )
    )
    .groupby("Season")
    .agg(
        Games=("HomeTeam", "size"),
        GamesWithXG=("HasXG", "sum")
    )
)

coverage["Missing"] = (
    coverage["Games"] -
    coverage["GamesWithXG"]
)

coverage["Coverage"] = (
    coverage["GamesWithXG"] /
    coverage["Games"] *
    100
)

print()
print("=" * 70)
print("XG COVERAGE BY SEASON")
print("=" * 70)

print(coverage)


# ============================================================
# DISPLAY MISSING FIXTURES
# ============================================================

if len(missing_xg) > 0:

    print()
    print("=" * 70)
    print("MISSING XG FIXTURES")
    print("=" * 70)

    print(
        missing_xg[
            [
                "Season",
                "Date",
                "OriginalHomeTeam",
                "OriginalAwayTeam"
            ]
        ].to_string(index=False)
    )


# ============================================================
# REMOVE DEBUG COLUMNS
# ============================================================

matches = matches.drop(
    columns=[
        "OriginalHomeTeam",
        "OriginalAwayTeam"
    ]
)


# ============================================================
# SAVE
# ============================================================

matches.to_csv(
    "data/processed/all_matches.csv",
    index=False
)

print()
print("=" * 70)
print("SAVED")
print("=" * 70)

print("data/processed/all_matches.csv")