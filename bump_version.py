#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Versiyonu otomatik artırır (patch seviyesi).

Kullanım:
    python bump_version.py            # 2.0.0 -> 2.0.1
    python bump_version.py --minor   # 2.0.0 -> 2.1.0
    python bump_version.py --major   # 2.0.0 -> 3.0.0
    python bump_version.py --set 2.5.3

hnetwork/__init__.py icindeki __version__ degiskenini gunceller.
pyproject.toml'deki version satirini da senkron tutar.
"""
import re
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
INIT = os.path.join(HERE, "hnetwork", "__init__.py")
PYPROJECT = os.path.join(HERE, "pyproject.toml")


def read_version():
    with open(INIT, encoding="utf-8") as f:
        for line in f:
            m = re.match(r'\s*__version__\s*=\s*["\']([\d]+\.[\d]+\.[\d]+)["\']', line)
            if m:
                return m.group(1)
    raise RuntimeError("__version__ bulunamadı: " + INIT)


def bump(ver, mode="patch"):
    major, minor, patch = (int(x) for x in ver.split("."))
    if mode == "major":
        major += 1; minor = 0; patch = 0
    elif mode == "minor":
        minor += 1; patch = 0
    else:
        patch += 1
    return f"{major}.{minor}.{patch}"


def write_version(new_ver):
    # __init__.py
    with open(INIT, encoding="utf-8") as f:
        src = f.read()
    src = re.sub(r'(__version__\s*=\s*["\'])([\d.]+)(["\'])',
                 r'\g<1>' + new_ver + r'\g<3>', src, count=1)
    with open(INIT, "w", encoding="utf-8") as f:
        f.write(src)
    # pyproject.toml
    if os.path.exists(PYPROJECT):
        with open(PYPROJECT, encoding="utf-8") as f:
            pp = f.read()
        pp = re.sub(r'(version\s*=\s*["\'])([\d.]+)(["\'])',
                    r'\g<1>' + new_ver + r'\g<3>', pp, count=1)
        with open(PYPROJECT, "w", encoding="utf-8") as f:
            f.write(pp)


def main():
    mode = "patch"
    new_ver = None
    for arg in sys.argv[1:]:
        if arg == "--major":
            mode = "major"
        elif arg == "--minor":
            mode = "minor"
        elif arg.startswith("--set"):
            new_ver = arg.split("=")[1] if "=" in arg else sys.argv[sys.argv.index(arg) + 1]
    old = read_version()
    if new_ver is None:
        new_ver = bump(old, mode)
    write_version(new_ver)
    print(f"Versiyon: {old} -> {new_ver}")


if __name__ == "__main__":
    main()
