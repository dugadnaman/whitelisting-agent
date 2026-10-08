"""Launcher invariants without installs, browser starts, or real account data.

Run: python -m unittest discover -s scripts -p 'test_apparel_local.py'
"""
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import apparel_local as launcher


class NativeLauncherTests(unittest.TestCase):
    def test_env_additions_preserve_existing_settings_and_are_persistent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            prefix = b"# Existing settings\r\nTATA_SETTING=synthetic-not-for-apparel\r\n"
            path.write_bytes(prefix)
            first = launcher.initialize_env(path)
            content = path.read_bytes()
            second = launcher.initialize_env(path)
            self.assertTrue(content.startswith(prefix))
            self.assertTrue(first == second)
            self.assertTrue(path.read_bytes() == content)
            self.assertTrue(first["JWT_SECRET"] != first["APPAREL_ATTRIBUTION_TOKEN"])
            launcher.validate_env(first)
            if os.name != "nt":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_existing_weak_secret_is_never_overwritten_or_disclosed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            content = b"JWT_SECRET=synthetic-weak-value\n"
            path.write_bytes(content)
            with self.assertRaises(launcher.LocalError) as failure:
                launcher.initialize_env(path)
            self.assertNotIn("synthetic-weak-value", str(failure.exception))
            self.assertTrue(path.read_bytes() == content)

    def test_secrets_and_foreign_account_settings_stay_out_of_frontend_and_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = launcher.make_runtime(Path(directory), 10000)
            values = {key: secrets.token_urlsafe(48) for key in launcher.SECRET_KEYS}
            inherited = {"PATH": "/synthetic/path", "HOME": directory,
                         "DATABASE_URL": "synthetic-cloud-db", "BAJAJ_AUTH_TOKEN": "synthetic-bajaj",
                         "TATA_WABA_AUTH_TOKEN": "synthetic-tata", "GOOGLE_SERVICE_ACCOUNT_JSON": "synthetic-key",
                         "APPAREL_ATTRIBUTION_WORKER_URL": "http://foreign-worker.invalid",
                         "NEXT_PUBLIC_APPAREL_ATTRIBUTION_TOKEN": "synthetic-client-secret"}
            with patch.dict(os.environ, inherited, clear=True):
                backend = launcher.environment(runtime, "api", values)
                worker = launcher.environment(runtime, "worker", values)
                portal = launcher.environment(runtime, "portal", values)
                chrome = launcher.environment(runtime, "chrome", values)
            for env in (backend, worker, portal, chrome):
                for key in ("DATABASE_URL", "BAJAJ_AUTH_TOKEN", "TATA_WABA_AUTH_TOKEN",
                            "GOOGLE_SERVICE_ACCOUNT_JSON", "NEXT_PUBLIC_APPAREL_ATTRIBUTION_TOKEN"):
                    self.assertNotIn(key, env)
            self.assertTrue(backend["APPAREL_ATTRIBUTION_TOKEN"] == worker["APPAREL_ATTRIBUTION_TOKEN"])
            self.assertNotIn("JWT_SECRET", worker)
            for env in (portal, chrome):
                self.assertTrue(not any(key in env for key in launcher.SECRET_KEYS))
            self.assertTrue(runtime["state"] in Path(backend["KARIX_DB_PATH"]).parents)
            self.assertTrue(runtime["env_file"] != launcher.ROOT / ".env")

    def test_data_parent_is_untouched_and_unmarked_child_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            (parent / "unrelated.txt").write_text("keep", encoding="utf-8")
            mode = parent.stat().st_mode
            runtime = launcher.make_runtime(parent)
            launcher.prepare_state(runtime)
            self.assertEqual(parent.stat().st_mode, mode)
            self.assertEqual((parent / "unrelated.txt").read_text(), "keep")
            self.assertTrue(runtime["state"] == parent / "apparel-local")
        with tempfile.TemporaryDirectory() as directory:
            runtime = launcher.make_runtime(Path(directory))
            runtime["state"].mkdir()
            unrelated = runtime["state"] / "notes.txt"
            unrelated.write_text("keep", encoding="utf-8")
            mode = runtime["state"].stat().st_mode
            with self.assertRaises(launcher.LocalError):
                launcher.prepare_state(runtime)
            self.assertEqual(runtime["state"].stat().st_mode, mode)
            self.assertEqual(unrelated.read_text(), "keep")
            self.assertFalse((runtime["state"] / ".apparel-local-state").exists())

    def test_port_refusal_leaves_existing_listener_running(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            with self.assertRaises(launcher.LocalError):
                launcher.check_ports({"api": port})
            self.assertEqual(listener.getsockname()[1], port)
            self.assertNotEqual(listener.fileno(), -1)
        for offset in (-1, 56314):
            with self.assertRaises(launcher.LocalError):
                launcher.make_runtime(port_offset=offset)

    def test_staged_source_removes_deleted_routes_without_copying_env_or_build(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            (source / "app").mkdir(parents=True)
            (source / "app/page.tsx").write_text("synthetic source", encoding="utf-8")
            (source / "app/.env").write_text("DO_NOT_COPY=synthetic", encoding="utf-8")
            (source / ".next").mkdir()
            (source / ".next/unrelated-build").write_text("keep", encoding="utf-8")
            (source / "node_modules/next/dist/bin").mkdir(parents=True)
            (source / "node_modules/next/dist/bin/next").write_text("not executed", encoding="utf-8")
            runtime = launcher.make_runtime(root / "state")
            launcher.prepare_state(runtime)
            with patch.object(launcher, "FRONTEND", source):
                staged = launcher.stage_frontend(runtime)
                self.assertFalse((staged / "app/.env").exists())
                self.assertFalse((staged / ".next").exists())
                (staged / "app/deleted-route").mkdir()
                (staged / "app/deleted-route/page.tsx").write_text("old", encoding="utf-8")
                (staged / ".next").mkdir()
                (staged / ".next/own-cache").write_text("keep", encoding="utf-8")
                launcher.stage_frontend(runtime)
                self.assertFalse((staged / "app/deleted-route").exists())
                self.assertEqual((staged / ".next/own-cache").read_text(), "keep")
                self.assertTrue((staged / "node_modules").resolve() == (source / "node_modules").resolve())
                self.assertEqual((source / ".next/unrelated-build").read_text(), "keep")

    def test_cleanup_stops_owned_processes_but_preserves_unrelated_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = launcher.make_runtime(Path(directory))
            launcher.prepare_state(runtime)
            children = launcher.Children(runtime)
            command = [sys.executable, "-c", "import time; time.sleep(60)"]
            unrelated = subprocess.Popen(command)
            try:
                children.launch("owned", command, runtime["state"], launcher.environment(runtime, "chrome", {}))
                owned = children.processes[0][1]
                children.close()
                self.assertIsNotNone(owned.poll())
                self.assertIsNone(unrelated.poll())
            finally:
                if any(process.poll() is None for _, process, _ in children.processes):
                    children.close()
                unrelated.terminate()
                unrelated.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
