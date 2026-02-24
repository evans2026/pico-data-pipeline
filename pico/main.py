# main.py — runs directly on the Pico W
# Reads DHT11 + MPU6050, publishes JSON via MQTT over WiFi
# Flash to Pico W via CLI: mpremote connect /dev/ttyACM0 fs cp pico/main.py :main.py

import network
import time
import json
import math
import machine
import dht
from umqtt.simple import MQTTClient
from mpu6050 import MPU6050  # see lib/mpu6050.py

# Onboard LED — blinks green on each successful publish
led = machine.Pin("LED", machine.Pin.OUT)

# ─────────────────────────────────────────
# CONFIGURATION — edit these values
# ─────────────────────────────────────────
WIFI_SSID     = "YOUR_WIFI_SSID"
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"
MQTT_BROKER   = "192.168.1.XXX"   # your Linux machine's local IP
MQTT_PORT     = 1883
MQTT_TOPIC    = b"sensors/pico1"
DEVICE_ID     = "pico_w_01"
READ_INTERVAL = 5  # seconds between readings

# ─────────────────────────────────────────
# PIN SETUP
# ─────────────────────────────────────────
# DHT11: data pin → GPIO 15
# MPU6050: SDA → GPIO 4, SCL → GPIO 5 (I2C bus 0)

dht_sensor = dht.DHT11(machine.Pin(15))
i2c        = machine.I2C(0, sda=machine.Pin(4), scl=machine.Pin(5), freq=400000)
mpu        = MPU6050(i2c)

# ─────────────────────────────────────────
# WIFI CONNECTION
# ─────────────────────────────────────────
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    print("Connecting to WiFi", end="")
    timeout = 20
    while not wlan.isconnected() and timeout > 0:
        print(".", end="")
        time.sleep(1)
        timeout -= 1
    if wlan.isconnected():
        print(f"\nConnected. IP: {wlan.ifconfig()[0]}")
        return True
    else:
        print("\nWiFi connection failed.")
        return False

# ─────────────────────────────────────────
# MQTT CONNECTION
# ─────────────────────────────────────────
def connect_mqtt():
    client = MQTTClient(
        client_id=DEVICE_ID,
        server=MQTT_BROKER,
        port=MQTT_PORT,
        keepalive=60
    )
    client.connect()
    print(f"Connected to MQTT broker at {MQTT_BROKER}")
    return client

# ─────────────────────────────────────────
# SENSOR READING
# ─────────────────────────────────────────
def read_sensors():
    # DHT11
    try:
        dht_sensor.measure()
        temp_c    = dht_sensor.temperature()
        temp_f    = round((temp_c * 9 / 5) + 32, 2)
        humidity  = dht_sensor.humidity()
    except Exception as e:
        print(f"DHT11 error: {e}")
        temp_f, temp_c, humidity = None, None, None

    # MPU6050
    try:
        accel = mpu.accel
        gyro  = mpu.gyro
        accel_x = round(accel.x, 4)
        accel_y = round(accel.y, 4)
        accel_z = round(accel.z, 4)
        gyro_x  = round(gyro.x, 4)
        gyro_y  = round(gyro.y, 4)
        gyro_z  = round(gyro.z, 4)
        vibration = round(math.sqrt(accel_x**2 + accel_y**2 + accel_z**2), 4)
    except Exception as e:
        print(f"MPU6050 error: {e}")
        accel_x = accel_y = accel_z = None
        gyro_x  = gyro_y  = gyro_z  = None
        vibration = None

    return {
        "device_id":   DEVICE_ID,
        "temp_f":      temp_f,
        "temp_c":      temp_c,
        "humidity":    humidity,
        "accel_x":     accel_x,
        "accel_y":     accel_y,
        "accel_z":     accel_z,
        "gyro_x":      gyro_x,
        "gyro_y":      gyro_y,
        "gyro_z":      gyro_z,
        "vibration":   vibration,
    }

# ─────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────
def main():
    if not connect_wifi():
        return

    client = connect_mqtt()
    print("Starting sensor loop...")

    while True:
        try:
            payload = read_sensors()
            msg     = json.dumps(payload)
            client.publish(MQTT_TOPIC, msg.encode())
            print(f"Published: {msg}")
            # blink LED to confirm successful publish
            led.on()
            time.sleep(0.1)
            led.off()
        except OSError as e:
            # MQTT dropped — attempt reconnect
            print(f"MQTT error: {e}. Reconnecting...")
            try:
                client = connect_mqtt()
            except Exception:
                time.sleep(5)

        time.sleep(READ_INTERVAL)

main()
