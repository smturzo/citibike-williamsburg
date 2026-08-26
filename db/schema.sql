-- Schema v2. Tuned for size: at ~20M rows/year, every byte per row is ~20MB.
--
-- Choices that matter:
--   * `sid` is a small int from config/station_keys.json, not the 19-char GBFS id.
--   * The PK is ordered (sid, dow, mod, ts_bucket) so the day x time grid query
--     is a primary-key range scan. That removes the need for ANY secondary index
--     on this table - secondary indexes on a WITHOUT ROWID table duplicate the
--     whole PK per entry and were a large share of the old row cost.
--   * Derived values are not stored: `classic` = bikes - ebikes, and local_date
--     = hour_key / 100. Cheap to compute, expensive to store 20M times.
--   * is_renting/is_returning are packed into `flags`; last_reported is kept as
--     `stale_s`, a small offset from ts_bucket rather than a full epoch.

CREATE TABLE IF NOT EXISTS snapshots (
  sid            INTEGER NOT NULL,
  dow            INTEGER NOT NULL,  -- 0=Mon .. 6=Sun, local
  mod            INTEGER NOT NULL,  -- minutes since local midnight
  ts_bucket      INTEGER NOT NULL,  -- epoch, floored to 5 min
  bikes          INTEGER NOT NULL,
  ebikes         INTEGER NOT NULL,
  docks          INTEGER NOT NULL,
  bikes_disabled INTEGER NOT NULL,
  docks_disabled INTEGER NOT NULL,
  flags          INTEGER NOT NULL,  -- bit0 = is_renting, bit1 = is_returning
  stale_s        INTEGER NOT NULL,  -- ts_bucket - last_reported
  hour_key       INTEGER NOT NULL,  -- YYYYMMDDHH, joins to weather
  PRIMARY KEY (sid, dow, mod, ts_bucket)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS stations (
  sid        INTEGER PRIMARY KEY,
  station_id TEXT UNIQUE,
  name       TEXT, short_name TEXT,
  lat REAL, lon REAL, capacity INTEGER, zone TEXT
);

CREATE TABLE IF NOT EXISTS weather (
  hour_key   INTEGER PRIMARY KEY,   -- YYYYMMDDHH
  temp_f REAL, apparent_f REAL, precip_mm REAL, rain_mm REAL, snow_cm REAL,
  wind_kmh REAL, gust_kmh REAL, humidity REAL, cloud_pct REAL, weather_code INTEGER
);

-- One row per poll attempt. Small (2 rows per bucket at most), and it carries the
-- day/hour coverage picture so snapshots needs no date index of its own.
CREATE TABLE IF NOT EXISTS coverage (
  ts_bucket INTEGER NOT NULL,
  src       TEXT    NOT NULL,
  ok        INTEGER NOT NULL,
  n_stations INTEGER, feed_last_updated INTEGER, fetch_ms INTEGER, note TEXT,
  local_date TEXT, mod INTEGER,
  PRIMARY KEY (ts_bucket, src)
) WITHOUT ROWID;
