# IPL Decision Lab: build plan

## Evidence from the refreshed source

- Cricsheet's official IPL JSON archive, fetched 2026-09-30 UTC, contains **1,243 matches and 295,732 recorded deliveries** from 2008-04-18 to 2026-05-31. The repo now mirrors all 1,243 JSON files at data version 1.2.0. See `data_manifest.json` for the source URL and SHA-256.
- The old repo already had 2024 and 2025. The refresh added 74 matches from 2026 and brought revisions to all older matches.
- There are 23 D/L matches, 25 matches without a listed winner, and 16 matches with extra innings, mostly super overs. These need explicit treatment in predictive evaluation.
- The existing CSVs and plots are stale outputs. The existing match model uses random splits across seasons, raw label-encoded teams and venues, and `eval` on CSV cells. Its reported accuracy is not a defensible future-season estimate.

## Product

An interactive, local-first cricket data lab with four linked views:

1. **Match replay:** every eligible chase has an after-ball win-probability trace, score, wickets, and turning points. Filter all seasons, teams, and matches.
2. **Era atlas:** scoring and boundary rates by year and innings phase; distinguish recorded deliveries from legal balls.
3. **Player landscape:** minimum-sample-aware batter and bowler profiles, contextual run residuals, and era trends, keyed by Cricsheet person IDs.
4. **Model audit:** held-out season metrics, reliability, baseline comparison, and slices by chase stage. Numbers are generated from the actual training run.

## Data and modeling

1. Stream one match at a time into a normalized SQLite database. Keep exact raw strings, person IDs, legal-delivery flags, extras, wicket kind, and source file ID. This bounds import memory and makes every metric reproducible.
2. Build a **post-delivery chase state** table. Features may use only information available at that point: target, runs and wickets, legal balls left, recent scoring, and the current state. Exclude D/L, no-result/tie, super-over, and invalid-target games from the primary model. Keep all raw matches in descriptive analysis.
3. Train a regularized logistic baseline and a gradient-boosted tree model. Train on 2008-2023; use 2024 for hyperparameter choice and calibration; reserve 2025 and 2026 for later evaluation. Split by whole match and time. Publish Brier score, log loss, AUC, calibration bins, and per-season results. Add match-level bootstrap intervals if runtime permits.
4. Build a second model for **next-ball runs and dismissal risk** from pre-delivery context. It supports expected-vs-observed player profiles, with shrinkage for small samples. Label all rankings as descriptive associations, never causal estimates.
5. Export compact, static JSON for the visual app. Keep train artifacts and the SQLite database outside Git; commit reproducible code and the small data products needed for the app.

## Engineering and RAM budget

- Target peak RSS below **2 GB** on this 16 GB laptop. One match at a time for ingest; maximum two numerical-library threads; single-process model fitting; no Spark or full-archive browser load.
- Pin dependencies, deterministic seeds, and schema/data checks. A `make all` run should rebuild database, models, metrics, and app assets from the checked-in source archive.
- Check correctness with score reconciliation, unique delivery keys, legal-ball accounting, player ID mapping, temporal split assertions, finite probabilities, and browser smoke tests.
- Delete stale generated artifacts only after new outputs and tests are working. Preserve Git history.

## Acceptance gates

- Archive mirror matches Cricsheet manifest: 1,243 JSON files and 295,732 deliveries.
- Pipeline completes on this machine without a memory spike, produces model metrics and app assets, and reruns deterministically.
- 2025 and 2026 holdout evaluation is reported honestly, including any failure to beat the baseline.
- The web app can select 2026 matches, render at least four distinct interactive analyses, explain model scope, and show Cricsheet attribution.
- Main branch is pushed only after tests and artifact verification.

## Implementation decisions after modeling

- 1,195 standard chases are eligible. The final state is a known result, including six innings that ended with an absent batter at nine recorded wickets, so no final state enters model training.
- The boosted model won the 2024 raw validation comparison but lost to calibrated logistic in 2025–26. The app uses logistic as its main replay line. Because this choice followed inspection of later scores, those scores are diagnostic rather than an untouched final estimate.
- Career batting balls include no-balls and exclude wides. Scoring trends count boundaries on legal balls only. Bowler conceded runs exclude byes and leg-byes.
- The published app has nine interactive charts, including a browser-side next-ball scenario map and a before-and-after swing audit, plus season-sharded replay data. Automated verification covers data, chart configuration, scenario math against Python reference predictions, and ball-by-ball behavior in every published replay. Local browser visual inspection was blocked by a saved browser permission setting in this workspace.
- The repaired replay model uses five monotonic chase-state inputs and continuous Platt calibration. The previous eleven-feature isotonic model remains in the audit to reproduce the original probability cliffs. See `MODEL_REPAIR.md` for the measured effect and retrospective evaluation caveat.
