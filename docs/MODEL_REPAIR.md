# Chase win probability repair

## What failed

The old replay combined an eleven-feature logistic model with isotonic calibration fitted on 2024. That calibrator had only 40 distinct output levels. One adjacent pair of raw scores, about 0.172431 and 0.172519, mapped to probabilities 12.77 percentage points apart. A small improvement after a four could therefore appear as a 16 to 32 percent jump. A dot could cross the same step in the other direction.

The old model also used wickets in the last 12 recorded deliveries. When a past wicket left that window, a dot could increase the forecast despite consuming a legal ball and scoring no run. The replay then joined its final model forecast to a forced 0 or 100 percent known outcome and called that gap a delivery swing. That final endpoint was not a prediction.

The boosted chase model is still published for audit but is not drawn in the replay. Its 2025–26 calibrated Brier was 0.16198, well behind either logistic model.

## Repair

- Train the replay model on whole 2008–23 matches with five chase-state inputs: target, wickets, legal balls left, runs required, and required run rate. The fitted directions are sensible for the next-ball simulator: another wicket lowers the forecast; more runs at fixed clock and wickets raise it; a scoreless legal ball lowers it.
- Fit a continuous Platt logistic mapping on 2024 raw decision scores. Export its coefficients and calibration parameters to the browser. The static smoke test checks Python and JavaScript probability parity on reference states and real scenarios, including an 11-over chase.
- End the forecast line at the last nonfinal delivery. Draw the known result as a separate marker. The result is never counted as a model swing or a next-ball starting point.
- Retain the previous replay model and the boosted model as reproducible audit comparisons. Rebuild all 19 replay shards, the scenario model, and the public report from the same training artifacts.

## Measured behavior

The 2025–26 diagnostic period contains 15,921 nonterminal chase states in 140 matches. Ball transitions below are from full 20-over chases, with consecutive recorded deliveries, one legal ball, no wicket, and exactly the listed team runs. Early means overs 1–6; middle means overs 7–15. The chart on the site uses the 99th percentile of absolute changes. In shortened chases, an over labeled "middle" can be near the final ball, so its legitimate swings need separate interpretation.

| Delivery | Count | Previous p99 | Repaired p99 | Previous max | Repaired max |
| --- | ---: | ---: | ---: | ---: | ---: |
| Early dot | 1,770 | 12.77 pp | 1.78 pp | 14.69 pp | 1.91 pp |
| Early four | 911 | 17.96 pp | 5.43 pp | 17.96 pp | 5.61 pp |
| Middle dot | 1,721 | 13.13 pp | 3.58 pp | 14.86 pp | 4.64 pp |
| Middle four | 862 | 17.96 pp | 7.02 pp | 18.47 pp | 7.56 pp |

The previous model had ten early or middle dots that **increased** win probability by more than half a point. The repaired model had zero. The tests enforce direction and sensible bounds on the actual published replay JSON, not only on raw model output. Near the end of a chase, a real boundary, wicket, or clock event can still cause a large and legitimate change; there is no arbitrary cap on all probabilities.

| 2025–26 metric | Previous replay | Repaired replay |
| --- | ---: | ---: |
| Brier, lower is better | 0.12538 | 0.12235 |
| Match-weighted Brier | 0.12129 | 0.11821 |
| Log loss | 0.39211 | 0.38027 |
| ROC AUC | 0.90995 | 0.91089 |
| Ten-bin calibration error | 0.05499 | 0.04502 |

Resampling entire matches gives a 95 percent interval of **-0.00521 to -0.00091** for repaired minus previous match-weighted Brier. The old isotonic fit scored 0.11949 on 2024; the new continuous fit scored 0.12195. Both calibrators were fitted on that same 2024 season, so these are in-sample calibration scores. The old model's better 2024 number did not reveal its sharp steps or later drift. The repaired model's features and calibration were selected after looking at 2025–26, so those later scores are retrospective diagnostics, not a pristine prospective estimate. Historical replay games are in the training sample. The model has no player or matchup effects and cannot assign a probability to which hypothetical next-ball event will occur.

## Reproduce

Run `make all && make test`. The report in `docs/data/report.json` contains the transition counts, score comparisons, and match bootstrap interval. The test suite checks every published replay, known terminal results, scenario math, and all nine chart configurations.
