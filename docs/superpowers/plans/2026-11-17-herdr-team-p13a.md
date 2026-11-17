# herdr-team 13단계 p13a(실사용·기반) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 설계 15.3 의 13 가운데 p13a 를 만든다. 실사용 문제 셋(upgrade 가 직무 문서의 프로젝트 절을 지운다, watch 막기의 heredoc 오탐, `relay_env_new` 문구)을 고치고, 뒤 계획(p13b–d)이 기대는 기반(규칙 참조 시험, 프로젝트 규칙 파일, `color.py`, 획일도 측정 스크립트)을 둔다.

**Architecture:** (1) `.herdr-team/project-rules/<직무>.md` 는 프로젝트 소유 파일이다. `compose.work_spec` 이 직무 문서 뒤에 붙이고 리뷰 프롬프트가 가리킨다. `setup.upgrade` 는 직무 문서를 덮어쓰기 전에 템플릿에 없는 제목의 절을 이 파일로 옮긴다. (2) 훅의 명령 판정 셋은 `cat`·`tee` 로 글을 옮기는 heredoc 의 본문을 지운 명령을 본다. (3) `color.py` 는 색 글을 OKLCH 로 바꾸는 순수 모듈이다. (4) `scripts/design-eval/eval.py` 는 저장소 개발용 측정 스크립트다(플러그인에 넣지 않는다).

**Tech Stack:** Python 3.11+ 표준 라이브러리(re, json, math, colorsys, subprocess, unittest). git. 측정 스크립트만 `claude` CLI 를 부른다(시험은 부르지 않는다).

**설계 문서:** `docs/superpowers/specs/2026-11-05-herdr-team-design.md`(이하 "설계"). 범위는 15.3 의 13 의 p13a 다. 함께 볼 절: 1장 13단계 결정·확인한 것, 5.11 의 1, 9.7, 11.9(규칙 참조 시험), 11.10 끝(`color.py`), 13장 13단계 한계, 15.1·15.5. 15.3 p13a 의 1 가운데 "15.4 의 12단계 끝 줄" 은 설계 커밋에서 이미 했다.

**코드가 기준이다.** 수정은 모두 브랜치 `herdr-team-p13` 의 지금 HEAD 에 대한 부분 수정이다(코드는 main 8cd549c 와 같다). 새 모듈은 `lib/hteam/color.py` 하나, 새 시험 파일은 `tests/test_rule_refs.py`·`tests/test_project_rules.py`·`tests/test_color.py`, 새 개발 스크립트는 `scripts/design-eval/` 이다.

**편집 표기:** `**Edit** \`경로\`` 다음 두 코드 블록은 "찾을 내용"과 "바꿀 내용"이다. 찾을 내용은 적용하는 그 시점의 파일에서 정확히 한 번 나오는 부분 문자열이다(블록 끝 개행은 넣지 않는다. README·skill 처럼 긴 줄의 일부만 바꾸는 블록이 있다). 태스크 순서대로 적용한다. 새 파일은 `**Create** \`경로\`` 다음 블록 하나다.

## Global Constraints

- Python 3.11 이상, 표준 라이브러리만. 커밋 전에 바꾼 `.py` 를 `python3 -m py_compile` 로 확인한다.
- 13단계 값(그대로 쓴다):
  - 프로젝트 규칙 파일: `.herdr-team/project-rules/<직무>.md`. 워커 사양에 붙이는 줄: `아래는 이 프로젝트가 더한 <직무> 규칙이다(.herdr-team/project-rules/<직무>.md). 이 사양의 작업 규칙(소유 경로, 커밋, 보고서, done)은 바꾸지 않는다.` 읽지 못하면 오류 코드 `project_rules_unreadable`, exit 1.
  - upgrade 출력 키 `moved: [{"path", "to", "sections"}]`. moved 가 있을 때만 `next` 끝에 ` moved 의 절은 직무 문서에서 .herdr-team/project-rules/ 로 옮겼다. 두 파일을 함께 커밋한다.` 를 붙인다(없으면 `next` 는 지금 글 그대로).
  - upgrade 건너뛰기 까닭: `project-rules/<직무>.md 를 쓸 수 없다: <까닭>. 앞 upgrade 가 옮기다 멈췄으면 그 파일에 이미 옮긴 절이 있다. 확인해 커밋한 뒤 다시 한다(같은 글은 다시 덧붙이지 않는다)`.
  - `RELAY_ENV_NEW` 문구: `메인 대리 보고 설정(.claude/settings.local.json 의 HORCH_RELAY_HOME)이 이 메인 세션에 아직 들어오지 않았다. 일이 덜 몰린 때 /exit 뒤 같은 터미널에서 claude --resume 으로 다시 연다(relay_env_new)`.
  - 획일도 측정: before 기준 커밋 `8cd549c`, 결과 폴더 `.design-eval/`, 목표(설계 15.5) 240–300° ≤ 20%, 브리프 안 최소 hue 거리 60° 이상인 실행 ≥ 90%, 과용 한글 본문 글꼴 ≤ 40%, 크림+세리프+테라코타 0건, 유효 실행 ≥ 80%.
- 바꾸지 않는 것: 훅의 `RELAY_ENV_NOTICE`, `hteam_only` 판정, 직무 문서 템플릿의 내용(p13b–d 에서 바꾼다), herdr-orch 코드와 버전(버전은 p13d).
- 문서·메시지·주석은 한국어. 명령·코드 식별자는 원문.
- 저장소는 공개돼 있다. 커밋 전에 `git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews'` 가 아무것도 찾지 않아야 한다.
- 작업 브랜치 `herdr-team-p13` 에서 한다. main 에 직접 커밋하지 않는다. 커밋은 늘 경로 지정, 메시지 끝에 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- 테스트: 모듈을 `(cd herdr-team && python3 -m unittest tests.test_a tests.test_b)` 로 고른다. herdr-orch 시험은 `(cd herdr-orch && python3 -m unittest tests.test_x)`. 측정 스크립트 시험은 `python3 -m unittest discover -s scripts/design-eval -p 'test_*.py'`. 전체는 저장소 루트에서 `bash herdr-team/tests/run.sh`(약 22분), `bash herdr-orch/tests/run.sh`(약 2분). 두 전체 시험을 동시에 돌리지 않는다. 기다릴 때 sleep 폴링하지 않고 백그라운드 알림을 받는다.
- **Codex 교차 검증(CLAUDE.md):** 이 계획은 실행 전에 `scripts/codex-review.sh doc` 로 검토받는다. 각 태스크의 마지막 단계는 커밋이다. 그 뒤 `scripts/codex-review.sh commit <sha>` 를 돌리고 끝 알림을 백그라운드로 받는다(`R=.codex-reviews; end=$(( $(date +%s) + 3600 )); until [ -f $R/commit-<sha7>.exit ] || [ $(date +%s) -gt $end ]; do hc wait <주소> --timeout 600 >/dev/null 2>&1 || sleep 30; done`). 지적을 코드로 확인해 고치거나 고치지 않는 이유를 적는다. 리뷰 수정 범위는 P0·P1, 기본 경로의 P2, 회귀다. 가장자리 경우는 알려진 한계로 적는다.

## 태스크 순서와 인터페이스(모든 태스크가 이 이름·꼴을 쓴다)

순서: Task 1 relay_env_new·다시 열기 문구 → Task 2 규칙 참조 시험 → Task 3 프로젝트 규칙(워커 사양·리뷰 프롬프트·메인 규칙) → Task 4 upgrade 옮기기·`RETIRED_HEADINGS` → Task 5 훅의 heredoc → Task 6 `color.py` → Task 7 획일도 측정 스크립트.

```python
# herdr-team/lib/hteam/paths.py (Task 3)
class Project:
    def project_rules(self, role: str) -> Path      # self.team / "project-rules" / f"{role}.md"

# herdr-team/lib/hteam/compose.py (Task 3)
PROJECT_RULES_NOTE: str                              # "아래는 이 프로젝트가 더한 {role} 규칙이다(...)" (format(role=...))
def project_rules(p, role: str) -> str | None       # 없거나 공백뿐이면 None, 읽지 못하면 HteamError("project_rules_unreadable", …, FAIL)

# herdr-team/lib/hteam/setup.py (Task 4)
ROLE_NAMES: tuple[str, ...]                          # ("planner", "director", "designer", "developer", "tester")
RETIRED_HEADINGS: dict[str, tuple[str, ...]]         # 직무마다 옛 `## ` 제목. 지금은 모두 빈 튜플
def split_sections(text: str) -> tuple[str, list[tuple[str, str]]]   # (머리, [(제목 줄, 절 글)]). 펜스 안 `## ` 는 제목이 아니다
def project_sections(role: str, text: str, template: str, retired: tuple[str, ...] | None = None) -> list[tuple[str, str]]

# herdr-team/hooks/hteam_hook.py (Task 5)
def strip_heredocs(cmd: str) -> str                  # 명령 전체가 cat·tee + 따옴표 끝 표시 꼴이면 본문을 지운 명령

# herdr-team/lib/hteam/color.py (Task 6)
LCH = tuple[float, float, float]                     # (L 0–1, C, h 0–360). C < ACHROMATIC_C 면 h 는 0.0
ACHROMATIC_C = 1e-4
def from_srgb(r: float, g: float, b: float) -> LCH   # r·g·b 는 0–1
def from_hex(text: str) -> LCH | None                # "#rgb"·"#rgba"·"#rrggbb"·"#rrggbbaa"(# 없어도 된다)
def parse(text: str) -> LCH | None                   # hex·rgb()·rgba()·hsl()·hsla()·oklch() 글 하나
def hue_distance(a: float, b: float) -> float        # 원형 거리 0–180
def oklab(lch: LCH) -> tuple[float, float, float]
def delta(x: LCH, y: LCH) -> float                   # OKLab 유클리드 거리
```

p13b 가 만들고 Task 7 의 측정 스크립트가 부르는 것(이 계획에서는 만들지 않는다. `after` 판만 쓴다):

```python
# herdr-team/lib/hteam/palette.py (p13b)
def deal(seed: str, brand_hue: float | None = None) -> dict   # 설계 11.10 의 출력 JSON 과 같은 dict
# herdr-team/lib/hteam/data/overused.json (p13b): {"colors": [{"hex", "name"}], "tailwind_ramp": ["#…"], "fonts": ["…"]}
# herdr-team/templates/palette.md, fonts-ko.md (p13b)
```

---

### Task 1: relay_env_new 판정과 다시 열기 문구(설계 9.7 의 3)

`up` 이 설정을 새로 쓴 그 실행에서는 `relay_env_new` 를 내지 않는다. 설정이 이미 그 값이었는데(`same`) 환경에 없을 때만 낸다. 문구와 README·herdr-orch skill 의 "세션을 시작할 때 읽힌다" 를 고친다.

**Files:**
- Modify: `herdr-team/lib/hteam/setup.py`(`RELAY_ENV_NEW`, `_relay_notes`)
- Modify: `herdr-team/tests/test_setup.py`(`RELAY_ENV_NEW` 상수, `RelayEnvTest`)
- Modify: `herdr-team/tests/test_wording.py`(새 시험 클래스)
- Modify: `README.md`(138줄·327줄)
- Modify: `herdr-orch/lib/horch/skill.md`(70줄)

**Interfaces:**
- Consumes: 없음.
- Produces: `setup.RELAY_ENV_NEW` 새 문구. `_relay_notes` 는 `written == "same"` 일 때만 `relay_env_new` 를 본다.

- [ ] **Step 1: 시험을 먼저 고친다**

**Edit** `herdr-team/tests/test_setup.py`

```python
RELAY_ENV_NEW = ("메인 대리 보고 설정(.claude/settings.local.json 의 HORCH_RELAY_HOME)이 이 세션에 아직 없다. 설정은 세션을 "
                 "시작할 때 읽히므로 메인을 다시 열어야 켜진다: 일이 덜 몰린 때 /exit 뒤 같은 터미널에서 claude --resume"
                 "(relay_env_new)")
```

```python
RELAY_ENV_NEW = ("메인 대리 보고 설정(.claude/settings.local.json 의 HORCH_RELAY_HOME)이 이 메인 세션에 아직 들어오지 않았다. "
                 "일이 덜 몰린 때 /exit 뒤 같은 터미널에서 claude --resume 으로 다시 연다(relay_env_new)")
```

**Edit** `herdr-team/tests/test_setup.py`

```python
    프로젝트의 horch 홈으로 쓴다. relay_env_new 는 쓰기와 상관없이 파일에 그 값이 있고 이 세션(시험) 환경에 없거나 다를 때
    든다. 시험 환경은 기본으로 옵트인한 메인과 같은 값을 갖는다(helpers). 여기서는 뺀다."""
```

```python
    프로젝트의 horch 홈으로 쓴다. relay_env_new 는 이번 up 이 쓰지 않았는데(same, 13단계 9.7 의 3) 파일에 그 값이 있고 이
    세션(시험) 환경에 없거나 다를 때 든다. 새로 쓴 up 은 알리지 않는다(Claude Code 가 세션 중 바뀐 설정을 다시 읽는다).
    시험 환경은 기본으로 옵트인한 메인과 같은 값을 갖는다(helpers). 여기서는 뺀다."""
```

**Edit** `herdr-team/tests/test_setup.py`

```python
        code, out = self.hteam("up", as_="main")
        self.assertEqual((code, out["status"], out.get("warnings")), (0, "running", [RELAY_ENV_NEW]), out)
        self.assertEqual(self.saved(), {"permissions": {"allow": ["Bash(ls)"]},
                                        "env": {"FOO": "1", "HORCH_RELAY_HOME": self.home}})
        self.assertEqual(list(self.saved()), ["permissions", "env"])  # 키 차례도 그대로다
        self.assertEqual((self.proj / ".gitignore").read_text(), ".herdr-team/state/\n.claude/settings.local.json\n")
        # 쓰기와 상관없이 상태로 본다: 값이 같아 쓰지 않는 다음 up 에도 든다(자동 부활의 up 이 먼저 쓴 경우)
        code, out = self.hteam("up", as_="main")
