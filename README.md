# IPL Decision Lab

An interactive, ball-by-ball IPL research lab. The checked-in [Cricsheet](https://cricsheet.org/downloads/) snapshot covers **1,243 matches and 295,732 recorded deliveries from 2008 through 2026**. The app replays 1,195 standard chases and exposes its model errors alongside the cricket.

**[Open the live IPL Decision Lab](https://aneesh495.github.io/ipl/)**

## Explore

- **Match lab:** Browse every standard chase, watch the calibrated win forecast respond after each nonfinal delivery, and inspect the biggest swings. The final result is marked separately.
- **Next-ball lab:** Click a run-and-wicket outcome to recompute the calibrated chase forecast from any nonfinal replay point.
- **Era atlas:** Compare scoring, boundaries, wickets, first-innings totals, phases, and franchise win rates across 19 seasons.
- **Player landscape:** Explore career batting and bowling profiles. Recent run residuals compare 2025–26 observed outcomes with a next-ball model, with small-sample shrinkage.
- **Model audit:** Inspect calibration, Brier scores, temporal evaluation, feature importance, and where the more flexible model fails.

The static app is in [docs/](docs/index.html). It works without an API or database server:

~~~bash
make setup     # install uv first: https://docs.astral.sh/uv/getting-started/installation/
make all       # rebuild SQLite, models, and browser data from checked-in JSON
make assets    # refresh the shared asset version after frontend edits
make test      # data checks, asset-version check, and app smoke test
make serve     # open http://localhost:8000/docs/
~~~

The data snapshot is already committed. Run make refresh to download the latest IPL JSON archive from Cricsheet, validate it, and update json/, README.txt, and data_manifest.json. Review the new manifest and rebuild after a refresh. The checked-in snapshot's SHA-256 and retrieval timestamp are in [data_manifest.json](data_manifest.json).

GitHub Pages caches HTML, scripts, styles, and data independently. The build gives every published asset the same content-derived URL version so a returning browser loads one consistent release. Run `make assets` after changing `docs/app.js` or `docs/styles.css`; `make test` rejects stale version tags.

## What the models actually did

The replay model predicts the eventual winner **after a delivery**, using the target, wickets, legal balls remaining, runs required, and required run rate. A continuous Platt calibration replaces the previous stepped isotonic mapping. Terminal states are shown as known outcomes and are excluded from training and scoring. Matches with adjusted targets, extra or missing innings, or no regulation winner are retained in the archive and atlas but excluded from chase modeling.

| Period | Role | Seasons |
| --- | --- | --- |
| Historical training | Fit logistic, boosted chase, and next-ball models | 2008–23 |
| Calibration and tree tuning | Fit probability calibrators and choose tree settings | 2024 |
| Later diagnostic period | Evaluate out-of-time performance | 2025–26 |

On 15,921 chase states from 140 matches in 2025–26, the repaired replay model reached **0.12235 Brier**, **0.38027 log loss**, and **0.91089 ROC AUC**. The previous replay model scored **0.12538 Brier**; calibrated boosted trees scored **0.16198**. On early legal four-run deliveries in full 20-over chases during that period, the largest displayed change fell from **17.96** to **5.61 percentage points**. The displayed replay model and its features were chosen after inspecting these later seasons, so these figures are **retrospective diagnostics, not an untouched prospective estimate**. Multiple states from one match share the same outcome; the report includes match-weighted Brier and match-level bootstrap intervals. See [the model repair audit](docs/MODEL_REPAIR.md) for the failure analysis and ball-by-ball checks.

The second model predicts batter runs and wicket risk for the next legal delivery using pre-ball match state. On 31,900 legal deliveries in 2025–26, its run MSE was **3.38326** versus **3.47838** for a constant mean; its run MAE was **1.36805** versus **1.35614** for that baseline. Wicket Brier was **0.04923** versus **0.04973** for a constant wicket rate. The player residuals are descriptive associations, not causal player-value estimates.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for feature definitions, cricket accounting, exclusions, and audit details. [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md) records the research plan and implementation decisions. Full numerical results are generated in build/model_report.json and published in [docs/data/report.json](docs/data/report.json).

## Reproducibility and resources

~~~text
Cricsheet JSON (1,243 files, data version 1.2.0)
  → SQLite matches + deliveries
  → 137,488 nonterminal chase states + 275,857 legal-ball examples
  → temporal training, calibration, and model audit
  → compact static JSON, 19 replay shards, and nine interactive charts
~~~

uv.lock pins the Python environment. The build uses a single process and caps numerical-library threads at two. On the development laptop, /usr/bin/time -l make all reported **477,233,152 bytes peak resident memory**, about **455 MiB**. SQLite and trained joblib models live in ignored build/; the published docs/data/ payload is about 8.5 MB total and loads replays one season at a time.

Match data is from [Cricsheet and its contributors](https://cricsheet.org/). The charting library is vendored ECharts 5.5.1 with its Apache 2.0 license in docs/vendor/.
