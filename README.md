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
db/build_db.py           CSVs -> data/citibike.db (idempotent)
analysis/build_stats.py  DB -> docs/data/stats.json (the day x time grid)
ops/health.py            coverage report — where and when we went blind
docs/                    the dashboard (GitHub Pages root)
```

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

Not yet built: historical trip-archive analysis (available immediately, no wait),
weather-effect analysis (needs enough rainy days), and predictive modelling.
