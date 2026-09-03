import pandas as pd

REFERENCE_PATH = "data/reference/team_names.csv"

ALIAS_COLUMNS = [
    "canonical_name",
    "football_data_name",
    "understat_name",
    "bbc_name"
]


def load_alias_map(reference_path=REFERENCE_PATH):

    reference = pd.read_csv(reference_path)

    alias_map = {}

    for _, row in reference.iterrows():

        canonical = row["canonical_name"]

        for column in ALIAS_COLUMNS:

            alias = row[column]

            if pd.notna(alias):
                alias_map[alias] = canonical

    return alias_map


def normalize_team_names(teams, alias_map, source_name="unknown source"):

    unknown = sorted(set(teams) - set(alias_map))

    if unknown:
        raise ValueError(
            f"Unrecognised team name(s) from {source_name}: {unknown}. "
            f"Add them to {REFERENCE_PATH} before continuing."
        )

    return teams.replace(alias_map)
