#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OUI (MAC vendor) lookup with a small built-in database + cache.

Keeps a local JSON cache under the data dir so lookups are offline-friendly.
Falls back to a compact built-in table for very common vendors.
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict

# Compact built-in table (OUI -> Vendor). Covers the most common home/office
# equipment so the UI is useful even with zero network access.
BUILTIN_OUI: Dict[str, str] = {
    "FCFC48": "Samsung",
    "8C882B": "Samsung",
    "AC9C8D": "Samsung",
    "3C5A:B4": "Apple",
    "A4C1:38": "Apple",
    "F0:18:98": "Apple",
    "AC:BC:32": "Apple",
    "D0:11:E5": "Apple",
    "BC:EC:5D": "Apple",
    "FC:A1:83": "Apple",
    "9C:30:5B": "Apple",
    "00:1A:2B": "Cisco",
    "00:21:1B": "Cisco",
    "F4:4E:FD": "Cisco",
    "00:23:EB": "Cisco-Linksys",
    "C8:D7:19": "ASUSTek",
    "AC:22:0B": "ASUSTek",
    "74:D0:2B": "ASUSTek",
    "50:C7:BF": "TP-Link",
    "B0:BE:83": "TP-Link",
    "EC:08:6B": "TP-Link",
    "E8:DE:27": "Huawei",
    "F4:1B:A1": "Huawei",
    "00:9A:CD": "Huawei",
    "7C:8B:CA": "Huawei",
    "3C:52:82": "Hikvision",
    "EC:5A:3E": "Hikvision",
    "FC:A7:96": "Dahua",
    "60:85:80": "Xiaomi",
    "28:6C:07": "Xiaomi",
    "DC:44:6D": "Xiaomi",
    "88:9F:FA": "Xiaomi",
    "B0:25:AA": "Google",
    "F4:F5:D8": "Google",
    "94:EB:2C": "Google",
    "18:B4:30": "Ubiquiti",
    "FC:EC:DA": "Ubiquiti",
    "24:5A:4C": "Ubiquiti",
    "00:26:18": "Netgear",
    "C0:FF:D4": "Netgear",
    "E0:46:9A": "Netgear",
    "00:1F:33": "Fortinet",
    "00:09:0F": "Fortinet",
    "00:0C:29": "VMware",
    "00:50:56": "VMware",
    "00:15:5D": "Microsoft Hyper-V",
    "00:03:FF": "Microsoft",
    "B8:27:EB": "Raspberry Pi",
    "DC:A6:32": "Raspberry Pi",
    "E4:5F:01": "Raspberry Pi",
    "3C:5A:B4": "Apple",
    "00:50:43": "Raspberry Pi (Espressif)",
    "24:0A:C4": "Espressif",
    "2C:CF:67": "Espressif",
    "84:CC:A8": "Espressif",
    "48:E7:DA": "Espressif",
    "68:C6:3A": "Espressif",
    "18:FE:34": "Espressif",
    "30:AE:A4": "Espressif",
    "A0:20:A6": "Sonoff/Tuya",
    "D8:1F:12": "Tuya",
    "7C:9E:BD": "Tuya",
    "B4:E6:2D": "Tuya",
    "10:52:1C": "Tuya",
    "48:8F:5A": "Tuya",
    "D4:1B:81": "LG",
    "00:1F:3D": "LG",
    "C0:5A:CF": "LG",
    "00:1D:0D": "LG",
    "00:E0:4C": "Realtek",
    "52:54:00": "QEMU/KVM",
    "0A:00:27": "VirtualBox",
    "02:42:AC": "Docker",
    "00:15:17": "Dell",
    "F0:4D:A2": "Dell",
    "D8:9E:F3": "Dell",
    "3C:D9:2B": "Hewlett Packard",
    "98:29:A6": "Hewlett Packard",
    "B4:99:BA": "Hewlett Packard",
    "1C:39:47": "Sonos",
    "5C:AA:FD": "Sonos",
    "94:9F:3E": "Sonos",
    "94:DE:80": "Synology",
    "00:11:32": "Synology",
    "00:0C:EE": "Synology",
    "00:1C:42": "Parallels",
    "00:50:B6": "Atheros",
    "00:13:10": "Cisco-Linksys",
    "00:18:39": "Cisco-Linksys",
    "00:1E:E5": "Cisco-Linksys",
    "00:21:29": "Cisco-Linksys",
    "00:25:9C": "Cisco-Linksys",
    "C0:C1:C0": "Cisco-Linksys",
    "68:7F:74": "Cisco-Linksys",
    "00:18:F3": "Cisco-Linksys",
    "00:1A:70": "Cisco-Linksys",
    "00:16:B6": "Cisco-Linksys",
    "00:12:17": "Cisco-Linksys",
    "00:14:BF": "Cisco-Linksys",
    "00:0F:66": "Cisco-Linksys",
    "00:06:25": "Cisco-Linksys",
    "00:0C:41": "Cisco-Linksys",
    "00:0A:BB": "Cisco-Linksys",
    "00:13:10": "Cisco-Linksys",
    "00:1B:63": "Cisco-Linksys",
    "00:1C:10": "Cisco-Linksys",
    "00:1D:7E": "Cisco-Linksys",
    "00:21:91": "Cisco-Linksys",
    "00:22:6B": "Cisco-Linksys",
    "00:24:01": "Cisco-Linksys",
    "00:25:53": "Cisco-Linksys",
    "00:26:37": "Cisco-Linksys",
    "00:26:62": "Cisco-Linksys",
    "00:27:19": "Cisco-Linksys",
    "58:6D:8F": "Cisco-Linksys",
    "68:7F:74": "Cisco-Linksys",
    "C8:D7:19": "ASUSTek",
    "AC:22:0B": "ASUSTek",
    "74:D0:2B": "ASUSTek",
    "00:1F:C6": "ASUSTek",
    "00:23:54": "ASUSTek",
    "00:24:8C": "ASUSTek",
    "00:26:18": "Netgear",
    "C0:FF:D4": "Netgear",
    "E0:46:9A": "Netgear",
    "00:09:5B": "Netgear",
    "00:0F:B5": "Netgear",
    "00:14:6C": "Netgear",
    "00:18:4D": "Netgear",
    "00:1B:2F": "Netgear",
    "00:1E:2A": "Netgear",
    "00:22:3F": "Netgear",
    "00:24:B2": "Netgear",
    "08:86:3B": "Netgear",
    "0C:79:C0": "Netgear",
    "10:0C:6F": "Netgear",
    "14:59:C0": "Netgear",
    "1C:7E:E5": "Netgear",
    "20:E5:2A": "Netgear",
    "28:80:3F": "Netgear",
    "2C:B0:5D": "Netgear",
    "30:46:9A": "Netgear",
    "34:98:B5": "Netgear",
    "38:94:ED": "Netgear",
    "3C:84:0E": "Netgear",
    "40:5D:82": "Netgear",
    "44:94:FC": "Netgear",
    "48:8E:BD": "Netgear",
    "4C:60:DE": "Netgear",
    "50:46:5D": "Netgear",
    "54:04:A6": "Netgear",
    "58:23:8C": "Netgear",
    "5C:DA:D4": "Netgear",
    "60:B0:0C": "Netgear",
    "64:66:B3": "Netgear",
    "68:1E:EC": "Netgear",
    "6C:CD:D6": "Netgear",
    "70:8B:CD": "Netgear",
    "74:44:A1": "Netgear",
    "78:44:FD": "Netgear",
    "7C:8B:CA": "Huawei",
    "80:1F:02": "Netgear",
    "84:1B:5E": "Netgear",
    "88:53:95": "Netgear",
    "8C:0F:6F": "Netgear",
    "90:84:0D": "Netgear",
    "94:10:3E": "Netgear",
    "98:40:BB": "Netgear",
    "9C:3D:CF": "Netgear",
    "A0:21:B7": "Netgear",
    "A4:2B:B0": "Netgear",
    "A8:20:66": "Netgear",
    "AC:9E:17": "Netgear",
    "B0:39:56": "Netgear",
    "B4:3E:ED": "Netgear",
    "B8:76:3F": "Netgear",
    "BC:30:D9": "Netgear",
    "C0:56:27": "Netgear",
    "C4:04:15": "Netgear",
    "C8:3A:35": "Netgear",
    "CC:40:D0": "Netgear",
    "D0:4D:F7": "Netgear",
    "D4:60:E3": "Netgear",
    "D8:32:14": "Netgear",
    "DC:0B:34": "Netgear",
    "E0:91:F5": "Netgear",
    "E4:4F:43": "Netgear",
    "E8:1C:BA": "Netgear",
    "EC:71:DB": "Netgear",
    "F0:18:98": "Apple",
    "F4:CA:E5": "Netgear",
    "F8:E9:03": "Netgear",
    "FC:75:16": "Netgear",
    "00:1B:63": "Cisco-Linksys",
    "00:1C:10": "Cisco-Linksys",
    "00:1D:7E": "Cisco-Linksys",
    "00:21:91": "Cisco-Linksys",
    "00:22:6B": "Cisco-Linksys",
    "00:24:01": "Cisco-Linksys",
    "00:25:53": "Cisco-Linksys",
    "00:26:37": "Cisco-Linksys",
    "00:26:62": "Cisco-Linksys",
    "00:27:19": "Cisco-Linksys",
    "58:6D:8F": "Cisco-Linksys",
    "68:7F:74": "Cisco-Linksys",
}


