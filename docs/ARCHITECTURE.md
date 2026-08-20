# Architecture and research notes

## Source and transformation

scripts/refresh_data.py validates the [Cricsheet IPL JSON zip](https://cricsheet.org/downloads/ipl_json.zip), hashes the entire archive, counts all deliveries, and mirrors the match files. The current snapshot is described in data_manifest.json. Cricsheet's [JSON format reference](https://cricsheet.org/format/json/) defines the source fields.

scripts/build_database.py reads one match at a time into a local SQLite database. The matches table keeps original and normalized franchise names, dates, targets, outcomes, stage, and exclusion reasons. The deliveries table keeps a unique (match_id, innings_no, delivery_no) key, ball sequence, batter and bowler IDs, each category of extras, runs, legal-ball status, and wicket kinds. The build reconciles every recorded match and delivery with the archive manifest. The database is generated and ignored by Git.

Original team names remain available. Only explicit franchise renames are normalized: Delhi Daredevils to Delhi Capitals, Kings XI Punjab to Punjab Kings, Royal Challengers Bangalore to Royal Challengers Bengaluru, and Rising Pune Supergiants to Rising Pune Supergiant. Person IDs come from Cricsheet's registry where available; names are the fallback.

For rate denominators, legal balls exclude wides and no-balls. A no-ball still counts as a ball faced by the batter; a wide does not. Bowler runs conceded include batter runs, wides, and no-balls, but exclude byes and leg-byes. Retired hurt and absent hurt do not cost a wicket. Bowler wicket totals exclude run outs, retired out, obstruction, and handled-ball dismissals. Super-over deliveries are in SQLite but omitted from regulation scoring trends and player career charts.

## Chase state model

The primary outcome is whether the second-innings team won in regulation. 1,195 matches have a normal two-innings chase, unadjusted target, and listed winner. The other 48 remain available for descriptive work: 22 have extra or missing innings, 23 have an adjusted target, and three have no regulation winner. This is a modeling eligibility rule, not a claim that the excluded data is bad.

Each example is the state **after** a recorded delivery. Eleven numerical inputs are: innings, target, runs, wickets, legal balls used, legal balls left, runs required, current and required run rates, runs in the previous 12 recorded deliveries, and wickets in the previous 12 recorded deliveries. The model does not receive the next event, final score, player identity, team identity, venue, or future information. Terminal states, including six matches that ended with an absent batter and only nine recorded wickets, are not scored. The displayed final point is the known result.

Training uses whole matches from 2008–23. The 2024 season selects boosted-tree hyperparameters and fits isotonic calibrators for both model families. The 2025–26 period contains 15,921 nonterminal chase states from 140 matches. Standard logistic regression with scaling and a histogram gradient booster are compared against the same target. The boosted model has lower raw validation Brier (0.12046 versus 0.12528 for raw logistic) but substantially worse later-season Brier. The app displays calibrated logistic as the main line after that comparison. Therefore the later-period report is a **retrospective diagnostic**, not an untouched estimate of a model-selection process. The raw and calibrated figures for both models remain in docs/data/report.json.

The report includes Brier, log loss, ROC AUC, 10-bin expected calibration error, season and stage slices, a match-weighted Brier, and a 300-resample match-level bootstrap interval. Delivery states within a match are correlated; the interval samples whole matches. Permutation importance is computed on a 2024 validation subset for the boosted model and should not be read as importance for logistic regression or as a causal explanation.

## Next-ball model and player view

The second task uses the state **before** each legal delivery to predict batter runs and a dismissal indicator. It fits histogram gradient boosting regression and classification on the same historical years. The model has match context but no player identity; it does not adjust for every matchup or selection effect. The held-period score compares it with constant training-set rates, including both MSE and MAE for runs.

For each 2025–26 player, the app aggregates observed minus predicted batter runs, or predicted minus observed runs conceded by a bowler. It reports the difference per 100 modeled legal balls after multiplying by n/(n+150) to shrink small samples. These are exploratory residuals, not player impact estimates. Career scatter charts use all regulation deliveries in the archive, including matches excluded from chase modeling, and require a minimum of 60 balls before a player enters the published profiles.

## Published app and resource budget

scripts/build_site_data.py exports a small docs/data/ payload. It includes match metadata, season and phase aggregates, player summaries, model report, and one replay JSON file per season. The web app uses ECharts 5.5.1 and lazy-loads only the selected season's replay shard. No database, API, or build step runs in the browser. HTML text that comes from match data is escaped before being inserted into tooltips or lists.

Rebuild with make all, then run make test. The tests reconcile archived counts and scores, check legal-ball and target logic, verify temporal splits and finite probabilities, check every published replay, and execute the app with mocked DOM and chart objects. The smoke test checks data loading and chart configuration; it is not a visual browser test. The measured local full-build peak was about 446 MiB of resident memory, under the 2 GB design budget.
