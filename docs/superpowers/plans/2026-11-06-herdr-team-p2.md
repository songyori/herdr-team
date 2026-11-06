# herdr-team 2단계(기획 인터뷰와 승인) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 설계 15.3 의 2단계를 만든다: 기획 인터뷰 체크리스트·확정 질문(10장), 승인 직무와 `awaiting_user` 흐름, 사용자 일괄 승인 `hteam design-review`(11.4), designer 기본 직무. 1단계가 넘긴 정확성 결함(변조 검사의 심볼릭 링크·실행 비트·경로 디코딩, 코디네이터 루프와 훅의 작은 결함)도 고친다.

**Architecture:** 새 모듈 `herdr-team/lib/hteam/approval.py` 가 승인 상황(`view`)과 일괄 승인 묶음(`design-review`), 그 답의 결정(`design-review --decide`)을 맡는다. 묶음은 `state/design-review.json` 에 먼저 기록하고 outbox 의 `approval` 항목으로 쓴다(그 사이 죽어도 두 번 묻지 않는다). 답은 결정 기록 하나(고칠 태스크와 의존 승인 태스크마다 그때의 라운드·사용자 요청, 승인할 태스크마다 그때의 라운드)를 한 번 쓰고 그대로 다시 하는 방식으로 처리한다. 수정 라운드는 바로 띄우지 않고(queued) `start-ready` 의 의존 검사가 선행이 다시 승인될 때까지 기다리게 한다. `coord.py` 는 이 모듈로 `status` 의 awaiting_user `next` 와 `wait` 의 답 주석(`design_review`)을 만든다. 인터뷰 규칙은 hteam 코드가 아니라 planner 직무 문서가 담는다(설계 10장). 리뷰어는 `hteam ask-user --history` 로 실제 질문과 답을 확인한다. 정리 태스크 둘은 `gitio.py` 의 무손실 경로와 git 항목(모드·객체 ID) 비교, 그리고 루프의 작은 결함을 고친다.

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
    approval.py   새로: 승인 상황 view·stale(읽기만), design-review 묶음·기록 검사·복구(Task 3), 일괄 승인 결정
                  --decide·답 주석 reply_view·reply_hint(Task 4)
    cli.py        COMMAND_MODULES 에 "approval"(Task 3), 출력 JSON 은 util.dumps(Task 5)
    paths.py      Project.design_review(Task 3)
    util.py       read_json_strict·bad_side_file(Task 3), dumps·show(Task 5)
    tasks.py      시작 예약의 선행 라운드(pred_rounds)와 새로 띄울 때의 basis(Task 3), accept·fix 의 --round,
                  accept 의 마지막 전이에서 stale 재확인·awaiting_user next, fix 의 queued·from_user(Task 4),
                  이어 붙인 워커의 next·hint(Task 6)
    compose.py    수정 라운드의 열린 질문(Task 2), 사용자 수정 요청 블록(Task 4), 리뷰 프롬프트 경로 표시(Task 5)
    coord.py      awaiting_user next·답 주석·한 Delivery 안의 중복(Task 4), applied 손상·run_error(Task 6)
    gitio.py      무손실 경로(top_prefix 포함)·git 항목(모드:ID)·작업 트리 항목(Task 5), index.lock 다시 시도(Task 6)
    review.py     기준점·변조 검사를 git 항목으로, 경로 표시(Task 5), plan_incomplete 를 코디네이터에게(Task 6)
    state.py      save 가 util.dumps(Task 5)
    dispatch.py   launch·_run_barrier 의 on_fresh(새로 띄울 때만 launched 와 같은 저장, Task 3),
                  adopt 결과에 outcome·summary(Task 6)
    outbox.py     append 의 reuse(같은 잠금 안에서 찾기, Task 3), applied_ids 엄격 읽기(Task 6)
    ask.py        --history 에 원래 render(Task 2)
    setup.py      scaffold 가 roles/designer.md 를 복사(Task 1)
  hooks/hteam_hook.py   Herdr 터미널 밖 메인(Task 6)
  templates/
    config.toml           [roles.designer], user_approval_roles = ["designer"](Task 1)
    roles/designer.md     새로(Task 1)
    roles/planner.md      체크리스트·확정 질문·리뷰 기준·designer 태스크(Task 2)
    roles/developer.md    패키지 설치는 임시 venv·격리 환경에서만(Task 1)
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
docs/superpowers/specs/2026-11-05-herdr-team-design.md   동작을 바꾼 태스크가 같은 커밋에서 맞춘다: 11.2(Task 1),
                                                         11.4(Task 3·4), 6.4·7.4(Task 4), 6.3(Task 5), 13장(Task 6), 15.4 결과(Task 7)
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
- 라운드 기록 `rounds[i].queued: true`: 일괄 승인 결정으로 만들고 아직 띄우지 않은 수정 라운드(`launch_failed`, Task 4). `start-ready` 가 의존이 풀린 뒤 띄운다.
- 라운드 기록 `rounds[i].basis: {선행: 라운드}`: 그 라운드의 워커를 새로 띄울 때 본 선행의 라운드(Task 3, stale 판단 기준). 시작 예약(프로젝트 잠금 안)이 실행 기록 `work.pred_rounds` 에 적고, `dispatch.launch` 가 새로 띄울 때(fresh)만 `launched` 와 같은 저장에서 `basis` 로 옮긴다. 같은 라운드 복구가 기존 Dispatch 를 이어 붙이거나(adopt) 다시 띄우면(retry) 처음 것 그대로다. queued 라운드는 띄울 때 남긴다.
- 묶음 기록 `batches[i].decision`(Task 4) = `{"at", "input": {태스크: 사용자 요청}, "fix": [{"task", "round", "note", "because"}], "accept": [{"task", "round"}], "skipped": [{"task", "why"}], "done": null | 시각}`.
- 새 필드는 아니지만 stale 판정(Task 3)이 history 의 `start`·`fix` 기록(`round`, `at`)으로 라운드를 연 시각을 읽는다.
- 리뷰 기준점 `baseline.exec_bit`(core.fileMode), `dirty`·`index` 의 값은 `모드:객체 ID`(Task 5). 이 커밋 전에 만든 기준점은 값이 객체 ID 뿐이라 그 시도의 review-finish 는 변조로 본다(배포 전 중간 형식이라 옮기지 않는다. 사용자가 확인한 뒤 `review --retry`).

## 태스크 순서와 의존

1(designer 직무·설정) → 2(기획 인터뷰) → 3(design-review) → 4(승인 흐름 연결) → 5(정리: 변조 검사) → 6(정리: 루프·훅) → 7(실환경 확인·결과 기록·브랜치 리뷰).

2 는 1 의 코드에 기대지 않는다(planner 문서가 designer 태스크를 설명하므로 1 뒤에 둔다). 4 는 3 의 `approval.view`·`approval.load`·`approval.stale`·`approval.Graph` 를 쓴다. 6 은 3 의 `util.read_json_strict` 를 쓰고 4 가 고친 `coord._annotate_main` 을 다시 고친다. 5 와 6 은 `gitio.py` 의 서로 다른 부분을 고친다(5 는 경로를 내는 함수와 `run` 의 시그니처, 6 은 `run` 의 오류 부분과 `commit_paths`·`unstage`). 각 태스크의 "찾을 내용"은 앞 태스크를 적용한 뒤의 코드다.

요구된 태스크 수: 기능 넷(1–4), 정리 둘(5–6), 실환경 하나(7). 정리는 리뷰어가 따로 판단할 수 있게 변조 검사(5)와 루프·훅(6)으로 나눴다.

---
### Task 1: designer 기본 직무와 승인 직무 설정

설계 4장·11.2(기본만)·15.3 2번: 설정 템플릿에 `[roles.designer]` 를 더하고 `user_approval_roles = ["designer"]` 로 둔다. designer 직무 문서(기본)를 만들고 scaffold 가 복사한다. init 스킬은 화면이 없는 프로젝트면 designer 를 빼자고 제안한다. developer 직무 문서에 패키지 설치 규칙(임시 venv 나 프로젝트의 격리 환경에서만)을 더한다(사용자 결정, 1단계 실환경에서 워커가 전역 Python 에 설치하려 했다). designer 기본형을 설계 11.2 에 적는다. 상태 기계(awaiting_user 전이, 의존 끝 조건, 승인 사슬 plan check, director·designer 는 claude 만)는 1단계 코드에 이미 있다. 이 태스크는 템플릿·scaffold 만 바꾼다.

**Files:**
- Create: `herdr-team/templates/roles/designer.md`
- Modify: `herdr-team/templates/config.toml`, `herdr-team/templates/roles/developer.md`, `herdr-team/lib/hteam/setup.py`(`FILES`), `herdr-team/skills/init/SKILL.md`, `docs/superpowers/specs/2026-11-05-herdr-team-design.md`(11.2)
- Test: `herdr-team/tests/test_setup.py`(`ScaffoldTest.test_creates_files_and_never_overwrites`, `TemplateContractTest`)

**Interfaces:**
- Consumes: `config.validate(raw)`, `config.build(raw)`, `plan.validate(cfg, tasks) -> (errors, groups)`(기존)
- Produces: 템플릿 직무 `planner·designer·developer·tester`, `user_approval_roles = ["designer"]`, designer owns `["docs/design/**", "assets/**"]`. developer 직무 문서의 설치 규칙(임시 venv·격리 환경에서만, 전역·시스템 Python·`--user` 금지). 직무 문서 `.herdr-team/roles/designer.md` 의 보고서 줄 `- 아티팩트: <claude.ai URL 또는 없음>`(Task 3 의 `approval.link` 가 마지막 claude.ai URL 을 읽는다). 화면 원본 위치 `docs/design/screens/<화면>/index.html`.

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
        developer = (ROOT / "templates/roles/developer.md").read_text(encoding="utf-8")
        self.assertIn("패키지는 임시 venv(또는 프로젝트의 격리 환경) 안에서만 설치한다. 전역·시스템 Python 에 설치하지 않고 "
                      "`--user` 도 쓰지 않는다.", developer)

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
Expected: FAIL — 템플릿에 designer 직무와 `roles/designer.md` 가 없다(`AssertionError`), scaffold 의 `created` 에 `.herdr-team/roles/designer.md` 가 없다, developer 문서에 설치 규칙이 없다.

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

**Edit** `herdr-team/templates/roles/developer.md`

```markdown
- 비밀값을 코드·커밋에 넣지 않는다.
```

```markdown
- 비밀값을 코드·커밋에 넣지 않는다.
- 패키지는 임시 venv(또는 프로젝트의 격리 환경) 안에서만 설치한다. 전역·시스템 Python 에 설치하지 않고 `--user` 도 쓰지 않는다.
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

설계 11.2 에 2단계 기본형을 적는다(같은 커밋).

**Edit** `docs/superpowers/specs/2026-11-05-herdr-team-design.md`

```markdown
- 계정 기본이 아니라 프로젝트 디자인 시스템으로 Claude Design 화면을 만든다. 화면 원본을 `docs/design/screens/<화면>/` 에 둔다(Codex 리뷰가 읽는다).
```

```markdown
- 계정 기본이 아니라 프로젝트 디자인 시스템으로 Claude Design 화면을 만든다. 화면 원본을 `docs/design/screens/<화면>/` 에 둔다(Codex 리뷰가 읽는다). 2단계 기본형은 원본(`index.html`·`notes.md`)을 만들고, Artifact 도구를 쓸 수 있으면 같은 화면을 claude.ai 아티팩트로 올려 보고서에 URL 을 적는다. 디자인 시스템·이미지·금지 목록 검사는 3단계다.
```

- [ ] **Step 4: 통과 확인**

Run: `bash herdr-team/tests/run.sh -k test_setup -k test_config`
Expected: OK(실패 없음).

- [ ] **Step 5: 커밋(구현자는 여기서 멈춘다)**

```bash
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews' || true
git add -- herdr-team/templates/roles/designer.md herdr-team/templates/roles/developer.md herdr-team/templates/config.toml \
  herdr-team/lib/hteam/setup.py herdr-team/skills/init/SKILL.md herdr-team/tests/test_setup.py \
  docs/superpowers/specs/2026-11-05-herdr-team-design.md
git commit -m "feat(herdr-team): designer 기본 직무와 승인 직무 설정 템플릿, developer 설치 규칙

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/templates herdr-team/lib/hteam/setup.py \
  herdr-team/skills/init/SKILL.md herdr-team/tests/test_setup.py docs/superpowers/specs/2026-11-05-herdr-team-design.md
```

Expected: `git grep` 출력 없음, 커밋 성공. 컨트롤러가 `scripts/codex-review.sh commit HEAD` 를 돌리고 Global Constraints 의 Codex 규칙대로 처리한다.

---
### Task 2: 기획 인터뷰 — 체크리스트 12항목과 확정 질문

설계 10장: 인터뷰 규칙은 planner 직무 문서가 담는다. 짧은 질문을 하나씩 `hteam ask-user` 로 하고, 체크리스트 12항목이 모두 "결정" 또는 "범위 밖"이 될 때까지 묻고(질문 수 제한 없음, 뻔한 항목은 "자동 결정"), 마지막 질문은 확정(`context` 에 계획 핵심·자동 결정·태스크 그래프 표, 선택지 "확정 (추천)" / "수정할 부분 있음")이다. 수정 라운드의 기획자는 먼저 `--pending` 과 열린 질문의 `--wait` 를 확인한다. 리뷰어는 `hteam ask-user --history` 로 실제 질문(보인 `render` 그대로: context·선택지)과 답을 확인한다(읽기 전용 명령이라 리뷰어 규칙 안이다). 코드는 둘만 바꾼다: 수정 블록 문구(열린 질문을 새로 묻지 않고 기다린다), `--history` 에 원래 `render` 를 더한다(Codex 계획 리뷰 r1: 이력에 context 가 없으면 확정 질문의 그래프를 확인할 수 없다). 그 밖의 인터뷰 장치(`ask-user`, 한 태스크 한 질문, 프로젝트마다 기획 하나 `planner_busy`, planner 사전 검사 `plan check`)는 1단계에 있다.

**Files:**
- Modify: `herdr-team/templates/roles/planner.md`, `herdr-team/lib/hteam/compose.py`(수정 블록), `herdr-team/lib/hteam/ask.py`(`history` 에 `render`)
- Create: `herdr-team/tests/test_interview.py`

**Interfaces:**
- Consumes: `outbox.validate_render(obj, default_header) -> dict`(기존), `compose.work_spec(p, cfg, spec, rd, owns) -> str`(기존), `hteam ask-user --task T --json - | --wait ID | --pending | --history`(기존)
- Produces: planner 문서의 절 `## 인터뷰 체크리스트`(12항목, 상태 `미정`·`결정`·`자동 결정`·`범위 밖`), `## 확정 질문`(선택지 `확정 (추천)`·`수정할 부분 있음`), `## 리뷰 기준(리뷰어가 본다)`. 수정 라운드 사양의 문장 `` `.herdr-team/bin/hteam ask-user --task T-xxx --wait <id>` 로 그 답을 기다린다 ``. `hteam ask-user --task T --history` 의 항목에 원래 질문 `render`(header·question·context·options)를 더한다(리뷰어가 확정 질문에 보인 태스크 그래프를 tasks.toml 과 견준다).

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
        for needle in ("ask-user --task <이 태스크> --history", "답이 `확정 (추천)` 이다", "12항목", "`render.context`"):
            self.assertIn(needle, review)
        self.assertIn("--wait <id>", section(self.text, "사용자에게 묻기"))
        self.assertIn("designer 태스크", section(self.text, "tasks.toml 형식"))


