# herdr-team 13단계 p13d(웹 플랫폼, 문서·버전) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 설계 15.3 의 13 가운데 p13d 를 만들고 13단계를 한 릴리스(herdr-team 0.8.0, herdr-orch 0.5.1)로 묶는다. 웹 UI 를 만드는 직무가 함께 읽는 웹 플랫폼 규칙(`web-rules.md`)을 두고(design-rules 의 웹 항목, 직무 문서·리뷰 디자인 절과 함께), 리뷰 디자인 절의 자동 검사에 웹 항목(클릭 처리기를 단 `div`·`span`, `role="button"`, 양수 `tabindex`, `transition` 의 `all`·레이아웃 속성, `:invalid`, 크기 없는 `<img>`·`<video>`, `title` 없는 `<iframe>`, `.css` 의 `@import`, `will-change`)과 지운 줄 신호(`aria-expanded`·`aria-pressed`·`<caption`·`scope`)를 더하고, README "0.7.2 → 0.8.0" 과 버전을 올린다.

**Architecture:** (1) `templates/web-rules.md` 는 새 규칙 파일이다. `setup.FILES` 에 넣어 scaffold 가 복사하고 upgrade 가 이미 세팅한 프로젝트에 `created` 로 만든다(p13b 의 palette.md·fonts-ko.md 와 같다). 번호 항목마다 검사 방식 표기를 붙인다. 자동 검사가 찾는 항목은 Task 2 가 `[기계]` 로 바꾼다(검사보다 표기가 먼저 생기지 않게). (2) 검사 방식 표기 시험(`tests/test_rule_refs.method_problems`)을 여러 파일로 넓힌다: design-rules 의 `## 자동 검사` 절이 `web-rules §5 의 1` 처럼 다른 파일의 항목을 가리키므로, 인용이 가리키는 파일을 규칙 참조 시험과 같은 규칙(같은 줄 앞의 마지막 규칙 파일 이름)으로 고른다(설계 13장의 "그 시험을 넓힌다"). (3) 웹 검사는 `lint.web_findings` 로 기존 내용 검사(`design_findings`)·색·글꼴 검사(`style_findings`)와 따로 돈다. `compose.design_findings` 가 넷째 `guarded` 로 부르고(designdiff → 내용 검사 → 웹 → 색·글꼴, 합쳐 50건), 프로젝트에 `.herdr-team/web-rules.md` 가 있을 때만 돈다(경고가 인용하는 web-rules 항목이 upgrade 전 프로젝트에는 없다. p13b 의 `has_style_rules` 와 같은 이유). 주석을 같은 길이의 공백으로 지운 글을 보고(줄 번호가 그대로다), 선언은 CSS 범위(.css·.scss, `<style>` 블록, 정적 `style` 속성 값)와 JS 범위(글 하나인 값만)로 나눠 읽고, 태그는 따옴표·중괄호 깊이를 따르는 태그 읽기 하나로 앞에서부터 한 번씩 읽어 속성 이름·값으로 판정한다(클릭 처리기·role·tabindex·클래스 값·미디어·iframe 이 같은 읽기를 쓴다). JS 문자열은 일반적으로 가르지 않는다(그 안의 예시는 경고 전용으로 잡힌다). styled-components·emotion 의 CSS 템플릿 글은 CSS 범위다. 모든 단계가 1 MB 입력에서 선형이다. (4) designdiff 는 `SIGNALS` 에 넷을 더한다(`scope` 는 표 머리 값이 붙은 것만 센다). (5) 버전은 herdr-team 세 곳·herdr-orch 세 곳이고 `HORCH_MIN` 은 0.5.0 그대로다.

**Tech Stack:** Python 3.11+ 표준 라이브러리(re, bisect, pathlib, unittest). git(시험은 임시 저장소). Herdr·Claude·Codex 를 부르지 않는다.

**설계 문서:** `docs/superpowers/specs/2026-11-05-herdr-team-design.md`(이하 "설계"). 범위는 15.3 의 13 의 p13d(1–3)와 README "0.7.2 → 0.8.0" 줄이다. 함께 볼 절: 1장 13단계 결정, 9.6·9.7(upgrade 출력, herdr-orch 0.5.1), 11.6(내용 검사 대상·designdiff 신호), 11.9(규칙 파일 구조, 검사 방식 표기, 규칙 참조 시험), 11.12 의 1·4·5, 11.13 의 1(웹)·2(지운 줄 신호), 13장 "13단계(품질 보완) 한계", 15.1 13단계(내용 검사·designdiff 추가, 직무 문서·템플릿), 15.2 13단계.

**코드가 기준이다.** 수정은 모두 브랜치 `herdr-team-p13` 의 지금 HEAD(ef7e37c, p13c 끝)에 대한 부분 수정이다. 새 파일은 `herdr-team/templates/web-rules.md` 하나다. 직무 문서의 `## ` 제목은 바꾸지 않는다(줄만 더한다. `RETIRED_HEADINGS` 는 그대로다).

**편집 표기:** `**Edit** \`경로\`` 다음 두 코드 블록은 "찾을 내용"과 "바꿀 내용"이다. 찾을 내용은 적용하는 그 시점의 파일에서 정확히 한 번 나오는 부분 문자열이다(블록 끝 개행은 넣지 않는다). 태스크 순서대로, 태스크 안에서는 적힌 순서대로 적용한다(Task 2 는 Task 1 이 쓴 web-rules.md·design-rules.md 의 줄을 찾는다). 새 파일은 `**Create** \`경로\`` 다음 블록 하나다(파일 끝에 개행 하나). 블록 안에 ``` 가 있으면 바깥 울타리를 더 길게 썼다.

## Global Constraints

- Python 3.11 이상, 표준 라이브러리만. 커밋 전에 바꾼 `.py` 를 `python3 -m py_compile` 로 확인한다.
- 13단계 값(그대로 쓴다):
  - 새 규칙 파일: `templates/web-rules.md` → 프로젝트 `.herdr-team/web-rules.md`. 읽는 쪽은 웹 UI 의 designer·developer·tester 와 디자인 리뷰어다(director·planner 는 읽지 않는다). 앱(iOS·Android·Flutter)만 만드는 태스크는 읽지 않는다. 절은 `§0 범위`, `§1 Baseline`, `§2 오버레이`, `§3 폼 검증 시점`, `§4 테마·색 구현`, `§5 움직임 구현`, `§6 성능`, `§7 구조·이름`, `§8 아이콘 구현`, `리뷰 등급`, `출처` 이고 번호 항목 수는 3·5·5·2·3·9·10·2 다.
  - 웹 경고가 인용하는 항목(바꾸지 않는다): `transition` 은 design-rules §6 의 3 과 web-rules §5 의 1, 크기 없는 `<img>`·`<video>` 는 web-rules §6 의 2, `@import` 는 web-rules §6 의 4, `will-change` 는 web-rules §6 의 7, `title` 없는 `<iframe>` 은 web-rules §7 의 9, `:invalid` 는 web-rules §3 의 2, 양수 `tabindex` 는 design-rules §2 의 3, 클릭 처리기를 단 `div`·`span` 과 `role="button"` 은 design-rules §2 의 1. 지운 줄 신호 `aria-expanded`·`aria-pressed` 는 web-rules §7 의 10, `<caption`·`scope` 는 web-rules §7 의 3.
  - 웹 경고 글: `<파일>:<줄>: <이름>(<발췌>) — <규칙>`. 이름은 `transition <속성>`, `크기 없는 <img>`·`크기 없는 <video>`, `title 없는 <iframe>`, `양수 tabindex`, `role="button"`, `클릭 처리기를 단 <div>`·`클릭 처리기를 단 <span>`, `user- 없는 :invalid`, `will-change` 다. `.css` 의 `@import` 는 파일당 한 줄 `<파일>:<첫 줄>: CSS @import N개 — web-rules §6 의 4` 다. 줄은 경고 위치(선언 머리, 속성 이름, 미디어·iframe 은 태그 머리, 클래스 값은 그 클래스)의 줄이고, 발췌는 그 위치부터 그 줄 끝까지(200자 안)를 원문에서 잘라 공백을 하나로 줄인 앞 60자다. 줄마다 이름 하나에 경고 하나다(위치 차례).
  - 웹 검사 판정(Codex 계획 리뷰 r1·r2): 주석은 같은 길이의 공백으로 지운 뒤 본다: `/* */`(여러 줄)·`<!-- -->`·`{/* */}` 는 어디서나, `//` 는 줄의 첫 글자일 때만(`.css`·`.json` 은 `//` 없음). 따옴표 글은 가리지 않는다. JS 문자열 안의 예시 태그·선언은 검사한다(경고 전용, 리뷰어 판단). .js·.jsx·.ts·.tsx 의 CSS 템플릿 글(`css`·`keyframes`·`createGlobalStyle`·`injectGlobal`·`styled.<태그>`·`styled(<X>)`, 타입 인수 `<…>`(세 겹까지)와 `.attrs(…)` 를 거쳐도)은 CSS 범위이고 그 안의 `${…}` 는 공백으로 지운다. 선언은 CSS 범위(.css·.scss 전체, `<style>` 블록, CSS 템플릿 글, 정적 `style="…"`)에서 선언 머리(범위 처음, `{`·`;`·줄 처음 뒤)이고 CSS 글 밖일 때만, 값을 `;`·`{`·`}`·줄 끝까지 읽고, 그 밖에서는 글 하나(`"…"`·`'…'`·`${` 없는 템플릿 글)이고 뒤가 `,`·`;`·`}`·`)`·`]`·줄 끝일 때만 읽는다. `:invalid` 는 CSS 선택자(.css·.scss·`<style>`·CSS 템플릿 글의 `{` 앞)와 클래스 값의 Tailwind 변형만이다. 태그는 머리 앞이 ASCII 낱말 글자·`$`·`.`·`)`·`]` 가 아니고, 따옴표·중괄호 깊이를 따라(중괄호 안 JS 글은 이스케이프를 따라) 닫는 `>` 를 찾는다. `.html` 은 태그 이름의 대소문자를 가리지 않고 그 밖은 소문자 태그만 네이티브다. `<img>`·`<video>` 는 클래스·style·펼침이 있으면 경고하지 않고, `<iframe>` 은 `title` 만 이름으로 친다. Vue `:role`·`v-bind:role` 은 `'button'` 글일 때만이다. Tailwind 클래스는 클래스 속성 값(정적 값 전체, JS 식은 그 안의 따옴표 글)에서만 본다.
  - designdiff 지운 줄 신호 `scope`: `scope\s*=\s*` 뒤에 (`{` 와) 따옴표가 있어도 되고 `row`·`col`·`rowgroup`·`colgroup` 낱말이 오는 것만.
  - 웹 검사 대상: 내용 검사(11.6)의 확장자에서 `.md` 를 뺀 것(`.html .css .scss .js .jsx .ts .tsx .vue .svelte .json`), 제외는 내용 검사와 같다. `@import` 는 `.css` 만(`.scss` 는 Sass 의 가져오기라 뺀다, `@import "tailwindcss…"` 도 뺀다).
  - 성능: 새 검사마다 1 MB(1 MiB) 적대적 입력이 1.5초 안이다(줄 끝까지 되풀이해 훑는 정규식·발췌 복사를 쓰지 않는다).
- 바꾸지 않는 것: `lint.scan`·`design_findings`·`style_findings`·`style_scan` 의 출력, designdiff 의 보존 신호·추가한 줄 검사, 직무 문서의 기존 `## ` 제목, `HORCH_MIN`(0.5.0), herdr-orch 코드(버전 문자열만 바꾼다).
- 문서·메시지·주석은 한국어. 명령·코드 식별자·들여온 원문은 원문.
- 저장소는 공개돼 있다. 커밋 전에 `git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews'` 가 아무것도 찾지 않아야 한다.
- 작업 브랜치 `herdr-team-p13` 에서 한다. main 에 직접 커밋하지 않는다. 커밋은 늘 경로 지정(`git commit … -- <경로들>`), 메시지 끝에 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- 테스트: 모듈(이나 클래스)을 `(cd herdr-team && python3 -m unittest tests.test_a tests.test_b)` 로 고른다. 태스크 안에서 전체 시험(`bash herdr-team/tests/run.sh`, `bash herdr-orch/tests/run.sh`)을 돌리지 않는다(p13d 끝에 한 번씩).
- **Codex 교차 검증(CLAUDE.md):** 이 계획은 실행 전에 `scripts/codex-review.sh doc` 로 검토받는다. 각 태스크의 마지막 단계는 커밋이다. 구현 워커는 `scripts/codex-review.sh` 를 돌리지 않는다. 관제(컨트롤러)가 커밋마다 `scripts/codex-review.sh commit <sha>` 를 돌리고 끝 알림을 백그라운드로 받는다(`R=.codex-reviews; end=$(( $(date +%s) + 3600 )); until [ -f $R/commit-<sha7>.exit ] || [ $(date +%s) -gt $end ]; do hc wait <주소> --timeout 600 >/dev/null 2>&1 || sleep 30; done`). 리뷰 수정 범위는 P0·P1, 기본 경로의 P2, 회귀다. 가장자리 경우는 알려진 한계로 적는다.

## 태스크 순서와 인터페이스(모든 태스크가 이 이름·꼴을 쓴다)

순서: Task 1 웹 규칙 파일·design-rules 웹 항목·직무 문서·리뷰 디자인 절·scaffold·검사 방식 표기 시험 넓히기(11.12 의 1·4·5, 11.9) → Task 2 내용 검사의 웹 항목과 designdiff 지운 줄 신호, 자동 검사 절·`[기계]` 표기(11.13) → Task 3 README "0.7.2 → 0.8.0" 과 버전(herdr-team 0.8.0, herdr-orch 0.5.1).

```python
# herdr-team/lib/hteam/setup.py (Task 1)
FILES["web-rules.md"] = ".herdr-team/web-rules.md"   # fonts-ko.md 다음, 직무 문서 앞

# herdr-team/tests/test_rule_refs.py (Task 1)
def _methods(path: Path) -> tuple[dict[tuple[int, int], set[str]], dict[str, set[tuple[int, int]]], list[str]]
def method_problems(*paths: Path) -> list[str]   # 여러 규칙 파일. 자동 검사 절 인용을 가리키는 파일로 나눠 본다

# herdr-team/lib/hteam/lint.py (Task 2)
RULE_TRANSITION, RULE_MEDIA, RULE_IMPORT, RULE_WILL_CHANGE, RULE_IFRAME, RULE_INVALID, RULE_TABINDEX, RULE_CLICK: str
WEB_SUFFIXES = SUFFIXES - {".md"}; WEB_RULES_FILE = "web-rules.md"; VALUE_WINDOW = 300; EXCERPT_WINDOW = 200
CSS_SUFFIXES = frozenset({".css", ".scss"}); JS_SUFFIXES = frozenset({".js", ".jsx", ".ts", ".tsx"}); HTML_SUFFIXES = frozenset({".html", ".htm"})
def strip_comments(text: str, line_comments: bool = True) -> str     # 같은 길이, 줄바꿈은 둔다
def _css_templates(code: str) -> tuple[str, list[tuple[int, int]]]  # (`${…}` 를 지운 글, CSS 템플릿 글 범위)
def _css_ranges(code: str, suffix: str, templates: list[tuple[int, int]]) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]   # (선택자 범위, CSS 범위)
def _declarations(code: str, css: list[tuple[int, int]]) -> list[tuple[str, int, str]]          # (이름, 위치, 규칙)
def _invalid_selectors(code: str, blocks: list[tuple[int, int]]) -> list[tuple[str, int, str]]
def _read_tag(code: str, i: int, limit: int) -> tuple[int, bool]                                 # (닫는 `>` 또는 멈춘 위치, 닫힘)
def _attrs(code: str, i: int, end: int) -> list[tuple[str, int, str, int, int]]                  # (이름, 이름 위치, 꼴, 값 시작, 값 끝)
def _js_strings(code: str, a: int, b: int) -> list[tuple[int, int]]                              # 클래스 JS 식 안 따옴표 글, 한 번씩 훑는다
def _tag_hits(code: str, fold: bool) -> list[tuple[str, int, str]]   # fold: .html 은 태그 이름 대소문자 무시
def web_scan(rel: str, text: str) -> list[str]
def web_findings(root: Path, files: list[str]) -> list[str]     # 상한 없음

# herdr-team/lib/hteam/compose.py (Task 2)
def design_findings(p, files, shas) -> list[str]   # designdiff → lint.design_findings → lint.web_findings(web-rules.md 가 있을 때)
                                                   # → lint.style_findings(has_style_rules 일 때), lint.cap

# herdr-team/lib/hteam/designdiff.py (Task 2)
SIGNALS += ("aria-expanded", "aria-pressed") 를 "aria-live" 뒤에, ("<caption", "scope") 를 "htmlFor" 뒤에(scope 는 row·col·rowgroup·colgroup 값만)
```

---

### Task 1: web-rules.md, design-rules 의 웹 항목, 직무 문서·리뷰 디자인 절, scaffold·upgrade, 검사 방식 표기 시험(설계 11.9, 11.12 의 1·4·5)

새 규칙 파일 `web-rules.md` 를 만들고 scaffold·upgrade 대상(`setup.FILES`)에 넣는다. design-rules 에는 첫머리의 직무별 참고 파일 줄(웹 UI 는 web-rules 도 읽고 앱만 만드는 태스크는 읽지 않는다), §2 의 7 덧붙임(blur 검사), §2 의 15(강제 색), §7 의 1 덧붙임(사용자 환경 설정 축), 즉시 차단 항목의 번쩍임, 출처(modern-web-guidance·agent-skills)를 더한다. 리뷰 디자인 절은 기준 1 에 web-rules 읽기와 등급을, 6번 즉시 차단 목록에 번쩍임을 더한다(design-rules 목록과 같아야 한다, 시험). 직무 문서는 입력 줄만 더한다(designer·developer·tester). tester 는 품질 기준에 키보드만으로 지나는 시나리오와 `lighthouse_audit` 접근성 결과(점수는 단서)를 더한다(11.12 의 5). 이 태스크의 web-rules 항목에는 `[기계]` 가 없다: 자동 검사가 아직 그 항목을 찾지 않는다(Task 2 가 검사와 함께 바꾼다, p13b Task 3 과 같은 순서). 검사 방식 표기 시험은 여러 규칙 파일을 함께 받게 넓힌다(설계 13장 "p13d 의 web-rules.md 가 다른 파일의 항목을 가리키면 그 시험을 넓힌다"). design-rules 는 150줄 안쪽(설계 11.9, 이 태스크 뒤 139줄)이다.

**Files:**
- Create: `herdr-team/templates/web-rules.md`
- Modify: `herdr-team/templates/design-rules.md`, `herdr-team/templates/review-design.md`, `herdr-team/templates/roles/designer.md`·`developer.md`·`tester.md`(입력·품질 기준 줄)
- Modify: `herdr-team/lib/hteam/setup.py`(`FILES`), `README.md`(디자인 규칙 줄, 묶음 검증 줄)
- Modify: `herdr-team/tests/test_rule_refs.py`, `herdr-team/tests/test_design_docs.py`, `herdr-team/tests/test_setup.py`

**Interfaces:**
- Consumes: 없음(p13c 까지의 코드).
- Produces: `.herdr-team/web-rules.md`(scaffold 가 만들고 upgrade 가 `created`), web-rules §1–§8 의 번호(Task 2 의 경고·자동 검사 절이 인용한다), design-rules §2 의 15·즉시 차단의 번쩍임, `tests.test_rule_refs.method_problems(*paths)`.

- [ ] **Step 1: 시험을 먼저 고친다**

**Edit** `herdr-team/tests/test_rule_refs.py`

