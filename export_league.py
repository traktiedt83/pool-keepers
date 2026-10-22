#!/usr/bin/env python3
"""Export the full history of one Yahoo Fantasy Football league.

Usage:
    python export_league.py find                       # list matching leagues, download nothing
    python export_league.py export --league-key KEY    # download KEY and every earlier season

Credentials come from .env (YAHOO_CLIENT_ID / YAHOO_CLIENT_SECRET) and are never printed.
OAuth tokens are cached in oauth2.json (gitignored).
"""
import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

from dotenv import dotenv_values
from yahoo_oauth import OAuth2

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RAW = DATA / "raw"
TOKEN_FILE = ROOT / "oauth2.json"
LEAGUE_NAME = "I was in the pool"
REDIRECT_URI = "https://localhost:8888"
API = "https://fantasysports.yahooapis.com/fantasy/v2/"

# yahoo_oauth logs token details at DEBUG/INFO; keep it quiet so nothing sensitive is printed.
# It also swaps in a DEBUG-level logger class globally, so disable DEBUG/INFO for every logger.
logging.setLoggerClass(logging.Logger)
logging.disable(logging.INFO)


# ---------------------------------------------------------------- auth / HTTP

def get_oauth():
    env = dotenv_values(ROOT / ".env")
    key, secret = env.get("YAHOO_CLIENT_ID"), env.get("YAHOO_CLIENT_SECRET")
    if not key or not secret:
        sys.exit("Missing YAHOO_CLIENT_ID or YAHOO_CLIENT_SECRET in .env")
    if not TOKEN_FILE.exists():
        TOKEN_FILE.write_text(json.dumps({"consumer_key": key, "consumer_secret": secret}))
        os.chmod(TOKEN_FILE, 0o600)
        print(
            "\nOne-time Yahoo login:\n"
            "  1. A browser window will open to Yahoo. Sign in and click 'Agree'.\n"
            f"  2. Yahoo then redirects to {REDIRECT_URI}/?code=... and the page will NOT load. That's expected.\n"
            "  3. Copy the value after 'code=' from the address bar (stop before any '&').\n"
            "  4. Paste it below at the 'Enter verifier' prompt and press Return.\n"
        )
    oauth = OAuth2(None, None, from_file=str(TOKEN_FILE), callback_uri=REDIRECT_URI)
    os.chmod(TOKEN_FILE, 0o600)
    return oauth


class Yahoo:
    def __init__(self):
        self.oauth = get_oauth()
        self.calls = 0

    def get(self, path, retries=5):
        if not self.oauth.token_is_valid():
            self.oauth.refresh_access_token()
        url = API + path
        for attempt in range(retries):
            resp = self.oauth.session.get(url, params={"format": "json"})
            self.calls += 1
            if resp.status_code == 200:
                time.sleep(0.3)  # be polite; Yahoo throttles bursts
                return resp.json()
            if resp.status_code == 401:
                self.oauth.refresh_access_token()
            elif resp.status_code in (429, 500, 502, 503, 999):
                wait = 5 * (attempt + 1)
                print(f"    Yahoo returned {resp.status_code}; retrying in {wait}s")
                time.sleep(wait)
            else:
                raise RuntimeError(f"GET {path} -> HTTP {resp.status_code}: {resp.text[:300]}")
        raise RuntimeError(f"GET {path} failed after {retries} attempts")


# ---------------------------------------------------------------- JSON helpers

def find_dicts(obj, required_key):
    """Yield every dict anywhere in obj that has required_key (Yahoo's JSON nesting is irregular)."""
    if isinstance(obj, dict):
        if required_key in obj:
            yield obj
        for v in obj.values():
            yield from find_dicts(v, required_key)
    elif isinstance(obj, list):
        for v in obj:
            yield from find_dicts(v, required_key)


def merged(parts):
    """Yahoo often splits one object into a list of single-key dicts; merge them."""
    out = {}
    for p in parts:
        if isinstance(p, dict):
            out.update(p)
    return out


def league_meta(data):
    """Return the league metadata dict from a league/{key}/... response."""
    league = data["fantasy_content"]["league"]
    return league[0] if isinstance(league, list) else league


def renew_to_key(renew):
    """'390_123456' -> '390.l.123456'"""
    if not renew:
        return None
    game_id, league_id = str(renew).split("_", 1)
    return f"{game_id}.l.{league_id}"


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1))


# ---------------------------------------------------------------- find