class FixRoundQuestionTest(TeamCase):
    """수정 라운드의 기획자는 앞 라운드의 열린 질문을 새로 묻지 않고 기다린다(설계 10장)."""

    QUESTION = {"question": "저장 위치는?\n예: 파일이면 서버가 필요 없다", "context": "앞선 답: 웹 앱이다",
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
        shown = out["history"][0]["render"]  # 리뷰어가 사용자에게 보인 그대로 본다(context·선택지)
        self.assertEqual((shown["context"], [o["label"] for o in shown["options"]]), ("앞선 답: 웹 앱이다", ["파일 (추천)", "DB"]))
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
Expected: FAIL — planner 문서에 `## 인터뷰 체크리스트`·`## 확정 질문`·`## 리뷰 기준(리뷰어가 본다)` 이 없고(`ValueError: substring not found`, 예시 질문 하나), r2 사양에 `--wait <id>` 문장이 없고, `--history` 항목에 `render` 가 없다(`KeyError`).

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
- `.herdr-team/bin/hteam ask-user --task <이 태스크> --history` 로 실제 질문과 답을 본다(읽기만 한다). 항목마다 `render` 가 사용자에게 보인 질문 그대로다(context·선택지). `interview.md` 의 질문 기록이 그것과 맞는다.
- 마지막 질문이 확정 질문이고 답이 `확정 (추천)` 이다. 그 뒤에 다른 질문이 없다.
- 체크리스트 12항목이 모두 `결정`·`자동 결정`·`범위 밖` 이고 근거가 있다. spec.md 가 그 결정을 담는다.
- `tasks.toml` 이 `plan check` 를 통과하고 확정 질문의 `render.context` 에 보인 태스크 그래프 표와 같다.

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

이력에 원래 질문을 더한다(리뷰어가 보인 그대로 확인한다).

**Edit** `herdr-team/lib/hteam/ask.py`

```python
def history(p, tid: str) -> dict:
    acks = _acks(p)
    return {"history": [_item(p, e, acks) for e in _entries(p, tid)]}
```

```python
def history(p, tid: str) -> dict:
    """이 태스크의 모든 질문과 답(이전 라운드 포함). render 는 메인이 사용자에게 보인 질문 그대로다(context·선택지)."""
    acks = _acks(p)
    return {"history": [{**_item(p, e, acks), "render": e["render"]} for e in _entries(p, tid)]}
```

- [ ] **Step 4: 통과 확인**

Run: `bash herdr-team/tests/run.sh -k test_interview -k test_start -k test_mainlink`
Expected: OK(실패 없음). `test_start` 는 수정 블록 문구를 검사하는 기존 테스트를 포함한다.

- [ ] **Step 5: 커밋(구현자는 여기서 멈춘다)**

```bash
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews' || true
git add -- herdr-team/templates/roles/planner.md herdr-team/lib/hteam/compose.py herdr-team/lib/hteam/ask.py \
  herdr-team/tests/test_interview.py
git commit -m "feat(herdr-team): 기획 인터뷰 체크리스트·확정 질문·리뷰 기준, 수정 라운드의 열린 질문 기다리기

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/templates/roles/planner.md \
  herdr-team/lib/hteam/compose.py herdr-team/lib/hteam/ask.py herdr-team/tests/test_interview.py
```

Expected: `git grep` 출력 없음, 커밋 성공. 컨트롤러가 `scripts/codex-review.sh commit HEAD` 를 돌리고 Global Constraints 의 Codex 규칙대로 처리한다.

---
### Task 3: `hteam design-review` — 승인 직무 일괄 승인 묶음

설계 11.4: `awaiting_user` 인 승인 직무 태스크가 하나 이상 있고, 진행 중(`working`·`reviewing`·`approved`·`changes`·`launch_failed`)이거나 지금 바로 시작할 수 있는(사양 통과·의존 충족·잠금 비어 있음) 승인 직무 태스크가 없을 때, 그 순간 `awaiting_user` 인 승인 태스크를 한 묶음으로 outbox 에 `approval` 항목 하나로 쓴다. 승인 → 비승인 → 승인 사슬의 뒤 태스크는 비승인 태스크가 `done` 이어야 시작할 수 있으므로 앞 묶음을 막지 않고 다음 묶음이 된다. `context` 에는 태스크마다 한 줄과 링크(보고서의 마지막 claude.ai URL, design_system_url 은 뺀다)를 넣고 선택지는 "모두 승인 (추천)" / "수정 요청" 이다(사용자 결정). 같은 태스크·라운드를 이미 물었으면 exit 3. 기록은 `state/design-review.json`.

정한 것(설계가 정하지 않은 부분, 이 커밋에서 설계 11.4 에 옮긴다):
- 한 (태스크, 라운드)는 한 번만 묻는다. 이미 물은 태스크가 답을 기다리는 동안 새 태스크가 awaiting_user 가 되면 새 묶음에는 새 태스크만 넣는다. 수정 라운드는 라운드가 달라 다시 묻는다. 링크가 없으면 보고서 경로를 쓴다.
- **stale**: 승인 태스크의 선행(직간접)이 이 태스크의 현재 라운드를 연 뒤에 새 라운드를 열었으면(사용자 수정 요청으로 고쳐졌으면) 이 태스크는 옛 선행을 보고 만든 것이다. 의존 승인 태스크는 일괄 승인 결정(Task 4)이 선행과 함께 고치므로, stale 은 결정 밖에서 선행을 고친 이상한 경우다. 그래서 읽기만 하는 검사 하나로 둔다: stale 인 awaiting_user 태스크가 있으면 묻지 않고 exit 3 `approval_stale`(fix 를 자동으로 권하지 않는다. 메인에 알린다). 기준은 그 라운드의 워커를 새로 띄울 때 본 선행의 라운드(`rounds[i].basis`)다: 선행의 지금 라운드가 그보다 크면 stale 이다. basis 가 없는 옛 라운드는 상태 history 의 그 라운드 `start`·`fix` 시각으로 본다(같은 초면 함께 고친 것).
- **basis 를 쓰는 때**: 시작 예약(`tasks._begin`, 프로젝트 잠금 안. start-ready 는 의존 검사와 같은 잠금)이 그때 본 선행 라운드를 실행 기록 `work.pred_rounds` 에 둔다. `dispatch.launch` 가 기존 horch Task 없이 새로 띄울 때(fresh)만 `launched` 와 같은 저장에서 그것을 라운드의 `basis` 로 옮긴다(`on_fresh`). 그래서 기록 전에 죽어도 `launched` 가 있으면 `basis` 도 있다. 같은 라운드 복구는 `_begin` 을 다시 지나 `pred_rounds` 만 바꾼다: 기존 Dispatch 를 이어 붙이거나(adopt) 같은 horch Task 를 다시 띄우면(retry) `basis` 는 처음 것 그대로다(옛 Dispatch 는 처음 본 선행으로 만들었다. retry 는 그 뒤 선행이 바뀌었으면 stale 로 보는 쪽이 안전하다: 놓치지 않고, 잘못 잡으면 fix 로 다시 만든다). 기록만 있고 뜬 워커가 없어 다시 띄우면(fresh) 새 예약에서 본 라운드가 된다. 띄우는 순간이 아니라 예약 때 읽는 까닭: 예약과 띄우기 사이에 선행이 고쳐지면 새 라운드 번호를 아직 결과가 없는데 본 것으로 적게 된다.
- 상태 파일 하나라도 읽지 못하면 묶음을 잘못 나눌 수 있어 묻지 않는다(exit 1 `bad_state_file`). 기록은 모양을 모두 검사한다(묶음 id·시각·out-id·태스크·라운드·render, 묶음·out-id·태스크 라운드 중복). 어기면 쓰기 전에 exit 1 `bad_side_file`.
- 쓰는 순서는 기록(id 없음) → outbox(묶음 id `batch` 를 붙인다) → 기록의 id 이고 모두 프로젝트 잠금 안이다. 그 사이 죽으면 다음 호출이 새 묶음보다 먼저 마저 쓴다. outbox 에서 같은 `batch` 를 찾는 일은 `outbox.append` 의 잠금 안에서, 마지막 LF 가 빠진 줄을 완결한 뒤에 한다(잠금 밖에서 찾으면 LF 만 빠진 항목을 못 보고 같은 질문을 두 번 쓴다).

**Files:**
- Create: `herdr-team/lib/hteam/approval.py`, `herdr-team/tests/test_approval.py`
- Modify: `herdr-team/lib/hteam/util.py`(`read_json_strict`, `bad_side_file`), `herdr-team/lib/hteam/paths.py`(`Project.design_review`), `herdr-team/lib/hteam/cli.py`(`COMMAND_MODULES`), `herdr-team/lib/hteam/outbox.py`(`append` 의 `reuse`), `herdr-team/lib/hteam/tasks.py`(`_basis`, `_begin` 의 `work.pred_rounds`, `run_work` 의 `on_fresh`), `herdr-team/lib/hteam/dispatch.py`(`launch`·`_run_barrier` 의 `on_fresh`)
- Modify: `docs/superpowers/specs/2026-11-05-herdr-team-design.md`(11.4 의 design-review 문단)

**Interfaces:**
- Consumes: `config.load(p)`, `cfg.is_approval(role)`, `cfg.role_title(role)`, `specs.check(p, cfg, tid)`, `specs.load(p, tid)`(`title`, `role`, `depends_on`), `tasks.deps_met(p, cfg, spec)`, `tasks.checked_owns(cfg, spec)`, `tasks.lock_conflicts(p, tid, owns)`, `tasks._unreadable(p, ids) -> HteamError`, `state.project_lock(p)`, `state.all_states(p)`, `state.unreadable_ids(p)`, `state.ID_RE`, `state.CLOSED`, `outbox.read_outbox(p)`, `outbox.validate_render(obj, header)`, `roles.require_coordinator(p)`, `util.die_at(point)`(모두 기존)
- Produces:
  - `util.read_json_strict(path, default)`: 없으면 `default`, 읽지 못하거나 JSON 이 아니면 `HteamError("bad_side_file", …, 1)`. `util.bad_side_file(path, why) -> HteamError`.
  - `Project.design_review` = `state/design-review.json`.
  - `outbox.append(p, fields, guard=None, reuse=None)`: `reuse(entries)` 가 항목을 돌려주면 쓰지 않고 그것을 돌려준다(같은 잠금 안, 끊긴 마지막 줄을 완결한 뒤).
  - `approval.load(p) -> {"batches": [...]}`(검사, 틀리면 `bad_side_file`), `approval.asked(data) -> {(task, round): out-id | None}`, `approval.Graph(p)`(`deps(tid)`, `role(tid)`, `ancestors(tid)`), `approval.opened(st) -> str | None`, `approval.stale(p, cfg, states, graph=None) -> {task: [선행]}`(basis 우선, 없으면 시각), `tasks._basis(p, tid) -> {선행: 라운드}`, 실행 기록 `work.pred_rounds`(`tasks._begin` 이 시작 예약에서 쓴다)와 라운드 기록 `basis: {선행: 라운드}`(새로 띄울 때만), `dispatch.launch(..., on_fresh=None)`(fresh 일 때만 `on_fresh(st)` 를 `launched` 와 같은 저장에서 부른다), `approval.view(p, cfg, states=None, data=None) -> {"waiting", "blockers": [{"task", "status", "why"}], "fresh", "asked", "stale": [{"task", "round", "because"}]}`, `approval.link(p, tid) -> str`, `approval.render(p, cfg, states) -> render`, `approval.design_review(p) -> {"id", "batch", "tasks": [{"task", "round"}], "resumed", "hint"}`. 상수 `approval.APPROVE = "모두 승인 (추천)"`, `approval.REVISE = "수정 요청"`, `approval.HEADER = "디자인 승인"`.
  - 명령 `hteam design-review`(코디네이터만). 오류: exit 2 `no_approval_roles`, exit 3 `nothing_to_approve`·`approval_stale`(data `stale`)·`already_asked`(data `asked`)·`approval_not_ready`(data `blockers`), exit 1 `bad_side_file`·`bad_state_file`.
  - 테스트 도우미 `tests.test_approval.ApprovalCase`(설정 `APPROVAL`, `task(tid, status, role=, rnd=, depends=, title=)`, `move(tid, status, rnd=)`, `opened(tid, rnd, at)`, `review(**kw)`, `outbox_items()`, `restart_after_predecessor_refix(die_at)`). Task 4 가 쓴다.
  - die_at 지점 `design_review_recorded`(기록 뒤), `design_review_appended`(outbox 항목 뒤).

- [ ] **Step 1: 실패하는 테스트 작성**

**Create** `herdr-team/tests/test_approval.py`

```python
"""사용자 일괄 승인(설계 11.4): design-review 의 묶음·조건·stale·기록·링크·복구."""
import json
import unittest

from tests.helpers import BASE_CONFIG, TeamCase
from hteam import approval, config, dispatch, outbox, roles, state
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
        """상태만 만든다(워커는 띄우지 않는다). designer 는 화면마다, developer 는 태스크마다 owns 를 나눈다. 시작한
        태스크에는 띄운 적 없는 라운드 기록 하나를 둔다(accept·fix 가 라운드 기록을 본다)."""
        owns = f"docs/design/screens/{tid.lower()}/**" if role == "designer" else f"src/{tid.lower()}/**"
        self.write_spec(tid, role, title=title, owns=owns, depends=depends, commit=False)
        state.create(self.p, tid, role)
        if status != "pending":
            with state.edit(self.p, tid) as st:
                rd = {"round": rnd, "round_base": None, "agent": "claude", "model": None, "effort": None, "note": None,
                      "supplement": None, "work": dispatch.new_slot(roles.work_title(tid, rnd)), "reviews": [],
                      "verdict": None}
                st.update(round=rnd, owns=[owns], rounds=[rd])
                state.move(st, status, "test")

    def move(self, tid, status, rnd=None):
        with state.edit(self.p, tid) as st:
            if rnd is not None:
                st["round"] = rnd
            state.move(st, status, "test")

    def opened(self, tid, rnd, at):
        """그 라운드를 연 기록(fix)을 남기고 라운드를 바꾼다. stale 판정이 이 시각을 본다."""
        with state.edit(self.p, tid) as st:
            st["round"] = rnd
            st["history"].append({"at": at, "from": st["status"], "to": st["status"], "event": "fix", "round": rnd})

    def restart_after_predecessor_refix(self, die_at):
        """T-002 가 T-001 r3 을 보고 뜨다가 die_at 에서 실행자가 죽었다. 그 사이 T-001 이 결정 밖에서 r4 로 고쳐져 다시
        승인됐다. T-002 를 다시 start 한 (exit, 출력). after_launch 면 그 전에 워커가 이미 성공으로 끝났다."""
        self.task("T-001", "awaiting_user", rnd=3)
        self.write_spec("T-002", "designer", owns="docs/design/screens/t-002/**", depends="T-001", commit=False)
        state.create(self.p, "T-002", "designer")
        self.assertEqual(self.hteam("start", "T-002", env={"HTEAM_TEST_DIE_AT": die_at})[0], 137)
        rd = self.task_state("T-002")["rounds"][-1]
        self.assertIsNotNone(rd["work"]["launched"])
        self.assertEqual(rd["basis"], {"T-001": 3})  # launched 와 같은 저장에 썼다
        if die_at == "after_launch":
            code, out = self.horch("worker-list")
            self.assertEqual(code, 0, out)
            [row] = out["workers"]
            code, out = self.act(row["id"], {"done": {"outcome": "succeeded", "summary": "r3 을 보고 만들었다"}})
            self.assertEqual(code, 0, out)
        self.move("T-001", "awaiting_user", rnd=4)
        return self.hteam("start", "T-002")

    def review(self, **kw):
        return self.hteam("design-review", **kw)

    def outbox_items(self):
        return outbox.read_outbox(self.p)

    def record(self):
        return json.loads((self.state_dir / "design-review.json").read_text(encoding="utf-8"))


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
        self.assertEqual([(b["batch"], b["id"]) for b in self.record()["batches"]], [("dr-0001", "out-0001")])
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

    def test_task_built_on_an_older_predecessor_is_not_asked(self):
        # T-002 r1 은 T-001 r1 을 보고 만들었다. 그 뒤 사용자 요청으로 T-001 r2 가 열렸다: T-002 도 고쳐야 한다
        self.task("T-001", "awaiting_user")
        self.task("T-002", "awaiting_user", depends="T-001")
        self.opened("T-001", 1, "2026-11-06T09:00:00Z")
        self.opened("T-002", 1, "2026-11-06T10:00:00Z")
        self.opened("T-001", 2, "2026-11-06T10:05:00Z")
        code, out = self.review()
        self.assertEqual((code, out["error"]["code"]), (3, "approval_stale"), out)
        self.assertEqual(out["stale"], [{"task": "T-002", "round": 1, "because": ["T-001"]}])
        self.assertIn("메인에 알린다", out["error"]["hint"])
        self.assertEqual(approval.stale(self.p, config.load(self.p), state.all_states(self.p)), {"T-002": ["T-001"]})
        self.opened("T-002", 2, "2026-11-06T10:05:00Z")  # 선행과 함께(같은 초에) 고쳤다: stale 이 아니다
        code, out = self.review()
        self.assertEqual((code, out.get("tasks")), (0, [{"task": "T-001", "round": 2}, {"task": "T-002", "round": 2}]),
                         out)

    def test_stale_uses_rounds_seen_at_launch(self):
        self.task("T-001", "awaiting_user", rnd=3)
        self.write_spec("T-002", "designer", owns="docs/design/screens/t-002/**", depends="T-001", commit=False)
        state.create(self.p, "T-002", "designer")
        self.assertEqual(self.hteam("start", "T-002")[0], 0)
        self.assertEqual(self.task_state("T-002")["rounds"][-1]["basis"], {"T-001": 3})  # 띄울 때 본 선행 라운드
        self.move("T-002", "awaiting_user")
        self.opened("T-001", 3, "2099-01-01T00:00:00Z")  # 시각만 보면 stale 로 보인다(선행 라운드를 나중에 열었다)
        cfg = config.load(self.p)
        self.assertEqual(approval.stale(self.p, cfg, state.all_states(self.p)), {})
        self.move("T-001", "awaiting_user", rnd=4)  # 띄운 뒤에 선행이 새 라운드를 열었다
        self.assertEqual(approval.stale(self.p, cfg, state.all_states(self.p)), {"T-002": ["T-001"]})

    def test_recovery_that_adopts_keeps_the_launch_basis(self):
        # 같은 라운드 복구가 옛 Dispatch(T-001 r3 을 보고 만든 결과)를 이어 붙인다. 복구가 basis 를 r4 로 덮으면 옛
        # 결과를 최신 선행을 본 것으로 승인하게 된다
        code, out = self.restart_after_predecessor_refix("after_launch")
        self.assertEqual((code, out.get("mode")), (0, "adopt"), out)
        rd = self.task_state("T-002")["rounds"][-1]
        self.assertEqual(rd["basis"], {"T-001": 3})  # 처음 띄울 때 본 선행 그대로다
        self.assertEqual(rd["work"]["pred_rounds"], {"T-001": 4})  # 복구의 시작 예약은 본 것을 적어 두기만 한다
        self.move("T-002", "awaiting_user")
        code, out = self.review()
        self.assertEqual((code, out["error"]["code"]), (3, "approval_stale"), out)
        self.assertEqual(out["stale"], [{"task": "T-002", "round": 1, "because": ["T-001"]}])

    def test_recovery_that_launches_again_records_a_new_basis(self):
        # 시작 바이트를 보내기 전에 죽어 워커가 뜨지 않았다. 다시 띄우는 워커는 T-001 r4 를 본다
        code, out = self.restart_after_predecessor_refix("after_child")
        self.assertEqual((code, out.get("mode")), (0, "fresh"), out)
        self.assertEqual(self.task_state("T-002")["rounds"][-1]["basis"], {"T-001": 4})
        self.move("T-002", "awaiting_user")
        self.assertEqual(approval.stale(self.p, config.load(self.p), state.all_states(self.p)), {})

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
        self.assertEqual([b["id"] for b in self.record()["batches"]], ["out-0001", "out-0002"])

    def test_resume_finds_entry_missing_only_its_last_lf(self):
        # 항목 JSON 은 다 썼는데 마지막 LF 만 못 쓰고 죽었다. 다음 호출은 그 항목을 완결해 쓰고 새로 쓰지 않는다
        self.task("T-001", "awaiting_user")
        code, _ = self.review(env={"HTEAM_TEST_DIE_AT": "design_review_appended"})
        self.assertEqual(code, 137)
        path = self.state_dir / "outbox.jsonl"
        path.write_bytes(path.read_bytes().rstrip(b"\n"))
        code, out = self.review()
        self.assertEqual((code, out.get("id"), out.get("resumed")), (0, "out-0001", True), out)
        self.assertEqual([(e["id"], e["batch"]) for e in self.outbox_items()], [("out-0001", "dr-0001")])
        self.assertEqual(self.record()["batches"][0]["id"], "out-0001")

    def test_corrupt_record_is_kept(self):
        self.task("T-001", "awaiting_user")
        path = self.state_dir / "design-review.json"
        good = {"batch": "dr-0001", "at": "2026-11-06T10:00:00Z", "id": "out-0001",
                "tasks": [{"task": "T-009", "round": 1}], "render": approval.render(self.p, config.load(self.p), [])}
        for broken in ("{broken", {"batches": [{"batch": 1}]}, {"batches": [{**good, "id": None, "render": 42}]},
                       {"batches": [{**good, "id": 7}]}, {"batches": [good, {**good, "batch": "dr-0002", "id": "out-0002"}]},
                       {"batches": [good, {**good, "tasks": [{"task": "T-008", "round": 1}]}]},
                       {"batches": [{**good, "tasks": [{"task": "T-009", "round": 0}]}]}):
            with self.subTest(broken):
                text = broken if isinstance(broken, str) else json.dumps(broken, ensure_ascii=False)
                path.write_text(text, encoding="utf-8")
                code, out = self.review()
                self.assertEqual((code, out["error"]["code"]), (1, "bad_side_file"), out)
                self.assertEqual(path.read_text(encoding="utf-8"), text)  # 덮어쓰지 않았다
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

outbox 의 덧붙이기에 "같은 잠금 안에서 찾아 있으면 쓰지 않는다"를 더한다.

**Edit** `herdr-team/lib/hteam/outbox.py`

```python
def append(p, fields: dict, guard=None) -> dict:
    """outbox 에 flock 으로 한 줄을 더한다. guard(entries) 는 같은 잠금 안에서 먼저 부른다.
```

```python
def append(p, fields: dict, guard=None, reuse=None) -> dict:
    """outbox 에 flock 으로 한 줄을 더한다. guard(entries) 는 같은 잠금 안에서 먼저 부른다. reuse(entries) 가 항목을
    돌려주면 쓰지 않고 그 항목을 돌려준다(이미 쓴 같은 항목. 끊긴 마지막 줄을 완결한 뒤에 보므로 LF 만 빠진 항목도 찾는다).
```

**Edit** `herdr-team/lib/hteam/outbox.py`

```python
        count, items, _ = _parse(raw)
        if guard is not None:
            guard([e for _, e in items])
        entry = {"id": f"out-{count + 1:04d}", "at": now(), **fields, "answered": False}
```

```python
        count, items, _ = _parse(raw)
        entries = [e for _, e in items]
        if guard is not None:
            guard(entries)
        if reuse is not None:
            found = reuse(entries)
            if found is not None:
                return found
        entry = {"id": f"out-{count + 1:04d}", "at": now(), **fields, "answered": False}
```

워커를 새로 띄울 때 본 선행의 라운드를 라운드 기록 `basis` 에 남긴다(stale 의 기준). 시작 예약(`_begin`, 프로젝트 잠금 안)이 그때 본 라운드를 실행 기록 `pred_rounds` 에 두고, `dispatch.launch` 가 새로 띄울 때(fresh)만 `launched` 와 같은 저장에서 `basis` 로 옮긴다. 같은 라운드 복구가 기존 Dispatch 를 이어 붙이거나(adopt) 다시 띄우면(retry) 옮기지 않는다. queued 로 미리 만든 라운드(Task 4)는 start-ready 가 띄울 때 예약을 다시 지나므로 그때 본 라운드가 된다.

**Edit** `herdr-team/lib/hteam/tasks.py`

```python
def _begin(p, st: dict, rd: dict, text: str, event: str, **info) -> None:
    """실행 키·실행자·라운드를 launch_failed 와 함께 먼저 쓴다(설계 5.4 3). 사양 파일도 쓴다."""
    st["launcher"] = {"key": rd["work"]["title"], **procs.me()}
```

```python
def _basis(p, tid: str) -> dict[str, int]:
    """지금 선행(직간접)의 라운드. 승인 태스크의 stale 판단 기준이다(설계 11.4, approval.stale)."""
    from . import approval  # approval 이 tasks 를 쓴다. 불러오는 순서가 꼬이지 않게 여기서 가져온다
    by_id = {s["id"]: s for s in state.all_states(p)}
    return {a: by_id[a]["round"] for a in sorted(approval.Graph(p).ancestors(tid), key=state.id_number) if a in by_id}


def _launch_basis(st: dict) -> None:
    """dispatch.launch 가 워커를 새로 띄울 때(fresh)만 launched 와 같은 저장에서 부른다(on_fresh). 시작 예약에서 본
    선행 라운드가 이 라운드의 basis 다. 기존 Dispatch 를 이어 붙이거나(adopt) 같은 horch Task 를 다시 띄우면(retry)
    부르지 않아 처음 띄울 때 것이 남는다(adopt 한 Dispatch 는 그 선행을 보고 만들었다. retry 는 그 사이 선행이
    바뀌었으면 stale 로 보는 쪽이 안전하다: 놓치지 않고, 잘못 잡으면 fix 로 다시 만든다)."""
    rd = st["rounds"][-1]
    if isinstance(rd["work"].get("pred_rounds"), dict):
        rd["basis"] = rd["work"]["pred_rounds"]


def _begin(p, st: dict, rd: dict, text: str, event: str, **info) -> None:
    """실행 키·실행자·라운드를 launch_failed 와 함께 먼저 쓴다(설계 5.4 3). 사양 파일도 쓴다. 지금 선행의 라운드를
    실행 기록 pred_rounds 에 둔다(프로젝트 잠금 안에서 부른다. start-ready 는 의존 검사와 같은 잠금). 라운드의 basis 는
    워커를 새로 띄울 때만 그것으로 정한다(_launch_basis). 같은 라운드 복구는 여기를 다시 지나도 basis 를 바꾸지 않는다."""
    rd["work"]["pred_rounds"] = _basis(p, st["id"])
    st["launcher"] = {"key": rd["work"]["title"], **procs.me()}
```

**Edit** `herdr-team/lib/hteam/tasks.py`

```python
    rd = state.require(p, tid)["rounds"][-1]
    res = dispatch.launch(p, h, tid, work_slot, agent=rd["agent"], model=rd["model"], effort=rd["effort"],
                          args=cfg.args(rd["agent"]), spec_file=_spec_file(p, tid, rd["round"]),
                          expect={"launch_failed"})
```

```python
    rd = state.require(p, tid)["rounds"][-1]
    res = dispatch.launch(p, h, tid, work_slot, agent=rd["agent"], model=rd["model"], effort=rd["effort"],
                          args=cfg.args(rd["agent"]), spec_file=_spec_file(p, tid, rd["round"]),
                          expect={"launch_failed"}, on_fresh=_launch_basis)
```

새로 띄울 때만 호출자의 기록을 `launched` 와 같은 저장에 더한다. 리뷰 Dispatch(`review.py`)는 넘기지 않는다.

**Edit** `herdr-team/lib/hteam/dispatch.py`

```python
def _run_barrier(p, tid: str, pick, argv: list[str], expect) -> tuple[int, dict]:
    barrier = Barrier(argv)
    try:
        # 기록을 저장한 직후 같은 태스크 잠금 안에서 시작 바이트를 보낸다. 그래서 fix·drop 의 취소는 기록 전(그러면
        # 위 검사가 막는다)이나 바이트 뒤(horch 가 떴다. 기록·working 전이가 막는다)에만 저장된다
        with owned(p, tid, pick, expect, after_save=_send(barrier)) as st:
            pick(st)["launched"] = barrier.record()
```

```python
def _run_barrier(p, tid: str, pick, argv: list[str], expect, on_fresh=None) -> tuple[int, dict]:
    barrier = Barrier(argv)
    try:
        # 기록을 저장한 직후 같은 태스크 잠금 안에서 시작 바이트를 보낸다. 그래서 fix·drop 의 취소는 기록 전(그러면
        # 위 검사가 막는다)이나 바이트 뒤(horch 가 떴다. 기록·working 전이가 막는다)에만 저장된다
        with owned(p, tid, pick, expect, after_save=_send(barrier)) as st:
            pick(st)["launched"] = barrier.record()
            if on_fresh is not None:  # 새로 띄우는 실행이 본 것을 launched 와 같은 저장에 남긴다
                on_fresh(st)
```

**Edit** `herdr-team/lib/hteam/dispatch.py`

```python
           spec_file, expect=None) -> dict:
    """pick(st) 가 가리키는 실행 기록으로 horch 워커를 띄우거나 이어 붙인다. 실패하면 HteamError(launch_failed).

    기록을 쓸 때마다 owned 로 이전 상태(expect)·취소·실행자를 다시 확인한다. 어긋나면 exit 3(launch_canceled 등)."""
```

```python
           spec_file, expect=None, on_fresh=None) -> dict:
    """pick(st) 가 가리키는 실행 기록으로 horch 워커를 띄우거나 이어 붙인다. 실패하면 HteamError(launch_failed).

    기록을 쓸 때마다 owned 로 이전 상태(expect)·취소·실행자를 다시 확인한다. 어긋나면 exit 3(launch_canceled 등).
    on_fresh(st) 는 기존 horch Task 없이 새로 띄울 때(fresh)만 launched 와 같은 저장에서 부른다. 이어 붙이거나(adopt)
    같은 horch Task 를 다시 띄우면(retry) 부르지 않는다."""
```

**Edit** `herdr-team/lib/hteam/dispatch.py`

```python
    code, data = _run_barrier(p, tid, pick, argv, expect)
```

```python
    code, data = _run_barrier(p, tid, pick, argv, expect, on_fresh if mode == "fresh" else None)
