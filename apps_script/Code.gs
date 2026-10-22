/**
 * Keeper declarations for "I Was In The Pool", stored in a Google Sheet.
 *
 * Paste this into Extensions → Apps Script of a new Google Sheet, run setup() once, then
 * Deploy → New deployment → Web app (Execute as: Me, Who has access: Anyone).
 * The site reads declarations with GET and declares / undeclares with POST.
 *
 * Tabs it creates:
 *   Declarations  one row per team: what the site shows on the Declared tab
 *   PINs          one PIN per team; text each manager theirs. Never commit these anywhere.
 *
 * Every write is checked against the live site data (docs/data.js): the team's PIN, the keeper
 * deadline, max keepers, and that each player is on that team and eligible. Costs come from the
 * site data, not from the request.
 */

const SITE_DATA_URL = "https://traktiedt83.github.io/pool-keepers/data.js";
const DECL_SHEET = "Declarations";
const PIN_SHEET = "PINs";
const DECL_HEADER = ["team_key", "team_name", "players_json", "player_names", "total_cost",
                     "remaining_budget", "declared_at"];
const MAX_PIN_TRIES = 5;          // wrong PINs allowed per team ...
const PIN_LOCK_SECONDS = 600;     // ... before that team is locked for 10 minutes

// ---------------------------------------------------------------- web app

function doGet() {
  return json_({ ok: true, declarations: listDeclarations_() });
}

function doPost(e) {
  let req;
  try {
    req = JSON.parse(e.postData.contents);
  } catch (err) {
    return json_({ ok: false, error: "Bad request." });
  }
  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    const site = siteData_();
    const team = String(req.team || "");
    const teamName = (site.teams[team] || {}).name;
    if (!teamName) return json_({ ok: false, error: "Unknown team." });
    const pinCheck = checkPin_(team, teamName, String(req.pin || ""));
    if (pinCheck) return json_(pinCheck);
    if (deadlinePassed_(site)) return json_({ ok: false, error: "The keeper deadline has passed." });
    if (req.action === "declare") return json_(declare_(site, team, teamName, req.players || []));
    if (req.action === "undeclare") return json_(undeclare_(team, teamName));
    return json_({ ok: false, error: "Unknown action." });
  } finally {
    lock.releaseLock();
  }
}

// ---------------------------------------------------------------- actions

function declare_(site, team, teamName, playerKeys) {
  const cfg = site.config;
  const keys = playerKeys.map(String);
  if (!keys.length) return { ok: false, error: "Pick at least one keeper, or use Undeclare." };
  if (new Set(keys).size !== keys.length) return { ok: false, error: "The same player is listed twice." };
  if (keys.length > cfg.max_keepers) return { ok: false, error: "You can keep at most " + cfg.max_keepers + "." };
  const byKey = {};
  site.players.forEach(function (p) { byKey[p.player_key] = p; });
  const picked = [];
  for (const k of keys) {
    const p = byKey[k];
    if (!p || p.team_key !== team) return { ok: false, error: "A picked player isn't on " + teamName + "." };
    if (!p.eligible) return { ok: false, error: p.name + " can't be kept (back to the draft pool)." };
    picked.push(p);
  }
  const total = picked.reduce(function (s, p) { return s + p.keeper_cost; }, 0);
  const remaining = cfg.draft_budget - total;
  if (remaining < 0) return { ok: false, error: "Those keepers cost more than the draft budget." };

  const row = [team, teamName,
    JSON.stringify(picked.map(function (p) {
      return { key: p.player_key, name: p.name, pos: p.position, cost: p.keeper_cost };
    })),
    picked.map(function (p) { return p.name + " ($" + p.keeper_cost + ")"; }).join(" + "),
    total, remaining, new Date().toISOString()];
  const sheet = declSheet_();
  const at = findTeamRow_(sheet, team, teamName);
  if (at) sheet.getRange(at, 1, 1, row.length).setValues([row]);
  else sheet.appendRow(row);
  return { ok: true, declarations: listDeclarations_() };
}

function undeclare_(team, teamName) {
  const sheet = declSheet_();
  const at = findTeamRow_(sheet, team, teamName);
  if (at) sheet.deleteRow(at);
  return { ok: true, declarations: listDeclarations_() };
}

