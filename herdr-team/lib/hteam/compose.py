"""워커 사양 조립(설계 5.5)과 리뷰 프롬프트 조립(6.2). horch 프리앰블이 이 사양 앞에 붙는다."""
from __future__ import annotations

from . import lint, textlint
from .errors import USAGE, HteamError
from .paths import SHIM, TEMPLATES, report_rel, review_rel
from .util import fill, show

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
        prior = review_rel(tid, rd.get("prior_review_round") or n - 1)  # 사용자 요청 라운드는 기록한 리뷰 라운드
        verdict = rd.get("prior_verdict")
        if rd.get("from_user"):
            said = "(이전 리뷰는 승인이었다)" if verdict == "APPROVE" else ""
            parts.append(f"사용자가 일괄 승인에서 수정을 요청했다{said}. 아래 사용자 요청을 모두 반영하고, "
                         f"요청마다 어떻게 반영했는지 보고서 `## r{n}` 절에 적는다.")
        if (not rd.get("from_user") or verdict == "REQUEST_CHANGES") and (p.root / prior).is_file():
            # 사용자 요청 라운드여도 이전 리뷰가 수정 요청이었으면 그 지적은 아직 남아 있다
            parts.append(f"`{prior}` 의 지적을 모두 다룬다. 지적마다 어떻게 다뤘는지 보고서 `## r{n}` 절에 적는다.")
        if spec.role in ASK_ROLES:
            parts.append(f"먼저 `{SHIM} ask-user --task {tid} --pending` 과 `--history` 로 이전 질문과 답을 확인한다. "
                         f"답이 없는 질문이 있으면 새로 묻지 않고 `{SHIM} ask-user --task {tid} --wait <id>` 로 그 답을 "
                         "기다린다(Bash `timeout: 600000`).")
        if rd.get("supplement"):
            sup = rd["supplement"]
            parts.append(f"디렉터 보강 태스크 {sup} 의 결과(`{report_rel(sup)}`, `docs/design/system/`)를 반영한다.")
        if rd.get("note"):
            parts.append(f"{'사용자 요청' if rd.get('from_user') else '코디네이터 메모'}: {rd['note']}")
        if rd.get("coord_note"):  # 사용자 요청 라운드를 잇는 fix 의 코디네이터 메모(사용자 요청과 섞지 않는다)
            parts.append(f"코디네이터 메모: {rd['coord_note']}")
    return "\n".join(parts).rstrip() + "\n"


def round_requests(p, rd: dict) -> list[tuple[str, str]]:
    """이번 라운드의 요청 (이름, 글): 사용자 요청 또는 코디네이터 메모(note), 따로 적은 코디네이터 메모(coord_note),
    디렉터 보강(supplement). work_spec 의 수정 블록과 같은 이름이다."""
    found = []
    if rd.get("note"):
        found.append(("사용자 요청" if rd.get("from_user") else "코디네이터 메모", rd["note"]))
    if rd.get("coord_note"):
        found.append(("코디네이터 메모", rd["coord_note"]))
    if rd.get("supplement"):
        sup = rd["supplement"]
        found.append(("디렉터 보강", f"{sup} 의 결과(`{report_rel(sup)}`, `docs/design/system/`)를 반영한다"))
    return found


BROWSER_TOOLS = {  # 리뷰어 에이전트마다 렌더링에 쓸 브라우저 도구(설계 6.2)
    "codex": "`hteam-browser` 서버의 chrome-devtools 도구로 직접 연다(헤드리스·격리 프로필. 사용자 Chrome 프로필을 쓸 수 "
             "있는 다른 브라우저 MCP 는 쓰지 않는다)",
    "claude": "자기 Chrome DevTools MCP(chrome-devtools 도구)로 직접 연다",
}


def failure(exc: Exception) -> str:
    """자동 검사 실패 한 줄: `자동 검사 실패: <예외 이름>: <메시지>`(공백·줄바꿈을 한 칸으로, 200자까지)."""
    return " ".join(f"자동 검사 실패: {type(exc).__name__}: {exc}".split())[:200]


def guarded(check) -> list[str]:
    """자동 검사 하나(인자 없는 함수)를 따로 돌린다(설계 6.2). 예외로 실패하면 그 검사 결과 자리에 failure 한 줄을 넣고
    다른 검사와 리뷰는 계속한다."""
    try:
        return list(check())
    except Exception as exc:  # noqa: BLE001  경고 전용 검사가 리뷰를 막지 않는다
        return [failure(exc)]


def findings_list(items: list[str]) -> str:
    """자동 검사 경고의 `- ` 글머리 목록. 없으면 `- 없음`."""
    return "\n".join(f"- {show(x)}" for x in items) or "- 없음"