```

**Create** `herdr-team/lib/hteam/approval.py`

```python
"""사용자 일괄 승인(설계 11.4): `hteam design-review`.

승인 직무(user_approval_roles) 태스크는 리뷰 승인 뒤 accept 로 awaiting_user 가 된다. 진행 중(working·reviewing·
approved·changes·launch_failed)이거나 지금 바로 시작할 수 있는(사양 통과·의존 충족·잠금 비어 있음) 승인 직무 태스크가
없을 때, 그 순간 awaiting_user 인 승인 태스크 가운데 아직 묻지 않은 (태스크, 라운드) 전부를 outbox 의 approval 항목
하나로 묻는다. 승인 → 비승인 → 승인 사슬의 뒤 태스크는 비승인 태스크가 done 이어야 시작할 수 있으므로 앞 묶음을 막지
않고 다음 묶음이 된다.

stale: 승인 태스크의 선행(직간접)이 이 태스크의 현재 라운드를 연 뒤에 새 라운드를 열었으면 이 태스크는 옛 선행을 보고
만든 것이다. 일괄 승인 결정(decide)은 의존 승인 태스크를 선행과 함께 고치므로 stale 은 결정 밖에서 선행을 고친 경우뿐이다.
읽기만 하는 검사다: stale 인 awaiting_user 태스크는 묻지 않고(approval_stale) accept 가 받지 않는다. 기준은 그 라운드의
워커를 새로 띄울 때 본 선행 라운드(basis. 같은 라운드 복구가 기존 Dispatch 를 이어 붙이면 그대로 둔다)이고, 없으면
history 의 그 라운드 start·fix 시각이다.

기록 `state/design-review.json` = {"batches": [{"batch": "dr-0001", "at", "id": "out-NNNN" | null, "render",
"tasks": [{"task", "round"}]}]}. 한 (태스크, 라운드)는 한 번만 묻는다(수정 라운드는 라운드가 달라 다시 묻는다).
쓰는 순서: 기록(id 없음) → outbox 항목(batch 를 붙인다) → 기록의 id. 모두 프로젝트 잠금 안에서 한다. 그 사이 죽으면
다음 호출이 새 묶음보다 먼저 outbox 에서 같은 batch 를 찾아 id 를 채우거나, 없으면 저장한 render 로 마저 쓴다(같은
묶음을 두 번 묻지 않는다). 기록을 읽지 못하거나 모양이 틀리면 덮어쓰지 않고 exit 1 이다.
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
BATCH_RE = re.compile(r"dr-\d{4,}")
OUT_RE = re.compile(r"out-\d{4,}")
CONTEXT_MAX = 4000
TITLE_MAX = 60
HEADER = "디자인 승인"
APPROVE = "모두 승인 (추천)"
REVISE = "수정 요청"


def _task_ok(t) -> bool:
    return (isinstance(t, dict) and isinstance(t.get("task"), str) and state.ID_RE.fullmatch(t["task"]) is not None
            and isinstance(t.get("round"), int) and not isinstance(t["round"], bool) and t["round"] >= 1)


def _problem(b) -> str | None:
    """묶음 기록 하나의 모양 문제(없으면 None)."""
    if not isinstance(b, dict):
        return "묶음이 객체가 아니다"
    if not isinstance(b.get("batch"), str) or not BATCH_RE.fullmatch(b["batch"]):
        return f"batch 가 dr-NNNN 이 아니다: {b.get('batch')!r}"
    if not isinstance(b.get("at"), str):
        return f"{b['batch']}: at 이 없다"
    if b.get("id") is not None and not (isinstance(b["id"], str) and OUT_RE.fullmatch(b["id"])):
        return f"{b['batch']}: id 가 out-NNNN 이나 null 이 아니다: {b['id']!r}"
    if not isinstance(b.get("tasks"), list) or not b["tasks"] or not all(_task_ok(t) for t in b["tasks"]):
        return f"{b['batch']}: tasks 가 [{{task, round}}] 가 아니다"
    try:
        outbox.validate_render(b.get("render"), HEADER)
    except HteamError as exc:
        return f"{b['batch']}: render 가 질문 형식이 아니다({exc.message})"
    return None


def load(p) -> dict:
    """design-review.json. 없으면 빈 기록. 읽지 못하거나 모양이 틀리면(필수 필드·타입, 묶음·out-id·태스크 라운드 중복)
    bad_side_file 이다(덮어쓰지 않는다. 그 기록으로 outbox 에 쓰지도 않는다)."""
    data = read_json_strict(p.design_review, {"batches": []})
    if not isinstance(data, dict) or not isinstance(data.get("batches"), list):
        raise bad_side_file(p.design_review, "batches 목록이 아니다")
    batches, ids, keys = set(), set(), set()
    for b in data["batches"]:
        why = _problem(b)
        if why is None:
            mine = {(t["task"], t["round"]) for t in b["tasks"]}
            if b["batch"] in batches:
                why = f"{b['batch']} 가 두 번 나온다"
            elif b.get("id") is not None and b["id"] in ids:
                why = f"{b['id']} 가 두 묶음에 있다"
            elif len(mine) != len(b["tasks"]) or mine & keys:
                why = f"{b['batch']}: 같은 태스크·라운드를 두 번 물었다"
            keys |= mine
        if why:
            raise bad_side_file(p.design_review, why)
        batches.add(b["batch"])
        if b.get("id") is not None:
            ids.add(b["id"])
    return data


def asked(data: dict) -> dict[tuple[str, int], str | None]:
    """이미 물은 (태스크, 라운드) → 그 묶음의 out-id(쓰다 멈췄으면 None)."""
    return {(t["task"], t["round"]): b.get("id") for b in data["batches"] for t in b["tasks"]}


class Graph:
    """사양의 depends_on 으로 본 태스크 그래프(읽기만). 사양을 읽지 못하는 태스크는 의존이 없고 직무를 모르는 것으로 본다."""

    def __init__(self, p):
        self.p = p
        self._deps: dict[str, list[str]] = {}
        self._roles: dict[str, str | None] = {}

    def deps(self, tid: str) -> list[str]:
        if tid not in self._deps:
            try:
                spec = specs.load(self.p, tid)
                self._deps[tid], self._roles[tid] = list(spec.depends_on), spec.role
            except HteamError:
                self._deps[tid], self._roles[tid] = [], None
        return self._deps[tid]

    def role(self, tid: str) -> str | None:
        self.deps(tid)
        return self._roles[tid]

    def ancestors(self, tid: str) -> set[str]:
        """직간접 선행(순환이 있어도 끝난다)."""
        seen: set[str] = set()
        todo = list(self.deps(tid))
        while todo:
            d = todo.pop()
            if d != tid and d not in seen:
                seen.add(d)
                todo += self.deps(d)
        return seen


def opened(st: dict) -> str | None:
    """현재 라운드를 연 시각(그 라운드의 가장 이른 start·fix 기록). 없으면 None(stale 을 판단하지 않는다)."""
    times = [h["at"] for h in st.get("history") or [] if isinstance(h, dict) and h.get("event") in ("start", "fix")
             and h.get("round") == st.get("round") and isinstance(h.get("at"), str)]
    return min(times) if times else None


def stale(p, cfg, states: list[dict], graph: Graph | None = None) -> dict[str, list[str]]:
    """{승인 태스크: [이 태스크의 현재 라운드를 띄운 뒤에 새 라운드를 연 선행]}. 끝난 태스크는 보지 않는다.

    기준은 그 라운드의 워커를 새로 띄울 때 본 선행의 라운드(`basis`, tasks._launch_basis)다: 선행의 지금 라운드가 그보다
    크면 stale 이다. 미리 만들어 둔(queued) 라운드는 실제로 띄울 때 기록하므로, 기다리는 동안 선행이 리뷰에서 한 번 더
    고쳐져도 그 최신 선행을 보고 만든 결과는 stale 이 아니다. 같은 라운드 복구가 옛 Dispatch 를 이어 붙이면 basis 는
    처음 것 그대로라 그 사이 고쳐진 선행을 놓치지 않는다. basis 가 없는 라운드(옛 기록)는 라운드를 연 시각으로
    본다(시각이 같으면 함께 고친 것이라 stale 이 아니다)."""
    graph = graph or Graph(p)
    by_id = {s["id"]: s for s in states}
    found: dict[str, list[str]] = {}
    for st in states:
        if st["status"] in state.CLOSED or not cfg.is_approval(st.get("role")):
            continue
        basis = (state.current_round(st) or {}).get("basis")
        if isinstance(basis, dict):
            newer = sorted(a for a in graph.ancestors(st["id"])
                           if a in by_id and isinstance(basis.get(a), int) and by_id[a]["round"] > basis[a])
        else:
            mine = opened(st)
            if mine is None:
                continue
            newer = sorted(a for a in graph.ancestors(st["id"])
                           if a in by_id and (o := opened(by_id[a])) is not None and o > mine)
        if newer:
            found[st["id"]] = newer
    return found


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
    stale: waiting 가운데 선행이 그 뒤에 고쳐진 것({task, round, because}), fresh: waiting 가운데 stale 이 아니고 아직 묻지
    않은 것, asked: 물은 (태스크, 라운드) → out-id. 상태는 읽기만 한다."""
    states = state.all_states(p) if states is None else states
    data = load(p) if data is None else data
    done = asked(data)
    behind = stale(p, cfg, states)
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
    late = [{"task": st["id"], "round": st["round"], "because": behind[st["id"]]} for st in waiting if st["id"] in behind]
    fresh = [st for st in waiting if st["id"] not in behind and (st["id"], st["round"]) not in done]
    return {"waiting": waiting, "blockers": blockers, "stale": late, "fresh": fresh, "asked": done}


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
    """기록한 묶음 b 를 outbox 에 쓰고 기록에 id 를 적는다. 같은 batch 항목이 이미 있으면(앞 호출이 쓰고 죽음) 그것을
    쓴다. 찾기와 쓰기는 outbox 잠금 안에서 한다(append 의 reuse)."""
    def mine(entries: list[dict]) -> dict | None:
        return next((e for e in entries if e.get("type") == "approval" and e.get("batch") == b["batch"]), None)

    entry = outbox.append(p, {"type": "approval", "render": b["render"], "from": "coordinator", "batch": b["batch"]},
                          reuse=mine)
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
        if v["stale"]:  # 읽기만 한다. 일괄 승인 결정은 의존 태스크를 함께 고치므로 이것은 결정 밖에서 선행을 고친 경우다
            names = ", ".join(f"{s['task']} r{s['round']}(선행 {', '.join(s['because'])})" for s in v["stale"])
            raise HteamError("approval_stale", f"선행이 그 뒤에 고쳐져 옛 선행을 보고 만든 승인 태스크는 묻지 않는다: {names}",
                             CONFLICT, "메인에 알린다. 사용자가 정하면 그 태스크를 `hteam fix T --note=…` 로 다시 만든 뒤 "
                             "design-review 를 다시 부른다", data={"stale": v["stale"]})
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

설계 11.4 에 이 태스크가 정한 것을 옮긴다(같은 커밋).

**Edit** `docs/superpowers/specs/2026-11-05-herdr-team-design.md`

```markdown
같은 태스크·라운드 묶음을 이미 물었으면 exit 3. 기록은 `state/design-review.json`.
```

```markdown
같은 태스크·라운드 묶음을 이미 물었으면 exit 3. 기록은 `state/design-review.json`. 한 (태스크, 라운드)는 한 번만 묻는다: 이미 물은 태스크가 답을 기다리는 동안 새로 awaiting_user 가 된 태스크는 다음 묶음이 되고, 수정 라운드는 라운드가 달라 다시 묻는다. 링크가 없으면 보고서 경로를 보인다. 선택지 label 은 render 규칙(7.4)대로 `모두 승인 (추천)` / `수정 요청` 이다. 묶음 기록을 먼저 쓰고 outbox 항목에 묶음 id 를 붙인다. 그 사이 죽으면 다음 호출이 그 묶음을 마저 쓴다(같은 묶음을 찾는 일은 outbox 잠금 안에서 한다. 두 번 묻지 않는다). 선행(직간접)이 그 태스크의 현재 라운드를 연 뒤에 새 라운드를 열었으면 그 태스크는 stale 이다: 옛 선행을 보고 만들었으므로 묻지 않는다(exit 3 `approval_stale`, 읽기만 하는 검사. 기준은 그 라운드의 워커를 새로 띄울 때 본 선행 라운드, 없으면 라운드를 연 시각. 시작 예약이 프로젝트 잠금 안에서 본 라운드를 기존 horch Task 없이 새로 띄울 때만 launched 와 같은 저장에 남긴다. 같은 라운드 복구가 기존 Dispatch 를 이어 붙이거나 다시 띄우면 처음 기록을 그대로 둔다). 일괄 승인 결정이 의존 태스크를 함께 고치므로 이것은 결정 밖에서 선행을 고친 경우다.
```

- [ ] **Step 4: 통과 확인**

Run: `bash herdr-team/tests/run.sh -k test_approval -k test_cli -k test_mainlink -k test_start -k test_review -k test_lifecycle`
Expected: OK(실패 없음). `test_mainlink` 는 `outbox.append` 의 기존 동작(ID·LF 복구·guard)을 검사한다. `test_start`·`test_review`·`test_lifecycle` 은 `dispatch.launch` 의 기존 fresh·adopt·retry 복구를 검사한다(`on_fresh` 를 넘기지 않는 리뷰 Dispatch 포함).

- [ ] **Step 5: 커밋(구현자는 여기서 멈춘다)**

```bash
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews' || true
git add -- herdr-team/lib/hteam/approval.py herdr-team/lib/hteam/util.py herdr-team/lib/hteam/paths.py \
  herdr-team/lib/hteam/cli.py herdr-team/lib/hteam/outbox.py herdr-team/lib/hteam/tasks.py herdr-team/lib/hteam/dispatch.py \
  herdr-team/tests/test_approval.py docs/superpowers/specs/2026-11-05-herdr-team-design.md
git commit -m "feat(herdr-team): design-review 로 승인 직무 태스크를 한 번에 묻는다(stale 은 묻지 않는다)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/lib/hteam/approval.py herdr-team/lib/hteam/util.py \
  herdr-team/lib/hteam/paths.py herdr-team/lib/hteam/cli.py herdr-team/lib/hteam/outbox.py herdr-team/lib/hteam/tasks.py \
  herdr-team/lib/hteam/dispatch.py herdr-team/tests/test_approval.py docs/superpowers/specs/2026-11-05-herdr-team-design.md
```

Expected: `git grep` 출력 없음, 커밋 성공. 컨트롤러가 `scripts/codex-review.sh commit HEAD` 를 돌리고 Global Constraints 의 Codex 규칙대로 처리한다.

---
### Task 4: 승인 흐름 연결 — 일괄 승인 결정 기록, accept·status·wait, 사용자 수정 라운드, 문서

설계 11.4·6.4·7.4·13장: 승인 직무 태스크를 accept 하면 `awaiting_user` 가 되고 다음 명령이 `design-review` 다. 일괄 승인 질문의 답은 코디네이터가 해석한다(사용자 결정): 이름이 나온 태스크는 그 요청으로 고치고, 이름이 없는 태스크는 승인하고, 고칠 태스크에 의존하는 승인 태스크도 고친다.

다시 온 답·재시작에서 일을 두 번 하거나 빠뜨리지 않게(Codex 계획 리뷰 r1·r2), 답 처리는 **결정 기록 하나를 한 번 쓰고 그대로 다시 하는 방식**이다:
- 코디네이터가 해석한 것을 `hteam design-review --decide <out-id> --json -` 에 넘긴다: `{"fix": {"T-xxx": "<사용자 요청 원문>"}}`(모두 승인이면 `{"fix": {}}`).
- hteam 이 프로젝트 잠금 안에서 결정을 한 번 계산해 그 묶음 기록(`state/design-review.json` 의 `decision`)에 **먼저** 쓴다: 고칠 태스크(지목된 묶음 태스크와 그것에 직간접으로 의존하는 승인 태스크 전부, 다른 묶음 포함)마다 **그때의 라운드**와 사용자 요청, 승인할 태스크(묶음의 나머지)마다 그때의 라운드. 아직 시작하지 않은 의존 태스크(pending)는 고칠 것이 없고(선행이 다시 승인된 뒤에 시작한다), 끝난 태스크(done·dropped)는 고칠 수 없어 `skipped` 로 남긴다.
- 그다음 기록대로 `fix --round <기록한 라운드>`·`accept --round <기록한 라운드>` 를 한다. 수정 라운드는 바로 띄우지 않는다(`launch_failed`, `queued`). 그래서 `start-ready` 의 의존 검사(승인 직무 선행은 awaiting_user·done 이어야 끝난 것, `tasks.deps_met`)가 의존 태스크를 선행의 수정 라운드가 다시 승인될 때까지 기다리게 한다. `status` 는 queued 라운드의 next 를 `start-ready` 로 준다(`start T` 는 의존을 보지 않으므로 권하지 않는다).
- 다시 부르면(재시작·다시 온 답, 입력 없이) 기록대로 이어 한다. 기록한 라운드가 이미 지난 항목은 한 것이다(`round_changed`·`task_closed`). 사용자 요청은 기록에 있으므로 잃지 않는다. 끝나면 hteam 이 `applied` 를 적는다.
- 결정이 끝나지 않은 동안에는 다른 묶음의 결정과 새 질문을 하지 않는다(exit 3 `decision_pending`). `status` 는 그 결정의 항목 태스크마다 next 를 `design-review --decide <out-id>` 로 준다(일반 fix 를 권하지 않는다).
- 시작 직전 다시 본다(Codex 계획 리뷰 r3): `start`·`start-ready` 는 프로젝트 잠금 안의 시작 예약에서 끝나지 않은 결정이 고치는 태스크와 그것에 의존하는 태스크를 띄우지 않고(`decision_pending`, start-ready 의 대기 사유 `decision`. 결정을 기록한 뒤 선행을 고치기 전 구간 포함), `start-ready` 는 의존도 다시 본다(잠금 밖에서 의존을 본 뒤 결정이 선행을 고쳤을 수 있다. 대기 사유 `deps`). 결정 밖의 일반 `fix` 도 끝나지 않은 결정이 고치는 태스크는 띄우지 않는다.
- 다른 답의 새 요청을 버리지 않는다(r3): 지목된 태스크의 라운드가 다른 결정 때문에 이미 바뀌었으면(의존 태스크로 함께 고쳐졌다) 처리한 것으로 넘기지 않고 지금 라운드에서 그 요청으로 다시 고친다(그 라운드가 사용자 요청 라운드면 그 요청도 이어 적는다). 지목된 태스크가 끝났으면(done·dropped) 아무것도 쓰지 않고 exit 3 `decision_conflict`(메인에 알린다. applied 하지 않는다).
- `accept` 의 stale 검사(Task 3, 읽기만)는 마지막 전이 때 프로젝트 → 태스크 잠금 아래에서 한다(선행의 새 라운드는 fix 가 프로젝트 잠금 안에서 쓴다).
- `wait` 는 답에 `design_review`(묶음, `approve_all`, `decision` 상태, 묶음 태스크의 `pending`, 상태를 읽지 못한 `unknown`)를 붙이고, 한 Delivery 안의 같은 out-id 는 뒤의 것을 `duplicate: true` 로 표시한다.

정한 것: `approve_all` 은 답이 정확히 `모두 승인 (추천)` 일 때만 참이다(코디네이터 안내용). 결정에 done 을 쓴 뒤 applied 전에 죽었으면 다시 온 답의 안내가 `--decide` 재호출이다(applied 만 적는다). 결정 입력의 태스크는 그 묶음의 태스크여야 한다. 이미 기록된 결정에 새 입력을 주면 쓰지 않고 경고한다. 결정으로 고치는 의존 태스크는 진행 중(working·launch_failed·changes·reviewing·approved)이어도 수정 라운드로 돌리고, 라운드 상한은 보지 않는다(사용자 요청에서 나온 수정이다). 메인은 사용자가 `수정 요청` 을 고르면 무엇을 고칠지 대화로 물은 뒤 `수정 요청: <내용>` 한 줄로 답한다. 이 커밋에서 설계 6.4·7.4·11.4 를 맞춘다.

**Files:**
- Modify: `herdr-team/lib/hteam/tasks.py`(`_expect_round`, `_refuse_stale`, `accept`, `fix`, CLI `--round`), `herdr-team/lib/hteam/compose.py`(수정 블록), `herdr-team/lib/hteam/approval.py`(결정: `decide`·`_compute`·`_apply`·검사, `view` 의 `replay`, `design_review` 의 `decision_pending`, `reply_view`, `reply_hint`, CLI `--decide`), `herdr-team/lib/hteam/coord.py`(`_once`, `_annotate_main`, `_design_review`, `annotate`, `wait`, `next_step`, `_awaiting`, `status`)
- Modify: `herdr-team/templates/coordinator.md`, `herdr-team/templates/CLAUDE.section.md`, `docs/superpowers/specs/2026-11-05-herdr-team-design.md`(6.4, 7.4, 11.4)
- Test: `herdr-team/tests/test_approval.py`(`ApprovalReplyTest`, `ApprovalDecisionTest`, `ApprovalFlowTest`, `ApprovalDocsTest`)

**Interfaces:**
- Consumes: Task 3 의 `approval.load`, `approval.view`, `approval.stale`, `approval.Graph`, `approval._task_ok`, `approval.APPROVE`, `tests.test_approval.ApprovalCase`(`task`·`opened`·`review`·`record`·`restart_after_predecessor_refix`). 기존 `tasks.deps_met`, `specs.list_ids(p)`, `state.load`, `state.all_states`, `state.unreadable_ids`, `state.id_number`, `outbox.mark_applied(p, oid)`.
- Produces:
  - `hteam accept T [--round N]`, `hteam fix T … [--round N]`: 지금 라운드가 N 이 아니면 exit 3 `round_changed`(data `round`). `tasks.accept(p, tid, expect_round=None)`: awaiting_user 인 승인 태스크가 stale 이면 마지막 전이에서 exit 3 `approval_stale`(data `because`). die_at 지점 `accept_before_final`.
  - `tasks.fix(..., expect_round=None, queue=False, from_user=None, extra_from=())`: `queue` 면 새 라운드를 쓰고 띄우지 않는다(`launch_failed`, 라운드 기록 `queued: true`, 결과 `{"task", "round", "status": "launch_failed", "queued": true, "next": [".herdr-team/bin/hteam", "start-ready"]}`). `from_user` 가 None 이면 awaiting_user 에서 연 라운드일 때 `from_user: true`. `extra_from` 은 FIX_FROM 밖에서 더 받을 상태.
  - `accept` 결과: awaiting_user 로 갔으면 `"next": [".herdr-team/bin/hteam", "design-review"]` 와 `hint`.
  - 사양 수정 블록 문장 `사용자가 일괄 승인에서 수정을 요청했다(이전 리뷰는 승인이었다).` 와 `사용자 요청: <note>`(아니면 `코디네이터 메모: <note>`).
  - `hteam design-review --decide OUT_ID [--json -]` → `approval.decide(p, oid, text)`: `{"id", "batch", "decision", "replayed", "fixed": [{"task", "round"}], "accepted": [태스크], "passed": [이미 한 항목], "skipped", "warnings", "next": [".herdr-team/bin/hteam", "start-ready"], "hint"}`. 오류: exit 2 `unknown_batch`·`bad_decision`·`usage`(결정이 없는데 입력 없음), exit 3 `decision_pending`(data `pending`)·`decision_conflict`(data `closed`)·`approval_stale`, exit 1 `bad_state_file`. die_at 지점 `decision_recorded`(기록 뒤), `decision_after_fix`(fix 항목마다), `decision_done`(done 뒤 applied 전).
  - `approval.held_by_decision(p, tid) -> out-id | None`: 끝나지 않은 결정이 고치는 태스크이거나 그 의존 태스크. `tasks._start_gate(p, cfg, spec, check_deps)`: 시작 예약(`_prepare_start`)과 결정 밖 `fix` 가 부른다(exit 3 `decision_pending`·`deps_unmet`). start-ready 대기 사유 `decision`·`deps`. die_at 지점 `start_ready_checked`(start-ready 가 의존을 본 뒤 시작 전).
  - 기록의 `decision` = `{"at", "input": {태스크: 요청}, "fix": [{"task", "round", "note", "because": [선행 지목 태스크]}], "accept": [{"task", "round"}], "skipped": [{"task", "why"}], "done": null | 시각}`.
  - `approval.view` 결과에 `replay`(끝나지 않은 결정의 항목 태스크 → out-id). `design-review`(묻기)는 끝나지 않은 결정이 있으면 exit 3 `decision_pending`.
  - `approval.reply_view(p, oid, answer, states=None) -> {"batch", "approve_all", "decision": None | "recorded" | "done", "applied", "unknown", "tasks": [{"task", "round", "status", "round_now", "pending"}]} | None`, `approval.reply_hint(view, oid) -> str`.
  - `coord.next_step(..., appr=None)`: 결정 항목이면 `design-review --decide <out-id>`, queued 라운드면 `start-ready`, awaiting_user 는 `appr` 로. `coord.annotate` 의 `[main] reply` 주석에 `design_review`. `wait` 는 한 Delivery 안의 같은 `reply_to` 뒤 메시지를 `duplicate: true` 로.

- [ ] **Step 1: 실패하는 테스트 작성**

**Edit** `herdr-team/tests/test_approval.py`

```python
import json
import unittest

from tests.helpers import BASE_CONFIG, TeamCase
```

