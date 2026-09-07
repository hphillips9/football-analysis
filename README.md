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
| `EloDiff` | home Elo + 130 home advantage − away Elo |
| `XGDDiffLast5` | each team's (xG for − xG against) over its last 5 games, home − away |
| `GoalsPerGameDiff` | season-to-date goals per game, home − away |

Every team has an **Elo rating** (starts at 1500, K-factor 35, carries across
seasons). A **calibrated logistic regression** (`CalibratedClassifierCV`, sigmoid)
maps the three features to H / D / A probabilities and is retrained on all
available history on every run.

Configuration lives at the top of
[`src/predict_next_matches.py`](src/predict_next_matches.py).

---

## Results

`src/backtest.py` scores each season with a model trained **only on the seasons
before it**. Baseline = always predicting a home win.

| Season | Trained on | Accuracy | Baseline | Edge | Log loss |
| --- | --- | --- | --- | --- | --- |
| 2022/23 | 2021/22 | 55.8% | 48.4% | +7.4 | 0.969 |
| 2023/24 | 2021/22–2022/23 | 57.9% | 46.1% | +11.8 | 0.939 |
| 2024/25 | 2021/22–2023/24 | 53.7% | 40.8% | +12.9 | 0.983 |
| 2025/26 | 2021/22–2024/25 | 49.7% | 42.6% | +7.1 | 1.031 |
| **Overall** | | **54.3%** | 44.5% | **+9.8** | 0.98 |

Beats the home-win baseline in every season, across 1,520 matches.

### Key findings from the research

- Season-long points per game was the strongest single predictor.
- Defensive metrics were more informative than attacking metrics.
- Venue-specific recent form did **not** improve performance.
- The model rarely predicts a draw — a common limitation of 3-class football
  models, and the biggest remaining weakness.
- Predictions above 0.55 confidence land around 57% of the time.

---

## The weekly pipeline

One command, [`src/run_week.py`](src/run_week.py), runs the whole cycle:

| Step | What it does |
| --- | --- |
| 1 | Fetch new results from football-data.co.uk into `data/raw/EPL26-27.csv` |
| 2 | Settle any pending bets in `data/raw/Bets.csv` (result + profit) |
| 3 | Rebuild `data/processed/all_matches.csv` (results + Understat xG, cached per season) |
| 4 | Backfill gameweek / probabilities on any `Bets.csv` rows missing them |
| 5 | Parse `data/raw/Next_Matchweek.txt`, predict that gameweek, append the bets |
| 6 | Export `web/src/data/*.json` for the website |

```bash
python src/run_week.py               # full run, including predictions
python src/run_week.py --no-predict   # results + settlement only
```

**To predict a gameweek**, paste the fixture list into
`data/raw/Next_Matchweek.txt` (an optional first line `GW7` sets the number
explicitly, otherwise it's inferred) and run the pipeline.

Bets are recorded as **1-unit flat stakes** at the best available price
(Sky Bet, or the market average when missing).

`src/backtest.py` is separate — re-run it by hand when a season finishes.

---

## Automation

[`.github/workflows/weekly.yml`](.github/workflows/weekly.yml):

- **Tue & Fri 08:00 UTC** and the **Run workflow** button → `--no-predict`
  (results only; a scheduled run has no fresh fixtures to predict)
- **push to `data/raw/Next_Matchweek.txt`** on `main` → full run with predictions

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
  fetch_results.py        pull new results, settle bets
  load_data.py            build all_matches.csv (results + Understat xG)
  future_games_parser.py  Next_Matchweek.txt → Future_Fixtures.csv
  predict_next_matches.py  Elo, features, model, prediction
  backfill_bet_probs.py   fill gameweek / probabilities on older bets
  export_web.py           write the site's JSON feed
  backtest.py             season-by-season evaluation
  team_names.py           name normalisation across data sources
data/
  raw/                    source CSVs, Bets.csv, understat/ cache
  processed/              all_matches.csv, feature snapshots
  reference/team_names.csv  canonical ↔ source name map
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
[Understat](https://understat.com/) (via `penaltyblog`).