def cmd_find(yahoo):
    print("Listing your Yahoo NFL leagues...")
    data = yahoo.get("users;use_login=1/games;game_codes=nfl/leagues")
    leagues = list(find_dicts(data, "league_key"))
    target = LEAGUE_NAME.strip().lower()
    matches = [l for l in leagues if l.get("name", "").strip().lower() == target]

    print(f"\nFound {len(leagues)} NFL league-seasons in your account.")
    if not matches:
        print(f'\nNo league named exactly "{LEAGUE_NAME}". Leagues found:')
        for l in sorted(leagues, key=lambda l: l.get("season", "")):
            print(f"  {l.get('season')}  {l.get('name')!r:40}  {l['league_key']}")
        return
    print(f'\nLeagues named "{LEAGUE_NAME}":')
    for l in sorted(matches, key=lambda l: l.get("season", ""), reverse=True):
        prev = renew_to_key(l.get("renew")) or "-"
        print(f"  season {l.get('season')}  key {l['league_key']}  teams {l.get('num_teams')}  "
              f"previous season key {prev}")
    print("\nNext step (after you confirm): python export_league.py export --league-key <most recent key>")


# ---------------------------------------------------------------- export

def fetch_transactions(yahoo, key):
    """Every transaction page for one league-season (Yahoo returns 25 at a time)."""
    pages, start_at = [], 0
    while True:
        page = yahoo.get(f"league/{key}/transactions;start={start_at};count=25")
        n = len(list(find_dicts(page, "transaction_key")))
        pages.append(page)
        if n < 25:
            return pages
        start_at += 25


def export_season(yahoo, key):
    meta_resp = yahoo.get(f"league/{key}/settings")
    meta = league_meta(meta_resp)
    season = str(meta["season"])
    out = RAW / season
    print(f"\n== {season}  {meta.get('name')!r}  ({key})")
    save(out / "settings.json", meta_resp)

    print("   teams & managers, standings")
    save(out / "teams.json", yahoo.get(f"league/{key}/teams"))
    save(out / "standings.json", yahoo.get(f"league/{key}/standings"))

    start, end = int(meta.get("start_week", 1)), int(meta.get("end_week", 17))
    current = int(meta.get("current_week", end))
    last_week = end if str(meta.get("is_finished")) == "1" else min(end, current)
    print(f"   scoreboards, weeks {start}-{last_week}")
    for week in range(start, last_week + 1):
        save(out / f"scoreboard_week_{week:02d}.json", yahoo.get(f"league/{key}/scoreboard;week={week}"))

    print("   draft results")
    draft = yahoo.get(f"league/{key}/draftresults")
    save(out / "draftresults.json", draft)
    player_keys = sorted({d["player_key"] for d in find_dicts(draft, "player_key") if d.get("player_key")})
    players = []
    for i in range(0, len(player_keys), 25):
        batch = ",".join(player_keys[i:i + 25])
        players.append(yahoo.get(f"league/{key}/players;player_keys={batch}"))
    save(out / "draft_players.json", players)

    print("   transactions")
    pages = fetch_transactions(yahoo, key)
    save(out / "transactions.json", pages)

    return {
        "season": season,
        "league_key": key,
        "name": meta.get("name"),
        "num_teams": meta.get("num_teams"),
        "is_finished": str(meta.get("is_finished")) == "1",
        "start_week": start,
        "end_week": end,
        "weeks_downloaded": last_week - start + 1,
        "draft_picks": len(list(find_dicts(draft, "pick"))),
        "transactions": sum(len(list(find_dicts(p, "transaction_key"))) for p in pages),
        "previous_league_key": renew_to_key(meta.get("renew")),
        "next_league_key": renew_to_key(meta.get("renewed")),
    }


def cmd_export(yahoo, start_key):
    seasons, key, seen = [], start_key, set()
    while key and key not in seen:
        seen.add(key)
        try:
            info = export_season(yahoo, key)
        except RuntimeError as e:
            print(f"   !! could not export {key}: {e}")
            seasons.append({"league_key": key, "error": str(e)})
            break
        seasons.append(info)
        key = info["previous_league_key"]

    if seasons and seasons[0].get("next_league_key"):
        print(f"\nNote: {start_key} has a newer season ({seasons[0]['next_league_key']}). "
              "Re-run export with that key to include it.")
    save(DATA / "seasons.json", sorted(seasons, key=lambda s: s.get("season", "")))
    print(f"\nDone. {len(seasons)} season(s), {yahoo.calls} API calls. Raw data in data/raw/<year>/")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("find")
    ex = sub.add_parser("export")
    ex.add_argument("--league-key", required=True, help="most recent season's league key, e.g. 461.l.123456")
    args = ap.parse_args()

    yahoo = Yahoo()
    if args.cmd == "find":
        cmd_find(yahoo)
    else:
        cmd_export(yahoo, args.league_key)


if __name__ == "__main__":
    main()