```python
import json
import time
import unittest
from pathlib import Path

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


class DecisionCase(ApprovalCase):
    def decide(self, oid, fix=None, **kw):
        """design-review --decide. fix 가 None 이면 입력 없이(기록대로 다시 한다)."""
        args = ["design-review", "--decide", oid] + ([] if fix is None else ["--json", "-"])
        stdin = None if fix is None else json.dumps({"fix": fix}, ensure_ascii=False)
        return self.hteam(*args, stdin=stdin, **kw)

    def rounds(self, *tids):
        return [(t, self.task_state(t)["status"], self.task_state(t)["round"]) for t in tids]


class ApprovalReplyTest(DecisionCase):
    def test_unreadable_task_state_is_not_treated_as_done(self):
        self.task("T-001", "awaiting_user")
        self.assertEqual(self.review()[0], 0)
        (self.state_dir / "tasks" / "T-001.json").write_text("{", encoding="utf-8")
        view = approval.reply_view(self.p, "out-0001", "모두 승인 (추천)")
        self.assertEqual((view["unknown"], view["tasks"][0]["pending"], view["decision"]), (["T-001"], False, None))
        hint = approval.reply_hint(view, "out-0001")
        self.assertIn("결정하지 않는다", hint)
        self.assertIsNone(approval.reply_view(self.p, "out-0009", "x"))  # 일괄 승인 질문이 아니다
        code, out = self.decide("out-0001", {})  # 결정도 상태를 읽지 못하면 하지 않는다
        self.assertEqual((code, out["error"]["code"]), (1, "bad_state_file"), out)
        self.assertNotIn("decision", self.record()["batches"][0])


class ApprovalDecisionTest(DecisionCase):
    """일괄 승인 결정: 한 번 기록하고 기록대로 다시 한다(설계 11.4)."""

    def cross_batches(self):
        """첫 묶음 T-001·T-002, 둘째 묶음 T-003(T-001 에 의존). 첫 답이 T-001 을 고치면 T-003 도 함께 고친다."""
        self.task("T-001", "awaiting_user")
        self.task("T-002", "awaiting_user")
        self.assertEqual(self.review()[1].get("id"), "out-0001")
        self.task("T-003", "awaiting_user", depends="T-001")  # T-001 의 답을 기다리는 동안 따로 둘째 묶음에 들어갔다
        self.assertEqual(self.review()[1].get("id"), "out-0002")
        self.task("T-004", "pending", depends="T-001")  # 아직 시작하지 않았다: 선행이 다시 승인된 뒤에 시작한다
        code, out = self.decide("out-0001", {"T-001": "버튼을 크게"})
        self.assertEqual(code, 0, out)
        return out

    def test_decision_fixes_named_tasks_and_their_dependents_in_other_batches(self):
        d = self.cross_batches()["decision"]
        self.assertEqual([(e["task"], e["round"], e["note"]) for e in d["fix"]],
                         [("T-001", 1, "버튼을 크게"), ("T-003", 1, "선행 T-001 의 사용자 요청을 반영한다: 버튼을 크게")])
        self.assertEqual(d["accept"], [{"task": "T-002", "round": 1}])
        self.assertEqual([s["task"] for s in d["skipped"]], ["T-004"])
        self.assertEqual(self.rounds("T-001", "T-002", "T-003"),
                         [("T-001", "launch_failed", 2), ("T-002", "done", 1), ("T-003", "launch_failed", 2)])
        self.assertTrue(self.task_state("T-003")["rounds"][-1]["queued"])
        work = (self.state_dir / "tasks/T-003/r2-work.md").read_text(encoding="utf-8")
        self.assertIn("사용자 요청: 선행 T-001 의 사용자 요청을 반영한다: 버튼을 크게", work)
        self.assertIn("out-0001", json.loads((self.state_dir / "applied.json").read_text(encoding="utf-8")))
        tasks_ = {t["id"]: t for t in self.hteam("status")[1]["tasks"]}
        self.assertEqual(tasks_["T-003"]["next"], [H, "start-ready"])  # start T 는 의존을 보지 않으므로 권하지 않는다
        # 둘째 묶음의 답(모두 승인)이 와도 이미 고친 T-003 을 승인하지 않는다
        code, out = self.decide("out-0002", {})
        self.assertEqual((code, out["decision"]["accept"]), (0, []), out)
        # 첫 답이 다시 와도 기록한 라운드가 지나 아무것도 다시 하지 않는다(T-003 은 r3 가 되지 않는다)
        code, out = self.decide("out-0001")
        self.assertEqual((code, out["replayed"]), (0, True), out)
        self.assertEqual(self.rounds("T-001", "T-003"), [("T-001", "launch_failed", 2), ("T-003", "launch_failed", 2)])

    def test_separate_request_for_a_task_another_decision_reopened_is_kept(self):
        # 둘째 묶음의 답이 T-003 에 따로 수정을 요청했다. T-003 은 첫 결정이 이미 r2 로 만들었지만 이 요청을 버리지 않는다
        self.cross_batches()
        code, out = self.decide("out-0002", {"T-003": "글꼴을 바꾼다"})
        self.assertEqual(code, 0, out)
        [entry] = out["decision"]["fix"]
        self.assertEqual((entry["task"], entry["round"]), ("T-003", 2))
        self.assertEqual(entry["note"], "글꼴을 바꾼다 / 이전 요청도 그대로 반영한다: 선행 T-001 의 사용자 요청을 반영한다: 버튼을 크게")
        self.assertEqual(self.rounds("T-003"), [("T-003", "launch_failed", 3)])
        work = (self.state_dir / "tasks/T-003/r3-work.md").read_text(encoding="utf-8")
        self.assertIn("글꼴을 바꾼다", work)
        self.assertIn("버튼을 크게", work)
        self.assertIn("out-0002", json.loads((self.state_dir / "applied.json").read_text(encoding="utf-8")))
        for oid in ("out-0001", "out-0002"):  # 어느 답이 다시 와도 r4 가 열리지 않는다
            self.assertEqual(self.decide(oid)[0], 0)
        self.assertEqual(self.rounds("T-003"), [("T-003", "launch_failed", 3)])

    def test_request_for_a_finished_task_is_a_conflict(self):
        self.task("T-001", "awaiting_user")
        self.review()
        self.move("T-001", "dropped")
        code, out = self.decide("out-0001", {"T-001": "x"})
        self.assertEqual((code, out["error"]["code"], out.get("closed")), (3, "decision_conflict", ["T-001"]), out)
        self.assertNotIn("decision", self.record()["batches"][0])
        self.assertFalse((self.state_dir / "applied.json").exists())

    def test_crash_and_replay_keep_every_request(self):
        # T-002 는 T-001 에 의존한다. 사용자는 둘 다 고치라고 했다(T-001 버튼, T-002 글꼴)
        self.task("T-001", "awaiting_user")
        self.task("T-002", "awaiting_user", depends="T-001")
        self.review()
        want = {"T-001": "버튼을 크게", "T-002": "글꼴을 바꾼다"}
        code, _ = self.decide("out-0001", want, env={"HTEAM_TEST_DIE_AT": "decision_recorded"})
        self.assertEqual(code, 137)
        self.assertEqual(self.rounds("T-001", "T-002"), [("T-001", "awaiting_user", 1), ("T-002", "awaiting_user", 1)])
        tasks_ = {t["id"]: t for t in self.hteam("status")[1]["tasks"]}
        self.assertEqual(tasks_["T-002"]["next"], [H, "design-review", "--decide", "out-0001"])  # 일반 fix 를 권하지 않는다
        code, _ = self.decide("out-0001", env={"HTEAM_TEST_DIE_AT": "decision_after_fix"})  # 첫 fix 뒤 죽었다
        self.assertEqual(code, 137)
        self.assertEqual(self.rounds("T-001", "T-002"), [("T-001", "launch_failed", 2), ("T-002", "awaiting_user", 1)])
        code, out = self.decide("out-0001", {"T-001": "다른 해석"})  # 다시 온 답을 다르게 읽어도 기록대로 한다
        self.assertEqual((code, out["replayed"], out["passed"]), (0, True, ["T-001"]), out)
        self.assertTrue(out["warnings"])
        self.assertEqual(self.rounds("T-001", "T-002"), [("T-001", "launch_failed", 2), ("T-002", "launch_failed", 2)])
        second = (self.state_dir / "tasks/T-002/r2-work.md").read_text(encoding="utf-8")
        self.assertIn("글꼴을 바꾼다", second)
        self.assertIn("선행 T-001 의 사용자 요청을 반영한다: 버튼을 크게", second)
        self.assertNotIn("다른 해석", (self.state_dir / "tasks/T-001/r2-work.md").read_text(encoding="utf-8"))

    def test_start_ready_rechecks_deps_after_a_decision_lands(self):
        # start-ready 가 T-002 의 의존(T-001 awaiting_user)을 본 직후 결정이 T-001 을 고쳤다. 시작 예약에서 다시 보고 띄우지 않는다
        self.task("T-001", "awaiting_user")
        self.review()
        self.task("T-002", "pending", depends="T-001")
        gate = self.tmp / "gate-start"
        proc = self.hteam_bg("start-ready", env={"HTEAM_TEST_PAUSE_AT": "start_ready_checked",
                                                 "HTEAM_TEST_PAUSE_FILE": str(gate)})
        reached = Path(str(gate) + ".reached")
        deadline = time.monotonic() + 30
        while not reached.exists():
            self.assertIsNone(proc.poll())
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.05)
        code, out = self.decide("out-0001", {"T-001": "버튼을 크게"})
        self.assertEqual((code, [s["task"] for s in out.get("decision", {}).get("skipped", [])]), (0, ["T-002"]), out)
        gate.touch()
        code, out = self.finish(proc)
        self.assertEqual((code, out.get("started")), (0, []), out)
        self.assertEqual([w["reason"] for w in out["waiting"] if w["task"] == "T-002"], ["deps"])
        self.assertEqual(self.task_state("T-002")["status"], "pending")

    def test_unfinished_decision_holds_its_dependents(self):
        self.task("T-001", "awaiting_user")
        self.review()
        self.task("T-002", "pending", depends="T-001")
        code, _ = self.decide("out-0001", {"T-001": "x"}, env={"HTEAM_TEST_DIE_AT": "decision_recorded"})
        self.assertEqual(code, 137)  # 기록만 했다. 선행은 아직 awaiting_user 라 의존 검사만 보면 T-002 를 띄운다
        code, out = self.hteam("start-ready")
        self.assertEqual((code, out.get("started")), (0, []), out)
        self.assertEqual([w["reason"] for w in out["waiting"] if w["task"] == "T-002"], ["decision"])
        code, out = self.hteam("start", "T-002")  # 손으로 띄워도 막는다
        self.assertEqual((code, out["error"]["code"], out.get("pending")), (3, "decision_pending", "out-0001"), out)
        self.assertEqual(self.decide("out-0001")[0], 0)  # 결정을 마저 한다
        code, out = self.hteam("start-ready")
        self.assertEqual([s["task"] for s in out["started"]], ["T-001"], out)  # 선행의 수정 라운드만
        self.assertEqual([w["reason"] for w in out["waiting"] if w["task"] == "T-002"], ["deps"])

    def test_queued_dependent_started_after_predecessor_refix_is_not_stale(self):
        self.task("T-001", "awaiting_user")
        self.task("T-002", "awaiting_user", depends="T-001")
        self.review()
        self.assertEqual(self.decide("out-0001", {"T-001": "x", "T-002": "y"})[0], 0)  # 둘 다 queued r2
        self.assertNotIn("basis", self.task_state("T-002")["rounds"][-1])  # 아직 띄우지 않았다
        # T-001 r2 가 리뷰에서 한 번 더 고쳐져 r3 에서 승인됐다(T-002 의 queued 라운드보다 나중에 열렸다)
        self.move("T-001", "awaiting_user", rnd=3)
        self.opened("T-001", 3, "2099-01-01T00:00:00Z")
        code, out = self.hteam("start-ready")
        self.assertEqual([s["task"] for s in out["started"]], ["T-002"], out)
        self.assertEqual(self.task_state("T-002")["rounds"][-1]["basis"], {"T-001": 3})  # 실제로 띄울 때 본 선행
        self.move("T-002", "awaiting_user")
        self.assertEqual(approval.stale(self.p, config.load(self.p), state.all_states(self.p)), {})

    def test_crash_between_done_and_applied_is_recovered(self):
        self.task("T-001", "awaiting_user")
        self.review()
        code, _ = self.decide("out-0001", {}, env={"HTEAM_TEST_DIE_AT": "decision_done"})
        self.assertEqual(code, 137)
        self.assertEqual(self.task_state("T-001")["status"], "done")
        self.assertFalse((self.state_dir / "applied.json").exists())
        view = approval.reply_view(self.p, "out-0001", "모두 승인 (추천)")
        self.assertEqual((view["decision"], view["applied"]), ("done", False))
        self.assertIn("--decide out-0001", approval.reply_hint(view, "out-0001"))  # ack 만 하라고 하지 않는다
        self.assertEqual(self.decide("out-0001")[0], 0)
        self.assertIn("out-0001", json.loads((self.state_dir / "applied.json").read_text(encoding="utf-8")))
        view = approval.reply_view(self.p, "out-0001", "모두 승인 (추천)")
        self.assertIn("ack 만", approval.reply_hint(view, "out-0001"))

    def test_unfinished_decision_comes_first(self):
        self.task("T-001", "awaiting_user")
        self.review()
        self.task("T-002", "awaiting_user")
        self.review()
        code, _ = self.decide("out-0001", {"T-001": "x"}, env={"HTEAM_TEST_DIE_AT": "decision_recorded"})
        self.assertEqual(code, 137)
        code, out = self.decide("out-0002", {})
        self.assertEqual((code, out["error"]["code"], out.get("pending")), (3, "decision_pending", "out-0001"), out)
        self.task("T-003", "awaiting_user")
        code, out = self.review()
        self.assertEqual((code, out["error"]["code"]), (3, "decision_pending"), out)

    def test_decision_input_is_checked_before_anything(self):
        self.task("T-001", "awaiting_user")
        self.review()
        for fix in ({"T-009": "x"}, {"T-001": " "}):
            code, out = self.decide("out-0001", fix)
            self.assertEqual((code, out["error"]["code"]), (2, "bad_decision"), out)
        code, out = self.decide("out-0001")  # 결정이 아직 없는데 입력이 없다
        self.assertEqual((code, out["error"]["code"]), (2, "usage"), out)
        code, out = self.decide("out-0009", {})
        self.assertEqual((code, out["error"]["code"]), (2, "unknown_batch"), out)
        code, out = self.decide("out-0001", {}, as_="main")
        self.assertEqual((code, out["error"]["code"]), (5, "not_coordinator"), out)
        self.assertNotIn("decision", self.record()["batches"][0])

    def test_corrupt_decision_record_is_kept(self):
        self.task("T-001", "awaiting_user")
        self.review()
        data = self.record()
        data["batches"][0]["decision"] = {"at": "2026-11-06T10:00:00Z", "fix": [{"task": "T-001", "round": 1}],
                                          "accept": [], "skipped": [], "done": None}  # note 가 없다
        path = self.state_dir / "design-review.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        before = path.read_text(encoding="utf-8")
        code, out = self.decide("out-0001")
        self.assertEqual((code, out["error"]["code"]), (1, "bad_side_file"), out)
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_accept_rechecks_predecessor_at_the_final_transition(self):
        # accept 의 사전 처리(Dispatch 정리) 동안 선행이 새 라운드를 열었다. 마지막 전이에서 다시 보고 승인하지 않는다
        self.task("T-001", "awaiting_user")
        self.task("T-002", "awaiting_user", depends="T-001")
        self.opened("T-001", 1, "2026-11-06T09:00:00Z")
        self.opened("T-002", 1, "2026-11-06T10:00:00Z")
        gate = self.tmp / "gate-accept"
        proc = self.hteam_bg("accept", "T-002", "--round", "1",
                             env={"HTEAM_TEST_PAUSE_AT": "accept_before_final", "HTEAM_TEST_PAUSE_FILE": str(gate)})
        reached = Path(str(gate) + ".reached")
        deadline = time.monotonic() + 30
        while not reached.exists():
            self.assertIsNone(proc.poll())
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.05)
        self.opened("T-001", 2, "2026-11-06T10:05:00Z")
        gate.touch()
        code, out = self.finish(proc)
        self.assertEqual((code, out["error"]["code"], out.get("because")), (3, "approval_stale", ["T-001"]), out)
        self.assertEqual(self.task_state("T-002")["status"], "awaiting_user")

    def test_accept_refuses_result_adopted_after_predecessor_refix(self):
        # 같은 라운드 복구가 T-001 r3 을 보고 만든 옛 Dispatch 를 이어 붙였다. 그 결과를 최신 선행을 본 것으로 승인하지 않는다
        code, out = self.restart_after_predecessor_refix("after_launch")
        self.assertEqual((code, out.get("mode")), (0, "adopt"), out)
        self.move("T-002", "awaiting_user")
        code, out = self.hteam("accept", "T-002", "--round", "1")
        self.assertEqual((code, out["error"]["code"], out.get("because")), (3, "approval_stale", ["T-001"]), out)
        self.assertEqual(self.task_state("T-002")["status"], "awaiting_user")


class ApprovalFlowTest(DecisionCase):
    """실제 워커로: accept → awaiting_user → design-review → 메인 답 → wait 주석 → 결정 → start-ready(설계 11.4)."""

    def setUp(self):
        super().setUp()
        self.env.update({"HTEAM_WAIT_CHUNK": "0.3", "HTEAM_NO_STATUS_GRACE": "60"})

    def start_design(self, tid, screen, depends=None):
        self.write_spec(tid, "designer", title=f"{screen} 화면", owns=f"docs/design/screens/{screen}/**",
                        depends=depends)
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

    def wait_mains(self):
        """메인 답이 올 때까지 wait 하고 묶음마다 ack 한다. 메인 답이 든 묶음의 메인 메시지 hteam 주석들을 돌려준다."""
        for _ in range(10):
            code, out = self.hteam("wait", "--timeout", "5")
            self.assertEqual(code, 0, out)
            if out.get("delivery") is not None:
                self.assertEqual(self.hteam("wait", "--ack", str(out["delivery"]), "--timeout", "0")[0], 0)
            found = [m["hteam"] for m in out["messages"] if m["hteam"].get("kind") == "main"]
            if found:
                return found
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
        [info] = self.wait_mains()
        self.assertEqual((info["reply_to"], info["duplicate"]), ("out-0001", False))
        self.assertEqual(info["design_review"], {"batch": "dr-0001", "approve_all": True, "decision": None,
                                                 "applied": False, "unknown": [], "tasks": [{"task": "T-001", "round": 1,
                                                                           "status": "awaiting_user", "round_now": 1,
                                                                           "pending": True}]})
        self.assertIn("--decide out-0001", info["hint"])
        code, out = self.decide("out-0001", {})
        self.assertEqual((code, out["accepted"], self.task_state("T-001")["status"]), (0, ["T-001"], "done"), out)
        code, out = self.hteam("start-ready")
        self.assertEqual([s["task"] for s in out.get("started", [])], ["T-002"], out)

    def test_same_answer_twice_in_one_delivery_is_handled_once(self):
        self.start_design("T-001", "login")
        self.finish_design("T-001", "login")
        self.assertEqual(self.hteam("design-review")[0], 0)
        for _ in range(2):  # 메인이 답을 다시 보냈다(보내기가 끊긴 줄 알았다)
            self.assertEqual(self.hteam("answer", "out-0001", "수정 요청: 버튼을 크게", as_="main")[0], 0)
        first, second = self.wait_mains()
        self.assertEqual((first["duplicate"], second["duplicate"]), (False, True))
        self.assertIn("design_review", first)
        self.assertNotIn("design_review", second)
        for _ in range(2):  # 두 번 처리해도 라운드는 하나만 열린다
            self.assertEqual(self.decide("out-0001", {"T-001": "버튼을 크게"})[0], 0)
        self.assertEqual(self.rounds("T-001"), [("T-001", "launch_failed", 2)])
        code, out = self.hteam("fix", "T-001", "--round", "1", "--note=버튼을 크게")
        self.assertEqual((code, out["error"]["code"], out.get("round")), (3, "round_changed", 2), out)

    def test_dependent_fix_waits_for_predecessor_and_keeps_both_requests(self):
        self.start_design("T-001", "login")
        self.finish_design("T-001", "login")
        self.start_design("T-002", "list", depends="T-001")
        self.assertIn("T-002", self.statuses()["T-001"]["hint"])  # 진행 중인 승인 태스크가 끝나면 함께 묻는다
        code, out = self.hteam("design-review")
        self.assertEqual((code, out["error"]["code"]), (3, "approval_not_ready"), out)
        self.finish_design("T-002", "list")
        code, out = self.hteam("design-review")
        self.assertEqual((code, out.get("tasks")), (0, [{"task": "T-001", "round": 1}, {"task": "T-002", "round": 1}]),
                         out)
        self.assertEqual(self.hteam("answer", "out-0001", "수정 요청: T-001 버튼, T-002 글꼴", as_="main")[0], 0)
        [info] = self.wait_mains()
        self.assertFalse(info["design_review"]["approve_all"])
        code, out = self.decide("out-0001", {"T-001": "버튼을 더 크게", "T-002": "글꼴을 바꾼다"})
        self.assertEqual((code, [f["task"] for f in out["fixed"]]), (0, ["T-001", "T-002"]), out)
        self.assertTrue(self.task_state("T-001")["rounds"][1]["from_user"])
        first = (self.state_dir / "tasks/T-001/r2-work.md").read_text(encoding="utf-8")
        self.assertIn("사용자가 일괄 승인에서 수정을 요청했다", first)
        self.assertIn("사용자 요청: 버튼을 더 크게", first)
        self.assertNotIn("의 지적을 모두 다룬다", first)
        second = (self.state_dir / "tasks/T-002/r2-work.md").read_text(encoding="utf-8")
        self.assertIn("글꼴을 바꾼다", second)
        self.assertIn("선행 T-001 의 사용자 요청을 반영한다: 버튼을 더 크게", second)
        code, out = self.hteam("start-ready")  # 선행의 수정 라운드가 다시 승인되기 전에는 의존 태스크를 띄우지 않는다
        self.assertEqual([s["task"] for s in out["started"]], ["T-001"], out)
        self.assertIn({"task": "T-002", "reason": "deps", "detail": "T-001"}, out["waiting"])
        self.assertEqual(self.task_state("T-002")["status"], "launch_failed")
        self.finish_design("T-001", "login")
        self.assertEqual(self.task_state("T-001")["status"], "awaiting_user")  # 이제 의존이 풀렸다
        code, out = self.hteam("start-ready")
        self.assertEqual([s["task"] for s in out["started"]], ["T-002"], out)
        self.finish_design("T-002", "list")
        code, out = self.hteam("design-review")  # 다시 승인된 r2 둘을 함께 묻는다
        self.assertEqual((code, out.get("tasks")), (0, [{"task": "T-001", "round": 2}, {"task": "T-002", "round": 2}]),
                         out)

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
                       "`hteam design-review --decide out-NNNN --json -`", '{"fix": {"T-xxx": "<사용자 요청 원문>"}}',
                       "`decision_pending`", "`decision_conflict`", "`approval_stale`", "`queued`",
                       "같은 `reply_to` 가 둘 이상이면",
                       "- designer:"):
            self.assertIn(needle, coord)
        main = (ROOT / "templates" / "CLAUDE.section.md").read_text(encoding="utf-8")
        self.assertIn("`수정 요청: <태스크 ID 와 고칠 내용>`", main)
        self.assertIn("디자인 `docs/design/`", main)


if __name__ == "__main__":
```

- [ ] **Step 2: 실패 확인**

Run: `bash herdr-team/tests/run.sh -k ApprovalReply -k ApprovalDecision -k ApprovalFlow -k ApprovalDocs`
Expected: FAIL — `--decide`·`--round` 를 모르고(exit 2 usage), `approval.reply_view` 가 없고, accept 결과에 `next` 가 없고, 문서에 일괄 승인 절이 없다.

- [ ] **Step 3: 구현**

라운드 조건, stale 거부(마지막 전이에서), queued 수정 라운드.

**Edit** `herdr-team/lib/hteam/tasks.py`

```python
def _live_error(tid: str, slot: dict, row: dict, horch_cmd: str) -> HteamError:
```

```python
def _expect_round(tid: str, st: dict, want: int | None) -> None:
    """--round N: 명령을 정한 때의 라운드와 지금 라운드가 같아야 한다. 다시 하는 결정(일괄 승인)이 이미 한 항목을
    다음 라운드에 다시 적용하지 않게 한다(설계 6.4)."""
    if want is not None and st["round"] != want:
        raise HteamError("round_changed", f"{tid} 는 지금 r{st['round']} 다(--round {want}). 그 라운드는 이미 처리됐다",
                         CONFLICT, "다시 하지 않는다. hteam status 로 지금 상태를 본다", data={"round": st["round"]})


def _start_gate(p, cfg, spec, check_deps: bool) -> None:
    """시작 예약(프로젝트 잠금 안)에서 다시 본다(설계 11.4). 끝나지 않은 일괄 승인 결정이 고치는 태스크와 그것에
    의존하는 태스크는 띄우지 않는다(결정을 기록한 뒤 선행을 고치기 전 구간 포함). check_deps(start-ready)면 의존도 다시
    본다: 잠금 밖에서 의존을 본 뒤 결정이 선행을 고쳤을 수 있다."""
    from . import approval  # approval 이 tasks 를 쓴다. 불러오는 순서가 꼬이지 않게 여기서 가져온다
    held = approval.held_by_decision(p, spec.id)
    if held:
        raise HteamError("decision_pending", f"{spec.id} 는 끝나지 않은 일괄 승인 결정 {held} 이 고치는 태스크이거나 그 "
                         "의존 태스크다", CONFLICT, f"`{SHIM} design-review --decide {held}` 로 결정을 마저 한 뒤 start-ready",
                         data={"pending": held})
    if check_deps and not deps_met(p, cfg, spec):
        raise HteamError("deps_unmet", f"{spec.id} 의 선행이 아직 끝나지 않았다: {', '.join(spec.depends_on)}", CONFLICT)


def _refuse_stale(p, cfg, tid: str) -> None:
    """awaiting_user 승인 태스크의 선행이 이 라운드를 연 뒤에 고쳐졌으면 승인하지 않는다(설계 11.4, 읽기만 하는 검사).
    프로젝트 잠금 안에서 부른다(선행의 새 라운드는 fix 가 같은 잠금 안에서 쓴다)."""
    from . import approval  # approval 이 tasks 를 쓴다. 불러오는 순서가 꼬이지 않게 여기서 가져온다
    behind = approval.stale(p, cfg, state.all_states(p)).get(tid)
    if behind:
        names = ", ".join(behind)
        raise HteamError("approval_stale", f"{tid} 의 선행 {names} 가 이 라운드를 연 뒤에 고쳐졌다. 옛 선행을 보고 만든 "
                         "결과를 승인하지 않는다", CONFLICT,
                         "메인에 알린다. 사용자가 정하면 일괄 승인 결정의 fix 에 넣거나 hteam fix T --note=… 로 다시 만든다",
                         data={"because": behind})


def _live_error(tid: str, slot: dict, row: dict, horch_cmd: str) -> HteamError:
```

**Edit** `herdr-team/lib/hteam/tasks.py`

```python
def accept(p, tid: str) -> dict:
```