```python
METHOD = re.compile(r"(?: \[(?:기계|렌더|판단)\])+$")


def method_problems(path: Path) -> list[str]:
    """검사 방식 표기(설계 11.9): `## §N` 절의 번호 항목마다 끝에 [기계]·[렌더]·[판단] 이 하나 이상 있다. `## 자동 검사` 절이
    `§N 의 M` 으로 가리키는 항목은 [기계] 이고, [기계] 항목은 모두 자동 검사 절이 가리킨다. 펜스 코드 블록 안은 보지 않는다."""
    name = path.name
    items: dict[tuple[int, int], set[str]] = {}
    auto: set[tuple[int, int]] = set()
    found = []
    cur, in_auto, fence = None, False, None
```

```python
METHOD = re.compile(r"(?: \[(?:기계|렌더|판단)\])+$")


def _methods(path: Path) -> tuple[dict[tuple[int, int], set[str]], dict[str, set[tuple[int, int]]], list[str]]:
    """한 규칙 파일의 (번호 항목 → 표기, 자동 검사 절이 가리키는 항목을 가리키는 규칙 파일별로, 표기가 없는 항목의 문제)."""
    name = path.name
    own = default_target(name)
    items: dict[tuple[int, int], set[str]] = {}
    auto: dict[str, set[tuple[int, int]]] = {}
    found = []
    cur, in_auto, fence = None, False, None
```

**Edit** `herdr-team/tests/test_rule_refs.py`

```python
        if in_auto:
            auto |= {(int(c.group(1)), int(c.group(4))) for c in CITE.finditer(line) if c.group(4)}
            continue
```

```python
        if in_auto:
            for c in CITE.finditer(line):
                if c.group(4):
                    names = NAME.findall(line[:c.start()])
                    later = LATER.match(line[c.end():])
                    target = names[-1] if names else (later.group(1) if later else own)
                    auto.setdefault(target, set()).add((int(c.group(1)), int(c.group(4))))
            continue
```

**Edit** `herdr-team/tests/test_rule_refs.py`

```python
            items[(cur, int(item.group(1)))] = set(re.findall(r"기계|렌더|판단", tag.group(0))) if tag else set()
    for key in sorted(auto):
        if key not in items:
            found.append(f"{name}: 자동 검사 절이 가리키는 항목이 없다: §{key[0]} 의 {key[1]}")
        elif "기계" not in items[key]:
            found.append(f"{name}: 자동 검사 절이 가리키는 항목이 [기계] 가 아니다: §{key[0]} 의 {key[1]}")
    for key, tags in sorted(items.items()):
        if "기계" in tags and key not in auto:
            found.append(f"{name}: 자동 검사 절이 가리키지 않는 [기계] 항목: §{key[0]} 의 {key[1]}")
    return found
```

```python
            items[(cur, int(item.group(1)))] = set(re.findall(r"기계|렌더|판단", tag.group(0))) if tag else set()
    return items, auto, found


def method_problems(*paths: Path) -> list[str]:
    """검사 방식 표기(설계 11.9): 규칙 파일마다 `## §N` 절의 번호 항목 끝에 [기계]·[렌더]·[판단] 이 하나 이상 있다. 주어진
    파일들의 `## 자동 검사` 절이 `§N 의 M` 으로 가리키는 항목은 [기계] 이고, [기계] 항목은 모두 어느 자동 검사 절이 가리킨다.
    인용이 가리키는 파일은 problems 와 같이 고른다(같은 줄 앞의 마지막 규칙 파일 이름, 인용 바로 뒤 괄호의 이름, 없으면 그 파일의
    기본 대상): design-rules 의 자동 검사 절이 `web-rules §5 의 1` 처럼 web-rules 의 항목을 가리킨다(13단계 p13d). 주어지지
    않은 파일을 가리키는 인용은 보지 않는다(그 항목이 있는지는 problems 가 본다). 펜스 코드 블록 안은 보지 않는다."""
    parsed = [(path.name, default_target(path.name), *_methods(path)) for path in paths]
    cited: dict[str, set[tuple[int, int]]] = {}
    for _, _, _, auto, _ in parsed:
        for target, keys in auto.items():
            cited.setdefault(target, set()).update(keys)
    found = []
    for name, own, items, _, missing in parsed:
        found += missing
        mine = cited.get(own, set())
        for key in sorted(mine):
            if key not in items:
                found.append(f"{name}: 자동 검사 절이 가리키는 항목이 없다: §{key[0]} 의 {key[1]}")
            elif "기계" not in items[key]:
                found.append(f"{name}: 자동 검사 절이 가리키는 항목이 [기계] 가 아니다: §{key[0]} 의 {key[1]}")
        for key, tags in sorted(items.items()):
            if "기계" in tags and key not in mine:
                found.append(f"{name}: 자동 검사 절이 가리키지 않는 [기계] 항목: §{key[0]} 의 {key[1]}")
    return found
```

**Edit** `herdr-team/tests/test_rule_refs.py`

```python
    def test_rule_items_have_check_methods(self):
        checked = [ROOT / "templates" / name for name in ("design-rules.md", "web-rules.md")
                   if (ROOT / "templates" / name).is_file()]
        self.assertIn(ROOT / "templates" / "design-rules.md", checked)
        for path in checked:
            self.assertEqual(method_problems(path), [], path.name)
```

```python
    def test_rule_items_have_check_methods(self):
        checked = [ROOT / "templates" / name for name in ("design-rules.md", "web-rules.md")]
        for path in checked:
            self.assertTrue(path.is_file(), path.name)  # 13단계 p13d: 웹 규칙도 본다
        self.assertEqual(method_problems(*checked), [])

    def test_method_checker_follows_auto_citations_into_other_rule_files(self):
        # 13단계 p13d(설계 11.9, 13장): design-rules 의 자동 검사 절이 web-rules 항목을 가리킨다. 그 항목도 [기계] 여야 하고
        # web-rules 의 [기계] 항목은 어느 자동 검사 절이 가리켜야 한다. 같은 줄 앞의 마지막 규칙 파일 이름이 대상이다
        with tempfile.TemporaryDirectory() as tmp:
            design, web = Path(tmp) / "design-rules.md", Path(tmp) / "web-rules.md"
            design.write_text("# 규칙\n\n## §1 금지\n1. 하나 [기계]\n2. 둘 [판단]\n\n## 자동 검사\n"
                              "- §1 의 1(하나), web-rules §5 의 1·web-rules §5 의 2, web-rules §6 의 9\n", encoding="utf-8")
            web.write_text("# 웹\n\n## §5 움직임\n1. 하나 [기계]\n2. 둘 [판단]\n3. 셋 [기계] [판단]\n\n## §6 성능\n1. 하나 [판단]\n",
                           encoding="utf-8")
            self.assertEqual(method_problems(design, web), [
                "web-rules.md: 자동 검사 절이 가리키는 항목이 [기계] 가 아니다: §5 의 2",
                "web-rules.md: 자동 검사 절이 가리키는 항목이 없다: §6 의 9",
                "web-rules.md: 자동 검사 절이 가리키지 않는 [기계] 항목: §5 의 3",
            ])
            self.assertEqual(method_problems(design), [])  # 주어지지 않은 파일을 가리키는 인용은 보지 않는다
```

**Edit** `herdr-team/tests/test_design_docs.py`

```python
        counts = {"§1 금지 목록 (AI 티)": 13, "§2 접근성 (WCAG 2.2 AA)": 14, "§3 색": 12, "§4 글자": 10, "§5 레이아웃": 10,
```

```python
        counts = {"§1 금지 목록 (AI 티)": 13, "§2 접근성 (WCAG 2.2 AA)": 15, "§3 색": 12, "§4 글자": 10, "§5 레이아웃": 10,
```

**Edit** `herdr-team/tests/test_design_docs.py`

```python
        self.assertEqual(len(rules), 10)
```

```python
        self.assertEqual(len(rules), 11)  # 13단계 p13d: 1초에 3번 넘는 번쩍임
```

**Edit** `herdr-team/tests/test_design_docs.py`

```python
class TextRulesDocTest(unittest.TestCase):
```

```python
class WebRulesDocTest(unittest.TestCase):
    """13단계 웹 규칙(설계 11.9·11.12 의 1·4·5): web-rules.md, design-rules 의 웹 항목, 직무 문서·리뷰 디자인 절."""

    def read(self, rel):
        return (ROOT / "templates" / rel).read_text(encoding="utf-8")

    def test_web_rules_sections_and_items(self):
        text = self.read("web-rules.md")
        heads = [line for line in text.split("\n") if line.startswith("#")]
        self.assertEqual(heads, ["# 웹 플랫폼 규칙", "## §0 범위", "## §1 Baseline", "## §2 오버레이", "## §3 폼 검증 시점",
                                 "## §4 테마·색 구현", "## §5 움직임 구현", "## §6 성능", "## §7 구조·이름", "## §8 아이콘 구현",
                                 "## 리뷰 등급", "## 출처"])
        counts = {"§1 Baseline": 3, "§2 오버레이": 5, "§3 폼 검증 시점": 5, "§4 테마·색 구현": 2, "§5 움직임 구현": 3,
                  "§6 성능": 9, "§7 구조·이름": 10, "§8 아이콘 구현": 2}
        for title, n in counts.items():
            found = re.findall(r"(?m)^(\d+)\. ", section(text, title))
            self.assertEqual([int(x) for x in found], list(range(1, n + 1)), title)
        head = text[:text.index("## §0 범위")]
        for needle in ("designer·developer·tester", "디자인 리뷰어", "`.herdr-team/design-rules.md`", "앱(iOS·Android·Flutter)만",
                       "`### 디자인 점검`"):
            self.assertIn(needle, head)
        self.assertIn("검사 방식 표기는 design-rules §0 과 같다", section(text, "§0 범위"))
        for title, needles in (
                ("§1 Baseline", ("Baseline Widely available", "`@supports`", "Origin Trial", "`### 시스템 추가 제안`",
                                 "`<dialog>`", "`popover`", "`<details>`", "`:user-invalid`", "`light-dark()`", "`text-wrap`")),
                ("§2 오버레이", ("`showModal()`", "`popover` 속성", "`<details>`·`<summary>`", "스크롤되지 않는다", "폴백 위치")),
                ("§3 폼 검증 시점", ("이미 보인 오류를 지우기만", "(blur)", "첫 틀린 칸으로 포커스", "`:user-invalid` 에 건다",
                                  "`aria-live`", "다시 보내지 않게", "서버가 한다")),
                ("§4 테마·색 구현", ("`<meta name=\"color-scheme\">`", "`light-dark()`", "`oklch(from …)`",
                                  "`color-mix(in oklab, …)`")),
                ("§5 움직임 구현", ("`opacity`·`transform`", "`max-height`", "`interpolate-size", "`@starting-style`",
                                  "`transition-behavior: allow-discrete`", "`opacity: 0` 으로 숨긴 채",
                                  "1초에 3번 넘게 번쩍이지 않는다", "동작 줄이기 설정과 상관없이")),
                ("§6 성능", ("`loading=\"lazy\"`", "`fetchpriority=\"high\"`", "`aspect-ratio`", "`sizes`", "`defer`·`async`",
                           "CSS `@import`", "`preload`", "`content-visibility: auto`", "`will-change`", "`scheduler.yield()`",
                           "Worker")),
                ("§7 구조·이름", ("`<h1>` 은 화면에 하나", "큰 글자 `div`", "`<caption>`", "`<th scope>`", "`<nav aria-label>`",
                                "대상을 넣는다", "역할 낱말", "`aria-hidden=\"true\"`", "`role=\"img\"`", "`<track>`",
                                "`<iframe>` 에는 내용을 말하는 `title`", "`aria-expanded`", "`aria-pressed`")),
                ("§8 아이콘 구현", ("`currentColor`", "3:1", "CSS `mask`", "CSS 필터"))):
            for needle in needles:
                self.assertIn(needle, section(text, title), title)
        grade = section(text, "리뷰 등급")
        for needle in ("§5 의 3 번쩍임", "P1(REQUEST_CHANGES)", "design-rules `## 즉시 차단 항목`", "P2",
                       "`### 디자인 점검`"):
            self.assertIn(needle, grade)
        for needle in ("GoogleChrome/modern-web-guidance", "CC-BY 4.0", "addyosmani/agent-skills", "MIT"):
            self.assertIn(needle, section(text, "출처"))

    def test_design_rules_web_items(self):
        rules = self.read("design-rules.md")
        head = rules[:rules.index("## §0 범위")]
        self.assertIn("`.herdr-team/web-rules.md`", head)
        self.assertIn("앱(iOS·Android·Flutter)만 만드는 태스크는 읽지 않는다", head)
        a11y = section(rules, "§2 접근성 (WCAG 2.2 AA)")
        self.assertIn("고친 칸은 blur 에서 검사해도 된다(`.herdr-team/web-rules.md` §3)", a11y)
        self.assertIn("15. 그림자·그라디언트·배경 이미지만으로 경계·구분·상태를 나타내지 않는다", a11y)
        self.assertIn("`forced-color-adjust: none`", a11y)
        self.assertIn("사용자 환경 설정 축(동작 줄이기, 밝은·어두운 테마, 대비 높임, 강제 색, 데이터 절약)", section(rules, "§7 상태"))
        self.assertIn("- 1초에 3번 넘게 번쩍이는 것", section(rules, "즉시 차단 항목"))
        for needle in ("GoogleChrome/modern-web-guidance", "CC-BY 4.0", "addyosmani/agent-skills"):
            self.assertIn(needle, section(rules, "출처"))

    def test_role_docs_review_and_readme(self):
        for role in ("designer", "developer", "tester"):
            self.assertIn("`.herdr-team/web-rules.md`", section(self.read(f"roles/{role}.md"), "입력"), role)
        for role in ("director", "planner"):
            self.assertNotIn("web-rules.md", self.read(f"roles/{role}.md"), role)
        quality = section(self.read("roles/tester.md"), "품질 기준")
        for needle in ("키보드만으로(Tab·Shift+Tab·화살표·Enter·Space·Esc) 전 흐름", "`lighthouse_audit`", "접근성 범주",
                       "합격 기준이 아니라 단서"):
            self.assertIn(needle, quality)
        review = self.read("review-design.md")
        first = review[review.index("1. UI 를 바꾼 태스크면"):review.index("\n2. ")]
        for needle in ("`.herdr-team/web-rules.md` 가 있으면 그 파일로도 본다", "`## 리뷰 등급`", "6번의 P1"):
            self.assertIn(needle, first)
        readme = (ROOT.parent / "README.md").read_text(encoding="utf-8")
        for needle in ("`.herdr-team/web-rules.md`(0.8.0", "즉시 차단 항목 11개", "`lighthouse_audit`"):
            self.assertIn(needle, readme)


class TextRulesDocTest(unittest.TestCase):
```

**Edit** `herdr-team/tests/test_setup.py`

```python
                    ".herdr-team/palette.md", ".herdr-team/fonts-ko.md", ".herdr-team/bin/hteam",
```

```python
                    ".herdr-team/palette.md", ".herdr-team/fonts-ko.md", ".herdr-team/web-rules.md", ".herdr-team/bin/hteam",
```

**Edit** `herdr-team/tests/test_setup.py`

```python
        self.git("rm", "-q", "--", ".herdr-team/palette.md", ".herdr-team/fonts-ko.md")
        self.git("commit", "-q", "-m", "0.7.2 처럼 새 규칙 파일이 없다")
        code, out = self.upgrade()
        self.assertEqual((code, out["created"], out["updated"]), (0, [".herdr-team/palette.md", ".herdr-team/fonts-ko.md"], []),
                         out)
        for name in ("palette.md", "fonts-ko.md"):
```

```python
        new = [".herdr-team/palette.md", ".herdr-team/fonts-ko.md", ".herdr-team/web-rules.md"]  # 13단계 새 규칙 파일 셋
        self.git("rm", "-q", "--", *new)
        self.git("commit", "-q", "-m", "0.7.2 처럼 새 규칙 파일이 없다")
        code, out = self.upgrade()
        self.assertEqual((code, out["created"], out["updated"]), (0, new, []), out)
        for name in ("palette.md", "fonts-ko.md", "web-rules.md"):
```

- [ ] **Step 2: 시험이 실패하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_rule_refs tests.test_design_docs tests.test_setup.ScaffoldTest tests.test_setup.UpgradeTest tests.test_setup.SubdirUpgradeTest)`
Expected: FAIL — `Ran 74 tests`, `FAILED (failures=8, errors=1)`(web-rules.md 가 없다: 검사 방식 표기·WebRulesDocTest 셋(하나는 FileNotFoundError), design-rules §2 의 15·즉시 차단 11개, scaffold·upgrade 의 web-rules.md 셋)

- [ ] **Step 3: web-rules.md 를 만든다**

**Create** `herdr-team/templates/web-rules.md`

```markdown
# 웹 플랫폼 규칙

웹 UI(브라우저에서 도는 화면과 그 시안)를 만들거나 시험하는 designer·developer·tester 와 디자인 리뷰어가 `.herdr-team/design-rules.md` 와 함께 읽는다. 앱(iOS·Android·Flutter)만 만드는 태스크는 읽지 않는다. design-rules 가 무엇을 지킬지 정하고, 이 파일은 그것을 웹 플랫폼 기능으로 어떻게 만드는지 정한다. 어긴 곳과 예외·근거는 design-rules 와 같이 보고서 `### 디자인 점검` 에 적는다.

## §0 범위
- 프로젝트 디자인 시스템과 기술 스택이 정한 것이 먼저다(design-rules §0). 이 파일과 다른 방식이 필요하면 designer 는 `### 시스템 추가 제안` 에 적고, developer 는 프리앰블의 ask 명령으로 메인에게 묻는다.
- 검사 방식 표기는 design-rules §0 과 같다: `[기계]` 는 hteam 자동 검사가 의심 위치를 찾는다(design-rules 의 "자동 검사" 절. 경고가 없다고 지킨 것은 아니다), `[렌더]` 는 화면을 렌더해야 안다, `[판단]` 은 읽고 판단한다.

## §1 Baseline
1. 기본은 Baseline Widely available(주요 브라우저가 모두 오래 지원한) 기능이다. 그보다 새 기능(Newly available, Limited)은 `@supports`·기능 검사와 폴백을 함께 둘 때만 쓴다. [판단]
2. 한 엔진에만 있는 기능과 Origin Trial 은 쓰지 않는다. 꼭 필요하면 developer 는 프리앰블의 ask 명령으로 메인에게 묻고, designer 는 `### 시스템 추가 제안` 에 적는다. [판단]
3. 직접 만들거나 라이브러리를 더하기 전에 네이티브 해법(`<dialog>`, `popover`, `<details>`, `:user-invalid`, `light-dark()`, `text-wrap`)을 먼저 본다. [판단]

## §2 오버레이
1. 응답이 있어야 하는 중단(확인, 필수 입력)은 `<dialog>` 를 `showModal()` 로 띄운다(포커스는 design-rules §2 의 4). [판단]
2. 메뉴·툴팁·토스트처럼 가벼운 일시 정보는 `popover` 속성으로 띄운다. [판단]
3. 인라인 펼침(아코디언, 자주 묻는 질문)은 `<details>`·`<summary>` 로 만든다. [판단]
4. 모달이 떠 있는 동안 뒤 페이지가 스크롤되지 않는다. [렌더]
5. 앵커 위치 지정(`anchor-name`·`position-anchor`)은 지원하지 않는 브라우저의 폴백 위치와 함께 쓴다. [판단]

## §3 폼 검증 시점
1. 입력하는 동안에는 이미 보인 오류를 지우기만 하고 새 오류를 띄우지 않는다. 고친 칸은 포커스가 떠날 때(blur) 검사해 보인다. 제출에서 막고 첫 틀린 칸으로 포커스를 옮긴다(design-rules §2 의 7). [판단] [렌더]
2. 오류 모양은 `:invalid` 가 아니라 `:user-invalid` 에 건다(손대기 전의 빈 필수 칸이 처음부터 오류로 보이지 않게). [판단]
3. 키 입력마다 `aria-live` 로 읽히게 하지 않는다. [판단]
4. 유효하게 제출한 뒤에는 응답이 올 때까지 같은 제출을 다시 보내지 않게 막는다. [판단]
5. 클라이언트 검증은 사용성을 위한 것이다. 보안과 데이터 검사는 서버가 한다. [판단]

## §4 테마·색 구현
1. 밝은·어두운 테마를 지원하면 `<meta name="color-scheme">` 과 CSS `color-scheme` 을 선언하고, 테마별 색은 `light-dark()` 로 한곳에서 정의한다. [판단]
2. 단계 색(hover·눌림 등)은 시스템이 미리 정한 토큰을 먼저 쓴다. 만들어야 하면 `oklch(from …)` 로 명도만 바꾸지 않고 `color-mix(in oklab, …)` 로 섞는다. [판단]

## §5 움직임 구현
1. `opacity`·`transform`(`translate`·`scale`)만 움직인다. `height`·`max-height`·`width`·`top`·`left` 와 `all` 을 transition 하지 않는다. 높이 펼침은 `interpolate-size: allow-keywords` 나 `<details>` 로 한다. [판단]
2. 나타나고 사라지는 전환은 `@starting-style` 과 `transition-behavior: allow-discrete` 로 한다. 전환이 끝난 요소는 최종 상태로 남긴다(`opacity: 0` 으로 숨긴 채 두지 않는다). [판단]
3. 1초에 3번 넘게 번쩍이지 않는다. 동작 줄이기 설정과 상관없이 지키는 즉시 차단 항목이다. [렌더] [판단]

## §6 성능
1. LCP 이미지(첫 화면의 가장 큰 그림)는 `loading="lazy"` 를 쓰지 않고 초기 HTML 에 둔다. `fetchpriority="high"` 는 그 하나에만 둔다. [판단]
2. 모든 `<img>`·`<video>` 에 `width`·`height` 나 `aspect-ratio` 를 둔다(늦게 온 그림이 레이아웃을 밀지 않게). `srcset` 에는 `sizes` 를 함께 둔다. [판단]
3. 첫 화면에 필요 없는 스크립트는 `defer`·`async` 로 불러온다. [판단]
4. CSS `@import` 로 스타일시트를 잇지 않는다(요청이 차례로 걸린다). 빌드 도구가 하나로 합치는 가져오기와 Sass 의 가져오기는 괜찮다. [판단]
5. 웹폰트는 쓰는 굵기만 불러오고, 첫 화면에 쓰는 글꼴 파일은 `preload` 한다(design-rules §4 의 2). [판단]
6. `content-visibility: auto` 는 첫 화면 아래 영역에만 쓴다. [판단]
7. `will-change` 는 움직이기 직전 그 요소에만 두고 끝나면 지운다. 늘 켜 두지 않는다. [판단]
8. 50ms 넘는 작업은 `scheduler.yield()` 로 쪼개고, 250ms 넘는 계산은 Worker 로 보낸다. [판단]
9. 레이아웃 값을 읽고 쓰는 일을 번갈아 해서 레이아웃을 거듭 계산하게 하지 않는다(읽기를 모은 뒤 쓴다). [판단]

## §7 구조·이름
1. 제목 단계를 건너뛰지 않는다. `<h1>` 은 화면에 하나다(모달 `<dialog>` 안은 따로 센다). [판단]
2. 큰 글자 `div` 로 제목을 흉내 내지 않는다. [판단]
3. 데이터 표에는 `<caption>` 과 `<th scope>` 를 둔다. 레이아웃에 표를 쓰지 않는다. [판단]
4. 내비게이션이 둘 이상이면 `<nav aria-label>` 로 가른다. [판단]
5. 같은 모양의 "수정"·"삭제" 버튼이 여럿이면 접근 가능한 이름에 대상을 넣는다(예: "주문 1024 삭제"). [판단]
6. 접근 가능한 이름에 역할 낱말("버튼", "링크")을 넣지 않는다. `title`·`placeholder` 로 이름을 대신하지 않는다. [판단]
7. 인라인 `<svg>` 는 장식이면 `aria-hidden="true"`, 정보면 `role="img"` 와 이름을 둔다. [판단]
8. 말이 있는 `<video>` 에는 자막 `<track>` 을 둔다. [판단]
9. `<iframe>` 에는 내용을 말하는 `title` 을 둔다. [판단]
10. 펼치는 토글은 `aria-expanded`, 켜고 끄는 토글 버튼은 `aria-pressed` 로 상태를 알린다. [판단]

## §8 아이콘 구현
1. 아이콘은 `currentColor` 로 글자색을 따르고, 두 테마 모두에서 배경과 대비 3:1 이상이다. [렌더]
2. 단색 아이콘은 CSS `mask` 로, 안쪽 색을 바꿔야 하는 아이콘은 인라인 SVG 로 넣는다. `<img>` 에 CSS 필터를 걸어 색을 바꾸지 않는다. [판단]

## 리뷰 등급
- 즉시 차단(보고서에 예외를 적었어도 리뷰어는 P1(REQUEST_CHANGES)로 판정한다): §5 의 3 번쩍임, 그리고 §7 을 어겨 이름이 없는 컨트롤이나 §3 을 어겨 복구 방법을 알려 주지 않는 오류처럼 이 파일을 어겨 design-rules `## 즉시 차단 항목` 에 해당하게 된 것.
- 그 밖의 위반은 P2 다. 보고서 `### 디자인 점검` 에 적은 예외의 근거가 타당하면 지적하지 않는다(design-rules §2–§7 과 같다).

## 출처
13단계(2026-11-16 조사)에 GoogleChrome/modern-web-guidance(원본 저장소 https://github.com/GoogleChrome/modern-web-guidance-src, 가이드 문서 CC-BY 4.0, 2026-11-13 커밋)의 가이드(accessibility, forms, motion, color, performance, preference-aware-ui 등)를 골라 줄이고 한국어로 새로 썼다(원문을 옮기지 않았다). 데이터 표 머리글 같은 접근성 점검은 addyosmani/agent-skills(https://github.com/addyosmani/agent-skills, MIT, 2026-11-13 커밋)를 참고했다.
```

- [ ] **Step 4: design-rules·리뷰 디자인 절·직무 문서·scaffold·README 를 고친다**

**Edit** `herdr-team/templates/design-rules.md`

```markdown
디자인 시스템 없이 글꼴을 고르는 designer 는 `.herdr-team/fonts-ko.md` 를 함께 읽는다.
```

```markdown
디자인 시스템 없이 글꼴을 고르는 designer 는 `.herdr-team/fonts-ko.md` 를 함께 읽는다. 웹 UI(브라우저에서 도는 화면과 그 시안)를 만들거나 시험하는 designer·developer·tester 는 `.herdr-team/web-rules.md`(웹 플랫폼 기능으로 만드는 법)도 읽는다. 앱(iOS·Android·Flutter)만 만드는 태스크는 읽지 않는다.
```

**Edit** `herdr-team/templates/design-rules.md`

```markdown
첫 틀린 칸으로 포커스를 옮긴다. [판단] [렌더]
```

```markdown
첫 틀린 칸으로 포커스를 옮긴다. 고친 칸은 blur 에서 검사해도 된다(`.herdr-team/web-rules.md` §3). [판단] [렌더]
```

**Edit** `herdr-team/templates/design-rules.md`

```markdown
`user-scalable=no` 를 쓰지 않는다. [기계] [렌더]
```

```markdown
`user-scalable=no` 를 쓰지 않는다. [기계] [렌더]
15. 그림자·그라디언트·배경 이미지만으로 경계·구분·상태를 나타내지 않는다(강제 색 모드에서 사라진다). `forced-color-adjust: none` 은 색 자체가 정보인 곳(색 견본)에만 쓴다. [판단] [렌더]
```

**Edit** `herdr-team/templates/design-rules.md`

```markdown
긴 글(긴 이름, 번역으로 늘어난 라벨). [판단] [렌더]
```

```markdown
긴 글(긴 이름, 번역으로 늘어난 라벨), 사용자 환경 설정 축(동작 줄이기, 밝은·어두운 테마, 대비 높임, 강제 색, 데이터 절약) 가운데 해당하는 것. [판단] [렌더]
```

**Edit** `herdr-team/templates/design-rules.md`

```markdown
- 움직임으로만 알리는 상태 변화
```

```markdown
- 움직임으로만 알리는 상태 변화
- 1초에 3번 넘게 번쩍이는 것
```

**Edit** `herdr-team/templates/design-rules.md`

```markdown
들여온 팔레트·과용 색 데이터의 라이선스 원문은 플러그인의 `lib/hteam/data/LICENSES.md` 에 있다.
```

```markdown
들여온 팔레트·과용 색 데이터의 라이선스 원문은 플러그인의 `lib/hteam/data/LICENSES.md` 에 있다.

§2 의 7 의 blur 검사, §2 의 15, §7 의 1 의 사용자 환경 설정 축, 번쩍임 즉시 차단과 `web-rules.md` 는 13단계(2026-11-16 조사)에 GoogleChrome/modern-web-guidance(원본 저장소 https://github.com/GoogleChrome/modern-web-guidance-src, 가이드 문서 CC-BY 4.0, 2026-11-13 커밋)를 요약·재작성하고 addyosmani/agent-skills(https://github.com/addyosmani/agent-skills, MIT, 2026-11-13 커밋)를 참고해 더했다.
```

**Edit** `herdr-team/templates/review-design.md`

```markdown
보고서 마지막 라운드의 `### 디자인 점검`(이전 버전 프로젝트는 `### 금지 목록 점검`)이 실제와 맞는지도 본다.
```

```markdown
보고서 마지막 라운드의 `### 디자인 점검`(이전 버전 프로젝트는 `### 금지 목록 점검`)이 실제와 맞는지도 본다. 웹 UI 를 바꾼 태스크이고 프로젝트에 `.herdr-team/web-rules.md` 가 있으면 그 파일로도 본다: 그 위반은 design-rules §2–§7 과 같이 다루고, 그 파일의 `## 리뷰 등급` 이 즉시 차단이라 한 것(번쩍임, 이름 없는 컨트롤 등)은 아래 6번의 P1 이다.
```

**Edit** `herdr-team/templates/review-design.md`

```markdown
     - 움직임으로만 알리는 상태 변화
```

```markdown
     - 움직임으로만 알리는 상태 변화
     - 1초에 3번 넘게 번쩍이는 것
```

**Edit** `herdr-team/templates/roles/designer.md`

```markdown
- 디자인 시스템이 없어 글꼴을 고르면 `.herdr-team/fonts-ko.md`(한글 글꼴 후보, 과용 글꼴, 글꼴 파일 넣기)
```

```markdown
- 디자인 시스템이 없어 글꼴을 고르면 `.herdr-team/fonts-ko.md`(한글 글꼴 후보, 과용 글꼴, 글꼴 파일 넣기)
- 웹 시안이면 `.herdr-team/web-rules.md`(웹 플랫폼 규칙: Baseline, 오버레이, 폼 검증 시점, 움직임, 성능, 구조·이름. 앱 화면 시안은 읽지 않는다)
```

**Edit** `herdr-team/templates/roles/developer.md`

```markdown
§2–§7 품질 규칙. UI 작업에 적용한다)
```

```markdown
§2–§7 품질 규칙. UI 작업에 적용한다)
- 웹 UI 를 구현하면 `.herdr-team/web-rules.md`(웹 플랫폼 규칙: Baseline, 오버레이, 폼 검증 시점, 테마·움직임 구현, 성능, 구조·이름. 앱만 만들면 읽지 않는다)
```

**Edit** `herdr-team/templates/roles/tester.md`

```markdown
- `docs/planning/` 수용 기준과 `contracts.md`, 묶음 developer 태스크 보고서(`docs/tasks/<선행 태스크 ID>/report.md`, 실행 방법)
```

```markdown
- `docs/planning/` 수용 기준과 `contracts.md`, 묶음 developer 태스크 보고서(`docs/tasks/<선행 태스크 ID>/report.md`, 실행 방법)
- 웹 UI 묶음이면 `.herdr-team/web-rules.md`(웹 플랫폼 규칙. 시나리오와 확인할 상태를 정할 때 본다)
```

**Edit** `herdr-team/templates/roles/tester.md`

```markdown
- 실패는 재현 절차와 함께 적는다.
```

```markdown
- 실패는 재현 절차와 함께 적는다.
- UI 가 있는 묶음이면 QA 시나리오에 키보드만으로(Tab·Shift+Tab·화살표·Enter·Space·Esc) 전 흐름을 지나는 시나리오를 넣는다. Chrome DevTools MCP 의 `lighthouse_audit` 이 있으면 접근성 범주 결과를 QA 보고서에 적는다. 점수는 합격 기준이 아니라 단서다(낮은 항목은 시나리오로 다시 확인한다).
```

**Edit** `herdr-team/lib/hteam/setup.py`

```python
    "fonts-ko.md": ".herdr-team/fonts-ko.md",
```

```python
    "fonts-ko.md": ".herdr-team/fonts-ko.md",
    "web-rules.md": ".herdr-team/web-rules.md",
```

**Edit** `README.md`

```markdown
즉시 차단 항목 10개(보고서에 예외를 적어도 리뷰가 P1)
```

```markdown
즉시 차단 항목 11개(보고서에 예외를 적어도 리뷰가 P1)
```

**Edit** `README.md`

```markdown
카탈로그(taste-skill MIT·impeccable Apache-2.0 팔레트, 한글 글꼴, 과용 색·글꼴)는 플러그인 `lib/hteam/data/` 에 있다.
```

```markdown
카탈로그(taste-skill MIT·impeccable Apache-2.0 팔레트, 한글 글꼴, 과용 색·글꼴)는 플러그인 `lib/hteam/data/` 에 있다.
- `.herdr-team/web-rules.md`(0.8.0, 웹 UI 를 만들거나 시험하는 designer·developer·tester 와 디자인 리뷰어): Baseline(새 기능은 폴백과 함께), 오버레이(`<dialog>`·`popover`·`<details>`), 폼 검증 시점(`:user-invalid`), 테마·색 구현(`light-dark()`), 움직임 구현(`opacity`·`transform` 만), 성능, 구조·이름, 아이콘 구현. 1초에 3번 넘는 번쩍임은 즉시 차단이다. 앱만 만드는 태스크는 읽지 않는다.
```

**Edit** `README.md`

```markdown
planner 는 확정 질문 전에 이 경고를 보고 나누거나 나누지 않은 이유를 적는다.
```

```markdown
planner 는 확정 질문 전에 이 경고를 보고 나누거나 나누지 않은 이유를 적는다.
- UI 가 있는 묶음의 tester(0.8.0)는 QA 시나리오에 키보드만으로 전 흐름을 지나는 시나리오와 Chrome DevTools MCP `lighthouse_audit`(있으면)의 접근성 결과를 넣는다. 점수는 합격 기준이 아니라 단서다.
```

- [ ] **Step 5: 시험이 통과하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_rule_refs tests.test_design_docs tests.test_setup.ScaffoldTest tests.test_setup.UpgradeTest tests.test_setup.SubdirUpgradeTest)`
Expected: PASS — `Ran 74 tests`, `OK`

Run: `(cd herdr-team && python3 -m unittest tests.test_quality tests.test_wording tests.test_interview tests.test_project_rules tests.test_review.DesignSectionTest)`(직무 문서·리뷰 디자인 절을 읽는 다른 시험)
Expected: PASS — `Ran 73 tests`, `OK (skipped=1)`

- [ ] **Step 6: 개인 경로를 확인하고 커밋한다**

```bash
python3 -m py_compile herdr-team/lib/hteam/setup.py herdr-team/tests/test_rule_refs.py herdr-team/tests/test_design_docs.py herdr-team/tests/test_setup.py
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews'
git add -- herdr-team/templates/web-rules.md herdr-team/templates/design-rules.md herdr-team/templates/review-design.md herdr-team/templates/roles/designer.md herdr-team/templates/roles/developer.md herdr-team/templates/roles/tester.md herdr-team/lib/hteam/setup.py README.md herdr-team/tests/test_rule_refs.py herdr-team/tests/test_design_docs.py herdr-team/tests/test_setup.py
git commit -m "feat(herdr-team): web-rules.md, design-rules 웹 항목·번쩍임 즉시 차단, 직무 문서·리뷰 디자인 절, scaffold·upgrade 대상(설계 11.9·11.12 의 1·4·5)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/templates/web-rules.md herdr-team/templates/design-rules.md herdr-team/templates/review-design.md herdr-team/templates/roles/designer.md herdr-team/templates/roles/developer.md herdr-team/templates/roles/tester.md herdr-team/lib/hteam/setup.py README.md herdr-team/tests/test_rule_refs.py herdr-team/tests/test_design_docs.py herdr-team/tests/test_setup.py
```

---

### Task 2: 내용 검사의 웹 항목과 designdiff 지운 줄 신호, 자동 검사 절과 `[기계]` 표기(설계 11.13 의 1 웹·2 지운 줄)

`lint.web_findings` 가 바뀐 파일에서 웹 의심 위치를 찾는다(Codex 계획 리뷰 r1 의 여덟 지적, r2 의 여섯 지적, r3 의 둘을 반영한 판이다. r3 의 나머지 셋은 알려진 한계다). JS 문자열은 일반적으로 가르지 않는다: JS 문자열 안의 예시 태그·선언은 검사한다(경고 전용, 리뷰어 판단. 의도한 범위다).

1. 주석을 같은 길이의 공백으로 지운 글을 본다(`strip_comments`, 줄 번호가 바뀌지 않는다): `/* */`(여러 줄, JSX `{/* */}` 포함)와 `<!-- -->` 는 어디서나, `//` 는 줄의 첫 글자(앞 공백 뒤)일 때만(주석 처리한 코드 줄. 줄 가운데의 `https://`·`url(//…)`·끝 주석은 그대로). 따옴표 글을 가리지 않는다: 본문의 아포스트로피(`Don't`)가 뒤의 주석을 가리지 않는 대신, 글 안의 `/*`(`"src/**/*.ts"`)는 다음 `*/` 까지 지운다(놓치는 쪽). `.css`·`.json` 에는 `//` 주석이 없다. .js·.jsx·.ts·.tsx 는 styled-components·emotion 의 CSS 템플릿 글(`css`·`keyframes`·`createGlobalStyle`·`injectGlobal`·`styled.<태그>`·`styled(<X>)` 뒤, TypeScript 타입 인수 `<Props>`(세 겹까지, 안의 `=>` 포함)와 `.attrs(…)` 를 거쳐도)을 찾아 그 안의 `${…}`(짝 맞는 중괄호, JS 글의 이스케이프를 따른다)도 공백으로 지운다.
2. 선언: `transition`·`transition-property`·`transitionProperty`·`will-change`·`willChange`. CSS 범위(.css·.scss 는 파일 전체, 그 밖은 `<style>` 블록, CSS 템플릿 글, 정적 `style="…"` 값)에서는 선언 머리(범위 처음, `{`·`;`·줄 처음 뒤. 사이 공백은 된다)이고 CSS 글(`content: 'transition: all'`) 밖일 때만 보고, 값을 `;`·`{`·`}`·줄 끝까지 읽는다(`${…}` 를 지운 값이 빈 칸이면 알리지 않는다). 그 밖(JS 객체·JSON)은 값이 글 하나일 때만 읽는다(`"…"`·`'…'`·`${` 없는 템플릿 글이고 뒤가 `,`·`;`·`}`·`)`·`]`·줄 끝): 삼항식·함수 호출·이름은 읽지 않아 다음 속성(`left: 0`)을 값으로 읽지 않는다. `transition` 값의 `all`·`height`·`max-height`·`width`·`top`·`left` 와 `auto` 가 아닌 `will-change` 를 알린다.
3. CSS 선택자의 `:invalid`: .css·.scss, `<style>` 블록, CSS 템플릿 글을 `{`·`;`·`}` 로 끊어 `{` 로 끝나는 조각(선택자)만 본다. JS 문자열(`querySelectorAll(":invalid, …")`)과 JS 객체(`{invalid:true}`)는 보지 않는다.
4. 태그: 태그 머리 `<이름`(앞이 ASCII 낱말 글자·`$`·`.`·`)`·`]` 면 비교식·제네릭이라 아니다)부터 닫는 `>` 를 따옴표 값과 중괄호 값 깊이를 따라 읽고(`{count > 0}`·`{a<b}` 안은 건너뛰고 중괄호 안 JS 글은 이스케이프 `'it\'s'` 를 따른다. 여러 줄, SCAN_WINDOW 안, 중괄호 밖에서 다음 태그의 `<` 를 만나면 멈춘다) 속성 이름·값으로 나눈다. `.html` 은 태그 이름의 대소문자를 가리지 않고(`<IMG>`·`<DIV onclick>`), 컴포넌트 파일(.jsx·.tsx·.vue·.svelte 등)은 소문자 태그만 네이티브로 본다. 태그를 앞에서부터 한 번씩 읽고 그 끝 뒤에서 다음 태그를 찾으므로 속성 값 안의 태그 모양(`title="<img>"`)은 태그가 아니다. 알리는 것:
   - 한 줄 안에서 닫힌 `<img>`·`<video>` 가 클래스(`class`·`className`·`:class`·`v-bind:class`·`class:list`·`class:…`)·style·펼침(`{...props}`) 없이 `width`·`height` 를 둘 다 갖지 않을 때(클래스·style 이 있으면 크기를 알 수 없어 경고하지 않는다).
   - 한 줄 안에서 닫힌 `<iframe>` 에 `title`(`:title` 포함)이 없을 때(설계 그대로 `aria-label` 은 대신하지 않는다).
   - `<div>`·`<span>` 에 `onClick`·`onclick`·`@click` 속성(여러 줄 태그 포함).
   - 모든 태그의 `role` 값이 `button`(정적 값, `{"button"}`). Vue `:role`·`v-bind:role` 은 값이 `'button'` 글일 때만이다(`:role="button"` 은 이름이다).
   - `tabindex`·`tabIndex`·`:tabindex` 의 양수 값.
   - 클래스 값의 Tailwind `transition-all`·`transition-[…]`·`will-change-*`(`auto` 빼고)·`invalid:`·`peer-invalid:`·`group-invalid:`. 정적 값(`class="…"`)은 값 전체, JS 식 값(`className={cn(…)}`·`:class="…"`·`class:list={…}`)은 그 안의 따옴표 글만 본다(글을 앞에서부터 한 번씩 훑는다: 이스케이프 따옴표가 많은 깨진 JSX 에서도 선형이다).
5. `.css` 의 `@import`: 주석을 지운 줄의 머리만 센다(파일당 한 줄, `@import "tailwindcss…"` 는 뺀다, `.scss` 는 Sass 의 가져오기라 보지 않는다).

Markdown 은 보지 않는다(README 배지 `<img>`, 규칙을 옮긴 설명 글). 모든 단계가 입력 길이에 비례한다: 주석은 정규식 한 번, CSS 템플릿 글은 앞에서부터 한 번씩, CSS 조각은 끝 문자를 빼도 되는 정규식(실패하고 다음 위치에서 다시 훑지 않는다), 태그는 한 번씩, 값은 300자, 발췌는 200자 안이다(1 MB 적대적 입력 시험). `compose.design_findings` 가 넷째 `guarded` 로 부른다(designdiff → 내용 검사 → 웹 → 색·글꼴, 50건). 프로젝트에 `.herdr-team/web-rules.md` 가 있을 때만 돈다: 경고가 인용하는 web-rules 항목이 upgrade 전 프로젝트에는 없다. designdiff 의 지운 줄 신호에 `aria-expanded`·`aria-pressed`·`<caption`·`scope` 를 더한다. `scope` 는 표 머리 값(`row`·`col`·`rowgroup`·`colgroup`, 따옴표·따옴표 없음·`{"col"}`)이 붙은 것만 센다: 같은 뜻의 HTML 정리(`scope=col`)가 줄어든 것으로 나오지 않고, `const scope = view` 같은 JS 변수는 신호가 아니다. designdiff 는 diff 의 줄 조각을 줄마다 세므로(지운 줄은 태그 전체가 아니다) 태그 읽기를 쓰지 않는다. 그다음 design-rules 의 자동 검사 절에 새 검사를 적고 가리키는 항목을 `[기계]` 로 바꾼다(design-rules §2 의 1·3, §6 의 3, web-rules §3 의 2, §5 의 1, §6 의 2·4·7, §7 의 3·9·10). 리뷰 디자인 절은 기준 4 에 표 머리를, 자동 검사 안내에 웹 경고를 더한다. 기존 `scan`·`design_findings`·`style_findings` 는 그대로라 기존 시험의 기대값이 바뀌지 않는다.

**Files:**
- Modify: `herdr-team/lib/hteam/lint.py`(웹 검사), `herdr-team/lib/hteam/compose.py`(`design_findings`), `herdr-team/lib/hteam/designdiff.py`(`SIGNALS`)
- Modify: `herdr-team/templates/design-rules.md`(표기, 자동 검사 절), `herdr-team/templates/web-rules.md`(표기), `herdr-team/templates/review-design.md`(기준 4, 자동 검사 안내), `README.md`(자동 검사 줄)
- Modify: `herdr-team/tests/test_lint.py`, `herdr-team/tests/test_designdiff.py`, `herdr-team/tests/test_review.py`(`DesignSectionTest`)

**Interfaces:**
- Consumes: Task 1 의 `web-rules.md`(항목 번호와 `[판단]` 표기 줄), design-rules §2 의 1·3, §6 의 3, `tests.test_rule_refs.method_problems(*paths)`(검사 방식 표기 시험이 design-rules 자동 검사 절의 `web-rules §N 의 M` 을 web-rules 항목으로 본다).
- Produces: `lint.web_scan(rel, text) -> list[str]`, `lint.web_findings(root, files) -> list[str]`, `lint.WEB_RULES_FILE`, `compose.design_findings` 의 웹 경고(Task 3 README 의 0.8.0 절이 가리킨다).

- [ ] **Step 1: 시험을 먼저 쓴다**

**Edit** `herdr-team/tests/test_lint.py`

```python
from hteam.lint import (DESIGN_ROLES, MAX_BYTES, MAX_FINDINGS, STYLE_RULES_MARKER, cap, design_findings, design_lint,
                        font_stack, has_style_rules, hue_family, scan, style_findings, style_scan)
```

```python
from hteam.lint import (DESIGN_ROLES, MAX_BYTES, MAX_FINDINGS, STYLE_RULES_MARKER, WEB_SUFFIXES, cap, design_findings,
                        design_lint, font_stack, has_style_rules, hue_family, scan, strip_comments, style_findings, style_scan,
                        web_findings, web_scan)
```

**Edit** `herdr-team/tests/test_lint.py`

```python
class LintCommandTest(TeamCase):
```

```python
class WebScanTest(unittest.TestCase):
    """13단계 웹 검사(설계 11.13 의 1 웹): 잡는 것과 잡지 않는 것(주석, 속성 값 안의 태그·비교식, 글 하나가 아닌 JS 값, JS 객체 키,
    CSS 글, 크기를 알 수 없는 태그), CSS 템플릿 글, HTML 의 대문자 태그, 대상 파일, 1 MB 입력의 시간."""

    def heads(self, rel, text):
        """`파일:줄: 이름` 부분만(발췌 앞 첫 괄호까지)."""
        return [item.split("(", 1)[0] for item in web_scan(rel, text)]

    def test_transition_values(self):
        css = (".a { transition: all .2s ease; }\n"
               ".b { transition: opacity .2s, max-height .3s; }\n"
               ".c { transition-property: width; }\n"
               ".d { transition: opacity .2s, transform .2s; transition-behavior: allow-discrete; }\n"
               ".e { transition: margin-left .2s, min-width .2s; }\n"
               ".f:has(.top) { --fade-transition: top; }\n"
               ".g { content: 'transition: all .2s'; }\n"
               ".h { color: red;transition: top 1s }\n")
        self.assertEqual(web_scan("src/a.css", css), [
            "src/a.css:1: transition all(transition: all .2s ease; }) — design-rules §6 의 3, web-rules §5 의 1",
            "src/a.css:2: transition max-height(transition: opacity .2s, max-height .3s; }) — design-rules §6 의 3, "
            "web-rules §5 의 1",
            "src/a.css:3: transition width(transition-property: width; }) — design-rules §6 의 3, web-rules §5 의 1",
            "src/a.css:8: transition top(transition: top 1s }) — design-rules §6 의 3, web-rules §5 의 1"])
        jsx = ("<div style={{ transition: 'opacity .2s', left: 0 }} />\n"
               '<div style={{ transition: "height 0.3s" }} />\n'
               "const s = { transitionProperty: 'top' }\n"
               '<p className="transition-all duration-200">x</p>\n'
               '<p className="transition-[max-height,opacity] transition-opacity">x</p>\n'
               "<p transition:slide>Move left</p>\n"
               '{"transition": "all 0.2s", "transition-duration": "200ms"}\n'
               'const t = { transition: enabled ? "opacity .2s" : "none", left: 0 };\n'
               "const u = { transition: theme.transitions.create('width'), top: 0 };\n"
               'const v = { transition: `${prop} .2s`, w: { transition: "left .2s" } };\n'
               'const x = "transition-all";\n'
               '<div style="transition: width .3s">x</div>\n')
        self.assertEqual(self.heads("src/a.tsx", jsx),
                         ["src/a.tsx:2: transition height", "src/a.tsx:3: transition top", "src/a.tsx:4: transition all",
                          "src/a.tsx:5: transition max-height", "src/a.tsx:7: transition all", "src/a.tsx:10: transition left",
                          "src/a.tsx:12: transition width"])

    def test_comments_are_not_code(self):
        # Codex 계획 리뷰 r1·r2: 주석 안의 선언·태그·가져오기(여러 줄 주석 포함)는 경고하지 않는다. 줄 번호는 그대로다. 본문의
        # 아포스트로피가 뒤의 주석을 가리지 않고, `//` 는 줄의 첫 글자일 때만 주석이라 `https://` 는 코드다
        css = ('/* transition: all .2s;\n   @import "old.css"; */\n'
               '.a { color: red; } /* will-change: transform */\n'
               '@import "real.css";\n')
        self.assertEqual(web_scan("src/a.css", css), ["src/a.css:4: CSS @import 1개 — web-rules §6 의 4"])
        scss = ('.a {\n  // transition: all .2s;\n  color: red; }\n'
                '.b { background: url(//cdn.example.com/a.png); transition: top .2s; }\n')
        self.assertEqual(self.heads("src/a.scss", scss), ["src/a.scss:4: transition top"])
        html = ('<!-- <img src="old.png"> -->\n'
                '<!--\n<iframe src="x"></iframe>\n-->\n'
                '<p>https://example.com 참고</p><img src="new.png">\n'
                "<p>Don't worry</p><!-- <img src=x> -->\n")
        self.assertEqual(self.heads("src/a.html", html), ["src/a.html:5: 크기 없는 <img>"])
        tsx = ('// <div onClick={go}>\n'
               '/* <div role="button">\n   <li tabindex="2"> */\n'
               '{/* <span onClick={go}>열기</span> */}\n'
               'const a = { transition: "left .2s" };\n'
               '  // const b = { transition: "all .2s" };\n'
               '<a href="https://example.com/a">링크</a><div tabIndex={3}>x</div>\n'
               "<p>Don't worry</p>{/* <img src=x> */}\n"
               'const u = "https://example.com"; const c = { transition: "top 1s" };\n')
        self.assertEqual(self.heads("src/a.tsx", tsx),
                         ["src/a.tsx:5: transition left", "src/a.tsx:7: 양수 tabindex", "src/a.tsx:9: transition top"])

    def test_strip_comments_keeps_positions(self):
        # 따옴표 글을 가리지 않는다: 글 안의 `/* */` 도 지우고(놓치는 쪽), 줄 가운데의 `//` 는 그대로 둔다
        text = 'a /* x\ny */ b <!-- c\n--> "/* 글 */" // d\n  // e\n{/* f */}\n'
        out = strip_comments(text)
        self.assertEqual(len(out), len(text))
        self.assertEqual(out.split("\n"), ["a     ", "     b       ", '    "       " // d', "      ", "{       }", ""])
        self.assertEqual(strip_comments("  // a\nb", line_comments=False), "  // a\nb")

    def test_css_import_once_per_file(self):
        css = ('@import "tailwindcss";\n@import url("https://fonts.googleapis.com/css2?family=Gowun+Dodum");\n.a {}\n'
               '  @import "./b.css";\n/* @import "c.css"; */\n')
        self.assertEqual(web_scan("src/app.css", css), ["src/app.css:2: CSS @import 2개 — web-rules §6 의 4"])
        self.assertEqual(web_scan("src/app.scss", '@import "vars";\n'), [])  # Sass 의 가져오기
        self.assertEqual(web_scan("src/app.css", '@import "tailwindcss/preflight";\n'), [])
        self.assertEqual(web_scan("src/a.html", '<style>@import "b.css";</style>\n'), [])  # .css 의 줄 머리만 본다

    def test_media_without_size_and_frame_without_title(self):
        html = ('<img src="a.png" alt="">\n'
                '<img src="b.png" alt="" width="40" height="40">\n'
                '<img src="c.png" alt="" width="40">\n'
                '<img class="avatar" src="d.png" alt="">\n'
                '<img className="w-full" src={u} alt="" />\n'
                '<img style="aspect-ratio: 4 / 3" src="e.png" alt="">\n'
                '<video controls :class="cls"></video><video src="m.mp4"></video>\n'
                '<img {...props} />\n'
                '<img alt="a > b" src="x.png"\n'
                '<Img src="x" /><img src="x" onLoad={() => setReady(true)} />\n'
                '<img\n  src="f.png"\n  alt=""\n/>\n'
                '<div title="<img src=x>">x</div>\n'
                '<iframe src="https://example.com/map"></iframe>\n'
                '<iframe title="매장 지도" src="https://example.com/map"></iframe>\n'
                '<iframe :title="t" src="x"></iframe><iframe aria-label="지도" src="y"></iframe>\n')
        self.assertEqual(self.heads("src/a.html", html),
                         ["src/a.html:1: 크기 없는 <img>", "src/a.html:3: 크기 없는 <img>", "src/a.html:7: 크기 없는 <video>",
                          "src/a.html:10: 크기 없는 <img>", "src/a.html:16: title 없는 <iframe>",
                          "src/a.html:18: title 없는 <iframe>"])
        found = web_scan("src/a.html", html)
        self.assertEqual(found[0], 'src/a.html:1: 크기 없는 <img>(<img src="a.png" alt="">) — web-rules §6 의 2')
        self.assertEqual(found[-1],
                         'src/a.html:18: title 없는 <iframe>(<iframe aria-label="지도" src="y"></iframe>) — web-rules §7 의 9')

    def test_keyboard_and_native_controls(self):
        jsx = ('<div tabIndex={2}>x</div>\n'
               '<li tabindex="1">x</li><li tabindex="0">y</li><li tabindex="-1">z</li>\n'
               'const [tabIndex, setTabIndex] = useState(0); tabIndex = 1; <p data-tabindex="3" />\n'
               '<div role="button" tabIndex={0} onClick={go} onKeyDown={key}>열기</div>\n'
               '<div\n  className="card"\n  onClick={() => open(item)}\n>\n'
               '<button onClick={save}>저장</button><span>{a > b ? 1 : 2}</span>\n'
               'el.onclick = go;\n'
               '<span @click.stop="toggle">펼치기</span>\n'
               '<div aria-hidden={count > 0} onClick={go}>x</div>\n'
               '<div data-x={a<b} onClick={go}>y</div>\n'
               "<p title=\"role='button'\">x</p><Box role={'button'} />\n"
               '<div :role="button">a</div><div :role="\'button\'">b</div><i v-bind:tabindex="2" />\n'
               "<p title={'it\\'s fine'} />\n<div onClick={go}>x</div>\n<img src=x>\n")
        self.assertEqual(self.heads("src/a.tsx", jsx),
                         ["src/a.tsx:1: 양수 tabindex", "src/a.tsx:2: 양수 tabindex", 'src/a.tsx:4: role="button"',
                          "src/a.tsx:4: 클릭 처리기를 단 <div>", "src/a.tsx:7: 클릭 처리기를 단 <div>",
                          "src/a.tsx:11: 클릭 처리기를 단 <span>", "src/a.tsx:12: 클릭 처리기를 단 <div>",
                          "src/a.tsx:13: 클릭 처리기를 단 <div>", 'src/a.tsx:14: role="button"', 'src/a.tsx:15: role="button"',
                          "src/a.tsx:15: 양수 tabindex", "src/a.tsx:17: 클릭 처리기를 단 <div>", "src/a.tsx:18: 크기 없는 <img>"])
        found = web_scan("src/a.tsx", jsx)
        self.assertEqual(found[0], "src/a.tsx:1: 양수 tabindex(tabIndex={2}>x</div>) — design-rules §2 의 3")
        self.assertEqual(found[4], "src/a.tsx:7: 클릭 처리기를 단 <div>(onClick={() => open(item)}) — design-rules §2 의 1")

    def test_html_tag_names_ignore_case(self):
        # Codex 계획 리뷰 r2: .html 의 대문자 태그는 같은 네이티브 태그다. 컴포넌트 파일은 소문자 태그만 네이티브다
        text = '<IMG src=x>\n<DIV onclick="go()">x</DIV>\n<Span ONCLICK="go()">y</Span>\n'
        self.assertEqual(self.heads("src/a.html", text),
                         ["src/a.html:1: 크기 없는 <img>", "src/a.html:2: 클릭 처리기를 단 <div>", "src/a.html:3: 클릭 처리기를 단 <span>"])
        self.assertEqual(web_scan("src/A.tsx", text), [])

    def test_css_in_js_templates(self):
        # Codex 계획 리뷰 r2: styled-components·emotion 의 CSS 템플릿 글은 CSS 다. `${…}` 는 지우고 본다
        tsx = ('const Box = styled.div`transition: all .2s; will-change: transform;`;\n'
               'const B = styled(Button).attrs({ type: "button" })`\n'
               '  transition: ${p => p.speed};\n'
               '  will-change: ${(p) => (p.on ? "transform" : "auto")};\n'
               '  &:invalid { color: red; }\n'
               '`;\n'
               'const fade = keyframes`from { opacity: 0 } to { opacity: 1 }`;\n'
               'const c = css`\n  content: "transition: all";\n  transition: height ${d}ms;\n`;\n'
               'const t = `transition: all .2s`;\n')
        self.assertEqual(self.heads("src/a.tsx", tsx),
                         ["src/a.tsx:1: transition all", "src/a.tsx:1: will-change", "src/a.tsx:5: user- 없는 :invalid",
                          "src/a.tsx:10: transition height"])
        self.assertEqual(web_scan("src/a.vue", "<script>const B = styled.div`transition: all .2s;`</script>\n"), [])
        # Codex 계획 리뷰 r3: 머리와 백틱 사이의 TypeScript 타입 인수(겹친 `<…>`, 안의 `=>`)도 CSS 템플릿 글이다
        typed = ('const A = styled.div<{ on: boolean; cb: () => void }>`transition: all .2s;`;\n'
                 'const B = styled(Button)<Props>`transition: all .2s;`;\n'
                 'const C = styled.div.attrs({ type: "button" })<P>`transition: all .2s;`;\n'
                 'const D = styled.div<Map<string, Array<number>>>`will-change: transform;`;\n'
                 'const E = a < b ? 1 : 2; const F = `transition: all`;\n')
        self.assertEqual(self.heads("src/b.tsx", typed),
                         ["src/b.tsx:1: transition all", "src/b.tsx:2: transition all", "src/b.tsx:3: transition all",
                          "src/b.tsx:4: will-change"])

    def test_invalid_and_will_change(self):
        css = ('input:invalid { border-color: red; }\n'
               'input:user-invalid { border-color: red; }\n'
               'form :not(:invalid),\n.b:invalid:focus {\n  color: red;\n}\n'
               '.c::before { content: ":invalid"; }\n'
               '.a { will-change: transform; }\n.b { will-change: auto; }\n')
        self.assertEqual(self.heads("src/a.css", css),
                         ["src/a.css:1: user- 없는 :invalid", "src/a.css:3: user- 없는 :invalid", "src/a.css:4: user- 없는 :invalid",
                          "src/a.css:8: will-change"])
        tsx = ('<input className="invalid:border-red-500 user-invalid:border-red-500 aria-invalid:ring" />\n'
               '<input className={cn("peer-invalid:block", ok && "group-invalid:flex")} />\n'
               'const errors = {invalid:true};\n'
               'form.querySelectorAll(":invalid, :out-of-range");\n'
               'input:invalid { color: red }\n'
               '<p className="will-change-transform will-change-auto">x</p>\n'
               'const s = { willChange: "opacity", w: { willChange: "auto" } };\n'
               'const t = { willChange: isOpen ? "transform" : "auto" };\n')
        self.assertEqual(self.heads("src/a.tsx", tsx),
                         ["src/a.tsx:1: user- 없는 :invalid", "src/a.tsx:2: user- 없는 :invalid", "src/a.tsx:6: will-change",
                          "src/a.tsx:7: will-change"])
        vue = ('<template><input :class="{ \'invalid:ring\': bad }" /></template>\n'
               '<style scoped>\ninput:invalid { color: red }\n.x { transition: height .2s; will-change: top }\n</style>\n'
               '<script>const s = { transition: open ? "height .2s" : "none" }</script>\n')
        self.assertEqual(self.heads("src/a.vue", vue),
                         ["src/a.vue:1: user- 없는 :invalid", "src/a.vue:3: user- 없는 :invalid", "src/a.vue:4: transition height",
                          "src/a.vue:4: will-change"])
        self.assertEqual(web_scan("src/a.css", "a:invalid{}\n"), ["src/a.css:1: user- 없는 :invalid(:invalid{}) — web-rules §3 의 2"])
        self.assertEqual(web_scan("src/a.css", "a{will-change:opacity}\n"),
                         ["src/a.css:1: will-change(will-change:opacity}) — web-rules §6 의 7"])

    def test_targets(self):
        root = Path(tempfile.mkdtemp(prefix="hteam-web-")).resolve()
        self.addCleanup(shutil.rmtree, root, True)
        for rel in ("src/a.html", "docs/design/system/README.md", "docs/planning/spec.md", "scripts/a.py",
                    "docs/design/screens/h/artifact/project/x.html"):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text('<div style="transition: all 1s"></div>\n<img src=x>\n', encoding="utf-8")
        files = ["src/a.html", "docs/design/system/README.md", "docs/planning/spec.md", "scripts/a.py",
                 "docs/design/screens/h/artifact/project/x.html", "../x.css", "src/gone.css"]
        self.assertEqual([x.split("(")[0] for x in web_findings(root, files)],
                         ["src/a.html:1: transition all", "src/a.html:2: 크기 없는 <img>"])
        self.assertNotIn(".md", WEB_SUFFIXES)
        self.assertEqual(design_lint(root, files), [])  # 이모지 등 내용 검사는 웹 경고를 섞지 않는다

    def test_linear_on_hostile_input(self):
        import time
        mb = 1 << 20
        cases = {
            "a.css": "transition:" * (mb // 11),
            "b.css": "/*" * (mb // 2),
            "c.html": "<!--" * (mb // 4),
            "d.tsx": "'a" * (mb // 2),
            "e.tsx": "//" * (mb // 2),
            "f.tsx": "`" + "a" * mb,
            "g.html": "<img " * (mb // 5),
            "h.html": "<img>" * (mb // 5),
            "i.tsx": "<div {" * (mb // 6),
            "j.tsx": '<div "' * (mb // 6),
            "k.tsx": "<div " + "x onClick={a} " * (mb // 14),
            "l.tsx": "<div\n onClick={a}\n>\n" * (mb // 18),
            "m.tsx": '<div className={cn("' + "invalid:x " * (mb // 10) + '")}>',
            "n.html": "<style" * (mb // 6),
            "o.html": 'style="' * (mb // 7),
            "p.html": "<style>" + "a{" * (mb // 2),
            "q.css": ".a{transition:all 1s}\n" * (mb // 22),
            "r.css": "@import x;\n" * (mb // 11),
            "s.tsx": 'transition: "' * (mb // 13),
            "t.tsx": "<a b=" * (mb // 5),
            "u.css": "a:invalid " * (mb // 10),
            "v.tsx": "styled.div`" * (mb // 11),
            "w.tsx": "css`${" * (mb // 6),
            "x.tsx": "styled.div.attrs((" * (mb // 18),
            "y.tsx": "css`" + "${'\\" * (mb // 4),
            "z.tsx": "\n  //" * (mb // 5),
            "aa.css": ".a{content:'" * (mb // 12),
            "ab.tsx": "<p title={'\\'" * (mb // 13),
            "ac.css": " " * mb + "transition: all",
            "ad.tsx": ('<div className={"\n' + r'\"a' * 1200 + '\n"} />\n') * 289,  # Codex 계획 리뷰 r3: 이스케이프 따옴표가 많은 깨진 JSX
            "ae.tsx": "styled.div<<<" * (mb // 13),
            "af.tsx": "styled(a)<" + "=" * mb,
        }
        for rel, text in cases.items():
            start = time.monotonic()
            web_scan(rel, text)
            self.assertLess(time.monotonic() - start, 1.5, rel)

    def test_rules_and_docs_name_the_checks(self):
        # 경고가 인용하는 항목이 자동 검사 절에 있고(검사 방식 표기 시험이 [기계] 를 본다) 리뷰 디자인 절·README 가 웹 검사를 적는다
        rules = (ROOT / "templates/design-rules.md").read_text(encoding="utf-8")
        auto = rules[rules.index("## 자동 검사"):rules.index("## 출처")]
        for needle in ("`role=\"button\"`(§2 의 1)", "양수 `tabindex`(§2 의 3)", "(§6 의 3)", "(web-rules §5 의 1)",
                       "(web-rules §3 의 2)", "(web-rules §6 의 2)", "(web-rules §6 의 4", "(web-rules §6 의 7)",
                       "(web-rules §7 의 9)", "(web-rules §7 의 10)", "(web-rules §7 의 3)", "web-rules.md 가 있을 때만",
                       "주석은 보지 않는다", "클래스·style 이 있는 `<img>`·`<video>` 는 크기를 알 수 없어 보지 않는다"):
            self.assertIn(needle, auto)
        review = (ROOT / "templates/review-design.md").read_text(encoding="utf-8")
        self.assertIn("웹 경고(`.herdr-team/web-rules.md` 가 있는 프로젝트에만 나오는", review)
        self.assertIn("표 머리(`<caption>`·`scope`)", review)
        readme = (ROOT.parent / "README.md").read_text(encoding="utf-8")
        self.assertIn("`.herdr-team/web-rules.md` 가 있는 프로젝트만", readme)
        self.assertIn("토글 `aria-expanded`·`aria-pressed`", readme)


class LintCommandTest(TeamCase):
```

**Edit** `herdr-team/tests/test_lint.py`

```python
    def test_lint_task_guard_findings(self):
```

```python
    def test_web_checks_only_with_web_rules(self):
        # 13단계 p13d(설계 11.13 의 1 웹): 웹 경고는 web-rules·design-rules 의 웹 항목을 인용한다. 프로젝트에 web-rules.md 가
        # 없으면(upgrade 전) 내지 않는다. 있으면 내용 검사 뒤에 붙는다
        self.write_spec("T-001", "developer")
        state.create(self.p, "T-001", "developer")
        self.assertEqual(self.hteam("start", "T-001")[0], 0)
        self.act_work("T-001", {"src/Menu.tsx": "<div onClick={open}>메뉴</div>\n<span>🚀</span>\n"})
        code, out = self.hteam("lint", "--task", "T-001", as_=None)
        self.assertEqual((code, out["findings"]), (0, ["src/Menu.tsx:2: 이모지(🚀)"]), out)
        self.commit(".herdr-team/web-rules.md", (ROOT / "templates/web-rules.md").read_text(encoding="utf-8"),
                    "chore: 0.8.0 upgrade")
        code, out = self.hteam("lint", "--task", "T-001", as_=None)
        self.assertEqual(out["findings"], ["src/Menu.tsx:2: 이모지(🚀)",
                                           "src/Menu.tsx:1: 클릭 처리기를 단 <div>(onClick={open}>메뉴</div>) — design-rules §2 의 1"],
                         out)

    def test_lint_task_guard_findings(self):
```

**Edit** `herdr-team/tests/test_designdiff.py`

```python
    def test_kept_signals_lost_in_a_redesign(self):  # 설계 11.13 의 2(13단계)
```

```python
    def test_toggle_and_table_header_signals(self):  # 설계 11.13 의 2(13단계 p13d)
        self.change({"src/Menu.tsx": '<button aria-expanded={open} aria-pressed="false">메뉴</button>\n',
                     "src/Table.html": '<table><caption>주문</caption><tr><th scope="col">번호</th></tr></table>\n'}, "기존")
        sha = self.change({"src/Menu.tsx": "<button>메뉴</button>\n",
                           "src/Table.html": "<table><tr><th>번호</th></tr></table>\n"})
        self.assertEqual(self.lint(["src/Menu.tsx", "src/Table.html"], [sha]),
                         [f"{rel}: 지운 줄에서 {name} 1개가 줄었다(대체가 있는지 확인)"
                          for rel, name in (("src/Menu.tsx", "aria-expanded"), ("src/Menu.tsx", "aria-pressed"),
                                            ("src/Table.html", "<caption"), ("src/Table.html", "scope"))])
        # 줄만 나눈 것은 상쇄된다
        self.change({"src/Menu.tsx": "<button\n  aria-expanded={open}\n>메뉴</button>\n"}, "[T-001] 되살림")
        again = self.change({"src/Menu.tsx": "<button aria-expanded={open}>\n  메뉴\n</button>\n"}, "[T-001] 줄 나눔")
        self.assertEqual(self.lint(["src/Menu.tsx"], [again]), [])
        # 같은 뜻의 HTML 정리(따옴표 없는 값)와 표가 아닌 JS 변수는 줄어든 것이 아니다(Codex 계획 리뷰 r1·r2)
        self.change({"src/T.html": '<th scope="col">번호</th>\n<th scope={"row"}>합계</th>\n',
                     "src/v.ts": "const scope = view\n"}, "기존 표")
        tidy = self.change({"src/T.html": "<th scope=col>번호</th>\n<th scope='row'>합계</th>\n",
                            "src/v.ts": "const area = view\n"}, "[T-001] 정리")
        self.assertEqual(self.lint(["src/T.html", "src/v.ts"], [tidy]), [])

    def test_kept_signals_lost_in_a_redesign(self):  # 설계 11.13 의 2(13단계)
```

**Edit** `herdr-team/tests/test_review.py`

```python
    def test_other_roles_have_no_design_section(self):
```

```python
    def test_web_warnings_follow_content_and_precede_style(self):
        # 13단계 p13d(설계 11.13 의 1 웹): 웹 검사는 프로젝트에 web-rules.md 가 있을 때만, 내용 검사 뒤·색·글꼴 검사 앞이다.
        # 따로 감싸 실패해도 다른 검사는 낸다
        with mock.patch.object(designdiff, "design_diff_lint", return_value=["d"]), \
                mock.patch.object(lint, "design_findings", return_value=["c"]), \
                mock.patch.object(lint, "web_findings", return_value=["w"]), \
                mock.patch.object(lint, "style_findings", return_value=["s"]):
            self.assertEqual(compose.design_findings(self.p, ["src/a.css"], []), ["d", "c"])
            self.commit(".herdr-team/web-rules.md", "# 웹 플랫폼 규칙\n", "chore: 웹 규칙")
            self.assertEqual(compose.design_findings(self.p, ["src/a.css"], []), ["d", "c", "w"])
            self.commit(".herdr-team/design-rules.md", (ROOT / "templates/design-rules.md").read_text(encoding="utf-8"),
                        "chore: 0.8.0 규칙")
            self.assertEqual(compose.design_findings(self.p, ["src/a.css"], []), ["d", "c", "w", "s"])
            with mock.patch.object(lint, "web_findings", side_effect=OSError("웹 검사가\n멈췄다")):
                found = compose.design_findings(self.p, ["src/a.css"], [])
        self.assertEqual(found, ["d", "c", "자동 검사 실패: OSError: 웹 검사가 멈췄다", "s"])

    def test_other_roles_have_no_design_section(self):
```

- [ ] **Step 2: 시험이 실패하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_lint tests.test_designdiff tests.test_review.DesignSectionTest tests.test_review.NoDirectorDesignTest tests.test_rule_refs)`
Expected: FAIL — `Ran 45 tests`, `FAILED (failures=1, errors=3)`(test_lint 은 `strip_comments`·`web_findings` 를 가져오지 못해 모듈 하나가 오류 하나로 센다, designdiff 의 새 신호·scope 정리, 리뷰의 웹 차례 둘)

- [ ] **Step 3: 웹 검사를 만든다**

**Edit** `herdr-team/lib/hteam/lint.py`

```python
read_source·cap 은 문구 검사(textlint)도 함께 쓴다.
"""
```

```python
13단계 웹 검사(web_findings)는 프로젝트에 web-rules.md 가 있을 때 design-rules·web-rules 의 웹 항목(클릭 처리기를 단 div·span,
role="button", 양수 tabindex, transition 의 all·레이아웃 속성, user- 없는 :invalid, 크기 없는 img·video, title 없는 iframe,
.css 의 @import, will-change)을 찾는다(compose 가 따로 감싼다).
read_source·cap 은 문구 검사(textlint)도 함께 쓴다.
"""
```

**Edit** `herdr-team/lib/hteam/lint.py`

```python
def design_lint(root: Path, files: list[str]) -> list[str]:
```

```python
# 13단계 웹 검사(설계 11.13 의 1 웹). 경고가 가리키는 규칙(규칙 참조 시험이 이 글의 인용을 본다)
RULE_TRANSITION = "design-rules §6 의 3, web-rules §5 의 1"
RULE_MEDIA = "web-rules §6 의 2"
RULE_IMPORT = "web-rules §6 의 4"
RULE_WILL_CHANGE = "web-rules §6 의 7"
RULE_IFRAME = "web-rules §7 의 9"
RULE_INVALID = "web-rules §3 의 2"
RULE_TABINDEX = "design-rules §2 의 3"
RULE_CLICK = "design-rules §2 의 1"
# Markdown 은 화면 코드가 아니다(README 배지의 <img>, 규칙을 옮겨 적은 설명 글). 그 밖의 대상·제외는 내용 검사와 같다
WEB_SUFFIXES = SUFFIXES - {".md"}
WEB_RULES_FILE = "web-rules.md"  # 프로젝트 .herdr-team/ 에 이 파일이 있을 때만 돈다(compose.design_findings)
CSS_SUFFIXES = frozenset({".css", ".scss"})  # 파일 전체가 CSS 다. 그 밖은 <style> 블록·정적 style 값·CSS 템플릿 글만 CSS 다
JS_SUFFIXES = frozenset({".js", ".jsx", ".ts", ".tsx"})  # styled-components·emotion 의 CSS 템플릿 글을 찾는 파일
HTML_SUFFIXES = frozenset({".html", ".htm"})  # 태그 이름의 대소문자를 가리지 않는 파일(컴포넌트 파일은 소문자 태그만 본다)
VALUE_WINDOW = 300  # 선언 값을 읽는 최대 글자 수(머리마다 줄 끝까지 읽지 않는다)
EXCERPT_WINDOW = 200  # 발췌를 만들기 전에 자르는 글자 수(긴 줄에서 경고마다 줄 끝까지 복사하지 않는다)
# 주석: `/* */`(JSX `{/* */}` 포함)·`<!-- -->` 는 어디서나, `//` 는 줄의 첫 글자(앞 공백 뒤)일 때만. 따옴표 글을 가리지 않는다
_COMMENTS = re.compile(r"/\*.*?(?:\*/|\Z)|<!--.*?(?:-->|\Z)|(?:\A|(?<=\n))[ \t]*//[^\n]*", re.S)
_COMMENTS_NO_LINE = re.compile(r"/\*.*?(?:\*/|\Z)|<!--.*?(?:-->|\Z)", re.S)
_NOT_NEWLINE = re.compile(r"[^\n]")
_STYLE_BLOCK = re.compile(r"<style\b[^<>]{0,500}>(.*?)(?:</style\s*>|\Z)", re.S | re.I)
_STYLE_ATTR = re.compile(r"""(?<![\w:.-])style\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.I)
# CSS 템플릿 글의 머리: css`…`·keyframes`…`·createGlobalStyle`…`·injectGlobal`…`·styled.div`…`·styled(X)`…`. 머리와 백틱 사이에
# TypeScript 타입 인수(`<Props>`, 세 겹까지의 `<…>`, 안의 `=>` 는 닫는 괄호가 아니다)와 `.attrs(…)` 가 올 수 있다. 반복은 모두 상한이
# 있고 되돌아가지 않는다(possessive)
_TYPE_ARGS = r"(?:\s*<(?:=>|[^<>`=]|=|<(?:=>|[^<>`=]|=|<(?:=>|[^<>`=]|=){0,200}+>){0,200}+>){0,300}+>)?"
_CSS_TEMPLATE = re.compile(r"(?<![\w$.])(?:css|keyframes|createGlobalStyle|injectGlobal|styled\.[A-Za-z]\w*|styled\([^()\n]{0,200}\))"
                           + _TYPE_ARGS + r"(?:\s*\.attrs\((?:[^()]|\([^()]{0,500}\)){0,500}\))?" + _TYPE_ARGS + r"\s*`")
