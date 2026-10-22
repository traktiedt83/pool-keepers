"""Unit tests for keeper.py, built from the test cases in KEEPER_TRACKER_SPEC.md.

Run from the project root:  .venv/bin/python -m unittest -v
"""
import unittest
from datetime import date, datetime, timezone

import keeper

# Spec values, pinned here so tests don't break if the commissioner edits keeper_config.json.
CONFIG = {
    "league_name": "I Was In The Pool",
    "first_keeper_season": 2027,
    "draft_budget": 200,
    "max_keepers": 2,
    "keeper_tax_schedule": [10, 15],
    "max_years_kept": 2,
    "free_agent_base_price": 0,
    "draft_date": None,
    "keeper_deadline_days_before_draft": 7,
}


def ts(day):
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp())


def add(player, team, day, bid=None):
    return {"timestamp": ts(day), "type": "add", "player_key": player,
            "from_team": None, "to_team": team, "faab_bid": bid}


def drop(player, team, day):
    return {"timestamp": ts(day), "type": "drop", "player_key": player,
            "from_team": team, "to_team": None, "faab_bid": None}


def trade(player, from_team, to_team, day):
    return {"timestamp": ts(day), "type": "trade", "player_key": player,
            "from_team": from_team, "to_team": to_team, "faab_bid": None}


def season_2026():
    """2026 season covering every spec scenario."""
    return {
        "season": 2026,
        "draft": [
            {"player_key": "gibbs", "team_key": "gibbs_owner", "cost": 65},
            {"player_key": "watson", "team_key": "trevor", "cost": 5},
            {"player_key": "jacobs", "team_key": "sato", "cost": 14},
            {"player_key": "achane", "team_key": "achane_drafter", "cost": 44},
            {"player_key": "dropped_drafted", "team_key": "sato", "cost": 30},
        ],
        "moves": [
            trade("jacobs", "sato", "brandon", "2026-10-20"),
            drop("achane", "achane_drafter", "2026-10-01"),
            add("achane", "achane_pickup", "2026-10-02", bid=3),
            add("boston", "boston_owner", "2026-09-15", bid=7),
            add("fa_guy", "fa_owner", "2026-09-20"),
            add("waiver_traded", "claimer", "2026-09-10", bid=7),
            trade("waiver_traded", "claimer", "receiver", "2026-10-15"),
            # listed out of order on purpose: moves are sorted by time
            add("reclaimed", "second_team", "2026-10-05", bid=2),
            add("reclaimed", "first_team", "2026-09-01", bid=20),
            drop("reclaimed", "first_team", "2026-10-01"),
            drop("dropped_drafted", "sato", "2026-11-01"),
        ],
        "rosters": {
            "gibbs_owner": ["gibbs"],
            "trevor": ["watson"],
            "brandon": ["jacobs"],
            "achane_pickup": ["achane"],
            "boston_owner": ["boston"],
            "fa_owner": ["fa_guy"],
            "receiver": ["waiver_traded"],
            "second_team": ["reclaimed"],
        },
    }


