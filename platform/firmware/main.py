"""
MicroPython firmware for the BTT Pico. Copy this file onto the board's
filesystem as main.py (e.g. via Thonny or mpremote) so it runs on boot.

Listens for line-delimited commands over USB serial (stdin/stdout):
    RAISE   - home both motors independently against their top endstops
    LOWER   - move both motors down a fixed step count from the homed zero
    STOP    - abort whatever RAISE/LOWER is in progress
    STATUS  - report homed state and current position

Two motors ("A"/"B"), each with its own STEP/DIR/EN output and its own
top endstop input, matching the independent-homing strategy in CLAUDE.md.
"""

from machine import Pin
import sys
import select
import utime

# ---------------------------------------------------------------------------
# PIN CONFIG - VERIFY AGAINST YOUR BTT PICO'S PINOUT DIAGRAM BEFORE RUNNING.
# These are placeholders; the values below are almost certainly wrong for
# your board revision. Wrong pins just won't work (no damage risk on RP2040
# GPIO), but confirm before wiring expectations against this code.
# ---------------------------------------------------------------------------
STEP_A_PIN = 11
DIR_A_PIN = 10
EN_A_PIN = 12
ENDSTOP_A_PIN = 4

STEP_B_PIN = 6
DIR_B_PIN = 5
EN_B_PIN = 7
ENDSTOP_B_PIN = 3

# Enable pins on TMC2209-based boards are typically active-low (0 = driver
# enabled). Flip if your board is the opposite.
ENABLE_ACTIVE_LOW = True

# Which DIR pin level moves the motor "up" (toward its endstop). Unknown
# until tested -- flip either constant if a motor moves the wrong way.
DIR_UP_A = 1
DIR_UP_B = 1

# Endstops are active-high per CLAUDE.md (low = untriggered, high =
# triggered), so use a pull-down to keep the input defined when idle.
ENDSTOP_TRIGGERED_VALUE = 1

# ---------------------------------------------------------------------------
# MOTION CONFIG - tune once the mechanism is running.
# ---------------------------------------------------------------------------
STEP_PULSE_US = 800          # time high and time low per step (speed knob)
HOMING_TIMEOUT_STEPS = 200000  # safety cutoff if an endstop never triggers
LOWER_STEPS = 20000          # distance from top (homed zero) to bottom

# ---------------------------------------------------------------------------

step_a = Pin(STEP_A_PIN, Pin.OUT)
dir_a = Pin(DIR_A_PIN, Pin.OUT)
en_a = Pin(EN_A_PIN, Pin.OUT)
endstop_a = Pin(ENDSTOP_A_PIN, Pin.IN, Pin.PULL_DOWN)

step_b = Pin(STEP_B_PIN, Pin.OUT)
dir_b = Pin(DIR_B_PIN, Pin.OUT)
en_b = Pin(EN_B_PIN, Pin.OUT)
endstop_b = Pin(ENDSTOP_B_PIN, Pin.IN, Pin.PULL_DOWN)

homed = False
stop_requested = False

poller = select.poll()
poller.register(sys.stdin, select.POLLIN)


def drivers_enable():
    en_a.value(0 if ENABLE_ACTIVE_LOW else 1)
    en_b.value(0 if ENABLE_ACTIVE_LOW else 1)


def drivers_disable():
    en_a.value(1 if ENABLE_ACTIVE_LOW else 0)
    en_b.value(1 if ENABLE_ACTIVE_LOW else 0)


def check_stop_requested():
    """Non-blocking check for an incoming STOP command mid-motion."""
    global stop_requested
    if poller.poll(0):
        line = sys.stdin.readline().strip().upper()
        if line == "STOP":
            stop_requested = True
    return stop_requested


def step_once(step_pin):
    step_pin.value(1)
    utime.sleep_us(STEP_PULSE_US)
    step_pin.value(0)
    utime.sleep_us(STEP_PULSE_US)


def home_motor(step_pin, dir_pin, endstop_pin, dir_up):
    """Step one motor upward until its endstop triggers. Independent per
    motor by design, so drift between the two screws is corrected every
    homing cycle regardless of skipped steps."""
    dir_pin.value(dir_up)
    for _ in range(HOMING_TIMEOUT_STEPS):
        if check_stop_requested():
            return False
        if endstop_pin.value() == ENDSTOP_TRIGGERED_VALUE:
            return True
        step_once(step_pin)
    return False  # timed out without triggering - treat as failure


def lower_both(steps, dir_up_a, dir_up_b):
    """Step both motors downward together for a fixed count."""
    dir_a.value(0 if dir_up_a else 1)
    dir_b.value(0 if dir_up_b else 1)
    for _ in range(steps):
        if check_stop_requested():
            return False
        step_once(step_a)
        step_once(step_b)
    return True


def cmd_raise():
    global homed, stop_requested
    stop_requested = False
    drivers_enable()
    ok_a = home_motor(step_a, dir_a, endstop_a, DIR_UP_A)
    ok_b = False
    if ok_a:
        ok_b = home_motor(step_b, dir_b, endstop_b, DIR_UP_B)
    if ok_a and ok_b:
        homed = True
        print("OK RAISED")
    elif stop_requested:
        homed = False
        print("OK STOPPED")
    else:
        homed = False
        print("ERROR HOMING_FAILED")


def cmd_lower():
    global stop_requested
    if not homed:
        print("ERROR NOT_HOMED")
        return
    stop_requested = False
    drivers_enable()
    completed = lower_both(LOWER_STEPS, not DIR_UP_A, not DIR_UP_B)
    if completed:
        print("OK LOWERED")
    elif stop_requested:
        print("OK STOPPED")
    else:
        print("ERROR LOWER_FAILED")


def cmd_status():
    print("HOMED" if homed else "NOT_HOMED")


def main():
    print("READY")
    while True:
        line = sys.stdin.readline()
        if not line:
            continue
        cmd = line.strip().upper()
        if cmd == "RAISE":
            cmd_raise()
        elif cmd == "LOWER":
            cmd_lower()
        elif cmd == "STOP":
            print("OK IDLE")  # nothing running; STOP mid-motion is handled inline
        elif cmd == "STATUS":
            cmd_status()
        elif cmd == "":
            continue
        else:
            print("ERROR UNKNOWN_COMMAND")


main()
