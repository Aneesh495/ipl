"""Train leakage-controlled IPL chase and next-ball models with temporal tests."""

from __future__ import annotations

from collections import defaultdict, deque
import json
import os
from pathlib import Path
import sqlite3
import time

os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "2")

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, mean_absolute_error, mean_squared_error, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.isotonic import IsotonicRegression

from build_database import DB_PATH, ROOT


FEATURES = [
    "innings", "target", "runs", "wickets", "legal_balls_used", "balls_left",
    "runs_required", "current_run_rate", "required_run_rate",
    "last_12_delivery_runs", "last_12_delivery_wickets",
]
SEED = 42


def state_features(innings_no, target, runs, wickets, legal_used, balls_total, recent):
    needed = max(0, target - runs) if innings_no == 2 else 0
    left = max(0, balls_total - legal_used)
    return [
        innings_no, target if innings_no == 2 else 0, runs, wickets,
        legal_used, left, needed, 6 * runs / max(legal_used, 1),
        6 * needed / max(left, 1),
        sum(x[0] for x in recent), sum(x[1] for x in recent),
    ]


def load_features(database: Path = DB_PATH):
    con = sqlite3.connect(database)
    query = """
      SELECT m.match_id,m.season,m.target,m.target_overs,m.chase_won,
             d.innings_no,d.delivery_no,d.over_no,d.total_runs,d.batter_runs,
             d.legal,d.wicket_count,d.batter_id,d.bowler_id
      FROM deliveries d JOIN matches m USING(match_id)
      WHERE m.eligible_chase=1 AND d.innings_no<=2 AND d.is_super_over=0
      ORDER BY m.match_date,m.match_id,d.innings_no,d.delivery_no
    """
    chase_x, chase_y, chase_meta = [], [], []
    ball_x, ball_runs, ball_wicket, ball_meta = [], [], [], []
    last_chase_delivery = {}
    current = None
    runs = wickets = legal_used = 0
    recent = deque(maxlen=12)
    for (match_id, season, target, target_overs, chase_won,
         innings_no, delivery_no, over_no, total_runs, batter_runs,
         legal, wicket_count, batter_id, bowler_id) in con.execute(query):
        key = (match_id, innings_no)
        if key != current:
            current = key
            runs = wickets = legal_used = 0
            recent.clear()
        total_balls = (target_overs if innings_no == 2 else 20) * 6
        pre = state_features(innings_no, target, runs, wickets, legal_used, total_balls, recent)
        if legal:
            ball_x.append(pre)
            ball_runs.append(batter_runs)
            ball_wicket.append(int(wicket_count > 0))
            ball_meta.append((match_id, season, delivery_no, batter_id or "", bowler_id or ""))
        runs += total_runs
        wickets += wicket_count
        legal_used += legal
        recent.append((total_runs, wicket_count))
        if innings_no == 2:
            last_chase_delivery[match_id] = delivery_no
        if innings_no == 2 and target - runs > 0 and legal_used < total_balls and wickets < 10:
            chase_x.append(state_features(innings_no, target, runs, wickets, legal_used, total_balls, recent))
            chase_y.append(chase_won)
            chase_meta.append((match_id, season, delivery_no))
    con.close()
    # A few innings end with nine recorded wickets because another batter is absent.
    # The last recorded delivery ends those matches even though numeric state limits do not.
    keep = [i for i, (mid, _, delivery_no) in enumerate(chase_meta)
            if delivery_no != last_chase_delivery[mid]]
    chase_x = [chase_x[i] for i in keep]
    chase_y = [chase_y[i] for i in keep]
    chase_meta = [chase_meta[i] for i in keep]
    return (
        np.asarray(chase_x, dtype=np.float32), np.asarray(chase_y, dtype=np.int8), chase_meta,
        np.asarray(ball_x, dtype=np.float32), np.asarray(ball_runs, dtype=np.float32),
        np.asarray(ball_wicket, dtype=np.int8), ball_meta,
    )


def split(years):
    years = np.asarray(years)
    return years <= 2023, years == 2024, years >= 2025


def score_classifier(y, p, match_ids):
    p = np.clip(np.asarray(p), 1e-5, 1 - 1e-5)
    by_match = defaultdict(list)
    for match_id, error in zip(match_ids, (p - y) ** 2):
        by_match[int(match_id)].append(float(error))
    return {
        "states": int(len(y)), "matches": len(by_match),
        "brier": round(float(brier_score_loss(y, p)), 5),
        "match_weighted_brier": round(float(np.mean([np.mean(v) for v in by_match.values()])), 5),
        "log_loss": round(float(log_loss(y, p, labels=[0, 1])), 5),
        "auc": round(float(roc_auc_score(y, p)), 5) if len(np.unique(y)) == 2 else None,
        "ece_10": round(float(sum(
            len(y[(p >= lo) & (p < hi)]) / len(y) *
            abs(float(np.mean(y[(p >= lo) & (p < hi)])) - float(np.mean(p[(p >= lo) & (p < hi)])))
            for lo, hi in zip(np.linspace(0, 1, 11)[:-1], np.linspace(0, 1, 11)[1:])
            if np.any((p >= lo) & (p < hi))
        )), 5),
    }


