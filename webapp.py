"""Local control panel for the French cash reconciliation.

A small Flask app that drives recon.py:

  * Settings — the €150 till-float floor, the gap threshold, whether a gap must
    be explained before writing, and the Zelty source mode (mock for now).
  * Populate — pull each site's cash for a chosen day (mock/demo data today,
    real Zelty later), carry the till float forward (floored at €150), and let
    you type the counted cash per site.
  * Gaps — as you enter counted cash, the gap (Zelty − counted) shows live; any
    nonzero gap must be explained before the row is written.
  * Write — append the day to every site's sheet in the workbook (formulas kept
    live, a .bak backup taken first).

Run:
    .venv/Scripts/python webapp.py         # then open http://127.0.0.1:5000
"""

from __future__ import annotations

import atexit
import datetime as dt
import json
import os
import signal
import subprocess
from pathlib import Path

from flask import Flask, jsonify, render_template, request

import recon
import zelty_source

app = Flask(__name__)

HOST = "127.0.0.1"
PORT = 5000


def _pids_on_port(port: int) -> set[int]:
    """PIDs of processes LISTENING on `port` (Windows netstat)."""
    pids: set[int] = set()
    try:
        out = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True, text=True,
        ).stdout
    except OSError:
        return pids
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" \
                and parts[3].upper() == "LISTENING" \
                and parts[1].endswith(f":{port}") and parts[4].isdigit():
            pids.add(int(parts[4]))
    return pids


def free_port(port: int) -> None:
    """Kill anything (other than us) still holding `port`."""
    for pid in _pids_on_port(port):
        if pid == os.getpid():
            continue
        try:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True)
        except OSError:
            pass

SETTINGS_PATH = Path(__file__).with_name("settings.json")
DEFAULT_SETTINGS = {
    "min_float": 150.0,            # €150 legal floor on the till float
    "gap_threshold": 0.01,         # |gap| below this needs no explanation
    "require_gap_explanation": True,
    "zelty_mode": "manual",        # "manual" (read sheet / type in) | "api" (live, once keyed)
}


