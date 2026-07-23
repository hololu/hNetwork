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
import socket
import subprocess
import threading
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
    ) -> Dict[str, Any]:
        """Run a scan over a list of target specs (interface / vlan / cidr).

        Returns a results dict and also stores it in ``self.last_results``.
        """
        if self.running:
            raise RuntimeError("A scan is already running")

        cfg = self.config.scan
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
            if _have_privileges() and _have_nmap():
                emit({"phase": "notice", "mode": "real",
                      "message": "Gerçek tarama (ARP + nmap) başlıyor."})
                devices = self._real_scan(expanded, ports, include_offline, emit)
            else:
                emit({"phase": "notice", "mode": "real-lite",
                      "message": "Root/nmap yok → saf-Python gerçek tarama (ping sweep + TCP socket + ARP tablosu)."})
                devices = self._real_scan_pure(expanded, ports, include_offline, emit)
        finally:
            self.running = False

        finished = datetime.now().isoformat()
        self.last_results = {
            "targets": expanded,
            "devices": devices,
            "started": started,
            "finished": finished,
            "profile": profile,
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

    # ---------------- real scan (root + nmap) ---------------- #
    def _real_scan(self, targets, ports, include_offline, emit) -> List[Dict]:
        devices: List[Dict] = []
        for t in targets:
            if self._stop:
                break
            net = ipaddress.IPv4Network(t["cidr"])
            emit({"phase": "discover", "target": t["label"], "message": f"Keşif: {t['label']}"})
            live = self._arp_discover(net)
            emit({"phase": "discover-done", "target": t["label"], "found": len(live)})
            with ThreadPoolExecutor(max_workers=self.config.scan.get("max_workers", 64)) as ex:
                futs = [ex.submit(self._probe_host, h["ip"], h["mac"], t, ports, include_offline)
                        for h in live]
                for i, f in enumerate(as_completed(futs), 1):
                    if self._stop:
                        break
                    dev = f.result()
                    if dev:
                        devices.append(dev)
                        emit({"phase": "host", "target": t["label"], "progress": i, "ip": dev["ip"]})
        return devices

    # ---------------- real scan (pure python, no root/nmap) ---------------- #
    def _real_scan_pure(self, targets, ports, include_offline, emit) -> List[Dict]:
        """Real scan without root or nmap.

        Strategy per target network:
          1. Concurrent ping sweep (system `ping`, no privileges needed) to
             find live hosts. This also fills the kernel ARP/neighbour cache.
          2. Read MAC addresses from `ip neigh` (ARP table).
          3. Concurrent pure-python TCP connect() port scan for each live host.
        """
        devices: List[Dict] = []
        max_workers = self.config.scan.get("max_workers", 128)
        n_targets = len(targets)
        for ti, t in enumerate(targets):
            if self._stop:
                break
            # each target occupies an equal slice of the 0-100 bar
            base = (ti / n_targets) * 100 if n_targets else 0
            span = (1 / n_targets) * 100 if n_targets else 100
            net = ipaddress.IPv4Network(t["cidr"])
            hosts = list(net.hosts()) if net.num_addresses > 2 else [net.network_address]
            # Guard against absurdly large ranges (e.g. /16 = 65k hosts)
            if len(hosts) > 4096:
                emit({"phase": "notice",
                      "message": f"{t['label']} çok geniş ({len(hosts)} host); ilk 4096 host taranıyor."})
                hosts = hosts[:4096]

            total = max(1, len(hosts))
            emit({"phase": "discover", "target": t["label"], "percent": round(base, 1),
                  "message": f"Ping sweep: {t['label']} ({len(hosts)} host)"})

            # --- 1. ping sweep (find live hosts) : slice 0-55% of this target ---
            live_ips: List[str] = []
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                fut = {ex.submit(self._ping, str(ip)): str(ip) for ip in hosts}
                done = 0
                for f in as_completed(fut):
                    if self._stop:
                        break
                    done += 1
                    if f.result():
                        live_ips.append(fut[f])
                    if done % 16 == 0 or done == total:
                        pct = base + span * 0.55 * (done / total)
                        emit({"phase": "progress", "target": t["label"], "percent": round(pct, 1),
                              "message": f"{t['label']}: {done}/{total} ping · {len(live_ips)} canlı"})
            live_ips.sort(key=lambda x: tuple(int(p) for p in x.split(".")))
            emit({"phase": "discover-done", "target": t["label"], "found": len(live_ips),
                  "percent": round(base + span * 0.55, 1),
                  "message": f"{t['label']}: {len(live_ips)} canlı host bulundu"})

            # --- 2. ARP table (MAC addresses) ---
            arp_table = self._read_arp_table()

            # --- 3. port scan + enrich : slice 55-100% of this target ---
            n_live = max(1, len(live_ips))
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                futs = {ex.submit(self._probe_host_pure, ip, arp_table.get(ip, "Unknown"),
                                  t, ports, include_offline): ip for ip in live_ips}
                for i, f in enumerate(as_completed(futs), 1):
                    if self._stop:
                        break
                    dev = f.result()
                    if dev:
                        devices.append(dev)
                    pct = base + span * (0.55 + 0.45 * (i / n_live))
                    emit({"phase": "host", "target": t["label"], "progress": i,
                          "percent": round(pct, 1), "device_count": len(devices),
                          "ip": dev["ip"] if dev else ""})
        emit({"phase": "scanning-done", "percent": 100.0})
        return devices

    def _probe_host_pure(self, ip, mac, target, ports, include_offline) -> Optional[Dict]:
        open_ports = self._tcp_scan_pure(ip, ports)
        # host answered ping -> it is online even with no open ports
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
            "status": "online",
            "last_seen": datetime.now().isoformat(),
        }

    def _tcp_scan_pure(self, ip: str, ports: List[int], timeout: float = 0.6) -> List[int]:
        """Pure-python TCP connect scan (no root, no nmap)."""
        open_ports: List[int] = []
        for port in ports:
            if self._stop:
                break
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            try:
                if s.connect_ex((ip, port)) == 0:
                    open_ports.append(port)
            except Exception:
                pass
            finally:
                s.close()
        return open_ports

    def _read_arp_table(self) -> Dict[str, str]:
        """Read IP->MAC mapping from the kernel neighbour/ARP cache."""
        table: Dict[str, str] = {}
        out = None
        try:
            res = subprocess.run(["ip", "neigh", "show"], capture_output=True, text=True, timeout=5)
            out = res.stdout
        except Exception:
            try:
                res = subprocess.run(["arp", "-an"], capture_output=True, text=True, timeout=5)
                out = res.stdout
            except Exception:
                out = None
        if not out:
            return table
        import re as _re
        for line in out.splitlines():
            ipm = _re.search(r"(\d+\.\d+\.\d+\.\d+)", line)
            macm = _re.search(r"([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})", line)
            if ipm and macm:
                table[ipm.group(1)] = macm.group(1).upper()
        return table

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

    def _ping(self, ip: str, timeout: float = 1.0) -> bool:
        try:
            w = max(1, int(round(timeout)))
            res = subprocess.run(["ping", "-c", "1", "-W", str(w), ip],
                                 capture_output=True, timeout=w + 2)
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
