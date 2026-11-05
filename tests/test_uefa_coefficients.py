"""
Tests for the kassiesa.net country-ranking parser.

    python tests/test_uefa_coefficients.py     (or pytest tests/)
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "tools"))

from fetch_uefa_coefficients import parse_ranking

# The shape of kassiesa.net's crank<year>.html table, trimmed to two rows
PAGE = """
<table class="t1">
<tr class="countryheader"><th>#</th><th></th><th>country</th><th>21/22</th>
<th>22/23</th><th>23/24</th><th>24/25</th><th>25/26</th><th>ranking</th><th>teams</th></tr>
<tr class="countryline"><td>1</td><td></td><td>England</td><td>21.000</td><td>23.000</td>
<td>17.375</td><td>29.464</td><td>28.680</td><td>119.519</td><td> 9</td></tr>
<tr class="countryline"><td>36</td><td></td><td>Türkiye</td><td>1.0</td><td>1.0</td>
<td>1.0</td><td>1.0</td><td>1.0</td><td>51.875</td><td> 5</td></tr>
</table>
"""


def test_parses_codes_coefficients_and_ranks():
    rows = parse_ranking(PAGE, "26-27")

    assert rows.to_dict("records") == [
        {"country": "ENG", "season": "26-27", "coefficient": 119.519, "rank": 1},
        {"country": "TUR", "season": "26-27", "coefficient": 51.875, "rank": 36},
    ]


def test_unknown_country_is_an_error():
    try:
        parse_ranking(PAGE.replace("England", "Atlantis"), "26-27")
        raise AssertionError("expected an unknown country to raise")
    except ValueError as exc:
        assert "Atlantis" in str(exc)


if __name__ == "__main__":
    for name, test in list(globals().items()):
        if name.startswith("test_"):
            test()
            print(f"ok  {name}")
