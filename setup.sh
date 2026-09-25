#!/usr/bin/env bash
# The launcher never evaluates configuration or installs packages implicitly.
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
python_bin="${DD_PYTHON:-python3}"
if ! command -v "$python_bin" >/dev/null 2>&1; then
    printf '%s\n' 'Python >=3.12 belum tersedia. Lihat README.md.' >&2
    exit 2
fi
export PYTHONPATH="${project_dir}/src${PYTHONPATH:+:${PYTHONPATH}}"
export PYTHONDONTWRITEBYTECODE=1
exec "$python_bin" -m dynamic_deployment "$@"
