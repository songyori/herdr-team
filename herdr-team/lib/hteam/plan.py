"""태스크 그래프(설계 5.2): `plan check`(읽기 전용), `plan apply [--append]`."""
from __future__ import annotations

import hashlib
import json
import re
import tomllib
from pathlib import Path

from . import config, gitio, roles, specs, state
from .errors import CONFLICT, USAGE, HteamError
from .globs import any_overlap, owns_problem, within
from .paths import find_project
from .util import die_at, read_json, write_json

PLAN_FILE = "docs/planning/tasks.toml"
KEY_RE = re.compile(r"[a-z0-9-]+")
TEXT_FIELDS = ("title", "target", "change", "constraints")
REQUIRED = ("key", "role", "title", "owns", "target", "change", "constraints", "acceptance")
ALLOWED = frozenset(REQUIRED + ("depends_on",))


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
        unknown = sorted(set(t) - ALLOWED)
        if unknown:  # 오타(depends 등)를 조용히 버리지 않는다
            errors.append(f"{label}: 모르는 필드 {', '.join(unknown)}")
        key = t.get("key")
        if "key" in t:
            if not isinstance(key, str) or not KEY_RE.fullmatch(key):
                errors.append(f"{label}: key 는 [a-z0-9-] 만 쓴다")
            elif key in keys:
                errors.append(f"{label}: key 가 중복이다")
            else:
                keys[key] = t
        if "role" in t and not isinstance(t["role"], str):
            errors.append(f"{label}: role 은 문자열이다")
        elif "role" in t and t["role"] not in cfg.roles:
            errors.append(f"{label}: 직무 {t['role']!r} 가 설정에 없다")
        if "owns" in t and not _str_list(t["owns"]):
            errors.append(f"{label}: owns 는 비지 않은 문자열 목록이다")
        elif "owns" in t:
            errors += [f"{label}: owns {o!r}: {why}" for o in t["owns"] if (why := owns_problem(o))]
        if not _str_list(t.get("depends_on", []), nonempty=False):
            errors.append(f"{label}: depends_on 은 문자열 목록이다")
        elif len(set(t.get("depends_on", []))) != len(t.get("depends_on", [])):
            errors.append(f"{label}: depends_on 에 같은 key 가 두 번 있다")
        if "acceptance" in t and not _str_list(t["acceptance"]):
            errors.append(f"{label}: acceptance 는 비지 않은 문자열 목록이다")
        for f in TEXT_FIELDS:
            if f in t and not (isinstance(t[f], str) and t[f].strip()):
                errors.append(f"{label}: {f} 는 비지 않은 문자열이다")
        if isinstance(t.get("title"), str) and t["title"].strip() and not specs._one_line(t["title"].strip()):
            errors.append(f"{label}: title 은 한 줄이다(사양 front matter 에 들어간다)")
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
    ids = {k: f"T-{i + 1:03d}" for i, k in enumerate(keys)}  # 자리 ID. 실제 ID 와 모양이 같아 결과도 같다
    for k, t in keys.items():
        errors += [f"{k}: {e}" for e in _roundtrip(t, ids[k], [ids[d] for d in deps[k]])]
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


def _checked(cfg, tasks: list[dict]) -> list[list[str]]:
    errors, groups = validate(cfg, tasks)
    if errors:
        raise HteamError("plan_invalid", f"tasks.toml 검사 실패({len(errors)}건)", USAGE,
                         data={"errors": errors, "groups": groups})
    return groups


def check(p, cfg, path: Path) -> dict:
    tasks = read_tasks(path)
    return {"tasks": len(tasks), "groups": _checked(cfg, tasks)}


