import pandas as pd

REFERENCE_PATH = "data/reference/team_names.csv"

ALIAS_COLUMNS = [
    "canonical_name",
    "football_data_name",
    "understat_name",
    "bbc_name",
    "football_data_org_name",
    "fotmob_name"
]

# Source team ids - stable across competitions (a club's FotMob id is the
# same in its league and the CL), so they join without name matching
ID_COLUMNS = ["fotmob_id", "football_data_org_id"]

REFERENCE_COLUMNS = [
    "canonical_name", "country", *ID_COLUMNS, *ALIAS_COLUMNS[1:],
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


def load_id_map(id_column="fotmob_id", reference_path=REFERENCE_PATH):
    """Source team id -> canonical name, e.g. load_id_map()[9825] -> "Arsenal"."""

    reference = pd.read_csv(reference_path, dtype={id_column: "Int64"})
    known = reference.dropna(subset=[id_column])

    return dict(zip(known[id_column].astype(int), known["canonical_name"]))


def load_country_map(reference_path=REFERENCE_PATH):
    """Canonical name -> country code ("ENG", "ESP", ...)."""

    reference = pd.read_csv(reference_path)

    return dict(zip(reference["canonical_name"], reference["country"]))


def normalize_team_names(teams, alias_map, source_name="unknown source"):

    unknown = sorted(set(teams) - set(alias_map))

    if unknown:
        raise ValueError(
            f"Unrecognised team name(s) from {source_name}: {unknown}. "
            f"Add them to {REFERENCE_PATH} before continuing."
        )

    return teams.replace(alias_map)
