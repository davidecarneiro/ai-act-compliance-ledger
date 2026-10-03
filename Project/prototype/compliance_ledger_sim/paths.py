"""Resolution of the experiments output directory.

In the dissertation vault the code lives under 04_projeto/prototype/ and the
experimental results under 06_dados/experiments/; the directory is located by
walking up the tree until a folder holding both 06_dados/ and 04_projeto/ is
found. In the folder delivered with the dissertation the marker is a parent
holding both prototype/ and experiments/, and outputs go to that experiments/.
Where neither marker exists they fall back to an experiments/ folder next to
the code. The EXPERIMENTS_DIR environment variable overrides all of this.
"""

from __future__ import annotations

import os
from pathlib import Path


def _experiments_dir() -> Path:
    env = os.environ.get("EXPERIMENTS_DIR")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "06_dados").is_dir() and (parent / "04_projeto").is_dir():
            return parent / "06_dados" / "experiments"
        # Folder delivered with the dissertation: prototype/ and experiments/ side by side.
        if (parent / "prototype").is_dir() and (parent / "experiments").is_dir():
            return parent / "experiments"
    return here.parent / "experiments"


EXPERIMENTS_DIR = _experiments_dir()


def run_dir(name: str, create: bool = False) -> Path:
    """Resolve a named experiment in either supported directory layout.

    Existing runs/name and name directories take precedence, in that order.
    New runs use runs/name when the runs directory exists. Set create=True
    to create the selected directory."""
    drawer = EXPERIMENTS_DIR / "runs" / name
    flat = EXPERIMENTS_DIR / name
    if drawer.is_dir():
        return drawer
    if flat.is_dir():
        return flat
    alvo = drawer if (EXPERIMENTS_DIR / "runs").is_dir() else flat
    if create:
        alvo.mkdir(parents=True, exist_ok=True)
    return alvo