def design_findings(p, files: list[str], shas: list[str]) -> list[str]:
    """디자인 절의 경고 목록(설계 11.6): 내용 검사(lint, files 는 시도 기록의 바뀐 파일, shas 는 대상 커밋)를 guarded 로
    감싸 MAX_FINDINGS 까지. `hteam lint --task` 의 findings 도 이것이다."""
    return lint.cap(guarded(lambda: lint.design_findings(p.root, files)))


def text_findings(p, files: list[str], shas: list[str]) -> list[str] | None:
    """문구 절의 경고 목록(설계 11.7): 대상 커밋(shas)이 추가한 줄의 textlint 지적. `.herdr-team/text-rules.md` 가 없으면
    None(0.1.x 프로젝트)."""
    if not p.text_rules.is_file():
        return None
    return guarded(lambda: textlint.text_lint(p.root, files, shas))


def design_section(p, cfg, spec, files: list[str], shas: list[str], agent: str = "codex") -> str:
    """리뷰 프롬프트의 디자인 절(설계 6.2): director·designer·developer 태스크이고 설정에 `[roles.director]` 가 있을
    때만 디자인 기준(11장)과 자동 검사 경고(design_findings)를 넣는다. 아니면 빈 문자열. 렌더링에 쓸 도구는 리뷰어
    에이전트(agent)에 따라 다르다(BROWSER_TOOLS: Codex 는 hteam-browser, Claude 는 자기 DevTools MCP)."""
    if spec.role not in lint.DESIGN_ROLES or "director" not in cfg.roles:
        return ""
    return fill(_template("review-design.md"), browser=BROWSER_TOOLS.get(agent, BROWSER_TOOLS["claude"]),
                lint=findings_list(design_findings(p, files, shas))).rstrip() + "\n\n"


def text_section(p, files: list[str], shas: list[str]) -> str:
    """리뷰 프롬프트의 문구 절(설계 6.2·11.7): 직무와 관계없이 `.herdr-team/text-rules.md` 가 있고 바뀐 파일 가운데 문구
    대상(textlint.targets)이 하나 이상이면 문구 기준과 자동 검사 경고. 아니면 빈 문자열. 대상 판정도 자동 검사라서 예외로
    실패하면 대상이 있는지 모르므로 절을 붙이고 경고 자리에 failure 한 줄을 넣는다(리뷰는 계속한다)."""
    if not p.text_rules.is_file():
        return ""
    try:
        if not textlint.targets(p.root, files):
            return ""
    except Exception as exc:  # noqa: BLE001
        found = [failure(exc)]
    else:
        found = text_findings(p, files, shas) or []
    return fill(_template("review-text.md"), text_lint=findings_list(found)).rstrip() + "\n\n"


def review_prompt(p, cfg, spec, rd: dict, att: dict) -> str:
    """리뷰 프롬프트(설계 6.2). 입력(대상 커밋, 바뀐 파일)은 시도 기록에 저장된 것을 쓴다. 이번 라운드에 요청(사용자
    요청·코디네이터 메모·디렉터 보강, round_requests)이 있으면 그 요청과 그 라운드 작업 사양을 보이고 기준에 한 줄을 더한다
    (없으면 그대로).
    기준 뒤에 디자인 절(design_section), 문구 절(text_section) 순서로 붙인다. 없는 절은 빈 문자열이다."""
    tid, n = spec.id, rd["round"]
    prior = [review_rel(tid, r) for r in range(1, n) if (p.root / review_rel(tid, r)).is_file()]
    commits = att["inputs"]["commits"]
    files = att["inputs"]["files"]
    shas = [c["sha"] for c in commits]
    request, request_rule = "", ""
    asks = round_requests(p, rd)
    if asks:
        labels = "·".join(dict.fromkeys(label for label, _ in asks))
        work = p.work_file(tid, n).relative_to(p.root).as_posix()
        request = "".join(f"\n- 이번 라운드 {label}: {text}" for label, text in asks) + f"\n- 이번 라운드 작업 사양: `{work}`"
        request_rule = (f"\n5. 이번 라운드 요청(위 {labels})을 반영했는가. 요청이 사양의 Acceptance 를 바꾸면 요청을 따른 쪽을 "
                        "맞는 것으로 본다.")
    return fill(_template("review-prompt.md"), role=spec.role, role_title=cfg.role_title(spec.role), task_id=tid,
                round=str(n), attempt=str(att["attempt"]), title=spec.title, review_file=att["file"],
                spec_path=f".herdr-team/tasks/{tid}.md", role_doc=f".herdr-team/roles/{spec.role}.md",
                report=report_rel(tid), prior=", ".join(f"`{x}`" for x in prior) or "없음", request=request,
                request_rule=request_rule,
                design=design_section(p, cfg, spec, files, shas, att.get("agent") or "codex"),
                text=text_section(p, files, shas),
                commits="\n".join(f"- {c['sha'][:10]} {c['subject']}" for c in commits) or "- 없음",
                files="\n".join(f"- `{show(f)}`" for f in files) or "- 없음").rstrip() + "\n"
