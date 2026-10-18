#!/usr/bin/env sh
# CLI 入口（macOS / Linux）。用法：./journal.sh status
set -e
cd "$(dirname "$0")"
export JOURNAL_HOME="${JOURNAL_HOME:-$HOME/DeepSeekJournal}"
export PYTHONIOENCODING=utf-8
exec "${PYTHON:-python3}" -m journal.cli "$@"
