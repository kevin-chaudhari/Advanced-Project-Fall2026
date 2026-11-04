"""
Code version identifier stored with every trace.

A trace has to be matched to the implementation that produced it, so each run
records:

* ``git``  — commit SHA, branch, ``git describe``, commit time and whether the
  working tree had uncommitted changes to tracked files (with the changed paths);
  read with the ``git`` CLI, or straight from ``.git`` when the CLI is missing.
* ``source_sha256`` — a hash over the backend's Python source (paths + contents,
  line endings normalised so Windows and Linux checkouts hash the same). This
  identifies the code even when the run used uncommitted edits or no git at all.
* ``id`` — one short string combining both, e.g. ``72f97d6-dirty+src.3be1c0a9d2f4``.

``CODE_VERSION`` in the environment (e.g. set by CI or a deployment) is recorded
as ``override`` and used as the ``id`` prefix. Computed once per process: the
backend restarts when its code changes. Nothing secret is read or stored.
"""

from __future__ import annotations

import functools
import hashlib
import os
import platform
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

BACKEND = Path(__file__).resolve().parents[2]          # …/backend
REPO = BACKEND.parent
_SKIP_DIRS = {"__pycache__", "tests", "data", "exports", "venv", ".venv", "env", "node_modules", ".pytest_cache"}


def _git(*args: str, strip: bool = True) -> Optional[str]:
    try:
        r = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, timeout=5)
        return (r.stdout.strip() if strip else r.stdout) if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _git_from_files() -> Dict[str, Any]:
    """Read HEAD without the git CLI (branch + commit only; dirtiness unknown)."""
    g = REPO / ".git"
    try:
        head = (g / "HEAD").read_text().strip()
    except OSError:
        return {}
    if not head.startswith("ref:"):
        return {"commit": head, "branch": None, "dirty": None}
    ref = head.split(" ", 1)[1].strip()
    sha = None
    try:
        sha = (g / ref).read_text().strip()
    except OSError:
        try:
            for line in (g / "packed-refs").read_text().splitlines():
                if line.endswith(" " + ref):
                    sha = line.split(" ", 1)[0]
        except OSError:
            pass
    return {"commit": sha, "branch": ref.rsplit("/", 1)[-1] if ref.startswith("refs/heads/") else ref, "dirty": None}


def _git_info() -> Dict[str, Any]:
    sha = _git("rev-parse", "HEAD")
    if not sha:
        info = _git_from_files()
        if info:
            info["source"] = "git-files"
        return info
    changed: List[str] = [l[3:] for l in (_git("status", "--porcelain", "--untracked-files=no", strip=False) or "").splitlines() if l.strip()]
    return {"source": "git-cli", "commit": sha, "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
            "describe": _git("describe", "--tags", "--always", "--dirty"),
            "commit_time": _git("show", "-s", "--format=%cI", "HEAD"),
            "dirty": bool(changed), "changed_files": changed[:50], "changed_files_count": len(changed)}


def _source_files() -> List[Path]:
    files = []
    for p in BACKEND.rglob("*.py"):
        rel = p.relative_to(BACKEND)
        if any(part in _SKIP_DIRS for part in rel.parts[:-1]):
            continue
        files.append(p)
    return sorted(files, key=lambda p: p.relative_to(BACKEND).as_posix())


def source_hash() -> Dict[str, Any]:
    h = hashlib.sha256()
    files = _source_files()
    for p in files:
        h.update(p.relative_to(BACKEND).as_posix().encode())
        h.update(b"\0")
        h.update(p.read_bytes().replace(b"\r\n", b"\n"))
        h.update(b"\0")
    return {"source_sha256": h.hexdigest(), "source_files": len(files)}


@functools.lru_cache(maxsize=1)
def code_version() -> Dict[str, Any]:
    from harness.agent_trace.trace_schema import TRACE_SCHEMA_VERSION
    git = _git_info()
    src = source_hash()
    override = os.getenv("CODE_VERSION") or None
    if override:
        prefix = override
    elif git.get("commit"):
        prefix = git["commit"][:7] + ("-dirty" if git.get("dirty") else "")
    else:
        prefix = "nogit"
    return {"id": f"{prefix}+src.{src['source_sha256'][:12]}", "override": override, "git": git or None, **src,
            "trace_schema": TRACE_SCHEMA_VERSION, "python": platform.python_version()}
