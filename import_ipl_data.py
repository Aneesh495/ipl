import os
import json
import pandas as pd
from tqdm import tqdm

# Directory containing all IPL JSON files
DATA_DIR = 'json'

# List all JSON files
json_files = [f for f in os.listdir(DATA_DIR) if f.endswith('.json')]

# Lists to store match-level and ball-by-ball data
matches = []
balls = []

for filename in tqdm(json_files, desc='Loading IPL JSON files'):
    with open(os.path.join(DATA_DIR, filename), 'r') as f:
        data = json.load(f)
        # Store match-level info
        match_info = data.get('info', {})
        match_info['file'] = filename
        matches.append(match_info)
        # Store ball-by-ball data
        for inning in data.get('innings', []):
            team = inning.get('team')
            for over in inning.get('overs', []):
                over_num = over.get('over')
                for delivery in over.get('deliveries', []):
                    ball = {
                        'file': filename,
                        'team': team,
                        'over': over_num,
                        **delivery
                    }
                    balls.append(ball)

# Convert to DataFrames
matches_df = pd.DataFrame(matches)
balls_df = pd.DataFrame(balls)

print(f"Loaded {len(matches_df)} matches and {len(balls_df)} deliveries.")
print("Match DataFrame columns:", matches_df.columns.tolist())
print("Ball-by-ball DataFrame columns:", balls_df.columns.tolist())

# --- Data Cleaning and Normalization ---
print("\nCleaning and normalizing data...")

# 1. Standardize team and player names (strip whitespace, consistent case)
def standardize_name(name):
    if isinstance(name, str):
        return name.strip().title()
    return name

# Clean matches DataFrame
for col in ['city', 'venue']:
    if col in matches_df.columns:
        matches_df[col] = matches_df[col].astype(str).str.strip().str.title()

if 'teams' in matches_df.columns:
    matches_df['teams'] = matches_df['teams'].apply(lambda x: [standardize_name(t) for t in x] if isinstance(x, list) else x)

if 'player_of_match' in matches_df.columns:
    matches_df['player_of_match'] = matches_df['player_of_match'].apply(lambda x: [standardize_name(p) for p in x] if isinstance(x, list) else x)

# Clean balls DataFrame
for col in ['team', 'batter', 'bowler', 'non_striker']:
    if col in balls_df.columns:
        balls_df[col] = balls_df[col].apply(standardize_name)

# 2. Handle missing values
# Fill missing values in key columns with 'Unknown' or appropriate default
def fillna_with(df, columns, value):
    for col in columns:
        if col in df.columns:
            df[col] = df[col].fillna(value)

fillna_with(matches_df, ['city', 'venue'], 'Unknown')
fillna_with(balls_df, ['team', 'batter', 'bowler', 'non_striker'], 'Unknown')

# 3. Ensure consistent data types
if 'season' in matches_df.columns:
    matches_df['season'] = pd.to_numeric(matches_df['season'], errors='coerce').astype('Int64')
if 'over' in balls_df.columns:
    balls_df['over'] = pd.to_numeric(balls_df['over'], errors='coerce').astype('Int64')

print("Data cleaning complete.")
print(f"Matches with missing city: {(matches_df['city'] == 'Unknown').sum()}")
print(f"Balls with missing batter: {(balls_df['batter'] == 'Unknown').sum()}")

# --- Save cleaned DataFrames ---
print("\nSaving cleaned DataFrames to CSV...")
matches_df.to_csv('ipl_matches_cleaned.csv', index=False)
balls_df.to_csv('ipl_balls_cleaned.csv', index=False)
print("Saved as ipl_matches_cleaned.csv and ipl_balls_cleaned.csv.")

# --- Exploratory Data Analysis (EDA) and Visualizations ---
import matplotlib.pyplot as plt
import seaborn as sns
sns.set(style="whitegrid")

print("\n--- EDA: IPL Overview ---")

# 1. Matches per season
matches_per_season = matches_df['season'].value_counts().sort_index()
plt.figure(figsize=(10,5))
sns.barplot(x=matches_per_season.index, y=matches_per_season.values, palette="viridis")
plt.title('Number of Matches per IPL Season')
plt.xlabel('Season')
plt.ylabel('Number of Matches')
plt.tight_layout()
plt.savefig('eda_matches_per_season.png')
plt.close()
print("Saved: eda_matches_per_season.png")

