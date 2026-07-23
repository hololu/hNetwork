#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Device type detection from hostname, vendor and open ports."""
from __future__ import annotations

import re
from typing import Dict, List


def detect_device_type(
    hostname: str,
    vendor: str,
    open_ports: List[int],
    rules: Dict,
) -> Dict:
    """Return {"device_type": str, "confidence": float, "method": str}."""
    hostname_l = (hostname or "").lower()
    vendor_l = (vendor or "").lower()

    # 1) hostname patterns (high confidence)
    for rule in rules.get("hostname_patterns", []):
        try:
            if re.search(rule["pattern"], hostname_l, re.IGNORECASE):
                return {"device_type": rule["type"], "confidence": 0.9, "method": "hostname"}
        except Exception:
            continue

    # 2) vendor patterns (with optional conditions)
    for rule in rules.get("vendor_patterns", []):
        try:
            if re.search(rule["pattern"], vendor_l, re.IGNORECASE):
                if "conditions" in rule:
                    if any(c in hostname_l or c in vendor_l for c in rule["conditions"]):
                        return {"device_type": rule["type"], "confidence": 0.8, "method": "vendor+cond"}
                else:
                    return {"device_type": rule["type"], "confidence": 0.7, "method": "vendor"}
        except Exception:
            continue

    # 3) port rules
    port_rules: Dict[int, str] = {int(k): v for k, v in rules.get("port_rules", {}).items()}
    for port in open_ports:
        if port in port_rules:
            return {"device_type": port_rules[port], "confidence": 0.6, "method": "port"}

    if open_ports:
        if 3389 in open_ports:
            return {"device_type": "Desktop", "confidence": 0.5, "method": "port"}
        if 22 in open_ports:
            return {"device_type": "Server", "confidence": 0.5, "method": "port"}
        if any(p in (80, 443, 8080, 8443) for p in open_ports):
            return {"device_type": "Web Device", "confidence": 0.4, "method": "port"}

    return {"device_type": "Unknown", "confidence": 0.0, "method": "none"}