```

```python
        code, out = self.hteam("up", as_="main")
        self.assertEqual((code, out["status"], out.get("warnings")), (0, "running", None), out)  # 새로 쓴 up 은 알리지 않는다
        self.assertEqual(self.saved(), {"permissions": {"allow": ["Bash(ls)"]},
                                        "env": {"FOO": "1", "HORCH_RELAY_HOME": self.home}})
        self.assertEqual(list(self.saved()), ["permissions", "env"])  # 키 차례도 그대로다
        self.assertEqual((self.proj / ".gitignore").read_text(), ".herdr-team/state/\n.claude/settings.local.json\n")
        # 이미 그 값인데(same) 이 세션 환경에 없으면 세션이 받지 못한 것이다(자동 부활의 up 이 먼저 쓴 경우도 같다)
        code, out = self.hteam("up", as_="main")
```

**Edit** `herdr-team/tests/test_setup.py`

```python
        code, out = self.hteam("up", as_="main")
        self.assertEqual((code, out["status"], out.get("warnings")), (0, "hung", [RELAY_ENV_NEW]), out)
```

```python
        code, out = self.hteam("up", as_="main")
        self.assertEqual((code, out["status"], out.get("warnings")), (0, "hung", None), out)  # 이 up 이 썼다
```

**Edit** `herdr-team/tests/test_setup.py`

```python
    def test_main_unreported_comes_after_relay_env_new(self):
        self.started()
        relay = self.fake_relay(MAIN, {"terminal": MAIN, "pid": 4242, "started_ms": 1, "decided": "no_tty"})
```

```python
    def test_main_unreported_comes_after_relay_env_new(self):
        self.started()
        self.assertEqual(self.hteam("up", as_="main")[0], 0)  # 설정을 먼저 쓴다(다음 up 은 same)
        relay = self.fake_relay(MAIN, {"terminal": MAIN, "pid": 4242, "started_ms": 1, "decided": "no_tty"})
```

**Append** `herdr-team/tests/test_wording.py` — 파일 끝에 아래 블록을 그대로 덧붙인다(블록 첫 두 줄이 빈 줄이다). 파일 머리에 이미 `import unittest` 와 `from tests.helpers import REPO, ROOT, TeamCase` 가 있다(`REPO` 는 저장소 루트).

```python


class ReopenWordingTest(unittest.TestCase):
    """13단계(설계 9.7 의 3): Claude Code 2.1.326 은 세션 중 바뀐 설정 env 를 다시 읽는다. README 의 herdr-orch 두 곳과
    herdr-orch skill 은 "세션을 시작할 때 읽힌다" 대신 "다시 읽으면 바로 켜진다, 아니면 다시 연다" 를 쓴다."""

    def test_reopen_wording(self):
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        skill = (REPO / "herdr-orch" / "lib" / "horch" / "skill.md").read_text(encoding="utf-8")
        self.assertNotIn("(설정은 세션을 시작할 때 읽힌다)", readme)
        self.assertNotIn("환경 변수는 세션을 시작할 때 읽힌다", skill)
        self.assertEqual(readme.count("Claude Code 가 세션 중 바뀐 설정을 다시 읽으면"), 2)
        self.assertIn("Claude Code 가 세션 중 바뀐 설정을 다시 읽으면(2.1.326 에서 확인) 바로 켜진다. 켜지지 않으면 그 세션을 "
                      "다시 연다", skill)
```

- [ ] **Step 2: 시험이 실패하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_setup.RelayEnvTest tests.test_wording.ReopenWordingTest)`
Expected: FAIL — RelayEnvTest 의 `warnings` 가 아직 `[옛 문구]`, ReopenWordingTest 는 README·skill 문구가 그대로라 실패.

- [ ] **Step 3: 구현한다**

**Edit** `herdr-team/lib/hteam/setup.py`

```python
RELAY_ENV_NEW = ("메인 대리 보고 설정(.claude/settings.local.json 의 HORCH_RELAY_HOME)이 이 세션에 아직 없다. 설정은 세션을 "
                 "시작할 때 읽히므로 메인을 다시 열어야 켜진다: 일이 덜 몰린 때 /exit 뒤 같은 터미널에서 claude --resume"
                 "(relay_env_new)")
```

```python
RELAY_ENV_NEW = ("메인 대리 보고 설정(.claude/settings.local.json 의 HORCH_RELAY_HOME)이 이 메인 세션에 아직 들어오지 않았다. "
                 "일이 덜 몰린 때 /exit 뒤 같은 터미널에서 claude --resume 으로 다시 연다(relay_env_new)")
```

**Edit** `herdr-team/lib/hteam/setup.py`

```python
    """up 결과의 12단계 경고(설계 9.3 의 8): 옵트인 env 를 쓴 결과(relay_env_unreadable·relay_env_tracked), 다시 열기
    안내(relay_env_new), main_unreported 차례다(다시 열면 relay_env_new 와 main_unreported 가 함께 풀린다)."""
    written = write_relay_env(p.root)
    notes = {"unreadable": [RELAY_ENV_UNREADABLE], "tracked": [RELAY_ENV_TRACKED]}.get(written, [])
    if written != "unreadable" and relay_env_new(p.root):
        notes.append(RELAY_ENV_NEW)
```

```python
    """up 결과의 12단계 경고(설계 9.3 의 8): 옵트인 env 를 쓴 결과(relay_env_unreadable·relay_env_tracked), 다시 열기
    안내(relay_env_new), main_unreported 차례다(다시 열면 relay_env_new 와 main_unreported 가 함께 풀린다).
    relay_env_new 는 이번 up 이 쓰지 않았을 때(same)만 본다(13단계 9.7 의 3): 막 쓴 up 은 쓰기 전에 받은 환경이라 늘 참이고,
    Claude Code 는 세션 중 바뀐 설정 env 를 훅·Bash 에 넣으므로 다음 up 이 그 값을 물려받는다. 그때도 없으면 받지 못한 세션이다."""
    written = write_relay_env(p.root)
    notes = {"unreadable": [RELAY_ENV_UNREADABLE], "tracked": [RELAY_ENV_TRACKED]}.get(written, [])
    if written == "same" and relay_env_new(p.root):
        notes.append(RELAY_ENV_NEW)
```

**Edit** `README.md`

```markdown
`{"env": {"HORCH_RELAY_HOME": "<horch 홈 절대 경로>"}}` 를 넣고 메인 세션을 다시 연다(설정은 세션을 시작할 때 읽힌다). 홈은
```

```markdown
`{"env": {"HORCH_RELAY_HOME": "<horch 홈 절대 경로>"}}` 를 넣는다. Claude Code 가 세션 중 바뀐 설정을 다시 읽으면(2.1.326 에서 확인) 바로 켜진다. 켜지지 않으면 메인 세션을 다시 연다. 홈은
```

**Edit** `README.md`

```markdown
감독 메인도 받으려면 같은 `HORCH_RELAY_HOME` 줄(위 "herdr-orch")을 넣고 메인 세션을 다시 연다.
```

```markdown
감독 메인도 받으려면 같은 `HORCH_RELAY_HOME` 줄(위 "herdr-orch")을 넣는다. Claude Code 가 세션 중 바뀐 설정을 다시 읽으면 바로 켜지고, 켜지지 않으면 메인 세션을 다시 연다.
```

**Edit** `herdr-orch/lib/horch/skill.md`

```markdown
`"HORCH_RELAY_HOME": "<위 HORCH: 줄의 --home 값>"` 을 넣고(개인 절대 경로라 git 에 넣지 않는다) 그 세션을 다시 연다. 환경 변수는 세션을 시작할 때 읽힌다.
```

```markdown
`"HORCH_RELAY_HOME": "<위 HORCH: 줄의 --home 값>"` 을 넣는다(개인 절대 경로라 git 에 넣지 않는다). Claude Code 가 세션 중 바뀐 설정을 다시 읽으면(2.1.326 에서 확인) 바로 켜진다. 켜지지 않으면 그 세션을 다시 연다.
```

- [ ] **Step 4: 시험이 통과하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_setup tests.test_wording) && (cd herdr-orch && python3 -m unittest tests.test_meta)`
Expected: OK. herdr-orch `test_skill_covers_relay` 의 "그 세션을 다시 연다" 는 새 문장에도 있다.

- [ ] **Step 5: 커밋하고 Codex 커밋 리뷰를 건다**

```bash
python3 -m py_compile herdr-team/lib/hteam/setup.py
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews'
git add -- herdr-team/lib/hteam/setup.py herdr-team/tests/test_setup.py herdr-team/tests/test_wording.py README.md herdr-orch/lib/horch/skill.md
git commit -m "fix(herdr-team): relay_env_new 는 설정이 이미 있을 때만 알린다, 다시 열기 문구(설계 9.7 의 3)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/lib/hteam/setup.py herdr-team/tests/test_setup.py herdr-team/tests/test_wording.py README.md herdr-orch/lib/horch/skill.md
scripts/codex-review.sh commit "$(git rev-parse HEAD)"
```

---

### Task 2: 규칙 참조 시험(설계 11.9)

템플릿과 `lib/hteam`·`hooks` 의 `§N`, `§N 의 M번`, `§N.M`, `§N–§K` 인용이 규칙 파일의 절·항목을 가리키는지 본다. 지금 파일에서 통과해야 한다(계획 작성 때 원형으로 확인했다). p13b 가 번호를 더하기 전의 안전망이다.

**Files:**
- Create: `herdr-team/tests/test_rule_refs.py`

**Interfaces:**
- Consumes: 없음.
- Produces: `tests.test_rule_refs.problems(root: Path) -> list[str]`(p13b 의 검사 방식 표기 시험이 같은 파일에 붙는다).

- [ ] **Step 1: 시험을 쓴다**

**Create** `herdr-team/tests/test_rule_refs.py`

```python
"""규칙 참조 시험(설계 11.9, 13단계): 템플릿·코드 글의 §N 인용이 규칙 파일의 절·항목을 가리킨다.

대상 규칙 파일은 인용 앞(같은 줄)에 나온 마지막 규칙 파일 이름(design-rules·text-rules·web-rules)이다. 없으면 파일마다
기본 대상이다: text-rules.md·review-text.md·textlint.py 는 text-rules, web-rules.md 는 web-rules, 그 밖은 design-rules.
앞에 이름이 없고 인용 바로 뒤 괄호에 규칙 파일 이름이 있으면(`§1 의 8번(text-rules.md)`) 그 파일이다. 바로 앞에 `orca` 가 붙은
인용(`orca §17`, orca-team 설계의 절)은 다른 문서라 보지 않는다. 범위(`§2–§6`)는 그 사이 절을
모두 본다. 규칙 파일의 `## §N` 제목 줄은 인용이 아니다.
"""
from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tests.helpers import ROOT

RULES = {"design-rules": "design-rules.md", "text-rules": "text-rules.md", "web-rules": "web-rules.md"}
CITE = re.compile(r"§(\d+)(?:\.(\d+))?(?:\s*[–-]\s*§?(\d+))?(?:\s*의\s*(\d+)번?)?")
NAME = re.compile(r"(design-rules|text-rules|web-rules)")
OTHER_DOC = re.compile(r"orca\s*$")  # 다른 문서의 절 번호(orca-team 설계)
LATER = re.compile(r"\s*\(\s*`?\.?(?:herdr-team/)?(design-rules|text-rules|web-rules)")  # 인용 바로 뒤 괄호의 파일 이름
FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")


def default_target(rel: str) -> str:
    name = rel.rsplit("/", 1)[-1]
    if name in ("text-rules.md", "review-text.md", "textlint.py"):
        return "text-rules"
    if name == "web-rules.md":
        return "web-rules"
    return "design-rules"


def parse_rules(path: Path) -> dict[int, set[int]]:
    """`## §N` 절마다 그 안의 번호 항목(줄 머리 `M. `). 펜스 코드 블록 안은 보지 않는다."""
    out: dict[int, set[int]] = {}
    cur, fence = None, None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = FENCE.match(line)
        if m:
            mark = m.group(1)
            if fence is None:
                fence = mark
            elif re.fullmatch(re.escape(fence[0]) + "{" + str(len(fence)) + ",}", line.strip()):
                fence = None
            continue
        if fence:
            continue
        h = re.match(r"## §(\d+)\b", line)
        if h:
            cur = int(h.group(1))
            out[cur] = set()
            continue
        if line.startswith("## "):
            cur = None
            continue
        item = re.match(r"(\d+)\. ", line)
        if item and cur is not None:
            out[cur].add(int(item.group(1)))
    return out


def problems(root: Path) -> list[str]:
    tpl = root / "templates"
    rules = {k: parse_rules(tpl / v) for k, v in RULES.items() if (tpl / v).is_file()}
    files = sorted(tpl.rglob("*.md")) + sorted((root / "lib" / "hteam").glob("*.py")) + sorted((root / "hooks").glob("*.py"))
    found = []
    for f in files:
        rel = f.relative_to(root).as_posix()
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if line.startswith("## §"):
                continue
            for m in CITE.finditer(line):
                before = line[:m.start()]
                if OTHER_DOC.search(before):
                    continue
                names = NAME.findall(before)
                later = LATER.match(line[m.end():])
                target = names[-1] if names else (later.group(1) if later else default_target(rel))
                sec = rules.get(target)
                if sec is None:
                    found.append(f"{rel}:{n}: {RULES[target]} 가 없다: {m.group(0)}")
                    continue
                a, dot, b, item = (int(x) if x else None for x in m.groups())
                item = item if item is not None else dot
                for s in range(a, (b if b is not None else a) + 1):
                    if s not in sec:
                        found.append(f"{rel}:{n}: {RULES[target]} 에 §{s} 가 없다: {m.group(0)}")
                if item is not None and a in sec and item not in sec[a]:
                    found.append(f"{rel}:{n}: {RULES[target]} §{a} 에 {item}번이 없다: {m.group(0)}")
    return found


