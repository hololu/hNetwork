#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Flask web application for hnetwork."""
from __future__ import annotations

import os
import json
import socket
import threading
from datetime import datetime
from typing import Any, Dict

from flask import Flask, jsonify, render_template, request, send_from_directory

from .scanner import Scanner
from .config import get_config

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(24).hex())
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

# One shared scanner instance + lock for the running scan.
scanner = Scanner()
_scan_thread: threading.Thread | None = None
_progress: Dict[str, Any] = {"phase": "idle", "log": []}

# Periodic auto-scan state
_schedule: Dict[str, Any] = {"enabled": False, "interval": 300, "targets": [], "profile": "basic",
                             "next_run": None, "last_run": None}
_sched_timer: threading.Timer | None = None


def _emit(update: Dict[str, Any]):
    """Progress callback that records the latest state for polling."""
    global _progress
    _progress.update({k: v for k, v in update.items() if k != "log"})
    msg = update.get("message") or update.get("phase")
    if msg and update.get("phase") not in ("host",):
        _progress.setdefault("log", []).append({
            "t": datetime.now().strftime("%H:%M:%S"),
            "msg": str(msg),
        })
        _progress["log"] = _progress["log"][-60:]


def _run_scan(targets, profile, include_offline):
    try:
        scanner.scan(targets, profile=profile, include_offline=include_offline,
                     progress=_emit)
    except Exception as e:  # pragma: no cover
        _emit({"phase": "error", "message": str(e)})


def _schedule_next():
    """(Re)arm the periodic scan timer based on _schedule."""
    global _sched_timer
    if _sched_timer is not None:
        _sched_timer.cancel()
        _sched_timer = None
    if not _schedule["enabled"]:
        _schedule["next_run"] = None
        return
    interval = max(30, int(_schedule["interval"]))
    _schedule["next_run"] = (datetime.now().timestamp() + interval)
    _sched_timer = threading.Timer(interval, _run_scheduled)
    _sched_timer.daemon = True
    _sched_timer.start()


def _run_scheduled():
    """Fire a scheduled scan, then re-arm (if still enabled and not busy)."""
    if _schedule["enabled"] and not scanner.running and _schedule["targets"]:
        _progress.clear()
        _progress.update({"phase": "starting", "log": [], "scheduled": True})
        _schedule["last_run"] = datetime.now().isoformat()
        t = threading.Thread(target=_run_scan,
                             args=(_schedule["targets"], _schedule["profile"], False),
                             daemon=True)
        t.start()
    _schedule_next()


# ----------------------------- routes ----------------------------- #
@app.route("/")
def index():
    return render_template("index.html", version="2.0.0")


@app.route("/api/interfaces")
def api_interfaces():
    return jsonify(scanner.interfaces())


@app.route("/api/vlans")
def api_vlans():
    return jsonify(scanner.vlans())


@app.route("/api/config")
def api_config():
    cfg = get_config()
    return jsonify(cfg.data)


@app.route("/api/scan", methods=["POST"])
def api_scan():
    global _scan_thread
    if scanner.running:
        return jsonify({"error": "Taramaya devam ediliyor"}), 409
    data = request.get_json(silent=True) or {}
    targets = data.get("targets") or []
    profile = data.get("profile", "basic")
    include_offline = bool(data.get("include_offline", False))
    if not targets:
        return jsonify({"error": "En az bir hedef (arayüz/VLAN/CIDR) girilmeli"}), 400
    _progress.clear()
    _progress.update({"phase": "starting", "log": []})
    _scan_thread = threading.Thread(
        target=_run_scan, args=(targets, profile, include_offline), daemon=True
    )
    _scan_thread.start()
    return jsonify({"message": "Tarama başlatıldı", "targets": targets})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    scanner.stop()
    return jsonify({"message": "Durdurma isteği gönderildi"})


@app.route("/api/progress")
def api_progress():
    return jsonify(_progress)


@app.route("/api/devices")
def api_devices():
    devices = scanner.last_results.get("devices", [])
    return jsonify(devices)


@app.route("/api/device/<path:ip>")
def api_device_detail(ip):
    """Return a single device's full record by IP."""
    devices = scanner.last_results.get("devices", [])
    for d in devices:
        if d.get("ip") == ip:
            return jsonify(d)
    return jsonify({"error": "Cihaz bulunamadı"}), 404


@app.route("/api/device/<path:ip>/ports", methods=["POST"])
def api_device_rescan_ports(ip):
    """Re-scan open ports for a single device using the pure-python scanner.

    Optional JSON body: {"ports": "1-1000, 22, 80, 443"} or a list of ints.
    """
    data = request.get_json(silent=True) or {}
    ports_arg = data.get("ports")
    # parse port specification
    if isinstance(ports_arg, str) and ports_arg.strip():
        ports = []
        for part in ports_arg.split(","):
            part = part.strip()
            if "-" in part:
                try:
                    a, b = part.split("-", 1)
                    lo, hi = int(a), int(b)
                    ports.extend(range(lo, hi + 1))
                except Exception:
                    pass
            elif part.isdigit():
                ports.append(int(part))
        ports = sorted(set(p for p in ports if 1 <= p <= 65535))
    elif isinstance(ports_arg, (list, tuple)):
        ports = [int(p) for p in ports_arg if str(p).isdigit()]
    else:
        ports = scanner.config.scan.get("basic_ports", [])
    # cap scan size to avoid hangs
    if len(ports) > 2000:
        ports = ports[:2000]
    try:
        open_ports = scanner._tcp_scan_pure(ip, ports)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    # update stored record
    for d in scanner.last_results.get("devices", []):
        if d.get("ip") == ip:
            d["open_ports"] = open_ports
            break
    return jsonify({"ip": ip, "open_ports": open_ports, "scanned": len(ports)})


