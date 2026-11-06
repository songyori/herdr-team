# herdr-team 2단계(기획 인터뷰와 승인) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 설계 15.3 의 2단계를 만든다: 기획 인터뷰 체크리스트·확정 질문(10장), 승인 직무와 `awaiting_user` 흐름, 사용자 일괄 승인 `hteam design-review`(11.4), designer 기본 직무. 1단계가 넘긴 정확성 결함(변조 검사의 심볼릭 링크·실행 비트·경로 디코딩, 코디네이터 루프와 훅의 작은 결함)도 고친다.

**Architecture:** 새 모듈 `herdr-team/lib/hteam/approval.py` 가 승인 상황(`view`)과 일괄 승인 묶음(`design-review`)을 맡는다. 묶음은 `state/design-review.json` 에 먼저 기록하고 outbox 의 `approval` 항목으로 쓴다(그 사이 죽어도 두 번 묻지 않는다). `coord.py` 는 이 모듈로 `status` 의 awaiting_user `next` 와 `wait` 의 답 주석(`design_review`)을 만든다. 인터뷰 규칙은 hteam 코드가 아니라 planner 직무 문서가 담는다(설계 10장). 리뷰어는 `hteam ask-user --history` 로 실제 질문과 답을 확인한다. 정리 태스크 둘은 `gitio.py` 의 무손실 경로와 git 항목(모드·객체 ID) 비교, 그리고 루프의 작은 결함을 고친다.

**Tech Stack:** Python 3.11+ 표준 라이브러리(argparse, tomllib, subprocess, fcntl, unittest), git, herdr-orch 0.1.1(`horch`, 바꾸지 않는다), herdr-core `hc`, herdr-app, Claude Code CLI, Codex CLI.

**설계 문서:** `docs/superpowers/specs/2026-11-05-herdr-team-design.md`(이하 "설계"). 2단계 범위는 설계 15.3 의 2번이다. 함께 볼 절: 5.2(승인 사슬 plan check), 5.3(awaiting_user, 의존 끝 조건), 6.4(awaiting_user 에서 accept·fix), 7.4–7.6(질문·approval·render), 10장, 11.2(designer 기본만), 11.4(design-review), 13장, 15.4(1단계 결과). 디렉터·Claude Design·`hteam image`·`lint`·리뷰 디자인 절·보강 루프는 3단계다. 계획과 설계가 다르면 설계가 맞다. 다르면 멈추고 사용자에게 묻는다.

**코드가 기준이다.** 1단계 코드는 여러 리뷰 라운드를 거치며 1단계 계획(`docs/superpowers/plans/2026-11-05-herdr-team-p1.md`)과 달라졌다(잠금 순서 프로젝트 → finish → 태스크, `dispatch.owned`·`left_running`, `tasks.Capacity`, review 가 finish 잠금을 쥠, `outbox.require_main`, 엄격한 `run.json` 읽기, `globs.overlaps` 의 대소문자·유니코드 세 갈래 판정, 훅의 horch 규칙 등). 이 계획의 수정은 모두 지금 `herdr-team/` 코드에 대한 부분 수정이다. 1단계 계획의 코드 목록을 옮겨 쓰지 않는다. 파일 전체를 바꾸지 않는다.

**편집 표기:** `**Create** \`경로\`` 다음 코드 블록은 새 파일 전체다. `**Edit** \`경로\`` 다음 두 코드 블록은 "찾을 내용"과 "바꿀 내용"이다. 찾을 내용은 그 파일에서 정확히 한 번 나와야 한다(앞 태스크의 수정을 반영한 내용이다). 안에 ``` 가 든 블록은 ```` 로 감쌌다.

## Global Constraints

- Python 3.11 이상, 표준 라이브러리만. 외부 패키지 금지. 3.11 에서도 동작해야 한다(닫힌 stdin 이 붙은 채로 `communicate()` 를 부르지 않는다. 테스트 하네스는 `proc.stdin = None` 으로 뗀다).
- 모듈 경계: `hc`·`herdr-app` 은 `herdr-team/lib/hteam/herdr.py` 에서만, `horch` 는 `herdr-team/lib/hteam/horch.py` 에서만 부른다(시작 장벽 `launch.py` 는 `horch.py` 가 만든 argv 를 exec 할 뿐이다), git 은 `herdr-team/lib/hteam/gitio.py` 에서만 부른다. 훅(`hooks/hteam_hook.py`)도 이 모듈들을 거친다. 새 모듈 `approval.py` 는 셋 중 아무것도 직접 부르지 않는다.
- hteam 은 horch 를 늘 `--home <프로젝트>/.herdr-team/state/horch` 로 부른다. 찾는 순서는 지금 코드 그대로다(`HERDR_ORCH_BIN` → 형제 `../herdr-orch/bin/horch` → `installed_plugins.json`, 테스트는 `HTEAM_PLUGINS_JSON`).
- 모든 명령은 stdout 에 JSON 한 개를 쓴다: 성공 `{"ok": true, ...}`, 실패 `{"ok": false, "error": {"code", "message", "hint"}, ...}`(오류의 `data` 는 최상위에 합친다). 출력 뒤 처리(`_after`)는 출력한 다음에만 한다.
- exit 코드는 horch 와 같다: 0 성공, 1 실패·확인 불가, 2 입력 오류, 3 상태 충돌, 4 대기 시간 초과, 5 권한 없음, 12 의존 프로그램 없음. `--root` 는 하위 명령 앞에 둔다.
- 권한 확인(실수 방지용, 보안 경계가 아님): 상태를 바꾸는 명령(start, start-ready, fix, drop, accept, review, review-finish, plan apply, task new, notify, applied, wait, 새로 `design-review`)은 `roles.require_coordinator`(HTEAM_ROLE·nonce, 아니면 exit 5). 메인 명령(tell, watch, answer, reask, up)은 `outbox.require_main`. `ask-user` 의 새 질문·ack 는 그 태스크의 작업 워커 터미널만.
- 상태 쓰기: 태스크마다 flock(`state/tasks/T-xxx.lock`) 아래에서 이전 상태를 다시 확인하고(`state.edit(expect=…)`, `dispatch.owned`, `tasks._closing`, `review._finish_write`) 임시 파일 + `os.replace` 로 쓴다. **쓸 때마다 이전 상태를 다시 본다**: 잠금 밖에서 본 상태로 결정했으면 잠금 안에서 그 상태·라운드·실행 기록이 그대로인지 확인하고, 아니면 exit 3(`state_changed` 등)으로 아무것도 바꾸지 않는다. 잠금 순서는 늘 프로젝트(`state/lock`) → finish(`state/tasks/T-xxx.finish.lock`) → 태스크. 뒤 잠금을 쥔 채 앞 잠금을 기다리지 않는다. outbox·run·applied·design-review 기록 잠금은 맨 끝(다른 잠금을 기다리지 않는 잎)이다.
- 손상된 기록을 없는 것으로 보지 않는다: 고쳐 다시 쓰는 기록(태스크 상태, `run.json`, `applied.json`, 새 `design-review.json`)은 읽지 못하면 오류로 멈추고 덮어쓰지 않는다(`state._read_state`, `outbox._run`, 새 `util.read_json_strict`).
- 사용자·워커 글은 `--옵션=값` 한 인자로 넘긴다(`--body=…`, `--note=…`, `--subject=…`). `-` 로 시작하는 글이 옵션으로 읽히지 않게 한다. 문서의 예도 이렇게 쓴다.
- JSONL(outbox)은 LF 로만 나눈다. LF 로 끝나지 않은 마지막 조각은 읽지 않고, ID·커서는 완결된 줄 수로 센다(본문의 U+2028 등은 경계가 아니다).
- 경로는 손실 없이 다룬다: git 이 내는 경로는 바이트로 읽어 `os.fsdecode` 로 푼다(text 모드는 `\r` 을 바꾸고 UTF-8 이 아닌 이름에서 실패한다). JSON 으로 쓸 때는 짝 없는 서로게이트를 `\udcXX` 로 이스케이프하고(`util.dumps`, Task 5), 사람이 읽는 글에는 `util.show` 로 넣는다. 커밋은 늘 경로 지정(`git add -- <경로>` + `git commit -m … -- <경로>`, 경로는 `:(literal)`).
- `hc run` 은 늘 `--no-notify` 를 붙인다(코드의 `herdr.run_bg` 는 이미 붙인다. 실환경 확인의 시험용 `hc run` 도 같다). 붙이지 않으면 끝날 때 종료 알림이 띄운 쪽 입력란에 들어간다(설계 15.4).
- 시각은 UTC `%Y-%m-%dT%H:%M:%SZ`. 태스크 ID 는 `T-` + 숫자 3자리 이상. 실행 키: 작업 `T-xxx rN 작업`, 리뷰 `T-xxx rN 리뷰 aK`.
- 문서·메시지·주석은 한국어. 명령·코드 식별자는 원문.
- 저장소는 공개될 수 있다. 커밋 전에 `git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews'` 가 아무것도 찾지 않아야 한다.
- 버전: 설계 15.3 은 세 단계를 마친 뒤 0.1.0 으로 main 에 병합한다고 정한다. 그래서 2단계는 버전을 바꾸지 않는다: herdr-team `0.1.0`(`herdr-team/lib/hteam/paths.py`, `herdr-team/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`), herdr-orch `0.1.1`(herdr-orch 코드는 바꾸지 않는다). `tests/test_cli.py` 의 `test_versions_match` 가 셋을 비교한다.
- 작업 브랜치 `design/herdr-team` 에서 한다. main 에 직접 커밋하지 않는다. main 병합은 3단계 뒤다.
- 테스트: 저장소 루트에서 `bash herdr-team/tests/run.sh`(전체는 4–8분이라 백그라운드로 돌린다)와 `bash herdr-orch/tests/run.sh`. 태스크 중간에는 `-k` 로 고른다(`run.sh` 는 인자를 `unittest discover` 에 넘긴다). 테스트는 실제 hc·Herdr·에이전트를 건드리지 않는다: 실제 `horch` 를 부르고 hc·herdr-app·claude·codex 는 `herdr-orch/tests/fakes/` 의 가짜, 워커·리뷰어의 일은 `herdr-team/tests/fakes/agent-act` 가 대신한다(`tests/helpers.py`).
- **Codex 교차 검증(CLAUDE.md):** 이 계획은 실행 전에 컨트롤러가 `scripts/codex-review.sh doc <이름> <프롬프트 파일>` 로 검토받는다(잘못된 가정, 빠진 실패 경로, 모순, 구현할 수 없는 요구, 범위 과잉, 심각도 P0–P3 와 근거 위치). 각 태스크의 마지막 단계는 커밋이다. **구현자는 커밋에서 멈춘다.** 그 뒤 컨트롤러가 Herdr pane 에서 `scripts/codex-review.sh commit HEAD` 를 돌린다(같은 space 의 "리뷰" 탭에 pane 을 띄우고 터미널 주소를 출력한다). 끝나기를 붙잡고 기다리지 않고 `hc wait <주소> --timeout 3600` 을 백그라운드로 건 뒤 다른 일을 한다. 결과 `.codex-reviews/commit-<sha 7자>.md`(커밋하지 않는다)의 지적은 그대로 따르지 않는다: 항목마다 코드로 사실인지 확인한 뒤 고치거나(고치면 재현 테스트를 먼저 더하고 커밋한 뒤 그 커밋을 다시 리뷰) 고치지 않는 이유를 적는다. P0·P1 이 남지 않을 때까지 최대 3 라운드. 3 라운드 뒤에도 남으면 사용자에게 묻는다. 사용자 보고에는 Codex 가 무엇을 지적했고 무엇을 고쳤는지, 무엇을 왜 고치지 않았는지 적는다.

## File Structure

```
herdr-team/
  lib/hteam/
    approval.py   새로: 승인 상황 view, design-review 묶음·기록·복구, 답 주석 reply_view·reply_hint(Task 3·4)
    cli.py        COMMAND_MODULES 에 "approval"(Task 3), 출력 JSON 은 util.dumps(Task 5)
    paths.py      Project.design_review(Task 3)
    util.py       read_json_strict·bad_side_file(Task 3), dumps·show(Task 5)
    tasks.py      accept 의 awaiting_user next(Task 4), fix 의 from_user(Task 4), 이어 붙인 워커의 next(Task 6)
    compose.py    수정 라운드의 열린 질문(Task 2), 사용자 수정 요청 블록(Task 4), 리뷰 프롬프트 경로 표시(Task 5)
    coord.py      awaiting_user next·답 주석(Task 4), applied 손상·run_error(Task 6)
    gitio.py      무손실 경로·git 항목(모드:ID)·작업 트리 항목(Task 5), index.lock 다시 시도(Task 6)
    review.py     기준점·변조 검사를 git 항목으로, 경로 표시(Task 5), plan_incomplete 를 코디네이터에게(Task 6)
    state.py      save 가 util.dumps(Task 5)
    dispatch.py   adopt 결과에 outcome·summary(Task 6)
    outbox.py     applied_ids 엄격 읽기(Task 6)
    setup.py      scaffold 가 roles/designer.md 를 복사(Task 1)
  hooks/hteam_hook.py   Herdr 터미널 밖 메인(Task 6)
  templates/
    config.toml           [roles.designer], user_approval_roles = ["designer"](Task 1)
    roles/designer.md     새로(Task 1)
    roles/planner.md      체크리스트·확정 질문·리뷰 기준·designer 태스크(Task 2)
    coordinator.md        일괄 승인 흐름(Task 4), next·plan_incomplete(Task 6)
    CLAUDE.section.md     approval 의 수정 요청, 디자인 위치(Task 4)
  skills/init/SKILL.md    designer 직무 안내(Task 1)
  skills/up/SKILL.md      run_error(Task 6)
  tests/
    test_setup.py         템플릿 직무·scaffold(Task 1), 문서 계약(Task 6)
    test_interview.py     새로: planner 문서·수정 라운드 열린 질문(Task 2)
    test_approval.py      새로: design-review(Task 3), 승인 흐름(Task 4)
    test_review.py        변조 검사 항목·무손실(Task 5), plan_incomplete(Task 6)
    test_plan.py          gitio 항목·index.lock(Task 5·6)
    test_start.py         이어 붙인 워커의 next(Task 6)
    test_hooks.py         Herdr 터미널 밖 메인(Task 6)
    test_coord.py         run_error(Task 6)
    test_mainlink.py      applied 손상(Task 6)
docs/superpowers/specs/2026-11-05-herdr-team-design.md   15.4 2단계 결과와 설계 동기화(Task 7)
```

### 새 기록 `state/design-review.json`(Task 3)

```json
{"batches": [{"batch": "dr-0001", "at": "2026-11-06T10:00:00Z", "id": "out-0007",
              "tasks": [{"task": "T-003", "round": 1}, {"task": "T-004", "round": 1}],
              "render": {"header": "디자인 승인", "question": "…", "context": "…", "options": ["…"], "multiSelect": false}}]}
```

`id` 가 `null` 이면 기록 뒤 outbox 를 쓰기 전에(또는 id 를 적기 전에) 멈춘 묶음이다. outbox 항목은 `{"id", "at", "type": "approval", "render", "from": "coordinator", "batch": "dr-0001", "answered": false}`.

### 태스크 상태에 더하는 것

- 라운드 기록 `rounds[i].from_user: true`: awaiting_user 에서 `fix` 로 연 라운드(사용자 수정 요청, Task 4).
- 리뷰 기준점 `baseline.exec_bit`(core.fileMode), `dirty`·`index` 의 값은 `모드:객체 ID`(Task 5). 이 커밋 전에 만든 기준점은 값이 객체 ID 뿐이라 그 시도의 review-finish 는 변조로 본다(배포 전 중간 형식이라 옮기지 않는다. 사용자가 확인한 뒤 `review --retry`).

## 태스크 순서와 의존

1(designer 직무·설정) → 2(기획 인터뷰) → 3(design-review) → 4(승인 흐름 연결) → 5(정리: 변조 검사) → 6(정리: 루프·훅) → 7(실환경 확인·결과 기록·브랜치 리뷰).

2 는 1 의 코드에 기대지 않는다(planner 문서가 designer 태스크를 설명하므로 1 뒤에 둔다). 4 는 3 의 `approval.view`·`approval.load` 를 쓴다. 6 은 3 의 `util.read_json_strict` 를 쓰고 4 가 고친 `coord._annotate_main` 을 다시 고친다. 5 와 6 은 `gitio.py` 의 서로 다른 부분을 고친다(5 는 경로를 내는 함수와 `run` 의 시그니처, 6 은 `run` 의 오류 부분과 `commit_paths`·`unstage`). 각 태스크의 "찾을 내용"은 앞 태스크를 적용한 뒤의 코드다.

요구된 태스크 수: 기능 넷(1–4), 정리 둘(5–6), 실환경 하나(7). 정리는 리뷰어가 따로 판단할 수 있게 변조 검사(5)와 루프·훅(6)으로 나눴다.

---
### Task 1: designer 기본 직무와 승인 직무 설정

설계 4장·11.2(기본만)·15.3 2번: 설정 템플릿에 `[roles.designer]` 를 더하고 `user_approval_roles = ["designer"]` 로 둔다. designer 직무 문서(기본)를 만들고 scaffold 가 복사한다. init 스킬은 화면이 없는 프로젝트면 designer 를 빼자고 제안한다. 상태 기계(awaiting_user 전이, 의존 끝 조건, 승인 사슬 plan check, director·designer 는 claude 만)는 1단계 코드에 이미 있다. 이 태스크는 템플릿·scaffold 만 바꾼다.

**Files:**
- Create: `herdr-team/templates/roles/designer.md`
- Modify: `herdr-team/templates/config.toml`, `herdr-team/lib/hteam/setup.py`(`FILES`), `herdr-team/skills/init/SKILL.md`
- Test: `herdr-team/tests/test_setup.py`(`ScaffoldTest.test_creates_files_and_never_overwrites`, `TemplateContractTest`)

**Interfaces:**
- Consumes: `config.validate(raw)`, `config.build(raw)`, `plan.validate(cfg, tasks) -> (errors, groups)`(기존)
- Produces: 템플릿 직무 `planner·designer·developer·tester`, `user_approval_roles = ["designer"]`, designer owns `["docs/design/**", "assets/**"]`. 직무 문서 `.herdr-team/roles/designer.md` 의 보고서 줄 `- 아티팩트: <claude.ai URL 또는 없음>`(Task 3 의 `approval.link` 가 마지막 claude.ai URL 을 읽는다). 화면 원본 위치 `docs/design/screens/<화면>/index.html`.

- [ ] **Step 1: 실패하는 테스트 작성**

**Edit** `herdr-team/tests/test_setup.py`

```python
        for rel in (".herdr-team/config.toml", ".herdr-team/coordinator.md", ".herdr-team/roles/planner.md",
                    ".herdr-team/roles/developer.md", ".herdr-team/roles/tester.md", ".herdr-team/bin/hteam",
```

```python
        for rel in (".herdr-team/config.toml", ".herdr-team/coordinator.md", ".herdr-team/roles/planner.md",
                    ".herdr-team/roles/designer.md", ".herdr-team/roles/developer.md", ".herdr-team/roles/tester.md",
                    ".herdr-team/bin/hteam",
```

`test_phase1_roles_only` 를 2단계 직무 검사로 바꾼다.

**Edit** `herdr-team/tests/test_setup.py`

```python
    def test_phase1_roles_only(self):
        import tomllib
        raw = tomllib.loads((ROOT / "templates/config.toml").read_text(encoding="utf-8"))
        self.assertEqual(set(raw["roles"]), {"planner", "developer", "tester"})
        self.assertEqual(raw["user_approval_roles"], [])
        self.assertEqual(config.validate(raw), [])
        self.assertEqual(sorted(p.name for p in (ROOT / "templates/roles").iterdir()),
                         ["developer.md", "planner.md", "tester.md"])
```

```python
    def test_template_roles(self):
        import tomllib
        from hteam import plan
        raw = tomllib.loads((ROOT / "templates/config.toml").read_text(encoding="utf-8"))
        self.assertEqual(set(raw["roles"]), {"planner", "designer", "developer", "tester"})
        self.assertEqual(raw["user_approval_roles"], ["designer"])
        self.assertEqual(raw["roles"]["designer"]["owns"], ["docs/design/**", "assets/**"])
        self.assertEqual(config.validate(raw), [])
        self.assertEqual(sorted(p.name for p in (ROOT / "templates/roles").iterdir()),
                         ["designer.md", "developer.md", "planner.md", "tester.md"])
        designer = (ROOT / "templates/roles/designer.md").read_text(encoding="utf-8")
        for needle in ("docs/design/screens/<화면>/index.html", "- 아티팩트: <claude.ai URL 또는 없음>",
                       "사용자 일괄 승인", "코드(`src/`)"):
            self.assertIn(needle, designer)

        def task(key, role, owns, deps=()):
            return {"key": key, "role": role, "title": f"{key} 제목", "owns": list(owns), "depends_on": list(deps),
                    "target": "대상", "change": "바꿀 것", "constraints": "제약", "acceptance": ["확인 1"]}
        # 템플릿 설정으로 화면마다 designer 태스크를 두고 개발이 그것에 의존하는 그래프가 plan check 를 통과한다
        cfg = config.build(raw)
        screens = [task("login-screen", "designer", ["docs/design/screens/login/**", "assets/login/**"]),
                   task("list-screen", "designer", ["docs/design/screens/list/**", "assets/list/**"])]
        app = task("app", "developer", ["src/**"], ["login-screen", "list-screen"])
        self.assertEqual(plan.validate(cfg, screens + [app]), ([], [["login-screen", "list-screen"], ["app"]]))
        chained = [screens[0], task("login-more", "designer", ["docs/design/screens/login/**"], ["login-screen"])]
        self.assertTrue(any("승인 직무 태스크" in e for e in plan.validate(cfg, chained)[0]))
```

- [ ] **Step 2: 실패 확인**

Run: `bash herdr-team/tests/run.sh -k test_template_roles -k test_creates_files_and_never_overwrites`
Expected: FAIL — 템플릿에 designer 직무와 `roles/designer.md` 가 없다(`AssertionError`), scaffold 의 `created` 에 `.herdr-team/roles/designer.md` 가 없다.

- [ ] **Step 3: 구현**

**Edit** `herdr-team/templates/config.toml`

```toml
user_approval_roles = []  # 리뷰 승인 뒤 사용자 일괄 승인을 기다릴 직무(2단계에서 designer)
```

```toml
user_approval_roles = ["designer"]  # 리뷰 승인 뒤 사용자 일괄 승인(hteam design-review)을 기다릴 직무
```

**Edit** `herdr-team/templates/config.toml`

```toml
owns = ["docs/planning/**"]

[roles.developer]
```

```toml
owns = ["docs/planning/**"]

# 화면 디자인. claude 만 된다(설계 4.2). 승인 직무라 리뷰 승인 뒤 사용자 일괄 승인을 기다린다.
[roles.designer]
title = "디자인"
claude_model = "sonnet"
claude_effort = "xhigh"
codex_model = "gpt-6.1-sol"
codex_effort = "medium"
owns = ["docs/design/**", "assets/**"]

[roles.developer]
```

**Create** `herdr-team/templates/roles/designer.md`

```markdown
# designer — 디자인

## 책임
- 기획 산출물의 화면 하나를 디자인한다(태스크 하나에 화면 하나). 개발 워커가 다시 묻지 않고 구현할 수 있을 만큼 구체적으로 만든다.

## 입력
- `docs/planning/`(spec.md 의 사용자 흐름·화면 목록, contracts.md), 선행 태스크 보고서 `docs/tasks/<T>/report.md`
- 있으면 `docs/design/` 의 앞서 만든 화면(같은 앱 안에서 모양을 맞춘다)

## 산출물
- `docs/design/screens/<화면>/index.html`: 화면 원본. 파일 하나로 열리고 외부 리소스(CDN·웹 글꼴·원격 이미지)를 쓰지 않는다. Codex 리뷰어와 개발 워커가 이 파일을 읽는다.
- `docs/design/screens/<화면>/notes.md`: 상태(기본·빈 목록·로딩·오류), 상호작용, 좁은 화면 기준, 쓴 색·글꼴·간격 값.
- Artifact 도구(claude.ai 아티팩트)를 쓸 수 있으면 같은 화면을 아티팩트로 올린다. 쓸 수 없거나 실패하면 올리지 않는다(일괄 승인 질문이 보고서 경로를 대신 보여 준다). 확인 창의 키를 누르거나 로그인을 기다리지 않는다.
- 보고서 `## rN` 절에 다음 세 줄을 그대로 둔다(일괄 승인 질문이 보고서의 마지막 claude.ai URL 을 링크로 쓴다):
  - `- 아티팩트: <claude.ai URL 또는 없음>`
  - `- 화면: <화면 이름> — docs/design/screens/<화면>/index.html`
  - `- 시스템 추가 제안: <없음 또는 목록>`

## 품질 기준
- spec.md 의 그 화면 요구(흐름·필드·문구·오류)를 빠짐없이 담는다. 기획 문서가 정하지 않은 제품 결정은 프리앰블의 ask 명령으로 코디네이터에게 묻는다.
- 상태별 모습(기본·빈·로딩·오류)을 `index.html` 안에 나란히 보여 준다.
- 본문 글자 대비 4.5:1, 큰 글자·UI 요소 3:1 이상.
- 장식용 이모지, 파랑·보라 그라디언트, 카드 왼쪽의 굵은 강조 테두리를 쓰지 않는다.
- 다른 화면과 색·글꼴·간격을 맞춘다. 새 값이 필요하면 notes.md 와 보고서의 "시스템 추가 제안"에 적는다.

## 승인
- 사용자 승인 직무다(`user_approval_roles`). 리뷰(Codex)가 승인하면 사용자 일괄 승인을 기다린다(`awaiting_user`). 코디네이터가 승인 직무 태스크를 묶어 메인을 거쳐 사용자에게 한 번에 묻는다.
- 사용자가 수정을 요청하면 수정 라운드가 온다. 수정 블록의 사용자 요청을 모두 반영하고, 요청마다 어떻게 반영했는지 보고서에 적는다.

