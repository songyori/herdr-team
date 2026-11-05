#!/usr/bin/env python3
"""herdr-team shim. herdr-team 플러그인의 bin/hteam 을 실행한다(플러그인 갱신이 바로 반영된다).

플러그인 위치(설계 3.4): HERDR_TEAM_PLUGIN_ROOT > .herdr-team/state/plugin-root(등록된 설치 경로이거나 디렉터리
마켓플레이스일 때만 믿는다) > 디렉터리 마켓플레이스 > installed_plugins.json. 못 찾으면 exit 12.
"""
import json
import os
import sys
from pathlib import Path


def real(path):
    try:
        return os.path.realpath(path)
    except (OSError, ValueError):
        return None


def directory_sources():
    """directory 소스 마켓플레이스의 <path>/herdr-team 목록."""
    known = Path(os.environ.get("HTEAM_KNOWN_MARKETPLACES_JSON")
                 or Path.home() / ".claude" / "plugins" / "known_marketplaces.json")
    found = []
    try:
        for entry in json.loads(known.read_text(encoding="utf-8")).values():
            source = entry.get("source") if isinstance(entry, dict) else None
            if isinstance(source, dict) and source.get("source") == "directory" and source.get("path"):
                found.append(Path(source["path"], "herdr-team"))
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    return found


def installed():
    registry = Path(os.environ.get("HTEAM_PLUGINS_JSON")
                    or Path.home() / ".claude" / "plugins" / "installed_plugins.json")
    try:
        data = json.loads(registry.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    plugins = data.get("plugins", data) if isinstance(data, dict) else {}
    paths = []
    for key, entries in (plugins.items() if isinstance(plugins, dict) else []):
        if key.split("@", 1)[0] != "herdr-team" or not isinstance(entries, list):
            continue
        for entry in sorted((e for e in entries if isinstance(e, dict)), key=lambda e: e.get("scope") != "user"):
            if isinstance(entry.get("installPath"), str) and entry["installPath"]:
                paths.append(Path(entry["installPath"]))
    return paths


def plugin_root():
    override = os.environ.get("HERDR_TEAM_PLUGIN_ROOT")
    if override:  # 사용자가 직접 준 경로다. bin/hteam 이 없으면 다른 곳으로 넘어가지 않고 실패한다
        return Path(override) if Path(override, "bin", "hteam").is_file() else None
    marker = Path(os.path.abspath(__file__)).parent.parent / "state" / "plugin-root"
    try:
        recorded = marker.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        recorded = ""
    trusted = {real(p) for p in installed() + directory_sources()} - {None}
    if recorded and Path(recorded, "bin", "hteam").is_file() and real(recorded) in trusted:
        return Path(recorded)
    for path in directory_sources() + installed():  # 디렉터리 소스가 오래된 설치 캐시보다 앞선다
        if (path / "bin" / "hteam").is_file():
            return path
    return None


root = plugin_root()
if root is None:
    override = os.environ.get("HERDR_TEAM_PLUGIN_ROOT")
    sys.stdout.write(json.dumps({"ok": False, "error": {
        "code": "plugin_missing",
        "message": (f"HERDR_TEAM_PLUGIN_ROOT({override}) 에 bin/hteam 이 없다" if override
                    else "herdr-team 플러그인을 찾지 못했다"),
        "hint": ("HERDR_TEAM_PLUGIN_ROOT 를 고치거나 지운다" if override
                 else "/plugin install herdr-team@herdr-team")}}, ensure_ascii=False) + "\n")
    sys.exit(12)
os.execv(sys.executable, [sys.executable, str(root / "bin" / "hteam"), *sys.argv[1:]])
