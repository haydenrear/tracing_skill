from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install tracing-skill-observability into a Python environment.")
    parser.add_argument("--project", type=Path, help="uv project directory to install into.")
    parser.add_argument("--python", help="Python executable or virtualenv python to install into.")
    parser.add_argument("--source", type=Path, default=_default_source(), help="Path to sources/python package directory.")
    args = parser.parse_args(argv)

    source = args.source.resolve()
    if not (source / "pyproject.toml").exists():
        parser.error(f"source does not contain pyproject.toml: {source}")

    if args.project:
        cmd = ["uv", "pip", "install", "--project", str(args.project.resolve()), str(source)]
    elif args.python:
        cmd = ["uv", "pip", "install", "--python", args.python, str(source)]
    elif os.getenv("VIRTUAL_ENV"):
        cmd = ["uv", "pip", "install", "--python", str(Path(os.environ["VIRTUAL_ENV"]) / "bin" / "python"), str(source)]
    else:
        parser.error("pass --project or --python, or activate a virtualenv")

    subprocess.run(cmd, check=True)
    return 0


def _default_source() -> Path:
    skill_dir = os.getenv("SKILL_DIR")
    if skill_dir:
        return Path(skill_dir) / "sources" / "python"
    return Path(__file__).resolve().parents[2]


if __name__ == "__main__":
    raise SystemExit(main())
