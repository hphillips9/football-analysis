# Premier League Football Predictor

A self-updating model that predicts Premier League results. Every gameweek it
rates the two teams, gives a Home / Draw / Away probability for each match,
records the pick as a flat-stake bet, and settles it once the game is played —
then publishes everything to a website.

**Live site:** https://hphillips9.github.io/football-analysis/

It started as a research project into building a leak-free football model from
five seasons of data; the notebooks in [`notebooks/`](notebooks/) are that work.
The rest of the repo is the production pipeline that grew out of it.

---

## The model

Each match is described by three chronological, leak-free features:

| Feature | Definition |
| --- | --- |
| `EloDiff` | home Elo − away Elo |
| `XGDDiffLast5` | each team's (xG for − xG against) over its last 5 games, home − away |
| `GoalsPerGameDiff` | season-to-date goals per game, home − away |

Every team has an **Elo rating** (starts at 1500, K-factor 35, carries across
seasons). The 130-point home advantage is used only inside the Elo update's
expected result; the model learns home advantage for itself through its
intercept. A promoted team keeps the rating it last had, and a team new to
the data starts at 1500 (`PROMOTED_ELO = None`). Restarting promoted teams at
1350 was tested in `notebooks/19_championship_promoted_teams.ipynb`, but the
gain was too small to keep. A **calibrated logistic regression** (`CalibratedClassifierCV`, sigmoid)
maps the three features to H / D / A probabilities and is retrained on all
available history on every run.

Configuration lives at the top of [`src/elo.py`](src/elo.py) (home advantage,
K-factor, promoted-team start) and [`src/model.py`](src/model.py) (features).

---

## Results

`src/backtest.py` scores each season with a model trained **only on the seasons
before it**. Baseline = always predicting a home win. One pooled model covers
every competition in the data (with a `League_<Div>` column per league), and
`backtest.json` reports it pooled and per competition; the table below is the
Premier League.

| Season | Trained on | Accuracy | Baseline | Edge | Log loss |
| --- | --- | --- | --- | --- | --- |
| 2022/23 | 2021/22 | 56.3% | 48.4% | +7.9 | 0.969 |
| 2023/24 | 2021/22–2022/23 | 57.6% | 46.1% | +11.6 | 0.938 |
| 2024/25 | 2021/22–2023/24 | 54.5% | 40.8% | +13.7 | 0.981 |
| 2025/26 | 2021/22–2024/25 | 50.3% | 42.6% | +7.6 | 1.031 |
| **Overall** | | **54.7%** | 44.5% | **+10.2** | 0.980 |

Beats the home-win baseline in every season, across 1,520 matches.

### Key findings from the research

- Season-long points per game was the strongest single predictor.
- Defensive metrics were more informative than attacking metrics.
- Venue-specific recent form did **not** improve performance.
- The model rarely predicts a draw — a common limitation of 3-class football
  models, and the biggest remaining weakness.
- Predictions above 0.55 confidence (47% of picks) land 62% of the time.

---

## The weekly pipeline

One command, [`src/run_week.py`](src/run_week.py), runs the whole cycle:

