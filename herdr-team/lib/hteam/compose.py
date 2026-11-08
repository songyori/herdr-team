"""워커 사양 조립(설계 5.5)과 리뷰 프롬프트 조립(6.2). horch 프리앰블이 이 사양 앞에 붙는다."""
from __future__ import annotations

from . import designdiff, lint, testgate, textlint
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


# 워커 사양의 테스트 절(설계 5.5, orca-team gate_block). {task_id} 는 태스크 ID 로 채운다
DEVELOPER_TEST_BLOCK = f"""## 테스트
- 순서: 작업을 `[{{task_id}}]` 커밋으로 먼저 커밋한다 → `{SHIM} test {{task_id}}` 를 돌린다 → 보고서를 따로 커밋한다. quick 은 커밋된 변경만 보므로 커밋하기 전에 돌리면 hteam 이 거부한다(exit 2).
- done 전에 `{SHIM} test {{task_id}}` 가 통과해야 한다(exit 0). 이 태스크가 바꾼 파일과 관련된 테스트만 돈다. 실패하면 고쳐서 커밋하고 다시 돌린다.
- 테스트가 소유 경로에 만드는 산출물(`__pycache__`, 스냅숏 등)은 소유 경로 안의 `.gitignore`(예: `src/.gitignore`)에 넣는다. 무시되지 않은 새 파일이 있으면 hteam test 가 거부한다.
- 전체 테스트는 돌리지 않는다. 묶음 테스트 태스크와 hteam 이 돌린다.
- 보고서의 검증 출력에 hteam test 출력의 `status`·`seconds` 를 붙인다. 실패를 고쳤으면 그 `tail` 도 붙인다.
- Bash 로 부를 때 `timeout: 600000` 을 준다. 그보다 오래 걸리면 `run_in_background: true` 로 돌리고 끝났다는 알림에서 출력을 읽는다."""
TESTER_TEST_BLOCK = f"""## 테스트
- 이 태스크는 묶음 테스트다. 선행 태스크(묶음 개발 태스크)의 기능을 잇는 묶음 통합 테스트를 소유 경로에 쓰고 커밋한다.
- 커밋한 뒤 `{SHIM} test {{task_id}} --full` 로 전체 테스트를 한 번 돌린다. 다시 돌리지 않는다. 리뷰는 같은 라운드에 보고서 밖 파일이 그대로면 이 결과를 다시 쓴다. 오래 걸리므로 Bash `run_in_background: true` 로 돌리고 끝났다는 알림에서 출력을 읽는다.
- 실패는 QA 보고서에서 둘로 나눈다. 테스트 코드의 잘못은 고친다(고친 테스트를 커밋한 뒤 `{SHIM} test {{task_id}}` 로 확인할 수 있다). 제품 회귀는 실패한 테스트 이름, 원인으로 보이는 선행 태스크 ID, 근거를 적는다. 제품 회귀는 리뷰가 `## 회귀` 로 넘기고 코디네이터가 회귀 수정 태스크로 만든다.
- 테스트를 통과시키려고 테스트를 약하게 만들거나 건너뛰거나 지우지 않는다. 제품 코드는 고치지 않는다."""
PENDING_TEST_BLOCK = f"""## 테스트(확정 대기)
- `docs/planning/tasks.toml` 의 `[test]` 를 사용자가 아직 확정하지 않았다. 그 quick·full 명령과 `{SHIM} test` 는 돌리지 않는다(확정 뒤에 리뷰하는 태스크는 관문이, 이미 관문 없이 리뷰한 태스크는 마무리의 마지막 full 이 돌린다).
- 테스트는 쓰고 커밋한다. 그 명령이 아닌 방법으로 할 수 있는 검증(빌드, 화면 확인, Acceptance 의 다른 확인)은 한다.
- 돌리지 못한 검증은 보고서 이번 라운드 절의 `### 테스트 확정 대기` 에 적는다(무엇을 확인하려 했는지, 확정 뒤 돌 명령). done 의 summary 에 "[test] 확정 필요" 를 넣는다. 확정을 기다리며 멈추지 않는다."""


def test_block(p, spec) -> str:
    """워커 사양의 테스트 절(설계 5.5): 직무가 developer·tester 이고 커밋된 HEAD 에 [test] 가 있을 때. 사용자가 확정했으면
    테스트 절, 아니면 확정 대기 절. [test] 가 없거나 읽지 못하면(형식·TOML 오류, 확정 기록 손상) 빈 문자열(리뷰 관문이
    알린다)."""
    if spec.role not in testgate.GATED_ROLES:
        return ""
    try:
        cfg = testgate.load_config(p)
        approved = cfg is not None and testgate.is_approved(p, testgate.digest(cfg))
    except HteamError:
        return ""
    if cfg is None:
        return ""
    if not approved:
        return PENDING_TEST_BLOCK
    block = TESTER_TEST_BLOCK if spec.role == testgate.TESTER_ROLE else DEVELOPER_TEST_BLOCK
    return block.format(task_id=spec.id)


def work_spec(p, cfg, spec, rd: dict, owns: list[str]) -> str:
    """직무 문서 → 태스크 본문 → 선행 태스크 → owns 와 작업 규칙 → 테스트 절(test_block) → 수정 블록(수정 라운드)."""
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
    block = test_block(p, spec)
    if block:
        parts += ["", block]
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
    """디자인 절의 경고 목록(설계 11.6): diff 검사(designdiff, 대상 커밋 shas 의 지운 줄·추가한 줄) 먼저, 내용 검사(lint,
    files 는 시도 기록의 바뀐 파일) 뒤. 검사마다 guarded 로 따로 감싸고 합쳐서 MAX_FINDINGS 까지. `hteam lint --task` 의
    findings 도 이것이다."""
    return lint.cap(guarded(lambda: designdiff.design_diff_lint(p.root, files, shas))
                    + guarded(lambda: lint.design_findings(p.root, files)))


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
