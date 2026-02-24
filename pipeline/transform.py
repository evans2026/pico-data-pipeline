#!/usr/bin/env python3
"""
transform.py
────────────
Reads unprocessed rows from raw_sensor_data, validates them,
computes rolling averages, flags anomalies using z-score method,
and writes clean records to clean_sensor_data.

Runs on a schedule (cron or APScheduler). Can also be run manually.

Usage:
    python3 transform.py              # process all unprocessed raw rows
    python3 transform.py --backfill   # reprocess everything from scratch
"""

import sqlite3
import logging
import argparse
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import yaml

# Ensure logs dir exists before logging is configured
Path("logs").mkdir(exist_ok=True)

# ─────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/transform.log"),
    ]
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────
CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.yaml"

with open(CONFIG_PATH) as f:
    config = yaml.safe_load(f)

DB_PATH = Path(__file__).parent.parent / config["database"]["path"]

# Validation thresholds — adjust to your environment
VALID_RANGES = {
    "temp_f":    (-40, 185),
    "humidity":  (0, 100),
    "vibration": (0, 50),
}

# Z-score threshold for anomaly flagging
ANOMALY_Z_THRESHOLD = 2.5

# Rolling window: how many recent readings to include
ROLLING_WINDOW = 12  # at 5s intervals this is ~60 seconds

# ─────────────────────────────────────────
# DATABASE HELPERS
# ─────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_unprocessed_raw_ids(conn):
    """Return raw IDs that haven't been cleaned yet."""
    cursor = conn.execute("""
        SELECT r.id
        FROM raw_sensor_data r
        LEFT JOIN clean_sensor_data c ON c.raw_id = r.id
        WHERE c.raw_id IS NULL
        ORDER BY r.received_at ASC
    """)
    return [row["id"] for row in cursor.fetchall()]


def get_raw_row(conn, raw_id):
    cursor = conn.execute(
        "SELECT * FROM raw_sensor_data WHERE id = ?", (raw_id,)
    )
    return cursor.fetchone()


def get_recent_clean_values(conn, device_id, field, n=ROLLING_WINDOW):
    """Fetch last N clean values for a field to compute rolling stats."""
    cursor = conn.execute(f"""
        SELECT {field}
        FROM clean_sensor_data
        WHERE device_id = ?
          AND {field} IS NOT NULL
          AND is_valid = 1
        ORDER BY processed_at DESC
        LIMIT ?
    """, (device_id, n))
    return [row[0] for row in cursor.fetchall()]

# ─────────────────────────────────────────
# VALIDATION
# ─────────────────────────────────────────
def validate_row(row):
    """
    Returns (is_valid, issues_list).
    A row is invalid if any critical field is outside expected range.
    """
    issues = []

    for field, (low, high) in VALID_RANGES.items():
        val = row[field]
        if val is None:
            issues.append(f"{field} is NULL")
        elif not (low <= val <= high):
            issues.append(f"{field}={val} outside [{low}, {high}]")

    return len(issues) == 0, issues

# ─────────────────────────────────────────
# ANOMALY DETECTION (Z-SCORE)
# ─────────────────────────────────────────
def is_anomaly(value, historical_values, threshold=ANOMALY_Z_THRESHOLD):
    """
    Z-score anomaly detection.
    Returns True if the value is more than `threshold` std deviations
    from the recent mean. Requires at least 5 data points.
    """
    if value is None or len(historical_values) < 5:
        return False

    arr  = np.array(historical_values, dtype=float)
    mean = np.mean(arr)
    std  = np.std(arr)

    if std == 0:
        return False

    z_score = abs((value - mean) / std)
    return z_score > threshold

# ─────────────────────────────────────────
# ROLLING AVERAGE
# ─────────────────────────────────────────
def rolling_avg(values):
    if not values:
        return None
    return round(float(np.mean(values)), 4)

# ─────────────────────────────────────────
# PROCESS ONE ROW
# ─────────────────────────────────────────
def process_row(conn, raw_id):
    row = get_raw_row(conn, raw_id)
    if not row:
        log.warning(f"Raw ID {raw_id} not found.")
        return

    is_valid, issues = validate_row(row)
    if not is_valid:
        log.warning(f"Raw ID {raw_id} failed validation: {issues}")

    device_id = row["device_id"]

    # Fetch recent history for rolling stats + anomaly detection
    recent_temp      = get_recent_clean_values(conn, device_id, "temp_f")
    recent_humidity  = get_recent_clean_values(conn, device_id, "humidity")
    recent_vibration = get_recent_clean_values(conn, device_id, "vibration")

    # Rolling averages
    temp_avg      = rolling_avg(recent_temp)
    humidity_avg  = rolling_avg(recent_humidity)
    vibration_avg = rolling_avg(recent_vibration)

    # Anomaly flags
    temp_anomaly      = int(is_anomaly(row["temp_f"],   recent_temp))
    humidity_anomaly  = int(is_anomaly(row["humidity"], recent_humidity))
    vibration_anomaly = int(is_anomaly(row["vibration"],recent_vibration))

    if temp_anomaly:
        log.warning(f"ANOMALY: temp_f={row['temp_f']} | device={device_id}")
    if vibration_anomaly:
        log.warning(f"ANOMALY: vibration={row['vibration']} | device={device_id}")

    conn.execute("""
        INSERT INTO clean_sensor_data (
            raw_id, processed_at, device_id,
            temp_f, temp_c, humidity,
            accel_x, accel_y, accel_z,
            gyro_x,  gyro_y,  gyro_z,
            vibration,
            temp_avg_60s, humidity_avg_60s, vibration_avg_60s,
            temp_anomaly, humidity_anomaly, vibration_anomaly,
            is_valid
        ) VALUES (
            ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?,
            ?,
            ?, ?, ?,
            ?, ?, ?,
            ?
        )
    """, (
        raw_id,
        datetime.utcnow().isoformat(),
        device_id,
        row["temp_f"],   row["temp_c"],  row["humidity"],
        row["accel_x"],  row["accel_y"], row["accel_z"],
        row["gyro_x"],   row["gyro_y"],  row["gyro_z"],
        row["vibration"],
        temp_avg, humidity_avg, vibration_avg,
        temp_anomaly, humidity_anomaly, vibration_anomaly,
        int(is_valid),
    ))
    conn.commit()

# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
def main(backfill=False):
    Path("logs").mkdir(exist_ok=True)
    conn = get_db()

    if backfill:
        log.info("Backfill mode: deleting all clean records and reprocessing.")
        conn.execute("DELETE FROM clean_sensor_data")
        conn.commit()

    unprocessed = get_unprocessed_raw_ids(conn)
    log.info(f"Found {len(unprocessed)} unprocessed raw rows.")

    for raw_id in unprocessed:
        try:
            process_row(conn, raw_id)
        except Exception as e:
            log.error(f"Failed to process raw_id={raw_id}: {e}")

    conn.close()
    log.info("Transform complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill", action="store_true",
                        help="Reprocess all raw data from scratch")
    args = parser.parse_args()
    main(backfill=args.backfill)