class SpecTestCases(unittest.TestCase):
    """One test per row of the spec's test-case table."""

    def setUp(self):
        self.r = keeper.compute_keepers(season_2026(), CONFIG)

    def test_gibbs_drafted_65(self):
        self.assertEqual(self.r["gibbs"]["keeper_cost"], 75)

    def test_watson_drafted_5_by_trevor(self):
        self.assertEqual(self.r["watson"]["keeper_cost"], 15)
        self.assertEqual(self.r["watson"]["team_key"], "trevor")

    def test_jacobs_traded_price_and_rights_move(self):
        self.assertEqual(self.r["jacobs"]["keeper_cost"], 24)
        self.assertEqual(self.r["jacobs"]["team_key"], "brandon")

    def test_achane_dropped_keeps_draft_price(self):
        # Re-claimed for a $3 bid, but the $44 draft price sticks forever.
        self.assertEqual(self.r["achane"]["keeper_cost"], 54)
        self.assertEqual(self.r["achane"]["team_key"], "achane_pickup")
        self.assertEqual(self.r["achane"]["price_source"], "draft")

    def test_waiver_pickup_7_bid(self):
        self.assertEqual(self.r["boston"]["keeper_cost"], 17)
        self.assertEqual(self.r["boston"]["price_source"], "waiver")

    def test_free_agent_no_bid(self):
        self.assertEqual(self.r["fa_guy"]["keeper_cost"], 10)
        self.assertEqual(self.r["fa_guy"]["price_source"], "free_agent")

    def test_gibbs_second_year_kept(self):
        prior = keeper.carry_forward(self.r, ["gibbs"], 2027)
        self.assertEqual(prior["gibbs"]["cost"], 75)
        r2027 = keeper.compute_keepers(
            {"season": 2027, "draft": [], "moves": [], "rosters": {"gibbs_owner": ["gibbs"]}},
            CONFIG, prior)
        self.assertEqual(r2027["gibbs"]["years_kept"], 1)
        self.assertEqual(r2027["gibbs"]["keeper_cost"], 90)

    def test_waiver_guy_traded(self):
        self.assertEqual(self.r["waiver_traded"]["keeper_cost"], 17)
        self.assertEqual(self.r["waiver_traded"]["team_key"], "receiver")

    def test_reclaimed_waiver_guy_uses_highest_bid(self):
        self.assertEqual(self.r["reclaimed"]["keeper_cost"], 30)
        self.assertEqual(self.r["reclaimed"]["team_key"], "second_team")

    def test_gibbs_third_year_back_to_pool(self):
        empty = {"draft": [], "moves": [], "rosters": {"gibbs_owner": ["gibbs"]}}
        r2027 = keeper.compute_keepers({**empty, "season": 2027}, CONFIG,
                                       keeper.carry_forward(self.r, ["gibbs"], 2027))
        r2028 = keeper.compute_keepers({**empty, "season": 2028}, CONFIG,
                                       keeper.carry_forward(r2027, ["gibbs"], 2028))
        g = r2028["gibbs"]
        self.assertFalse(g["eligible"])
        self.assertEqual(g["status"], "back_to_pool")
        self.assertIsNone(g["keeper_cost"])
        with self.assertRaises(ValueError):
            keeper.carry_forward(r2028, ["gibbs"], 2029)

    def test_budget_gibbs_plus_watson(self):
        season = season_2026()
        season["rosters"] = {"t": ["gibbs", "watson"]}
        r = keeper.compute_keepers(season, CONFIG)
        check = keeper.validate_keepers("t", ["gibbs", "watson"], r, CONFIG)
        self.assertTrue(check["ok"], check["errors"])
        self.assertEqual(check["total_cost"], 90)
        self.assertEqual(check["remaining_budget"], 110)

    def test_limit_three_keepers_rejected(self):
        season = season_2026()
        season["rosters"] = {"t": ["gibbs", "watson", "boston"]}
        r = keeper.compute_keepers(season, CONFIG)
        check = keeper.validate_keepers("t", ["gibbs", "watson", "boston"], r, CONFIG)
        self.assertFalse(check["ok"])
        self.assertTrue(any("max is 2" in e for e in check["errors"]))