def load_settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    if SETTINGS_PATH.exists():
        try:
            s.update(json.loads(SETTINGS_PATH.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    return s


def save_settings(s: dict) -> dict:
    merged = dict(DEFAULT_SETTINGS)
    merged.update(s)
    SETTINGS_PATH.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return merged


def site_names() -> list[str]:
    wb = recon.openpyxl.load_workbook(recon.WORKBOOK, read_only=True)
    names = wb.sheetnames
    wb.close()
    return names


@app.route("/")
def index():
    return render_template("index.html")


@app.get("/api/state")
def api_state():
    """Settings + per-site last state + a suggested next date to fill."""
    settings = load_settings()
    sites = []
    latest = None
    for name in site_names():
        st = recon.site_last_state(name)
        last_date = st["last_date"]
        if last_date and (latest is None or last_date > latest):
            latest = last_date
        sites.append({
            "name": name,
            "last_date": last_date.isoformat() if last_date else None,
            "last_caisse": round(st["last_caisse"], 2),
        })
    suggested = (latest + dt.timedelta(days=1)).isoformat() if latest else None
    return jsonify({"settings": settings, "sites": sites,
                    "suggested_date": suggested, "workbook": recon.WORKBOOK.name})


@app.post("/api/settings")
def api_settings():
    data = request.get_json(force=True) or {}
    clean = {}
    if "min_float" in data:
        clean["min_float"] = max(0.0, float(data["min_float"]))
    if "gap_threshold" in data:
        clean["gap_threshold"] = max(0.0, float(data["gap_threshold"]))
    if "require_gap_explanation" in data:
        clean["require_gap_explanation"] = bool(data["require_gap_explanation"])
    if "zelty_mode" in data and data["zelty_mode"] in ("manual", "api"):
        clean["zelty_mode"] = data["zelty_mode"]
    return jsonify(save_settings(clean))


@app.post("/api/populate")
def api_populate():
    """For a date, return each site's carried till float + pulled Zelty cash."""
    data = request.get_json(force=True) or {}
    settings = load_settings()
    try:
        date = dt.date.fromisoformat(data["date"])
    except (KeyError, ValueError):
        return jsonify({"error": "A valid date (YYYY-MM-DD) is required."}), 400

    names = site_names()
    # No invented data: only pull cash when the live API mode is on. In manual
    # mode, column D comes from the sheet (existing days) or is typed in.
    cash = None
    if settings["zelty_mode"] == "api":
        try:
            cash = zelty_source.get_cash(date, names)
        except NotImplementedError as e:
            return jsonify({"error": str(e)}), 503

    min_float = settings["min_float"]
    rows = []
    for name in names:
        st = recon.site_last_state(name)
        last_date = st["last_date"]
        existing = recon.day_values(name, date)
        if existing["found"]:
            # The day is already in the sheet — surface its real numbers and the
            # gap that's already there, read-only, instead of mock data.
            row = {
                "site": name,
                "last_date": last_date.isoformat() if last_date else None,
                "last_caisse": round(st["last_caisse"], 2),
                "caisse": round(existing["caisse"], 2),
                "zelty": round(existing["zelty"], 2),
                "counted": round(existing["counted"], 2),
                "sortie": round(existing["sortie"], 2),
                "depot": round(existing["depot"], 2),
                "gap": round(existing["gap"], 2),
                "duplicate": True,
            }
        else:
            # A new day — carry the floored till float. Zelty (D) is blank unless
            # the live API supplied it; the counted total is entered by the user.
            row = {
                "site": name,
                "last_date": last_date.isoformat() if last_date else None,
                "last_caisse": round(st["last_caisse"], 2),
                "caisse": round(max(min_float, st["last_caisse"]), 2),
                "zelty": round(cash[name], 2) if cash else None,
                "counted": None,
                "sortie": 0.0,
                "depot": 0.0,
                "gap": None,
                "duplicate": False,
            }
        rows.append(row)
    return jsonify({"date": date.isoformat(), "mode": settings["zelty_mode"],
                    "min_float": min_float, "rows": rows})


@app.post("/api/write")
def api_write():
    """Append the day to each site's sheet. Blocks unexplained gaps if required."""
    data = request.get_json(force=True) or {}
    settings = load_settings()
    try:
        date = dt.date.fromisoformat(data["date"])
    except (KeyError, ValueError):
        return jsonify({"error": "A valid date (YYYY-MM-DD) is required."}), 400

    rows = data.get("rows") or []
    threshold = settings["gap_threshold"]
    require = settings["require_gap_explanation"]

    # Server-side guard: an unexplained gap must not be written.
    if require:
        offenders = []
        for r in rows:
            gap = float(r.get("zelty", 0)) - float(r.get("counted", 0))
            if abs(gap) >= threshold and not str(r.get("comment", "")).strip():
                offenders.append(f"{r['site']} (gap {gap:+.2f})")
        if offenders:
            return jsonify({"error": "Explain the gap for: "
                            + ", ".join(offenders)}), 422

    results = []
    for r in rows:
        # Attach the day's date to each gap explanation so the note is
        # self-dated in the Commentaires column, e.g. "2026-07-22 — till short".
        typed = str(r.get("comment", "")).strip()
        comment = f"{date.isoformat()} — {typed}" if typed else ""
        try:
            res = recon.append_day(
                r["site"], date,
                zelty=float(r.get("zelty", 0)),
                counted=float(r.get("counted", 0)),
                sortie=float(r.get("sortie", 0)),
                depot=float(r.get("depot", 0)),
                comment=comment,
                min_float=settings["min_float"],
            )
        except PermissionError:
            return jsonify({"error": f"Can't write {recon.WORKBOOK.name} — it's "
                            "open in Excel (or locked). Close it and try again. "
                            f"No rows were written."}), 423
        except (KeyError, ValueError) as e:
            res = {"site": r.get("site", "?"), "written": False,
                   "message": str(e)}
        results.append(res)
    return jsonify({"date": date.isoformat(), "results": results})


def _shutdown(*_args) -> None:
    """Free the port and exit — kills the reloader child that holds it."""
    free_port(PORT)
    # Use os._exit so a second Ctrl+C can't get stuck in cleanup handlers.
    os._exit(0)


if __name__ == "__main__":
    # A previous run may have left a stale process on the port — clear it
    # before we try to bind.
    free_port(PORT)

    # Clean shutdown: free the port on Ctrl+C / termination / normal exit.
    atexit.register(free_port, PORT)
    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # use_reloader=False keeps this to a single process. The reloader spawns a
    # child that inherits the listening socket, and on Windows that child is
    # what gets orphaned and holds the port after Ctrl+C. One process means
    # Ctrl+C stops it cleanly. (Trade-off: edits no longer auto-restart —
    # re-run the script to pick up changes. The debugger error pages stay.)
    try:
        app.run(host=HOST, port=PORT, debug=True, use_reloader=False)
    finally:
        free_port(PORT)
