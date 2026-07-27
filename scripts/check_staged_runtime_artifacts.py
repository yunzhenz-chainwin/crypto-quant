#!/usr/bin/env python3
"""Block feature commits that include generated runtime artifacts.

The check is deliberately read-only: it inspects the Git index and never
stages, unstages, deletes, or rewrites a file.  Its non-zero exit code is
suitable for a pre-commit hook or a CI step.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path, PurePosixPath


GENERATED_REPORT_SUFFIXES = frozenset({".csv", ".json", ".png"})
GENERATED_REPORT_TEXT_PREFIXES = ("crosscheck_", "validation_")
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def normalize_git_path(path: str) -> str:
    """Return a repository-relative path using Git's forward-slash form."""

    return path.replace("\\", "/").removeprefix("./")


def is_runtime_artifact(path: str) -> bool:
    """Classify scheduler/runtime outputs while leaving reviewed docs trackable."""

    normalized = normalize_git_path(path)
    if normalized.startswith("data/clean/"):
        return True
    if not normalized.startswith("reports/"):
        return False

    relative = normalized.removeprefix("reports/")
    # Nested report outputs follow the same policy; Markdown remains available
    # for intentionally reviewed, human-authored reports.
    name = PurePosixPath(relative).name
    suffix = PurePosixPath(name).suffix.lower()
    return suffix in GENERATED_REPORT_SUFFIXES or (
        suffix == ".txt" and name.startswith(GENERATED_REPORT_TEXT_PREFIXES)
    )


def find_runtime_artifacts(paths: Iterable[str]) -> list[str]:
    """Return unique generated paths in stable display order."""

    return sorted(
        {
            normalized
            for path in paths
            if (normalized := normalize_git_path(path))
            and is_runtime_artifact(normalized)
        }
    )


def read_staged_paths() -> list[str]:
    """Read staged path names without changing the working tree or index."""

    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "-z", "--"],
        check=True,
        cwd=REPOSITORY_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return [
        entry.decode("utf-8", errors="surrogateescape")
        for entry in result.stdout.split(b"\0")
        if entry
    ]


def main() -> int:
    """Run the staged-artifact guard and return a hook-friendly exit code."""

    try:
        blocked = find_runtime_artifacts(read_staged_paths())
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        detail = (
            exc.stderr.decode(errors="replace").strip()
            if getattr(exc, "stderr", None)
            else str(exc)
        )
        print(
            f"[staged-runtime-check] ERROR: cannot read the Git index: {detail}",
            file=sys.stderr,
        )
        return 2

    if not blocked:
        print("[staged-runtime-check] OK: no generated runtime artifacts are staged.")
        return 0

    print(
        f"[staged-runtime-check] BLOCKED: {len(blocked)} generated runtime artifact(s) are staged:",
        file=sys.stderr,
    )
    for path in blocked:
        print(f"  - {path}", file=sys.stderr)
    print(
        "These files are rewritten by schedulers or research replays and must not be mixed into a feature commit.\n"
        "Restage only the intended source/docs. This read-only check never unstages, deletes, or modifies the index.\n"
        "For a reviewed baseline, use docs/, tests/fixtures/, or a separate versioned snapshot commit.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
