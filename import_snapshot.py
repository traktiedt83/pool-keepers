#!/usr/bin/env python3
"""Build data/<season>/ from hand-transcribed Yahoo pages, as a placeholder until the Yahoo
Fantasy API is available. Rosters are rebuilt by replaying every move since the draft.

Usage:
    python import_snapshot.py data/2026/snapshot     # then: python refresh.py --offline

The snapshot folder holds draft.json and tx*.json (one per saved Transactions page, newest page
first: tx1 = newest). The real Yahoo refresh overwrites everything this writes.

Every move is checked while replaying (a drop or trade must involve a player who is on that team
at that moment, an add must be a free player), so transcription mistakes fail loudly.
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NOTE = ("Built by hand from Yahoo draft and transaction pages saved {as_of}, while we wait for "
        "Yahoo to approve live data. Tell the commish if anything looks off.")


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def team_key(name):
    return "snap.t." + slug(name)


def player_key(name, pos):
    return "snap.p." + slug(f"{name} {pos}")


def timestamp(day, clock):
    when = datetime.strptime(f"{day} {clock.replace('.', '').upper()}", "%Y-%m-%d %I:%M %p")
    return int(when.replace(tzinfo=timezone.utc).timestamp())


def load_transactions(folder):
    """All transactions, oldest first (files are newest-first, as are rows within a file)."""
    files = sorted(folder.glob("tx*.json"), key=lambda p: int(p.stem[2:]))
    out = []
    for path in reversed(files):
        txns = json.loads(path.read_text())["transactions"]
        out += [dict(t, source=f"{path.stem} #{t['seq']}") for t in sorted(txns, key=lambda t: -t["seq"])]
    return out


def build(folder, season, as_of):
    draft_doc = json.loads((folder / "draft.json").read_text())
    teams, players, rosters, draft = {}, {}, {}, []

    def remember(name, pos, nfl):
        pk = player_key(name, pos)
        players[pk] = {"player_key": pk, "name": name, "position": pos, "nfl_team": nfl}
        return pk

    for t in draft_doc["teams"]:
        tk = team_key(t["team"])
        teams[tk] = {"name": t["team"], "manager": ""}
        rosters[tk] = []
        for p in t["picks"]:
            pk = remember(p["player"], p["pos"], p["nfl"])
            draft.append({"player_key": pk, "team_key": tk, "cost": p["cost"]})
            rosters[tk].append(pk)

    owner = {pk: tk for tk, pks in rosters.items() for pk in pks}
    moves, errors, last_ts = [], [], 0
    for txn in load_transactions(folder):
        ts = max(timestamp(txn["date"], txn["time"]), last_ts)  # keep page order for equal minutes
        last_ts = ts
        for m in txn["moves"]:
            pk = remember(m["player"], m["pos"], m["nfl"])
            src = m.get("from_team") and team_key(m["from_team"])
            dst = m.get("to_team") and team_key(m["to_team"])
            for k in (src, dst):
                if k and k not in teams:
                    errors.append(f"{txn['source']}: unknown team {k}")
            where = f"{txn['source']} ({txn['date']} {txn['time']}) {m['type']} {m['player']}"
            if m["type"] == "add":
                if pk in owner:
                    errors.append(f"{where}: already on {teams[owner[pk]]['name']}")
                owner[pk] = dst
            elif m["type"] == "drop":
                if owner.get(pk) != src:
                    errors.append(f"{where}: not on {m['from_team']} (on {owner.get(pk)})")
                owner.pop(pk, None)
            elif m["type"] == "trade":
                if owner.get(pk) != src:
                    errors.append(f"{where}: not on {m['from_team']} (on {owner.get(pk)})")
                owner[pk] = dst
            else:
                errors.append(f"{where}: unknown move type")
            moves.append({"timestamp": ts, "type": m["type"], "player_key": pk, "from_team": src,
                          "to_team": dst, "faab_bid": m.get("faab_bid") if m["type"] == "add" else None})

    rosters = {tk: sorted(pk for pk, owner_tk in owner.items() if owner_tk == tk) for tk in teams}
    info = {"season": season, "league_key": "snapshot", "is_finished": False, "roster_week": None,
            "snapshot": {"as_of": as_of, "note": NOTE.format(as_of=as_of)}}
    return info, teams, draft, moves, rosters, players, errors


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    folder = Path(sys.argv[1]).resolve()
    season = int(folder.parent.name)
    info, teams, draft, moves, rosters, players, errors = build(folder, season, "Oct 21, 2026")
    if errors:
        print("Replay found problems; nothing written:")
        for e in errors:
            print("  ! " + e)
        sys.exit(1)
    out = folder.parent
    for name, data in (("season", info), ("teams", teams), ("draft", draft), ("transactions", moves),
                       ("rosters", rosters), ("players", players)):
        (out / f"{name}.json").write_text(json.dumps(data, indent=1))
    sizes = ", ".join(f"{teams[tk]['name']} {len(pks)}" for tk, pks in rosters.items())
    print(f"Wrote {out}: {len(draft)} draft picks, {len(moves)} moves.\nRoster sizes: {sizes}")


if __name__ == "__main__":
    main()
