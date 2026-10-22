// Keeper site. All numbers come from data.js, which refresh.py builds with keeper.py;
// this file only displays them (the what-if calculator just adds up computed costs).
(function () {
  "use strict";
  const D = window.KEEPER_DATA;
  const view = document.getElementById("view");
  if (!D) {
    // Shown until the first refresh writes data.js.
    document.getElementById("league-name").textContent = "I Was In The Pool Keepers";
    document.querySelector(".tabs").hidden = true;
    view.innerHTML = '<div class="card"><h2>Keeper costs coming soon</h2>' +
      "<p>Every player's keeper cost, who holds the rights, and each team's draft budget will show up here " +
      "once we're pulling data from Yahoo. Check back soon.</p></div>";
    return;
  }
  const C = D.config;
  const players = D.players;
  const byKey = Object.fromEntries(players.map((p) => [p.player_key, p]));
  const teamKeys = Object.keys(D.teams).filter((k) => players.some((p) => p.team_key === k))
    .sort((a, b) => teamName(a).localeCompare(teamName(b)));

  // ------------------------------------------------------------ helpers

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function money(n) { return n == null ? "—" : "$" + n; }
  function teamName(k) {
    if (!k) return "?";
    if (D.teams[k]) return D.teams[k].name;
    // Team keys change each season (461.l.X.t.4 -> 470.l.Y.t.4); match on the team number.
    const id = k.split(".t.")[1];
    const match = Object.keys(D.teams).find((t) => t.split(".t.")[1] === id);
    return match ? D.teams[match].name : k;
  }
  function ordinal(n) { return n + (["th", "st", "nd", "rd"][n % 10 > 3 || [11, 12, 13].includes(n % 100) ? 0 : n % 10]); }
  function playerMeta(p) { return [p.position, p.nfl_team].filter(Boolean).join(" · "); }
  function statusPill(p) {
    let html = p.eligible ? '<span class="pill ok">Eligible</span>' : '<span class="pill out">Back to pool</span>';
    if (p.override) html += ' <span class="pill ovr" title="' + esc(p.override.note) + '">Commish</span>';
    return html;
  }
  function sourceText(p) {
    return {
      keeper: "last year's keeper price",
      draft: "draft price",
      waiver: "highest waiver bid this season",
      free_agent: "free-agent pickup (no bid)",
      no_record: "no draft or pickup on record — priced as a free agent",
    }[p.price_source] || p.price_source;
  }
  function matches(p, q) {
    q = q.trim().toLowerCase();
    return !q || p.name.toLowerCase().includes(q) || teamName(p.team_key).toLowerCase().includes(q);
  }
  function teamOptions(selected, blank) {
    return (blank ? '<option value="">' + esc(blank) + "</option>" : "") +
      teamKeys.map((k) => '<option value="' + esc(k) + '"' + (k === selected ? " selected" : "") + ">" +
        esc(teamName(k)) + "</option>").join("");
  }
  function trailHtml(p) {
    const lines = p.history.map((h) => {
      const t = teamName(h.team_key);
      const text = {
        drafted: "Drafted by " + t + " for " + money(h.price),
        claimed: h.price == null ? "Added by " + t + " as a free agent" : "Claimed by " + t + " for a " + money(h.price) + " bid",
        dropped: "Dropped by " + t,
        traded: "Traded from " + teamName(h.from_team) + " to " + t,
        kept: "Kept by " + t + " for " + h.season + " at " + money(h.price),
      }[h.event] || h.event;
      return "<li>" + esc(text) + (h.date ? ' <span class="date">' + esc(h.date) + "</span>" : "") + "</li>";
    });
    return lines.length ? '<ol class="trail">' + lines.join("") + "</ol>" : '<p class="muted small">No moves on record.</p>';
  }

  // ------------------------------------------------------------ header

  document.getElementById("league-name").textContent = C.league_name + " Keepers";
  document.title = "Pool Keepers";
  document.getElementById("status-line").textContent = D.keeper_season + " keeper costs · rosters as of " +
    (D.snapshot ? D.snapshot.as_of : D.season + (D.season_finished ? " (final)" : " week " + D.roster_week));
  (function deadline() {
    const el = document.getElementById("deadline");
    if (!D.keeper_deadline) { el.textContent = "Keeper deadline: TBD (one week before the draft)"; return; }
    const end = new Date(D.keeper_deadline + "T23:59:59");
    const days = Math.ceil((end - new Date()) / 86400000);
    el.textContent = days < 0
      ? "Keeper deadline passed (" + D.keeper_deadline + ") — budgets are locked"
      : "Keeper deadline " + D.keeper_deadline + " · " + (days === 0 ? "today" : days + " day" + (days === 1 ? "" : "s") + " left");
  })();
  document.getElementById("foot").textContent = "Updated " + new Date(D.generated_at).toLocaleString() +
    ". Commish corrections are marked “Commish”.";
  // Hand-built data (before the Yahoo feed is connected) gets a banner on every tab.
  const snapshotNote = D.snapshot
    ? '<div class="notice"><b>Preliminary.</b> ' + esc(D.snapshot.note) + "</div>"
    : "";

  // ------------------------------------------------------------ views

  const state = { sort: "keeper_cost", asc: false, q: "", team: "", eligibleOnly: false };

  // Costs come right after the name so they stay on screen on a phone; the team column
  // hides on narrow screens and shows under the player's name instead.
  // Cost subtitles name the keeper year and tax. Once some players have already been kept,
  // the year differs by player, so the subtitle just says "+ keeper tax".
  const tax = C.keeper_tax_schedule;
  const allFirstYear = players.every((p) => p.years_kept === 0);
  const COLS = [
    { key: "name", label: "Player" },
    { key: "base_price", label: "Paid " + D.season, num: true,
      sub: allFirstYear ? "draft or top bid" : "base price" },
    { key: "keeper_cost", label: "Keep " + D.keeper_season, num: true,
      sub: allFirstYear ? "+" + money(tax[0]) + " tax (1st yr)" : "+ keeper tax" },
    { key: "cost_if_kept_again", label: "Keep " + (D.keeper_season + 1), num: true,
      sub: allFirstYear && tax[1] != null ? "+" + money(tax[1]) + " tax (2nd yr)" : "+ next year's tax" },
    { key: "years_kept", label: "Yrs kept", num: true, cls: "wide-only" },
    { key: "status", label: "Status" },
    { key: "team", label: "Team", cls: "wide-only" },
  ];

  function sortValue(p, key) {
    if (key === "team") return teamName(p.team_key);
    if (key === "status") return (p.eligible ? 0 : 1) + (p.override ? 0.5 : 0);
    return p[key];
  }

  function board() {
    view.innerHTML =
      "<h2>Keeper Board</h2>" +
      '<div class="controls">' +
      '<input type="search" id="q" placeholder="Search player or team" value="' + esc(state.q) + '">' +
      '<select id="team">' + teamOptions(state.team, "All teams") + "</select>" +
      '<label class="check"><input type="checkbox" id="elig"' + (state.eligibleOnly ? " checked" : "") + "> Eligible only</label>" +
      "</div>" +
      '<div class="table-wrap"><table><thead><tr>' +
      COLS.map((c) => '<th data-k="' + c.key + '" class="' + (c.num ? "num " : "") + (c.cls ? c.cls + " " : "") +
        (state.sort === c.key ? "sorted" + (state.asc ? " asc" : "") : "") + '">' + esc(c.label) +
        (c.sub ? '<span class="th-sub">' + esc(c.sub) + "</span>" : "") + "</th>").join("") +
      '</tr></thead><tbody id="rows"></tbody></table></div>';
    const rows = document.getElementById("rows");

    function draw() {
      const list = players
        .filter((p) => matches(p, state.q) && (!state.team || p.team_key === state.team) && (!state.eligibleOnly || p.eligible))
        .sort((a, b) => {
          let x = sortValue(a, state.sort), y = sortValue(b, state.sort);
          if (x == null) return 1;
          if (y == null) return -1;
          const r = typeof x === "string" ? x.localeCompare(y) : x - y;
          return state.asc ? r : -r;
        });
      rows.innerHTML = list.map((p) =>
        '<tr class="' + (p.eligible ? "" : "out") + '">' +
        '<td><a href="#player/' + encodeURIComponent(p.player_key) + '">' + esc(p.name) + '</a><span class="meta">' + esc(playerMeta(p)) +
        '<span class="narrow-only"> · ' + esc(teamName(p.team_key)) + "</span></span></td>" +
        '<td class="num">' + money(p.base_price) + "</td>" +
        '<td class="num"><b>' + money(p.keeper_cost) + "</b></td>" +
        '<td class="num">' + money(p.cost_if_kept_again) + "</td>" +
        '<td class="num wide-only">' + p.years_kept + "</td>" +
        "<td>" + statusPill(p) + "</td>" +
        '<td class="wide-only">' + esc(teamName(p.team_key)) + "</td></tr>").join("") ||
        '<tr><td colspan="' + COLS.length + '" class="muted">No players match.</td></tr>';
    }
    draw();

    document.getElementById("q").addEventListener("input", (e) => { state.q = e.target.value; draw(); });
    document.getElementById("team").addEventListener("change", (e) => { state.team = e.target.value; draw(); });
    document.getElementById("elig").addEventListener("change", (e) => { state.eligibleOnly = e.target.checked; draw(); });
    view.querySelectorAll("th").forEach((th) => th.addEventListener("click", () => {
      const k = th.dataset.k;
      state.asc = state.sort === k ? !state.asc : k === "name" || k === "team";
      state.sort = k;
      board();
    }));
  }

  function teams(team) {
    team = team || teamKeys[0];
    const roster = players.filter((p) => p.team_key === team)
      .sort((a, b) => (b.eligible - a.eligible) || ((b.keeper_cost || 0) - (a.keeper_cost || 0)));
    const t = D.teams[team] || {};
    view.innerHTML =
      "<h2>Team keepers</h2>" +
      '<div class="controls"><select id="team">' + teamOptions(team) + "</select></div>" +
      '<div class="card"><h3>' + esc(teamName(team)) + (t.manager ? ' <span class="muted small">' + esc(t.manager) + "</span>" : "") + "</h3>" +
      '<p class="muted small">Pick up to ' + C.max_keepers + " to see what you'd have left to spend in the " + D.keeper_season + " draft.</p>" +
      '<div class="picks">' + roster.map((p) =>
        '<label class="' + (p.eligible ? "" : "disabled") + '">' +
        '<input type="checkbox" value="' + esc(p.player_key) + '"' + (p.eligible ? "" : " disabled") + ">" +
        '<span class="name">' + esc(p.name) + ' <span class="muted small">' + esc(playerMeta(p)) +
        (p.years_kept ? " · kept " + p.years_kept + "x" : "") + "</span>" +
        (p.override ? ' <span class="pill ovr" title="' + esc(p.override.note) + '">Commish</span>' : "") + "</span>" +
        '<span class="cost">' + (p.eligible ? money(p.keeper_cost) : '<span class="pill out">Back to pool</span>') + "</span></label>").join("") +
      "</div>" +
      '<div class="budget" id="budget"></div></div>';

    const boxes = Array.from(view.querySelectorAll(".picks input"));
    function update() {
      const picked = boxes.filter((b) => b.checked).map((b) => byKey[b.value]);
      const total = picked.reduce((s, p) => s + p.keeper_cost, 0);
      const full = picked.length >= C.max_keepers;
      boxes.forEach((b) => {
        const off = !byKey[b.value].eligible || (full && !b.checked);
        b.disabled = off;
        b.parentElement.classList.toggle("disabled", off);
      });
      document.getElementById("budget").innerHTML = picked.length
        ? "Keeping " + picked.map((p) => esc(p.name)).join(" + ") + " (" + money(total) + ")<br><b>" +
          money(C.draft_budget - total) + "</b> to spend in the draft"
        : "No keepers picked · <b>" + money(C.draft_budget) + "</b> to spend";
    }
    boxes.forEach((b) => b.addEventListener("change", update));
    update();
    document.getElementById("team").addEventListener("change", (e) => { location.hash = "teams/" + encodeURIComponent(e.target.value); });
  }

  function playerCard(p) {
    return '<div class="card"><h3>' + esc(p.name) + ' <span class="muted small">' + esc(playerMeta(p)) + "</span></h3>" +
      "<div>" + statusPill(p) + "</div>" +
      '<div class="stats">' +
      "<div><b>" + money(p.base_price) + "</b><span>Paid " + D.season + " (" + esc(sourceText(p)) + ")</span></div>" +
      "<div><b>" + money(p.keeper_cost) + "</b><span>" + D.keeper_season + " keeper cost" +
        (p.eligible ? " (+" + money(p.keeper_tax) + " tax, " + ordinal(p.years_kept + 1) + " yr)" : "") + "</span></div>" +
      "<div><b>" + esc(teamName(p.team_key)) + "</b><span>Holds keeper rights</span></div>" +
      "<div><b>" + p.years_kept + " of " + C.max_years_kept + "</b><span>Years kept so far</span></div>" +
      "<div><b>" + money(p.cost_if_kept_again) + "</b><span>" + (D.keeper_season + 1) + " cost if kept again" +
        (p.cost_if_kept_again != null ? " (+" + money(C.keeper_tax_schedule[p.years_kept + 1]) + " tax, " + ordinal(p.years_kept + 2) + " yr)" : "") +
        "</span></div>" +
      "</div>" +
      '<p class="small">' + (p.eligible
        ? "Base " + money(p.base_price) + " (" + esc(sourceText(p)) + ") + " + money(p.keeper_tax) + " " + ordinal(p.years_kept + 1) + "-year keeper tax."
        : "Already kept the max " + C.max_years_kept + " years, so he goes back into the draft pool.") + "</p>" +
      (p.override ? '<div class="notice">Commissioner override' + (p.override.note ? ": " + esc(p.override.note) : "") +
        ". Was: " + esc(Object.entries(p.override.original).map(([k, v]) => k.replace(/_/g, " ") + " " + (k === "team_key" ? teamName(v) : v)).join(", ")) + "</div>" : "") +
      "<h3>History</h3>" + trailHtml(p) + "</div>";
  }

  function lookup(key) {
    const p = key && byKey[key];
    view.innerHTML = "<h2>Player lookup</h2>" +
      '<div class="controls"><input type="search" id="q" placeholder="Type a player name" autocomplete="off"></div>' +
      '<div class="results" id="results"></div><div id="card">' + (p ? playerCard(p) : "") + "</div>";
    const q = document.getElementById("q");
    q.addEventListener("input", () => {
      const hits = q.value.trim() ? players.filter((x) => matches(x, q.value)).slice(0, 8) : [];
      document.getElementById("results").innerHTML = hits.map((x) =>
        '<button data-k="' + esc(x.player_key) + '">' + esc(x.name) + ' <span class="muted small">' +
        esc(teamName(x.team_key)) + " · " + (x.eligible ? money(x.keeper_cost) : "back to pool") + "</span></button>").join("");
    });
    document.getElementById("results").addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (b) location.hash = "player/" + encodeURIComponent(b.dataset.k);
    });
    if (!p) q.focus();
  }

  function trade() {
    const sorted = players.slice().sort((a, b) => a.name.localeCompare(b.name));
    view.innerHTML = "<h2>Trade helper</h2>" +
      '<p class="muted small">Keeper rights and price travel with the player. Pick who\'s moving and where.</p>' +
      '<div class="controls"><select id="pl"><option value="">Pick a player</option>' +
      teamKeys.map((t) => '<optgroup label="' + esc(teamName(t)) + '">' + sorted.filter((p) => p.team_key === t)
        .map((p) => '<option value="' + esc(p.player_key) + '">' + esc(p.name) + "</option>").join("") + "</optgroup>").join("") +
      '</select><select id="to">' + teamOptions("", "Receiving team") + "</select></div>" +
      '<div id="out"></div>';
    function draw() {
      const p = byKey[document.getElementById("pl").value];
      const to = document.getElementById("to").value;
      const out = document.getElementById("out");
      if (!p) { out.innerHTML = ""; return; }
      const who = to ? teamName(to) : "the receiving team";
      out.innerHTML = '<div class="card"><h3>' + esc(p.name) + " → " + esc(who) + "</h3>" +
        (p.eligible
          ? '<p><span class="big">' + money(p.keeper_cost) + "</span><br>" + esc(who) + " could keep him for " + D.keeper_season +
            " at this price, the same as " + esc(teamName(p.team_key)) + " would pay. " +
            (p.cost_if_kept_again != null ? "Keeping him again in " + (D.keeper_season + 1) + " would cost " + money(p.cost_if_kept_again) + "." :
              "That would be his last keeper year.") + "</p>"
          : "<p>He's been kept the max " + C.max_years_kept + " years, so nobody can keep him. He goes back into the draft pool.</p>") +
        '<p class="small muted">Rights go to whoever has him on their roster at season\'s end.</p></div>';
    }
    document.getElementById("pl").addEventListener("change", draw);
    document.getElementById("to").addEventListener("change", draw);
  }

  function declarations() {
    const any = Object.keys(D.declarations).length > 0;
    view.innerHTML = "<h2>" + D.keeper_season + " keeper declarations</h2>" +
      (any ? "" : '<div class="notice">No keepers declared yet. ' + (D.keeper_deadline ? "Deadline: " + esc(D.keeper_deadline) + "." :
        "The deadline is one week before the draft (date TBD).") + "</div>") +
      '<div class="table-wrap"><table><thead><tr><th>Team</th><th>Keepers</th><th class="num">Cost</th><th class="num">Draft budget</th></tr></thead><tbody>' +
      teamKeys.map((t) => {
        const d = D.declarations[t];
        const keepers = d ? d.keepers.map((k) => byKey[k] ? esc(byKey[k].name) + " " + money(byKey[k].keeper_cost) : esc(k)).join("<br>") || "None" : '<span class="muted">Not declared</span>';
        return "<tr><td>" + esc(teamName(t)) + "</td><td>" + keepers +
          (d && d.errors.length ? '<div class="error">' + d.errors.map(esc).join("<br>") + "</div>" : "") + "</td>" +
          '<td class="num">' + money(d ? d.total_cost : 0) + '</td><td class="num"><b>' + money(d ? d.remaining_budget : C.draft_budget) + "</b></td></tr>";
      }).join("") + "</tbody></table></div>";
  }

  function rules() {
    const tax = C.keeper_tax_schedule.slice(0, C.max_years_kept);
    view.innerHTML = '<h2>Keeper rules</h2><div class="card"><ol class="rules">' +
      "<li><b>Keep up to " + C.max_keepers + " players.</b> Keeping fewer (or none) is fine.</li>" +
      "<li><b>Keeper cost = last season's price + a keeper tax</b> that grows each year: " +
      tax.map((t, i) => "+" + money(t) + " the " + ordinal(i + 1) + " year").join(", ") + ".</li>" +
      "<li><b>Max " + C.max_years_kept + " years kept.</b> After that he goes back into the draft pool.</li>" +
      "<li><b>Keeper costs come out of your " + money(C.draft_budget) + " draft budget.</b></li>" +
      "<li><b>Whoever has him on their roster at season's end holds the rights.</b> Trades move the rights, and the price goes with him.</li>" +
      "<li><b>Drafted players keep their draft price forever</b>, even if dropped and picked up by someone else.</li>" +
      "<li><b>Waiver pickups cost their FAAB bid + tax.</b> If he was claimed more than once, the highest bid that season counts. " +
      "A free-agent add with no bid counts as " + money(C.free_agent_base_price) + ".</li>" +
      "<li><b>Unrostered at season's end?</b> Nobody can keep him, and his price resets next year.</li>" +
      "<li><b>Declare keepers " + C.keeper_deadline_days_before_draft + " days before the draft</b>" +
      (D.keeper_deadline ? " (" + esc(D.keeper_deadline) + ")" : " (draft date TBD)") +
      ". After the deadline, undeclared players go into the pool and budgets lock.</li>" +
      "<li>The commissioner can correct anything; corrections are marked “Commish”.</li>" +
      "</ol></div>" +
      '<div class="card small"><b>Example:</b> Gibbs drafted for $65 → kept at ' + money(65 + tax[0]) +
      (tax[1] != null ? " → kept again at " + money(65 + tax[0] + tax[1]) : "") +
      " → back to the pool. Keeping him at " + money(65 + tax[0]) + " leaves " + money(C.draft_budget - 65 - tax[0]) + " to spend.</div>";
  }

  // ------------------------------------------------------------ routing

  const ROUTES = { board: board, teams: teams, player: lookup, trade: trade, declarations: declarations, rules: rules };
  function route() {
    const [name, arg] = (location.hash.slice(1) || "board").split("/");
    const fn = ROUTES[name] || board;
    document.querySelectorAll(".tabs a").forEach((a) => a.classList.toggle("on", a.getAttribute("href") === "#" + (ROUTES[name] ? name : "board")));
    fn(arg && decodeURIComponent(arg));
    if (snapshotNote) view.insertAdjacentHTML("afterbegin", snapshotNote);
    window.scrollTo(0, 0);
  }
  window.addEventListener("hashchange", route);
  route();
})();
