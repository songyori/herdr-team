"""설정 읽기와 검사(설계 4장), 작업·리뷰 에이전트와 모델 결정(4.1)."""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from urllib.parse import urlsplit

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
# 작업 공간(설계 4.1·4.2·5.10, 7단계)
WORKSPACE_MODES = ("shared", "worktree")
WORKSPACE_ROLES = ("developer", "tester")  # roles 기본값
WORKSPACE_KEYS = ("mode", "roles", "slots", "setup", "teardown", "setup_timeout_min", "env")
ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
ENV_NAME_PREFIXES = ("HTEAM_", "HC_", "HORCH_")
ENV_NAME_WORDS = ("KEY", "SECRET", "TOKEN")  # Codex 의 셸 환경 정책이 뺄 수 있는 이름(herdr-orch 설계 14.3). 부분 문자열로 본다
ENV_VALUE_MAX = 1024  # UTF-8 바이트
# 워커에는 HTEAM_SLOT 을 더해 horch --env 로 넘기므로 horch 상한 32(herdr-orch workers.ENV_MAX)보다 하나 적다
WORKSPACE_ENV_MAX = 31
ENV_NAME_RULE = "이름은 대문자·숫자·_ 이고 HTEAM_·HC_·HORCH_ 로 시작하지 않으며 KEY·SECRET·TOKEN 을 담지 않는다"
ENV_VALUE_RULE = "값은 줄바꿈 없는 1 KiB 이하 문자열이다"
# Redmine(설계 4.1·4.2·8.12, 7단계)
REDMINE_KEYS = ("url", "key_env", "env_file", "status")
REDMINE_STATUS = ("start", "done", "changes", "closed")
ENV_VAR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")  # key_env


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


