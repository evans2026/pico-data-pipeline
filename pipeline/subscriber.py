#!/usr/bin/env python3
"""
subscriber.py
─────────────
Subscribes to MQTT topic, receives Pico W sensor payloads,
writes raw records to SQLite. Runs continuously as a background process.

Usage:
    python3 subscriber.py
    # or as a service: see setup instructions in README
"""

import json
import sqlite3
import logging
import signal
import sys
from datetime import datetime
from pathlib import Path

import paho.mqtt.client as mqtt
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
        logging.FileHandler("logs/subscriber.log"),
    ]
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────
CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.yaml"

with open(CONFIG_PATH) as f:
    config = yaml.safe_load(f)

MQTT_BROKER = config["mqtt"]["broker"]
MQTT_PORT   = config["mqtt"]["port"]
MQTT_TOPIC  = config["mqtt"]["topic"]
DB_PATH     = Path(__file__).parent.parent / config["database"]["path"]

# ─────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def insert_raw(payload: dict, raw_json: str):
    """Write one sensor reading to raw_sensor_data."""
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO raw_sensor_data (
                received_at, device_id,
                temp_f, temp_c, humidity,
                accel_x, accel_y, accel_z,
                gyro_x,  gyro_y,  gyro_z,
                vibration, raw_payload
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
        """, (
            datetime.utcnow().isoformat(),
            payload.get("device_id"),
            payload.get("temp_f"),
            payload.get("temp_c"),
            payload.get("humidity"),
            payload.get("accel_x"),
            payload.get("accel_y"),
            payload.get("accel_z"),
            payload.get("gyro_x"),
            payload.get("gyro_y"),
            payload.get("gyro_z"),
            payload.get("vibration"),
            raw_json,
        ))
        conn.commit()
        log.info(f"Inserted raw record | device={payload.get('device_id')} "
                 f"temp={payload.get('temp_f')}°F "
                 f"humidity={payload.get('humidity')}% "
                 f"vibration={payload.get('vibration')}")
    except sqlite3.Error as e:
        log.error(f"DB insert failed: {e}")
    finally:
        conn.close()

# ─────────────────────────────────────────
# MQTT CALLBACKS
# ─────────────────────────────────────────
def on_connect(client, userdata, flags, reason_code, properties=None):
    # compatible with paho-mqtt v1 (rc) and v2 (reason_code)
    rc = reason_code if isinstance(reason_code, int) else reason_code.value
    if rc == 0:
        log.info(f"Connected to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}")
        client.subscribe(MQTT_TOPIC)
        log.info(f"Subscribed to topic: {MQTT_TOPIC}")
    else:
        log.error(f"MQTT connection failed with code {rc}")


def on_message(client, userdata, msg):
    raw_json = msg.payload.decode("utf-8")
    log.debug(f"Received: {raw_json}")
    try:
        payload = json.loads(raw_json)
        insert_raw(payload, raw_json)
    except json.JSONDecodeError as e:
        log.error(f"JSON parse error: {e} | raw: {raw_json}")


def on_disconnect(client, userdata, rc):
    if rc != 0:
        log.warning(f"Unexpected MQTT disconnect (rc={rc}). Will auto-reconnect.")

# ─────────────────────────────────────────
# GRACEFUL SHUTDOWN
# ─────────────────────────────────────────
def handle_shutdown(sig, frame):
    log.info("Shutting down subscriber...")
    sys.exit(0)

signal.signal(signal.SIGINT,  handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)

# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
def main():
    # Ensure logs directory exists
    Path("logs").mkdir(exist_ok=True)

    # paho-mqtt v2 requires explicit callback_api_version
    try:
        from paho.mqtt.client import CallbackAPIVersion
        client = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id="linux_subscriber",
            clean_session=True
        )
    except ImportError:
        # paho-mqtt v1 fallback
        client = mqtt.Client(client_id="linux_subscriber", clean_session=True)
    client.on_connect    = on_connect
    client.on_message    = on_message
    client.on_disconnect = on_disconnect

    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    log.info("Subscriber running. Waiting for messages...")
    client.loop_forever()


if __name__ == "__main__":
    main()