class RuleRefTest(unittest.TestCase):
    def test_templates_and_code_cite_existing_rules(self):
        self.assertEqual(problems(ROOT), [])

    def test_checker_catches_broken_citations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "templates" / "roles").mkdir(parents=True)
            (root / "lib" / "hteam").mkdir(parents=True)
            (root / "hooks").mkdir()
            (root / "templates" / "design-rules.md").write_text(
                "# 디자인 규칙\n\n## §1 금지\n1. 하나\n2. 둘\n\n```\n3. 펜스 안은 항목이 아니다\n```\n\n## §2 접근성\n1. 하나\n"
                "\n## §4 글자\n1. 하나\n",
                encoding="utf-8")
            (root / "templates" / "text-rules.md").write_text("# 문구\n\n## §1 보존\n1. 하나\n", encoding="utf-8")
            (root / "templates" / "roles" / "designer.md").write_text(
                "- §1 의 2번, §2 의 1번, §1–§2 는 있다\n- §1 의 3번은 없다\n- §9 는 없다\n- text-rules §1 의 4번은 없다\n"
                "- §1.2 는 있다\n- §2–§4 는 가운데 §3 이 빠졌다\n- §1 의 8번(text-rules.md) 은 없다\n",
                encoding="utf-8")
            (root / "lib" / "hteam" / "x.py").write_text(
                '"""orca §17 은 다른 문서다. 이름 없는 §9 도 본다. design-rules §5 는 없다."""\n', encoding="utf-8")
            self.assertEqual(problems(root), [
                "templates/roles/designer.md:2: design-rules.md §1 에 3번이 없다: §1 의 3번",
                "templates/roles/designer.md:3: design-rules.md 에 §9 가 없다: §9",
                "templates/roles/designer.md:4: text-rules.md §1 에 4번이 없다: §1 의 4번",
                "templates/roles/designer.md:6: design-rules.md 에 §3 가 없다: §2–§4",
                "templates/roles/designer.md:6: design-rules.md 에 §3 가 없다: §3",
                "templates/roles/designer.md:7: text-rules.md §1 에 8번이 없다: §1 의 8번",
                "lib/hteam/x.py:1: design-rules.md 에 §9 가 없다: §9",
                "lib/hteam/x.py:1: design-rules.md 에 §5 가 없다: §5",
            ])
```

- [ ] **Step 2: 시험을 돌린다**

Run: `(cd herdr-team && python3 -m unittest tests.test_rule_refs -v)`
Expected: 두 시험 모두 PASS(지금 파일은 깨진 인용이 없다. 시험 자체를 시험하는 둘째 시험이 검사기가 잡는 것을 보인다). 첫째 시험이 실패하면 출력된 `파일:줄` 의 인용을 읽고, 시험 규칙(기본 대상)이 틀렸는지 문서 인용이 틀렸는지 판단해 고친다. 판단을 커밋 메시지에 적는다.

- [ ] **Step 3: 커밋하고 Codex 커밋 리뷰를 건다**

```bash
git add -- herdr-team/tests/test_rule_refs.py
git commit -m "test(herdr-team): 규칙 참조 시험 — 템플릿·코드의 § 인용이 규칙 파일의 절·항목을 가리킨다(설계 11.9)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/tests/test_rule_refs.py
scripts/codex-review.sh commit "$(git rev-parse HEAD)"
```

---

### Task 3: 프로젝트 규칙 — 워커 사양·리뷰 프롬프트·메인 규칙(설계 5.11 의 1)

**Files:**
- Modify: `herdr-team/lib/hteam/paths.py`(`Project.project_rules`)
- Modify: `herdr-team/lib/hteam/compose.py`(`PROJECT_RULES_NOTE`, `project_rules`, `work_spec`, `review_prompt`)
- Modify: `herdr-team/templates/review-prompt.md`(19줄·33줄)
- Modify: `herdr-team/templates/CLAUDE.section.md`(upgrade 줄 뒤)
- Create: `herdr-team/tests/test_project_rules.py`

**Interfaces:**
- Consumes: 없음.
- Produces: `Project.project_rules(role) -> Path`, `compose.project_rules(p, role) -> str | None`, `compose.PROJECT_RULES_NOTE`, 리뷰 프롬프트의 `{{project_rules}}` 자리.

- [ ] **Step 1: 실패하는 시험을 쓴다**

**Create** `herdr-team/tests/test_project_rules.py`

```python
"""프로젝트 규칙 파일(설계 5.11 의 1, 13단계): .herdr-team/project-rules/<직무>.md 를 워커 사양이 직무 문서 뒤에 붙이고, 리뷰
프롬프트가 가리키고, 메인 규칙이 그 파일에 쓰라고 한다. upgrade 옮기기는 test_setup.UpgradeTest(9.7 의 1)."""
from __future__ import annotations

import unittest

from tests.helpers import ROOT, TeamCase
from hteam import compose, config, specs, state
from hteam.errors import HteamError
from hteam.paths import Project

NOTE = ("아래는 이 프로젝트가 더한 developer 규칙이다(.herdr-team/project-rules/developer.md). 이 사양의 작업 규칙"
        "(소유 경로, 커밋, 보고서, done)은 바꾸지 않는다.")


class ProjectRulesSpecTest(TeamCase):
    def setUp(self):
        super().setUp()
        self.init_project()
        self.p = Project(self.proj)
        self.write_spec("T-001")
        self.rules = self.team / "project-rules" / "developer.md"

    def spec_text(self):
        cfg = config.load(self.p)
        return compose.work_spec(self.p, cfg, specs.load(self.p, "T-001"), {"round": 1}, ["src/**"])

    def test_rules_follow_the_role_doc(self):
        self.assertEqual(self.p.project_rules("developer"), self.rules)
        self.assertNotIn("이 프로젝트가 더한", self.spec_text())  # 없으면 지금 그대로
        self.rules.parent.mkdir()
        self.rules.write_text("  \n\n", encoding="utf-8")
        self.assertNotIn("이 프로젝트가 더한", self.spec_text())  # 공백뿐이면 붙이지 않는다
        self.rules.write_text("## 이 프로젝트 규칙\n- 제품 책임자의 개인 폰은 쓰지 않는다.\n", encoding="utf-8")
        text = self.spec_text()
        self.assertLess(text.index("# developer 직무 문서"), text.index(NOTE))
        self.assertLess(text.index(NOTE), text.index("- 제품 책임자의 개인 폰은 쓰지 않는다."))
        self.assertLess(text.index("- 제품 책임자의 개인 폰은 쓰지 않는다."), text.index("---\n\n# 태스크 T-001"))
        self.assertEqual(text.count(NOTE), 1)

    def test_other_roles_do_not_get_the_file(self):
        self.rules.parent.mkdir()
        (self.team / "project-rules" / "tester.md").write_text("- 테스터만의 규칙\n", encoding="utf-8")
        self.assertNotIn("테스터만의 규칙", self.spec_text())

    def test_unreadable_rules_stop_the_spec(self):
        self.rules.mkdir(parents=True)  # 디렉터리라 읽지 못한다
        with self.assertRaises(HteamError) as ctx:
            self.spec_text()
        self.assertEqual((ctx.exception.code, ctx.exception.exit_code), ("project_rules_unreadable", 1))
        self.rules.rmdir()
        self.rules.write_bytes(b"\xff\xfe\x00")  # UTF-8 아님
        with self.assertRaises(HteamError) as ctx:
            self.spec_text()
        self.assertEqual(ctx.exception.code, "project_rules_unreadable")
        self.rules.unlink()
        self.rules.symlink_to(self.tmp / "없는-규칙.md")  # 끊어진 링크는 "없음" 이 아니다
        with self.assertRaises(HteamError) as ctx:
            self.spec_text()
        self.assertEqual(ctx.exception.code, "project_rules_unreadable")
        self.assertIn("끊어진 심볼릭 링크", ctx.exception.message)


class ProjectRulesReviewTest(TeamCase):
    """태스크 하나씩(두 developer 태스크를 함께 띄우면 owns 잠금이 겹친다)."""

    def setUp(self):
        super().setUp()
        self.init_project()
        self.setup_run()
        self.p = Project(self.proj)

    def prompt(self):
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        self.assertEqual(self.hteam("start", "T-001")[0], 0)
        self.assertEqual(self.act_work("T-001")[0], 0)
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out.get("status")), (0, "reviewing"), out)
        return (self.state_dir / "tasks" / "T-001" / "r1-review-a1.md").read_text(encoding="utf-8")

    def test_no_rules_line_without_file(self):
        text = self.prompt()
        self.assertIn("- 직무 문서: `.herdr-team/roles/developer.md`\n- 워커 보고서:", text)
        self.assertIn("2. 직무 문서와 프로젝트 규칙(위에 있으면)의 규칙과 품질 기준을 지키는가.", text)

    def test_rules_line_with_file(self):
        self.commit(".herdr-team/project-rules/developer.md", "- 개인 폰은 쓰지 않는다.\n", "프로젝트 규칙")
        text = self.prompt()
        self.assertIn("- 직무 문서: `.herdr-team/roles/developer.md`\n"
                      "- 프로젝트 규칙: `.herdr-team/project-rules/developer.md`\n- 워커 보고서:", text)


class MainRuleTest(unittest.TestCase):
    def test_main_rule_says_where_project_rules_go(self):
        main = (ROOT / "templates" / "CLAUDE.section.md").read_text(encoding="utf-8")
        self.assertIn("직무 문서(`.herdr-team/roles/<직무>.md`)가 아니라 `.herdr-team/project-rules/<직무>.md` 에 쓰고 "
                      "커밋한다", main)
```

- [ ] **Step 2: 시험이 실패하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_project_rules)`
Expected: FAIL — `Project` 에 `project_rules` 가 없다(AttributeError), 리뷰 프롬프트 기준 2 문구가 다르다, 메인 규칙 줄이 없다.

- [ ] **Step 3: 구현한다**

**Edit** `herdr-team/lib/hteam/paths.py`

```python
    def role_doc(self, role: str) -> Path:
        return self.roles / f"{role}.md"
```

```python
    def role_doc(self, role: str) -> Path:
        return self.roles / f"{role}.md"

    def project_rules(self, role: str) -> Path:
        """프로젝트가 그 직무에 더한 규칙(설계 5.11 의 1, 13단계). hteam 은 만들거나 고치지 않는다(upgrade 옮기기만 쓴다)."""
        return self.team / "project-rules" / f"{role}.md"
```

**Edit** `herdr-team/lib/hteam/compose.py`

```python
from .errors import USAGE, HteamError
```

```python
from .errors import FAIL, USAGE, HteamError
```

**Edit** `herdr-team/lib/hteam/compose.py`

```python
TEAM_REF = re.compile(r"`\.herdr-team/(?!bin/)")  # 글 안의 팀 파일 경로. shim(`.herdr-team/bin/hteam`)은 슬롯 것을 부른다
```

```python
PROJECT_RULES_NOTE = ("아래는 이 프로젝트가 더한 {role} 규칙이다(.herdr-team/project-rules/{role}.md). 이 사양의 작업 규칙"
                      "(소유 경로, 커밋, 보고서, done)은 바꾸지 않는다.")


def project_rules(p, role: str) -> str | None:
    """프로젝트가 더한 직무 규칙(설계 5.11 의 1). 상태 루트의 파일이다. 없거나 공백뿐이면 None. 있는데 읽지 못하면 시작을 멈춘다
    (project_rules_unreadable): 기기 사용 금지 같은 안전 규칙을 빼고 일하게 두지 않는다."""
    path = p.project_rules(role)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        if path.is_symlink():  # 끊어진 심볼릭 링크: 규칙이 있다고 정했는데 읽지 못한다
            raise HteamError("project_rules_unreadable",
                             f"프로젝트 규칙을 읽지 못했다: {path.relative_to(p.root)} (끊어진 심볼릭 링크)", FAIL) from None
        return None
    except (OSError, UnicodeDecodeError) as exc:
        raise HteamError("project_rules_unreadable",
                         f"프로젝트 규칙을 읽지 못했다: {path.relative_to(p.root)} ({exc.__class__.__name__})", FAIL) from None
    return text.strip() + "\n" if text.strip() else None


TEAM_REF = re.compile(r"`\.herdr-team/(?!bin/)")  # 글 안의 팀 파일 경로. shim(`.herdr-team/bin/hteam`)은 슬롯 것을 부른다
```

**Edit** `herdr-team/lib/hteam/compose.py`

```python
    parts = [team_refs(p, role_doc(p, spec.role)), "---", "",
             f"# 태스크 {tid} · 라운드 {n} — [{cfg.role_title(spec.role)}] {spec.title}", "",
             team_refs(p, spec.body.strip()), ""]
```

```python
    parts = [team_refs(p, role_doc(p, spec.role))]
    extra_rules = project_rules(p, spec.role)  # 직무 문서 바로 뒤(설계 5.11 의 1)
    if extra_rules:
        parts += [PROJECT_RULES_NOTE.format(role=spec.role), "", team_refs(p, extra_rules)]
    parts += ["---", "",
              f"# 태스크 {tid} · 라운드 {n} — [{cfg.role_title(spec.role)}] {spec.title}", "",
              team_refs(p, spec.body.strip()), ""]
```

**Edit** `herdr-team/lib/hteam/compose.py`

```python
                role_doc=p.state_ref(f".herdr-team/roles/{spec.role}.md"),
```

```python
                role_doc=p.state_ref(f".herdr-team/roles/{spec.role}.md"),
                project_rules=(f"\n- 프로젝트 규칙: `{p.state_ref(f'.herdr-team/project-rules/{spec.role}.md')}`"
                               if p.project_rules(spec.role).is_file() else ""),
