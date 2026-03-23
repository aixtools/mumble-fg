#!/usr/bin/env python3
"""Validate commit messages against Conventional Commits."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ALLOWED_TYPES = (
    "feat",
    "fix",
    "docs",
    "refactor",
    "test",
    "chore",
    "ci",
    "build",
    "perf",
    "style",
    "revert",
)

_TYPE_PATTERN = "|".join(ALLOWED_TYPES)
COMMIT_RE = re.compile(
    rf"^(?P<type>{_TYPE_PATTERN})(\([a-z0-9][a-z0-9._/-]*\))?(?P<breaking>!)?: (?P<subject>\S.*)$",
    re.IGNORECASE,
)


def _read_subject_from_file(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        subject = line.strip()
        if subject:
            return subject
    return ""


def _validate(subject: str) -> tuple[bool, str]:
    if not subject:
        return False, "Commit message subject is empty."
    if COMMIT_RE.match(subject):
        return True, ""
    examples = ", ".join(
        [
            "feat(bg): add pilot snapshot hash cache",
            "docs: update installation guide",
            "fix(fg)!: rename deprecated endpoint",
        ]
    )
    return (
        False,
        "Invalid commit subject. Use Conventional Commits: "
        f"type(scope): summary. Allowed types: {', '.join(ALLOWED_TYPES)}. "
        f"Examples: {examples}",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Conventional Commit message.")
    parser.add_argument("--message", help="Commit subject text to validate.")
    parser.add_argument("--file", help="Path to commit message file (e.g. git commit-msg hook arg).")
    args = parser.parse_args()

    subject = (args.message or "").strip()
    if args.file:
        subject = _read_subject_from_file(Path(args.file))

    if not subject:
        parser.error("one of --message or --file with a non-empty subject is required")

    ok, error = _validate(subject)
    if ok:
        print(f"commit message ok: {subject}")
        return 0
    print(error, file=sys.stderr)
    print(f"received: {subject}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

