#!/usr/bin/env python3
"""Keeper rules for "I Was In The Pool".

Pure logic: no Yahoo calls, no site code. Every rule value comes from keeper_config.json.

Inputs are normalized season data (the refresh step builds these from the raw Yahoo export):

    season = {
        "season": 2026,
        "draft": [{"player_key": "...", "team_key": "...", "cost": 65}, ...],
        "moves": [  # one entry per player per transaction, any order
            {"timestamp": 1760000000, "type": "add" | "drop" | "trade",
             "player_key": "...", "from_team": team_key or None, "to_team": team_key or None,
             "faab_bid": 7 or None},  # adds only; None = free-agent add with no bid
        ],
        "rosters": {team_key: [player_key, ...]},  # end-of-season (or current) rosters
    }

    prior_keepers = {player_key: {"cost": 75, "years_kept": 1, "team_key": ..., "history": [...]}}
        Players kept INTO this season. years_kept counts this season. Build it with carry_forward().
"""
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "keeper_config.json"
OVERRIDES_FILE = ROOT / "data" / "keeper_overrides.json"

REQUIRED_INT_KEYS = ("draft_budget", "max_keepers", "max_years_kept",
                     "free_agent_base_price", "keeper_deadline_days_before_draft")
OVERRIDABLE = ("team_key", "base_price", "years_kept", "eligible", "keeper_cost")


# ---------------------------------------------------------------- config / overrides

def load_config(path=CONFIG_FILE):
    config = json.loads(Path(path).read_text())
    validate_config(config)
    return config


def validate_config(config):
    for key in REQUIRED_INT_KEYS:
        if not isinstance(config.get(key), int) or config[key] < 0:
            raise ValueError(f"keeper_config: {key} must be a non-negative whole number")
    schedule = config.get("keeper_tax_schedule")
    if not isinstance(schedule, list) or not all(isinstance(t, int) and t >= 0 for t in schedule):
        raise ValueError("keeper_config: keeper_tax_schedule must be a list of non-negative whole numbers")
    if len(schedule) < config["max_years_kept"]:
        raise ValueError("keeper_config: keeper_tax_schedule needs one entry per allowed keeper year "
                         f"({config['max_years_kept']}), got {len(schedule)}")
    if config.get("draft_date") is not None:
        date.fromisoformat(config["draft_date"])  # raises on a bad date


def load_overrides(path=OVERRIDES_FILE):
    """{player_key: {field: value, "note": "..."}}; keys starting with '_' are comments."""
    path = Path(path)
    if not path.exists():
        return {}
    return {k: v for k, v in json.loads(path.read_text()).items() if not k.startswith("_")}


def keeper_deadline(config):
    """Keeper declaration deadline (a date), or None while the draft date is TBD."""
    if not config.get("draft_date"):
        return None
    return date.fromisoformat(config["draft_date"]) - timedelta(days=config["keeper_deadline_days_before_draft"])


# ---------------------------------------------------------------- core rules

def compute_keepers(season, config, prior_keepers=None):
    """Return {player_key: keeper record} for every rostered player.

    Players on no roster are left out: nobody holds their rights, and a drafted player's
    price resets (next season he is a fresh draft/waiver player).
    """
    prior_keepers = prior_keepers or {}
    drafted = {p["player_key"]: p for p in season.get("draft", [])}
    moves = defaultdict(list)
    for m in sorted(season.get("moves", []), key=lambda m: m["timestamp"]):
        moves[m["player_key"]].append(m)

    results = {}
    for team_key, player_keys in season["rosters"].items():
        for pk in player_keys:
            if pk in results:
                raise ValueError(f"{pk} is on two rosters ({results[pk]['team_key']} and {team_key})")
            results[pk] = player_record(pk, team_key, drafted.get(pk), moves[pk],
                                        prior_keepers.get(pk), config)
    return results


def player_record(player_key, team_key, draft_pick, moves, kept, config):
    base_price, price_source, years_kept = base_price_for(draft_pick, moves, kept, config)
    return {
        "player_key": player_key,
        "team_key": team_key,  # rights holder: whoever rosters him now / at season's end
        "base_price": base_price,
        "price_source": price_source,
        "years_kept": years_kept,
        **pricing(base_price, years_kept, config),
        "history": build_history(draft_pick, moves, kept),
        "override": None,
    }


def pricing(base_price, years_kept, config, eligible=None, keeper_cost=None):
    """Eligibility and cost fields. eligible / keeper_cost are only passed by overrides."""
    schedule, max_years = config["keeper_tax_schedule"], config["max_years_kept"]
    if eligible is None:
        eligible = years_kept < max_years
    tax = schedule[years_kept] if eligible and years_kept < len(schedule) else None
    if not eligible:
        keeper_cost = None
    elif keeper_cost is None:
        keeper_cost = base_price + (tax or 0)
    # What it would cost to keep him once more the year after (shows the price climbing).
    again = (keeper_cost + schedule[years_kept + 1]
             if eligible and years_kept + 1 < min(max_years, len(schedule)) else None)
    return {
        "eligible": eligible,
        "status": "eligible" if eligible else "back_to_pool",
        "keeper_tax": tax,
        "keeper_cost": keeper_cost,
        "cost_if_kept_again": again,
    }


