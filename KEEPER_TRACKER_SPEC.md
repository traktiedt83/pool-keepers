# Keeper Tracker — Spec for "I Was In The Pool"

## Goal
Add a **Keepers** section to our league site that tracks, for every player on every roster, whether they're keeper-eligible next season, who holds the rights, and what they'd cost. Yahoo can't handle these rules, so we compute them ourselves from Yahoo's data.

Keep it simple. The commissioner should never have to do math by hand.

---

## League basics
- Yahoo league: "I Was In The Pool"
- Auction draft, **$200 budget** per team
- Keeper rules start with the **2027 draft** (based on 2026 rosters)

## Keeper rules (as discussed — values in config, not hard-coded)

1. **Keepers per team: up to 2** (`max_keepers: 2` in config). Keeping 0 or 1 is fine.
2. **Keeper cost = last season's price + keeper tax.** The tax grows the longer you keep a player (`keeper_tax_schedule: [10, 15]` in config):
   - **1st year kept:** +$10
   - **2nd year kept:** +$15 (on top of last year's keeper price)
   - Example: Gibbs drafted $65 → kept 2027 at **$75** → kept again 2028 at **$90**.
   - **Max 2 years kept** (`max_years_kept: 2`). After his 2nd keeper year, the player goes back into the draft pool — no one can keep him a 3rd year.
   - Budget: a team keeping Gibbs at $75 enters the draft with $200 − $75 = **$125**.
   - Two keepers: both costs come out. Gibbs ($75) + Watson ($15) → $200 − $90 = **$110** to spend.
3. **Keeper cost comes out of next year's draft budget.**
4. **Only the team rostering the player at season's end holds keeper rights.**
5. **Trades transfer keeper rights** — and the price travels with the player.
   - Example: Josh Jacobs drafted by Sato's Escorts for $14, traded to Brandon → Brandon can keep him at $14 + tax.
6. **Drafted players keep their original draft price forever**, even if dropped and picked up by someone else.
   - Example: De'Von Achane drafted for $44, dropped, picked up off waivers → whoever has him at season's end keeps him at $44 + tax, *not* $1.
7. **Undrafted players (waiver/free-agent pickups): keeper cost = what was spent to acquire him + the keeper tax.**
   - "What was spent" = the **FAAB waiver bid** from the Yahoo transaction (the `faab_bid` field on add transactions). The league uses a FAAB waiver budget, so this data exists.
   - **If he's claimed more than once in a season, use the highest bid anyone paid for him that season.** His price can go up during the year but never down. This stops a team from dropping a guy and re-claiming him (or having a buddy claim him) cheaply to lower his keeper price.
   - A free-agent add with no bid counts as `free_agent_base_price` (default $0 → keeper cost $10).
   - Example: Boston claimed for a $7 bid → keeper cost **$17**.
   - The waiver price travels with the player in a trade, just like a draft price.

### Rule decisions (all settled — keep values in config so they can change later)
- ~~`max_keepers`~~ — DECIDED: 2
- ~~`keeper_tax`~~ — DECIDED: $10
- ~~Waiver keepers~~ — DECIDED: waiver bid + tax
- ~~Multi-year keepers~~ — DECIDED: 1st year +$10, 2nd year +$15
- ~~3rd year~~ — DECIDED: max 2 years kept
- ~~Re-claimed waiver guys~~ — DECIDED: highest bid paid that season
- ~~FAAB~~ — CONFIRMED: league uses a waiver budget
- ~~Keeper declaration deadline~~ — DECIDED: **one week before the draft.** Config stores `draft_date`; the site computes `keeper_deadline = draft_date − 7 days` and shows a countdown. After the deadline, undeclared players go into the draft pool and each team's starting budget is locked. (2027 draft date TBD — likely late Aug / Labor Day weekend; NFL kickoff expected ~Sept 9, 2027.)
- **Edge case (use this default unless the commissioner overrides):** a player who isn't on any roster at season's end can't be kept by anyone. If he was drafted, his price resets — next year he's treated as a fresh draft/waiver player.

---

## Data — pull from Yahoo Fantasy API
Reuse the existing Yahoo auth from the league-history site if it's there. Otherwise set up a Yahoo Developer app (OAuth2) and use a Python library such as `yfpy` or `yahoo_fantasy_api`.

Needed endpoints/data:
- **Draft results** — player, team, auction price (`league/{league_key}/draftresults`)
- **Current rosters** for every team
- **Transactions** — adds, drops, trades (`league/{league_key}/transactions`)
- **Team names + manager names**

Cache everything to local JSON files (e.g. `data/2026/draft.json`, `rosters.json`, `transactions.json`) so the site works without hitting Yahoo every load.

### Manual override file
Add `data/keeper_overrides.json` so the commissioner can correct anything by hand (e.g. a disputed price, a ruling). Overrides always win over computed values and should be visibly marked on the site.

---

## Logic
For each player on each current roster:
1. Look up whether they were drafted this season.
   - **Drafted** → base price = draft price (no matter who drafted them).
   - **Not drafted** → base price = highest FAAB bid paid for him this season (or `free_agent_base_price` if never claimed with a bid).
2. If the player was kept last season, base price = last season's keeper price, and track **years kept** per player.
3. If years kept = `max_years_kept` (2), he is **not eligible** — show as "Back to draft pool."
4. Otherwise keeper cost = base price + `keeper_tax_schedule[years_kept]` (0 → $10, 1 → $15).
5. Rights holder = team rostering him right now (or at the final week once the season ends).
6. Store a short **history trail** per player: drafted by X for $Y → traded to Z (date) → dropped (date) → claimed by W for $B (date) → kept in 2027 at $C.
7. Show **years kept** and next year's projected cost on the Keeper Board, so managers see the price climbing.

Write this logic as a standalone module with **unit tests** using the real examples below.

### Test cases (from our 2026 draft)
| Player | Situation | Expected keeper cost (tax $10) |
|---|---|---|
| Jahmyr Gibbs | Drafted $65 | $75 |
| Christian Watson | Drafted $5 by Trevor | $15 |
| Josh Jacobs | Drafted $14, traded to Brandon | $24, rights = Brandon |
| De'Von Achane | Drafted $44, dropped, picked up by someone else | $54, rights = new team |
| Waiver pickup (e.g. Boston) | Claimed with a $7 FAAB bid | $17 |
| Free-agent add, no bid | Never drafted, $0 | $10 |
| Gibbs, 2nd year kept | Kept 2027 at $75 | 2028 cost $90 |
| Waiver guy traded | Claimed for $7, then traded | $17, rights = new team |
| Re-claimed waiver guy | Claimed $20, dropped, re-claimed by another team for $2 | $30 (highest bid), rights = 2nd team |
| Gibbs, 3rd year | Kept 2027 and 2028 | Not eligible — back to draft pool |
| Budget check | Team keeps Gibbs + Watson | $200 − $90 = $110 |
| Limit check | Team tries to keep 3 players | Rejected — max 2 |

---

## Site pages / features
1. **Keeper Board** — every team, every player, with keeper cost. Sortable. Highlight "steals" (big gap between keeper cost and current value/rank, if easy to pull).
2. **Team page** — each team's eligible keepers, plus a **"what if" calculator**: pick up to 2 keepers → shows remaining draft budget.
3. **Player lookup** — search a player, see price, rights holder, and history trail.
4. **Trade helper** — pick a player, see what his keeper cost would be for the receiving team (rights transfer with him). This is for the late-season "I'm out of the playoffs, I'm selling" trades.
5. **Rules page** — plain-English rules, auto-filled from config values.
6. **Keeper declarations (2027 offseason)** — a simple place to record each team's final keepers before the deadline, and a summary of each team's starting draft budget.

## Tech / hosting
- Fit this into the existing league-history site's stack if possible; otherwise a static site (plain HTML/JS or a light framework) built from the cached JSON.
- One command to refresh: `python refresh.py` (or similar) pulls Yahoo data, recomputes keepers, rebuilds the site.
- Host free (GitHub Pages, Netlify, or Vercel) so the whole league can see it on their phones.
- Mobile-first — most of the league will look at this from the group chat.
- Config in one file: `keeper_config.json`.

## Out of scope (for now)
- Logging in / letting managers edit anything themselves
- Pulling projections or rankings (nice-to-have later)
