"""설정 읽기와 검사(설계 4장), 작업·리뷰 에이전트와 모델 결정(4.1)."""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass

from .errors import USAGE, HteamError
from .globs import owns_problem

AGENTS = ("claude", "codex")
CLAUDE_ONLY = ("director", "designer")  # Claude Design 을 쓰는 직무(설계 4.2, 11장)
ROLE_RE = re.compile(r"[a-z][a-z0-9-]*")
MODEL_KEYS = tuple(f"{a}_{k}" for a in AGENTS for k in ("model", "effort"))  # [defaults]·[roles.*] 의 모델·effort
CREW_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")  # 탭 id·인수인계 파일 이름·Codex 대화 이름에 쓴다(설계 4.1)
CREW_KEYS = ("title", "roles", "agent", "model", "effort")
OLD_CONFIG_MESSAGE = ("config.toml 에 [coordinator] 가 있다. 0.4.0 은 코디네이터 대신 관제(hteam drive)를 쓴다. "
                      "[coordinator] 를 지우고 템플릿의 [drive]·[overflow]·[crew.*] 를 옮긴다. 또는 config.toml 을 지운 뒤 "
                      "다시 세팅한다(/herdr-team:init. 있는 파일은 덮어쓰지 않으므로 config.toml 만 새로 생긴다)")
# Codex 의 샌드박스·승인 우회 플래그(herdr-orch agents._BYPASS 와 같은 목록. horch 는 이것이 있으면 -s·-a 를 뺀다)
CODEX_BYPASS = ("--dangerously-bypass-approvals-and-sandbox", "--yolo", "--full-auto", "--approve-for-me")


def other(agent: str) -> str:
    """리뷰어는 작업 에이전트의 반대쪽이다."""
    return "codex" if agent == "claude" else "claude"


def _pos_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _str_list(value, nonempty: bool) -> bool:
    return (isinstance(value, list) and all(isinstance(v, str) and v.strip() for v in value)
            and (bool(value) or not nonempty))


def _table(raw: dict, key: str, errors: list[str]) -> dict:
    value = raw.get(key, {})
    if not isinstance(value, dict):
        errors.append(f"[{key}] 는 표여야 한다")
        return {}
    return value


def _names(table: dict, where: str, keys, errors: list[str]) -> None:
    """모델·effort 값은 있으면 비지 않은 문자열이다(argv 에 그대로 들어간다). 무엇을 쓸 수 있는지는 에이전트가 판단한다."""
    errors += [f"{where}.{k} 는 비지 않은 문자열이다" for k in keys
               if k in table and not (isinstance(table[k], str) and table[k].strip())]


