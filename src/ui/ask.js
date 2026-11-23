// Claude · 2026-11-23 · Session 8e680ddd · Prism Ask box (trip pages) and Plan a new trip (home); inlined by build_portal.py
// On a trip page a question goes to the portal's helper and can come back as a removable filter on the flights shown.
// On the home page a described trip becomes a search job, created only when Start search is pressed.
(function () {
  "use strict";
  const host = document.getElementById("ask");
  if (!host) return;
  const IS_TRIP = typeof TRIP !== "undefined" && !!TRIP;
  const PAGE = IS_TRIP ? TRIP.slug : "home";
  const BASE = typeof API !== "undefined" ? API : null;
  const e = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const enc = encodeURIComponent;
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const TA = () => (window.TripAPI && typeof window.TripAPI === "object" ? window.TripAPI : null);
  const tryCall = (f, d) => { try { return f(); } catch (x) { return d; } };
  const ptTime = iso => tryCall(() => new Date(iso).toLocaleString("en-US", {timeZone: "America/Los_Angeles", weekday: "short", hour: "numeric", minute: "2-digit"}).replace(" AM", "am").replace(" PM", "pm") + " PT", "");
  const day = s => tryCall(() => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d).toLocaleDateString("en-US", {weekday: "short", month: "short", day: "numeric"}); }, s);
  const call = (path, body) => fetch(BASE + path, body ? {method: "POST", headers: {"Content-Type": "application/json", "X-Flights": "1"}, body: JSON.stringify(body)} : {cache: "no-store"})
    .then(async r => ({ok: r.ok, status: r.status, d: await r.json().catch(() => ({}))})).catch(() => ({ok: false, status: 0, d: {error: "Could not reach the portal. Check you are on your private network, then try again."}}));
  const HIDE_KEY = "flights-ask-hidden-jobs";
  const hidden = new Set(tryCall(() => JSON.parse(localStorage.getItem(HIDE_KEY) || "[]"), []));

  host.classList.add("ask");
  if (!IS_TRIP) host.classList.add("ask-home", "box");
  host.innerHTML =
    (IS_TRIP ? "" : '<div class="ask-title">Plan a new trip</div>') +
    '<form class="ask-in" id="askForm" novalidate><label class="ask-sr" for="askQ">' + (IS_TRIP ? "Ask about these flights, or describe what you want" : "Describe a trip") + "</label>" +
    '<input id="askQ" type="text" maxlength="500" autocomplete="off" enterkeyhint="send" placeholder="' +
    (IS_TRIP ? "Ask about these flights, or describe what you want" : "Describe it, like Bay Area to Austin, Dec 18 to 21, nonstop if I can") + '">' +
    '<button class="btn pri" id="askGo" type="submit">' + (IS_TRIP ? "Ask" : "Plan") + "</button></form>" +
    '<div class="ask-status" id="askStatus" role="status" aria-live="polite"></div><div id="askOut"></div><div id="askJobs"></div>' +
    '<details class="ask-hist" id="askHist" hidden><summary id="askHistSum">Recent questions</summary><div id="askHistList"></div></details>';
  const $a = id => document.getElementById(id);
  const input = $a("askQ"), go = $a("askGo"), statusEl = $a("askStatus"), out = $a("askOut"), jobsEl = $a("askJobs");
  let busy = false, shown = null, recent = [], jobs = [], limits = null, pollT = null;

  function status(t, kind) { statusEl.textContent = t || ""; statusEl.className = "ask-status" + (kind ? " " + kind : ""); }

  // ---- asking ----
  async function ask(q) {
    q = (q || "").trim();
    if (!q) { input.focus(); return; }
    if (!BASE) { status("Asking works on the portal itself (this copy is offline).", "bad"); return; }
    if (busy) return;
    busy = true; go.disabled = true;
    const ctx = IS_TRIP && TA() && typeof TA().context === "function" ? tryCall(() => TA().context(), null) : null;
    const total = (ctx && ctx.total) || (IS_TRIP && TRIP.rows ? TRIP.rows.length : 0);
    const body = {page: PAGE, question: q, filters: ctx && ctx.filters && typeof ctx.filters === "object" ? ctx.filters : null, visible: ctx && Array.isArray(ctx.visibleIds) ? ctx.visibleIds.slice(0, 2000) : null};
    const t0 = Date.now();
    const words = IS_TRIP ? "Claude is reading the " + (total ? total + " " : "") + "flights on this page" : "Claude is turning that into a search plan";
    const tick = () => status(words + "... " + Math.round((Date.now() - t0) / 1000) + "s (usually 20 to 40 seconds)");
    tick(); const timer = setInterval(tick, 1000);
    const finish = () => { clearInterval(timer); busy = false; go.disabled = false; };
    const r = await call("/ask", body);
    if (!r.ok) { finish(); status(r.d.error || "Could not ask (error " + r.status + ").", "bad"); return; }
    let rec = r.d, misses = 0;
    while (rec.status === "working") {
      await sleep(Date.now() - t0 < 30000 ? 2000 : 3000);
      const g = await call("/ask/" + enc(rec.id));
      if (g.ok) { rec = g.d; misses = 0; } else if (++misses >= 6) { rec = {status: "error", question: q, error: g.d.error || "Lost touch with the portal while waiting."}; }
      if (rec.status === "working" && Date.now() - t0 > 200000) rec = {status: "error", question: q, error: "No answer after more than 3 minutes. Try again, or ask in chat."};
    }
    finish(); status("");
    rec.question = rec.question || q;
    if (rec.status === "done") { input.value = ""; recent = [rec].concat(recent.filter(h => h.id !== rec.id)).slice(0, 6); paintHistory(); }
    show(rec, true);
  }

  function applyFilter(rec) {
    const t = TA();
    if (!t || typeof t.setQuery !== "function") return false;
    return tryCall(() => { t.setQuery({label: rec.label || rec.ids.length + " flights", ids: rec.ids.slice(), answer: rec.answer}); return true; }, false);
  }

  function show(rec, fresh) {
    shown = rec;
    if (rec.status === "error") {
      out.innerHTML = '<div class="ask-card box"><div class="ask-q">' + e(rec.question) + '</div><p class="ask-a bad">' + e(rec.error || "Something went wrong.") +
        '</p><div class="ask-acts"><button class="btn sm" data-act="again">Try again</button><button class="lnk" data-act="close">Close</button></div></div>';
      return;
    }
    let h = '<div class="ask-card box"><div class="ask-q">' + e(rec.question) + (rec.asked_at ? " · " + e(ptTime(rec.asked_at)) : "") + '</div><p class="ask-a">' + e(rec.answer) + "</p>";
    if (IS_TRIP && rec.ids && rec.ids.length) {
      const ok = fresh ? applyFilter(rec) : false;
      h += '<div class="ask-f" id="askF">' + (ok ? "Filtered to " + rec.ids.length + " flight" + (rec.ids.length > 1 ? "s" : "") + ": <b>" + e(rec.label || "") + '</b><button class="lnk" data-act="clear">Remove filter</button>'
        : (TA() && typeof TA().setQuery === "function" ? rec.ids.length + " flights match. " + '<button class="lnk" data-act="apply">Show only these</button>' : rec.ids.length + " flights match (this page cannot filter to them yet).")) + "</div>";
    }
    if (rec.needs_search) h += proposal(rec);
    h += '<div class="ask-acts end"><button class="lnk" data-act="close">Close</button></div></div>';
    out.innerHTML = h;
  }

  function proposal(rec) {
    const ns = rec.needs_search;
    const left = limits ? Math.max(0, limits.per_day - limits.used_today) : null;
    return '<div class="ask-prop"><div class="ask-prop-h">' + (IS_TRIP ? "This needs a new search" : "Proposed search") + "</div><div>" + e(ns.description) + "</div>" +
      '<div class="ask-kv"><span>From</span>' + e((ns.origins || []).join(", ") || "as described") + "</div>" +
      '<div class="ask-kv"><span>To</span>' + e((ns.dests || []).join(", ")) + "</div>" +
      '<div class="ask-kv"><span>Dates</span>' + e((ns.dates || []).map(day).join(", ") || "as described") + "</div>" +
      '<div class="ask-acts" id="askPropActs"><button class="btn pri" data-act="start">Start search</button><button class="btn" data-act="close">Not now</button></div>' +
      '<div class="mu">Runs on your MacBook with your signed-in Chrome, so it needs to be awake with Chrome open. Search only; nothing is booked.' +
      (left != null ? " " + left + " of " + limits.per_day + " searches left today." : "") + "</div></div>";
  }

  async function startSearch() {
    const rec = shown; if (!rec || !rec.needs_search) return;
    const acts = $a("askPropActs"); if (acts) acts.innerHTML = '<span class="mu">Sending...</span>';
    const ns = rec.needs_search;
    const r = await call("/jobs", {page: PAGE, description: ns.description, origins: ns.origins, dests: ns.dests, dates: ns.dates, from_ask: rec.id || null});
    if (acts) acts.innerHTML = r.ok ? '<span class="good">Search queued. Progress shows below.</span>' : '<span class="bad">' + e(r.d.error || "Could not start the search (error " + r.status + ").") + "</span>";
    await loadJobs();
  }

  // ---- jobs ----
  const LABEL = {queued: ["Waiting", ""], starting: ["Starting", "acc"], running: ["Searching", "acc"], done: ["Done", "good"], failed: ["Failed", "bad"], needs_you: ["Needs you", "warn"], cancelled: ["Cancelled", ""]};
  const ACTIVE = s => s === "queued" || s === "starting" || s === "running";
  function mine(j) { return !IS_TRIP || j.page === PAGE || j.slug === PAGE; }
  function paintJobs() {
    const now = Date.now();
    const list = jobs.filter(j => mine(j) && !hidden.has(j.id) && (ACTIVE(j.status) || now - new Date(j.updated_at).getTime() < 12 * 36e5)).slice(-4).reverse();
    jobsEl.innerHTML = list.map(j => {
      const [lab, cls] = LABEL[j.status] || [j.status, ""];
      let act = "";
      if (j.status === "done" && j.slug) act = j.slug === PAGE ? '<button class="btn sm pri" data-act="reload">New flights are in, reload</button>' : '<a class="btn sm pri" href="/flights/' + e(j.slug) + '/">New flights are in, open the trip</a>';
      else if (j.status === "done" && !IS_TRIP) act = '<button class="btn sm" data-act="reload">Reload</button>';
      if (j.status === "failed" || j.status === "needs_you") act += '<button class="btn sm" data-act="retry" data-id="' + e(j.id) + '">Try again</button>';
      if (j.status === "queued") act += '<button class="lnk" data-act="cancel" data-id="' + e(j.id) + '">Cancel</button>';
      if (!ACTIVE(j.status)) act += '<button class="lnk" data-act="hide" data-id="' + e(j.id) + '">Hide</button>';
      return '<div class="ask-job box"><div class="ask-job-h"><span class="pill ' + cls + '">' + e(lab) + (j.dry_run ? " (dry run)" : "") + '</span><span class="ask-job-d">' + e(j.description) + "</span></div>" +
        '<div class="ask-job-n">' + e(j.note || "") + (j.updated_at ? " · " + e(ptTime(j.updated_at)) : "") + "</div>" + (act ? '<div class="ask-acts">' + act + "</div>" : "") + "</div>";
    }).join("");
    const active = jobs.some(j => mine(j) && ACTIVE(j.status));
    clearTimeout(pollT); pollT = null;
    if (active && !document.hidden) pollT = setTimeout(loadJobs, 4000);  // poll only while a search is active
  }
  async function loadJobs() {
    if (!BASE) return;
    const r = await call("/jobs");
    if (r.ok) { jobs = r.d.jobs || []; limits = r.d.limits || null; }
    paintJobs();
  }
  async function jobAction(id, act) {
    const r = await call("/jobs/" + enc(id) + "/" + act, {});
    if (!r.ok) status(r.d.error || "Could not " + act + " (error " + r.status + ").", "bad");
    await loadJobs();
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden) loadJobs(); });

  // ---- recent questions (shared across devices through the portal) ----
  function paintHistory() {
    const list = recent.filter(h => h.status === "done").slice(0, 6), box = $a("askHist");
    box.hidden = !list.length;
    $a("askHistSum").textContent = "Recent questions (" + list.length + ")";
    $a("askHistList").innerHTML = list.map((h, i) => '<div class="ask-hi"><div class="ask-hq">' + e(h.question) + ' <span class="mu">' + e(ptTime(h.asked_at)) + '</span></div><div class="ask-a">' + e(h.answer) + '</div><div class="ask-acts">' +
      '<button class="lnk" data-act="show" data-i="' + i + '">Show answer</button>' + (IS_TRIP && h.ids && h.ids.length ? '<button class="lnk" data-act="hfilter" data-i="' + i + '">Filter to these ' + h.ids.length + "</button>" : "") + "</div></div>").join("");
  }
  async function loadHistory() {
    if (!BASE) return;
    const r = await call("/ask?page=" + enc(PAGE));
    if (r.ok) { recent = (r.d.asks || []).filter(h => h.status === "done"); paintHistory(); }
  }

  // ---- events ----
  $a("askForm").addEventListener("submit", ev => { ev.preventDefault(); ask(input.value); });
  host.addEventListener("click", ev => {
    const b = ev.target.closest("[data-act]"); if (!b) return;
    const act = b.getAttribute("data-act"), id = b.getAttribute("data-id"), hi = recent.filter(h => h.status === "done")[+b.getAttribute("data-i")];
    if (act === "close") { out.innerHTML = ""; shown = null; }
    else if (act === "again" && shown) ask(shown.question);
    else if (act === "start") startSearch();
    else if (act === "clear") { const t = TA(); if (t && typeof t.clearQuery === "function") tryCall(() => t.clearQuery()); const f = $a("askF"); if (f) f.innerHTML = 'Filter removed. <button class="lnk" data-act="apply">Show only these again</button>'; }
    else if (act === "apply" && shown) show(shown, true);
    else if (act === "show" && hi) show(hi, false);
    else if (act === "hfilter" && hi) show(hi, true);
    else if (act === "reload") location.reload();
    else if ((act === "retry" || act === "cancel") && id) jobAction(id, act);
    else if (act === "hide" && id) { hidden.add(id); tryCall(() => localStorage.setItem(HIDE_KEY, JSON.stringify([...hidden].slice(-50)))); paintJobs(); }
  });
  if (!BASE) { status("Asking works on the portal itself (this copy is offline)."); go.disabled = true; return; }
  loadJobs(); loadHistory();
})();