```python
def accept(p, tid: str, expect_round: int | None = None) -> dict:
```

**Edit** `herdr-team/lib/hteam/tasks.py`

```python
    if st["status"] not in ("approved", "awaiting_user"):
        raise HteamError("bad_state", f"{tid} 는 {st['status']} 다(accept 는 approved·awaiting_user 에서)", CONFLICT,
                         data={"status": st["status"]})
    to = "awaiting_user" if st["status"] == "approved" and cfg.is_approval(st["role"]) else "done"
```

```python
    if st["status"] not in ("approved", "awaiting_user"):
        raise HteamError("bad_state", f"{tid} 는 {st['status']} 다(accept 는 approved·awaiting_user 에서)", CONFLICT,
                         data={"status": st["status"]})
    _expect_round(tid, st, expect_round)
    to = "awaiting_user" if st["status"] == "approved" and cfg.is_approval(st["role"]) else "done"
```

**Edit** `herdr-team/lib/hteam/tasks.py`

```python
    with state.edit(p, tid, expect={st["status"]}) as cur:
        if cur["round"] != st["round"]:  # 멈춘 사이 다음 라운드가 같은 상태에 닿았다. 본 적 없는 라운드를 닫지 않는다
            raise _changed(tid, st, cur)
        work_slot(cur)["cleaned"] = cleaned
        state.move(cur, to, "accept")
    return {"task": tid, "status": to, "warnings": warnings}
```

```python
    die_at("accept_before_final")
    with state.project_lock(p):  # 선행의 새 라운드(fix 가 같은 잠금 안에서 쓴다)와 겹치지 않게 이 안에서 다시 본다
        if st["status"] == "awaiting_user" and cfg.is_approval(st["role"]):
            _refuse_stale(p, cfg, tid)
        with state.edit(p, tid, expect={st["status"]}) as cur:
            if cur["round"] != st["round"]:  # 멈춘 사이 다음 라운드가 같은 상태에 닿았다. 본 적 없는 라운드를 닫지 않는다
                raise _changed(tid, st, cur)
            work_slot(cur)["cleaned"] = cleaned
            state.move(cur, to, "accept")
    out = {"task": tid, "status": to, "warnings": warnings}
    if to == "awaiting_user":  # 승인 직무: 다른 승인 태스크와 묶어 사용자에게 묻는다(설계 11.4)
        out["next"] = [SHIM, "design-review"]
        out["hint"] = (f"`{SHIM} start-ready` 뒤 `{SHIM} design-review`. exit 3 approval_not_ready 면 다른 승인 직무 "
                       "태스크를 accept 한 뒤 다시 부른다")
    return out
```

**Edit** `herdr-team/lib/hteam/tasks.py`

```python
def fix(p, tid: str, *, note: str | None, supplement: str | None, force_round: bool, cli: dict) -> dict:
    """새 라운드(설계 6.4). 입력(사양·owns·잠금)을 먼저 검사하고, 이전 라운드들의 작업·리뷰 Dispatch 를 모두 정리한
    뒤에만 새 라운드를 쓰고 띄운다(이전 워커와 새 워커가 같은 폴더에서 함께 일하지 않게). 일하는 중인 워커는
    abandon --kill 뒤 release."""
```

```python
def fix(p, tid: str, *, note: str | None, supplement: str | None, force_round: bool, cli: dict,
        expect_round: int | None = None, queue: bool = False, from_user: bool | None = None,
        extra_from: tuple[str, ...] = ()) -> dict:
    """새 라운드(설계 6.4). 입력(사양·owns·잠금)을 먼저 검사하고, 이전 라운드들의 작업·리뷰 Dispatch 를 모두 정리한
    뒤에만 새 라운드를 쓰고 띄운다(이전 워커와 새 워커가 같은 폴더에서 함께 일하지 않게). 일하는 중인 워커는
    abandon --kill 뒤 release.

    일괄 승인 결정(설계 11.4)이 부를 때: queue 면 새 라운드를 쓰고 띄우지 않는다(launch_failed, queued. start-ready 가
    의존이 풀린 뒤 띄운다). from_user 가 None 이면 awaiting_user 에서 연 라운드가 사용자 요청이다. extra_from 은
    FIX_FROM 밖에서 더 받을 상태다(결정이 고치는 의존 태스크는 리뷰 중·승인됨이어도 다시 만든다)."""
```

**Edit** `herdr-team/lib/hteam/tasks.py`

```python
    def allowed(st: dict) -> None:
        if st["status"] in state.CLOSED:
            raise state.closed_error(st)
        if st["status"] not in FIX_FROM:
            raise HteamError("bad_state", f"{tid} 는 {st['status']} 다(fix 는 {', '.join(FIX_FROM)} 에서)", CONFLICT,
                             data={"status": st["status"]})
```

```python
    allowed_from = FIX_FROM + tuple(extra_from)

    def allowed(st: dict) -> None:
        if st["status"] in state.CLOSED:
            raise state.closed_error(st)
        _expect_round(tid, st, expect_round)  # 미리 보고, 취소를 저장하는 잠금 안에서 다시 본다(_close_round 의 check)
        if st["status"] not in allowed_from:
            raise HteamError("bad_state", f"{tid} 는 {st['status']} 다(fix 는 {', '.join(allowed_from)} 에서)", CONFLICT,
                             data={"status": st["status"]})
```

**Edit** `herdr-team/lib/hteam/tasks.py`

```python
        rd = _new_round(st, st["round"] + 1, gitio.head(p.root), choice, note=note, supplement=supplement)
        text = compose.work_spec(p, cfg, spec, rd, owns)
```

```python
        rd = _new_round(st, st["round"] + 1, gitio.head(p.root), choice, note=note, supplement=supplement)
        if (old == "awaiting_user") if from_user is None else from_user:
            rd["from_user"] = True  # 사용자 일괄 승인의 수정 요청(설계 11.4). 수정 블록이 사용자 요청으로 적는다
        if queue:
            rd["queued"] = True
        text = compose.work_spec(p, cfg, spec, rd, owns)
```

**Edit** `herdr-team/lib/hteam/tasks.py`

```python
        _begin(p, st, rd, text, "fix", previous=old, force_round=force_round)
    return run_work(p, cfg, h, tid)
```

```python
        _begin(p, st, rd, text, "fix", previous=old, force_round=force_round)
    if queue:  # 띄우지 않는다. start-ready 의 의존 검사가 선행이 다시 승인된 뒤에 띄운다(설계 11.4)
        return {"task": tid, "round": rd["round"], "status": "launch_failed", "queued": True,
                "next": [SHIM, "start-ready"],
                "hint": "수정 라운드를 만들었다. start-ready 가 선행이 끝난(승인 직무는 awaiting_user) 뒤에 띄운다"}
    return run_work(p, cfg, h, tid)
```

**Edit** `herdr-team/lib/hteam/tasks.py`

```python
    return fix(p, args.task, note=args.note, supplement=args.supplement, force_round=args.force_round, cli=_cli(args))


def _cmd_accept(args) -> dict:
    p = find_project(args.root)
    roles.require_coordinator(p)
    return accept(p, args.task)
```

```python
    return fix(p, args.task, note=args.note, supplement=args.supplement, force_round=args.force_round, cli=_cli(args),
               expect_round=args.expect_round)


def _cmd_accept(args) -> dict:
    p = find_project(args.root)
    roles.require_coordinator(p)
    return accept(p, args.task, args.expect_round)
```

**Edit** `herdr-team/lib/hteam/tasks.py`

```python
    s.add_argument("--force-round", action="store_true")
    _overrides(s)
    s.set_defaults(func=_cmd_fix)
    s = sub.add_parser("accept")
    s.add_argument("task")
    s.set_defaults(func=_cmd_accept)
```

```python
    s.add_argument("--force-round", action="store_true")
    s.add_argument("--round", type=int, dest="expect_round", help="지금 라운드가 이것일 때만(설계 6.4)")
    _overrides(s)
    s.set_defaults(func=_cmd_fix)
    s = sub.add_parser("accept")
    s.add_argument("task")
    s.add_argument("--round", type=int, dest="expect_round", help="지금 라운드가 이것일 때만(설계 6.4)")
    s.set_defaults(func=_cmd_accept)
```

시작 예약에서 결정과 의존을 다시 본다.

**Edit** `herdr-team/lib/hteam/tasks.py`

```python
            _check_locks(p, cfg, spec, owns)
            if cap is not None:
```

```python
            _check_locks(p, cfg, spec, owns)
            _start_gate(p, cfg, spec, check_deps=cap is not None)
            if cap is not None:
```

**Edit** `herdr-team/lib/hteam/tasks.py`

```python
WAIT_CODES = {"owns_locked": "lock", "planner_busy": "lock", "launching": "launching", "parallel_limit": "limit"}
```

```python
WAIT_CODES = {"owns_locked": "lock", "planner_busy": "lock", "launching": "launching", "parallel_limit": "limit",
              "deps_unmet": "deps", "decision_pending": "decision"}
```

**Edit** `herdr-team/lib/hteam/tasks.py`

```python
                waiting.append({"task": tid, "reason": "deps", "detail": ", ".join(spec.depends_on)})
                continue
            res = start(p, tid, {}, cfg=cfg, h=h, cap=cap)
```

```python
                waiting.append({"task": tid, "reason": "deps", "detail": ", ".join(spec.depends_on)})
                continue
            die_at("start_ready_checked")  # 테스트: 의존을 본 뒤 시작 전에 결정이 끼는 순서를 재현한다
            res = start(p, tid, {}, cfg=cfg, h=h, cap=cap)
```

**Edit** `herdr-team/lib/hteam/tasks.py`

```python
    with _closing(p, tid, seen) as st:
        _check_locks(p, cfg, spec, owns)
```

```python
    with _closing(p, tid, seen) as st:
        _check_locks(p, cfg, spec, owns)
        if not queue:  # 결정 밖의 fix 는 끝나지 않은 결정이 고치는 태스크를 띄우지 않는다(결정 자신의 fix 는 queue 다)
            _start_gate(p, cfg, spec, check_deps=False)
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

approval: 결정 기록·검사·재생, 끝나지 않은 결정, 답 주석.

**Edit** `herdr-team/lib/hteam/approval.py`

```python
import re

from . import config, outbox, roles, specs, state, tasks
from .errors import CONFLICT, USAGE, HteamError
from .paths import find_project, report_rel
```

```python
import json
import re
import sys

from . import config, outbox, roles, specs, state, tasks
from .errors import CONFLICT, FAIL, USAGE, HteamError
from .paths import SHIM, find_project, report_rel
```

**Edit** `herdr-team/lib/hteam/approval.py`

```python
    try:
        outbox.validate_render(b.get("render"), HEADER)
    except HteamError as exc:
        return f"{b['batch']}: render 가 질문 형식이 아니다({exc.message})"
    return None
```

```python
    try:
        outbox.validate_render(b.get("render"), HEADER)
    except HteamError as exc:
        return f"{b['batch']}: render 가 질문 형식이 아니다({exc.message})"
    if b.get("decision") is not None:
        return _decision_problem(b)
    return None


def _decision_problem(b: dict) -> str | None:
    """결정 기록의 모양 문제(없으면 None). 틀린 결정으로 accept·fix 를 하지 않는다."""
    d, name = b["decision"], b["batch"]
    if b.get("id") is None:
        return f"{name}: 묻지 않은 묶음에 결정이 있다"
    if not isinstance(d, dict) or not isinstance(d.get("at"), str) or not isinstance(d.get("input"), dict):
        return f"{name}: decision 이 객체가 아니거나 at·input 이 없다"
    if not all(isinstance(d.get(k), list) for k in ("fix", "accept", "skipped")):
        return f"{name}: decision 의 fix·accept·skipped 가 목록이 아니다"
    if not all(_task_ok(e) and isinstance(e.get("note"), str) and e["note"].strip()
               and isinstance(e.get("because"), list) for e in d["fix"]):
        return f"{name}: decision.fix 가 [{{task, round, note, because}}] 가 아니다"
    if not all(_task_ok(e) for e in d["accept"]):
        return f"{name}: decision.accept 가 [{{task, round}}] 가 아니다"
    if d.get("done") is not None and not isinstance(d["done"], str):
        return f"{name}: decision.done 이 시각이나 null 이 아니다"
    return None


def _open_decision(data: dict, but: dict | None = None) -> dict | None:
    """끝나지 않은 결정이 있는 묶음(but 은 뺀다)."""
    return next((b for b in data["batches"] if b is not but and b.get("decision") and not b["decision"].get("done")),
                None)


def _decision_pending(b: dict) -> HteamError:
    return HteamError("decision_pending", f"{b['id']} 의 일괄 승인 결정을 아직 다 하지 않았다", CONFLICT,
                      f"먼저 `{SHIM} design-review --decide {b['id']}` 로 기록대로 마저 한다", data={"pending": b["id"]})


def _unfinished(data: dict, states: list[dict]) -> dict[str, str]:
    """끝나지 않은 결정의 항목 가운데 아직 하지 않은 것(태스크가 기록한 라운드 그대로) → 그 out-id."""
    by_id = {s["id"]: s for s in states}
    found: dict[str, str] = {}
    for b in data["batches"]:
        d = b.get("decision")
        if not d or d.get("done"):
            continue
        for e in [*d["fix"], *d["accept"]]:
            st = by_id.get(e["task"])
            if st is not None and st["status"] not in state.CLOSED and st["round"] == e["round"]:
                found[e["task"]] = b["id"]
    return found
```

**Edit** `herdr-team/lib/hteam/approval.py`

```python
    data = load(p) if data is None else data
    done = asked(data)
    behind = stale(p, cfg, states)
```

```python
    data = load(p) if data is None else data
    done = asked(data)
    behind = stale(p, cfg, states)
    replay = _unfinished(data, states)
```

**Edit** `herdr-team/lib/hteam/approval.py`

```python
    return {"waiting": waiting, "blockers": blockers, "stale": late, "fresh": fresh, "asked": done}
```

```python
    return {"waiting": waiting, "blockers": blockers, "stale": late, "fresh": fresh, "asked": done, "replay": replay}
```

**Edit** `herdr-team/lib/hteam/approval.py`

```python
        bad = state.unreadable_ids(p)
        if bad:  # 그 태스크가 진행 중인 승인 태스크인지 알 수 없다. 묶음을 잘못 나누지 않게 묻지 않는다
```

```python
        busy = _open_decision(data)
        if busy is not None:  # 끝나지 않은 결정이 태스크를 바꾸는 중이다. 그 태스크를 새 묶음에 넣지 않는다
            raise _decision_pending(busy)
        bad = state.unreadable_ids(p)
        if bad:  # 그 태스크가 진행 중인 승인 태스크인지 알 수 없다. 묶음을 잘못 나누지 않게 묻지 않는다
```

**Edit** `herdr-team/lib/hteam/approval.py`

```python
def _cmd(args) -> dict:
    p = find_project(args.root)
    roles.require_coordinator(p)
    return design_review(p)


def register(sub) -> None:
    sub.add_parser("design-review").set_defaults(func=_cmd)
```

````python
# 결정이 고치는 의존 태스크는 진행 중(리뷰 중·승인됨 포함)이어도 다시 만든다(옛 선행을 보고 만들었다)
DEPENDENT_FROM = ("reviewing", "approved")


def held_by_decision(p, tid: str) -> str | None:
    """끝나지 않은 결정이 고치는 태스크이거나 그것에 직간접으로 의존하는 태스크면 그 결정의 out-id(시작 예약이 본다)."""
    data = load(p)
    graph = None
    for b in data["batches"]:
        d = b.get("decision")
        if not d or d.get("done"):
            continue
        targets = {e["task"] for e in d["fix"]}
        if tid in targets:
            return b["id"]
        graph = graph or Graph(p)
        if targets & graph.ancestors(tid):
            return b["id"]
    return None


def _decision_input(text: str | None, b: dict) -> dict[str, str]:
    """코디네이터가 해석한 답: {"fix": {태스크: 사용자 요청}}. 태스크는 그 묶음의 것이어야 한다. 틀리면 exit 2."""
    if text is None:
        raise HteamError("usage", f"{b['id']} 에는 아직 결정이 없다. --json - 으로 {{\"fix\": {{태스크: 사용자 요청}}}} 을 "
                         "준다(모두 승인이면 {\"fix\": {}})", USAGE)
    try:
        obj = json.loads(text)
    except ValueError as exc:
        raise HteamError("bad_decision", f"결정 JSON 을 읽지 못했다: {exc}", USAGE) from None
    fix = obj.get("fix") if isinstance(obj, dict) else None
    if not isinstance(obj, dict) or set(obj) != {"fix"} or not isinstance(fix, dict):
        raise HteamError("bad_decision", "결정은 {\"fix\": {태스크: 사용자 요청}} 이다", USAGE)
    mine = {t["task"] for t in b["tasks"]}
    errors = [f"{k}: 이 묶음({b['id']})의 태스크가 아니다" for k in fix if k not in mine]
    errors += [f"{k}: 사용자 요청이 비었다" for k, v in fix.items() if not isinstance(v, str) or not v.strip()]
    if errors:
        raise HteamError("bad_decision", "결정 입력이 틀렸다: " + "; ".join(errors), USAGE, data={"errors": errors})
    return {k: v.strip() for k, v in fix.items()}


def _compute(p, cfg, b: dict, wanted: dict[str, str]) -> dict:
    """결정을 한 번 계산한다(프로젝트 잠금 안). 고칠 태스크 = 지목된 묶음 태스크 + 그것에 직간접으로 의존하는 승인 태스크
    전부(다른 묶음 포함). 각자 지금 라운드와 사용자 요청을 적는다. 지목된 태스크의 라운드가 다른 결정 때문에 이미 바뀌었어도
    (의존 태스크로 함께 고쳐졌다) 이 새 요청을 버리지 않고 지금 라운드에서 다시 고친다(그 라운드가 사용자 요청 라운드면 그
    요청도 이어 적는다). 지목된 태스크가 끝났으면 decision_conflict(아무것도 쓰지 않는다). 시작하지 않은 의존 태스크
    (pending)는 선행이 다시 승인된 뒤 시작하므로 고칠 것이 없고, 끝난 의존 태스크는 고칠 수 없어 skipped 다. 승인할 태스크 =
    묶음의 나머지(아직 그 라운드의 awaiting_user). 상태를 읽지 못하면, 승인할 태스크가 stale 이면 아무것도 쓰지 않는다."""
    bad = state.unreadable_ids(p)
    if bad:
        raise tasks._unreadable(p, bad)
    states = state.all_states(p)
    by_id = {s["id"]: s for s in states}
    missing = [t["task"] for t in b["tasks"] if t["task"] not in by_id]
    if missing:
        raise HteamError("bad_state_file", f"묶음 태스크의 상태 파일이 없다: {', '.join(missing)}", FAIL,
                         "메인에 알린다", data={"missing": missing})
    graph = Graph(p)
    live = {t["task"] for t in b["tasks"]
            if by_id[t["task"]]["status"] == "awaiting_user" and by_id[t["task"]]["round"] == t["round"]}
    closed = [t for t in sorted(wanted, key=state.id_number) if by_id[t]["status"] in state.CLOSED]
    if closed:  # 사용자 요청을 반영할 수 없다. 처리한 것으로 넘기지 않는다
        raise HteamError("decision_conflict", f"고치라는 태스크가 이미 끝났다: {', '.join(closed)}", CONFLICT,
                         "메인에 알린다. 사용자가 정한 대로(새 태스크 등) 그 태스크를 뺀 결정을 다시 준다",
                         data={"closed": closed})
    direct = sorted(wanted, key=state.id_number)
    skipped: list[dict] = []
    fix: dict[str, dict] = {}
    for tid in sorted(set(by_id) | set(specs.list_ids(p)), key=state.id_number):
        ups = [d for d in direct if d != tid and d in graph.ancestors(tid)]
        if tid not in direct and not ups:
            continue
        st = by_id.get(tid)
        if tid not in direct:
            if not cfg.is_approval((st or {}).get("role") or graph.role(tid)):
                continue
            if st is None or st["status"] == "pending":
                skipped.append({"task": tid, "why": "pending: 선행이 다시 승인된 뒤에 시작한다(고칠 것이 없다)"})
                continue
            if st["status"] in state.CLOSED:
                skipped.append({"task": tid, "why": f"{st['status']}: 끝난 태스크라 고칠 수 없다(메인에 알린다)"})
                continue
        parts = [wanted[tid]] if tid in direct else []
        prev = state.current_round(st) or {}
        if tid in direct and tid not in live and prev.get("from_user") and prev.get("note"):
            parts.append(f"이전 요청도 그대로 반영한다: {prev['note']}")  # 다른 결정이 연 라운드의 요청을 잃지 않는다
        parts += [f"선행 {d} 의 사용자 요청을 반영한다: {wanted[d]}" for d in ups]
        fix[tid] = {"task": tid, "round": st["round"], "note": " / ".join(parts), "because": ups}
    # 선행부터(결정 안의 선행 수가 적은 것부터). 라운드를 연 시각이 선행 → 의존 순서가 된다
    order = sorted(fix.values(), key=lambda e: (len([x for x in fix if x in graph.ancestors(e["task"])]),
                                                state.id_number(e["task"])))
    accept = [{"task": t["task"], "round": t["round"]} for t in b["tasks"] if t["task"] in live and t["task"] not in fix]
    skipped += [{"task": t["task"], "why": "이미 처리됐다"} for t in b["tasks"]
                if t["task"] not in live and t["task"] not in wanted]
    behind = stale(p, cfg, states, graph)
    late = [a["task"] for a in accept if a["task"] in behind]
    if late:
        raise HteamError("approval_stale", f"승인할 태스크의 선행이 그 뒤에 고쳐졌다: {', '.join(late)}", CONFLICT,
                         "메인에 알린다. 사용자가 정하면 그 태스크도 결정의 fix 에 넣는다", data={"stale": late})
    return {"at": now(), "input": wanted, "fix": order, "accept": accept, "skipped": skipped, "done": None}


def _stopped(exc: HteamError, oid: str) -> HteamError:
    exc.hint = (f"{exc.hint} 결정은 기록돼 있다. 원인이 풀리면 `{SHIM} design-review --decide {oid}` 를 다시 한다"
                "(기록대로 이어 한다)").strip()
    return exc


def _apply(p, oid: str, d: dict) -> dict:
    """기록한 결정을 그대로 한다. 기록한 라운드가 이미 지났거나 닫힌 항목은 한 것으로 본다(다시 하지 않는다). 다른 오류는
    거기서 멈춘다(다시 부르면 이어 한다). 다 하면 결정에 done 을 적고 그 답을 applied 로 적는다."""
    fixed: list[dict] = []
    accepted: list[str] = []
    passed: list[str] = []
    for e in d["fix"]:
        try:
            res = tasks.fix(p, e["task"], note=e["note"], supplement=None, force_round=True, cli={},
                            expect_round=e["round"], queue=True, from_user=True, extra_from=DEPENDENT_FROM)
            fixed.append({"task": e["task"], "round": res["round"]})
        except HteamError as exc:
            if exc.code not in ("round_changed", "task_closed"):
                raise _stopped(exc, oid)
            passed.append(e["task"])
        die_at("decision_after_fix")
    for e in d["accept"]:
        try:
            tasks.accept(p, e["task"], expect_round=e["round"])
            accepted.append(e["task"])
        except HteamError as exc:
            if exc.code not in ("round_changed", "task_closed"):
                raise _stopped(exc, oid)
            passed.append(e["task"])
    with state.project_lock(p):
        data = load(p)
        b = next(x for x in data["batches"] if x.get("id") == oid)
        b["decision"]["done"] = now()
        write_json(p.design_review, data)
    die_at("decision_done")  # 여기서 죽으면 다시 온 답의 안내가 --decide 재호출이다(applied 만 적는다)
    outbox.mark_applied(p, oid)
    return {"fixed": fixed, "accepted": accepted, "passed": passed}


def decide(p, oid: str, text: str | None) -> dict:
    """일괄 승인 답의 결정(설계 11.4). 결정이 없으면 계산해 묶음 기록에 먼저 쓰고, 있으면 그대로 쓴다. 그다음 기록대로
    fix(queued)·accept 를 한다. 다른 묶음의 결정이 끝나지 않았으면 exit 3 decision_pending."""
    cfg = config.load(p)
    warnings: list[str] = []
    with state.project_lock(p):
        data = load(p)
        b = next((x for x in data["batches"] if x.get("id") == oid), None)
        if b is None:
            raise HteamError("unknown_batch", f"{oid} 는 design-review 가 쓴 일괄 승인 질문이 아니다", USAGE)
        other = _open_decision(data, but=b)
        if other is not None:
            raise _decision_pending(other)
        replayed = b.get("decision") is not None
        if not replayed:
            b["decision"] = _compute(p, cfg, b, _decision_input(text, b))
            write_json(p.design_review, data)
        elif text is not None:
            warnings.append("결정이 이미 기록돼 있어 새 입력은 쓰지 않았다(기록대로 한다)")
        d = b["decision"]
    die_at("decision_recorded")
    out = {"id": oid, "batch": b["batch"], "decision": d, "replayed": replayed, "skipped": d["skipped"]}
    if d.get("done"):
        outbox.mark_applied(p, oid)  # 다 한 뒤 applied 전에 죽었을 수 있다(두 번 적어도 같다)
        res = {"fixed": [], "accepted": [], "passed": [e["task"] for e in [*d["fix"], *d["accept"]]]}
    else:
        res = _apply(p, oid, d)
    closed = [s["task"] for s in d["skipped"] if s["why"].startswith(("done", "dropped"))]
    if closed:
        warnings.append(f"끝난 의존 태스크({', '.join(closed)})는 고치지 못했다. 메인에 알린다")
    return {**out, **res, "warnings": warnings, "next": [SHIM, "start-ready"],
            "hint": "고칠 태스크는 수정 라운드를 만들어 두었다(queued). start-ready 가 선행이 다시 승인된 뒤 띄운다"}


def reply_view(p, oid: str, answer: str, states: list[dict] | None = None) -> dict | None:
    """oid 가 design-review 묶음의 질문이면 그 답의 처리 정보, 아니면 None(설계 11.4).

    {"batch", "approve_all": 답이 정확히 APPROVE 인가, "decision": None | "recorded" | "done", "applied": 답을 applied 로
    적었나, "unknown": [상태를 읽지 못한 묶음 태스크], "tasks": [{"task", "round"(물은 라운드), "status", "round_now",
    "pending"}]}. 읽지 못한 태스크는 처리한 것으로 보지 않는다. 기록을 읽지 못하면 bad_side_file."""
    b = next((x for x in load(p)["batches"] if x.get("id") == oid), None)
    if b is None:
        return None
    by_id = {s["id"]: s for s in (state.all_states(p) if states is None else states)}
    unknown: list[str] = []
    items = []
    for t in b["tasks"]:
        st = by_id.get(t["task"])
        if st is None:
            try:
                st = state.load(p, t["task"])
            except HteamError:
                st = None
            if st is None or st.get("id") != t["task"]:
                unknown.append(t["task"])
                st = {}
        items.append({"task": t["task"], "round": t["round"], "status": st.get("status"), "round_now": st.get("round"),
                      "pending": st.get("status") == "awaiting_user" and st.get("round") == t["round"]})
    d = b.get("decision")
    return {"batch": b["batch"], "approve_all": answer.strip() == APPROVE,
            "decision": None if d is None else ("done" if d.get("done") else "recorded"),
            "applied": oid in outbox.applied_ids(p), "unknown": unknown, "tasks": items}


def reply_hint(view: dict, oid: str) -> str:
    """reply_view 결과로 코디네이터가 할 일(coordinator.md 의 "일괄 승인 답")."""
    cmd = f"{SHIM} design-review --decide {oid}"
    if view["unknown"]:
        return (f"상태를 읽지 못한 태스크가 있다({', '.join(view['unknown'])}). 결정하지 않는다. 메인에 알려 상태 파일을 고친 뒤 "
                "다시 받는다")
    if view["decision"] == "done" and view["applied"]:
        return "이 답은 이미 결정대로 처리했다. ack 만 한다"
    if view["decision"] == "done":  # done 을 쓴 뒤 applied 전에 죽었다
        return f"결정은 다 했지만 applied 기록이 없다. `{cmd}` 를 입력 없이 다시 해 applied 를 적는다"
    if view["decision"] == "recorded":
        return f"이 답의 결정이 기록돼 있다. `{cmd}` 를 입력 없이 다시 해 기록대로 마저 한다"
    if view["approve_all"]:
        return f"모두 승인이다. `{cmd} --json -` 에 {{\"fix\": {{}}}} 를 준다. 그다음 `{SHIM} start-ready`"
    return (f"수정 요청이다. 답에서 고칠 태스크와 사용자 요청을 정해 `{cmd} --json -` 에 "
            "{\"fix\": {\"T-xxx\": \"<사용자 요청 원문>\"}} 를 준다. 이름이 없는 태스크는 승인되고, 의존 승인 태스크는 "
            f"hteam 이 같은 요청과 함께 고친다. 모호하면 notify --type question 으로 다시 묻는다. 그다음 `{SHIM} start-ready`")


def _cmd(args) -> dict:
    p = find_project(args.root)
    roles.require_coordinator(p)
    if args.decide:
        text = sys.stdin.read() if args.json == "-" else args.json
        return decide(p, args.decide, text)
    if args.json is not None:
        raise HteamError("usage", "--json 은 --decide 와 함께 쓴다", USAGE)
    return design_review(p)


def register(sub) -> None:
    s = sub.add_parser("design-review")
    s.add_argument("--decide", metavar="OUT_ID", help="그 질문의 답을 결정으로 기록하고 기록대로 한다(설계 11.4)")
    s.add_argument("--json", help="'-' 면 표준 입력: {\"fix\": {태스크: 사용자 요청}}. 모두 승인이면 {\"fix\": {}}")
    s.set_defaults(func=_cmd)
````

coord: 답 주석, 한 Delivery 안의 중복, 결정·queued·awaiting_user 의 next.

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
        info["warning"] = f"이 답이 일괄 승인 답인지 보지 못했다: {exc.message}. 고친 뒤 다시 받는다(결정하지 않는다)"
        return
    if view is not None:
        info["design_review"] = view
        info["hint"] = approval.reply_hint(view, oid)


def _once(messages: list[dict]) -> list[dict]:
    """한 Delivery 안에 같은 out-id 의 답이 둘 이상이면(메인이 답을 다시 보냄) 뒤의 것을 duplicate 로 표시한다(설계 7.4:
    같은 out-id 는 한 번만 처리한다). 같은 상태 스냅숏으로 주석을 달아 둘 다 처리할 일로 보이기 때문이다."""
    seen: set[str] = set()
    for m in messages:
        info = m.get("hteam") or {}
        oid = info.get("reply_to")
        if info.get("kind") != "main" or not oid:
            continue
        if oid in seen:
            info.pop("design_review", None)
            info.update(duplicate=True, hint="이 묶음에 같은 답이 앞에 있다(다시 보낸 답). 앞의 것만 처리하고 이것은 ack 만 한다")
        seen.add(oid)
    return messages
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
                   "messages": [annotate(p, m, rows, cmd, cfg=cfg, states=states) for m in data["messages"]],
```