def reliability(y, p, bins=10):
    edges = np.linspace(0, 1, bins + 1)
    result = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        selected = (p >= lo) & (p < hi if hi < 1 else p <= hi)
        if selected.any():
            result.append({"predicted": round(float(np.mean(p[selected])), 4),
                           "observed": round(float(np.mean(y[selected])), 4),
                           "states": int(selected.sum())})
    return result


def match_bootstrap_brier(y, p, match_ids, repeats=300):
    grouped = defaultdict(list)
    for match_id, error in zip(match_ids, (p - y) ** 2):
        grouped[int(match_id)].append(float(error))
    means = np.array([np.mean(x) for x in grouped.values()])
    rng = np.random.default_rng(SEED)
    sampled = means[rng.integers(0, len(means), size=(repeats, len(means)))].mean(axis=1)
    return [round(float(v), 5) for v in np.quantile(sampled, [0.025, 0.975])]


def main():
    start = time.time()
    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    chase_x, chase_y, chase_meta, ball_x, ball_runs, ball_wicket, ball_meta = load_features()
    years = np.array([x[1] for x in chase_meta], dtype=np.int16)
    ids = np.array([x[0] for x in chase_meta], dtype=np.int32)
    train, val, test = split(years)
    assert set(ids[train]).isdisjoint(set(ids[val]))
    assert set(ids[train]).isdisjoint(set(ids[test]))
    assert set(ids[val]).isdisjoint(set(ids[test]))
    assert train.sum() > 100_000 and val.sum() > 5_000 and test.sum() > 10_000

    baseline = make_pipeline(StandardScaler(), LogisticRegression(C=0.2, max_iter=700, random_state=SEED))
    baseline.fit(chase_x[train], chase_y[train])
    baseline_val = baseline.predict_proba(chase_x[val])[:, 1]
    baseline_test = baseline.predict_proba(chase_x[test])[:, 1]
    baseline_calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.001, y_max=0.999)
    baseline_calibrator.fit(baseline_val, chase_y[val])
    baseline_cal_test = baseline_calibrator.predict(baseline_test)

    candidates = []
    for leaves, iterations in [(15, 120), (31, 180)]:
        model = HistGradientBoostingClassifier(
            max_leaf_nodes=leaves, max_iter=iterations, learning_rate=0.06,
            min_samples_leaf=100, l2_regularization=5, random_state=SEED,
        )
        model.fit(chase_x[train], chase_y[train])
        raw_val = model.predict_proba(chase_x[val])[:, 1]
        candidates.append((float(brier_score_loss(chase_y[val], raw_val)), leaves, iterations, model))
    val_brier, leaves, iterations, model = min(candidates, key=lambda item: item[0])
    calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.001, y_max=0.999)
    calibrator.fit(model.predict_proba(chase_x[val])[:, 1], chase_y[val])
    raw_test = model.predict_proba(chase_x[test])[:, 1]
    calibrated_test = calibrator.predict(raw_test)
    all_probability = baseline_calibrator.predict(baseline.predict_proba(chase_x)[:, 1])
    all_boosted_probability = calibrator.predict(model.predict_proba(chase_x)[:, 1])
    np.savez_compressed(build / "chase_predictions.npz",
                        match_id=ids, delivery_no=np.array([x[2] for x in chase_meta], dtype=np.int16),
                        probability=all_probability.astype(np.float32),
                        boosted_probability=all_boosted_probability.astype(np.float32))
    joblib.dump({"baseline": baseline, "baseline_calibrator": baseline_calibrator,
                 "boosted": model, "boosted_calibrator": calibrator,
                 "features": FEATURES}, build / "chase_model.joblib")

    permutation = permutation_importance(
        model, chase_x[val][:4000], chase_y[val][:4000],
        scoring="neg_brier_score", n_repeats=3, random_state=SEED,
    )
    importance = sorted(
        [{"feature": name, "brier_increase": round(float(value), 5)}
         for name, value in zip(FEATURES, permutation.importances_mean)],
        key=lambda row: row["brier_increase"], reverse=True,
    )

    ball_years = np.array([x[1] for x in ball_meta], dtype=np.int16)
    btrain, bval, btest = split(ball_years)
    run_model = HistGradientBoostingRegressor(
        max_iter=100, max_leaf_nodes=15, learning_rate=0.05,
        min_samples_leaf=150, l2_regularization=10, random_state=SEED,
    )
    run_model.fit(ball_x[btrain], ball_runs[btrain])
    wicket_model = HistGradientBoostingClassifier(
        max_iter=100, max_leaf_nodes=15, learning_rate=0.05,
        min_samples_leaf=150, l2_regularization=10, random_state=SEED,
    )
    wicket_model.fit(ball_x[btrain], ball_wicket[btrain])
    run_pred = np.clip(run_model.predict(ball_x[btest]), 0, None)
    wicket_pred = wicket_model.predict_proba(ball_x[btest])[:, 1]
    ball_predictions = []
    test_indices = np.flatnonzero(btest)
    for j, index in enumerate(test_indices):
        mid, season, delivery_no, batter_id, bowler_id = ball_meta[index]
        ball_predictions.append((mid, season, delivery_no, batter_id, bowler_id,
                                 float(ball_runs[index]), float(run_pred[j]),
                                 int(ball_wicket[index]), float(wicket_pred[j])))
    joblib.dump({"runs": run_model, "wicket": wicket_model, "features": FEATURES},
                build / "next_ball_models.joblib")
    (build / "next_ball_predictions.json").write_text(json.dumps(ball_predictions, separators=(",", ":")))

    report = {
        "source_archive_sha256": json.loads((ROOT / "data_manifest.json").read_text())["archive_sha256"],
        "feature_names": FEATURES,
        "training": {"train_years": "2008-2023", "validation_year": 2024,
                     "test_years": [2025, 2026], "random_seed": SEED,
                     "selected_max_leaf_nodes": leaves, "selected_iterations": iterations,
                     "validation_logistic_raw_brier": round(float(brier_score_loss(chase_y[val], baseline_val)), 5),
                     "validation_raw_brier": round(val_brier, 5),
                     "terminal_chase_states_excluded": True,
                     "replay_model_selection": "Retrospective: calibrated logistic chosen after inspecting 2025-2026 aggregate performance; holdout scores are diagnostic, not an untouched final estimate."},
        "chase": {
            "baseline_logistic": score_classifier(chase_y[test], baseline_test, ids[test]),
            "calibrated_logistic": score_classifier(chase_y[test], baseline_cal_test, ids[test]),
            "gradient_boosting_raw": score_classifier(chase_y[test], raw_test, ids[test]),
            "gradient_boosting_calibrated": score_classifier(chase_y[test], calibrated_test, ids[test]),
            "brier_match_bootstrap_95pct": match_bootstrap_brier(chase_y[test], baseline_cal_test, ids[test]),
            "reliability": reliability(chase_y[test], baseline_cal_test),
            "feature_importance": importance,
            "by_season": {}, "by_stage": {},
        },
        "next_ball": {
            "test_legal_balls": int(btest.sum()),
            "runs_mse": round(float(mean_squared_error(ball_runs[btest], run_pred)), 5),
            "runs_constant_baseline_mse": round(float(mean_squared_error(
                ball_runs[btest], np.full(btest.sum(), float(np.mean(ball_runs[btrain]))))), 5),
            "runs_mae": round(float(mean_absolute_error(ball_runs[btest], run_pred)), 5),
            "runs_constant_baseline_mae": round(float(mean_absolute_error(
                ball_runs[btest], np.full(btest.sum(), float(np.mean(ball_runs[btrain]))))), 5),
            "wicket_brier": round(float(brier_score_loss(ball_wicket[btest], wicket_pred)), 5),
            "wicket_constant_baseline_brier": round(float(brier_score_loss(
                ball_wicket[btest], np.full(btest.sum(), float(np.mean(ball_wicket[btrain]))))), 5),
        },
    }
    for season in [2025, 2026]:
        mask = test & (years == season)
        report["chase"]["by_season"][str(season)] = score_classifier(
            chase_y[mask], all_probability[mask], ids[mask])
    balls_left = chase_x[:, FEATURES.index("balls_left")]
    for name, stage_mask in [
        ("early_overs_1_6", balls_left > 84),
        ("middle_overs_7_15", (balls_left <= 84) & (balls_left > 30)),
        ("death_overs_16_20", balls_left <= 30),
    ]:
        mask = test & stage_mask
        report["chase"]["by_stage"][name] = score_classifier(
            chase_y[mask], all_probability[mask], ids[mask])
    report["runtime_seconds"] = round(time.time() - start, 2)
    (build / "model_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"chase_states": len(chase_y), "legal_balls": len(ball_runs),
                      "chase_test": report["chase"]["calibrated_logistic"],
                      "next_ball": report["next_ball"],
                      "runtime_seconds": report["runtime_seconds"]}, indent=2))


if __name__ == "__main__":
    main()
