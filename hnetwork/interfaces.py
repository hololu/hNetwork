#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Network interface, VLAN and target-range discovery for hnetwork.

This module is privilege-agnostic: it only reads local interface
configuration and lets the caller translate an interface / VLAN id into
a list of CIDR ranges to scan.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import subprocess
from typing import Any, Dict, List, Optional


def _run(cmd: List[str], timeout: float = 5.0) -> Optional[str]:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return res.stdout + res.stderr
    except Exception:
        return None


def list_interfaces() -> List[Dict[str, Any]]:
    """Return all usable IPv4 interfaces with their address/netmask/cidr.

    Skips loopback and link-local addresses. Each entry::

        {
          "name": "eth0",
          "ip": "10.0.0.5",
          "netmask": "255.255.255.0",
          "cidr": "10.0.0.0/24",
          "mac": "AA:BB:CC:DD:EE:FF",
          "type": "Ethernet",
          "vlans": [10, 20],     # 802.1q sub-interfaces detected
          "default_gw": "10.0.0.1"
        }
    """
    interfaces: List[Dict[str, Any]] = []

    # 1) Collect raw addresses using `ip` (portable on Linux).
    raw = _collect_ip_addr()

    # 2) Default gateway
    default_gw = _default_gateway()

    # 3) MAC addresses
    macs = _collect_macs()

    # 4) VLAN ids per base interface (from naming eth0.10 or ip link type vlan)
    vlan_map = _collect_vlans()

    for name, info in raw.items():
        ip = info["ip"]
        netmask = info["netmask"]
        try:
            net = ipaddress.IPv4Network(f"{ip}/{netmask}", strict=False)
        except Exception:
            continue
        if ip.startswith("127.") or ip.startswith("169.254."):
            continue
        iface_type = _classify_interface(name)
        interfaces.append({
            "name": name,
            "ip": ip,
            "netmask": netmask,
            "cidr": str(net),
            "mac": macs.get(name, "Unknown"),
            "type": iface_type,
            "vlans": sorted(vlan_map.get(name, [])),
            "default_gw": default_gw if _gw_on_interface(default_gw, net) else None,
        })

    # Sort: interfaces that carry the default gateway first.
    interfaces.sort(key=lambda i: (i["default_gw"] is None, i["name"]))
    return interfaces


def cidr_for_interface(name: str) -> Optional[str]:
    for iface in list_interfaces():
        if iface["name"] == name:
            return iface["cidr"]
    return None


def cidr_for_vlan(base_interface: str, vlan_id: int) -> Optional[str]:
    """Resolve the subnet of a VLAN sub-interface (e.g. eth0.100)."""
    vlan_if = f"{base_interface}.{vlan_id}"
    cidr = cidr_for_interface(vlan_if)
    if cidr:
        return cidr
    # If the VLAN interface does not exist on this host, we cannot resolve a
    # real subnet. The caller may still scan a manually supplied CIDR.
    return None


def vlan_interfaces() -> List[Dict[str, Any]]:
    """Return a flat list of VLAN sub-interfaces with their parent + cidr."""
    out: List[Dict[str, Any]] = []
    for iface in list_interfaces():
        for v in iface["vlans"]:
            vname = f"{iface['name']}.{v}"
            out.append({
                "vlan_id": v,
                "interface": vname,
                "parent": iface["name"],
                "cidr": cidr_for_interface(vname),
                "parent_cidr": iface["cidr"],
            })
    return out


# --------------------------- helpers ----------------------------------- #
def _collect_ip_addr() -> Dict[str, Dict[str, str]]:
    out: Dict[str, Dict[str, str]] = {}
    text = _run(["ip", "-o", "-4", "addr", "show"])
    if not text:
        return out
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        name = parts[1]
        addr = parts[3]  # 10.0.0.5/24
        try:
            net = ipaddress.IPv4Network(addr, strict=False)
        except Exception:
            continue
        out.setdefault(name, {
            "ip": str(net.network_address + (0 if False else _host_index(net, addr))),
            "netmask": str(net.netmask),
        })
        # store the real host ip (not network address)
        host_ip = addr.split("/")[0]
        out[name]["ip"] = host_ip
    return out


def _host_index(net: ipaddress.IPv4Network, addr: str) -> int:
    return 0


