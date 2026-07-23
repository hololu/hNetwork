#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Core hnetwork scanner engine.

Supports:
  * multi-interface scanning (scan several interfaces in one run)
  * 802.1q VLAN scanning via sub-interfaces (eth0.10, eth0.20, ...)
  * ARP + ping host discovery
  * TCP port scanning (basic / full profile)
  * device-type detection (hostname/vendor/port rules)
  * DEMO mode: synthesize realistic devices when no privileges / nmap

The engine is backend-agnostic: it exposes a simple API used by both the
web app and the CLI.
"""
from __future__ import annotations

import ipaddress
import json
import os
import random
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from .config import get_config
from .interfaces import list_interfaces, parse_targets
from .oui import get_oui
from .detection import detect_device_type

ProgressCb = Callable[[Dict[str, Any]], None]


def _have_privileges() -> bool:
    """Best-effort check for raw-socket / ARP capability."""
    try:
        import os as _os
        return _os.geteuid() == 0
    except Exception:
        # Windows / unknown -> assume no raw ARP
        return False


def _have_nmap() -> bool:
    try:
        subprocess.run(["nmap", "--version"], capture_output=True, timeout=5)
        return True
    except Exception:
        return False


class Scanner:
    def __init__(self):
        self.config = get_config()
        self.oui = get_oui()
        self._lock = threading.Lock()
        self.running = False
        self._stop = False
        self.last_results: Dict[str, Any] = {"targets": [], "devices": [], "started": None, "finished": None}

    # ---------------- public API ---------------- #
    def scan(
        self,
        targets: List[str],
        profile: str = "basic",
        include_offline: Optional[bool] = None,
        progress: Optional[ProgressCb] = None,
        demo: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Run a scan over a list of target specs (interface / vlan / cidr).

        Returns a results dict and also stores it in ``self.last_results``.
        """
        if self.running:
            raise RuntimeError("A scan is already running")

        cfg = self.config.scan
        demo = cfg.get("demo", False) if demo is None else demo
        include_offline = cfg.get("include_offline", False) if include_offline is None else include_offline
        profile = profile or cfg.get("default_profile", "basic")
        ports = cfg.get("full_ports" if profile == "full" else "basic_ports", [])

        # Expand targets into CIDR networks + metadata
        expanded = self._expand_targets(targets)

        self.running = True
        self._stop = False
        started = datetime.now().isoformat()

        emit = progress or (lambda d: None)
        devices: List[Dict[str, Any]] = []
        total_hosts = sum(t["hosts"] for t in expanded)

        emit({"phase": "start", "targets": [t["label"] for t in expanded], "total_hosts": total_hosts})

        try:
            if demo or (not _have_privileges()) or (not _have_nmap()):
                reason = "demo" if demo else ("no-root" if not _have_privileges() else "no-nmap")
                emit({"phase": "notice", "mode": "simulated", "reason": reason,
                      "message": "Gerçek tarama için root + nmap gerekir; simülasyon modunda çalışılıyor."})
                devices = self._simulate(expanded, emit)
            else:
                devices = self._real_scan(expanded, ports, include_offline, emit)
        finally:
            self.running = False

        finished = datetime.now().isoformat()
        self.last_results = {
            "targets": expanded,
            "devices": devices,
            "started": started,
            "finished": finished,
            "profile": profile,
            "simulated": demo,
            "counts": self._summarize(devices),
        }
        emit({"phase": "done", "counts": self.last_results["counts"], "device_count": len(devices)})
        return self.last_results

    def stop(self):
        self._stop = True

    # ---------------- target expansion ---------------- #
    def _expand_targets(self, targets: List[str]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        seen = set()
        for spec in targets:
            for cidr in parse_targets(spec):
                try:
                    net = ipaddress.IPv4Network(cidr, strict=False)
                except Exception:
                    continue
                key = (str(net.network_address), net.prefixlen, spec)
                if key in seen:
                    continue
                seen.add(key)
                out.append({
                    "spec": spec,
                    "cidr": str(net),
                    "network": str(net.network_address),
                    "prefix": net.prefixlen,
                    "label": f"{spec} ({cidr})",
                    "hosts": net.num_addresses,
                })
        return out

    # ---------------- real scan ---------------- #
    def _real_scan(self, targets, ports, include_offline, emit) -> List[Dict]:
        devices: List[Dict] = []
        for t in targets:
            net = ipaddress.IPv4Network(t["cidr"])
            emit({"phase": "discover", "target": t["label"]})
            live = self._arp_discover(net)
            emit({"phase": "discover-done", "target": t["label"], "found": len(live)})
            with ThreadPoolExecutor(max_workers=self.config.scan.get("max_workers", 64)) as ex:
                futs = [ex.submit(self._probe_host, ip, mac, t, ports, include_offline) for ip, mac in live]
                for i, f in enumerate(as_completed(futs), 1):
                    if self._stop:
                        break
                    dev = f.result()
                    if dev:
                        devices.append(dev)
                        emit({"phase": "host", "target": t["label"], "progress": i, "ip": dev["ip"]})
        return devices

    def _arp_discover(self, net: ipaddress.IPv4Network) -> List[Dict[str, str]]:
        """ARP scan using scapy. Falls back to ping sweep if scapy missing."""
        found: List[Dict[str, str]] = []
        try:
            from scapy.all import ARP, Ether, srp
            ans, _ = srp(Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=str(net)),
                         timeout=2, verbose=0)
            for _, rcv in ans:
                found.append({"ip": rcv.psrc, "mac": rcv.hwsrc})
        except Exception:
            # fallback to ping sweep
            for ip in net.hosts():
                if self._ping(str(ip)):
                    found.append({"ip": str(ip), "mac": "Unknown"})
        return found

    def _ping(self, ip: str, timeout: float = 0.4) -> bool:
        try:
            res = subprocess.run(["ping", "-c", "1", "-W", str(int(timeout)),
                                  ip], capture_output=True, timeout=timeout + 1)
            return res.returncode == 0
        except Exception:
            return False

    def _probe_host(self, ip, mac, target, ports, include_offline) -> Optional[Dict]:
        open_ports = self._tcp_scan(ip, ports)
        if not open_ports and not include_offline:
            return None
        hostname = self._resolve_hostname(ip)
        vendor = self.oui.lookup(mac)
        det = detect_device_type(hostname, vendor, open_ports, self.config.detection)
        return {
            "ip": ip,
            "mac": mac,
            "hostname": hostname,
            "vendor": vendor,
            "open_ports": open_ports,
            "device_type": det["device_type"],
            "confidence": det["confidence"],
            "interface": target["spec"],
            "network": target["cidr"],
            "status": "online" if open_ports else "offline",
            "last_seen": datetime.now().isoformat(),
        }

    def _tcp_scan(self, ip: str, ports: List[int]) -> List[int]:
        try:
            import nmap
            nm = nmap.PortScanner()
            rng = ",".join(map(str, ports))
            nm.scan(ip, rng, arguments="-sT -T4 --max-retries 1 --host-timeout 5s")
            out = []
            if ip in nm.scan_result.get("scan", {}):
                tcp = nm.scan_result["scan"][ip].get("tcp", {})
                out = [p for p, info in tcp.items() if info.get("state") == "open"]
            return out
        except Exception:
            return []

    def _resolve_hostname(self, ip: str) -> str:
        try:
            return socket.gethostbyaddr(ip)[0]
        except Exception:
            return ""

    # ---------------- demo / simulation ---------------- #
    def _simulate(self, targets, emit) -> List[Dict]:
        """Synthesize realistic devices for UI testing without privileges."""
        rng = random.Random(42)  # deterministic
        pool = [
            ("Router", "ASUSTek", "router.local", [22, 53, 80, 443]),
            ("IP Camera", "Hikvision", "cam-front", [80, 443, 554]),
            ("Printer", "HP", "office-printer", [80, 443, 631, 9100]),
            ("Smart TV", "LG", "living-tv", [80, 443, 8001, 8443]),
            ("Laptop", "Apple", "mert-macbook", [22, 445, 548]),
            ("Smartphone", "Apple", "iphone-12", [443]),
            ("NAS", "Synology", "nas-01", [22, 80, 443, 5000]),
            ("Server", "Ubuntu", "srv-web", [22, 80, 443, 3306]),
            ("IoT Device", "Tuya", "smart-plug", [80, 443]),
            ("Gaming Console", "Sony", "ps5", [80, 443, 9307]),
            ("Access Point", "Ubiquiti", "ap-office", [22, 80, 443]),
            ("Desktop", "Dell", "pc-odasi", [3389, 445]),
            ("Switch", "Cisco", "sw-core", [22, 23, 161]),
            ("Raspberry Pi", "Raspberry Pi", "pi-cctv", [22, 80]),
        ]
        devices = []
        for t in targets:
            net = ipaddress.IPv4Network(t["cidr"])
            hosts = list(net.hosts())
            # pick a deterministic subset of hosts to "populate"
            count = min(len(pool), max(3, rng.randint(4, len(pool))))
            chosen = rng.sample(pool, count)
            gateway = str(net.network_address + 1)
            for idx, (dtype, vendor, base_host, ports) in enumerate(chosen):
                ip = str(net.network_address + 2 + idx) if len(hosts) > 2 else gateway
                mac = self._random_mac(rng, vendor)
                hostname = f"{base_host}.{t['spec'].split('.')[0]}" if "." in t["spec"] else base_host
                devices.append({
                    "ip": ip,
                    "mac": mac,
                    "hostname": hostname,
                    "vendor": vendor,
                    "open_ports": ports,
                    "device_type": dtype,
                    "confidence": round(rng.uniform(0.6, 0.98), 2),
                    "interface": t["spec"],
                    "network": t["cidr"],
                    "status": "online",
                    "last_seen": datetime.now().isoformat(),
                    "simulated": True,
                })
                emit({"phase": "host", "target": t["label"], "progress": idx + 1, "ip": ip})
                time.sleep(0.02)
        return devices

    @staticmethod
    def _random_mac(rng, vendor: str) -> str:
        for oui, v in get_oui().cache.items():
            pass
        # use built-in table mapping
        from .oui import BUILTIN_OUI
        match = [k for k, v in BUILTIN_OUI.items() if v.lower() == vendor.lower()]
        if match:
            prefix = match[0].replace(":", "")
        else:
            prefix = "DE:AD:BE"
        prefix = prefix.replace(":", "")[:6]
        suffix = "".join(rng.choice("0123456789ABCDEF") for _ in range(6))
        return f"{prefix[:2]}:{prefix[2:4]}:{prefix[4:6]}:{suffix[0:2]}:{suffix[2:4]}:{suffix[4:6]}"

    # ---------------- helpers ---------------- #
    def _summarize(self, devices: List[Dict]) -> Dict[str, Any]:
        by_type: Dict[str, int] = {}
        by_vendor: Dict[str, int] = {}
        online = 0
        for d in devices:
            by_type[d.get("device_type", "Unknown")] = by_type.get(d.get("device_type", "Unknown"), 0) + 1
            by_vendor[d.get("vendor", "Unknown")] = by_vendor.get(d.get("vendor", "Unknown"), 0) + 1
            if d.get("status") == "online":
                online += 1
        return {"total": len(devices), "online": online, "by_type": by_type, "by_vendor": by_vendor}

    # ---------------- discovery for UI ---------------- #
    def interfaces(self):
        return list_interfaces()

    def vlans(self):
        from .interfaces import vlan_interfaces
        return vlan_interfaces()

    def save_results(self, path: Optional[str] = None):
        path = path or os.path.join(_data_dir(), "scan_results.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.last_results.get("devices", []), fh, indent=2, ensure_ascii=False)
        return path


def _data_dir() -> str:
    env = os.environ.get("HN_DATA_DIR")
    if env:
        return env
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if os.path.exists(os.path.join(here, "hnetwork")):
        return os.path.join(here, "data")
    return os.path.join(os.path.expanduser("~"), ".local", "share", "hnetwork")
