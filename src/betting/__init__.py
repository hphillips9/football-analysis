"""
Betting-strategy research (Phase 8). Nothing here touches Bets.csv or
the live pipeline.

    market.py    odds sources, de-margined market probabilities
    simulate.py  strategy simulator, metrics, week bootstrap
    staking.py   value-bet selection, Kelly and other staking plans, risk of ruin
    variants.py  shared log of every strategy variant tried
    goals.py     O/U 2.5 and Asian-handicap maths from score grids (P8-06)
    oos.py       writes data/processed/oos_predictions.csv
"""
