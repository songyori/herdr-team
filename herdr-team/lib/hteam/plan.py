"""태스크 그래프(설계 5.2): `plan check`(읽기 전용), `plan apply [--append]`. `[test]` 가 있으면 그 형식과 묶음 규칙도 본다."""
from __future__ import annotations

import hashlib
import json
import re
import tomllib
from pathlib import Path

from . import config, gitio, roles, specs, state, testgate
from .errors import CONFLICT, USAGE, HteamError
from .globs import any_overlap, owns_problem, within
from .paths import find_project
from .util import die_at, read_json, write_atomic, write_json

PLAN_FILE = "docs/planning/tasks.toml"
KEY_RE = re.compile(r"[a-z0-9-]+")
TEXT_FIELDS = ("title", "target", "change", "constraints")
REQUIRED = ("key", "role", "title", "owns", "target", "change", "constraints", "acceptance")
ALLOWED = frozenset(REQUIRED + ("depends_on", "issue"))
NO_TEST = object()  # tasks.toml 에 [test] 가 없다(validate 의 test 기본값)


def read_plan_data(path: Path) -> dict:
    """tasks.toml 의 TOML 표 전체(`task` 목록과 `[test]` 등, 설계 5.2). task 는 [[task]] 표의 목록이어야 한다."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise HteamError("no_plan", f"{path} 가 없다", USAGE) from None
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise HteamError("bad_plan", f"tasks.toml 을 읽지 못했다: {exc}", USAGE) from exc
    tasks = data.get("task", [])
    if not isinstance(tasks, list) or not all(isinstance(t, dict) for t in tasks):
        raise HteamError("bad_plan", "tasks.toml 은 [[task]] 표의 목록이다", USAGE)
    return data


def plan_tasks(data: dict) -> list[dict]:
    return data.get("task", [])


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
        if "issue" in t and specs.issue_value(t["issue"]) is None:  # 7단계(설계 5.2)
            errors.append(f"{label}: issue 는 숫자 1–9자리 이슈 번호다(문자열이나 정수, 앞의 # 는 뗀다)")
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


def group_problems(keys: dict[str, dict], fresh: set[str], tester_paths=None) -> list[str]:
    """묶음 규칙(설계 5.2, `[test]` 가 있을 때). 묶음은 tester 태스크 하나와 그 depends_on 의 developer 태스크들이다.
    fresh(아직 적용하지 않은 key) 안의 태스크만 본다. 직무 이름은 설정과 관계없이 글자 그대로다. 문구는 orca-team 원문이다.
    tester_paths(`[test]` 의 7단계 키)가 있으면 규칙 1 의 시험 경로는 그 항목의 {key} 를 key 로 채운 것이다(QA 보고서
    경로는 그대로다)."""
    testers = [k for k, t in keys.items() if t["role"] == testgate.TESTER_ROLE]
    found = []
    for k in testers:
        if k not in fresh:
            continue
        paths = [f"tests/{k}/**"] if tester_paths is None else [path.replace("{key}", k) for path in tester_paths]
        want = paths + [f"docs/qa/{k}.md"]
        if sorted(keys[k]["owns"]) != sorted(want):
            shown = ", ".join(f'"{w}"' for w in want)
            found.append(f"{k}: tester 태스크 owns 는 정확히 [{shown}] 다")
        others = [d for d in keys[k].get("depends_on", []) if keys[d]["role"] != testgate.DEVELOPER_ROLE]
        if others:
            found.append(f"{k}: tester 태스크의 depends_on 에는 developer 태스크만 둔다({', '.join(others)})")
    for k, t in keys.items():
        if t["role"] != testgate.DEVELOPER_ROLE or k not in fresh:
            continue
        on_tester = [d for d in t.get("depends_on", []) if keys[d]["role"] == testgate.TESTER_ROLE]
        if on_tester:
            found.append(f"{k}: developer 태스크는 tester 태스크에 의존하지 않는다({', '.join(on_tester)}). "
                         "다음 묶음 구현이 앞 묶음 테스트를 기다리지 않게 한다")
        if all(o == "README.md" or o.startswith("docs/") for o in t["owns"]):  # 문서 전용은 묶음에 넣지 않아도 된다
            continue
        holders = [s for s in testers if k in keys[s].get("depends_on", [])]
        if len(holders) != 1:
            found.append(f"{k}: 문서 전용이 아닌 developer 태스크는 정확히 한 tester 태스크(묶음)의 depends_on 에 "
                         f"든다(지금: {', '.join(holders) or '없음'})")
    return found


def validate(cfg, tasks: list[dict], test=NO_TEST, applied=()) -> tuple[list[str], list[list[str]]]:
    """(오류 목록, 병렬 깊이 묶음). 구조 오류가 있으면 그래프 검사는 하지 않는다. test 는 tasks.toml 의 `[test]` 값이다
    (없으면 NO_TEST): 있으면 그 형식을 필드 오류와 함께 모으고, 그래프 검사가 통과하면 묶음 규칙을 아직 적용하지 않은
    key(applied 밖)에 본다(설계 5.2)."""
    errors, keys = _fields(cfg, tasks)
    if test is not NO_TEST:
        errors += testgate.config_problems(test)
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
    graph_ok = not errors
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
    if graph_ok and test is not NO_TEST:
        errors += group_problems(keys, set(keys) - set(applied), test.get("tester_paths"))
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


def _checked(cfg, data: dict, applied=()) -> list[list[str]]:
    errors, groups = validate(cfg, plan_tasks(data), data.get("test", NO_TEST), applied)
    if errors:
        raise HteamError("plan_invalid", f"tasks.toml 검사 실패({len(errors)}건)", USAGE,
                         data={"errors": errors, "groups": groups})
    return groups


def check(p, cfg, path: Path) -> dict:
    """읽기 전용. 파일 검사에 더해 이미 적용한 계획(plan.json)이 있으면 apply --append 가 받아들일지도 본다.
    그래서 기획 태스크의 사전 검사가 승인 전에 막는다(승인 뒤에는 고칠 라운드가 없다). 묶음 규칙은 적용한 key 를 빼고
    본다(apply --append 와 같다). 출력 test 는 그 파일에 `[test]` 가 있는지다."""
    data = read_plan_data(path)
    tasks = plan_tasks(data)
    plan = read_json(p.plan_file, None)
    known = _surviving(p, plan) if plan is not None and "test" in data else None
    groups = _checked(cfg, data, known or {})
    if plan is not None:
        _keep_applied(known if known is not None else _surviving(p, plan), tasks)
    return {"tasks": len(tasks), "groups": groups, "test": "test" in data}


def _surviving(p, plan: dict) -> dict:
    """plan.json 의 tasks 가운데 다음 apply 의 복구(_settle) 뒤에도 남을 항목(읽기 전용). pending 이 아니면 남는다.
    pending 은 _settle 처럼 사양이 HEAD 에 있으면(커밋 뒤에 멈춤, 마저 끝낸다) 남고 없으면(되돌린다) 빠진다."""
    pending = {r["key"]: _rel(p, r["id"]) for r in plan.get("pending", [])}
    committed = set(_pending_done(p, list(pending.values())))  # 일부만 커밋됐으면 apply 처럼 plan_incomplete
    return {k: v for k, v in plan["tasks"].items() if k not in pending or pending[k] in committed}


def digest(task: dict) -> str:
    return hashlib.sha1(json.dumps(task, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _keep_applied(known: dict, tasks: list[dict]) -> dict[str, dict]:
    """이미 적용한 key(known: plan.json 의 tasks)가 tasks 에 같은 내용으로 남아 있는가(읽기 전용). 빠졌거나 바뀌면
    plan_changed. tasks 는 _checked 를 통과한 것이다. key → 태스크를 돌려준다."""
    by_key = {t["key"]: t for t in tasks}
    for key, rec in known.items():
        if key not in by_key:
            raise HteamError("plan_changed", f"이미 적용한 {key} 가 tasks.toml 에서 빠졌다", USAGE,
                             "적용한 태스크는 tasks.toml 에 그대로 둔다")
        if digest(by_key[key]) != rec["digest"]:
            raise HteamError("plan_changed", f"이미 적용한 {key} 의 내용이 바뀌었다", USAGE,
                             "바꾸려면 새 key 로 더하거나 수정 태스크를 만든다")
    return by_key


def _body(t: dict) -> str:
    acceptance = "\n".join(f"- {a}" for a in t["acceptance"])
    return (f"## Target\n{t['target'].strip()}\n\n## Change\n{t['change'].strip()}\n\n"
            f"## Constraints\n{t['constraints'].strip()}\n\n## Acceptance\n{acceptance}\n")


def _spec_text(t: dict, tid: str, deps: list[str]) -> str:
    front = {"issue": specs.issue_value(t["issue"])} if "issue" in t else None  # plan_key 줄 다음(설계 5.2 7단계)
    return specs.render(tid, t["role"], t["title"].strip(), _body(t), owns=t["owns"], depends=deps, plan_key=t["key"],
                        front=front)


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
    if "issue" in t:
        want["issue"] = specs.issue_value(t["issue"])
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


def _pending_done(p, files: list[str]) -> list[str]:
    """pending 사양 files 가운데 HEAD 에 커밋된 것. 전부(커밋 뒤에 멈춤)나 하나도 없음(커밋 전)이 아니면 되돌리지도
    마저 끝내지도 못하므로 plan_incomplete 다. _settle 과 읽기 전용 check 가 같이 쓴다."""
    done = _committed(p, files)
    if done and len(done) != len(files):
        raise HteamError("plan_incomplete", f"앞선 plan apply 의 사양 일부만 커밋돼 있다: {', '.join(done)}", CONFLICT,
                         "남은 사양을 커밋하거나 커밋한 사양을 되돌린 뒤 다시 plan apply 한다")
    return done


def _settle(p, plan: dict) -> tuple[dict | None, dict | None]:
    """앞선 apply 가 남긴 pending 을 정리한다. 사양이 모두 HEAD 에 있으면 커밋 뒤에 멈춘 것이라 마저 끝내고
    (상태를 만든 뒤 pending 을 지우고 그 결과를 돌려준다), 하나도 없으면 커밋 전에 멈춘 것이라 되돌린다."""
    pending = plan["pending"]
    files = [_rel(p, r["id"]) for r in pending]
    done = _pending_done(p, files)
    if not done:
        return _rollback(p, plan), None
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
        data = read_plan_data(path)
        tasks = plan_tasks(data)
        plan = read_json(p.plan_file, None)
        # 묶음 규칙은 적용한 key 를 빼고 본다. 쓰기 전이라 복구(_settle) 뒤에도 남을 key 를 읽기 전용으로 센다
        groups = _checked(cfg, data, _surviving(p, plan) if plan is not None and "test" in data else {})
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
        by_key = _keep_applied(known, tasks)
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
                write_atomic(p.spec_path(tid), text)  # 쓰다 멈춰도 반쪽 사양이 제 경로에 남지 않는다(_check_ours 가 남으로 본다)
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
    roles.require_drive(p)
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