def digest(task: dict) -> str:
    return hashlib.sha1(json.dumps(task, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _body(t: dict) -> str:
    acceptance = "\n".join(f"- {a}" for a in t["acceptance"])
    return (f"## Target\n{t['target'].strip()}\n\n## Change\n{t['change'].strip()}\n\n"
            f"## Constraints\n{t['constraints'].strip()}\n\n## Acceptance\n{acceptance}\n")


def _spec_text(t: dict, tid: str, deps: list[str]) -> str:
    return specs.render(tid, t["role"], t["title"].strip(), _body(t), owns=t["owns"], depends=deps, plan_key=t["key"])


def _roundtrip(t: dict, tid: str, deps: list[str]) -> list[str]:
    """사양으로 쓴 뒤 다시 읽어도 검사한 값 그대로이고 start 전 검사(specs.problems)를 통과하는가."""
    try:
        spec = specs.parse(_spec_text(t, tid, deps))
    except HteamError as exc:
        return [f"사양으로 옮기면 읽히지 않는다: {exc.message}"]
    found = [f"사양으로 옮기면 {e}" for e in specs.problems(spec)]
    want = {"id": tid, "role": t["role"], "title": t["title"].strip(), "owns": t["owns"], "plan_key": t["key"]}
    if deps:
        want["depends_on"] = deps
    if spec.front != want:
        found.append("사양으로 옮기면 front matter(role·title·owns·depends_on·plan_key)가 바뀐다")
    return found


def _rel(p, tid: str) -> str:
    return str(p.spec_path(tid).relative_to(p.root))


def _committed(p, files: list[str]) -> list[str]:
    """files(프로젝트 기준) 가운데 HEAD 에 있는 것. 없다고 확인된 것만 빠진다. git 이 읽지 못하면 git_failed 로
    멈춘다(되돌리지 않는다). 프로젝트가 git 하위 디렉터리일 수 있어 git 최상위 기준 경로로 바꿔 찾는다."""
    if not files or not gitio.has_head(p.root):
        return []
    top = gitio.top_prefix(p.root)
    return [f for f in files if gitio.blob(p.root, "HEAD", top + f)]


def _check_ours(p, pending: list[dict], need_file: bool) -> None:
    """pending ID 의 사양이 그 apply 가 쓴 것(front matter plan_key 가 pending key)인지 본다. 다른 길로 같은 ID 를
    쓴 사양이면 지우거나 받아들이지 않고 멈춘다. need_file 이 거짓이면 아직 쓰지 않은(없는) 사양은 넘어간다."""
    taken = []
    for r in pending:
        path = p.spec_path(r["id"])
        if not need_file and not path.exists():
            continue
        try:
            key = specs.parse(path.read_text(encoding="utf-8")).front.get("plan_key")
        except (OSError, ValueError, HteamError):
            key = None
        if key != r["key"]:
            taken.append(r["id"])
    if taken:
        raise HteamError("plan_id_taken", f"앞선 plan apply 가 잡아 둔 {', '.join(taken)} 에 그 apply 가 쓰지 않은 사양이 "
                         "있다", CONFLICT, "그 사양을 다른 ID 로 옮기거나 치운 뒤 다시 plan apply 한다")


def _rollback(p, plan: dict) -> dict | None:
    """커밋 전에 멈춘 apply 를 되돌린다: 그 실행이 쓴 사양을 인덱스에서 빼고 지운 뒤 plan.json 에서 뺀다.
    plan.json 은 마지막에 쓴다. 중간에 실패하면 pending 이 남아 다음 apply 가 마저 되돌린다."""
    pending = plan["pending"]
    _check_ours(p, pending, need_file=False)
    files = [_rel(p, r["id"]) for r in pending]
    gitio.unstage(p.root, files)
    for f in files:
        (p.root / f).unlink(missing_ok=True)
    rest = {k: v for k, v in plan["tasks"].items() if k not in {r["key"] for r in pending}}
    if not rest:
        p.plan_file.unlink(missing_ok=True)
        return None
    plan = {"tasks": rest, "order": [k for k in plan["order"] if k in rest]}
    write_json(p.plan_file, plan)
    return plan


def _settle(p, plan: dict) -> tuple[dict | None, dict | None]:
    """앞선 apply 가 남긴 pending 을 정리한다. 사양이 모두 HEAD 에 있으면 커밋 뒤에 멈춘 것이라 마저 끝내고
    (상태를 만든 뒤 pending 을 지우고 그 결과를 돌려준다), 하나도 없으면 커밋 전에 멈춘 것이라 되돌린다."""
    pending = plan["pending"]
    files = [_rel(p, r["id"]) for r in pending]
    done = _committed(p, files)
    if not done:
        return _rollback(p, plan), None
    if len(done) != len(files):
        raise HteamError("plan_incomplete", f"앞선 plan apply 의 사양 일부만 커밋돼 있다: {', '.join(done)}", CONFLICT,
                         "남은 사양을 커밋하거나 커밋한 사양을 되돌린 뒤 다시 plan apply 한다")
    _check_ours(p, pending, need_file=True)
    for r in pending:
        state.create(p, r["id"], r["role"])
    resumed = {"applied": [{"key": r["key"], "id": r["id"]} for r in pending],
               "commit": gitio.last_commit(p.root, files[0])}
    plan = {k: v for k, v in plan.items() if k != "pending"}
    write_json(p.plan_file, plan)
    return plan, resumed


def _planned_specs(p) -> list[str]:
    found = []
    committed = set(_committed(p, [_rel(p, tid) for tid in specs.list_ids(p)]))
    for tid in specs.list_ids(p):
        if _rel(p, tid) not in committed:
            continue  # 커밋하지 않은 사양은 계획이 아니다(멈춘 apply 가 남긴 파일이 재시도를 막지 않게)
        try:
            if specs.load(p, tid).front.get("plan_key"):
                found.append(tid)
        except HteamError:
            continue
    return found


def apply(p, cfg, append: bool) -> dict:
    """tasks.toml 을 프로젝트 잠금 아래에서 한 번 읽어 검사하고 적용한다.

    실패할 수 있는 일(검사, 사양 왕복, digest)은 쓰기 전에 끝낸다. 쓰기 순서: plan.json(이번 태스크를 pending 으로)
    → 사양 → 경로 지정 커밋 → pending 상태 파일 → pending 지움. 커밋이 실패하면 이번에 쓴 것을 되돌린다. 커밋 앞뒤에서
    프로세스가 죽으면 다음 apply(--append 없이도)가 pending 을 보고 되돌리거나 마저 끝낸다. 상태 만들기는 늘 다시 해도
    된다. pending ID 는 specs.next_id 가 예약한다."""
    path = p.root / PLAN_FILE
    with state.project_lock(p):
        tasks = read_tasks(path)
        groups = _checked(cfg, tasks)
        plan = read_json(p.plan_file, None)
        resumed = None
        if plan is not None and plan.get("pending"):
            plan, resumed = _settle(p, plan)
        if plan is None:
            planned = _planned_specs(p)
            if planned:
                raise HteamError("plan_state_missing", f"state/plan.json 이 없는데 계획된 태스크가 있다: {', '.join(planned)}",
                                 USAGE, "plan.json 을 잃었다. 메인에 알린다")
            plan = {"tasks": {}, "order": []}
        elif not append and resumed is None:
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
        for key, rec in known.items():  # 앞선 apply 가 상태를 다 만들지 못하고 멈췄으면 여기서 채운다
            state.create(p, rec["id"], by_key[key]["role"])
        fresh = [t for t in tasks if t["key"] not in known]
        if not fresh:
            return {"applied": resumed["applied"] if resumed else [], "commit": resumed["commit"] if resumed else None,
                    "groups": groups}
        n = state.id_number(specs.next_id(p))
        mapping = {k: rec["id"] for k, rec in known.items()}
        for i, t in enumerate(fresh):
            mapping[t["key"]] = f"T-{n + i:03d}"
        texts = {mapping[t["key"]]: _spec_text(t, mapping[t["key"]], [mapping[d] for d in t.get("depends_on", [])])
                 for t in fresh}
        for t in fresh:
            known[t["key"]] = {"id": mapping[t["key"]], "digest": digest(t)}
        plan["order"] = [t["key"] for t in tasks]
        plan["pending"] = [{"key": t["key"], "id": mapping[t["key"]], "role": t["role"]} for t in fresh]
        files = [_rel(p, tid) for tid in texts]
        write_json(p.plan_file, plan)
        try:
            p.tasks.mkdir(parents=True, exist_ok=True)
            for tid, text in texts.items():
                p.spec_path(tid).write_text(text, encoding="utf-8")
            die_at("plan_before_commit")
            sha = gitio.commit_paths(p.root, files, f"[plan] apply: {len(fresh)} tasks")
        except (HteamError, OSError) as exc:
            try:
                if not _committed(p, files):
                    _rollback(p, plan)
            except (HteamError, OSError) as again:
                if isinstance(exc, HteamError):
                    exc.hint = f"되돌리지 못했다({again}). 원인을 없애고 다시 plan apply 하면 마저 정리한다"
            raise
        die_at("plan_after_commit")
        for t in fresh:
            state.create(p, mapping[t["key"]], t["role"])
        del plan["pending"]
        write_json(p.plan_file, plan)
    applied = [{"key": t["key"], "id": mapping[t["key"]]} for t in fresh]
    return {"applied": (resumed["applied"] if resumed else []) + applied, "commit": sha, "groups": groups}


def order(p) -> list[str]:
    """start-ready 순서: tasks.toml 순서(plan.json), 그다음 나머지 ID 순."""
    plan = read_json(p.plan_file, None) or {}
    pending = {r["key"] for r in plan.get("pending", [])}  # 아직 커밋되지 않았을 수 있다
    first = [plan["tasks"][k]["id"] for k in plan.get("order", []) if k in plan.get("tasks", {}) and k not in pending]
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