```

**Edit** `herdr-team/templates/review-prompt.md`

```markdown
- 직무 문서: `{{role_doc}}`
```

```markdown
- 직무 문서: `{{role_doc}}`{{project_rules}}
```

**Edit** `herdr-team/templates/review-prompt.md`

```markdown
2. 직무 문서의 규칙과 품질 기준을 지키는가.
```

```markdown
2. 직무 문서와 프로젝트 규칙(위에 있으면)의 규칙과 품질 기준을 지키는가.
```

**Edit** `herdr-team/templates/CLAUDE.section.md`

```markdown
`CLAUDE.md` 절이 바뀌었으면 사용자에게 메인 세션을 새로 열라고 알린다(메인 규칙은 세션을 시작할 때 읽힌다).
```

```markdown
`CLAUDE.md` 절이 바뀌었으면 사용자에게 메인 세션을 새로 열라고 알린다(메인 규칙은 세션을 시작할 때 읽힌다).
- 사용자가 이 프로젝트에 맞는 직무 규칙(기기 사용, 스택, 하지 말 것 등)을 더하라고 하면 직무 문서(`.herdr-team/roles/<직무>.md`)가 아니라 `.herdr-team/project-rules/<직무>.md` 에 쓰고 커밋한다. 직무 문서는 upgrade 가 템플릿으로 바꾸고, project-rules 는 그 직무 워커의 사양에 직무 문서 뒤로 붙는다.
```

- [ ] **Step 4: 시험이 통과하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_project_rules tests.test_review tests.test_start tests.test_wording tests.test_workspace_flow tests.test_setup tests.test_rule_refs)`
Expected: OK. `test_workspace_flow` 의 `^- 직무 문서: \`…\`$` 정규식은 프로젝트 규칙 파일이 없으면 지금처럼 맞는다.

- [ ] **Step 5: 커밋하고 Codex 커밋 리뷰를 건다**

```bash
python3 -m py_compile herdr-team/lib/hteam/paths.py herdr-team/lib/hteam/compose.py
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews'
git add -- herdr-team/lib/hteam/paths.py herdr-team/lib/hteam/compose.py herdr-team/templates/review-prompt.md herdr-team/templates/CLAUDE.section.md herdr-team/tests/test_project_rules.py
git commit -m "feat(herdr-team): 프로젝트 규칙 파일 — 워커 사양이 직무 문서 뒤에 붙이고 리뷰가 가리킨다(설계 5.11 의 1)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/lib/hteam/paths.py herdr-team/lib/hteam/compose.py herdr-team/templates/review-prompt.md herdr-team/templates/CLAUDE.section.md herdr-team/tests/test_project_rules.py
scripts/codex-review.sh commit "$(git rev-parse HEAD)"
```

---

### Task 4: upgrade 의 프로젝트 규칙 옮기기와 `RETIRED_HEADINGS`(설계 9.7 의 1)

**Files:**
- Modify: `herdr-team/lib/hteam/setup.py`(`import re`, 상수, `split_sections`, `project_sections`, `_move_sections`, `upgrade`)
- Modify: `herdr-team/tests/test_setup.py`(`UpgradeTest` 에 시험 셋)
- Modify: `herdr-team/tests/test_project_rules.py`(순수 함수 시험, 템플릿 제목 기록 시험)

**Interfaces:**
- Consumes: Task 3 의 파일 경로 꼴 `.herdr-team/project-rules/<직무>.md`.
- Produces: `setup.ROLE_NAMES`, `setup.RETIRED_HEADINGS`, `setup.split_sections`, `setup.project_sections`, upgrade 출력 키 `moved`.

- [ ] **Step 1: 실패하는 시험을 쓴다**

**Edit** `herdr-team/tests/test_setup.py` — `UpgradeTest` 의 `def test_uncommitted_deletions_are_not_restored(self):` 줄을 찾을 내용으로 쓰고, 바꿀 내용은 그 앞에 아래 세 메서드를 넣은 것이다:

```python
    MOVED_NEXT = " moved 의 절은 직무 문서에서 .herdr-team/project-rules/ 로 옮겼다. 두 파일을 함께 커밋한다."

    def test_project_sections_move_to_project_rules(self):  # 설계 9.7 의 1(13단계)
        doc = ".herdr-team/roles/developer.md"
        extra = ("## 이 프로젝트 규칙\n- 제품 책임자의 개인 폰은 쓰지 않는다.\n\n```text\n## 코드 블록 안 제목은 절이 아니다\n"
                 "```\n")
        self.edit_commit(doc, self.template("roles/developer.md") + "\n" + extra)
        head = self.head()
        code, out = self.upgrade()
        self.assertEqual(code, 0, out)
        self.assertEqual(out["updated"], [doc])
        self.assertEqual(out["moved"], [{"path": doc, "to": ".herdr-team/project-rules/developer.md",
                                         "sections": ["## 이 프로젝트 규칙"]}])
        self.assertEqual((self.proj / doc).read_text(encoding="utf-8"), self.template("roles/developer.md"))
        self.assertEqual((self.team / "project-rules/developer.md").read_text(encoding="utf-8"), extra)
        self.assertTrue(out["next"].endswith(self.MOVED_NEXT), out["next"])
        self.assertEqual(self.head(), head)  # 커밋하지 않는다
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "upgrade")
        code, again = self.upgrade()
        self.assertEqual((code, again["updated"], again["moved"]), (0, [], []), again)
        self.assertFalse(again["next"].endswith(self.MOVED_NEXT))

    def test_existing_rules_are_not_duplicated(self):
        doc, rules = ".herdr-team/roles/tester.md", ".herdr-team/project-rules/tester.md"
        extra = "## 이 프로젝트 규칙\n- 에뮬레이터만 쓴다.\n"
        self.edit_commit(doc, self.template("roles/tester.md") + "\n" + extra)
        self.edit_commit(rules, "## 다른 규칙\n- 하나\n\n" + extra)  # 앞 upgrade 가 옮긴 뒤 커밋했다(직무 문서는 못 바꿨다)
        code, out = self.upgrade()
        self.assertEqual((code, out["moved"]), (0, [{"path": doc, "to": rules, "sections": ["## 이 프로젝트 규칙"]}]), out)
        self.assertEqual((self.proj / rules).read_text(encoding="utf-8"), "## 다른 규칙\n- 하나\n\n" + extra)
        self.assertEqual((self.proj / doc).read_text(encoding="utf-8"), self.template("roles/tester.md"))

    def test_dirty_or_untracked_rules_skip_the_role_doc(self):
        doc, rules = ".herdr-team/roles/tester.md", ".herdr-team/project-rules/tester.md"
        body = self.template("roles/tester.md") + "\n## 이 프로젝트 규칙\n- 에뮬레이터만 쓴다.\n"
        self.edit_commit(doc, body)
        reason = ("project-rules/tester.md 를 쓸 수 없다: {}. 앞 upgrade 가 옮기다 멈췄으면 그 파일에 이미 옮긴 절이 있다. "
                  "확인해 커밋한 뒤 다시 한다(같은 글은 다시 덧붙이지 않는다)")
        (self.proj / rules).parent.mkdir(parents=True)
        (self.proj / rules).write_text("추적하지 않는 파일\n", encoding="utf-8")
        code, out = self.upgrade()
        self.assertEqual((code, out["moved"], out["skipped"]),
                         (0, [], [{"path": doc, "reason": reason.format("git 에 추적되지 않는다")}]), out)
        self.assertEqual((self.proj / doc).read_text(encoding="utf-8"), body)
        self.edit_commit(rules, "커밋한 파일\n")
        (self.proj / rules).write_text("커밋 안 한 수정\n", encoding="utf-8")
        code, out = self.upgrade()
        self.assertEqual(out["skipped"], [{"path": doc, "reason": reason.format("커밋 안 된 변경이 있다(지운 것 포함)")}])
        self.assertEqual(((self.proj / doc).read_text(encoding="utf-8"), (self.proj / rules).read_text(encoding="utf-8")),
                         (body, "커밋 안 한 수정\n"))

    def test_similar_rule_is_not_taken_for_a_duplicate(self):
        doc, rules = ".herdr-team/roles/developer.md", ".herdr-team/project-rules/developer.md"
        self.edit_commit(doc, self.template("roles/developer.md") + "\n## 이 프로젝트 규칙\n- 개인 폰 사용 금지\n")
        self.edit_commit(rules, "## 이 프로젝트 규칙\n- 개인 폰 사용 금지 해제\n")  # 부분 문자열로는 같아 보인다
        code, out = self.upgrade()
        self.assertEqual((code, len(out["moved"])), (0, 1), out)
        self.assertEqual((self.proj / rules).read_text(encoding="utf-8"),
                         "## 이 프로젝트 규칙\n- 개인 폰 사용 금지 해제\n\n## 이 프로젝트 규칙\n- 개인 폰 사용 금지\n")

    def test_write_failure_skips_and_a_crash_resumes(self):
        doc, rules = ".herdr-team/roles/developer.md", ".herdr-team/project-rules/developer.md"
        extra = "## 이 프로젝트 규칙\n- 개인 폰은 쓰지 않는다.\n"
        body = self.template("roles/developer.md") + "\n" + extra
        self.edit_commit(doc, body)
        self.edit_commit(".herdr-team/project-rules/other.md", "다른 직무\n")
        folder = self.team / "project-rules"
        folder.chmod(0o555)  # 쓰지 못한다
        try:
            code, out = self.upgrade()
        finally:
            folder.chmod(0o755)
        self.assertEqual((code, out["moved"]), (0, []), out)
        self.assertEqual(out["skipped"][0]["path"], doc)
        self.assertIn("project-rules/developer.md 를 쓸 수 없다: 쓰지 못했다(PermissionError)", out["skipped"][0]["reason"])
        self.assertEqual((self.proj / doc).read_text(encoding="utf-8"), body)
        # 덧붙인 직후 죽으면: 직무 문서는 그대로, project-rules 는 커밋 안 된 새 파일
        code, _ = self.hteam("upgrade", as_=None, env={"HTEAM_TEST_DIE_AT": "after_project_rules"})
        self.assertEqual(code, 137)
        self.assertEqual(((self.proj / doc).read_text(encoding="utf-8"), (self.proj / rules).read_text(encoding="utf-8")),
                         (body, extra))
        code, out = self.upgrade()  # 추적하지 않는 project-rules: 건너뛴다
        self.assertEqual((out["moved"], out["skipped"][0]["path"]), ([], doc), out)
        self.git("add", "--", rules)
        self.git("commit", "-q", "-m", "옮긴 규칙", "--", rules)
        code, out = self.upgrade()  # 같은 절은 다시 덧붙이지 않고 끝난다
        self.assertEqual((code, out["moved"]), (0, [{"path": doc, "to": rules, "sections": ["## 이 프로젝트 규칙"]}]), out)
        self.assertEqual(((self.proj / doc).read_text(encoding="utf-8"), (self.proj / rules).read_text(encoding="utf-8")),
                         (self.template("roles/developer.md"), extra))
```

**Edit** `herdr-team/tests/test_project_rules.py`

```python
from hteam import compose, config, specs, state
```

```python
import subprocess

from hteam import compose, config, setup, specs, state
```

**Edit** `herdr-team/tests/test_project_rules.py` — 파일 끝 `class MainRuleTest(unittest.TestCase):` 를 찾을 내용으로 쓰고, 바꿀 내용은 그 앞에 아래 두 클래스를 넣은 것이다:

```python
class SectionsTest(unittest.TestCase):
    TEMPLATE = "# developer\n\n## 책임\n- 하나\n\n## 하지 않는 것\n- 둘\n"

    def test_split_ignores_fenced_headings(self):
        head, sections = setup.split_sections("# 제목\n머리\n\n## 가\n```\n## 펜스 안\n```\n## 나\n~~~~\n## 물결 펜스\n~~~~\n")
        self.assertEqual(head, "# 제목\n머리\n\n")
        self.assertEqual(sections, [("## 가", "## 가\n```\n## 펜스 안\n```\n"), ("## 나", "## 나\n~~~~\n## 물결 펜스\n~~~~\n")])

    def test_project_sections_are_those_unknown_to_the_template(self):
        text = self.TEMPLATE + "\n## 이 프로젝트 규칙\n- 폰 금지\n\n## 옛 제목\n- 옛 템플릿 글\n"
        self.assertEqual(setup.project_sections("developer", self.TEMPLATE, self.TEMPLATE), [])
        self.assertEqual([h for h, _ in setup.project_sections("developer", text, self.TEMPLATE)],
                         ["## 이 프로젝트 규칙", "## 옛 제목"])
        self.assertEqual([h for h, _ in setup.project_sections("developer", text, self.TEMPLATE, retired=("## 옛 제목",))],
                         ["## 이 프로젝트 규칙"])
        self.assertEqual(setup.ROLE_NAMES, ("planner", "director", "designer", "developer", "tester"))
        self.assertEqual(set(setup.RETIRED_HEADINGS), set(setup.ROLE_NAMES))


class RetiredHeadingTest(unittest.TestCase):
    """템플릿 직무 문서의 `## ` 제목을 바꾸거나 지우면 옛 제목을 setup.RETIRED_HEADINGS 에 넣는다(설계 9.7 의 1). git 기록의
    모든 판을 본다. 저장소 밖(설치본)에서는 건너뛴다."""

    def test_removed_template_headings_are_retired(self):
        repo = ROOT.parent
        for role in setup.ROLE_NAMES:
            rel = f"herdr-team/templates/roles/{role}.md"
            log = subprocess.run(["git", "-C", str(repo), "log", "--format=%H", "--", rel], capture_output=True, text=True)
            if log.returncode != 0 or not log.stdout.strip():
                self.skipTest("git 기록이 없다")
            now = {h for h, _ in setup.split_sections((ROOT / "templates" / "roles" / f"{role}.md").read_text(
                encoding="utf-8"))[1]}
            seen = set()
            for sha in log.stdout.split():
                old = subprocess.run(["git", "-C", str(repo), "show", f"{sha}:{rel}"], capture_output=True, text=True)
                if old.returncode == 0:
                    seen |= {h for h, _ in setup.split_sections(old.stdout)[1]}
            self.assertEqual(seen - now - set(setup.RETIRED_HEADINGS[role]), set(), role)
