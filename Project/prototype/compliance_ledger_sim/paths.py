"""Resolution of the published evidence and of the output directory.

Two directories are distinguished:

* ``PUBLISHED_DIR`` holds the evidence shipped with the dissertation (tag
  ``thesis-v1.0``). It is read, never written: ``verify_delivery.py`` checks it
  against fixed final ``chain_hash`` anchors. It is located by walking up the
  tree: in the dissertation vault the code lives under 04_projeto/prototype/
  and the results under 06_dados/experiments/; in the delivered folder the
  marker is a parent holding both prototype/ and experiments/. Where neither
  marker exists it falls back to an experiments/ folder next to the code. The
  ``PUBLISHED_DIR`` environment variable overrides the search.
* ``EXPERIMENTS_DIR`` is where new runs write. It defaults to
  ``PUBLISHED_DIR / "article"``, so that regenerating a ledger, an OSCAL export
  or a benchmark for the article never replaces published evidence. The
  ``EXPERIMENTS_DIR`` environment variable overrides it, as before.
"""

from __future__ import annotations

import os
from pathlib import Path


def _published_dir() -> Path:
    env = os.environ.get("PUBLISHED_DIR")
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


def _experiments_dir() -> Path:
    env = os.environ.get("EXPERIMENTS_DIR")
    if env:
        return Path(env)
    return PUBLISHED_DIR / "article"


PUBLISHED_DIR = _published_dir()
EXPERIMENTS_DIR = _experiments_dir()


def _run_dir_in(base: Path, name: str, create: bool) -> Path:
    drawer = base / "runs" / name
    flat = base / name
    if drawer.is_dir():
        return drawer
    if flat.is_dir():
        return flat
    alvo = drawer if (base / "runs").is_dir() else flat
    if create:
        alvo.mkdir(parents=True, exist_ok=True)
    return alvo


def run_dir(name: str, create: bool = False) -> Path:
    """Resolve a named run under the output directory (``EXPERIMENTS_DIR``).

    Existing runs/name and name directories take precedence, in that order.
    New runs use runs/name when the runs directory exists. Set create=True
    to create the selected directory."""
    return _run_dir_in(EXPERIMENTS_DIR, name, create)


def published_run_dir(name: str) -> Path:
    """Resolve a named run in the published evidence (read only)."""
    return _run_dir_in(PUBLISHED_DIR, name, create=False)
