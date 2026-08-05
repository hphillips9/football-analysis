import pandas as pd
import os
import glob

csv_files = glob.glob(os.path.join("data/raw", "*.csv"))
all_dfs = []

for f in csv_files:
    df = pd.read_csv(f)
    filename = os.path.basename(f).replace(".csv", "").replace("EPL", "")
    season_df = pd.DataFrame({
        "Season": [filename] * len(df)
    })

    df = pd.concat([season_df, df], axis=1)
    all_dfs.append(df)

matches = pd.concat(all_dfs, ignore_index=True)
matches["MatchDateTime"] = pd.to_datetime(matches["Date"] + " " + matches["Time"], dayfirst=True)
matches = matches.sort_values("MatchDateTime")
matches = matches.reset_index(drop=True)
matches.to_csv("data/processed/all_matches.csv", index=False)