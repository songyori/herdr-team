# herdr-team 13단계 p13c(코드 품질·문구) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 설계 15.3 의 13 가운데 p13c 를 만든다. 워커가 검사를 약하게 만들어 통과시키지 않게 하고(작업 규칙 7번, 리뷰의 `## 검사 약화 의심` 절과 P1 정의), 버그·회귀 수정은 실패하는 시험부터 쓰게 하고(재현 시험 표시 줄), 리뷰가 P2 로 뒤늦게 잡던 보고서 소절 누락을 hteam 이 리뷰어 없이 돌려보내고(사전 검사 셋), 기획 단계에서 큰 태스크와 빠진 voice.md 를 알리고(plan check 경고), 문구 규칙·검사·작성자 점검표를 보강한다(11.14).

**Architecture:** (1) 재현 시험 태스크는 사양 `## Constraints` 의 표시 줄(줄 머리 `- 재현 시험:`)로 가른다. 관제의 회귀 수정 사양이 그 줄을 넣고(`create_task(repro=True)`), 메인·기획자는 규칙대로 손으로 넣는다. 판정은 `specs.repro_task` 하나다. (2) 검사 약화 의심은 새 모듈 `lib/hteam/guardlint.py` 다. 문구 검사처럼 "지금 파일에서 내용이 대상 커밋의 추가한 줄에 있는 줄" 을 보고, 시험 파일은 `gitio.diff_lines` 의 지운 줄·추가한 줄로 지운 시험과 단언 수를 센다. 리뷰 프롬프트와 `hteam lint --task` 가 같은 `compose.guard_findings` 를 쓴다(`guarded` 로 감싼 경고). (3) 보고서 소절 사전 검사는 `review.prechecks` 끝에 붙는다. 보고서 이번 라운드 절을 펜스 코드 블록을 따라가며 읽는다(사양 절 읽기와 같은 `specs.code_lines`). (4) `plan check` 는 막지 않는 `warnings` 를 더 낸다. (5) textlint 는 줄 원문과 같은 길이의 "검사할 글" 을 만들어(사람 글 표시는 공백으로 지운다) 발췌가 일치 위치를 쓰고, 파일 단위 반복 집계와 파일들 전체의 복붙·라벨 혼용을 더한다. 모두 경고이고 자동 불합격은 사전 검사 셋뿐이다.

**Tech Stack:** Python 3.11+ 표준 라이브러리(re, fnmatch, pathlib, unittest). git(시험은 임시 저장소). Herdr·Claude·Codex 를 부르지 않는다.

**설계 문서:** `docs/superpowers/specs/2026-11-05-herdr-team-design.md`(이하 "설계"). 범위는 15.3 의 13 의 p13c(1–5)다. 함께 볼 절: 1장 13단계 결정·확인한 것, 5.11 의 2–5(1 은 p13a 에서 했다), 6.6 의 1–4, 7.7(메인 규칙), 8.4(관제의 회귀 수정), 11.7(textlint·`gitio.diff_lines`), 11.9(규칙 참조 시험), 11.14, 13장 "13단계(품질 보완) 한계", 15.1 13단계(검사 약화 의심·리뷰 프롬프트·사전 검사·회귀 수정 사양·plan check 경고·textlint 추가). **p13d 로 미룬 것:** `web-rules.md` 와 웹 플랫폼 항목, README "0.7.2 → 0.8.0" 절과 버전(이 계획의 README 줄은 새 출력·새 검사를 설명하는 줄만이다).

**코드가 기준이다.** 수정은 모두 브랜치 `herdr-team-p13` 의 지금 HEAD(550cc73, p13b 끝)에 대한 부분 수정이다. 새 모듈은 `herdr-team/lib/hteam/guardlint.py`, 새 시험 파일은 `herdr-team/tests/test_quality.py`(Task 1 이 만들고 Task 4·5 가 더한다)·`herdr-team/tests/test_guardlint.py` 다. 직무 문서에는 `## 재현 시험`(developer) 제목 하나만 더하고 기존 `## ` 제목은 바꾸지 않는다(`RETIRED_HEADINGS` 는 그대로다).

**편집 표기:** `**Edit** \`경로\`` 다음 두 코드 블록은 "찾을 내용"과 "바꿀 내용"이다. 찾을 내용은 적용하는 그 시점의 파일에서 정확히 한 번 나오는 부분 문자열이다(블록 끝 개행은 넣지 않는다). 태스크 순서대로, 태스크 안에서는 적힌 순서대로 적용한다(Task 3 의 README 편집은 Task 2 가 더한 줄을 찾는다). 새 파일은 `**Create** \`경로\`` 다음 블록 하나다. 블록 안에 ``` 가 있으면 바깥 울타리를 더 길게 썼다.

## Global Constraints

- Python 3.11 이상, 표준 라이브러리만. 커밋 전에 바꾼 `.py` 를 `python3 -m py_compile` 로 확인한다.
- 13단계 값(그대로 쓴다):
  - 재현 시험 표시 줄: `- 재현 시험: 고치기 전에 실패하는 시험을 먼저 쓴다(보고서 ### 재현 시험)`. 판정은 `## Constraints` 에 줄 머리(앞 공백 뒤)가 `- 재현 시험:` 인 줄이 있는지다. 넣는 곳은 관제의 회귀 수정 사양(기본 줄 다음 줄), 메인이 만드는 버그·회귀 수정 태스크, planner 가 쓰는 버그 수정 태스크다. 묶음 정리 태스크와 수정 라운드에는 넣지 않는다.
  - 작업 규칙 7번은 설계 5.11 의 2 원문 그대로다. tester.md 의 같은 뜻 한 줄은 그대로 둔다.
  - 사전 검사 글: `보고서 r<N> 절에 ### <제목> 이 없다(<까닭>)`. 까닭은 `문구 대상 파일에 한글 줄을 더했다: <파일들>`, `<직무> 태스크다`, `화면 파일을 바꿨다: <파일들>`, `사양 Constraints 가 재현 시험을 요구한다`(파일은 3개까지, 넘으면 ` 외 N개`). developer 의 화면 파일은 `.html .htm .css .scss .jsx .tsx .vue .svelte` 다.
  - 검사 약화 의심 출력: `<파일>:<줄>: <억제 주석|시험 건너뛰기|빈 catch> "<일치>"(<줄 60자>)`, `<파일>: 시험 파일을 지웠다`, `<파일>: 지운 시험 N개(<이름 5개까지>) — 같은 이름을 추가한 줄이 없다`, `<파일>: @Test 표시 N개 지움, M개 더함`, `<파일>: 단언 N개 지움, M개 더함`. 빈 catch 는 추가한 한 줄 `catch (…) {}`·`except …: pass` 와, 머리나 `pass` 줄 가운데 하나라도 추가한 줄인 빈 except 블록(그대로 둔 머리 아래 본문만 `pass` 로 바꾼 것 포함, 머리 줄 번호로 낸다)이다. 50건 상한(`… 외 N건`). 리뷰 프롬프트 절 제목 `## 검사 약화 의심`, 찾은 것이 없으면 절이 없다.
  - plan check 경고: `<key>: 태스크가 크다(acceptance N개, 제목에 '및'). 둘로 나눌지 본다`(까닭은 있는 것만 `, ` 로 잇는다), `docs/planning/voice.md 가 없다. 서비스 문구가 있으면 문구 기준을 쓴다`(늘 작업 루트의 `docs/planning/voice.md` 를 본다. `--file` 과 상관없다). 크기 기준은 developer 태스크의 acceptance 6개 이상 또는 제목의 "및"·"그리고"다.
  - textlint: Markdown 의 코드 블록은 `specs.code_lines(…, any_indent=True)` 로 가른다(펜스 문자와 길이를 따른다. Task 3), 발췌는 일치 위치 앞뒤 30자(잘린 쪽에 `…`), 사람 글 표시는 `.html .jsx .tsx .vue .svelte` 에서 속성 이름이 정확히 `data-sample` 인 요소의 내용(여는 태그를 속성 단위로 읽어 따옴표·중괄호 값 안의 글자는 이름으로 보지 않는다. 빈 요소 `area br col embed hr img input link meta source track wbr` 와 스스로 닫는 태그는 건너뛴다), 반복 문턱은 "아니라" 2·"을 통해·를 통해" 3·"에 대해" 3·"것이다·것입니다" 3, 복붙은 10자 이상 문장이 5번 이상, 라벨은 10자 이하. 새 범주 `상용구 오류`·`2인칭`, 낱말은 설계 11.14 의 2 그대로. 문장 찾기와 종결 낱말 찾기는 줄 길이에 비례해야 한다(마침표 없는 글자 20만 줄과 1 MB 파일이 각각 1.5초 안). 사람 글 표시도 같다: 닫는 태그 위치를 이름마다 한 번 모아 이분 탐색한다(빈 `data-sample` 요소 25,000개, 닫히지 않은 `<div data-sample>` 25,000개가 각각 1.5초 안).
- 바꾸지 않는 것: `plan apply`, design-rules·`lint.design_findings`·`lint.style_findings`·designdiff, 직무 문서의 기존 `## ` 제목, tester.md, AGENTS.section.md, herdr-orch 코드와 버전(버전은 p13d).
- 문서·메시지·주석은 한국어. 명령·코드 식별자·들여온 원문은 원문.
- 저장소는 공개돼 있다. 커밋 전에 `git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews'` 가 아무것도 찾지 않아야 한다.
- 작업 브랜치 `herdr-team-p13` 에서 한다. main 에 직접 커밋하지 않는다. 커밋은 늘 경로 지정, 메시지 끝에 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- 테스트: 모듈(이나 클래스)을 `(cd herdr-team && python3 -m unittest tests.test_a tests.test_b)` 로 고른다. 태스크 안에서 전체 시험(`bash herdr-team/tests/run.sh`, 약 22분)을 돌리지 않는다(p13c 끝에 한 번).
- **Codex 교차 검증(CLAUDE.md):** 이 계획은 실행 전에 `scripts/codex-review.sh doc` 로 검토받는다. 각 태스크의 마지막 단계는 커밋이다. 구현 워커는 `scripts/codex-review.sh` 를 돌리지 않는다. 관제(컨트롤러)가 커밋마다 `scripts/codex-review.sh commit <sha>` 를 돌리고 끝 알림을 백그라운드로 받는다(`R=.codex-reviews; end=$(( $(date +%s) + 3600 )); until [ -f $R/commit-<sha7>.exit ] || [ $(date +%s) -gt $end ]; do hc wait <주소> --timeout 600 >/dev/null 2>&1 || sleep 30; done`). 리뷰 수정 범위는 P0·P1, 기본 경로의 P2, 회귀다. 가장자리 경우는 알려진 한계로 적는다.

## 태스크 순서와 인터페이스(모든 태스크가 이 이름·꼴을 쓴다)

순서: Task 1 작업 규칙·직무 문서·메인 규칙·회귀 수정 사양(5.11 의 2–4) → Task 2 검사 약화 의심과 리뷰 기준(6.6 의 1–2) → Task 3 보고서 소절 사전 검사와 리뷰어 문구 인용(6.6 의 3–4) → Task 4 plan check 경고(5.11 의 5) → Task 5 text-rules §4·textlint·작성자 점검표(11.14). Task 3 의 재현 시험 사전 검사는 Task 1 의 `specs.repro_task` 를, Task 3 의 문구 사전 검사는 Task 5 가 고칠 `textlint.visible_lines` 를 쓴다(Task 5 뒤에는 사람 글 표시 안의 한글 줄은 세지 않는다).

```python
# herdr-team/lib/hteam/specs.py
REPRO_LINE = "- 재현 시험: 고치기 전에 실패하는 시험을 먼저 쓴다(보고서 ### 재현 시험)"   # Task 1
REPRO_RE = re.compile(r"(?m)^[ \t]*- 재현 시험:")                                          # Task 1
def repro_task(spec: Spec) -> bool                                                           # Task 1
def code_lines(lines: list[str], any_indent: bool = False) -> list[bool]   # Task 3: 줄마다 펜스 코드 블록의 줄인가. parse·report_headings 는 기본값, textlint 는 any_indent=True

# herdr-team/lib/hteam/drive.py (Task 1)
def create_task(self, *, role, title, target, change, acceptance, owns=None, depends=None, plan_append=False,
                issue=None, repro: bool = False) -> str | None   # repro 면 Constraints 가 "<기본 줄>\n<REPRO_LINE>"

# herdr-team/lib/hteam/guardlint.py (Task 2, 새)
EXCLUDE = ("docs/tasks/**", "docs/reviews/**", ".herdr-team/**"); PROSE = {".md", ".mdx", ".txt", ".rst"}
TEST_DIRS = {"test", "tests", "spec", "__tests__"}; TEST_NAMES = ("*_test.*", "*.test.*", "*.spec.*", "test_*")
LINE_CHECKS: tuple[tuple[str, re.Pattern], ...]   # ("억제 주석", …), ("시험 건너뛰기", …), ("빈 catch", …)
def is_test_file(rel: str) -> bool
def empty_excepts(lines: list[str]) -> list[tuple[int, int]]   # 지금 파일의 빈 except 블록 (머리 줄, pass 줄), 0 부터
def line_findings(rel: str, text: str, added: set[str]) -> list[str]
def defined_tests(lines: list[str]) -> list[str]
def guard_lint(root: Path, files: list[str], shas: list[str]) -> list[str]   # lint.cap 으로 50건

# herdr-team/lib/hteam/compose.py (Task 2)
def guard_findings(p, files: list[str], shas: list[str]) -> list[str]   # guarded(guardlint.guard_lint)
def guard_section(p, files: list[str], shas: list[str]) -> str          # "## 검사 약화 의심\n…" 또는 ""
REPRO_RULE: str                                                         # 재현 시험 태스크의 기준 끝 한 줄
# templates/review-prompt.md 의 새 자리 {{guard}}: {{design}}{{text}}{{guard}}## REVIEW_FILE 형식

# herdr-team/lib/hteam/lint.py (Task 2): lint_task 출력에 "guard_findings"(목록)

# herdr-team/lib/hteam/review.py (Task 3)
TEXT_ROLES = ("designer", "developer"); SCREEN_SUFFIXES = {".html", ".htm", ".css", ".scss", ".jsx", ".tsx", ".vue", ".svelte"}
SECTION_MISSING = "보고서 r{n} 절에 ### {title} 이 없다({why})"; LISTED = 3
def report_headings(text: str, n: int) -> list[str]
def report_prechecks(p, cfg, st: dict, spec, commits: list[dict], files: list[str]) -> list[str]   # prechecks 끝(커밋이 있을 때)

# herdr-team/lib/hteam/textlint.py
def added_text_files(root: Path, files: list[str], shas: list[str]) -> list[str]   # Task 3
SIDE = 30; SAMPLE_SUFFIXES; REPEATS; COPY_MIN_CHARS = 10; COPY_MIN_TIMES = 5; COPY_SHOWN = 40; LABEL_MAX = 10   # Task 5
def sentences(body: str) -> list[str]                                               # Task 5: 나누기로 찾는 문장 후보
def excerpt(line: str, start: int, end: int) -> str                                 # Task 5(옛 excerpt(line) 을 바꾼다)
VOID_TAGS; TAG_WINDOW = 2000; SAMPLE_ATTR = "data-sample"                          # Task 5
def open_tag(text: str, name_end: int, limit: int) -> tuple[int, bool, bool] | None   # Task 5: (끝, 스스로 닫음, data-sample)
def mask_samples(text: str) -> str                                                  # Task 5
def added_rows(rel, text, added) -> list[tuple[int, str, str]]                      # Task 5
def scan_rows(rel, rows, glossary) -> list[str]; def scan(rel, text, added, glossary) -> list[str]   # Task 5
def copies(files_rows) -> list[str]; def labels(files_rows) -> list[str]           # Task 5

# herdr-team/lib/hteam/plan.py (Task 4)
SIZE_ACCEPTANCE = 5; SIZE_WORDS = ("및", "그리고"); VOICE_FILE = "docs/planning/voice.md"
VOICE_WARNING = "docs/planning/voice.md 가 없다. 서비스 문구가 있으면 문구 기준을 쓴다"
def warnings(tasks: list[dict], voice: Path, applied=()) -> list[str]   # check 출력의 "warnings". check 는 voice=p.work_root / VOICE_FILE
```

---

### Task 1: 작업 규칙 7번·3번, developer 재현 시험, planner·메인 규칙의 표시 줄, 회귀 수정 사양(설계 5.11 의 2–4, 8.4)

작업 규칙(`worker-rules.md`, 모든 직무의 워커 사양에 들어간다)에 검사 약화 금지 7번을 더하고 3번의 보고서 항목에 `### 건드리지 않고 본 것` 을 더한다. developer.md 에 `## 재현 시험` 절을 두고, 표시 줄을 넣는 세 곳(관제의 회귀 수정 사양, 메인 규칙, planner 의 tasks.toml 형식)에 같은 줄을 둔다. 메인 규칙 줄은 decide 처리 줄 앞에 둔다(그 줄 뒤에는 7단계 시험이 지키는 index.lock 줄이 붙어 있다). `unknown_regression` 기준에도 한 마디를 더한다(메인이 그 decide 로 회귀 수정 태스크를 만든다). 관제의 묶음 정리 태스크는 그대로 기본 줄 하나다. 표시 줄 판정 `specs.repro_task` 는 Task 2(리뷰 기준)·Task 3(사전 검사)이 쓴다.

**Files:**
- Modify: `herdr-team/templates/worker-rules.md`, `herdr-team/templates/roles/developer.md`, `herdr-team/templates/roles/planner.md`, `herdr-team/templates/CLAUDE.section.md`
- Modify: `herdr-team/lib/hteam/specs.py`, `herdr-team/lib/hteam/drive.py`
- Create: `herdr-team/tests/test_quality.py`
- Modify: `herdr-team/tests/test_wording.py`, `herdr-team/tests/test_start.py`, `herdr-team/tests/test_drive_flows.py`

**Interfaces:**
- Consumes: 없음(p13b 까지의 코드).
- Produces: `specs.REPRO_LINE`, `specs.REPRO_RE`, `specs.repro_task(spec) -> bool`, `Drive.create_task(..., repro=False)`, `tests/test_quality.py`(`read`·`section` 도움 함수, Task 4·5 가 클래스를 더한다).

- [ ] **Step 1: 시험을 먼저 쓴다**

**Create** `herdr-team/tests/test_quality.py`

```python
"""13단계 코드 품질 규칙(설계 5.11 의 2–4): 작업 규칙 7번·3번, developer 의 재현 시험, planner·메인 규칙의 표시 줄, 표시 줄 읽기."""
import unittest

from tests.helpers import ROOT, VALID_BODY
from hteam import specs

REPRO_LINE = "- 재현 시험: 고치기 전에 실패하는 시험을 먼저 쓴다(보고서 ### 재현 시험)"
GUARD_RULE = ("7. 검사를 통과시키려고 다음을 더하지 않는다: 억제 주석(`@ts-ignore`, `eslint-disable`, `# noqa`, `# type: ignore` "
              "같은 것), 시험 건너뛰기·골라 돌리기(`.skip`, `.only`, `xit`, skip 표시), 시험·단언 지우기나 약하게 바꾸기, 빈 "
              "catch·`except: pass`, 기준값 낮추기, 동작하지 않는 자리 채움(`Not implemented`). 꼭 필요하면 보고서에 이유를 적는다.")
UNTOUCHED = ("그 절 안 `### 건드리지 않고 본 것` 소절에 범위 밖에서 본 문제를 고치지 않고 `파일:줄 — 무엇` 으로 적는다"
             "(없으면 \"없음\").")


def read(rel):
    return (ROOT / "templates" / rel).read_text(encoding="utf-8")


def section(text, title):
    start = text.index(f"## {title}\n")
    end = text.find("\n## ", start + 1)
    return text[start:] if end == -1 else text[start:end]


class WorkerRulesTest(unittest.TestCase):
    def test_guard_rule_is_seventh_and_untouched_list_in_third(self):
        rules = read("worker-rules.md")
        self.assertIn("수정 라운드로 돌려보낸다).\n" + GUARD_RULE + "\n", rules)
        self.assertTrue(rules.rstrip().endswith(GUARD_RULE))
        self.assertIn("남은 위험, 가정. " + UNTOUCHED + " 이슈 트래커의", rules)
        # tester 의 같은 뜻 한 줄은 그대로 둔다(설계 5.11 의 2)
        self.assertIn("테스트를 통과시키려고 테스트를 약하게 만들거나 건너뛰거나 지우지 않는다.", read("roles/tester.md"))


class ReproDocTest(unittest.TestCase):
    def test_developer_repro_section(self):
        text = section(read("roles/developer.md"), "재현 시험")
        for needle in ("`- 재현 시험:`", "먼저 쓰고 돌려 실패를 확인한 뒤 고친다", "`### 재현 시험`", "고치기 전 실패 출력 원문",
                       "고친 뒤 통과 출력 원문", "이미 실패하는 시험이 있으면", "그 이유와 대신 확인한 방법", "수정 라운드도"):
            self.assertIn(needle, text)

    def test_marker_line_is_the_same_everywhere(self):
        planner = section(read("roles/planner.md"), "tasks.toml 형식")
        main = read("CLAUDE.section.md")
        rules = main[main.index("### 메인 규칙\n"):main.index("### decide 처리 기준\n")]
        for text in (planner, rules):
            self.assertIn(f"`{REPRO_LINE}`", text)
        self.assertIn("묶음 정리 태스크와 수정 라운드", rules)
        self.assertEqual(specs.REPRO_LINE, REPRO_LINE)
        # 메인 규칙 줄은 decide 처리 줄 앞이다(그 줄 뒤에는 7단계 index.lock 줄이 붙어 있다)
        self.assertLess(rules.index(REPRO_LINE), rules.index("- decide 를 처리하며 만든 태스크"))
        table = main[main.index("### decide 처리 기준\n"):main.index("### 질문 표시 규칙\n")]
        row = next(line for line in table.splitlines() if line.startswith("| `unknown_regression` |"))
        self.assertIn("재현 시험 줄", row)


