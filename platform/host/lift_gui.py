"""
Simple GUI for the Z-lift platform, run on the Raspberry Pi 5.

Buttons for RAISE / LOWER / STOP / STATUS send the same commands as
lift_control.py over USB serial to the BTT Pico. Also includes a
"Reset Board" button: if the board ever gets left sitting in MicroPython's
raw REPL (e.g. after using mpremote for debugging), main.py stops running
and RAISE/LOWER/STOP/STATUS silently do nothing. Reset Board forces it back
to friendly REPL and soft-resets it, which reliably gets main.py running
again.

Usage:
    python3 lift_gui.py
"""

import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

import serial

import charge_sensors
import lift_control

POLL_STATUS_SECONDS = 5
POLL_SENSORS_MS = 500  # sensor readout rate while the platform is moving


class LiftGUI:
    def __init__(self, root):
        self.root = root
        root.title("Z-Lift Control")

        self.result_queue = queue.Queue()
        self.busy = False
        self.moving = False  # a RAISE/LOWER is in flight (charge data is live)
        self.sensor_read_inflight = False

        main = ttk.Frame(root, padding=12)
        main.grid(sticky="nsew")

        self.status_var = tk.StringVar(value="Status: unknown")
        ttk.Label(main, textvariable=self.status_var, font=("", 12, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 10)
        )

        self.raise_btn = ttk.Button(main, text="RAISE", command=lambda: self.run_command("RAISE"))
        self.raise_btn.grid(row=1, column=0, sticky="ew", padx=2, pady=2)

        self.lower_btn = ttk.Button(main, text="LOWER", command=lambda: self.run_command("LOWER"))
        self.lower_btn.grid(row=1, column=1, sticky="ew", padx=2, pady=2)

        self.stop_btn = ttk.Button(main, text="STOP", command=self.stop_pressed)
        self.stop_btn.grid(row=2, column=0, sticky="ew", padx=2, pady=2)

        self.status_btn = ttk.Button(main, text="STATUS", command=lambda: self.run_command("STATUS"))
        self.status_btn.grid(row=2, column=1, sticky="ew", padx=2, pady=2)

        ttk.Separator(main).grid(row=3, column=0, columnspan=2, sticky="ew", pady=8)

        ttk.Label(main, text="Jog (10 steps, ignores endstops -- for checking DIR polarity)").grid(
            row=4, column=0, columnspan=2, sticky="w"
        )

        self.jog_a_up_btn = ttk.Button(main, text="A ▲", command=lambda: self.run_command("JOG_A_UP"))
        self.jog_a_up_btn.grid(row=5, column=0, sticky="ew", padx=2, pady=2)
        self.jog_a_down_btn = ttk.Button(main, text="A ▼", command=lambda: self.run_command("JOG_A_DOWN"))
        self.jog_a_down_btn.grid(row=6, column=0, sticky="ew", padx=2, pady=2)
        self.jog_b_up_btn = ttk.Button(main, text="B ▲", command=lambda: self.run_command("JOG_B_UP"))
        self.jog_b_up_btn.grid(row=5, column=1, sticky="ew", padx=2, pady=2)
        self.jog_b_down_btn = ttk.Button(main, text="B ▼", command=lambda: self.run_command("JOG_B_DOWN"))
        self.jog_b_down_btn.grid(row=6, column=1, sticky="ew", padx=2, pady=2)

        ttk.Separator(main).grid(row=7, column=0, columnspan=2, sticky="ew", pady=8)

        ttk.Label(main, text="Charge sensors (live only while platform is moving)").grid(
            row=8, column=0, columnspan=2, sticky="w"
        )
        self.sensor_var = tk.StringVar(value="platform idle")
        ttk.Label(main, textvariable=self.sensor_var, font=("Courier", 11)).grid(
            row=9, column=0, columnspan=2, sticky="w", padx=2, pady=(0, 4)
        )

        ttk.Separator(main).grid(row=10, column=0, columnspan=2, sticky="ew", pady=8)

        self.reset_btn = ttk.Button(main, text="Reset Board (fix stuck/unresponsive)", command=self.reset_board)
        self.reset_btn.grid(row=11, column=0, columnspan=2, sticky="ew", padx=2, pady=2)

        self.log = tk.Text(main, width=50, height=14, state="disabled")
        self.log.grid(row=12, column=0, columnspan=2, sticky="nsew", pady=(10, 0))

        # STOP is intentionally NOT in this list: it must stay clickable
        # while a RAISE/LOWER is in flight, or it can't abort anything.
        self.buttons = [
            self.raise_btn,
            self.lower_btn,
            self.status_btn,
            self.jog_a_up_btn,
            self.jog_a_down_btn,
            self.jog_b_up_btn,
            self.jog_b_down_btn,
            self.reset_btn,
        ]

        self.root.after(200, self.poll_queue)
        self.root.after(1000, self.auto_status)
        self.root.after(POLL_SENSORS_MS, self.poll_sensors)

    def log_line(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", f"{time.strftime('%H:%M:%S')}  {text}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def set_busy(self, busy):
        self.busy = busy
        state = "disabled" if busy else "normal"
        for b in self.buttons:
            b.configure(state=state)

    def run_command(self, command):
        if self.busy:
            return
        self.set_busy(True)
        if command in ("RAISE", "LOWER"):
            self.moving = True
        self.log_line(f"> {command}")

        def worker():
            try:
                reply = lift_control.send_command(command)
            except serial.SerialException as e:
                reply = f"ERROR CONNECTION: {e}"
            self.result_queue.put((command, reply))

        threading.Thread(target=worker, daemon=True).start()

    def stop_pressed(self):
        if not self.moving:
            self.run_command("STOP")
            return
        # A RAISE/LOWER worker is blocked holding a serial read for its
        # reply. Send STOP write-only on a second handle (Linux allows the
        # port to be opened twice); the firmware picks it up mid-motion and
        # the in-flight worker receives the "OK STOPPED" reply as usual.
        self.log_line("> STOP (mid-motion)")

        def worker():
            try:
                with serial.Serial(lift_control.PORT, lift_control.BAUD, timeout=2) as ser:
                    ser.write(b"STOP\n")
            except serial.SerialException as e:
                self.result_queue.put(("STOP", f"ERROR CONNECTION: {e}"))

        threading.Thread(target=worker, daemon=True).start()

    def poll_sensors(self):
        if self.moving and not self.sensor_read_inflight:
            self.sensor_read_inflight = True

            def worker():
                readings = charge_sensors.read_all()
                if not readings:
                    text = "moving -- no sensor addresses configured"
                else:
                    text = "   ".join(f"{k}: {v}" for k, v in readings.items())
                # tkinter StringVar.set from a thread is tolerated, but route
                # through `after` to stay on the main loop properly.
                self.root.after(0, self.sensor_var.set, text)
                self.sensor_read_inflight = False

            threading.Thread(target=worker, daemon=True).start()
        elif not self.moving:
            self.sensor_var.set("platform idle")
        self.root.after(POLL_SENSORS_MS, self.poll_sensors)

    def reset_board(self):
        if self.busy:
            return
        self.set_busy(True)
        self.log_line("> RESET BOARD")

        def worker():
            try:
                with serial.Serial(lift_control.PORT, lift_control.BAUD, timeout=2) as ser:
                    ser.reset_input_buffer()
                    ser.write(b"\x02")  # Ctrl-B: exit raw REPL -> friendly REPL
                    time.sleep(0.3)
                    ser.write(b"\x04")  # Ctrl-D: soft reset from friendly REPL -> runs main.py
                    time.sleep(1.0)
                    out = ser.read(500).decode(errors="replace")
                if "READY" in out:
                    reply = "OK REBOOTED"
                else:
                    reply = f"UNCERTAIN, raw output: {out!r}"
            except serial.SerialException as e:
                reply = f"ERROR CONNECTION: {e}"
            self.result_queue.put(("RESET", reply))

        threading.Thread(target=worker, daemon=True).start()

    def auto_status(self):
        if not self.busy:
            self.run_command("STATUS")
        self.root.after(POLL_STATUS_SECONDS * 1000, self.auto_status)

    def poll_queue(self):
        try:
            while True:
                command, reply = self.result_queue.get_nowait()
                self.log_line(f"< {reply}")
                if command in ("RAISE", "LOWER"):
                    self.moving = False
                if command in ("STATUS", "RAISE", "LOWER"):
                    if "HOMED" in reply and "NOT_HOMED" not in reply:
                        self.status_var.set("Status: HOMED")
                    elif "NOT_HOMED" in reply:
                        self.status_var.set("Status: NOT HOMED")
                    elif reply.startswith("ERROR CONNECTION"):
                        self.status_var.set("Status: board not responding")
                self.set_busy(False)
        except queue.Empty:
            pass
        self.root.after(200, self.poll_queue)


def main():
    root = tk.Tk()
    LiftGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
