import json
import os
import subprocess
import threading
import time
from pathlib import Path

import httpx
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, DirCreatedEvent

from runner import log
from runner.core.tmux import is_tmux_alive

LIVENESS_INTERVAL = 10
WATCHER_SYNC_INTERVAL = 30
FALLBACK_SCAN_INTERVAL = 60

METRICS_FORMATS = {".json"}
VISUAL_FORMATS = {".png", ".svg", ".html", ".jpg", ".jpeg", ".gif"}
ITERATION_DOCS = {"hypothesis.md", "analysis.md", "guidelines_version.txt"}


class IterationEventHandler(FileSystemEventHandler):
    def __init__(self, branch_id: int, branch_path: str, controlplane_url: str):
        self.branch_id = branch_id
        self.branch_path = branch_path
        self.controlplane_url = controlplane_url
        self._client = httpx.Client(base_url=controlplane_url, timeout=10)

    def on_created(self, event):
        path = Path(event.src_path)
        iterations_dir = Path(self.branch_path) / ".coresearch" / "iterations"

        try:
            rel = path.relative_to(iterations_dir)
        except ValueError:
            return

        parts = rel.parts
        if not parts:
            return

        iteration_hash = parts[0]

        if isinstance(event, DirCreatedEvent) and len(parts) == 1:
            self._report_iteration(iteration_hash)
        elif isinstance(event, FileCreatedEvent) and len(parts) == 2:
            # Root-level files
            filename = parts[1]
            if filename in ITERATION_DOCS:
                self._report_doc(iteration_hash, filename, path)
            elif filename == "metrics.json":
                self._report_metrics(iteration_hash, path)
        elif isinstance(event, FileCreatedEvent) and len(parts) >= 3:
            subdir = parts[1]
            filename = parts[-1]
            suffix = Path(filename).suffix.lower()

            if subdir == "metrics" and suffix in METRICS_FORMATS:
                self._report_metrics(iteration_hash, path)
            elif subdir in ("visual", "visuals") and suffix in VISUAL_FORMATS:
                self._report_visual(iteration_hash, path)

    def on_modified(self, event):
        if isinstance(event, FileCreatedEvent):
            return
        path = Path(event.src_path)
        iterations_dir = Path(self.branch_path) / ".coresearch" / "iterations"
        try:
            rel = path.relative_to(iterations_dir)
        except ValueError:
            return
        parts = rel.parts
        if len(parts) == 2 and parts[1] == "metrics.json":
            self._report_metrics(parts[0], path)
        elif len(parts) >= 3 and parts[1] == "metrics" and Path(parts[-1]).suffix.lower() in METRICS_FORMATS:
            self._report_metrics(parts[0], path)
        elif len(parts) == 2 and parts[1] in ITERATION_DOCS:
            self._report_doc(parts[0], parts[1], path)

    def _is_valid_commit(self, hash: str) -> bool:
        try:
            result = subprocess.run(
                ["git", "-C", self.branch_path, "cat-file", "-t", hash],
                capture_output=True, text=True, timeout=5,
            )
            return result.returncode == 0 and result.stdout.strip() == "commit"
        except Exception:
            return False

    def _report_iteration(self, iteration_hash: str):
        if not self._is_valid_commit(iteration_hash):
            log.warn("iteration directory does not match a git commit", branch_id=self.branch_id, hash=iteration_hash)
            return
        try:
            self._client.post("/internal/iterations", json={
                "branch_id": self.branch_id,
                "hash": iteration_hash,
            })
            log.info("iteration discovered", branch_id=self.branch_id, hash=iteration_hash)
        except Exception as e:
            log.error("failed to report iteration", branch_id=self.branch_id, hash=iteration_hash, error=str(e))

    def _report_metrics(self, iteration_hash: str, file_path: Path):
        try:
            data = json.loads(file_path.read_text())
        except Exception:
            return
        metrics = {}
        for key, value in data.items():
            try:
                metrics[key] = float(value)
            except (TypeError, ValueError):
                continue
        if not metrics:
            return
        try:
            self._client.post("/internal/iterations/metrics", json={
                "branch_id": self.branch_id,
                "hash": iteration_hash,
                "metrics": metrics,
            })
        except Exception as e:
            log.error("failed to report metrics", branch_id=self.branch_id, hash=iteration_hash, error=str(e))

    def _report_visual(self, iteration_hash: str, file_path: Path):
        try:
            self._client.post("/internal/iterations/visuals", json={
                "branch_id": self.branch_id,
                "hash": iteration_hash,
                "filename": file_path.name,
                "format": file_path.suffix.lstrip(".").lower(),
                "path": str(file_path),
            })
        except Exception as e:
            log.error("failed to report visual", branch_id=self.branch_id, filename=file_path.name, error=str(e))

    def _report_doc(self, iteration_hash: str, filename: str, file_path: Path):
        try:
            content = file_path.read_text()
        except Exception:
            return
        # Map filename to field name
        field_map = {
            "hypothesis.md": "hypothesis",
            "analysis.md": "analysis",
            "guidelines_version.txt": "guidelines_version",
        }
        field = field_map.get(filename)
        if not field:
            return
        try:
            self._client.post("/internal/iterations/doc", json={
                "branch_id": self.branch_id,
                "hash": iteration_hash,
                "field": field,
                "content": content,
            })
        except Exception as e:
            log.error("failed to report doc", branch_id=self.branch_id, filename=filename, error=str(e))


