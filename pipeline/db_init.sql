-- db_init.sql
-- Run once to create your schema
-- SQLite: sqlite3 pipeline.db < db_init.sql
-- PostgreSQL: psql -U postgres -d pipeline -f db_init.sql

-- ─────────────────────────────────────────
-- RAW TABLE
-- Exact mirror of what comes off the Pico W
-- Never modified after insert — source of truth
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS raw_sensor_data (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    device_id   TEXT,
    temp_f      REAL,
    temp_c      REAL,
    humidity    REAL,
    accel_x     REAL,
    accel_y     REAL,
    accel_z     REAL,
    gyro_x      REAL,
    gyro_y      REAL,
    gyro_z      REAL,
    vibration   REAL,
    raw_payload TEXT   -- full original JSON string for audit
);

-- ─────────────────────────────────────────
-- CLEAN TABLE
-- Validated, transformed, anomaly-flagged
-- This is what the dashboard reads
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS clean_sensor_data (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_id          INTEGER REFERENCES raw_sensor_data(id),
    processed_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    device_id       TEXT,
    temp_f          REAL,
    temp_c          REAL,
    humidity        REAL,
    accel_x         REAL,
    accel_y         REAL,
    accel_z         REAL,
    gyro_x          REAL,
    gyro_y          REAL,
    gyro_z          REAL,
    vibration       REAL,
    -- rolling averages (60s window)
    temp_avg_60s    REAL,
    humidity_avg_60s REAL,
    vibration_avg_60s REAL,
    -- anomaly flags
    temp_anomaly    INTEGER DEFAULT 0,  -- 1 = flagged
    humidity_anomaly INTEGER DEFAULT 0,
    vibration_anomaly INTEGER DEFAULT 0,
    -- data quality
    is_valid        INTEGER DEFAULT 1   -- 0 = failed validation
);

-- ─────────────────────────────────────────
-- INDEXES for dashboard query performance
-- ─────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_raw_received_at  ON raw_sensor_data(received_at);
CREATE INDEX IF NOT EXISTS idx_clean_processed  ON clean_sensor_data(processed_at);
CREATE INDEX IF NOT EXISTS idx_clean_device     ON clean_sensor_data(device_id);
CREATE INDEX IF NOT EXISTS idx_clean_anomalies  ON clean_sensor_data(temp_anomaly, vibration_anomaly);
