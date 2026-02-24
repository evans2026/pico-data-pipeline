# Pico W Real-Time Sensor Data Pipeline

A complete, end-to-end IoT data pipeline built from first principles — from physical sensor collection on embedded hardware through wireless transmission, ingestion, transformation, anomaly detection, and live visualization.

---

## What This Is

This project implements the same architectural pattern used in production data infrastructure at scale — just at a tangible, physical level. A Raspberry Pi Pico W reads environmental and motion data from two sensors, transmits it over WiFi via MQTT, and a pipeline on a Linux machine ingests, validates, transforms, and surfaces it on a live dashboard.

Every layer has a distinct responsibility. Nothing bleeds into the wrong layer.

---

## Architecture

```
┌─────────────────────┐
│    Pico W (Edge)    │
│  DHT11 + MPU6050    │
│  MicroPython loop   │
│  JSON → MQTT pub    │
└────────┬────────────┘
         │ WiFi / MQTT
         ▼
┌─────────────────────┐
│  Mosquitto Broker   │
│  (message routing)  │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│   subscriber.py     │  ← always running, writes raw records
│   (ingestion)       │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│   raw_sensor_data   │  ← immutable source of truth
│   (SQLite table)    │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│   transform.py      │  ← validation, rolling averages, z-score anomaly detection
│   (transformation)  │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  clean_sensor_data  │  ← validated, enriched, anomaly-flagged
│  (SQLite table)     │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│   Plotly Dash       │  ← live-updating browser dashboard
│   (visualization)   │
└─────────────────────┘
```

### Enterprise Equivalent

| This Project         | At Enterprise Scale              |
|----------------------|----------------------------------|
| Pico W + sensors     | IoT devices / distributed agents |
| MQTT + Mosquitto     | Apache Kafka                     |
| subscriber.py        | Kafka consumer / Flink job       |
| SQLite raw table     | Data lake / S3 raw zone          |
| transform.py         | dbt models                       |
| SQLite clean table   | Data warehouse (Snowflake/BQ)    |
| Plotly Dash          | Grafana / Tableau                |

---

## Sensors & Hardware

| Component         | Role                                              |
|-------------------|---------------------------------------------------|
| Raspberry Pi Pico W | Microcontroller with onboard WiFi               |
| DHT11             | Temperature (°F/°C) and relative humidity (%)    |
| MPU6050           | 3-axis accelerometer + 3-axis gyroscope          |

The MPU6050 reports acceleration in g-force across X, Y, Z axes. A scalar vibration magnitude is computed as `√(x² + y² + z²)`.

---

## Project Structure

```
pico-data-pipeline/
│
├── pico/
│   ├── main.py              # MicroPython — runs on hardware
│   └── lib/
│       └── mpu6050.py       # MPU6050 driver (no external dependency)
│
├── pipeline/
│   ├── subscriber.py        # MQTT listener → raw DB writes
│   ├── transform.py         # Raw → clean: validation, rolling avg, anomaly detection
│   └── db_init.sql          # Schema: raw + clean tables, indexes
│
├── dashboard/
│   └── app.py               # Plotly Dash live dashboard
│
├── config/
│   └── config.yaml          # Local config (NOT committed — see .gitignore)
│
├── docs/
│   └── architecture.png     # Architecture diagram
│
├── requirements.txt
├── .gitignore
└── README.md
```

---

## Setup & Installation

### Prerequisites

- Linux machine (tested on Linux Mint 22.2)
- Python 3.10+
- Mosquitto MQTT broker
- mpremote (for flashing Pico W from CLI)

### 1. Install Mosquitto

```bash
sudo apt update
sudo apt install mosquitto mosquitto-clients
sudo systemctl enable mosquitto
sudo systemctl start mosquitto
```

Verify it's running:
```bash
mosquitto_sub -t "sensors/pico1" -v
```

### 2. Clone & Install Python Dependencies