```

- [ ] **Step 2: 시험이 실패하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_project_rules tests.test_setup.UpgradeTest)`
Expected: FAIL — `setup.split_sections` 가 없다, upgrade 출력에 `moved` 가 없다.

- [ ] **Step 3: 구현한다**

**Edit** `herdr-team/lib/hteam/setup.py`

```python
import platform
import secrets
```

```python
import platform
import re
import secrets
```

**Edit** `herdr-team/lib/hteam/setup.py`

```python
SECTIONS = (("CLAUDE.md", "CLAUDE.section.md"), ("AGENTS.md", "AGENTS.section.md"))  # 덧붙인 절은 바꾸지 않고 알린다
```

```python
SECTIONS = (("CLAUDE.md", "CLAUDE.section.md"), ("AGENTS.md", "AGENTS.section.md"))  # 덧붙인 절은 바꾸지 않고 알린다
ROLE_NAMES = ("planner", "director", "designer", "developer", "tester")
ROLE_DOCS = {f"roles/{role}.md": role for role in ROLE_NAMES}  # upgrade 가 프로젝트 절을 옮기는 템플릿(설계 9.7 의 1)
# 템플릿에서 바꾸거나 지운 직무 문서 `## ` 제목. 옛 템플릿 절을 프로젝트 규칙으로 옮기지 않게 한다. 제목을 바꾸는 커밋이
# 옛 제목을 여기 넣는다(tests/test_project_rules.RetiredHeadingTest 가 git 기록으로 지킨다)
RETIRED_HEADINGS: dict[str, tuple[str, ...]] = {role: () for role in ROLE_NAMES}
MOVED_NEXT = "moved 의 절은 직무 문서에서 .herdr-team/project-rules/ 로 옮겼다. 두 파일을 함께 커밋한다."
_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
```

**Edit** `herdr-team/lib/hteam/setup.py`

```python
def upgrade(root: Path) -> dict:
```

```python
def split_sections(text: str) -> tuple[str, list[tuple[str, str]]]:
    """마크다운을 머리(첫 `## ` 제목 줄 앞)와 `## ` 절 [(제목 줄(끝 공백 뗌), 절 글)] 로 나눈다(설계 9.7 의 1). 펜스 코드 블록
    (``` · ~~~, 같은 문자로 같은 길이 이상인 줄이 닫는다) 안의 줄은 제목이 아니다. 절 글은 제목 줄부터 다음 제목 줄 앞까지다."""
    head: list[str] = []
    sections: list[list] = []
    fence = None
    for line in text.splitlines(keepends=True):
        m = _FENCE.match(line)
        if m:
            mark = m.group(1)
            if fence is None:
                fence = mark
            elif re.fullmatch(re.escape(fence[0]) + "{" + str(len(fence)) + ",}", line.strip()):
                fence = None
        elif fence is None and line.startswith("## "):
            sections.append([line.rstrip("\n").rstrip(), [line]])
            continue
        (sections[-1][1] if sections else head).append(line)
    return "".join(head), [(title, "".join(body)) for title, body in sections]


def project_sections(role: str, text: str, template: str, retired: tuple[str, ...] | None = None) -> list[tuple[str, str]]:
    """직무 문서 text 의 절 가운데 제목이 지금 템플릿에도 옛 제목(retired, 없으면 RETIRED_HEADINGS[role])에도 없는 절."""
    known = {title for title, _ in split_sections(template)[1]}
    known |= set(RETIRED_HEADINGS.get(role, ()) if retired is None else retired)
    return [(title, body) for title, body in split_sections(text)[1] if title not in known]


def _rules_rel(role: str) -> str:
    return f".herdr-team/project-rules/{role}.md"


def _section_key(body: str) -> str:
    """절 글의 비교 열쇠: 앞뒤 빈 줄과 줄 끝 공백을 뗀 것."""
    return "\n".join(line.rstrip() for line in body.strip("\n").splitlines())


def _move_reason(role: str, why: str) -> str:
    return (f"project-rules/{role}.md 를 쓸 수 없다: {why}. 앞 upgrade 가 옮기다 멈췄으면 그 파일에 이미 옮긴 절이 있다. "
            "확인해 커밋한 뒤 다시 한다(같은 글은 다시 덧붙이지 않는다)")


def _move_sections(root: Path, role: str, found: list[tuple[str, str]], hidden: set, prefix: str) -> str | None:
    """프로젝트 절을 project-rules/<직무>.md 끝에 덧붙인다(설계 9.7 의 1). 그 파일에 같은 절(절로 나눠 _section_key 가 같은
    것. 부분 문자열이 아니다)이 이미 있으면 그 절은 덧붙이지 않는다. 쓸 수 없으면 까닭을 돌려준다(그 직무 문서는 건너뛴다).
    파일이 없는 것은 괜찮다."""
    rel = _rules_rel(role)
    path = root / rel
    parts = Path(rel).parts
    why = None
    if any(root.joinpath(*parts[:i]).is_symlink() for i in range(1, len(parts) + 1)):
        why = "경로에 심볼릭 링크가 있다"
    elif prefix + rel in hidden:
        why = "git 숨김 플래그(assume-unchanged·skip-worktree)가 있다"
    else:
        try:
            if any(code != "??" for code in gitio.status_codes(root, rel)):
                why = "커밋 안 된 변경이 있다(지운 것 포함)"
            elif path.exists() and not gitio.tracked(root, rel):
                why = "git 에 추적되지 않는다"
        except HteamError as exc:
            why = f"git 상태를 읽지 못했다: {exc.message}"
    old = ""
    if why is None and path.exists():
        try:
            old = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            why = f"읽지 못했다({exc.__class__.__name__})"
    if why is not None:
        return _move_reason(role, why)
    have = {_section_key(body) for _, body in split_sections(old)[1]}
    add = [body.strip("\n") for _, body in found if _section_key(body) not in have]
    if add:
        try:
            write_atomic(path, (old.rstrip("\n") + "\n\n" if old.strip() else "") + "\n\n".join(add) + "\n")
        except OSError as exc:
            return _move_reason(role, f"쓰지 못했다({exc.__class__.__name__})")
        die_at("after_project_rules")  # 시험: 덧붙인 뒤 직무 문서를 덮어쓰기 전에 죽는다
    return None


def upgrade(root: Path) -> dict:
```

**Edit** `herdr-team/lib/hteam/setup.py`

```python
    역할을 확인하지 않고 config.toml 을 읽지 않는다."""
    updated, created, skipped = [], [], []
```

```python
    역할을 확인하지 않고 config.toml 을 읽지 않는다. 직무 문서를 덮어쓰기 전에 템플릿에 없는 제목의 절을
    project-rules/<직무>.md 로 옮긴다(13단계 9.7 의 1, 출력 moved)."""
    updated, created, skipped, moved = [], [], [], []
```

**Edit** `herdr-team/lib/hteam/setup.py`

```python
            elif dst.read_bytes() != want.encode("utf-8"):
                write_atomic(dst, want)  # 같은 폴더 임시 파일 + os.replace
                updated.append(rel)
```

```python
            elif dst.read_bytes() != want.encode("utf-8"):
                role = ROLE_DOCS.get(src)
                try:
                    found = project_sections(role, dst.read_text(encoding="utf-8"), want) if role else []
                except UnicodeDecodeError:
                    found = []  # UTF-8 이 아닌 직무 문서는 지금처럼 덮어쓴다(git 이 백업이다)
                if found:
                    problem = _move_sections(root, role, found, hidden, prefix)
                    if problem is not None:
                        skipped.append({"path": rel, "reason": problem})
                        continue
                    moved.append({"path": rel, "to": _rules_rel(role), "sections": [title for title, _ in found]})
                write_atomic(dst, want)  # 같은 폴더 임시 파일 + os.replace
                updated.append(rel)
```

**Edit** `herdr-team/lib/hteam/setup.py`

```python
        stat = gitio.diff_stat(root, updated + created)  # 바꾸거나 만든 파일만(건너뛴 파일의 사용자 변경이 섞이지 않게)
    except HteamError:
        stat = ""
    return {"updated": updated, "created": created, "skipped": skipped, "manual": _section_manual(root),
            "diff_stat": stat, "next": UPGRADE_NEXT}
```

```python
        # 바꾸거나 만든 파일과 옮긴 곳만(건너뛴 파일의 사용자 변경이 섞이지 않게)
        stat = gitio.diff_stat(root, updated + created + list(dict.fromkeys(m["to"] for m in moved)))
    except HteamError:
        stat = ""
    return {"updated": updated, "created": created, "skipped": skipped, "moved": moved, "manual": _section_manual(root),
            "diff_stat": stat, "next": UPGRADE_NEXT + (" " + MOVED_NEXT if moved else "")}
```

- [ ] **Step 4: 시험이 통과하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_project_rules tests.test_setup)`
Expected: OK. 기존 `test_overwrites_committed_copies_and_skips_the_rest` 는 직무 문서에 `## ` 제목이 없는 글을 커밋하므로 옮길 절이 없어 그대로 통과한다.

- [ ] **Step 5: 커밋하고 Codex 커밋 리뷰를 건다**

```bash
python3 -m py_compile herdr-team/lib/hteam/setup.py
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews'
git add -- herdr-team/lib/hteam/setup.py herdr-team/tests/test_setup.py herdr-team/tests/test_project_rules.py
git commit -m "fix(herdr-team): upgrade 가 직무 문서의 프로젝트 절을 project-rules 로 옮긴 뒤 덮어쓴다, RETIRED_HEADINGS(설계 9.7 의 1)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/lib/hteam/setup.py herdr-team/tests/test_setup.py herdr-team/tests/test_project_rules.py
scripts/codex-review.sh commit "$(git rev-parse HEAD)"
```

---

### Task 5: 훅 명령 판정의 heredoc(설계 9.7 의 2)

명령 전체가 `cat`·`tee` 한 번과 따옴표 있는 끝 표시이고 마지막 줄이 끝 표시인 꼴만 본문을 지우고 판정한다(heredoc 해석기는 두지 않는다). 기존 `HorchRuleTest` 의 거부 사례는 그대로 거부된다.

**Files:**
- Modify: `herdr-team/hooks/hteam_hook.py`(`_SIMPLE_HEREDOC`, `strip_heredocs`, 판정 셋)
- Modify: `herdr-team/tests/test_hooks.py`(새 시험 클래스)

**Interfaces:**
- Consumes: 없음.
- Produces: `strip_heredocs(cmd: str) -> str`(순수 함수).

- [ ] **Step 1: 실패하는 시험을 쓴다**

**Edit** `herdr-team/tests/test_hooks.py` — `class HookImportTest(TeamCase):` 를 찾을 내용으로 쓰고, 바꿀 내용은 그 앞에 아래 클래스를 넣은 것이다:

```python
class HeredocRuleTest(unittest.TestCase):
    """13단계(설계 9.7 의 2): 명령 전체가 cat·tee 한 번과 따옴표 있는 끝 표시이고 마지막 줄이 끝 표시인 heredoc 은 본문의
    낱말을 거부하지 않는다. 그 밖의 꼴은 지금처럼 원문으로 본다."""

    ALLOW = (  # (판정 이름, 명령)
        ("watch", "cat >> notes.md <<'EOF'\nhteam watch 는 run_in_background 로 띄운다\nEOF"),
        ("watch", "cat >> notes.md <<-'EOF'\n\thteam watch\n\tEOF"),
        ("watch", "cat > m/a.md <<\"END\"\nhteam watch &\nEND"),
        ("watch", "tee -a notes.md >/dev/null <<'EOF'\nhteam watch\nEOF"),
        ("watch", "cat <<'EOF' >> 메모.md\nhteam watch\nEOF\n"),
        ("drive", "cat >> notes.md <<'EOF'\nhteam drive 는 직접 부르지 않는다\nEOF"),
        ("horch", "cat >> notes.md <<'EOF'\nhorch worker-list 는 관제가 쓴다\nEOF"),
    )
    DENY = (
        ("watch", "cat >> notes.md <<EOF\nhteam watch\nEOF"),  # 따옴표 없는 끝 표시
        ("watch", "cat <<'EOF'\nx\nEOF\nhteam watch &"),  # 끝 표시 뒤의 줄
        ("watch", "cat <<'EOF'\nEOF\nhteam watch &\nEOF"),  # 끝 표시가 먼저 나온다
        ("watch", "cat >> a <<'EOF'\nhteam watch\n"),  # 끝 표시 없음
        ("watch", "mkdir -p m && cat > m/a.md <<'EOF'\nhteam watch\nEOF"),  # 앞에 다른 명령
        ("watch", "cat <<'EOF' | sh\nhteam watch\nEOF"),
        ("watch", "cat <<'EOF' > >(bash)\nhteam watch\nEOF"),
        ("watch", "bash <<'EOF'\nhteam watch\nEOF"),
        ("watch", "bash < <(\ncat <<'EOF'\nhteam watch\nEOF\n)"),
        ("watch", "cat <<1\ncat <<'EOF'\n1\nhteam watch &"),
        ("watch", "printf '%s\\n' '<<EOF'\nhteam watch &"),
        ("watch", "cat <<<'hteam watch'"),
        ("drive", "cat <<EOF\n$(hteam drive)\nEOF"),
        ("horch", "cat <<'EOF'\nx\nEOF\nhorch worker-list"),
        ("horch", "python3 - <<'EOF'\nhorch\nEOF"),
        ("horch", "cat <<EOF-X\n본문\nEOF-X\nhorch run-create --objective demo"),
    )

    def judge(self, hook, name, cmd):
        if name == "watch":
            return hook.watch_denied(cmd, False)
        return hook.drive_denied(cmd) if name == "drive" else hook.horch_denied(cmd)

    def test_rule(self):
        hook = load_hook()
        self.assertEqual([c for n, c in self.ALLOW if self.judge(hook, n, c)], [])
        self.assertEqual([c for n, c in self.DENY if not self.judge(hook, n, c)], [])

    def test_strip_only_the_simple_form(self):
        hook = load_hook()
        self.assertEqual(hook.strip_heredocs("cat > a <<'EOF'\n본문\n둘째\nEOF"), "cat > a <<'EOF'\nEOF")
        for cmd in ("cat > a <<'EOF'\n본문\nEOF\nls", "bash <<'EOF'\n본문\nEOF", "cat > a <<EOF\n본문\nEOF", "ls"):
            self.assertEqual(hook.strip_heredocs(cmd), cmd)
```