class ReproTaskTest(unittest.TestCase):
    def spec(self, constraints):
        body = VALID_BODY.replace("표준 라이브러리만.", constraints)
        return specs.parse(f"---\nid: T-001\nrole: developer\ntitle: 고치기\n---\n{body}")

    def test_marker_line_head(self):
        self.assertTrue(specs.repro_task(self.spec(f"표준 라이브러리만.\n{REPRO_LINE}")))
        self.assertTrue(specs.repro_task(self.spec("  - 재현 시험: 손으로 쓴 뒤쪽 글은 보지 않는다")))
        for text in ("표준 라이브러리만.", "재현 시험: 글머리가 없다", "표준 라이브러리만. - 재현 시험: 줄 머리가 아니다",
                     "- 재현 시험 줄이 없다"):
            self.assertFalse(specs.repro_task(self.spec(text)), text)
        self.assertFalse(specs.repro_task(specs.parse("---\nid: T-001\nrole: developer\ntitle: x\n---\n## Target\nx\n")))


if __name__ == "__main__":
    unittest.main()
```

**Edit** `herdr-team/tests/test_wording.py`

```python
        self.assertTrue(text.rstrip().endswith("(리뷰 사전 검사가 수정 라운드로 돌려보낸다)."))
```

```python
        self.assertIn("(리뷰 사전 검사가 수정 라운드로 돌려보낸다).\n7. 검사를 통과시키려고", text)  # 13단계 7번(설계 5.11 의 2)
```

**Edit** `herdr-team/tests/test_wording.py`

```python
        self.assertIn("남은 위험, 가정. " + P7_RULES_ISSUE + "\n4. ", rules)
```

```python
        self.assertIn("남은 위험, 가정. 그 절 안 `### 건드리지 않고 본 것`", rules)  # 13단계(설계 5.11 의 3)
        self.assertIn("없음\"). " + P7_RULES_ISSUE + "\n4. ", rules)
```

**Edit** `herdr-team/tests/test_drive_flows.py`

```python
        self.assertEqual(sp.sections["Constraints"], CONSTRAINTS)
        self.assertEqual(sp.sections["Acceptance"], f"{REGRESSION_ACCEPT_RUN}\n- `hteam test T-004` 가 통과한다")
```

```python
        self.assertEqual(sp.sections["Constraints"], f"{CONSTRAINTS}\n{REPRO_LINE}")  # 재현 시험 태스크(설계 5.11 의 4)
        self.assertEqual(sp.sections["Acceptance"], f"{REGRESSION_ACCEPT_RUN}\n- `hteam test T-004` 가 통과한다")
```

**Edit** `herdr-team/tests/test_drive_flows.py`

```python
CLEANUP_ACCEPT = "- 항목마다 고쳤거나 고치지 않은 이유를 보고서에 적었다"
```

```python
CLEANUP_ACCEPT = "- 항목마다 고쳤거나 고치지 않은 이유를 보고서에 적었다"
REPRO_LINE = "- 재현 시험: 고치기 전에 실패하는 시험을 먼저 쓴다(보고서 ### 재현 시험)"
```

**Edit** `herdr-team/tests/test_drive_flows.py`

```python
        self.assertEqual(dev.sections["Acceptance"], CLEANUP_ACCEPT)
```

```python
        self.assertEqual(dev.sections["Acceptance"], CLEANUP_ACCEPT)
        self.assertEqual(dev.sections["Constraints"], CONSTRAINTS)  # 묶음 정리 태스크에는 재현 시험 줄을 넣지 않는다
```

**Edit** `herdr-team/tests/test_start.py`

```python
        self.assertIn("(리뷰 사전 검사가 수정 라운드로 돌려보낸다).\n\n## 테스트\n- 순서: 작업을 `[T-001]` 커밋으로 먼저 "
```

```python
        self.assertIn("꼭 필요하면 보고서에 이유를 적는다.\n\n## 테스트\n- 순서: 작업을 `[T-001]` 커밋으로 먼저 "  # 작업 규칙 7번 뒤
```

- [ ] **Step 2: 시험이 실패하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_quality tests.test_wording tests.test_start.TestBlockTest tests.test_drive_flows.BatchTest tests.test_drive_flows.CreateTaskTest)`
Expected: FAIL·ERROR 8개(64개 실행): test_quality 넷(작업 규칙 7번·3번, developer `## 재현 시험` 절, 세 곳의 표시 줄, `specs.repro_task` 없음), test_wording 둘(`AgentsRulesP7Test.test_worker_rules`·`PromptTemplateP7Test.test_worker_rules_priority_paragraph`), `TestBlockTest.test_developer_block_order_and_text`(작업 규칙 끝 줄), `BatchTest.test_regression_with_one_cause_makes_fix_task`(Constraints).

- [ ] **Step 3: 규칙 문서와 코드를 고친다**

**Edit** `herdr-team/templates/worker-rules.md`

```markdown
3. 보고서 `{{report}}` 에 이번 라운드 `## r{{round}}` 절을 더한다: 바꾼 파일, 이유, 검증 명령과 출력 원문, 남은 위험, 가정. 이슈 트래커의
```

```markdown
3. 보고서 `{{report}}` 에 이번 라운드 `## r{{round}}` 절을 더한다: 바꾼 파일, 이유, 검증 명령과 출력 원문, 남은 위험, 가정. 그 절 안 `### 건드리지 않고 본 것` 소절에 범위 밖에서 본 문제를 고치지 않고 `파일:줄 — 무엇` 으로 적는다(없으면 "없음"). 이슈 트래커의
```

**Edit** `herdr-team/templates/worker-rules.md`

```markdown
6. 할 수 없으면 `--outcome failed` 로 보고한다. 커밋하지 않은 변경을 남긴 채 succeeded 로 끝내지 않는다(리뷰 사전 검사가 수정 라운드로 돌려보낸다).
```

```markdown
6. 할 수 없으면 `--outcome failed` 로 보고한다. 커밋하지 않은 변경을 남긴 채 succeeded 로 끝내지 않는다(리뷰 사전 검사가 수정 라운드로 돌려보낸다).
7. 검사를 통과시키려고 다음을 더하지 않는다: 억제 주석(`@ts-ignore`, `eslint-disable`, `# noqa`, `# type: ignore` 같은 것), 시험 건너뛰기·골라 돌리기(`.skip`, `.only`, `xit`, skip 표시), 시험·단언 지우기나 약하게 바꾸기, 빈 catch·`except: pass`, 기준값 낮추기, 동작하지 않는 자리 채움(`Not implemented`). 꼭 필요하면 보고서에 이유를 적는다.
```

**Edit** `herdr-team/templates/roles/developer.md`

```markdown
- voice.md 는 고치지 않는다. 용어집에 없는 용어가 꼭 필요하면 `### 문구 점검` 에 적는다.

## 산출물
```

```markdown
- voice.md 는 고치지 않는다. 용어집에 없는 용어가 꼭 필요하면 `### 문구 점검` 에 적는다.

## 재현 시험
- 사양 `## Constraints` 에 `- 재현 시험:` 줄이 있는 태스크(재현 시험 태스크. 버그·회귀 수정)는 owns 안에 결함을 재현하는 시험을 먼저 쓰고 돌려 실패를 확인한 뒤 고친다.
- 보고서 이번 라운드 `## rN` 절 안에 `### 재현 시험` 소절을 둔다: 시험 이름, 고치기 전 실패 출력 원문, 고친 뒤 통과 출력 원문. 이 소절이 없으면 리뷰 사전 검사가 리뷰어 없이 돌려보낸다.
- 이미 실패하는 시험이 있으면(회귀 수정의 묶음 테스트 등) 그 시험이 재현 시험이다. 새로 쓰지 않아도 된다.
- 시험으로 재현할 수 없으면(화면에서만 보이는 결함, 외부 환경) `### 재현 시험` 에 그 이유와 대신 확인한 방법을 적는다.
- 수정 라운드도 이번 라운드 절에 `### 재현 시험` 을 둔다. 앞 라운드의 시험을 그대로 쓰면 그 라운드를 가리키고 이번 라운드의 통과 출력을 붙인다.

## 산출물
```

**Edit** `herdr-team/templates/roles/planner.md`

```markdown
- 테스트 도구를 설치하는 첫 developer 태스크의 `acceptance` 에 "`[test]` 의 quick·full 명령이 실행된다" 를 넣는다.
```

```markdown
- 테스트 도구를 설치하는 첫 developer 태스크의 `acceptance` 에 "`[test]` 의 quick·full 명령이 실행된다" 를 넣는다.
- 버그·회귀를 고치는 developer 태스크(증분 기획의 결함 수정 등)는 `constraints` 끝에 줄을 바꿔 `- 재현 시험: 고치기 전에 실패하는 시험을 먼저 쓴다(보고서 ### 재현 시험)` 를 넣는다(TOML 문자열 안의 `\n`). 그 줄이 있는 태스크는 워커가 실패하는 시험을 먼저 쓰고 리뷰가 그 기록을 본다. 새 기능 태스크에는 넣지 않는다.
```

**Edit** `herdr-team/templates/CLAUDE.section.md`

```markdown
- decide 를 처리하며 만든 태스크(회귀 수정, `[test]` 고치기, 증분 기획)도 같은 순서(task new → 채우기 → 커밋 → start)를 마친 뒤 decide 를 `hteam answer` 로 닫는다.
```

```markdown
- 버그·회귀를 고치는 태스크를 `.herdr-team/bin/hteam task new` 로 만들면(decide `unknown_regression` 의 회귀 수정 포함) `## Constraints` 에 `- 재현 시험: 고치기 전에 실패하는 시험을 먼저 쓴다(보고서 ### 재현 시험)` 줄을 넣는다. 워커가 실패하는 시험을 먼저 쓰고 리뷰가 그 기록을 본다. 묶음 정리 태스크와 수정 라운드(`hteam fix`)에는 넣지 않는다.
- decide 를 처리하며 만든 태스크(회귀 수정, `[test]` 고치기, 증분 기획)도 같은 순서(task new → 채우기 → 커밋 → start)를 마친 뒤 decide 를 `hteam answer` 로 닫는다.
```

**Edit** `herdr-team/templates/CLAUDE.section.md`

```markdown
`hteam status` 의 `test_gate.state` 가 `approved`). 커밋하고 `hteam start T-yyy` 한 뒤 닫는다 |
```

```markdown
`hteam status` 의 `test_gate.state` 가 `approved`). Constraints 에 재현 시험 줄(위 메인 규칙)을 넣는다. 커밋하고 `hteam start T-yyy` 한 뒤 닫는다 |
```

**Edit** `herdr-team/lib/hteam/specs.py`

```python
SECTIONS = ("Target", "Change", "Constraints", "Acceptance")
```

```python
SECTIONS = ("Target", "Change", "Constraints", "Acceptance")
# 재현 시험 표시 줄(설계 5.11 의 4). 사양 `## Constraints` 에 줄 머리가 `- 재현 시험:` 인 줄이 있으면 재현 시험 태스크다
REPRO_LINE = "- 재현 시험: 고치기 전에 실패하는 시험을 먼저 쓴다(보고서 ### 재현 시험)"
REPRO_RE = re.compile(r"(?m)^[ \t]*- 재현 시험:")
```

**Edit** `herdr-team/lib/hteam/specs.py`

```python
def load(p, tid: str) -> Spec:
```

```python
def repro_task(spec: Spec) -> bool:
    """재현 시험 태스크인가(설계 5.11 의 4): `## Constraints` 에 줄 머리(앞 공백 뒤)가 `- 재현 시험:` 인 줄이 있다. 메인·기획자가
    손으로 쓰는 줄이라 뒤쪽 글은 견주지 않는다."""
    return bool(REPRO_RE.search(spec.sections.get("Constraints", "")))


def load(p, tid: str) -> Spec:
```

**Edit** `herdr-team/lib/hteam/drive.py`

```python
                    plan_append: bool = False, issue: str | None = None) -> str | None:
        """`task new` 와 같은 함수로 다음 ID 의 사양과 pending 상태를 만들고(직무·owns 검사. 입력 오류는 사양을 쓰기 전에
        그대로 올린다) 네 절을 채워 덮어쓴다. acceptance 의 `{tid}` 는 새 ID 로 바꾼다. 사양 검사가 실패하면 커밋하지 않고
```

```python
                    plan_append: bool = False, issue: str | None = None, repro: bool = False) -> str | None:
        """`task new` 와 같은 함수로 다음 ID 의 사양과 pending 상태를 만들고(직무·owns 검사. 입력 오류는 사양을 쓰기 전에
        그대로 올린다) 네 절을 채워 덮어쓴다. acceptance 의 `{tid}` 는 새 ID 로 바꾼다. repro 면 Constraints 의 기본 줄 뒤에
        재현 시험 표시 줄(specs.REPRO_LINE, 설계 5.11 의 4)을 더한다(회귀 수정). 사양 검사가 실패하면 커밋하지 않고
```

**Edit** `herdr-team/lib/hteam/drive.py`

```python
        body = (f"## Target\n{target}\n\n## Change\n{change}\n\n## Constraints\n{CONSTRAINTS}\n\n## Acceptance\n"
```

```python
        constraints = f"{CONSTRAINTS}\n{specs.REPRO_LINE}" if repro else CONSTRAINTS
        body = (f"## Target\n{target}\n\n## Change\n{change}\n\n## Constraints\n{constraints}\n\n## Acceptance\n"
```

**Edit** `herdr-team/lib/hteam/drive.py`

```python
                                   change=f"{src}\n{item['text']}", acceptance=acceptance, owns=owns,
                                   issue=redmine.issue_of(self.p, causes[0]))  # 원인 태스크의 issue(설계 5.1)
```

```python
                                   change=f"{src}\n{item['text']}", acceptance=acceptance, owns=owns,
                                   issue=redmine.issue_of(self.p, causes[0]),  # 원인 태스크의 issue(설계 5.1)
                                   repro=True)  # 회귀 수정은 재현 시험 태스크다(설계 5.11 의 4)
```

- [ ] **Step 4: 시험이 통과하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_quality tests.test_wording tests.test_start.TestBlockTest tests.test_drive_flows.BatchTest tests.test_drive_flows.CreateTaskTest tests.test_design_docs tests.test_rule_refs tests.test_state_specs tests.test_project_rules tests.test_setup.UpgradeTest)`
Expected: `Ran 152 tests`, `OK (skipped=1)`.

- [ ] **Step 5: 커밋한다**

```bash
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews'
git add -- herdr-team/templates/worker-rules.md herdr-team/templates/roles/developer.md herdr-team/templates/roles/planner.md herdr-team/templates/CLAUDE.section.md herdr-team/lib/hteam/specs.py herdr-team/lib/hteam/drive.py herdr-team/tests/test_quality.py herdr-team/tests/test_wording.py herdr-team/tests/test_start.py herdr-team/tests/test_drive_flows.py
git commit -m "feat(herdr-team): 작업 규칙 7번·건드리지 않고 본 것, 재현 시험 표시 줄과 회귀 수정 사양(설계 5.11 의 2–4)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/templates/worker-rules.md herdr-team/templates/roles/developer.md herdr-team/templates/roles/planner.md herdr-team/templates/CLAUDE.section.md herdr-team/lib/hteam/specs.py herdr-team/lib/hteam/drive.py herdr-team/tests/test_quality.py herdr-team/tests/test_wording.py herdr-team/tests/test_start.py herdr-team/tests/test_drive_flows.py
```

---

### Task 2: 검사 약화 의심(`guardlint.py`)과 리뷰 기준 더하기(설계 6.6 의 1–2)

새 모듈 `guardlint.py` 가 대상 커밋의 diff 에서 의심 위치를 찾는다. 줄 경고(억제 주석·시험 건너뛰기·빈 catch)는 문구 검사처럼 지금 파일의 줄 가운데 내용이 추가한 줄에 있는 것만 지금 줄 번호로 낸다(같은 내용의 기존 줄도 잡히는 것은 11.7 의 알려진 한계와 같다). 빈 except 블록은 지금 파일의 문맥으로 가른다(`empty_excepts`: 머리 다음의 문장이 더 들여 쓴 `pass` 하나뿐이다). 머리나 `pass` 줄 가운데 하나라도 추가한 줄이면 경고하므로 그대로 둔 `except ValueError:` 아래 본문만 `pass` 로 바꾼 것도 잡는다. 보고서·리뷰·hteam 파일과 글 문서(`.md .mdx .txt .rst`)는 줄 경고를 보지 않는다(억제 주석을 설명하는 글). 시험 파일은 지운 파일(마지막 대상 커밋에 없고 첫 대상 커밋의 부모에 있었다), 지운 시험(지운 줄의 시험 정의 이름이 바뀐 시험 파일 어디의 추가한 줄에도 없다), `@Test` 표시 줄어듦(함수는 두고 표시만 지우면 지운 줄에 이름이 없다. 파일마다 표시 줄 수를 견준다), 단언 줄어듦(파일마다)을 본다. 리뷰 프롬프트는 직무와 관계없이 `## 검사 약화 의심` 절을 문구 절 뒤에 넣는다(`guarded`: 실패하면 한 줄, 리뷰는 계속). `hteam lint --task` 가 같은 목록을 `guard_findings` 로 낸다. 리뷰 기준은 P1 정의·기준 3 뒤 문장·재현 시험 태스크의 끝 줄을 더한다. 끝 줄은 developer.md 의 예외(시험으로 재현할 수 없는 결함)도 받는다: 그때는 실패 출력 대신 이유와 대신 확인한 방법이 타당한지 본다. 기준 2 의 "직무 문서와 프로젝트 규칙" 문장은 p13a 에서 이미 넣었다(바꾸지 않는다). 재현 시험 줄의 번호는 이번 라운드 요청 줄(5)이 있으면 6, 없으면 5 이고 `request_rule` 값 뒤에 붙인다(템플릿의 `{{request_rule}}\n\n{{extra}}` 자리를 지키는 7단계 시험 그대로).

**Files:**
- Create: `herdr-team/lib/hteam/guardlint.py`, `herdr-team/tests/test_guardlint.py`
- Modify: `herdr-team/lib/hteam/compose.py`, `herdr-team/lib/hteam/lint.py`, `herdr-team/templates/review-prompt.md`, `README.md`
- Modify: `herdr-team/tests/test_review.py`, `herdr-team/tests/test_lint.py`

**Interfaces:**
- Consumes: Task 1 의 `specs.repro_task`. `gitio.diff_lines`·`parents`·`tree_entry`·`top_prefix`·`to_top`, `lint.cap`·`read_source`, `compose.guarded`·`findings_list`.
- Produces: `guardlint.guard_lint(root, files, shas)`, `compose.guard_findings`, `compose.guard_section`, `compose.REPRO_RULE`, 템플릿 자리 `{{guard}}`, `lint_task` 의 `guard_findings`. 시험 쪽은 `tests/test_review.py` 의 `REPRO_LINE` 상수와 `VALID_BODY` 가져오기(Task 3 이 쓴다).

- [ ] **Step 1: 시험을 먼저 쓴다**

**Create** `herdr-team/tests/test_guardlint.py`

