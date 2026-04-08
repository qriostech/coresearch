import os
import subprocess


def create_tmux_session(name: str, working_dir: str = None) -> str:
    """
    Creates a new detached tmux session with the given name.
    Returns the attach command for that session.
    """
    cmd = ["tmux", "new-session", "-d", "-s", name]
    if working_dir:
        cmd += ["-c", working_dir]
    subprocess.run(
        cmd,
        check=True,
        env={**os.environ, "TERM": "xterm-256color"},
        timeout=10,
    )
    return f"tmux attach-session -t {name}"
