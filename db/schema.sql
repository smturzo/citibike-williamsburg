-- Station snapshots, one row per (5-minute bucket, station).
-- PK dedupes the Mac and GitHub Actions collectors against each other.
CREATE TABLE IF NOT EXISTS snapshots (
  ts_bucket      INTEGER NOT NULL,
  station_id     TEXT    NOT NULL,
  bikes          INTEGER NOT NULL,
  ebikes         INTEGER NOT NULL,
  classic        INTEGER NOT NULL,
  docks          INTEGER NOT NULL,
  bikes_disabled INTEGER NOT NULL,
  docks_disabled INTEGER NOT NULL,
  is_renting     INTEGER NOT NULL,
  is_returning   INTEGER NOT NULL,
  last_reported  INTEGER NOT NULL,
  src            TEXT    NOT NULL,
  local_date     TEXT    NOT NULL,  -- YYYY-MM-DD, America/New_York
  dow            INTEGER NOT NULL,  -- 0=Mon .. 6=Sun, local
  mod            INTEGER NOT NULL,  -- minutes since local midnight
  hour_local     TEXT    NOT NULL,  -- YYYY-MM-DDTHH:00, joins to weather
  PRIMARY KEY (ts_bucket, station_id)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS ix_snap_station_dow_mod ON snapshots(station_id, dow, mod);
CREATE INDEX IF NOT EXISTS ix_snap_hour            ON snapshots(hour_local);
CREATE INDEX IF NOT EXISTS ix_snap_date            ON snapshots(local_date);

CREATE TABLE IF NOT EXISTS stations (
  station_id TEXT PRIMARY KEY,
  name       TEXT, short_name TEXT,
  lat REAL, lon REAL, capacity INTEGER, zone TEXT
);

CREATE TABLE IF NOT EXISTS weather (
  hour_local TEXT PRIMARY KEY,
  temp_f REAL, apparent_f REAL, precip_mm REAL, rain_mm REAL, snow_cm REAL,
  wind_kmh REAL, gust_kmh REAL, humidity REAL, cloud_pct REAL, weather_code INTEGER
);

-- Every poll attempt, so gaps are visible as gaps rather than as quiet nights.
CREATE TABLE IF NOT EXISTS coverage (
  ts_bucket INTEGER NOT NULL,
  src       TEXT    NOT NULL,
  ok        INTEGER NOT NULL,
  n_stations INTEGER, feed_last_updated INTEGER, fetch_ms INTEGER, note TEXT,
  PRIMARY KEY (ts_bucket, src)
) WITHOUT ROWID;
