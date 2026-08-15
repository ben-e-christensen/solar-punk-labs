"""
ADS1115 charge readout, run on the Raspberry Pi 5. Two ADS1115 ADCs, one
per electrometer, ride on the platform and wire back to the Pi's I2C bus:

    "roots"          -> ADDR pin to GND  -> 0x48 (the ADS1115 default)
    "grounded_roots" -> ADDR pin to VDD  -> 0x49

If i2cdetect -y 1 shows different addresses once wired, just fix SENSORS
below. Each reading is a single-shot conversion of AIN0 vs GND at the
FSR set by PGA below.

Requires smbus2 on the Pi:  pip install smbus2
(Enable I2C via raspi-config if /dev/i2c-1 doesn't exist.)

Degrades gracefully: read_all() returns an error string per sensor when
smbus2/the bus/a device is missing, so the GUI runs anywhere.
"""

import time

I2C_BUS = 1  # /dev/i2c-1, the standard GPIO-header I2C bus on the Pi

SENSORS = {
    "roots": 0x48,
    "grounded_roots": 0x49,
}

# ADS1115 registers
_REG_CONVERSION = 0x00
_REG_CONFIG = 0x01

# Full-scale range. ±4.096 V covers a 3.3 V-referenced electrometer output
# with headroom; change PGA bits + FSR_VOLTS together if the signal differs.
#   PGA bits (config bits 11:9): 000=±6.144  001=±4.096  010=±2.048
#                                011=±1.024  100=±0.512  101..=±0.256
_PGA_BITS = 0b001
FSR_VOLTS = 4.096

# Common config bits: MUX=100 (AIN0 vs GND), PGA as above, DR=111
# (860 SPS), comparator disabled.
_CONFIG_BASE = (
    (0b100 << 12)
    | (_PGA_BITS << 9)
    | (0b111 << 5)
    | 0b00000011
)
# Single-shot: start bit (OS=1) + MODE=1. Used for one-off reads.
_CONFIG_SINGLE = _CONFIG_BASE | (1 << 15) | (1 << 8)
# Continuous conversion (MODE=0): written once, then the conversion
# register always holds the latest 860 SPS result -- each sample is just
# one register read, which is what makes 100 Hz logging feasible.
_CONFIG_CONTINUOUS = _CONFIG_BASE | (1 << 15)

try:
    from smbus2 import SMBus
    _SMBUS_AVAILABLE = True
except ImportError:
    _SMBUS_AVAILABLE = False


def _swap16(word):
    """SMBus word ops are little-endian; the ADS1115 is big-endian."""
    return ((word & 0xFF) << 8) | (word >> 8)


def _to_volts(raw):
    if raw > 0x7FFF:
        raw -= 0x10000  # two's complement
    return raw * FSR_VOLTS / 32768.0


class ContinuousSampler:
    """High-rate sampling: puts every sensor in continuous-conversion mode
    once, then read() is a single conversion-register read per sensor.

    Usage:
        sampler = ContinuousSampler()
        sampler.start()          # opens the bus, configures the ADCs
        ... sampler.read() ...   # {name: volts | error string}, fast
        sampler.stop()

    Degrades gracefully like read_all(): if the bus or a device is missing,
    start() still succeeds and read() reports the error per sensor.
    """

    def __init__(self):
        self.bus = None
        self.bus_error = None
        self.dead = {}  # name -> error string for sensors that failed config

    def start(self):
        self.dead = {}
        if not _SMBUS_AVAILABLE:
            self.bus_error = "smbus2 not installed"
            return
        try:
            self.bus = SMBus(I2C_BUS)
        except (OSError, FileNotFoundError) as e:
            self.bus_error = f"bus unavailable ({e})"
            return
        for name, addr in SENSORS.items():
            try:
                self.bus.write_word_data(addr, _REG_CONFIG, _swap16(_CONFIG_CONTINUOUS))
            except OSError as e:
                self.dead[name] = f"config failed ({e})"

    @property
    def ok(self):
        """True if at least one sensor is delivering data."""
        return self.bus is not None and len(self.dead) < len(SENSORS)

    def read(self):
        if self.bus is None:
            return {name: self.bus_error for name in SENSORS}
        readings = {}
        for name, addr in SENSORS.items():
            if name in self.dead:
                readings[name] = self.dead[name]
                continue
            try:
                readings[name] = _to_volts(_swap16(self.bus.read_word_data(addr, _REG_CONVERSION)))
            except OSError as e:
                readings[name] = f"read failed ({e})"
        return readings

    def stop(self):
        if self.bus is not None:
            try:
                self.bus.close()
            except OSError:
                pass
            self.bus = None


def _read_one(bus, addr):
    """One single-shot conversion; returns volts (float)."""
    bus.write_word_data(addr, _REG_CONFIG, _swap16(_CONFIG_SINGLE))
    # 860 SPS -> ~1.2 ms conversion; wait with margin, then confirm the OS
    # bit reads 1 (conversion complete).
    for _ in range(10):
        time.sleep(0.002)
        if _swap16(bus.read_word_data(addr, _REG_CONFIG)) & 0x8000:
            break
    return _to_volts(_swap16(bus.read_word_data(addr, _REG_CONVERSION)))


def read_all():
    """Read every sensor. Returns {name: volts | error string}."""
    if not _SMBUS_AVAILABLE:
        return {name: "smbus2 not installed" for name in SENSORS}
    readings = {}
    try:
        with SMBus(I2C_BUS) as bus:
            for name, addr in SENSORS.items():
                try:
                    readings[name] = _read_one(bus, addr)
                except OSError as e:
                    readings[name] = f"read failed ({e})"
    except (OSError, FileNotFoundError) as e:
        return {name: f"bus unavailable ({e})" for name in SENSORS}
    return readings


if __name__ == "__main__":
    for name, value in read_all().items():
        if isinstance(value, float):
            print(f"{name}: {value:.4f} V")
        else:
            print(f"{name}: {value}")
