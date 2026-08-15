"""
Host-side control script, run on the Raspberry Pi 5.

Talks to the BTT Pico over USB serial (the BTT Pico enumerates as a USB CDC
device, typically /dev/ttyACM0). Requires pyserial: pip install pyserial

Usage:
    python3 lift_control.py raise
    python3 lift_control.py lower
    python3 lift_control.py stop
    python3 lift_control.py status
"""

import sys
import serial

PORT = "/dev/ttyACM0"
BAUD = 115200
TIMEOUT_S = 180  # RAISE/LOWER block until the BTT Pico finishes moving; a
# full-travel RAISE at 800us pulses is ~80s, so 60s silently timed out and
# left the reply in the buffer to desync the next command.


def send_command(command):
    with serial.Serial(PORT, BAUD, timeout=TIMEOUT_S) as ser:
        ser.write((command + "\n").encode())
        reply = ser.readline().decode().strip()
        return reply


def main():
    if len(sys.argv) != 2 or sys.argv[1].upper() not in ("RAISE", "LOWER", "STOP", "STATUS"):
        print(f"Usage: {sys.argv[0]} raise|lower|stop|status")
        sys.exit(1)

    command = sys.argv[1].upper()
    reply = send_command(command)
    print(reply)
    if reply.startswith("ERROR"):
        sys.exit(1)


if __name__ == "__main__":
    main()
