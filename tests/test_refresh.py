"""End-to-end test of refresh.build over two seasons, using temp folders (no Yahoo, no real data)."""
import json
import tempfile
import unittest
from pathlib import Path

import refresh
from tests.test_keeper import CONFIG


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def site_data(site):
    text = (site / "data.js").read_text()
    return json.loads(text[text.index("=") + 1:].rstrip().rstrip(";"))


class Build(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data, self.site = Path(self.tmp.name) / "data", Path(self.tmp.name) / "docs"
        d = self.data / "2026"
        write(d / "season.json", {"season": 2026, "league_key": "461.l.1", "is_finished": True, "roster_week": 17})
        write(d / "teams.json", {"461.l.1.t.1": {"name": "Gibbs Owner", "manager": "A"},
                                 "461.l.1.t.2": {"name": "Trevor", "manager": "T"}})
        write(d / "draft.json", [{"player_key": "461.p.1", "team_key": "461.l.1.t.1", "cost": 65},
                                 {"player_key": "461.p.2", "team_key": "461.l.1.t.2", "cost": 5}])
        write(d / "transactions.json", [])
        write(d / "rosters.json", {"461.l.1.t.1": ["461.p.1"], "461.l.1.t.2": ["461.p.2"]})
        write(d / "players.json", {"461.p.1": {"player_key": "461.p.1", "name": "Jahmyr Gibbs",
                                               "position": "RB", "nfl_team": "DET"}})

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, season):
        refresh.build(season, CONFIG, data=self.data, site=self.site)
        return site_data(self.site)

    def test_first_season(self):
        out = self.build(2026)
        gibbs = next(p for p in out["players"] if p["player_key"] == "461.p.1")
        self.assertEqual((gibbs["name"], gibbs["keeper_cost"]), ("Jahmyr Gibbs", 75))
        self.assertEqual(out["keeper_season"], 2027)
        self.assertTrue((self.data / "2026" / "keepers.json").exists())

    def test_declarations_budget_and_overrides(self):
        write(self.data / "keeper_declarations.json", {"2027": {"461.l.1.t.1": ["461.p.1"]}})
        write(self.data / "keeper_overrides.json", {"_comment": "ignored", "461.p.2": {"keeper_cost": 12, "note": "ruling"}})
        out = self.build(2026)
        self.assertEqual(out["declarations"]["461.l.1.t.1"]["remaining_budget"], 125)
        watson = next(p for p in out["players"] if p["player_key"] == "461.p.2")
        self.assertEqual(watson["keeper_cost"], 12)
        self.assertEqual(watson["override"]["note"], "ruling")

    def test_keeper_carries_into_next_season_with_new_yahoo_keys(self):
        write(self.data / "keeper_declarations.json", {"2027": {"461.l.1.t.1": ["461.p.1"]}})
        self.build(2026)
        # 2027: Yahoo issues new league/player/team keys; Gibbs is still on team 1.
        d = self.data / "2027"
        write(d / "season.json", {"season": 2027, "league_key": "470.l.9", "is_finished": True, "roster_week": 17})
        write(d / "teams.json", {"470.l.9.t.1": {"name": "Gibbs Owner", "manager": "A"}})
        write(d / "draft.json", [{"player_key": "470.p.1", "team_key": "470.l.9.t.1", "cost": 75}])
        write(d / "transactions.json", [])
        write(d / "rosters.json", {"470.l.9.t.1": ["470.p.1"]})
        write(d / "players.json", {})
        out = self.build(2027)
        gibbs = out["players"][0]
        self.assertEqual((gibbs["years_kept"], gibbs["keeper_cost"], gibbs["price_source"]), (1, 90, "keeper"))
        self.assertEqual([h["event"] for h in gibbs["history"]], ["drafted", "kept"])


if __name__ == "__main__":
    unittest.main()