_TEMPLATE_STOP = re.compile(r"[`\\]|\$\{")
_CSS_STRING = re.compile(r""""(?:\\.|[^"\\\n])*+"?|'(?:\\.|[^'\\\n])*+'?""")  # CSS 글(content: '…'). 닫히지 않으면 줄 끝까지
# 선언 머리: CSS·JSON(`"transition":`)·JS 객체. 앞이 낱말 글자·`$`·`.`·`-` 면 아니다(`--fade-transition`, `.transition:hover`)
_DECL = re.compile(r"""(?<![\w$.-])(transition(?:-property|Property)?|will-change|willChange)["']?\s*:\s*""")
_CSS_VALUE = re.compile(r"""[^;{}<>\n"']*""")  # CSS 값의 끝. `"`·`'` 는 style 속성 값의 끝이다
_JS_LITERAL = re.compile(r""""((?:\\.|[^"\\\n]){0,300})"|'((?:\\.|[^'\\\n]){0,300})'|`((?:\\.|[^`\\]){0,300})`""")
_VALUE_END = re.compile(r"[ \t]*(?:[,;})\]\r\n]|\Z)")  # JS 값이 글 하나로 끝났다(뒤에 `+`·`?`·`.` 가 이어지지 않는다)
_AUTO = re.compile(r"\s*auto\b")
_TRANSITION_PROP = re.compile(r"(?<![\w-])(all|max-height|height|width|top|left)(?![\w-])")
_SEGMENT = re.compile(r"[^{};]*[{};]?")  # CSS 를 `{`·`;`·`}` 로 끊은 조각. `{` 로 끝나면 선택자다
_CSS_INVALID = re.compile(r"(?<!:):invalid(?![\w-])")  # `:user-invalid` 는 `:invalid` 를 담지 않는다
_TW_TRANSITION = re.compile(r"(?<![\w-])transition-(all|\[[^\]\s]{0,100}\])(?![\w-])")
_TW_WILL_CHANGE = re.compile(r"(?<![\w-])will-change-(?!auto(?![\w-]))[\w\[]")
_TW_INVALID = re.compile(r"(?<![\w-])(?:peer-|group-)?invalid:(?=[\w!\[])")
_CSS_IMPORT = re.compile(r"[ \t]*@import\b")
_TW_IMPORT = re.compile(r"""[ \t]*@import\s+["']tailwindcss["'/]""")  # Tailwind v4 의 입구
# 태그 머리: 앞이 ASCII 낱말 글자·`$`·`.`·`)`·`]` 면 비교식·제네릭(`a<b`, `useState<boolean>`)이라 태그가 아니다
_TAG_OPEN = re.compile(r"(?<![A-Za-z0-9_$.)\]])<([A-Za-z][\w.:-]*)")
_TAG_STOP = re.compile(r"""["'`{}>]|<(?=[A-Za-z/!])""")
_BRACE_STOP = re.compile(r"""["'`{}]""")
# 중괄호 안 JS 글의 나머지(역슬래시 이스케이프를 따른다, `'it\'s'`). 닫는 따옴표까지 맞는다
_QUOTE_TAIL = {q: re.compile(r"(?:\\.|[^%s\\])*+%s" % (q, q), re.S) for q in "\"'`"}
_ATTR_NAME = re.compile(r"""[^\s=/>"'`{}]+""")
_ATTR_GAP = re.compile(r"[\s/]*")
_WS = re.compile(r"\s*")
_UNQUOTED = re.compile(r"[^\s>]*")
_BUTTON = re.compile(r"""\s*(["'`])button\1\s*""")
_POSITIVE = re.compile(r"\s*\+?0*[1-9]\d*\s*")
_STRING_START = re.compile(r"""["'`]""")
# 클래스 JS 식 안 따옴표 글의 나머지(이스케이프를 따른다). `"`·`'` 는 줄 끝에서 끝난다. 그룹 1 은 닫는 따옴표(없으면 None)
_STRING_REST = {'"': re.compile(r'(?:\\.|[^"\\\n])*+(")?'), "'": re.compile(r"(?:\\.|[^'\\\n])*+(')?"),
                "`": re.compile(r"(?:\\[\s\S]|[^`\\])*+(`)?")}
