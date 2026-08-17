"""Launcher: run `python3 platform/main.py` to start the lift GUI.

The GUI and its sibling modules (lift_control, charge_sensors) live in
platform/host/ and import each other as top-level modules, so that directory
goes on sys.path before importing.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "host"))

import lift_gui

if __name__ == "__main__":
    lift_gui.main()