```python
"""검사 약화 의심(설계 6.6 의 1): 추가한 줄의 패턴, 시험 파일 판정, 시험 정의 이름, 지운 시험 파일·시험, `@Test` 표시·단언
줄어듦, 본문만 pass 로 바꾼 except, 상한."""
import unittest

from tests.helpers import TeamCase
from hteam import gitio
from hteam.guardlint import defined_tests, guard_lint, is_test_file, line_findings


def heads(rel, text):
    """`분류 "일치"` 부분만(파일 전체를 추가한 줄로 본다). 일치한 글에는 따옴표가 없다."""
    out = []
    for item in line_findings(rel, text, set(text.split("\n"))):
        rest = item.split(": ", 1)[1]
        out.append(rest[:rest.index('"(', rest.index('"') + 1) + 1])
    return out


class LineTest(unittest.TestCase):
    def test_each_pattern(self):
        cases = {
            "// @ts-ignore": '억제 주석 "@ts-ignore"', "// @ts-expect-error": '억제 주석 "@ts-expect-error"',
            "// @ts-nocheck": '억제 주석 "@ts-nocheck"', "/* eslint-disable no-console */": '억제 주석 "eslint-disable"',
            "x = 1  # noqa: E501": '억제 주석 "# noqa"', "y = f()  # type: ignore": '억제 주석 "# type: ignore"',
            "z = g()  # pyright: ignore": '억제 주석 "# pyright: ignore"',
            "/* istanbul ignore next */": '억제 주석 "istanbul ignore"', "/* c8 ignore next */": '억제 주석 "c8 ignore"',
            "if x:  # pragma: no cover": '억제 주석 "pragma: no cover"', "a := b //nolint": '억제 주석 "//nolint"',
            '@SuppressWarnings("unchecked")': '억제 주석 "@SuppressWarnings"',
            "it.skip('a', f)": '시험 건너뛰기 ".skip("', "describe.only('a', f)": '시험 건너뛰기 ".only("',
            "xit('a', f)": '시험 건너뛰기 "xit("', "xdescribe('a', f)": '시험 건너뛰기 "xdescribe("',
            "xtest('a', f)": '시험 건너뛰기 "xtest("',
            "@pytest.mark.skip(reason='x')": '시험 건너뛰기 "@pytest.mark.skip"',
            "@pytest.mark.xfail": '시험 건너뛰기 "@pytest.mark.xfail"', "@unittest.skip('x')": '시험 건너뛰기 "@unittest.skip"',
            '\tt.Skip("flaky")': '시험 건너뛰기 "t.Skip("', "#[ignore]": '시험 건너뛰기 "#[ignore]"',
            "@Ignore": '시험 건너뛰기 "@Ignore"', "@Disabled": '시험 건너뛰기 "@Disabled"',
            "try { a() } catch (e) {}": '빈 catch "catch (e) {}"', "} catch {}": '빈 catch "catch {}"',
            "except: pass": '빈 catch "except: pass"',
        }
        for line, want in cases.items():
            self.assertEqual(heads("src/a.ts", line), [want], line)

    def test_except_then_pass_and_lookalikes(self):
        text = "try:\n    a()\nexcept ValueError:\n    pass\nexcept KeyError:\n    log()\n"
        self.assertEqual(heads("src/a.py", text), ['빈 catch "except ValueError:"'])
        for line in ("sys.exit(1)", "context(x)", "stream.skipLast(2)", "@IgnoreExtraProperties", "@TestFactory",
                     "catch (e) { log(e) }", "except ValueError as e: log(e)"):
            self.assertEqual(heads("src/a.ts", line), [], line)

    def test_finding_format_and_only_added_lines(self):
        text = "a()\n// @ts-ignore\nb()\n"
        self.assertEqual(line_findings("src/a.ts", text, {"// @ts-ignore"}),
                         ['src/a.ts:2: 억제 주석 "@ts-ignore"(// @ts-ignore)'])
        self.assertEqual(line_findings("src/a.ts", text, {"a()"}), [])
        long = "x = 1  # noqa " + "가" * 80
        shown = line_findings("src/a.py", long, {long})[0].split("(", 1)[1][:-1]
        self.assertEqual((len(shown), shown[-1]), (60, "…"))

    def test_test_files(self):
        for rel in ("tests/a.py", "src/test/Foo.kt", "spec/a_spec.rb", "src/__tests__/a.js", "pkg/a_test.go",
                    "src/a.test.ts", "src/a.spec.tsx", "test_a.py", "src/test_util.py"):
            self.assertTrue(is_test_file(rel), rel)
        for rel in ("src/app.py", "src/testing/a.py", "src/contest.py", "src/latest.ts", "docs/spec.md", "src/tests.py"):
            self.assertFalse(is_test_file(rel), rel)

    def test_defined_tests(self):
        lines = ["def test_save(self):", "    async def test_load():", "func TestAdd(t *testing.T) {",
                 "it('저장한다', () => {", 'test("불러온다", async () => {', "  it(`템플릿`, f)", "@Test",
                 '@DisplayName("x")', "public void keepsOrder() {", "def helper():", "describe('묶음', () => {"]
        self.assertEqual(defined_tests(lines),
                         ["test_save", "test_load", "TestAdd", "저장한다", "불러온다", "템플릿", "keepsOrder"])


class GuardLintGitTest(TeamCase):
    """git 이 필요한 것: 지운 시험 파일·시험 정의, 단언 줄어듦, 옮긴 시험, 실제 diff 의 except 본문·`@Test` 표시, 상한, 보지 않는
    경로, 하위 폴더 프로젝트."""

    def test_existing_except_body_changed_to_pass(self):
        # 그대로 둔 except 머리 아래 본문만 pass 로 바꿨다(실제 diff: 추가한 줄은 본문뿐이다. Codex 계획 리뷰 p13c r1)
        base = ("try:\n    a()\nexcept ValueError:\n    log()\n\nclass B:\n    def f(self):\n        try:\n            b()\n"
                "        except KeyError:\n            pass\n")
        self.commit("src/a.py", base, "기존")
        sha = self.commit("src/a.py", base.replace("    log()\n", "    # 무시한다\n    pass\n"), "[T-001] 본문만 바꿈")
        self.assertEqual(gitio.added_lines(self.proj, [sha], "src/a.py"), {"    # 무시한다", "    pass"})
        self.assertEqual(guard_lint(self.proj, ["src/a.py"], [sha]),
                         ['src/a.py:3: 빈 catch "except ValueError:"(except ValueError:)'])  # 그대로 둔 KeyError 블록은 아니다
        more = self.commit("src/b.py", "try:\n    a()\nexcept ValueError:\n    pass\n    log()\n", "[T-001] 문장이 더 있다")
        self.assertEqual(guard_lint(self.proj, ["src/b.py"], [more]), [])

    def test_removed_test_annotation_only(self):
        # 함수는 두고 `@Test` 만 지우면 그 시험은 돌지 않는다. 지운 줄에는 표시만 있어 이름을 찾지 못한다(r1)
        rel = "src/test/java/a/FooTest.java"
        body = ("class FooTest {\n    @Test\n    void saves() {\n        assertEquals(1, f());\n    }\n\n    @Test\n"
                "    void loads() {\n        assertEquals(2, g());\n    }\n}\n")
        self.commit(rel, body, "기존 시험")
        sha = self.commit(rel, body.replace("    @Test\n    void loads", "    void loads"), "[T-001] 표시만 지움")
        self.assertEqual(gitio.diff_lines(self.proj, [sha], rel), ([], ["    @Test"]))
        self.assertEqual(guard_lint(self.proj, [rel], [sha]), [f"{rel}: @Test 표시 1개 지움, 0개 더함"])

    def test_deleted_test_file_tests_and_asserts(self):
        self.commit("tests/test_a.py", "def test_save():\n    assert f() == 1\n    assert g()\n\ndef test_load():\n"
                    "    assert h()\n", "기존 시험")
        self.commit("tests/test_b.py", "def test_x():\n    assert 1\n", "기존 시험 b")
        self.commit("src/a.py", "assert x\n", "제품 코드")
        first = self.commit("tests/test_a.py", "def test_save():\n    assert f() == 1\n\ndef test_renamed():\n    pass\n",
                            "[T-001] 시험 고침")
        self.git("rm", "-q", "--", "tests/test_b.py")
        self.git("commit", "-q", "-m", "[T-001] 시험 지움")
        second = self.head()
        third = self.commit("src/a.py", "", "[T-001] 단언 지움")  # 제품 코드의 단언은 세지 않는다
        found = guard_lint(self.proj, ["src/a.py", "tests/test_a.py", "tests/test_b.py"], [first, second, third])
        self.assertEqual(found, ["tests/test_a.py: 지운 시험 1개(test_load) — 같은 이름을 추가한 줄이 없다",
                                 "tests/test_a.py: 단언 2개 지움, 0개 더함",
                                 "tests/test_b.py: 시험 파일을 지웠다"])

    def test_moved_test_is_not_a_deleted_test(self):
        # 같은 이름이 다른 시험 파일의 추가한 줄에 있으면 지운 시험이 아니다. 단언은 파일마다 센다(설계 6.6 의 1)
        self.commit("tests/test_a.py", "def test_save():\n    assert 1\n", "기존")
        a = self.commit("tests/test_a.py", "", "[T-001] 옮김")
        b = self.commit("tests/test_c.py", "def test_save():\n    assert 1\n", "[T-001] 새 파일")
        self.assertEqual(guard_lint(self.proj, ["tests/test_a.py", "tests/test_c.py"], [a, b]),
                         ["tests/test_a.py: 단언 1개 지움, 0개 더함"])

    def test_added_test_file_is_not_deleted(self):
        a = self.commit("tests/test_n.py", "def test_n():\n    assert 1\n", "[T-001] 새 시험")
        self.git("rm", "-q", "--", "tests/test_n.py")
        self.git("commit", "-q", "-m", "[T-001] 다시 지움")
        found = guard_lint(self.proj, ["tests/test_n.py"], [a, self.head()])
        self.assertNotIn("tests/test_n.py: 시험 파일을 지웠다", found)  # 이 태스크 전에는 없던 파일이다

    def test_cap_and_excluded_paths(self):
        sha = self.commit("src/a.ts", "".join(f"// @ts-ignore {n}\n" for n in range(53)), "[T-001] 많다")
        found = guard_lint(self.proj, ["src/a.ts"], [sha])
        self.assertEqual((len(found), found[-1]), (51, "… 외 3건"))
        docs = self.commit("docs/tasks/T-001/report.md", "`@ts-ignore` 를 더한 이유\n", "[T-001] 보고서")
        readme = self.commit("README.md", "eslint-disable 을 쓰지 않는다\n", "[T-001] 문서")
        self.assertEqual(guard_lint(self.proj, ["docs/tasks/T-001/report.md", "README.md", "../x.ts"], [docs, readme]), [])
        self.assertEqual(guard_lint(self.proj, ["src/a.ts"], []), [])

    def test_subdir_project(self):
        self.commit("app/README.md", "앱\n", "하위 폴더 프로젝트")
        self.commit("app/tests/test_a.py", "def test_a():\n    assert 1\n", "기존")
        self.git("rm", "-q", "--", "app/tests/test_a.py")
        self.git("commit", "-q", "-m", "[T-001] 지움")
        self.assertEqual(guard_lint(self.proj / "app", ["tests/test_a.py"], [self.head()]),
                         ["tests/test_a.py: 시험 파일을 지웠다"])


if __name__ == "__main__":
    unittest.main()
```

**Edit** `herdr-team/tests/test_review.py`

```python
from tests.helpers import BASE_CONFIG, ROOT, TeamCase
```

```python
from tests.helpers import BASE_CONFIG, ROOT, VALID_BODY, TeamCase
```

**Edit** `herdr-team/tests/test_review.py`

```python
        self.assertIn("\n\n{{tests}}{{round_scope}}{{group}}{{design}}{{text}}## REVIEW_FILE 형식\n", prompt)
```

```python
        self.assertIn("\n\n{{tests}}{{round_scope}}{{group}}{{design}}{{text}}{{guard}}## REVIEW_FILE 형식\n", prompt)
```

**Edit** `herdr-team/tests/test_review.py`

```python
class TextTemplateTest(unittest.TestCase):
```

```python
REPRO_LINE = "- 재현 시험: 고치기 전에 실패하는 시험을 먼저 쓴다(보고서 ### 재현 시험)"


class GuardSectionTest(ReviewCase):
    """검사 약화 의심 절과 리뷰 기준 더하기(설계 6.6 의 1·2): 직무와 관계없이 붙고, 없으면 절이 없고, 실패해도 리뷰가 계속된다.
    재현 시험 태스크면 기준 끝에 한 줄."""

    def prompt(self, files, report=None, **kw):
        self.started("T-001", "developer", **kw)
        self.assertEqual(self.act_work("T-001", files, report=report)[0], 0)
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out.get("status")), (0, "reviewing"), out)
        return (self.state_dir / "tasks/T-001/r1-review-a1.md").read_text(encoding="utf-8")

    def test_guard_section_lists_added_suppressions(self):
        text = self.prompt({"src/app.ts": "// @ts-ignore\nconst a: number = 'x';\n"})
        self.assertIn("## 검사 약화 의심\n자동 검사(`hteam review`, 이 태스크의 대상 커밋.", text)
        self.assertIn('- src/app.ts:1: 억제 주석 "@ts-ignore"(// @ts-ignore)\n\n## REVIEW_FILE 형식', text)

    def test_no_section_without_findings(self):
        text = self.prompt({"src/app.py": "print('x')\n"})
        self.assertNotIn("## 검사 약화 의심", text)
        self.assertNotIn("{{", text)
        self.assertNotIn("\n\n\n", text)

    def test_check_failure_is_one_line_and_review_goes_on(self):
        from hteam import guardlint, review
        self.started("T-001", "developer")
        self.assertEqual(self.act_work("T-001", {"src/app.py": "x = 1\n"})[0], 0)
        with mock.patch.dict(os.environ, self._env("drive", None, None), clear=True), \
                mock.patch.object(guardlint, "guard_lint", side_effect=RuntimeError("터졌다\n둘째")):
            out = review.review(self.p, "T-001")
        self.assertEqual(out["status"], "reviewing", out)
        text = (self.state_dir / "tasks/T-001/r1-review-a1.md").read_text(encoding="utf-8")
        self.assertIn("판단한다):\n- 자동 검사 실패: RuntimeError: 터졌다 둘째\n\n## REVIEW_FILE 형식", text)

    def test_criteria_sentences(self):
        text = self.prompt({"src/app.py": "print('x')\n"})
        self.assertIn("hteam 테스트 실패, 이 태스크가 더한 억제 주석·시험 건너뛰기·지운 시험·약해진 단언 가운데 보고서에 이유가 "
                      "없거나 이유가 타당하지 않은 것, 아래 디자인·문구 기준이 P1 으로 정한 것.", text)
        self.assertIn("3. 버그, 보안, 회귀 위험. 태스크 범위를 넘는 변경(무관한 이름 바꾸기, 주석 지우기, 리팩터링)은 P2 로 "
                      "`## 후속` 에 적는다. 보고서 `### 건드리지 않고 본 것` 의 항목은 지적하지 않는다.\n", text)
        self.assertIn("2. 직무 문서와 프로젝트 규칙(위에 있으면)의 규칙과 품질 기준을 지키는가.\n", text)
        self.assertNotIn("재현 시험을 요구한다", text)

    def test_repro_task_adds_the_last_criterion(self):
        body = VALID_BODY.replace("표준 라이브러리만.", "표준 라이브러리만.\n" + REPRO_LINE)
        text = self.prompt({"src/app.py": "print('x')\n"}, report="## r1\n### 재현 시험\n- 실패 뒤 통과\n", body=body)
        self.assertIn("4. 수정 라운드면 이전 리뷰의 P1 지적이 모두 반영됐는가.\n5. 사양이 재현 시험을 요구한다. 보고서 "
                      "`### 재현 시험` 의 실패 출력이 사양의 결함과 맞고", text)
        self.assertIn("고치기 전 코드로 되돌려 돌리지 않는다(git 쓰기 금지).\n\n## 등급과 판정", text)
        # developer.md 의 예외(시험으로 재현할 수 없는 결함)는 이유와 대신 확인한 방법을 본다(Codex 계획 리뷰 p13c r1)
        self.assertIn("보고서가 시험으로 재현할 수 없다고 적었으면(화면에서만 보이는 결함, 외부 환경) 실패 출력 대신 그 이유와 대신 "
                      "확인한 방법이 타당한지 본다.", text)
        from hteam import config, specs
        st = self.task_state("T-001")
        rd = {**st["rounds"][-1], "note": "더 고친다"}
        text = compose.review_prompt(self.p, config.load(self.p), specs.load(self.p, "T-001"), rd,
                                     st["rounds"][-1]["reviews"][0])
        self.assertIn("요청을 따른 쪽을 맞는 것으로 본다.\n6. 사양이 재현 시험을 요구한다.", text)


class TextTemplateTest(unittest.TestCase):
```

**Edit** `herdr-team/tests/test_lint.py`

```python
    def test_scaffold_copies_design_rules(self):
```

```python
    def test_lint_task_guard_findings(self):
        # 리뷰 프롬프트의 검사 약화 의심 절과 같은 목록이다(설계 6.6 의 1). 직무와 관계없다
        self.write_spec("T-001", "developer")
        state.create(self.p, "T-001", "developer")
        code, out = self.hteam("lint", "--task", "T-001", as_=None)
        self.assertEqual((code, out["guard_findings"]), (0, []), out)
        self.assertEqual(self.hteam("start", "T-001")[0], 0)
        self.act_work("T-001", {"src/app.test.ts": "it.skip('저장', () => {});\n"})
        code, out = self.hteam("lint", "--task", "T-001", as_=None)
        self.assertEqual(out["guard_findings"], ["src/app.test.ts:1: 시험 건너뛰기 \".skip(\"(it.skip('저장', () => {});)"],
                         out)

    def test_scaffold_copies_design_rules(self):
```

- [ ] **Step 2: 시험이 실패하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_guardlint tests.test_review.GuardSectionTest tests.test_review.TextTemplateTest tests.test_lint.LintCommandTest)`
Expected: FAIL·ERROR 7개(15개 실행): `tests.test_guardlint` 가져오기 실패(guardlint 가 없다. 그 모듈의 시험 열넷이 모두 여기에 든다), `GuardSectionTest` 넷, `TextTemplateTest.test_review_text_and_prompt_slots`(`{{guard}}` 자리), `LintCommandTest.test_lint_task_guard_findings`(KeyError).

- [ ] **Step 3: 구현한다**

**Create** `herdr-team/lib/hteam/guardlint.py`

```python
"""검사 약화 의심(설계 6.6 의 1): 리뷰 대상 커밋이 더한 억제 주석·시험 건너뛰기·빈 catch, 지운 시험 파일·시험 정의, 줄어든 단언.

결과는 경고다(자동 불합격은 없다). 판정은 리뷰어가 보고서의 이유와 함께 한다(리뷰 프롬프트의 P1 정의). 언어는 설정이 모르므로
패턴은 고정 목록이고 줄 단위 정규식이라 문자열 안의 낱말도 잡는다. 추가한 줄은 문구 검사(textlint)처럼 "지금 파일에서 내용이
대상 커밋의 추가한 줄에 있는 줄" 이다. git 은 gitio.diff_lines·parents·tree_entry 로만 읽고 hc·horch·codex 를 부르지 않는다.
"""
from __future__ import annotations

import re
from fnmatch import fnmatch
from pathlib import Path

from . import gitio
from .globs import matches_any
from .lint import cap, read_source

# 줄 단위로 보지 않는 파일: 보고서·리뷰·hteam 파일과 글 문서(억제 주석을 설명하는 글이 경고가 되지 않게). 시험 파일 판정과
# 지운 시험·단언 세기는 이 제외와 상관없다
EXCLUDE = ("docs/tasks/**", "docs/reviews/**", ".herdr-team/**")
PROSE = frozenset({".md", ".mdx", ".txt", ".rst"})
TEST_DIRS = frozenset({"test", "tests", "spec", "__tests__"})
TEST_NAMES = ("*_test.*", "*.test.*", "*.spec.*", "test_*")
SNIPPET = 60
NAMES_SHOWN = 5
# (분류 이름, 정규식). 이름이 출력에 그대로 나온다. 낱말처럼 생긴 것(xit·t.Skip)은 앞에 낱말 글자·점이 붙으면 보지 않는다
# (sys.exit( 의 xit( 같은 것)
LINE_CHECKS = (
    ("억제 주석", re.compile(r"@ts-ignore|@ts-expect-error|@ts-nocheck|eslint-disable|#\s*noqa\b|#\s*type:\s*ignore"
                         r"|#\s*pyright:\s*ignore|istanbul ignore|c8 ignore|pragma: no cover|//\s*nolint\b"
                         r"|@SuppressWarnings\b")),
    ("시험 건너뛰기", re.compile(r"\.skip\(|\.only\(|(?<![\w$.])(?:xit|xdescribe|xtest)\(|@pytest\.mark\.(?:skip|xfail)"
                           r"|@unittest\.skip|(?<![\w$.])t\.Skip\w*\(|#\[ignore\]|@Ignore\b|@Disabled")),
    ("빈 catch", re.compile(r"\bcatch\s*(?:\([^()]*\))?\s*\{\s*\}")),
)
_EXCEPT = re.compile(r"^\s*except\b[^:]*:\s*(?:#.*)?$")
_EXCEPT_PASS = re.compile(r"^\s*except\b[^:]*:\s*pass\s*(?:#.*)?$")
_PASS = re.compile(r"^\s*pass\s*(?:#.*)?$")
_SKIP_LINE = re.compile(r"^\s*(?:#.*)?$")  # 빈 줄·주석 줄(except 블록의 문장을 셀 때 건너뛴다)
_PY_GO_TEST = re.compile(r"^\s*(?:async\s+)?def\s+(test\w*)|^\s*func\s+(Test\w*)")
_JS_TEST = re.compile(r"^\s*(?:it|test)\(\s*(?:([\"'`])(.*?)\1)?")
_ANNOTATION = re.compile(r"^\s*@Test\b")
_CALL_NAME = re.compile(r"(`[^`]+`|[A-Za-z_]\w*)\s*\(")
# 단언 호출: assert 로 시작하는 호출(assertEqual(, assert.Equal(, assert_eq!(, Python 의 `assert x`), expect(, XCTAssert…(
_ASSERT = re.compile(r"(?<![\w$])(?:assert\w*(?:\.\w+)?!?\s*\(|assert\s+(?=\S)|expect\s*\(|XCTAssert\w*\s*\()")


def is_test_file(rel: str) -> bool:
    """시험 파일(설계 6.6 의 1): 경로의 폴더 조각에 test·tests·spec·__tests__ 가 있거나 이름이 `*_test.*`·`*.test.*`·
    `*.spec.*`·`test_*` 다."""
    parts = rel.split("/")
    return any(p in TEST_DIRS for p in parts[:-1]) or any(fnmatch(parts[-1], pat) for pat in TEST_NAMES)


def _shown(line: str) -> str:
    """발췌: 공백을 하나로 줄인 줄 전체를 60자까지(넘으면 59자 + `…`)."""
    text = " ".join(line.split())
    return text if len(text) <= SNIPPET else text[:SNIPPET - 1] + "…"


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def empty_excepts(lines: list[str]) -> list[tuple[int, int]]:
    """지금 파일의 빈 except 블록 (머리 줄, pass 줄)(0 부터 센 줄 번호): `except …:` 머리 다음의 첫 문장 줄(빈 줄·주석 줄은
    건너뛴다)이 머리보다 들여 쓴 `pass` 이고, 그다음 문장 줄이 머리보다 들여 쓰지 않았거나 없다(블록의 문장이 `pass` 하나)."""
    def statement(i: int) -> int:
        while i < len(lines) and _SKIP_LINE.match(lines[i]):
            i += 1
        return i
    out = []
    for i, line in enumerate(lines):
        if not _EXCEPT.match(line):
            continue
        j = statement(i + 1)
        if j == len(lines) or not _PASS.match(lines[j]) or _indent(lines[j]) <= _indent(line):
            continue
        k = statement(j + 1)
        if k == len(lines) or _indent(lines[k]) <= _indent(line):
            out.append((i, j))
    return out


def line_findings(rel: str, text: str, added: set[str]) -> list[str]:
    """추가한 줄(내용이 added 에 있는 지금 줄)의 억제 주석·시험 건너뛰기·빈 catch. 빈 catch 는 한 줄 `catch (…) {}`,
    추가한 `except …: pass` 한 줄, 그리고 머리나 `pass` 줄 가운데 하나라도 추가한 줄인 빈 except 블록(empty_excepts. 그대로 둔
    머리 아래 본문만 `pass` 로 바꾼 것도 잡는다)이다. 빈 except 블록은 머리 줄 번호로 낸다. 차례는 (줄 번호, 줄 안 위치)."""
    lines = text.split("\n")
    hits: list[tuple[int, int, str, str]] = []
    for n, line in enumerate(lines):
        if line not in added:
            continue
        hits += [(n, m.start(), name, m.group(0)) for name, rx in LINE_CHECKS for m in rx.finditer(line)]
        if _EXCEPT_PASS.match(line):
            hits.append((n, line.index("except"), "빈 catch", line.strip()))
    for head, body in empty_excepts(lines):
        if lines[head] in added or lines[body] in added:
            hits.append((head, lines[head].index("except"), "빈 catch", lines[head].strip()))
    return [f'{rel}:{n + 1}: {name} "{what}"({_shown(lines[n])})' for n, _, name, what in sorted(hits)]