## 하지 않는 것
- 코드(`src/`)·테스트 고치기, 다른 화면 폴더 고치기.
- 래스터 이미지 만들기, 디자인 토큰·디자인 시스템 새로 만들기(3단계의 `hteam image` 와 디자인 디렉터가 한다).
```

**Edit** `herdr-team/lib/hteam/setup.py`

```python
    "roles/planner.md": ".herdr-team/roles/planner.md",
    "roles/developer.md": ".herdr-team/roles/developer.md",
```

```python
    "roles/planner.md": ".herdr-team/roles/planner.md",
    "roles/designer.md": ".herdr-team/roles/designer.md",
    "roles/developer.md": ".herdr-team/roles/developer.md",
```

**Edit** `herdr-team/skills/init/SKILL.md`

```markdown
- 추가 직무: 기본 직무(planner·developer·tester)로 부족할 때만. `.herdr-team/roles/<직무>.md`(기본 직무 문서와 같은 절 구성)와 config 항목을 같이 만든다.
```

```markdown
- 직무: 기본 직무는 planner·designer·developer·tester 다. 화면이 없는 프로젝트(CLI·라이브러리 등)면 `[roles.designer]` 와 `user_approval_roles` 의 `"designer"` 를 빼고 `.herdr-team/roles/designer.md` 를 지우자고 제안한다. 추가 직무는 기본 직무로 부족할 때만 둔다. `.herdr-team/roles/<직무>.md`(기본 직무 문서와 같은 절 구성)와 config 항목을 같이 만든다.
```

- [ ] **Step 4: 통과 확인**

Run: `bash herdr-team/tests/run.sh -k test_setup -k test_config`
Expected: OK(실패 없음).

- [ ] **Step 5: 커밋(구현자는 여기서 멈춘다)**

```bash
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews' || true
git add -- herdr-team/templates/roles/designer.md herdr-team/templates/config.toml herdr-team/lib/hteam/setup.py \
  herdr-team/skills/init/SKILL.md herdr-team/tests/test_setup.py
git commit -m "feat(herdr-team): designer 기본 직무와 승인 직무 설정 템플릿

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/templates herdr-team/lib/hteam/setup.py \
  herdr-team/skills/init/SKILL.md herdr-team/tests/test_setup.py
```

Expected: `git grep` 출력 없음, 커밋 성공. 컨트롤러가 `scripts/codex-review.sh commit HEAD` 를 돌리고 Global Constraints 의 Codex 규칙대로 처리한다.

---
### Task 2: 기획 인터뷰 — 체크리스트 12항목과 확정 질문

설계 10장: 인터뷰 규칙은 planner 직무 문서가 담는다. 짧은 질문을 하나씩 `hteam ask-user` 로 하고, 체크리스트 12항목이 모두 "결정" 또는 "범위 밖"이 될 때까지 묻고(질문 수 제한 없음, 뻔한 항목은 "자동 결정"), 마지막 질문은 확정(`context` 에 계획 핵심·자동 결정·태스크 그래프 표, 선택지 "확정 (추천)" / "수정할 부분 있음")이다. 수정 라운드의 기획자는 먼저 `--pending` 과 열린 질문의 `--wait` 를 확인한다. 리뷰어는 `hteam ask-user --history` 로 실제 질문과 답을 확인한다(읽기 전용 명령이라 리뷰어 규칙 안이다). 코드는 수정 블록 문구 한 줄만 바꾼다(열린 질문을 새로 묻지 않고 기다린다). 그 밖의 인터뷰 장치(`ask-user`, 한 태스크 한 질문, 프로젝트마다 기획 하나 `planner_busy`, planner 사전 검사 `plan check`)는 1단계에 있다.

**Files:**
- Modify: `herdr-team/templates/roles/planner.md`, `herdr-team/lib/hteam/compose.py`(수정 블록)
- Create: `herdr-team/tests/test_interview.py`

**Interfaces:**
- Consumes: `outbox.validate_render(obj, default_header) -> dict`(기존), `compose.work_spec(p, cfg, spec, rd, owns) -> str`(기존), `hteam ask-user --task T --json - | --wait ID | --pending | --history`(기존)
- Produces: planner 문서의 절 `## 인터뷰 체크리스트`(12항목, 상태 `미정`·`결정`·`자동 결정`·`범위 밖`), `## 확정 질문`(선택지 `확정 (추천)`·`수정할 부분 있음`), `## 리뷰 기준(리뷰어가 본다)`. 수정 라운드 사양의 문장 `` `.herdr-team/bin/hteam ask-user --task T-xxx --wait <id>` 로 그 답을 기다린다 ``.

- [ ] **Step 1: 실패하는 테스트 작성**

**Create** `herdr-team/tests/test_interview.py`

```python
"""기획 인터뷰(설계 10장): planner 직무 문서의 체크리스트·확정 질문·리뷰 기준, 수정 라운드의 열린 질문."""
import json
import re
import unittest

from tests.helpers import ROOT, TeamCase
from hteam import outbox, state
from hteam.paths import Project

PLANNER = ROOT / "templates" / "roles" / "planner.md"
# 설계 10장의 체크리스트 순서 그대로
CHECKLIST = ["목적과 성공 기준", "사용자와 상황", "범위", "사용자 흐름", "화면 목록", "데이터와 상태", "오류",
             "비기능 요구", "기술 스택과 실행 환경", "인터페이스 계약", "브랜드 자산과 아는 레퍼런스", "범위 밖"]
HEREDOC = re.compile(r"ask-user --task T-xxx --json - <<'EOF'\n(.*?)\nEOF", re.S)


def section(text: str, title: str) -> str:
    start = text.index(f"## {title}\n")
    end = text.find("\n## ", start + 1)
    return text[start:] if end == -1 else text[start:end]


class PlannerDocTest(unittest.TestCase):
    def setUp(self):
        self.text = PLANNER.read_text(encoding="utf-8")

    def test_checklist_is_the_design_list(self):
        items = re.findall(r"(?m)^(\d+)\. (.+)$", section(self.text, "인터뷰 체크리스트"))
        self.assertEqual([int(n) for n, _ in items], list(range(1, 13)))
        self.assertEqual([t for _, t in items], CHECKLIST)
        for word in ("`미정`", "`결정`", "`자동 결정`", "`범위 밖`"):
            self.assertIn(word, section(self.text, "인터뷰 체크리스트"))

    def test_examples_are_valid_questions(self):
        found = [json.loads(x) for x in HEREDOC.findall(self.text)]
        self.assertEqual(len(found), 2)  # 보통 질문 하나, 확정 질문 하나
        for obj in found:
            outbox.validate_render(obj, "기획")  # ask-user 가 받는 형식 그대로다(어기면 exit 2)
        confirm = found[-1]
        self.assertEqual([o["label"] for o in confirm["options"]], ["확정 (추천)", "수정할 부분 있음"])
        for part in ("계획 핵심", "자동 결정", "태스크 그래프"):
            self.assertIn(part, confirm["context"])

    def test_confirmation_resume_and_review_rules(self):
        confirm = section(self.text, "확정 질문")
        for needle in ("마지막 질문은 늘 확정 질문이다", "`plan check` 가 통과한 뒤", "확정 질문을 다시 한다"):
            self.assertIn(needle, confirm)
        review = section(self.text, "리뷰 기준(리뷰어가 본다)")
        for needle in ("ask-user --task <이 태스크> --history", "답이 `확정 (추천)` 이다", "12항목"):
            self.assertIn(needle, review)
        self.assertIn("--wait <id>", section(self.text, "사용자에게 묻기"))
        self.assertIn("designer 태스크", section(self.text, "tasks.toml 형식"))


class FixRoundQuestionTest(TeamCase):
    """수정 라운드의 기획자는 앞 라운드의 열린 질문을 새로 묻지 않고 기다린다(설계 10장)."""

    QUESTION = {"question": "저장 위치는?\n예: 파일이면 서버가 필요 없다",
                "options": [{"label": "파일 (추천)", "description": "추천 사유: 서버가 없다"},
                            {"label": "DB", "description": "서버가 필요하다"}]}

    def setUp(self):
        super().setUp()
        self.init_project()
        self.setup_run()
        self.p = Project(self.proj)
        self.env["HTEAM_ASK_TIMEOUT"] = "0.3"

    def ask(self):
        term = self.dispatch_row(self.work_dispatch("T-001"))["terminal"]
        return self.hteam("ask-user", "--task", "T-001", "--json", "-", as_=None, terminal=term,
                          stdin=json.dumps(self.QUESTION))

    def test_open_question_carries_into_fix_round(self):
        self.write_spec("T-001", "planner")
        state.create(self.p, "T-001", "planner")
        self.assertEqual(self.hteam("start", "T-001")[0], 0)
        code, out = self.ask()
        self.assertEqual((code, out.get("id")), (4, "out-0001"), out)  # 답을 받기 전에 r1 이 끝났다
        self.act_work("T-001", {"docs/planning/spec.md": "초안\n"}, outcome="failed")
        code, out = self.hteam("fix", "T-001", "--note=인터뷰를 이어 한다")
        self.assertEqual((code, out.get("round")), (0, 2), out)
        work = (self.state_dir / "tasks/T-001/r2-work.md").read_text(encoding="utf-8")
        self.assertIn("`.herdr-team/bin/hteam ask-user --task T-001 --wait <id>` 로 그 답을 기다린다", work)
        code, out = self.hteam("ask-user", "--task", "T-001", "--history", as_=None)
        self.assertEqual([(i["id"], i["answer"]) for i in out["history"]], [("out-0001", None)])
        self.assertEqual([q["id"] for q in outbox.open_questions(self.p)], ["out-0001"])  # r2 도 working 이다
        code, out = self.ask()  # r2 워커가 같은 질문을 새로 하면 열린 질문 때문에 거부된다
        self.assertEqual((code, out["error"]["code"], out.get("id")), (3, "question_open", "out-0001"), out)
        self.assertEqual(self.hteam("answer", "out-0001", "파일 (추천)", as_="main")[0], 0)
        code, out = self.hteam("ask-user", "--task", "T-001", "--wait", "out-0001", as_=None)
        self.assertEqual((code, out.get("answer")), (0, "파일 (추천)"), out)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인**

Run: `bash herdr-team/tests/run.sh -k test_interview`
Expected: FAIL — planner 문서에 `## 인터뷰 체크리스트`·`## 확정 질문`·`## 리뷰 기준(리뷰어가 본다)` 이 없고(`ValueError: substring not found`, 예시 질문 하나), r2 사양에 `--wait <id>` 문장이 없다.

- [ ] **Step 3: 구현**

산출물 설명을 고치고 체크리스트 절을 더한다.

**Edit** `herdr-team/templates/roles/planner.md`

```markdown
- `docs/planning/spec.md`: 목적, 범위, 사용자 흐름, 화면·기능 목록, 데이터, 오류 처리, 비기능 요구, 범위 밖.
- `docs/planning/contracts.md`: 모듈 경계, API·데이터 형태, 파일 위치 약속.
- `docs/planning/tasks.toml`: 태스크 그래프(아래 형식).
- `docs/planning/interview.md`: 질문 번호, 질문, 답.

## 사용자에게 묻기
```

```markdown
- `docs/planning/spec.md`: 목적과 성공 기준, 사용자와 상황, 범위, 사용자 흐름, 화면·기능 목록, 데이터와 상태, 오류 처리, 비기능 요구, 기술 스택과 실행 환경, 범위 밖, 자동 결정.
- `docs/planning/contracts.md`: 모듈 경계, API·데이터 형태, 파일 위치 약속.
- `docs/planning/tasks.toml`: 태스크 그래프(아래 형식).
- `docs/planning/interview.md`: 맨 위에 체크리스트 표(아래), 그 아래 질문 기록(번호, 질문, 답, 반영한 곳).

## 인터뷰 체크리스트
다음 12항목이 모두 결정되거나 범위 밖이 될 때까지 묻는다. 질문 수에는 제한이 없다.

1. 목적과 성공 기준
2. 사용자와 상황
3. 범위
4. 사용자 흐름
5. 화면 목록
6. 데이터와 상태
7. 오류
8. 비기능 요구
9. 기술 스택과 실행 환경
10. 인터페이스 계약
11. 브랜드 자산과 아는 레퍼런스
12. 범위 밖

- 항목마다 상태는 `미정`·`결정`·`자동 결정`·`범위 밖` 가운데 하나다. 기술적으로 뻔한 항목은 묻지 않고 `자동 결정` 으로 적는다(근거와 함께, spec.md 의 "자동 결정" 에도). 화면이 없는 프로젝트면 5번은 `범위 밖`(근거: 화면 없음)이다.
- 기존 `docs/planning/` 이 이미 결정한 항목은 다시 묻지 않는다(근거: 그 문서). 증분 기획이면 추가 요청에 걸린 항목만 다시 본다.
- `interview.md` 맨 위의 표를 질문할 때마다 고친다:

| # | 항목 | 상태 | 근거 |
|---|---|---|---|
| 1 | 목적과 성공 기준 | 결정 | Q2 |
| 9 | 기술 스택과 실행 환경 | 자동 결정 | project.md 가 파이썬 표준 라이브러리로 정했다 |
| 11 | 브랜드 자산과 아는 레퍼런스 | 범위 밖 | Q5: 첫 버전은 브랜드 없음 |

## 사용자에게 묻기
```

수정 라운드 안내를 열린 질문 기다리기로 바꾸고, 확정 질문과 리뷰 기준 절을 더한다.

**Edit** `herdr-team/templates/roles/planner.md`

````markdown
- 답을 기다리는 질문이 있으면 새 질문은 exit 3 이다. 수정 라운드에서는 먼저 `--pending` 과 `--history` 로 이전 질문과 답을 확인한다.

## tasks.toml 형식
````

````markdown
- 답을 기다리는 질문이 있으면 새 질문은 exit 3 이다.
- 수정 라운드에서는 먼저 `hteam ask-user --task T-xxx --pending`(답이 왔지만 반영하지 않은 질문)과 `--history` 를 본다. `--history` 에 답이 없는(`"answer": null`) 질문이 있으면 새로 묻지 말고 `hteam ask-user --task T-xxx --wait <id>` 로 그 답을 기다린다(Bash `timeout: 600000`).

## 확정 질문
마지막 질문은 늘 확정 질문이다. 체크리스트에 `미정` 이 없고, spec.md·contracts.md·tasks.toml 을 다 쓰고, `plan check` 가 통과한 뒤에 묻는다.

- `context` 에 셋을 넣는다: 계획 핵심(목적·범위·주요 흐름 몇 줄), 자동 결정 목록, 태스크 그래프 표(key·직무·제목·의존). 4000자를 넘으면 줄인다(먼저 표의 제목 열을 뺀다).
- 선택지는 정확히 둘이다: `확정 (추천)` 과 `수정할 부분 있음`.

```bash
.herdr-team/bin/hteam ask-user --task T-xxx --json - <<'EOF'
{"header": "기획 확정",
 "question": "이 계획으로 확정할까요?\n예: 확정하면 태스크 그래프대로 디자인·개발·테스트가 시작된다",
 "context": "## 계획 핵심\n- 할 일 목록 웹 앱. 추가·완료·삭제, 브라우저 저장소에 저장\n\n## 자동 결정\n- 빌드 도구 없음(정적 HTML·JS)\n\n## 태스크 그래프\n| key | 직무 | 제목 | 의존 |\n|---|---|---|---|\n| list-screen | designer | 목록 화면 디자인 | - |\n| app | developer | 앱 구현 | list-screen |\n| e2e | tester | 동작 시험 | app |",
 "options": [{"label": "확정 (추천)", "description": "추천 사유: 체크리스트 12항목이 모두 결정되거나 범위 밖이다"},
             {"label": "수정할 부분 있음", "description": "고칠 곳을 알려 주면 반영한 뒤 확정을 다시 묻는다"}],
 "multiSelect": false}
EOF
```

- 답이 `확정 (추천)` 이 아니면(`수정할 부분 있음` 이나 직접 쓴 글) 무엇을 고칠지 묻고(답에 이미 있으면 묻지 않는다), 문서를 고치고, `plan check` 를 다시 통과시킨 뒤 확정 질문을 다시 한다.
- 확정 답을 받은 뒤에는 다른 질문을 하지 않는다. 그 뒤에 문서를 바꿔야 하면 바꾼 뒤 확정 질문을 다시 한다.
- 확정 답을 `interview.md` 에 적고 `--ack` 한 뒤 보고서를 커밋하고 done 한다.

## 리뷰 기준(리뷰어가 본다)
- `.herdr-team/bin/hteam ask-user --task <이 태스크> --history` 로 실제 질문과 답을 본다(읽기만 한다). `interview.md` 의 질문 기록이 그것과 맞는다.
- 마지막 질문이 확정 질문이고 답이 `확정 (추천)` 이다. 그 뒤에 다른 질문이 없다.
- 체크리스트 12항목이 모두 `결정`·`자동 결정`·`범위 밖` 이고 근거가 있다. spec.md 가 그 결정을 담는다.
- `tasks.toml` 이 `plan check` 를 통과하고 확정 질문의 태스크 그래프 표와 같다.

## tasks.toml 형식
````

designer 태스크를 그래프에 넣는 규칙을 더한다.

**Edit** `herdr-team/templates/roles/planner.md`

```markdown
- 텍스트 필드 안에 `## ` 로 시작하는 줄을 쓰지 않는다.
```

```markdown
- 텍스트 필드 안에 `## ` 로 시작하는 줄을 쓰지 않는다.
- 화면이 있으면 화면마다 designer 태스크를 하나 둔다: key `<화면>-screen`, owns `["docs/design/screens/<화면>/**", "assets/<화면>/**"]`. 그 화면을 구현하는 developer 태스크는 그 designer 태스크에 의존한다(사용자 일괄 승인 뒤에 시작된다).
- designer 태스크끼리 의존 관계면 owns 가 겹치면 안 된다(`plan check` 가 거부한다: 선행이 승인을 기다리며 잠금을 쥔 채 후행을 기다려 일괄 승인이 멈춘다).
```

수정 블록이 열린 질문을 기다리라고 적게 한다.

**Edit** `herdr-team/lib/hteam/compose.py`

```python
        if spec.role in ASK_ROLES:
            parts.append(f"먼저 `{SHIM} ask-user --task {tid} --pending` 과 `--history` 로 이전 질문과 답을 확인한다.")
```

```python
        if spec.role in ASK_ROLES:
            parts.append(f"먼저 `{SHIM} ask-user --task {tid} --pending` 과 `--history` 로 이전 질문과 답을 확인한다. "
                         f"답이 없는 질문이 있으면 새로 묻지 않고 `{SHIM} ask-user --task {tid} --wait <id>` 로 그 답을 "
                         "기다린다(Bash `timeout: 600000`).")
```

- [ ] **Step 4: 통과 확인**

Run: `bash herdr-team/tests/run.sh -k test_interview -k test_start -k test_mainlink`
Expected: OK(실패 없음). `test_start` 는 수정 블록 문구를 검사하는 기존 테스트를 포함한다.

- [ ] **Step 5: 커밋(구현자는 여기서 멈춘다)**

```bash
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews' || true
git add -- herdr-team/templates/roles/planner.md herdr-team/lib/hteam/compose.py herdr-team/tests/test_interview.py
git commit -m "feat(herdr-team): 기획 인터뷰 체크리스트·확정 질문·리뷰 기준, 수정 라운드의 열린 질문 기다리기

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/templates/roles/planner.md \
  herdr-team/lib/hteam/compose.py herdr-team/tests/test_interview.py
```

Expected: `git grep` 출력 없음, 커밋 성공. 컨트롤러가 `scripts/codex-review.sh commit HEAD` 를 돌리고 Global Constraints 의 Codex 규칙대로 처리한다.

---
### Task 3: `hteam design-review` — 승인 직무 일괄 승인 묶음

설계 11.4: `awaiting_user` 인 승인 직무 태스크가 하나 이상 있고, 진행 중(`working`·`reviewing`·`approved`·`changes`·`launch_failed`)이거나 지금 바로 시작할 수 있는(사양 통과·의존 충족·잠금 비어 있음) 승인 직무 태스크가 없을 때, 그 순간 `awaiting_user` 인 승인 태스크를 한 묶음으로 outbox 에 `approval` 항목 하나로 쓴다. 승인 → 비승인 → 승인 사슬의 뒤 태스크는 비승인 태스크가 `done` 이어야 시작할 수 있으므로 앞 묶음을 막지 않고 다음 묶음이 된다. `context` 에는 태스크마다 한 줄과 링크(보고서의 마지막 claude.ai URL, design_system_url 은 뺀다)를 넣고 선택지는 "모두 승인 (추천)" / "수정 요청" 이다. 같은 태스크·라운드를 이미 물었으면 exit 3. 기록은 `state/design-review.json`.

정한 것(설계가 정하지 않은 부분): 한 (태스크, 라운드)는 한 번만 묻는다. 이미 물은 태스크가 답을 기다리는 동안 새 태스크가 awaiting_user 가 되면 새 묶음에는 새 태스크만 넣는다(같은 태스크를 두 질문에 넣지 않는다). 수정 라운드는 라운드가 달라 다시 묻는다. 링크가 없으면 보고서 경로를 쓴다. 상태 파일 하나라도 읽지 못하면 묶음을 잘못 나눌 수 있어 묻지 않는다(exit 1 `bad_state_file`). 쓰는 순서는 기록(id 없음) → outbox(묶음 id `batch` 를 붙인다) → 기록의 id 이고 모두 프로젝트 잠금 안이다. 그 사이 죽으면 다음 호출이 새 묶음보다 먼저 outbox 에서 같은 `batch` 를 찾아 id 를 채우거나, 없으면 저장한 render 로 마저 쓴다.

**Files:**
- Create: `herdr-team/lib/hteam/approval.py`, `herdr-team/tests/test_approval.py`
- Modify: `herdr-team/lib/hteam/util.py`(`read_json_strict`, `bad_side_file`), `herdr-team/lib/hteam/paths.py`(`Project.design_review`), `herdr-team/lib/hteam/cli.py`(`COMMAND_MODULES`)

**Interfaces:**
- Consumes: `config.load(p)`, `cfg.is_approval(role)`, `cfg.role_title(role)`, `specs.check(p, cfg, tid)`, `specs.load(p, tid).title`, `tasks.deps_met(p, cfg, spec)`, `tasks.checked_owns(cfg, spec)`, `tasks.lock_conflicts(p, tid, owns)`, `tasks._unreadable(p, ids) -> HteamError`, `state.project_lock(p)`, `state.all_states(p)`, `state.unreadable_ids(p)`, `outbox.append(p, fields) -> entry`, `outbox.read_outbox(p)`, `outbox.validate_render(obj, header)`, `roles.require_coordinator(p)`, `util.die_at(point)`(모두 기존)
- Produces:
  - `util.read_json_strict(path, default)`: 없으면 `default`, 읽지 못하거나 JSON 이 아니면 `HteamError("bad_side_file", …, 1)`. `util.bad_side_file(path, why) -> HteamError`.
  - `Project.design_review` = `state/design-review.json`.
  - `approval.load(p) -> {"batches": [...]}`(모양이 틀리면 `bad_side_file`), `approval.asked(data) -> {(task, round): out-id | None}`, `approval.view(p, cfg, states=None, data=None) -> {"waiting": [state], "blockers": [{"task", "status", "why"}], "fresh": [state], "asked": {...}}`, `approval.link(p, tid) -> str`, `approval.render(p, cfg, states) -> render`, `approval.design_review(p) -> {"id", "batch", "tasks": [{"task", "round"}], "resumed", "hint"}`. 상수 `approval.APPROVE = "모두 승인 (추천)"`, `approval.REVISE = "수정 요청"`, `approval.HEADER = "디자인 승인"`.
  - 명령 `hteam design-review`(코디네이터만). 오류: exit 2 `no_approval_roles`, exit 3 `nothing_to_approve`·`already_asked`(data `asked`: out-id 목록)·`approval_not_ready`(data `blockers`), exit 1 `bad_side_file`·`bad_state_file`.
  - 테스트 도우미 `tests.test_approval.ApprovalCase`(설정 `APPROVAL`, `task(tid, status, role=, rnd=, depends=, title=)`, `move(tid, status, rnd=)`, `review(**kw)`, `outbox_items()`). Task 4 가 쓴다.
  - die_at 지점 `design_review_recorded`(기록 뒤), `design_review_appended`(outbox 항목 뒤).

- [ ] **Step 1: 실패하는 테스트 작성**

**Create** `herdr-team/tests/test_approval.py`

```python
"""사용자 일괄 승인(설계 11.4): design-review 의 묶음·조건·기록·링크·복구."""
import json
import unittest

from tests.helpers import BASE_CONFIG, TeamCase
from hteam import approval, config, outbox, state
from hteam.paths import Project

APPROVAL = BASE_CONFIG.replace("user_approval_roles = []", 'user_approval_roles = ["designer"]') + """
[roles.designer]
title = "디자인"
owns = ["docs/design/**", "assets/**"]
"""


class ApprovalCase(TeamCase):
    config = APPROVAL

    def setUp(self):
        super().setUp()
        self.init_project(config=self.config, roles=("planner", "designer", "developer", "tester"))
        self.setup_run()
        self.p = Project(self.proj)

    def task(self, tid, status, role="designer", rnd=1, depends=None, title="화면 디자인"):
        """상태만 만든다(워커는 띄우지 않는다). designer 는 화면마다, developer 는 태스크마다 owns 를 나눈다."""
        owns = f"docs/design/screens/{tid.lower()}/**" if role == "designer" else f"src/{tid.lower()}/**"
        self.write_spec(tid, role, title=title, owns=owns, depends=depends, commit=False)
        state.create(self.p, tid, role)
        if status != "pending":
            with state.edit(self.p, tid) as st:
                st.update(round=rnd, owns=[owns])
                state.move(st, status, "test")

    def move(self, tid, status, rnd=None):
        with state.edit(self.p, tid) as st:
            if rnd is not None:
                st["round"] = rnd
            state.move(st, status, "test")

    def review(self, **kw):
        return self.hteam("design-review", **kw)

    def outbox_items(self):
        return outbox.read_outbox(self.p)