function listDeclarations_() {
  const rows = declSheet_().getDataRange().getValues().slice(1);
  const out = {};
  rows.forEach(function (r) {
    if (!r[0]) return;
    let players = [];
    try { players = JSON.parse(r[2]); } catch (err) { /* hand-edited cell; show the row without players */ }
    out[r[0]] = { team_name: r[1], players: players, total_cost: Number(r[4]),
                  remaining_budget: Number(r[5]), declared_at: String(r[6]) };
  });
  return out;
}

// ---------------------------------------------------------------- PINs

/** Returns an error response, or null when the PIN is right. Locks a team after repeated misses. */
function checkPin_(team, teamName, pin) {
  const cache = CacheService.getScriptCache();
  const triesKey = "tries:" + team;
  const tries = Number(cache.get(triesKey) || 0);
  if (tries >= MAX_PIN_TRIES) {
    return { ok: false, code: "locked", error: "Too many wrong PINs. Try again in 10 minutes." };
  }
  const rows = pinSheet_().getDataRange().getValues().slice(1);
  const match = rows.find(function (r) { return r[0] === team; }) ||
                rows.find(function (r) { return r[1] === teamName; });
  if (match && String(match[2]).trim() !== "" && String(match[2]).trim() === pin.trim()) {
    cache.remove(triesKey);
    return null;
  }
  cache.put(triesKey, String(tries + 1), PIN_LOCK_SECONDS);
  return { ok: false, code: "pin", error: "Wrong PIN for " + teamName + "." };
}

// ---------------------------------------------------------------- setup (run once from the editor)

/** Creates both tabs and gives every team a random 4-digit PIN (existing PINs are kept). */
function setup() {
  declSheet_();
  const sheet = pinSheet_();
  const site = siteData_();
  const rows = sheet.getDataRange().getValues().slice(1);
  Object.keys(site.teams).forEach(function (key) {
    const name = site.teams[key].name;
    const at = rows.findIndex(function (r) { return r[0] === key || r[1] === name; });
    if (at === -1) {
      sheet.appendRow([key, name, randomPin_()]);
    } else if (String(rows[at][2]).trim() === "") {
      sheet.getRange(at + 2, 3).setValue(randomPin_());
    }
  });
  sheet.getRange("C:C").setNumberFormat("@");  // keep leading zeros
  SpreadsheetApp.getActive().toast("Set up " + Object.keys(site.teams).length + " teams. PINs are on the PINs tab.");
}

function onOpen() {
  SpreadsheetApp.getUi().createMenu("Keepers").addItem("Set up / fill missing PINs", "setup").addToUi();
}

// ---------------------------------------------------------------- helpers

function siteData_() {
  const text = UrlFetchApp.fetch(SITE_DATA_URL + "?t=" + Date.now()).getContentText();
  return JSON.parse(text.slice(text.indexOf("=") + 1).trim().replace(/;\s*$/, ""));
}

function deadlinePassed_(site) {
  if (!site.keeper_deadline) return false;
  const tz = Session.getScriptTimeZone();
  return Utilities.formatDate(new Date(), tz, "yyyy-MM-dd") > site.keeper_deadline;
}

/** Row number (1-based) for a team, matched by key, then by name (keys change when live Yahoo data arrives). */
function findTeamRow_(sheet, team, teamName) {
  const rows = sheet.getDataRange().getValues();
  for (let i = 1; i < rows.length; i++) if (rows[i][0] === team) return i + 1;
  for (let i = 1; i < rows.length; i++) if (rows[i][1] === teamName) return i + 1;
  return 0;
}

function declSheet_() {
  return sheet_(DECL_SHEET, DECL_HEADER);
}

function pinSheet_() {
  return sheet_(PIN_SHEET, ["team_key", "team_name", "pin"]);
}

function sheet_(name, header) {
  const ss = SpreadsheetApp.getActive();
  let sheet = ss.getSheetByName(name);
  if (!sheet) {
    sheet = ss.insertSheet(name);
    sheet.appendRow(header);
    sheet.setFrozenRows(1);
  }
  return sheet;
}

function randomPin_() {
  return String(Math.floor(Math.random() * 10000)).padStart(4, "0");
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
