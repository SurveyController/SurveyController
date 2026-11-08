#!/usr/bin/env bash
# Keep the existing entrypoint; select the interpreter explicitly if needed.
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "${JS_REVERSE_PYTHON:-python3}" "$script_dir/check-deps.py" "$@"
