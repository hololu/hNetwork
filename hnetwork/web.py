#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Flask web application for hnetwork."""
from __future__ import annotations

import os
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


def _run_scan(targets, profile, include_offline, demo):
    try:
        scanner.scan(targets, profile=profile, include_offline=include_offline,
                     progress=_emit, demo=demo)
    except Exception as e:  # pragma: no cover
        _emit({"phase": "error", "message": str(e)})


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
    demo = bool(data.get("demo", False))
    if not targets:
        return jsonify({"error": "En az bir hedef (arayüz/VLAN/CIDR) girilmeli"}), 400
    _progress.clear()
    _progress.update({"phase": "starting", "log": []})
    _scan_thread = threading.Thread(
        target=_run_scan, args=(targets, profile, include_offline, demo), daemon=True
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


@app.route("/api/results")
def api_results():
    return jsonify(scanner.last_results)


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
    app.run(host=host, port=port, debug=debug, use_reloader=False)


if __name__ == "__main__":
    run()
