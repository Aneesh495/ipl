import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import plotly.express as px
import plotly.graph_objects as go
import networkx as nx
from mpl_toolkits.mplot3d import Axes3D
import warnings
warnings.filterwarnings('ignore')

# --- Load Data ---
matches = pd.read_csv('ipl_matches_cleaned.csv')
balls = pd.read_csv('ipl_balls_cleaned.csv')
batters = pd.read_csv('model_batting_rankings.csv')
bowlers = pd.read_csv('model_bowling_rankings.csv')
fielders = pd.read_csv('model_fielding_rankings.csv')
teams = pd.read_csv('model_team_power_rankings.csv')
clutch = pd.read_csv('model_clutch_batters.csv')
consistency = pd.read_csv('model_batter_consistency.csv')
batter_clusters = pd.read_csv('model_batter_clusters.csv')

# --- 1. Improved Animated Run Worms for Top Matches ---
def plot_run_worm(match_id, save_path):
    match_balls = balls[balls['file'] == match_id]
    if match_balls.empty:
        return
    plt.figure(figsize=(14,7))
    for team in match_balls['team'].unique():
        team_balls = match_balls[match_balls['team'] == team].copy()
        team_balls = team_balls.sort_values(['over'])
        # Calculate ball number for x-axis
        team_balls['ball_num'] = np.arange(1, len(team_balls)+1)
        team_balls['run_this_ball'] = [r.get('total',0) if isinstance(r, dict) else 0 for r in team_balls['runs']]
        team_balls['cumulative_runs'] = team_balls['run_this_ball'].cumsum()
        plt.plot(team_balls['ball_num'], team_balls['cumulative_runs'], label=team, linewidth=2)
    plt.title(f'Run Worm (Cumulative Runs per Ball): {match_id}')
    plt.xlabel('Ball Number')
    plt.ylabel('Cumulative Runs')
    plt.legend()
    plt.tight_layout()
    plt.savefig(save_path)
    plt.close()

# Example: Plot run worms for 5 highest scoring matches
for match_id in balls.groupby('file').apply(lambda x: sum([r.get('total',0) if isinstance(r, dict) else 0 for r in x['runs']])).sort_values(ascending=False).head(5).index:
    plot_run_worm(match_id, f'visual_runworm_{match_id}.png')
    print(f'Saved: visual_runworm_{match_id}.png')

# --- 2. Improved Network Graph of Player Connections (Top Partnerships) ---
from collections import Counter
partnerships = balls[['batter','non_striker','runs']].dropna()
pairs = [tuple(sorted([row['batter'], row['non_striker']])) for _, row in partnerships.iterrows()]
pair_runs = Counter()
for (_, row) in partnerships.iterrows():
    pair = tuple(sorted([row['batter'], row['non_striker']]))
    run = row['runs']
    pair_runs[pair] += run.get('total',0) if isinstance(run, dict) else 0
# Top 20 partnerships by runs
top_pairs = dict(pair_runs.most_common(20))
G = nx.Graph()
for (p1, p2), w in top_pairs.items():
    if p1 != p2:
        G.add_edge(p1, p2, weight=w)
plt.figure(figsize=(16,10))
pos = nx.spring_layout(G, k=0.4)
weights = [G[u][v]['weight']/10 for u,v in G.edges()]
nx.draw(G, pos, with_labels=True, node_size=[G.degree(n)*300 for n in G.nodes()], width=weights, edge_color=weights, edge_cmap=plt.cm.Blues)
edge_labels = nx.get_edge_attributes(G, 'weight')
nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_size=10)
plt.title('Top 20 Player Partnerships by Runs')
plt.tight_layout()
plt.savefig('visual_network_partnerships.png')
plt.close()
print('Saved: visual_network_partnerships.png')

# --- 3. Improved 3D Pitch Map for Bowler Performance (Wickets by Over & Match) ---
def plot_3d_pitch_bowler(bowler_name, save_path):
    bowler_balls = balls[balls['bowler'] == bowler_name]
    if bowler_balls.empty:
        return
    # Aggregate wickets by over and match
    agg = bowler_balls.groupby(['file','over']).agg({'wickets': lambda x: sum([len(w) if isinstance(w, list) else 0 for w in x])}).reset_index()
    agg = agg[agg['wickets'] > 0]
    if agg.empty:
        # fallback to 2D heatmap
        pivot = bowler_balls.pivot_table(index='over', columns='file', values='wickets', aggfunc=lambda x: sum([len(w) if isinstance(w, list) else 0 for w in x]))
        plt.figure(figsize=(12,6))
        sns.heatmap(pivot.fillna(0), cmap='Reds', annot=False)
        plt.title(f'2D Heatmap: {bowler_name} Wickets by Over & Match')
        plt.xlabel('Match')
        plt.ylabel('Over')
        plt.tight_layout()
        plt.savefig(save_path)
        plt.close()
        return
    fig = plt.figure(figsize=(12,8))
    ax = fig.add_subplot(111, projection='3d')
    xs = agg['over']
    ys = agg['file'].astype('category').cat.codes
    zs = agg['wickets']
    sc = ax.scatter(xs, ys, zs, c=zs, cmap='Reds', s=60)
    ax.set_xlabel('Over')
    ax.set_ylabel('Match')
    ax.set_zlabel('Wickets')
    plt.title(f'3D Pitch Map: {bowler_name} (Wickets by Over & Match)')
    fig.colorbar(sc, ax=ax, label='Wickets')
    plt.tight_layout()
    plt.savefig(save_path)
    plt.close()