def _collect_macs() -> Dict[str, str]:
    macs: Dict[str, str] = {}
    text = _run(["ip", "-o", "link", "show"])
    if not text:
        return macs
    cur = None
    for line in text.splitlines():
        m = re.search(r"^\d+:\s+([\w@.]+):", line)
        if m:
            cur = m.group(1)
        m2 = re.search(r"link/ether\s+([0-9a-fA-F:]{17})", line)
        if m2 and cur:
            macs[cur] = m2.group(1).upper()
    return macs


def _collect_vlans() -> Dict[str, List[int]]:
    """Detect VLAN ids from `ip link` (type vlan) and ethN.VLAN naming."""
    vmap: Dict[str, set] = {}
    text = _run(["ip", "-o", "link", "show"])
    if not text:
        return {}
    # explicit vlan interfaces:  eth0.100@eth0  or  vlan100@eth0
    for line in text.splitlines():
        m = re.search(r"^\d+:\s+([\w.]+)@([\w.]+):", line)
        if m:
            child, parent = m.group(1), m.group(2)
            vm = re.match(r".+\.(\d+)$", child)
            if vm:
                vmap.setdefault(parent, set()).add(int(vm.group(1)))
    return {k: list(v) for k, v in vmap.items()}


def _default_gateway() -> Optional[str]:
    text = _run(["ip", "route", "show", "default"])
    if text:
        m = re.search(r"default via (\d+\.\d+\.\d+\.\d+)", text)
        if m:
            return m.group(1)
    return None


def _gw_on_interface(gw: Optional[str], net: ipaddress.IPv4Network) -> bool:
    if not gw:
        return False
    try:
        return ipaddress.IPv4Address(gw) in net
    except Exception:
        return False


def _classify_interface(name: str) -> str:
    n = name.lower()
    if "docker" in n or n.startswith("br-") or "veth" in n:
        return "Docker"
    if n.startswith("vlan") or ".v" in n:
        return "VLAN"
    if "wlan" in n or "wifi" in n or "wl" in n:
        return "WiFi"
    if "eth" in n or n.startswith("en") or "em" in n:
        return "Ethernet"
    if "tun" in n or "tap" in n or "vpn" in n:
        return "VPN"
    if "bond" in n:
        return "Bond"
    if "br" in n or "bridge" in n:
        return "Bridge"
    return "Other"


def parse_targets(spec: str) -> List[str]:
    """Parse a comma separated list of targets into CIDR ranges.

    Accepts:
      - interface name:   ``eth0``
      - vlan spec:        ``eth0.10``  or  ``eth0:vlan10``
      - cidr:             ``10.0.0.0/24``
      - range:            ``10.0.0.1-10.0.0.50``
      - single ip:        ``10.0.0.5``
    Returns a list of CIDR strings (each expanded).
    """
    targets: List[str] = []
    for piece in spec.split(","):
        piece = piece.strip()
        if not piece:
            continue
        # VLAN sub-interface
        if re.match(r"^[\w]+(\.\d+|:vlan\d+)$", piece):
            if ".vlan" in piece or piece.endswith(".vlan"):
                base, vid = piece.rsplit(".vlan", 1)
                vid = int(re.sub(r"\D", "", vid) or 0)
            elif "." in piece:
                base, vid = piece.split(".", 1)
                vid = int(re.sub(r"\D", "", vid) or 0)
            else:
                base, vid = re.split(r":vlan", piece)
                vid = int(re.sub(r"\D", "", vid) or 0)
            cidr = cidr_for_vlan(base, vid) or cidr_for_interface(base)
            if cidr:
                targets.append(cidr)
            continue
        # an interface name (no slash, no dot, no digits after letters)
        if re.match(r"^[a-zA-Z]+[\w]*$", piece) and "." not in piece:
            cidr = cidr_for_interface(piece)
            if cidr:
                targets.append(cidr)
            continue
        # CIDR
        if "/" in piece:
            try:
                ipaddress.IPv4Network(piece, strict=False)
                targets.append(piece)
                continue
            except Exception:
                pass
        # range a.b.c.d-e.f.g.h
        if "-" in piece:
            try:
                start, end = piece.split("-")
                net = ipaddress.summarize_address_range(
                    ipaddress.IPv4Address(start.strip()),
                    ipaddress.IPv4Address(end.strip()),
                )
                targets.extend(str(n) for n in net)
                continue
            except Exception:
                pass
        # single ip -> /32
        try:
            ipaddress.IPv4Address(piece)
            targets.append(f"{piece}/32")
            continue
        except Exception:
            pass
    return targets