def base_price_for(draft_pick, moves, kept, config):
    """(base_price, price_source, years_kept) for one player this season.

    Order of precedence: last season's keeper price, then draft price (forever, whoever
    drafted him), then the highest acquisition price anyone paid this season.
    """
    if kept:
        return kept["cost"], "keeper", kept["years_kept"]
    if draft_pick:
        return draft_pick["cost"], "draft", 0
    fa_base = config["free_agent_base_price"]
    prices = [(m["faab_bid"], "waiver") if m.get("faab_bid") is not None else (fa_base, "free_agent")
              for m in moves if m["type"] == "add"]
    if not prices:
        return fa_base, "no_record", 0  # rostered but no draft or add found; worth a commissioner look
    price, source = max(prices, key=lambda p: p[0])
    return price, source, 0


def build_history(draft_pick, moves, kept):
    trail = list(kept.get("history", [])) if kept else []
    if draft_pick and not kept:
        trail.append({"event": "drafted", "team_key": draft_pick["team_key"], "price": draft_pick["cost"]})
    for m in moves:
        entry = {"event": {"add": "claimed", "drop": "dropped", "trade": "traded"}[m["type"]],
                 "date": datetime.fromtimestamp(m["timestamp"], timezone.utc).date().isoformat()}
        if m["type"] == "add":
            entry.update(team_key=m["to_team"], price=m.get("faab_bid"))
        elif m["type"] == "drop":
            entry.update(team_key=m["from_team"])
        else:
            entry.update(from_team=m["from_team"], team_key=m["to_team"])
        trail.append(entry)
    return trail


# ---------------------------------------------------------------- declarations / budget

def validate_keepers(team_key, player_keys, results, config):
    """Check one team's keeper picks. Returns {ok, errors, total_cost, remaining_budget}."""
    errors, total = [], 0
    if len(set(player_keys)) != len(player_keys):
        errors.append("The same player is listed twice.")
    if len(player_keys) > config["max_keepers"]:
        errors.append(f"Too many keepers: {len(player_keys)} picked, max is {config['max_keepers']}.")
    for pk in dict.fromkeys(player_keys):
        r = results.get(pk)
        if r is None:
            errors.append(f"{pk} is not on any roster, so nobody can keep him.")
        elif r["team_key"] != team_key:
            errors.append(f"{pk}'s keeper rights belong to {r['team_key']}.")
        elif not r["eligible"]:
            errors.append(f"{pk} is not eligible (back to draft pool).")
        else:
            total += r["keeper_cost"]
    remaining = config["draft_budget"] - total
    if remaining < 0:
        errors.append(f"Keepers cost ${total}, more than the ${config['draft_budget']} budget.")
    return {"ok": not errors, "errors": errors, "total_cost": total, "remaining_budget": remaining}


def carry_forward(results, kept_player_keys, next_season):
    """Build next season's prior_keepers from this season's results and the declared keepers."""
    out = {}
    for pk in kept_player_keys:
        r = results[pk]
        if not r["eligible"]:
            raise ValueError(f"{pk} is not eligible to be kept")
        out[pk] = {
            "cost": r["keeper_cost"],
            "years_kept": r["years_kept"] + 1,
            "team_key": r["team_key"],
            "history": r["history"] + [{"event": "kept", "season": next_season,
                                        "team_key": r["team_key"], "price": r["keeper_cost"]}],
        }
    return out


# ---------------------------------------------------------------- overrides

def apply_overrides(results, overrides, config):
    """Commissioner overrides always win. Returns (new_results, unmatched_player_keys).

    Overridable fields: team_key, base_price, years_kept, eligible, keeper_cost. Cost fields not
    overridden are recomputed from the overridden inputs. Each overridden record gets
    record["override"] = {"note": ..., "original": {field: old value}} so the site can mark it.
    """
    out = {pk: dict(r) for pk, r in results.items()}
    unmatched = []
    for pk, ov in overrides.items():
        r = out.get(pk)
        if r is None:
            unmatched.append(pk)
            continue
        fields = [f for f in OVERRIDABLE if f in ov]
        r["override"] = {"note": ov.get("note", ""), "original": {f: r[f] for f in fields}}
        for f in ("team_key", "base_price", "years_kept"):
            if f in ov:
                r[f] = ov[f]
        r.update(pricing(r["base_price"], r["years_kept"], config,
                         eligible=ov.get("eligible"), keeper_cost=ov.get("keeper_cost")))
    return out, unmatched