def _int_in(value, low: int, high: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _env_value_ok(value) -> bool:
    """한 줄(splitlines 가 나누는 줄바꿈 없음), NUL 없음, UTF-8 1024 바이트 이하 문자열. 빈 문자열은 된다."""
    return (isinstance(value, str) and (not value or value.splitlines() == [value]) and "\x00" not in value
            and len(value.encode("utf-8")) <= ENV_VALUE_MAX)


def _workspace(ws, roles: dict) -> list[str]:
    """[workspace] 표 검사(설계 4.1·4.2 7단계). 해당하는 것을 모두 모은다. shared 여도 같은 검사를 한다(검사만 하고
    쓰지 않는다). roles 는 [roles] 표(정의된 직무)다."""
    if not isinstance(ws, dict):
        return ["[workspace] 는 표여야 한다"]
    found = []
    if ws.get("mode", "shared") not in WORKSPACE_MODES:
        found.append("workspace.mode 는 shared·worktree 다")
    if "roles" in ws:
        if not _str_list(ws["roles"], nonempty=True):
            found.append("workspace.roles 는 비지 않은 직무 이름 목록이다")
        else:
            unknown = [r for r in ws["roles"] if r not in roles]
            if unknown:
                found.append(f"workspace.roles 에 정의되지 않은 직무가 있다: {', '.join(unknown)}")
    if "slots" in ws and not _int_in(ws["slots"], 1, 9):
        found.append("workspace.slots 는 1–9 정수다")
    found += [f"workspace.{k} 은 비지 않은 문자열이다" for k in ("setup", "teardown") if k in ws and not _nonempty(ws[k])]
    if "setup_timeout_min" in ws and not _int_in(ws["setup_timeout_min"], 1, 120):
        found.append("workspace.setup_timeout_min 은 1–120 정수다")
    env = ws.get("env", {})
    if not isinstance(env, dict):
        found.append("[workspace.env] 는 표여야 한다")
    else:
        for name, value in env.items():
            if (not ENV_NAME_RE.fullmatch(name) or name.startswith(ENV_NAME_PREFIXES)
                    or any(w in name for w in ENV_NAME_WORDS)):
                found.append(f"workspace.env.{name}: {ENV_NAME_RULE}")
            if not _env_value_ok(value):
                found.append(f"workspace.env.{name}: {ENV_VALUE_RULE}")
        if len(env) > WORKSPACE_ENV_MAX:
            found.append("workspace.env 는 31개 이하다(HTEAM_SLOT 을 더해 horch --env 32개 안이다)")
    extra = sorted(set(ws) - set(WORKSPACE_KEYS))
    if extra:
        found.append(f"workspace: 모르는 키 {', '.join(extra)}")
    return found


def _workspace_roles(ws: dict, roles: dict) -> tuple[str, ...]:
    """작업 공간 직무: 검사를 통과한 roles, 아니면(없거나 틀렸으면) 기본 roles 가운데 [roles] 에 정의된 것(기본 순서)."""
    members = ws.get("roles")
    if _str_list(members, nonempty=True) and all(r in roles for r in members):
        return tuple(members)
    return tuple(r for r in WORKSPACE_ROLES if r in roles)


def _workspace_owners(raw: dict, members: tuple[str, ...]) -> list[str]:
    """worktree 모드에서만(설계 4.2·5.10.6): 작업 공간 직무는 고정 에이전트도 승인 직무도 갖지 못한다."""
    found = []
    crew = raw.get("crew", {})
    for name, entry in (crew.items() if isinstance(crew, dict) else ()):
        if isinstance(entry, dict) and _str_list(entry.get("roles"), nonempty=False):
            found += [f"crew.{name}: {r} 는 작업 공간 직무다(worktree 모드에서는 임시 워커만 맡는다)"
                      for r in entry["roles"] if r in members]
    approval = raw.get("user_approval_roles", [])
    if _str_list(approval, nonempty=False):
        found += [f"user_approval_roles 의 {r} 는 작업 공간 직무다(worktree 모드에서는 승인 직무로 두지 않는다)"
                  for r in approval if r in members]
    return found


def _url_ok(url) -> bool:
    if not isinstance(url, str) or any(c.isspace() for c in url):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:  # 닫히지 않은 [ 같은 읽지 못하는 URL
        return False
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def _env_file_ok(path) -> bool:
    """프로젝트 안 상대 경로: 비지 않은 한 줄, ~ 로 시작하지 않고 절대 경로가 아니며 .. 마디가 없다."""
    if not _nonempty(path) or path.splitlines() != [path] or path.startswith("~"):
        return False
    pure = PurePosixPath(path)
    return not pure.is_absolute() and ".." not in pure.parts


def _redmine(rm) -> list[str]:
    """[redmine] 표 검사(설계 4.1·4.2·8.12 7단계). url·key_env·status 는 반드시 있고 env_file 은 선택이다."""
    if not isinstance(rm, dict):
        return ["[redmine] 는 표여야 한다"]
    found = []
    if not _url_ok(rm.get("url")):
        found.append("redmine.url 은 http·https URL 이다")
    if not (isinstance(rm.get("key_env"), str) and ENV_VAR_RE.fullmatch(rm["key_env"])):
        found.append("redmine.key_env 는 환경 변수 이름이다")
    if "env_file" in rm and not _env_file_ok(rm["env_file"]):
        found.append("redmine.env_file 은 프로젝트 안 상대 경로다")
    status = rm.get("status")
    if not (isinstance(status, dict) and set(status) == set(REDMINE_STATUS)
            and all(_pos_int(v) for v in status.values())):
        found.append("redmine.status 는 start·done·changes·closed 네 양의 정수다")
    extra = sorted(set(rm) - set(REDMINE_KEYS))
    if extra:
        found.append(f"redmine: 모르는 키 {', '.join(extra)}")
    return found


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
    if "workspace" in raw:
        ws = raw["workspace"]
        errors += _workspace(ws, roles)
        if isinstance(ws, dict) and ws.get("mode") == "worktree":
            errors += _workspace_owners(raw, _workspace_roles(ws, roles))
    if "redmine" in raw:
        errors += _redmine(raw["redmine"])
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


@dataclass(frozen=True)
class Workspace:
    """[workspace](설계 4.1·5.10). 표가 없으면 기본값(shared)이다. env 값의 {slot} 은 그대로 둔다(쓰는 쪽이 채운다)."""
    mode: str = "shared"
    roles: tuple[str, ...] = WORKSPACE_ROLES
    slots: int = 2
    setup: str | None = None
    teardown: str | None = None
    setup_timeout_min: int = 20
    env: dict[str, str] = field(default_factory=dict)

    @property
    def on(self) -> bool:
        return self.mode == "worktree"

    def covers(self, role: str) -> bool:
        """그 직무 태스크가 슬롯에서 도나(worktree 모드의 작업 공간 직무)."""
        return self.on and role in self.roles


@dataclass(frozen=True)
class Redmine:
    """[redmine](설계 4.1·8.12). url 은 끝의 / 를 뗀 값이다."""
    url: str
    key_env: str
    env_file: str | None
    status: dict[str, int]


@dataclass(frozen=True)
class RedmineKey:
    """테스트 실행 설정의 Redmine 몫: 테스트 환경에서 뺄 키 변수 이름만."""
    key_env: str


@dataclass(frozen=True)
class TestSettings:
    """`hteam test` 가 config.load 없이 쓰는 설정(설계 4.2: 설정이 깨져도 돈다). Config 와 같은 이름의 두 속성만 있어
    cfg.workspace·cfg.redmine.key_env 만 쓰는 함수는 Config 대신 이것을 받는다."""
    workspace: Workspace = field(default_factory=Workspace)
    redmine: RedmineKey | None = None


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
    workspace: Workspace = field(default_factory=Workspace)
    redmine: Redmine | None = None

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
        workspace=_build_workspace(raw["workspace"], raw.get("roles", {})) if "workspace" in raw else Workspace(),
        redmine=_build_redmine(raw["redmine"]) if "redmine" in raw else None,
    )