```python
                   "messages": _once([annotate(p, m, rows, cmd, cfg=cfg, states=states) for m in data["messages"]]),
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
    appr: approval.view 결과(끝나지 않은 일괄 승인 결정, awaiting_user 의 next). 읽지 못했으면 None."""
```

**Edit** `herdr-team/lib/hteam/coord.py`

```python
    slot = rd["work"]
    if _round_canceled(rd):
        return None, CANCELED_HINT
```

```python
    slot = rd["work"]
    if _round_canceled(rd):
        return None, CANCELED_HINT
    if appr is not None and tid in appr.get("replay", {}):
        oid = appr["replay"][tid]  # 일반 fix·accept 를 권하지 않는다(사용자 요청은 결정 기록에 있다)
        return H("design-review", "--decide", oid), f"일괄 승인 결정 {oid} 을 기록대로 마저 한다"
```

**Edit** `herdr-team/lib/hteam/coord.py`

```python
    if s == "launch_failed":
        if dispatch.busy(st, slot):
            return None, "띄우는 중이다(launching)"
        return H("start", tid), None
```

```python
    if s == "launch_failed":
        if dispatch.busy(st, slot):
            return None, "띄우는 중이다(launching)"
        if rd.get("queued") and not slot.get("launched") and not slot.get("horch_task"):
            # start T 는 의존을 보지 않는다. start-ready 가 선행이 다시 승인된 뒤에 띄운다(설계 11.4)
            return H("start-ready"), "일괄 승인 결정으로 연 수정 라운드다. 선행이 끝나면 start-ready 가 띄운다"
        return H("start", tid), None
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
    """awaiting_user 의 다음(설계 11.4): stale 이면 알리기만 하고, 이미 물었으면 그 답을 기다리고, 진행 중이거나 시작할 수
    있는 승인 태스크가 있으면 그것을 기다리고, 아니면 design-review."""
    if appr is None:
        return None, "사용자 일괄 승인을 기다린다(일괄 승인 기록을 읽지 못했다. status 의 warnings 를 본다)"
    late = next((s for s in appr["stale"] if s["task"] == st["id"]), None)
    if late:
        return None, (f"선행 {', '.join(late['because'])} 가 이 라운드를 연 뒤에 결정 밖에서 고쳐졌다. 묻지도 승인하지도 "
                      "않는다. 메인에 알린다")
    key = (st["id"], st["round"])
    if key in appr["asked"]:
        oid = appr["asked"][key]
        if oid is None:
            return H("design-review"), "일괄 승인 질문을 쓰다 멈췄다. design-review 가 마저 쓴다"
        return None, f"일괄 승인 질문 {oid} 의 사용자 답을 기다린다(답이 오면 design-review --decide {oid})"
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
- 승인 직무(designer 등)는 `accept` 가 `status: awaiting_user` 와 `next` 를 준다. `hteam start-ready` 뒤 `hteam design-review` 를 부른다. exit 3 `approval_not_ready` 면 다른 승인 직무 태스크가 아직 진행 중이거나 지금 시작할 수 있다: 그 태스크를 accept 한 뒤 다시 부른다. `already_asked` 면 사용자 답을 기다린다. `nothing_to_approve` 면 할 일이 없다. `decision_pending` 이면 hint 의 `--decide` 를 먼저 마저 한다. `approval_stale` 이면 메인에 알린다(아래).
```

**Edit** `herdr-team/templates/coordinator.md`

```markdown
## 요청 처리
```

```markdown
## 일괄 승인 답
`hteam design-review` 가 올린 approval 질문의 답은 `kind: main`, `reply_to: out-NNNN` 에 `design_review` 필드(`batch`, `approve_all`, `decision`, `unknown`, `tasks`)가 붙어 온다. hint 가 할 일을 알려 준다.
- 같은 묶음(Delivery)에 같은 `reply_to` 가 둘 이상이면 앞의 것만 처리한다(뒤의 것은 `duplicate: true`). `unknown` 이 비어 있지 않으면 결정하지 않는다(메인에 알린다).
- 답을 읽어 고칠 태스크와 사용자 요청을 정하고 결정을 한 번에 넘긴다: `hteam design-review --decide out-NNNN --json -` 의 표준 입력에 `{"fix": {"T-xxx": "<사용자 요청 원문>"}}`(여럿이면 태스크마다). 모두 승인이면 `{"fix": {}}`. 이름이 나오지 않은 태스크는 승인된다(사용자 결정). 고칠 태스크에 직간접으로 의존하는 승인 태스크는 다른 묶음에 있어도 hteam 이 더해 같은 요청과 함께 고친다. 어느 태스크를 고치라는지 모호하면 `hteam notify --type question` 으로 다시 묻고 그 답이 올 때까지 결정하지 않는다.
- hteam 은 결정(태스크마다 그때의 라운드와 요청)을 먼저 기록한 뒤 accept 와 수정 라운드를 만든다. 수정 라운드는 바로 띄우지 않는다(`launch_failed`, `queued`): `hteam start-ready` 가 선행의 수정 라운드가 다시 승인된 뒤에 띄운다. 결정을 다 하면 `applied` 도 hteam 이 적는다. 다음은 `hteam start-ready`.
- 결정이 이미 있으면(재시작, 다시 온 답) 같은 `hteam design-review --decide out-NNNN` 을 입력 없이 다시 부른다. 기록대로 이어 하고, 기록한 라운드가 지난 항목은 다시 하지 않는다. `status` 의 next 도 그 명령을 준다(그 태스크에 일반 fix·accept 를 하지 않는다). 다른 묶음의 결정이 끝나지 않았으면 exit 3 `decision_pending`: 그 결정을 먼저 마저 한다.
- `skipped` 에 끝난(done·dropped) 의존 태스크가 있으면 고치지 못한 것이다. 메인에 알린다(새 태스크로 고칠지 사용자가 정한다). 지목한 태스크가 끝났으면 exit 3 `decision_conflict` 로 아무것도 하지 않는다: 메인에 알리고 사용자가 정한 대로 그 태스크를 뺀 결정을 다시 준다.
- 다른 묶음의 결정이 이미 고친 태스크(라운드가 지났다)를 이 답이 지목해도 그대로 넘긴다. hteam 이 지금 라운드에서 새 요청(과 앞 요청)으로 다시 고친다.
- 결정이 끝나기 전에는 그 결정이 고치는 태스크와 의존 태스크를 `start`·`start-ready` 가 띄우지 않는다(start-ready 의 대기 사유 `decision`).
- 고친 태스크가 다시 승인되면(accept 뒤 awaiting_user) 새 라운드라 `hteam design-review` 가 다시 묻는다.
- `approval_stale`: 선행이 결정 밖에서 고쳐져 옛 선행을 보고 만든 승인 태스크다. design-review 가 묻지 않고 accept 가 받지 않는다. 메인에 알리고, 사용자가 정하면 `hteam fix T --note="…"` 로 다시 만든다.

## 요청 처리
```

**Edit** `herdr-team/templates/coordinator.md`

```markdown
- developer: 구현. tester: 테스트와 QA 보고서.
```

```markdown
- designer: 화면 디자인(화면마다 태스크 하나, `docs/design/screens/<화면>/`). 승인 직무라 리뷰 승인 뒤 accept 하면 `awaiting_user` 가 되고, 사용자 일괄 승인(`hteam design-review`, `--decide`) 뒤 `done` 이 된다. 그 화면을 구현하는 개발 태스크는 그 뒤에 시작된다.
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

설계를 같은 커밋에서 맞춘다(6.4 의 `--round`, 7.4 의 한 Delivery 안의 중복, 11.4 의 결정 기록).

**Edit** `docs/superpowers/specs/2026-11-05-herdr-team-design.md`

```markdown
- `hteam accept T`: `approved` → `done`
```

```markdown
- `hteam accept T [--round N]`: `approved` → `done`
```

**Edit** `docs/superpowers/specs/2026-11-05-herdr-team-design.md`

```markdown
`hteam fix T [--note "…"] [--supplement T-yyy] [--force-round] [--model …] [--effort …] [--worker …]`
```

```markdown
`hteam fix T [--note "…"] [--supplement T-yyy] [--force-round] [--round N] [--model …] [--effort …] [--worker …]`
```

**Edit** `docs/superpowers/specs/2026-11-05-herdr-team-design.md`

```markdown
- `max_rounds` 에 닿으면 코디네이터가 메인에 묻는다(계속 / 버림). 계속이면 `--note` 와 함께 `fix --force-round`(상한을 한 번 넘긴다).
```

```markdown
- `max_rounds` 에 닿으면 코디네이터가 메인에 묻는다(계속 / 버림). 계속이면 `--note` 와 함께 `fix --force-round`(상한을 한 번 넘긴다).
- `--round N`(`accept`·`fix`): 지금 라운드가 N 일 때만 한다(아니면 아무것도 바꾸지 않고 exit 3 `round_changed`). 일괄 승인 결정(11.4)을 다시 할 때 이미 한 항목을 다시 하지 않게 한다. `accept` 는 awaiting_user 인 승인 태스크가 stale(11.4)이면 마지막 전이 때 프로젝트 잠금 아래에서 다시 보고 exit 3 `approval_stale` 로 거부한다.
```

**Edit** `docs/superpowers/specs/2026-11-05-herdr-team-design.md`

```markdown
같은 답이 두 번 와서 둘 다 적용 전이면 둘 다 `duplicate: false` 이므로, 코디네이터는 같은 `out-id` 를 한 번만 처리하고 `applied` 를 기록한 뒤 나머지를 무시한다.
```

```markdown
같은 답이 두 번 와서 둘 다 적용 전이면: 한 Delivery 안이면 `hteam wait` 가 뒤 메시지를 `duplicate: true` 로 표시하고, Delivery 가 다르면 둘 다 `duplicate: false` 이므로 코디네이터는 같은 `out-id` 를 한 번만 처리하고 `applied` 를 기록한 뒤 나머지를 무시한다. 일괄 승인 답은 결정 기록(11.4)이 두 번 처리하지 않게 한다.
```

**Edit** `docs/superpowers/specs/2026-11-05-herdr-team-design.md`

```markdown
- 코디네이터가 답을 해석한다: 승인이면 `accept`(`awaiting_user` → `done`), 아니면 해당 태스크 `fix --note`, 그 태스크에 의존하는 승인 태스크도 이어서 `fix`.
```

```markdown
- 코디네이터가 답을 해석한다: 승인이면 `accept`(`awaiting_user` → `done`), 아니면 해당 태스크 `fix --note`, 그 태스크에 의존하는 승인 태스크도 이어서 `fix`. 수정 요청이 가리키지 않은 태스크는 승인으로 본다(모호하면 다시 묻는다). 해석한 것은 `hteam design-review --decide <out-id> --json -`(`{"fix": {태스크: 사용자 요청}}`, 모두 승인이면 빈 `fix`)로 넘긴다. hteam 은 결정을 한 번 계산해 묶음 기록에 먼저 쓴다: 고칠 태스크(지목된 태스크와 그것에 직간접으로 의존하는 승인 태스크 전부, 다른 묶음 포함, 리뷰 중·승인됨이어도)마다 그때의 라운드와 사용자 요청, 승인할 태스크마다 그때의 라운드. 아직 시작하지 않은 의존 태스크는 고칠 것이 없고(선행이 다시 승인된 뒤 시작한다), 끝난 의존 태스크는 고칠 수 없어 알린다. 그다음 기록대로 `fix --round`·`accept --round` 를 한다. 수정 라운드는 바로 띄우지 않는다(`launch_failed`, queued). `start-ready` 의 의존 검사(승인 직무 선행은 awaiting_user·done 이어야 끝난 것)가 선행의 수정 라운드가 다시 승인될 때까지 기다리게 한다. 다시 부르면(재시작·다시 온 답) 기록대로 이어 하고 기록한 라운드가 지난 항목은 다시 하지 않는다. 결정이 끝나지 않은 동안에는 다른 묶음의 결정과 새 질문을 하지 않고(`decision_pending`) `status` 의 next 가 그 결정을 다시 하는 명령이다. 시작 예약(프로젝트 잠금 안)은 끝나지 않은 결정이 고치는 태스크와 그 의존 태스크를 띄우지 않고, `start-ready` 는 의존도 다시 본다. 지목된 태스크의 라운드가 다른 결정 때문에 이미 바뀌었으면 처리한 것으로 넘기지 않고 지금 라운드에서 그 요청(과 그 라운드의 앞 요청)으로 다시 고친다. 지목된 태스크가 끝났으면 결정하지 않는다(`decision_conflict`, 메인에 알린다). done 을 쓴 뒤 applied 전에 멈췄으면 다시 부를 때 applied 를 적는다. 다 하면 hteam 이 `applied` 를 적는다. `hteam wait` 는 답에 `design_review`(묶음 태스크의 `pending`, 결정 상태, 상태를 읽지 못한 `unknown`)를 붙인다. 묶음 태스크의 상태 파일을 읽지 못하면 결정하지 않는다. 메인은 사용자가 `수정 요청` 을 고르면 무엇을 고칠지 물은 뒤 `수정 요청: <내용>` 한 줄로 답한다. 결정으로 연 라운드의 사양은 수정 블록에 "사용자 요청"으로 적는다.
```

- [ ] **Step 4: 통과 확인**

Run: `bash herdr-team/tests/run.sh -k test_approval -k test_coord -k test_lifecycle -k test_setup -k test_start`
Expected: OK(실패 없음). `test_lifecycle` 의 수정 블록 문구 검사(`코디네이터 메모: …`)는 그대로 통과한다. `test_start` 는 시작 예약의 새 검사가 기존 시작·복구를 막지 않는지 본다.

- [ ] **Step 5: 커밋(구현자는 여기서 멈춘다)**

```bash
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews' || true
git add -- herdr-team/lib/hteam/tasks.py herdr-team/lib/hteam/compose.py herdr-team/lib/hteam/approval.py \
  herdr-team/lib/hteam/coord.py herdr-team/templates/coordinator.md herdr-team/templates/CLAUDE.section.md \
  herdr-team/tests/test_approval.py docs/superpowers/specs/2026-11-05-herdr-team-design.md
git commit -m "feat(herdr-team): 승인 흐름 — 일괄 승인 결정 기록(--decide), queued 수정 라운드, --round, 답 주석

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/lib/hteam herdr-team/templates \
  herdr-team/tests/test_approval.py docs/superpowers/specs/2026-11-05-herdr-team-design.md
```

Expected: `git grep` 출력 없음, 커밋 성공. 컨트롤러가 `scripts/codex-review.sh commit HEAD` 를 돌리고 Global Constraints 의 Codex 규칙대로 처리한다.

---
### Task 5: 정리 — 변조 검사를 git 항목(모드·링크)으로, 경로를 손실 없이

1단계가 2단계로 넘긴 정확성 결함(진행 기록 "Final(2단계로, Codex r3·커밋 P2)")을 고친다. 설계 6.3 3 의 변조 검사가 놓치던 것:
- 심볼릭 링크: `hash_files` 가 링크를 따라가 내용만 견줬다. 추적 파일을 같은 내용의 바깥 파일을 가리키는 링크로 바꾸거나, 상위 폴더를 링크로 바꿔도 변조가 아니었다.
- 파일 모드: 실행 비트 변경을 보지 않았다. 리뷰어가 `core.fileMode` 를 바꿔 숨길 수도 있었다.
- 경로: `tracked_changes` 등이 text 모드로 읽어 `\r` 이 든 경로를 바꿔 읽었고(그 파일의 변경을 놓친다), 바뀐 경로가 UTF-8 이 아니면 디코딩 오류로 리뷰가 internal 로 멈췄다. 그런 경로를 상태 파일에 쓸 때도 실패했다.

고친 뒤: 기준점과 변조 검사는 git 이 보는 항목 `모드:객체 ID` 로 견준다(작업 트리·인덱스·트리 모두). 링크는 따라가지 않고(120000, 링크 글자의 blob) 상위 폴더가 링크면 git 처럼 없는 파일이다. 트리·인덱스의 모드는 늘 그대로 견준다(`git update-index --chmod` 로 스테이징한 실행 비트 변경도 변조다). `core.fileMode=false` 는 작업 트리의 실행 비트를 믿지 않는다는 뜻이라 그때 작업 트리 파일의 모드는 git 처럼 인덱스의 모드로 본다. 이 설정은 기준점 때의 값으로 고정한다. git 이 한 줄로 내는 경로(`--show-prefix`·`--show-toplevel`·`--git-path`)도 바이트로 읽고 마지막 LF 하나만 지운다(하위 프로젝트 폴더 이름의 `\r` 이 text 모드에서 바뀌면 프로젝트 안 변경을 밖으로 잘못 나눈다). git 출력의 경로는 모두 바이트로 읽어 `os.fsdecode` 로 풀고, JSON 은 `util.dumps`(짝 없는 서로게이트를 `\udcXX` 로), 사람이 읽는 글은 `util.show` 로 쓴다. 이 커밋 전에 만든 기준점은 값이 객체 ID 뿐이라 진행 중이던 그 리뷰 시도는 변조로 멈춘다(배포 전 중간 형식이라 옮기지 않는다. 사용자가 확인한 뒤 `review --retry`).

**Files:**
- Modify: `herdr-team/lib/hteam/gitio.py`(`run`, `_zb`, `log_since`, `commit_files`, `diff_names`, `dirty`, `file_mode`, `tracked_changes`, `index_entries`, `untracked`, `tree_entry`, `blob`, `_ref_present`, `_out_line`, `top_prefix`, `toplevel`, `worktree_entries`)
- Modify: `docs/superpowers/specs/2026-11-05-herdr-team-design.md`(6.3 3)
- Modify: `herdr-team/lib/hteam/review.py`(`_precheck_fail`, `_index`, `baseline`, `tamper_check`, `_warning_body`), `herdr-team/lib/hteam/util.py`(`dumps`, `show`, `write_json`), `herdr-team/lib/hteam/state.py`(`save`), `herdr-team/lib/hteam/cli.py`(출력), `herdr-team/lib/hteam/compose.py`(리뷰 프롬프트 경로)
- Test: `herdr-team/tests/test_review.py`(`TamperEntryTest`, `LosslessJsonTest`), `herdr-team/tests/test_plan.py`(`GitioTest`)

**Interfaces:**
- Consumes: 기존 `gitio.run`, `gitio.top_prefix`, `gitio.to_top`, `gitio.literal`, `state.save`, `review.tamper_check`
- Produces:
  - `gitio.file_mode(root) -> bool`(core.fileMode, 없으면 True), `gitio.tracked_changes(root, exec_bit=None)`(주면 `-c core.fileMode=…` 로 고정), `gitio.index_entries(root, paths) -> {경로: "모드:ID" | "단계:모드:ID,…" | None}`(옛 `index_blobs` 를 바꾼다, 모드는 그대로), `gitio.tree_entry(root, commit, path) -> "모드:ID" | None`, `gitio.blob(root, commit, path) -> ID | None`(그대로), `gitio.top_prefix(root)`(바이트로 읽는다), `gitio.toplevel(root) -> str`, `gitio.worktree_entries(root, paths, exec_bit=True, index=None) -> {경로: "모드:ID" | "dir" | "other" | None}`(옛 `hash_files` 를 바꾼다. exec_bit 가 거짓이면 일반 파일 모드는 `index`(root 기준 경로 → 인덱스 항목)의 모드).
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

    def test_staged_exec_bit_is_tamper_even_when_git_ignores_modes(self):
        # core.fileMode=false 는 작업 트리의 실행 비트만 믿지 않는다. 인덱스에 올린 모드 변경은 실제 변경이다
        self.git("config", "core.fileMode", "false")
        self.reviewing()
        self.git("update-index", "--chmod=+x", "README.md")
        self.assertEqual(self.assert_tamper("README.md")["tamper"]["paths"], ["README.md"])

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
        # 실행 비트를 믿지 않으면(core.fileMode=false) git 처럼 인덱스의 모드를 쓴다
        self.assertEqual(gitio.worktree_entries(self.proj, ["x.txt"], exec_bit=False)["x.txt"], f"100644:{blob}")
        self.assertEqual(gitio.worktree_entries(self.proj, ["x.txt"], exec_bit=False,
                                                index={"x.txt": f"100755:{blob}"})["x.txt"], f"100755:{blob}")
        self.assertEqual(gitio.tree_entry(self.proj, "HEAD", "x.txt"), f"100644:{blob}")
        self.assertEqual(gitio.blob(self.proj, "HEAD", "x.txt"), blob)

    def test_top_prefix_keeps_carriage_return_in_folder_name(self):
        # 하위 프로젝트 폴더 이름의 \r 이 text 모드로 \n 이 되면 그 안 변경을 프로젝트 밖(`../`)으로 잘못 나눈다
        sub = self.proj / "app\r"
        try:
            sub.mkdir()
        except OSError as exc:
            self.skipTest(f"이 파일 시스템은 \\r 이 든 이름을 만들지 못한다: {exc}")
        prefix = gitio.top_prefix(sub)
        self.assertEqual(prefix, "app\r/")
        self.assertEqual(gitio.from_top(prefix, "app\r/README.md"), "README.md")
        self.assertEqual(gitio.toplevel(sub), os.path.realpath(self.proj))

    def test_git_errors_are_not_answers(self):
```

