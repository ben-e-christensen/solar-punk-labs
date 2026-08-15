"""
I2C charge-sensor readout, run on the Raspberry Pi 5 (sensors ride on the
platform, wired back to the Pi's I2C bus).

The exact sensor part/addresses aren't pinned down yet -- fill in
SENSOR_ADDRS (and the register reads in _read_one) once known. Until then
this module degrades gracefully: read_all() reports each configured address
as unreadable, or an empty dict when none are configured, and the GUI just
shows that state instead of crashing.

Requires smbus2 on the Pi:  pip install smbus2
(Enable I2C via raspi-config if /dev/i2c-1 doesn't exist.)

Quick way to discover addresses once the sensors are wired:
    sudo apt install i2c-tools && i2cdetect -y 1
"""

I2C_BUS = 1  # /dev/i2c-1, the standard GPIO-header I2C bus on the Pi

# TODO: fill in real 7-bit addresses once known, e.g. [0x40, 0x41]
SENSOR_ADDRS = []

try:
    from smbus2 import SMBus
    _SMBUS_AVAILABLE = True
except ImportError:
    _SMBUS_AVAILABLE = False


def _read_one(bus, addr):
    """Read one sensor and return a charge value.

    TODO: replace with the real register map for the actual sensor part.
    The placeholder below just reads a single byte from register 0x00 so the
    wiring/address can be smoke-tested before the real driver is written.
    """
    return bus.read_byte_data(addr, 0x00)


def read_all():
    """Read every configured sensor.

    Returns {label: value} where value is a number, or a string describing
    why it couldn't be read. Empty dict if no addresses are configured.
    """
    readings = {}
    if not SENSOR_ADDRS:
        return readings
    if not _SMBUS_AVAILABLE:
        return {f"0x{a:02x}": "smbus2 not installed" for a in SENSOR_ADDRS}
    try:
        with SMBus(I2C_BUS) as bus:
            for addr in SENSOR_ADDRS:
                label = f"0x{addr:02x}"
                try:
                    readings[label] = _read_one(bus, addr)
                except OSError as e:
                    readings[label] = f"read failed ({e})"
    except (OSError, FileNotFoundError) as e:
        return {f"0x{a:02x}": f"bus unavailable ({e})" for a in SENSOR_ADDRS}
    return readings


if __name__ == "__main__":
    result = read_all()
    if not result:
        print("No sensor addresses configured (edit SENSOR_ADDRS in this file).")
    else:
        for label, value in result.items():
            print(f"{label}: {value}")
