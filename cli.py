"""octl - Octify dev workflow CLI"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import click
import questionary

VERSION = "1.3.0"


# -- Helpers -------------------------------------------------------------------

def check_infisical() -> None:
    if shutil.which("infisical") is None:
        raise click.ClickException(
            "Infisical CLI not installed.\n"
            "Install it: https://infisical.com/docs/cli/overview"
        )


def env_file(env: str, cwd: Path) -> Path:
    return cwd / (".env.development" if env == "dev" else ".env.production")


def parse_keys(path: Path) -> list[str]:
    """Return all non-comment KEY names from an env file."""
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


def run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(args, **kwargs)


def infisical_export(env: str, dest: Path) -> bool:
    with dest.open("w") as f:
        r = run(["infisical", "export", f"--env={env}"], stdout=f, stderr=None)
    return r.returncode == 0 and dest.stat().st_size > 0 and bool(parse_keys(dest))


# -- Syncenv operations --------------------------------------------------------

def pull(env: str, cwd: Path) -> int:
    out_file = env_file(env, cwd)
    click.echo(f"\n-- Pulling [{env}] from Infisical...")

    tmp = Path(tempfile.mktemp(prefix=f"octl.{env}."))
    try:
        if not infisical_export(env, tmp):
            click.echo(click.style(f"Error: Export failed [{env}]. File unchanged.", fg="red"), err=True)
            return 1
        shutil.move(str(tmp), str(out_file))
        click.secho(f"  Saved -> {out_file}", fg="green")
        return 0
    except Exception as e:
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)
        return 1
    finally:
        tmp.unlink(missing_ok=True)


def push(env: str, cwd: Path) -> int:
    env_f = env_file(env, cwd)

    if not env_f.exists() or not env_f.stat().st_size:
        raise click.ClickException(f"{env_f} not found or empty.")

    click.echo(f"\n-- Checking [{env}] for removed keys...")
    rc = _handle_deletions(env, env_f)
    if rc != 0:
        return rc

    click.echo(f"\n-- Pushing secrets -> Infisical [{env}]...")
    r = run(["infisical", "secrets", "set", f"--file={env_f}", f"--env={env}"])
    if r.returncode != 0:
        click.echo(click.style(f"Error: Push failed for [{env}]", fg="red"), err=True)
        return 1

    click.secho(f"  Pushed {len(parse_keys(env_f))} secret(s) -> [{env}]", fg="green")
    return 0


def _handle_deletions(env: str, env_f: Path) -> int:
    tmp = Path(tempfile.mktemp(prefix=f"octl.{env}_remote."))
    try:
        if not infisical_export(env, tmp):
            click.secho("Warning: Could not fetch remote secrets. Skipping deletion check.", fg="yellow", err=True)
            return 0

        removed = [k for k in parse_keys(tmp) if k not in set(parse_keys(env_f))]
        if not removed:
            click.echo("No removed keys.")
            return 0

        click.echo(f"\nKeys in Infisical [{env}] missing from {env_f.name}:")
        to_delete = questionary.checkbox(
            f"Select keys to delete from [{env}]:",
            choices=[questionary.Choice(k, checked=False) for k in removed],
        ).ask()

        if to_delete is None or not to_delete:
            click.echo("No keys selected for deletion.")
            return 0

        if not questionary.confirm(f"Delete {len(to_delete)} key(s)?", default=False).ask():
            click.echo("Skipped deletion.")
            return 0

        deleted, failed = 0, []
        for key in to_delete:
            r = run(["infisical", "secrets", "delete", key, f"--env={env}"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if r.returncode == 0:
                click.secho(f"  Deleted {key}", fg="green")
                deleted += 1
            else:
                err = r.stderr.decode(errors="replace") if isinstance(r.stderr, bytes) else (r.stderr or "")
                if "404" in err or "not found" in err.lower():
                    click.echo(f"  Skipped {key} (already gone)")
                    deleted += 1
                else:
                    click.echo(click.style(f"  Failed to delete {key}", fg="red"), err=True)
                    failed.append(key)

        if failed:
            click.echo(click.style(f"\n  {deleted} deleted, {len(failed)} failed: {', '.join(failed)}", fg="red"), err=True)
            return 1

        click.secho(f"  Deleted {deleted} key(s) from [{env}]", fg="green")
        return 0
    except Exception as e:
        click.secho(f"Warning: Deletion diff error: {e}. Continuing.", fg="yellow", err=True)
        return 0
    finally:
        tmp.unlink(missing_ok=True)


# -- Git: clean-branches -------------------------------------------------------

SAFE_BRANCHES = {"main", "production"}


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True)


def _clean_branches() -> int:
    if shutil.which("git") is None:
        raise click.ClickException("git not installed")

    if _git("rev-parse", "--git-dir").returncode != 0:
        raise click.ClickException("Not a git repository")

    landed_on = None
    for branch in ("main", "production"):
        if _git("checkout", branch).returncode == 0:
            landed_on = branch
            break

    if not landed_on:
        raise click.ClickException("Could not switch to main or production")

    click.echo(f"\n-- Switched to [{landed_on}]")

    r = _git("branch")
    candidates = [
        b[2:].strip() if b.startswith("* ") else b.strip()
        for b in r.stdout.splitlines()
        if b.strip() and b.strip().lstrip("* ") not in SAFE_BRANCHES
    ]

    if not candidates:
        click.echo("  Nothing to clean -- no branches outside main/production.")
        return 0

    to_delete = questionary.checkbox(
        f"Select branches to delete ({len(candidates)} found):",
        choices=[questionary.Choice(b, checked=True) for b in candidates],
    ).ask()

    if not to_delete:
        click.echo("No branches selected.")
        return 0

    if not questionary.confirm(f"Force-delete {len(to_delete)} branch(es)?", default=False).ask():
        click.echo("Aborted.")
        return 0

    failed = []
    for branch in to_delete:
        r = _git("branch", "-D", branch)
        if r.returncode == 0:
            click.secho(f"  Deleted {branch}", fg="green")
        else:
            click.echo(click.style(f"  Failed: {branch} -- {r.stderr.strip()}", fg="red"), err=True)
            failed.append(branch)

    if failed:
        raise click.ClickException(f"{len(failed)} branch(es) could not be deleted.")

    click.secho(f"\n  Cleaned {len(to_delete)} branch(es). Kept: {', '.join(sorted(SAFE_BRANCHES))}", fg="green")
    return 0


# -- CLI -----------------------------------------------------------------------

@click.group(invoke_without_command=True, context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(VERSION, "-v", "--version", prog_name="octl")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """octl - Octify dev workflow CLI"""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@cli.group(invoke_without_command=True)
@click.pass_context
def syncenv(ctx: click.Context) -> None:
    """Sync environment secrets with Infisical."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@syncenv.command("pull")
@click.argument("environment", default="all", type=click.Choice(["dev", "prod", "all"]))
def syncenv_pull(environment: str) -> None:
    """Pull secrets from Infisical -> .env files."""
    check_infisical()
    cwd = Path.cwd()
    envs = ["dev", "prod"] if environment == "all" else [environment]
    rc = max(pull(env, cwd) for env in envs)
    sys.exit(rc)


@syncenv.command("push")
@click.argument("environment", default="all", type=click.Choice(["dev", "prod", "all"]))
def syncenv_push(environment: str) -> None:
    """Push .env files -> Infisical (with deletion diff)."""
    check_infisical()
    cwd = Path.cwd()
    envs = ["dev", "prod"] if environment == "all" else [environment]
    rc = max(push(env, cwd) for env in envs)
    sys.exit(rc)


@cli.command("clean-branches")
def clean_branches() -> None:
    """Delete all local branches except main & production."""
    sys.exit(_clean_branches())


# -- Entry points --------------------------------------------------------------

def main() -> None:
    cli()


def syncenv_cmd() -> None:
    syncenv(standalone_mode=True)


def clean_branches_cmd() -> None:
    sys.exit(_clean_branches())


if __name__ == "__main__":
    main()