# 2. Team win counts
win_counts = matches_df['outcome'].apply(lambda x: x.get('winner') if isinstance(x, dict) else None).value_counts()
plt.figure(figsize=(12,6))
sns.barplot(y=win_counts.index, x=win_counts.values, palette="crest")
plt.title('Total Wins by Team')
plt.xlabel('Wins')
plt.ylabel('Team')
plt.tight_layout()
plt.savefig('eda_team_win_counts.png')
plt.close()
print("Saved: eda_team_win_counts.png")

# 3. Top run scorers (batters)
batter_runs = balls_df.groupby('batter').apply(lambda x: sum([r.get('batter',0) if isinstance(r, dict) else 0 for r in x['runs']])).sort_values(ascending=False).head(15)
plt.figure(figsize=(12,6))
sns.barplot(y=batter_runs.index, x=batter_runs.values, palette="flare")
plt.title('Top 15 IPL Run Scorers (All Time)')
plt.xlabel('Runs')
plt.ylabel('Batter')
plt.tight_layout()
plt.savefig('eda_top_batters.png')
plt.close()
print("Saved: eda_top_batters.png")

# 4. Top wicket takers (bowlers)
def count_wickets(wickets_col):
    if isinstance(wickets_col, list):
        return len(wickets_col)
    return 0
balls_df['wickets_count'] = balls_df['wickets'].apply(count_wickets)
bowler_wickets = balls_df.groupby('bowler')['wickets_count'].sum().sort_values(ascending=False).head(15)
plt.figure(figsize=(12,6))
sns.barplot(y=bowler_wickets.index, x=bowler_wickets.values, palette="mako")
plt.title('Top 15 IPL Wicket Takers (All Time)')
plt.xlabel('Wickets')
plt.ylabel('Bowler')
plt.tight_layout()
plt.savefig('eda_top_bowlers.png')
plt.close()
print("Saved: eda_top_bowlers.png")

print("\nEDA complete! Check the generated PNG files for visualizations.") 

# --- Comprehensive IPL Data Extraction and Summary ---
print("\n--- Extracting ALL possible IPL insights and summary tables ---")

# 1. Season-level summary
season_summary = matches_df.groupby('season').agg(
    matches=('file', 'count'),
    venues=('venue', pd.Series.nunique),
    teams=('teams', lambda x: len(set([t for sublist in x for t in sublist]))),
    cities=('city', pd.Series.nunique)
).reset_index()
season_summary.to_csv('summary_season.csv', index=False)
print("Saved: summary_season.csv (season-level summary)")

# 2. Team-level summary
from collections import Counter
def flatten_teams(teams_col):
    return [t for sublist in teams_col if isinstance(sublist, list) for t in sublist]
team_counts = Counter(flatten_teams(matches_df['teams']))
team_summary = pd.DataFrame({'team': list(team_counts.keys()), 'matches_played': list(team_counts.values())})
# Add win counts
team_summary['wins'] = team_summary['team'].map(matches_df['outcome'].apply(lambda x: x.get('winner') if isinstance(x, dict) else None).value_counts())
team_summary['wins'] = team_summary['wins'].fillna(0).astype(int)
team_summary.to_csv('summary_team.csv', index=False)
print("Saved: summary_team.csv (team-level summary)")

# 3. Player-level summary (batting, bowling, fielding)
# Batting
batter_stats = balls_df.groupby('batter').agg(
    runs_scored=('runs', lambda x: sum([r.get('batter',0) if isinstance(r, dict) else 0 for r in x])),
    balls_faced=('batter', 'count'),
    matches_played=('file', pd.Series.nunique)
).sort_values('runs_scored', ascending=False).reset_index()
batter_stats.to_csv('summary_batters.csv', index=False)
print("Saved: summary_batters.csv (batting stats)")
# Bowling
bowler_stats = balls_df.groupby('bowler').agg(
    balls_bowled=('bowler', 'count'),
    wickets_taken=('wickets', lambda x: sum([len(w) if isinstance(w, list) else 0 for w in x])),
    runs_conceded=('runs', lambda x: sum([r.get('total',0) if isinstance(r, dict) else 0 for r in x])),
    matches_played=('file', pd.Series.nunique)
).sort_values('wickets_taken', ascending=False).reset_index()
bowler_stats.to_csv('summary_bowlers.csv', index=False)
print("Saved: summary_bowlers.csv (bowling stats)")
# Fielding (dismissals as fielder)
def extract_fielders(wickets_col):
    fielders = []
    if isinstance(wickets_col, list):
        for w in wickets_col:
            if isinstance(w, dict) and 'fielders' in w:
                fielders.extend([f['name'] for f in w['fielders'] if 'name' in f])
    return fielders