class DesignReviewTest(ApprovalCase):
    def test_batches_every_waiting_task(self):
        self.task("T-001", "awaiting_user", title="로그인 화면")
        self.task("T-002", "awaiting_user", title="목록 화면")
        self.task("T-003", "working", role="developer")  # 비승인 직무는 묶음을 막지 않는다
        self.commit("docs/tasks/T-001/report.md", "## r1\n- 아티팩트: https://claude.ai/artifact/abc-1\n", "[T-001] r1")
        code, out = self.review()
        self.assertEqual(code, 0, out)
        self.assertEqual((out["id"], out["batch"], out["resumed"]), ("out-0001", "dr-0001", False))
        self.assertEqual(out["tasks"], [{"task": "T-001", "round": 1}, {"task": "T-002", "round": 1}])
        [entry] = self.outbox_items()
        self.assertEqual((entry["type"], entry["from"], entry["batch"]), ("approval", "coordinator", "dr-0001"))
        render = entry["render"]
        self.assertEqual([o["label"] for o in render["options"]], ["모두 승인 (추천)", "수정 요청"])
        self.assertIn("- T-001 r1 [디자인] 로그인 화면: https://claude.ai/artifact/abc-1", render["context"])
        self.assertIn("- T-002 r1 [디자인] 목록 화면: docs/tasks/T-002/report.md", render["context"])  # 링크가 없다
        outbox.validate_render(render, "디자인 승인")
        rec = json.loads((self.state_dir / "design-review.json").read_text(encoding="utf-8"))
        self.assertEqual([(b["batch"], b["id"]) for b in rec["batches"]], [("dr-0001", "out-0001")])
        self.assertIn("out-0001", [q["id"] for q in outbox.open_questions(self.p)])

    def test_waits_for_approval_tasks_in_progress(self):
        self.task("T-001", "awaiting_user")
        self.task("T-002", "working")
        for status in ("working", "reviewing", "approved", "changes", "launch_failed"):
            with self.subTest(status):
                self.move("T-002", status)
                code, out = self.review()
                self.assertEqual((code, out["error"]["code"]), (3, "approval_not_ready"), out)
                self.assertEqual([b["task"] for b in out["blockers"]], ["T-002"])
        self.assertEqual(self.outbox_items(), [])

    def test_startable_pending_blocks_but_waiting_on_deps_does_not(self):
        self.task("T-001", "awaiting_user")
        self.task("T-002", "pending", role="developer")
        self.task("T-003", "pending", depends="T-002")  # 승인 → 비승인 → 승인: 다음 묶음이 된다
        code, out = self.review()
        self.assertEqual((code, out.get("tasks")), (0, [{"task": "T-001", "round": 1}]), out)
        self.task("T-004", "awaiting_user")
        self.task("T-005", "pending")  # 의존 없음, 잠금 비어 있음: 지금 시작할 수 있다
        code, out = self.review()
        self.assertEqual((code, out["error"]["code"]), (3, "approval_not_ready"), out)
        self.assertEqual(out["blockers"], [{"task": "T-005", "status": "pending", "why": "지금 시작할 수 있다"}])

    def test_locked_pending_does_not_block(self):
        self.task("T-001", "awaiting_user")
        self.write_spec("T-002", "designer", owns="docs/design/screens/t-001/**", commit=False)  # T-001 의 잠금과 겹친다
        state.create(self.p, "T-002", "designer")
        code, out = self.review()
        self.assertEqual((code, out.get("tasks")), (0, [{"task": "T-001", "round": 1}]), out)

    def test_task_round_is_asked_once(self):
        self.task("T-001", "awaiting_user")
        self.assertEqual(self.review()[0], 0)
        code, out = self.review()
        self.assertEqual((code, out["error"]["code"], out.get("asked")), (3, "already_asked", ["out-0001"]), out)
        self.task("T-002", "awaiting_user")  # T-001 의 답을 기다리는 동안 새로 기다리는 태스크만 묻는다
        code, out = self.review()
        self.assertEqual((code, out.get("id"), out.get("tasks")), (0, "out-0002", [{"task": "T-002", "round": 1}]), out)
        self.move("T-001", "awaiting_user", rnd=2)  # 사용자 수정 요청 뒤 r2 가 다시 승인됐다
        code, out = self.review()
        self.assertEqual((code, out.get("id"), out.get("tasks")), (0, "out-0003", [{"task": "T-001", "round": 2}]), out)

    def test_nothing_to_approve_and_permissions(self):
        code, out = self.review()
        self.assertEqual((code, out["error"]["code"]), (3, "nothing_to_approve"), out)
        code, out = self.review(as_="main")
        self.assertEqual((code, out["error"]["code"]), (5, "not_coordinator"), out)
        (self.team / "config.toml").write_text(BASE_CONFIG, encoding="utf-8")
        code, out = self.review()
        self.assertEqual((code, out["error"]["code"]), (2, "no_approval_roles"), out)

    def test_crash_between_record_and_outbox_asks_once(self):
        self.task("T-001", "awaiting_user")
        code, _ = self.review(env={"HTEAM_TEST_DIE_AT": "design_review_recorded"})
        self.assertEqual(code, 137)
        self.assertEqual(self.outbox_items(), [])
        code, out = self.review()
        self.assertEqual((code, out.get("id"), out.get("resumed")), (0, "out-0001", True), out)
        self.task("T-002", "awaiting_user")
        code, _ = self.review(env={"HTEAM_TEST_DIE_AT": "design_review_appended"})
        self.assertEqual(code, 137)
        code, out = self.review()
        self.assertEqual((code, out.get("id"), out.get("batch"), out.get("resumed")), (0, "out-0002", "dr-0002", True),
                         out)
        self.assertEqual([e["id"] for e in self.outbox_items()], ["out-0001", "out-0002"])  # 두 번 묻지 않았다
        rec = json.loads((self.state_dir / "design-review.json").read_text(encoding="utf-8"))
        self.assertEqual([b["id"] for b in rec["batches"]], ["out-0001", "out-0002"])

    def test_corrupt_record_is_kept(self):
        self.task("T-001", "awaiting_user")
        path = self.state_dir / "design-review.json"
        for text in ("{broken", '{"batches": [{"batch": 1}]}'):
            with self.subTest(text):
                path.write_text(text, encoding="utf-8")
                code, out = self.review()
                self.assertEqual((code, out["error"]["code"]), (1, "bad_side_file"), out)
                self.assertEqual(path.read_text(encoding="utf-8"), text)
        self.assertEqual(self.outbox_items(), [])

    def test_unreadable_state_refuses(self):
        self.task("T-001", "awaiting_user")
        (self.state_dir / "tasks" / "T-002.json").write_text("{", encoding="utf-8")
        code, out = self.review()
        self.assertEqual((code, out["error"]["code"]), (1, "bad_state_file"), out)
        self.assertEqual(self.outbox_items(), [])


class LinkTest(ApprovalCase):
    def test_last_claude_url_without_design_system(self):
        report = ("## r1\n- 아티팩트: https://claude.ai/artifact/old\n## r2\n- 아티팩트: https://claude.ai/artifact/new).\n"
                  "- design_system_url: https://claude.ai/artifact/sys\n- 시스템 URL: https://claude.ai/artifact/sys2\n")
        self.commit("docs/tasks/T-001/report.md", report, "[T-001] r2")
        self.commit("docs/design/direction.md", "design_system_url: https://claude.ai/artifact/sys2\n", "dir")
        self.assertEqual(approval.link(self.p, "T-001"), "https://claude.ai/artifact/new")
        self.assertEqual(approval.link(self.p, "T-009"), "docs/tasks/T-009/report.md")

    def test_context_stays_within_limit(self):
        ids = [f"T-{i:03d}" for i in range(1, 81)]
        for tid in ids:
            self.task(tid, "awaiting_user", title="아주 긴 화면 이름 " * 8)
        render = approval.render(self.p, config.load(self.p), [state.load(self.p, t) for t in ids])
        self.assertLessEqual(len(render["context"]), 4000)
        self.assertIn("그 밖", render["context"])
        self.assertIn("T-080", render["context"])  # 줄이 넘친 태스크도 ID 는 남는다


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인**

Run: `bash herdr-team/tests/run.sh -k test_approval`
Expected: FAIL — `ImportError: cannot import name 'approval'`.

- [ ] **Step 3: 구현**

**Edit** `herdr-team/lib/hteam/util.py`

```python
from pathlib import Path
from typing import Iterator
```

```python
from pathlib import Path
from typing import Iterator

from .errors import FAIL, HteamError
```

**Edit** `herdr-team/lib/hteam/util.py`

```python
def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
```

```python
def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def bad_side_file(path: Path, why: str) -> HteamError:
    return HteamError("bad_side_file", f"{path.name} 을 읽지 못했다: {why}", FAIL,
                      f"`.herdr-team/state/{path.name}` 을 직접 고치거나 치운 뒤 다시 한다(덮어쓰지 않았다)")


def read_json_strict(path: Path, default):
    """없으면 default. 있는데 읽지 못하거나 JSON 이 아니면 bad_side_file(exit 1).

    read_json 과 달리 손상을 없는 것으로 보지 않는다. 읽은 값을 고쳐 다시 쓰는 기록이 손상 때문에 빈 기록으로 덮어써져
    지워지지 않게 한다. 모양(dict 인지 등)은 부르는 쪽이 보고 틀리면 bad_side_file 을 낸다."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as exc:  # 디렉터리·권한·UTF-8 아님
        raise bad_side_file(path, str(exc)) from None
    try:
        return json.loads(text)
    except ValueError as exc:
        raise bad_side_file(path, f"JSON 이 아니다: {exc}") from None
```

**Edit** `herdr-team/lib/hteam/paths.py`

```python
        self.context_denied = self.state / "context-denied.json"
```

```python
        self.context_denied = self.state / "context-denied.json"
        self.design_review = self.state / "design-review.json"
```

**Edit** `herdr-team/lib/hteam/cli.py`

```python
    "ask",
    "coord",
```

```python
    "ask",
    "approval",
    "coord",
```

**Create** `herdr-team/lib/hteam/approval.py`

```python
"""사용자 일괄 승인(설계 11.4): `hteam design-review`.

승인 직무(user_approval_roles) 태스크는 리뷰 승인 뒤 accept 로 awaiting_user 가 된다. 진행 중(working·reviewing·
approved·changes·launch_failed)이거나 지금 바로 시작할 수 있는(사양 통과·의존 충족·잠금 비어 있음) 승인 직무 태스크가
없을 때, 그 순간 awaiting_user 인 승인 태스크 가운데 아직 묻지 않은 (태스크, 라운드) 전부를 outbox 의 approval 항목
하나로 묻는다. 승인 → 비승인 → 승인 사슬의 뒤 태스크는 비승인 태스크가 done 이어야 시작할 수 있으므로 앞 묶음을 막지
않고 다음 묶음이 된다.

기록 `state/design-review.json` = {"batches": [{"batch": "dr-0001", "at", "id": "out-NNNN" | null, "render",
"tasks": [{"task", "round"}]}]}. 한 (태스크, 라운드)는 한 번만 묻는다(수정 라운드는 라운드가 달라 다시 묻는다).
쓰는 순서: 기록(id 없음) → outbox 항목(batch 를 붙인다) → 기록의 id. 모두 프로젝트 잠금 안에서 한다. 그 사이 죽으면
다음 호출이 새 묶음보다 먼저 outbox 에서 같은 batch 를 찾아 id 를 채우거나, 없으면 저장한 render 로 마저 쓴다(같은
묶음을 두 번 묻지 않는다). 기록을 읽지 못하면 덮어쓰지 않고 exit 1 이다.
"""
from __future__ import annotations

import re

from . import config, outbox, roles, specs, state, tasks
from .errors import CONFLICT, USAGE, HteamError
from .paths import find_project, report_rel
from .util import bad_side_file, die_at, now, read_json_strict, write_json

PROGRESS = frozenset({"working", "reviewing", "approved", "changes", "launch_failed"})
# 아티팩트 링크. 괄호·따옴표·꺾쇠·공백·제어 문자는 URL 밖이다(context 에 그대로 들어가므로 render 검사를 지나야 한다)
URL_RE = re.compile(r"https://claude\.ai/[A-Za-z0-9._~:/?#@!$&*+,;=%-]+")
CONTEXT_MAX = 4000
TITLE_MAX = 60
HEADER = "디자인 승인"
APPROVE = "모두 승인 (추천)"
REVISE = "수정 요청"


def _valid(b) -> bool:
    return (isinstance(b, dict) and isinstance(b.get("batch"), str) and isinstance(b.get("tasks"), list)
            and all(isinstance(t, dict) and isinstance(t.get("task"), str) and isinstance(t.get("round"), int)
                    for t in b["tasks"]))


def load(p) -> dict:
    """design-review.json. 없으면 빈 기록. 읽지 못하거나 모양이 다르면 bad_side_file(덮어쓰지 않는다)."""
    data = read_json_strict(p.design_review, {"batches": []})
    if not isinstance(data, dict) or not isinstance(data.get("batches"), list) or \
            not all(_valid(b) for b in data["batches"]):
        raise bad_side_file(p.design_review, "batches 목록 모양이 아니다")
    return data


def asked(data: dict) -> dict[tuple[str, int], str | None]:
    """이미 물은 (태스크, 라운드) → 그 묶음의 out-id(쓰다 멈췄으면 None)."""
    return {(t["task"], t["round"]): b.get("id") for b in data["batches"] for t in b["tasks"]}


def _startable(p, cfg, st: dict) -> bool:
    """pending 승인 태스크를 지금 바로 시작할 수 있나: 사양 검사·의존 충족·잠금 비어 있음(설계 11.4). 사양이 틀렸거나
    owns 를 판단할 수 없으면 시작할 수 없다(start-ready 도 띄우지 않는다)."""
    try:
        spec = specs.check(p, cfg, st["id"])
        return tasks.deps_met(p, cfg, spec) and not tasks.lock_conflicts(p, spec.id, tasks.checked_owns(cfg, spec))
    except HteamError:
        return False


def view(p, cfg, states: list[dict] | None = None, data: dict | None = None) -> dict:
    """지금의 승인 상황. waiting: awaiting_user 승인 태스크, blockers: 진행 중이거나 지금 시작할 수 있는 승인 태스크,
    fresh: waiting 가운데 아직 묻지 않은 것, asked: 물은 (태스크, 라운드) → out-id. 상태는 읽기만 한다."""
    states = state.all_states(p) if states is None else states
    done = asked(load(p) if data is None else data)
    waiting, blockers = [], []
    for st in states:
        if not cfg.is_approval(st.get("role")):
            continue
        if st["status"] == "awaiting_user":
            waiting.append(st)
        elif st["status"] in PROGRESS:
            blockers.append({"task": st["id"], "status": st["status"], "why": "진행 중"})
        elif st["status"] == "pending" and _startable(p, cfg, st):
            blockers.append({"task": st["id"], "status": "pending", "why": "지금 시작할 수 있다"})
    fresh = [st for st in waiting if (st["id"], st["round"]) not in done]
    return {"waiting": waiting, "blockers": blockers, "fresh": fresh, "asked": done}


def _urls(text: str) -> list[str]:
    return [u.rstrip(".,;:!?") for u in URL_RE.findall(text)]


def _system_urls(p) -> set[str]:
    """`docs/design/direction.md` 의 `design_system_url:` 줄 URL(디자인 시스템, 3단계 디렉터가 남긴다)."""
    try:
        text = (p.root / "docs" / "design" / "direction.md").read_text(encoding="utf-8")
    except (OSError, ValueError):
        return set()
    return {u for line in text.splitlines() if "design_system_url" in line for u in _urls(line)}


def link(p, tid: str) -> str:
    """태스크 보고서의 마지막 claude.ai URL. `design_system_url` 줄과 디자인 시스템 URL 은 뺀다. 없으면 보고서 경로."""
    try:
        text = (p.root / report_rel(tid)).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return report_rel(tid)
    skip = _system_urls(p)
    found = [u for line in text.splitlines() if "design_system_url" not in line for u in _urls(line) if u not in skip]
    return found[-1] if found else report_rel(tid)


def _line(p, cfg, st: dict) -> str:
    try:
        title = specs.load(p, st["id"]).title
    except HteamError:
        title = "(사양을 읽지 못했다)"
    if len(title) > TITLE_MAX:
        title = title[:TITLE_MAX - 1] + "…"
    return f"- {st['id']} r{st['round']} [{cfg.role_title(st['role'])}] {title}: {link(p, st['id'])}"


def _tail(rest: list[str]) -> str:
    return f"\n- 그 밖 {len(rest)}개(링크는 각 보고서): " + ", ".join(rest) if rest else ""


def render(p, cfg, sts: list[dict]) -> dict:
    """approval 질문(설계 7.4 형식). context 는 태스크마다 한 줄과 링크다. 4000자를 넘으면 뒤 태스크는 ID 만 적는다
    (남은 ID 줄이 들어갈 자리를 늘 남긴다)."""
    head = f"리뷰(Codex)가 승인한 디자인 {len(sts)}개다. 링크를 열어 보고 한 번에 답한다.\n"
    ids = [st["id"] for st in sts]
    lines: list[str] = []
    for i, st in enumerate(sts):
        line = _line(p, cfg, st)
        if len(head + "\n".join(lines + [line]) + _tail(ids[i + 1:])) > CONTEXT_MAX:
            break
        lines.append(line)
    context = head + "\n".join(lines) + _tail(ids[len(lines):])
    if len(context) > CONTEXT_MAX:  # ID 만으로도 넘친다(태스크가 수백 개)
        context = context[:CONTEXT_MAX - 1] + "…"
    obj = {"header": HEADER,
           "question": f"디자인 {len(sts)}개를 승인할까요?\n예: 모두 승인이면 이 디자인에 의존하는 개발이 이어서 시작된다",
           "context": context,
           "options": [{"label": APPROVE, "description": "추천 사유: 리뷰(Codex)가 모두 승인했다"},
                       {"label": REVISE, "description": "고칠 태스크와 내용을 이어서 알려 준다"}],
           "multiSelect": False}
    return outbox.validate_render(obj, HEADER)


def _write(p, data: dict, b: dict) -> None:
    """기록한 묶음 b 를 outbox 에 쓰고 기록에 id 를 적는다. outbox 에 같은 batch 가 이미 있으면(앞 호출이 쓰고 죽음)
    그것을 쓴다."""
    entry = next((e for e in outbox.read_outbox(p) if e.get("type") == "approval" and e.get("batch") == b["batch"]),
                 None)
    if entry is None:
        entry = outbox.append(p, {"type": "approval", "render": b["render"], "from": "coordinator", "batch": b["batch"]})
        die_at("design_review_appended")
    b["id"] = entry["id"]
    write_json(p.design_review, data)


def _result(b: dict, resumed: bool) -> dict:
    return {"id": b["id"], "batch": b["batch"], "tasks": b["tasks"], "resumed": resumed,
            "hint": f"메인의 답(`[main] reply {b['id']}`)을 기다린다. hteam wait 가 그 답에 design_review 필드를 붙인다"}


def design_review(p) -> dict:
    cfg = config.load(p)
    if not cfg.user_approval_roles:
        raise HteamError("no_approval_roles", "user_approval_roles 가 비었다(승인 직무가 없다)", USAGE,
                         "`.herdr-team/config.toml` 의 user_approval_roles 에 직무를 넣는다")
    with state.project_lock(p):
        data = load(p)
        stuck = next((b for b in data["batches"] if b.get("id") is None), None)
        if stuck is not None:  # 앞 호출이 기록 뒤 죽었다. 새 묶음보다 먼저 마저 쓴다
            _write(p, data, stuck)
            return _result(stuck, resumed=True)
        bad = state.unreadable_ids(p)
        if bad:  # 그 태스크가 진행 중인 승인 태스크인지 알 수 없다. 묶음을 잘못 나누지 않게 묻지 않는다
            raise tasks._unreadable(p, bad)
        v = view(p, cfg, data=data)
        if not v["waiting"]:
            raise HteamError("nothing_to_approve", "awaiting_user 인 승인 직무 태스크가 없다", CONFLICT)
        if not v["fresh"]:
            ids = sorted({v["asked"][(s["id"], s["round"])] for s in v["waiting"]})
            raise HteamError("already_asked", f"awaiting_user 승인 태스크는 이미 물었다: {', '.join(ids)}", CONFLICT,
                             "메인의 답(`[main] reply out-NNNN`)을 기다린다", data={"asked": ids})
        if v["blockers"]:
            names = ", ".join(f"{b['task']}({b['status']})" for b in v["blockers"])
            raise HteamError("approval_not_ready", f"진행 중이거나 지금 시작할 수 있는 승인 직무 태스크가 있다: {names}",
                             CONFLICT, "시작할 수 있으면 start-ready 를 먼저 한다. 그 태스크들이 accept 로 awaiting_user 가 "
                             "된 뒤 다시 부른다", data={"blockers": v["blockers"]})
        b = {"batch": f"dr-{len(data['batches']) + 1:04d}", "at": now(), "id": None,
             "tasks": [{"task": s["id"], "round": s["round"]} for s in v["fresh"]], "render": render(p, cfg, v["fresh"])}
        data["batches"].append(b)
        write_json(p.design_review, data)
        die_at("design_review_recorded")
        _write(p, data, b)
    return _result(b, resumed=False)


def _cmd(args) -> dict:
    p = find_project(args.root)
    roles.require_coordinator(p)
    return design_review(p)


def register(sub) -> None:
    sub.add_parser("design-review").set_defaults(func=_cmd)
```

- [ ] **Step 4: 통과 확인**

Run: `bash herdr-team/tests/run.sh -k test_approval -k test_cli`
Expected: OK(실패 없음).

- [ ] **Step 5: 커밋(구현자는 여기서 멈춘다)**

```bash
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews' || true
git add -- herdr-team/lib/hteam/approval.py herdr-team/lib/hteam/util.py herdr-team/lib/hteam/paths.py \
  herdr-team/lib/hteam/cli.py herdr-team/tests/test_approval.py
git commit -m "feat(herdr-team): design-review 로 승인 직무 태스크를 한 번에 묻는다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/lib/hteam/approval.py herdr-team/lib/hteam/util.py \
  herdr-team/lib/hteam/paths.py herdr-team/lib/hteam/cli.py herdr-team/tests/test_approval.py
```

Expected: `git grep` 출력 없음, 커밋 성공. 컨트롤러가 `scripts/codex-review.sh commit HEAD` 를 돌리고 Global Constraints 의 Codex 규칙대로 처리한다.

---
### Task 4: 승인 흐름 연결 — accept·status·wait 답 주석·사용자 수정 라운드·문서

설계 11.4·6.4·13장: 승인 직무 태스크를 accept 하면 `awaiting_user` 가 되고 다음 명령이 `design-review` 다. `status` 는 awaiting_user 태스크마다 `next`(묻지 않았고 막는 승인 태스크가 없으면 `design-review`) 또는 `hint`(어느 질문의 답을 기다리는지, 어느 승인 태스크를 기다리는지)를 준다. 1단계 `coord.py` 의 awaiting_user hint 가 없는 명령을 가리키던 것을 이것으로 바꾼다. `wait` 는 일괄 승인 질문의 답(`[main] reply out-NNNN`)에 `design_review`(묶음, `approve_all`, 태스크마다 `pending`·`depends_on`)를 붙인다. 코디네이터가 답을 해석한다: 승인이면 accept, 아니면 해당 태스크 `fix --note`, 그 태스크에 의존하는 승인 태스크도 이어서 fix. awaiting_user 에서 연 수정 라운드는 사양의 수정 블록이 "사용자 요청"으로 적는다.

정한 것: `approve_all` 은 답이 정확히 `모두 승인 (추천)` 일 때만 참이다. `pending` 은 그 태스크가 아직 그 라운드의 awaiting_user 일 때만 참이라, 적용 기록(`applied`)을 쓰기 전에 코디네이터가 죽어 답이 다시 와도 두 번 fix 하지 않는다. 수정 요청 답이 고치라고 하지 않은 태스크는 승인으로 본다(모호하면 다시 묻는다). 의존하는 승인 태스크는 선행 수정과 함께 바로 고친다(같은 묶음의 수정을 다음 묶음에 함께 묻는다). 메인은 사용자가 `수정 요청` 을 고르면 무엇을 고칠지 대화로 물은 뒤 `수정 요청: <내용>` 한 줄로 답한다.

**Files:**
- Modify: `herdr-team/lib/hteam/tasks.py`(`accept`, `fix`), `herdr-team/lib/hteam/compose.py`(수정 블록), `herdr-team/lib/hteam/approval.py`(`reply_view`, `reply_hint`), `herdr-team/lib/hteam/coord.py`(`_annotate_main`, `annotate`, `next_step`, `status`)
- Modify: `herdr-team/templates/coordinator.md`, `herdr-team/templates/CLAUDE.section.md`
- Test: `herdr-team/tests/test_approval.py`(`ApprovalFlowTest`, `ApprovalDocsTest`)