- [ ] **Step 2: 시험이 실패하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_hooks.HeredocRuleTest)`
Expected: FAIL — `strip_heredocs` 가 없고, ALLOW 의 cat heredoc 이 거부된다.

- [ ] **Step 3: 구현한다**

**Edit** `herdr-team/hooks/hteam_hook.py`

```python
def horch_denied(cmd: str) -> bool:
```

```python
# 본문을 지워 보는 heredoc(설계 9.7 의 2): 명령 전체가 cat·tee 한 번으로 글을 파일에 옮기는 꼴이고, 끝 표시에 따옴표가 있고
# (본문이 확장되지 않는다), 마지막 줄이 끝 표시다. 그 밖은 원문으로 본다(heredoc 을 해석하는 일반 규칙은 두지 않는다)
_PATH = r"[\w./~-]+"
_SIMPLE_HEREDOC = re.compile(
    rf"\s*(?:cat|tee)(?:\s+(?:>>?\s*{_PATH}|{_PATH}))*\s+<<(-?)\s*(['\"])([A-Za-z_][A-Za-z0-9_]*)\2(?:\s+>>?\s*{_PATH})*\s*")


def strip_heredocs(cmd: str) -> str:
    """판정 셋이 보는 명령(설계 9.7 의 2). 명령 전체가 `cat`·`tee` 한 번(선택지·공백 없는 경로·그 경로로의 `>`·`>>`)과 따옴표
    있는 끝 표시이고 마지막 줄만 끝 표시면 본문을 지운 `<첫 줄>\n<끝 표시 줄>` 이다. 아니면 원문 그대로다. 순수 함수다."""
    lines = cmd.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if len(lines) < 2:
        return cmd
    m = _SIMPLE_HEREDOC.fullmatch(lines[0])
    if not m:
        return cmd
    tabs, delim = m.group(1) == "-", m.group(3)
    ends = [i for i, line in enumerate(lines[1:], 1) if (line.lstrip("\t") if tabs else line) == delim]
    if ends != [len(lines) - 1]:
        return cmd
    return f"{lines[0]}\n{lines[-1]}"


def horch_denied(cmd: str) -> bool:
```

**Edit** `herdr-team/hooks/hteam_hook.py`

```python
    return not hteam_only(cmd) and bool(HORCH_RE.search(cmd))
```

```python
    return not hteam_only(cmd) and bool(HORCH_RE.search(strip_heredocs(cmd)))
```

**Edit** `herdr-team/hooks/hteam_hook.py`

```python
        return i < len(words) and words[i] == "drive"
    return bool(DRIVE_RE.search(cmd))
```

```python
        return i < len(words) and words[i] == "drive"
    return bool(DRIVE_RE.search(strip_heredocs(cmd)))
```

**Edit** `herdr-team/hooks/hteam_hook.py`

```python
        return i < len(words) and words[i] == "watch" and not background
    return bool(WATCH_RE.search(cmd))
```

```python
        return i < len(words) and words[i] == "watch" and not background
    return bool(WATCH_RE.search(strip_heredocs(cmd)))
```

`hteam_hook.py` 머리에 `import os` 가 없으면 더한다(`hteam_only` 가 `os.path.basename` 을 쓰므로 이미 있을 것이다. 확인만 한다).

- [ ] **Step 4: 시험이 통과하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_hooks)`
Expected: OK. 기존 `HorchRuleTest`·`WatchRuleTest`·drive 시험의 모든 거부·허용 사례가 그대로다.

- [ ] **Step 5: 커밋하고 Codex 커밋 리뷰를 건다**

```bash
python3 -m py_compile herdr-team/hooks/hteam_hook.py
git add -- herdr-team/hooks/hteam_hook.py herdr-team/tests/test_hooks.py
git commit -m "fix(herdr-team): 메인 Bash 판정은 cat·tee 로 옮기는 heredoc 본문의 낱말을 보지 않는다(설계 9.7 의 2)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/hooks/hteam_hook.py herdr-team/tests/test_hooks.py
scripts/codex-review.sh commit "$(git rev-parse HEAD)"
```

---

### Task 6: `color.py`(설계 11.10 끝)

**Files:**
- Create: `herdr-team/lib/hteam/color.py`
- Create: `herdr-team/tests/test_color.py`

**Interfaces:**
- Consumes: 없음.
- Produces: 위 "태스크 순서와 인터페이스" 의 `color` 함수 전부.

- [ ] **Step 1: 실패하는 시험을 쓴다**

**Create** `herdr-team/tests/test_color.py`

```python
"""색 계산(설계 11.10, 13단계): 색 글을 OKLCH 로 바꾼다. 값은 조사 자료 anti-slop §4 와 CSS Color 4 의 예다."""
from __future__ import annotations

import unittest

import tests.helpers  # noqa: F401  (lib 를 sys.path 에 넣는다)
from hteam import color

RED = (0.62796, 0.25768, 29.2339)


class ColorTest(unittest.TestCase):
    def close(self, got, want, tol=(0.002, 0.002, 0.3)):
        self.assertIsNotNone(got)
        for g, w, t in zip(got, want, tol):
            self.assertAlmostEqual(g, w, delta=t, msg=(got, want))

    def test_hex(self):
        self.close(color.from_hex("#1e3a8a"), (0.379, 0.138, 265.5))  # Tailwind v3 blue-900
        self.close(color.parse("#d97757"), (0.672, 0.131, 38.8))  # Anthropic 군집의 테라코타
        self.close(color.parse("#FF0000"), RED)
        self.close(color.parse("#f00"), RED)
        self.close(color.parse("#ff0000cc"), RED)  # 알파는 버린다
        self.close(color.from_hex("ff0000"), RED)
        white = color.parse("#fff")
        self.assertAlmostEqual(white[0], 1.0, delta=0.001)
        self.assertLess(white[1], 0.001)
        self.assertEqual(white[2], 0.0)  # 무채색 hue 는 0

    def test_functions(self):
        for text in ("rgb(255 0 0)", "rgb(255, 0, 0)", "rgba(255,0,0,0.5)", "rgb(100% 0% 0%)", "hsl(0 100% 50%)",
                     "hsl(0deg, 100%, 50%)", "hsla(360, 100%, 50%, 1)"):
            self.close(color.parse(text), RED)
        self.assertEqual(color.parse("oklch(62.3% 0.214 259.815)"), (0.623, 0.214, 259.815))
        self.assertEqual(color.parse("oklch(0.5 0 none)"), (0.5, 0.0, 0.0))
        self.close(color.parse("OKLCH(0.7 50% 400deg)"), (0.7, 0.2, 40.0))  # C 100% = 0.4, hue 는 360 으로 나눈 나머지

    def test_unreadable(self):
        for text in ("blue", "#12", "#12345", "rgb(x y z)", "oklch(1 2)", "hsl()", "", "oklch(0.6 0.15 nan)",
                     "oklch(inf 0.1 30)", "rgb(nan 0 0)", "hsl(nan 100% 50%)"):
            self.assertIsNone(color.parse(text), text)

    def test_distances(self):
        self.assertEqual(color.hue_distance(350, 10), 20)
        self.assertEqual(color.hue_distance(10, 350), 20)
        self.assertEqual(color.hue_distance(0, 180), 180)
        self.assertEqual(color.hue_distance(30, 30), 0)
        self.assertLess(color.delta(color.parse("#1e3a8a"), color.parse("#1e3a8b")), 0.01)
        self.assertGreater(color.delta(color.parse("#ff0000"), color.parse("#0000ff")), 0.3)
        L, a, b = color.oklab((0.5, 0.1, 90.0))
        self.assertAlmostEqual(L, 0.5)
        self.assertAlmostEqual(a, 0.0, places=9)
        self.assertAlmostEqual(b, 0.1, places=9)
```

- [ ] **Step 2: 시험이 실패하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_color)`
Expected: FAIL — `ImportError: cannot import name 'color'`.

- [ ] **Step 3: 구현한다**

**Create** `herdr-team/lib/hteam/color.py`

```python
"""색 글을 OKLCH 로 바꾼다(설계 11.10, 13단계). 표준 라이브러리만 쓴다. sRGB → 선형 → OKLab 은 Björn Ottosson 의 행렬이다.
lint(11.13)·deal 시험·획일도 측정(15.5)이 같이 쓴다. HSL 기준 lint.hue_family(그라디언트 검사)는 바꾸지 않는다."""
from __future__ import annotations

import colorsys
import math
import re

LCH = tuple[float, float, float]  # (L 0–1, C, h 0–360). C 가 ACHROMATIC_C 보다 작으면 h 는 0.0
ACHROMATIC_C = 1e-4
_HEX = re.compile(r"#?([0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})")
_FUNC = re.compile(r"(rgba?|hsla?|oklch)\(\s*([^()]*)\)", re.I)


def _linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _hue(c: float, h: float) -> float:
    return h % 360 if c >= ACHROMATIC_C else 0.0


def from_srgb(r: float, g: float, b: float) -> LCH:
    """sRGB(각 0–1, 범위 밖은 자른다)의 OKLCH."""
    r, g, b = (_linear(min(max(x, 0.0), 1.0)) for x in (r, g, b))
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l, m, s = (math.copysign(abs(x) ** (1 / 3), x) for x in (l, m, s))
    lightness = 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s
    a = 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s
    bb = 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s
    chroma = math.hypot(a, bb)
    return (lightness, chroma, _hue(chroma, math.degrees(math.atan2(bb, a))))


def from_hex(text: str) -> LCH | None:
    """`#rgb`·`#rgba`·`#rrggbb`·`#rrggbbaa`(# 없어도 된다, 알파는 버린다)."""
    m = _HEX.fullmatch(text.strip())
    if not m:
        return None
    digits = m.group(1)
    if len(digits) in (3, 4):
        digits = "".join(ch * 2 for ch in digits[:3])
    return from_srgb(*(int(digits[i:i + 2], 16) / 255 for i in (0, 2, 4)))


def _parts(args: str) -> list[str]:
    return [x for x in re.split(r"[\s,/]+", args.strip()) if x]


def _num(text: str) -> float:
    """수 글 하나. NaN·무한대는 ValueError(색으로 받지 않는다)."""
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(text)
    return value


def _angle(text: str) -> float:
    return _num(text.lower().removesuffix("deg"))


def parse(text: str) -> LCH | None:
    """색 글 하나(hex, `rgb()`·`rgba()`, `hsl()`·`hsla()`, `oklch()`)의 OKLCH. 못 읽거나 NaN·무한대가 섞이면 None."""
    lch = _parse(text)
    return lch if lch is not None and all(math.isfinite(x) for x in lch) else None


def _parse(text: str) -> LCH | None:
    t = text.strip()
    if t.startswith("#"):
        return from_hex(t)
    m = _FUNC.fullmatch(t)
    if not m:
        return None
    name, args = m.group(1).lower(), _parts(m.group(2))
    if len(args) < 3:
        return None
    try:
        if name.startswith("rgb"):
            return from_srgb(*(_num(x[:-1]) / 100 if x.endswith("%") else _num(x) / 255 for x in args[:3]))
        if name.startswith("hsl"):
            h, s, l = _angle(args[0]), _num(args[1].rstrip("%")) / 100, _num(args[2].rstrip("%")) / 100
            return from_srgb(*colorsys.hls_to_rgb((h % 360) / 360, l, s))
        lightness = _num(args[0][:-1]) / 100 if args[0].endswith("%") else _num(args[0])
        chroma = _num(args[1][:-1]) / 100 * 0.4 if args[1].endswith("%") else _num(args[1])
        h = 0.0 if args[2].lower() == "none" else _angle(args[2])
        return (lightness, chroma, _hue(chroma, h))
    except ValueError:
        return None


def hue_distance(a: float, b: float) -> float:
    """두 hue 의 원형 거리(0–180)."""
    d = abs(a - b) % 360
    return min(d, 360 - d)


def oklab(lch: LCH) -> tuple[float, float, float]:
    lightness, chroma, h = lch
    r = math.radians(h)
    return (lightness, chroma * math.cos(r), chroma * math.sin(r))


def delta(x: LCH, y: LCH) -> float:
    """두 색의 OKLab 유클리드 거리. 0.02 아래면 눈으로 거의 같다(획일도 측정의 과용 색 일치)."""
    return math.dist(oklab(x), oklab(y))
```

- [ ] **Step 4: 시험이 통과하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_color -v)`
Expected: OK(넷).

- [ ] **Step 5: 커밋하고 Codex 커밋 리뷰를 건다**

```bash
python3 -m py_compile herdr-team/lib/hteam/color.py
git add -- herdr-team/lib/hteam/color.py herdr-team/tests/test_color.py
git commit -m "feat(herdr-team): color.py — 색 글을 OKLCH 로(설계 11.10)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/lib/hteam/color.py herdr-team/tests/test_color.py
scripts/codex-review.sh commit "$(git rev-parse HEAD)"
```

---

### Task 7: 획일도 측정 스크립트(설계 15.5)

저장소 개발용이다. 플러그인에 넣지 않는다. 이 태스크는 스크립트·브리프·순수 함수 시험을 만들고 claude 호출 한 번으로 플래그를 확인한다. 실제 측정(before·after 두 판)은 p13b 의 마지막 태스크에서 한다(`overused.json`·`palette.py` 가 그때 생긴다).

