#!/usr/bin/env python3
"""Pre-accept the Claude Code workspace trust dialog for a given directory.

Used by the runner image's `claude` bash function: before launching the real
claude CLI, the function calls this script with the current working directory,
which adds an entry to `~/.claude.json` marking that path as trusted. Without
this, claude would prompt "Do you trust the files in this folder?" the first
time the user opens it inside a freshly-created branch tmux session.

Branch working directories live under /data/sessions/<uuid>/... and are
created on the fly by the runner — there's no way to pre-populate the
`projects` map at image build time, so we do it lazily per invocation.

Idempotent: re-running with the same directory is a no-op write.
"""
import json
import os
import sys

CONFIG = os.path.expanduser("~/.claude.json")


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: claude-trust-cwd <absolute-path>", file=sys.stderr)
        return 2
    cwd = sys.argv[1]

    try:
        with open(CONFIG) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}

    # Skipping the first-run onboarding flow — orthogonal to trust but the
    # same dialog gauntlet, so set it here too.
    data["hasCompletedOnboarding"] = True

    projects = data.setdefault("projects", {})
    entry = projects.setdefault(cwd, {})
    entry["hasTrustDialogAccepted"] = True

    # Atomic-ish write: open + write + flush. Good enough for a config that's
    # only touched by interactive shells, never concurrently.
    with open(CONFIG, "w") as f:
        json.dump(data, f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
