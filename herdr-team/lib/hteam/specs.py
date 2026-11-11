"""태스크 사양(설계 5.1): 읽기, 검사, `task new`."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import config, outbox, roles, state
from .errors import CONFLICT, USAGE, HteamError
from .globs import owns_problem, within
from .paths import find_project
from .util import read_json, write_atomic

ID_RE = re.compile(r"T-\d{3,}")
ISSUE_RE = re.compile(r"#?([0-9]{1,9})")  # 이슈 번호(설계 5.1 7단계). 앞의 # 는 뗀다
SECTIONS = ("Target", "Change", "Constraints", "Acceptance")
LIST_KEYS = ("owns", "depends_on")
PLACEHOLDER_RE = re.compile(r"<[^<>\n]*>")
# 자리표시를 지운 뒤 남는 목록·강조·인용 서식과 공백. 이것뿐이면 빈 절이다.
MARKUP_RE = re.compile(r"(?m)^\s*\d+[.)](?=\s)|[\s\-*_+>`~|]")
NEW_BODY = """## Target
<대상 파일·컴포넌트·환경>

## Change
<만들 결과>

## Constraints
<지킬 불변식, 호환성, 건드리지 말 것>

## Acceptance
<완료를 증명할 테스트·명령 출력·증거>
"""


@dataclass
class Spec:
    id: str
    role: str
    title: str
    front: dict
    sections: dict[str, str]
    body: str
    owns: list[str] | None = None
    depends_on: list[str] = field(default_factory=list)
    issue: str | None = None  # 이슈 번호 숫자 문자열(앞의 # 를 뗀 값). front["issue"] 는 쓴 값 그대로다


def issue_value(value) -> str | None:
    """사양 front matter·tasks.toml 의 issue(설계 5.1·5.2): 숫자 1–9자리(앞의 # 는 떼고 앞자리 0 은 그대로) 문자열.
    정수는 문자열로 본다(bool 은 아니다). 아니면 None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        value = str(value)
    if not isinstance(value, str):
        return None
    m = ISSUE_RE.fullmatch(value.strip())
    return m.group(1) if m else None


def _bad(message: str) -> HteamError:
    return HteamError("bad_spec", message, USAGE)


def _one_line(text: str) -> bool:
    """splitlines 가 나누는 모든 줄바꿈(\\r, \\x0b, \\x0c, \\x85, \\u2028 …)이 없다."""
    return text.splitlines() == [text]


def parse(text: str) -> Spec:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise _bad("사양 첫 줄이 front matter 시작(---)이 아니다")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise _bad("front matter 끝(---)이 없다") from None
    front: dict = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        if not sep:
            raise _bad(f"front matter 줄을 읽지 못했다: {line!r}")
        key, value = key.strip(), value.strip()
        front[key] = [v.strip() for v in value.split(",") if v.strip()] if key in LIST_KEYS else value
    missing = [k for k in ("id", "role", "title") if not front.get(k)]
    if missing:
        raise _bad(f"front matter 에 {', '.join(missing)} 가 없다")
    body = "\n".join(lines[end + 1:]).strip("\n") + "\n"
    sections: dict[str, str] = {}
    current, buf, fence = None, [], None
    for line in body.splitlines():
        # 코드 블록 안의 `## ...` 는 절 머리가 아니다. CommonMark 펜스 규칙: 여는 줄은 같은 문자 3개 이상
        # (백틱 펜스의 info 에 백틱이 있으면 인라인 코드라 펜스가 아니다), 닫는 줄은 같은 문자 ≥ 여는 길이 + 공백뿐.
        if fence is None:
            fm = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
            if fm and not (fm.group(1)[0] == "`" and "`" in fm.group(2)):
                fence = (fm.group(1)[0], len(fm.group(1)))
                if current is not None:
                    buf.append(line)
                continue
        else:
            if re.fullmatch(r" {0,3}" + re.escape(fence[0]) + "{%d,}[ \t]*" % fence[1], line):
                fence = None
            if current is not None:
                buf.append(line)
            continue
        m = None if fence else re.match(r"^## (.+?)\s*$", line)
        if m:
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current, buf = m.group(1), []
        elif current is not None:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    return Spec(id=front["id"], role=front["role"], title=front["title"], front=front, sections=sections, body=body,
                owns=front.get("owns") or None, depends_on=list(front.get("depends_on") or []),
                issue=issue_value(front.get("issue")))


def problems(spec: Spec) -> list[str]:
    """시작 전 검사(설계 5.1): 네 절이 있고 비지 않고 `<…>` 자리표시만 있지 않다."""
    found = []
    for name in SECTIONS:
        text = spec.sections.get(name)
        if text is None:
            found.append(f"## {name} 절이 없다")
        elif not MARKUP_RE.sub("", PLACEHOLDER_RE.sub("", text)):
            found.append(f"## {name} 절이 비었거나 <…> 자리표시뿐이다")
    if spec.front.get("worker") not in (None, "claude", "codex"):
        found.append(f"worker 는 claude·codex 중 하나다: {spec.front['worker']!r}")
    found += [f"depends_on 의 {d!r} 는 태스크 ID 가 아니다" for d in spec.depends_on if not ID_RE.fullmatch(d)]
    found += [f"owns {o!r}: {why}" for o in spec.owns or [] if (why := owns_problem(o))]
    if "issue" in spec.front and spec.issue is None:
        found.append(f"issue 는 숫자 1–9자리 이슈 번호다(앞의 # 는 뗀다): {spec.front['issue']!r}")
    return found


def load(p, tid: str) -> Spec:
    path = p.spec_path(tid)
    if not ID_RE.fullmatch(tid):
        raise HteamError("bad_task_id", f"태스크 ID 는 T- 와 숫자 3자리 이상이다: {tid!r}", USAGE)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise HteamError("unknown_task", f"{tid} 사양이 없다({path.relative_to(p.root)})", USAGE) from None
    except (OSError, ValueError) as exc:  # 디렉터리, 권한, UTF-8 아님
        raise _bad(f"{path.name} 을 읽지 못했다: {exc}") from None
    spec = parse(text)
    if spec.id != tid:
        raise _bad(f"{path.name} 의 id 가 {spec.id} 다")
    return spec


def check(p, cfg, tid: str) -> Spec:
    """start 전 검사. 어기면 exit 2 bad_spec(problems 목록)."""
    spec = load(p, tid)
    cfg.role(spec.role)
    found = problems(spec)
    if found:
        raise HteamError("bad_spec", f"{tid} 사양 검사 실패: " + "; ".join(found), USAGE,
                         "사양을 채우고 `spec: T-xxx` 로 커밋한다", data={"problems": found})
    return spec


def owns_of(cfg, spec: Spec) -> list[str]:
    """front matter owns 가 있으면 그것(직무 owns 를 좁힌다), 없으면 직무 owns."""
    return list(spec.owns) if spec.owns else cfg.owns(spec.role)


def list_ids(p) -> list[str]:
    if not p.tasks.is_dir():
        return []
    ids = [path.stem for path in p.tasks.glob("T-*.md") if ID_RE.fullmatch(path.stem)]
    return sorted(ids, key=state.id_number)


def _pending_ids(p) -> list[str]:
    """멈춘 plan apply 가 plan.json pending 에 잡아 둔 ID. 사양·상태 파일이 아직 없어도 다른 태스크가 쓰지 않는다."""
    plan = read_json(p.plan_file, None)
    pending = plan.get("pending") if isinstance(plan, dict) else None
    return [r["id"] for r in pending if isinstance(r, dict) and ID_RE.fullmatch(str(r.get("id")))] \
        if isinstance(pending, list) else []


def next_id(p) -> str:
    known = list_ids(p) + state.state_ids(p) + _pending_ids(p)
    n = max((state.id_number(t) for t in known), default=0) + 1
    return f"T-{n:03d}"


def render(tid: str, role: str, title: str, body: str, *, owns: list[str] | None = None,
           depends: list[str] | None = None, plan_key: str | None = None, front: dict | None = None) -> str:
    """front 의 키·값은 plan_key 줄 뒤에 `key: value` 로 더한다(관제가 만드는 기획 수정 태스크의 `plan: append`, 설계 8.9)."""
    lines = ["---", f"id: {tid}", f"role: {role}", f"title: {title}"]
    if owns:
        lines.append(f"owns: {', '.join(owns)}")
    if depends:
        lines.append(f"depends_on: {', '.join(depends)}")
    if plan_key:
        lines.append(f"plan_key: {plan_key}")
    lines += [f"{key}: {value}" for key, value in (front or {}).items()]
    lines.append("---")
    return "\n".join(lines) + "\n" + body


def add_depends(p, tid: str, dep: str) -> bool:
    """사양 front matter 의 depends_on 끝에 dep 을 더해 쓴다(줄이 없으면 닫는 `---` 앞에 `depends_on: <dep>`). 이미 있으면
    False(쓰지 않는다). 커밋은 부르는 쪽이 한다(관제의 UI 기반 처리, 설계 8.9)."""
    if dep in load(p, tid).depends_on:
        return False
    path = p.spec_path(tid)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")  # load 가 front matter 를 이미 검사했다
    at = next((i for i in range(1, end) if lines[i].partition(":")[0].strip() == "depends_on"), None)
    if at is None:
        lines.insert(end, f"depends_on: {dep}\n")
    else:
        old = lines[at].rstrip("\r\n")
        values = [v.strip() for v in old.partition(":")[2].split(",") if v.strip()]
        lines[at] = f"depends_on: {', '.join([*values, dep])}" + lines[at][len(old):]
    write_atomic(path, "".join(lines))
    return True


def new(p, cfg, role: str, title: str, owns: list[str] | None = None, depends: list[str] | None = None) -> dict:
    cfg.role(role)
    if not title.strip() or not _one_line(title):
        raise HteamError("bad_title", "제목은 비지 않은 한 줄이다", USAGE)
    for glob in owns or []:
        why = owns_problem(glob)
        if why:
            raise _bad(f"owns {glob!r}: {why}")
    wide = [o for o in owns or [] if not any(within(o, r) for r in cfg.owns(role))]
    if wide:  # start 의 checked_owns 와 같은 규칙. 묶음 정리 태스크는 직무별로 만든다(설계 8.4)
        raise HteamError("owns_too_wide", f"owns 가 직무 {role} 의 owns({', '.join(cfg.owns(role))}) 를 넘거나 판단할 수 "
                         f"없다: {', '.join(wide)}", USAGE, "직무 owns 안의 하위 경로로 좁힌다. 다른 직무의 파일이면 그 직무로 만든다")
    for dep in depends or []:
        if not ID_RE.fullmatch(dep):
            raise HteamError("bad_task_id", f"depends_on 의 {dep!r} 는 태스크 ID 가 아니다", USAGE)
    p.tasks.mkdir(parents=True, exist_ok=True)
    with state.project_lock(p):
        tid = next_id(p)
        path = p.spec_path(tid)
        try:
            with path.open("x", encoding="utf-8") as fh:
                fh.write(render(tid, role, title, NEW_BODY, owns=owns, depends=depends))
        except FileExistsError:
            raise HteamError("task_exists", f"{tid} 사양이 이미 있다", CONFLICT) from None
        state.create(p, tid, role)
    return {"id": tid, "path": str(path.relative_to(p.root)),
            "hint": f"네 절을 채우고 `git add -- {path.relative_to(p.root)} && git commit -m \"spec: {tid}\" -- "
                    f"{path.relative_to(p.root)}` 로 커밋한다"}


def _split(value: str | None) -> list[str] | None:
    return [v.strip() for v in value.split(",") if v.strip()] if value else None


def _cmd_task_new(args) -> dict:
    """메인·관제가 한다(큐 명령이 아니다, 설계 7.1·8.3). 관제 밖이면 메인 터미널이어야 한다."""
    p = find_project(args.root)
    if not roles.drive_env(p):
        outbox.require_main(p)
    return new(p, config.load(p), args.role, args.title, _split(args.owns), _split(args.depends_on))


def register(sub) -> None:
    task = sub.add_parser("task")
    tsub = task.add_subparsers(dest="task_cmd", required=True, parser_class=task.__class__)
    s = tsub.add_parser("new")
    s.add_argument("--role", required=True)
    s.add_argument("--title", required=True)
    s.add_argument("--owns", help="쉼표로 나눈 glob(직무 owns 를 좁힌다)")
    s.add_argument("--depends-on", help="쉼표로 나눈 태스크 ID")
    s.set_defaults(func=_cmd_task_new)