**Interfaces:**
- Consumes: Task 3 의 `approval.load(p)`, `approval.view(p, cfg, states)`, `approval.APPROVE`, `tests.test_approval.ApprovalCase`. 기존 `specs.load(p, tid).depends_on`, `state.all_states(p)`.
- Produces:
  - `accept` 결과: awaiting_user 로 갔으면 `"next": [".herdr-team/bin/hteam", "design-review"]` 와 `hint`.
  - 라운드 기록 `from_user: true`(awaiting_user 에서 연 fix). 사양 수정 블록 문장 `사용자가 일괄 승인에서 수정을 요청했다(이전 리뷰는 승인이었다).` 와 `사용자 요청: <note>`(아니면 `코디네이터 메모: <note>`).
  - `approval.reply_view(p, oid, answer, states=None) -> {"batch", "approve_all", "tasks": [{"task", "round", "status", "round_now", "pending", "depends_on"}]} | None`, `approval.reply_hint(view, oid) -> str`.
  - `coord.next_step(..., appr=None)`: awaiting_user 는 `appr`(approval.view 결과)로 정한다. `coord.annotate` 의 `[main] reply` 주석에 `design_review`(일괄 승인 질문의 답일 때). 기록을 읽지 못하면 `warning`.
  - `status` 의 `warnings` 에 일괄 승인 기록 오류.

- [ ] **Step 1: 실패하는 테스트 작성**

**Edit** `herdr-team/tests/test_approval.py`

```python
from tests.helpers import BASE_CONFIG, TeamCase
```

```python
from tests.helpers import BASE_CONFIG, ROOT, TeamCase
```

**Edit** `herdr-team/tests/test_approval.py`

```python
        self.assertIn("T-080", render["context"])  # 줄이 넘친 태스크도 ID 는 남는다


if __name__ == "__main__":
```

```python
        self.assertIn("T-080", render["context"])  # 줄이 넘친 태스크도 ID 는 남는다


H = ".herdr-team/bin/hteam"


class ApprovalFlowTest(ApprovalCase):
    """accept → awaiting_user → design-review → 메인 답 → wait 주석 → accept·fix(설계 11.4)."""

    def setUp(self):
        super().setUp()
        self.env.update({"HTEAM_WAIT_CHUNK": "0.3", "HTEAM_NO_STATUS_GRACE": "60"})

    def start_design(self, tid, screen):
        self.write_spec(tid, "designer", title=f"{screen} 화면", owns=f"docs/design/screens/{screen}/**")
        state.create(self.p, tid, "designer")
        code, out = self.hteam("start", tid)
        self.assertEqual(code, 0, out)

    def finish_design(self, tid, screen):
        """현재 라운드의 작업 → Codex 리뷰 APPROVE → accept(awaiting_user)."""
        rnd = self.task_state(tid)["round"]
        report = f"## r{rnd}\n- 아티팩트: https://claude.ai/artifact/{screen}-r{rnd}\n"
        code, out = self.act_work(tid, {f"docs/design/screens/{screen}/index.html": f"<p>{screen} r{rnd}</p>\n"},
                                  report=report)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.hteam("review", tid)[1].get("status"), "reviewing")
        self.act_review(tid, "APPROVE")
        self.assertEqual(self.hteam("review-finish", tid)[1].get("status"), "approved")
        code, out = self.hteam("accept", tid)
        self.assertEqual((code, out["status"], out.get("next")), (0, "awaiting_user", [H, "design-review"]), out)

    def statuses(self):
        code, out = self.hteam("status")
        self.assertEqual(code, 0, out)
        return {t["id"]: t for t in out["tasks"]}

    def wait_main(self):
        """메인 답이 올 때까지 wait 하고 묶음마다 ack 한다. 메인 메시지의 hteam 주석을 돌려준다."""
        for _ in range(10):
            code, out = self.hteam("wait", "--timeout", "5")
            self.assertEqual(code, 0, out)
            if out.get("delivery") is not None:
                self.assertEqual(self.hteam("wait", "--ack", str(out["delivery"]), "--timeout", "0")[0], 0)
            found = [m["hteam"] for m in out["messages"] if m["hteam"].get("kind") == "main"]
            if found:
                return found[-1]
        self.fail("메인 답이 오지 않았다")

    def test_approve_all_then_dependent_development_starts(self):
        self.start_design("T-001", "login")
        self.finish_design("T-001", "login")
        self.write_spec("T-002", "developer", owns="src/**", depends="T-001")
        state.create(self.p, "T-002", "developer")
        self.assertEqual(self.statuses()["T-001"]["next"], [H, "design-review"])
        code, out = self.hteam("start-ready")
        self.assertEqual((code, out.get("started")), (0, []), out)  # T-002 는 T-001 이 done 이 되기를 기다린다
        code, out = self.hteam("design-review")
        self.assertEqual((code, out.get("id")), (0, "out-0001"), out)
        task = self.statuses()["T-001"]
        self.assertIsNone(task["next"])
        self.assertIn("out-0001", task["hint"])
        self.assertIn("https://claude.ai/artifact/login-r1", self.outbox_items()[0]["render"]["context"])
        self.assertEqual(self.hteam("answer", "out-0001", "모두 승인 (추천)", as_="main")[0], 0)
        info = self.wait_main()
        self.assertEqual((info["reply_to"], info["duplicate"]), ("out-0001", False))
        self.assertEqual(info["design_review"], {"batch": "dr-0001", "approve_all": True, "tasks": [
            {"task": "T-001", "round": 1, "status": "awaiting_user", "round_now": 1, "pending": True,
             "depends_on": []}]})
        self.assertIn("accept", info["hint"])
        self.assertEqual(self.hteam("accept", "T-001")[1].get("status"), "done")
        code, out = self.hteam("start-ready")
        self.assertEqual([s["task"] for s in out.get("started", [])], ["T-002"], out)
        self.assertEqual(self.hteam("applied", "out-0001")[0], 0)

    def test_revise_answer_and_user_fix_round(self):
        self.start_design("T-001", "login")
        self.finish_design("T-001", "login")
        self.start_design("T-002", "list")
        self.assertIn("T-002", self.statuses()["T-001"]["hint"])  # 진행 중인 승인 태스크가 끝나면 함께 묻는다
        code, out = self.hteam("design-review")
        self.assertEqual((code, out["error"]["code"]), (3, "approval_not_ready"), out)
        self.finish_design("T-002", "list")
        code, out = self.hteam("design-review")
        self.assertEqual((code, out.get("tasks")), (0, [{"task": "T-001", "round": 1}, {"task": "T-002", "round": 1}]),
                         out)
        self.assertEqual(self.hteam("answer", "out-0001", "수정 요청: T-001 버튼을 더 크게", as_="main")[0], 0)
        info = self.wait_main()
        self.assertFalse(info["design_review"]["approve_all"])
        self.assertIn("fix", info["hint"])
        code, out = self.hteam("fix", "T-001", "--note=T-001 버튼을 더 크게")
        self.assertEqual((code, out.get("round")), (0, 2), out)
        self.assertTrue(self.task_state("T-001")["rounds"][1]["from_user"])
        work = (self.state_dir / "tasks/T-001/r2-work.md").read_text(encoding="utf-8")
        self.assertIn("사용자가 일괄 승인에서 수정을 요청했다", work)
        self.assertIn("사용자 요청: T-001 버튼을 더 크게", work)
        self.assertNotIn("의 지적을 모두 다룬다", work)
        self.assertEqual(self.hteam("accept", "T-002")[1].get("status"), "done")
        view = approval.reply_view(self.p, "out-0001", "수정 요청")  # 답이 다시 와도 다시 처리하지 않는다
        self.assertEqual([t["pending"] for t in view["tasks"]], [False, False])
        self.assertIn("이미 모두 처리됐다", approval.reply_hint(view, "out-0001"))
        self.finish_design("T-001", "login")  # r2 가 다시 승인됐다: 새 라운드라 다시 묻는다
        code, out = self.hteam("design-review")
        self.assertEqual((code, out.get("tasks")), (0, [{"task": "T-001", "round": 2}]), out)

    def test_unreadable_record_is_a_warning_not_a_crash(self):
        self.start_design("T-001", "login")
        self.finish_design("T-001", "login")
        (self.state_dir / "design-review.json").write_text("{broken", encoding="utf-8")
        code, out = self.hteam("status")
        self.assertEqual(code, 0, out)
        self.assertTrue(any("design-review.json" in w for w in out.get("warnings", [])), out)
        task = {t["id"]: t for t in out["tasks"]}["T-001"]
        self.assertIsNone(task["next"])


class ApprovalDocsTest(unittest.TestCase):
    def test_coordinator_and_main_docs(self):
        coord = (ROOT / "templates" / "coordinator.md").read_text(encoding="utf-8")
        for needle in ("`hteam design-review`", "exit 3 `approval_not_ready`", "`already_asked`", "## 일괄 승인 답",
                       "`pending: true`", '--note="<사용자 요청 원문>"', "- designer:"):
            self.assertIn(needle, coord)
        main = (ROOT / "templates" / "CLAUDE.section.md").read_text(encoding="utf-8")
        self.assertIn("`수정 요청: <태스크 ID 와 고칠 내용>`", main)
        self.assertIn("디자인 `docs/design/`", main)


if __name__ == "__main__":
```

- [ ] **Step 2: 실패 확인**

Run: `bash herdr-team/tests/run.sh -k ApprovalFlow -k ApprovalDocs`
Expected: FAIL — accept 결과에 `next` 가 없고(`KeyError`/`AssertionError`), 답 주석에 `design_review` 가 없고, 문서에 일괄 승인 절이 없다.

- [ ] **Step 3: 구현**

accept 가 awaiting_user 로 가면 다음 명령을 준다.

**Edit** `herdr-team/lib/hteam/tasks.py`

```python
        work_slot(cur)["cleaned"] = cleaned
        state.move(cur, to, "accept")
    return {"task": tid, "status": to, "warnings": warnings}
```

```python
        work_slot(cur)["cleaned"] = cleaned
        state.move(cur, to, "accept")
    out = {"task": tid, "status": to, "warnings": warnings}
    if to == "awaiting_user":  # 승인 직무: 다른 승인 태스크와 묶어 사용자에게 묻는다(설계 11.4)
        out["next"] = [SHIM, "design-review"]
        out["hint"] = (f"`{SHIM} start-ready` 뒤 `{SHIM} design-review`. exit 3 approval_not_ready 면 다른 승인 직무 "
                       "태스크를 accept 한 뒤 다시 부른다")
    return out
```

awaiting_user 에서 연 라운드에 표시를 남긴다(사양 조립 전에).

**Edit** `herdr-team/lib/hteam/tasks.py`

```python
        rd = _new_round(st, st["round"] + 1, gitio.head(p.root), choice, note=note, supplement=supplement)
        text = compose.work_spec(p, cfg, spec, rd, owns)
```

```python
        rd = _new_round(st, st["round"] + 1, gitio.head(p.root), choice, note=note, supplement=supplement)
        if old == "awaiting_user":  # 사용자 일괄 승인의 수정 요청(설계 11.4). 수정 블록이 사용자 요청으로 적는다
            rd["from_user"] = True
        text = compose.work_spec(p, cfg, spec, rd, owns)
```

**Edit** `herdr-team/lib/hteam/compose.py`

```python
        prior = review_rel(tid, n - 1)
        if (p.root / prior).is_file():
            parts.append(f"`{prior}` 의 지적을 모두 다룬다. 지적마다 어떻게 다뤘는지 보고서 `## r{n}` 절에 적는다.")
```

```python
        prior = review_rel(tid, n - 1)
        if rd.get("from_user"):
            parts.append("사용자가 일괄 승인에서 수정을 요청했다(이전 리뷰는 승인이었다). 아래 사용자 요청을 모두 반영하고, "
                         f"요청마다 어떻게 반영했는지 보고서 `## r{n}` 절에 적는다.")
        elif (p.root / prior).is_file():
            parts.append(f"`{prior}` 의 지적을 모두 다룬다. 지적마다 어떻게 다뤘는지 보고서 `## r{n}` 절에 적는다.")
```

**Edit** `herdr-team/lib/hteam/compose.py`

```python
        if rd.get("note"):
            parts.append(f"코디네이터 메모: {rd['note']}")
```

```python
        if rd.get("note"):
            parts.append(f"{'사용자 요청' if rd.get('from_user') else '코디네이터 메모'}: {rd['note']}")
```

일괄 승인 답의 처리 정보를 approval 에 더한다.

**Edit** `herdr-team/lib/hteam/approval.py`

```python
from .paths import find_project, report_rel
```

```python
from .paths import SHIM, find_project, report_rel
```

**Edit** `herdr-team/lib/hteam/approval.py`

```python
def _cmd(args) -> dict:
    p = find_project(args.root)
    roles.require_coordinator(p)
    return design_review(p)
```

```python
def reply_view(p, oid: str, answer: str, states: list[dict] | None = None) -> dict | None:
    """oid 가 design-review 묶음의 질문이면 그 답의 처리 정보, 아니면 None(설계 11.4).

    {"batch", "approve_all": 답이 정확히 APPROVE 인가, "tasks": [{"task", "round", "status", "round_now", "pending",
    "depends_on"}]}. pending: 그 태스크가 아직 그 라운드의 awaiting_user 다. 이미 accept·fix 했거나 버렸으면 거짓이라,
    적용 기록 전에 코디네이터가 죽어 답이 다시 와도 두 번 처리하지 않는다. 기록을 읽지 못하면 bad_side_file."""
    b = next((x for x in load(p)["batches"] if x.get("id") == oid), None)
    if b is None:
        return None
    by_id = {s["id"]: s for s in (state.all_states(p) if states is None else states)}
    items = []
    for t in b["tasks"]:
        st = by_id.get(t["task"]) or {}
        try:
            deps = specs.load(p, t["task"]).depends_on
        except HteamError:
            deps = []
        items.append({"task": t["task"], "round": t["round"], "status": st.get("status"), "round_now": st.get("round"),
                      "pending": st.get("status") == "awaiting_user" and st.get("round") == t["round"],
                      "depends_on": deps})
    return {"batch": b["batch"], "approve_all": answer.strip() == APPROVE, "tasks": items}


def reply_hint(view: dict, oid: str) -> str:
    """reply_view 결과로 코디네이터가 할 일(coordinator.md 의 "일괄 승인 답")."""
    pending = [t["task"] for t in view["tasks"] if t["pending"]]
    if not pending:
        return f"이 묶음의 태스크는 이미 모두 처리됐다. 다시 accept·fix 하지 않는다. `{SHIM} applied {oid}` 만 한다"
    names = ", ".join(pending)
    if view["approve_all"]:
        return f"모두 승인이다. pending 태스크({names})마다 `{SHIM} accept <T>` 뒤 `{SHIM} start-ready`, `{SHIM} applied {oid}`"
    return (f"수정 요청이다. pending 태스크({names}) 가운데 답이 고치라는 태스크마다 `{SHIM} fix <T> --note=\"<사용자 요청>\"`, "
            "그 태스크에 직간접으로 의존하는(depends_on) 이 묶음의 pending 태스크도 fix 한다. 답이 고치라고 하지 않은 pending "
            "태스크는 accept 한다. 어느 태스크인지 모호하면 notify --type question 으로 다시 묻는다. 끝나면 "
            f"`{SHIM} start-ready`, `{SHIM} applied {oid}`")


def _cmd(args) -> dict:
    p = find_project(args.root)
    roles.require_coordinator(p)
    return design_review(p)
```

coord: 답 주석과 awaiting_user 의 next.

**Edit** `herdr-team/lib/hteam/coord.py`

```python
from . import config, dispatch, herdr, outbox, roles, specs, state
```

```python
from . import approval, config, dispatch, herdr, outbox, roles, specs, state
```

**Edit** `herdr-team/lib/hteam/coord.py`

```python
def _annotate_main(p, m: dict, rows: list[dict] | None) -> dict:
```

```python
def _annotate_main(p, m: dict, rows: list[dict] | None, states: list[dict] | None = None) -> dict:
```

**Edit** `herdr-team/lib/hteam/coord.py`

```python
        info["hint"] = ("이미 적용한 답이다. ack 만 한다" if info["duplicate"]
                        else f"{oid} 의 답이다. 처리한 뒤 `{SHIM} applied {oid}`")
    return info
```

```python
        info["hint"] = ("이미 적용한 답이다. ack 만 한다" if info["duplicate"]
                        else f"{oid} 의 답이다. 처리한 뒤 `{SHIM} applied {oid}`")
        if not info["duplicate"]:
            _design_review(p, info, oid, m, states)
    return info


def _design_review(p, info: dict, oid: str, m: dict, states: list[dict] | None) -> None:
    """design-review 묶음의 답이면 처리 정보(design_review)와 할 일(hint)을 붙인다(설계 11.4)."""
    try:
        view = approval.reply_view(p, oid, m.get("body") or "", states)
    except HteamError as exc:
        info["warning"] = f"일괄 승인 기록을 읽지 못해 이 답이 일괄 승인인지 모른다: {exc.message}"
        return
    if view is not None:
        info["design_review"] = view
        info["hint"] = approval.reply_hint(view, oid)
```

**Edit** `herdr-team/lib/hteam/coord.py`

```python
        return {**m, "hteam": _annotate_main(p, m, rows)}
```

```python
        return {**m, "hteam": _annotate_main(p, m, rows, states)}
```

**Edit** `herdr-team/lib/hteam/coord.py`

```python
def next_step(cfg, st: dict, by_task: dict[str, dict], have_rows: bool,
              rows: list[dict] | None = None, horch_cmd: str | None = None) -> tuple[list[str] | None, str | None]:
    """태스크마다 다음 명령(설계 13장). 끝났다는 확실한 증거가 있을 때만 바꾸라고 하고, 모르면 기다린다.

    by_task: horch Task → 최신 시도 행. rows 를 주면(worker-list 전체) 지난 시도·제목으로 찾은 Dispatch 까지 본다.
    horch_cmd: 힌트에 넣을 horch 명령(--home 포함, Horch.cmd). 없으면 `horch`."""
```

```python
def next_step(cfg, st: dict, by_task: dict[str, dict], have_rows: bool,
              rows: list[dict] | None = None, horch_cmd: str | None = None,
              appr: dict | None = None) -> tuple[list[str] | None, str | None]:
    """태스크마다 다음 명령(설계 13장). 끝났다는 확실한 증거가 있을 때만 바꾸라고 하고, 모르면 기다린다.

    by_task: horch Task → 최신 시도 행. rows 를 주면(worker-list 전체) 지난 시도·제목으로 찾은 Dispatch 까지 본다.
    horch_cmd: 힌트에 넣을 horch 명령(--home 포함, Horch.cmd). 없으면 `horch`.
    appr: approval.view 결과(awaiting_user 의 next). 읽지 못했으면 None."""
```

**Edit** `herdr-team/lib/hteam/coord.py`

```python
    if s == "awaiting_user":
        return None, "사용자 일괄 승인을 기다린다(design-review)"
    return None, None
```

```python
    if s == "awaiting_user":
        return _awaiting(st, appr)
    return None, None


def _awaiting(st: dict, appr: dict | None) -> tuple[list[str] | None, str | None]:
    """awaiting_user 의 다음(설계 11.4): 이미 물었으면 그 답을 기다리고, 진행 중이거나 시작할 수 있는 승인 태스크가 있으면
    그것을 기다리고, 아니면 design-review."""
    if appr is None:
        return None, "사용자 일괄 승인을 기다린다(일괄 승인 기록을 읽지 못했다. status 의 warnings 를 본다)"
    key = (st["id"], st["round"])
    if key in appr["asked"]:
        oid = appr["asked"][key]
        if oid is None:
            return H("design-review"), "일괄 승인 질문을 쓰다 멈췄다. design-review 가 마저 쓴다"
        return None, f"일괄 승인 질문 {oid} 의 사용자 답을 기다린다"
    if appr["blockers"]:
        names = ", ".join(b["task"] for b in appr["blockers"])
        return None, f"승인 직무 태스크 {names} 가 accept 로 awaiting_user 가 되면 함께 묻는다(그때 design-review)"
    return H("design-review"), None
```

**Edit** `herdr-team/lib/hteam/coord.py`

```python
    items = []
    for st in state.all_states(p):
```

```python
    items = []
    states = state.all_states(p)
    warnings: list[str] = []
    appr = None
    if cfg is not None and cfg.user_approval_roles:
        try:
            appr = approval.view(p, cfg, states)
        except HteamError as exc:  # 기록이 손상됐다. awaiting_user 는 next 없이 hint 만 준다
            warnings.append(f"일괄 승인 기록: {exc.message}")
    for st in states:
```

**Edit** `herdr-team/lib/hteam/coord.py`

```python
        nxt, hint = next_step(cfg, st, by_task, horch_error is None, rows if horch_error is None else None,
                              horch_cmd=horch_cmd)
```

```python
        nxt, hint = next_step(cfg, st, by_task, horch_error is None, rows if horch_error is None else None,
                              horch_cmd=horch_cmd, appr=appr)
```

**Edit** `herdr-team/lib/hteam/coord.py`

```python
    warnings: list[str] = []
    questions = [_question(q) for q in outbox.open_questions(p, warnings)]
```

```python
    questions = [_question(q) for q in outbox.open_questions(p, warnings)]
```

코디네이터 문서: 메시지 표, 리뷰 결과, 일괄 승인 답, 직무.

**Edit** `herdr-team/templates/coordinator.md`

```markdown
| `kind: main`, `reply_to: out-NNNN` | 네가 올린 질문의 사용자 답이다. 기다리던 일에 반영하고 `hteam applied <out-id>`. `duplicate: true` 면 이미 적용했으니 무시한다 |
```

```markdown
| `kind: main`, `reply_to: out-NNNN` | 네가 올린 질문의 사용자 답이다. 기다리던 일에 반영하고 `hteam applied <out-id>`. `duplicate: true` 면 이미 적용했으니 무시한다. `design_review` 가 있으면 아래 "일괄 승인 답" 대로 한다 |
```

**Edit** `herdr-team/templates/coordinator.md`

```markdown
- `review-finish` 의 `status: approved` → `hteam accept T` → `hteam start-ready`. 기획 태스크면 accept 뒤 `hteam plan apply`(처음) 또는 `hteam plan apply --append`(추가) 를 먼저 한다.
```

```markdown
- `review-finish` 의 `status: approved` → `hteam accept T` → `hteam start-ready`. 기획 태스크면 accept 뒤 `hteam plan apply`(처음) 또는 `hteam plan apply --append`(추가) 를 먼저 한다.
- 승인 직무(designer 등)는 `accept` 가 `status: awaiting_user` 와 `next` 를 준다. `hteam start-ready` 뒤 `hteam design-review` 를 부른다. exit 3 `approval_not_ready` 면 다른 승인 직무 태스크가 아직 진행 중이거나 지금 시작할 수 있다: 그 태스크를 accept 한 뒤 다시 부른다. `already_asked` 면 사용자 답을 기다린다. `nothing_to_approve` 면 할 일이 없다.
```

**Edit** `herdr-team/templates/coordinator.md`

```markdown
## 요청 처리
```

```markdown
## 일괄 승인 답
`hteam design-review` 가 올린 approval 질문의 답은 `kind: main`, `reply_to: out-NNNN` 에 `design_review` 필드(`batch`, `approve_all`, `tasks`)가 붙어 온다. `tasks` 가운데 `pending: true` 인 태스크만 처리한다(`false` 는 이미 처리했거나 상태가 바뀌었다. 다시 accept·fix 하지 않는다). hint 가 할 일을 요약한다.
- `approve_all: true`(모두 승인): pending 태스크마다 `hteam accept T` → `hteam start-ready` → `hteam applied out-NNNN`.
- 그 밖(수정 요청): 답이 고치라는 pending 태스크마다 `hteam fix T --note="<사용자 요청 원문>"`. 그 태스크에 직간접으로 의존하는(`depends_on`) 이 묶음의 pending 태스크도 `hteam fix T --note="선행 T-xxx 의 사용자 요청을 반영한다: <원문>"` 으로 이어서 고친다. 답이 고치라고 하지 않은 pending 태스크는 `hteam accept T`. 어느 태스크를 고치라는지 모호하면 `hteam notify --type question` 으로 다시 묻고, 그 답이 올 때까지 이 묶음의 태스크를 바꾸지 않는다. 끝나면 `hteam start-ready` → `hteam applied out-NNNN`.
- 고친 태스크가 다시 승인되면(accept 뒤 awaiting_user) 새 라운드라 `hteam design-review` 가 다시 묻는다.

## 요청 처리
```

**Edit** `herdr-team/templates/coordinator.md`

```markdown
- developer: 구현. tester: 테스트와 QA 보고서.
```

```markdown
- designer: 화면 디자인(화면마다 태스크 하나, `docs/design/screens/<화면>/`). 승인 직무라 리뷰 승인 뒤 accept 하면 `awaiting_user` 가 되고, 사용자 일괄 승인(`hteam design-review`) 뒤 accept 로 `done` 이 된다. 그 화면을 구현하는 개발 태스크는 그 뒤에 시작된다.
- developer: 구현. tester: 테스트와 QA 보고서.
```

메인 문서: approval 의 수정 요청과 디자인 위치.

**Edit** `herdr-team/templates/CLAUDE.section.md`

```markdown
- 사용자가 고른 label 을, Other 로 쓴 글이면 그 글을 그대로 `hteam answer` 로 넘긴다. 질문을 바꾸거나 합치지 않는다. 여러 개가 오면 하나씩 묻는다.
```

```markdown
- 사용자가 고른 label 을, Other 로 쓴 글이면 그 글을 그대로 `hteam answer` 로 넘긴다. 질문을 바꾸거나 합치지 않는다. 여러 개가 오면 하나씩 묻는다.
- `approval`(디자인 일괄 승인)에서 사용자가 `수정 요청` 을 고르면 바로 답하지 않는다. 어느 태스크를 어떻게 고칠지 대화로 물은 뒤 `수정 요청: <태스크 ID 와 고칠 내용>` 한 줄을 답으로 보낸다(답은 한 번만 보낼 수 있다).
```

**Edit** `herdr-team/templates/CLAUDE.section.md`

```markdown
- 설정 `.herdr-team/config.toml`, 태스크 사양 `.herdr-team/tasks/`, 기획 `docs/planning/`, 워커 보고서 `docs/tasks/`, 리뷰 `docs/reviews/`.
```

```markdown
- 설정 `.herdr-team/config.toml`, 태스크 사양 `.herdr-team/tasks/`, 기획 `docs/planning/`, 디자인 `docs/design/`, 워커 보고서 `docs/tasks/`, 리뷰 `docs/reviews/`.
```

- [ ] **Step 4: 통과 확인**

Run: `bash herdr-team/tests/run.sh -k test_approval -k test_coord -k test_lifecycle -k test_setup`
Expected: OK(실패 없음). `test_lifecycle` 의 수정 블록 문구 검사(`코디네이터 메모: …`)는 그대로 통과한다.

- [ ] **Step 5: 커밋(구현자는 여기서 멈춘다)**

```bash
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews' || true
git add -- herdr-team/lib/hteam/tasks.py herdr-team/lib/hteam/compose.py herdr-team/lib/hteam/approval.py \
  herdr-team/lib/hteam/coord.py herdr-team/templates/coordinator.md herdr-team/templates/CLAUDE.section.md \
  herdr-team/tests/test_approval.py