def _build_workspace(ws: dict, roles: dict) -> Workspace:
    """검사를 통과한 [workspace] 표. 없는 키는 기본값, roles 가 없으면 기본 roles 가운데 정의된 직무(설계 4.1)."""
    d = Workspace()
    return Workspace(mode=ws.get("mode", d.mode), roles=_workspace_roles(ws, roles), slots=ws.get("slots", d.slots),
                     setup=ws.get("setup"), teardown=ws.get("teardown"),
                     setup_timeout_min=ws.get("setup_timeout_min", d.setup_timeout_min), env=dict(ws.get("env", {})))


def _build_redmine(rm: dict) -> Redmine:
    return Redmine(url=rm["url"].rstrip("/"), key_env=rm["key_env"], env_file=rm.get("env_file"),
                   status={k: rm["status"][k] for k in REDMINE_STATUS})


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


def _raw_unchecked(p) -> dict:
    """config.toml 을 검사 없이 읽는다. 없거나 읽지 못하면 빈 표."""
    try:
        return tomllib.loads(p.config.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return {}


def _key_env(raw: dict) -> str | None:
    rm = raw.get("redmine")
    name = rm.get("key_env") if isinstance(rm, dict) else None
    return name if isinstance(name, str) and ENV_VAR_RE.fullmatch(name) else None


def redmine_key_env(p) -> str | None:
    """[redmine] key_env 이름(검사 없이, 설계 5.7·8.12). 테스트 환경에서 뺄 변수다. 다른 키가 틀려도 이름만 맞으면 낸다
    (키가 테스트 명령으로 가지 않는 쪽). 파일이 없거나 읽지 못하거나 이름이 틀리면 None. 예외를 내지 않는다."""
    return _key_env(_raw_unchecked(p))


def test_settings(p) -> TestSettings:
    """`hteam test` 의 설정(설계 4.2·5.7): config.toml 을 검사 없이 한 번 읽는다. [workspace] 는 그 표의 검사를 통과할
    때만 build 와 같은 값이고 아니면 기본값(shared)이다. 다른 표의 오류는 보지 않는다. 예외를 내지 않는다."""
    raw = _raw_unchecked(p)
    workspace = Workspace()
    ws = raw.get("workspace")
    if isinstance(ws, dict):
        roles = raw.get("roles") if isinstance(raw.get("roles"), dict) else {}
        if not _workspace(ws, roles):
            workspace = _build_workspace(ws, roles)
    name = _key_env(raw)
    return TestSettings(workspace=workspace, redmine=RedmineKey(name) if name else None)


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