**Files:**
- Create: `scripts/design-eval/briefs.json`
- Create: `scripts/design-eval/eval.py`
- Create: `scripts/design-eval/test_eval.py`
- Modify: `.gitignore`(`.design-eval/`)

**Interfaces:**
- Consumes: Task 6 의 `color.parse`·`color.hue_distance`·`color.delta`. p13b 의 `palette.deal(seed)`·`data/overused.json`·`templates/palette.md`·`templates/fonts-ko.md`(`after` 판과 `metrics` 만).
- Produces: `python3 scripts/design-eval/eval.py run|metrics|report|judge-prompt`. 함수 `stage2`, `parse_output`, `validate`, `is_cluster`, `metrics`.

- [ ] **Step 1: 브리프와 실패하는 시험을 쓴다**

**Create** `scripts/design-eval/briefs.json`

```json
[
 {"id": "budget", "name": "두런 가계부", "desc": "맞벌이 부부가 함께 쓰는 모바일 가계부. 카드 문자로 지출을 모으고 달마다 예산을 나눈다.",
  "users": "30대 맞벌이 부부, 퇴근 뒤 휴대폰으로 5분 정도 본다", "screens": ["이번 달 요약", "지출 내역 목록", "지출 직접 입력"]},
 {"id": "clinic", "name": "골목의원 예약", "desc": "동네 내과·소아과의 진료 예약과 대기 순서 확인. 접수 직원이 웹으로 예약을 관리한다.",
  "users": "아이를 데려가는 보호자와 노년 환자, 접수 직원", "screens": ["예약 가능한 시간", "오늘 대기 명단", "예약 정보 입력"]},
 {"id": "bookshop", "name": "책방 소요", "desc": "독립 서점의 웹사이트. 이달의 추천 책, 낭독회 일정, 온라인 주문을 한다.",
  "users": "동네 독자와 책을 좋아하는 20–40대", "screens": ["이달의 추천", "재고 책 목록", "낭독회 신청"]},
 {"id": "inventory", "name": "적재 재고판", "desc": "중소 제조사의 B2B 재고 대시보드. 창고 셋의 품목별 재고와 입출고를 본다.",
  "users": "창고 관리자와 구매 담당, 업무 시간 내내 큰 모니터로 본다", "screens": ["창고별 재고 현황", "품목 입출고 기록", "입고 등록"]},
 {"id": "kids", "name": "콩콩 낱말놀이", "desc": "5–7세 어린이의 한글 낱말 익히기 앱. 그림 카드를 맞히고 별을 모은다. 보호자 화면이 따로 있다.",
  "users": "5–7세 어린이와 보호자", "screens": ["오늘의 놀이", "보호자의 학습 기록", "아이 프로필 만들기"]}
]
```

**Create** `scripts/design-eval/test_eval.py`

```python
"""획일도 측정 스크립트의 순수 함수 시험(설계 15.5). claude·codex 를 부르지 않는다."""
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("design_eval", HERE / "eval.py")
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)


def option(accent="oklch(0.6 0.15 30)", bg="oklch(0.98 0.01 90)", heading_class="돋움", body_font="SUIT",
           posture="절제"):
    return {"bg": bg, "ink": "oklch(0.2 0.01 90)", "accent": accent, "neutral": "틴트", "heading_font": "Hahmlet",
            "heading_class": heading_class, "body_font": body_font, "posture": posture, "radius": 6,
            "mood": "봄 시장 좌판의 종이 간판", "idea": "영수증 모양 요약"}


def run(*accents, valid=True, **kw):
    if not valid:
        return {"valid": False, "output": None, "error": "JSON 이 아니다"}
    return {"valid": True, "output": {k: option(accent=a, **kw) for k, a in zip("ABC", accents)}}


OVERUSED = {"colors": [{"hex": "#1e3a8a", "name": "Tailwind blue-900"}], "tailwind_ramp": ["#fb923c"],
            "fonts": ["Pretendard", "Noto Sans KR"]}


class EvalTest(unittest.TestCase):
    def test_stage2_is_cut_from_director(self):
        director = (HERE.parents[1] / "herdr-team" / "templates" / "roles" / "director.md").read_text(encoding="utf-8")
        text = ev.stage2(director)
        self.assertTrue(text.startswith("## 단계 ② 톤 시안"))
        self.assertNotIn("## 단계 ③", text)

    def test_parse_output(self):
        self.assertEqual(ev.parse_output('```json\n{"A": 1}\n```'), {"A": 1})
        self.assertEqual(ev.parse_output('{"A": 1}'), {"A": 1})
        self.assertIsNone(ev.parse_output("[1, 2]"))
        self.assertIsNone(ev.parse_output("설명 {"))

    def test_validate(self):
        good = run("oklch(0.6 0.15 30)", "oklch(0.6 0.15 120)", "oklch(0.6 0.15 210)")["output"]
        self.assertIsNone(ev.validate(good))
        bad = json.loads(json.dumps(good))
        del bad["C"]
        self.assertEqual(ev.validate(bad), "C 가 없다")
        bad = json.loads(json.dumps(good))
        bad["A"]["accent"] = "oklch(0.6 0.01 30)"
        self.assertEqual(ev.validate(bad), "A.accent 가 무채색이다")
        bad = json.loads(json.dumps(good))
        bad["B"]["heading_class"] = "세리프"
        self.assertEqual(ev.validate(bad), "B.heading_class 가 돋움·부리·표시가 아니다")
        bad = json.loads(json.dumps(good))
        bad["B"]["bg"] = "아이보리"
        self.assertEqual(ev.validate(bad), "B.bg 를 색으로 읽지 못했다")
        bad = json.loads(json.dumps(good))
        bad["C"]["mood"] = " "
        self.assertEqual(ev.validate(bad), "C.mood 가 비었다")

    def test_cluster(self):
        self.assertTrue(ev.is_cluster(option(accent="oklch(0.6 0.13 39)", bg="oklch(0.95 0.02 85)", heading_class="부리")))
        self.assertFalse(ev.is_cluster(option(accent="oklch(0.6 0.13 39)", bg="oklch(0.95 0.02 85)")))  # 돋움 제목
        self.assertFalse(ev.is_cluster(option(accent="oklch(0.6 0.13 150)", bg="oklch(0.95 0.02 85)",
                                              heading_class="부리")))

    def test_metrics_count_failed_runs_against_targets(self):
        runs = [run("oklch(0.6 0.15 30)", "oklch(0.6 0.15 120)", "oklch(0.6 0.15 210)"),  # 거리 90
                run("oklch(0.6 0.15 250)", "oklch(0.6 0.15 280)", "oklch(0.6 0.15 30)", body_font="Pretendard"),
                run(valid=False)]
        m = ev.metrics(runs, OVERUSED)
        self.assertEqual((m["runs"], m["valid"], m["measured"]), (3, 2, False))  # 2/3 < 80%
        self.assertEqual(m["blue_violet"], round((2 + 3) / 9, 3))  # 실패 실행의 세 안은 나쁜 쪽으로 센다
        self.assertEqual(m["spread_ge_60"], round(1 / 3, 3))
        self.assertEqual(m["overused_body"], round((3 + 3) / 9, 3))
        self.assertEqual(m["cluster"], 0)
        self.assertEqual(sum(m["buckets"]), 6)
        self.assertEqual(m["targets"], {"blue_violet_le_20": False, "spread_ge_60_ge_90": False,
                                        "overused_body_le_40": False, "cluster_zero": True})
        hit = run("#1e3a8a", "oklch(0.6 0.15 120)", "oklch(0.6 0.15 210)")
        self.assertEqual(ev.metrics([hit], OVERUSED)["overused_color_hits"], 1)
        variant = run("oklch(0.6 0.15 30)", "oklch(0.6 0.15 120)", "oklch(0.6 0.15 210)", body_font="Pretendard Variable")
        self.assertEqual(ev.metrics([variant], OVERUSED)["overused_body"], 1.0)

    def test_judge_prompt_tolerates_missing_optional_fields(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            r = run("oklch(0.6 0.15 30)", "oklch(0.6 0.15 120)", "oklch(0.6 0.15 210)")
            del r["output"]["A"]["idea"]  # 유효 조건에 들지 않는 필드
            r["output"]["B"]["mood"] = "가|나\n둘째 줄"  # 표를 깨는 글자와 개행
            (folder / "budget-1.json").write_text(json.dumps({"brief": "budget", "rep": 1, **r}, ensure_ascii=False),
                                                  encoding="utf-8")
            text = ev.judge_prompt(folder).read_text(encoding="utf-8")
        self.assertIn("| budget | 1 | A |", text)
        self.assertIn("| 봄 시장 좌판의 종이 간판 | - |", text)
        self.assertIn("| 가/나 둘째 줄 |", text)
```

- [ ] **Step 2: 시험이 실패하는지 본다**

Run: `python3 -m unittest discover -s scripts/design-eval -p 'test_*.py'`
Expected: FAIL — `eval.py` 가 없다.

- [ ] **Step 3: 스크립트를 쓴다**

**Create** `scripts/design-eval/eval.py`

```python
#!/usr/bin/env python3
"""획일도 측정(설계 15.5, 13단계). 저장소 개발용이고 플러그인에 넣지 않는다.

  python3 scripts/design-eval/eval.py run --variant before|after [--reps 2] [--briefs budget,clinic]
  python3 scripts/design-eval/eval.py metrics <결과 폴더>
  python3 scripts/design-eval/eval.py report <before 폴더> <after 폴더>
  python3 scripts/design-eval/eval.py judge-prompt <결과 폴더>

run 은 claude -p(opus, 도구 없음, 사용자 설정·플러그인 없음)를 빈 임시 폴더에서 부른다. 결과는 저장소 .design-eval/ 아래다
(git 제외). before 판은 0.7.2(커밋 8cd549c)의 director.md·design-rules.md 를 git 에서 읽고, after 판은 작업 트리의 템플릿과
palette.deal 의 배정을 쓴다. 정성 판정은 judge-prompt 가 만든 프롬프트를 scripts/codex-review.sh doc 으로 돌린다.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LIB = REPO / "herdr-team" / "lib"
sys.path.insert(0, str(LIB))
from hteam import color  # noqa: E402

BASE = "8cd549c"  # 0.7.2(설계 15.5 의 before)
OUT = REPO / ".design-eval"
BRIEFS = Path(__file__).with_name("briefs.json")
OVERUSED = LIB / "hteam" / "data" / "overused.json"
CLASSES = ("돋움", "부리", "표시")
CLAUDE = ["claude", "-p", "--model", "opus", "--tools", "", "--output-format", "json", "--no-session-persistence",
          "--strict-mcp-config", "--setting-sources", "project"]
SCHEMA = ('JSON 객체 하나만 낸다(코드 블록·설명 없이). 키는 "A"·"B"·"C" 이고 값마다 다음 키를 둔다: "bg"·"ink"·"accent"'
          '(색, oklch(L C H) 글), "neutral"("순회색" 또는 "틴트"), "heading_font"·"body_font"(글꼴 이름), "heading_class"'
          '("돋움"·"부리"·"표시" 가운데 하나), "posture"(색 자세 낱말), "radius"(px 수), "mood"(무드 문장), "idea"(이 서비스만의 '
          '아이디어 한 문장).')


def stage2(director: str) -> str:
    """director.md 의 `## 단계 ② 톤 시안` 절(다음 `## ` 앞까지)."""
    m = re.search(r"^## 단계 ② 톤 시안\n.*?(?=^## )", director, re.M | re.S)
    if not m:
        raise SystemExit("director.md 에 단계 ② 절이 없다")
    return m.group(0).strip()


def sources(variant: str) -> dict[str, str]:
    tpl = REPO / "herdr-team" / "templates"
    if variant == "before":
        def show(rel: str) -> str:
            return subprocess.run(["git", "-C", str(REPO), "show", f"{BASE}:herdr-team/templates/{rel}"],
                                  capture_output=True, text=True, check=True).stdout
        return {"director": show("roles/director.md"), "design_rules": show("design-rules.md")}
    out = {"director": (tpl / "roles" / "director.md").read_text(encoding="utf-8"),
           "design_rules": (tpl / "design-rules.md").read_text(encoding="utf-8")}
    for name in ("palette.md", "fonts-ko.md"):
        if not (tpl / name).is_file():
            raise SystemExit(f"after 판에는 templates/{name} 가 필요하다(p13b 뒤에 잰다)")
        out[name] = (tpl / name).read_text(encoding="utf-8")
    return out


def deal_for(brief_id: str, rep: int) -> dict:
    from hteam import palette  # p13b 가 만든다(after 판만)
    return palette.deal(f"{brief_id}:{rep}")


def prompt(variant: str, src: dict, brief: dict, deal: dict | None = None) -> str:
    parts = ["너는 herdr-team 의 디자인 디렉터다. 아래 지시의 단계 ② 톤 시안만 한다. 도구를 쓰지 않고, 아티팩트를 만들지 않고, "
             "질문하지 않는다. 실제 디렉터라면 만들 톤 A·B·C 를 정해 JSON 으로만 답한다.",
             "## 서비스", json.dumps(brief, ensure_ascii=False, indent=1),
             "## 지시(director.md 단계 ②)", stage2(src["director"]),
             "## 디자인 규칙(design-rules.md)", src["design_rules"]]
    if variant == "after":
        parts += ["## 배정 절차(palette.md)", src["palette.md"], "## 한글 글꼴(fonts-ko.md)", src["fonts-ko.md"],
                  "## 받은 배정(hteam palette deal 출력)", json.dumps(deal, ensure_ascii=False, indent=1)]
    parts += ["## 출력", SCHEMA]
    return "\n\n".join(parts) + "\n"


