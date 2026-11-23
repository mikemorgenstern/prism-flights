// Claude · 2026-11-23 · Session 8e680ddd · flights portal Ask UI test (a headless Chrome of its own, never a signed-in browser)
// node src/tests/ask_ui_test.js <base url> <screenshot dir> <stub job log> [trip slug]
// Needs a local service.py running with stub FLIGHTS_ASK_CMD and FLIGHTS_JOB_CMD; write them with
// python3 src/tests/ask_jobs_test.py --write-stubs <dir>. Built for the sample trip (examples/), whose stub proposal is PAE to BOS.
const { chromium } = require(process.env.PLAYWRIGHT_CORE || 'playwright-core');
const fs = require('fs');
(async () => {
  const [base, shots, joblog, slugArg] = process.argv.slice(2); const out = {}; const errs = []; const fails = [];
  const check = (name, ok, detail) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (!ok && detail !== undefined ? '  [' + JSON.stringify(detail) + ']' : '')); if (!ok) fails.push(name); };
  const b = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome' });
  const slug = slugArg || '27-03-12-boston';
  for (const scheme of ['light', 'dark']) {
    const ctx = await b.newContext({ viewport: { width: 375, height: 812 }, colorScheme: scheme, isMobile: true, hasTouch: true });
    // a stand-in for window.TripAPI (the main page script is adding the real one); records what the Ask box sends
    await ctx.addInitScript(() => {
      window.__calls = [];
      Object.defineProperty(window, 'TripAPI', { configurable: true, get() { return window.__ta; }, set(v) { window.__real = v; } });
      window.__ta = { context: () => ({ slug: TRIP.slug, filters: { stops: 'any' }, visibleIds: TRIP.rows.slice(0, 5).map(r => r[0]), total: TRIP.rows.length }),
        setQuery: q => window.__calls.push(['set', q]), clearQuery: () => window.__calls.push(['clear']) };
    });
    const p = await ctx.newPage();
    p.on('pageerror', e => errs.push(scheme + ' page: ' + e.message)); p.on('console', m => { if (m.type() === 'error') errs.push(scheme + ' console: ' + m.text()); });
    await p.goto(base + '/flights/' + slug + '/', { waitUntil: 'networkidle' });
    const box = await p.$eval('#askQ', el => { const r = el.getBoundingClientRect(); return { top: r.top + scrollY, h: r.height, ph: el.placeholder, fs: getComputedStyle(el).fontSize }; });
    const btnH = await p.$eval('#askGo', el => el.getBoundingClientRect().height);
    check(scheme + ': trip input and Ask button present, 44px tall, 16px text', box.ph === 'Ask about these flights, or describe what you want' && box.h >= 44 && btnH >= 44 && box.fs === '16px', { box, btnH });
    const picksBefore = await p.$eval('#picks', el => el.getBoundingClientRect().top + scrollY);
    await p.fill('#askQ', 'which are cheapest'); await p.click('#askGo');
    await p.waitForTimeout(300); out[scheme + 'Working'] = await p.textContent('#askStatus');
    const nFlights = await p.evaluate(() => TRIP.rows.length);
    check(scheme + ': working line shows while waiting', new RegExp('Claude is reading the ' + nFlights + ' flights').test(out[scheme + 'Working']), out[scheme + 'Working']);
    await p.waitForSelector('.ask-card .ask-a', { timeout: 15000 });
    const calls = await p.evaluate(() => window.__calls);
    check(scheme + ': ids applied through TripAPI.setQuery with label and answer', calls.length === 1 && calls[0][1].ids.length === 2 && calls[0][1].label === 'Stub pick' && calls[0][1].answer === 'Two flights fit.', calls);
    const boxAfter = await p.$eval('#askQ', el => el.getBoundingClientRect().top + scrollY);
    const picksAfter = await p.$eval('#picks', el => el.getBoundingClientRect().top + scrollY);
    check(scheme + ': nothing above the input moved; growth only below it', boxAfter === box.top && picksAfter >= picksBefore, { before: box.top, after: boxAfter, picksBefore, picksAfter });
    out[scheme + 'Filter'] = await p.textContent('#askF');
    await p.click('[data-act="clear"]'); const calls2 = await p.evaluate(() => window.__calls);
    check(scheme + ': Remove filter calls TripAPI.clearQuery', calls2[calls2.length - 1][0] === 'clear', calls2);
    const hist = await p.$eval('#askHist', el => !el.hidden && el.querySelector('summary').textContent);
    check(scheme + ': recent questions list appears', /Recent questions \(\d\)/.test(hist), hist);
    const noScroll = await p.evaluate(() => document.scrollingElement.scrollWidth <= innerWidth + 1);
    check(scheme + ': no sideways page scroll at 375px', noScroll);
    await p.screenshot({ path: `${shots}/trip-answer-${scheme}.png` });
    if (scheme === 'light') {
      await p.fill('#askQ', 'search'); await p.press('#askQ', 'Enter');
      await p.waitForSelector('.ask-prop [data-act="start"]', { timeout: 15000 });
      out.prop = (await p.textContent('.ask-prop')).replace(/\s+/g, ' ');
      check('proposal shows route, dates and the MacBook note', /From\s*PAE/.test(out.prop) && /To\s*BOS/.test(out.prop) && /Fri, Mar 12/.test(out.prop) && /MacBook/.test(out.prop), out.prop);
      await p.screenshot({ path: `${shots}/trip-proposal-light.png` });
      await p.click('[data-act="start"]'); await p.waitForSelector('.ask-job', { timeout: 5000 });
      out.job1 = (await p.textContent('.ask-job')).replace(/\s+/g, ' ');
      check('Start search creates a job and shows it', /Starting|Waiting/.test(out.job1) && /PAE to BOS/.test(out.job1), out.job1);
      await p.waitForTimeout(800);
      const lines = fs.readFileSync(joblog, 'utf8').trim().split('\n').map(JSON.parse); const j = lines[lines.length - 1];
      const r = await p.request.post(j.progress_url, { headers: { 'X-Flights': '1', 'X-Job-Token': j.token, 'Content-Type': 'application/json' }, data: { status: 'done', note: 'Added 12 flights from PAE', slug } });
      check('stub Mac reports done', r.status() === 200);
      await p.waitForSelector('[data-act="reload"]', { timeout: 8000 });
      out.jobDone = (await p.textContent('.ask-job')).replace(/\s+/g, ' ');
      check('page picks up done by polling and offers reload', /New flights are in, reload/.test(out.jobDone) && /Added 12 flights/.test(out.jobDone), out.jobDone);
      await p.screenshot({ path: `${shots}/trip-job-done-light.png`, fullPage: false });
    }
    // home page: Plan a new trip
    const h = await ctx.newPage(); h.on('pageerror', e => errs.push(scheme + ' home: ' + e.message));
    await h.goto(base + '/flights/', { waitUntil: 'networkidle' });
    check(scheme + ': home has the Plan a new trip box', (await h.textContent('#ask .ask-title')) === 'Plan a new trip' && (await h.textContent('#askGo')) === 'Plan');
    await h.fill('#askQ', 'search'); await h.click('#askGo');
    await h.waitForSelector('.ask-prop', { timeout: 15000 });
    check(scheme + ': home shows the proposed search with Start search', /Proposed search/.test(await h.textContent('.ask-prop')) && !!(await h.$('.ask-prop [data-act="start"]')));
    check(scheme + ': home no sideways scroll', await h.evaluate(() => document.scrollingElement.scrollWidth <= innerWidth + 1));
    await h.screenshot({ path: `${shots}/home-plan-${scheme}.png` });
    await ctx.close();
  }
  // a page without TripAPI must still work (filter offered as text only)
  const c2 = await b.newContext({ viewport: { width: 430, height: 900 } }); const q = await c2.newPage();
  q.on('pageerror', e => errs.push('noapi page: ' + e.message));
  await q.goto(base + '/flights/' + slug + '/', { waitUntil: 'networkidle' });
  const hasReal = await q.evaluate(() => !!window.TripAPI);
  await q.fill('#askQ', 'which are cheapest'); await q.click('#askGo'); await q.waitForSelector('.ask-card .ask-a', { timeout: 15000 });
  out.noApi = await q.textContent('.ask-card');
  check('works with or without the real TripAPI (present: ' + hasReal + ')', /Two flights fit/.test(out.noApi), out.noApi);
  await b.close();
  check('no page or console errors', errs.length === 0, errs);
  console.log(fails.length ? fails.length + ' failed' : 'all passed');
  process.exit(fails.length ? 1 : 0);
})();
