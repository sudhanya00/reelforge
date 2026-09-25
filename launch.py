"""Start ReelForge: build the UI if needed, start the local server, open the browser.

  python launch.py              # normal
  python launch.py --demo       # fake model, nothing billed, separate projects-demo/ folder
  python launch.py --rebuild    # force a rebuild of the web UI
  python launch.py --shortcut   # put a ReelForge shortcut on the desktop
  python launch.py --no-browser

Double-clicking ReelForge.bat does the same as the first line.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
DEFAULT_PORT = 8765


def say(msg: str) -> None:
    print(f"  {msg}", flush=True)


def refresh_path() -> None:
    """Pick up tools installed since this shell started (e.g. ffmpeg via winget) on Windows."""
    if os.name != "nt":
        return
    import winreg
    parts = []
    for hive, key in ((winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
                      (winreg.HKEY_CURRENT_USER, r"Environment")):
        try:
            with winreg.OpenKey(hive, key) as k:
                parts += os.path.expandvars(winreg.QueryValueEx(k, "Path")[0]).split(";")
        except OSError:
            pass
    current = os.environ.get("PATH", "").split(os.pathsep)
    os.environ["PATH"] = os.pathsep.join(current + [p for p in parts if p and p not in current])


def ensure_python_deps() -> None:
    try:
        import fastapi, uvicorn, google.genai, dotenv, PIL  # noqa: F401,E401
    except ImportError:
        say("Installing Python packages (one time)…")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements.txt")], check=True)


def ui_needs_build() -> bool:
    built = WEB / "out" / "index.html"
    if not built.exists():
        return True
    newest = max(p.stat().st_mtime for d in ("app", "components", "lib") for p in (WEB / d).rglob("*") if p.is_file())
    newest = max(newest, *((WEB / f).stat().st_mtime for f in ("package.json", "next.config.ts") if (WEB / f).exists()))
    return newest > built.stat().st_mtime


def build_ui(force: bool) -> None:
    if not force and not ui_needs_build():
        return
    npm = shutil.which("npm")
    if not npm:
        if (WEB / "out" / "index.html").exists():
            say("Node.js not found; using the existing UI build.")
            return
        sys.exit("ReelForge needs Node.js once to build its UI: https://nodejs.org (LTS), then run this again.")
    if not (WEB / "node_modules").exists():
        say("Installing UI packages (one time, ~1 min)…")
        subprocess.run([npm, "install", "--no-audit", "--no-fund", "--loglevel=error"], cwd=WEB, check=True)
    say("Building the UI (~1 min, only after updates)…")
    subprocess.run([npm, "run", "build", "--silent"], cwd=WEB, check=True,
                   env={**os.environ, "NEXT_TELEMETRY_DISABLED": "1"})


def reelforge_at(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=1) as r:
            return "settings" in json.loads(r.read())
    except Exception:  # noqa: BLE001
        return False


def port_free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def make_shortcut() -> None:
    if os.name != "nt":
        sys.exit("--shortcut is Windows only.")
    target = ROOT / "ReelForge.bat"
    ps = (
        "$d=[Environment]::GetFolderPath('Desktop');"
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut(\"$d\\ReelForge.lnk\");"
        f"$s.TargetPath='{target}';$s.WorkingDirectory='{ROOT}';$s.WindowStyle=7;"
        "$s.IconLocation='%SystemRoot%\\System32\\imageres.dll,18';$s.Description='ReelForge';$s.Save()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
    say("Added ReelForge to your desktop.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Start ReelForge")
    ap.add_argument("--demo", action="store_true", help="fake model; nothing is billed")
    ap.add_argument("--rebuild", action="store_true", help="rebuild the web UI")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--shortcut", action="store_true", help="create a desktop shortcut and exit")
    a = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")

    print("\n  ReelForge\n")
    if a.shortcut:
        make_shortcut()
        return

    port = a.port
    if reelforge_at(port):
        say(f"Already running — opening http://localhost:{port}")
        if not a.no_browser:
            webbrowser.open(f"http://localhost:{port}")
        return
    while not port_free(port):
        port += 1

    refresh_path()
    ensure_python_deps()
    build_ui(a.rebuild)

    import uvicorn
    import server
    server.CONFIG["projects"] = ROOT / ("projects-demo" if a.demo else "projects")
    server.CONFIG["fake"] = a.demo
    if a.demo:  # fake timings must never feed real progress estimates
        server.STATS_PATH = server.CONFIG["projects"] / "stats.json"
    server.mount_web()
    if not shutil.which("ffmpeg"):
        say("Note: ffmpeg not found — continuous scenes, posters and stitching need it.")
    if a.demo:
        say("Demo mode: fake model, nothing is billed. Films go to projects-demo/.")

    address = f"http://localhost:{port}"

    def open_when_ready():
        for _ in range(100):
            if reelforge_at(port):
                say(f"Open at {address}   (Ctrl+C here to stop)\n")
                if not a.no_browser:
                    webbrowser.open(address)
                return
            time.sleep(0.2)

    threading.Thread(target=open_when_ready, daemon=True).start()
    uvicorn.run(server.app, host="127.0.0.1", port=port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