- [ ] **Step 2: 실패 확인**

Run: `bash herdr-team/tests/run.sh -k TamperEntry -k LosslessJson -k test_index_entries -k test_worktree_entries -k test_top_prefix`
Expected: FAIL — 링크·링크 폴더·실행 비트(작업 트리·인덱스)·`\r` 경로의 변경이 승인으로 지나가고(`review_tampered` 가 아니다), 비 UTF-8 경로에서 `internal`(UnicodeDecodeError), `util.dumps`·`gitio.index_entries`·`gitio.worktree_entries` 가 없고, `top_prefix` 가 `app\n/` 을 낸다.

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


def _entry(mode: str, oid: str) -> str:
    """git 항목 `모드:객체 ID`. 트리·인덱스의 모드는 core.fileMode 와 상관없이 그대로다(설정은 작업 트리만 본다)."""
    return f"{mode}:{oid}"


def index_entries(root, paths: list[str]) -> dict[str, str | None]:
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
        item = _entry(mode, sha)
        found.setdefault(os.fsdecode(name), []).append(item if stage == "0" else f"{stage}:{item}")
    result.update({name: ",".join(items) for name, items in found.items() if name in result})
    return result


def untracked(root) -> list[str]:
    """root 아래의 추적하지 않는 파일(무시 규칙 적용), root 기준."""
    return sorted(_zb(run(root, "ls-files", "--others", "--exclude-standard", "-z", raw=True).stdout))


def tree_entry(root, commit: str, path: str) -> str | None:
    """commit 의 path(git 최상위 기준, 글자 그대로) 항목 `모드:객체 ID`. 없다고 확인되면 None. git 이 읽지 못하면(잘못된
    리비전, 손상·권한) git_failed 다. `rev-parse commit:path` 는 둘을 같은 exit 1 로 내서 ls-tree 를 쓴다."""
    out = run(root, "ls-tree", "-z", "--full-tree", commit, "--", literal(path), raw=True).stdout
    for entry in _zb(out):
        meta, _, name = entry.partition("\t")
        if name == path:
            mode, _, oid = meta.split()
            return _entry(mode, oid)
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
    return _out_line(run(root, "rev-parse", "--show-toplevel", raw=True).stdout)


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


def worktree_entries(root, paths: list[str], exec_bit: bool = True,
                     index: dict[str, str | None] | None = None) -> dict[str, str | None]:
    """root 기준 경로(`../` 포함)의 작업 트리 항목 `모드:객체 ID`(tree_entry·index_entries 와 견줄 수 있다). 없으면 None.

    git 이 보는 대로 본다. 심볼릭 링크는 따라가지 않는다: 120000 과 링크 글자의 blob 이다. 상위 폴더가 링크면 git 처럼
    그 파일은 없다. 일반 파일은 실행 비트로 100755·100644 와 git 필터를 적용한 hash-object 다. exec_bit 가 거짓이면
    (core.fileMode=false) git 처럼 실행 비트를 믿지 않고 index(root 기준 경로 → 인덱스 항목)의 모드를 쓴다(없거나
    충돌 중이면 100644). 폴더는 그 자리가 서브모듈 작업 트리면 160000 과 그 HEAD, 아니면 `dir`. 그 밖(FIFO 등)은 `other`.
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
            if exec_bit:
                mode = "100755" if info.st_mode & stat.S_IXUSR else "100644"
            else:
                mode = "100755" if ((index or {}).get(rel) or "").startswith("100755:") else "100644"
            regular.append((rel, name, mode))
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

git 이 한 줄로 내는 경로도 바이트로 읽는다(마지막 LF 하나만 지운다).

**Edit** `herdr-team/lib/hteam/gitio.py`

```python
def top_prefix(root) -> str:
    """root 의 git 최상위 기준 경로(`sub/` 꼴, 최상위면 빈 문자열). root 기준 경로를 blob 에 넘길 때 앞에 붙인다."""
    return run(root, "rev-parse", "--show-prefix").stdout.rstrip("\n")
```

```python
def _out_line(data: bytes) -> str:
    """git 이 한 줄로 내는 경로(바이트) → 글자. 출력 구분자인 마지막 LF 하나만 지우고 os.fsdecode 로 푼다(이름의 \\r·끝
    공백·UTF-8 이 아닌 바이트는 그대로)."""
    return os.fsdecode(data[:-1] if data.endswith(b"\n") else data)


def top_prefix(root) -> str:
    """root 의 git 최상위 기준 경로(`sub/` 꼴, 최상위면 빈 문자열). root 기준 경로를 blob 에 넘길 때 앞에 붙인다.
    바이트로 읽는다(text 모드는 폴더 이름의 \\r 을 \\n 으로 바꿔 프로젝트 안 경로를 밖으로 잘못 나눈다)."""
    return _out_line(run(root, "rev-parse", "--show-prefix", raw=True).stdout)
```

**Edit** `herdr-team/lib/hteam/gitio.py`

```python
    loose = run(root, "rev-parse", "--git-path", ref).stdout.strip()
```

```python
    loose = _out_line(run(root, "rev-parse", "--git-path", ref, raw=True).stdout)
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
def _index(p, prefix: str, paths: list[str]) -> dict[str, str | None]:
    """프로젝트 기준 경로의 인덱스 항목 `모드:객체 ID`(gitio.index_entries 는 최상위 기준 경로를 받는다)."""
    tops = {x: gitio.to_top(prefix, x) for x in paths}
    entries = gitio.index_entries(p.root, list(tops.values()))
    return {x: entries[t] for x, t in tops.items()}


def baseline(p, tid: str) -> dict:
    """변조 기준점(설계 6.1 5): HEAD, HEAD 와 다른 추적 파일(작업 트리·인덱스)의 작업 트리 항목과 인덱스 항목
    (`모드:객체 ID`), 추적 안 된 파일, 진행 중인 다른 태스크, git 이 작업 트리의 실행 비트를 보는지(exec_bit,
    core.fileMode. 거짓이면 작업 트리 파일의 모드는 인덱스의 모드다).
    경로는 프로젝트 기준이다. 추적 파일은 저장소 전체를 본다(프로젝트 밖은 `../`, 리뷰 동안 바뀌면 경고를 내려고).
    추적 안 된 파일은 프로젝트 안만 본다."""
    others = [s["id"] for s in state.all_states(p) if s["id"] != tid and s["status"] in ("working", "launch_failed")]
    prefix = gitio.top_prefix(p.root)
    exec_bit = gitio.file_mode(p.root)
    changed = _rel(prefix, gitio.tracked_changes(p.root, exec_bit))
    index = _index(p, prefix, changed)
    return {"at": now(), "head": gitio.head(p.root), "exec_bit": exec_bit,
            "dirty": gitio.worktree_entries(p.root, changed, exec_bit, index), "index": index,
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
    견주는 값은 git 항목 `모드:객체 ID` 다: 내용이 같아도 심볼릭 링크로 바꾸거나 실행 비트를 바꾸면 변조다. 트리·인덱스의
    모드는 그대로 견주고, 작업 트리의 실행 비트는 기준점 때의 core.fileMode 로 본다(false 면 인덱스의 모드). 값이 객체
    ID 뿐인 옛 기준점(이 형식 전)은 모두 달라 보여 변조로 멈춘다."""
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
    now_index = _index(p, prefix, changed)
    now_dirty = gitio.worktree_entries(p.root, changed, exec_bit, now_index)
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
            return gitio.tree_entry(p.root, commit, top)
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

설계 6.3 3 의 변조 판정에 비교 대상을 적는다(같은 커밋).

**Edit** `docs/superpowers/specs/2026-11-05-herdr-team-design.md`

```markdown
기준점 이후 새 커밋이 제외 경로 밖을 바꿨거나, 추적 파일 내용이 바뀌었으면 변조다.
```

```markdown
기준점 이후 새 커밋이 제외 경로 밖을 바꿨거나, 추적 파일 내용이 바뀌었으면 변조다. 내용은 git 항목(모드와 객체 ID)으로 견준다: 같은 내용이라도 심볼릭 링크로 바꾸거나 실행 비트를 바꾸면 변조다. 트리·인덱스의 모드는 그대로 견주고, 작업 트리의 실행 비트는 기준점 때의 `core.fileMode` 로 본다(false 면 git 처럼 인덱스의 모드). 상위 폴더가 링크면 git 처럼 그 파일은 없는 것이다. git 이 내는 경로는 바이트로 읽어 손실 없이 푼다.
```

- [ ] **Step 4: 통과 확인**

Run: `bash herdr-team/tests/run.sh -k test_review -k test_plan -k test_cli -k test_state_specs`
Expected: OK(실패 없음). macOS 에서는 `test_non_utf8_changed_path_is_kept_losslessly` 가 skip 없이 돈다(인덱스에만 넣으므로). 리뷰 흐름 전체는 다른 모듈도 쓰므로 Step 5 전에 `bash herdr-team/tests/run.sh` 를 백그라운드로 한 번 돌려 OK 를 확인한다.

- [ ] **Step 5: 커밋(구현자는 여기서 멈춘다)**

```bash
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews' || true
git add -- herdr-team/lib/hteam/gitio.py herdr-team/lib/hteam/review.py herdr-team/lib/hteam/util.py \
  herdr-team/lib/hteam/state.py herdr-team/lib/hteam/cli.py herdr-team/lib/hteam/compose.py \
  herdr-team/tests/test_review.py herdr-team/tests/test_plan.py docs/superpowers/specs/2026-11-05-herdr-team-design.md
git commit -m "fix(herdr-team): 변조 검사는 git 항목(모드·링크)으로 견주고 경로는 손실 없이 다룬다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/lib/hteam herdr-team/tests/test_review.py \
  herdr-team/tests/test_plan.py docs/superpowers/specs/2026-11-05-herdr-team-design.md
```

Expected: `git grep` 출력 없음, 커밋 성공. 컨트롤러가 `scripts/codex-review.sh commit HEAD` 를 돌리고 Global Constraints 의 Codex 규칙대로 처리한다.

---
### Task 6: 정리 — 코디네이터 루프와 메인 훅의 작은 결함

1단계 최종 리뷰가 2단계로 넘긴 것(진행 기록 "Final(2단계로)") 가운데 동작이 틀리거나 멈추는 것을 고친다. 하나하나는 작고 서로 다른 함수다.

1. **이어 붙인 워커가 이미 끝났으면 `next`**: 실행자가 horch 를 띄운 뒤 기록 전에 죽고 그 사이 워커가 done 했으면, 그 `worker_done` 은 태스크가 `launch_failed` 일 때 와서(`next` 는 `start`) 다시 오지 않는다. `start` 가 끝난 Dispatch 를 이어 붙여도 `next` 가 없어 코디네이터가 `wait` 시간 초과(최대 1시간)까지 기다렸다. 이제 `start`(와 `start-ready` 의 `started` 행)가 `review` 또는 `fix --note` 를 주고, 라운드 상한이면 `next` 없이 메인에 물으라는 `hint` 를 준다(`started` 행도 hint 를 버리지 않는다). review 의 이어 붙이기는 1단계에 이미 있다.
2. **Herdr 터미널 밖 메인의 Stop 훅**: `$HC_TERMINAL_ID` 가 없는 세션은 메인으로 판별되는데 `hteam watch` 는 exit 5 라 띄울 수 없다. Stop 훅이 매 턴 막았다. 이제 막지 않고 SessionStart 가 이유를 알린다.
3. **`commit_paths` 의 index.lock**: 같은 폴더의 워커가 커밋하는 순간 hteam 의 경로 지정 커밋(review-finish 판정, 사전 검사, plan apply)이 `index.lock` 으로 실패했다(힌트도 비었다). 이제 최대 `HTEAM_GIT_LOCK_WAIT`(10초) 동안 다시 하고, 그래도 안 되면 할 일을 알린다. 오류 문구를 300자로 자르기 전에 표시한다(git 의 긴 안내문 뒤로 `index.lock` 이 잘릴 수 있다).
4. **손상된 `applied.json`**: 빈 기록으로 읽어 적용한 답을 다시 처리할 수 있었고(같은 fix 를 두 번), `applied` 가 빈 기록으로 덮어써 기록을 잃었다. 이제 엄격히 읽는다: `applied` 는 exit 1 `bad_side_file` 로 덮어쓰지 않고, `wait` 의 답 주석은 `duplicate: null` 과 확인하라는 hint 를 준다.
5. **plan_incomplete 를 기획자에게 돌려보냄**: 앞선 `plan apply`(코디네이터)가 사양 일부만 커밋한 채 멈췄으면 planner 사전 검사가 그것을 기획자의 REQUEST_CHANGES 로 만들었다(기획자는 고칠 수 없다). 이제 `review` 가 아무것도 쓰지 않고 exit 3 `plan_incomplete` 로 코디네이터에게 알린다.
6. **`status` 가 손상된 `run.json` 을 숨김**: 없는 것처럼 보여 코디네이터가 없다고 판단하게 했다. 이제 `run_error` 로 보여 준다.

**Files:**
- Modify: `herdr-team/lib/hteam/dispatch.py`(`launch` 의 adopt 결과), `herdr-team/lib/hteam/tasks.py`(`run_work`, `_adopted_next`, `start_ready`), `herdr-team/hooks/hteam_hook.py`(`stop`, `session_start`), `herdr-team/lib/hteam/gitio.py`(import, `run`, `_wait_index`, `commit_paths`, `unstage`), `herdr-team/lib/hteam/outbox.py`(`applied_ids`), `herdr-team/lib/hteam/coord.py`(`_annotate_main`, `coordinator_view`, `status`), `herdr-team/lib/hteam/review.py`(`prechecks`)
- Modify: `herdr-team/templates/coordinator.md`, `herdr-team/skills/up/SKILL.md`, `docs/superpowers/specs/2026-11-05-herdr-team-design.md`(13장 표)
- Test: `herdr-team/tests/test_start.py`, `herdr-team/tests/test_hooks.py`, `herdr-team/tests/test_plan.py`, `herdr-team/tests/test_mainlink.py`, `herdr-team/tests/test_review.py`, `herdr-team/tests/test_coord.py`, `herdr-team/tests/test_setup.py`

