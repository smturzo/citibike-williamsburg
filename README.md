# Williamsburg Citi Bike

Tracking bike and dock availability across **195 stations / 6,806 docks** in
Williamsburg, Greenpoint, East Williamsburg, and the Manhattan bridge landings —
to answer, at any hour: *where do I actually get a bike, and where can I actually
park one?*

Live dashboard: **`https://<you>.github.io/<repo>/`** (see setup below)

---

## What it does

- Polls the Citi Bike GBFS feed every 5 minutes and records, per station:
  classic bikes, e-bikes, free docks, broken bikes, and service status.
- Backfills hourly weather (temp, precipitation, wind) for the same period.
- Aggregates into a **weekday × time-of-day grid** covering Mon/Wed/Fri/Sat/Sun at
  27 times from 7am through 1am.
- Serves a live dashboard that ranks stations for *"I'm leaving in 5 minutes"* —
  combining what's there right now, which way it's trending, how far you'd walk,
  and how reliable that station usually is at this hour.

## Why two collectors

`collect.py` runs in two places and that is deliberate:

| | spacing | uptime |
|---|---|---|
| **Mac** (launchd) | exactly 5 min | only while awake — lid closed = no data |
| **GitHub Actions** | irregular, 5–20 min | ~24/7 |

They fail in opposite ways, so together they cover the grid far better than
either alone. Each poll writes a uniquely-named shard (`1720-mac.csv`,
`1720-gha.csv`), so the two never touch the same file and duplicate buckets
collapse at DB build time via the `(ts_bucket, station_id)` primary key.

## Layout

```
config/zones.json        bounding boxes defining the tracked area
config/stations.json     resolved station set (generated, committed)
config/local.json        your origin coords — GITIGNORED, never pushed
collect/collect.py       GBFS poll -> data/raw/<date>/<HHMM>-<src>.csv
collect/compact.py       folds finished days into one .csv.gz (~12x smaller)
collect/weather.py       Open-Meteo hourly backfill
collect/resolve_stations.py   rebuild the station set after zone edits
db/station_keys.py       append-only station_id -> small int registry
db/build_db.py           CSVs -> data/citibike.db (idempotent)
analysis/fetch_trips.sh  download + filter a month of the trip archive
analysis/extract_trips.py    ~1GB monthly zip -> trips touching our stations
analysis/build_stats.py  DB -> docs/data/stats.json (the day x time grid)
ops/health.py            coverage report — where and when we went blind
ops/sizecheck.py         storage budget guard (fails the daily run if over)
ops/push_shards.sh       stage shards on the throwaway branch
docs/                    the dashboard (GitHub Pages root)
```

## Storage

Two hard budgets, enforced by `ops/sizecheck.py` in the daily workflow — it exits
nonzero if a 12-month projection breaches either, so drift shows up as a failed
run rather than a surprise a year out.

| | 12-month projection | Budget |
|---|---|---|
| GitHub repo | **416 MB** | 1.0 GB |
| Local disk (incl. SQLite) | **1.09 GB** | 3.0 GB |

Getting there took two decisions worth knowing about:

**Shards never enter `main`'s history.** Git keeps every blob it ever saw, so
committing 288 small CSVs a day costs ~464 MB/year in `main` even though
compaction deletes them the next morning. They're staged on a `data-staging`
branch that is force-reset to an empty orphan commit after each compaction, so
`main` only ever receives the compacted `.csv.gz` (~137 MB/year).

**The snapshots table is 33 bytes/row, down from 291.** Stations are a small int
from `config/station_keys.json` rather than a 19-character GBFS id; `classic` and
`local_date` are derived instead of stored; service flags are bit-packed. The
primary key is ordered `(sid, dow, mod, ts_bucket)` so the day × time query is a
PK range scan, which removed the need for **any** secondary index — those were a
large share of the old row cost. Result: 5.96 GB/year → 0.68 GB/year.

Raw trip zips (~1 GB each) are deleted after extraction and are excluded from the
budget, since they're re-downloadable from S3 at any time.

Raw CSVs are the source of truth; `citibike.db` is derived and gitignored.
CSVs diff, merge, and compress. A SQLite binary does none of those.

## Setup

Everything uses the Python standard library. No pip install.

**1. Local collection**

```bash
zsh ops/install_launchd.sh
```

Installs two agents: a 5-minute collector and a 4:10am rollup. Verify with
`launchctl list | grep citibike`. Remove with `ops/uninstall_launchd.sh`.

**2. GitHub**

Create a **public** repo — public repos get unlimited Actions minutes, and at
8,640 runs/month a private repo would exhaust the 2,000-minute free tier in about
a week. Then:

```bash
git remote add origin git@github.com:<you>/<repo>.git && git push -u origin main
```

In **Settings → Pages**, set source to `main` / `/docs`.
In **Settings → Actions → General**, allow *Read and write permissions* so the
workflows can commit data back.

The `data-staging` branch is created automatically on the first collector run.
Never merge it — it is transient shard storage and gets force-reset daily.

**3. Your origin**

```bash
cp config/local.example.json config/local.json
```

Or just open the dashboard and click the map / hit *Use my location*. Your
coordinates live in `localStorage` and in the gitignored `local.json`; they are
never committed.

## Known gotchas

- **Scheduled workflows auto-disable after 60 days of repo inactivity**, and
  commits from the Actions bot may not reset that timer. GitHub emails a warning
  first. Re-enable from the Actions tab, or push any manual commit every couple of
  months.
- **Actions cron is best-effort.** `*/5` is a request, not a guarantee. Check
  real capture rate with `python3 ops/health.py` rather than assuming.
- **A sleeping Mac and a quiet night look identical in the raw data.** That is
  what the `coverage` table and `ops/health.py` exist to prevent — always read
  coverage before drawing a conclusion about a time slot.

## Daily use

```bash
python3 ops/health.py
```

```bash
python3 db/build_db.py && python3 analysis/build_stats.py
```

## Status

Collection infrastructure is complete and verified end-to-end. The day × time
grid needs roughly **4 weeks** before slots have enough observations to be
meaningful — until then the dashboard says so explicitly rather than showing
confident numbers off three samples.

**Trip archive analysis is done** — 4,248,619 rides across Aug 2025 and May–Jul
2026, ~21% of all NYC Citi Bike traffic. Findings are written up in
`docs/report.html` (also served at `/report.html` on Pages). Headlines:

- The weekday peak is **18:00**, not the 16:30–17:30 window the time grid
  over-samples.
- E-bikes are **72–77%** of all rides — the default, not the scarce upgrade.
- Accumulated daily flow, not per-window net flow, is what empties a rack:
  five of the six deepest drains are in the Lower East Side, three of the six
  deepest pile-ups are in Williamsburg proper.
- **N 6 St & Bedford Ave** absorbs a net 26 bikes by 20:45 into 28 docks — 93%
  of its capacity. Worst dock-hunt station in the set.

Rebuild with `python3 analysis/analyze_trips.py`.

Not yet built: the trip-archive *analysis* itself, weather-effect analysis (needs
enough rainy days to contrast against dry ones), and predictive modelling.
