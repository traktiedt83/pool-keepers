"""Tests for yahoo_data.py against hand-built samples shaped like Yahoo's API JSON.

These samples follow Yahoo's documented shapes; the first real `python refresh.py` run is the
check that they match what our league actually returns.
"""
import unittest

import yahoo_data


def player(key, name, pos="RB", team="det", *extra):
    return {"player": [[{"player_key": key}, {"player_id": key.split(".")[-1]},
                        {"name": {"full": name}}, [], {"editorial_team_abbr": team},
                        {"display_position": pos}], *extra]}


def txn(key, ttype, timestamp, players, faab_bid=None, status="successful"):
    meta = {"transaction_key": key, "type": ttype, "status": status, "timestamp": str(timestamp)}
    if faab_bid is not None:
        meta["faab_bid"] = str(faab_bid)
    block = {str(i): p for i, p in enumerate(players)}
    block["count"] = len(players)
    return {"transaction": [meta, {"players": block}]}


def page(*txns):
    body = {str(i): t for i, t in enumerate(txns)}
    body["count"] = len(txns)
    return {"fantasy_content": {"league": [{"league_key": "461.l.1"}, {"transactions": body}]}}


class Parsing(unittest.TestCase):

    def test_teams(self):
        resp = {"fantasy_content": {"league": [{"league_key": "461.l.1"}, {"teams": {
            "0": {"team": [[{"team_key": "461.l.1.t.1"}, {"team_id": "1"}, {"name": "Sato's Escorts"}, [],
                            {"managers": [{"manager": {"manager_id": "1", "nickname": "Sato"}}]}]]},
            "count": 1}}]}}
        self.assertEqual(yahoo_data.parse_teams(resp),
                         {"461.l.1.t.1": {"name": "Sato's Escorts", "manager": "Sato"}})

    def test_draft(self):
        resp = {"fantasy_content": {"league": [{}, {"draft_results": {
            "0": {"draft_result": {"pick": 1, "round": 1, "team_key": "461.l.1.t.1",
                                   "player_key": "461.p.100", "cost": "65"}},
            "1": {"draft_result": {"pick": 2, "round": 1}},  # empty slot
            "count": 2}}]}}
        self.assertEqual(yahoo_data.parse_draft(resp),
                         [{"player_key": "461.p.100", "team_key": "461.l.1.t.1", "cost": 65}])

    def test_transactions(self):
        pages = [page(
            txn("t1", "add/drop", 1760000000, [
                player("461.p.200", "Boston", "WR", "sea",
                       {"transaction_data": [{"type": "add", "source_type": "waivers",
                                              "destination_type": "team",
                                              "destination_team_key": "461.l.1.t.2"}]}),
                player("461.p.201", "Cut Guy", "TE", "nyj",
                       {"transaction_data": {"type": "drop", "source_type": "team",
                                             "source_team_key": "461.l.1.t.2",
                                             "destination_type": "waivers"}}),
            ], faab_bid=7),
            txn("t2", "trade", 1760500000, [
                player("461.p.300", "Josh Jacobs", "RB", "gb",
                       {"transaction_data": [{"type": "trade", "source_team_key": "461.l.1.t.1",
                                              "destination_team_key": "461.l.1.t.3"}]}),
            ]),
            txn("t3", "add", 1760600000, [
                player("461.p.400", "Free Guy", "K", "kc",
                       {"transaction_data": [{"type": "add", "source_type": "freeagents",
                                              "destination_team_key": "461.l.1.t.4"}]}),
            ]),
            txn("t4", "trade", 1760700000, [
                player("461.p.500", "Vetoed", "QB", "buf",
                       {"transaction_data": [{"type": "trade", "source_team_key": "461.l.1.t.1",
                                              "destination_team_key": "461.l.1.t.3"}]}),
            ], status="vetoed"),
        )]
        moves, players = yahoo_data.parse_transactions(pages)
        self.assertEqual(moves, [
            {"timestamp": 1760000000, "type": "add", "player_key": "461.p.200",
             "from_team": None, "to_team": "461.l.1.t.2", "faab_bid": 7},
            {"timestamp": 1760000000, "type": "drop", "player_key": "461.p.201",
             "from_team": "461.l.1.t.2", "to_team": None, "faab_bid": None},
            {"timestamp": 1760500000, "type": "trade", "player_key": "461.p.300",
             "from_team": "461.l.1.t.1", "to_team": "461.l.1.t.3", "faab_bid": None},
            {"timestamp": 1760600000, "type": "add", "player_key": "461.p.400",
             "from_team": None, "to_team": "461.l.1.t.4", "faab_bid": None},
        ])
        self.assertEqual(players["461.p.300"],
                         {"player_key": "461.p.300", "name": "Josh Jacobs", "position": "RB", "nfl_team": "GB"})

    def test_roster(self):
        resp = {"fantasy_content": {"team": [[{"team_key": "461.l.1.t.1"}], {"roster": {"0": {"players": {
            "0": player("461.p.100", "Jahmyr Gibbs", "RB", "det", {"selected_position": [{"position": "RB"}]}),
            "count": 1}}}}]}}
        self.assertEqual(yahoo_data.parse_roster(resp),
                         [{"player_key": "461.p.100", "name": "Jahmyr Gibbs", "position": "RB", "nfl_team": "DET"}])

    def test_rekey_players_for_new_season(self):
        self.assertEqual(yahoo_data.rekey_players({"461.p.100": 1}, "470"), {"470.p.100": 1})
        self.assertEqual(yahoo_data.game_id("461.l.1"), "461")


if __name__ == "__main__":
    unittest.main()
