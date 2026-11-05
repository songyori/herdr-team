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


def validate(raw: dict) -> list[str]:
    """설계 4.2 검사. 모델·effort 값은 검사하지 않는다(에이전트가 판단)."""
    errors: list[str] = []
    if not _pos_int(raw.get("max_parallel", 4)):
        errors.append("max_parallel 은 1 이상의 정수다")
    if not _pos_int(_table(raw, "review", errors).get("max_rounds", 3)):
        errors.append("review.max_rounds 는 1 이상의 정수다")
    defaults = _table(raw, "defaults", errors)
    dworker = defaults.get("worker", "claude")
    if dworker not in AGENTS:
        errors.append(f"defaults.worker 는 claude·codex 중 하나다: {dworker!r}")
    for key in ("coordinator", "image"):
        _table(raw, key, errors)
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
    return errors


@dataclass
class Config:
    raw: dict
    max_parallel: int
    max_rounds: int
    user_approval_roles: list[str]
    coordinator: dict
    defaults: dict
    agent_args: dict[str, list[str]]
    image: dict
    roles: dict[str, dict]

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

    def image_choice(self) -> tuple[str | None, str | None]:
        """`hteam image` 의 Codex 모델·effort. [image] 에 없으면 [defaults] 의 codex_*(설계 4.1)."""
        return (self.image.get("codex_model") or self.defaults.get("codex_model"),
                self.image.get("codex_effort") or self.defaults.get("codex_effort"))


def build(raw: dict) -> Config:
    agents = raw.get("agents", {})
    return Config(
        raw=raw,
        max_parallel=raw.get("max_parallel", 4),
        max_rounds=raw.get("review", {}).get("max_rounds", 3),
        user_approval_roles=list(raw.get("user_approval_roles", [])),
        coordinator={"model": "opus", "effort": "xhigh", **raw.get("coordinator", {})},
        defaults={"worker": "claude", **raw.get("defaults", {})},
        agent_args={name: list(agents.get(name, {}).get("args", [])) for name in AGENTS},
        image=dict(raw.get("image", {})),
        roles=dict(raw.get("roles", {})),
    )


def load(p) -> Config:
    """설정을 읽는 명령은 모두 이것을 부른다. 깨졌으면 exit 2."""
    try:
        raw = tomllib.loads(p.config.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise HteamError("no_config", f"{p.config} 가 없다", USAGE, "/herdr-team:init 으로 세팅한다") from None
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
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
