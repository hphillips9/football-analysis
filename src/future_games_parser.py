import re

import pandas as pd

from team_names import load_alias_map, normalize_team_names

INPUT_PATH = "data/raw/Next_Matchweek.txt"
OUTPUT_PATH = "data/raw/Future_Fixtures.csv"

SEASON_START_YEAR = 2026

DAY_HEADER_RE = re.compile(
    r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun) (\d{1,2}) "
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)$"
)
TIME_RE = re.compile(r"^\d{2}:\d{2}$")
GAMEWEEK_RE = re.compile(r"^(?:GW|Gameweek)\s*(\d{1,2})$", re.IGNORECASE)

MONTH_NUMBERS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12
}


def read_lines(input_path):

    with open(input_path, encoding="utf-8") as f:
        lines = [line.strip() for line in f]

    return [line for line in lines if line]


def take_gameweek(lines):
    """
    Pull an optional leading 'GW<n>' / 'Gameweek <n>' line off the top of
    the pasted text. Returns (gameweek_or_None, remaining_lines).
    """

    if lines:
        match = GAMEWEEK_RE.match(lines[0])
        if match:
            return int(match.group(1)), lines[1:]

    return None, lines


def resolve_year(month_number, season_start_year):

    # Season runs Aug-May, so Jan-Jul dates belong to the following year
    if month_number >= 8:
        return season_start_year

    return season_start_year + 1


def parse_fixtures(lines, season_start_year=SEASON_START_YEAR):

    fixtures = []
    current_date = None

    for i, line in enumerate(lines):

        day_match = DAY_HEADER_RE.match(line)

        if day_match:

            _, day_number, month_name = day_match.groups()
            month_number = MONTH_NUMBERS[month_name]
            year = resolve_year(month_number, season_start_year)

            current_date = f"{int(day_number):02d}/{month_number:02d}/{year}"
            continue

        if TIME_RE.match(line):

            if current_date is None:
                raise ValueError(
                    f"Found kickoff time {line!r} before any day header"
                )

            if i == 0 or i == len(lines) - 1:
                raise ValueError(
                    f"Kickoff time {line!r} is missing a team on one side"
                )

            fixtures.append({
                "Div": "E0",
                "Date": current_date,
                "Time": line,
                "HomeTeam": lines[i - 1],
                "AwayTeam": lines[i + 1]
            })

    return fixtures


def build_future_fixtures(
    input_path=INPUT_PATH,
    output_path=OUTPUT_PATH,
    season_start_year=SEASON_START_YEAR
):

    lines = read_lines(input_path)
    gameweek, lines = take_gameweek(lines)
    fixtures = parse_fixtures(lines, season_start_year)

    if not fixtures:
        raise ValueError("No fixtures found - check the pasted matchweek text.")

    future = pd.DataFrame(fixtures)

    if gameweek is not None:
        future.insert(0, "Gameweek", gameweek)

    alias_map = load_alias_map()

    future["HomeTeam"] = normalize_team_names(
        future["HomeTeam"], alias_map, source_name="Premier League fixtures"
    )
    future["AwayTeam"] = normalize_team_names(
        future["AwayTeam"], alias_map, source_name="Premier League fixtures"
    )

    future.to_csv(output_path, index=False)

    print(f"Wrote {len(future)} fixture(s) to {output_path}:")
    print(future.to_string(index=False))

    return future


if __name__ == "__main__":
    build_future_fixtures()