```bash
git clone https://github.com/YOUR_USERNAME/pico-data-pipeline.git
cd pico-data-pipeline
pip install -r requirements.txt
```

### 3. Configure

```bash
cp config/config.yaml.example config/config.yaml
```

Edit `config/config.yaml` — set your local IP (`hostname -I` to find it).

### 4. Initialize the Database

```bash
mkdir -p data logs
sqlite3 data/pipeline.db < pipeline/db_init.sql
```

### 5. Flash the Pico W

Install mpremote if you haven't:
```bash
pip install mpremote
```

Connect Pico W via USB and verify it's detected:
```bash
mpremote connect list
# should show something like /dev/ttyACM0
```

Edit WiFi credentials and broker IP in `pico/main.py` before copying.

Copy files to the device:
```bash
mpremote connect /dev/ttyACM0 fs mkdir :lib
mpremote connect /dev/ttyACM0 fs cp pico/lib/mpu6050.py :lib/mpu6050.py
mpremote connect /dev/ttyACM0 fs cp pico/main.py :main.py
```

Verify what's on the device:
```bash
mpremote connect /dev/ttyACM0 fs ls
mpremote connect /dev/ttyACM0 fs ls :lib
```

Reset and let main.py autorun:
```bash
mpremote connect /dev/ttyACM0 reset
```

Watch live output:
```bash
mpremote connect /dev/ttyACM0 run pico/main.py
```

### 6. Start the Pipeline

**Terminal 1 — Subscriber (ingestion):**
```bash
python3 pipeline/subscriber.py
```

**Terminal 2 — Transform (runs every 60s):**
```bash
watch -n 60 python3 pipeline/transform.py
```

**Terminal 3 — Dashboard:**
```bash
python3 dashboard/app.py
```

Open `http://localhost:8050` in your browser.

---

## Data Model

### `raw_sensor_data`
Exact mirror of every MQTT payload received. Never modified after insert. This is the source of truth — if transformation logic changes, raw data can be reprocessed with `--backfill`.

### `clean_sensor_data`
Validated, enriched records. Each row links back to its raw source via `raw_id`. Includes:
- Rolling 60-second averages for temperature, humidity, and vibration
- Z-score anomaly flags (threshold: 2.5σ) for each metric
- `is_valid` flag for records that failed range validation

---

## Anomaly Detection

Uses a z-score approach: for each incoming reading, the pipeline computes how many standard deviations it sits from the rolling mean of recent clean data. Readings beyond 2.5σ are flagged and surfaced on the dashboard as red markers.

This is a deliberate, interpretable choice — as opposed to black-box ML — appropriate for a system where explainability matters.

---

## What I'd Do Differently at Scale

1. **Replace SQLite with PostgreSQL** for concurrent write handling and native Grafana integration. The code is database-agnostic; it's a connection string change.
2. **Replace MQTT + subscriber.py with Kafka** for guaranteed delivery, replay, and partitioned consumption across multiple devices.
3. **Replace transform.py with dbt** for version-controlled, tested transformation models with lineage tracking.
4. **Add a dead letter queue** for payloads that fail JSON parsing — currently they're logged and discarded.
5. **Containerize with Docker Compose** so the broker, pipeline, and dashboard spin up together.
6. **Add schema validation** (e.g., Pydantic) at the ingestion layer to catch malformed payloads before they touch the database.

---

## Skills Demonstrated

- Embedded systems / IoT (MicroPython, I2C, MQTT)
- Network protocols and message brokering
- Data pipeline architecture (ingestion → raw → transform → clean)
- Statistical anomaly detection (z-score)
- Relational database design (schema, indexing, foreign keys)
- Python (async patterns, pandas, numpy, Dash/Plotly)
- Data visualization and live dashboards
- Git, documentation, system design thinking

---

## Author

**Evan Sahinovic**  
[evan@sahinovic.org](mailto:evan@sahinovic.org) · [LinkedIn](https://linkedin.com/in/YOUR_PROFILE)
