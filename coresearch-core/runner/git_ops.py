import os
import subprocess


def inject_token(url: str, token: str | None) -> str:
    if token and "://" in url:
        scheme, rest = url.split("://", 1)
        return f"{scheme}://oauth2:{token}@{rest}"
    return url


def detect_default_branch(auth_url: str) -> tuple[str, str]:
    result = subprocess.run(
        ["git", "ls-remote", "--symref", auth_url, "HEAD"],
        capture_output=True, text=True, timeout=30, check=True,
    )
    branch = "main"
    commit = None
    for line in result.stdout.strip().splitlines():
        if line.startswith("ref:"):
            branch = line.split("refs/heads/")[-1].split("\t")[0]
        elif "HEAD" in line:
            commit = line.split()[0]
    if not commit:
        raise ValueError("Could not detect default branch")
    return branch, commit


def resolve_branch_and_commit(
    repository_url: str,
    requested_branch: str | None,
    requested_commit: str | None,
    access_token: str | None = None,
) -> tuple[str, str]:
    token = access_token or os.environ.get("GITHUB_TOKEN")
    auth_url = inject_token(repository_url, token)

    if requested_branch:
        result = subprocess.run(
            ["git", "ls-remote", auth_url, f"refs/heads/{requested_branch}"],
            capture_output=True, text=True, timeout=30,
        )
        lines = [l for l in result.stdout.strip().splitlines() if l]
        if lines:
            branch = requested_branch
            remote_commit = lines[0].split()[0]
        else:
            branch, remote_commit = detect_default_branch(auth_url)
    else:
        branch, remote_commit = detect_default_branch(auth_url)

    if requested_commit and len(requested_commit) >= 7 and all(c in "0123456789abcdefABCDEF" for c in requested_commit):
        return branch, requested_commit

    return branch, remote_commit


def clone_repo(url: str, dest: str, branch: str, access_token: str | None = None) -> None:
    token = access_token or os.environ.get("GITHUB_TOKEN")
    clone_url = inject_token(url, token)
    subprocess.run(
        ["git", "clone", "--branch", branch, clone_url, dest],
        check=True, timeout=120,
    )


def clone_local(source: str, dest: str) -> None:
    subprocess.run(["git", "clone", source, dest], check=True, timeout=120)


def checkout_branch(repo_path: str, git_branch: str, start_point: str) -> str:
    subprocess.run(
        ["git", "-C", repo_path, "checkout", "-b", git_branch, start_point],
        check=True, timeout=10,
    )
    result = subprocess.run(
        ["git", "-C", repo_path, "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True, timeout=10,
    )
    return result.stdout.strip()


def git_diff(repo_path: str, from_hash: str, to_hash: str) -> str:
    result = subprocess.run(
        ["git", "diff", from_hash, to_hash],
        cwd=repo_path,
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        raise ValueError(result.stderr.strip())
    return result.stdout


def git_tree(repo_path: str, commit_hash: str) -> list[str]:
    result = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", commit_hash],
        cwd=repo_path,
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        raise ValueError(result.stderr.strip())
    return [f for f in result.stdout.strip().split("\n") if f]


def git_show_file(repo_path: str, commit_hash: str, path: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{commit_hash}:{path}"],
        cwd=repo_path,
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        raise ValueError(result.stderr.strip())
    return result.stdout


def git_push(repo_path: str, url: str, refspec: str, access_token: str | None = None) -> str:
    token = access_token or os.environ.get("GITHUB_TOKEN")
    push_url = inject_token(url, token)
    result = subprocess.run(
        ["git", "-C", repo_path, "push", push_url, refspec],
        capture_output=True, text=True, check=True, timeout=60,
    )
    return result.stdout.strip() or "pushed successfully"