_CLASS_NAMES = frozenset({"class", "classname", ":class", "v-bind:class", "class:list"})
_STYLE_NAMES = frozenset({"style", ":style", "v-bind:style"})


def _blank(text: str, spans: list[tuple[int, int]]) -> str:
    """spans(차례, 겹치지 않는다)를 같은 길이의 공백으로 바꾼 글(줄바꿈은 둔다)."""
    out: list[str] = []
    last = 0
    for a, b in spans:
        out += [text[last:a], _NOT_NEWLINE.sub(" ", text[a:b])]
        last = b
    out.append(text[last:])
    return "".join(out)


def strip_comments(text: str, line_comments: bool = True) -> str:
    """주석을 같은 길이의 공백으로 바꾼 글(줄바꿈은 두므로 줄 번호·위치가 그대로다): `/* */`(여러 줄, JSX `{/* */}` 포함)와
    `<!-- -->` 는 어디서나, line_comments 면 줄의 첫 글자(앞 공백 뒤)인 `//` 줄(주석 처리한 코드 줄)도. 따옴표 글을 가리지
    않는다(본문의 아포스트로피가 주석을 가리지 않게): 글 안의 `/*`(`"src/**/*.ts"`)는 다음 `*/` 까지 지운다. 닫히지 않은
    주석은 파일 끝까지다."""
    rx = _COMMENTS if line_comments else _COMMENTS_NO_LINE
    return _blank(text, [m.span() for m in rx.finditer(text)])