**Interfaces:**
- Consumes: Task 3 의 `util.read_json_strict`, `util.bad_side_file`. Task 4 의 `coord._annotate_main`(design_review 주석을 붙이는 판). 기존 `dispatch.launch`, `outbox._run`.
- Produces:
  - `dispatch.launch` 의 adopt 결과에 `outcome`·`summary`. `tasks.run_work`·`start` 결과의 `next`(이어 붙인 Dispatch 가 `settled`·`retained`·`released` 면 `[".herdr-team/bin/hteam", "review", T]` 또는 `[..., "fix", T, "--note", "작업 실패: …"]`)와 `hint`, `start-ready` 의 `started[i].next`·`started[i].hint`.
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

    def test_start_ready_keeps_hint_for_failed_worker_at_round_limit(self):
        # 라운드 상한이면 fix 를 권하지 않고 메인에 물으라는 hint 만 준다. start-ready 의 started 행도 그것을 버리지 않는다
        (self.team / "config.toml").write_text(BASE_CONFIG.replace("max_rounds = 3", "max_rounds = 1"))
        self.make_task("T-001")
        self.assertEqual(self.hteam("start", "T-001", env={"HTEAM_TEST_DIE_AT": "after_launch"})[0], 137)
        [row] = self.horch_tasks()
        self.assertEqual(self.act(row["id"], {"done": {"outcome": "failed", "summary": "실패"}})[0], 0)
        code, out = self.hteam("start-ready")
        self.assertEqual(code, 0, out)
        [started] = out["started"]
        self.assertNotIn("next", started)
        self.assertIn("max_rounds", started["hint"])

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
        self.assertIn("`start-ready` 의 `started` 행에도 `next`·`hint` 가 붙을 수 있다", coord)
        self.assertIn("exit 3 `plan_incomplete`", coord)
        up = (ROOT / "skills/up/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("`run_error`", up)

    def test_no_personal_paths_or_trust_all(self):
```

- [ ] **Step 2: 실패 확인**

Run: `bash herdr-team/tests/run.sh -k test_adopting -k test_start_ready_keeps_hint -k test_main_outside_herdr -k index_lock -k AppliedRecord -k test_partial_plan_apply -k test_status_reports_corrupt_run_file -k test_cleanup_rules_in_docs`
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
                            "warnings": res["warnings"], **{k: res[k] for k in ("next", "hint") if res.get(k)}})
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
- `start`·`review` 결과와 `start-ready` 의 `started` 행에도 `next`·`hint` 가 붙을 수 있다(이어 붙인 워커가 이미 끝났다. 그 `worker_done` 은 다시 오지 않는다). `next` 가 있으면 그대로 실행한다. `next` 없이 `hint` 만 있으면 hint 대로 한다(라운드 상한이면 메인에 묻는다).
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

설계 13장 표에 두 경우를 더한다(같은 커밋).

**Edit** `docs/superpowers/specs/2026-11-05-herdr-team-design.md`

```markdown
| `launch_failed` | `hteam start T`(같은 라운드, 같은 horch Task 를 `--retry` 로) |
```

```markdown
| `launch_failed` | `hteam start T`(같은 라운드, 같은 horch Task 를 `--retry` 로) |
| 이어 붙인 작업 워커가 이미 끝남(기록 전 실행자 사망 뒤 done) | 그 `worker_done` 은 다시 오지 않는다. `start`(`start-ready` 의 `started` 행) 결과의 `next`(`review` 또는 `fix --note`)를 따르고, 라운드 상한이면 `hint` 대로 메인에 묻는다 |
| hteam 커밋이 워커 커밋의 `index.lock` 과 겹침 | 경로 지정 커밋이 10초까지 기다렸다 다시 한다. 그래도 남으면 메인에 알린다(지우지 않는다) |
```

- [ ] **Step 4: 통과 확인**

Run: `bash herdr-team/tests/run.sh -k test_start -k test_hooks -k test_plan -k test_mainlink -k test_review -k test_coord -k test_setup`
Expected: OK(실패 없음).

- [ ] **Step 5: 커밋(구현자는 여기서 멈춘다)**

```bash
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews' || true
git add -- herdr-team/lib/hteam/dispatch.py herdr-team/lib/hteam/tasks.py herdr-team/hooks/hteam_hook.py \
  herdr-team/lib/hteam/gitio.py herdr-team/lib/hteam/outbox.py herdr-team/lib/hteam/coord.py herdr-team/lib/hteam/review.py \
  herdr-team/templates/coordinator.md herdr-team/skills/up/SKILL.md herdr-team/tests \
  docs/superpowers/specs/2026-11-05-herdr-team-design.md
git commit -m "fix(herdr-team): 이어 붙인 워커의 next, 터미널 밖 Stop, index.lock 대기, applied 손상, plan_incomplete, run_error

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/lib/hteam herdr-team/hooks/hteam_hook.py \
  herdr-team/templates/coordinator.md herdr-team/skills/up/SKILL.md herdr-team/tests \
  docs/superpowers/specs/2026-11-05-herdr-team-design.md
```

Expected: `git grep` 출력 없음, 커밋 성공. 컨트롤러가 `scripts/codex-review.sh commit HEAD` 를 돌리고 Global Constraints 의 Codex 규칙대로 처리한다.

---
### Task 7: 실환경 확인 — 사용자가 인터뷰에 답하고 일괄 승인

설계 15.2·15.3 2단계 실환경: 사용자가 기획 인터뷰(체크리스트 질문과 확정 질문)에 답하고, 디자인 태스크들을 `design-review` 로 한 번에 승인한다. 버리는 시험 프로젝트에서 실제 Herdr·Claude·Codex 로 한 바퀴 돌리고 설계 15.4 에 기록한다. 마지막에 2단계 커밋 전체를 Codex 가 검토한다. 코드는 결함을 고칠 때만 바꾼다(고치면 그 결함을 재현하는 테스트를 먼저 더한다). main 병합은 하지 않는다(설계 15.3: 세 단계 뒤 0.1.0 으로 병합).

**Files:**
- Modify: `docs/superpowers/specs/2026-11-05-herdr-team-design.md`(15.4 에 2단계 결과)
- Modify: 결함이 나온 파일과 그 테스트

**Interfaces:**
- Consumes: Task 1–6 의 hteam(`design-review`, 승인 흐름, planner·designer 문서), 실제 `hc`·`herdr-app`·`claude`·`codex`
- Produces: 실환경 확인 기록, 2단계 브랜치 리뷰 반영

안전 규칙(1단계 Task 13 의 사용자 결정 그대로, 이 태스크 내내):
- 시험 프로젝트는 세션 스크래치패드 안에 만든다. 이 저장소와 사용자의 다른 프로젝트는 건드리지 않는다.
- 플러그인은 **시험 프로젝트 범위(project scope)에만** 등록·설치하고 끝나면 제거한다: 시험 프로젝트 폴더에서 `claude plugin marketplace add "$REPO_ROOT" --scope project`, `claude plugin install herdr-orch@herdr-team --scope project`, `claude plugin install herdr-team@herdr-team --scope project`. 사용자 범위(user scope)에 설치하지 않는다.
- `--permission-mode bypassPermissions` 는 이 버리는 시험 프로젝트의 `[agents.claude].args`(`--permission-mode=bypassPermissions`)와 시험용 메인 실행에만 쓴다. 실제 프로젝트에 같은 설정을 쓰지 않는다.
- 사용자의 hc core 를 멈추거나 다시 띄우지 않는다(`hc server stop` 금지). 시험이 만든 터미널만 kill·rm 한다.
- 시험용 `hc run` 은 늘 `--no-notify` 를 붙인다(끝날 때 종료 알림이 띄운 쪽 입력란에 들어가지 않게).
- Claude 의 처음 보는 폴더 신뢰 창(기본 "No, exit")은 `hc read` 로 커서를 본 뒤 `hc keys <터미널> down enter` 로 "Yes, I trust this folder" 를 고른다. Codex 폴더 신뢰 창은 "Trust and continue"(이 폴더만)를 고른다. **"Trust all" 류는 절대 고르지 않는다.** 키는 운영자(이 태스크를 하는 에이전트)만 누른다. 코디네이터는 누르지 않는다.
- 질문의 답: 운영자(이 태스크를 하는 에이전트)가 사용자 역할로 메인 pane 의 AskUserQuestion 에 `hc keys` 로 답한다(사용자 결정, 1단계와 같다). 답은 아래 단계에 적힌 대로 고른다.
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
- 첫 일괄 승인에서는 `수정 요청` 을 고른다. 메인이 무엇을 고칠지 대화로 묻는다 → 운영자가 "통계 화면의 완료율 숫자를 더 크게" 라고 답한다 → 메인이 `hteam answer <id> "수정 요청: <통계 화면 태스크 ID> 완료율 숫자를 더 크게"`. 코디네이터의 `wait` 결과에 `design_review`(두 태스크 `pending: true`)가 붙는다 → 코디네이터가 `hteam design-review --decide <id> --json -` 에 `{"fix": {"<통계 화면 태스크>": "완료율 숫자를 더 크게"}}` → 결정 기록(`state/design-review.json` 의 `decision`) → 통계 화면은 queued 수정 라운드(r2, 사양 수정 블록에 "사용자 요청"), 목록 화면은 accept → `done`(둘 사이에 의존이 있으면 의존하는 쪽도 같은 요청과 함께 queued 된다) → `start-ready` 가 r2 를 띄운다. developer 태스크는 통계 화면이 done 이 아니라 아직 기다린다.
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

- [ ] **Step 8: 15.4 에 결과 기록**

설계 동기화(6.3·6.4·7.4·11.2·11.4·13장)는 그 동작을 바꾼 Task 1·3·4·5·6 의 커밋에 이미 들어 있다. 실환경에서 설계와 다른 것을 찾았으면 고친 커밋에서 함께 고친다.

15.4 의 1단계 기록 뒤(16장 앞)에 결과를 더한다. 아래 틀의 `<…>` 를 실제 관찰로 채운다(채우지 않은 칸을 남기지 않는다):

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
git commit -m "docs: herdr-team 2단계 실환경 확인 결과

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- docs/superpowers/specs/2026-11-05-herdr-team-design.md
P2_BASE="$(git log --diff-filter=A --format=%H -- docs/superpowers/plans/2026-11-06-herdr-team-p2.md | tail -1)"
scripts/codex-review.sh base "$P2_BASE"
```

Expected: 두 테스트 모음 OK, `git grep` 출력 없음, 커밋 성공. `codex-review.sh` 가 리뷰 pane 의 주소를 출력한다. `hc wait <주소> --timeout 3600` 을 백그라운드로 건다. 결과 `.codex-reviews/base-<sha>.md` 의 지적은 Global Constraints 의 Codex 규칙대로 처리한다(고칠 때마다 재현 테스트를 먼저 더하고 커밋하고 그 커밋을 리뷰. 최대 3 라운드).

- [ ] **Step 10: 2단계 마무리 보고**

main 에 병합하지 않는다(3단계 뒤). 사용자에게 실환경 결과, 남은 것(Step 7), Codex 가 무엇을 지적했고 무엇을 고쳤는지, 무엇을 왜 고치지 않았는지, 3단계로 넘길 것(아래 "2단계에 넣지 않은 것")을 보고한다.

---
## 자체 검토: 설계 대응표(15.3 2번)

계획의 코드는 이 저장소(1f35fb7)를 새로 복사한 작업 트리에 Task 1–7 의 편집을 처음부터 차례로 적용해 확인했다(Codex 계획 리뷰 r1–r4 반영 뒤 다시). 편집 지시는 모두 정확히 한 번씩 맞았다. 태스크 커밋마다 그 태스크의 Step 4 테스트와 Python 3.11 문법 검사(`ast.parse(..., feature_version=(3, 11))`, 모든 .py 와 진입점)를 돌렸다. Task 2·5·6 은 구현 전에 새 테스트가 실패하는 것도, r1 의 지적 7건(P1 중복 답·LF, P2 기록 검사·인덱스 모드·top_prefix·이력 render·started hint)은 옛 계획 코드에서 새 테스트가 실패하는 것도 확인했다. r2 의 지적은 결정 기록 회귀 테스트(기록 뒤·첫 fix 뒤 죽음과 재생, 다른 묶음 의존 태스크와 재전달, 선행이 끝나기 전 의존 태스크를 띄우지 않음, accept 마지막 전이의 재확인)로 덮었다. r3 의 지적 4건은 새 회귀 테스트 6개가 r2 계획 코드에서 실패하는 것으로 재현했다. r4 의 지적은 새 회귀 테스트 2개가 r3 계획 코드에서 실패하는 것으로 재현했다(복구 뒤 basis 가 `{T-001: 4}` 로 덮였고 accept 가 거부 없이 통과했다). 마지막에 두 테스트 모음 전체: herdr-team 473, herdr-orch 202, 모두 OK(1단계 끝은 412·202).

| 설계 | 내용 | 태스크 |
|---|---|---|
| 10 | 짧은 질문을 하나씩 `ask-user` 로, 선택 질문에 예시·추천안·추천 사유, 모순은 따로 묻기 | 1단계 planner.md(그대로) |
| 10 | 체크리스트 12항목, "결정"·"범위 밖"이 될 때까지(질문 수 제한 없음), 뻔한 항목은 "자동 결정" | 2(`## 인터뷰 체크리스트`, `interview.md` 표) |
| 10 | 마지막 질문은 확정: `context` 에 계획 핵심·자동 결정·태스크 그래프 표, 선택지 "확정 (추천)" / "수정할 부분 있음" | 2(`## 확정 질문`, 예시가 render 검사를 통과하는 테스트, 리뷰어가 `--history` 의 `render` 로 확인) |
| 10 | 결과물 spec·contracts·tasks.toml·interview.md, 끝내기 전 `plan check` 통과 | 2(산출물 절), 1단계(planner 사전 검사) |
| 10 | 수정 라운드의 기획자는 `--pending` 과 열린 질문의 `--wait` 를 먼저 확인 | 2(planner.md, 수정 블록 문구, 라운드를 넘는 열린 질문 테스트) |
| 10 | 인터뷰는 프로젝트마다 하나 | 1단계(`planner_busy`) |
| 4, 4.2 | `user_approval_roles = ["designer"]`, designer owns, director·designer 는 claude 만 | 1(템플릿), 1단계(검사) |
| 5.2 | 승인 직무 사이 의존 + owns 겹침 거부 | 1단계(plan check), 1(템플릿 설정으로 다시 확인), 2(planner.md 안내) |
| 5.3 | awaiting_user 는 잠금을 쥔다, 의존 끝 조건(승인 → 승인은 awaiting_user 도 끝) | 1단계(`state.LOCKING`, `deps_met`), 3(`view` 가 같은 조건을 쓴다) |
| 6.4 | accept: approved → awaiting_user(승인 직무) → done. fix: awaiting_user 에서 상한을 보지 않는다 | 1단계 + 4(accept 의 `next`, 수정 블록의 사용자 요청, `--round`, 마지막 전이의 stale 재확인) |
| 7.2, 7.4 | approval 항목, render 검사, answer(파일 먼저 → send), applied, duplicate(같은 out-id 는 한 번) | 3(approval 항목을 쓴다), 1단계(answer·applied), 4(`design_review` 주석, 한 Delivery 안의 중복), 6(applied 손상) |
| 7.6 | 답이 없는 approval 은 열린 질문, `reask` | 1단계(`open_questions`), 3(테스트가 열린 질문을 확인) |
| 11.2 | designer 기본: 화면마다 태스크, owns, 화면 원본, 보고서 항목, 승인 직무 | 1(designer.md), 2(tasks.toml 안내) |
| 11.4 | `design-review` 조건(진행 중·지금 시작할 수 있는 승인 태스크 없음), 그 순간의 awaiting_user 전부, 승인 → 비승인 → 승인은 다음 묶음, context 한 줄과 링크(design_system_url 제외), 선택지, 이미 물었으면 exit 3, `state/design-review.json` | 3 |
| 11.4 | 답 해석: 승인 → accept, 아니면 그 태스크 fix --note, 의존하는 승인 태스크도 fix | 4(결정 기록 `--decide`, queued 수정 라운드, 주석·hint·coordinator.md·설계), 3(stale 은 읽기만 하는 검사) |
| 8.3 | 명령 표의 `design-review`(코디네이터) | 3 |
| 13 | status 의 next(awaiting_user), 오류·복구 | 4(next), 6(이어 붙인 워커의 next·hint, index.lock, run_error, 13장 표) |
| 15.2 | 실환경: 사용자가 인터뷰에 답하고 일괄 승인 | 7 |

### 설계에서 정하지 않아 계획이 정한 것

- 인터뷰 장치는 코드가 아니라 직무 문서와 리뷰 기준이다(설계 10장 "직무 문서가 규칙을 담는다"). 확정 답을 받았는지 hteam 이 기계적으로 검사하지 않는다(설계 6.1 의 사전 검사 목록에 없다). 대신 리뷰어가 `hteam ask-user --task T --history` 로 실제 질문과 답을 확인한다. 이 명령은 읽기 전용이라 리뷰어 규칙 안이다.
- `interview.md` 형식: 맨 위에 체크리스트 표(`#`·항목·상태·근거), 상태는 `미정`·`결정`·`자동 결정`·`범위 밖`. 확정 답 뒤에 문서를 바꾸면 확정을 다시 묻는다.
- 일괄 승인 선택지 label 은 `모두 승인 (추천)` / `수정 요청` 이다(사용자 결정. render 규칙이 추천안 label 끝에 `(추천)` 을 요구한다).
- 한 (태스크, 라운드)는 한 번만 묻는다. 이미 물은 태스크가 답을 기다리는 동안 새로 awaiting_user 가 된 태스크는 새 묶음에 그것만 넣는다(같은 태스크를 두 질문에 넣지 않는다). 수정 라운드는 다시 묻는다.
- 링크: 보고서의 마지막 `https://claude.ai/…` URL. `design_system_url` 이 든 줄과 `docs/design/direction.md` 의 `design_system_url` 값은 뺀다. 없으면 보고서 경로를 보인다. context 가 4000자를 넘으면 뒤 태스크는 ID 만 적는다.
- `design-review` 오류: exit 2 `no_approval_roles`, exit 3 `nothing_to_approve`·`approval_stale`·`already_asked`·`approval_not_ready`, exit 1 `bad_side_file`(기록 손상·모양 오류·중복, 덮어쓰지 않는다)·`bad_state_file`(읽지 못하는 상태 파일이 하나라도 있으면 묶음을 나누지 않는다). 코디네이터만 부른다. 프로젝트 잠금 안에서 기록 → outbox → id 순서로 쓴다. 같은 묶음 항목 찾기는 `outbox.append` 의 잠금 안에서(LF 만 빠진 마지막 줄을 완결한 뒤) 한다.
- 일괄 승인 답의 처리는 결정 기록 하나다(Codex 계획 리뷰 r2 뒤 단순화): 코디네이터가 해석한 `{"fix": {태스크: 사용자 요청}}` 을 `design-review --decide` 에 넘기면 hteam 이 프로젝트 잠금 안에서 한 번 계산해 먼저 기록한다. 고칠 태스크 = 지목된 묶음 태스크 + 그것에 직간접으로 의존하는 승인 태스크 전부(다른 묶음 포함, 리뷰 중·승인됨이어도), 각자 그때의 라운드와 요청(의존 태스크는 선행의 요청을 함께 적는다). 승인할 태스크 = 묶음의 나머지. 시작 안 한 의존 태스크는 고칠 것이 없다(선행이 다시 승인된 뒤 시작한다). 끝난 의존 태스크는 고칠 수 없어 알린다. 그다음 기록대로 `fix --round`(queued: 띄우지 않는다)·`accept --round` 를 한다. 다시 부르면 기록대로 이어 하고, 기록한 라운드가 지난 항목은 한 것이다. 사용자 결정(라벨, 이름 없는 태스크는 승인, 의존 승인 태스크도 고침)은 그대로다. 메인은 `수정 요청` 을 고르면 무엇을 고칠지 대화로 물은 뒤 `수정 요청: <내용>` 한 줄로 답한다.
- 순서: queued 수정 라운드는 `start-ready` 의 기존 의존 검사(`tasks.deps_met`: 승인 직무 선행은 awaiting_user·done 이어야 끝난 것)가 선행의 수정 라운드가 다시 승인될 때까지 띄우지 않는다. `status` 는 queued 라운드에 `start-ready` 를 권한다(`start T` 는 의존을 보지 않는다). 끝나지 않은 결정이 있으면 다른 묶음의 결정과 새 질문을 하지 않고(`decision_pending`), 그 항목 태스크의 next 는 `design-review --decide <out-id>` 다.
- 다시 온 답이 일을 두 번 하지 않게: accept·fix 에 `--round N`(지금 라운드가 N 일 때만, 아니면 exit 3 `round_changed`)이고 결정은 기록한 라운드로만 부른다. 한 Delivery 안의 같은 out-id 는 `wait` 가 뒤 메시지를 `duplicate: true` 로 표시한다(설계 7.4 의 "한 번만 처리"). 상태를 읽지 못한 태스크가 있으면 결정하지 않는다.
- stale(줄였다): 승인 태스크의 선행(직간접)이 이 태스크의 현재 라운드를 띄운 뒤에 새 라운드를 열었으면 옛 선행을 보고 만든 것이다. 기준은 그 라운드의 워커를 새로 띄울 때 본 선행 라운드(`basis`)다. 시작 예약(`tasks._begin`, 프로젝트 잠금 안)이 본 라운드를 실행 기록 `work.pred_rounds` 에 적고, `dispatch.launch` 가 기존 horch Task 없이 새로 띄울 때(fresh)만 `launched` 와 같은 저장에서 `basis` 로 옮긴다. 같은 라운드 복구가 기존 Dispatch 를 이어 붙이거나(adopt) 다시 띄우면(retry) 처음 것 그대로다(retry 는 그 사이 선행이 바뀌었으면 stale 로 보는 쪽이 안전하다). queued 라운드는 띄울 때 기록하므로, 기다리는 동안 선행이 리뷰에서 한 번 더 고쳐져도 최신 선행을 보고 만든 결과는 stale 이 아니다. basis 가 없는 옛 라운드만 라운드를 연 시각(history 의 `start`·`fix`, 같은 초면 함께 고친 것)으로 본다. 결정이 의존 태스크를 함께 고치므로 이것은 결정 밖에서 선행을 고친 경우뿐이다. 그래서 읽기만 하는 검사로 둔다: design-review 가 묻지 않고(exit 3 `approval_stale`), accept 가 마지막 전이에서 프로젝트 → 태스크 잠금 아래 다시 보고 거부하고, 결정이 그런 태스크를 승인하지 않는다. 자동으로 fix 를 권하지 않는다(메인에 알린다).
- accept 가 awaiting_user 로 가면 `next` 가 `design-review` 다(그 전에 `start-ready` 를 하라는 hint). status 는 awaiting_user 에 묻지 않았고 막는 승인 태스크가 없을 때만 `next` 를 준다.
- designer 기본형: 화면 원본은 `docs/design/screens/<화면>/index.html`(외부 리소스 없이)·`notes.md`. claude.ai 아티팩트는 쓸 수 있을 때만(워커 pane 에서 Artifact 도구를 쓸 수 있는지 보장되지 않는다).
- 설정 템플릿은 designer 를 기본으로 담고 `user_approval_roles = ["designer"]` 다(사용자 결정, 설계 4장 예시와 같다). 화면이 없는 프로젝트면 init 이 빼자고 제안한다.
- developer 직무 문서: 패키지는 임시 venv(또는 프로젝트의 격리 환경)에서만 설치한다. 전역·시스템 Python 과 `--user` 는 쓰지 않는다(사용자 결정).
- `ask-user --history` 항목에 원래 질문 `render` 를 더한다(리뷰어가 확정 질문의 context 를 tasks.toml 과 견준다).
- 변조 검사의 실행 비트: 트리·인덱스 모드는 늘 그대로 견준다. `core.fileMode=false` 면 작업 트리 파일의 모드는 git 처럼 인덱스의 모드다.
- 변조 검사의 옛 기준점(값이 객체 ID 뿐): 옮기지 않는다. 업그레이드 때 진행 중이던 리뷰 시도는 변조로 멈추고 사용자가 확인한 뒤 `review --retry` 한다(배포 전 중간 형식, 1단계의 옛 pending·attention 형식과 같은 판단).
- `index.lock` 대기는 10초(`HTEAM_GIT_LOCK_WAIT`). 잠금 파일은 지우지 않는다.

### Codex 계획 리뷰 r1(P1×4, P2×6) 반영

| 지적 | 판단 | 반영 |
|---|---|---|
| P1 같은 Delivery 의 중복 답이 fix 를 두 번 한다 | 맞다(같은 스냅숏으로 둘 다 pending) | Task 4: `wait` 가 뒤 메시지를 duplicate 로, accept·fix `--round`, 테스트 |
| P1 선행만 고치고 죽으면 의존 태스크를 승인한다 | 맞다(재전달 시 선행이 pending 이 아님) | Task 3 stale + Task 4 accept 거부·status next·hint 순서(묶음 전체로 대상 확정), 테스트 |
| P1 다른 묶음의 의존 태스크가 수정에서 빠진다 | 맞다 | Task 4 `dependents` 를 프로젝트 전체에서, stale 이 그 묶음의 옛 답 적용을 막는다, 테스트 |
| P1 LF 만 빠진 outbox 끝이면 같은 질문을 두 번 쓴다 | 맞다(잠금 밖에서 찾음) | Task 3 `outbox.append(reuse=)` 로 같은 잠금 안에서 찾기, 테스트 |
| P2 읽지 못한 상태를 처리한 것으로 본다 | 맞다 | Task 4 reply_view 의 엄격 읽기·`unknown`, hint 가 applied 를 막는다, 테스트 |
| P2 승인 기록의 필수 필드를 검사하지 않는다 | 맞다 | Task 3 `load` 가 필드·타입·render·중복을 검사, 테스트 |
| P2 core.fileMode=false 가 인덱스의 모드 변경을 숨긴다 | 맞다 | Task 5 트리·인덱스 모드는 그대로, 작업 트리만 인덱스 모드로, `update-index --chmod` 테스트 |
| P2 top_prefix 가 text 모드다 | 맞다(`--git-path`·`--show-toplevel` 도 같은 결함) | Task 5 `_out_line` 으로 셋 다 바이트로, 테스트 |
| P2 이력에 확정 질문의 context 가 없다 | 맞다 | Task 2 `--history` 에 `render`, planner 리뷰 기준, 테스트 |
| P2 start-ready 가 상한 hint 를 버린다 | 맞다 | Task 6 `started` 행에 hint, coordinator.md, 테스트 |

### Codex 계획 리뷰 r2(P1×3, P2×1) 반영

r1 의 10건 가운데 8건은 해결로 판정됐고, 의존 승인 2건이 부분 해결이었다. 새 지적은 모두 의존 승인 장치(stale 자동 수정·현재 라운드 계산)에서 나왔다. 가드를 더하지 않고 장치를 결정 기록 하나로 바꿨다(Task 4).

| 지적 | 판단 | 반영 |
|---|---|---|
| P1 재시작의 stale 자동 수정이 사용자 요청 일부를 잃는다 | 맞다(status next 가 일반 메모로 fix) | 사용자 요청은 결정 기록에 있고, 결정 항목 태스크의 next 는 `--decide` 재생이다. stale 은 fix 를 권하지 않는다. 테스트: 기록 뒤·첫 fix 뒤에 죽고 다시 해도 두 태스크의 요청이 다 사양에 있다 |
| P1 의존 수정 워커가 선행 수정이 끝나기 전에 뜬다 | 맞다(fix 는 의존을 보지 않는다) | 결정의 수정 라운드는 queued 로 만들고 `start-ready` 의 의존 검사가 띄운다. 테스트: 선행이 working 인 동안 start-ready 가 의존 태스크를 `deps` 로 기다리게 하고, 선행이 awaiting_user 가 된 뒤에만 띄운다 |
| P1 재전달 때 의존 태스크의 현재 라운드를 쓴다 | 맞다 | 결정이 처음 계산할 때의 라운드를 기록하고 재생은 그 라운드로만 한다. 테스트: 다른 묶음의 의존 태스크를 고친 뒤 첫 답을 다시 해도 r3 가 열리지 않고, 둘째 묶음의 모두 승인도 그 태스크를 승인하지 않는다 |
| P2 accept 의 stale 검사가 마지막 전이 전에 낡는다 | 맞다 | 마지막 전이에서 프로젝트 → 태스크 잠금 아래 다시 본다. 테스트: accept 를 사전 처리 뒤에 멈추고 선행 라운드를 바꾸면 거부한다 |

### Codex 계획 리뷰 r3(P1×2, P2×2) 반영(사용자가 4번째 라운드를 허락했다)

| 지적 | 판단 | 반영 |
|---|---|---|
| P1 다른 묶음의 별도 수정 요청을 처리 완료로 버린다 | 맞다(지목된 태스크의 라운드가 다른 결정으로 바뀌면 빠졌다) | 지목된 태스크는 라운드가 바뀌었어도 지금 라운드에서 새 요청(과 그 라운드의 앞 요청)으로 다시 고친다. 끝난 태스크를 지목하면 `decision_conflict`(쓰지 않고 applied 하지 않는다). 테스트: 둘째 묶음이 같은 태스크에 따로 요청하면 r3 에 두 요청이 다 있고, 어느 답을 다시 해도 r4 가 열리지 않는다 |
| P1 의존 검사와 시작 사이에 결정이 끼면 선행보다 먼저 뜬다 | 맞다(시작 예약이 의존을 다시 보지 않았다) | 시작 예약(프로젝트 잠금 안)에서 끝나지 않은 결정이 고치는 태스크·그 의존 태스크를 막고 start-ready 는 의존도 다시 본다. 결정 밖의 fix 도 같은 검사. 테스트: start-ready 를 의존 검사 직후에 멈추고 결정을 끼우면 띄우지 않는다(`deps`), 결정 기록 직후에는 `decision` 으로 기다린다 |
| P2 queued 생성 시각 때문에 최신 선행을 본 결과도 stale | 맞다 | stale 기준을 실제로 띄울 때 기록한 선행 라운드(`basis`)로 바꿨다. 테스트: 선행이 r3 로 다시 고쳐진 뒤 띄운 의존 태스크는 stale 이 아니다 |
| P2 done 직후 죽으면 applied 가 복구되지 않는다 | 맞다(안내가 ack 뿐) | 답 주석에 `applied`, done 인데 applied 가 없으면 안내가 `--decide` 재호출. 테스트: done 과 applied 사이에서 죽고 다시 받는다 |

### Codex 계획 리뷰 r4(P1×1) 반영(사용자가 5번째 라운드를 허락했다)

| 지적 | 판단 | 반영 |
|---|---|---|
| P1 같은 라운드 복구가 기존 결과의 선행 기준(basis)을 덮어쓴다 | 맞다(복구가 지나는 `_begin` 이 basis 를 지금 선행 라운드로 다시 쓰는데 `dispatch.launch` 는 옛 Dispatch 를 adopt 했다. r3 계획 코드에서 basis 가 `{T-001: 4}` 로 덮였고 accept 가 그대로 통과했다) | `_begin` 은 시작 예약에서 본 라운드를 실행 기록 `work.pred_rounds` 에만 적는다. `dispatch.launch(on_fresh=)` 가 새로 띄울 때(fresh)만 `launched` 와 같은 저장에서 그것을 `basis` 로 옮긴다(adopt·retry 는 부르지 않는다. 리뷰 Dispatch 는 넘기지 않는다). 띄우는 순간이 아니라 예약 때 읽은 것을 옮기는 까닭: 예약(start-ready 는 의존 검사와 같은 잠금)과 띄우기 사이에 선행이 고쳐지면 아직 결과가 없는 새 라운드를 본 것으로 적어 stale 을 놓친다. 설계 11.4 의 기준 문장도 같은 커밋(Task 3)에서 고쳤다. 테스트: `after_launch` 에서 죽고 선행이 r4 로 고쳐져 승인된 뒤 복구가 adopt 하면 basis 는 r3 그대로이고 design-review(Task 3)·accept(Task 4) 모두 `approval_stale`. `after_child`(워커가 뜨지 않았다) 뒤 복구는 fresh 라 basis 가 r4 다 |

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
