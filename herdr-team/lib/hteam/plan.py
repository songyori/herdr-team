"""태스크 그래프(설계 5.2): `plan check`(읽기 전용), `plan apply [--append]`."""
from __future__ import annotations

import hashlib
import json
import re
import tomllib
from pathlib import Path

from . import config, gitio, roles, specs, state
from .errors import CONFLICT, USAGE, HteamError
from .globs import any_overlap, within
from .paths import find_project
from .util import read_json, write_json

PLAN_FILE = "docs/planning/tasks.toml"
KEY_RE = re.compile(r"[a-z0-9-]+")
TEXT_FIELDS = ("title", "target", "change", "constraints")
REQUIRED = ("key", "role", "title", "owns", "target", "change", "constraints", "acceptance")


def read_tasks(path: Path) -> list[dict]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise HteamError("no_plan", f"{path} 가 없다", USAGE) from None
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise HteamError("bad_plan", f"tasks.toml 을 읽지 못했다: {exc}", USAGE) from exc
    tasks = data.get("task", [])
    if not isinstance(tasks, list) or not all(isinstance(t, dict) for t in tasks):
        raise HteamError("bad_plan", "tasks.toml 은 [[task]] 표의 목록이다", USAGE)
    return tasks


def _str_list(value, nonempty: bool = True) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) and v.strip() for v in value) and \
        (bool(value) or not nonempty)


def _fields(cfg, tasks: list[dict]) -> tuple[list[str], dict[str, dict]]:
    errors: list[str] = []
    keys: dict[str, dict] = {}
    for i, t in enumerate(tasks):
        label = t["key"] if isinstance(t.get("key"), str) else f"#{i + 1}"
        errors += [f"{label}: {f} 가 없다" for f in REQUIRED if f not in t]
        key = t.get("key")
        if "key" in t:
            if not isinstance(key, str) or not KEY_RE.fullmatch(key):
                errors.append(f"{label}: key 는 [a-z0-9-] 만 쓴다")
            elif key in keys:
                errors.append(f"{label}: key 가 중복이다")
            else:
                keys[key] = t
        if "role" in t and t["role"] not in cfg.roles:
            errors.append(f"{label}: 직무 {t['role']!r} 가 설정에 없다")
        if "owns" in t and not _str_list(t["owns"]):
            errors.append(f"{label}: owns 는 비지 않은 문자열 목록이다")
        if not _str_list(t.get("depends_on", []), nonempty=False):
            errors.append(f"{label}: depends_on 은 문자열 목록이다")
        if "acceptance" in t and not _str_list(t["acceptance"]):
            errors.append(f"{label}: acceptance 는 비지 않은 문자열 목록이다")
        for f in TEXT_FIELDS:
            if f in t and not (isinstance(t[f], str) and t[f].strip()):
                errors.append(f"{label}: {f} 는 비지 않은 문자열이다")
        texts = [t.get(f) for f in TEXT_FIELDS] + (t["acceptance"] if _str_list(t.get("acceptance")) else [])
        if any(isinstance(v, str) and any(line.startswith("## ") for line in v.splitlines()) for v in texts):
            errors.append(f"{label}: 텍스트 필드에 '## ' 로 시작하는 줄이 있다(사양의 절 머리와 섞인다)")
    return errors, keys


def _cycle(deps: dict[str, list[str]]) -> list[str] | None:
    color: dict[str, int] = {}
    path: list[str] = []

    def visit(k: str) -> list[str] | None:
        color[k] = 1
        path.append(k)
        for d in deps[k]:
            if color.get(d) == 1:
                return path[path.index(d):] + [d]
            if d not in color:
                found = visit(d)
                if found:
                    return found
        path.pop()
        color[k] = 2
        return None

    for k in deps:
        if k not in color:
            found = visit(k)
            if found:
                return found
    return None