def _brace_end(code: str, i: int, end: int) -> int:
    """code[i] 의 `{` 와 짝이 맞는 `}` 의 위치. 따옴표 글(이스케이프를 따른다) 안의 괄호는 건너뛴다. 없으면 end."""
    depth = 0
    while True:
        m = _BRACE_STOP.search(code, i, end)
        if m is None:
            return end
        c, i = m.group(0), m.end()
        if c in "\"'`":
            tail = _QUOTE_TAIL[c].match(code, i, end)
            if tail is None:
                return end
            i = tail.end()
        elif c == "{":
            depth += 1
        else:
            depth -= 1
            if depth <= 0:
                return m.start()


def _css_templates(code: str) -> tuple[str, list[tuple[int, int]]]:
    """styled-components·emotion 의 CSS 템플릿 글(_CSS_TEMPLATE 뒤 `` `…` ``)의 범위들과, 그 안의 `${…}`(짝 맞는 중괄호)를
    같은 길이의 공백으로 지운 글. 템플릿 글을 앞에서부터 한 번씩 읽는다."""
    spans: list[tuple[int, int]] = []
    holes: list[tuple[int, int]] = []
    pos = 0
    while (m := _CSS_TEMPLATE.search(code, pos)) is not None:
        i, end = m.end(), len(code)
        while (s := _TEMPLATE_STOP.search(code, i)) is not None:
            if s.group(0) == "\\":
                i = s.end() + 1
            elif s.group(0) == "`":
                end = s.start()
                break
            else:
                close = min(_brace_end(code, s.start() + 1, len(code)) + 1, len(code))
                holes.append((s.start(), close))
                i = close
        spans.append((m.end(), end))
        pos = end + 1
    return (_blank(code, holes) if holes else code), spans


