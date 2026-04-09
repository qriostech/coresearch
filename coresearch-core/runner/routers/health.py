"""Runner health probe — used by Docker healthcheck and the controlplane's deep /health."""
import os
import subprocess

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from runner.config import STORAGE_ROOT

router = APIRouter()


@router.get("/health")
def health_check():
    checks = {"tmux": "ok", "storage": "ok"}
    healthy = True

    result = subprocess.run(["tmux", "list-sessions"], capture_output=True, timeout=5)
    if result.returncode not in (0, 1):  # 1 = no sessions, which is fine
        checks["tmux"] = "tmux not available"
        healthy = False

    if not os.path.isdir(STORAGE_ROOT):
        checks["storage"] = f"{STORAGE_ROOT} not found"
        healthy = False
    else:
        try:
            test_file = os.path.join(STORAGE_ROOT, ".health_check")
            with open(test_file, "w") as f:
                f.write("ok")
            os.remove(test_file)
        except Exception as e:
            checks["storage"] = f"not writable: {e}"
            healthy = False

    return JSONResponse(
        {"status": "healthy" if healthy else "unhealthy", "checks": checks},
        status_code=200 if healthy else 503,
    )
