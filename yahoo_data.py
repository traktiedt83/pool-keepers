"""Turn raw Yahoo Fantasy API JSON into the normalized season data keeper.py expects.

Pure parsing, no network. Yahoo's JSON nests irregularly, so this leans on the same
find_dicts / merged helpers export_league.py uses.
"""
from export_league import find_dicts, merged


def player_info(player):
    """A Yahoo "player" value ([info_parts, extra, ...]) -> {player_key, name, position, nfl_team}."""
    info = merged(player[0] if player and isinstance(player[0], list) else player)
    return {
        "player_key": info.get("player_key"),
        "name": (info.get("name") or {}).get("full") or info.get("player_key"),
        "position": info.get("display_position", ""),
        "nfl_team": (info.get("editorial_team_abbr") or "").upper(),
    }


def parse_teams(teams_resp):
    """league/{key}/teams -> {team_key: {"name", "manager"}}"""
    teams = {}
    for t in find_dicts(teams_resp, "team"):
        info = merged(t["team"][0] if isinstance(t["team"][0], list) else t["team"])
        managers = list(find_dicts(info.get("managers", []), "nickname"))
        teams[info["team_key"]] = {"name": info.get("name", info["team_key"]),
                                   "manager": managers[0]["nickname"] if managers else ""}
    return teams


def parse_draft(draft_resp):
    """league/{key}/draftresults -> [{"player_key", "team_key", "cost"}]"""
    return [{"player_key": d["player_key"], "team_key": d["team_key"], "cost": int(d.get("cost") or 0)}
            for d in find_dicts(draft_resp, "pick") if d.get("player_key")]


def parse_transactions(pages):
    """Transaction pages -> (moves, players). One move per player per completed transaction."""
    moves, players = [], {}
    for t in find_dicts(pages, "transaction"):
        parts = t["transaction"]
        if not isinstance(parts, list) or not parts:
            continue
        meta = parts[0]
        if meta.get("status", "successful") != "successful":
            continue
        bid = meta.get("faab_bid")
        block = parts[1].get("players", {}) if len(parts) > 1 and isinstance(parts[1], dict) else {}
        for p in find_dicts(block, "player"):
            info = player_info(p["player"])
            players[info["player_key"]] = info
            extra = merged(p["player"][1:])
            data = extra.get("transaction_data", {})
            data = merged(data) if isinstance(data, list) else data
            kind = data.get("type")
            if kind not in ("add", "drop", "trade"):
                continue
            moves.append({
                "timestamp": int(meta["timestamp"]),
                "type": kind,
                "player_key": info["player_key"],
                "from_team": data.get("source_team_key"),
                "to_team": data.get("destination_team_key"),
                "faab_bid": int(bid) if kind == "add" and bid not in (None, "") else None,
            })
    return moves, players


def parse_roster(roster_resp):
    """team/{team_key}/roster -> [player info dicts]"""
    return [player_info(p["player"]) for p in find_dicts(roster_resp, "player")]


# ---------------------------------------------------------------- keys across seasons

def game_id(key):
    """'461.l.123456' or '461.p.30123' -> '461' (Yahoo's id for one NFL season)."""
    return str(key).split(".", 1)[0]


def rekey_players(mapping, new_game_id):
    """Player keys change every season ('461.p.30123' -> '470.p.30123'); move a dict onto new keys."""
    return {f"{new_game_id}.p.{pk.split('.p.', 1)[1]}" if ".p." in pk else pk: v
            for pk, v in mapping.items()}