def _css_ranges(code: str, suffix: str, templates: list[tuple[int, int]]) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """(선택자를 읽는 범위, CSS 로 읽는 범위 전체). .css·.scss 는 파일 전체다. 그 밖은 `<style>` 블록 안과 CSS 템플릿 글
    (선택자와 선언), 정적 `style="…"` 속성 값(선언만)이고, 둘째 목록은 겹친 범위를 합친 차례 목록이다."""
    if suffix in CSS_SUFFIXES:
        return [(0, len(code))], [(0, len(code))]
    blocks = sorted([m.span(1) for m in _STYLE_BLOCK.finditer(code)] + templates)
    merged: list[tuple[int, int]] = []
    for a, b in sorted(blocks + [m.span(g) for m in _STYLE_ATTR.finditer(code) for g in (1, 2) if m.group(g) is not None]):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return blocks, merged


def _declarations(code: str, css: list[tuple[int, int]]) -> list[tuple[str, int, str]]:
    """transition·transition-property·will-change 선언의 경고 (이름, 위치, 규칙). CSS 범위에서는 선언 머리(범위 처음, `{`·`;`·줄
    처음 뒤. 사이 공백은 된다)이고 CSS 글(`content: 'transition: …'`) 밖일 때만, 값을 `;`·`{`·`}`·줄 끝까지 읽는다. 그 밖(JS
    객체·JSON)은 값이 글 하나일 때만 그 글을 읽는다: 삼항식·함수 호출·이름·`${` 가 든 템플릿 글은 읽지 않는다. JS 문자열 안의
    예시 선언(`"transition: 'all'"` 같은 글)은 가리지 않는다(경고 전용, 리뷰어가 판단한다)."""
    starts = [a for a, _ in css]
    strings = [m.span() for a, b in css for m in _CSS_STRING.finditer(code, a, b)]
    string_starts = [a for a, _ in strings]
    out = []
    for m in _DECL.finditer(code):
        v = m.end()
        i = bisect.bisect_right(starts, m.start()) - 1
        if i >= 0 and m.start() < css[i][1]:
            k = bisect.bisect_right(string_starts, m.start()) - 1
            if k >= 0 and m.start() < strings[k][1]:
                continue
            j = m.start() - 1
            while j >= css[i][0] and code[j] in " \t":
                j -= 1
            if j >= css[i][0] and code[j] not in "{;\r\n":
                continue
            value = _CSS_VALUE.match(code, v, v + VALUE_WINDOW).group(0)
        else:
            lit = _JS_LITERAL.match(code, v)
            if lit is None or not _VALUE_END.match(code, lit.end()) or (lit.group(3) is not None and "${" in lit.group(3)):
                continue
            value = next(g for g in lit.groups() if g is not None)
        if m.group(1).startswith("will"):
            if value.strip() and not _AUTO.match(value):
                out.append(("will-change", m.start(), RULE_WILL_CHANGE))
            continue
        prop = _TRANSITION_PROP.search(value)
        if prop:
            out.append((f"transition {prop.group(1)}", m.start(), RULE_TRANSITION))
    return out


def _invalid_selectors(code: str, blocks: list[tuple[int, int]]) -> list[tuple[str, int, str]]:
    """CSS 선택자(`{` 앞)의 `:invalid`. .css·.scss, `<style>` 블록, CSS 템플릿 글만 본다(JS 문자열
    `querySelectorAll(":invalid")` 는 아니다)."""
    out = []
    for a, b in blocks:
        for seg in _SEGMENT.finditer(code, a, b):
            if seg.group(0).endswith("{"):
                out += [("user- 없는 :invalid", m.start(), RULE_INVALID) for m in _CSS_INVALID.finditer(code, seg.start(), seg.end())]
    return out


def _read_tag(code: str, i: int, limit: int) -> tuple[int, bool]:
    """태그 이름 뒤 i 부터 태그를 닫는 `>` 를 찾는다: (위치, 닫힘). 따옴표 값과 중괄호 값(`{count > 0}`, `{a<b}`) 안은 건너뛰고,
    중괄호 안의 JS 글은 이스케이프(`'it\\'s'`)를 따른다. 중괄호 밖에서 다음 태그의 `<` 를 만나거나 limit 까지 닫히지 않으면
    (멈춘 위치, False)."""
    depth = 0
    while True:
        m = _TAG_STOP.search(code, i, limit)
        if m is None:
            return limit, False
        c, i = m.group(0), m.end()
        if c in "\"'`":
            if depth:
                tail = _QUOTE_TAIL[c].match(code, i, limit)
                if tail is None:
                    return limit, False
                i = tail.end()
            else:
                close = code.find(c, i, limit)
                if close < 0:
                    return limit, False
                i = close + 1
        elif c == "{":
            depth += 1
        elif c == "}":
            depth = max(depth - 1, 0)
        elif c == "<":
            if depth == 0:
                return m.start(), False
        elif depth == 0:
            return m.start(), True


def _attrs(code: str, i: int, end: int) -> list[tuple[str, int, str, int, int]]:
    """태그 이름 뒤 i 부터 end(`>`) 앞까지의 속성 (이름, 이름 위치, 꼴, 값 시작, 값 끝). 꼴은 따옴표 `q`, 중괄호 `b`, 따옴표 없음
    `u`, 값 없음 ``. 펼침(`{...props}`)은 이름 `{` 다. 값 안의 글자는 이름으로 읽지 않는다."""
    out = []
    while True:
        i = _ATTR_GAP.match(code, i, end).end()
        if i >= end:
            return out
        if code[i] == "{":
            close = _brace_end(code, i, end)
            out.append(("{", i, "b", i + 1, close))
            i = close + 1
            continue
        m = _ATTR_NAME.match(code, i, end)
        if m is None:
            i += 1
            continue
        j = _WS.match(code, m.end(), end).end()
        if j < end and code[j] == "=":
            j = _WS.match(code, j + 1, end).end()
            if j < end and code[j] in "\"'`":
                close = code.find(code[j], j + 1, end)
                close = end if close < 0 else close
                out.append((m.group(0), m.start(), "q", j + 1, close))
                i = close + 1
            elif j < end and code[j] == "{":
                close = _brace_end(code, j, end)
                out.append((m.group(0), m.start(), "b", j + 1, close))
                i = close + 1
            else:
                v = _UNQUOTED.match(code, j, end)
                out.append((m.group(0), m.start(), "u", j, v.end()))
                i = max(v.end(), j + 1)
        else:
            out.append((m.group(0), m.start(), "", m.end(), m.end()))
            i = m.end()


def _base(low: str) -> str:
    """Vue 바인딩 머리(`:`·`v-bind:`)를 뗀 속성 이름."""
    return low[1:] if low.startswith(":") else low[7:] if low.startswith("v-bind:") else low


def _js_strings(code: str, a: int, b: int) -> list[tuple[int, int]]:
    """code[a:b] 의 따옴표 글 안쪽 범위들. 앞에서부터 글마다 한 번씩 훑는다(닫히지 않은 글은 그 끝까지 건너뛰고 그 안에서 다시
    찾지 않는다. 이스케이프 따옴표가 많은 깨진 JSX 에서도 선형이다)."""
    out = []
    i = a
    while (m := _STRING_START.search(code, i, b)) is not None:
        rest = _STRING_REST[m.group(0)].match(code, m.end(), b)
        if rest.group(1) is not None:
            out.append((m.end(), rest.end() - 1))
        i = rest.end()
    return out


def _class_hits(code: str, low: str, kind: str, a: int, b: int) -> list[tuple[str, int, str]]:
    """클래스 속성 값의 Tailwind transition·will-change·invalid 변형. 정적 값(`class="…"`)은 값 전체를, JS 식(`className={…}`,
    `:class="…"`, `class:list={…}`)은 그 안의 따옴표 글만 본다(객체 키 `{invalid:true}` 는 클래스가 아니다)."""
    if kind in ("q", "u") and low in ("class", "classname"):
        spans = [(a, b)]
    else:
        spans = _js_strings(code, a, b)
    out = []
    for s, e in spans:
        for m in _TW_TRANSITION.finditer(code, s, e):
            prop = _TRANSITION_PROP.search(m.group(1))
            if prop:
                out.append((f"transition {prop.group(1)}", m.start(), RULE_TRANSITION))
        out += [("will-change", m.start(), RULE_WILL_CHANGE) for m in _TW_WILL_CHANGE.finditer(code, s, e)]
        out += [("user- 없는 :invalid", m.start(), RULE_INVALID) for m in _TW_INVALID.finditer(code, s, e)]
    return out


def _size_missing(attrs: list[tuple[str, int, str, int, int]]) -> bool:
    """`<img>`·`<video>` 에 크기가 없다고 단정할 수 있나: 클래스·style·펼침이 있으면 크기를 알 수 없어 아니다. 아니면
    `width`·`height` 속성 둘 다 없을 때."""
    names = set()
    for name, *_ in attrs:
        low = name.lower()
        if low == "{" or low in _CLASS_NAMES or low.startswith("class:") or low in _STYLE_NAMES:
            return False
        names.add(_base(low))
    return not {"width", "height"} <= names


def _tag_hits(code: str, fold: bool) -> list[tuple[str, int, str]]:
    """태그를 앞에서부터 한 번씩 읽어(_read_tag, SCAN_WINDOW 안, 여러 줄) 속성으로 본다: 한 줄 안에서 닫힌 `<img>`·`<video>`
    의 크기, `<iframe>` 의 `title`, `<div>`·`<span>` 의 클릭 처리기(onClick·onclick·@click), 모든 태그의 `role="button"`·양수
    tabindex·클래스 값. fold 면(.html) 태그 이름의 대소문자를 가리지 않는다. 닫히지 않은 태그는 멈춘 곳부터 다시 찾는다(같은 글을
    두 번 읽지 않는다). JS 문자열 안의 예시 태그도 태그로 읽는다(경고 전용, 리뷰어가 판단한다)."""
    out = []
    pos = 0
    while (m := _TAG_OPEN.search(code, pos)) is not None:
        end, closed = _read_tag(code, m.end(), min(len(code), m.start() + SCAN_WINDOW))
        pos = end + 1 if closed else end
        if not closed:
            continue
        tag, attrs = (m.group(1).lower() if fold else m.group(1)), _attrs(code, m.end(), end)
        if tag in ("img", "video", "iframe") and code.find("\n", m.start(), end) < 0:
            if tag == "iframe":
                if all(a[0] != "{" for a in attrs) and "title" not in {_base(a[0].lower()) for a in attrs}:
                    out.append(("title 없는 <iframe>", m.start(), RULE_IFRAME))
            elif _size_missing(attrs):
                out.append((f"크기 없는 <{tag}>", m.start(), RULE_MEDIA))
        for name, at, kind, a, b in attrs:
            low = name.lower()
            if tag in ("div", "span") and (low == "onclick" or low == "@click" or low.startswith("@click.")):
                out.append((f"클릭 처리기를 단 <{tag}>", at, RULE_CLICK))
            elif ((low == "role" and (kind in ("q", "u") and code[a:b].strip() == "button"
                                      or kind == "b" and _BUTTON.fullmatch(code, a, b)))
                  or (low in (":role", "v-bind:role") and kind == "q" and _BUTTON.fullmatch(code, a, b))):
                out.append(('role="button"', at, RULE_CLICK))
            elif _base(low) == "tabindex" and kind in ("q", "u", "b") and _POSITIVE.fullmatch(code, a, b):
                out.append(("양수 tabindex", at, RULE_TABINDEX))
            elif low in _CLASS_NAMES:
                out += _class_hits(code, low, kind, a, b)
    return out


def _excerpt(text: str, at: int) -> str:
    """at 부터 그 줄 끝까지(EXCERPT_WINDOW 안)의 발췌."""
    end = text.find("\n", at, at + EXCERPT_WINDOW)
    return _short(text[at:end if end >= 0 else at + EXCERPT_WINDOW])


def web_scan(rel: str, text: str) -> list[str]:
    """한 파일의 웹 경고(설계 11.13 의 1 웹)를 줄 순서로 `파일:줄: 이름(발췌) — 규칙`. 주석을 지운 글(strip_comments)을 보고,
    .js·.jsx·.ts·.tsx 는 CSS 템플릿 글의 `${…}` 도 지운다. 줄마다 이름 하나에 경고 하나. `.css` 의 `@import` 는 파일당 한 줄(첫
    줄과 개수)이고 `@import "tailwindcss…"` 는 뺀다(`.scss` 는 Sass 의 가져오기라 보지 않는다). 태그는 .css·.scss·.json 이
    아닌 파일에서만 읽는다."""
    suffix = Path(rel).suffix.lower()
    code = strip_comments(text, line_comments=suffix not in (".css", ".json"))
    templates: list[tuple[int, int]] = []
    if suffix in JS_SUFFIXES:
        code, templates = _css_templates(code)
    blocks, css = _css_ranges(code, suffix, templates)
    hits = _declarations(code, css) + _invalid_selectors(code, blocks)
    if suffix not in CSS_SUFFIXES and suffix != ".json":
        hits += _tag_hits(code, fold=suffix in HTML_SUFFIXES)
    starts = _line_starts(text)
    found: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()
    for name, at, rule in sorted(hits, key=lambda h: h[1]):
        number = bisect.bisect_right(starts, at)
        if (number, name) not in seen:
            seen.add((number, name))
            found.append((number, f"{name}({_excerpt(text, at)}) — {rule}"))
    if suffix == ".css":
        imports = [n for n, line in enumerate(code.split("\n"), 1) if _CSS_IMPORT.match(line) and not _TW_IMPORT.match(line)]
        if imports:
            found.append((imports[0], f"CSS @import {len(imports)}개 — {RULE_IMPORT}"))
    return [f"{rel}:{number}: {what}" for number, what in sorted(found, key=lambda x: x[0])]


def web_findings(root: Path, files: list[str]) -> list[str]:
    """files 가운데 웹 검사 대상(WEB_SUFFIXES, 제외는 design_findings 와 같다)의 웹 경고(상한 없음)."""
    found: list[str] = []
    for rel in files:
        if rel.startswith("../") or Path(rel).suffix.lower() not in WEB_SUFFIXES or matches_any(rel, EXCLUDE):
            continue
        text = read_source(root, rel)
        if text is not None:
            found += web_scan(rel, text)
    return found


def design_lint(root: Path, files: list[str]) -> list[str]:
```

**Edit** `herdr-team/lib/hteam/compose.py`

```python
    """디자인 절의 경고 목록(설계 11.6·11.13): diff 검사(designdiff, 대상 커밋 shas 의 지운 줄·추가한 줄) 먼저, 내용 검사(lint,
    files 는 시도 기록의 바뀐 파일)와 색·글꼴 검사(lint.style_findings) 뒤. 검사마다 guarded 로 따로 감싸고(카탈로그가 깨져도
    다른 검사는 낸다) 합쳐서 MAX_FINDINGS 까지. `hteam lint --task` 의 findings 도 이것이다. 색·글꼴 검사는 프로젝트의
    `.herdr-team/design-rules.md` 가 13단계 판일 때(lint.has_style_rules)만 돈다: 경고가 인용하는 design-rules §1 의 7·11, §3 의
    11 이 옛 규칙 사본에는 없다(upgrade 전 프로젝트, 고친 규칙 사본을 건너뛴 upgrade)."""
    style = (guarded(lambda: lint.style_findings(p.work_root, files))
             if lint.has_style_rules(p.team / "design-rules.md") else [])
    return lint.cap(guarded(lambda: designdiff.design_diff_lint(p.work_root, files, shas))
                    + guarded(lambda: lint.design_findings(p.work_root, files)) + style)
