#!/usr/bin/env bash
# herdr-orch 테스트. 저장소 루트나 어디서든 실행한다.
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 -m unittest discover -s tests -t . "$@"
