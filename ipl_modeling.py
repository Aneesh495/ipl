import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import accuracy_score, roc_auc_score, classification_report
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.decomposition import PCA
from sklearn.cluster import KMeans
import warnings
warnings.filterwarnings('ignore')

# --- Load Cleaned Data ---
matches = pd.read_csv('ipl_matches_cleaned.csv')
balls = pd.read_csv('ipl_balls_cleaned.csv')

# --- 1. Batting Rankings (Composite Score) ---
batters = pd.read_csv('summary_batters.csv')
batters['strike_rate'] = batters['runs_scored'] / batters['balls_faced'] * 100
batters['batting_score'] = (
    batters['runs_scored'] * 0.7 +
    batters['strike_rate'] * 0.2 +
    batters['matches_played'] * 0.1
)
batters = batters.sort_values('batting_score', ascending=False)
batters.to_csv('model_batting_rankings.csv', index=False)
print('Saved: model_batting_rankings.csv')

# --- 2. Bowling Rankings (Composite Score) ---
bowlers = pd.read_csv('summary_bowlers.csv')
bowlers['wickets_per_match'] = bowlers['wickets_taken'] / bowlers['matches_played']
bowlers['economy'] = bowlers['runs_conceded'] / (bowlers['balls_bowled'] / 6)
bowlers['bowling_score'] = (
    bowlers['wickets_taken'] * 0.6 +
    (1 / (bowlers['economy'] + 1e-6)) * 0.2 +
    bowlers['wickets_per_match'] * 0.2
)
bowlers = bowlers.sort_values('bowling_score', ascending=False)
bowlers.to_csv('model_bowling_rankings.csv', index=False)
print('Saved: model_bowling_rankings.csv')

# --- 3. Fielding Rankings (Dismissals) ---
fielders = pd.read_csv('summary_fielders.csv')
fielders = fielders.sort_values('dismissals', ascending=False)
fielders.to_csv('model_fielding_rankings.csv', index=False)
print('Saved: model_fielding_rankings.csv')

# --- 4. Team Power Rankings (Elo-like) ---
team_stats = pd.read_csv('summary_team.csv')
team_stats['power_score'] = (
    team_stats['wins'] * 0.7 +
    team_stats['matches_played'] * 0.3
)
team_stats = team_stats.sort_values('power_score', ascending=False)
team_stats.to_csv('model_team_power_rankings.csv', index=False)
print('Saved: model_team_power_rankings.csv')

# --- 5. Toss Effect on Match Outcome ---
def safe_eval_dict(x):
    try:
        d = eval(x) if pd.notnull(x) else {}
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}

matches['toss_winner'] = matches['toss'].apply(lambda x: safe_eval_dict(x).get('winner'))
matches['match_winner'] = matches['outcome'].apply(lambda x: safe_eval_dict(x).get('winner'))
toss_effect = pd.crosstab(matches['toss_winner'], matches['match_winner'])
toss_effect.to_csv('model_toss_effect.csv')
print('Saved: model_toss_effect.csv')

# --- 6. Venue Effect (Home Advantage) ---
venue_effect = matches.groupby('venue').apply(lambda x: x['outcome'].apply(lambda y: safe_eval_dict(y).get('winner')).value_counts()).unstack().fillna(0)
venue_effect.to_csv('model_venue_effect.csv')
print('Saved: model_venue_effect.csv')

# --- 7. Win Probability Model (Random Forest) ---
# Prepare features for match-level prediction
features = []
labels = []
for _, row in matches.iterrows():
    try:
        teams = row['teams']
        if isinstance(teams, str):
            teams = eval(teams)
        if not isinstance(teams, list) or len(teams) != 2:
            continue
        team1, team2 = teams
        toss = safe_eval_dict(row['toss'])
        toss_winner = toss.get('winner')
        toss_decision = toss.get('decision')
        venue = row['venue']
        season = row['season']
        outcome = safe_eval_dict(row['outcome'])
        winner = outcome.get('winner')
        if not winner or not team1 or not team2:
            continue
        features.append([
            season,
            team1 == toss_winner,
            team2 == toss_winner,
            toss_decision == 'bat',
            toss_decision == 'field',
            venue,
            team1,
            team2
        ])
        labels.append(1 if winner == team1 else 0)
    except Exception as e:
        continue
# Encode categorical features
features_df = pd.DataFrame(features, columns=['season','team1_toss','team2_toss','toss_bat','toss_field','venue','team1','team2'])
le_venue = LabelEncoder()
le_team = LabelEncoder()
features_df['venue'] = le_venue.fit_transform(features_df['venue'])
features_df['team1'] = le_team.fit_transform(features_df['team1'])
features_df['team2'] = le_team.transform(features_df['team2'])
X = features_df.values
y = np.array(labels)
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
rf = RandomForestClassifier(n_estimators=100, random_state=42)
rf.fit(X_train, y_train)
y_pred = rf.predict(X_test)
acc = accuracy_score(y_test, y_pred)
print(f'Random Forest Win Prediction Accuracy: {acc:.3f}')
pd.DataFrame({'y_true': y_test, 'y_pred': y_pred}).to_csv('model_win_predictions.csv', index=False)
print('Saved: model_win_predictions.csv')

# --- 8. Clutch & Consistency Analysis ---
# Clutch: runs scored in chases, playoffs, last 5 overs, etc.
balls['is_chase'] = balls['file'].map(
    matches.set_index('file').apply(lambda x: x['outcome'], axis=1).apply(lambda x: safe_eval_dict(x).get('winner'))
)
balls['is_last5'] = balls['over'] >= 15
clutch_batters = balls[(balls['is_last5'])].groupby('batter').agg(
    clutch_runs=('runs', lambda x: sum([r.get('batter',0) if isinstance(r, dict) else 0 for r in x])),
    balls_faced=('batter', 'count')
).sort_values('clutch_runs', ascending=False).head(20)
clutch_batters.to_csv('model_clutch_batters.csv')
print('Saved: model_clutch_batters.csv')
# Consistency: std dev of runs per match
batter_match_runs = balls.groupby(['batter','file']).apply(lambda x: sum([r.get('batter',0) if isinstance(r, dict) else 0 for r in x['runs']])).reset_index()
consistency = batter_match_runs.groupby('batter')[0].std().reset_index().rename(columns={0:'run_stddev'})
consistency = consistency.sort_values('run_stddev')
consistency.to_csv('model_batter_consistency.csv', index=False)
print('Saved: model_batter_consistency.csv')

# --- 9. Anomaly & Pattern Detection (Clustering) ---
# Use PCA + KMeans to cluster batters by style
batters_for_cluster = batters[['runs_scored','balls_faced','strike_rate','matches_played']].fillna(0)
scaler = StandardScaler()
batters_scaled = scaler.fit_transform(batters_for_cluster)
pca = PCA(n_components=2)
batters_pca = pca.fit_transform(batters_scaled)
kmeans = KMeans(n_clusters=5, random_state=42)
clusters = kmeans.fit_predict(batters_pca)
batters['cluster'] = clusters
batters.to_csv('model_batter_clusters.csv', index=False)
print('Saved: model_batter_clusters.csv')

print('\nAll advanced statistical models and machine learning outputs have been saved as CSVs!') 