```

```python
    """디자인 절의 경고 목록(설계 11.6·11.13): diff 검사(designdiff, 대상 커밋 shas 의 지운 줄·추가한 줄) 먼저, 그다음 내용 검사
    (lint, files 는 시도 기록의 바뀐 파일), 웹 검사(lint.web_findings), 색·글꼴 검사(lint.style_findings) 차례. 검사마다
    guarded 로 따로 감싸고(카탈로그가 깨져도 다른 검사는 낸다) 합쳐서 MAX_FINDINGS 까지. `hteam lint --task` 의 findings 도
    이것이다. 색·글꼴 검사는 프로젝트의 `.herdr-team/design-rules.md` 가 13단계 판일 때(lint.has_style_rules)만 돈다: 경고가
    인용하는 design-rules §1 의 7·11, §3 의 11 이 옛 규칙 사본에는 없다(upgrade 전 프로젝트, 고친 규칙 사본을 건너뛴 upgrade).
    웹 검사는 프로젝트에 `.herdr-team/web-rules.md` 가 있을 때만 돈다(경고가 인용하는 web-rules 가 upgrade 전 프로젝트에는 없다)."""
    style = (guarded(lambda: lint.style_findings(p.work_root, files))
             if lint.has_style_rules(p.team / "design-rules.md") else [])
    web = guarded(lambda: lint.web_findings(p.work_root, files)) if (p.team / lint.WEB_RULES_FILE).is_file() else []
    return lint.cap(guarded(lambda: designdiff.design_diff_lint(p.work_root, files, shas))
                    + guarded(lambda: lint.design_findings(p.work_root, files)) + web + style)
```

**Edit** `herdr-team/lib/hteam/designdiff.py`

```python
    ("aria-live", _text("aria-live")),
```

```python
    ("aria-live", _text("aria-live")),
    ("aria-expanded", _text("aria-expanded")),  # 13단계 p13d: 토글 상태(web-rules §7 의 10)
    ("aria-pressed", _text("aria-pressed")),
```

**Edit** `herdr-team/lib/hteam/designdiff.py`

```python
    ("htmlFor", _word("htmlFor")),
```

```python
    ("htmlFor", _word("htmlFor")),
    ("<caption", re.compile(r"<caption\b")),  # 13단계 p13d: 표 머리(web-rules §7 의 3)
    # scope 는 표 머리의 값(row·col·rowgroup·colgroup)이 있을 때만 센다(따옴표·따옴표 없음·`{"col"}`). `const scope = view` 는 아니다
    ("scope", re.compile(r"""(?<![\w.$-])scope\s*=\s*(?:\{\s*)?["'`]?(?:row|col)(?:group)?\b""")),
```

- [ ] **Step 4: 규칙 파일의 표기·자동 검사 절, 리뷰 디자인 절, README 를 고친다**

**Edit** `herdr-team/templates/design-rules.md`

```markdown
네이티브 요소가 있으면 ARIA 로 흉내 내지 않는다. [판단]
```

```markdown
네이티브 요소가 있으면 ARIA 로 흉내 내지 않는다. [기계] [판단]
```

**Edit** `herdr-team/templates/design-rules.md`

```markdown
`tabindex` 는 `0` 과 `-1` 만 쓴다. [렌더]
```

```markdown
`tabindex` 는 `0` 과 `-1` 만 쓴다. [기계] [렌더]
```

**Edit** `herdr-team/templates/design-rules.md`

```markdown
`transition-property` 에 바뀌는 속성만 적고 `all` 을 쓰지 않는다. [판단]
```

```markdown
`transition-property` 에 바뀌는 속성만 적고 `all` 을 쓰지 않는다. [기계] [판단]
```

**Edit** `herdr-team/templates/design-rules.md`

```markdown
`keep-all`(§4 의 6), `tabular-nums`(§4 의 8)
```

```markdown
`keep-all`(§4 의 6), `tabular-nums`(§4 의 8), 토글 상태 `aria-expanded`·`aria-pressed`(web-rules §7 의 10), 표 머리 `<caption`·`scope`(web-rules §7 의 3)
```

**Edit** `herdr-team/templates/design-rules.md`

```markdown
(다시 그리면서 동작·시험 연결을 잃었는지 본다)
```

```markdown
(다시 그리면서 동작·시험 연결을 잃었는지 본다)
- 웹: 클릭 처리기(`onClick`·`@click`)를 단 `<div>`·`<span>` 과 `role="button"`(§2 의 1), 양수 `tabindex`(§2 의 3), `transition` 의 `all`(§6 의 3). 아래 줄과 함께 프로젝트에 web-rules.md 가 있을 때만 찾고, Markdown 은 보지 않는다
- web-rules 항목: `transition` 의 `height`·`max-height`·`width`·`top`·`left`(web-rules §5 의 1), CSS 선택자의 `:invalid` 와 클래스 값의 `invalid:` 변형(web-rules §3 의 2), 크기(`width`·`height`) 없는 `<img>`·`<video>`(web-rules §6 의 2), `.css` 의 `@import`(web-rules §6 의 4, 파일당 한 줄), `will-change`(web-rules §6 의 7), `title` 없는 `<iframe>`(web-rules §7 의 9). 주석은 보지 않는다. JS 객체의 값은 글 하나일 때만 읽고, styled-components·emotion 의 CSS 템플릿 글은 CSS 로 읽는다. JS 문자열 안의 예시 태그·선언도 잡는다. `<img>`·`<video>`·`<iframe>` 은 한 줄 안에서 닫힌 태그만 보고, 클래스·style 이 있는 `<img>`·`<video>` 는 크기를 알 수 없어 보지 않는다
```

**Edit** `herdr-team/templates/web-rules.md`

```markdown
처음부터 오류로 보이지 않게). [판단]
```

```markdown
처음부터 오류로 보이지 않게). [기계] [판단]
```

**Edit** `herdr-team/templates/web-rules.md`

```markdown
`interpolate-size: allow-keywords` 나 `<details>` 로 한다. [판단]
```

```markdown
`interpolate-size: allow-keywords` 나 `<details>` 로 한다. [기계] [판단]
```

**Edit** `herdr-team/templates/web-rules.md`

```markdown
`srcset` 에는 `sizes` 를 함께 둔다. [판단]
```

```markdown
`srcset` 에는 `sizes` 를 함께 둔다. [기계] [판단]
```

**Edit** `herdr-team/templates/web-rules.md`

```markdown
Sass 의 가져오기는 괜찮다. [판단]
```

```markdown
Sass 의 가져오기는 괜찮다. [기계] [판단]
```

**Edit** `herdr-team/templates/web-rules.md`

```markdown
늘 켜 두지 않는다. [판단]
```

```markdown
늘 켜 두지 않는다. [기계] [판단]
```

**Edit** `herdr-team/templates/web-rules.md`

```markdown
레이아웃에 표를 쓰지 않는다. [판단]
```

```markdown
레이아웃에 표를 쓰지 않는다. [기계] [판단]
```

**Edit** `herdr-team/templates/web-rules.md`

```markdown
내용을 말하는 `title` 을 둔다. [판단]
```

```markdown
내용을 말하는 `title` 을 둔다. [기계] [판단]
```

**Edit** `herdr-team/templates/web-rules.md`

```markdown
`aria-pressed` 로 상태를 알린다. [판단]
```

```markdown
`aria-pressed` 로 상태를 알린다. [기계] [판단]
```

**Edit** `herdr-team/templates/review-design.md`

```markdown
고정폭 숫자, `div` 로 바뀐 `<button>`·`<a>`
```

```markdown
고정폭 숫자, 표 머리(`<caption>`·`scope`), `div` 로 바뀐 `<button>`·`<a>`
```

**Edit** `herdr-team/templates/review-design.md`

```markdown
이모지·왼쪽 줄 강조·파랑·보라 그라디언트는 바뀐 파일 전체를 보므로 이 태스크가 만든 것인지 diff 로 확인한다):
```

```markdown
이모지·왼쪽 줄 강조·파랑·보라 그라디언트와 웹 경고(`.herdr-team/web-rules.md` 가 있는 프로젝트에만 나오는 "클릭 처리기를 단 <div>"·`role="button"`·"양수 tabindex"·transition·`:invalid`·"크기 없는 <img>"·"title 없는 <iframe>"·"CSS @import"·will-change. 정당한 쓰임(배경 막의 클릭 닫기, 빌드 도구가 합치는 가져오기)이 있다)는 바뀐 파일 전체를 보므로 이 태스크가 만든 것인지 diff 로 확인한다):
```

**Edit** `README.md`

```markdown
diff 의 지운 줄에서 줄어든 접근성·글자 신호, 지운 줄의 보존 신호
```

```markdown
diff 의 지운 줄에서 줄어든 접근성·글자 신호(0.8.0 부터 토글 `aria-expanded`·`aria-pressed`, 표 `<caption>`·`scope` 도), 지운 줄의 보존 신호
```

**Edit** `README.md`

```markdown
과용 기본 색·Tailwind 기본 램프·파랑·남색·보라 주 강조·과용 글꼴(색·글꼴 검사. `.herdr-team/design-rules.md` 가 0.8.0 판인 프로젝트만) 뒤, 합쳐 50건까지.
```

```markdown
웹 검사(클릭 처리기를 단 `<div>`·`<span>`, `role="button"`, 양수 `tabindex`, `transition` 의 `all`·레이아웃 속성, `user-` 없는 `:invalid`, 크기 없는 `<img>`·`<video>`, `title` 없는 `<iframe>`, `.css` 의 `@import`, `will-change`. `.herdr-team/web-rules.md` 가 있는 프로젝트만, Markdown 은 보지 않는다)와 과용 기본 색·Tailwind 기본 램프·파랑·남색·보라 주 강조·과용 글꼴(색·글꼴 검사. `.herdr-team/design-rules.md` 가 0.8.0 판인 프로젝트만) 뒤, 합쳐 50건까지.
```

- [ ] **Step 5: 시험이 통과하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_lint tests.test_designdiff tests.test_review.DesignSectionTest tests.test_review.NoDirectorDesignTest tests.test_rule_refs)`
Expected: PASS — `Ran 95 tests`, `OK`

Run: `(cd herdr-team && python3 -m unittest tests.test_design_docs tests.test_cli.CompileWarningTest tests.test_setup.TemplateContractTest)`(규칙 문서, 정규식 이스케이프 경고, README)
Expected: PASS — `Ran 44 tests`, `OK`

- [ ] **Step 6: 개인 경로를 확인하고 커밋한다**

```bash
python3 -m py_compile herdr-team/lib/hteam/lint.py herdr-team/lib/hteam/compose.py herdr-team/lib/hteam/designdiff.py herdr-team/tests/test_lint.py herdr-team/tests/test_designdiff.py herdr-team/tests/test_review.py
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews'
git add -- herdr-team/lib/hteam/lint.py herdr-team/lib/hteam/compose.py herdr-team/lib/hteam/designdiff.py herdr-team/templates/design-rules.md herdr-team/templates/web-rules.md herdr-team/templates/review-design.md README.md herdr-team/tests/test_lint.py herdr-team/tests/test_designdiff.py herdr-team/tests/test_review.py
git commit -m "feat(herdr-team): 내용 검사의 웹 항목(web-rules 가 있을 때)과 designdiff 지운 줄 신호 aria-expanded·aria-pressed·caption·scope(설계 11.13)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/lib/hteam/lint.py herdr-team/lib/hteam/compose.py herdr-team/lib/hteam/designdiff.py herdr-team/templates/design-rules.md herdr-team/templates/web-rules.md herdr-team/templates/review-design.md README.md herdr-team/tests/test_lint.py herdr-team/tests/test_designdiff.py herdr-team/tests/test_review.py
```

---

### Task 3: README "0.7.2 → 0.8.0" 과 버전(herdr-team 0.8.0, herdr-orch 0.5.1)(설계 15.3 의 13 의 p13d 3, 9.7 의 3)

README 의 플러그인 표와 "이미 세팅한 프로젝트 업그레이드" 에 0.7.2 → 0.8.0 절을 더한다(설계 15.3 의 "README \"0.7.2 → 0.8.0\"" 다섯: 플러그인 둘, upgrade 의 새 규칙 파일 셋과 `moved`·`git diff -- .herdr-team`·함께 커밋, `CLAUDE.md` manual, 관제·메인 다시 열기, 확정한 디자인 시스템은 그대로·배정은 새 director 태스크부터·앞으로 직무 규칙은 project-rules). `CLAUDE.md` 의 바뀐 곳 셋은 이 브랜치의 `CLAUDE.section.md` 변경(재현 시험 줄, project-rules 줄, `unknown_regression` 줄)이다. 버전은 herdr-team 세 곳(`.claude-plugin/marketplace.json`, `herdr-team/.claude-plugin/plugin.json`, `herdr-team/lib/hteam/paths.py`)과 herdr-orch 세 곳(같은 marketplace 항목, `herdr-orch/.claude-plugin/plugin.json`, `herdr-orch/lib/horch/paths.py`)이다. herdr-orch 0.5.1 은 p13a 가 고친 skill 문서 한 문장뿐이라 `HORCH_MIN` 은 0.5.0 그대로다(1장 13단계 결정). 그래서 "`HORCH_MIN` 은 함께 배포하는 herdr-orch 와 같다" 는 시험을 두 값으로 바꾼다.

**Files:**
- Modify: `README.md`(플러그인 표, `#### 0.7.2 → 0.8.0`)
- Modify: `.claude-plugin/marketplace.json`, `herdr-team/.claude-plugin/plugin.json`, `herdr-team/lib/hteam/paths.py`, `herdr-orch/.claude-plugin/plugin.json`, `herdr-orch/lib/horch/paths.py`
- Modify: `herdr-team/tests/test_cli.py`, `herdr-team/tests/test_setup.py`, `herdr-orch/tests/test_cli.py`, `herdr-orch/tests/test_meta.py`

**Interfaces:**
- Consumes: Task 1 의 `web-rules.md`(새 규칙 파일 셋), 이 브랜치의 `CLAUDE.section.md` 변경 셋.
- Produces: `hteam version` 0.8.0, `horch version` 0.5.1.

- [ ] **Step 1: 시험을 먼저 고친다**

**Edit** `herdr-team/tests/test_cli.py`

```python
        self.assertEqual((code, out["ok"], out["version"]), (0, True, "0.7.2"))
```

```python
        self.assertEqual((code, out["ok"], out["version"]), (0, True, "0.8.0"))
```

**Edit** `herdr-team/tests/test_cli.py`

```python
        self.assertEqual({VERSION, plugin["version"], entry["version"]}, {"0.7.2"})
        self.assertEqual(entry["source"], "./herdr-team")
        # hteam 이 받는 가장 낮은 herdr-orch 는 함께 배포하는 herdr-orch 와 같다(12단계: 대리 보고·relay-status, 0.5.0)
        from hteam.horch import HORCH_MIN
        orch = [p for p in market["plugins"] if p["name"] == "herdr-orch"][0]
        self.assertEqual(HORCH_MIN, orch["version"])
```

```python
        self.assertEqual({VERSION, plugin["version"], entry["version"]}, {"0.8.0"})
        self.assertEqual(entry["source"], "./herdr-team")
        # hteam 이 받는 가장 낮은 herdr-orch(12단계: 대리 보고·relay-status, 0.5.0)는 그대로다. 함께 배포하는 herdr-orch 0.5.1 은
        # skill 문서 한 문장만 바꿨다(설계 9.7 의 3, 13단계)
        from hteam.horch import HORCH_MIN
        orch = [p for p in market["plugins"] if p["name"] == "herdr-orch"][0]
        self.assertEqual((HORCH_MIN, orch["version"]), ("0.5.0", "0.5.1"))
```

**Edit** `herdr-team/tests/test_setup.py`

```python
        self.assertEqual(json.loads(out.stdout)["version"], "0.7.2")
```

```python
        self.assertEqual(json.loads(out.stdout)["version"], "0.8.0")
```

**Edit** `herdr-team/tests/test_setup.py`

```python
                       "도는 임시 워커는 끝날 때까지 그대로다", "herdr-orch 만 쓰는 프로젝트"):
            self.assertIn(needle, p12)
```

```python
                       "도는 임시 워커는 끝날 때까지 그대로다", "herdr-orch 만 쓰는 프로젝트"):
            self.assertIn(needle, p12)
        # 13단계(0.8.0): 플러그인 둘(herdr-orch 0.5.1 은 문서만), upgrade 의 새 규칙 파일 셋·moved·project-rules 와 함께 커밋,
        # CLAUDE.md 세 곳, 관제·메인 다시 열기, 확정한 디자인 시스템은 그대로(설계 15.3 의 13 README "0.7.2 → 0.8.0")
        self.assertLess(readme.index("#### 0.7.2 → 0.8.0"), readme.index("#### 0.7.1 → 0.7.2"))
        p13 = readme[readme.index("#### 0.7.2 → 0.8.0"):readme.index("#### 0.7.1 → 0.7.2")]
        for needle in ("herdr-orch 도 0.5.1 로 올린다", "`claude plugin update herdr-orch@herdr-team`",
                       "`.herdr-team/palette.md`", "`.herdr-team/fonts-ko.md`", "`.herdr-team/web-rules.md`", "`moved`",
                       "`.herdr-team/project-rules/<직무>.md`", "`git diff -- .herdr-team`",
                       "직무 문서와 project-rules 를 함께 경로를 지정해 커밋한다", "`manual` 에 `CLAUDE.md` 가 나온다",
                       "바뀐 곳은 셋이다", "`- 재현 시험:`", "`unknown_regression`", "관제를 끈다",
                       "같은 터미널에서 메인 세션을 새로 열고", "`…/herdr-team/0.8.0/bin/hteam`", "이미 확정한 디자인 시스템",
                       "새 director 태스크", "herdr-orch 만 쓰는 프로젝트"):
            self.assertIn(needle, p13)
        self.assertIn("| `herdr-team` | 0.8.0 |", readme)
        self.assertIn("| `herdr-orch` | 0.5.1 |", readme)
```

**Edit** `herdr-orch/tests/test_cli.py`

```python
        self.assertEqual(out, {"ok": True, "version": "0.5.0"})
```

```python
        self.assertEqual(out, {"ok": True, "version": "0.5.1"})
```

**Edit** `herdr-orch/tests/test_meta.py`

```python
        self.assertEqual(VERSION, "0.5.0")  # Claude 상태 대리 보고와 백그라운드 일(herdr-orch 설계 16장)
```

```python
        self.assertEqual(VERSION, "0.5.1")  # 0.5.1: skill 문서 한 문장(herdr-team 설계 9.7 의 3). 대리 보고·백그라운드 일은 0.5.0
```

- [ ] **Step 2: 시험이 실패하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_cli tests.test_setup.ScaffoldTest tests.test_setup.TemplateContractTest)`
Expected: FAIL — `Ran 25 tests`, `FAILED (failures=3, errors=1)`(version 둘, shim, README 의 0.7.2 → 0.8.0 절)

Run: `(cd herdr-orch && python3 -m unittest tests.test_cli tests.test_meta)`
Expected: FAIL — `Ran 18 tests`, `FAILED (failures=2)`

- [ ] **Step 3: 버전과 README 를 고친다**

**Edit** `.claude-plugin/marketplace.json`

```json
      "version": "0.5.0",
```

```json
      "version": "0.5.1",
```

**Edit** `.claude-plugin/marketplace.json`

```json
      "version": "0.7.2",
```

```json
      "version": "0.8.0",
```

**Edit** `herdr-team/.claude-plugin/plugin.json`

```json
  "version": "0.7.2",
```

```json
  "version": "0.8.0",