class OtherRules(unittest.TestCase):

    def setUp(self):
        self.r = keeper.compute_keepers(season_2026(), CONFIG)

    def test_single_keeper_budget(self):
        check = keeper.validate_keepers("gibbs_owner", ["gibbs"], self.r, CONFIG)
        self.assertEqual(check["remaining_budget"], 125)

    def test_zero_keepers_ok(self):
        check = keeper.validate_keepers("trevor", [], self.r, CONFIG)
        self.assertTrue(check["ok"])
        self.assertEqual(check["remaining_budget"], 200)

    def test_cannot_keep_another_teams_player(self):
        check = keeper.validate_keepers("sato", ["jacobs"], self.r, CONFIG)
        self.assertFalse(check["ok"])

    def test_unrostered_player_cannot_be_kept(self):
        self.assertNotIn("dropped_drafted", self.r)
        check = keeper.validate_keepers("sato", ["dropped_drafted"], self.r, CONFIG)
        self.assertFalse(check["ok"])

    def test_unrostered_drafted_player_price_resets_next_season(self):
        # Dropped at $30 draft price, unrostered at season's end; claimed next year for $4.
        r2027 = keeper.compute_keepers(
            {"season": 2027, "draft": [], "moves": [add("dropped_drafted", "x", "2027-09-20", bid=4)],
             "rosters": {"x": ["dropped_drafted"]}},
            CONFIG, keeper.carry_forward(self.r, [], 2027))
        self.assertEqual(r2027["dropped_drafted"]["keeper_cost"], 14)

    def test_cost_if_kept_again(self):
        self.assertEqual(self.r["gibbs"]["cost_if_kept_again"], 90)

    def test_no_record_falls_back_to_free_agent_price(self):
        season = season_2026()
        season["rosters"]["fa_owner"].append("mystery")
        r = keeper.compute_keepers(season, CONFIG)
        self.assertEqual(r["mystery"]["price_source"], "no_record")
        self.assertEqual(r["mystery"]["keeper_cost"], 10)

    def test_player_on_two_rosters_is_an_error(self):
        season = season_2026()
        season["rosters"]["trevor"].append("gibbs")
        with self.assertRaises(ValueError):
            keeper.compute_keepers(season, CONFIG)

    def test_history_trail(self):
        events = [(h["event"], h.get("team_key"), h.get("price")) for h in self.r["achane"]["history"]]
        self.assertEqual(events, [("drafted", "achane_drafter", 44),
                                  ("dropped", "achane_drafter", None),
                                  ("claimed", "achane_pickup", 3)])
        jacobs = self.r["jacobs"]["history"][-1]
        self.assertEqual((jacobs["event"], jacobs["from_team"], jacobs["team_key"], jacobs["date"]),
                         ("traded", "sato", "brandon", "2026-10-20"))

    def test_history_carries_across_seasons(self):
        r2027 = keeper.compute_keepers(
            {"season": 2027, "draft": [], "moves": [], "rosters": {"gibbs_owner": ["gibbs"]}},
            CONFIG, keeper.carry_forward(self.r, ["gibbs"], 2027))
        self.assertEqual([h["event"] for h in r2027["gibbs"]["history"]], ["drafted", "kept"])
        self.assertEqual(r2027["gibbs"]["history"][-1]["price"], 75)

    def test_tax_comes_from_config(self):
        cfg = {**CONFIG, "keeper_tax_schedule": [5, 8]}
        self.assertEqual(keeper.compute_keepers(season_2026(), cfg)["gibbs"]["keeper_cost"], 70)


class Overrides(unittest.TestCase):

    def setUp(self):
        self.r = keeper.compute_keepers(season_2026(), CONFIG)

    def test_cost_override_wins_and_is_marked(self):
        out, unmatched = keeper.apply_overrides(
            self.r, {"boston": {"keeper_cost": 12, "note": "disputed bid"}}, CONFIG)
        self.assertEqual(out["boston"]["keeper_cost"], 12)
        self.assertEqual(out["boston"]["override"], {"note": "disputed bid", "original": {"keeper_cost": 17}})
        self.assertEqual(unmatched, [])
        self.assertEqual(self.r["boston"]["keeper_cost"], 17)  # input untouched

    def test_base_price_override_recomputes_cost(self):
        out, _ = keeper.apply_overrides(self.r, {"boston": {"base_price": 3}}, CONFIG)
        self.assertEqual(out["boston"]["keeper_cost"], 13)
        self.assertEqual(out["boston"]["cost_if_kept_again"], 28)

    def test_ineligible_override(self):
        out, _ = keeper.apply_overrides(self.r, {"gibbs": {"eligible": False}}, CONFIG)
        self.assertEqual(out["gibbs"]["status"], "back_to_pool")
        self.assertIsNone(out["gibbs"]["keeper_cost"])

    def test_rights_override_used_by_validation(self):
        out, _ = keeper.apply_overrides(self.r, {"jacobs": {"team_key": "sato"}}, CONFIG)
        self.assertTrue(keeper.validate_keepers("sato", ["jacobs"], out, CONFIG)["ok"])

    def test_unknown_player_reported(self):
        _, unmatched = keeper.apply_overrides(self.r, {"nobody": {"keeper_cost": 1}}, CONFIG)
        self.assertEqual(unmatched, ["nobody"])


class Config(unittest.TestCase):

    def test_real_config_file_is_valid_and_matches_spec(self):
        cfg = keeper.load_config()
        for key in ("draft_budget", "max_keepers", "keeper_tax_schedule", "max_years_kept",
                    "free_agent_base_price", "keeper_deadline_days_before_draft"):
            self.assertEqual(cfg[key], CONFIG[key], key)

    def test_tax_schedule_must_cover_max_years(self):
        with self.assertRaises(ValueError):
            keeper.validate_config({**CONFIG, "max_years_kept": 3})

    def test_deadline_tbd(self):
        self.assertIsNone(keeper.keeper_deadline(CONFIG))

    def test_deadline_one_week_before_draft(self):
        cfg = {**CONFIG, "draft_date": "2027-09-04"}
        self.assertEqual(keeper.keeper_deadline(cfg), date(2027, 8, 28))


if __name__ == "__main__":
    unittest.main()
