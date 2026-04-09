import os
import subprocess


def create_tmux_session(name: str, working_dir: str = None) -> str:
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


def session_name_from_attach(attach_command: str) -> str:
    return attach_command.split()[-1]


def is_tmux_alive(attach_command: str) -> bool:
    name = session_name_from_attach(attach_command)
    result = subprocess.run(
        ["tmux", "has-session", "-t", name],
        capture_output=True, timeout=5,
    )
    return result.returncode == 0


def kill_tmux_session(attach_command: str) -> None:
    name = session_name_from_attach(attach_command)
    subprocess.run(
        ["tmux", "kill-session", "-t", name],
        capture_output=True, timeout=5,
    )