def validate(cfg, tasks: list[dict]) -> tuple[list[str], list[list[str]]]:
    """(오류 목록, 병렬 깊이 묶음). 구조 오류가 있으면 그래프 검사는 하지 않는다."""
    errors, keys = _fields(cfg, tasks)
    if errors:
        return errors, []
    deps = {k: list(t.get("depends_on", [])) for k, t in keys.items()}
    for k, ds in deps.items():
        errors += [f"{k}: 모르는 의존 {d!r}" for d in ds if d not in keys]
    if errors:
        return errors, []
    loop = _cycle(deps)
    if loop:
        return [f"순환 의존: {' -> '.join(loop)}"], []
    for k, t in keys.items():  # 태스크 owns 는 직무 owns 를 좁히기만 한다(설계 4.1)
        wide = [o for o in t["owns"] if not any(within(o, r) for r in cfg.owns(t["role"]))]
        if wide:
            errors.append(f"{k}: owns 가 직무 {t['role']} 의 owns 를 넘거나 판단할 수 없다: {', '.join(wide)}")
    anc: dict[str, set[str]] = {}

    def ancestors(k: str) -> set[str]:
        if k not in anc:
            found: set[str] = set()
            for d in deps[k]:
                found |= {d} | ancestors(d)
            anc[k] = found
        return anc[k]

    order = list(keys)
    for i, a in enumerate(order):
        for b in order[i + 1:]:
            related = a in ancestors(b) or b in ancestors(a)
            pairs = any_overlap(keys[a]["owns"], keys[b]["owns"])
            if not pairs:
                continue
            x, y = pairs[0]
            if not related:
                errors.append(f"{a} 와 {b} 의 owns 가 겹친다({x} ↔ {y}). 의존 관계가 아니면 함께 돌 수 있다")
            elif cfg.is_approval(keys[a]["role"]) and cfg.is_approval(keys[b]["role"]):
                errors.append(f"승인 직무 태스크 {a}·{b} 가 의존 관계이고 owns 가 겹친다({x} ↔ {y}). 선행이 "
                              "awaiting_user 로 잠금을 쥔 채 후행을 기다려 일괄 승인이 교착된다. owns 를 나누거나 승인 묶음을 나눈다")
    if "director" in cfg.roles and any(t["role"] == "designer" for t in keys.values()):
        directors = [k for k, t in keys.items() if t["role"] == "director"]
        if len(directors) != 1:
            errors.append(f"designer 태스크가 있으면 director 태스크가 정확히 하나여야 한다(지금 {len(directors)}개)")
        else:
            for k, t in keys.items():
                asset_only = all(o.startswith("assets/") for o in t["owns"])
                if t["role"] == "designer" and not asset_only and directors[0] not in ancestors(k):
                    errors.append(f"{k}: 에셋 전용이 아닌 designer 태스크는 director 태스크 {directors[0]} 에 "
                                  "직간접으로 의존해야 한다")
    depth: dict[str, int] = {}

    def level(k: str) -> int:
        if k not in depth:
            depth[k] = 0 if not deps[k] else 1 + max(level(d) for d in deps[k])
        return depth[k]

    groups: list[list[str]] = []
    for k in order:
        n = level(k)
        while len(groups) <= n:
            groups.append([])
        groups[n].append(k)
    return errors, groups


def check(p, cfg, path: Path) -> dict:
    tasks = read_tasks(path)
    errors, groups = validate(cfg, tasks)
    if errors:
        raise HteamError("plan_invalid", f"tasks.toml 검사 실패({len(errors)}건)", USAGE,
                         data={"errors": errors, "groups": groups})
    return {"tasks": len(tasks), "groups": groups}