```

**Edit** `herdr-team/lib/hteam/paths.py`

```python
VERSION = "0.7.2"
```

```python
VERSION = "0.8.0"
```

**Edit** `herdr-orch/.claude-plugin/plugin.json`

```json
  "version": "0.5.0",
```

```json
  "version": "0.5.1",
```

**Edit** `herdr-orch/lib/horch/paths.py`

```python
VERSION = "0.5.0"
```

```python
VERSION = "0.5.1"
```

**Edit** `README.md`

```markdown
| `herdr-orch` | 0.5.0 |
```

```markdown
| `herdr-orch` | 0.5.1 |
```

**Edit** `README.md`

```markdown
| `herdr-team` | 0.7.2 |
```

```markdown
| `herdr-team` | 0.8.0 |
```

**Edit** `README.md`

```markdown
#### 0.7.1 → 0.7.2

```

```markdown
#### 0.7.2 → 0.8.0

herdr-orch 도 0.5.1 로 올린다(skill 문서의 감독 메인 대리 보고 한 문장만 바뀌었다. hteam 이 받는 가장 낮은 herdr-orch 는 0.5.0 그대로라 올리지 않아도 hteam 은 돈다). herdr-team 은 품질 보완이다: 디렉터의 팔레트 배정(`hteam palette deal`)과 새 규칙 파일 셋(`palette.md`·`fonts-ko.md`·`web-rules.md`), design-rules·text-rules 보강, 리뷰의 검사 약화 의심·보고서 소절 사전 검사·재현 시험, 색·글꼴·웹 자동 검사, 직무 문서와 따로 두는 프로젝트 규칙(`.herdr-team/project-rules/<직무>.md`). 순서는 0.5.0 → 0.6.0 과 같다. 2 는 메인 세션에 맡겨도 되고, 3–5 는 프로젝트를 쓰는 사람이 직접 한다(이유는 0.5.0 → 0.6.0 과 같다).

1. 플러그인 둘을 올린다(`claude plugin marketplace update herdr-team`, `claude plugin update herdr-orch@herdr-team`, `claude plugin update herdr-team@herdr-team`).
2. 프로젝트 루트에서 `.herdr-team/bin/hteam upgrade` 를 실행한다.
   - `created` 에 새 규칙 파일 셋(`.herdr-team/palette.md`·`.herdr-team/fonts-ko.md`·`.herdr-team/web-rules.md`)이, `updated` 에 바뀐 규칙 파일(`design-rules.md`·`text-rules.md`)과 직무 문서 다섯이 나온다.
   - 직무 문서에 직접 더한 절(지금 템플릿에 없는 `## ` 제목의 절. 예: `## 이 프로젝트 규칙`)은 지우지 않고 `moved` 에 적힌 대로 `.herdr-team/project-rules/<직무>.md` 로 옮긴다. 그 파일은 그 직무 워커의 사양에 직무 문서 뒤로 붙는다. project-rules 파일에 커밋 안 된 변경이 있으면 그 직무 문서는 `skipped` 다(확인해 커밋한 뒤 다시 한다). 템플릿 제목 절 안에 더한 줄은 옮기지 않고 템플릿으로 덮인다(필요하면 git 에서 꺼내 project-rules 에 옮긴다).
   - `git diff -- .herdr-team` 으로 바뀐 것을 확인하고, 직무 문서와 project-rules 를 함께 경로를 지정해 커밋한다(`git add -- .herdr-team && git commit -m "chore: herdr-team 0.8.0" -- .herdr-team`).
   - `manual` 에 `CLAUDE.md` 가 나온다. `<!-- herdr-team -->` 절을 `herdr-team/templates/CLAUDE.section.md` 와 견줘 고친다. 바뀐 곳은 셋이다.
     - 메인 규칙의 새 줄("작업 공간 태스크가 기준 브랜치의 새 커밋" 줄 뒤): 버그·회귀를 고치는 태스크의 `## Constraints` 에 `- 재현 시험:` 줄을 넣는다.
     - 메인 규칙의 새 줄("플러그인을 올린 뒤" 줄 뒤): 이 프로젝트에 맞는 직무 규칙은 직무 문서가 아니라 `.herdr-team/project-rules/<직무>.md` 에 쓴다.
     - decide 처리 기준의 `unknown_regression` 줄: Constraints 에 재현 시험 줄을 넣는다.
   - 바꾼 파일을 경로를 지정해 커밋한다(`git add -- CLAUDE.md && git commit -m "chore: herdr-team 0.8.0" -- CLAUDE.md`).
3. 지금 메인 세션을 끝낸다(`/exit`).
4. 관제를 끈다(0.5.0 → 0.6.0 의 4). 리뷰(사전 검사·자동 검사)와 워커 띄우기는 관제 쪽이고, 관제와 그 자식은 관제가 뜰 때의 플러그인 경로로 돈다.
5. 같은 터미널에서 메인 세션을 새로 열고 메시지를 하나 보낸다. 새 세션의 훅이 관제를 0.8.0 으로 다시 띄운다. 관제가 뜨지 않으면 `/herdr-team:up` 을 실행한다. 메인 규칙(2 의 `CLAUDE.md`)은 세션을 시작할 때 읽힌다. 메인 대리 보고 설정은 0.7.2 에서 했으므로 할 일이 없다.
6. 확인한다: `.herdr-team/bin/hteam version` 이 `0.8.0` 이고, `hc get <관제 터미널>` 의 `argv` 가 `…/herdr-team/0.8.0/bin/hteam` 이다.

올린 뒤 달라지는 것:

- 이미 확정한 디자인 시스템(`docs/design/system/`)과 화면 시안은 바뀌지 않는다. 팔레트 배정은 새 director 태스크(와 그 방향 전환)부터다. 확정한 시스템이 과용 색·글꼴을 쓰면 그 파일을 바꾸는 태스크의 리뷰에 색·글꼴 경고가 나올 수 있다: 근거(브랜드 자산, 사용자 선택)를 `### 디자인 점검` 에 적으면 리뷰어가 지적하지 않는다.
- 앞으로 이 프로젝트에 맞는 직무 규칙을 더할 때는 직무 문서가 아니라 `.herdr-team/project-rules/<직무>.md` 에 쓴다(직무 문서는 upgrade 가 템플릿으로 바꾼다).
- 리뷰 전에 hteam 이 보고서 이번 라운드 절의 소절(`### 문구 점검`·`### 디자인 점검`·`### 재현 시험`)을 보고, 그 태스크에 필요한 소절이 없으면 리뷰어 없이 돌려보낸다(수정 라운드도 그 라운드 절에 다시 둔다).
- 도는 워커는 끝날 때까지 옛 사양 그대로다. 작업 규칙 7번(검사 약화 금지)과 project-rules 는 다음에 띄우는 워커 사양부터다.
- herdr-team 없이 herdr-orch 만 쓰는 프로젝트는 0.5.1 로 올려도 바뀌는 동작이 없다(문서만).

#### 0.7.1 → 0.7.2

```

- [ ] **Step 4: 시험이 통과하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_cli tests.test_setup.ScaffoldTest tests.test_setup.TemplateContractTest)`
Expected: PASS — `Ran 25 tests`, `OK`

Run: `(cd herdr-orch && python3 -m unittest tests.test_cli tests.test_meta)`
Expected: PASS — `Ran 18 tests`, `OK`

- [ ] **Step 5: 개인 경로를 확인하고 커밋한다**

```bash
python3 -m py_compile herdr-team/lib/hteam/paths.py herdr-orch/lib/horch/paths.py herdr-team/tests/test_cli.py herdr-team/tests/test_setup.py herdr-orch/tests/test_cli.py herdr-orch/tests/test_meta.py
python3 -m json.tool .claude-plugin/marketplace.json >/dev/null && python3 -m json.tool herdr-team/.claude-plugin/plugin.json >/dev/null && python3 -m json.tool herdr-orch/.claude-plugin/plugin.json >/dev/null
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews'
git add -- README.md .claude-plugin/marketplace.json herdr-team/.claude-plugin/plugin.json herdr-team/lib/hteam/paths.py herdr-orch/.claude-plugin/plugin.json herdr-orch/lib/horch/paths.py herdr-team/tests/test_cli.py herdr-team/tests/test_setup.py herdr-orch/tests/test_cli.py herdr-orch/tests/test_meta.py
git commit -m "docs: README 0.7.2 → 0.8.0, 버전 herdr-team 0.8.0·herdr-orch 0.5.1(설계 15.3 의 13, 9.7 의 3)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- README.md .claude-plugin/marketplace.json herdr-team/.claude-plugin/plugin.json herdr-team/lib/hteam/paths.py herdr-orch/.claude-plugin/plugin.json herdr-orch/lib/horch/paths.py herdr-team/tests/test_cli.py herdr-team/tests/test_setup.py herdr-orch/tests/test_cli.py herdr-orch/tests/test_meta.py
```

---

## p13d 끝

- [ ] **전체 시험.** `bash herdr-team/tests/run.sh` 를 돌린 뒤 `bash herdr-orch/tests/run.sh` 를 돌린다(동시에 돌리지 않는다). 실패하면 원인 태스크로 돌아가 고치고 그 태스크의 시험과 전체 시험을 다시 돌린다.
- [ ] **설계 13장.** "13단계(품질 보완) 한계" 에 아래 알려진 한계 가운데 리뷰를 거쳐 남은 것을 더한다. 같은 절의 "검사 방식 표기 시험(11.9)은 design-rules 안 `## 자동 검사` 절이 `§N 의 M` 으로 적은 항목만 본다. p13d 의 `web-rules.md` 가 다른 파일의 항목을 가리키면 그 시험을 넓힌다." 는 넓힌 뒤의 사실(주어진 규칙 파일들의 자동 검사 절 인용을 같은 줄 앞의 규칙 파일 이름으로 가른다)로 바꾼다. 15.3 의 13 에서 p13d 가 끝났음을 적는다. 커밋은 경로 지정(`git commit -m "docs: p13d 알려진 한계(설계 13장)" -- docs/superpowers/specs/2026-11-05-herdr-team-design.md`).
- [ ] **브랜치 최종 리뷰.** p13a–p13d 전체(main..HEAD)를 컨트롤러가 리뷰한 뒤 `scripts/codex-review.sh base main` 을 Herdr pane 에서 돌리고 `hc wait <주소> --timeout 3600` 을 백그라운드로 건다(결과 `.codex-reviews/base-herdr-team-p13.md`). 지적은 항목마다 코드로 확인하고 P0·P1, 기본 경로의 P2, 회귀만 고친다(가장자리는 알려진 한계). P0·P1 이 남으면 고치고 다시 돌린다(3 라운드까지, 그 뒤는 사용자에게 묻는다).
- [ ] **실환경 확인(설계 15.2 의 13단계 1–6).** 1 획일도 측정(15.5)의 결과 확인, 2 0.7.2 로 세팅한 시험 프로젝트의 upgrade 옮기기(`moved`, project-rules, 직무 문서가 템플릿과 같음, 띄운 developer 워커 사양에 절이 붙음, 새 규칙 파일 셋 `palette.md`·`fonts-ko.md`·`web-rules.md` 가 `created`), 3 director 태스크 한 번(배정 출력, `## 팔레트 배정`, 시안 표, `palette_source:`, `design_systems: false`, 리뷰 디자인 절의 새 lint 경고. 웹 시안이면 웹 경고도 본다), 4 재현 시험 태스크, 5 메인 훅의 heredoc, 6 회귀(전체 시험 둘, 따로). 결과는 설계 15.4 에 적는다. 시험 폴더는 스크래치패드의 빈 폴더이고 저장소의 두 플러그인(`--plugin-dir`)으로 띄운다.
- [ ] **병합과 안내.** main 병합, 사용 프로젝트 안내(README "0.7.2 → 0.8.0")는 브랜치 최종 리뷰와 실환경 확인을 마친 뒤 사용자에게 확인받고 한 번에 한다(1장 13단계 "나누기").

## 알려진 한계(설계 13장에 더할 후보)

- 웹 검사(11.13 의 1 웹)는 경고이고 정규식과 작은 태그 읽기다. JS 문자열은 일반적으로 가르지 않는다: JS 문자열 안의 예시 태그·선언(`const example = '<img src=x>'`, `"transition: all"` 를 값으로 둔 객체 키)은 검사한다(경고 전용, 리뷰어 판단. Codex 계획 리뷰 r2 의 결정). 주석 지우기도 따옴표 글을 가리지 않는다: 글 안의 `/*`(`"src/**/*.ts"`)는 다음 `*/` 까지 지워 그 사이를 보지 않고(놓치는 쪽), `//` 는 줄의 첫 글자일 때만 주석이라 코드 뒤에 붙은 끝 주석(`x(); // <img src=a>`)은 검사한다. CSS 글(`content: 'transition: all'`)은 CSS 범위에서만 가린다.
- 태그 읽기: 태그 머리 바로 앞이 ASCII 낱말 글자·`$`·`.`·`)`·`]` 면 태그가 아니다(`a<b`·`useState<boolean>` 을 거르려는 것이라 `Total<span onClick>` 처럼 영문 글자에 붙은 태그도 보지 않는다. 한글 글자 뒤는 본다). 태그는 앞에서부터 한 번씩 읽으므로 앞 태그의 중괄호 값 안에 든 태그(`onClick={() => <span …/>}`)는 보지 않는다. SCAN_WINDOW(4000자) 안에서 닫히지 않은 태그는 그 창 안의 다음 태그를 보지 않는다(선형을 지키는 대가). 태그 읽기는 JS 정규식 리터럴을 가르지 않는다: 속성 값 안의 정규식에 `{`·따옴표가 있으면(`<p title={x.replace(/{/g, "")} />`) 중괄호 깊이·글 끝을 잘못 세어 그 태그가 닫히지 않은 것으로 읽히고, 그 뒤 4000자 안의 태그(클릭 처리기를 단 `<div>`, 크기 없는 `<img>`)를 보지 않는다(Codex 계획 리뷰 r3, 놓치는 쪽). 속성 값의 따옴표(중괄호 밖)는 HTML 처럼 이스케이프 없이 읽는다. 대소문자: `.html` 은 태그 이름을 가리지 않고(`.htm` 은 11.6 대로 대상이 아니다), 그 밖의 파일은 소문자 태그만 네이티브로 본다(`<Image>`·`<Img>` 같은 컴포넌트는 보지 않는다).
- `<img>`·`<video>`·`<iframe>` 은 한 줄 안에서 닫힌 태그만 본다(설계 그대로. Prettier 로 나뉜 태그는 놓친다). `<img>`·`<video>` 에 클래스·style·펼침 속성이 있으면 크기를 알 수 없다고 보고 경고하지 않는다: 크기를 정하지 않는 클래스(`class="rounded"`)만 단 그림도 놓친다(Codex 계획 리뷰 r1 의 결정. 거짓 경고보다 놓침을 고른 것이다). `<iframe>` 은 `title`·`:title` 만 이름으로 친다(`aria-label` 은 설계·web-rules 대로 대신하지 않는다).
- 클릭 처리기는 `onClick`·`onclick`·`@click`(`@click.stop` 등)만 본다(`v-on:click`, Svelte `on:click`, Angular `(click)` 은 보지 않는다). 배경 막의 클릭 닫기나 `stopPropagation` 만 하는 처리기처럼 정당한 쓰임도 경고한다.
- 선언(`transition`·`transition-property`·`will-change`)은 CSS 범위(.css·.scss, `<style>` 블록, CSS 템플릿 글, 정적 `style="…"`)에서만 따옴표 없는 값을 읽고, 선언 머리(범위 처음, `{`·`;`·줄 처음 뒤)일 때만 본다. CSS 템플릿 글은 .js·.jsx·.ts·.tsx 에서 `css`·`keyframes`·`createGlobalStyle`·`injectGlobal`·`styled.<태그>`·`styled(<X>)`(`.attrs(…)` 한 번, 괄호 한 겹까지) 바로 뒤의 템플릿만이다: 다른 이름(`tw`, `styled.div.withConfig(…)`), .vue·.svelte 의 `<script>` 안 템플릿, `${…}` 안에 다시 백틱 템플릿이 든 CSS 는 놓치거나 범위가 일찍 끝난다. `${…}` 를 지운 값은 남은 낱말만 본다(`transition: ${speed}` 는 보지 않는다). JS 범위는 글 하나인 값만 읽으므로 `theme.transitions.create('width')`, 삼항식, 이름, `${` 가 든 템플릿 글은 놓친다. `-webkit-transition` 과 `el.style.transition = …` 대입은 보지 않는다. Tailwind `transition-all` 등은 클래스 속성 값에서만 본다(클래스 속성 밖의 `cn("transition-all")` 변수는 놓친다). 클래스 값은 토큰·대괄호 문맥을 가르지 않으므로 `before:content-['transition-all']`·`after:content-['will-change-transform']` 처럼 글을 만드는 값 안의 유틸리티 이름도 유틸리티로 읽어 경고한다(Codex 계획 리뷰 r3, 거짓 경고 쪽. 판단은 리뷰어).
- `:invalid` 는 CSS 선택자(.css·.scss·`<style>`·CSS 템플릿 글의 `{` 앞)와 클래스 속성 값의 `invalid:`·`peer-invalid:`·`group-invalid:` 만 본다. `group-invalid/이름:` 과 선택자 안 속성 값 글(`[title=":invalid"] {`)의 모양은 놓치거나 잡는다.
- 양수 `tabindex` 와 `role="button"` 은 태그 속성만 본다(`el.tabIndex = 2`, `setAttribute('role', 'button')` 은 보지 않는다). Vue `:role`·`v-bind:role` 은 값이 `'button'` 글일 때만이다.
- `@import` 는 주석을 지운 `.css` 줄의 머리만 본다(`<style>` 안은 보지 않는다). `@import "tailwindcss…"` 만 빼고 빌드 도구가 합치는 가져오기도 경고한다(판단은 리뷰어, web-rules §6 의 4 가 괜찮다고 적는다).
- 웹 검사는 프로젝트에 `.herdr-team/web-rules.md` 가 있을 때만 돈다(upgrade 전 프로젝트, web-rules.md 를 지운 프로젝트에는 웹 경고가 없다). Markdown(`.md`)은 보지 않는다(설계 11.13 의 "대상 확장자는 11.6 그대로" 에서 뺐다: README 배지 `<img>`, 규칙을 옮긴 설명 글). 50건 상한에서 웹 경고는 내용 검사 뒤, 색·글꼴 경고 앞이다(색·글꼴이 먼저 잘린다).
- 지운 줄 신호 `scope` 는 diff 줄마다 센다(지운 줄은 태그 조각이라 태그 읽기를 쓰지 않았다). 표 머리 값(`row`·`col`·`rowgroup`·`colgroup`)이 같은 줄에 붙은 것만 세므로 `const scope = view` 는 신호가 아니지만 `const scope = "col"` 은 센다. 이름·`=`·값 사이를 줄로 나눈 꼴(`<th scope\n="col">`, `<th scope=\n"col">`)과 바인딩 값(`:scope="kind"`)은 세지 않아, `<th scope="col">` 을 그렇게 정리하면 표 머리 신호가 줄었다고 경고한다(diff 의 이웃 줄을 함께 보지 않는다. Codex 계획 리뷰 r2·r3, 거짓 경고 쪽). `aria-expanded`·`aria-pressed` 는 글자 그대로 세어 `ariaExpanded` 같은 다른 꼴은 보지 않는다.
- 검사 방식 표기 시험은 주어진 규칙 파일들(design-rules·web-rules)의 `## 자동 검사` 절 인용을 같은 줄 앞의 마지막 규칙 파일 이름으로 가른다. 한 줄에 `web-rules §5 의 1, §2 의 1` 처럼 쓰면 뒤 인용도 web-rules 로 본다(규칙 참조 시험과 같은 가장자리. design-rules 자동 검사 절은 design-rules 인용을 줄 앞에 둔다).
- tester 의 키보드 시나리오와 `lighthouse_audit` 결과는 직무 문서의 규칙이다. hteam 이 QA 보고서에 있는지 검사하지 않는다(리뷰어가 본다).
