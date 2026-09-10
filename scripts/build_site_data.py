"""Export compact, browser-ready IPL Decision Lab datasets from SQLite and models."""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import sqlite3

import joblib
import numpy as np

from build_database import DB_PATH, ROOT
from train_models import state_features


SITE = ROOT / "docs"
DATA = SITE / "data"


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, separators=(",", ":"), ensure_ascii=False))


def build():
    DATA.mkdir(exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    manifest = json.loads((ROOT / "data_manifest.json").read_text())
    report = json.loads((ROOT / "build" / "model_report.json").read_text())
    matches = [dict(row) for row in con.execute("SELECT * FROM matches ORDER BY match_date DESC,match_id DESC")]
    match_lookup = {m["match_id"]: m for m in matches}
    write_json(DATA / "manifest.json", manifest)
    public_report = dict(report)
    public_report.pop("runtime_seconds", None)
    write_json(DATA / "report.json", public_report)
    chase_artifact = joblib.load(ROOT / "build" / "chase_model.joblib")
    baseline = chase_artifact["baseline"]
    scaler = baseline.named_steps["standardscaler"]
    classifier = baseline.named_steps["logisticregression"]
    calibrator = chase_artifact["baseline_calibrator"]
    reference_states = np.asarray([
        state_features(2, 180, 72, 2, 60, 120, [(1, 0)] * 12),
        state_features(2, 180, 156, 6, 108, 120, [(2, 0)] * 12),
        state_features(2, 190, 22, 1, 18, 120, [(0, 0)] * 12),
    ], dtype=np.float32)
    reference_probabilities = calibrator.predict(
        baseline.predict_proba(reference_states)[:, 1])
    scenario_model = {
        "features": chase_artifact["features"],
        "mean": scaler.mean_.tolist(),
        "scale": scaler.scale_.tolist(),
        "coefficients": classifier.coef_[0].tolist(),
        "intercept": float(classifier.intercept_[0]),
        "thresholds": calibrator.X_thresholds_.tolist(),
        "calibrated_values": calibrator.y_thresholds_.tolist(),
        "references": [
            {"features": row.tolist(), "probability": float(probability)}
            for row, probability in zip(reference_states, reference_probabilities)
        ],
    }
    write_json(DATA / "matches.json", [
        {"id": m["match_id"], "date": m["match_date"], "season": m["season"],
         "team1": m["team1_franchise"], "team2": m["team2_franchise"],
         "batting": m["chase_team_franchise"], "winner": m["winner_franchise"],
         "target": m["target"], "overs": m["target_overs"], "chase_runs": m["second_total"],
         "venue": m["venue"], "stage": m["stage"], "eligible": bool(m["eligible_chase"]),
         "exclusion": m["exclusion_reason"]}
        for m in matches
    ])

    season = defaultdict(lambda: {"matches": 0, "runs": 0, "legal_balls": 0,
                                  "deliveries": 0, "fours": 0, "sixes": 0,
                                  "wickets": 0, "first_innings_runs": 0,
                                  "first_innings_count": 0})
    phase = defaultdict(lambda: {"runs": 0, "legal_balls": 0, "boundaries": 0,
                                 "wickets": 0, "deliveries": 0})
    team_seasons = defaultdict(lambda: {"played": 0, "wins": 0})
    for m in matches:
        s = season[m["season"]]
        s["matches"] += 1
        if m["first_total"] is not None:
            s["first_innings_runs"] += m["first_total"]
            s["first_innings_count"] += 1
        for team in {m["team1_franchise"], m["team2_franchise"]}:
            team_seasons[(team, m["season"])]["played"] += 1
        if m["winner_franchise"]:
            team_seasons[(m["winner_franchise"], m["season"])]["wins"] += 1

    names = {}
    batters = defaultdict(lambda: {"runs": 0, "balls": 0, "fours": 0, "sixes": 0,
                                 "matches": set(), "first": 9999, "last": 0})
    bowlers = defaultdict(lambda: {"runs": 0, "balls": 0, "wickets": 0,
                                 "matches": set(), "first": 9999, "last": 0})
    query = """
      SELECT m.season,d.match_id,d.innings_no,d.over_no,d.batter,d.batter_id,
             d.bowler,d.bowler_id,d.batter_runs,d.total_runs,d.wides,d.no_balls,
             d.byes,d.legbyes,d.legal,d.wicket_count,d.bowler_wickets
      FROM deliveries d JOIN matches m USING(match_id)
      WHERE d.innings_no<=2 AND d.is_super_over=0
    """
    for row in con.execute(query):
        y = row["season"]
        s = season[y]
        s["deliveries"] += 1
        s["runs"] += row["total_runs"]
        s["legal_balls"] += row["legal"]
        s["fours"] += row["legal"] and row["batter_runs"] == 4
        s["sixes"] += row["legal"] and row["batter_runs"] == 6
        s["wickets"] += row["wicket_count"]
        stage = "Powerplay" if row["over_no"] < 6 else "Middle" if row["over_no"] < 15 else "Death"
        p = phase[(y, stage)]
        p["runs"] += row["total_runs"]
        p["legal_balls"] += row["legal"]
        p["boundaries"] += row["legal"] and row["batter_runs"] in (4, 6)
        p["wickets"] += row["wicket_count"]
        p["deliveries"] += 1
        batter_id = row["batter_id"] or row["batter"]
        bowler_id = row["bowler_id"] or row["bowler"]
        names[batter_id] = row["batter"]
        names[bowler_id] = row["bowler"]
        b = batters[batter_id]
        b["runs"] += row["batter_runs"]
        # A no-ball counts as faced by the batter; a wide does not.
        b["balls"] += row["wides"] == 0
        b["fours"] += row["batter_runs"] == 4
        b["sixes"] += row["batter_runs"] == 6
        b["matches"].add(row["match_id"])
        b["first"] = min(b["first"], y)
        b["last"] = max(b["last"], y)
        w = bowlers[bowler_id]
        w["runs"] += row["batter_runs"] + row["wides"] + row["no_balls"]
        w["balls"] += row["legal"]
        w["wickets"] += row["bowler_wickets"]
        w["matches"].add(row["match_id"])
        w["first"] = min(w["first"], y)
        w["last"] = max(w["last"], y)

    season_rows = []
    for y, s in sorted(season.items()):
        season_rows.append({"year": y, "matches": s["matches"], "runs": s["runs"],
                            "deliveries": s["deliveries"], "legal_balls": s["legal_balls"],
                            "run_rate": round(6 * s["runs"] / max(s["legal_balls"], 1), 2),
                            "boundary_pct": round(100 * (s["fours"] + s["sixes"]) / max(s["legal_balls"], 1), 2),
                            "wickets": s["wickets"],
                            "avg_first_innings": round(s["first_innings_runs"] / max(s["first_innings_count"], 1), 1)})
    phase_rows = []
    for (y, stage), p in sorted(phase.items()):
        phase_rows.append({"year": y, "phase": stage,
                           "run_rate": round(6 * p["runs"] / max(p["legal_balls"], 1), 2),
                           "boundary_pct": round(100 * p["boundaries"] / max(p["legal_balls"], 1), 2),
                           "wicket_pct": round(100 * p["wickets"] / max(p["legal_balls"], 1), 2),
                           "legal_balls": p["legal_balls"]})
    team_rows = [{"team": t, "year": y, **v, "win_pct": round(100 * v["wins"] / v["played"], 1)}
                 for (t, y), v in sorted(team_seasons.items())]
    write_json(DATA / "atlas.json", {"seasons": season_rows, "phases": phase_rows, "teams": team_rows})

    observed = defaultdict(lambda: [0.0, 0.0, 0])
    allowed = defaultdict(lambda: [0.0, 0.0, 0])
    for mid, y, delivery_no, batter_id, bowler_id, actual, predicted, wicket, wicket_probability in json.loads(
        (ROOT / "build" / "next_ball_predictions.json").read_text()
    ):
        if batter_id:
            row = observed[batter_id]
            row[0] += actual
            row[1] += predicted
            row[2] += 1
        if bowler_id:
            row = allowed[bowler_id]
            row[0] += actual
            row[1] += predicted
            row[2] += 1

    batter_rows = []
    for player_id, s in batters.items():
        if s["balls"] < 60:
            continue
        residual = observed[player_id]
        lift = 100 * (residual[0] - residual[1]) / residual[2] * residual[2] / (residual[2] + 150) if residual[2] >= 60 else None
        batter_rows.append({"id": player_id, "name": names[player_id],
                            "runs": s["runs"], "balls": s["balls"],
                            "strike_rate": round(100 * s["runs"] / s["balls"], 1),
                            "boundary_pct": round(100 * (s["fours"] + s["sixes"]) / s["balls"], 1),
                            "matches": len(s["matches"]), "first": s["first"], "last": s["last"],
                            "recent_context_lift": round(lift, 1) if lift is not None else None,
                            "recent_balls": residual[2]})
    bowler_rows = []
    for player_id, s in bowlers.items():
        if s["balls"] < 60:
            continue
        residual = allowed[player_id]
        suppression = 100 * (residual[1] - residual[0]) / residual[2] * residual[2] / (residual[2] + 150) if residual[2] >= 60 else None
        bowler_rows.append({"id": player_id, "name": names[player_id],
                            "wickets": s["wickets"], "balls": s["balls"],
                            "economy": round(6 * s["runs"] / s["balls"], 2),
                            "wickets_per_100": round(100 * s["wickets"] / s["balls"], 2),
                            "matches": len(s["matches"]), "first": s["first"], "last": s["last"],
                            "recent_run_suppression": round(suppression, 1) if suppression is not None else None,
                            "recent_balls": residual[2]})
    write_json(DATA / "players.json", {"batters": sorted(batter_rows, key=lambda x: -x["runs"]),
                                        "bowlers": sorted(bowler_rows, key=lambda x: -x["wickets"])})

    probabilities = np.load(ROOT / "build" / "chase_predictions.npz")
    probability_lookup = {
        (int(mid), int(dno)): (round(float(p), 4), round(float(q), 4))
        for mid, dno, p, q in zip(probabilities["match_id"], probabilities["delivery_no"],
                                 probabilities["probability"], probabilities["boosted_probability"])
    }
    replays = defaultdict(dict)
    query = """
      SELECT d.match_id,d.delivery_no,d.over_no,d.actual_delivery,d.batter,d.bowler,
             d.total_runs,d.wicket_count,d.wicket_kinds,d.legal
      FROM deliveries d JOIN matches m USING(match_id)
      WHERE m.eligible_chase=1 AND d.innings_no=2
      ORDER BY d.match_id,d.delivery_no
    """
    current_id = None
    runs = wickets = legal_balls = 0
    trace = []
    for row in con.execute(query):
        mid = row["match_id"]
        if mid != current_id:
            if current_id is not None:
                trace[-1][4] = trace[-1][5] = int(bool(match_lookup[current_id]["chase_won"]))
                replays[str(match_lookup[current_id]["season"])][str(current_id)] = trace
            current_id = mid
            runs = wickets = legal_balls = 0
            trace = []
        m = match_lookup[mid]
        runs += row["total_runs"]
        wickets += row["wicket_count"]
        legal_balls += row["legal"]
        p, q = probability_lookup.get((mid, row["delivery_no"]), (None, None))
        if p is None:
            p = q = int(bool(m["chase_won"]))
        point = [row["delivery_no"], legal_balls, runs, wickets, p, q,
                 row["batter"], row["bowler"], row["total_runs"], row["wicket_kinds"] or ""]
        trace.append(point)
    if current_id is not None:
        trace[-1][4] = trace[-1][5] = int(bool(match_lookup[current_id]["chase_won"]))
        replays[str(match_lookup[current_id]["season"])][str(current_id)] = trace
    for year, rows in replays.items():
        write_json(DATA / "replays" / f"{year}.json", rows)
    scenario_references = []
    for match_id, selected_index, next_runs, next_wicket in [
        (1535465, 50, 4, 0),
        (1535465, 50, 0, 1),
        (1527686, 25, 2, 0),
    ]:
        match = match_lookup[match_id]
        points = replays[str(match["season"])][str(match_id)]
        current = points[selected_index]
        recent = [
            (points[i][8], points[i][3] - (points[i - 1][3] if i else 0))
            for i in range(max(0, selected_index - 10), selected_index + 1)
        ] + [(next_runs, next_wicket)]
        features = np.asarray([state_features(
            2, match["target"], current[2] + next_runs, current[3] + next_wicket,
            current[1] + 1, match["target_overs"] * 6, recent,
        )], dtype=np.float32)
        probability = float(calibrator.predict(baseline.predict_proba(features)[:, 1])[0])
        scenario_references.append({
            "match_id": match_id, "season": match["season"], "selected_index": selected_index,
            "next_runs": next_runs, "next_wicket": next_wicket, "probability": probability,
        })
    scenario_model["scenario_references"] = scenario_references
    write_json(DATA / "scenario_model.json", scenario_model)
    con.close()
    return {"matches": len(matches), "replay_matches": sum(map(len, replays.values())),
            "batter_profiles": len(batter_rows), "bowler_profiles": len(bowler_rows),
            "site_data_megabytes": round(sum(p.stat().st_size for p in DATA.rglob("*.json")) / 1e6, 2)}


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
