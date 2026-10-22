#!/usr/bin/env python3
"""Pull this season from Yahoo, recompute keepers, rebuild the site.

Usage:
    python refresh.py                      # league key from keeper_config.json
    python refresh.py --league-key KEY     # this season's key, e.g. 461.l.123456
    python refresh.py --offline            # rebuild the site from cached data/<season>/ only

Writes:
    data/raw/<season>/          raw Yahoo responses
    data/<season>/              normalized draft, transactions, rosters, teams, players, keepers
    docs/data.js                everything the site shows (docs/ is what GitHub Pages serves)

Hand-edited inputs:
    keeper_config.json          rule values
    data/keeper_overrides.json  commissioner corrections: {player_key: {field: value, "note": "..."}}
    data/keeper_declarations.json  final keepers: {"2027": {team_key: [player_key, ...]}}
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import keeper
import yahoo_data

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SITE = ROOT / "docs"
DECLARATIONS_FILE = DATA / "keeper_declarations.json"


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1))


def load(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


# ---------------------------------------------------------------- fetch from Yahoo

def fetch_season(league_key):
    """Download one season and save raw + normalized copies. Returns the season year."""
    from export_league import Yahoo, fetch_transactions, league_meta  # needs yahoo_oauth + .env

    yahoo = Yahoo()
    settings = yahoo.get(f"league/{league_key}/settings")
    meta = league_meta(settings)
    season = int(meta["season"])
    finished = str(meta.get("is_finished")) == "1"
    week = int(meta.get("end_week", 17)) if finished else int(meta.get("current_week", 1))
    raw = DATA / "raw" / str(season)
    print(f"{season} {meta.get('name')!r} ({league_key}), rosters as of week {week}")

    print("  teams, draft results, transactions")
    teams_resp = yahoo.get(f"league/{league_key}/teams")
    draft_resp = yahoo.get(f"league/{league_key}/draftresults")
    txn_pages = fetch_transactions(yahoo, league_key)
    teams = yahoo_data.parse_teams(teams_resp)

    print(f"  rosters for {len(teams)} teams")
    roster_resps = {tk: yahoo.get(f"team/{tk}/roster;week={week}") for tk in teams}

    for name, resp in (("settings", settings), ("teams", teams_resp), ("draftresults", draft_resp),
                       ("transactions", txn_pages), ("rosters", roster_resps)):
        save(raw / f"{name}.json", resp)

    moves, players = yahoo_data.parse_transactions(txn_pages)
    rosters = {}
    for tk, resp in roster_resps.items():
        roster = yahoo_data.parse_roster(resp)
        rosters[tk] = [p["player_key"] for p in roster]
        players.update({p["player_key"]: p for p in roster})

    out = DATA / str(season)
    save(out / "season.json", {"season": season, "league_key": league_key, "is_finished": finished,
                               "roster_week": week})
    save(out / "teams.json", teams)
    save(out / "draft.json", yahoo_data.parse_draft(draft_resp))
    save(out / "transactions.json", moves)
    save(out / "rosters.json", rosters)
    save(out / "players.json", players)
    print(f"  {yahoo.calls} API calls")
    return season


# ---------------------------------------------------------------- compute + build

def latest_season():
    seasons = sorted(int(p.parent.name) for p in DATA.glob("*/season.json"))
    if not seasons:
        sys.exit("No cached season in data/. Run without --offline first.")
    return seasons[-1]


def load_season(data, season):
    d = data / str(season)
    return {"season": season, "draft": load(d / "draft.json", []),
            "moves": load(d / "transactions.json", []), "rosters": load(d / "rosters.json", {})}


def prior_keepers(data, season, declarations, info):
    """Players kept INTO this season, from last season's results + this season's declarations.

    Invalid declarations were already flagged when last season was built; they're skipped here.
    """
    last = load(data / str(season - 1) / "keepers.json")
    declared = declarations.get(str(season), {})
    if not last or not declared:
        return {}
    kept = [pk for tk, pks in declared.items() for pk in pks
            if pk in last and last[pk]["eligible"] and last[pk]["team_key"] == tk]
    return yahoo_data.rekey_players(keeper.carry_forward(last, kept, season),
                                    yahoo_data.game_id(info["league_key"]))


def build(season, config, data=DATA, site=SITE):
    info = load(data / str(season) / "season.json")
    declarations = load(data / "keeper_declarations.json", {})
    overrides = keeper.load_overrides(data / "keeper_overrides.json")

    results = keeper.compute_keepers(load_season(data, season), config,
                                     prior_keepers(data, season, declarations, info))
    results, unmatched = keeper.apply_overrides(results, overrides, config)
    save(data / str(season) / "keepers.json", results)

    warnings = [f"Override for {pk} matches no rostered player." for pk in unmatched]
    warnings += [f"{pk}: no draft or pickup found, priced as a free agent." for pk, r in results.items()
                 if r["price_source"] == "no_record" and not r["override"]]

    next_season = season + 1
    declared = declarations.get(str(next_season), {})
    decl = {tk: {"keepers": pks, **keeper.validate_keepers(tk, pks, results, config)}
            for tk, pks in declared.items()}
    warnings += [f"{tk} keeper declaration: {e}" for tk, d in decl.items() for e in d["errors"]]

    # Team names from every cached season, so history entries from past seasons still read well.
    teams = {}
    for path in sorted(data.glob("*/teams.json")):
        teams.update(load(path))
    players = load(data / str(season) / "players.json", {})

    deadline = keeper.keeper_deadline(config)
    site_data = {
        "generated_at": now_iso(),
        "season": season,
        "keeper_season": next_season,
        "roster_week": info.get("roster_week"),
        "season_finished": info.get("is_finished", False),
        # Set when data/<season>/ was built by hand (e.g. from saved Yahoo pages) instead of the API.
        "snapshot": info.get("snapshot"),
        "config": {k: config[k] for k in ("league_name", "draft_budget", "max_keepers", "keeper_tax_schedule",
                                          "max_years_kept", "free_agent_base_price", "draft_date",
                                          "keeper_deadline_days_before_draft")},
        # Google Apps Script web app holding managers' declarations (apps_script/Code.gs), or None.
        "declarations_api": config.get("declarations_api"),
        "keeper_deadline": deadline.isoformat() if deadline else None,
        "teams": teams,
        "players": [{**players.get(pk, {"name": pk, "position": "", "nfl_team": ""}), **r}
                    for pk, r in results.items()],
        "declarations": decl,
        "warnings": warnings,
    }
    # Leave data.js alone when nothing but the timestamp would change, so scheduled runs
    # only commit real changes. generated_at is "when the data last changed".
    out = site / "data.js"
    previous = read_site_data(out)
    if previous and {**previous, "generated_at": None} == {**site_data, "generated_at": None}:
        print(f"No changes; {out} left as is.")
    else:
        site.mkdir(parents=True, exist_ok=True)
        out.write_text("window.KEEPER_DATA = " + json.dumps(site_data, indent=1) + ";\n")
        print(f"Built {out}: {len(results)} rostered players, {len(teams)} teams.")
    for w in warnings:
        print(f"  ! {w}")


def read_site_data(path):
    if not path.exists():
        return None
    text = path.read_text()
    return json.loads(text[text.index("=") + 1:].rstrip().rstrip(";"))


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league-key", help="this season's Yahoo league key (default: keeper_config.json)")
    ap.add_argument("--offline", action="store_true", help="skip Yahoo; rebuild from cached data")
    args = ap.parse_args()

    config = keeper.load_config()
    if args.offline:
        season = latest_season()
    else:
        league_key = args.league_key or config.get("league_key")
        if not league_key:
            sys.exit("Set league_key in keeper_config.json (find it with: python export_league.py find)")
        season = fetch_season(league_key)
    build(season, config)


if __name__ == "__main__":
    main()