git commit -m "feat(herdr-team): 승인 흐름 연결 — accept·status 의 design-review, 일괄 승인 답 주석, 사용자 수정 라운드

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/lib/hteam herdr-team/templates \
  herdr-team/tests/test_approval.py
```

Expected: `git grep` 출력 없음, 커밋 성공. 컨트롤러가 `scripts/codex-review.sh commit HEAD` 를 돌리고 Global Constraints 의 Codex 규칙대로 처리한다.

---
### Task 5: 정리 — 변조 검사를 git 항목(모드·링크)으로, 경로를 손실 없이

1단계가 2단계로 넘긴 정확성 결함(진행 기록 "Final(2단계로, Codex r3·커밋 P2)")을 고친다. 설계 6.3 3 의 변조 검사가 놓치던 것:
- 심볼릭 링크: `hash_files` 가 링크를 따라가 내용만 견줬다. 추적 파일을 같은 내용의 바깥 파일을 가리키는 링크로 바꾸거나, 상위 폴더를 링크로 바꿔도 변조가 아니었다.
- 파일 모드: 실행 비트 변경을 보지 않았다. 리뷰어가 `core.fileMode` 를 바꿔 숨길 수도 있었다.
- 경로: `tracked_changes` 등이 text 모드로 읽어 `\r` 이 든 경로를 바꿔 읽었고(그 파일의 변경을 놓친다), 바뀐 경로가 UTF-8 이 아니면 디코딩 오류로 리뷰가 internal 로 멈췄다. 그런 경로를 상태 파일에 쓸 때도 실패했다.

고친 뒤: 기준점과 변조 검사는 git 이 보는 항목 `모드:객체 ID` 로 견준다(작업 트리·인덱스·트리 모두). 링크는 따라가지 않고(120000, 링크 글자의 blob) 상위 폴더가 링크면 git 처럼 없는 파일이다. 실행 비트는 기준점 때의 `core.fileMode` 로 고정해 본다. git 출력의 경로는 모두 바이트로 읽어 `os.fsdecode` 로 풀고, JSON 은 `util.dumps`(짝 없는 서로게이트를 `\udcXX` 로), 사람이 읽는 글은 `util.show` 로 쓴다. 이 커밋 전에 만든 기준점은 값이 객체 ID 뿐이라 진행 중이던 그 리뷰 시도는 변조로 멈춘다(배포 전 중간 형식이라 옮기지 않는다. 사용자가 확인한 뒤 `review --retry`).

**Files:**
- Modify: `herdr-team/lib/hteam/gitio.py`(`run`, `_zb`, `log_since`, `commit_files`, `diff_names`, `dirty`, `file_mode`, `tracked_changes`, `index_entries`, `untracked`, `tree_entry`, `blob`, `toplevel`, `worktree_entries`)
- Modify: `herdr-team/lib/hteam/review.py`(`_precheck_fail`, `_index`, `baseline`, `tamper_check`, `_warning_body`), `herdr-team/lib/hteam/util.py`(`dumps`, `show`, `write_json`), `herdr-team/lib/hteam/state.py`(`save`), `herdr-team/lib/hteam/cli.py`(출력), `herdr-team/lib/hteam/compose.py`(리뷰 프롬프트 경로)
- Test: `herdr-team/tests/test_review.py`(`TamperEntryTest`, `LosslessJsonTest`), `herdr-team/tests/test_plan.py`(`GitioTest`)

**Interfaces:**
- Consumes: 기존 `gitio.run`, `gitio.top_prefix`, `gitio.to_top`, `gitio.literal`, `state.save`, `review.tamper_check`
- Produces:
  - `gitio.file_mode(root) -> bool`(core.fileMode, 없으면 True), `gitio.tracked_changes(root, exec_bit=None)`(주면 `-c core.fileMode=…` 로 고정), `gitio.index_entries(root, paths, exec_bit=True) -> {경로: "모드:ID" | "단계:모드:ID,…" | None}`(옛 `index_blobs` 를 바꾼다), `gitio.tree_entry(root, commit, path, exec_bit=True) -> "모드:ID" | None`, `gitio.blob(root, commit, path) -> ID | None`(그대로), `gitio.toplevel(root) -> str`, `gitio.worktree_entries(root, paths, exec_bit=True) -> {경로: "모드:ID" | "dir" | "other" | None}`(옛 `hash_files` 를 바꾼다).
  - `util.dumps(obj, indent=None) -> str`, `util.show(text) -> str`. `write_json`·`state.save`·cli 출력이 `dumps` 를 쓴다.
  - 기준점 `baseline.exec_bit`, `dirty`·`index` 값은 `모드:ID`.

- [ ] **Step 1: 실패하는 테스트 작성**

**Edit** `herdr-team/tests/test_review.py`

```python
class AttemptTest(ReviewCase):
    def test_failed_attempt_retries_once_then_review_failed(self):
```

```python
class TamperEntryTest(ReviewCase):
    """변조 검사는 git 이 보는 항목(모드와 객체 ID)으로 견준다: 심볼릭 링크, 실행 비트, 링크 폴더, 손실 없는 경로."""

    def finish(self):
        return self.hteam("review-finish", "T-001")

    def assert_tamper(self, path):
        self.act_review("T-001", "APPROVE")
        code, out = self.finish()
        self.assertEqual((code, out["error"]["code"]), (1, "review_tampered"), out)
        self.assertIn(path, out["tamper"]["paths"])
        return out

    def test_file_swapped_for_symlink_with_same_content_is_tamper(self):
        self.reviewing()
        outside = self.tmp / "outside.md"
        outside.write_text("# proj\n")  # README.md 와 같은 내용
        readme = self.proj / "README.md"
        readme.unlink()
        readme.symlink_to(outside)
        self.assertEqual(self.assert_tamper("README.md")["tamper"]["paths"], ["README.md"])

    def test_folder_swapped_for_symlink_is_tamper(self):
        self.commit("lib/x.txt", "x\n", "lib")
        self.reviewing()
        (self.proj / "lib").rename(self.tmp / "lib-real")
        (self.proj / "lib").symlink_to(self.tmp / "lib-real")  # lib/x.txt 의 내용은 그대로 읽힌다
        self.assert_tamper("lib/x.txt")

    def test_exec_bit_change_is_tamper(self):
        self.reviewing()
        os.chmod(self.proj / "README.md", 0o755)
        self.assertEqual(self.assert_tamper("README.md")["tamper"]["paths"], ["README.md"])

    def test_exec_bit_is_ignored_when_git_ignores_modes(self):
        self.git("config", "core.fileMode", "false")
        self.reviewing()
        os.chmod(self.proj / "README.md", 0o755)
        self.act_review("T-001", "APPROVE")
        code, out = self.finish()
        self.assertEqual((code, out.get("status")), (0, "approved"), out)

    def test_file_mode_flipped_during_review_does_not_hide_chmod(self):
        self.reviewing()
        os.chmod(self.proj / "README.md", 0o755)
        self.git("config", "core.fileMode", "false")  # 리뷰어가 설정을 바꿔 숨기려 했다
        self.assert_tamper("README.md")

    def test_carriage_return_in_path_is_read_losslessly(self):
        name = "a\rb.txt"
        try:
            self.commit(name, "x\n", "cr")
        except (OSError, AssertionError) as exc:
            self.skipTest(f"이 파일 시스템은 \\r 이 든 이름을 만들지 못한다: {exc}")
        self.reviewing()
        (self.proj / name).write_text("리뷰어가 고침\n")
        self.assertEqual(self.assert_tamper(name)["tamper"]["paths"], [name])

    def test_non_utf8_changed_path_is_kept_losslessly(self):
        # 기준점의 바뀐 경로에 UTF-8 이 아닌 이름이 있어도 리뷰가 멈추지 않고 그 이름 그대로 견준다. macOS(APFS) 는 그런
        # 파일을 만들지 못하므로 인덱스에만 넣고(skip-worktree) 스테이징만 바꾼다
        import subprocess
        name = os.fsencode("bad-") + b"\xff.txt"
        git = ["git", "-C", str(self.proj)]

        def plumb(*args, data=None):
            done = subprocess.run(git + list(args), input=data, capture_output=True, env=self.env)
            if done.returncode:
                self.skipTest(f"git 이 비 UTF-8 이름을 받지 않는다: {done.stderr!r}")
            return done.stdout.strip()
        one = plumb("hash-object", "-w", "--stdin", data=b"1\n")
        two = plumb("hash-object", "-w", "--stdin", data=b"2\n")
        plumb("update-index", "--add", "--cacheinfo", b"100644," + one + b"," + name)
        plumb("update-index", "--skip-worktree", name)
        plumb("commit", "-q", "-m", "비 UTF-8 이름")
        plumb("update-index", "--cacheinfo", b"100644," + two + b"," + name)  # 스테이징만 바뀌었다(기준점에 남는다)
        self.worked()
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out.get("status")), (0, "reviewing"), out)
        self.assertIn(os.fsdecode(name), self.attempt("T-001")["baseline"]["index"])
        self.act_review("T-001", "APPROVE")
        code, out = self.finish()
        self.assertEqual((code, out.get("status")), (0, "approved"), out)


class LosslessJsonTest(unittest.TestCase):
    def test_surrogates_round_trip_as_valid_utf8(self):
        from hteam.util import dumps, show
        value = {"bad-\udcff.txt": ["a\rb", "정상"]}
        text = dumps(value, indent=2)
        text.encode("utf-8")  # 올바른 UTF-8 이다(짝 없는 서로게이트는 이스케이프됐다)
        self.assertIn("\\udcff", text)
        self.assertEqual(json.loads(text), value)
        self.assertEqual(show("bad-\udcff.txt"), "bad-\\xff.txt")
        self.assertEqual(show("정상 a\rb"), "정상 a\rb")


class AttemptTest(ReviewCase):
    def test_failed_attempt_retries_once_then_review_failed(self):
```

**Edit** `herdr-team/tests/test_plan.py`

```python
    def test_index_blobs_reads_index_once_without_path_argv(self):
        # 리뷰 기준점은 저장소 전체 변경을 거르기 전에 묻는다. 경로마다 argv 를 늘리면 대량 변경에서 ARG_MAX 를 넘는다
        self.commit("src/a.py", "a\n", "a")
        want = self.git("rev-parse", ":src/a.py").strip()
```

```python
    def test_index_entries_read_index_once_without_path_argv(self):
        # 리뷰 기준점은 저장소 전체 변경을 거르기 전에 묻는다. 경로마다 argv 를 늘리면 대량 변경에서 ARG_MAX 를 넘는다
        self.commit("src/a.py", "a\n", "a")
        want = "100644:" + self.git("rev-parse", ":src/a.py").strip()
```

**Edit** `herdr-team/tests/test_plan.py`

```python
            got = gitio.index_blobs(self.proj, paths)
```

```python
            got = gitio.index_entries(self.proj, paths)
```

**Edit** `herdr-team/tests/test_plan.py`

```python
    def test_git_errors_are_not_answers(self):
```

```python
    def test_worktree_entries_see_what_git_sees(self):
        self.commit("x.txt", "x\n", "x")
        blob = self.git("rev-parse", "HEAD:x.txt").strip()
        (self.tmp / "out.txt").write_text("x\n")
        (self.proj / "link.txt").symlink_to(self.tmp / "out.txt")
        os.chmod(self.proj / "x.txt", 0o755)
        got = gitio.worktree_entries(self.proj, ["x.txt", "link.txt", "nope.txt"])
        self.assertEqual(got["x.txt"], f"100755:{blob}")
        self.assertTrue(got["link.txt"].startswith("120000:"))
        self.assertNotEqual(got["link.txt"], f"120000:{blob}")  # 링크 대상의 내용이 아니라 링크 글자다
        self.assertIsNone(got["nope.txt"])
        self.assertEqual(gitio.worktree_entries(self.proj, ["x.txt"], exec_bit=False)["x.txt"], f"100644:{blob}")
        self.assertEqual(gitio.tree_entry(self.proj, "HEAD", "x.txt"), f"100644:{blob}")
        self.assertEqual(gitio.blob(self.proj, "HEAD", "x.txt"), blob)

    def test_git_errors_are_not_answers(self):
```

- [ ] **Step 2: 실패 확인**

Run: `bash herdr-team/tests/run.sh -k TamperEntry -k LosslessJson -k test_index_entries -k test_worktree_entries`
Expected: FAIL — 링크·링크 폴더·실행 비트·`\r` 경로의 변경이 승인으로 지나가고(`review_tampered` 가 아니다), 비 UTF-8 경로에서 `internal`(UnicodeDecodeError), `util.dumps`·`gitio.index_entries`·`gitio.worktree_entries` 가 없다.

- [ ] **Step 3: 구현**

git 출력은 바이트로 읽고 `os.fsdecode` 로 푼다.

**Edit** `herdr-team/lib/hteam/gitio.py`

```python
def run(root, *args: str, check: bool = True, input: str | None = None, raw: bool = False) -> subprocess.CompletedProcess:
    """raw 면 출력을 바이트로 둔다(파일명이 UTF-8 이 아닐 수 있는 출력을 부르는 쪽이 os.fsdecode 로 푼다)."""
```

```python
def run(root, *args: str, check: bool = True, input: str | bytes | None = None,
        raw: bool = False) -> subprocess.CompletedProcess:
    """raw 면 입출력을 바이트로 둔다(파일명이 UTF-8 이 아닐 수 있는 출력은 부르는 쪽이 os.fsdecode 로 푼다. input 도
    바이트로 준다)."""
```

**Edit** `herdr-team/lib/hteam/gitio.py`

```python
def _z(text: str) -> list[str]:
    return [x for x in text.split("\0") if x]
```

```python
def _zb(data: bytes) -> list[str]:
    """NUL 로 나눈 git 출력(바이트) → 경로. os.fsdecode(surrogateescape)로 푼다: UTF-8 이 아닌 이름도 손실 없이 남고
    text 모드처럼 \\r 을 줄바꿈으로 바꾸지 않는다. 그대로 argv 로 넘기면 같은 바이트가 된다."""
    return [os.fsdecode(x) for x in data.split(b"\0") if x]
```

**Edit** `herdr-team/lib/hteam/gitio.py`

```python
    out = run(root, "log", "--reverse", "--format=%H%x1f%s%x1e", f"{base}..HEAD").stdout
    pairs = []
    for rec in out.split("\x1e"):
        rec = rec.strip("\n")
        if rec:
            sha, _, subject = rec.partition("\x1f")
            pairs.append((sha, subject))
    return pairs
```

```python
    out = run(root, "log", "--reverse", "--format=%H%x1f%s%x1e", f"{base}..HEAD", raw=True).stdout
    pairs = []
    for rec in out.split(b"\x1e"):
        rec = rec.strip(b"\n")
        if rec:
            sha, _, subject = rec.partition(b"\x1f")
            # 제목은 `[T-xxx]` 접두사만 본다. UTF-8 이 아닌 제목도 실패하지 않게 바꿔 읽는다
            pairs.append((sha.decode("ascii"), subject.decode("utf-8", "replace")))
    return pairs
```

**Edit** `herdr-team/lib/hteam/gitio.py`

```python
    return _z(run(root, *ABSOLUTE, *args).stdout)
```

```python
    return _zb(run(root, *ABSOLUTE, *args, raw=True).stdout)
```

**Edit** `herdr-team/lib/hteam/gitio.py`

```python
    return _z(run(root, *ABSOLUTE, "diff", "--name-only", "-z", "--no-renames", a, b).stdout)
```

```python
    return _zb(run(root, *ABSOLUTE, "diff", "--name-only", "-z", "--no-renames", a, b, raw=True).stdout)
```

**Edit** `herdr-team/lib/hteam/gitio.py`

```python
    out = run(root, *ABSOLUTE, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames", "--",
              *pathspecs).stdout
    entries, found = _z(out), []
```

```python
    out = run(root, *ABSOLUTE, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames", "--",
              *pathspecs, raw=True).stdout
    entries, found = _zb(out), []
```

**Edit** `herdr-team/lib/hteam/gitio.py`

```python
def tracked_changes(root) -> list[str]:
    """HEAD 와 다른 추적 파일(작업 트리나 인덱스 어느 한쪽이라도), 최상위 기준, 저장소 전체. 이름 바꾸기는 양쪽 경로를
    다 낸다(`git mv 제품 제외경로` 가 옛 경로를 숨기지 못하게). `git diff HEAD` 는 작업 트리만 HEAD 와 견주므로
    스테이징한 뒤 작업 트리만 되돌린 변경은 `diff --cached` 로 더한다."""
    work = _z(run(root, *ABSOLUTE, "diff", "--name-only", "-z", "--no-renames", "HEAD").stdout)
    staged = _z(run(root, *ABSOLUTE, "diff", "--cached", "--name-only", "-z", "--no-renames", "HEAD").stdout)
    return sorted(set(work) | set(staged))


def index_blobs(root, paths: list[str]) -> dict[str, str | None]:
    """최상위 기준 경로(글자 그대로)의 인덱스 객체 ID(blob 과 견줄 수 있다). 인덱스에 없으면 None. 충돌 중이라 단계가
    여럿이면 `단계:ID` 를 이어 붙인다(어느 blob 과도 같지 않다). 경로를 argv 로 넘기면 대량 변경에서 ARG_MAX 를
    넘으므로 인덱스 전체(`:(top)`, root 가 하위 폴더여도 저장소 전체)를 한 번 읽어 거른다. 저장소 어딘가의 UTF-8
    이 아닌 파일명이 디코딩 오류를 내지 않게 바이트로 읽고 os.fsdecode(surrogateescape, 손실 없음)로 푼다. UTF-8
    이름은 다른 git 출력(text)과 같은 글자로 풀린다."""
    result: dict[str, str | None] = dict.fromkeys(paths)
    if not paths:
        return result
    out = run(root, "ls-files", "-s", "-z", "--full-name", "--", ":(top)", raw=True).stdout
    found: dict[str, list[str]] = {}
    for entry in (x for x in out.split(b"\0") if x):
        meta, _, name = entry.partition(b"\t")
        _, sha, stage = meta.decode("ascii").split()
        found.setdefault(os.fsdecode(name), []).append(sha if stage == "0" else f"{stage}:{sha}")
    result.update({name: ",".join(shas) for name, shas in found.items() if name in result})
    return result


def untracked(root) -> list[str]:
    """root 아래의 추적하지 않는 파일(무시 규칙 적용), root 기준."""
    return sorted(_z(run(root, "ls-files", "--others", "--exclude-standard", "-z").stdout))


def blob(root, commit: str, path: str) -> str | None:
    """commit 의 path(git 최상위 기준, 글자 그대로) 객체 ID. 없다고 확인되면 None. git 이 읽지 못하면(잘못된 리비전,
    손상·권한) git_failed 다. `rev-parse commit:path` 는 둘을 같은 exit 1 로 내서 ls-tree 를 쓴다."""
    out = run(root, "ls-tree", "-z", "--full-tree", commit, "--", literal(path)).stdout
    for entry in _z(out):
        meta, _, name = entry.partition("\t")
        if name == path:
            return meta.split()[2]
    return None
```

```python
def file_mode(root) -> bool:
    """git 이 실행 비트를 보는가(core.fileMode, 없으면 true). false 면 git 처럼 변조 검사도 실행 비트를 보지 않는다."""
    return run(root, "config", "--bool", "core.fileMode", check=False).stdout.strip() != "false"


def tracked_changes(root, exec_bit: bool | None = None) -> list[str]:
    """HEAD 와 다른 추적 파일(작업 트리나 인덱스 어느 한쪽이라도), 최상위 기준, 저장소 전체. 이름 바꾸기는 양쪽 경로를
    다 낸다(`git mv 제품 제외경로` 가 옛 경로를 숨기지 못하게). `git diff HEAD` 는 작업 트리만 HEAD 와 견주므로
    스테이징한 뒤 작업 트리만 되돌린 변경은 `diff --cached` 로 더한다. exec_bit 를 주면 core.fileMode 를 그 값으로
    고정해 견준다(리뷰 동안 바뀐 설정이 실행 비트 변경을 숨기지 못하게)."""
    flags = (*ABSOLUTE, *(() if exec_bit is None else ("-c", f"core.fileMode={'true' if exec_bit else 'false'}")))
    work = _zb(run(root, *flags, "diff", "--name-only", "-z", "--no-renames", "HEAD", raw=True).stdout)
    staged = _zb(run(root, *flags, "diff", "--cached", "--name-only", "-z", "--no-renames", "HEAD", raw=True).stdout)
    return sorted(set(work) | set(staged))


def _entry(mode: str, oid: str, exec_bit: bool) -> str:
    """git 항목 `모드:객체 ID`. 실행 비트를 보지 않으면(exec_bit 거짓, core.fileMode=false) 일반 파일을 100644 로 적는다."""
    return f"{'100644' if mode == '100755' and not exec_bit else mode}:{oid}"


def index_entries(root, paths: list[str], exec_bit: bool = True) -> dict[str, str | None]:
    """최상위 기준 경로(글자 그대로)의 인덱스 항목 `모드:객체 ID`(tree_entry·worktree_entries 와 견줄 수 있다). 인덱스에
    없으면 None. 충돌 중이라 단계가 여럿이면 `단계:모드:ID` 를 쉼표로 잇는다(어느 항목과도 같지 않다). 경로를 argv 로
    넘기면 대량 변경에서 ARG_MAX 를 넘으므로 인덱스 전체(`:(top)`, root 가 하위 폴더여도 저장소 전체)를 한 번 읽어
    거른다. 바이트로 읽고 os.fsdecode 로 푼다(UTF-8 이 아닌 이름도 손실 없이, 다른 git 출력과 같은 글자로)."""
    result: dict[str, str | None] = dict.fromkeys(paths)
    if not paths:
        return result
    out = run(root, "ls-files", "-s", "-z", "--full-name", "--", ":(top)", raw=True).stdout
    found: dict[str, list[str]] = {}
    for entry in (x for x in out.split(b"\0") if x):
        meta, _, name = entry.partition(b"\t")
        mode, sha, stage = meta.decode("ascii").split()
        item = _entry(mode, sha, exec_bit)
        found.setdefault(os.fsdecode(name), []).append(item if stage == "0" else f"{stage}:{item}")
    result.update({name: ",".join(items) for name, items in found.items() if name in result})
    return result


def untracked(root) -> list[str]:
    """root 아래의 추적하지 않는 파일(무시 규칙 적용), root 기준."""
    return sorted(_zb(run(root, "ls-files", "--others", "--exclude-standard", "-z", raw=True).stdout))


def tree_entry(root, commit: str, path: str, exec_bit: bool = True) -> str | None:
    """commit 의 path(git 최상위 기준, 글자 그대로) 항목 `모드:객체 ID`. 없다고 확인되면 None. git 이 읽지 못하면(잘못된
    리비전, 손상·권한) git_failed 다. `rev-parse commit:path` 는 둘을 같은 exit 1 로 내서 ls-tree 를 쓴다."""
    out = run(root, "ls-tree", "-z", "--full-tree", commit, "--", literal(path), raw=True).stdout
    for entry in _zb(out):
        meta, _, name = entry.partition("\t")
        if name == path:
            mode, _, oid = meta.split()
            return _entry(mode, oid, exec_bit)
    return None


def blob(root, commit: str, path: str) -> str | None:
    """commit 의 path 객체 ID(없으면 None). tree_entry 의 ID 부분이다."""
    found = tree_entry(root, commit, path)
    return found.split(":", 1)[1] if found else None
```

**Edit** `herdr-team/lib/hteam/gitio.py`

```python
def hash_files(root, paths: list[str]) -> dict[str, str | None]:
    """root 기준 경로(`../` 포함)의 작업 트리 내용 해시(필터 적용, blob 과 견줄 수 있다). 없는 파일은 None.

    `hash-object --stdin-paths` 는 상대 경로를 git 최상위 기준으로 읽는다(root 가 하위 폴더면 root 기준 경로로는
    다른 파일을 읽거나 실패한다). 그래서 절대 경로로 넘긴다."""
    import os
    full = {x: os.path.normpath(os.path.join(str(root), x)) for x in paths}
    result: dict[str, str | None] = dict.fromkeys(paths)
    present = [x for x in paths if os.path.isfile(full[x])]
    if present:
        hashes = run(root, "hash-object", "--stdin-paths", input="\n".join(full[x] for x in present) + "\n").stdout.split()
        result.update(zip(present, hashes))
    return result
```

```python
def toplevel(root) -> str:
    """git 최상위 폴더(git 이 낸 실제 경로)."""
    return os.fsdecode(run(root, "rev-parse", "--show-toplevel", raw=True).stdout.rstrip(b"\n"))


