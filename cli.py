"""
octl - Octify dev workflow CLI

Usage:
    octl pull [dev|prod|all]       Pull secrets from Infisical -> .env files
    octl push [dev|prod|all]       Push .env files -> Infisical (with deletion diff)
    octl clean-branches            Delete all local branches except main & production
    octl --help                    Show this help message
    octl --version                 Show version
    clean-branches                 (standalone) same as octl clean-branches
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

VERSION = "1.1.0"

COMMANDS = ("pull", "push", "clean-branches")


# -- Helpers -------------------------------------------------------------------

def warn(msg: str) -> None:
    print(f"Warning: {msg}", file=sys.stderr)


def check_infisical() -> None:
    if shutil.which("infisical") is None:
        print("Error: Infisical CLI not installed.", file=sys.stderr)
        print(
            "Install it: https://infisical.com/docs/cli/overview",
            file=sys.stderr,
        )
        sys.exit(1)


def env_file(env: str, cwd: Path) -> Path:
    return cwd / (".env.development" if env == "dev" else ".env.production")


def parse_keys(path: Path) -> list[str]:
    """Return all non-comment KEY names from an env file.
    Handles both KEY=value and export KEY=value formats.
    """
    keys = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key.startswith("export "):
                key = key[7:].strip()
            if key:
                keys.append(key)
    return keys


def has_keylines(path: Path) -> bool:
    return bool(parse_keys(path))


def make_tmp(suffix: str) -> Path:
    fd, path = tempfile.mkstemp(prefix=f"octl.{suffix}.")
    os.close(fd)
    return Path(path)


def prompt_yn(question: str) -> bool:
    print(f"\n{question} [y/N] ", end="", flush=True)
    try:
        if os.path.exists("/dev/tty"):
            with open("/dev/tty") as tty:
                answer = tty.readline().strip().lower()
        else:
            if not sys.stdin.isatty():
                print()
                return False
            answer = sys.stdin.readline().strip().lower()
    except (EOFError, KeyboardInterrupt, OSError):
        print()
        return False
    return answer in ("y", "yes")


# -- Core operations -----------------------------------------------------------

def pull(env: str, cwd: Path) -> int:
    out_file = env_file(env, cwd)
    print(f"\n-- Pulling [{env}] from Infisical...")

    tmp = make_tmp(env)
    try:
        with tmp.open("w") as f:
            result = subprocess.run(
                ["infisical", "export", f"--env={env}"],
                stdout=f,
                stderr=None,
            )

        if result.returncode != 0:
            print(
                f"Error: Export failed [{env}]. Existing file unchanged.",
                file=sys.stderr,
            )
            return 1

        if not tmp.stat().st_size or not has_keylines(tmp):
            print(
                f"Error: Empty or invalid export [{env}]. Existing file unchanged.",
                file=sys.stderr,
            )
            return 1

        shutil.move(str(tmp), str(out_file))
        print(f"  Saved -> {out_file}")
        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def push(env: str, cwd: Path) -> int:
    env_f = env_file(env, cwd)

    if not env_f.exists():
        print(f"Error: {env_f} not found", file=sys.stderr)
        return 1
    if not env_f.stat().st_size:
        print(f"Error: {env_f} is empty; refusing to push.", file=sys.stderr)
        return 1

    print(f"\n-- Checking [{env}] for removed keys...")

    rc = _handle_deletions(env, env_f)
    if rc != 0:
        return rc

    print(f"\n-- Pushing secrets -> Infisical [{env}]...")

    result = subprocess.run(
        ["infisical", "secrets", "set", f"--file={env_f}", f"--env={env}"],
    )

    if result.returncode != 0:
        print(f"Error: Push failed for [{env}]", file=sys.stderr)
        return 1

    count = len(parse_keys(env_f))
    print(f"  Pushed {count} secret(s) -> [{env}]")
    return 0


def _handle_deletions(env: str, env_f: Path) -> int:
    tmp = make_tmp(f"{env}_remote")
    try:
        with tmp.open("w") as f:
            result = subprocess.run(
                ["infisical", "export", f"--env={env}"],
                stdout=f,
                stderr=subprocess.PIPE,
            )

        if result.returncode != 0 or not has_keylines(tmp):
            warn("Could not fetch remote secrets for diff. Skipping deletion check.")
            return 0

        remote_keys = parse_keys(tmp)
        local_keys = set(parse_keys(env_f))
        removed = [k for k in remote_keys if k not in local_keys]

        if not removed:
            print("No removed keys.")
            return 0

        print(f"\nKeys in Infisical [{env}] missing from {env_f.name}:")
        for key in removed:
            print(f"  - {key}")

        if not prompt_yn(f"Delete {len(removed)} key(s) from Infisical [{env}]?"):
            print("Skipped deletion.")
            return 0

        print("Deleting...")
        result = subprocess.run(
            ["infisical", "secrets", "delete", *removed, f"--env={env}"],
            stderr=None,
        )

        if result.returncode != 0:
            print(f"Error: Deletion failed for [{env}]", file=sys.stderr)
            return 1

        print(f"  Deleted {len(removed)} key(s) from [{env}]")
        return 0

    except Exception as e:
        warn(f"Deletion diff error: {e}. Continuing with push.")
        return 0
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


# -- Git: clean-branches -------------------------------------------------------

SAFE_BRANCHES = {"main", "production"}


def _git(*args: str, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        text=True,
    )


def clean_branches() -> int:
    if shutil.which("git") is None:
        print("Error: git not installed", file=sys.stderr)
        return 1

    if _git("rev-parse", "--git-dir", capture=True).returncode != 0:
        print("Error: Not a git repository", file=sys.stderr)
        return 1

    landed_on: str | None = None
    for branch in ("main", "production"):
        r = _git("checkout", branch, capture=True)
        if r.returncode == 0:
            landed_on = branch
            break

    if landed_on is None:
        print("Error: Could not switch to main or production", file=sys.stderr)
        return 1

    print(f"\n-- Switched to [{landed_on}]")

    r = _git("branch", capture=True)
    if r.returncode != 0:
        print("Error: Could not list branches", file=sys.stderr)
        return 1

    candidates = []
    for line in r.stdout.splitlines():
        branch = line.strip()
        if branch.startswith("* "):
            branch = branch[2:]
        if branch and branch not in SAFE_BRANCHES:
            candidates.append(branch)

    if not candidates:
        print("  Nothing to clean -- no branches outside main/production.")
        return 0

    print(f"\nBranches to delete ({len(candidates)}):")
    for b in candidates:
        print(f"  - {b}")

    if not prompt_yn(f"Force-delete {len(candidates)} branch(es)?"):
        print("Aborted.")
        return 0

    failed = []
    for branch in candidates:
        r = _git("branch", "-D", branch, capture=True)
        if r.returncode == 0:
            print(f"  Deleted {branch}")
        else:
            print(
                f"  Failed: {branch} -- {r.stderr.strip()}", file=sys.stderr)
            failed.append(branch)

    if failed:
        print(
            f"\n{len(failed)} branch(es) could not be deleted.",
            file=sys.stderr,
        )
        return 1

    print(
        f"\n  Cleaned {len(candidates)} branch(es). Kept: {', '.join(sorted(SAFE_BRANCHES))}")
    return 0


# -- Entry points --------------------------------------------------------------

def _setup_signal() -> None:
    signal.signal(
        signal.SIGINT,
        lambda *_: (print("\nInterrupted (Ctrl+C).",
                    file=sys.stderr), sys.exit(130)),
    )


def usage() -> None:
    print(
        "octl - Octify dev workflow CLI\n"
        "\n"
        "Usage:\n"
        "  octl pull [dev|prod|all]       Pull secrets from Infisical -> .env files\n"
        "  octl push [dev|prod|all]       Push .env files -> Infisical (with deletion diff)\n"
        "  octl clean-branches            Delete all local branches except main & production\n"
        "\n"
        "Options:\n"
        "  --help, -h      Show this help message\n"
        "  --version, -v   Show version\n"
        "\n"
        "Environments:\n"
        "  dev       .env.development\n"
        "  prod      .env.production\n"
        "  all       Both (default)\n"
        "\n"
        "Prerequisites:\n"
        "  - Infisical CLI (https://infisical.com/docs/cli/overview)\n"
        "  - Run `infisical login` and `infisical init` in your project first\n",
    )


def main() -> None:
    _setup_signal()

    args = sys.argv[1:]

    if not args or args[0] in ("--help", "-h", "help"):
        usage()
        sys.exit(0 if args else 1)

    if args[0] in ("--version", "-v"):
        print(f"octl {VERSION}")
        sys.exit(0)

    command = args[0]

    if command == "clean-branches":
        sys.exit(clean_branches())

    if command not in ("pull", "push"):
        print(f"Error: Unknown command '{command}'", file=sys.stderr)
        usage()
        sys.exit(1)

    environment = args[1] if len(args) > 1 else "all"

    if environment in ("--help", "-h"):
        usage()
        sys.exit(0)

    if environment not in ("dev", "prod", "all"):
        print(f"Error: Unknown environment '{environment}'", file=sys.stderr)
        print("Valid environments: dev, prod, all", file=sys.stderr)
        sys.exit(1)

    check_infisical()

    cwd = Path.cwd()
    fn = pull if command == "pull" else push
    envs = ["dev", "prod"] if environment == "all" else [environment]

    rc = 0
    for env in envs:
        rc = max(rc, fn(env, cwd))

    sys.exit(rc)


def clean_branches_cmd() -> None:
    _setup_signal()
    sys.exit(clean_branches())


if __name__ == "__main__":
    main()