def defined_tests(lines: list[str]) -> list[str]:
    """줄 목록의 시험 정의 이름: `def test_…`, `func Test…`, 줄 머리의 `it(`·`test(`(첫 인자 글자. 글자가 아니면 그 줄),
    `@Test` 다음 줄(사이의 다른 `@` 줄은 건너뛴다)의 함수 이름."""
    names = []
    for i, line in enumerate(lines):
        m = _PY_GO_TEST.match(line)
        if m:
            names.append(m.group(1) or m.group(2))
            continue
        m = _JS_TEST.match(line)
        if m:
            names.append(m.group(2) if m.group(2) is not None else line.strip())
            continue
        if _ANNOTATION.match(line):
            j = i + 1
            while j < len(lines) and j <= i + 3 and lines[j].strip().startswith("@"):
                j += 1
            call = _CALL_NAME.search(lines[j]) if j < len(lines) else None
            if call:
                names.append(call.group(1))
    return names


def _asserts(lines: list[str]) -> int:
    return sum(len(_ASSERT.findall(line)) for line in lines)


def _marks(lines: list[str]) -> int:
    """`@Test` 표시 줄 수(`@TestFactory` 같은 다른 표시는 세지 않는다)."""
    return sum(1 for line in lines if _ANNOTATION.match(line))


def _deleted(root: Path, shas: list[str], top: str) -> bool:
    """대상 커밋이 그 파일(최상위 기준 top)을 지웠는가: 마지막 대상 커밋에 없고 첫 대상 커밋의 첫 부모에는 있었다."""
    if gitio.tree_entry(root, shas[-1], top) is not None:
        return False
    ups = gitio.parents(root, shas[0])
    return bool(ups) and gitio.tree_entry(root, ups[0], top) is not None


def guard_lint(root: Path, files: list[str], shas: list[str]) -> list[str]:
    """files(프로젝트 기준 경로, 시도 기록의 바뀐 파일)에서 대상 커밋(shas)의 검사 약화 의심. 줄 경고(파일 차례) 뒤에 시험 파일의
    지운 파일·지운 시험·`@Test` 표시 줄어듦·단언 줄어듦(파일 차례). 프로젝트 밖(`../`)·보고서·리뷰·hteam 파일은 보지 않고, 글 문서는 줄 경고만
    보지 않는다. diff 를 읽지 못한 파일(None)은 건너뛴다. 지운 시험은 같은 이름이 바뀐 시험 파일 어디의 추가한 줄에도 없을 때다.
    MAX_FINDINGS(50)를 넘으면 마지막 항목이 `… 외 N건`."""
    root = Path(root)
    if not shas:
        return []
    found: list[str] = []
    tests: list[tuple[str, list[str], list[str]]] = []
    for rel in files:
        if rel.startswith("../") or matches_any(rel, EXCLUDE):
            continue
        lines = gitio.diff_lines(root, shas, rel)
        if lines is None:
            continue
        added, removed = lines
        text = read_source(root, rel)
        if text is not None and Path(rel).suffix.lower() not in PROSE:
            found += line_findings(rel, text, set(added))
        if is_test_file(rel):
            tests.append((rel, added, removed))
    prefix = gitio.top_prefix(root)
    added_names = {name for _, added, _ in tests for name in defined_tests(added)}
    for rel, added, removed in tests:
        if _deleted(root, shas, gitio.to_top(prefix, rel)):
            found.append(f"{rel}: 시험 파일을 지웠다")
            continue
        gone = [name for name in dict.fromkeys(defined_tests(removed)) if name not in added_names]
        if gone:
            shown = ", ".join(gone[:NAMES_SHOWN]) + (", …" if len(gone) > NAMES_SHOWN else "")
            found.append(f"{rel}: 지운 시험 {len(gone)}개({shown}) — 같은 이름을 추가한 줄이 없다")
        marks_cut, marks_put = _marks(removed), _marks(added)
        if marks_cut > marks_put:  # 함수는 두고 `@Test` 만 지우면 그 시험은 돌지 않는다
            found.append(f"{rel}: @Test 표시 {marks_cut}개 지움, {marks_put}개 더함")
        cut, put = _asserts(removed), _asserts(added)
        if cut > put:
            found.append(f"{rel}: 단언 {cut}개 지움, {put}개 더함")
    return cap(found)
```

**Edit** `herdr-team/lib/hteam/compose.py`

```python
from . import designdiff, gitio, lint, specs, state, testgate, textlint, workspace
```

```python
from . import designdiff, gitio, guardlint, lint, specs, state, testgate, textlint, workspace
```

**Edit** `herdr-team/lib/hteam/compose.py`

```python
def design_section(p, cfg, spec, files: list[str], shas: list[str], agent: str = "codex") -> str:
```

```python
def guard_findings(p, files: list[str], shas: list[str]) -> list[str]:
    """검사 약화 의심 경고 목록(설계 6.6 의 1): guardlint 를 guarded 로 감싼다(실패하면 failure 한 줄이고 리뷰는 계속한다).
    직무와 관계없다. `hteam lint --task` 의 guard_findings 도 이것이다."""
    return guarded(lambda: guardlint.guard_lint(p.work_root, files, shas))


GUARD_INTRO = ("자동 검사(`hteam review`, 이 태스크의 대상 커밋. 문자열 안의 낱말도 잡고 정당한 쓰임도 있으니 직접 열어 보고, "
               "보고서에 적은 이유와 함께 위 P1 정의로 판단한다):")


def guard_section(p, files: list[str], shas: list[str]) -> str:
    """리뷰 프롬프트의 검사 약화 의심 절(설계 6.6 의 1). 찾은 것(실패 줄 포함)이 없으면 빈 문자열."""
    found = guard_findings(p, files, shas)
    return f"## 검사 약화 의심\n{GUARD_INTRO}\n{findings_list(found)}\n\n" if found else ""


def design_section(p, cfg, spec, files: list[str], shas: list[str], agent: str = "codex") -> str:
```

**Edit** `herdr-team/lib/hteam/compose.py`

```python
REQUEST_SCOPE = "4. 위 기준 5 의 이번 라운드 요청을 반영했는지. 반영하지 않았으면 P1 이다.\n"
```

```python
REQUEST_SCOPE = "4. 위 기준 5 의 이번 라운드 요청을 반영했는지. 반영하지 않았으면 P1 이다.\n"
# 재현 시험 태스크의 기준 끝 한 줄(설계 6.6 의 2). 번호는 이번 라운드 요청 줄(5)이 있으면 6, 없으면 5 다
REPRO_RULE = ("사양이 재현 시험을 요구한다. 보고서 `### 재현 시험` 의 실패 출력이 사양의 결함과 맞고 그 시험이 대상 커밋에 있는지"
              "(이미 실패하던 시험을 쓴 회귀 수정이면 그 시험이 저장소에 있는지) 본다. 보고서가 시험으로 재현할 수 없다고 "
              "적었으면(화면에서만 보이는 결함, 외부 환경) 실패 출력 대신 그 이유와 대신 확인한 방법이 타당한지 본다. 고치기 전 "
              "코드로 되돌려 돌리지 않는다(git 쓰기 금지).")
```

**Edit** `herdr-team/lib/hteam/compose.py`

```python
    기준 뒤에 프로젝트 점검표(review_extra), 테스트 절(tests_section), 묶음 절(group_section), 디자인 절(design_section),
    문구 절(text_section) 순서로 붙인다. 없는 절은 빈 문자열이다. 점검표를 읽지 못한 경고는 warnings(리스트면)에 더한다.
```

```python
    기준 뒤에 프로젝트 점검표(review_extra), 테스트 절(tests_section), 묶음 절(group_section), 디자인 절(design_section),
    문구 절(text_section), 검사 약화 의심 절(guard_section) 순서로 붙인다. 없는 절은 빈 문자열이다. 재현 시험 태스크
    (specs.repro_task)면 기준 끝에 REPRO_RULE 한 줄을 더한다. 점검표를 읽지 못한 경고는 warnings(리스트면)에 더한다.
```

**Edit** `herdr-team/lib/hteam/compose.py`

```python
        request_rule = (f"\n5. 이번 라운드 요청(위 {labels})을 반영했는가. 요청이 사양의 Acceptance 를 바꾸면 요청을 따른 쪽을 "
                        "맞는 것으로 본다.")
```

```python
        request_rule = (f"\n5. 이번 라운드 요청(위 {labels})을 반영했는가. 요청이 사양의 Acceptance 를 바꾸면 요청을 따른 쪽을 "
                        "맞는 것으로 본다.")
    if specs.repro_task(spec):  # 재현 시험 태스크(설계 5.11 의 4, 6.6 의 2)
        request_rule += f"\n{6 if asks else 5}. {REPRO_RULE}"
```

**Edit** `herdr-team/lib/hteam/compose.py`

```python
                text=team_refs(p, text_section(p, files, shas)),
```

```python
                text=team_refs(p, text_section(p, files, shas)), guard=guard_section(p, files, shas),
```

**Edit** `herdr-team/templates/review-prompt.md`

```markdown
3. 버그, 보안, 회귀 위험.
```

```markdown
3. 버그, 보안, 회귀 위험. 태스크 범위를 넘는 변경(무관한 이름 바꾸기, 주석 지우기, 리팩터링)은 P2 로 `## 후속` 에 적는다. 보고서 `### 건드리지 않고 본 것` 의 항목은 지적하지 않는다.
```

**Edit** `herdr-team/templates/review-prompt.md`

```markdown
- P1(막는다): 수용 기준 미충족, 재현되는 동작 버그, 보안 문제, 데이터 손실, `docs/planning/contracts.md` 위반, hteam 테스트 실패, 아래 디자인·문구 기준이 P1 으로 정한 것.
```

```markdown
- P1(막는다): 수용 기준 미충족, 재현되는 동작 버그, 보안 문제, 데이터 손실, `docs/planning/contracts.md` 위반, hteam 테스트 실패, 이 태스크가 더한 억제 주석·시험 건너뛰기·지운 시험·약해진 단언 가운데 보고서에 이유가 없거나 이유가 타당하지 않은 것, 아래 디자인·문구 기준이 P1 으로 정한 것.
```

**Edit** `herdr-team/templates/review-prompt.md`

```markdown
{{tests}}{{round_scope}}{{group}}{{design}}{{text}}## REVIEW_FILE 형식
```

```markdown
{{tests}}{{round_scope}}{{group}}{{design}}{{text}}{{guard}}## REVIEW_FILE 형식
```

**Edit** `herdr-team/lib/hteam/lint.py`

```python
    findings 는 디자인 절의 경고 목록(디렉터 직무 유무와 관계없이), text_findings 는 문구 절의 경고 목록
    (`.herdr-team/text-rules.md` 가 없으면 None)."""
```

```python
    findings 는 디자인 절의 경고 목록(디렉터 직무 유무와 관계없이), text_findings 는 문구 절의 경고 목록
    (`.herdr-team/text-rules.md` 가 없으면 None), guard_findings 는 검사 약화 의심 절의 경고 목록(설계 6.6 의 1)."""
```

**Edit** `herdr-team/lib/hteam/lint.py`

```python
            "text_findings": compose.text_findings(p, files, shas)}
```

```python
            "text_findings": compose.text_findings(p, files, shas), "guard_findings": compose.guard_findings(p, files, shas)}
```

**Edit** `README.md`

```markdown
리뷰어가 볼 경고는 `.herdr-team/bin/hteam lint --task T` 로 미리 본다(`findings` 는 디자인, `text_findings` 는 문구).
```

```markdown
리뷰어가 볼 경고는 `.herdr-team/bin/hteam lint --task T` 로 미리 본다(`findings` 는 디자인, `text_findings` 는 문구, `guard_findings` 는 아래 "검사 약화 의심").
```

**Edit** `README.md`

```markdown
- 수정 라운드의 리뷰는 고친 함수·데이터를 읽는 다른 호출처와 출력 경로, 고친 방법이 만든 새 경계 조건(잠금 대기의 누적, 시각·순서, 늦은 응답)도 본다.
```

```markdown
- 수정 라운드의 리뷰는 고친 함수·데이터를 읽는 다른 호출처와 출력 경로, 고친 방법이 만든 새 경계 조건(잠금 대기의 누적, 시각·순서, 늦은 응답)도 본다.
- 검사 약화 의심(0.8.0): 대상 커밋이 더한 억제 주석(`@ts-ignore`, `eslint-disable`, `# noqa` 등)·시험 건너뛰기(`.skip(`, `.only(`, `@pytest.mark.skip` 등)·빈 catch, 지운 시험 파일과 시험 정의, 시험 파일의 단언 줄어듦을 찾으면 직무와 관계없이 리뷰 프롬프트에 `## 검사 약화 의심` 절로 넣는다(경고, 50건까지). 보고서에 이유가 없거나 타당하지 않으면 리뷰어가 P1 로 본다. 워커 작업 규칙 7번이 같은 것을 금한다.
```

- [ ] **Step 4: 시험이 통과하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_guardlint tests.test_review.GuardSectionTest tests.test_review.TextTemplateTest tests.test_review.ReviewTest tests.test_lint tests.test_wording tests.test_rule_refs)`
Expected: `Ran 109 tests`, `OK`.

- [ ] **Step 5: 커밋한다**

```bash
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews'
git add -- herdr-team/lib/hteam/guardlint.py herdr-team/lib/hteam/compose.py herdr-team/lib/hteam/lint.py herdr-team/templates/review-prompt.md README.md herdr-team/tests/test_guardlint.py herdr-team/tests/test_review.py herdr-team/tests/test_lint.py
git commit -m "feat(herdr-team): 검사 약화 의심 절과 lint guard_findings, 리뷰 P1 정의·범위 밖 변경·재현 시험 기준(설계 6.6 의 1–2)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/lib/hteam/guardlint.py herdr-team/lib/hteam/compose.py herdr-team/lib/hteam/lint.py herdr-team/templates/review-prompt.md README.md herdr-team/tests/test_guardlint.py herdr-team/tests/test_review.py herdr-team/tests/test_lint.py
```

---

### Task 3: 보고서 소절 사전 검사 셋과 리뷰어 문구 인용(설계 6.6 의 3–4)

`review.prechecks` 끝에(대상 커밋이 있을 때만. 커밋이 없으면 "리뷰 대상 커밋이 없다" 가 이미 돌려보낸다) `report_prechecks` 를 붙인다. 보고서는 작업 루트의 `docs/tasks/<T>/report.md` 를 읽는다(사전 검사의 "owns 안에 커밋하지 않은 변경" 검사가 커밋본과 같게 지킨다. 읽지 못하면 빈 글). 이번 라운드 절은 `## r<N>` 뒤가 숫자가 아닌 제목 줄부터 다음 `## ` 앞까지이고(같은 제목의 절이 여럿이면 모두), 사양 절 읽기와 같은 펜스 규칙으로 코드 블록 안 줄을 건너뛴다. 이 규칙을 `specs.code_lines` 로 꺼내 `specs.parse` 도 쓰게 한다(동작은 그대로다. 사양 펜스 시험이 지킨다). 문구 대상의 Markdown 줄도 같은 함수(`any_indent=True`: 목록 안에 들여 쓴 펜스도 지금처럼 펜스로 본다)로 가른다. 지금의 `visible_lines` 는 백틱 셋이나 물결표 셋으로 시작하는 줄마다 상태를 뒤집어, 네 백틱 펜스 안의 세 백틱 예시 속 한글을 문구로 센다. 그대로 두면 코드 예시만 바꾼 태스크를 `### 문구 점검` 사전 검사가 돌려보낸다(Codex 계획 리뷰 p13c r1). 문구 조건 판정이 예외로 실패하면 돌려보내지 않는다(경고 전용 검사가 리뷰를 막지 않는다는 6.2 의 원칙. 리뷰 프롬프트의 문구 절은 따로 실패 줄을 낸다). 디자인 절과 문구 절 시험은 이제 소절이 있는 보고서(`CHECKED_REPORT`)로 리뷰어까지 간다. 리뷰어 문구 인용은 review-text.md 한 줄이다(hteam 은 인용을 검사하지 않는다).

**Files:**
- Modify: `herdr-team/lib/hteam/review.py`, `herdr-team/lib/hteam/specs.py`, `herdr-team/lib/hteam/textlint.py`, `herdr-team/templates/review-text.md`, `README.md`
- Modify: `herdr-team/tests/test_review.py`, `herdr-team/tests/test_textlint.py`

**Interfaces:**
- Consumes: Task 1 의 `specs.repro_task`, Task 2 의 `tests/test_review.py` `REPRO_LINE`·`VALID_BODY`, `lint.DESIGN_ROLES`, `textlint.targets`·`visible_lines`, `gitio.added_lines`, `paths.report_rel`.
- Produces: `specs.code_lines(lines, any_indent=False)`, `textlint.added_text_files`, 펜스를 따르는 `textlint.visible_lines`, `review.report_headings`, `review.report_prechecks`, `review.SECTION_MISSING`·`SCREEN_SUFFIXES`·`TEXT_ROLES`. 시험 쪽 `CHECKED_REPORT`.

- [ ] **Step 1: 시험을 먼저 쓴다**

**Edit** `herdr-team/tests/test_review.py`

```python
DESIGN_CONFIG = BASE_CONFIG + """
[roles.director]
title = "디자인 디렉터"
owns = ["docs/design/**", "assets/**"]

[roles.designer]
title = "디자인"
owns = ["docs/design/**", "assets/**"]
"""
```

```python
DESIGN_CONFIG = BASE_CONFIG + """
[roles.director]
title = "디자인 디렉터"
owns = ["docs/design/**", "assets/**"]

[roles.designer]
title = "디자인"
owns = ["docs/design/**", "assets/**"]
"""
# 보고서 소절 사전 검사(설계 6.6 의 3)를 지나는 보고서. 디자인·문구 절 시험은 이 보고서로 리뷰어까지 간다
CHECKED_REPORT = "## r1\n- 바꾼 파일: 시험\n### 디자인 점검\n- 지킴\n### 문구 점검\n- 지킴\n"
```

**Edit** `herdr-team/tests/test_review.py`

```python
    def prompt(self, tid, role, files, **kw):
        self.started(tid, role, **kw)
        self.assertEqual(self.act_work(tid, files)[0], 0)
        code, out = self.hteam("review", tid)
        self.assertEqual(code, 0, out)
        return (self.state_dir / f"tasks/{tid}/r1-review-a1.md").read_text(encoding="utf-8")

    def test_designer_prompt_has_design_rules_and_lint(self):
```

```python
    def prompt(self, tid, role, files, **kw):
        self.started(tid, role, **kw)
        self.assertEqual(self.act_work(tid, files, report=CHECKED_REPORT)[0], 0)
        code, out = self.hteam("review", tid)
        self.assertEqual(code, 0, out)
        return (self.state_dir / f"tasks/{tid}/r1-review-a1.md").read_text(encoding="utf-8")

    def test_designer_prompt_has_design_rules_and_lint(self):
```

**Edit** `herdr-team/tests/test_review.py`

```python
    def prompt(self, tid, role, files, **kw):
        self.started(tid, role, **kw)
        self.assertEqual(self.act_work(tid, files)[0], 0)
        code, out = self.hteam("review", tid)
        self.assertEqual(code, 0, out)
        return (self.state_dir / f"tasks/{tid}/r1-review-a1.md").read_text(encoding="utf-8")

    def test_korean_ui_text_adds_text_section_with_lint(self):
```

```python
    def prompt(self, tid, role, files, **kw):
        self.started(tid, role, **kw)
        self.assertEqual(self.act_work(tid, files, report=CHECKED_REPORT)[0], 0)
        code, out = self.hteam("review", tid)
        self.assertEqual(code, 0, out)
        return (self.state_dir / f"tasks/{tid}/r1-review-a1.md").read_text(encoding="utf-8")

    def test_korean_ui_text_adds_text_section_with_lint(self):
```

**Edit** `herdr-team/tests/test_review.py`

```python
        self.assertEqual(self.hteam("start", "T-001", "--worker", "codex")[0], 0)
        self.assertEqual(self.act_work("T-001", {"src/app.tsx": 'a = "저장됬어요";\n'})[0], 0)
        self.assertEqual(self.hteam("review", "T-001")[0], 0)
```

```python
        self.assertEqual(self.hteam("start", "T-001", "--worker", "codex")[0], 0)
        self.assertEqual(self.act_work("T-001", {"src/app.tsx": 'a = "저장됬어요";\n'}, report=CHECKED_REPORT)[0], 0)
        self.assertEqual(self.hteam("review", "T-001")[0], 0)
```

**Edit** `herdr-team/tests/test_review.py`

```python
        self.started("T-001", "developer")
        self.assertEqual(self.act_work("T-001", {"src/app.tsx": 'a = "저장됬어요";\n'})[0], 0)
        with mock.patch.dict(os.environ, self._env("drive", None, None), clear=True), \
                mock.patch.object(textlint, "targets", side_effect=RuntimeError("대상 판정\n실패")):
```

```python
        self.started("T-001", "developer")
        self.assertEqual(self.act_work("T-001", {"src/app.tsx": 'a = "저장됬어요";\n'}, report=CHECKED_REPORT)[0], 0)
        with mock.patch.dict(os.environ, self._env("drive", None, None), clear=True), \
                mock.patch.object(textlint, "targets", side_effect=RuntimeError("대상 판정\n실패")):
```

**Edit** `herdr-team/tests/test_review.py`

```python
    def test_review_design_example_and_agents_reviewer_lines(self):
```

```python
    def test_review_text_quotes_service_text(self):
        # 설계 6.6 의 4: 리뷰어가 읽은 서비스 문구를 인용한다. hteam 은 인용이 없다고 막지 않는다
        text = (ROOT / "templates/review-text.md").read_text(encoding="utf-8")
        self.assertIn("- `## 직접 확인한 것` 에 이 태스크가 바꾼 서비스 문구 가운데 직접 읽은 3–5줄을 `파일:줄 \"문구\"` 로 "
                      "인용한다(바뀐 문구가 그보다 적으면 전부).\n\n자동 검사", text)

    def test_review_design_example_and_agents_reviewer_lines(self):
```

**Edit** `herdr-team/tests/test_review.py`

```python
class PrecheckTest(ReviewCase):
```

`````python
class ReportHeadingsTest(unittest.TestCase):
    """보고서 소절 읽기(설계 6.6 의 3): 이번 라운드 절만, 펜스 코드 블록 안의 `## `·`### ` 줄은 절을 끊지도 소절로 세지도 않는다."""

    def test_round_section_and_fences(self):
        from hteam import review
        text = ("# T-001 보고서\n## r1\n### 문구 점검\n- 지킴\n## r2\n```text\n## r3\n### 재현 시험\n```\n### 디자인 점검\n"
                "~~~~\n```\n### 가짜\n~~~~\n### 재현 시험 (회귀)   \n## r20\n### 다른 라운드\n")
        self.assertEqual(review.report_headings(text, 2), ["### 디자인 점검", "### 재현 시험 (회귀)"])
        self.assertEqual(review.report_headings(text, 1), ["### 문구 점검"])
        self.assertEqual(review.report_headings(text, 20), ["### 다른 라운드"])
        self.assertEqual(review.report_headings(text, 3), [])  # 펜스 안의 `## r3` 은 절이 아니다
        self.assertEqual(review.report_headings("## r1\n```\n### 문구 점검\n", 1), [])  # 닫히지 않은 펜스는 끝까지다