def parse_output(text: str) -> dict | None:
    t = text.strip()
    m = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", t, re.S)
    if m:
        t = m.group(1)
    try:
        obj = json.loads(t)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def validate(obj) -> str | None:
    """유효하면 None, 아니면 까닭(설계 15.5 의 유효한 실행)."""
    if not isinstance(obj, dict):
        return "JSON 객체가 아니다"
    for key in "ABC":
        opt = obj.get(key)
        if not isinstance(opt, dict):
            return f"{key} 가 없다"
        for name in ("bg", "ink", "accent"):
            if not isinstance(opt.get(name), str) or color.parse(opt[name]) is None:
                return f"{key}.{name} 를 색으로 읽지 못했다"
        if color.parse(opt["accent"])[1] < 0.03:
            return f"{key}.accent 가 무채색이다"
        for name in ("heading_font", "body_font", "posture", "mood"):
            if not isinstance(opt.get(name), str) or not opt[name].strip():
                return f"{key}.{name} 가 비었다"
        if opt.get("heading_class") not in CLASSES:
            return f"{key}.heading_class 가 돋움·부리·표시가 아니다"
    return None


def call_claude(text: str, cwd: Path) -> str:
    env = {**os.environ, "DISABLE_AUTOUPDATER": "1"}
    proc = subprocess.run(CLAUDE + [text], cwd=cwd, capture_output=True, text=True, timeout=900, env=env)
    if proc.returncode != 0:
        raise RuntimeError(f"claude exit {proc.returncode}: {proc.stderr[-300:]}")
    return str(json.loads(proc.stdout).get("result", ""))


def run(variant: str, reps: int, only: list[str]) -> Path:
    briefs = [b for b in json.loads(BRIEFS.read_text(encoding="utf-8")) if not only or b["id"] in only]
    src = sources(variant)
    out = OUT / f"{dt.datetime.now():%Y%m%d-%H%M%S}-{variant}"
    out.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="design-eval-") as tmp:
        for brief in briefs:
            for rep in range(1, reps + 1):
                deal = deal_for(brief["id"], rep) if variant == "after" else None
                text = prompt(variant, src, brief, deal)
                record = {"brief": brief["id"], "rep": rep, "variant": variant, "deal": deal, "attempts": []}
                obj, why = None, "실행 안 함"
                for attempt in range(2):
                    ask = text if attempt == 0 else text + f"\n앞 출력이 형식에 맞지 않았다({why}). JSON 객체 하나만 다시 낸다.\n"
                    try:
                        raw = call_claude(ask, Path(tmp))
                    except (RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
                        raw, obj, why = "", None, f"호출 실패: {exc}"
                    else:
                        obj = parse_output(raw)
                        why = validate(obj) if obj is not None else "JSON 이 아니다"
                    record["attempts"].append({"raw": raw, "error": why})
                    if why is None:
                        break
                record.update(output=obj if why is None else None, valid=why is None, error=why)
                (out / f"{brief['id']}-{rep}.json").write_text(json.dumps(record, ensure_ascii=False, indent=1),
                                                               encoding="utf-8")
                print(f"{brief['id']} {rep}: {'ok' if why is None else why}", flush=True)
    return out


def _font(name: str) -> str:
    return re.sub(r"[\s\"']", "", name.split(",")[0]).lower()


def is_cluster(opt: dict) -> bool:
    """크림·베이지 배경 + 부리 제목 + 테라코타 강조(설계 15.5)."""
    bg, accent = color.parse(opt["bg"]), color.parse(opt["accent"])
    return (bg[0] >= 0.9 and 60 <= bg[2] <= 100 and 0.01 <= bg[1] <= 0.05 and opt.get("heading_class") == "부리"
            and 20 <= accent[2] <= 50)


def metrics(runs: list[dict], overused: dict) -> dict:
    """설계 15.5 의 숫자. 비율은 모든 실행의 안(실행 × 3)이 분모이고 실패한 실행의 세 안은 나쁜 쪽으로 센다(거리는 60° 미만).
    군집 수는 유효한 실행만 센다. 유효한 실행이 80% 보다 적으면 measured 가 거짓이다(다시 잰다)."""
    total = len(runs)
    valid = [r for r in runs if r.get("valid")]
    failed = total - len(valid)
    options = [r["output"][k] for r in valid for k in "ABC"]
    hues = [color.parse(o["accent"])[2] for o in options]
    buckets = Counter(int(h // 30) % 12 for h in hues)
    shares = [buckets[i] / len(hues) for i in range(12) if hues and buckets[i]]
    slots = max(total * 3, 1)

    def spread(r: dict) -> float:
        hs = [color.parse(r["output"][k]["accent"])[2] for k in "ABC"]
        return min(color.hue_distance(a, b) for i, a in enumerate(hs) for b in hs[i + 1:])

    fonts = {_font(f) for f in overused.get("fonts", [])}
    pool = [color.parse(c["hex"]) for c in overused.get("colors", [])]
    ramp = [color.parse(h) for h in overused.get("tailwind_ramp", [])]

    def hits(group: list) -> int:
        return sum(1 for o in options for k in ("bg", "ink", "accent")
                   if any(p is not None and color.delta(color.parse(o[k]), p) < 0.02 for p in group))

    out = {
        "runs": total, "valid": len(valid), "measured": total > 0 and len(valid) >= 0.8 * total,
        "buckets": [buckets[i] for i in range(12)],
        "entropy": round(-sum(s * math.log2(s) for s in shares), 3),
        "blue_violet": round((sum(1 for h in hues if 240 <= h < 300) + failed * 3) / slots, 3),
        "spread_ge_60": round(sum(1 for r in valid if spread(r) >= 60) / max(total, 1), 3),
        "overused_body": round((sum(1 for o in options if any(_font(o["body_font"]).startswith(f) for f in fonts))
                                + failed * 3) / slots, 3),  # 'Pretendard Variable' 같은 표기 변형도 센다
        "overused_color_hits": hits(pool), "tailwind_ramp_hits": hits(ramp),
        "cluster": sum(1 for o in options if is_cluster(o)),
        "postures": dict(Counter(o["posture"] for o in options)),
    }
    out["targets"] = {"blue_violet_le_20": out["blue_violet"] <= 0.20, "spread_ge_60_ge_90": out["spread_ge_60"] >= 0.90,
                      "overused_body_le_40": out["overused_body"] <= 0.40, "cluster_zero": out["cluster"] == 0}
    return out


def load_runs(folder: Path) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*-[0-9]*.json"))]


def load_overused() -> dict:
    if not OVERUSED.is_file():
        raise SystemExit(f"{OVERUSED.relative_to(REPO)} 가 없다(p13b 의 카탈로그 뒤에 집계한다)")
    return json.loads(OVERUSED.read_text(encoding="utf-8"))


def write_metrics(folder: Path) -> dict:
    m = metrics(load_runs(folder), load_overused())
    (folder / "metrics.json").write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    return m


def report(before: Path, after: Path) -> Path:
    a, b = write_metrics(before), write_metrics(after)
    rows = [("유효 실행", f"{a['valid']}/{a['runs']}", f"{b['valid']}/{b['runs']}", "80% 이상"),
            ("240–300° 주 강조 비율", a["blue_violet"], b["blue_violet"], "≤ 0.20"),
            ("최소 hue 거리 60° 이상 실행 비율", a["spread_ge_60"], b["spread_ge_60"], "≥ 0.90"),
            ("과용 한글 본문 글꼴 비율", a["overused_body"], b["overused_body"], "≤ 0.40"),
            ("크림+세리프+테라코타 군집", a["cluster"], b["cluster"], "0"),
            ("hue 12칸 엔트로피(bit)", a["entropy"], b["entropy"], "높을수록 고르다"),
            ("과용 색 일치", a["overused_color_hits"], b["overused_color_hits"], "-"),
            ("Tailwind 램프 일치", a["tailwind_ramp_hits"], b["tailwind_ramp_hits"], "-")]
    lines = [f"# 획일도 측정 {dt.date.today()}", "", f"- before: `{before.name}`", f"- after: `{after.name}`", "",
             "| 지표 | before | after | 목표 |", "|---|---|---|---|"]
    lines += [f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} |" for r in rows]
    lines += ["", f"- after 목표: {json.dumps(b['targets'], ensure_ascii=False)}",
              f"- before hue 칸: {a['buckets']}", f"- after hue 칸: {b['buckets']}",
              f"- before 자세: {a['postures']}", f"- after 자세: {b['postures']}"]
    path = OUT / f"report-{dt.datetime.now():%Y%m%d-%H%M%S}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def judge_prompt(folder: Path) -> Path:
    rows = []
    for r in load_runs(folder):
        if not r.get("valid"):
            continue
        for k in "ABC":
            o = r["output"][k]
            cell = {name: " ".join(str(o.get(name) or "-").replace("|", "/").split()) for name in
                    ("bg", "ink", "accent", "heading_font", "heading_class", "body_font", "posture", "mood", "idea")}
            rows.append(f"| {r['brief']} | {r['rep']} | {k} | {cell['bg']} / {cell['ink']} / {cell['accent']} | "
                        f"{cell['heading_font']}({cell['heading_class']}) / {cell['body_font']} | {cell['posture']} | "
                        f"{cell['mood']} | {cell['idea']} |")
    text = "\n".join([
        "너는 디자인 리뷰어다. 읽기만 한다. 아래 표는 같은 지시를 받은 디자인 디렉터가 서비스 브리프 다섯에 낸 톤 시안이다"
        f"(판 `{folder.name}`). 브리프는 `scripts/design-eval/briefs.json` 이다.",
        "안마다 다음을 매긴다: AI 군집 닮음 1–5(5 = AI 생성 디자인의 흔한 모습: 크림+세리프+테라코타, 슬레이트+파랑, 검정+네온, "
        "옅은 배경+소심한 강조 하나), 거울 시험 예/아니오(같은 분야 다른 서비스에 그대로 붙여도 맞으면 예), 무드 구체성 1–5"
        "(5 = 구체적인 장면·소재), 한 줄 이유.",
        "출력: 마크다운 표 `| 브리프 | 반복 | 안 | 군집 닮음 | 거울 | 구체성 | 이유 |` 와 마지막 줄 "
        "`평균 군집 닮음 <x>, 거울 예 <n>/<m>, 평균 구체성 <y>`.", "",
        "| 브리프 | 반복 | 안 | 배경/글자/강조 | 제목(계열)/본문 글꼴 | 자세 | 무드 | 아이디어 |",
        "|---|---|---|---|---|---|---|---|", *rows])
    path = folder / "judge-prompt.md"
    path.write_text(text + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="획일도 측정(설계 15.5)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--variant", choices=("before", "after"), required=True)
    r.add_argument("--reps", type=int, default=2)
    r.add_argument("--briefs", default="")
    sub.add_parser("metrics").add_argument("folder", type=Path)
    rp = sub.add_parser("report")
    rp.add_argument("before", type=Path)
    rp.add_argument("after", type=Path)
    sub.add_parser("judge-prompt").add_argument("folder", type=Path)
    args = ap.parse_args(argv)
    if args.cmd == "run":
        print(run(args.variant, args.reps, [x for x in args.briefs.split(",") if x]))
    elif args.cmd == "metrics":
        print(json.dumps(write_metrics(args.folder), ensure_ascii=False, indent=1))
    elif args.cmd == "report":
        print(report(args.before, args.after))
    else:
        path = judge_prompt(args.folder)
        print(path)
        print(f"scripts/codex-review.sh doc design-eval-{args.folder.name} {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**Edit** `.gitignore`

```
.codex-reviews/
```

```
.codex-reviews/
.design-eval/
```

- [ ] **Step 4: 시험이 통과하는지 본다**

Run: `python3 -m unittest discover -s scripts/design-eval -p 'test_*.py' -v`
Expected: OK(여섯).

- [ ] **Step 5: claude 호출 한 번으로 플래그를 확인한다(사용자 터미널·시험 프로젝트를 건드리지 않는다)**

Run: `python3 scripts/design-eval/eval.py run --variant before --reps 1 --briefs budget`
Expected: `budget 1: ok` 와 결과 폴더 경로. 결과 JSON 의 `attempts[0].error` 가 null 이다.
- `claude` 가 플래그를 거부하면(예: `--setting-sources` 의 값) `claude --help` 로 맞는 꼴을 찾아 `CLAUDE` 목록을 고치고 다시 한다. 고친 내용과 까닭을 커밋 메시지에 적는다.
- 인증이 안 되면 사용자에게 알리고 멈춘다(`--bare` 는 OAuth 를 읽지 않으므로 쓰지 않는다).
- 이 결과 폴더는 측정에 쓰지 않는다(`.design-eval/` 는 git 제외. 지워도 된다).

- [ ] **Step 6: 커밋하고 Codex 커밋 리뷰를 건다**

```bash
python3 -m py_compile scripts/design-eval/eval.py
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews'
git add -- scripts/design-eval/briefs.json scripts/design-eval/eval.py scripts/design-eval/test_eval.py .gitignore
git commit -m "feat: 획일도 측정 스크립트(설계 15.5) — 브리프 다섯, claude -p 생성, 숫자 집계, Codex 판정 프롬프트

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- scripts/design-eval/briefs.json scripts/design-eval/eval.py scripts/design-eval/test_eval.py .gitignore
scripts/codex-review.sh commit "$(git rev-parse HEAD)"
```

---

## p13a 끝

- 전체 시험: `bash herdr-team/tests/run.sh` 를 백그라운드로 돌리고(약 22분) 끝 알림을 받는다. 그다음 `bash herdr-orch/tests/run.sh`(약 2분). 둘을 동시에 돌리지 않는다.
- 태스크마다 Codex 커밋 리뷰 지적을 처리한 수정 커밋도 같은 방식으로 리뷰한다(리뷰 수정 범위는 Global Constraints).
- p13b 계획(`docs/superpowers/plans/2026-11-17-herdr-team-p13b.md`)을 쓴다. p13b 의 마지막 태스크가 획일도 측정 before·after 를 잰다.