class Daemon:
    def __init__(self):
        self._controlplane_url: str = ""
        self._observer = Observer()
        self._watched: dict[int, str] = {}
        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []
        self._client: httpx.Client | None = None

    def start(self, controlplane_url: str):
        self._controlplane_url = controlplane_url
        self._client = httpx.Client(base_url=controlplane_url, timeout=10)
        self._observer.start()

        self._threads = [
            threading.Thread(target=self._liveness_loop, daemon=True),
            threading.Thread(target=self._watcher_sync_loop, daemon=True),
            threading.Thread(target=self._fallback_scan_loop, daemon=True),
        ]
        for t in self._threads:
            t.start()
        log.info("daemon started", controlplane_url=controlplane_url)

    def stop(self):
        self._stop_event.set()
        self._observer.stop()
        self._observer.join(timeout=5)
        if self._client:
            self._client.close()
        log.info("daemon stopped")

    def _liveness_loop(self):
        self._wait_for_controlplane()
        while not self._stop_event.is_set():
            try:
                self._check_sessions()
            except Exception as e:
                log.error("liveness check error", error=str(e))
            self._stop_event.wait(LIVENESS_INTERVAL)

    def _check_sessions(self):
        resp = self._client.get("/internal/sessions/active")
        if resp.status_code != 200:
            return
        sessions = resp.json()
        for session in sessions:
            attach_command = session["attach_command"]
            if not attach_command:
                continue
            alive = is_tmux_alive(attach_command)
            if not alive:
                try:
                    self._client.patch(
                        f"/internal/sessions/{session['id']}/status",
                        json={"status": "dead"},
                    )
                    log.info("session marked dead", session_id=session["id"])
                except Exception as e:
                    log.error("failed to mark session dead", session_id=session["id"], error=str(e))

    def _watcher_sync_loop(self):
        self._wait_for_controlplane()
        while not self._stop_event.is_set():
            try:
                self._sync_watchers()
            except Exception as e:
                log.error("watcher sync error", error=str(e))
            self._stop_event.wait(WATCHER_SYNC_INTERVAL)

    def _sync_watchers(self):
        resp = self._client.get("/internal/branches")
        if resp.status_code != 200:
            return
        branches = resp.json()
        active_ids = set()

        for branch in branches:
            branch_id = branch["id"]
            branch_path = branch["path"]
            active_ids.add(branch_id)

            if branch_id in self._watched:
                continue

            iterations_dir = os.path.join(branch_path, ".coresearch", "iterations")
            if not os.path.isdir(iterations_dir):
                os.makedirs(iterations_dir, exist_ok=True)

            handler = IterationEventHandler(branch_id, branch_path, self._controlplane_url)
            try:
                watch = self._observer.schedule(handler, iterations_dir, recursive=True)
                self._watched[branch_id] = watch
                log.info("watcher added", branch_id=branch_id, path=iterations_dir)
            except Exception as e:
                log.error("watcher failed", branch_id=branch_id, error=str(e))

        stale = set(self._watched.keys()) - active_ids
        for branch_id in stale:
            watch = self._watched.pop(branch_id)
            try:
                self._observer.unschedule(watch)
            except Exception:
                pass
            log.info("watcher removed", branch_id=branch_id)

    def _fallback_scan_loop(self):
        self._wait_for_controlplane()
        while not self._stop_event.is_set():
            try:
                self._fallback_scan()
            except Exception as e:
                log.error("fallback scan error", error=str(e))
            self._stop_event.wait(FALLBACK_SCAN_INTERVAL)

    def _fallback_scan(self):
        resp = self._client.get("/internal/branches")
        if resp.status_code != 200:
            return
        branches = resp.json()
        for branch in branches:
            self._scan_branch(branch["id"], branch["path"])

    def _scan_branch(self, branch_id: int, branch_path: str):
        iterations_dir = Path(branch_path) / ".coresearch" / "iterations"
        if not iterations_dir.is_dir():
            return

        for iter_dir in sorted(iterations_dir.iterdir()):
            if not iter_dir.is_dir():
                continue
            iteration_hash = iter_dir.name

            # Verify it's a real git commit
            try:
                result = subprocess.run(
                    ["git", "-C", branch_path, "cat-file", "-t", iteration_hash],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode != 0 or result.stdout.strip() != "commit":
                    log.warn("iteration directory does not match a git commit", branch_id=branch_id, hash=iteration_hash)
                    continue
            except Exception:
                log.warn("failed to verify iteration commit", branch_id=branch_id, hash=iteration_hash)
                continue

            try:
                self._client.post("/internal/iterations", json={
                    "branch_id": branch_id,
                    "hash": iteration_hash,
                })
            except Exception:
                continue

            # Root-level metrics.json
            root_metrics = iter_dir / "metrics.json"
            if root_metrics.is_file():
                try:
                    data = json.loads(root_metrics.read_text())
                    metrics = {}
                    for key, value in data.items():
                        try:
                            metrics[key] = float(value)
                        except (TypeError, ValueError):
                            continue
                    if metrics:
                        self._client.post("/internal/iterations/metrics", json={
                            "branch_id": branch_id,
                            "hash": iteration_hash,
                            "metrics": metrics,
                        })
                except Exception:
                    pass

            # Metrics subdirectory (legacy)
            metrics_dir = iter_dir / "metrics"
            if metrics_dir.is_dir():
                for f in metrics_dir.iterdir():
                    if f.is_file() and f.suffix in METRICS_FORMATS:
                        try:
                            data = json.loads(f.read_text())
                            metrics = {}
                            for key, value in data.items():
                                try:
                                    metrics[key] = float(value)
                                except (TypeError, ValueError):
                                    continue
                            if metrics:
                                self._client.post("/internal/iterations/metrics", json={
                                    "branch_id": branch_id,
                                    "hash": iteration_hash,
                                    "metrics": metrics,
                                })
                        except Exception:
                            continue

            # Scan visuals from both "visual/" and "visuals/" dirs
            for vdir_name in ("visual", "visuals"):
                visual_dir = iter_dir / vdir_name
                if visual_dir.is_dir():
                    for f in visual_dir.iterdir():
                        if f.is_file() and f.suffix.lower() in VISUAL_FORMATS:
                            try:
                                self._client.post("/internal/iterations/visuals", json={
                                    "branch_id": branch_id,
                                    "hash": iteration_hash,
                                    "filename": f.name,
                                    "format": f.suffix.lstrip(".").lower(),
                                    "path": str(f),
                                })
                            except Exception:
                                continue

            # Scan root-level docs (hypothesis.md, analysis.md, guidelines_version.txt)
            field_map = {
                "hypothesis.md": "hypothesis",
                "analysis.md": "analysis",
                "guidelines_version.txt": "guidelines_version",
            }
            for filename, field in field_map.items():
                doc_file = iter_dir / filename
                if doc_file.is_file():
                    try:
                        self._client.post("/internal/iterations/doc", json={
                            "branch_id": branch_id,
                            "hash": iteration_hash,
                            "field": field,
                            "content": doc_file.read_text(),
                        })
                    except Exception:
                        continue

    def _wait_for_controlplane(self):
        while not self._stop_event.is_set():
            try:
                resp = self._client.get("/internal/health")
                if resp.status_code == 200:
                    log.info("controlplane reachable")
                    return
            except Exception:
                pass
            log.warn("waiting for controlplane")
            self._stop_event.wait(2)
