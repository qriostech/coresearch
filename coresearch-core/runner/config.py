"""Runtime configuration loaded from environment variables."""
import os

STORAGE_ROOT = os.environ.get("STORAGE_ROOT", "/data/sessions")
RUNNER_NAME = os.environ.get("RUNNER_NAME", "runner-default")
RUNNER_PORT = int(os.environ.get("RUNNER_PORT", "8001"))
