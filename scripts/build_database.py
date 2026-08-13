"""Stream Cricsheet JSON into a normalized, queryable SQLite database."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import sqlite3


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "build" / "ipl.sqlite"
TEAM_ALIASES = {
    "Delhi Daredevils": "Delhi Capitals",
    "Kings XI Punjab": "Punjab Kings",
    "Royal Challengers Bangalore": "Royal Challengers Bengaluru",
    "Rising Pune Supergiants": "Rising Pune Supergiant",
}
NON_WICKETS = {"retired hurt", "absent hurt"}
NON_BOWLER_WICKETS = NON_WICKETS | {
    "run out", "retired out", "obstructing the field", "handled the ball"
}


def canonical_team(name: str | None) -> str | None:
    return TEAM_ALIASES.get(name, name)


SCHEMA = """
CREATE TABLE matches (
  match_id INTEGER PRIMARY KEY, match_date TEXT NOT NULL, season INTEGER NOT NULL,
  stage TEXT, team1 TEXT NOT NULL, team2 TEXT NOT NULL,
  team1_franchise TEXT NOT NULL, team2_franchise TEXT NOT NULL,
  venue TEXT, winner TEXT, winner_franchise TEXT, toss_winner TEXT,
  chase_team TEXT, chase_team_franchise TEXT, chase_won INTEGER,
  target INTEGER, target_overs INTEGER, first_total INTEGER, second_total INTEGER,
  innings_count INTEGER NOT NULL, deliveries INTEGER NOT NULL,
  method TEXT, eligible_chase INTEGER NOT NULL, exclusion_reason TEXT
);
CREATE TABLE deliveries (
  match_id INTEGER NOT NULL, innings_no INTEGER NOT NULL, delivery_no INTEGER NOT NULL,
  over_no INTEGER NOT NULL, actual_delivery TEXT, batting_team TEXT NOT NULL,
  batter TEXT NOT NULL, batter_id TEXT, bowler TEXT NOT NULL, bowler_id TEXT,
  non_striker TEXT, batter_runs INTEGER NOT NULL, extras_runs INTEGER NOT NULL,
  total_runs INTEGER NOT NULL, wides INTEGER NOT NULL, no_balls INTEGER NOT NULL,
  byes INTEGER NOT NULL, legbyes INTEGER NOT NULL, legal INTEGER NOT NULL,
  wicket_count INTEGER NOT NULL, bowler_wickets INTEGER NOT NULL,
  wicket_kinds TEXT, is_super_over INTEGER NOT NULL,
  PRIMARY KEY (match_id, innings_no, delivery_no)
);
CREATE INDEX deliveries_match_innings ON deliveries(match_id, innings_no);
CREATE INDEX deliveries_batter ON deliveries(batter_id);
CREATE INDEX deliveries_bowler ON deliveries(bowler_id);
CREATE INDEX matches_date ON matches(match_date);
"""


def exclusion(info: dict, innings: list, first_total: int, target: int | None) -> str | None:
    if len(innings) != 2 or any(item.get("super_over") for item in innings):
        return "extra_or_missing_innings"
    if info.get("outcome", {}).get("method"):
        return "adjusted_target"
    winner = info.get("outcome", {}).get("winner")
    if winner not in info["teams"]:
        return "no_regulation_winner"
    if target is None or target <= 0 or not innings[1].get("target", {}).get("overs"):
        return "missing_target"
    if innings[0]["team"] == innings[1]["team"]:
        return "invalid_innings_teams"
    if target != first_total + 1:
        return "target_mismatch"
    return None


def build_database(path: Path = DB_PATH) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp.sqlite")
    temporary.unlink(missing_ok=True)
    con = sqlite3.connect(temporary)
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("PRAGMA synchronous=OFF")
    con.executescript(SCHEMA)
    exclusions: Counter[str] = Counter()
    match_count = delivery_count = 0
    try:
        for file in sorted((ROOT / "json").glob("*.json")):
            data = json.loads(file.read_text())
            info = data["info"]
            innings = data["innings"]
            match_id = int(file.stem)
            date = str(info["dates"][0])
            players = info.get("registry", {}).get("people", {})
            totals = []
            delivery_rows = []
            for innings_no, inning in enumerate(innings, start=1):
                innings_total = 0
                delivery_no = 0
                for over in inning["overs"]:
                    for ball in over["deliveries"]:
                        delivery_no += 1
                        extras = ball.get("extras", {})
                        runs = ball["runs"]
                        wickets = ball.get("wickets", [])
                        valid_wickets = [w for w in wickets if w["kind"] not in NON_WICKETS]
                        bowler_wickets = sum(w["kind"] not in NON_BOWLER_WICKETS for w in wickets)
                        innings_total += runs["total"]
                        delivery_rows.append((
                            match_id, innings_no, delivery_no, int(over["over"]),
                            ball.get("actual_delivery"), inning["team"],
                            ball["batter"], players.get(ball["batter"]),
                            ball["bowler"], players.get(ball["bowler"]),
                            ball.get("non_striker"), int(runs["batter"]),
                            int(runs["extras"]), int(runs["total"]),
                            int(extras.get("wides", 0)), int(extras.get("noballs", 0)),
                            int(extras.get("byes", 0)), int(extras.get("legbyes", 0)),
                            int("wides" not in extras and "noballs" not in extras),
                            len(valid_wickets), bowler_wickets,
                            ",".join(w["kind"] for w in wickets), int(bool(inning.get("super_over"))),
                        ))
                totals.append(innings_total)

            target_data = innings[1].get("target", {}) if len(innings) > 1 else {}
            target = target_data.get("runs")
            reason = exclusion(info, innings, totals[0] if totals else 0, target)
            if reason:
                exclusions[reason] += 1
            winner = info.get("outcome", {}).get("winner")
            event = info.get("event", {})
            con.execute(
                "INSERT INTO matches VALUES (" + ",".join("?" * 24) + ")",
                (match_id, date, int(date[:4]), event.get("stage"),
                 info["teams"][0], info["teams"][1],
                 canonical_team(info["teams"][0]), canonical_team(info["teams"][1]),
                 info.get("venue"), winner, canonical_team(winner),
                 info.get("toss", {}).get("winner"),
                 innings[1]["team"] if len(innings) > 1 else None,
                 canonical_team(innings[1]["team"]) if len(innings) > 1 else None,
                 int(winner == innings[1]["team"]) if winner and len(innings) > 1 else None,
                 target, target_data.get("overs"),
                 totals[0] if totals else None, totals[1] if len(totals) > 1 else None,
                 len(innings), len(delivery_rows), info.get("outcome", {}).get("method"),
                 int(reason is None), reason),
            )
            con.executemany(
                "INSERT INTO deliveries VALUES (" + ",".join("?" * 23) + ")",
                delivery_rows,
            )
            match_count += 1
            delivery_count += len(delivery_rows)
        con.commit()
        manifest = json.loads((ROOT / "data_manifest.json").read_text())
        assert match_count == manifest["matches"], (match_count, manifest["matches"])
        assert delivery_count == manifest["deliveries"], (delivery_count, manifest["deliveries"])
        assert con.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0] == delivery_count
        assert con.execute("SELECT COUNT(*) FROM matches WHERE eligible_chase=1").fetchone()[0] > 1100
    except BaseException:
        con.close()
        temporary.unlink(missing_ok=True)
        raise
    con.close()
    temporary.replace(path)
    return {"matches": match_count, "deliveries": delivery_count,
            "eligible_chases": match_count - sum(exclusions.values()),
            "excluded": dict(exclusions)}


if __name__ == "__main__":
    print(json.dumps(build_database(), indent=2))