class ReportPrecheckTest(ReviewCase):
    """보고서 소절 사전 검사(설계 6.6 의 3): 셋이 각각 조건일 때만 리뷰어 없이 돌려보낸다."""

    def setUp(self):
        TeamCase.setUp(self)
        self.init_project(config=DESIGN_CONFIG, roles=("planner", "director", "designer", "developer", "tester"))
        self.commit(".herdr-team/text-rules.md", "# 문구 규칙\n", "chore: 문구 규칙")
        self.setup_run()
        self.p = Project(self.proj)

    def review(self, tid, role, files, report, **kw):
        self.started(tid, role, **kw)
        self.assertEqual(self.act_work(tid, files, report=report)[0], 0)
        code, out = self.hteam("review", tid)
        self.assertEqual(code, 0, out)
        return out

    def assert_sent_back(self, out, problems):
        self.assertEqual((out["status"], out["source"], out["problems"]), ("changes", "hteam", problems), out)

    def test_text_check_needs_added_korean_line(self):
        out = self.review("T-001", "developer", {"src/t1/app.tsx": 'a = "저장했어요";\n', "src/t1/b.py": "print('저장')\n"},
                          "## r1\n### 디자인 점검\n- 지킴\n", owns="src/t1/**")
        self.assert_sent_back(out, ["보고서 r1 절에 ### 문구 점검 이 없다(문구 대상 파일에 한글 줄을 더했다: src/t1/app.tsx)"])
        text = (self.proj / "docs/reviews/T-001/r1.md").read_text(encoding="utf-8")
        self.assertIn("- [P1] 보고서 r1 절에 ### 문구 점검 이 없다", text)
        # 한글이 주석에만 있거나 한글 줄을 더하지 않은 코드 변경은 돌려보내지 않는다
        out = self.review("T-002", "developer", {"src/t2/server.ts": "// 저장 주석\nconst a = 1;\n"}, "## r1\n- 바꾼 파일\n",
                          owns="src/t2/**")
        self.assertEqual(out["status"], "reviewing", out)

    def test_design_check_by_role_and_screen_files(self):
        out = self.review("T-001", "designer", {"docs/design/screens/home/notes.md": "메모\n"}, "## r1\n### 문구 점검\n",
                          owns="docs/design/screens/home/**")
        self.assert_sent_back(out, ["보고서 r1 절에 ### 디자인 점검 이 없다(designer 태스크다)"])
        out = self.review("T-002", "developer", {"src/t2/Btn.tsx": "<b/>\n", "src/t2/x.css": "a{}\n", "src/t2/y.vue": "<b/>\n",
                                                 "src/t2/z.svelte": "<b/>\n"}, "## r1\n", owns="src/t2/**")
        self.assert_sent_back(out, ["보고서 r1 절에 ### 디자인 점검 이 없다(화면 파일을 바꿨다: src/t2/Btn.tsx, src/t2/x.css, "
                                    "src/t2/y.vue 외 1개)"])
        # 서버 코드일 수 있는 .ts·.js·.json 만, 앱 파일만 바꾼 developer 는 돌려보내지 않는다(리뷰어가 본다)
        out = self.review("T-003", "developer", {"src/t3/api.ts": "export {}\n", "src/t3/a.js": "x\n", "src/t3/d.json": "{}\n",
                                                 "src/t3/V.swift": "x\n", "src/t3/A.kt": "x\n", "src/t3/m.dart": "x\n"},
                          "## r1\n", owns="src/t3/**")
        self.assertEqual(out["status"], "reviewing", out)

    def test_old_design_heading_is_accepted(self):
        out = self.review("T-001", "director", {"docs/design/direction.md": "방향\n"}, "## r1\n### 금지 목록 점검\n- 지킴\n",
                          owns="docs/design/direction.md")
        self.assertEqual(out["status"], "reviewing", out)

    def test_repro_check_only_for_repro_tasks(self):
        body = VALID_BODY.replace("표준 라이브러리만.", "표준 라이브러리만.\n" + REPRO_LINE)
        out = self.review("T-001", "developer", {"src/t1/app.py": "x = 1\n"}, "## r1\n```\n### 재현 시험\n```\n",
                          owns="src/t1/**", body=body)
        self.assert_sent_back(out, ["보고서 r1 절에 ### 재현 시험 이 없다(사양 Constraints 가 재현 시험을 요구한다)"])
        report = "## r1\n### 재현 시험 (실패 뒤 통과)\n```\n## r1\n```\n"  # 펜스 안의 `## r1` 은 절을 끊지 않는다
        out = self.review("T-002", "developer", {"src/t2/app.py": "x = 2\n"}, report, owns="src/t2/**", body=body)
        self.assertEqual(out["status"], "reviewing", out)
        out = self.review("T-003", "developer", {"src/t3/app.py": "x = 3\n"}, "## r1\n", owns="src/t3/**")  # 표시 줄이 없다
        self.assertEqual(out["status"], "reviewing", out)

    def test_other_round_section_does_not_count(self):
        self.started("T-001", "developer")
        self.assertEqual(self.act_work("T-001", {"src/app.tsx": 'a = "저장"\n'}, report=CHECKED_REPORT)[0], 0)
        self.assertEqual(self.hteam("review", "T-001")[1]["status"], "reviewing")
        self.act_review("T-001", "REQUEST_CHANGES", text="## 지적 사항\n- [P1] src/app.tsx:1 — 틀림. 고친다.\n")
        self.assertEqual(self.hteam("review-finish", "T-001")[1]["status"], "changes")
        self.assertEqual(self.hteam("fix", "T-001")[0], 0)
        report = CHECKED_REPORT + "## r2\n- 고쳤다\n"  # r1 절의 소절은 r2 에 세지 않는다
        self.assertEqual(self.act_work("T-001", {"src/app.tsx": 'a = "저장해요"\n'}, report=report)[0], 0)
        code, out = self.hteam("review", "T-001")
        self.assertEqual(code, 0, out)
        self.assert_sent_back(out, ["보고서 r2 절에 ### 문구 점검 이 없다(문구 대상 파일에 한글 줄을 더했다: src/app.tsx)",
                                    "보고서 r2 절에 ### 디자인 점검 이 없다(화면 파일을 바꿨다: src/app.tsx)"])

    def test_markdown_code_example_change_is_not_text(self):
        # 네 백틱 펜스 안의 세 백틱 예시는 코드다. 예시만 바꾼 태스크는 돌려보내지 않는다(Codex 계획 리뷰 p13c r1)
        guide = "# 안내\n\n설명 글이다.\n\n````markdown\n```\n예시 하나\n```\n````\n"
        self.commit("src/t1/guide.md", guide, "기존 안내")
        out = self.review("T-001", "developer", {"src/t1/guide.md": guide.replace("예시 하나", "예시 둘")}, "## r1\n",
                          owns="src/t1/**")
        self.assertEqual(out["status"], "reviewing", out)

    def test_text_check_failure_does_not_send_back(self):
        from hteam import review
        self.started("T-001", "developer")
        self.assertEqual(self.act_work("T-001", {"src/app.tsx": 'a = "저장"\n'}, report="## r1\n### 디자인 점검\n")[0], 0)
        with mock.patch.dict(os.environ, self._env("drive", None, None), clear=True), \
                mock.patch.object(textlint, "added_text_files", side_effect=RuntimeError("판정 실패")):
            out = review.review(self.p, "T-001")
        self.assertEqual(out["status"], "reviewing", out)

    def test_no_commits_skips_report_checks(self):
        self.started("T-001", "designer", owns="docs/design/screens/home/**")
        self.act_work("T-001", commit=False)
        code, out = self.hteam("review", "T-001")
        self.assertEqual(code, 0, out)
        self.assertFalse(any("### 디자인 점검" in x for x in out["problems"]), out["problems"])


class PrecheckTest(ReviewCase):
`````

**Edit** `herdr-team/tests/test_textlint.py`

```python
    def test_only_added_lines(self):
```

`````python
    def test_nested_fence_example_is_code(self):
        # 펜스 문자와 길이를 따른다: 네 백틱 펜스 안의 세 백틱 줄은 펜스를 닫지 않는다(Codex 계획 리뷰 p13c r1)
        text = "설명 됬다\n````markdown\n```\n예시 됬다\n```\n````\n뒤 됬다\n  ~~~\n  들여 쓴 예시 됬다\n  ~~~\n"
        self.assertEqual([x.split(":", 2)[1] for x in self.found(text, "docs/user/a.md")], ["1", "7"])
        self.assertEqual([n for n, _, _ in visible_lines("docs/user/a.md", text)], [1, 7])

    def test_only_added_lines(self):
`````

- [ ] **Step 2: 시험이 실패하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_review.ReportHeadingsTest tests.test_review.ReportPrecheckTest tests.test_review.TextTemplateTest tests.test_textlint.ScanTest)`
Expected: FAIL·ERROR 8개(25개 실행): `ReportHeadingsTest`(`report_headings` 가 없다), `ReportPrecheckTest` 다섯(돌려보내지 않고 리뷰어로 넘어가 `source` 가 없다), `TextTemplateTest.test_review_text_quotes_service_text`, `ScanTest.test_nested_fence_example_is_code`(세 백틱 줄이 네 백틱 펜스를 닫는다). `test_old_design_heading_is_accepted`·`test_markdown_code_example_change_is_not_text`·`test_no_commits_skips_report_checks` 는 사전 검사가 아직 없어 지금도 통과한다.

- [ ] **Step 3: 구현한다**

**Edit** `herdr-team/lib/hteam/specs.py`

```python
def parse(text: str) -> Spec:
```

```python
def code_lines(lines: list[str], any_indent: bool = False) -> list[bool]:
    """줄마다 펜스 코드 블록의 줄(여는 줄·안·닫는 줄)인가. CommonMark 펜스 규칙: 여는 줄은 같은 문자 3개 이상(백틱 펜스의
    info 에 백틱이 있으면 인라인 코드라 펜스가 아니다), 닫는 줄은 같은 문자 ≥ 여는 길이 + 공백뿐(네 백틱 펜스 안의 세 백틱 줄은
    닫지 않는다). 닫히지 않으면 끝까지다. 펜스 줄의 앞 공백은 3칸까지이고, any_indent 면 보지 않는다(목록 안에 들여 쓴 코드
    블록). 사양 절 읽기(parse)와 보고서 소절 사전 검사(review.report_headings, 설계 6.6 의 3)는 기본값으로, 문구 검사
    (textlint.visible_lines)는 any_indent 로 쓴다."""
    pad = r"[ \t]*" if any_indent else r" {0,3}"
    opening = re.compile(rf"^{pad}(`{{3,}}|~{{3,}})(.*)$")
    out: list[bool] = []
    fence = None
    for line in lines:
        if fence is None:
            fm = opening.match(line)
            if fm and not (fm.group(1)[0] == "`" and "`" in fm.group(2)):
                fence = (fm.group(1)[0], len(fm.group(1)))
            out.append(fence is not None)
        else:
            if re.fullmatch(pad + re.escape(fence[0]) + "{%d,}[ \t]*" % fence[1], line):
                fence = None
            out.append(True)
    return out


def parse(text: str) -> Spec:
```

**Edit** `herdr-team/lib/hteam/specs.py`

```python
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
```

```python
    current, buf = None, []
    body_lines = body.splitlines()
    for line, code in zip(body_lines, code_lines(body_lines)):
        m = None if code else re.match(r"^## (.+?)\s*$", line)  # 코드 블록 안의 `## ...` 는 절 머리가 아니다
