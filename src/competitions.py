"""
Every competition the pipeline knows about, and which ones it runs.

One entry per competition, keyed by its football-data.co.uk division code
("CL" for the Champions League, which football-data.co.uk doesn't carry):

    name          display name
    kind          "league" or "cup"
    country       ISO-like country code (None for a European cup)
    fd_uk         football-data.co.uk division code (results + odds CSVs)
    fd_org        football-data.org competition code (fixtures API)
    fotmob        FotMob league id (xG)
    understat     Understat competition name (backup xG), or None
    features      "full" (Elo + xG + goals) or "elo_only" (results only)
    promoted_elo  starting Elo for a promoted club, or None to carry its
                  old rating over (see notebooks 19 and 20)
    model         "pooled" (the model shared across competitions) or "own"
                  (one trained on this competition alone) - see model.py

Adding a league means one entry here plus its rows in
data/reference/team_names.csv. Only codes in ENABLED are run.
"""


COMPETITIONS = {
    "E0": dict(
        name="Premier League", kind="league", country="ENG",
        fd_uk="E0", fd_org="PL", fotmob=47, understat="ENG Premier League",
        features="full", promoted_elo=None, model="own",
    ),
    "SP1": dict(
        name="La Liga", kind="league", country="ESP",
        fd_uk="SP1", fd_org="PD", fotmob=87, understat="ESP La Liga",
        features="full", promoted_elo=None, model="pooled",
    ),
    "D1": dict(
        name="Bundesliga", kind="league", country="GER",
        fd_uk="D1", fd_org="BL1", fotmob=54, understat="DEU Bundesliga 1",
        features="full", promoted_elo=None, model="pooled",
    ),
    "I1": dict(
        name="Serie A", kind="league", country="ITA",
        fd_uk="I1", fd_org="SA", fotmob=55, understat="ITA Serie A",
        features="full", promoted_elo=None, model="pooled",
    ),
    "F1": dict(
        name="Ligue 1", kind="league", country="FRA",
        fd_uk="F1", fd_org="FL1", fotmob=53, understat="FRA Ligue 1",
        features="full", promoted_elo=None, model="pooled",
    ),
    "P1": dict(
        name="Primeira Liga", kind="league", country="POR",
        fd_uk="P1", fd_org="PPL", fotmob=61, understat=None,
        features="full", promoted_elo=None, model="pooled",
    ),
    "N1": dict(
        name="Eredivisie", kind="league", country="NED",
        fd_uk="N1", fd_org="DED", fotmob=57, understat=None,
        features="full", promoted_elo=None, model="pooled",
    ),
    "CL": dict(
        name="Champions League", kind="cup", country=None,
        fd_uk=None, fd_org="CL", fotmob=42, understat=None,
        features="full", promoted_elo=None, model="pooled",
    ),
}

# Grows phase by phase (docs/multi-league-plan.md)
ENABLED = ["E0", "SP1", "D1", "I1", "F1", "P1", "N1"]

# The season live results and fixtures are fetched for. Bump it when a
# new season starts.
CURRENT_SEASON = "26-27"


def get(div):
    """The registry entry for ``div``, e.g. get("E0")["fotmob"] -> 47."""

    try:
        return COMPETITIONS[div]
    except KeyError:
        raise KeyError(
            f"Unknown competition {div!r}. Known: {', '.join(COMPETITIONS)}"
        ) from None


def enabled():
    """Division codes the pipeline runs, in ENABLED order."""

    return list(ENABLED)