class OUILookup:
    def __init__(self, cache_path: str | None = None):
        self.cache_path = cache_path or os.path.join(_data_dir(), "oui_cache.json")
        self.cache: Dict[str, str] = {}
        self._load()

    def _load(self):
        try:
            with open(self.cache_path, "r", encoding="utf-8") as fh:
                self.cache = json.load(fh)
        except Exception:
            self.cache = {}

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            with open(self.cache_path, "w", encoding="utf-8") as fh:
                json.dump(self.cache, fh, indent=2)
        except Exception:
            pass

    @staticmethod
    def _normalize(mac: str) -> str:
        mac = (mac or "").upper().replace("-", ":").replace(".", ":")
        return mac

    def lookup(self, mac: str) -> str:
        mac = self._normalize(mac)
        if not mac or mac in ("UNKNOWN", "00:00:00:00:00:00"):
            return "Unknown"
        # Try 3-byte OUI first, then 4-byte (OUI-36) and 5-byte (CID).
        for length in (8, 11, 14):  # "AA:BB:CC" -> 8 chars, etc.
            key = mac[:length]
            if key in self.cache:
                return self.cache[key]
            if key in BUILTIN_OUI:
                return BUILTIN_OUI[key]
            # also try with separators removed (some tables store AABBCCDDEE)
        # bare form
        bare = mac.replace(":", "")
        for length in (6, 9, 12):
            key = bare[:length]
            if key in BUILTIN_OUI:
                return BUILTIN_OUI[key]
        # store Unknown to avoid repeated work
        self.cache[mac[:8]] = "Unknown"
        if len(self.cache) % 25 == 0:
            self._save()
        return "Unknown"


_oui = None


def get_oui() -> OUILookup:
    global _oui
    if _oui is None:
        _oui = OUILookup()
    return _oui


def _data_dir() -> str:
    env = os.environ.get("HN_DATA_DIR")
    if env:
        return env
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if os.path.exists(os.path.join(here, "hnetwork")):
        return os.path.join(here, "data")
    return os.path.join(os.path.expanduser("~"), ".local", "share", "hnetwork")
