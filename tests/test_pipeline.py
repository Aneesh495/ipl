"""Data, cricket-rule, temporal split, and published-artifact checks."""

import json
import pathlib
import sqlite3
import sys
import unittest

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_database import DB_PATH, exclusion
from train_models import split, state_features


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((ROOT / "data_manifest.json").read_text())
        cls.report = json.loads((ROOT / "build" / "model_report.json").read_text())
        cls.con = sqlite3.connect(DB_PATH)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def test_archive_and_feature_store_cover_all_seasons(self):
        self.assertEqual(self.manifest["matches"], 1243)
        self.assertEqual(self.manifest["deliveries"], 295732)
        self.assertEqual(len(list((ROOT / "json").glob("*.json"))), self.manifest["matches"])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM matches").fetchone()[0], 1243)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0], 295732)
        years = [row[0] for row in self.con.execute("SELECT DISTINCT season FROM matches ORDER BY season")]
        self.assertEqual(years, list(range(2008, 2027)))
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM matches WHERE season=2026").fetchone()[0], 74)

    def test_delivery_keys_scores_and_legal_balls(self):
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM deliveries WHERE legal=0").fetchone()[0] > 0, True)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM deliveries WHERE wides>0 AND legal=1").fetchone()[0], 0)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM deliveries WHERE no_balls>0 AND legal=1").fetchone()[0], 0)
        mismatches = self.con.execute("""
            SELECT COUNT(*) FROM matches m JOIN (
              SELECT match_id, innings_no, SUM(total_runs) AS score FROM deliveries GROUP BY match_id, innings_no
            ) d USING(match_id)
            WHERE (d.innings_no=1 AND d.score<>m.first_total)
               OR (d.innings_no=2 AND d.score<>m.second_total)
        """).fetchone()[0]
        self.assertEqual(mismatches, 0)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM matches WHERE eligible_chase=1").fetchone()[0], 1195)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM matches WHERE eligible_chase=1 AND target<>first_total+1").fetchone()[0], 0)

    def test_exclusion_and_chase_state_use_only_known_information(self):
        info = {"teams": ["A", "B"], "outcome": {"winner": "B"}}
        innings = [{"team": "A"}, {"team": "B", "target": {"runs": 101, "overs": 20}}]
        self.assertIsNone(exclusion(info, innings, 100, 101))
        self.assertEqual(exclusion(info, innings, 100, 102), "target_mismatch")
        self.assertEqual(exclusion({**info, "outcome": {"result": "no result"}}, innings, 100, 101), "no_regulation_winner")
        feature = state_features(2, 150, 30, 4, 50, 120, [(2, 0), (0, 1)])
        self.assertEqual(feature[2:7], [30, 4, 50, 70, 120])
        self.assertEqual(feature[-2:], [2, 1])

    def test_temporal_split_and_probabilities(self):
        years = np.array([2023, 2024, 2025, 2026])
        a, b, c = split(years)
        self.assertEqual(a.tolist(), [True, False, False, False])
        self.assertEqual(b.tolist(), [False, True, False, False])
        self.assertEqual(c.tolist(), [False, False, True, True])
        predictions = np.load(ROOT / "build" / "chase_predictions.npz")
        self.assertGreater(len(predictions["probability"]), 130000)
        self.assertEqual(len(predictions["probability"]), len(predictions["match_id"]))
        self.assertTrue(np.isfinite(predictions["probability"]).all())
        self.assertTrue(((predictions["probability"] >= 0) & (predictions["probability"] <= 1)).all())
        self.assertLess(self.report["chase"]["calibrated_logistic"]["brier"],
                        self.report["chase"]["gradient_boosting_calibrated"]["brier"])

    def test_published_replays_and_audit(self):
        matches = json.loads((ROOT / "docs" / "data" / "matches.json").read_text())
        eligible = [m for m in matches if m["eligible"]]
        match_lookup = {str(m["id"]): m for m in eligible}
        published = 0
        checked = {"early_dot": 0, "early_four": 0, "middle_dot": 0, "middle_four": 0}
        for year in range(2008, 2027):
            replays = json.loads((ROOT / "docs" / "data" / "replays" / f"{year}.json").read_text())
            published += len(replays)
            for mid, points in replays.items():
                self.assertGreater(len(points), 1)
                self.assertIn(points[-1][4], (0, 1))
                if year < 2025 or match_lookup[mid]["overs"] != 20:
                    continue
                for previous, current in zip(points[:-2], points[1:-1]):
                    if current[1] - previous[1] != 1 or current[3] != previous[3]:
                        continue
                    phase = "early" if previous[1] < 36 else "middle" if previous[1] < 90 else None
                    runs = current[2] - previous[2]
                    event = "dot" if runs == 0 else "four" if runs == 4 else None
                    if not phase or not event:
                        continue
                    key = f"{phase}_{event}"
                    checked[key] += 1
                    delta = 100 * (current[4] - previous[4])
                    self.assertGreaterEqual(delta, -0.51 if event == "four" else -9)
                    self.assertLessEqual(delta, 0.51 if event == "dot" else 9)
                    if phase == "early":
                        self.assertLessEqual(abs(delta), 3 if event == "dot" else 7)
                    else:
                        self.assertLessEqual(abs(delta), 6 if event == "dot" else 9)
        self.assertEqual(published, len(eligible))
        self.assertEqual(sum(m["season"] == 2026 for m in eligible), 71)
        self.assertTrue(all(count > 500 for count in checked.values()))
        self.assertEqual(checked, {key: value["count"] for key, value in
                                   self.report["chase"]["replay_transitions"].items()})
        self.assertEqual(self.report["source_archive_sha256"], self.manifest["archive_sha256"])

    def test_batter_balls_faced_include_no_balls(self):
        players = json.loads((ROOT / "docs" / "data" / "players.json").read_text())
        batter = next(p for p in players["batters"] if p["name"] == "V Kohli")
        faced, legal = self.con.execute("""
            SELECT SUM(wides=0), SUM(legal) FROM deliveries
            WHERE innings_no<=2 AND is_super_over=0 AND batter_id=?
        """, (batter["id"],)).fetchone()
        self.assertGreater(faced, legal)
        self.assertEqual(batter["balls"], faced)
        self.assertEqual(batter["strike_rate"], round(100 * batter["runs"] / faced, 1))


if __name__ == "__main__":
    unittest.main()
