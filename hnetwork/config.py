#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Configuration management for hnetwork.

Single source of truth for settings. Stores a JSON file under the data
directory so the web UI and CLI share the same configuration.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict

DEFAULTS: Dict[str, Any] = {
    "scan": {
        # Which discovery method(s) to use. Order matters.
        "methods": ["arp", "ping"],
        # Ports scanned in the "basic" profile.
        "basic_ports": [22, 23, 80, 443, 8080, 8443],
        # Ports scanned in the "full" profile.
        "full_ports": [
            21, 22, 23, 25, 53, 80, 110, 111, 135, 139, 143, 161, 389,
            443, 445, 465, 514, 587, 631, 993, 995, 1433, 1521, 3306,
            3389, 5432, 5900, 6379, 8080, 8443, 8888, 9000, 9090, 9200,
        ],
        "default_profile": "basic",
        "host_timeout": 1.0,
        "max_workers": 64,
        "include_offline": False,
        "ping_first": True,   # ping before TCP port scan to skip dead hosts
        "demo": False,        # synthesize devices when no privileges available
    },
    "detection": {
        "hostname_patterns": [
            {"pattern": r".*router.*|.*gateway.*|.*modem.*", "type": "Router"},
            {"pattern": r".*camera.*|.*cam.*|.*ipcam.*", "type": "IP Camera"},
            {"pattern": r".*printer.*|.*print.*", "type": "Printer"},
            {"pattern": r".*tv.*|.*smart.*tv.*", "type": "Smart TV"},
            {"pattern": r".*nas.*|.*storage.*", "type": "NAS"},
            {"pattern": r".*phone.*|.*mobile.*", "type": "Smartphone"},
            {"pattern": r".*tablet.*|.*ipad.*", "type": "Tablet"},
            {"pattern": r".*laptop.*|.*notebook.*", "type": "Laptop"},
            {"pattern": r".*desktop.*|.*pc.*", "type": "Desktop"},
            {"pattern": r".*xbox.*|.*playstation.*|.*nintendo.*", "type": "Gaming Console"},
            {"pattern": r".*ap.*|.*access.*point.*|.*unifi.*", "type": "Access Point"},
            {"pattern": r".*switch.*|.*managed.*", "type": "Switch"},
        ],
        "vendor_patterns": [
            {"pattern": r"Apple.*", "type": "Smartphone", "conditions": ["iphone", "ios"]},
            {"pattern": r"Apple.*", "type": "Tablet", "conditions": ["ipad"]},
            {"pattern": r"Apple.*", "type": "Laptop", "conditions": ["macbook", "mac"]},
            {"pattern": r"Samsung.*", "type": "Smartphone", "conditions": ["galaxy", "android"]},
            {"pattern": r"Samsung.*", "type": "Smart TV", "conditions": ["tv", "display"]},
            {"pattern": r"LG.*", "type": "Smart TV", "conditions": ["tv", "display"]},
            {"pattern": r"Sony.*", "type": "Gaming Console", "conditions": ["playstation"]},
            {"pattern": r"Microsoft.*", "type": "Gaming Console", "conditions": ["xbox"]},
            {"pattern": r"TP-Link.*|TpLink.*", "type": "Router"},
            {"pattern": r"ASUSTek.*|Asus.*", "type": "Router"},
            {"pattern": r"Netgear.*", "type": "Router"},
            {"pattern": r"Ubiquiti.*|Ubnt.*", "type": "Access Point"},
            {"pattern": r"Xiaomi.*", "type": "Smartphone"},
            {"pattern": r"Raspberry.*", "type": "Raspberry Pi"},
            {"pattern": r"Dyson.*", "type": "Smart Home"},
            {"pattern": r"Petkit.*", "type": "Pet Feeder"},
            {"pattern": r"Espressif.*|Xiaomi.*|Tuya.*", "type": "IoT Device"},
            {"pattern": r"Hikvision.*|Dahua.*", "type": "IP Camera"},
        ],
        "port_rules": {
            "554": "IP Camera",
            "8554": "IP Camera",
            "631": "Printer",
            "9100": "Printer",
            "515": "Printer",
            "3389": "Desktop",
            "22": "Server",
            "23": "Network Gear",
            "161": "Network Gear",
            "80": "Web Device",
            "443": "Web Device",
        },
        "confidence_threshold": 0.5,
    },
    "ui": {
        "language": "tr",
        "theme": "dark",
    },
}


class Config:
    """Thin persistent configuration wrapper around a JSON file."""

    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(_data_dir(), "config.json")
        self.data: Dict[str, Any] = {}
        self.load()

    # ----- IO -----------------------------------------------------------
    def load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            self.data = _deep_merge(DEFAULTS, loaded)
        except FileNotFoundError:
            self.data = json.loads(json.dumps(DEFAULTS))  # deep copy
            self.save()
        except Exception:
            self.data = json.loads(json.dumps(DEFAULTS))

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=2, ensure_ascii=False)

    # ----- accessors ----------------------------------------------------
    def get(self, *keys, default=None):
        node = self.data
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node

    def set(self, *keys, value) -> None:
        node = self.data
        for k in keys[:-1]:
            node = node.setdefault(k, {})
        node[keys[-1]] = value
        self.save()

    @property
    def scan(self) -> Dict[str, Any]:
        return self.data.setdefault("scan", {})

    @property
    def detection(self) -> Dict[str, Any]:
        return self.data.setdefault("detection", {})


# ---------------------------------------------------------------------- #
def _data_dir() -> str:
    env = os.environ.get("HN_DATA_DIR")
    if env:
        return env
    # default: ~/.local/share/hnetwork (or ./data when run from project root)
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if os.path.exists(os.path.join(here, "hnetwork")):
        return os.path.join(here, "data")
    return os.path.join(os.path.expanduser("~"), ".local", "share", "hnetwork")


def _deep_merge(base: Dict, override: Dict) -> Dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


_config = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config