```

**Edit** `herdr-team/lib/hteam/textlint.py`

```python
from .lint import cap, read_source
```

```python
from .lint import cap, read_source
from .specs import code_lines
```

**Edit** `herdr-team/lib/hteam/textlint.py`

````python
    """검사할 줄 (줄 번호, 줄 원문, 검사할 글). 코드 확장자는 주석으로 시작하는 줄, HTML·XML 은 `<!--` 로 시작하는 줄,
    Markdown 은 펜스(``` · ~~~) 블록을 빼고 인라인 코드를 지운 글을 본다(`* 글머리` 는 남는다). 한글이 없는 줄은 뺀다."""
    suffix = Path(rel).suffix.lower()
    out: list[tuple[int, str, str]] = []
    fenced = False
    for number, line in enumerate(text.split("\n"), 1):
        head, body = line.lstrip(), line
        if suffix in MARKDOWN:
            if head.startswith(("```", "~~~")):
                fenced = not fenced
                continue
            if fenced:
                continue
            body = _INLINE.sub(" ", line)
````

```python
    """검사할 줄 (줄 번호, 줄 원문, 검사할 글). 코드 확장자는 주석으로 시작하는 줄, HTML·XML 은 `<!--` 로 시작하는 줄,
    Markdown 은 펜스 코드 블록(specs.code_lines: 펜스 문자와 길이를 따르고 앞 공백은 보지 않는다. 네 백틱 펜스 안의 세 백틱
    예시도 코드다)을 빼고 인라인 코드를 지운 글을 본다(`* 글머리` 는 남는다). 한글이 없는 줄은 뺀다."""
    suffix = Path(rel).suffix.lower()
    lines = text.split("\n")
    code = code_lines(lines, any_indent=True) if suffix in MARKDOWN else [False] * len(lines)
    out: list[tuple[int, str, str]] = []
    for number, (line, fenced) in enumerate(zip(lines, code), 1):
        head, body = line.lstrip(), line
        if fenced:
            continue
        if suffix in MARKDOWN:
            body = _INLINE.sub(" ", line)
```

**Edit** `herdr-team/lib/hteam/textlint.py`

```python
def text_lint(root: Path, files: list[str], shas: list[str]) -> list[str]:
```

```python
def added_text_files(root: Path, files: list[str], shas: list[str]) -> list[str]:
    """문구 대상(targets) 가운데 대상 커밋(shas)이 검사할 줄(주석이 아니고 한글이 보이는 줄)을 더한 파일(설계 6.6 의 3,
    `### 문구 점검` 사전 검사). diff 를 읽지 못한 파일은 세지 않는다(그 파일 때문에 돌려보내지 않는다)."""
    out = []
    for rel in targets(root, files):
        added = gitio.added_lines(root, shas, rel)
        text = read_source(root, rel)
        if added and text is not None and any(line in added for _, line, _ in visible_lines(rel, text)):
            out.append(rel)
    return out


def text_lint(root: Path, files: list[str], shas: list[str]) -> list[str]:
```

**Edit** `herdr-team/lib/hteam/review.py`

```python
from . import compose, config, crew, dispatch, gitio, plan, procs, queue, roles, specs, state, tasks, testgate, workspace
```

```python
from . import (compose, config, crew, dispatch, gitio, lint, plan, procs, queue, roles, specs, state, tasks, testgate,
               textlint, workspace)
```

**Edit** `herdr-team/lib/hteam/review.py`

```python
from .paths import SHIM, find_project, review_rel
```

```python
from .paths import SHIM, find_project, report_rel, review_rel
```

**Edit** `herdr-team/lib/hteam/review.py`

```python
REVIEW_STATES = frozenset({"working", "reviewing"})
```

```python
REVIEW_STATES = frozenset({"working", "reviewing"})
# 보고서 소절 사전 검사(설계 6.6 의 3)
TEXT_ROLES = ("designer", "developer")  # `### 문구 점검` 을 쓰는 직무(설계 11.7)
SCREEN_SUFFIXES = frozenset({".html", ".htm", ".css", ".scss", ".jsx", ".tsx", ".vue", ".svelte"})  # developer 의 화면 파일
SECTION_MISSING = "보고서 r{n} 절에 ### {title} 이 없다({why})"
LISTED = 3  # 까닭에 보이는 파일 수
```

**Edit** `herdr-team/lib/hteam/review.py`

```python
def prechecks(p, cfg, st: dict, spec, commits: list[dict], files: list[str]) -> list[str]:
    """설계 6.1 4. 하나라도 걸리면 리뷰어를 띄우지 않고 REQUEST_CHANGES."""
```

```python
def report_headings(text: str, n: int) -> list[str]:
    """보고서 글의 이번 라운드 `## r<n>` 절(그 제목 줄부터 다음 `## ` 제목 앞까지. 같은 제목의 절이 여럿이면 모두) 안의 `### `
    제목 줄(끝 공백을 뗀 것). 펜스 코드 블록 안의 줄은 절을 끊지도 소절로 세지도 않는다(specs.code_lines: 출력 원문에 든
    `## `·`### ` 줄이 소절을 밀어내거나 대신하지 않게)."""
    lines = text.splitlines()
    head = re.compile(rf"## r{n}(?![0-9])")
    found, inside = [], False
    for line, code in zip(lines, specs.code_lines(lines)):
        if code:
            continue
        if line.startswith("## "):
            inside = bool(head.match(line))
        elif inside and line.startswith("### "):
            found.append(line.rstrip())
    return found


def _listed(paths: list[str]) -> str:
    shown = ", ".join(show(f) for f in paths[:LISTED])
    return shown + (f" 외 {len(paths) - LISTED}개" if len(paths) > LISTED else "")


def report_prechecks(p, cfg, st: dict, spec, commits: list[dict], files: list[str]) -> list[str]:
    """보고서 소절 사전 검사(설계 6.6 의 3). 보고서 이번 라운드 절(report_headings)에 그 제목으로 시작하는 `### ` 줄이 없으면
    한 줄(SECTION_MISSING):
    - `### 문구 점검`: designer·developer 이고 `.herdr-team/text-rules.md` 가 있고 대상 커밋이 문구 대상 파일에 검사할 줄(한글이
      보이는, 주석이 아닌 줄)을 더했다(textlint.added_text_files). 이 판정이 예외로 실패하면 돌려보내지 않는다.
    - `### 디자인 점검`(옛 `### 금지 목록 점검` 도 받는다): 디자인 절이 붙는 태스크(director·designer·developer 이고
      `[roles.director]` 가 있다)이고 director·designer 거나, developer 이면서 화면 파일(SCREEN_SUFFIXES)을 바꿨다.
    - `### 재현 시험`: 재현 시험 태스크(specs.repro_task).
    보고서를 읽지 못하면(없음, UTF-8 아님) 빈 글로 본다. 제목 줄만 보고 내용은 리뷰어가 본다."""
    n = st["round"]
    try:
        text = (p.work_root / report_rel(st["id"])).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        text = ""
    heads = report_headings(text, n)

    def has(*titles: str) -> bool:
        return any(h.startswith(f"### {t}") for h in heads for t in titles)

    found = []
    if spec.role in TEXT_ROLES and p.text_rules.is_file() and not has("문구 점검"):
        try:
            touched = textlint.added_text_files(p.work_root, files, [c["sha"] for c in commits])
        except Exception:  # noqa: BLE001  조건을 모르면 돌려보내지 않는다(리뷰 프롬프트의 문구 절은 따로 실패 줄을 낸다)
            touched = []
        if touched:
            found.append(SECTION_MISSING.format(n=n, title="문구 점검",
                                                why=f"문구 대상 파일에 한글 줄을 더했다: {_listed(touched)}"))
    if spec.role in lint.DESIGN_ROLES and "director" in cfg.roles and not has("디자인 점검", "금지 목록 점검"):
        if spec.role != "developer":
            found.append(SECTION_MISSING.format(n=n, title="디자인 점검", why=f"{spec.role} 태스크다"))
        else:
            screens = [f for f in files if os.path.splitext(f)[1].lower() in SCREEN_SUFFIXES]
            if screens:
                found.append(SECTION_MISSING.format(n=n, title="디자인 점검", why=f"화면 파일을 바꿨다: {_listed(screens)}"))
    if specs.repro_task(spec) and not has("재현 시험"):
        found.append(SECTION_MISSING.format(n=n, title="재현 시험", why="사양 Constraints 가 재현 시험을 요구한다"))
    return found


def prechecks(p, cfg, st: dict, spec, commits: list[dict], files: list[str]) -> list[str]:
    """설계 6.1 4. 하나라도 걸리면 리뷰어를 띄우지 않고 REQUEST_CHANGES. 대상 커밋이 있으면 보고서 소절 사전 검사
    (report_prechecks, 6.6 의 3)도 한다."""
```

**Edit** `herdr-team/lib/hteam/review.py`

```python
    if dirty:
        found.append("owns 안에 커밋하지 않은 변경이 있다: " + ", ".join(dirty))
    return found
```

```python
    if dirty:
        found.append("owns 안에 커밋하지 않은 변경이 있다: " + ", ".join(dirty))
    if commits:
        found += report_prechecks(p, cfg, st, spec, commits, files)
    return found
```

**Edit** `herdr-team/templates/review-text.md`

```markdown
- 워커 직무 문서(`.herdr-team/roles/<직무>.md`)가 `### 문구 점검` 을 요구하면, 보고서 마지막 라운드에 그 소절이 있는지와 실제와 맞는지 본다.
```

```markdown
- 워커 직무 문서(`.herdr-team/roles/<직무>.md`)가 `### 문구 점검` 을 요구하면, 보고서 마지막 라운드에 그 소절이 있는지와 실제와 맞는지 본다.
- `## 직접 확인한 것` 에 이 태스크가 바꾼 서비스 문구 가운데 직접 읽은 3–5줄을 `파일:줄 "문구"` 로 인용한다(바뀐 문구가 그보다 적으면 전부).
```

**Edit** `README.md`

```markdown
보고서에 이유가 없거나 타당하지 않으면 리뷰어가 P1 로 본다. 워커 작업 규칙 7번이 같은 것을 금한다.
```

```markdown
보고서에 이유가 없거나 타당하지 않으면 리뷰어가 P1 로 본다. 워커 작업 규칙 7번이 같은 것을 금한다.
- 보고서 소절 사전 검사(0.8.0): 리뷰어를 띄우기 전에 보고서 이번 라운드 절의 `### ` 소절을 본다. 문구 대상 파일에 한글 줄을 더한 designer·developer 태스크(`text-rules.md` 가 있을 때)는 `### 문구 점검`, 디자인 절이 붙는 director·designer 태스크와 화면 파일(`.html .htm .css .scss .jsx .tsx .vue .svelte`)을 바꾼 developer 태스크는 `### 디자인 점검`(옛 `### 금지 목록 점검` 도 받는다), 사양 Constraints 에 `- 재현 시험:` 줄이 있는 태스크는 `### 재현 시험` 이 없으면 hteam 이 REQUEST_CHANGES 로 돌려보낸다. 제목 줄만 보고 내용은 리뷰어가 본다. 문구 절이 붙은 리뷰어는 `## 직접 확인한 것` 에 읽은 서비스 문구를 `파일:줄 "문구"` 로 인용한다.
```

- [ ] **Step 4: 시험이 통과하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_review tests.test_state_specs tests.test_textlint tests.test_wording tests.test_rule_refs)`
Expected: `Ran 289 tests`, `OK`(약 6분).

- [ ] **Step 5: 커밋한다**

```bash
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews'
git add -- herdr-team/lib/hteam/review.py herdr-team/lib/hteam/specs.py herdr-team/lib/hteam/textlint.py herdr-team/templates/review-text.md README.md herdr-team/tests/test_review.py herdr-team/tests/test_textlint.py
git commit -m "feat(herdr-team): 보고서 소절 사전 검사(문구·디자인·재현 시험)와 리뷰어 문구 인용(설계 6.6 의 3–4)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/lib/hteam/review.py herdr-team/lib/hteam/specs.py herdr-team/lib/hteam/textlint.py herdr-team/templates/review-text.md README.md herdr-team/tests/test_review.py herdr-team/tests/test_textlint.py
```

---

### Task 4: plan check 경고(설계 5.11 의 5)

`plan check` 출력에 `warnings`(문자열 목록, 없으면 빈 목록)를 더한다. 검사를 통과한 뒤에만 계산하고 막지 않는다(exit 0). 크기 경고는 이미 적용한 key(plan.json 의 `tasks`)를 빼고 본다(`plan apply --append` 가 적용한 태스크를 바꾸지 못하게 하므로 나눌 수 없다). voice.md 는 늘 작업 루트의 `docs/planning/voice.md`(`VOICE_FILE`)를 본다(`--file` 은 검사할 계획 파일만 바꾼다. 리뷰 사전 검사는 그 태스크 작업 루트의 것). 사전 검사(`review.prechecks`)는 `plan.check` 를 부르지만 결과를 쓰지 않으므로 경고가 기획 태스크를 돌려보내지 않는다. `plan apply` 는 바꾸지 않는다. planner.md 는 확정 질문 절과 tasks.toml 형식 절에 같은 기준을 둔다.

**Files:**
- Modify: `herdr-team/lib/hteam/plan.py`, `herdr-team/templates/roles/planner.md`, `README.md`
- Modify: `herdr-team/tests/test_plan.py`, `herdr-team/tests/test_quality.py`

**Interfaces:**
- Consumes: `plan.check`·`plan_tasks`, `read_json(p.plan_file)`. 시험은 `tests/test_plan.py` 의 `task`·`toml`·`APPROVAL`, Task 1 의 `tests/test_quality.py` `read`·`section`.
- Produces: `plan.warnings`, `plan.SIZE_ACCEPTANCE`·`SIZE_WORDS`·`VOICE_FILE`·`VOICE_WARNING`, `plan check` 출력 `warnings`.

- [ ] **Step 1: 시험을 먼저 쓴다**

**Edit** `herdr-team/tests/test_plan.py`

```python
class PlanApplyTest(TeamCase):
```

```python
class PlanWarningTest(TeamCase):
    """plan check 의 warnings(설계 5.11 의 5): 크기와 voice.md. 막지 않는다(exit 0)."""

    def setUp(self):
        super().setUp()
        self.init_project(config=APPROVAL)
        self.path = self.proj / "docs/planning/tasks.toml"
        self.path.parent.mkdir(parents=True)

    def check(self, tasks):
        self.path.write_text(toml(tasks), encoding="utf-8")
        code, out = self.hteam("plan", "check", as_=None)
        self.assertEqual(code, 0, out)
        return out["warnings"]

    def test_size(self):
        five = [f"확인 {n}" for n in range(5)]
        six = five + ["확인 5"]
        self.assertEqual(self.check([task("a", owns=["src/a/**"], acceptance=five),
                                     task("b", owns=["src/b/**"], title="로그인 화면")]), [])
        big = [task("a", owns=["src/a/**"], acceptance=six), task("b", owns=["src/b/**"], title="로그인 및 가입"),
               task("c", owns=["src/c/**"], title="저장 그리고 불러오기", acceptance=six),
               task("d", "planner", ["docs/planning/**"], acceptance=six, title="기획 및 정리")]  # developer 만 본다
        self.assertEqual(self.check(big), ["a: 태스크가 크다(acceptance 6개). 둘로 나눌지 본다",
                                           "b: 태스크가 크다(제목에 '및'). 둘로 나눌지 본다",
                                           "c: 태스크가 크다(acceptance 6개, 제목에 '그리고'). 둘로 나눌지 본다"])

    def test_voice(self):
        missing = "docs/planning/voice.md 가 없다. 서비스 문구가 있으면 문구 기준을 쓴다"
        screens = [task("dir", "director", ["docs/design/system/**"]),
                   task("s1", "designer", ["docs/design/screens/a/**"], deps=["dir"])]
        self.assertEqual(self.check(screens), [missing])
        terms = [task("terms", owns=["src/terms/**"], constraints="docs/planning/voice.md 와 text-rules 를 따른다")]
        self.assertEqual(self.check(terms), [missing])
        self.assertEqual(self.check([task("a", owns=["src/a/**"])]), [])  # 문구를 쓰는 태스크가 없다
        (self.proj / "docs/planning/voice.md").write_text("# 문구 기준\n", encoding="utf-8")
        self.assertEqual(self.check(screens), [])

    def test_applied_tasks_are_not_size_warned(self):
        # 이미 적용한 태스크는 나눌 수 없다(plan apply --append 가 바꾸지 못하게 한다)
        six = [f"확인 {n}" for n in range(6)]
        self.setup_run()
        self.path.write_text(toml([task("a", owns=["src/a/**"], acceptance=six)]), encoding="utf-8")
        code, out = self.hteam("plan", "apply")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.check([task("a", owns=["src/a/**"], acceptance=six),
                                     task("b", owns=["src/b/**"], acceptance=six)]),
                         ["b: 태스크가 크다(acceptance 6개). 둘로 나눌지 본다"])

    def test_file_option_still_reads_the_project_voice(self):
        # --file 은 검사할 계획 파일만 바꾼다. 문구 기준은 늘 프로젝트 작업 루트의 docs/planning/voice.md 다(Codex 계획 리뷰 p13c r1)
        missing = "docs/planning/voice.md 가 없다. 서비스 문구가 있으면 문구 기준을 쓴다"
        alt = self.proj / "alt/tasks.toml"
        alt.parent.mkdir()
        alt.write_text(toml([task("terms", owns=["src/terms/**"], constraints="voice.md 를 따른다")]), encoding="utf-8")
        (self.proj / "alt/voice.md").write_text("# 문구 기준\n", encoding="utf-8")  # 계획 파일 옆의 voice.md 는 보지 않는다
        code, out = self.hteam("plan", "check", "--file", "alt/tasks.toml", as_=None)
        self.assertEqual((code, out["warnings"]), (0, [missing]), out)
        (self.proj / "docs/planning/voice.md").write_text("# 문구 기준\n", encoding="utf-8")
        code, out = self.hteam("plan", "check", "--file", "alt/tasks.toml", as_=None)
        self.assertEqual((code, out["warnings"]), (0, []), out)


class PlanApplyTest(TeamCase):
```

**Edit** `herdr-team/tests/test_quality.py`

```python
class ReproTaskTest(unittest.TestCase):
```

```python
class PlanWarningDocTest(unittest.TestCase):
    def test_planner_reads_warnings_before_the_confirm_question(self):
        text = read("roles/planner.md")
        confirm = section(text, "확정 질문")
        for needle in ("`plan check` 출력의 `warnings`", "나누지 않은 경고는 그 이유를 확정 질문 `context` 에 적는다"):
            self.assertIn(needle, confirm)
        tasks = section(text, "tasks.toml 형식")
        for needle in ("`acceptance` 를 5개 이하로", "`title` 에 \"및\"·\"그리고\" 를 쓰지 않는다", "`warnings`"):
            self.assertIn(needle, tasks)


class ReproTaskTest(unittest.TestCase):
```

- [ ] **Step 2: 시험이 실패하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_plan.PlanWarningTest tests.test_quality.PlanWarningDocTest)`
Expected: FAIL·ERROR 5개(5개 실행): `PlanWarningTest` 넷(KeyError `warnings`), `PlanWarningDocTest` 하나.

- [ ] **Step 3: 구현한다**

**Edit** `herdr-team/lib/hteam/plan.py`

```python
NO_TEST = object()  # tasks.toml 에 [test] 가 없다(validate 의 test 기본값)
```

```python
NO_TEST = object()  # tasks.toml 에 [test] 가 없다(validate 의 test 기본값)
# plan check 의 막지 않는 경고(설계 5.11 의 5)
SIZE_ACCEPTANCE = 5  # developer 태스크의 acceptance 가 이보다 많으면 크다
SIZE_WORDS = ("및", "그리고")  # developer 태스크 제목에 있으면 두 일을 묶었을 수 있다
VOICE_FILE = "docs/planning/voice.md"  # 프로젝트 문구 기준. 작업 루트 기준이다(--file 과 상관없다)
VOICE_WARNING = "docs/planning/voice.md 가 없다. 서비스 문구가 있으면 문구 기준을 쓴다"
```

**Edit** `herdr-team/lib/hteam/plan.py`

```python
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
```

```python
def warnings(tasks: list[dict], voice: Path, applied=()) -> list[str]:
    """막지 않는 경고(설계 5.11 의 5). tasks 는 검사를 통과한 것이다.
    - 크기: developer 태스크의 acceptance 가 SIZE_ACCEPTANCE 개를 넘거나 title 에 SIZE_WORDS 가 있다. 이미 적용한 key(applied)는
      나눌 수 없어 보지 않는다.
    - voice.md: designer 태스크가 있거나 constraints 에 `voice.md` 가 나오는 태스크가 있는데 voice(프로젝트 작업 루트의
      VOICE_FILE)가 없다."""
    out = []
    for t in tasks:
        if t["role"] != "developer" or t["key"] in applied:
            continue
        why = [f"acceptance {len(t['acceptance'])}개"] if len(t["acceptance"]) > SIZE_ACCEPTANCE else []
        why += [f"제목에 '{word}'" for word in SIZE_WORDS if word in t["title"]]
        if why:
            out.append(f"{t['key']}: 태스크가 크다({', '.join(why)}). 둘로 나눌지 본다")
    if any(t["role"] == "designer" or "voice.md" in t["constraints"] for t in tasks) and not voice.is_file():
        out.append(VOICE_WARNING)
    return out


def check(p, cfg, path: Path) -> dict:
    """읽기 전용. 파일 검사에 더해 이미 적용한 계획(plan.json)이 있으면 apply --append 가 받아들일지도 본다.
    그래서 기획 태스크의 사전 검사가 승인 전에 막는다(승인 뒤에는 고칠 라운드가 없다). 묶음 규칙은 적용한 key 를 빼고
    본다(apply --append 와 같다). 출력 test 는 그 파일에 `[test]` 가 있는지, warnings 는 막지 않는 경고(warnings 함수, 없으면
    빈 목록)다. voice.md 는 검사하는 파일 위치와 상관없이 그 작업 루트(p.work_root)의 VOICE_FILE 을 본다."""
    data = read_plan_data(path)
    tasks = plan_tasks(data)
    plan = read_json(p.plan_file, None)
    known = _surviving(p, plan) if plan is not None and "test" in data else None
    groups = _checked(cfg, data, known or {})
    if plan is not None:
        _keep_applied(known if known is not None else _surviving(p, plan), tasks)
    applied = set(plan.get("tasks") or {}) if isinstance(plan, dict) else set()
    return {"tasks": len(tasks), "groups": groups, "test": "test" in data,
            "warnings": warnings(tasks, p.work_root / VOICE_FILE, applied)}
```

**Edit** `herdr-team/templates/roles/planner.md`

```markdown
마지막 질문은 늘 확정 질문이다. 체크리스트에 `미정` 이 없고, spec.md·contracts.md·tasks.toml·voice.md 를 다 쓰고, `plan check` 가 통과한 뒤에 묻는다.
```

```markdown
마지막 질문은 늘 확정 질문이다. 체크리스트에 `미정` 이 없고, spec.md·contracts.md·tasks.toml·voice.md 를 다 쓰고, `plan check` 가 통과한 뒤에 묻는다. `plan check` 출력의 `warnings`(막지 않는다)를 보고 큰 태스크는 나누고 voice.md 가 없다는 경고면 voice.md 를 쓴다. 나누지 않은 경고는 그 이유를 확정 질문 `context` 에 적는다.
```

**Edit** `herdr-team/templates/roles/planner.md`

```markdown
- 단위 테스트는 developer 가 자기 소유 경로 안(예: `src/**/*.test.ts`)에 쓴다. tester 는 묶음 통합 테스트와 QA 보고서를 쓴다.
```

```markdown
- 단위 테스트는 developer 가 자기 소유 경로 안(예: `src/**/*.test.ts`)에 쓴다. tester 는 묶음 통합 테스트와 QA 보고서를 쓴다.
- developer 태스크 하나는 한 가지 일이다: `acceptance` 를 5개 이하로 두고 `title` 에 "및"·"그리고" 를 쓰지 않는다. 넘으면 `plan check` 가 `warnings` 에 적는다(막지 않는다). 나누기 어려우면 그 이유를 확정 질문 `context` 에 적는다.
```

**Edit** `README.md`

```markdown
tester 는 developer 에만 의존, developer 는 tester 에 의존하지 않음, 문서 전용이 아닌 developer 는 정확히 한 묶음.
```

```markdown
tester 는 developer 에만 의존, developer 는 tester 에 의존하지 않음, 문서 전용이 아닌 developer 는 정확히 한 묶음.
- `hteam plan check` 는 막지 않는 `warnings`(0.8.0)도 낸다: acceptance 가 5개를 넘거나 제목에 "및"·"그리고" 가 있는 developer 태스크(이미 적용한 태스크는 빼고), designer 태스크나 constraints 에 `voice.md` 가 나오는 태스크가 있는데 `docs/planning/voice.md` 가 없을 때. planner 는 확정 질문 전에 이 경고를 보고 나누거나 나누지 않은 이유를 적는다.
```

- [ ] **Step 4: 시험이 통과하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_plan tests.test_quality tests.test_interview tests.test_review.PrecheckTest tests.test_wording tests.test_rule_refs)`
Expected: `Ran 147 tests`, `OK`.

- [ ] **Step 5: 커밋한다**

```bash
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews'
git add -- herdr-team/lib/hteam/plan.py herdr-team/templates/roles/planner.md README.md herdr-team/tests/test_plan.py herdr-team/tests/test_quality.py
git commit -m "feat(herdr-team): plan check 경고(태스크 크기, voice.md)와 planner 기준(설계 5.11 의 5)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/lib/hteam/plan.py herdr-team/templates/roles/planner.md README.md herdr-team/tests/test_plan.py herdr-team/tests/test_quality.py
```

---

### Task 5: text-rules §4, textlint 더하기, 작성자 점검표(설계 11.14)

text-rules §4 "항상 고친다" 에 9–12번(상용구 오류 문구, UI 상투어, 2인칭, 문장 복사)을 절 끝에 더하고(번호는 바꾸지 않는다, 11.9), "반복될 때만" 에 넷을 더하고, 출처에 k-skill `korean-humanizer` 를 더한다. textlint 는 (1) 검사할 글을 줄 원문과 같은 길이로 만든다: 사람 글 표시 요소의 내용과 Markdown 인라인 코드를 같은 길이의 공백으로 바꾼다. 그래서 발췌가 일치 위치 앞뒤 30자를 줄 원문에서 자른다. (2) 범주·낱말을 더하고 (3) 파일 단위 반복 집계를 높임법 섞임처럼 그 첫 줄의 다른 지적 뒤에 두고 (4) 파일들 전체의 복붙·라벨 혼용을 파일별 지적 뒤에 둔다. 복붙 문장은 정규식 검색이 아니라 나누기(`sentences`: 따옴표·태그·중괄호·`|` 로 나눈 뒤 마침표로 나눈다)로 찾는다. 마침표 없는 긴 줄에서 시작점마다 끝까지 다시 훑는 검색은 제곱 시간이다(Codex 계획 리뷰 p13c r1). 같은 까닭으로 높임법의 종결 낱말 찾기(`_ENDING`)를 낱말 머리에서만 시작하게 한다(결과는 같다). Task 3 이 펜스를 따르게 한 `visible_lines` 는 그대로 두고 사람 글 표시만 얹는다. 사람 글 표시는 여는 태그를 속성 단위로 읽어(`open_tag`) 속성 이름이 정확히 `data-sample` 일 때만 걸고(`class="data-sample"` 같은 값 안의 글자는 아니다), 빈 요소와 스스로 닫는 태그는 바로 건너뛰고, 닫는 태그는 이름마다 한 번 모은 위치에서 이분 탐색으로 찾는다(닫히지 않은 요소가 많아도 파일을 다시 훑지 않는다. Codex 계획 리뷰 p13c r2). 사람 글 표시는 `targets`·`added_text_files` 에도 걸린다(가짜 댓글만 바꾼 시안은 문구 대상이 아니고 `### 문구 점검` 사전 검사도 세지 않는다). 작성자 점검표는 developer.md·designer.md 의 `### 문구 점검` 줄을 바꾸고, designer.md 에 `data-sample` 을 붙이는 법을 둔다(p13b 가 p13c 로 미룬 것).

**Files:**
- Modify: `herdr-team/lib/hteam/textlint.py`, `herdr-team/templates/text-rules.md`, `herdr-team/templates/roles/developer.md`, `herdr-team/templates/roles/designer.md`, `README.md`
- Modify: `herdr-team/tests/test_textlint.py`, `herdr-team/tests/test_quality.py`

**Interfaces:**
- Consumes: Task 3 의 `textlint.added_text_files`(이 태스크의 `visible_lines` 를 쓴다), Task 1 의 `tests/test_quality.py`.
- Produces: `textlint.excerpt(line, start, end)`, `open_tag`, `mask_samples`, `added_rows`, `scan_rows`, `sentences`, `copies`, `labels`, 상수 `SIDE`·`SAMPLE_SUFFIXES`·`REPEATS`·`COPY_*`·`LABEL_MAX`. `scan(rel, text, added, glossary)` 와 `text_lint(root, files, shas)` 의 꼴은 그대로다.

- [ ] **Step 1: 시험을 먼저 쓴다**

**Edit** `herdr-team/tests/test_textlint.py`

```python
                 "저장하고, 보낸다": '쉼표 "고,"'}
```

```python
                 "저장하고, 보낸다": '쉼표 "고,"',
                 # 13단계(설계 11.14 의 2)
                 "잠시 뒤 문제가 발생했습니다": '상용구 오류 "문제가 발생했습니다"', "오류가 발생했습니다": '상용구 오류 "오류가 발생했습니다"',
                 "문제가 생겼습니다": '상용구 오류 "문제가 생겼습니다"', "당신의 계정": '2인칭 "당신의"', "당신이 고른": '2인칭 "당신"',
                 "성공적으로 저장했어요": '상투어 "성공적으로"', "다양한 기능": '상투어 "다양한"', "효율적인 관리": '상투어 "효율적"',
                 "원활한 결제": '상투어 "원활"', "한눈에 보는 요약": '상투어 "한눈에"', "손쉽게 시작": '상투어 "손쉽게"',
                 "간편하게 결제": '상투어 "간편하게"', "올인원 앱": '상투어 "올인원"', "차원이 다른 속도": '상투어 "차원이 다른"',
                 "정보를 가지고 있어요": '번역투 "가지고 있"', "관리자에 의해 지워졌어요": '번역투 "에 의해"',
                 "화면에서의 동작": '번역투 "에서의"', "앱으로의 이동": '번역투 "으로의"', "시사하는 바가 크다": '번역투 "시사하는 바"',
                 "주목할 만하다": '번역투 "주목할 만하"'}
```

**Edit** `herdr-team/tests/test_textlint.py`

```python
    def test_long_line_excerpt_is_cut(self):
        text = 'const a = "' + "가" * 80 + '됬";'
        item = self.found(text)[0]
        snippet = item.split("(", 1)[1][:-1]
        self.assertEqual(len(snippet), 60)
        self.assertTrue(snippet.endswith("…"))
```

```python
    def test_excerpt_is_around_the_match(self):
        # 설계 11.14 의 2: 줄 앞 60자 대신 일치 위치 앞뒤 30자(시안 HTML 의 수천 자 줄에서 위치를 찾게)
        text = 'const a = "' + "가" * 80 + '됬";'
        self.assertEqual(self.found(text), ['src/app.tsx:1: 오탈자 "됬"(…' + "가" * 30 + '됬";)'])
        text = 'x = "' + "가" * 40 + "됬" + "나" * 40 + '"'
        self.assertEqual(self.found(text)[0].split("(", 1)[1], "…" + "가" * 30 + "됬" + "나" * 30 + "…)")
        # Markdown 의 인라인 코드는 같은 길이의 공백으로 바꿔 보므로 발췌 위치가 맞다
        self.assertEqual(self.found("앞 `코드` 됬다\n", "docs/user/a.md"), ['docs/user/a.md:1: 오탈자 "됬"(앞 `코드` 됬다)'])

    def test_repeat_counts_per_file(self):
        text = ('a = "A가 아니라 B예요";\nb = "C가 아니라 D예요";\n' + 'c = "카드를 통해 결제해요";\n' * 2
                + 'd = "앱을 통해 받아요";\n' + 'e = "결제에 대해 알려요";\n' * 2)
        self.assertEqual(self.found(text), ['src/app.tsx:1: 반복 "아니라" 2번(줄: 1, 2)',
                                            'src/app.tsx:3: 반복 "을 통해·를 통해" 3번(줄: 3, 4, 5)'])
        self.assertEqual(self.found('a = "이것이다 저것이다";\nb = "그것입니다";\n'),
                         ['src/app.tsx:1: 반복 "것이다·것입니다" 3번(줄: 1, 2)'])
        self.assertEqual(self.found('a = "에 대해 에 대해";\nb = "아니라";\n'), [])  # 문턱 아래

    def test_data_sample_content_is_not_checked(self):
        text = ('<li data-sample>사용자 댓글: 완료됬어요\n여러 줄 됬어요</li>\n<li>저장됬어요</li>\n'
                '<div data-sample="1"><div>안쪽됬</div>바깥됬</div>\n<p data-sample />자기 닫음됬\n'
                '<p data-sample-id="x">표시 아님됬</p>\n')
        found = self.found(text, "docs/design/screens/home/index.html")
        self.assertEqual([x.split(":", 2)[1] for x in found], ["3", "4", "5", "6"])
        self.assertIn('오탈자 "됬"(…ta-sample="1"><div>안쪽됬</div>바깥됬</div>)', found[1])  # 발췌는 줄 원문이다
        self.assertEqual(len(self.found("<p data-sample>됬</p>\n", "docs/user/a.md")), 1)  # Markdown 은 보지 않는다
        self.assertEqual(textlint.mask_samples("<b data-sample>가\n나</b>끝"), "<b data-sample> \n </b>끝")
        self.assertEqual(textlint.mask_samples("<b data-sample>닫지 않음"), "<b data-sample>닫지 않음")
        # 속성 이름이 정확히 data-sample 일 때만이다. 속성 값 안의 글자는 이름이 아니다(Codex 계획 리뷰 p13c r2)
        real = ('<p class="data-sample">저장됬어요</p>\n<p title=\'data-sample 예시\'>저장됬어요</p>\n'
                '<p data-sample-id="x">저장됬어요</p>\n<Item onClick={() => a > b} data-sample>가짜됬</Item>\n'
                '<img data-sample src="a.png">이미지 뒤됬\n<li {...props} DATA-SAMPLE>가짜됬</li>\n')
        found = self.found(real, "src/app.tsx")
        self.assertEqual([x.split(":", 2)[1] for x in found], ["1", "2", "3", "5"])

    def test_sample_scan_stays_linear(self):
        # 빈 요소와 닫히지 않은 요소가 많아도 닫는 태그를 찾으려 파일 끝까지 다시 훑지 않는다(Codex 계획 리뷰 p13c r2)
        import time
        voids = '<img data-sample src="avatar.png"><p>저장했어요</p>\n' * 25000
        unclosed = "<div data-sample><p>저장했어요</p>\n" * 25000
        for text in (voids, unclosed):
            start = time.monotonic()
            rows = textlint.visible_lines("docs/design/screens/home/index.html", text)
            self.assertLess(time.monotonic() - start, 1.5, text[:20])
            self.assertEqual(len(rows), 25000)  # 빈 요소·닫히지 않은 요소는 아무것도 지우지 않는다

    def test_long_lines_stay_linear(self):
        # 마침표 없는 긴 줄에서 복붙 문장 찾기와 종결 낱말 찾기가 제곱 시간이 되지 않는다(Codex 계획 리뷰 p13c r1)
        import time
        spaced = "a = '" + "가나다 라마바 " * 25000 + "'"  # 글자 20만(약 200 KB 이상), 마침표 없음
        solid = "b = '" + "가" * 200000 + "x"  # 띄어 쓰지 않은 한글, 따옴표로 닫지 않음
        for line in (spaced, solid):
            start = time.monotonic()
            rows = textlint.added_rows("src/app.tsx", line, {line})
            textlint.scan_rows("src/app.tsx", rows, [])
            self.assertEqual(textlint.copies([("src/app.tsx", rows)]), [])
            self.assertEqual(textlint.labels([("src/app.tsx", rows)]), [])
            self.assertLess(time.monotonic() - start, 1.5, line[:10])
```

**Edit** `herdr-team/tests/test_textlint.py`

```python
    def test_diff_lines(self):
```

```python
    def test_copied_sentences_and_label_forms_across_files(self):
        same = "변경 내용은 저장하면 바로 적용됩니다."
        a = self.commit("src/a.tsx", "".join(f'a{n} = "{same}";\n' for n in range(3)) + "<button>저장</button>\n",
                        "[T-001] a")
        b = self.commit("src/b.tsx", "".join(f'b{n} = "{same}";\n' for n in range(2)) + "<button>저장하기</button>\n",
                        "[T-001] b")
        self.assertEqual(text_lint(self.proj, ["src/a.tsx", "src/b.tsx"], [a, b]),
                         [f'src/a.tsx:1: 복붙 "{same}" 5번',
                          'src/b.tsx:3: 라벨 형태 혼용 "저장"·"저장하기"(처음 "저장": src/a.tsx:4)'])
        self.assertEqual(text_lint(self.proj, ["src/a.tsx"], [a]), [])  # 한 파일에 세 번, 라벨은 한 형태
        self.assertEqual(textlint.copies([("x.md", [(1, "", "짧다. 아주 짧은 문장.")] * 6)]), [])  # 10자 미만

    def test_one_megabyte_changed_file(self):
        import time
        line = "<p>저장하면 바로 적용돼요. 다음 화면으로 가요</p>\n"
        n = 1_000_000 // len(line.encode("utf-8"))
        sha = self.commit("src/big.html", line * n, "[T-001] 큰 화면")
        start = time.monotonic()
        found = text_lint(self.proj, ["src/big.html"], [sha])
        self.assertLess(time.monotonic() - start, 1.5)
        self.assertEqual(found, [f'src/big.html:1: 복붙 "저장하면 바로 적용돼요." {n}번'])

    def test_added_text_files_for_the_precheck(self):
        sha = self.commit("src/a.tsx", '// 한글 주석\nconst a = 1;\n', "[T-001] 주석")
        other = self.commit("src/b.tsx", '<p data-sample>가짜 댓글</p>\n<p>저장</p>\n', "[T-001] 화면")
        self.assertEqual(textlint.added_text_files(self.proj, ["src/a.tsx", "src/b.tsx"], [sha, other]), ["src/b.tsx"])
        self.commit("src/c.tsx", '<p data-sample>가짜 댓글</p>\n', "[T-001] 표본만")
        self.assertEqual(textlint.added_text_files(self.proj, ["src/c.tsx"], [self.head()]), [])

    def test_diff_lines(self):
```

**Edit** `herdr-team/tests/test_quality.py`

```python
import unittest

from tests.helpers import ROOT, VALID_BODY
```

```python
import re
import unittest

from tests.helpers import ROOT, VALID_BODY
```

**Edit** `herdr-team/tests/test_quality.py`

```python
class ReproTaskTest(unittest.TestCase):
```

```python
class WriterChecklistTest(unittest.TestCase):
    """작성자 점검표(설계 11.14 의 3), 사람 글 표시, text-rules §4 더하기(11.14 의 1)."""

    def test_writer_checklist(self):
        for role in ("developer", "designer"):
            rules = section(read(f"roles/{role}.md"), "문구 규칙")
            for needle in ('§4 "항상 고친다" 항목마다 한 줄', "`<번호>. 지킴`", "`<번호>. 고침: <위치>`", "`<번호>. 해당 없음`",
                           "§1 보존을 지켰는지", "리뷰 사전 검사가 돌려보낸다"):
                self.assertIn(needle, rules, role)
        self.assertIn("`data-sample` 속성을 붙인다", section(read("roles/designer.md"), "문구 규칙"))

    def test_text_rules_section_four(self):
        text = read("text-rules.md")
        four = section(text, "§4 AI 티·번역투")
        always = four[four.index("항상 고친다:"):four.index("반복될 때만")]
        self.assertEqual([int(n) for n in re.findall(r"(?m)^(\d+)\. ", always)], list(range(1, 13)))
        for needle in ('"문제가 발생했습니다"', "한눈에, 손쉽게, 간편하게, 올인원, 차원이 다른, 성공적으로, 다양한, 효율적, 원활",
                       '2인칭 "당신"', "같은 문장을 여러 곳에 복사하지 않는다"):
            self.assertIn(needle, always)
        repeat = four[four.index("반복될 때만"):four.index("고치지 않는다(과교정 방지)")]
        for needle in ('"~할 수 있다"(정책 문서의 권한·가능성 표현은 §1 의 3번이 우선한다)', '"가지고 있다"', '"~에 의해"',
                       '"~에서의·~으로의"'):
            self.assertIn(needle, repeat)
        self.assertIn("k-skill `korean-humanizer`(https://github.com/NomaDamas/k-skill, MIT)", section(text, "출처"))


class ReproTaskTest(unittest.TestCase):
```

- [ ] **Step 2: 시험이 실패하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_textlint tests.test_quality.WriterChecklistTest)`
Expected: FAIL·ERROR 10개(30개 실행): `ScanTest` 다섯(새 범주, 발췌, 반복 집계, 사람 글 표시, 긴 줄 시간), `GitTextLintTest` 셋(복붙·라벨 혼용, 1 MB 파일, 사전 검사용 파일), `WriterChecklistTest` 둘. `ScanTest.test_sample_scan_stays_linear` 는 사람 글 표시가 아직 없어 지금도 통과한다.

- [ ] **Step 3: 구현한다**

**Edit** `herdr-team/lib/hteam/textlint.py`

```python
SNIPPET = 60
HANGUL = re.compile("[가-힣]")
```

```python
SIDE = 30  # 발췌: 일치 위치 앞뒤 글자 수(설계 11.14 의 2. 시안 HTML 의 긴 줄에서 위치를 찾게)
HANGUL = re.compile("[가-힣]")
# 사람 글 표시(설계 11.14 의 2): 이 확장자에서 속성 이름이 정확히 `data-sample` 인 요소의 내용(같은 이름의 처음 닫는 태그
# 앞까지)은 모든 검사에서 뺀다. 시안 속 가짜 사용자 댓글 같은 글이다. 여는 태그는 속성 단위로 읽어 따옴표·중괄호 값 안의 글을
# 속성 이름으로 보지 않는다. 내용이 없는 빈 요소와 스스로 닫는 태그는 건너뛴다(Codex 계획 리뷰 p13c r2)
SAMPLE_SUFFIXES = frozenset({".html", ".jsx", ".tsx", ".vue", ".svelte"})
SAMPLE_ATTR = "data-sample"
VOID_TAGS = frozenset({"area", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"})
TAG_WINDOW = 2000  # 여는 태그 하나를 읽는 최대 글자 수(닫히지 않은 따옴표에서 파일 끝까지 읽지 않게)
_OPEN_TAG = re.compile(r"<([A-Za-z][\w.:-]*)(?=[\s/>])")
_CLOSE_TAG = re.compile(r"</([A-Za-z][\w.:-]*)\s*>")
_TAG_SPACE = re.compile(r"\s*")
_ATTR_NAME = re.compile(r"[^\s\"'=<>/`{}]+")
_ATTR_VALUE = re.compile(r"\s*=\s*(?:\"[^\"]*\"|'[^']*'|\{[^{}]*\}|[^\s\"'=<>`{}]+)")
_SPREAD = re.compile(r"\{[^{}]*\}")  # JSX 의 {...props}
```

**Edit** `herdr-team/lib/hteam/textlint.py`

```python
import re
from pathlib import Path

from . import gitio
```

```python
import bisect
import re
from pathlib import Path

from . import gitio
```

**Edit** `herdr-team/lib/hteam/textlint.py`

```python
    ("번역투", re.compile(r"에 있어서|에 있어(?=\s)")),
    # 영문은 낱말 경계(영문·숫자·_ 가 붙지 않음)만. unlock·elevate 는 코드 식별자·i18n 키와 겹쳐 넣지 않는다
    ("상투어", re.compile("혁신적|획기적|최적의|극대화|차세대|시너지|패러다임|게임 체인저"
                       "|(?<![A-Za-z0-9_])(?:seamlessly|seamless|empower)(?![A-Za-z0-9_])", re.I)),
```

```python
    ("번역투", re.compile(r"에 있어서|에 있어(?=\s)|가지고 있|에 의해|에서의|으로의|시사하는 바|주목할 만하")),
    # 영문은 낱말 경계(영문·숫자·_ 가 붙지 않음)만. unlock·elevate 는 코드 식별자·i18n 키와 겹쳐 넣지 않는다
    ("상투어", re.compile("혁신적|획기적|최적의|극대화|차세대|시너지|패러다임|게임 체인저|성공적으로|다양한|효율적|원활|한눈에"
                       "|손쉽게|간편하게|올인원|차원이 다른"
                       "|(?<![A-Za-z0-9_])(?:seamlessly|seamless|empower)(?![A-Za-z0-9_])", re.I)),
    ("상용구 오류", re.compile("문제가 발생했습니다|오류가 발생했습니다|문제가 생겼습니다")),  # 무엇이 잘못됐는지 없는 오류 문구
    ("2인칭", re.compile("당신의?")),
```

**Edit** `herdr-team/lib/hteam/textlint.py`

```python
# 종결로 보는 낱말: 한글 낱말 + 선택적 문장 부호 + 공백 + (따옴표·백틱·`<`·`|` 또는 줄 끝)
_ENDING = re.compile(r"([가-힣]+)[.!?…~]?\s*(?=[\"'`<|]|$)")
```

```python
# 종결로 보는 낱말: 한글 낱말 + 선택적 문장 부호 + 공백 + (따옴표·백틱·`<`·`|` 또는 줄 끝). 낱말 머리에서만 시작한다(앞이 한글이면
# 같은 낱말의 뒷부분이라 결과가 같다). 띄어 쓰지 않은 긴 한글 줄에서 시작점마다 다시 훑지 않게 한다
_ENDING = re.compile(r"(?<![가-힣])([가-힣]+)[.!?…~]?\s*(?=[\"'`<|]|$)")
```

**Edit** `herdr-team/lib/hteam/textlint.py`

```python
_RULE_ROW = re.compile(r":?-+:?")


def excerpt(line: str) -> str:
    """공백을 하나로 줄인 줄 전체를 60자까지(넘으면 59자 + `…`)."""
    text = " ".join(line.split())
    return text if len(text) <= SNIPPET else text[:SNIPPET - 1] + "…"
```

```python
_RULE_ROW = re.compile(r":?-+:?")
# 반복 집계(설계 11.14 의 2): 파일마다 추가한 줄 전체에서 (이름, 정규식, 문턱) 이상이면 범주마다 한 줄
REPEATS = (("아니라", re.compile("아니라"), 2), ("을 통해·를 통해", re.compile("[을를] 통해"), 3),
           ("에 대해", re.compile("에 대해"), 3), ("것이다·것입니다", re.compile("것이다|것입니다"), 3))
LINES_SHOWN = 5
# 복붙(설계 11.14 의 2): 따옴표·태그·중괄호·`|` 로 나눈 조각을 다시 마침표로 나눈, 마침표로 끝나는 10자 이상의 문장이 바뀐
# 파일들 전체에서 5번 이상. 긴 줄에서도 한 번 훑고 끝나게 정규식 검색이 아니라 나누기로 찾는다(Codex 계획 리뷰 p13c r1)
_SENTENCE_BREAK = re.compile(r"[\"'`<>{}|]")
COPY_MIN_CHARS = 10
COPY_MIN_TIMES = 5
COPY_SHOWN = 40
# 라벨 형태 혼용(설계 11.14 의 2): 따옴표 안 값과 태그 사이 글 가운데 10자 이하
_LABEL = re.compile(r"\"([^\"\n]{1,10})\"|'([^'\n]{1,10})'|>([^<>\n]{1,10})<")
LABEL_MAX = 10


def excerpt(line: str, start: int, end: int) -> str:
    """발췌: 줄의 일치 위치(start–end) 앞뒤 SIDE 자. 잘린 쪽에 `…` 를 붙이고 공백을 하나로 줄인다."""
    a, b = max(0, start - SIDE), min(len(line), end + SIDE)
    text = " ".join(line[a:b].split())
    return ("…" if line[:a].strip() else "") + text + ("…" if line[b:].strip() else "")


def open_tag(text: str, name_end: int, limit: int) -> tuple[int, bool, bool] | None:
    """여는 태그(이름 뒤 name_end 부터, limit 앞까지)를 속성 단위로 읽는다: (태그 끝 다음 위치, 스스로 닫는가, 이름이 정확히
    SAMPLE_ATTR 인 속성이 있는가). 따옴표·중괄호 값과 `{...props}` 는 통째로 건너뛴다. limit 안에서 `>` 를 찾지 못하거나 읽을
    수 없는 글(겹친 중괄호 값 등)이 나오면 None."""
    i, sample = name_end, False
    while True:
        i = _TAG_SPACE.match(text, i, limit).end()
        if i >= limit:
            return None
        if text[i] == ">":
            return i + 1, False, sample
        if text.startswith("/>", i):
            return i + 2, True, sample
        spread = _SPREAD.match(text, i, limit) if text[i] == "{" else None
        if spread:
            i = spread.end()
            continue
        name = _ATTR_NAME.match(text, i, limit)
        if name is None:
            return None
        sample = sample or name.group(0).lower() == SAMPLE_ATTR
        value = _ATTR_VALUE.match(text, name.end(), limit)
        i = value.end() if value else name.end()


def mask_samples(text: str) -> str:
    """사람 글 표시: 속성 이름이 정확히 `data-sample` 인 요소의 내용(여는 태그 끝부터 같은 이름의 처음 닫는 태그 앞까지. 같은
    태그가 안에 겹쳐도 처음 닫는 태그까지)을 공백으로 바꾼다. 줄바꿈과 길이는 그대로다. 빈 요소(VOID_TAGS)·스스로 닫는 태그·
    닫는 태그가 없는 요소는 그대로 둔다. 닫는 태그 위치는 이름마다 한 번 모아 이분 탐색하므로 닫히지 않은 요소가 많아도 파일을
    다시 훑지 않는다(줄 길이에 비례)."""
    closes: dict[str, list[int]] = {}
    for m in _CLOSE_TAG.finditer(text):
        closes.setdefault(m.group(1).lower(), []).append(m.start())
    out: list[str] = []
    pos = 0
    for m in _OPEN_TAG.finditer(text):
        name = m.group(1).lower()
        if m.start() < pos or name in VOID_TAGS:  # 이미 지운 내용 안의 태그, 내용이 없는 빈 요소
            continue
        tag = open_tag(text, m.end(), min(len(text), m.start() + TAG_WINDOW))
        if tag is None or tag[1] or not tag[2]:
            continue
        starts = closes.get(name, [])
        k = bisect.bisect_left(starts, tag[0])
        if k == len(starts):
            continue
        out += [text[pos:tag[0]], re.sub(r"[^\n]", " ", text[tag[0]:starts[k]])]
        pos = starts[k]
    out.append(text[pos:])
    return "".join(out)
```

**Edit** `herdr-team/lib/hteam/textlint.py`

```python
    """검사할 줄 (줄 번호, 줄 원문, 검사할 글). 코드 확장자는 주석으로 시작하는 줄, HTML·XML 은 `<!--` 로 시작하는 줄,
    Markdown 은 펜스 코드 블록(specs.code_lines: 펜스 문자와 길이를 따르고 앞 공백은 보지 않는다. 네 백틱 펜스 안의 세 백틱
    예시도 코드다)을 빼고 인라인 코드를 지운 글을 본다(`* 글머리` 는 남는다). 한글이 없는 줄은 뺀다."""
    suffix = Path(rel).suffix.lower()
    lines = text.split("\n")
    code = code_lines(lines, any_indent=True) if suffix in MARKDOWN else [False] * len(lines)
    out: list[tuple[int, str, str]] = []
    for number, (line, fenced) in enumerate(zip(lines, code), 1):
        head, body = line.lstrip(), line
        if fenced:
            continue
        if suffix in MARKDOWN:
            body = _INLINE.sub(" ", line)
```

```python
    """검사할 줄 (줄 번호, 줄 원문, 검사할 글). `.html .jsx .tsx .vue .svelte` 는 먼저 사람 글 표시 요소의 내용을 지운다
    (mask_samples). 코드 확장자는 주석으로 시작하는 줄, HTML·XML 은 `<!--` 로 시작하는 줄, Markdown 은 펜스 코드 블록
    (specs.code_lines: 펜스 문자와 길이를 따르고 앞 공백은 보지 않는다. 네 백틱 펜스 안의 세 백틱 예시도 코드다)을 빼고 인라인
    코드를 같은 길이의 공백으로 바꾼 글을 본다(`* 글머리` 는 남는다). 검사할 글은 줄 원문과 길이가 같다(발췌가 일치 위치를
    쓴다). 한글이 없는 줄은 뺀다."""
    suffix = Path(rel).suffix.lower()
    lines = text.split("\n")
    shown = mask_samples(text).split("\n") if suffix in SAMPLE_SUFFIXES else lines
    code = code_lines(lines, any_indent=True) if suffix in MARKDOWN else [False] * len(lines)
    out: list[tuple[int, str, str]] = []
    for number, (line, body, fenced) in enumerate(zip(lines, shown, code), 1):
        head = body.lstrip()
        if fenced:
            continue
        if suffix in MARKDOWN:
            body = _INLINE.sub(lambda m: " " * len(m.group(0)), body)
```

**Edit** `herdr-team/lib/hteam/textlint.py`

```python
def _banned(body: str, glossary: list[tuple[str, list[str]]]) -> list[tuple[int, str]]:
    """금지 표기 (위치, 지적). 어느 행이든 쓰는 표기의 일치 구간이 그 자리를 다 덮으면 건너뛴다(회원가입 안의 가입)."""
    covers = [(m.start(), m.end()) for pref, _ in glossary for m in re.finditer(re.escape(pref), body)]
    found = []
    for pref, banned in glossary:
        for term in banned:
            for m in re.finditer(re.escape(term), body):
                if not any(a <= m.start() and m.end() <= b for a, b in covers):
                    found.append((m.start(), f'금지 표기 "{term}"→"{pref}"'))
    return found
```

```python
def _banned(body: str, glossary: list[tuple[str, list[str]]]) -> list[tuple[int, int, str]]:
    """금지 표기 (시작, 끝, 지적). 어느 행이든 쓰는 표기의 일치 구간이 그 자리를 다 덮으면 건너뛴다(회원가입 안의 가입)."""
    covers = [(m.start(), m.end()) for pref, _ in glossary for m in re.finditer(re.escape(pref), body)]
    found = []
    for pref, banned in glossary:
        for term in banned:
            for m in re.finditer(re.escape(term), body):
                if not any(a <= m.start() and m.end() <= b for a, b in covers):
                    found.append((m.start(), m.end(), f'금지 표기 "{term}"→"{pref}"'))
    return found
```

**Edit** `herdr-team/lib/hteam/textlint.py`

```python
def scan(rel: str, text: str, added: set[str], glossary: list[tuple[str, list[str]]]) -> list[str]:
    """한 파일의 지적(상한 없음). 검사할 줄 가운데 내용이 added(이 태스크가 추가한 줄)에 있는 줄만 지금 줄 번호로 본다.
    순서는 (줄 번호, 줄 안 위치)이고 높임법 섞임은 그 줄의 다른 지적들 뒤다."""
    rows = [(n, line, body) for n, line, body in visible_lines(rel, text) if line in added]
    found: list[tuple[int, float, str]] = []
    for number, line, body in rows:
        hits = [(m.start(), f'{name} "{m.group(0)}"') for name, rx in CATEGORIES for m in rx.finditer(body)]
        hits += _banned(body, glossary)
        found += [(number, pos, f"{rel}:{number}: {what}({excerpt(line)})")
                  for pos, what in sorted(hits, key=lambda h: h[0])]
    mixed = _mixed(rel, [(n, ending_styles(body)) for n, _, body in rows])
    if mixed:
        found.append((mixed[0], float("inf"), mixed[1]))
    return [item for _, _, item in sorted(found, key=lambda f: (f[0], f[1]))]
```

```python
def _repeats(rel: str, rows: list[tuple[int, str, str]]) -> list[tuple[int, str]]:
    """반복 집계(REPEATS): 문턱 이상이면 (첫 줄, `<파일>:<첫 줄>: 반복 "<이름>" N번(줄: a, b, …)`). 줄 번호는 5개까지."""
    out = []
    for name, rx, limit in REPEATS:
        at = [n for n, _, body in rows for _ in rx.finditer(body)]
        if len(at) >= limit:
            nums = list(dict.fromkeys(at))
            shown = ", ".join(map(str, nums[:LINES_SHOWN])) + (", …" if len(nums) > LINES_SHOWN else "")
            out.append((at[0], f'{rel}:{at[0]}: 반복 "{name}" {len(at)}번(줄: {shown})'))
    return out


def added_rows(rel: str, text: str, added: set[str]) -> list[tuple[int, str, str]]:
    """검사할 줄 가운데 내용이 added(이 태스크가 추가한 줄)에 있는 줄(지금 줄 번호)."""
    return [(n, line, body) for n, line, body in visible_lines(rel, text) if line in added]


def scan_rows(rel: str, rows: list[tuple[int, str, str]], glossary: list[tuple[str, list[str]]]) -> list[str]:
    """한 파일의 지적(상한 없음). 순서는 (줄 번호, 줄 안 위치)이고, 파일 단위 지적(반복 집계, 높임법 섞임)은 그 첫 줄의 다른
    지적들 뒤다. 발췌는 일치 위치 앞뒤(excerpt)."""
    found: list[tuple[int, float, int, str]] = []
    for number, line, body in rows:
        hits = [(m.start(), m.end(), f'{name} "{m.group(0)}"') for name, rx in CATEGORIES for m in rx.finditer(body)]
        hits += _banned(body, glossary)
        found += [(number, start, 0, f"{rel}:{number}: {what}({excerpt(line, start, end)})")
                  for start, end, what in sorted(hits, key=lambda h: h[0])]
    tail = _repeats(rel, rows)
    mixed = _mixed(rel, [(n, ending_styles(body)) for n, _, body in rows])
    if mixed:
        tail.append(mixed)
    found += [(first, float("inf"), k, item) for k, (first, item) in enumerate(tail)]
    return [item for *_, item in sorted(found, key=lambda f: (f[0], f[1], f[2]))]


def scan(rel: str, text: str, added: set[str], glossary: list[tuple[str, list[str]]]) -> list[str]:
    """한 파일의 지적(scan_rows(added_rows(…)))."""
    return scan_rows(rel, added_rows(rel, text, added), glossary)


def sentences(body: str) -> list[str]:
    """검사할 글의 문장 후보: 따옴표·태그·중괄호·`|` 로 나눈 조각마다 마침표로 나눠 마침표로 끝나는 것(마침표를 붙여서). 나누기만
    하므로 줄 길이에 비례한다."""
    out = []
    for segment in _SENTENCE_BREAK.split(body):
        parts = segment.split(".")
        out += [part + "." for part in parts[:-1] if part]
    return out


def copies(files_rows: list[tuple[str, list[tuple[int, str, str]]]]) -> list[str]:
    """복붙: 추가한 줄의 문장(sentences, 공백을 하나로 줄여 10자 이상, 한글 포함)이 바뀐 파일들 전체에서 5번 이상 같으면 문장마다
    한 줄 `<처음 파일>:<줄>: 복붙 "<문장 40자>" N번`(처음 나온 차례)."""
    seen: dict[str, list] = {}
    for rel, rows in files_rows:
        for n, _, body in rows:
            for piece in sentences(body):
                sentence = " ".join(piece.split())
                if len(sentence) >= COPY_MIN_CHARS and HANGUL.search(sentence):
                    seen.setdefault(sentence, [f"{rel}:{n}", 0])[1] += 1
    out = []
    for sentence, (where, times) in seen.items():
        if times >= COPY_MIN_TIMES:
            shown = sentence if len(sentence) <= COPY_SHOWN else sentence[:COPY_SHOWN - 1] + "…"
            out.append(f'{where}: 복붙 "{shown}" {times}번')
    return out


def labels(files_rows: list[tuple[str, list[tuple[int, str, str]]]]) -> list[str]:
    """라벨 형태 혼용: 추가한 줄의 따옴표 안 값과 태그 사이 글 가운데 10자 이하(한글 포함)를 모아 `X` 와 `X하기` 가 함께
    있으면 한 줄 `<X하기 의 처음 위치>: 라벨 형태 혼용 "X"·"X하기"(처음 "X": <위치>)`."""
    first: dict[str, str] = {}
    for rel, rows in files_rows:
        for n, _, body in rows:
            for m in _LABEL.finditer(body):
                value = next(g for g in m.groups() if g is not None).strip()
                if value and len(value) <= LABEL_MAX and HANGUL.search(value):
                    first.setdefault(value, f"{rel}:{n}")
    out = []
    for value, where in first.items():
        base = value[:-2].strip()
        if value.endswith("하기") and base and base in first:
            out.append(f'{where}: 라벨 형태 혼용 "{base}"·"{value}"(처음 "{base}": {first[base]})')
    return out
```

**Edit** `herdr-team/lib/hteam/textlint.py`

```python
    """문구 대상마다 리뷰 대상 커밋(shas)이 추가한 줄의 지적. 용어집은 한 번 읽는다. diff 를 읽지 못한 파일(None)은
    건너뛴다. MAX_FINDINGS(50)를 넘으면 마지막 항목이 `… 외 N건`."""
    glossary = load_glossary(root)
    found: list[str] = []
    for rel in targets(root, files):
        added = gitio.added_lines(root, shas, rel)
        text = read_source(root, rel)
        if added is not None and text is not None:
            found += scan(rel, text, added, glossary)
    return cap(found)
```

```python
    """문구 대상마다 리뷰 대상 커밋(shas)이 추가한 줄의 지적(파일 차례), 그 뒤에 파일들 전체의 복붙(copies)과 라벨 형태
    혼용(labels). 용어집은 한 번 읽는다. diff 를 읽지 못한 파일(None)은 건너뛴다. MAX_FINDINGS(50)를 넘으면 마지막 항목이
    `… 외 N건`."""
    glossary = load_glossary(root)
    found: list[str] = []
    files_rows: list[tuple[str, list[tuple[int, str, str]]]] = []
    for rel in targets(root, files):
        added = gitio.added_lines(root, shas, rel)
        text = read_source(root, rel)
        if added is not None and text is not None:
            rows = added_rows(rel, text, added)
            found += scan_rows(rel, rows, glossary)
            files_rows.append((rel, rows))
    return cap(found + copies(files_rows) + labels(files_rows))
```

**Edit** `herdr-team/templates/text-rules.md`

```markdown
8. 이모지 장식은 `.herdr-team/design-rules.md` §1 의 1번을 따른다.
```

```markdown
8. 이모지 장식은 `.herdr-team/design-rules.md` §1 의 1번을 따른다.
9. 상용구 오류 문구: 무엇이 잘못됐는지 없는 "문제가 발생했습니다", "오류가 발생했습니다", "문제가 생겼습니다" 같은 문구. §3 의 4번처럼 무엇이 잘못됐는지와 사용자가 할 일을 쓴다.
10. UI 상투어: 한눈에, 손쉽게, 간편하게, 올인원, 차원이 다른, 성공적으로, 다양한, 효율적, 원활. 무엇을 어떻게 하는지 구체적으로 쓰거나 뺀다("성공적으로 저장했어요"→"저장했어요").
11. 2인칭 "당신"("당신의"). 호칭은 voice.md 를 따르고, 정하지 않았으면 뺀다.
12. 같은 문장을 여러 곳에 복사하지 않는다. 자리마다 그 자리에 맞게 쓰거나 한 곳에만 둔다.
```

**Edit** `herdr-team/templates/text-rules.md`

```markdown
연결어미("-며", "-고", "-지만", "-면서", "-아서/-어서") 바로 뒤 쉼표(긴 문장을 끊어 읽어야 하면 남긴다).
```

```markdown
연결어미("-며", "-고", "-지만", "-면서", "-아서/-어서") 바로 뒤 쉼표(긴 문장을 끊어 읽어야 하면 남긴다), "~할 수 있다"(정책 문서의 권한·가능성 표현은 §1 의 3번이 우선한다), "가지고 있다", "~에 의해", "~에서의·~으로의".
```

**Edit** `herdr-team/templates/text-rules.md`

```markdown
UI 라벨·오류 메시지·i18n 변수 규칙은 orca-team 이 더했다. herdr-team 은 orca-team 0.5.0 에서 옮겼다.
```

```markdown
UI 라벨·오류 메시지·i18n 변수 규칙은 orca-team 이 더했다. herdr-team 은 orca-team 0.5.0 에서 옮겼다. §4 "반복될 때만" 의 "~할 수 있다", "가지고 있다", "~에 의해", "~에서의·~으로의" 는 k-skill `korean-humanizer`(https://github.com/NomaDamas/k-skill, MIT)의 AI 티 분류에서 골라 더했고, §4 "항상 고친다" 의 9–12번은 herdr-team 이 사용 프로젝트의 리뷰를 보고 더했다.
```

**Edit** `herdr-team/templates/roles/developer.md`

```markdown
- 그런 태스크의 보고서 이번 라운드 `## rN` 절 안에 `### 문구 점검` 소절을 둔다: text-rules §1–§4 를 지켰는지, 예외와 근거, 용어집에 없는 새 핵심 용어.
```

```markdown
- 그런 태스크의 보고서 이번 라운드 `## rN` 절 안에 `### 문구 점검` 소절(작성자 점검표)을 둔다: text-rules §1–§4 를 지켰는지를 §4 "항상 고친다" 항목마다 한 줄(`<번호>. 지킴`·`<번호>. 고침: <위치>`·`<번호>. 해당 없음`)과 §1 보존을 지켰는지로 적고, 예외와 근거, 용어집에 없는 새 핵심 용어를 적는다. 문구 대상 파일에 한글 줄을 더한 태스크에 이 소절이 없으면 리뷰 사전 검사가 돌려보낸다.
```

**Edit** `herdr-team/templates/roles/designer.md`

```markdown
- 문구가 있는 화면을 만들거나 바꾼 태스크는 보고서 이번 라운드 `## rN` 절 안에 `### 문구 점검` 소절을 둔다: text-rules §1–§4 를 지켰는지, 예외와 근거, 용어집에 없는 새 핵심 용어.
```

```markdown
- 문구가 있는 화면을 만들거나 바꾼 태스크는 보고서 이번 라운드 `## rN` 절 안에 `### 문구 점검` 소절(작성자 점검표)을 둔다: text-rules §1–§4 를 지켰는지를 §4 "항상 고친다" 항목마다 한 줄(`<번호>. 지킴`·`<번호>. 고침: <위치>`·`<번호>. 해당 없음`)과 §1 보존을 지켰는지로 적고, 예외와 근거, 용어집에 없는 새 핵심 용어를 적는다. 문구 대상 파일에 한글 줄을 더한 태스크에 이 소절이 없으면 리뷰 사전 검사가 돌려보낸다.
- 시안 속 가짜 사람 글(사용자 댓글·후기·채팅처럼 서비스 문구가 아닌 예시 글)은 그 글을 감싼 요소에 `data-sample` 속성을 붙인다(예 `<li data-sample>`). 문구 자동 검사가 그 요소의 내용을 보지 않는다. 라벨·버튼·안내 같은 서비스 문구에는 붙이지 않는다.
```

**Edit** `README.md`

```markdown
태스크가 추가한 줄의 의심 위치(오탈자, 이중피동, 번역투, 상투어, hedging, 챗봇 잔재, 쉼표, 용어집의 쓰지 않는 표기, 높임법 섞임)를 경고로 넣는다.
```

```markdown
태스크가 추가한 줄의 의심 위치(오탈자, 이중피동, 번역투, 상투어, 상용구 오류, 2인칭 "당신", hedging, 챗봇 잔재, 쉼표, 용어집의 쓰지 않는 표기, 높임법 섞임, 파일마다 "아니라"·"을 통해"·"에 대해"·"것이다" 반복, 여러 파일에 5번 이상 복사한 문장, "저장"·"저장하기" 같은 라벨 형태 혼용)를 경고로 넣는다(0.8.0: 발췌는 일치 위치 앞뒤 30자, `data-sample` 속성이 붙은 요소의 가짜 사람 글은 보지 않는다).
```

- [ ] **Step 4: 시험이 통과하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_textlint tests.test_quality tests.test_design_docs tests.test_review.TextSectionTest tests.test_review.TextTemplateTest tests.test_review.ReportPrecheckTest tests.test_lint tests.test_wording tests.test_rule_refs)`
Expected: `Ran 167 tests`, `OK`.

- [ ] **Step 5: 커밋한다**

```bash
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews'
git add -- herdr-team/lib/hteam/textlint.py herdr-team/templates/text-rules.md herdr-team/templates/roles/developer.md herdr-team/templates/roles/designer.md README.md herdr-team/tests/test_textlint.py herdr-team/tests/test_quality.py
git commit -m "feat(herdr-team): text-rules §4 더하기, textlint 발췌·사람 글 표시·반복·복붙·라벨 혼용, 작성자 점검표(설계 11.14)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/lib/hteam/textlint.py herdr-team/templates/text-rules.md herdr-team/templates/roles/developer.md herdr-team/templates/roles/designer.md README.md herdr-team/tests/test_textlint.py herdr-team/tests/test_quality.py
```

---

## p13c 끝

- 계획 작성 때 모든 태스크를 적용한 사본에서 `(cd herdr-team && python3 -m unittest tests.test_rule_refs tests.test_review tests.test_lint tests.test_textlint tests.test_plan)` 가 `Ran 345 tests`, `OK`(약 6분) 이었다. 구현 뒤 같은 명령을 한 번 더 돌린다.
- 전체 시험: `bash herdr-team/tests/run.sh` 를 백그라운드로 돌리고(약 22분) 끝 알림을 받는다. 그다음 `bash herdr-orch/tests/run.sh`(약 2분). 둘을 동시에 돌리지 않는다.
- 태스크마다 Codex 커밋 리뷰 지적을 처리한 수정 커밋도 같은 방식으로 리뷰한다(리뷰 수정 범위는 Global Constraints).
- 설계 13장 "13단계(품질 보완) 한계" 에 아래 "알려진 한계" 가운데 설계에 아직 없는 것을 더한다(리뷰에서 기록만 하기로 한 것도 함께). 경로 지정 커밋 `docs: 13단계 p13c 알려진 한계(설계 13장)`.
- p13d 계획(`docs/superpowers/plans/2026-11-18-herdr-team-p13d.md`)을 쓴다.

## 알려진 한계(설계 13장에 더할 후보)

- 재현 시험 표시 줄 판정은 `## Constraints` 의 줄 머리 `- 재현 시험:` 만 본다. 다른 글머리(`* 재현 시험:`)나 글머리 없는 줄은 재현 시험 태스크가 아니고, Constraints 안 펜스 코드 블록의 그 줄은 재현 시험 태스크로 친다. 메인·기획자가 손으로 쓰는 줄이라 틀리게 쓰면 사전 검사도 리뷰 기준 줄도 붙지 않는다.
- 보고서 소절 사전 검사의 조건은 대상 커밋 전체(모든 라운드의 커밋)를 본다. 수정 라운드도 이번 라운드 절에 `### 문구 점검`·`### 디자인 점검`·`### 재현 시험` 을 다시 둬야 한다(앞 라운드를 가리키는 한 줄로 된다). 문구 조건 판정이 예외로 실패하거나 그 파일의 diff 를 읽지 못하면 그 소절은 요구하지 않는다.
- developer 의 화면 파일 판정은 확장자만 본다. 화면 확장자의 시험·스토리 파일(`Btn.test.tsx`)만 바꿔도 `### 디자인 점검` 을 요구하고, `.ts`·`.js` 로 그린 화면(CSS-in-JS, 문자열 템플릿)은 요구하지 않는다(리뷰어가 본다).
- 검사 약화 의심의 줄 경고는 "내용이 같은 지금 줄" 기준이라 같은 파일에 내용이 똑같은 기존 줄이 있으면 그 줄도 잡힌다(11.7 과 같다). 글 문서(`.md .mdx .txt .rst`)와 보고서·리뷰·hteam 파일의 줄은 보지 않는다. 지운 시험은 이름으로만 견준다: 이름을 바꾼 시험은 지운 시험이고, 다른 시험 파일로 옮긴 시험은 아니다. 단언 수는 파일마다 세서 시험을 다른 파일로 옮기면 옛 파일에 "단언 줄어듦" 이 뜬다. `@Test` 다음 함수는 사이의 `@` 줄 셋까지 건너뛰어 찾는다. 지운 시험 파일은 첫 대상 커밋의 첫 부모에 있고 마지막 대상 커밋에 없는 파일이다(같은 작업 폴더의 다른 태스크가 그 사이에 만든 시험 파일을 이 태스크가 지워도 지운 파일로 본다). 바뀐 파일 목록이 이름 바꾸기를 나누므로(`--no-renames`) 옮긴 시험 파일의 옛 경로도 지운 시험 파일로 잡힌다. 리뷰 한 번에 바뀐 파일×커밋 수만큼 git 을 더 부른다(11.6 의 한계 3 과 같다). 빈 except 블록은 지금 파일의 들여쓰기로 가른다: 탭과 공백을 섞은 파일, 여러 줄에 걸친 `except (…)` 머리는 틀리거나 놓친다. `pass` 줄은 내용이 같은 줄이 많아, 이 태스크가 다른 곳에 같은 들여쓰기의 `pass` 를 더하면 그대로 둔 다른 빈 except 블록도 경고한다(내용이 같은 지금 줄 기준). `@Test` 표시 줄어듦은 파일마다 표시 줄 수만 견준다: JUnit 시험 하나를 통째로 지우면 지운 시험 줄과 표시 줄어듦 줄이 함께 나오고, 다른 표시(`@ParameterizedTest`·`@TestFactory`)는 세지 않는다.
- 리뷰 기준의 재현 시험 줄은 설계 6.6 의 2 문장에 두 가지를 더했다(5.11 의 4 와 맞춘다): 이미 실패하던 시험(묶음 테스트)을 쓴 회귀 수정이면 그 시험이 대상 커밋이 아니라 저장소에 있는지 보고, 보고서가 시험으로 재현할 수 없다고 적었으면 실패 출력 대신 그 이유와 대신 확인한 방법이 타당한지 본다. 그 판단은 리뷰어의 몫이고 사전 검사는 `### 재현 시험` 제목 줄만 본다.
- plan check 의 크기 경고는 제목의 "및"·"그리고" 를 낱말 경계 없이 찾고, 이미 적용한 태스크(plan.json)는 보지 않는다.
- textlint: 번역투에 더한 "가지고 있"·"에 의해"·"에서의"·"으로의" 는 text-rules 에서 "반복될 때만"(P3) 항목인데 경고는 한 번에도 낸다(설계 11.14 의 2 그대로, 판정은 리뷰어가 §5 로 한다). "시사하는 바"·"주목할 만하" 는 text-rules 항목이 없는 경고다. 복붙의 문장은 마침표로 끝나는 따옴표·태그·중괄호 밖 조각이라 소수점(`1.5`)에서 끊기고 `!`·`?` 로 끝나는 문장은 세지 않는다. 라벨 혼용은 `X`·`X하기` 쌍만 본다. 반복 집계·복붙·라벨 혼용은 태스크가 추가한 줄끼리만 센다(기존 줄과의 중복은 보지 않는다). `data-sample` 여는 태그는 2000자 안에서 속성 단위로 읽는다: 겹친 중괄호 값(`style={{…}}`)이나 2000자를 넘는 여는 태그는 읽지 못해 빼지 않고(그 글도 검사한다), 닫는 태그가 없으면 빼지 않는다. 태그 이름은 대소문자를 가리지 않고 짝을 찾는다(`<Item>` 과 `</item>`). 빈 요소 목록 밖의 이름에 붙은 스스로 닫지 않는 빈 태그는 같은 이름의 다음 닫는 태그까지 뺀다. 사람 글 표시는 `.htm`·Markdown 에는 걸리지 않는다(설계 11.14 의 2 의 확장자 그대로).
- 작성자 점검표(§4 "항상 고친다" 항목마다 한 줄)의 형식은 hteam 이 검사하지 않는다. 사전 검사는 `### 문구 점검` 제목 줄만 본다(13장 "보고서 소절 사전 검사" 와 같다).
- 문구 검사의 Markdown 펜스는 펜스 문자와 길이를 따르고 앞 공백은 보지 않는다(목록 안에 들여 쓴 펜스를 지금처럼 코드로 본다. 사양·보고서 절 읽기는 3칸까지). 펜스 없이 네 칸 들여 쓴 코드 블록은 지금처럼 코드로 보지 않는다.
