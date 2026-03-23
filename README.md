# octl

Octify dev workflow CLI — manage Infisical secrets and git branches.

## Prerequisites

- **Python** >= 3.8
- **Infisical CLI** — [install guide](https://infisical.com/docs/cli/overview)
- **Git** (for `clean-branches`)

## Install

```bash
pip install git+https://github.com/Octify-Technologies/octl.git
```

Or install locally for development:

```bash
git clone https://github.com/Octify-Technologies/octl.git
cd octl
pip install -e .
```

## Upgrade

```bash
pip install --upgrade git+https://github.com/Octify-Technologies/octl.git
```

Or if installed locally:

```bash
cd octl
git pull
pip install -e .
```

## Uninstall

```bash
pip uninstall octl
```

## Setup

Before using secret management commands, log in and initialize Infisical in your project:

```bash
infisical login
cd your-project
infisical init
```

## Usage

```
octl syncenv pull [dev|prod|all]   Pull secrets from Infisical -> .env files
octl syncenv push [dev|prod|all]   Push .env files -> Infisical (with deletion diff)
octl clean-branches                Delete all local branches except main & production
octl --help                        Show help
octl --version                     Show version
```

All subcommands are also available as standalone commands:

```
syncenv pull [dev|prod|all]
syncenv push [dev|prod|all]
clean-branches
```

### syncenv pull

Download secrets from Infisical and save them to local `.env` files.

```bash
octl syncenv pull dev          # -> .env.development
octl syncenv pull prod         # -> .env.production
octl syncenv pull              # -> both (default: all)

# or standalone:
syncenv pull dev
```

### syncenv push

Upload local `.env` files to Infisical. Detects removed keys and prompts before deleting them remotely.

```bash
octl syncenv push dev          # .env.development -> Infisical
octl syncenv push prod         # .env.production  -> Infisical
octl syncenv push              # both (default: all)

# or standalone:
syncenv push prod
```

### clean-branches

Delete all local git branches except `main` and `production`. Prompts for confirmation.

```bash
octl clean-branches
# or standalone:
clean-branches
```

## Environment mapping

| Argument | File               | Infisical env |
| -------- | ------------------ | ------------- |
| `dev`    | `.env.development` | `dev`         |
| `prod`   | `.env.production`  | `prod`        |
| `all`    | Both               | Both          |