# Example: Top 3 bowlers
for bowler in bowlers.head(3)['bowler']:
    plot_3d_pitch_bowler(bowler, f'visual_3dpitch_{bowler}.png')
    print(f'Saved: visual_3dpitch_{bowler}.png')

# --- 4. Heatmap of Team Performance by Venue ---
venue_team = matches.groupby(['venue']).apply(lambda x: x['outcome'].apply(lambda y: eval(y)['winner'] if pd.notnull(y) and 'winner' in eval(y) else None).value_counts()).unstack().fillna(0)
plt.figure(figsize=(16,8))
sns.heatmap(venue_team, cmap='YlGnBu', annot=False)
plt.title('Team Wins by Venue')
plt.xlabel('Team')
plt.ylabel('Venue')
plt.tight_layout()
plt.savefig('visual_heatmap_venue_team.png')
plt.close()
print('Saved: visual_heatmap_venue_team.png')

# --- 5. Interactive Dashboard: Top Batters by Cluster (Plotly) ---
fig = px.scatter(batter_clusters, x='runs_scored', y='strike_rate', color='cluster', hover_data=['batter','matches_played'], title='Batter Clusters: Runs vs Strike Rate')
fig.write_html('visual_batter_clusters.html')
print('Saved: visual_batter_clusters.html')

# --- 6. Deep-Dive Analytics: Clutch, Consistency, Toss/Venue Effects ---
# Clutch Batters
fig = px.bar(clutch.head(10), x='batter', y='clutch_runs', title='Top 10 Clutch Batters (Runs in Last 5 Overs)')
fig.write_html('visual_clutch_batters.html')
print('Saved: visual_clutch_batters.html')
# Consistency
fig = px.bar(consistency.head(10), x='batter', y='run_stddev', title='Most Consistent Batters (Lowest Std Dev)')
fig.write_html('visual_consistent_batters.html')
print('Saved: visual_consistent_batters.html')
# Toss Effect
import plotly.figure_factory as ff
toss_effect = pd.read_csv('model_toss_effect.csv', index_col=0)
fig = ff.create_annotated_heatmap(z=toss_effect.values, x=list(toss_effect.columns), y=list(toss_effect.index), colorscale='Viridis', showscale=True)
fig.update_layout(title='Toss Winner vs Match Winner')
fig.write_html('visual_toss_effect.html')
print('Saved: visual_toss_effect.html')
# Venue Effect
venue_effect = pd.read_csv('model_venue_effect.csv', index_col=0)
fig = ff.create_annotated_heatmap(z=venue_effect.values, x=list(venue_effect.columns), y=list(venue_effect.index), colorscale='Cividis', showscale=True)
fig.update_layout(title='Venue vs Match Winner')
fig.write_html('visual_venue_effect.html')
print('Saved: visual_venue_effect.html')

# --- 4. List of All Insights and Visuals ---
insights = [
    ('ipl_matches_cleaned.csv', 'Cleaned match-level data'),
    ('ipl_balls_cleaned.csv', 'Cleaned ball-by-ball data'),
    ('summary_season.csv', 'Season-level summary'),
    ('summary_team.csv', 'Team-level summary'),
    ('summary_batters.csv', 'Batting stats for all players'),
    ('summary_bowlers.csv', 'Bowling stats for all players'),
    ('summary_fielders.csv', 'Fielding stats (dismissals)'),
    ('summary_venues.csv', 'Venue stats'),
    ('summary_toss.csv', 'Toss stats'),
    ('summary_outcome_runs.csv', 'Win by runs stats'),
    ('summary_outcome_wickets.csv', 'Win by wickets stats'),
    ('summary_super_overs.csv', 'Super over matches'),
    ('summary_partnerships.csv', 'Top partnerships'),
    ('summary_hat_tricks.csv', 'Hat-tricks'),
    ('summary_highest_totals.csv', 'Highest team totals'),
    ('model_batting_rankings.csv', 'Advanced batting rankings'),
    ('model_bowling_rankings.csv', 'Advanced bowling rankings'),
    ('model_fielding_rankings.csv', 'Advanced fielding rankings'),
    ('model_team_power_rankings.csv', 'Team power rankings'),
    ('model_toss_effect.csv', 'Toss effect on match outcome'),
    ('model_venue_effect.csv', 'Venue effect on match outcome'),
    ('model_win_predictions.csv', 'Win probability model predictions'),
    ('model_clutch_batters.csv', 'Clutch batters (last 5 overs)'),
    ('model_batter_consistency.csv', 'Consistency of batters'),
    ('model_batter_clusters.csv', 'Batter style clusters'),
    ('visual_runworm_*.png', 'Run worm plots for top matches'),
    ('visual_3dpitch_*.png', '3D/2D pitch maps for top bowlers'),
    ('visual_heatmap_venue_team.png', 'Heatmap of team wins by venue'),
    ('visual_network_partnerships.png', 'Network graph of top partnerships'),
    ('visual_batter_clusters.html', 'Interactive batter clusters dashboard'),
    ('visual_clutch_batters.html', 'Interactive clutch batters dashboard'),
    ('visual_consistent_batters.html', 'Interactive consistent batters dashboard'),
    ('visual_toss_effect.html', 'Interactive toss effect heatmap'),
    ('visual_venue_effect.html', 'Interactive venue effect heatmap'),
]
print('\n--- List of All Insights and Visuals ---')
for fname, desc in insights:
    print(f'- {fname}: {desc}')

print('\nAll insane visuals and deep-dive analytics have been generated and saved!') 