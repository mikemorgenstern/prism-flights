// Claude · 2026-11-22, updated 2026-11-23 · Session 8e680ddd · flights portal end-to-end test
// node src/tests/portal_test.js <base url> <screenshot dir> [trip slug]
// Run it only against a local src/service.py with a copy of the site and a scratch FLIGHTS_STATE: it clicks a like and
// submits a check request. The trip defaults to the first one on the home page; airports and days are read from the
// page's own data, so the same test covers any trip. Needs playwright-core (PLAYWRIGHT_CORE = its path, if not installed).
const { chromium } = require(process.env.PLAYWRIGHT_CORE || 'playwright-core');
(async () => {
  const [base, shots, slugArg] = process.argv.slice(2); const out = {}; const errs = []; const fails = [];
  const step = async (name, fn) => { try { await fn(); } catch (e) { fails.push(name + ': ' + e.message.split('\n')[0]); } };
  const b = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome' });
  const ctx = await b.newContext({ viewport: { width: 1400, height: 900 } }); const p = await ctx.newPage();
  p.on('pageerror', e => errs.push('page: ' + e.message)); p.on('console', m => { if (m.type() === 'error') errs.push('console: ' + m.text()); });
  const count = async () => (await p.textContent('#count')).replace(/\s+/g, ' ');
  // home
  await p.goto(base + '/flights/', { waitUntil: 'networkidle' }); await p.waitForTimeout(500);
  const slug = slugArg || await p.evaluate(() => (HOME.trips[0] || {}).slug);
  out.slug = slug;
  await step('home tiles and lists', async () => {
    out.tiles = await p.$$eval('.tile2', t => t.map(x => x.innerText.replace(/\s+/g, ' ')));
    out.trips = await p.$$eval('.trip .tl', t => t.map(x => x.innerText.replace(/\s+/g, ' ').slice(0, 300)));
    out.credits = await p.$$eval('.crow', t => t.length); out.bals = await p.$$eval('.brow', t => t.length);
    out.oldLinks = await p.evaluate(() => (HOME.oldLinks || []).length);
    out.oldLinksShown = await p.$('#oldLinks') ? (await p.$$eval('#oldLinks a', a => a.length)) : null;
  });
  await step('home check request round', async () => {
    await p.click('.crow >> nth=0'); out.expanded = !!(await p.$('.cdet'));
    await p.click('[data-chk^="credit:"]'); out.draftOpen = await p.isVisible('#draftbar'); out.draftText = await p.textContent('#draftText');
    await p.click('#draftbar .btn.pri'); await p.waitForTimeout(400); out.needs = await p.textContent('#needs');
    const chk = await (await p.request.get(base + '/flights/api/checks')).json(); out.checksStored = chk.checks.length;
    if (!out.checksStored) throw new Error('no check request stored');
  });
  // trip page
  await p.goto(base + '/flights/' + slug + '/', { waitUntil: 'networkidle' }); await p.waitForTimeout(500);
  const info = await p.evaluate(() => ({ total: TRIP.rows.length, days: Object.keys(TRIP.days), dests: Object.keys(TRIP.destNames),
    vias: [...new Set(TRIP.rows.flatMap(r => r[7]))] }));
  out.tripInfo = info;
  await step('trip page start', async () => {
    out.start = await count(); out.picks = await p.$$eval('.pick', t => t.map(x => x.innerText.replace(/\s+/g, ' ')));
    out.held = await p.$('#held') ? (await p.textContent('#held')).replace(/\s+/g, ' ') : null;
    out.gridCells = await p.$$eval('.gc', t => t.length); out.chips = await p.$$eval('.chip', t => t.map(x => x.innerText.replace(/\s+/g, ' ')));
  });
  await step('connection filter', async () => {
    await p.click('[data-chip="conn"]'); await p.waitForTimeout(200); out.connRows = await p.$$eval('#shList .opt', t => t.length);
    const opts = await p.$$eval('#shList .opt input[data-opt]', t => t.map(x => x.dataset.opt)); out.connOpts = opts.slice(0, 6);
    if (opts.length < 2) throw new Error('fewer than two connection options');
    await p.click(`#shList .opt:has(input[data-opt="${opts[0]}"]) input`); out.afterUntickFirst = await count();
    await p.hover(`#shList .opt:has(input[data-opt="${opts[1]}"])`); await p.click(`#shList .opt:has(input[data-opt="${opts[1]}"]) .only`); out.onlySecond = await count();
    await p.click('#shGo'); await p.click('[data-clear="conn"]'); out.afterClear = await count();
  });
  await step('day choice', async () => {
    if (info.days.length < 2) return;
    await p.click(`[data-seg="day"][data-v="${info.days[0]}"]`); await p.waitForTimeout(250); out.oneDay = await count();
    await p.click('[data-seg="day"][data-v="*"]'); await p.waitForTimeout(250); out.bothDays = await count();
  });
  await step('pay with Delta miles, then reset', async () => {
    await p.click('[data-chip="pay"]'); await p.click('#shList input[data-opt="dl"]'); await p.waitForTimeout(250); out.payDL = await count();
    if (await p.$('[data-chip="reset"]')) await p.click('[data-chip="reset"]');
    await p.waitForTimeout(250); out.reset = await count();
  });
  await step('flight panel opens from a row and closes', async () => {
    const id = await p.$eval('#list [data-ids]', e => e.id);
    await p.click('#' + id + ' td.t'); await p.waitForTimeout(300);
    out.panelOpen = await p.evaluate(() => document.getElementById('fp').classList.contains('open'));
    out.panelHeads = await p.$$eval('#fpBody h3', h => h.map(x => x.textContent));
    await p.click('#fpX'); await p.waitForTimeout(250);
    const still = await p.evaluate(() => document.getElementById('fp').classList.contains('open'));
    if (!out.panelOpen || still) throw new Error('panel open ' + out.panelOpen + ', still open after close ' + still);
  });
  await step('a best pick opens the panel', async () => {
    await p.click('.pick[data-go]'); await p.waitForTimeout(300);
    out.pickPanel = await p.evaluate(() => document.getElementById('fp').classList.contains('open'));
    await p.keyboard.press('Escape'); await p.waitForTimeout(200);
    if (!out.pickPanel) throw new Error('no panel from a pick');
  });
  await step('like a flight, saved on the server and kept after reload', async () => {
    const id = await p.$eval('#list [data-ids]', e => e.id);
    await p.evaluate(sel => document.querySelector(sel + ' [data-like]').click(), '#' + id); await p.waitForTimeout(700);
    const st = await (await p.request.get(base + '/flights/api/state/' + slug)).json();
    const n = Object.keys((st.value || {}).like || {}).length; out.likeSaved = n + ' liked, rev ' + st.revision;
    if (!n) throw new Error('like not saved on the server');
    await p.reload({ waitUntil: 'networkidle' }); await p.waitForTimeout(400);
    out.afterReload = await count(); out.likedChip = (await p.textContent('[data-chip="liked"]')).trim();
    if (!/\(\d+\)/.test(out.likedChip) || /\(0\)/.test(out.likedChip)) throw new Error('liked count not kept: ' + out.likedChip);
  });
  await p.screenshot({ path: shots + '/trip-1400.png' });
  // phone
  const ph = await b.newContext({ viewport: { width: 390, height: 844 }, colorScheme: 'dark', isMobile: true, hasTouch: true }); const q = await ph.newPage();
  q.on('pageerror', e => errs.push('phone: ' + e.message));
  await q.goto(base + '/flights/' + slug + '/', { waitUntil: 'networkidle' }); await q.waitForTimeout(500);
  await step('phone trip page', async () => {
    out.phoneCards = await q.$$eval('.card', t => t.length);
    out.phoneNoSide = await q.evaluate(() => document.documentElement.scrollWidth === document.documentElement.clientWidth);
    if (!out.phoneNoSide) throw new Error('page scrolls sideways at 390px');
  });
  await q.screenshot({ path: shots + '/trip-390-dark-top.png' });
  await q.goto(base + '/flights/', { waitUntil: 'networkidle' }); await q.waitForTimeout(400);
  out.phoneHomeNoSide = await q.evaluate(() => document.documentElement.scrollWidth === document.documentElement.clientWidth);
  await q.screenshot({ path: shots + '/home-390-dark.png', fullPage: true });
  const lt = await b.newContext({ viewport: { width: 1400, height: 1000 } }); const r2 = await lt.newPage(); await r2.goto(base + '/flights/', { waitUntil: 'networkidle' }); await r2.waitForTimeout(300); await r2.screenshot({ path: shots + '/home-1400.png', fullPage: true });
  out.errors = errs; out.failed = fails; console.log(JSON.stringify(out, null, 1)); await b.close();
  console.log(fails.length || errs.length ? `${fails.length} steps failed, ${errs.length} page errors` : 'all steps passed');
  process.exit(fails.length || errs.length ? 1 : 0);
})();