| Step | What it does |
| --- | --- |
| 1 | Fetch new results from football-data.co.uk into `data/raw/<Div>/results_<season>.csv` for each enabled competition (`CURRENT_SEASON` in `src/competitions.py`) |
| 2 | Settle any pending bets in `data/raw/Bets.csv` (result, the odds used, profit; no odds = unpriced, counted for accuracy only) |
| 3 | Rebuild `data/processed/all_matches.csv` (results + FotMob/Opta xG, with football-data.co.uk's xG then Understat as backup, cached per season) |
| 4 | Backfill gameweek / probabilities on any `Bets.csv` rows missing them |
| 5 | Pull each competition's next round from football-data.org, predict them, append the bets |
| 6 | Export `web/src/data/*.json` for the website |

```bash
python src/run_week.py               # full run, including predictions
python src/run_week.py --no-predict   # results + settlement only
python src/run_week.py --divs E0 SP1  # just these competitions (default: ENABLED)
```

Steps 1, 3 and 5 run **competition by competition**. One that fails (a
source outage, an unknown team name) is skipped and logged, and the others
carry on. Every run writes `data/processed/run_status.json`:

```json
{"E0": {"results": "ok", "xg": "ok", "predicted": 10, "error": null}}
```

`results` is `ok`, `stale` (download failed; the results on file were used) or
`failed`. `xg` is `ok`, `partial` (some matches missing xG) or `failed`.
`predicted` is the number of new bets added.

Step 5 predicts **one round at a time per competition**: it waits until
every fixture already in `Bets.csv` has been played and the results are on
file, then predicts the next round (plus any rearranged games that fall
inside it). A postponement in one league doesn't hold up the others.
It needs a `FOOTBALL_DATA_API_KEY` (environment variable, or a git-ignored
`.env` at the repo root). Without one it falls back to the fixture list
pasted into `data/raw/Next_Matchweek.txt`, Premier League only (an optional
first line `GW7` sets the number explicitly, otherwise it's inferred).

Bets are recorded as **1-unit flat stakes** at the best available price
(Sky Bet, or the market average when missing).

`src/backtest.py` is separate — re-run it by hand when a season finishes.

---

## Automation

[`.github/workflows/weekly.yml`](.github/workflows/weekly.yml):

- **Daily 08:00 UTC** → full run: results, settlement, and the next
  round's predictions once the current round is finished
- **Run workflow** button → full run, or results only with "predict" unticked

Running daily is safe — fixtures already bet on are never re-predicted, and
nothing new is predicted while a bet round is still being played. Needs the
repo secret `FOOTBALL_DATA_API_KEY`.

It commits the refreshed data back to the repo, then builds and deploys the site.
[`deploy-site.yml`](.github/workflows/deploy-site.yml) redeploys on any change to
`web/`.

---

## The website

An [Observable Framework](https://observablehq.com/framework/) static site in
[`web/`](web/), five pages:

- **This Gameweek** — the upcoming predictions, probability bars, fixture table
- **Gameweeks** — pick any gameweek, see its predictions and how they did
- **Track Record** — profit/loss per gameweek, bankroll curve, full bet log
- **Ratings** — current Elo table
- **About** — full methodology, the season backtest, calibration

```bash
cd web
npm install
npm run dev      # local preview
npm run build    # static build → web/dist/
```

---

## Repository layout

```
src/
  run_week.py             orchestrator for the weekly cycle
  run_status.py           per-competition outcome of a run -> run_status.json
  fetch_results.py        pull new results, settle bets
  load_data.py            build all_matches.csv (results + FotMob xG; football-data, Understat backup)
  fetch_fixtures.py       football-data.org → Future_Fixtures.csv
  future_games_parser.py  Next_Matchweek.txt → Future_Fixtures.csv (fallback)
  predict_next_matches.py  predict the next round, record bets (re-exports the three below)
  elo.py                  Elo ratings: update rule, pre-match Elo, fixture Elo; feature scope
  features.py             goals per game, last-5 xG difference, build_history (per competition)
  model.py                FEATURES + League_<Div> columns, calibrated logistic regression, predict_fixtures
  backfill_bet_probs.py   fill gameweek / probabilities on older bets
  export_web.py           write the site's JSON feed (Premier League only for now) + leagues.json
  backtest.py             season-by-season evaluation, pooled and per competition
  evaluate.py             walk-forward, per-match log loss, paired bootstrap (shared with notebooks)
  team_names.py           name normalisation across data sources; lookups by FotMob / football-data.org id
  bet_schema.py           Bets.csv columns and order, shared by everything that writes it
  competitions.py         registry of competitions (codes, ids) and which are enabled
  tools/migrate_layout.py one-off move to the per-competition data layout
  tools/backfill_top5.py  one-off: La Liga / Bundesliga / Serie A / Ligue 1 results + xG caches
  tools/migrate_bets.py   one-off Bets.csv migration to the multi-competition schema
  tools/suggest_aliases.py  offline: suggest team_names.csv rows by date+score voting (run when clubs are promoted)
data/
  raw/<Div>/              per competition: results_<yy-yy>.csv, fotmob_ + understat_ xG caches
  raw/                    Bets.csv, fixtures
  processed/              all_matches.csv, run_status.json, feature snapshots
  reference/team_names.csv  one row per club: canonical name, country, FotMob + football-data.org ids, each source's name
tests/                    unit tests (python tests/test_<name>.py, or pytest tests/)
web/                      Observable Framework site
notebooks/                the original research (01–15)
```

---

## Setup

```bash
python -m venv .venv
source .venv/bin/activate     # Linux/Mac
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

Data sources: match results and odds from
[football-data.co.uk](https://www.football-data.co.uk/), expected goals from
[FotMob](https://www.fotmob.com/) (Opta's xG, as shown on BBC and Sky). Any
match FotMob is missing takes football-data.co.uk's own xG columns (2026-27 on;
also Opta, but not updated after Opta's revisions), then
[Understat](https://understat.com/) (via `penaltyblog`).
