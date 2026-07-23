#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hnetwork command line interface."""
from __future__ import annotations

import argparse
import json
import sys
from .scanner import Scanner


def _print_devices(devices):
    print(f"\n{'IP':<16} {'MAC':<19} {'HOSTNAME':<22} {'VENDOR':<16} {'TYPE':<14} PORTS")
    print("-" * 110)
    for d in devices:
        ports = ",".join(str(p) for p in d.get("open_ports", []))[:40]
        print(f"{d.get('ip',''):<16} {d.get('mac',''):<19} {str(d.get('hostname','')):<22} "
              f"{str(d.get('vendor','')):<16} {str(d.get('device_type','')):<14} {ports}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="hnetwork", description="Multi-interface / multi-VLAN network scanner")
    p.add_argument("targets", nargs="*", help="interface / vlan / cidr (e.g. eth0 eth0.10 192.168.1.0/24)")
    p.add_argument("-p", "--profile", choices=["basic", "full"], default="basic")
    p.add_argument("-o", "--offline", action="store_true", help="include offline hosts")
    p.add_argument("--demo", action="store_true", help="force simulated scan")
    p.add_argument("--list-interfaces", action="store_true", help="list interfaces + vlans and exit")
    p.add_argument("--json", action="store_true", help="output JSON")
    p.add_argument("-s", "--save", help="save results to file")
    args = p.parse_args(argv)

    sc = Scanner()

    if args.list_interfaces:
        iface = sc.interfaces()
        print("INTERFACES:")
        for i in iface:
            vlan = ",".join(str(v) for v in i.get("vlans", [])) or "-"
            print(f"  {i['name']:<14} {i['ip']:<16} {i['cidr']:<18} {i['type']:<9} vlans=[{vlan}]")
        return 0

    if not args.targets:
        # default: scan all non-loopback interfaces
        args.targets = [i["name"] for i in sc.interfaces()]

    results = sc.scan(args.targets, profile=args.profile, include_offline=args.offline, demo=args.demo)
    devices = results["devices"]

    if args.json:
        print(json.dumps(devices, indent=2, ensure_ascii=False))
    else:
        print(f"\nScanned {len(results['targets'])} target(s), found {len(devices)} device(s).")
        _print_devices(devices)

    if args.save:
        with open(args.save, "w", encoding="utf-8") as fh:
            json.dump(devices, fh, indent=2, ensure_ascii=False)
        print(f"Saved -> {args.save}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