def digest(task: dict) -> str:
    return hashlib.sha1(json.dumps(task, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _body(t: dict) -> str:
    acceptance = "\n".join(f"- {a}" for a in t["acceptance"])
    return (f"## Target\n{t['target'].strip()}\n\n## Change\n{t['change'].strip()}\n\n"
            f"## Constraints\n{t['constraints'].strip()}\n\n## Acceptance\n{acceptance}\n")


def _planned_specs(p) -> list[str]:
    found = []
    for tid in specs.list_ids(p):
        try:
            if specs.load(p, tid).front.get("plan_key"):
                found.append(tid)
        except HteamError:
            continue
    return found


def apply(p, cfg, append: bool) -> dict:
    path = p.root / PLAN_FILE
    result = check(p, cfg, path)
    tasks = read_tasks(path)
    with state.project_lock(p):
        plan = read_json(p.plan_file, None)
        if plan is None:
            planned = _planned_specs(p)
            if planned:
                raise HteamError("plan_state_missing", f"state/plan.json 이 없는데 계획된 태스크가 있다: {', '.join(planned)}",
                                 USAGE, "plan.json 을 잃었다. 메인에 알린다")
            plan = {"tasks": {}, "order": []}
        elif not append:
            raise HteamError("plan_applied", "이미 plan apply 했다", CONFLICT, "새 태스크만 더하려면 plan apply --append")
        known: dict = plan["tasks"]
        by_key = {t["key"]: t for t in tasks}
        for key, rec in known.items():
            if key not in by_key:
                raise HteamError("plan_changed", f"이미 적용한 {key} 가 tasks.toml 에서 빠졌다", USAGE,
                                 "적용한 태스크는 tasks.toml 에 그대로 둔다")
            if digest(by_key[key]) != rec["digest"]:
                raise HteamError("plan_changed", f"이미 적용한 {key} 의 내용이 바뀌었다", USAGE,
                                 "바꾸려면 새 key 로 더하거나 수정 태스크를 만든다")
        fresh = [t for t in tasks if t["key"] not in known]
        if not fresh:
            return {"applied": [], "commit": None, "groups": result["groups"]}
        n = state.id_number(specs.next_id(p))
        mapping = {k: rec["id"] for k, rec in known.items()}
        for i, t in enumerate(fresh):
            mapping[t["key"]] = f"T-{n + i:03d}"
        files = []
        for t in fresh:
            tid = mapping[t["key"]]
            text = specs.render(tid, t["role"], t["title"].strip(), _body(t), owns=t["owns"],
                                depends=[mapping[d] for d in t.get("depends_on", [])], plan_key=t["key"])
            p.tasks.mkdir(parents=True, exist_ok=True)
            p.spec_path(tid).write_text(text, encoding="utf-8")
            files.append(str(p.spec_path(tid).relative_to(p.root)))
        sha = gitio.commit_paths(p.root, files, f"[plan] apply: {len(fresh)} tasks")
        for t in fresh:
            known[t["key"]] = {"id": mapping[t["key"]], "digest": digest(t)}
        plan["order"] = [t["key"] for t in tasks]
        write_json(p.plan_file, plan)
        for t in fresh:
            state.create(p, mapping[t["key"]], t["role"])
    return {"applied": [{"key": t["key"], "id": mapping[t["key"]]} for t in fresh], "commit": sha,
            "groups": result["groups"]}


def order(p) -> list[str]:
    """start-ready 순서: tasks.toml 순서(plan.json), 그다음 나머지 ID 순."""
    plan = read_json(p.plan_file, None) or {}
    first = [plan["tasks"][k]["id"] for k in plan.get("order", []) if k in plan.get("tasks", {})]
    rest = [s["id"] for s in state.all_states(p) if s["id"] not in first]
    return first + rest


def _cmd_check(args) -> dict:
    p = find_project(args.root)
    path = Path(args.file) if args.file else p.root / PLAN_FILE
    if not path.is_absolute():
        path = Path.cwd() / path
    return {"file": str(path), **check(p, config.load(p), path)}


def _cmd_apply(args) -> dict:
    p = find_project(args.root)
    roles.require_coordinator(p)
    return apply(p, config.load(p), args.append)


def register(sub) -> None:
    plan = sub.add_parser("plan")
    psub = plan.add_subparsers(dest="plan_cmd", required=True, parser_class=plan.__class__)
    s = psub.add_parser("check")
    s.add_argument("--file")
    s.set_defaults(func=_cmd_check)
    s = psub.add_parser("apply")
    s.add_argument("--append", action="store_true")
    s.set_defaults(func=_cmd_apply)