balls_df['fielders'] = balls_df['wickets'].apply(extract_fielders)
from itertools import chain
fielder_counts = pd.Series(list(chain.from_iterable(balls_df['fielders']))).value_counts().reset_index()
fielder_counts.columns = ['fielder', 'dismissals']
fielder_counts.to_csv('summary_fielders.csv', index=False)
print("Saved: summary_fielders.csv (fielding stats)")

# 4. Venue stats
venue_stats = matches_df['venue'].value_counts().reset_index()
venue_stats.columns = ['venue', 'matches_hosted']
venue_stats.to_csv('summary_venues.csv', index=False)
print("Saved: summary_venues.csv (venue stats)")

# 5. Toss stats
toss_stats = matches_df['toss'].apply(lambda x: x.get('winner') if isinstance(x, dict) else None).value_counts().reset_index()
toss_stats.columns = ['team', 'tosses_won']
toss_stats.to_csv('summary_toss.csv', index=False)
print("Saved: summary_toss.csv (toss stats)")

# 6. Match outcome stats
outcome_stats = matches_df['outcome'].apply(lambda x: x.get('by') if isinstance(x, dict) else None).dropna().apply(pd.Series)
if 'runs' in outcome_stats:
    runs_wins = outcome_stats['runs'].dropna().astype(int)
    runs_wins.describe().to_csv('summary_outcome_runs.csv')
    print("Saved: summary_outcome_runs.csv (win by runs stats)")
if 'wickets' in outcome_stats:
    wickets_wins = outcome_stats['wickets'].dropna().astype(int)
    wickets_wins.describe().to_csv('summary_outcome_wickets.csv')
    print("Saved: summary_outcome_wickets.csv (win by wickets stats)")

# 7. Super overs
super_overs = matches_df[matches_df['overs'] > 20]
super_overs.to_csv('summary_super_overs.csv', index=False)
print("Saved: summary_super_overs.csv (super over matches)")

# 8. Partnerships (top partnerships by runs)
partnerships = []
for _, over in balls_df.iterrows():
    if over['batter'] and over['non_striker'] and isinstance(over['runs'], dict):
        partnerships.append((over['batter'], over['non_striker'], over['runs'].get('total',0)))
from collections import defaultdict
partnership_totals = defaultdict(int)
for b, n, r in partnerships:
    key = tuple(sorted([b, n]))
    partnership_totals[key] += r
partnership_df = pd.DataFrame([{'batter1': k[0], 'batter2': k[1], 'partnership_runs': v} for k, v in partnership_totals.items()])
partnership_df = partnership_df.sort_values('partnership_runs', ascending=False).head(50)
partnership_df.to_csv('summary_partnerships.csv', index=False)
print("Saved: summary_partnerships.csv (top partnerships)")

# 9. Rare events (hat-tricks, 6 sixes, 5-wicket hauls, etc.)
# Hat-tricks: bowler takes 3 wickets in 3 consecutive balls
hat_tricks = []
for bowler, group in balls_df.sort_values(['file', 'over']).groupby('bowler'):
    wickets_seq = group['wickets_count'].tolist()
    for i in range(len(wickets_seq)-2):
        if wickets_seq[i] == 1 and wickets_seq[i+1] == 1 and wickets_seq[i+2] == 1:
            hat_tricks.append(bowler)
pd.Series(hat_tricks).value_counts().reset_index().to_csv('summary_hat_tricks.csv', index=False)
print("Saved: summary_hat_tricks.csv (hat-tricks)")

# 10. Anomaly/rare event detection (e.g., highest/lowest scores, fastest 50/100, etc.)
# Highest team totals
team_innings = balls_df.groupby(['file', 'team']).apply(lambda x: sum([r.get('total',0) if isinstance(r, dict) else 0 for r in x['runs']])).reset_index()
team_innings.columns = ['file', 'team', 'total_runs']
team_innings = team_innings.sort_values('total_runs', ascending=False).head(50)
team_innings.to_csv('summary_highest_totals.csv', index=False)
print("Saved: summary_highest_totals.csv (highest team totals)")

print("\nAll possible summary tables and insights have been extracted and saved as CSVs!") 