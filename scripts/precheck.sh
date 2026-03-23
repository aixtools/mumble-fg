#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $# -eq 0 ]]; then
  cat >&2 <<'USAGE'
Usage:
  ./scripts/precheck.sh --message "feat(fg): your summary"
  ./scripts/precheck.sh --file /path/to/commit_message.txt
USAGE
  exit 2
fi

python3 "${SCRIPT_DIR}/validate_commit_message.py" "$@"

