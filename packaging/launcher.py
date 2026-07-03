"""Entry point for the packaged (PyInstaller) build.

Double-clicking the exe starts the local service with sensible defaults:
the workspace defaults to a `workspace/` folder next to the executable, and
the browser opens automatically. All CLI flags of bnct-agent-web still work.
"""
from __future__ import annotations

import multiprocessing
import sys
from pathlib import Path

from bnct_tps_agent.web_server import main


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


if __name__ == "__main__":
    multiprocessing.freeze_support()
    if "--root" not in sys.argv:
        workspace = _base_dir() / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        sys.argv += ["--root", str(workspace)]
    if "--open-browser" not in sys.argv:
        sys.argv.append("--open-browser")
    main()