@app.route("/api/device/<path:ip>/wol", methods=["POST"])
def api_device_wol(ip):
    """Send a Wake-on-LAN magic packet to the device's MAC."""
    import struct
    mac = None
    for d in scanner.last_results.get("devices", []):
        if d.get("ip") == ip:
            mac = d.get("mac")
            break
    if not mac or mac in ("Unknown", "—", ""):
        return jsonify({"error": "MAC adresi yok"}), 400
    try:
        mac_bytes = bytes.fromhex(mac.replace(":", "").replace("-", ""))
        if len(mac_bytes) != 6:
            return jsonify({"error": "Geçersiz MAC"}), 400
        # magic packet: 6x FF + 16x MAC
        packet = b"\xff" * 6 + mac_bytes * 16
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        # send to both local broadcast and directed (subnet broadcast via ip)
        sock.sendto(packet, ("255.255.255.255", 9))
        try:
            subnet_bcast = ".".join(ip.split(".")[:3]) + ".255"
            sock.sendto(packet, (subnet_bcast, 9))
        except Exception:
            pass
        sock.close()
        return jsonify({"ok": True, "mac": mac, "ip": ip})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/results")
def api_results():
    return jsonify(scanner.last_results)


@app.route("/api/export/<fmt>")
def api_export(fmt):
    import csv
    import io
    from flask import Response

    devices = scanner.last_results.get("devices", [])
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    cols = ["ip", "mac", "hostname", "vendor", "device_type", "status", "open_ports", "network", "interface", "last_seen"]

    if fmt == "json":
        return Response(
            json.dumps(scanner.last_results, ensure_ascii=False, indent=2),
            mimetype="application/json",
            headers={"Content-Disposition": f"attachment; filename=hnetwork_{ts}.json"},
        )
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(cols)
        for d in devices:
            row = [d.get(c, "") for c in cols]
            row[cols.index("open_ports")] = " ".join(str(p) for p in d.get("open_ports", []))
            w.writerow(row)
        return Response(
            buf.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename=hnetwork_{ts}.csv"},
        )
    if fmt == "txt":
        lines = [f"hnetwork tarama raporu — {ts}",
                 f"Toplam cihaz: {len(devices)}", f"IP{' '*(15-2)}MAC{' '*(17-3)}TİP{' '*(15-3)}"
                 f"VENDOR{' '*(21-6)}HOST  PORTLAR", "=" * 78]
        for d in devices:
            ports = ", ".join(str(p) for p in d.get("open_ports", [])) or "-"
            lines.append(
                f"{d.get('ip',''):<16}{d.get('mac',''):<18}{(d.get('device_type','') or '-'):<16}"
                f"{(d.get('vendor','') or '-'):<22}{(d.get('hostname','') or '-'):<14}{ports}"
            )
        return Response(
            "\n".join(lines),
            mimetype="text/plain",
            headers={"Content-Disposition": f"attachment; filename=hnetwork_{ts}.txt"},
        )
    return jsonify({"error": "Geçersiz format (json/csv/txt)"}), 400


@app.route("/api/schedule", methods=["GET", "POST"])
def api_schedule():
    if request.method == "GET":
        return jsonify(_schedule)
    data = request.get_json(silent=True) or {}
    if "enabled" in data:
        _schedule["enabled"] = bool(data["enabled"])
    if "interval" in data:
        try:
            _schedule["interval"] = max(30, int(data["interval"]))
        except (TypeError, ValueError):
            pass
    if "targets" in data and isinstance(data["targets"], list):
        _schedule["targets"] = data["targets"]
    if "profile" in data:
        _schedule["profile"] = data["profile"]
    _schedule_next()
    return jsonify(_schedule)


@app.route("/api/config", methods=["POST"])
def api_config_update():
    cfg = get_config()
    data = request.get_json(silent=True) or {}
    for section, values in data.items():
        if isinstance(values, dict):
            for k, v in values.items():
                cfg.set(section, k, value=v)
    return jsonify({"ok": True})


# ----------------------------- main ----------------------------- #
def run(host="0.0.0.0", port=5883, debug=False):
    app.run(host=host, port=port, debug=debug, use_reloader=False, threaded=True)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="hnetwork web server")
    ap.add_argument("--host", default="0.0.0.0", help="bind address")
    ap.add_argument("--port", type=int, default=5883, help="listen port")
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()
    run(host=a.host, port=a.port, debug=a.debug)
