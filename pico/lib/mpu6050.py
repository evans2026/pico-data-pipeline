# lib/mpu6050.py — lightweight MPU6050 driver for MicroPython
# Place this file in the /lib folder on your Pico W

import struct

class Vector:
    def __init__(self, x, y, z):
        self.x = x
        self.y = y
        self.z = z

    def __repr__(self):
        return f"Vector(x={self.x:.4f}, y={self.y:.4f}, z={self.z:.4f})"


class MPU6050:
    # Register addresses
    PWR_MGMT_1  = 0x6B
    ACCEL_XOUT  = 0x3B
    GYRO_XOUT   = 0x43
    ACCEL_CONFIG = 0x1C
    GYRO_CONFIG  = 0x1B
    WHO_AM_I     = 0x75

    ADDR = 0x68  # default I2C address (AD0 low)

    # Sensitivity scale factors (default ±2g, ±250°/s)
    ACCEL_SCALE = 16384.0   # LSB/g
    GYRO_SCALE  = 131.0     # LSB/°/s

    def __init__(self, i2c, addr=0x68):
        self.i2c  = i2c
        self.addr = addr
        self._wake()

    def _wake(self):
        """Wake the MPU6050 from sleep mode."""
        self.i2c.writeto_mem(self.addr, self.PWR_MGMT_1, b'\x00')

    def _read_raw(self, reg):
        """Read two bytes and return as signed 16-bit int."""
        data = self.i2c.readfrom_mem(self.addr, reg, 2)
        value = struct.unpack('>h', data)[0]
        return value

    @property
    def accel(self):
        """Return acceleration in g-force as a Vector."""
        ax = self._read_raw(self.ACCEL_XOUT)     / self.ACCEL_SCALE
        ay = self._read_raw(self.ACCEL_XOUT + 2) / self.ACCEL_SCALE
        az = self._read_raw(self.ACCEL_XOUT + 4) / self.ACCEL_SCALE
        return Vector(ax, ay, az)

    @property
    def gyro(self):
        """Return gyroscope in degrees/second as a Vector."""
        gx = self._read_raw(self.GYRO_XOUT)     / self.GYRO_SCALE
        gy = self._read_raw(self.GYRO_XOUT + 2) / self.GYRO_SCALE
        gz = self._read_raw(self.GYRO_XOUT + 4) / self.GYRO_SCALE
        return Vector(gx, gy, gz)

    @property
    def temperature(self):
        """Return die temperature in Celsius."""
        raw = self._read_raw(0x41)
        return (raw / 340.0) + 36.53

    def who_am_i(self):
        """Should return 0x68 if sensor is connected correctly."""
        return self.i2c.readfrom_mem(self.addr, self.WHO_AM_I, 1)[0]
