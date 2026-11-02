#!/usr/bin/env python3
"""One-terminal native Apparel setup/start; no Docker or browser downloads."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import secrets
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from functools import lru_cache
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "agents" / "apparel-attribution" / "Backend"
FRONTEND = ROOT / "frontend"
STATE_MARKER = "karix-apparel-local-v1\n"
BASE_PORTS = {"portal": 3000, "api": 8000}
SECRET_KEYS = ("JWT_SECRET",)
SOURCE_NAMES = (
    "app", "components", "lib", "public", "pages", "styles", "middleware.ts", "middleware.js",
    "next.config.mjs", "next.config.js", "next.config.ts", "postcss.config.mjs", "postcss.config.js",
    "tailwind.config.ts", "tailwind.config.js", "tsconfig.json", "next-env.d.ts",
    "package.json", "package-lock.json",
)


class LocalError(Exception):
    """An actionable error safe to display without subprocess output or secrets."""


@lru_cache(maxsize=1)
def private_storage():
    spec = importlib.util.spec_from_file_location("apparel_local_storage", WORKER / "app/core/local_storage.py")
    if spec is None or spec.loader is None:
        raise LocalError("Private storage helper is missing. Update this checkout and try again.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def strong_secret(value: str, *, jwt: bool = False) -> bool:
    if not (32 <= len(value) <= 512 and value.isascii() and all(33 <= ord(c) <= 126 for c in value)):
        return False
    if len(set(value)) < (16 if jwt else 10):
        return False
    if re.search(r"change.?me|placeholder|replace.?me|your[-_ ]|example|default", value, re.I):
        return False
    if value == "karix_whitelisting_secure_jwt_secret_key_2026_prod":
        return False
    return not any(value == (value[:n] * ((len(value) + n - 1) // n))[:len(value)]
                   for n in range(1, len(value) // 2 + 1))


def read_env(path: Path) -> dict[str, str]:
    values = {}
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except UnicodeError:
        raise LocalError("The private .env file must use UTF-8 text. Ask your administrator to correct its encoding; its contents were not printed or overwritten.") from None
    for line in lines:
        line = line.strip()
        if line.startswith("export "):
            line = line[7:].strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if key not in SECRET_KEYS:
            continue  # Never import another company's credentials into this local runtime.
        if key in values:
            raise LocalError(f"Keep exactly one {key} entry in the private .env file.")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def validate_env(values: dict[str, str]) -> None:
    for key in SECRET_KEYS:
        if not strong_secret(values.get(key, ""), jwt=key == "JWT_SECRET"):
            raise LocalError(f"Private .env needs a strong {key}. Run setup for missing entries; existing weak/empty values must be explicitly replaced, not reused.")


def initialize_env(path: Path) -> dict[str, str]:
    """Generate only absent secrets, preserving all existing file bytes/settings."""
    storage = private_storage()
    storage.private_file(path)
    values = read_env(path)
    for key, value in values.items():
        if not strong_secret(value, jwt=key == "JWT_SECRET"):
            raise LocalError(f"Existing {key} is empty or weak. Replace that entry with a strong private value before setup; it was not overwritten.")
    additions = []
    for key in SECRET_KEYS:
        if key not in values:
            value = secrets.token_urlsafe(48)
            while not strong_secret(value, jwt=key == "JWT_SECRET"):
                value = secrets.token_urlsafe(48)
            values[key] = value
            additions.append(f"{key}={value}\n")
    if additions:
        with path.open("ab") as destination:
            if destination.tell():
                destination.write(b"\n")
            destination.write("".join(additions).encode("ascii"))
            destination.flush()
            os.fsync(destination.fileno())
    return values


def make_runtime(data_dir: Path | None = None, port_offset: int = 0) -> dict:
    if not 0 <= port_offset <= 65535 - max(BASE_PORTS.values()):
        raise LocalError("--port-offset is outside the supported TCP port range.")
    if data_dir is None:
        checkout = hashlib.sha256(str(ROOT).encode("utf-8")).hexdigest()[:12]
        base = (Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "Karix/Apparel"
                if os.name == "nt" else Path.home() / ".karix-apparel")
        state = base / checkout
        env_file = ROOT / ".env"
    else:
        # Never chmod, clean, or interpret the caller's arbitrary directory itself.
        state = data_dir.expanduser().absolute() / "apparel-local"
        env_file = state / ".env"
    return {"state": state, "env_file": env_file,
            "ports": {name: port + port_offset for name, port in BASE_PORTS.items()}}


def prepare_state(runtime: dict) -> None:
    state = runtime["state"]
    marker = state / ".apparel-local-state"
    if state.is_symlink() or (hasattr(state, "is_junction") and state.is_junction()):
        raise LocalError("The Apparel state folder must not be a link to another folder.")
    if state.exists():
        if not state.is_dir():
            raise LocalError("The Apparel state path is not a directory. Choose another --data-dir.")
        if marker.is_symlink() or not marker.is_file() or marker.read_bytes() not in (
            STATE_MARKER.encode("ascii"), STATE_MARKER.replace("\n", "\r\n").encode("ascii")
        ):
            if any(state.iterdir()):
                raise LocalError("Refusing an existing unmarked Apparel state folder. Choose an empty --data-dir; existing files were not changed.")
    storage = private_storage()
    storage.private_directory(state)
    storage.private_file(marker)
    marker.write_bytes(STATE_MARKER.encode("ascii"))
    for name in ("backend", "worker", "frontend", "logs"):
        storage.private_directory(state / name)


def environment(runtime: dict, service: str, values: dict[str, str]) -> dict[str, str]:
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "HOME", "USERPROFILE",
               "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL",
               "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS"}
    if service == "api":
        allowed.update({"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "CURL_CA_BUNDLE"})
    result = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    result.update(PYTHONUTF8="1", PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1")
    ports, state = runtime["ports"], runtime["state"]
    if service == "api":
        result.update(values)
        result.update(PYTHONPATH=os.pathsep.join((str(ROOT / "backend"), str(ROOT))),
                      KARIX_DB_PATH=str(state / "backend/karix_store.db"),
                      APPAREL_ATTRIBUTION_STORAGE_DIR=str(state / "worker"),
                      ALLOWED_ORIGINS=f"http://127.0.0.1:{ports['portal']}")
    elif service == "portal":
        result.update(BACKEND_INTERNAL_URL=f"http://127.0.0.1:{ports['api']}",
                      NODE_ENV="development", NEXT_TELEMETRY_DISABLED="1")
    elif service != "portal":
        raise ValueError("Unknown local service")
    return result


def venv_python() -> Path:
    return ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def npm_command(node: str, npm: str) -> list[str]:
    if os.name != "nt":
        return [npm]
    # Run npm's JS entrypoint with node.exe, not a .cmd shim requiring shell quoting.
    for directory in (Path(npm).parent, Path(node).parent):
        cli = directory / "node_modules/npm/bin/npm-cli.js"
        if cli.is_file():
            return [node, str(cli)]
    raise LocalError("The installed npm CLI is missing. Reinstall Node.js 22 LTS or newer from nodejs.org and reopen your terminal.")


def quiet_run(command, *, cwd: Path, env: dict | None = None, failure: str) -> None:
    try:
        completed = subprocess.run(command, cwd=cwd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        raise LocalError(failure) from None
    if completed.returncode:
        raise LocalError(failure)


def prerequisites() -> tuple[str, str]:
    if sys.version_info < (3, 11):
        raise LocalError("Install Python 3.12 from python.org (enable Add Python to PATH), reopen Git Bash, and run: py -3.12 scripts/apparel_local.py setup")
    node, npm = shutil.which("node"), shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not node or not npm:
        raise LocalError("Install Node.js 22 LTS or newer from nodejs.org, reopen Git Bash, and rerun this command.")
    try:
        version = subprocess.check_output([node, "--version"], text=True, stderr=subprocess.DEVNULL).strip()
        major = int(version.lstrip("v").split(".", 1)[0])
    except (OSError, ValueError, subprocess.CalledProcessError):
        raise LocalError("Node could not report its version. Reinstall Node.js 22 LTS or newer and reopen Git Bash.") from None
    if major < 22:
        raise LocalError("Node.js 22 LTS or newer is required. Update Node from nodejs.org, reopen Git Bash, and rerun this command.")
    return node, npm


def require_venv() -> Path:
    python = venv_python()
    if not python.is_file():
        raise LocalError("Local Python dependencies are missing. Run: python scripts/apparel_local.py setup")
    try:
        version = subprocess.check_output([str(python), "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
                                          text=True, stderr=subprocess.DEVNULL).strip()
        if tuple(map(int, version.split("."))) < (3, 11):
            raise LocalError("The existing .venv uses an older Python. Keep a backup of it, create .venv with Python 3.12, then rerun setup.")
    except (OSError, ValueError, subprocess.CalledProcessError):
        raise LocalError("The existing .venv cannot run on this device. Keep a backup, create .venv with Python 3.12, then rerun setup.") from None
    return python


def has_apparel_admin(runtime: dict) -> bool:
    path = runtime["state"] / "backend/karix_store.db"
    if not path.exists():
        return False
    try:
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
            if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'").fetchone():
                return False
            return bool(connection.execute("SELECT 1 FROM users WHERE tenant_id='apparel' AND role='admin' AND is_active=1 LIMIT 1").fetchone())
    except sqlite3.Error:
        raise LocalError("The local account database cannot be read. Keep the data folder; ask your administrator to repair it before setup.") from None


def provision_admin(runtime: dict, python: Path, values: dict[str, str]) -> None:
    if has_apparel_admin(runtime):
        print("Your Apparel administrator is already set up; existing accounts are unchanged.")
        return
    if not sys.stdin.isatty():
        raise LocalError("First setup needs an interactive terminal for a hidden password. On Windows, open PowerShell and run: py -3.12 scripts/apparel_local.py setup (include the same --data-dir if used).")
    print("Create your first Apparel administrator (no password is supplied or saved by this helper).")
    name = input("Administrator name: ").strip()
    email = input("Administrator email: ").strip()
    if not name or not email:
        raise LocalError("Administrator name and email are required. Rerun setup; your configuration is preserved.")
    # Fail before getpass can fall back to echoing a password in an unsupported terminal.
    bootstrap = ("import getpass\n"
                 "def require_hidden(*args, **kwargs):\n"
                 "    raise ValueError('Hidden password entry is unavailable. Rerun setup in PowerShell or a real console.')\n"
                 "getpass.fallback_getpass = require_hidden\n"
                 "from auth import bootstrap_cli\n"
                 "bootstrap_cli()\n")
    completed = subprocess.run([str(python), "-c", bootstrap, "--email", email, "--name", name, "--tenant", "apparel"],
                               cwd=runtime["state"] / "backend", env=environment(runtime, "api", values))
    if completed.returncode:
        raise LocalError("Administrator creation did not finish. Rerun setup with a valid email and matching 12+ character password. If hidden entry is unavailable in Git Bash, use PowerShell.")


def setup(runtime: dict) -> None:
    node, npm = prerequisites()
    print("Installing local dependencies (existing .venv and npm cache are reused)…", flush=True)
    if not venv_python().is_file():
        if (ROOT / ".venv").exists():
            raise LocalError("An incompatible .venv already exists. Keep a backup of it, create .venv with Python 3.12, then rerun setup.")
        quiet_run([sys.executable, "-m", "venv", str(ROOT / ".venv")], cwd=ROOT,
                  failure="Could not create .venv. Install Python 3.12 from python.org and rerun setup.")
    python = require_venv()
    quiet_run([str(python), "-m", "pip", "install", "-r", str(ROOT / "requirements.txt"),
               "-r", str(WORKER / "requirements.txt")], cwd=ROOT,
              failure="Python dependency installation failed. Check your internet/company package access and rerun setup with Python 3.12.")
    quiet_run([*npm_command(node, npm), "ci", "--legacy-peer-deps"], cwd=FRONTEND,
              failure="Frontend dependency installation failed. Check your internet/company npm access and rerun setup with Node.js 22 LTS or newer.")
    prepare_state(runtime)
    with private_storage().worker_storage_lock(runtime["state"]):
        values = initialize_env(runtime["env_file"])
        provision_admin(runtime, python, values)
    invocation = f"py -{sys.version_info.major}.{sys.version_info.minor}" if os.name == "nt" else "python3"
    print(f"Ready. Run: {invocation} scripts/apparel_local.py start (reuse any --data-dir/--port-offset options).")
    print("Invite colleagues in Settings > Organization Team Directory > Add Colleague, with the Operator role.")


def check_ports(ports: dict[str, int]) -> None:
    reservations = []
    try:
        for name, port in ports.items():
            connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            reservations.append(connection)
            if os.name == "nt":
                connection.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                connection.bind(("127.0.0.1", port))
            except OSError:
                raise LocalError(f"Port {port} ({name}) is already in use. Close your own previous launcher, or choose --port-offset; no existing service was stopped.") from None
    finally:
        for connection in reservations:
            connection.close()


def stage_frontend(runtime: dict) -> Path:
    """Stage only source, never credentials or existing build/profile state."""
    destination = runtime["state"] / "frontend"
    modules = FRONTEND / "node_modules"
    if not (modules / "next/dist/bin/next").is_file():
        raise LocalError("Frontend dependencies are missing. Run: python scripts/apparel_local.py setup")
    patterns = shutil.ignore_patterns(".env*", "node_modules", ".next", "__pycache__", "*.tsbuildinfo",
                                     "*credentials*.json", "google-service-account*.json")
    def ignored(directory, names):
        excluded = patterns(directory, names)
        if any((Path(directory) / name).is_symlink() for name in names if name not in excluded):
            raise LocalError("Frontend source links are not supported by the native launcher.")
        return excluded
    for name in SOURCE_NAMES:
        target, source = destination / name, FRONTEND / name
        if target.is_symlink():
            raise LocalError("A staged source path is a link. Choose a clean --data-dir; no linked files were removed.")
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        if source.is_symlink():
            raise LocalError("Frontend source links are not supported by the native launcher.")
        if source.is_dir():
            shutil.copytree(source, target, ignore=ignored)
        elif source.is_file():
            shutil.copy2(source, target)
    link = destination / "node_modules"
    if link.exists() or link.is_symlink():
        if link.resolve() != modules.resolve():
            raise LocalError("Staged node_modules does not point to this checkout. Choose a clean --data-dir; nothing was removed.")
    elif os.name == "nt":
        # A directory junction needs no Administrator/developer-mode privilege.
        if any(character in str(link) + str(modules) for character in ('"', '%', '\n', '\r')):
            raise LocalError("Use checkout/data paths without percent signs or quotes for the Windows dependency junction.")
        comspec = os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe")
        quiet_run(f'"{comspec}" /d /v:off /c mklink /J "{link}" "{modules}"', cwd=ROOT,
                  failure="Could not reuse node_modules. Choose a writable local --data-dir and rerun start.")
    else:
        link.symlink_to(modules, target_is_directory=True)
    return destination


class Children:
    """Own child process groups on Unix, and an entire child job on Windows."""

    def __init__(self, runtime: dict):
        self.runtime = runtime
        self.processes = []
        self.job = None
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            for name, argtypes, restype in (
                ("CreateJobObjectW", [ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
                ("AssignProcessToJobObject", [wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
                ("TerminateJobObject", [wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
                ("CloseHandle", [wintypes.HANDLE], wintypes.BOOL),
            ):
                function = getattr(self.kernel, name)
                function.argtypes, function.restype = argtypes, restype
            self.job = self.kernel.CreateJobObjectW(None, None)
            if not self.job:
                raise LocalError("Windows could not create a private child-process job. Run from a normal PowerShell terminal.")
            class BasicLimits(ctypes.Structure):
                _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                            ("flags", wintypes.DWORD), ("minimum_set", ctypes.c_size_t),
                            ("maximum_set", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
                            ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                            ("scheduling", wintypes.DWORD)]
            class ExtendedLimits(ctypes.Structure):
                _fields_ = [("basic", BasicLimits), ("io", ctypes.c_uint64 * 6),
                            ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                            ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]
            self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
            self.kernel.SetInformationJobObject.restype = wintypes.BOOL
            limits = ExtendedLimits()
            limits.basic.flags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not self.kernel.SetInformationJobObject(self.job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                self.kernel.CloseHandle(self.job)
                self.job = None
                raise LocalError("Windows could not protect child-process cleanup. Run from a normal local terminal.")

    def launch(self, name: str, command: list[str], cwd: Path, env: dict) -> None:
        path = self.runtime["state"] / "logs" / f"{name}.log"
        private_storage().private_file(path)
        if os.name == "nt":
            # Gate startup until the child broker belongs to our Windows job.
            broker = ("import json, subprocess, sys\n"
                      "if sys.stdin.buffer.read(1) != b'\\n': sys.exit(1)\n"
                      "sys.exit(subprocess.call(json.loads(sys.argv[1]), stdin=subprocess.DEVNULL))\n")
            command = [sys.executable, "-c", broker, json.dumps(command)]
        with path.open("wb") as log:
            process = subprocess.Popen(command, cwd=cwd, env=env,
                                       stdin=subprocess.PIPE if os.name == "nt" else subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=os.name != "nt",
                                       creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
        self.processes.append((name, process, path))
        if os.name == "nt":
            try:
                if not self.kernel.AssignProcessToJobObject(self.job, int(process._handle)):
                    raise LocalError(f"Windows could not supervise {name}. Run from PowerShell.")
                process.stdin.write(b"\n")
                process.stdin.close()
            except (OSError, LocalError):
                process.terminate()
                process.wait()
                process.stdin.close()
                raise

    def require_alive(self) -> None:
        for name, process, path in self.processes:
            if process.poll() is not None:
                raise LocalError(f"{name} stopped before the launcher finished. Private diagnostic log: {path}. Check prerequisites and rerun start; no unrelated service was stopped.")

    def close(self) -> None:
        for _, process, _ in reversed(self.processes):
            try:
                if os.name == "nt":
                    if process.poll() is None:
                        process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    os.killpg(process.pid, signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass
        deadline = time.monotonic() + 6
        for _, process, _ in self.processes:
            try:
                process.wait(timeout=max(0.01, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                pass
        if os.name == "nt":
            if self.job:
                self.kernel.TerminateJobObject(self.job, 0)
                self.kernel.CloseHandle(self.job)
                self.job = None
        else:
            # A parent may have exited while leaving descendants in its own group.
            for _, process, _ in self.processes:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    pass
        for _, process, _ in self.processes:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass


def http_json(url: str, *, headers: dict | None = None, method: str = "GET", timeout: float = 3) -> dict:
    # Never send local debugger/token requests through an inherited corporate proxy.
    opener = build_opener(ProxyHandler({}))
    with opener.open(Request(url, headers=headers or {}, method=method), timeout=timeout) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError("Local service did not return a JSON object")
    return payload


def wait_ready(children: Children, name: str, check, *, timeout: float = 180) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        children.require_alive()
        try:
            if check():
                children.require_alive()
                return
        except (URLError, OSError, ValueError, TimeoutError):
            pass
        time.sleep(0.25)
    raise LocalError(f"{name} did not become ready. See its private log in {children.runtime['state'] / 'logs'}; check company security policy and rerun start.")




def login_ready(url: str) -> bool:
    with build_opener(ProxyHandler({})).open(url + "/login", timeout=10) as response:
        return response.status == 200 and "text/html" in response.headers.get("Content-Type", "")


def start(runtime: dict) -> None:
    node, _ = prerequisites()
    python = require_venv()
    check_ports(runtime["ports"])
    prepare_state(runtime)
    env_file = runtime["env_file"]
    if not env_file.is_file():
        raise LocalError("Private .env is missing. Run setup with the same --data-dir, then start again.")
    private_storage().private_file(env_file)
    values = read_env(env_file)
    validate_env(values)
    with private_storage().worker_storage_lock(runtime["state"]):
        frontend = stage_frontend(runtime)
        children = Children(runtime)
        ports, state = runtime["ports"], runtime["state"]
        portal_url = f"http://127.0.0.1:{ports['portal']}"
        api_url = f"http://127.0.0.1:{ports['api']}"
        try:
            print("Starting Apparel portal and main API; attribution uses direct HTTP…", flush=True)
            children.launch("api", [str(python), "-m", "uvicorn", "api:app", "--host", "127.0.0.1",
                                    "--port", str(ports["api"]), "--loop", "asyncio", "--no-access-log"],
                            state / "backend", environment(runtime, "api", values))
            wait_ready(children, "API", lambda: http_json(api_url + "/healthz").get("service") == "karix-whitelisting-api")
            children.launch("portal", [node, str(FRONTEND / "node_modules/next/dist/bin/next"), "dev", str(frontend),
                                       "--hostname", "127.0.0.1", "--port", str(ports["portal"])],
                            frontend, environment(runtime, "portal", values))
            wait_ready(children, "portal", lambda: http_json(portal_url + "/api/health", timeout=30).get("service") == "karix-whitelisting-api", timeout=240)
            wait_ready(children, "portal sign-in", lambda: login_ready(portal_url))
            print(f"Ready: {portal_url}/apparel/attribution — Ctrl+C stops these local services.")
            print("Connect Apparel Auth Sync in Settings > MoEngage. No dedicated Chrome or hosted browser is needed.")
            while True:
                children.require_alive()
                time.sleep(0.5)
        finally:
            # A second Ctrl+C must not interrupt cleanup halfway through.
            previous_int = signal.signal(signal.SIGINT, signal.SIG_IGN)
            previous_term = signal.signal(signal.SIGTERM, signal.SIG_IGN)
            try:
                children.close()
            finally:
                signal.signal(signal.SIGINT, previous_int)
                signal.signal(signal.SIGTERM, previous_term)


def main() -> int:
    parser = argparse.ArgumentParser(description="Native Apparel setup/start. Requires Python 3.11+ and Node.js 22+; no browser automation.")
    parser.add_argument("command", choices=("setup", "start"))
    parser.add_argument("--port-offset", type=int, default=0, help="Add to portal 3000 and main API 8000; refuses busy ports.")
    parser.add_argument("--data-dir", type=Path, help="Use a separate apparel-local folder and private accounts/configuration.")
    args = parser.parse_args()
    if os.name != "nt":
        os.umask(0o077)
    def interrupted(_signal, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    try:
        runtime = make_runtime(args.data_dir, args.port_offset)
        (setup if args.command == "setup" else start)(runtime)
    except KeyboardInterrupt:
        print("\nStopped. Your Apparel accounts and uploaded Google key are preserved.")
        return 130
    except LocalError as exc:
        print(f"Apparel: {exc}", file=sys.stderr)
        return 1
    except EOFError:
        print("Apparel: Setup input closed. Rerun setup in an interactive terminal (PowerShell on Windows).", file=sys.stderr)
        return 1
    except (OSError, RuntimeError):
        # System errors can contain private paths/configuration: never dump them or child logs.
        print("Apparel: Could not safely access local files or start a child process. Check folder permissions, close your own previous launcher, and rerun with an empty --data-dir if needed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