def _nonempty(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _crew(raw: dict, roles: dict, defaults: dict, dworker, errors: list[str]) -> None:
    """[crew.<이름>] 검사(설계 4.2 6단계). 해당하는 것을 모두 모은다."""
    crew = raw.get("crew", {})
    if not isinstance(crew, dict):
        errors.append("crew 는 표여야 한다")
        return
    owner: dict[str, str] = {}  # 직무 → 그 직무를 먼저 가진 고정 에이전트(설정 순서)
    for name, entry in crew.items():
        where = f"crew.{name}"
        if not CREW_NAME_RE.fullmatch(name):
            errors.append(f"{where}: 이름은 소문자로 시작하는 소문자·숫자·- 1–32자다")
        if not isinstance(entry, dict):
            errors.append(f"{where} 는 표여야 한다")
            continue
        if "title" in entry and not _nonempty(entry["title"]):
            errors.append(f"{where}.title 은 비지 않은 문자열이다")
        members = entry.get("roles")
        if not _str_list(members, nonempty=True):
            errors.append(f"{where}.roles 는 비지 않은 직무 이름 목록이다")
            members = []
        else:
            unknown = [r for r in members if r not in roles]
            if unknown:
                errors.append(f"{where}.roles 에 정의되지 않은 직무가 있다: {', '.join(unknown)}")
            for r in members:
                if r not in roles:
                    continue
                first = owner.setdefault(r, name)
                if first != name:
                    errors.append(f"직무 {r} 가 crew.{first} 와 {where} 에 함께 있다")
        agent = entry.get("agent", dworker)
        if agent not in AGENTS:
            errors.append(f"{where}.agent 는 claude·codex 다")
        else:
            if agent == "codex":
                errors += [f'{where}: {r} 는 claude 만 된다(agent = "codex")' for r in members if r in CLAUDE_ONLY]
            for kind in ("model", "effort"):
                if kind not in entry and not _nonempty(defaults.get(f"{agent}_{kind}")):
                    errors.append(f"{where}.{kind} 을 정하지 못했다([{where}].{kind} 또는 [defaults].{agent}_{kind})")
        extra = sorted(set(entry) - set(CREW_KEYS))
        if extra:
            errors.append(f"{where}: 모르는 키 {', '.join(extra)}")
        _names(entry, where, ("model", "effort"), errors)


def validate(raw: dict) -> list[str]:
    """설계 4.2 검사. 모델·effort 값은 비지 않은 문자열인지만 본다(어떤 값인지는 에이전트가 판단)."""
    errors: list[str] = []
    if not _pos_int(raw.get("max_parallel", 4)):
        errors.append("max_parallel 은 1 이상의 정수다")
    if not _pos_int(_table(raw, "review", errors).get("max_rounds", 3)):
        errors.append("review.max_rounds 는 1 이상의 정수다")
    defaults = _table(raw, "defaults", errors)
    dworker = defaults.get("worker", "claude")
    if dworker not in AGENTS:
        errors.append(f"defaults.worker 는 claude·codex 중 하나다: {dworker!r}")
    _names(defaults, "defaults", MODEL_KEYS, errors)
    if "coordinator" in raw:  # 0.3.0 설정이다. 이전 명령은 없다(설계 4.2 6단계)
        errors.append(OLD_CONFIG_MESSAGE)
    if not isinstance(_table(raw, "drive", errors).get("auto_up", True), bool):
        errors.append("drive.auto_up 은 true·false 다")
    if not isinstance(_table(raw, "overflow", errors).get("enabled", True), bool):
        errors.append("overflow.enabled 은 true·false 다")
    _names(_table(raw, "image", errors), "image", ("codex_model", "codex_effort"), errors)
    roles = _table(raw, "roles", errors)
    if not roles:
        errors.append("[roles.<직무>] 가 하나 이상 있어야 한다")
    for name, role in roles.items():
        if not isinstance(role, dict):
            errors.append(f"roles.{name} 는 표여야 한다")
            continue
        if not ROLE_RE.fullmatch(name):
            errors.append(f"직무 이름 {name!r} 은 소문자·숫자·- 만 쓴다")
        worker = role.get("worker", dworker)
        if worker not in AGENTS:
            errors.append(f"roles.{name}.worker 는 claude·codex 중 하나다: {worker!r}")
        elif name in CLAUDE_ONLY and worker != "claude":
            errors.append(f"roles.{name} 는 worker = \"claude\" 만 된다(Claude Design 을 쓴다)")
        _names(role, f"roles.{name}", MODEL_KEYS, errors)
        if not _str_list(role.get("owns"), nonempty=True):
            errors.append(f"roles.{name}.owns 는 비지 않은 문자열 목록이다")
        else:  # 태스크 owns 와 같은 규칙. 어기면 owns_too_wide 가 아니라 설정 오류로 알린다
            errors += [f"roles.{name}.owns {o!r}: {why}" for o in role["owns"] if (why := owns_problem(o))]
    approval = raw.get("user_approval_roles", [])
    if not _str_list(approval, nonempty=False):
        errors.append("user_approval_roles 는 문자열 목록이다")
    else:
        errors += [f"user_approval_roles 의 {r} 가 [roles] 에 없다" for r in approval if r not in roles]
    for name, agent in _table(raw, "agents", errors).items():
        if name not in AGENTS:
            errors.append(f"agents.{name}: 지원하지 않는 에이전트다(claude·codex)")
        elif not isinstance(agent, dict) or not _str_list(agent.get("args", []), nonempty=False):
            errors.append(f"agents.{name}.args 는 문자열 목록이다")
    _crew(raw, roles, defaults, dworker, errors)
    return errors


@dataclass(frozen=True)
class Crew:
    """고정 에이전트(설계 5.9). model·effort 는 처음 띄울 때만 쓴다."""
    name: str
    title: str
    roles: tuple[str, ...]
    agent: str
    model: str
    effort: str


@dataclass
class Config:
    raw: dict
    max_parallel: int
    max_rounds: int
    user_approval_roles: list[str]
    defaults: dict
    agent_args: dict[str, list[str]]
    image: dict
    roles: dict[str, dict]
    crew: dict[str, Crew]  # 설정 순서
    overflow: bool
    drive: dict

    def role(self, name: str) -> dict:
        if name not in self.roles:
            raise HteamError("unknown_role", f"설정에 직무 {name!r} 이 없다", USAGE,
                             f"있는 직무: {', '.join(self.roles)}")
        return self.roles[name]

    def role_title(self, name: str) -> str:
        return str(self.roles.get(name, {}).get("title") or name)

    def owns(self, name: str) -> list[str]:
        return list(self.role(name)["owns"])

    def is_approval(self, name: str) -> bool:
        return name in self.user_approval_roles

    def args(self, agent: str) -> list[str]:
        return list(self.agent_args.get(agent, []))

    def crew_of(self, role: str) -> Crew | None:
        """그 직무를 roles 에 가진 고정 에이전트. 없으면 그 직무 태스크는 임시 워커로 돈다."""
        return next((c for c in self.crew.values() if role in c.roles), None)

    @property
    def auto_up(self) -> bool:
        """메인 세션 훅이 확실히 죽은 관제를 다시 띄우나(설계 9.5). 키가 없으면 True."""
        return self.drive.get("auto_up", True)

    def image_choice(self) -> tuple[str | None, str | None]:
        """`hteam image` 의 Codex 모델·effort. [image] 에 없으면 [defaults] 의 codex_*(설계 4.1)."""
        return (self.image.get("codex_model") or self.defaults.get("codex_model"),
                self.image.get("codex_effort") or self.defaults.get("codex_effort"))


def build(raw: dict) -> Config:
    """검사를 통과한 설정만 받는다."""
    agents = raw.get("agents", {})
    defaults = {"worker": "claude", **raw.get("defaults", {})}
    crew = {}
    for name, entry in raw.get("crew", {}).items():
        agent = entry.get("agent", defaults["worker"])
        crew[name] = Crew(name, entry.get("title") or name, tuple(entry["roles"]), agent,
                          entry.get("model") or defaults[f"{agent}_model"],
                          entry.get("effort") or defaults[f"{agent}_effort"])
    return Config(
        raw=raw,
        max_parallel=raw.get("max_parallel", 4),
        max_rounds=raw.get("review", {}).get("max_rounds", 3),
        user_approval_roles=list(raw.get("user_approval_roles", [])),
        defaults=defaults,
        agent_args={name: list(agents.get(name, {}).get("args", [])) for name in AGENTS},
        image=dict(raw.get("image", {})),
        roles=dict(raw.get("roles", {})),
        crew=crew,
        overflow=raw.get("overflow", {}).get("enabled", True),
        drive=dict(raw.get("drive", {})),
    )


def crew_warnings(cfg: Config) -> list[str]:
    """경고(오류 아님, 설계 4.2): 고정 에이전트의 agent 가 그 roles 의 어느 직무의 작업 에이전트와도 같지 않다."""
    out = []
    for c in cfg.crew.values():
        workers = {cfg.roles[r].get("worker") or cfg.defaults.get("worker") or "claude" for r in c.roles}
        if c.agent not in workers:
            out.append(f"crew.{c.name}: 어느 직무의 작업 에이전트도 {c.agent} 가 아니다. 이 에이전트는 태스크를 받지 않는다"
                       "(태스크 front matter 의 worker 로만 받는다)")
    return out


def load(p) -> Config:
    """설정을 읽는 명령은 모두 이것을 부른다. 깨졌으면 exit 2."""
    try:
        raw = tomllib.loads(p.config.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise HteamError("no_config", f"{p.config} 가 없다", USAGE, "/herdr-team:init 으로 세팅한다") from None
    except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError) as exc:  # OSError: 디렉터리·권한 없음 등
        raise HteamError("bad_config", f"config.toml 을 읽지 못했다: {exc}", USAGE) from exc
    errors = validate(raw)
    if errors:
        raise HteamError("bad_config", "설정 검사 실패: " + "; ".join(errors), USAGE,
                         "`.herdr-team/config.toml` 을 고친다", data={"errors": errors})
    return build(raw)


@dataclass
class Choice:
    worker: str
    model: str | None
    effort: str | None
    reviewer: str
    review_model: str | None
    review_effort: str | None


def resolve(cfg: Config, role: str, front: dict | None = None, cli: dict | None = None) -> Choice:
    """값마다 따로: CLI(--worker·--model·--effort, 작업에만) > 태스크 front matter > [roles.<직무>] > [defaults]."""
    front, cli = front or {}, cli or {}
    table = cfg.role(role)
    worker = cli.get("worker") or front.get("worker") or table.get("worker") or cfg.defaults.get("worker") or "claude"
    if worker not in AGENTS:
        raise HteamError("bad_worker", f"worker 는 claude·codex 중 하나다: {worker!r}", USAGE)
    if role in CLAUDE_ONLY and worker != "claude":
        raise HteamError("claude_only_role", f"{role} 직무는 worker = \"claude\" 만 된다(Claude Design 을 쓴다)", USAGE)

    def pick(agent: str, kind: str, use_cli: bool) -> str | None:
        key = f"{agent}_{kind}"
        return (cli.get(kind) if use_cli else None) or front.get(key) or table.get(key) or cfg.defaults.get(key)

    reviewer = other(worker)
    return Choice(worker, pick(worker, "model", True), pick(worker, "effort", True),
                  reviewer, pick(reviewer, "model", False), pick(reviewer, "effort", False))


def crew_choice(cfg: Config, crew: Crew, role: str, front: dict | None,
                cli: dict | None) -> tuple[Choice, bool]:
    """고정 에이전트 태스크(설계 4.1 6단계): 작업 모델·effort 는 [crew.<이름>] > [defaults](build 가 채웠다).
    CLI --model·--effort 와 front matter 의 <agent>_model·<agent>_effort 는 쓰지 않고 둘째 값(model_ignored)만 True 로
    알린다. 리뷰어(반대쪽 에이전트)와 그 모델·effort 는 resolve 와 같은 직무 규칙이다(CLI 는 리뷰어에 쓰지 않는다)."""
    front, cli = front or {}, cli or {}
    rule = resolve(cfg, role, front, {"worker": crew.agent})
    ignored = any(cli.get(kind) or front.get(f"{crew.agent}_{kind}") for kind in ("model", "effort"))
    return Choice(crew.agent, crew.model, crew.effort, rule.reviewer, rule.review_model, rule.review_effort), bool(ignored)
