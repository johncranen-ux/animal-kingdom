"""
Animal Kingdom service manager.

Usage:
    python manage.py start    — start backend + frontend, open browser
    python manage.py stop     — stop backend + frontend
    python manage.py status   — show what is running

The backend port defaults to 8000; set AK_PORT to use another one.
Backend output is written to backend.log in the project root.
"""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"
PID_FILE = ROOT / ".pids.json"
LOG_FILE = ROOT / "backend.log"
BACKEND_PORT = int(os.environ.get("AK_PORT", "8000"))
OLLAMA_URL = "http://localhost:11434/api/tags"
BACKEND_URL = f"http://localhost:{BACKEND_PORT}/health"
APP_URL = f"http://localhost:{BACKEND_PORT}"

VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _python() -> str:
    return str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable


def backend_command(port: int) -> list[str]:
    # Not uvicorn's default ProactorEventLoop: on Windows it closes the listening
    # socket for good when clients abort connections while the server is busy.
    return [_python(), "-m", "uvicorn", "app.main:app", "--port", str(port),
            "--loop", "asyncio:SelectorEventLoop"]


def _load_pids() -> dict:
    if PID_FILE.exists():
        try:
            return json.loads(PID_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_pids(pids: dict) -> None:
    PID_FILE.write_text(json.dumps(pids, indent=2))


def _pid_alive(pid: int) -> bool:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True
        )
        return str(pid) in result.stdout
    except Exception:
        return False


def _http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except Exception:
        return False


def _kill(pid: int, label: str) -> None:
    if not _pid_alive(pid):
        print(f"  {label}: already stopped")
        return
    try:
        subprocess.run(["powershell", "-Command", f"Stop-Process -Id {pid} -Force"],
                       capture_output=True)
        print(f"  {label}: stopped (PID {pid})")
    except Exception as e:
        print(f"  {label}: could not stop — {e}")


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _port_owner(port: int) -> tuple[int, str] | None:
    """Return (pid, command line) of the process listening on port, if any."""
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             f"$p = (Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue"
             f" | Select-Object -First 1).OwningProcess; if ($p) {{ $p;"
             f" (Get-CimInstance Win32_Process -Filter \"ProcessId=$p\").CommandLine }}"],
            capture_output=True, text=True
        )
        lines = result.stdout.strip().splitlines()
        if lines and lines[0].strip().isdigit():
            return int(lines[0]), (lines[1].strip() if len(lines) > 1 else "")
    except Exception:
        pass
    return None


def _cmdline(pid: int) -> str:
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine"],
            capture_output=True, text=True
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _is_our_backend(cmdline: str) -> bool:
    return "uvicorn" in cmdline and "app.main:app" in cmdline


def _describe_owner(pid: int, cmdline: str) -> str:
    # Show only the executable name — full command lines can contain credentials.
    exe = Path(cmdline.split('"')[1] if cmdline.startswith('"') else cmdline.split(" ")[0]).name
    return f"PID {pid} ({exe or 'unknown'})"


def _start_bg(args: list[str], cwd: Path) -> subprocess.Popen:
    """Start a process in the background (no console window), logging to LOG_FILE."""
    log = open(LOG_FILE, "w", encoding="utf-8")
    return subprocess.Popen(
        args,
        cwd=str(cwd),
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def _log_tail(lines: int = 15) -> str:
    try:
        return "\n".join(LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except Exception:
        return "(no log output)"


def _wait_for(url: str, label: str, proc: subprocess.Popen | None = None, timeout: int = 30) -> bool:
    print(f"  Waiting for {label}", end="", flush=True)
    for _ in range(timeout):
        if _http_ok(url):
            print(" ✓")
            return True
        if proc is not None and proc.poll() is not None:
            print(f" ✗ exited with code {proc.returncode}")
            return False
        print(".", end="", flush=True)
        time.sleep(1)
    print(" ✗ timed out")
    return False


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_start() -> None:
    pids = _load_pids()

    # ── Ollama check ──────────────────────────────────────────────────────────
    print("Checking Ollama...")
    if _http_ok(OLLAMA_URL):
        print("  Ollama is running ✓")
    else:
        print("  ✗ Ollama is not running.")
        print("    Start it from the AMD AI Bundle in your system tray,")
        print("    then re-run:  python manage.py start")
        sys.exit(1)

    # ── Backend ───────────────────────────────────────────────────────────────
    print("Starting backend...")
    if "backend" in pids and _pid_alive(pids["backend"]):
        print("  Already running ✓")
    else:
        if not _port_free(BACKEND_PORT):
            owner = _port_owner(BACKEND_PORT)
            who = _describe_owner(*owner) if owner else "another process"
            print(f"  ✗ Port {BACKEND_PORT} is already in use by {who}.")
            print("    Stop that process, or pick another port, e.g.:")
            print("      set AK_PORT=8010 && python manage.py start")
            sys.exit(1)
        proc = _start_bg(backend_command(BACKEND_PORT), cwd=BACKEND_DIR)
        pids["backend"] = proc.pid
        _save_pids(pids)
        if not _wait_for(BACKEND_URL, "backend", proc):
            print(f"  Backend did not start. Last lines of {LOG_FILE.name}:\n")
            print(_log_tail())
            sys.exit(1)

    # ── Open browser ──────────────────────────────────────────────────────────
    print(f"\nAll services running. Opening {APP_URL} ...")
    os.startfile(APP_URL)
    print("\nTo stop everything:  python manage.py stop")


def cmd_stop() -> None:
    pids = _load_pids()

    print("Stopping services...")
    for label, pid in pids.items():
        # A stale PID may since have been reused by an unrelated process.
        if _pid_alive(pid) and not _is_our_backend(_cmdline(pid)):
            print(f"  {label}: PID {pid} is no longer ours — skipped")
            continue
        _kill(pid, label)

    # Stop an orphaned backend on the port (started outside manage.py), but
    # never touch an unrelated process that happens to use the same port.
    owner = _port_owner(BACKEND_PORT)
    if owner and owner[0] not in pids.values():
        pid, cmdline = owner
        if _is_our_backend(cmdline):
            _kill(pid, f"backend (port {BACKEND_PORT}, untracked)")
        else:
            print(f"  Port {BACKEND_PORT} is used by {_describe_owner(pid, cmdline)} — not ours, left running")

    PID_FILE.unlink(missing_ok=True)
    print("\nAll services stopped.")


def cmd_status() -> None:
    pids = _load_pids()

    print(f"{'Service':<12} {'PID':<8} {'Process':<10} {'HTTP'}")
    print("-" * 45)

    def row(label, pid, url):
        alive = _pid_alive(pid) if pid else False
        http  = _http_ok(url) if url else "—"
        pid_s = str(pid) if pid else "—"
        proc  = "alive" if alive else "dead"
        http_s = "ok" if http is True else ("✗" if http is False else "—")
        print(f"  {label:<10} {pid_s:<8} {proc:<10} {http_s}")

    ollama_pid = pids.get("ollama")
    ollama_ok = _http_ok(OLLAMA_URL)
    print(f"  {'ollama':<10} {'—':<8} {'—':<10} {'ok' if ollama_ok else '✗'}")

    for label, url in [("backend", BACKEND_URL)]:
        pid = pids.get(label)
        row(label, pid, url)


# ── Entry point ───────────────────────────────────────────────────────────────

COMMANDS = {"start": cmd_start, "stop": cmd_stop, "status": cmd_status}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in COMMANDS:
        print(__doc__)
        sys.exit(0)
    COMMANDS[cmd]()