def _through_link(top: str, full: str) -> bool:
    """full 의 상위 폴더(top 아래) 가운데 심볼릭 링크가 있나. 있으면 git 은 그 파일을 없는 것으로 본다."""
    cur = top
    for part in os.path.relpath(full, top).split(os.sep)[:-1]:
        if part == "..":
            return False  # 저장소 밖(git 경로에서는 나오지 않는다)
        cur = os.path.join(cur, part)
        if os.path.islink(cur):
            return True
    return False


def worktree_entries(root, paths: list[str], exec_bit: bool = True) -> dict[str, str | None]:
    """root 기준 경로(`../` 포함)의 작업 트리 항목 `모드:객체 ID`(tree_entry·index_entries 와 견줄 수 있다). 없으면 None.

    git 이 보는 대로 본다. 심볼릭 링크는 따라가지 않는다: 120000 과 링크 글자의 blob 이다. 상위 폴더가 링크면 git 처럼
    그 파일은 없다. 일반 파일은 실행 비트로 100755·100644(exec_bit 가 거짓이면 늘 100644)와 git 필터를 적용한
    hash-object 다. 폴더는 그 자리가 서브모듈 작업 트리면 160000 과 그 HEAD, 아니면 `dir`. 그 밖(FIFO 등)은 `other`.
    lstat 할 수 없는 경로(권한, 파일 시스템이 거부하는 이름)는 없는 것이다.
    hash-object 는 최상위에서 최상위 기준 경로를 argv 로 넘겨 부른다(`--stdin-paths` 는 줄 끝 \\r 을 지우고 `"` 로
    시작하면 따옴표를 풀며, 절대 경로는 .gitattributes 의 필터가 맞지 않는다). ARG_MAX 를 넘지 않게 나눠 부른다."""
    import stat
    result: dict[str, str | None] = dict.fromkeys(paths)
    if not paths:
        return result
    top, prefix = toplevel(root), top_prefix(root)
    regular: list[tuple[str, str, str]] = []  # (root 기준, 최상위 기준, 모드)
    for rel in paths:
        name = to_top(prefix, rel)
        full = os.path.join(top, name)
        if _through_link(top, full):
            continue
        try:
            info = os.lstat(full)
        except OSError:
            continue
        if stat.S_ISLNK(info.st_mode):
            oid = run(top, "hash-object", "--stdin", input=os.readlink(os.fsencode(full)), raw=True).stdout
            result[rel] = f"120000:{oid.decode('ascii').strip()}"
        elif stat.S_ISREG(info.st_mode):
            regular.append((rel, name, "100755" if exec_bit and info.st_mode & stat.S_IXUSR else "100644"))
        elif stat.S_ISDIR(info.st_mode):
            sub = run(full, "rev-parse", "--show-toplevel", "HEAD", check=False, raw=True)
            lines = sub.stdout.split(b"\n")
            mine = sub.returncode == 0 and len(lines) > 1 and os.fsdecode(lines[0]) == os.path.realpath(full)
            result[rel] = f"160000:{lines[1].decode('ascii').strip()}" if mine else "dir"
        else:
            result[rel] = "other"
    for i in range(0, len(regular), 500):
        chunk = regular[i:i + 500]
        oids = run(top, "hash-object", "--", *[name for _, name, _ in chunk]).stdout.split()
        for (rel, _, mode), oid in zip(chunk, oids):
            result[rel] = f"{mode}:{oid}"
    return result
```

JSON 은 서로게이트를 이스케이프하고, 사람이 읽는 글에는 `show` 로 넣는다.

**Edit** `herdr-team/lib/hteam/util.py`

```python
def write_json(path: Path, obj) -> None:
    write_atomic(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
```

```python
_SURROGATE = re.compile(r"[\ud800-\udfff]")


def dumps(obj, indent: int | None = None) -> str:
    """JSON 글(ensure_ascii=False). UTF-8 이 아닌 파일명을 os.fsdecode 로 푼 짝 없는 서로게이트(\\udcXX)는 `\\udcXX` 로
    이스케이프한다: 결과는 늘 올바른 UTF-8 이고 json.loads 가 같은 글자로 되읽는다(손실 없음)."""
    return _SURROGATE.sub(lambda m: f"\\u{ord(m.group()):04x}", json.dumps(obj, ensure_ascii=False, indent=indent))


def show(text: str) -> str:
    """사람이 읽는 글(리뷰 파일·프롬프트·커밋 본문)에 넣을 경로. UTF-8 이 아닌 바이트는 `\\xff` 꼴로 보인다."""
    try:
        return os.fsencode(text).decode("utf-8", "backslashreplace")
    except UnicodeEncodeError:  # surrogateescape 로 만들 수 없는 서로게이트
        return text.encode("utf-8", "backslashreplace").decode("utf-8")


def write_json(path: Path, obj) -> None:
    write_atomic(path, dumps(obj, indent=2) + "\n")
```

**Edit** `herdr-team/lib/hteam/state.py`

```python
from .util import flock, now, read_json, write_atomic
```

```python
from .util import dumps, flock, now, read_json, write_atomic
```

**Edit** `herdr-team/lib/hteam/state.py`

```python
    write_atomic(p.state_path(st["id"]), json.dumps(st, ensure_ascii=False, indent=2) + "\n")
```

```python
    write_atomic(p.state_path(st["id"]), dumps(st, indent=2) + "\n")  # 기준점의 경로가 UTF-8 이 아니어도 쓴다
```

**Edit** `herdr-team/lib/hteam/cli.py`

```python
import argparse
import importlib
import json
import signal
import sys

from .errors import FAIL, USAGE, HteamError
from .paths import VERSION
```

```python
import argparse
import importlib
import signal
import sys

from .errors import FAIL, USAGE, HteamError
from .paths import VERSION
from .util import dumps
```

**Edit** `herdr-team/lib/hteam/cli.py`

```python
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
```

```python
    sys.stdout.write(dumps(obj) + "\n")
```

**Edit** `herdr-team/lib/hteam/cli.py`

```python
        line = json.dumps({"ok": True, **result}, ensure_ascii=False)
```

```python
        line = dumps({"ok": True, **result})
```

**Edit** `herdr-team/lib/hteam/compose.py`

```python
from .util import fill
```

```python
from .util import fill, show
```

**Edit** `herdr-team/lib/hteam/compose.py`

```python
                files="\n".join(f"- `{f}`" for f in files) or "- 없음").rstrip() + "\n"
```

```python
                files="\n".join(f"- `{show(f)}`" for f in files) or "- 없음").rstrip() + "\n"
```

리뷰: 기준점과 변조 검사를 git 항목으로 견주고, 글에는 `show` 로 넣는다.

**Edit** `herdr-team/lib/hteam/review.py`

```python
from .util import die_at, now, write_atomic
```

```python
from .util import die_at, now, show, write_atomic
```

**Edit** `herdr-team/lib/hteam/review.py`

```python
            "## 지적 사항\n" + "".join(f"- [P1] {x}\n" for x in problems) + "\nVERDICT: REQUEST_CHANGES\n")
```

```python
            "## 지적 사항\n" + "".join(f"- [P1] {show(x)}\n" for x in problems) + "\nVERDICT: REQUEST_CHANGES\n")
```

**Edit** `herdr-team/lib/hteam/review.py`

```python
def _index(p, prefix: str, paths: list[str]) -> dict[str, str | None]:
    """프로젝트 기준 경로의 인덱스 객체 ID(gitio.index_blobs 는 최상위 기준 경로를 받는다)."""
    tops = {x: gitio.to_top(prefix, x) for x in paths}
    blobs = gitio.index_blobs(p.root, list(tops.values()))
    return {x: blobs[t] for x, t in tops.items()}


def baseline(p, tid: str) -> dict:
    """변조 기준점(설계 6.1 5): HEAD, HEAD 와 다른 추적 파일(작업 트리·인덱스)의 작업 트리 내용 해시와 인덱스 객체
    ID, 추적 안 된 파일, 진행 중인 다른 태스크. 경로는 프로젝트 기준이다. 추적 파일은 저장소 전체를 본다(프로젝트
    밖은 `../`, 리뷰 동안 바뀌면 경고를 내려고). 추적 안 된 파일은 프로젝트 안만 본다."""
    others = [s["id"] for s in state.all_states(p) if s["id"] != tid and s["status"] in ("working", "launch_failed")]
    prefix = gitio.top_prefix(p.root)
    changed = _rel(prefix, gitio.tracked_changes(p.root))
    return {"at": now(), "head": gitio.head(p.root), "dirty": gitio.hash_files(p.root, changed),
            "index": _index(p, prefix, changed), "untracked": gitio.untracked(p.root), "in_progress": others}
```

```python
def _index(p, prefix: str, paths: list[str], exec_bit: bool = True) -> dict[str, str | None]:
    """프로젝트 기준 경로의 인덱스 항목 `모드:객체 ID`(gitio.index_entries 는 최상위 기준 경로를 받는다)."""
    tops = {x: gitio.to_top(prefix, x) for x in paths}
    entries = gitio.index_entries(p.root, list(tops.values()), exec_bit)
    return {x: entries[t] for x, t in tops.items()}


def baseline(p, tid: str) -> dict:
    """변조 기준점(설계 6.1 5): HEAD, HEAD 와 다른 추적 파일(작업 트리·인덱스)의 작업 트리 항목과 인덱스 항목
    (`모드:객체 ID`), 추적 안 된 파일, 진행 중인 다른 태스크, git 이 실행 비트를 보는지(exec_bit, core.fileMode).
    경로는 프로젝트 기준이다. 추적 파일은 저장소 전체를 본다(프로젝트 밖은 `../`, 리뷰 동안 바뀌면 경고를 내려고).
    추적 안 된 파일은 프로젝트 안만 본다."""
    others = [s["id"] for s in state.all_states(p) if s["id"] != tid and s["status"] in ("working", "launch_failed")]
    prefix = gitio.top_prefix(p.root)
    exec_bit = gitio.file_mode(p.root)
    changed = _rel(prefix, gitio.tracked_changes(p.root, exec_bit))
    return {"at": now(), "head": gitio.head(p.root), "exec_bit": exec_bit,
            "dirty": gitio.worktree_entries(p.root, changed, exec_bit), "index": _index(p, prefix, changed, exec_bit),
            "untracked": gitio.untracked(p.root), "in_progress": others}
```

**Edit** `herdr-team/lib/hteam/review.py`

```python
    변조: fast-forward 가 아닌 HEAD 이동, 프로젝트 안 제외 경로 밖의 추적 파일 변경과 커밋. 경고: 프로젝트 안의 추적 안 된
    새 파일, 프로젝트 밖(`../`)에서 바뀐 추적 파일과 커밋(hteam 작업은 owns 밖을 건드리지 않으므로 모노레포의 다른 일이다)."""
```

```python
    변조: fast-forward 가 아닌 HEAD 이동, 프로젝트 안 제외 경로 밖의 추적 파일 변경과 커밋. 경고: 프로젝트 안의 추적 안 된
    새 파일, 프로젝트 밖(`../`)에서 바뀐 추적 파일과 커밋(hteam 작업은 owns 밖을 건드리지 않으므로 모노레포의 다른 일이다).
    견주는 값은 git 항목 `모드:객체 ID` 다: 내용이 같아도 심볼릭 링크로 바꾸거나 실행 비트를 바꾸면 변조다. 실행 비트는
    기준점 때의 core.fileMode 로 본다. 값이 객체 ID 뿐인 옛 기준점(이 형식 전)은 모두 달라 보여 변조로 멈춘다."""
```

**Edit** `herdr-team/lib/hteam/review.py`

```python
    prefix = gitio.top_prefix(p.root)
    head = gitio.head(p.root)
    record = {"head_before": base["head"], "head_after": head, "excluded_tasks": excluded_tasks}
```

```python
    prefix = gitio.top_prefix(p.root)
    head = gitio.head(p.root)
    exec_bit = base.get("exec_bit", True)  # 기준점 때의 core.fileMode 로 고정한다(리뷰어가 설정을 바꿔도)
    record = {"head_before": base["head"], "head_after": head, "excluded_tasks": excluded_tasks}
```

**Edit** `herdr-team/lib/hteam/review.py`

```python
    changed = _rel(prefix, gitio.tracked_changes(p.root))
    now_dirty = gitio.hash_files(p.root, changed)
    now_index = _index(p, prefix, changed)
```

```python
    changed = _rel(prefix, gitio.tracked_changes(p.root, exec_bit))
    now_dirty = gitio.worktree_entries(p.root, changed, exec_bit)
    now_index = _index(p, prefix, changed, exec_bit)
```

**Edit** `herdr-team/lib/hteam/review.py`

```python
        top = gitio.to_top(prefix, path)  # ls-tree --full-tree 는 최상위 기준 경로를 받는다
        before = base["dirty"][path] if path in base["dirty"] else gitio.blob(p.root, base["head"], top)
        after = now_dirty[path] if path in now_dirty else gitio.blob(p.root, head, top)
        moved = before != after
        if not moved and "index" in base:  # 스테이징한 뒤 작업 트리만 되돌린 변경은 인덱스에만 남는다
            before = base["index"][path] if path in base["index"] else gitio.blob(p.root, base["head"], top)
            after = now_index[path] if path in now_index else gitio.blob(p.root, head, top)
            moved = before != after
```

```python
        top = gitio.to_top(prefix, path)  # ls-tree --full-tree 는 최상위 기준 경로를 받는다

        def tree(commit: str, top: str = top) -> str | None:
            return gitio.tree_entry(p.root, commit, top, exec_bit)
        before = base["dirty"][path] if path in base["dirty"] else tree(base["head"])
        after = now_dirty[path] if path in now_dirty else tree(head)
        moved = before != after
        if not moved and "index" in base:  # 스테이징한 뒤 작업 트리만 되돌린 변경은 인덱스에만 남는다
            before = base["index"][path] if path in base["index"] else tree(base["head"])
            after = now_index[path] if path in now_index else tree(head)
            moved = before != after
```

**Edit** `herdr-team/lib/hteam/review.py`

```python
    if fresh:
        parts.append("리뷰 동안 생긴 추적하지 않는 새 파일:\n" + "\n".join(f"- {w}" for w in fresh))
    if outside:
        parts.append("리뷰 동안 프로젝트 밖에서 바뀐 추적 파일:\n" + "\n".join(f"- {w}" for w in outside))
```

```python
    if fresh:
        parts.append("리뷰 동안 생긴 추적하지 않는 새 파일:\n" + "\n".join(f"- {show(w)}" for w in fresh))
    if outside:
        parts.append("리뷰 동안 프로젝트 밖에서 바뀐 추적 파일:\n" + "\n".join(f"- {show(w)}" for w in outside))
```

- [ ] **Step 4: 통과 확인**

Run: `bash herdr-team/tests/run.sh -k test_review -k test_plan -k test_cli -k test_state_specs`
Expected: OK(실패 없음). macOS 에서는 `test_non_utf8_changed_path_is_kept_losslessly` 가 skip 없이 돈다(인덱스에만 넣으므로). 리뷰 흐름 전체는 다른 모듈도 쓰므로 Step 5 전에 `bash herdr-team/tests/run.sh` 를 백그라운드로 한 번 돌려 OK 를 확인한다.

- [ ] **Step 5: 커밋(구현자는 여기서 멈춘다)**

```bash
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews' || true
git add -- herdr-team/lib/hteam/gitio.py herdr-team/lib/hteam/review.py herdr-team/lib/hteam/util.py \
  herdr-team/lib/hteam/state.py herdr-team/lib/hteam/cli.py herdr-team/lib/hteam/compose.py \
  herdr-team/tests/test_review.py herdr-team/tests/test_plan.py
git commit -m "fix(herdr-team): 변조 검사는 git 항목(모드·링크)으로 견주고 경로는 손실 없이 다룬다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/lib/hteam herdr-team/tests/test_review.py \
  herdr-team/tests/test_plan.py
```

Expected: `git grep` 출력 없음, 커밋 성공. 컨트롤러가 `scripts/codex-review.sh commit HEAD` 를 돌리고 Global Constraints 의 Codex 규칙대로 처리한다.

---
### Task 6: 정리 — 코디네이터 루프와 메인 훅의 작은 결함

1단계 최종 리뷰가 2단계로 넘긴 것(진행 기록 "Final(2단계로)") 가운데 동작이 틀리거나 멈추는 것을 고친다. 하나하나는 작고 서로 다른 함수다.

1. **이어 붙인 워커가 이미 끝났으면 `next`**: 실행자가 horch 를 띄운 뒤 기록 전에 죽고 그 사이 워커가 done 했으면, 그 `worker_done` 은 태스크가 `launch_failed` 일 때 와서(`next` 는 `start`) 다시 오지 않는다. `start` 가 끝난 Dispatch 를 이어 붙여도 `next` 가 없어 코디네이터가 `wait` 시간 초과(최대 1시간)까지 기다렸다. 이제 `start`(와 `start-ready` 의 `started` 행)가 `review` 또는 `fix --note`(라운드 상한이면 hint)를 준다(review 의 이어 붙이기는 1단계에 이미 있다).
2. **Herdr 터미널 밖 메인의 Stop 훅**: `$HC_TERMINAL_ID` 가 없는 세션은 메인으로 판별되는데 `hteam watch` 는 exit 5 라 띄울 수 없다. Stop 훅이 매 턴 막았다. 이제 막지 않고 SessionStart 가 이유를 알린다.
3. **`commit_paths` 의 index.lock**: 같은 폴더의 워커가 커밋하는 순간 hteam 의 경로 지정 커밋(review-finish 판정, 사전 검사, plan apply)이 `index.lock` 으로 실패했다(힌트도 비었다). 이제 최대 `HTEAM_GIT_LOCK_WAIT`(10초) 동안 다시 하고, 그래도 안 되면 할 일을 알린다. 오류 문구를 300자로 자르기 전에 표시한다(git 의 긴 안내문 뒤로 `index.lock` 이 잘릴 수 있다).
4. **손상된 `applied.json`**: 빈 기록으로 읽어 적용한 답을 다시 처리할 수 있었고(같은 fix 를 두 번), `applied` 가 빈 기록으로 덮어써 기록을 잃었다. 이제 엄격히 읽는다: `applied` 는 exit 1 `bad_side_file` 로 덮어쓰지 않고, `wait` 의 답 주석은 `duplicate: null` 과 확인하라는 hint 를 준다.
5. **plan_incomplete 를 기획자에게 돌려보냄**: 앞선 `plan apply`(코디네이터)가 사양 일부만 커밋한 채 멈췄으면 planner 사전 검사가 그것을 기획자의 REQUEST_CHANGES 로 만들었다(기획자는 고칠 수 없다). 이제 `review` 가 아무것도 쓰지 않고 exit 3 `plan_incomplete` 로 코디네이터에게 알린다.
6. **`status` 가 손상된 `run.json` 을 숨김**: 없는 것처럼 보여 코디네이터가 없다고 판단하게 했다. 이제 `run_error` 로 보여 준다.

**Files:**
- Modify: `herdr-team/lib/hteam/dispatch.py`(`launch` 의 adopt 결과), `herdr-team/lib/hteam/tasks.py`(`run_work`, `_adopted_next`, `start_ready`), `herdr-team/hooks/hteam_hook.py`(`stop`, `session_start`), `herdr-team/lib/hteam/gitio.py`(import, `run`, `_wait_index`, `commit_paths`, `unstage`), `herdr-team/lib/hteam/outbox.py`(`applied_ids`), `herdr-team/lib/hteam/coord.py`(`_annotate_main`, `coordinator_view`, `status`), `herdr-team/lib/hteam/review.py`(`prechecks`)
- Modify: `herdr-team/templates/coordinator.md`, `herdr-team/skills/up/SKILL.md`
- Test: `herdr-team/tests/test_start.py`, `herdr-team/tests/test_hooks.py`, `herdr-team/tests/test_plan.py`, `herdr-team/tests/test_mainlink.py`, `herdr-team/tests/test_review.py`, `herdr-team/tests/test_coord.py`, `herdr-team/tests/test_setup.py`

**Interfaces:**
- Consumes: Task 3 의 `util.read_json_strict`, `util.bad_side_file`. Task 4 의 `coord._annotate_main`(design_review 주석을 붙이는 판). 기존 `dispatch.launch`, `outbox._run`.
- Produces:
  - `dispatch.launch` 의 adopt 결과에 `outcome`·`summary`. `tasks.run_work`·`start` 결과의 `next`(이어 붙인 Dispatch 가 `settled`·`retained`·`released` 면 `[".herdr-team/bin/hteam", "review", T]` 또는 `[..., "fix", T, "--note", "작업 실패: …"]`)와 `hint`, `start-ready` 의 `started[i].next`.
  - `gitio.run` 의 git_failed 오류 `data.index_lock: true`(stderr 에 index.lock), `gitio._wait_index(root, *args)`(환경 변수 `HTEAM_GIT_LOCK_WAIT`).
  - `outbox.applied_ids(p)` 는 손상이면 `bad_side_file`. 답 주석 `duplicate: None`.
  - `review` 의 exit 3 `plan_incomplete`(상태·리뷰 파일을 바꾸지 않는다).
  - `status` 의 `run_error`(문자열 또는 null). `coord.coordinator_view(p, run=None)`.

- [ ] **Step 1: 실패하는 테스트 작성**

**Edit** `herdr-team/tests/test_start.py`

```python
    def test_live_launcher_is_launching_and_canceled_key(self):
```

```python
    def adopt_finished(self, tid, outcome):
        """실행자가 horch 를 띄운 뒤 기록 전에 죽었고, 그 사이 워커가 done 했다. 다시 start 하면 끝난 Dispatch 를 이어 붙인다."""
        self.make_task(tid)
        self.assertEqual(self.hteam("start", tid, env={"HTEAM_TEST_DIE_AT": "after_launch"})[0], 137)
        [row] = self.horch_tasks()
        code, out = self.act(row["id"], {"done": {"outcome": outcome, "summary": "워커가 끝냈다"}})
        self.assertEqual(code, 0, out)
        code, out = self.hteam("start", tid)
        self.assertEqual((code, out["mode"], out["state"]), (0, "adopt", "settled"), out)
        return out

    def test_adopting_succeeded_worker_points_to_review(self):
        # 그 worker_done 은 launch_failed 때 왔다(next 는 start). 다시 오지 않으므로 start 가 다음 명령을 준다
        out = self.adopt_finished("T-001", "succeeded")
        self.assertEqual(out["next"], [".herdr-team/bin/hteam", "review", "T-001"])

    def test_adopting_failed_worker_points_to_fix(self):
        out = self.adopt_finished("T-001", "failed")
        self.assertEqual(out["next"][:4], [".herdr-team/bin/hteam", "fix", "T-001", "--note"])
        self.assertIn("워커가 끝냈다", out["next"][4])

    def test_adopting_live_worker_has_no_next(self):
        self.make_task("T-001")
        self.hteam("start", "T-001", env={"HTEAM_TEST_DIE_AT": "after_launch"})
        code, out = self.hteam("start", "T-001")
        self.assertEqual((code, out["mode"], out["state"]), (0, "adopt", "active"), out)
        self.assertNotIn("next", out)  # 일하는 중이다. worker_done 을 기다린다

    def test_live_launcher_is_launching_and_canceled_key(self):
```

**Edit** `herdr-team/tests/test_hooks.py`

```python
    def test_live_watch_or_dead_coordinator_passes(self):
