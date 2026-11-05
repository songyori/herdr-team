"""워커 사양 조립(설계 5.5)과 리뷰 프롬프트 조립(6.2). horch 프리앰블이 이 사양 앞에 붙는다."""
from __future__ import annotations

from .errors import USAGE, HteamError
from .paths import SHIM, TEMPLATES, report_rel, review_rel
from .util import fill

ASK_ROLES = ("planner", "director")  # 사용자에게 직접 묻는 직무(설계 7.5)


def _template(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def role_doc(p, role: str) -> str:
    path = p.role_doc(role)
    try:
        return path.read_text(encoding="utf-8").rstrip() + "\n"
    except FileNotFoundError:
        raise HteamError("no_role_doc", f"직무 문서가 없다: {path.relative_to(p.root)}", USAGE) from None


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- `{x}`" for x in items)


def work_spec(p, cfg, spec, rd: dict, owns: list[str]) -> str:
    """직무 문서 → 태스크 본문 → 선행 태스크 → owns 와 작업 규칙 → 수정 블록(수정 라운드)."""
    tid, n = spec.id, rd["round"]
    if spec.role in ASK_ROLES:
        ask_rule = (f"사용자에게 물어야 하면 `{SHIM} ask-user --task {tid} --json -` 로 묻는다(Bash `timeout: 600000`, "
                    "직무 문서의 질문 형식). 코디네이터에게 물을 것은 프리앰블의 ask 명령을 쓴다.")
    else:
        ask_rule = "막히면 프리앰블의 ask 명령으로 코디네이터에게 묻고 답을 기다린다."
    parts = [role_doc(p, spec.role), "---", "",
             f"# 태스크 {tid} · 라운드 {n} — [{cfg.role_title(spec.role)}] {spec.title}", "", spec.body.strip(), ""]
    parts.append("## 선행 태스크")
    if spec.depends_on:
        parts.append("먼저 `docs/planning/contracts.md`(있으면)와 선행 태스크의 보고서를 읽는다:")
        parts += [f"- {d}: `{report_rel(d)}`" for d in spec.depends_on]
    else:
        parts.append("없음.")
    parts += ["", fill(_template("worker-rules.md"), owns=_bullets(owns), report=report_rel(tid), task_id=tid,
                       round=str(n), ask_rule=ask_rule).rstrip()]
    if n > 1:
        parts += ["", f"## 수정 라운드 r{n}",
                  f"이전 대화는 없다. 먼저 `{report_rel(tid)}` 와 `git log --grep '^\\[{tid}\\]'` 를 읽는다."]
        prior = review_rel(tid, n - 1)
        if (p.root / prior).is_file():
            parts.append(f"`{prior}` 의 지적을 모두 다룬다. 지적마다 어떻게 다뤘는지 보고서 `## r{n}` 절에 적는다.")
        if spec.role in ASK_ROLES:
            parts.append(f"먼저 `{SHIM} ask-user --task {tid} --pending` 과 `--history` 로 이전 질문과 답을 확인한다.")
        if rd.get("supplement"):
            sup = rd["supplement"]
            parts.append(f"디렉터 보강 태스크 {sup} 의 결과(`{report_rel(sup)}`, `docs/design/system/`)를 반영한다.")
        if rd.get("note"):
            parts.append(f"코디네이터 메모: {rd['note']}")
    return "\n".join(parts).rstrip() + "\n"
