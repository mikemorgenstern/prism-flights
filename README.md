<!-- ai-suggestion:unverified | session:8e680ddd-6b26-44d7-8b07-e667fe163a25 | date:2026-11-23 -->
# Prism

A personal flights portal. The home page shows your airline miles and points balances and your travel credits with
their expiry dates. Each saved flight search gets its own page, where every flight shows its cash price and its award
price in each program side by side, with filters, likes, hides, a "cash after your credits" view and booking links.

Pages are plain, self-contained HTML built from JSON files. A small Python server (standard library only) serves them
and stores likes and hides, credit-check requests, questions for the Ask box, and optional search jobs.

## Try it with the made-up sample

Needs Python 3 (standard library only). Everything in `examples/` is invented.

```sh
python3 tools/make_sample.py
FLIGHTS_DATA=examples FLIGHTS_SITE=sample-site python3 src/build_portal.py
FLIGHTS_SITE=sample-site FLIGHTS_STATE=sample-state python3 src/service.py
```

Then open http://127.0.0.1:8873/flights/ for the home page and http://127.0.0.1:8873/flights/27-03-12-boston/ for
the sample trip.

## What is here

| Path | What it does |
|---|---|
| `src/build_portal.py` | Builds `site/index.html` (home) and `site/<trip>/index.html` from `data/` |
| `src/service.py` | Serves the pages under `/flights` plus a small JSON API (likes, hides, check requests, Ask, jobs) |
| `src/ui/` | Page templates, styles and scripts |
| `src/credits.py` | Balance and credit history, optional booking-email check, check requests |
| `src/ask_helper.py` | Answers a question about the flights on a page with the `claude` command line tool |
| `src/jobs_start.py`, `src/jobs_mac.py`, `src/jobs_report.py` | Optional search jobs: a click on the page starts a Claude Code session on a Mac that searches with a signed-in browser and reports progress back |
| `src/gflights.py` | Builds Google Flights search and booking links |
| `src/gf_to_rows.py` | Turns saved Google Flights results into raw rows for `pipeline/merge.py` |
| `pipeline/merge.py`, `pipeline/build_rows.py` | Merge raw cash and award results into one list per trip, then write the page rows |
| `pipeline/nws.py` | National Weather Service forecasts for connection airports |
| `tools/make_sample.py` | Writes the made-up `examples/` data |
| `deploy.sh` | Builds the pages and copies them to a server (settings below) |

The scripts that read airline websites to produce raw search files are not included. Raw files can come from any
source; their formats are described at the top of `pipeline/merge.py`.

## Your own data

Put it in `data/` (ignored by git), laid out like `examples/`:

- `data/credits/wallet.json`: programs (airline, program, unit, balance) and credits (airline, what, amount, use-by date;
  `"useBy": null` for a credit with no end date, drawn in a "No end date" column at the end of the expiry timeline).
  Any program gets a balance pill, not only the five airlines: Chase, Amex, Citi, Capital One and Bilt have short keys,
  other names get one made from the name; add a cents value for the key in `src/point_values.json` to show a worth
- `data/credits/tracking.json` and `flags.json`: which airlines are tracked, and credits marked "maybe used"
- `data/searches/<YY-MM-DD-name>/trip.json`: the trip (dates, airports, notes), plus `page-rows.json` from the
  pipeline, and optionally `weather/nws.json` and one folder per extra origin airport

To make page rows from raw search files, run the pipeline inside the search folder:

```sh
cd data/searches/<trip>
python3 ../../../pipeline/merge.py        # raw files -> itineraries.json
python3 ../../../pipeline/build_rows.py   # itineraries.json -> page-rows.json
python3 ../../../pipeline/nws.py 2027-03-12,2027-03-13 ORD,DEN   # optional weather
```

Then `python3 src/build_portal.py` builds the pages into `site/`.

## Settings

Copy `config.example.json` to `config.local.json` (ignored by git) and fill in only what you use. With no settings
file the portal still builds and serves pages; the email check, notes snapshots, `deploy.sh` and search jobs are off.

The server has no login. Run it behind a reverse proxy on a private network, never on the open internet.

The Ask box and search jobs call the `claude` command line tool (Claude Code) with your own login. Search jobs only
search: their instructions forbid booking, paying, signing in and sending anything.

## Tests

```sh
python3 src/tests/ask_jobs_test.py
```

The browser tests need `playwright-core` (set `PLAYWRIGHT_CORE` to its folder if it is not installed where Node finds
it) and Chrome. Run them only against a local server with a scratch `FLIGHTS_STATE`, since they click likes and submit
requests:

```sh
node src/tests/portal_test.js http://127.0.0.1:8873 <screenshot folder> [trip]
python3 src/tests/ask_jobs_test.py --write-stubs stubs
FLIGHTS_SITE=sample-site FLIGHTS_STATE=sample-state FLIGHTS_ASK_CMD="python3 stubs/stub_ask.py" \
  FLIGHTS_JOB_CMD="python3 stubs/stub_job.py" STUB_JOB_LOG=stubs/jobs.log python3 src/service.py &
node src/tests/ask_ui_test.js http://127.0.0.1:8873 <screenshot folder> stubs/jobs.log
```

## Publishing checks

`tools/check_public.sh` is the maintainer's check that nothing private is about to be published. It compares the
files and the full git history against a private list kept outside the repo, so without that list it refuses to pass.
To run it on every commit and push in your clone: `git config core.hooksPath tools/hooks`.

## Credits

- The logo and header art are original drawings made for Prism.
- Point values in `src/point_values.json` are published averages; the source is named in that file.
- Written with Claude Code.

## License

MIT; see `LICENSE`.

---
_Claude · 2026-11-23 · Session: 8e680ddd-6b26-44d7-8b07-e667fe163a25_