```

```python
    def test_main_outside_herdr_is_not_blocked_every_turn(self):
        # $HC_TERMINAL_ID 가 없는 세션은 메인이지만 watch 를 띄울 수 없다(require_main 이 exit 5). 매 턴 막지 않는다
        self.assertIsNone(self.hook("stop", {"session_id": "out1"}))
        out = self.hook("session-start", {"session_id": "out2"})
        self.assertIn("Herdr 터미널이 아니다", out["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(self.hook("stop", {"session_id": "in1"}, terminal=MAIN)["decision"], "block")

    def test_live_watch_or_dead_coordinator_passes(self):
```

**Edit** `herdr-team/tests/test_plan.py`

```python
    def test_git_timeout_is_json_error(self):
```

```python
    def test_commit_paths_waits_for_index_lock(self):
        # 같은 폴더의 워커 커밋이 index.lock 을 쥔 순간이면 잠깐 기다렸다 다시 한다
        import threading
        lock = self.proj / ".git" / "index.lock"
        (self.proj / "a.txt").write_text("a\n")
        lock.write_text("")
        timer = threading.Timer(0.5, lock.unlink)
        timer.start()
        self.addCleanup(timer.cancel)
        with mock.patch.dict(os.environ, {**self.env, "HTEAM_GIT_LOCK_WAIT": "10"}, clear=True):
            sha = gitio.commit_paths(self.proj, ["a.txt"], "a")
        self.assertEqual(gitio.commit_files(self.proj, sha), ["a.txt"])

    def test_commit_paths_gives_up_on_stale_index_lock(self):
        (self.proj / "a.txt").write_text("a\n")
        (self.proj / ".git" / "index.lock").write_text("")
        with mock.patch.dict(os.environ, {**self.env, "HTEAM_GIT_LOCK_WAIT": "0.3"}, clear=True):
            with self.assertRaises(HteamError) as cm:
                gitio.commit_paths(self.proj, ["a.txt"], "a")
        self.assertEqual((cm.exception.code, cm.exception.data.get("index_lock")), ("git_failed", True))
        self.assertIn("index.lock", cm.exception.hint)
        self.assertIn("직접 지우지 않는다", cm.exception.hint)

    def test_git_timeout_is_json_error(self):
```

**Edit** `herdr-team/tests/test_mainlink.py`

```python
class AskUserTest(LinkCase):
```

```python
class AppliedRecordTest(LinkCase):
    def test_corrupt_applied_record_is_kept_and_reported(self):
        from hteam import coord
        oid = self.notify_q()
        self.assertEqual(self.hteam("answer", oid, "a", as_="main")[0], 0)
        path = self.state_dir / "applied.json"
        path.write_text("{broken")
        code, out = self.hteam("applied", oid)
        self.assertEqual((code, out["error"]["code"]), (1, "bad_side_file"), out)
        self.assertEqual(path.read_text(), "{broken")  # 빈 기록으로 덮어쓰지 않았다
        msg = {"id": 9, "type": "status", "subject": f"[main] reply {oid}", "body": "a", "sender": "external:t1"}
        info = coord.annotate(self.p, msg, [], "horch")["hteam"]
        self.assertEqual((info["kind"], info["reply_to"], info["duplicate"]), ("main", oid, None))
        self.assertIn("이미 적용했는지 모른다", info["hint"])


class AskUserTest(LinkCase):
```

**Edit** `herdr-team/tests/test_review.py`

```python
    def test_resume_after_precheck_commit(self):
```

```python
    def test_partial_plan_apply_is_not_sent_back_to_the_planner(self):
        # 앞선 plan apply 가 사양 일부만 커밋하고 멈췄다(plan_incomplete). 기획자가 고칠 수 없으므로 수정 라운드로 보내지
        # 않고 코디네이터에게 exit 3 으로 알린다
        two = ('[[task]]\nkey = "a"\nrole = "developer"\ntitle = "a 제목"\nowns = ["src/**"]\n'
               'target = "대상"\nchange = "바꿀 것"\nconstraints = "제약"\nacceptance = ["확인 1"]\n\n'
               '[[task]]\nkey = "b"\nrole = "tester"\ntitle = "b 제목"\nowns = ["tests/**"]\n'
               'target = "대상"\nchange = "바꿀 것"\nconstraints = "제약"\nacceptance = ["확인 1"]\n')
        self.commit("docs/planning/tasks.toml", two, "기획 초안")
        code, _ = self.hteam("plan", "apply", env={"HTEAM_TEST_DIE_AT": "plan_before_commit"})
        self.assertEqual(code, 137)
        self.git("add", "--", ".herdr-team/tasks/T-001.md")
        self.git("commit", "-q", "-m", "a 만 커밋", "--", ".herdr-team/tasks/T-001.md")
        self.started("T-003", "planner")
        self.act_work("T-003", files={"docs/planning/spec.md": "기획\n"})
        code, out = self.hteam("review", "T-003")
        self.assertEqual((code, out["error"]["code"]), (3, "plan_incomplete"), out)
        self.assertIn("같은 review 를 다시 한다", out["error"]["hint"])
        self.assertEqual(self.task_state("T-003")["status"], "working")
        self.assertFalse((self.proj / "docs/reviews/T-003").exists())

    def test_resume_after_precheck_commit(self):
```

**Edit** `herdr-team/tests/test_coord.py`

```python
    def test_status_from_main_and_broken_config(self):
```

```python
    def test_status_reports_corrupt_run_file(self):
        (self.state_dir / "run.json").write_text("{broken")
        code, out = self.hteam("status", as_="main")
        self.assertEqual(code, 0, out)
        self.assertIn("run.json", out["run_error"])
        self.assertIsNone(out["coordinator"]["terminal"])

    def test_status_from_main_and_broken_config(self):
```

**Edit** `herdr-team/tests/test_setup.py`

```python
    def test_no_personal_paths_or_trust_all(self):
```

```python
    def test_cleanup_rules_in_docs(self):
        coord = (ROOT / "templates/coordinator.md").read_text(encoding="utf-8")
        self.assertIn("`start-ready` 의 `started` 행에도 `next` 가 붙을 수 있다", coord)
        self.assertIn("exit 3 `plan_incomplete`", coord)
        up = (ROOT / "skills/up/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("`run_error`", up)

    def test_no_personal_paths_or_trust_all(self):
```

- [ ] **Step 2: 실패 확인**

Run: `bash herdr-team/tests/run.sh -k test_adopting -k test_main_outside_herdr -k index_lock -k AppliedRecord -k test_partial_plan_apply -k test_status_reports_corrupt_run_file -k test_cleanup_rules_in_docs`
Expected: FAIL — `next` 가 없다(`KeyError`), Stop 이 막는다, index.lock 에서 바로 git_failed, `applied` 가 손상 기록을 덮어쓴다, review 가 기획자 수정 라운드(`status: changes`)로 간다, `run_error` 가 없다, 문서 문장이 없다.

- [ ] **Step 3: 구현**

1) 이어 붙인 Dispatch 의 끝 상태를 돌려주고 run_work 가 다음 명령을 준다.

**Edit** `herdr-team/lib/hteam/dispatch.py`

```python
        return {"mode": "adopt", "horch_task": row["task"], "dispatch": row["id"], "terminal": row.get("terminal"),
                "state": row["state"], "agent": row.get("agent"), "model": row.get("model"),
                "effort": row.get("effort"), "warnings": warnings}
```

```python
        return {"mode": "adopt", "horch_task": row["task"], "dispatch": row["id"], "terminal": row.get("terminal"),
                "state": row["state"], "outcome": row.get("outcome"), "summary": row.get("summary"),
                "agent": row.get("agent"), "model": row.get("model"), "effort": row.get("effort"),
                "warnings": warnings}
```

**Edit** `herdr-team/lib/hteam/tasks.py`

```python
    return {"task": tid, "round": rd["round"], "status": "working", "agent": rd["agent"], "model": rd["model"],
            "effort": rd["effort"], **res}
```

```python
    out = {"task": tid, "round": rd["round"], "status": "working", "agent": rd["agent"], "model": rd["model"],
           "effort": rd["effort"], **res}
    nxt, hint = _adopted_next(cfg, tid, rd["round"], res)
    if nxt is not None:
        out["next"] = nxt
    if hint:
        out["hint"] = hint
    return out


def _adopted_next(cfg, tid: str, rnd: int, res: dict) -> tuple[list[str] | None, str | None]:
    """이어 붙인 작업 Dispatch 가 이미 끝났으면(done 뒤 settled·retained·released) 다음 명령. 그 worker_done 은 태스크가
    launch_failed 일 때 와서(그때 next 는 start) 다시 오지 않으므로 여기서 준다(아니면 wait 가 시간 초과까지 기다린다)."""
    if res.get("mode") != "adopt" or res.get("state") not in ("settled", "retained", "released"):
        return None, None
    if res.get("outcome") == "succeeded":
        return [SHIM, "review", tid], "이어 붙인 작업 워커가 이미 성공으로 끝났다"
    if rnd >= cfg.max_rounds:
        return None, (f"이어 붙인 작업 워커가 실패로 끝났고 max_rounds({cfg.max_rounds}) 에 닿았다. 메인에 묻고, 사용자가 "
                      f"계속하라고 하면 {SHIM} fix {tid} --force-round --note …")
    return ([SHIM, "fix", tid, "--note", f"작업 실패: {(res.get('summary') or '')[:200]}"],
            "이어 붙인 작업 워커가 이미 실패로 끝났다")
```

**Edit** `herdr-team/lib/hteam/tasks.py`

```python
            started.append({"task": tid, "round": res["round"], "dispatch": res["dispatch"],
                            "warnings": res["warnings"]})
```

```python
            started.append({"task": tid, "round": res["round"], "dispatch": res["dispatch"],
                            "warnings": res["warnings"], **({"next": res["next"]} if res.get("next") else {})})
```

2) Herdr 터미널 밖 메인.

**Edit** `herdr-team/hooks/hteam_hook.py`

```python
    """메인이고 코디네이터가 살아 있는데 watch 가 없으면 턴을 끝내지 못하게 한다. stop_hook_active 면 다시 막지 않는다.
```

```python
    """메인이고 코디네이터가 살아 있는데 watch 가 없으면 턴을 끝내지 못하게 한다. stop_hook_active 면 다시 막지 않는다.
    Herdr 터미널 밖($HC_TERMINAL_ID 없음)의 메인은 watch 를 띄울 수 없으므로(require_main 이 exit 5) 막지 않는다.
```

**Edit** `herdr-team/hooks/hteam_hook.py`

```python
    if payload.get("stop_hook_active") or p.setup_mode.exists() or role_of(p, payload) != "main":
        return None
    if outbox.watch_alive(p):
        return None
```

```python
    if payload.get("stop_hook_active") or p.setup_mode.exists() or role_of(p, payload) != "main":
        return None
    if not os.environ.get("HC_TERMINAL_ID", "").strip():
        return None
    if outbox.watch_alive(p):
        return None
```

**Edit** `herdr-team/hooks/hteam_hook.py`

```python
             f"- 먼저 `/herdr-team:up` 을 실행한다. 산출물 작업은 `{SHIM} tell \"<요청>\"` 으로 코디네이터에게 넘긴다."]
```

```python
             f"- 먼저 `/herdr-team:up` 을 실행한다. 산출물 작업은 `{SHIM} tell \"<요청>\"` 으로 코디네이터에게 넘긴다."]
    if not os.environ.get("HC_TERMINAL_ID", "").strip():
        lines.append("- 이 세션은 Herdr 터미널이 아니다($HC_TERMINAL_ID 없음). tell·watch·answer 는 Herdr 터미널의 메인 "
                     "세션에서만 된다. 사용자에게 Herdr 안에서 다시 열라고 알린다.")
```

3) index.lock 을 기다린다.

**Edit** `herdr-team/lib/hteam/gitio.py`

```python
import os
import subprocess

from .errors import FAIL, MISSING, HteamError
```

```python
import os
import subprocess
import time

from .errors import FAIL, MISSING, HteamError
from .util import env_float
```

**Edit** `herdr-team/lib/hteam/gitio.py`

```python
        raise HteamError("git_failed", f"git {_name(args)} 실패: {err.strip()[-300:]}", FAIL)
    return proc
```

```python
        # index.lock 은 git 의 긴 안내문 앞에 나와 300자로 자르면 사라질 수 있다. 자르기 전에 표시한다(_wait_index)
        raise HteamError("git_failed", f"git {_name(args)} 실패: {err.strip()[-300:]}", FAIL,
                         data={"index_lock": True} if "index.lock" in err else None)
    return proc
```

**Edit** `herdr-team/lib/hteam/gitio.py`

```python
def commit_paths(root, paths: list[str], subject: str, body: str | None = None) -> str:
    """경로 지정 커밋. 다른 워커가 스테이징한 파일을 담지 않는다. 경로의 `*?[` 가 glob 으로 읽히지 않게 literal 로 넘긴다."""
    named = [literal(p) for p in paths]
    run(root, "add", "--", *named)
    args = ["commit", "-q", "-m", subject]
    if body:
        args += ["-m", body]
    run(root, *args, "--", *named)
    return head(root)


def unstage(root, paths: list[str]) -> None:
    """HEAD 에 없는 새 파일을 인덱스에서만 뺀다(작업 트리 파일은 그대로). 인덱스에 없으면 넘어간다."""
    run(root, "rm", "--cached", "-q", "-f", "--ignore-unmatch", "--", *[literal(p) for p in paths])
```

```python
def _wait_index(root, *args: str) -> None:
    """index 를 쓰는 git 명령. 같은 폴더의 다른 git(워커의 커밋)이 index.lock 을 쥔 순간이면 잠깐 기다렸다 다시 한다.
    잠금을 얻지 못해 실패한 add·commit·rm 은 아무것도 바꾸지 않았으므로 다시 해도 된다. HTEAM_GIT_LOCK_WAIT 초(기본 10)
    안에 풀리지 않으면 git_failed 와 할 일을 알린다."""
    deadline = time.monotonic() + env_float("HTEAM_GIT_LOCK_WAIT", 10.0)
    while True:
        try:
            run(root, *args)
            return
        except HteamError as exc:
            if not exc.data.get("index_lock"):
                raise
            if time.monotonic() >= deadline:
                exc.hint = ("다른 git 명령(같은 폴더에서 일하는 워커의 커밋 등)이 `.git/index.lock` 을 쥐고 있다. 끝난 뒤 같은 "
                            "명령을 다시 한다. git 이 돌지 않는데도 남아 있으면 메인에 알린다(직접 지우지 않는다)")
                raise
            time.sleep(0.2)


def commit_paths(root, paths: list[str], subject: str, body: str | None = None) -> str:
    """경로 지정 커밋. 다른 워커가 스테이징한 파일을 담지 않는다. 경로의 `*?[` 가 glob 으로 읽히지 않게 literal 로 넘긴다.
    다른 git 이 index.lock 을 쥐고 있으면 잠깐 기다린다(_wait_index)."""
    named = [literal(p) for p in paths]
    _wait_index(root, "add", "--", *named)
    args = ["commit", "-q", "-m", subject]
    if body:
        args += ["-m", body]
    _wait_index(root, *args, "--", *named)
    return head(root)


def unstage(root, paths: list[str]) -> None:
    """HEAD 에 없는 새 파일을 인덱스에서만 뺀다(작업 트리 파일은 그대로). 인덱스에 없으면 넘어간다."""
    _wait_index(root, "rm", "--cached", "-q", "-f", "--ignore-unmatch", "--", *[literal(p) for p in paths])
```

4) applied.json 을 엄격히 읽는다.

**Edit** `herdr-team/lib/hteam/outbox.py`

```python
from .util import die_at, env_float, flock, now, read_json, write_atomic, write_json
```

```python
from .util import bad_side_file, die_at, env_float, flock, now, read_json, read_json_strict, write_atomic, write_json
```

**Edit** `herdr-team/lib/hteam/outbox.py`

```python
def applied_ids(p) -> dict:
    return read_json(p.applied, {}) or {}
```

```python
def applied_ids(p) -> dict:
    """적용한 답 기록(out-id → 시각). 없으면 {}. 읽지 못하면 bad_side_file 이다: 빈 기록으로 보면 적용한 답을 다시
    처리하고(같은 fix 를 두 번 등) mark_applied 가 덮어써 기록을 잃는다."""
    data = read_json_strict(p.applied, {})
    if not isinstance(data, dict):
        raise bad_side_file(p.applied, "JSON 객체가 아니다")
    return data
```

**Edit** `herdr-team/lib/hteam/coord.py`

```python
        oid = hit.group(1)
        info.update(reply_to=oid, duplicate=oid in outbox.applied_ids(p))
```

```python
        oid = hit.group(1)
        try:
            duplicate = oid in outbox.applied_ids(p)
        except HteamError as exc:  # 적용 기록을 읽지 못했다. 빈 기록으로 보면 적용한 답을 다시 처리한다
            info.update(reply_to=oid, duplicate=None,
                        hint=f"{exc.message}. 이 답을 이미 적용했는지 모른다. `{SHIM} status` 로 태스크 상태를 보고 적용한 "
                             "흔적이 있으면 다시 하지 않는다. 메인에 알려 사용자가 기록을 고치게 한다")
            return info
        info.update(reply_to=oid, duplicate=duplicate)
```

5) plan_incomplete 는 코디네이터에게.

**Edit** `herdr-team/lib/hteam/review.py`

```python
        except HteamError as exc:
            detail = "; ".join(exc.data.get("errors") or []) or exc.message
            found.append(f"`{plan.PLAN_FILE}` 가 plan check 를 통과하지 못한다: {detail}")
```

```python
        except HteamError as exc:
            if exc.code == "plan_incomplete":  # 앞선 plan apply(코디네이터)가 남긴 일이다. 기획자가 고칠 수 없다
                raise HteamError("plan_incomplete", f"{tid} 를 리뷰하기 전에 앞선 plan apply 를 정리해야 한다: {exc.message}",
                                 CONFLICT, f"{exc.hint}. 메인에 알려 사용자가 정리한 뒤 같은 review 를 다시 한다",
                                 data=exc.data) from None
            detail = "; ".join(exc.data.get("errors") or []) or exc.message
            found.append(f"`{plan.PLAN_FILE}` 가 plan check 를 통과하지 못한다: {detail}")
```

6) status 의 run_error.

**Edit** `herdr-team/lib/hteam/coord.py`

```python
def coordinator_view(p) -> dict:
    run = _run(p)
```

```python
def coordinator_view(p, run: dict | None = None) -> dict:
    run = _run(p) if run is None else run
```

**Edit** `herdr-team/lib/hteam/coord.py`

```python
    out = {"tasks": items, "config_error": config_error, "horch_error": horch_error, "horch": horch_cmd,
           "coordinator": coordinator_view(p), "watch_alive": outbox.watch_alive(p),
```

```python
    run, run_error = {}, None
    try:
        run = outbox._run(p)
    except HteamError as exc:  # 손상된 run.json 을 없는 것처럼 숨기지 않는다(up·tell 은 bad_run_file 로 거부한다)
        run_error = exc.message
    out = {"tasks": items, "config_error": config_error, "run_error": run_error, "horch_error": horch_error,
           "horch": horch_cmd, "coordinator": coordinator_view(p, run), "watch_alive": outbox.watch_alive(p),
```

문서.

**Edit** `herdr-team/templates/coordinator.md`

```markdown
- `next` 는 argv 목록이고 늘 `.herdr-team/bin/hteam` 으로 시작한다. 그대로(셸 인용만 해서) 실행한다. `.herdr-team/bin/hteam` 으로 시작하지 않는 것은 `next` 로 실행하지 않는다.
```

```markdown
- `next` 는 argv 목록이고 늘 `.herdr-team/bin/hteam` 으로 시작한다. 그대로(셸 인용만 해서) 실행한다. `.herdr-team/bin/hteam` 으로 시작하지 않는 것은 `next` 로 실행하지 않는다.
- `start`·`review` 결과와 `start-ready` 의 `started` 행에도 `next` 가 붙을 수 있다(이어 붙인 워커가 이미 끝났다. 그 `worker_done` 은 다시 오지 않는다). 있으면 그대로 실행한다.
```

**Edit** `herdr-team/templates/coordinator.md`

```markdown
- `review` 가 바로 `status: changes`(`source: hteam`)를 주면 사전 검사에 걸린 것이다. `hteam fix T --note "<problems 요약>"`.
```

```markdown
- `review` 가 바로 `status: changes`(`source: hteam`)를 주면 사전 검사에 걸린 것이다. `hteam fix T --note "<problems 요약>"`.
- `review` 가 exit 3 `plan_incomplete` 를 주면 앞선 `hteam plan apply` 가 사양 일부만 커밋한 채 멈췄다(기획자가 고칠 일이 아니다). hint 와 함께 메인에 묻고, 사용자가 정리한 뒤 같은 `hteam review T` 를 다시 한다.
```

**Edit** `herdr-team/skills/up/SKILL.md`

```markdown
1. `hteam status` 를 실행한다.
```

```markdown
1. `hteam status` 를 실행한다. `run_error` 가 있으면 `.herdr-team/state/run.json` 이 손상됐다. 고치지 말고 그 내용을 사용자에게 알리고 멈춘다(`hteam up` 도 exit 1 `bad_run_file` 로 거부한다).
```

- [ ] **Step 4: 통과 확인**

Run: `bash herdr-team/tests/run.sh -k test_start -k test_hooks -k test_plan -k test_mainlink -k test_review -k test_coord -k test_setup`
Expected: OK(실패 없음).

- [ ] **Step 5: 커밋(구현자는 여기서 멈춘다)**

```bash
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews' || true
git add -- herdr-team/lib/hteam/dispatch.py herdr-team/lib/hteam/tasks.py herdr-team/hooks/hteam_hook.py \
  herdr-team/lib/hteam/gitio.py herdr-team/lib/hteam/outbox.py herdr-team/lib/hteam/coord.py herdr-team/lib/hteam/review.py \
  herdr-team/templates/coordinator.md herdr-team/skills/up/SKILL.md herdr-team/tests
git commit -m "fix(herdr-team): 이어 붙인 워커의 next, 터미널 밖 Stop, index.lock 대기, applied 손상, plan_incomplete, run_error

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/lib/hteam herdr-team/hooks/hteam_hook.py \
  herdr-team/templates/coordinator.md herdr-team/skills/up/SKILL.md herdr-team/tests
```

Expected: `git grep` 출력 없음, 커밋 성공. 컨트롤러가 `scripts/codex-review.sh commit HEAD` 를 돌리고 Global Constraints 의 Codex 규칙대로 처리한다.

---
### Task 7: 실환경 확인 — 사용자가 인터뷰에 답하고 일괄 승인

설계 15.2·15.3 2단계 실환경: 사용자가 기획 인터뷰(체크리스트 질문과 확정 질문)에 답하고, 디자인 태스크들을 `design-review` 로 한 번에 승인한다. 버리는 시험 프로젝트에서 실제 Herdr·Claude·Codex 로 한 바퀴 돌리고 설계 15.4 에 기록한다. 설계 문서를 이 단계의 결정에 맞춘다. 마지막에 2단계 커밋 전체를 Codex 가 검토한다. 코드는 결함을 고칠 때만 바꾼다(고치면 그 결함을 재현하는 테스트를 먼저 더한다). main 병합은 하지 않는다(설계 15.3: 세 단계 뒤 0.1.0 으로 병합).

**Files:**
- Modify: `docs/superpowers/specs/2026-11-05-herdr-team-design.md`(6.3, 11.2, 11.4, 13장 동기화, 15.4 에 2단계 결과)
- Modify: 결함이 나온 파일과 그 테스트

**Interfaces:**
- Consumes: Task 1–6 의 hteam(`design-review`, 승인 흐름, planner·designer 문서), 실제 `hc`·`herdr-app`·`claude`·`codex`
- Produces: 실환경 확인 기록, 설계 동기화, 2단계 브랜치 리뷰 반영

안전 규칙(1단계 Task 13 의 사용자 결정 그대로, 이 태스크 내내):
- 시험 프로젝트는 세션 스크래치패드 안에 만든다. 이 저장소와 사용자의 다른 프로젝트는 건드리지 않는다.
- 플러그인은 **시험 프로젝트 범위(project scope)에만** 등록·설치하고 끝나면 제거한다: 시험 프로젝트 폴더에서 `claude plugin marketplace add "$REPO_ROOT" --scope project`, `claude plugin install herdr-orch@herdr-team --scope project`, `claude plugin install herdr-team@herdr-team --scope project`. 사용자 범위(user scope)에 설치하지 않는다.
- `--permission-mode bypassPermissions` 는 이 버리는 시험 프로젝트의 `[agents.claude].args`(`--permission-mode=bypassPermissions`)와 시험용 메인 실행에만 쓴다. 실제 프로젝트에 같은 설정을 쓰지 않는다.
- 사용자의 hc core 를 멈추거나 다시 띄우지 않는다(`hc server stop` 금지). 시험이 만든 터미널만 kill·rm 한다.
- 시험용 `hc run` 은 늘 `--no-notify` 를 붙인다(끝날 때 종료 알림이 띄운 쪽 입력란에 들어가지 않게).
- Claude 의 처음 보는 폴더 신뢰 창(기본 "No, exit")은 `hc read` 로 커서를 본 뒤 `hc keys <터미널> down enter` 로 "Yes, I trust this folder" 를 고른다. Codex 폴더 신뢰 창은 "Trust and continue"(이 폴더만)를 고른다. **"Trust all" 류는 절대 고르지 않는다.** 키는 운영자(이 태스크를 하는 에이전트)만 누른다. 코디네이터는 누르지 않는다.
- 질문의 답: 사용자가 직접 답하겠다고 하지 않았으면 운영자가 사용자 역할로 메인 pane 의 AskUserQuestion 에 `hc keys` 로 답한다(1단계와 같다). 답은 아래 단계에 적힌 대로 고른다.
- 매 단계 뒤 작업 폴더를 저장소 루트로 돌린다(`cd "$REPO_ROOT"`). 시험 산출물은 이 저장소에 커밋하지 않는다.

- [ ] **Step 1: 시험 프로젝트·space 준비, 전역 파일 스냅숏**

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
E2E="<세션 스크래치패드>/hteam-e2e-p2"; mkdir -p "$E2E/repo" "$E2E/pre"
cp ~/.claude/plugins/known_marketplaces.json ~/.claude/plugins/installed_plugins.json "$E2E/pre/" 2>/dev/null || true
(cd "$E2E/repo" && git init -q -b main && echo "# todo web" > README.md && git add README.md && git commit -qm init)
herdr-app do space.new --name hteam-e2e-p2 --folder "$E2E/repo"
```

Expected: `{"space", "tab", "terminal"}`. 값을 `$S`, `$T` 로 적는다.

- [ ] **Step 2: 플러그인을 시험 프로젝트 범위에만 설치**

```bash
cd "$E2E/repo"
claude plugin marketplace add "$REPO_ROOT" --scope project
claude plugin install herdr-orch@herdr-team --scope project
claude plugin install herdr-team@herdr-team --scope project
cd "$REPO_ROOT"
```

Expected: 셋 다 성공. 시험 프로젝트 `.claude/settings.json` 에 `extraKnownMarketplaces`·`enabledPlugins`. 디렉터리 소스라 Claude Code 는 저장소 폴더를 바로 읽는다(설계 15.4 1단계). 그래서 고친 결함은 다음 hteam 호출부터 반영된다.

- [ ] **Step 3: 메인 세션으로 init(designer 직무 유지)**

```bash
hc run --bg --json --no-parent --no-notify --name hteam-e2e2-main --cwd "$E2E/repo" \
  --label herdr.space="$S" --label herdr.tab="$T" -- \
  claude --permission-mode bypassPermissions "/herdr-team:init 할 일 목록 웹 페이지(정적 HTML·CSS·JS, 빌드 도구 없음). 목록 화면(추가·완료·삭제)과 통계 화면(완료율), 브라우저 localStorage 저장, 테스트 포함."
```

`hc wait hteam-e2e2-main --timeout 600` 과 `hc read hteam-e2e2-main --lines 80` 으로 따라간다. init 4단계 표에서 화면이 있는 프로젝트이므로 designer 직무를 그대로 둔다(빼자는 제안이 나오면 "바꾸지 않고 진행"이 아니라 Other 로 "designer 유지, `[agents.claude].args` 에 `--permission-mode=bypassPermissions`"). Expected: `doctor` 통과(경고만), `.herdr-team/roles/designer.md` 와 `config.toml` 의 `[roles.designer]`·`user_approval_roles = ["designer"]`, 코디네이터가 "팀" 탭에 뜨고 bind, 메인이 watch 를 백그라운드로 띄움, `chore: herdr-team 세팅` 커밋.

- [ ] **Step 4: 기획 인터뷰 — 체크리스트 질문과 확정 질문**

```bash
hc send hteam-e2e2-main "할 일 목록 웹 페이지를 만들어 줘. 목록 화면에서 추가·완료·삭제, 통계 화면에서 완료율을 본다. 화면 디자인을 먼저 보고 승인한 뒤에 구현해 줘."
```

Expected(설계 10장): 메인이 `hteam tell` → 코디네이터가 planner 태스크를 띄운다 → 기획자가 `hteam ask-user` 로 한 번에 한 질문씩 묻는다 → 메인이 질문마다 `context`(있으면)를 보여 준 뒤 AskUserQuestion. 운영자는 사용자 역할로 질문마다 추천안을 고른다. 확인할 것:
- 질문이 체크리스트 항목을 따라간다(선택 질문에 예시·추천안·추천 사유). 뻔한 항목(빌드 도구 없음 등)은 묻지 않는다.
- 마지막 질문이 확정 질문이다: header "기획 확정" 류, `context` 에 계획 핵심·자동 결정·태스크 그래프 표, 선택지 `확정 (추천)` / `수정할 부분 있음`.
- 첫 확정 질문에는 Other 로 "수정할 부분 있음: 통계 화면에 완료한 항목 수도 보여 줘" 를 답한다. 기획자가 문서를 고치고 `plan check` 를 다시 통과시킨 뒤 확정 질문을 다시 한다. 두 번째에 `확정 (추천)` 을 고른다.
- `docs/planning/interview.md` 맨 위 체크리스트 표 12항목이 모두 `결정`·`자동 결정`·`범위 밖`. `tasks.toml` 에 화면마다 designer 태스크(`list-screen`, `stats-screen`, owns `docs/design/screens/<화면>/**`·`assets/<화면>/**`), 둘에 의존하는 developer 태스크, tester 태스크. `plan check` 통과.
- 기획 리뷰어(Codex pane)가 `hteam ask-user --task <T> --history` 로 질문과 답을 확인하고 판정한다. accept 뒤 `plan apply` → `start-ready` 가 designer 둘을 동시에 띄운다.

- [ ] **Step 5: 디자인 → 일괄 승인(수정 요청 한 번, 그다음 모두 승인) → 개발·테스트**

`herdr-app ls` 와 `"$E2E/repo/.herdr-team/bin/hteam" --root "$E2E/repo" status`(메인 밖에서 보면 `horch_error` 가 있을 수 있다. 태스크 상태와 hint 만 본다)로 따라간다. Expected(설계 11.2·11.4):
- designer 워커가 `docs/design/screens/<화면>/index.html`·`notes.md` 와 보고서(`- 아티팩트: …` 줄)를 커밋하고, Codex 리뷰어 pane 이 APPROVE 하면 코디네이터가 accept → `awaiting_user`(출력 `next` 가 `design-review`).
- 하나가 먼저 awaiting_user 가 되면 `design-review` 는 exit 3 `approval_not_ready`(다른 하나가 진행 중). 둘 다 awaiting_user 가 된 뒤 `design-review` 가 approval 질문 하나를 쓴다(`state/design-review.json` 의 `dr-0001`).
- 메인이 `context`(태스크마다 한 줄과 링크: 아티팩트 URL 또는 보고서 경로)를 그대로 보여 준 뒤 AskUserQuestion(`모두 승인 (추천)` / `수정 요청`).
- 첫 일괄 승인에서는 `수정 요청` 을 고른다. 메인이 무엇을 고칠지 대화로 묻는다 → 운영자가 "통계 화면의 완료율 숫자를 더 크게" 라고 답한다 → 메인이 `hteam answer <id> "수정 요청: <통계 화면 태스크 ID> 완료율 숫자를 더 크게"`. 코디네이터의 `wait` 결과에 `design_review`(두 태스크 `pending: true`)가 붙는다 → 통계 화면은 `fix --note=…`(r2, 사양 수정 블록에 "사용자 요청"), 목록 화면은 accept → `done`. developer 태스크는 통계 화면이 done 이 아니라 아직 기다린다.
- r2 리뷰 승인 → accept → `design-review` 가 새 묶음(통계 화면 r2 하나)을 묻는다 → `모두 승인 (추천)` → accept → `done` → `start-ready` 가 developer 를 띄운다 → tester → 모두 `done`.
- 끝난 워커·리뷰어 pane 은 release 로 닫힌다.

막히면(`no_status`, blocked 등) `hc read` 로 원인을 본다. hteam 결함이면 테스트를 먼저 더해 고친다. 하네스·에이전트 문제면 기록한다.

- [ ] **Step 6: 결과 확인**

```bash
cd "$E2E/repo"
git log --oneline | head -40
ls docs/design/screens/*/ docs/reviews/*/ docs/tasks/*/
head -20 docs/planning/interview.md
python3 -c 'import json; print(json.dumps(json.load(open(".herdr-team/state/design-review.json")), ensure_ascii=False, indent=1))'
python3 -m unittest discover -s tests 2>&1 | tail -3
cd "$REPO_ROOT"
```

Expected: `spec:`·`[plan] apply`·`[T-xxx] …`·`[T-xxx] review rN: …` 커밋. 통계 화면 태스크 보고서에 r1·r2 절. `design-review.json` 에 묶음 둘(첫 묶음 두 태스크, 둘째 묶음 통계 화면 r2). 시험 프로젝트 테스트 통과(테스트가 브라우저가 필요하면 tester 보고서의 수동 시나리오로 대신 확인한다).

- [ ] **Step 7: 정리와 남은 것 목록**

```bash
hc ls --all --json          # hteam-e2e2-main, hteam-coord-*, 워커·리뷰어(dsp-*) 터미널을 찾는다
hc kill <각 시험 터미널> --json; hc rm <각 시험 터미널> --json
herdr-app do space.close --id "$S" --confirmed true
cd "$E2E/repo"
claude plugin uninstall herdr-team@herdr-team --scope project
claude plugin uninstall herdr-orch@herdr-team --scope project
claude plugin marketplace remove herdr-team --scope project
cd "$REPO_ROOT"
diff <(python3 -m json.tool "$E2E/pre/installed_plugins.json") <(python3 -m json.tool ~/.claude/plugins/installed_plugins.json) || true
diff <(python3 -m json.tool "$E2E/pre/known_marketplaces.json") <(python3 -m json.tool ~/.claude/plugins/known_marketplaces.json) || true
hc ls --all --json
```

Expected: 시험이 만든 터미널이 남지 않는다. 사용자의 다른 터미널은 그대로다. 전역 플러그인 기록의 herdr 항목이 사라진다(다른 마켓플레이스의 `lastUpdated` 차이만 남을 수 있다). 사용자에게 보고할 남은 것을 적는다: `~/.claude/plugins/cache/herdr-team/` 복사본(uninstall 뒤에도 남는다), `$E2E` 폴더, 그 밖에 찾은 것.

- [ ] **Step 8: 설계 동기화와 15.4 기록**

설계가 정하지 않아 2단계가 정한 것을 설계에 옮긴다.

**Edit** `docs/superpowers/specs/2026-11-05-herdr-team-design.md`

```markdown
같은 태스크·라운드 묶음을 이미 물었으면 exit 3. 기록은 `state/design-review.json`.
```

```markdown
같은 태스크·라운드 묶음을 이미 물었으면 exit 3. 기록은 `state/design-review.json`. 한 (태스크, 라운드)는 한 번만 묻는다: 이미 물은 태스크가 답을 기다리는 동안 새로 awaiting_user 가 된 태스크는 다음 묶음이 되고, 수정 라운드는 라운드가 달라 다시 묻는다. 링크가 없으면 보고서 경로를 보인다. 선택지 label 은 render 규칙(7.4)대로 `모두 승인 (추천)` / `수정 요청` 이다. 묶음 기록을 먼저 쓰고 outbox 항목에 묶음 id 를 붙인다. 그 사이 죽으면 다음 호출이 그 묶음을 마저 쓴다(두 번 묻지 않는다).
```

**Edit** `docs/superpowers/specs/2026-11-05-herdr-team-design.md`

```markdown
- 코디네이터가 답을 해석한다: 승인이면 `accept`(`awaiting_user` → `done`), 아니면 해당 태스크 `fix --note`, 그 태스크에 의존하는 승인 태스크도 이어서 `fix`.
```

```markdown
- 코디네이터가 답을 해석한다: 승인이면 `accept`(`awaiting_user` → `done`), 아니면 해당 태스크 `fix --note`, 그 태스크에 의존하는 승인 태스크도 이어서 `fix`. `hteam wait` 가 그 답에 `design_review`(태스크마다 아직 그 라운드의 awaiting_user 인지 `pending`)를 붙인다. `pending` 이 아닌 태스크는 다시 처리하지 않는다. 수정 요청이 가리키지 않은 태스크는 승인으로 본다(모호하면 다시 묻는다). 메인은 사용자가 `수정 요청` 을 고르면 무엇을 고칠지 물은 뒤 `수정 요청: <내용>` 한 줄로 답한다. awaiting_user 에서 연 라운드의 사양은 수정 블록에 "사용자 요청"으로 적는다.
```

**Edit** `docs/superpowers/specs/2026-11-05-herdr-team-design.md`

```markdown
- 계정 기본이 아니라 프로젝트 디자인 시스템으로 Claude Design 화면을 만든다. 화면 원본을 `docs/design/screens/<화면>/` 에 둔다(Codex 리뷰가 읽는다).
```

```markdown
- 계정 기본이 아니라 프로젝트 디자인 시스템으로 Claude Design 화면을 만든다. 화면 원본을 `docs/design/screens/<화면>/` 에 둔다(Codex 리뷰가 읽는다). 2단계 기본형은 원본(`index.html`·`notes.md`)을 만들고, Artifact 도구를 쓸 수 있으면 같은 화면을 claude.ai 아티팩트로 올려 보고서에 URL 을 적는다. 디자인 시스템·이미지·금지 목록 검사는 3단계다.
```

**Edit** `docs/superpowers/specs/2026-11-05-herdr-team-design.md`

```markdown
| `launch_failed` | `hteam start T`(같은 라운드, 같은 horch Task 를 `--retry` 로) |
```

```markdown
| `launch_failed` | `hteam start T`(같은 라운드, 같은 horch Task 를 `--retry` 로) |
| 이어 붙인 작업 워커가 이미 끝남(기록 전 실행자 사망 뒤 done) | 그 `worker_done` 은 다시 오지 않는다. `start` 결과의 `next`(`review` 또는 `fix --note`)를 따른다 |
| hteam 커밋이 워커 커밋의 `index.lock` 과 겹침 | 경로 지정 커밋이 10초까지 기다렸다 다시 한다. 그래도 남으면 메인에 알린다(지우지 않는다) |
```

6.3 3 의 변조 판정 문장에 비교 대상을 적는다.

**Edit** `docs/superpowers/specs/2026-11-05-herdr-team-design.md`

```markdown
기준점 이후 새 커밋이 제외 경로 밖을 바꿨거나, 추적 파일 내용이 바뀌었으면 변조다.
```

```markdown
기준점 이후 새 커밋이 제외 경로 밖을 바꿨거나, 추적 파일 내용이 바뀌었으면 변조다. 내용은 git 항목(모드와 객체 ID)으로 견준다: 같은 내용이라도 심볼릭 링크로 바꾸거나 실행 비트를 바꾸면 변조다(실행 비트는 기준점 때의 `core.fileMode` 로 본다). 상위 폴더가 링크면 git 처럼 그 파일은 없는 것이다.
```

그다음 15.4 의 1단계 기록 뒤(16장 앞)에 결과를 더한다. 아래 틀의 `<…>` 를 실제 관찰로 채운다(채우지 않은 칸을 남기지 않는다):

```markdown
#### 2단계 (YYYY-MM-DD)

환경: <hc·Claude Code·codex-cli·Python 버전>. 버리는 시험 프로젝트("할 일 목록 웹 페이지", 정적 HTML·JS)를 새 space 에 만들고 플러그인은 시험 프로젝트 범위에만 설치했다(끝나고 제거).

- init(designer 직무 유지): <확인 결과>
- 기획 인터뷰(체크리스트 질문, 확정 질문, 수정할 부분 있음 → 다시 확정): <질문 수, 자동 결정, context 표시, interview.md 체크리스트>
- 기획 리뷰어의 `ask-user --history` 확인: <확인 결과>
- designer 병렬, Codex 리뷰, accept → awaiting_user, approval_not_ready: <확인 결과>
- design-review 첫 묶음 → 수정 요청 → design_review 주석 → fix(사용자 요청) + accept: <확인 결과>
- 둘째 묶음 → 모두 승인 → developer·tester 시작 → 모두 done: <확인 결과>
- 발견한 문제와 처리: <없음 또는 목록>
- 남은 것(사용자에게 알림): <캐시 폴더 등>
```

- [ ] **Step 9: 전체 테스트, 커밋, 2단계 브랜치 리뷰**

```bash
cd "$REPO_ROOT"
bash herdr-team/tests/run.sh && bash herdr-orch/tests/run.sh
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews' || true
git add -- docs/superpowers/specs/2026-11-05-herdr-team-design.md
git commit -m "docs: herdr-team 2단계 실환경 확인 결과와 설계 동기화

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- docs/superpowers/specs/2026-11-05-herdr-team-design.md
P2_BASE="$(git log --diff-filter=A --format=%H -- docs/superpowers/plans/2026-11-06-herdr-team-p2.md | tail -1)"
scripts/codex-review.sh base "$P2_BASE"
```

Expected: 두 테스트 모음 OK, `git grep` 출력 없음, 커밋 성공. `codex-review.sh` 가 리뷰 pane 의 주소를 출력한다. `hc wait <주소> --timeout 3600` 을 백그라운드로 건다. 결과 `.codex-reviews/base-<sha>.md` 의 지적은 Global Constraints 의 Codex 규칙대로 처리한다(고칠 때마다 재현 테스트를 먼저 더하고 커밋하고 그 커밋을 리뷰. 최대 3 라운드).

- [ ] **Step 10: 2단계 마무리 보고**

main 에 병합하지 않는다(3단계 뒤). 사용자에게 실환경 결과, 남은 것(Step 7), Codex 가 무엇을 지적했고 무엇을 고쳤는지, 무엇을 왜 고치지 않았는지, 3단계로 넘길 것(아래 "2단계에 넣지 않은 것")을 보고한다.

---
## 자체 검토: 설계 대응표(15.3 2번)

계획의 코드는 이 저장소(1f35fb7)를 복사한 작업 트리에 Task 1–7 의 편집을 차례로 적용해 확인했다. 태스크마다 그 태스크의 Step 4 테스트를 돌렸고, Task 2·5·6 은 구현 전에 새 테스트가 실패하는 것도 확인했다. 마지막에 두 테스트 모음 전체를 돌렸다(herdr-team 450, herdr-orch 202, 모두 OK. 1단계 끝은 412·202). 새로 복사한 트리에 이 문서의 편집을 처음부터 다시 적용해도 같은 결과가 나오는 것을 확인했다.

| 설계 | 내용 | 태스크 |
|---|---|---|
| 10 | 짧은 질문을 하나씩 `ask-user` 로, 선택 질문에 예시·추천안·추천 사유, 모순은 따로 묻기 | 1단계 planner.md(그대로) |
| 10 | 체크리스트 12항목, "결정"·"범위 밖"이 될 때까지(질문 수 제한 없음), 뻔한 항목은 "자동 결정" | 2(`## 인터뷰 체크리스트`, `interview.md` 표) |
| 10 | 마지막 질문은 확정: `context` 에 계획 핵심·자동 결정·태스크 그래프 표, 선택지 "확정 (추천)" / "수정할 부분 있음" | 2(`## 확정 질문`, 예시가 render 검사를 통과하는 테스트) |
| 10 | 결과물 spec·contracts·tasks.toml·interview.md, 끝내기 전 `plan check` 통과 | 2(산출물 절), 1단계(planner 사전 검사) |
| 10 | 수정 라운드의 기획자는 `--pending` 과 열린 질문의 `--wait` 를 먼저 확인 | 2(planner.md, 수정 블록 문구, 라운드를 넘는 열린 질문 테스트) |
| 10 | 인터뷰는 프로젝트마다 하나 | 1단계(`planner_busy`) |
| 4, 4.2 | `user_approval_roles = ["designer"]`, designer owns, director·designer 는 claude 만 | 1(템플릿), 1단계(검사) |
| 5.2 | 승인 직무 사이 의존 + owns 겹침 거부 | 1단계(plan check), 1(템플릿 설정으로 다시 확인), 2(planner.md 안내) |
| 5.3 | awaiting_user 는 잠금을 쥔다, 의존 끝 조건(승인 → 승인은 awaiting_user 도 끝) | 1단계(`state.LOCKING`, `deps_met`), 3(`view` 가 같은 조건을 쓴다) |
| 6.4 | accept: approved → awaiting_user(승인 직무) → done. fix: awaiting_user 에서 상한을 보지 않는다 | 1단계 + 4(accept 의 `next`, 수정 블록의 사용자 요청) |
| 7.2, 7.4 | approval 항목, render 검사, answer(파일 먼저 → send), applied, duplicate | 3(approval 항목을 쓴다), 1단계(answer·applied), 4(`design_review` 주석), 6(applied 손상) |
| 7.6 | 답이 없는 approval 은 열린 질문, `reask` | 1단계(`open_questions`), 3(테스트가 열린 질문을 확인) |
| 11.2 | designer 기본: 화면마다 태스크, owns, 화면 원본, 보고서 항목, 승인 직무 | 1(designer.md), 2(tasks.toml 안내) |
| 11.4 | `design-review` 조건(진행 중·지금 시작할 수 있는 승인 태스크 없음), 그 순간의 awaiting_user 전부, 승인 → 비승인 → 승인은 다음 묶음, context 한 줄과 링크(design_system_url 제외), 선택지, 이미 물었으면 exit 3, `state/design-review.json` | 3 |
| 11.4 | 답 해석: 승인 → accept, 아니면 그 태스크 fix --note, 의존하는 승인 태스크도 fix | 4(주석·hint·coordinator.md), 7(설계 동기화) |
| 8.3 | 명령 표의 `design-review`(코디네이터) | 3 |
| 13 | status 의 next(awaiting_user), 오류·복구 | 4(next), 6(이어 붙인 워커의 next, index.lock, run_error), 7(13장 표 동기화) |
| 15.2 | 실환경: 사용자가 인터뷰에 답하고 일괄 승인 | 7 |

### 설계에서 정하지 않아 계획이 정한 것

- 인터뷰 장치는 코드가 아니라 직무 문서와 리뷰 기준이다(설계 10장 "직무 문서가 규칙을 담는다"). 확정 답을 받았는지 hteam 이 기계적으로 검사하지 않는다(설계 6.1 의 사전 검사 목록에 없다). 대신 리뷰어가 `hteam ask-user --task T --history` 로 실제 질문과 답을 확인한다. 이 명령은 읽기 전용이라 리뷰어 규칙 안이다.
- `interview.md` 형식: 맨 위에 체크리스트 표(`#`·항목·상태·근거), 상태는 `미정`·`결정`·`자동 결정`·`범위 밖`. 확정 답 뒤에 문서를 바꾸면 확정을 다시 묻는다.
- 일괄 승인 선택지 label 은 `모두 승인 (추천)` / `수정 요청` 이다(render 규칙이 추천안 label 끝에 `(추천)` 을 요구한다).
- 한 (태스크, 라운드)는 한 번만 묻는다. 이미 물은 태스크가 답을 기다리는 동안 새로 awaiting_user 가 된 태스크는 새 묶음에 그것만 넣는다(같은 태스크를 두 질문에 넣지 않는다). 수정 라운드는 다시 묻는다.
- 링크: 보고서의 마지막 `https://claude.ai/…` URL. `design_system_url` 이 든 줄과 `docs/design/direction.md` 의 `design_system_url` 값은 뺀다. 없으면 보고서 경로를 보인다. context 가 4000자를 넘으면 뒤 태스크는 ID 만 적는다.
- `design-review` 오류: exit 2 `no_approval_roles`, exit 3 `nothing_to_approve`·`already_asked`·`approval_not_ready`, exit 1 `bad_side_file`(기록 손상, 덮어쓰지 않는다)·`bad_state_file`(읽지 못하는 상태 파일이 하나라도 있으면 묶음을 나누지 않는다). 코디네이터만 부른다. 프로젝트 잠금 안에서 기록 → outbox → id 순서로 쓴다.
- 답 해석 보조: `wait` 가 답에 `design_review` 를 붙이고 `pending`(아직 그 라운드의 awaiting_user)인 태스크만 처리하게 한다. `approve_all` 은 답이 정확히 `모두 승인 (추천)` 일 때만이다. 수정 요청이 가리키지 않은 태스크는 승인으로 본다. 의존하는 승인 태스크는 선행 수정과 함께 바로 fix 한다(둘이 다시 승인되면 다음 묶음으로 함께 묻는다). 메인은 `수정 요청` 을 고르면 무엇을 고칠지 대화로 물은 뒤 `수정 요청: <내용>` 한 줄로 답한다.
- accept 가 awaiting_user 로 가면 `next` 가 `design-review` 다(그 전에 `start-ready` 를 하라는 hint). status 는 awaiting_user 에 묻지 않았고 막는 승인 태스크가 없을 때만 `next` 를 준다.
- designer 기본형: 화면 원본은 `docs/design/screens/<화면>/index.html`(외부 리소스 없이)·`notes.md`. claude.ai 아티팩트는 쓸 수 있을 때만(워커 pane 에서 Artifact 도구를 쓸 수 있는지 보장되지 않는다).
- 설정 템플릿은 designer 를 기본으로 담고 `user_approval_roles = ["designer"]` 다(설계 4장 예시와 같다). 화면이 없는 프로젝트면 init 이 빼자고 제안한다.
- 변조 검사의 옛 기준점(값이 객체 ID 뿐): 옮기지 않는다. 업그레이드 때 진행 중이던 리뷰 시도는 변조로 멈추고 사용자가 확인한 뒤 `review --retry` 한다(배포 전 중간 형식, 1단계의 옛 pending·attention 형식과 같은 판단).
- `index.lock` 대기는 10초(`HTEAM_GIT_LOCK_WAIT`). 잠금 파일은 지우지 않는다.

### 1단계가 넘긴 것의 처리

| 넘긴 것(진행 기록) | 처리 |
|---|---|
| 변조 검사가 심볼릭 링크 교체·실행 비트를 못 봄 | Task 5 |
| `\r`·비 UTF-8 경로(무손실 디코딩 통일) | Task 5 |
| `start` 가 끝난 워커를 이어 붙이면 next 없음 | Task 6 |
| `HC_TERMINAL_ID` 없는 세션을 메인으로 보고 Stop 이 매 턴 막음 | Task 6 |
| `commit_paths` 의 index.lock 재시도 없음·빈 힌트 | Task 6 |
| 손상된 부속 JSON 을 빈 값으로 읽음 | Task 6(`applied.json`. 다시 처리·기록 손실이 생기는 것). `ask-acks`·`attention`·`context-denied` 는 넣지 않았다(손상이면 답을 다시 보여 주거나 다시 알리거나 한 번 더 거부할 뿐, 안전한 쪽으로 틀린다) |
| `status` 가 손상 `run.json` 을 숨김 | Task 6(`run_error`) |
| 일부 커밋 pending 의 plan_incomplete 를 기획자 수정 라운드로 보냄 | Task 6 |
| awaiting_user 힌트가 1단계에 없는 design-review 를 가리킴 | Task 3·4(명령과 next) |
| 캐시 설치의 horch 찾기(scope·projectPath·≥0.1.1 검사 없음) | 넣지 않았다. 디렉터리 마켓플레이스·형제 경로에서는 쓰이지 않는다(1·2단계 실환경 모두 형제 경로). scope 우선순위·projectPath·버전 규칙을 정하는 설계 결정이 필요해 3단계(병합 전)로 넘긴다 |
| herdr-orch `cli.py` 성공 봉투가 try 밖 | 넣지 않았다. 2단계는 herdr-orch 를 바꾸지 않는다(버전 0.1.1 유지). 3단계 병합 전에 herdr-orch 변경과 함께 |
| 테스트 하네스 env 목록·kill 뒤 wait, packed-refs 테스트 | 넣지 않았다(테스트 위생. 제품 동작에 영향 없음) |
| coord `attention.json` reported 증가·since 시점·상한 오류 힌트 | 넣지 않았다(Dispatch 수만큼만 자라고 힌트 문구 문제) |
| Herdr core 재시작 뒤 터미널 ID 재사용 확인 | 넣지 않았다. 사용자 core 를 멈추지 않는다는 규칙 때문에 실환경에서 확인할 수 없다 |
| Task 2 의 작은 것들(`--help`·SIGINT 가 JSON 아님, `parse_title` 의 유니코드 숫자, `write_atomic` 임시 이름, NaN 허용 등) | 넣지 않았다(실수 방지 수준, 2단계 기능과 무관) |

### 2단계에 넣지 않은 것(설계 15.3 3단계)

- 디자인 디렉터(레퍼런스·톤 시안·디자인 시스템), Chrome DevTools MCP 캡처, Claude Design 디자인 시스템 타입.
- designer 전체(디자인 시스템 기반 화면, `### 시스템 추가 제안` 의 보강 루프, `fix --supplement` 실사용).
- `hteam image`·`scripts/codex-run.sh`, doctor 의 Codex 래퍼 점검.
- `design-rules.md`(금지 목록 원문), `hteam lint`, 리뷰 프롬프트의 디자인 절.
- herdr-team 0.1.0 main 병합(세 단계 뒤).
