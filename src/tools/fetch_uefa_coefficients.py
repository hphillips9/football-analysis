"""
Snapshot UEFA's 5-year country coefficients, point in time, for the
league-strength Elo prior (P4-02, plan §4A.2).

    python src/tools/fetch_uefa_coefficients.py           # show what would be written
    python src/tools/fetch_uefa_coefficients.py --apply   # write it

Season "21-22" gets kassiesa.net's 2021 ranking (16/17 to 20/21): the
coefficient as it stood when that season kicked off, so nothing from
the season itself leaks in. Writes

    data/reference/uefa_country_coefficients.csv   country, season, coefficient, rank

with FotMob's country codes, the ones european.py's clubs carry.
"""

import argparse
import sys
import time
import urllib.request
from io import StringIO
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import competitions  # noqa: E402
import european  # noqa: E402
from fetch_results import REQUEST_HEADERS  # noqa: E402

URL = "https://kassiesa.net/uefa/data/method5/crank{year}.html"
OUTPUT_PATH = ROOT / "data" / "reference" / "uefa_country_coefficients.csv"
DOWNLOAD_GAP = 1.0  # seconds between kassiesa.net requests

# kassiesa.net's country names -> FotMob's codes
COUNTRY_CODES = {
    "Albania": "ALB", "Andorra": "AND", "Armenia": "ARM", "Austria": "AUT",
    "Azerbaijan": "AZE", "Belarus": "BLR", "Belgium": "BEL",
    "Bosnia-Herzegovina": "BIH", "Bulgaria": "BUL", "Croatia": "CRO",
    "Cyprus": "CYP", "Czechia": "CZE", "Denmark": "DEN", "England": "ENG",
    "Estonia": "EST", "Faroe Islands": "FRO", "Finland": "FIN", "France": "FRA",
    "Georgia": "GEO", "Germany": "GER", "Gibraltar": "GIB", "Greece": "GRE",
    "Hungary": "HUN", "Iceland": "ISL", "Ireland": "IRL", "Israel": "ISR",
    "Italy": "ITA", "Kazakhstan": "KAZ", "Kosovo": "KVX", "Latvia": "LVA",
    "Liechtenstein": "LIE", "Lithuania": "LTU", "Luxembourg": "LUX",
    "Malta": "MLT", "Moldova": "MDA", "Montenegro": "MNE",
    "Netherlands": "NED", "North Macedonia": "MKD", "Northern Ireland": "NIR",
    "Norway": "NOR", "Poland": "POL", "Portugal": "POR", "Romania": "ROU",
    "Russia": "RUS", "San Marino": "SMR", "Scotland": "SCO", "Serbia": "SRB",
    "Slovakia": "SVK", "Slovenia": "SVN", "Spain": "ESP", "Sweden": "SWE",
    "Switzerland": "SUI", "Türkiye": "TUR", "Ukraine": "UKR", "Wales": "WAL",
}

COLUMNS = ["country", "season", "coefficient", "rank"]


def seasons():
    """21-22 to the current season."""

    first = int(european.FIRST_SEASON[:2])
    last = int(competitions.CURRENT_SEASON[:2])

    return [f"{y:02d}-{y + 1:02d}" for y in range(first, last + 1)]


def parse_ranking(html, season):
    """One season's rows from a kassiesa.net crank<year>.html page."""

    table = pd.read_html(StringIO(html))[0]

    unknown = sorted(set(table["country"]) - set(COUNTRY_CODES))
    if unknown:
        raise ValueError(f"Unknown country name(s) for {season}: {unknown}; add to COUNTRY_CODES")

    return pd.DataFrame({
        "country": table["country"].map(COUNTRY_CODES),
        "season": season,
        "coefficient": table["ranking"].astype(float),
        "rank": table["#"].astype(int),
    })


def download(season):

    request = urllib.request.Request(URL.format(year=f"20{season[:2]}"), headers=REQUEST_HEADERS)

    with urllib.request.urlopen(request, timeout=30) as response:
        html = response.read().decode("utf-8")

    time.sleep(DOWNLOAD_GAP)

    return html


def missing_countries(coefficients):
    """(season, country) pairs in the European caches with no coefficient."""

    raw = european.load_cache()
    teams = european.read_teams().set_index("FotMobId")["Country"]
    clubs = pd.concat([
        raw[["Season", "HomeId"]].set_axis(["season", "id"], axis=1),
        raw[["Season", "AwayId"]].set_axis(["season", "id"], axis=1),
    ])
    needed = set(zip(clubs["season"], clubs["id"].astype(int).map(teams)))
    have = set(zip(coefficients["season"], coefficients["country"]))

    return sorted(needed - have)


def main():

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--apply", action="store_true", help=f"Write {OUTPUT_PATH.name}.")
    args = parser.parse_args()

    coefficients = pd.concat(
        [parse_ranking(download(season), season) for season in seasons()],
        ignore_index=True,
    )

    print(coefficients.pivot(index="country", columns="season", values="coefficient")
          .sort_values(coefficients["season"].max(), ascending=False).head(10).to_string())

    missing = missing_countries(coefficients)
    print(f"\nEuropean clubs' countries without a coefficient: {missing or 'none'}")

    if not args.apply:
        print("\nDry run - re-run with --apply to write it.")
        return

    coefficients[COLUMNS].to_csv(OUTPUT_PATH, index=False)
    print(f"Saved {len(coefficients)} rows to {OUTPUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
