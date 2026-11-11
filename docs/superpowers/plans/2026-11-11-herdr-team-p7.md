# herdr-team 7단계(작업 공간·Redmine·보완 요청) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 설계 15.3 의 7번을 만든다: 다른 프로젝트가 보낸 보완 요청서(2026-11-11)를 검토해 받은 것(설계 1장 "보완 요청 처리 (7단계)" 표)이다. 병렬 개발용 작업 공간(`[workspace] mode = "worktree"`: 개발 단계 직무 태스크를 슬롯 worktree·태스크 브랜치에서 돌리고 accept 때 기준 브랜치에 `--no-ff` 로 병합한다, 슬롯마다 시험 환경 변수와 setup·teardown), tester 시험 경로 `[test] tester_paths` 와 `full_if`, 리뷰의 프로젝트 점검표(`.herdr-team/review-extra.md`)·우선순위 줄·재검증 문구, 선택 적용 Redmine 연동(`[redmine]`, 관제가 이슈 상태·노트를 바꾼다), herdr-orch 의 워커 환경 변수(`worker-start --env`)다. 한 주기로 herdr-orch 0.2.0 → 0.3.0, herdr-team 0.4.0 → 0.5.0 이다. 새 기능은 설정이 있을 때만 켜진다: 설정이 없는 프로젝트는 0.4.0 과 같이 돈다(회귀 시험으로 지킨다). 실환경은 설계 15.2 의 7단계(사전 검증 S2, 작업 공간 흐름, 가짜 Redmine 서버, shared 회귀)를 본다. main 병합은 계획 밖이다(컨트롤러가 한다).

**Architecture:** herdr-orch 는 `worker-start --env KEY=VALUE`(되풀이)를 받아 스키마 v4 의 `dispatches.env` 에 JSON 으로 기록하고, `launch-guard` 가 가드 등록 뒤 `os.execvp` 바로 앞에서 `os.environ` 에 더한다(`hc run` 터미널은 부른 셸 환경을 물려받지 않는다). herdr-team 은 새 모듈 둘을 더한다. `workspace.py` 는 작업 공간이다: `state/slots.json`(슬롯 `free`·`preparing`·`busy`·`dirty`)과 슬롯 잠금(`state/slots/slot-<N>.lock`), 슬롯 폴더 `.herdr-team/state/slots/slot-<N>`(저장소 전체의 worktree), 태스크 브랜치 `herdr/T-xxx`, 작업 루트의 표시 파일 `.herdr-team/state/slot.json`(`{main_root, slot, task}`)이다. `start` 는 프로젝트 잠금 안에서 슬롯을 예약만 하고(예약이 owns 잠금을 쥔다) 대기 사유 `slot_setup` 으로 돌아오며, 관제가 자식 `hteam slot prepare T` 로 폴더·브랜치·표시 파일·setup 을 하고(슬롯 잠금을 쥔 채), 다음 `start` 가 슬롯을 `busy` 로 바꾸고 horch 를 `--cwd <작업 루트> --env <슬롯 env>` 로 부른다. 리뷰의 git 조회·관문 테스트·리뷰 커밋·변조 기준점·리뷰어는 작업 루트에서 돈다. accept 는 관제가 메인 폴더에서 `git merge --no-ff` 로 병합한 뒤 `done` 이고(거부면 다시 시도, 10분 넘으면 `workspace_failed`(`merge_blocked`)), 충돌이면 되돌리고 `changes`·`base_merge`·base 이동·decide `merge_conflict` 다. 기준 병합 라운드는 사양에 병합 지시를 넣고 리뷰 시작이 그 병합 커밋을 보면 `base_merge` 를 지운다. 놓기(teardown → 작업 트리 검사 → `git switch --detach` → 브랜치 지우기 → `free`, 끝나지 않은 병합·버린 태스크의 변경이 있으면 `dirty`)와 마무리 full(빈 슬롯에서)도 슬롯 잠금을 쥔 자식이다. `hteam` 과 훅은 슬롯 안에서 불려도 표시 파일로 상태 루트(메인)와 작업 루트(슬롯)를 나눈다. `redmine.py` 는 Redmine 이다: 관제가 사건마다 `state/redmine/queue/<순번>.json` 을 쓰고, 자식 `hteam redmine-sync` 만 키를 읽어 순번 순으로 `PUT /issues/<N>.json` 을 보낸다(2xx 지움, 4xx `failed/`, 연결 실패·5xx 는 1·2·5·10분 뒤 다시, 24시간이면 `failed/`). 리뷰 프롬프트는 우선순위 줄·`## 프로젝트 점검표`·이슈 줄을, 라운드 절 2 는 재검증 범위를, 워커 사양은 우선순위 줄·작업 공간 절·이슈 줄·`full_if` 줄을 더한다. 테스트 관문은 developer 태스크가 바꾼 경로가 `full_if` 에 맞으면 quick 대신 full 을 돈다.

**Tech Stack:** Python 3.11+ 표준 라이브러리(sqlite3, tomllib, json, fcntl, signal, subprocess, re, urllib.request, http.server(시험), threading(시험), unittest, unittest.mock), git 2.23 이상(`git worktree`·`git switch`·`git merge`), herdr-core `hc`(시험은 가짜), Claude Code·Codex CLI(실환경 Task 10 만).

**설계 문서:** `docs/superpowers/specs/2026-11-05-herdr-team-design.md`(이하 "설계")와 `docs/superpowers/specs/2026-11-04-herdr-orch-design.md` 14장(이하 "orch 설계"). 7단계 범위는 설계 15.3 의 7번이다. 함께 볼 절: 1장(7단계 사용자 결정 표, 보완 요청 처리 표), 4.1 `[workspace]`·`[redmine]`, 4.2 검사, 5.1·5.2 의 `issue`·`tester_paths`, 5.5 의 8·작업 규칙 줄, 5.6, 5.7 의 `full_if`·작업 공간, 5.9.4 의 0, 5.10 전체, 6.1·6.2·6.4 의 7단계 줄, 7.7 의 decide 두 줄·메인 규칙 줄, 8.8·8.10·8.11 의 7단계 줄, 8.12, 9.1 의 4a, 9.2, 13·14장의 7단계 줄, 15.2(S1 결과·S2·실환경), 15.3 의 7, 16장. 계획과 설계가 다르면 설계가 맞다. 다르면 멈추고 사용자에게 묻는다. 설계에 없는 방어 코드를 더하지 않는다. 설계가 정하지 않아 계획이 정한 것은 맨 뒤 "설계에서 정하지 않아 계획이 정한 것" 에 모았다. 설계 리뷰(`.codex-reviews/team-p7-spec-r1.md`·`r2.md`)가 가장자리 경우라 한계로 돌린 것(준비 중 drop 의 늦은 완료, 병합 뒤 상태 쓰기 전 중단, `full_if` 만 바꾼 뒤 retry, Redmine 사건 누락·중복)은 고치지 않는다.

**코드가 기준이다.** 앞 단계 코드는 여러 리뷰 라운드를 거치며 앞 계획들과 달라졌다. 이 계획의 수정은 모두 지금 HEAD(de385e7, 브랜치 `design/herdr-team-p7`. 코드는 main 5ac2922 와 같고 설계 문서만 다르다)의 코드에 대한 부분 수정이거나 새 파일이다. Orca·orca-team 코드에 의존하지 않는다(개념만 참고한다).

**계획 방식(사용자 결정, 6단계와 같다):** 시험은 전부, 구현은 규칙·인터페이스. 태스크마다 시험 코드와 시험 도구(가짜 hc·herdr-app·agent-act·claude, `tests/helpers.py`)는 전부 블록으로 쓴다. 구현은 `**Interfaces:**`(모듈·함수 시그니처와 반환, CLI 인자·exit 코드·오류 code·문구 원문, 상태 파일 필드와 예시 JSON, 잠금 순서, 시간 상수)와 `**Rules:**`(설계 절 번호를 붙인 단계별 규칙)로 쓴다. 까다로운 곳(슬롯 예약과 owns 잠금, 병합과 충돌 전이, 기준 병합 라운드의 base 이동과 `base_merge` 지우기, 슬롯 잠금과 준비 자식 재시작, 훅의 두 루트 편집 보호, Redmine 큐 순서·재시도)만 "핵심 조각" 코드를 붙인다(그대로 옮기지 않아도 되고 규칙과 시험이 기준이다). 템플릿·직무 문서·`CLAUDE.section.md`·`AGENTS.section.md`·`review-round.md`·init 스킬처럼 문구가 계약인 파일은 원문 전체 또는 정확한 Edit 블록이다.

**편집 표기:** `**Create** \`경로\`` 다음 코드 블록은 새 파일 전체다. `**Replace** \`경로\`` 는 있는 파일 전체를 바꾼다. `**Edit** \`경로\`` 다음 두 코드 블록은 "찾을 내용"과 "바꿀 내용"이다. 찾을 내용은 적용하는 그 시점의 파일에서 정확히 한 번 나온다(앞 태스크와 같은 태스크의 앞 편집을 반영한 내용이다). `**Append** \`경로\`` 는 파일 끝에 덧붙인다(기존 시험 파일에 새 시험 클래스를 더할 때. 필요한 import 는 덧붙이는 블록 첫머리에 있다). `**Delete** \`경로\``·`**Chmod** \`경로\`` 는 파일을 지우거나 실행 비트를 켠다. `**Run**` 다음 bash 블록은 기계적 일괄 바꾸기다(macOS BSD sed, 끝에 남은 것이 없음을 grep 로 확인한다). 같은 파일의 편집이 여럿이면 적힌 차례로 적용한다. 안에 ``` 가 든 블록은 더 긴 펜스로 감쌌다. 구현의 "핵심 조각" 은 이 표기를 쓰지 않는 그냥 코드 블록이다.

## Global Constraints

- Python 3.11 이상, 표준 라이브러리만. 외부 패키지 금지. 3.11 에서도 동작해야 한다(닫힌 stdin 이 붙은 채로 `communicate()` 를 부르지 않는다. 시험 하네스는 `proc.stdin = None` 으로 뗀다). 커밋 전에 바꾼 `.py` 와 `herdr-orch/bin/horch`·`herdr-team/bin/hteam`·`herdr-team/hooks/hteam_hook.py`·`tests/fakes/*`(Python 가짜 프로그램)가 `ast.parse(..., feature_version=(3, 11))` 를 통과해야 한다. bash 를 바꾸면 bash 3.2 로 돈다.
- 모듈 경계: herdr-team 은 `hc`·`herdr-app` 을 `herdr-team/lib/hteam/herdr.py` 에서만, `horch` 를 `herdr-team/lib/hteam/horch.py` 에서만, git 을 `herdr-team/lib/hteam/gitio.py` 에서만(7단계의 `git worktree`·`switch`·`branch`·`merge`·`reset`·`clean`·`symbolic-ref`·`rev-parse --git-common-dir` 도), HTTP 를 새 `herdr-team/lib/hteam/redmine.py` 에서만 부른다. herdr-orch 는 hc 를 `herdr-orch/lib/horch/hcio.py` 에서만 부른다. `codex exec` 는 `herdr-team/scripts/codex-run.sh` 에서만 부른다. 테스트 명령(`/bin/sh`)은 `testgate.py` 가, 작업 공간 setup·teardown(`/bin/sh`)은 `workspace.py` 가 직접 돌린다(테스트 명령과 같은 실행 규칙: 새 세션, 그룹 종료, 로그).
- hteam 은 horch 를 늘 `--home <프로젝트>/.herdr-team/state/horch` 로 부른다. 찾는 순서는 지금 그대로(`HERDR_ORCH_BIN` → 형제 `../herdr-orch/bin/horch` → `installed_plugins.json`), `HORCH_MIN` 은 Task 1 이 `0.3.0` 으로 올린다(herdr-orch 0.3.0 과 같은 커밋이어야 herdr-team 의 `test_versions_match` 가 통과한다. 6단계와 같은 까닭).
- 모든 명령은 stdout 에 JSON 한 개를 쓴다: 성공 `{"ok": true, ...}`, 실패 `{"ok": false, "error": {"code", "message", "hint"}, ...}`(오류의 `data` 는 최상위에 합친다). `hteam drive` 는 지금처럼 끝날 때만 JSON 한 줄이다. 오류는 `error.code` 로 가른다.
- exit 코드는 horch 와 같다: 0 성공, 1 실패·확인 불가, 2 입력 오류, 3 상태 충돌, 4 대기 시간 초과, 5 권한 없음, 12 의존 프로그램 없음. `--root` 는 하위 명령 앞에 둔다.
- 권한 확인(실수 방지용, 설계 8.3): 관제 판별은 6단계 그대로다. 새 명령 `slot prepare`·`slot release`·`redmine-sync` 는 관제만 한다(관제 밖에서 부르면 exit 5 `drive_only`). `slot reset` 은 큐 명령이다(관제에서 부르면 바로, 메인에서 부르면 요청 큐로, 설계 7.1·5.10.8).
- 상태 쓰기와 잠금 순서: **슬롯 잠금(`state/slots/slot-<N>.lock`) → 프로젝트(`state/lock`) → git 잠금(`state/git.lock`) → finish(`state/tasks/T-xxx.finish.lock`) → 태스크(`state/tasks/T-xxx.lock`)**. 슬롯 잠금은 준비·놓기·마무리 full 자식이 그 슬롯을 쓰는 동안 쥔다. 프로젝트 잠금을 쥔 쪽(관제, `start`)은 슬롯 잠금을 비차단으로만 시도한다(못 쥐면 자식이 산 것으로 보고 기다린다, 설계 5.10.3). `state/slots.json` 은 프로젝트 잠금 안에서 엄격하게 읽고(읽지 못하면 덮어쓰지 않고 exit 1 `bad_slots_file`) 임시 파일 + `os.replace` 로 쓴다. git 잠금은 병합(Task 5)만 쓴다. Redmine 큐 순번은 `state/redmine/queue.lock` 안에서 정한다(그 안에서 다른 잠금을 잡지 않는다). 전송 자식 `hteam redmine-sync` 는 실행 내내 `state/redmine/sync.lock` 을 비차단으로 쥔다(못 쥐면 보내지 않고 끝난다, Task 8). 차례는 `sync.lock` → `queue.lock` 만 된다(sync.lock 을 쥔 채 queue.lock 을 잠깐 쥘 수 있고, 반대 차례는 없다. sync.lock 을 쥔 채 슬롯·프로젝트·태스크 잠금을 잡지 않는다). `state/crew.json`·요청 큐·run.json 잠금은 6단계 그대로다. 관제 안에서 부르는 `fix`·`accept`·`drop`·`review-finish` 의 `nowait`(설계 8.5)도 그대로다.
- 손상된 기록을 없는 것으로 보지 않는다(6단계 그대로): 확정 기록·답 파일·상태 파일·`slots.json`·슬롯 표시 파일은 엄격 읽기(표시 파일이 깨졌거나 `main_root` 의 git common dir 이 다르면 표시 파일을 무시한다, 설계 5.10.2). Redmine 큐 항목이 깨졌으면 `failed/` 로 옮기고 다음으로 간다(Task 8).
- 사용자·워커 글은 `--옵션=값` 한 인자로 넘긴다(`--body=`·`--note=`·`--env=`). 경로는 손실 없이 다룬다. 커밋은 늘 경로 지정(`git add -- <경로>` + `git commit -m … -- <경로>`). 예외는 설계 5.10.6 의 기준 병합 커밋 하나(워커가 한다. hteam 은 하지 않는다)와 관제의 `git merge --no-ff`(병합 커밋)다.
- `hc run` 은 늘 `--no-notify` 를 붙인다(지금 그대로).
- 시각: 태스크 상태·outbox·요청 파일·`slots.json` 의 `since`·Redmine 큐의 `at` 은 UTC `%Y-%m-%dT%H:%M:%SZ`(`util.now`). drive.log·로그 파일 이름 시각은 지금 규칙 그대로(`util.local_now`, `%Y%m%d-%H%M%S`).
- 설계의 7단계 값(그대로 쓴다): `[workspace]` 기본 `mode = "shared"`·`roles = ["developer", "tester"]`·`slots = 2`(1–9)·`setup_timeout_min = 20`(1–120), env 이름 `^[A-Z][A-Z0-9_]*$` 이고 `HTEAM_`·`HC_`·`HORCH_` 로 시작하지 않고 `KEY`·`SECRET`·`TOKEN` 을 담지 않는다, env 값은 줄바꿈 없는 1 KiB 이하(계획이 더한 것: NUL 없음, 항목 31개 이하. `HTEAM_SLOT` 을 더해 horch `--env` 32개 안이다, Task 2), horch `--env` 32개·KEY `^[A-Za-z_][A-Za-z0-9_]*$`(`HC_`·`HORCH_` 아님)·VALUE 1 KiB(줄바꿈·NUL 없음), 병합 거부 상한 `MERGE_BLOCKED_S = 600`, Redmine 재시도 간격 `RETRY_S = (60, 120, 300, 600)`(그 뒤는 600)·포기 `GIVE_UP_S = 86400`·요청 제한 10초·doctor 5초, `review-extra.md` 6000자, P1 줄 최대 5개·줄마다 200자, done 요약 300자, decide kind 둘(`merge_conflict`·`workspace_failed`, `detail.kind` 는 `setup_failed`·`slot_dirty`·`branch_exists`·`base_moved`·`merge_blocked`), 문구 원문(설계 4.2·5.1·5.2·5.5·5.7·5.10.5·5.10.6·6.2·7.7·8.11·8.12 의 따옴표 안 문장).
- 시험용 환경 변수: 6단계 것 그대로. 새로 더하지 않는다: 10분·24시간·재시도 간격은 시험이 상태 파일·큐 항목의 시각을 옛 시각으로 쓴다. 죽음 재현은 지금처럼 `HTEAM_TEST_DIE_AT`(지점 이름은 태스크가 정한다).
- 문서·메시지·주석은 한국어. 명령·코드 식별자는 원문. 템플릿에 물결표 범위(`\d~\d`)를 쓰지 않는다.
- 저장소는 공개될 수 있다. 커밋 전에 `git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews'` 가 아무것도 찾지 않아야 한다. 템플릿·스킬은 `tests/test_setup.py` 의 `test_no_personal_paths_or_trust_all` 이 `/[h]ome/` 까지 본다.
- 버전: herdr-orch 는 Task 1 이 `0.2.0` → `0.3.0`(`herdr-orch/lib/horch/paths.py` 의 `VERSION`, `herdr-orch/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` 의 herdr-orch 항목. `herdr-orch/tests/test_meta.py` 의 `test_versions_match`)과 `HORCH_MIN = "0.3.0"`. herdr-team 은 Task 9 가 `0.4.0` → `0.5.0`(`herdr-team/lib/hteam/paths.py`, `herdr-team/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` 의 herdr-team 항목. `herdr-team/tests/test_cli.py` 의 `test_versions_match`).
- 기본값은 지금 동작 그대로다(사용자 결정): `[workspace]` 가 없거나 `mode = "shared"`, `[redmine]` 이 없거나, `[test]` 에 `tester_paths`·`full_if` 가 없으면 0.4.0 과 같은 출력·상태·명령이다. 태스크마다 이 회귀를 지키는 시험이 있다(shared 모드에서 horch 호출에 `--env` 가 없고 `--cwd` 가 프로젝트 루트, 상태에 `workspace` 가 없음 등). 새 필드는 켜졌을 때만 쓴다(`status` 의 `workspace`·`redmine` 은 켜졌을 때만 키가 있다).
- 작업 브랜치 `design/herdr-team-p7` 에서 한다. main 에 직접 커밋하지 않는다. main 병합은 이 계획 밖이다(컨트롤러가 한다).
- 테스트: 저장소 루트에서 `bash herdr-team/tests/run.sh`(전체 10–15분)와 `bash herdr-orch/tests/run.sh`(1–2분). 태스크 중간에는 모듈이나 `-k` 로 고른다(`run.sh` 는 인자를 `unittest discover` 에 넘긴다). **전체 모음은 백그라운드로 하나씩 돌린다. 두 전체 모음을 함께 돌리거나 다른 무거운 일과 함께 돌리지 않는다(이 기계는 함께 돌면 exit 137 로 죽인다). 기다릴 때 sleep 으로 폴링하지 않는다(끝나면 알림이 온다).** 시험은 실제 hc·Herdr·에이전트·codex·Redmine 을 건드리지 않는다: 실제 `horch` 를 부르고 hc·claude·codex 는 `herdr-orch/tests/fakes/` 의 가짜, herdr-app 은 `herdr-team/tests/fakes/herdr-app`, 워커·리뷰어의 일은 `herdr-team/tests/fakes/agent-act`, Redmine 은 시험 프로세스 안의 `http.server` 가짜 서버다. git worktree 는 시험이 만든 임시 저장소 안에서만 만든다(이 저장소에 worktree 를 만들지 않는다). 사용자 hc core 를 멈추거나 다시 띄우지 않고(`hc server stop|restart`, `hc update` 금지), 새 `HC_SESSION` 으로 hc 를 부르지 않는다. `~/.claude/settings.json`·`~/.claude/plugins/*.json`·`~/.codex/config.toml`·`~/.claude.json` 을 고치지 않고 플러그인을 설치하지 않는다.
- **Codex 교차 검증(CLAUDE.md):** 이 계획은 실행 전에 컨트롤러가 `scripts/codex-review.sh doc <이름> <프롬프트 파일>` 로 검토받는다. 각 태스크의 마지막 단계는 커밋이다. **구현자는 커밋에서 멈춘다.** 그 뒤 컨트롤러가 Herdr pane 에서 `scripts/codex-review.sh commit <sha>` 를 돌린다. 끝나기를 붙잡고 기다리지 않고 `hc wait <주소> --timeout 3600` 을 백그라운드로 건 뒤 다른 일을 한다. 결과 `.codex-reviews/commit-<sha 7자>.md`(커밋하지 않는다)의 지적은 그대로 따르지 않는다: 항목마다 코드로 사실인지 확인한 뒤 고치거나(고치면 재현 시험을 먼저 더하고 커밋한 뒤 그 커밋을 다시 리뷰) 고치지 않는 이유를 적는다. 고칠 범위(사용자 결정): P0·P1, 기본 경로의 P2, 이번 변경이 만든 회귀. 가장자리 경우의 P2 는 알려진 한계로 적는다. P0·P1 이 남지 않을 때까지 최대 3 라운드. 3 라운드 뒤에도 남으면 사용자에게 묻는다.
- 설계가 정하지 않은 방어 코드를 더하지 않는다(사용자 결정). 알려진 한계는 설계 5.10.9·8.12 끝·13장·orch 설계 14.4 그대로 두고 고치지 않는다.

## File Structure

```
herdr-orch/
  lib/horch/
    store.py       스키마 v4(dispatches.env)(Task 1)
    workers.py     start 의 env, --task --retry 의 env 물려받기, worker-list·worker-show 행의 env(Task 1)
    guard.py       exec 직전 환경 적용(Task 1)
    cli.py         worker-start --env(형식 검사, --terminal 충돌)(Task 1)
    skill.md       --env 한 줄(Task 1)
    paths.py       VERSION 0.3.0(Task 1)
  .claude-plugin/plugin.json   0.3.0(Task 1)
  tests/
    fakes/claude          받은 환경의 HT_·HTEAM_ 변수도 출력(Task 1)
    test_env.py           새로(Task 1)
    test_store.py·test_meta.py(Task 1)
herdr-team/
  lib/hteam/
    config.py      Workspace·Redmine, [workspace]·[redmine] 검사, worktree 모드의 crew·승인 직무 검사, 검사 없이 읽는
                   TestSettings·test_settings·redmine_key_env(Task 2)
    specs.py       Spec.issue, issue 검사(Task 2)
    plan.py        tasks.toml issue·plan apply 복사, 묶음 규칙 1 의 tester_paths(Task 2)
    testgate.py    tester_paths·full_if 형식(Task 2), child_env(Task 3), 작업 루트·슬롯 env 실행(Task 4), full_if 관문·
                   key_env 빼기(Task 6), worktree 마무리 full 의 슬롯(Task 5)
    workspace.py   새로: slots.json·슬롯 잠금·폴더·브랜치·표시 파일·setup/teardown·prepare·slot CLI(Task 3), 예약·busy·
                   env 인자(Task 4), 병합·놓기·reset·재확인 도우미(Task 5)
    paths.py       Project(work_root)·find_project 의 표시 파일·슬롯 경로(Task 3), redmine 경로(Task 8), VERSION 0.5.0(Task 9)
    gitio.py       worktree·switch·branch·symbolic-ref·common dir(Task 3), merge·abort·reset·clean·MERGE_HEAD(Task 5)
    tasks.py       시작의 슬롯 예약·대기 사유 slot·slot_setup·잠금 검사의 예약·fix 의 슬롯 확인(Task 4), accept 병합·drop 놓기(Task 5)
    crew.py        place 의 0(Task 4)
    dispatch.py    launch 의 cwd·env(Task 4)
    review.py      작업 루트의 git·관문·리뷰 커밋·변조 기준점·리뷰어 cwd·env(Task 4), base_merge 지우기(Task 5),
                   점검표·우선순위·이슈 줄(Task 7)
    compose.py     작업 공간 절(Task 4), 기준 병합 줄(Task 5), full_if 줄(Task 6), 우선순위·이슈 줄(Task 7)
    drive.py       준비 자식·workspace_failed·decide files 의 슬롯 경로(Task 4), 병합·충돌·놓기·재확인·마무리 슬롯·merge_conflict(Task 5),
                   Redmine 사건·전송 자식(Task 8)
    queue.py       slot reset(Task 5)
    coord.py       status 의 workspace(Task 5)·redmine(Task 8)
    approval.py    일괄 승인 줄의 #N, 결정의 accept 뒤 Redmine 닫기(Task 8)
    redmine.py     새로: 큐·전송·키·가리기·요약(Task 8)
    setup.py       doctor 의 Redmine(Task 8)·worktree(Task 9)
    cli.py         COMMAND_MODULES 의 workspace(Task 3)·redmine(Task 8)
    horch.py       HORCH_MIN 0.3.0(Task 1)
  hooks/hteam_hook.py   find_root 의 두 루트, 편집 보호(Task 3)
  templates/
    config.toml          [workspace]·[redmine] 주석 예시(Task 2)
    review-prompt.md     우선순위 줄·점검표·이슈 줄 자리(Task 7)
    review-round.md      2(Task 7)
    worker-rules.md      우선순위 문단(Task 7), 작업 공간·Redmine 일반 규칙(Task 9. 태스크별 이슈 줄은 compose 가 넣는다)
    CLAUDE.section.md    decide 두 줄·index.lock·Redmine 줄(Task 9)
    AGENTS.section.md    작업 공간·이슈·우선순위 줄(Task 9)
  skills/init/SKILL.md   4a(Task 9)
  .claude-plugin/plugin.json   0.5.0(Task 9)
  tests/
    helpers.py            WS_CONFIG·slot_root·slots·git_at·act 의 cwd(Task 3), ws_start(Task 4)
    test_workspace.py         새로(Task 3)
    test_workspace_flow.py    새로(Task 4)
    test_workspace_merge.py   새로(Task 5)
    test_redmine.py           새로(Task 8)
    test_config.py·test_state_specs.py·test_plan.py(Task 2), test_testgate.py(Task 6), test_review.py·test_start.py(Task 7),
    test_wording.py·test_setup.py·test_cli.py(Task 9), 그 밖에 태스크가 적은 파일
.claude-plugin/marketplace.json   herdr-orch 0.3.0(Task 1), herdr-team 0.5.0(Task 9)
README.md                          작업 공간·Redmine·점검표·시험 도구에서 .herdr-team/ 빼기·0.4.0 → 0.5.0(Task 9)
docs/superpowers/specs/2026-11-05-herdr-team-design.md   머리 상태 줄과 15.4 의 7단계 결과(Task 10)
```

### 기록·필드에 더하는 것

- horch DB(Task 1): 스키마 v4 `dispatches.env TEXT`(JSON 객체 `{"KEY": "VALUE"}`, 없으면 NULL). `worker-list`·`worker-show` 행의 `env`(dict|null).
- `state/slots.json`(Task 3–5): `{"slots": {"<N>": {"state", "task", "branch", "base_branch", "base", "setup_done", "since", "ready"?, "use"?, "reset_request"?}}}`. 없는 번호는 `free`. `ready` 는 준비가 끝난 예약(Task 3), `use: "final"` 은 마무리 full 이 쓰는 동안의 `busy`(태스크 없음), `reset_request` 는 `slot reset` 큐 요청 id(Task 5). 예시:

  ```json
  {"slots": {"1": {"state": "busy", "task": "T-003", "branch": "herdr/T-003", "base_branch": "main",
                   "base": "4f1c…", "setup_done": "T-003", "since": "2026-11-12T01:02:03Z"},
             "2": {"state": "preparing", "task": "T-004", "branch": "herdr/T-004", "base_branch": "main",
                   "base": "4f1c…", "setup_done": null, "since": "2026-11-12T01:03:00Z", "ready": true}}}
  ```
- `state/slots/slot-<N>/`(슬롯 폴더 = worktree), `state/slots/slot-<N>.lock`(슬롯 잠금), `state/slots/logs/slot-<N>-<setup|teardown>-<%Y%m%d-%H%M%S>.log`, `state/git.lock`(Task 3·5).
- 작업 루트의 `.herdr-team/state/slot.json`(표시 파일, Task 3): `{"main_root": "<메인 프로젝트 루트>", "slot": N, "task": "T-xxx"}`.
- 태스크 상태(Task 4·5): `workspace: {"slot", "branch", "base_branch", "root", "merge"}`(`root` 는 작업 루트 절대 경로, `merge` 는 병합 커밋 sha 또는 null), `base_merge`(풀어야 할 기준 커밋 sha, 기준 병합 라운드 동안만), `merge_wait: {since, asked: [kind]}`(첫 병합 거부 시각과 이미 올린 `workspace_failed` kind, Task 5), 라운드 기록의 `merge_conflict: {base, files}`·`base_merge`·`merge_resume`(Task 5).
- 테스트 기록(Task 6): developer 태스크의 `full_if` full 은 `state/tests/T-xxx.json` 의 `full` 키(tester full 과 같은 꼴)에 `reason: "full_if"`, `matched: [<경로>]` 를 더한다.
- `state/redmine/`(Task 8): `queue/<NNNNNN>.json`(`{seq, issue, task, event, status_id, notes, at}` + 재시도 `tries`·`next_at`·`last_error`), `failed/<NNNNNN>.json`(같은 꼴 + `error`), `queue.lock`, `sync.lock`(전송자 하나), `seq`.
- outbox(Task 4·5): decide `workspace_failed`(`detail: {kind, slot, …}`, `tail`)·`merge_conflict`(`detail: {base, files}`).
- `hteam status`(Task 5·8): 켜졌을 때만 `workspace: {mode, slots: [{n, state, task, branch}]}`, `redmine: {enabled, pending, failed, last_error}`.

### 태스크 사이 계약(이름과 시그니처)

여러 태스크가 쓰는 이름을 여기 고정한다. 각 태스크의 Interfaces 는 이것을 자세히 적고, 뒤 태스크는 이것을 Consumes 로 쓴다.

- `config.Workspace`(Task 2, frozen dataclass): `mode: str`(`"shared"`·`"worktree"`), `roles: tuple[str, ...]`, `slots: int`, `setup: str | None`, `teardown: str | None`, `setup_timeout_min: int`, `env: dict[str, str]`(값의 `{slot}` 그대로). 속성 `on`(mode == "worktree"), 메서드 `covers(role) -> bool`(on 이고 role 이 roles 안). `config.Redmine`(frozen dataclass): `url: str`(끝 `/` 를 뗀 값), `key_env: str`, `env_file: str | None`, `status: dict[str, int]`(`start`·`done`·`changes`·`closed`). `Config.workspace: Workspace`(늘 있다, 없으면 shared 기본), `Config.redmine: Redmine | None`.
- `specs.Spec.issue: str | None`(Task 2): 숫자 문자열(앞 `#` 를 뗀 값). 없으면 None.
- `testgate.GateConfig.tester_paths: tuple[str, ...] | None`, `GateConfig.full_if: tuple[str, ...]`(Task 2, 없으면 None·빈 튜플). `digest` 에 들지 않는다.
- `paths.Project(root, work_root=None)`(Task 3): `root` 는 상태 루트(메인 프로젝트), `work_root` 는 작업 루트(기본 root). 새 경로 `slots_file`(`state/slots.json`), `slots_dir`(`state/slots`), `slot_logs`(`state/slots/logs`), `git_lock`(`state/git.lock`). `find_project` 는 찾은 폴더의 표시 파일이 맞으면 `Project(main_root, work_root=<찾은 폴더>)`.
- `workspace.py`(Task 3): `MARKER_REL = ".herdr-team/state/slot.json"`, `branch_of(tid) -> str`(`herdr/T-xxx`), `load(p) -> dict`(엄격, `bad_slots_file`), `entry(data, n) -> dict`(빈 번호는 free 기본값), `save(p, data)`(프로젝트 잠금 안), `held_by(data, tid) -> int | None`, `folder(p, n) -> Path`, `work_root(p, n) -> Path`(폴더 + `gitio.top_prefix`), `task_root(p, st) -> Path`(`st["workspace"]["root"]`, 없으면 `p.root`), `slot_env(cfg, n) -> dict[str, str]`(`[workspace.env]` 의 `{slot}` 을 채운 값 + `HTEAM_SLOT`), `task_env(p, cfg, st) -> dict[str, str]`(작업 공간 태스크면 그 슬롯의 `slot_env`, worktree 모드의 메인 폴더 태스크면 `slot_env(cfg, 0)`, shared 면 빈 dict), `slot_lock(p, n, *, nowait=False)`(컨텍스트 관리자. nowait 에 못 쥐면 exit 3 `slot_locked`), `slot_busy(p, n) -> bool`(비차단 시도로 자식이 쥐었는지), `marker(root) -> dict | None`, `run_hook(p, cfg, n, kind, tid) -> dict`(`kind` 는 `"setup"`·`"teardown"`, 결과 `{status: "passed"|"failed"|"timeout"|"unrunnable", exit, seconds, log, tail}`), `prepare(p, cfg, tid) -> dict`(`hteam slot prepare` 의 몸통). CLI `hteam slot prepare T`(관제만).
- `testgate.child_env(cfg, extra=None) -> dict[str, str]`(Task 3): 지금 `_env()` 의 뺄 변수(`DROP_ENV`)를 뺀 환경에 extra 를 더한다. 테스트 명령과 setup·teardown 이 같이 쓴다. Task 6 이 `cfg.redmine.key_env` 도 뺀다. `cfg` 는 `config.Config`·`config.TestSettings`(Task 2, `hteam test` 가 검사 없이 읽은 설정) 또는 None.
- `config.TestSettings`·`config.test_settings(p)`·`config.redmine_key_env(p)`(Task 2): `hteam test` 가 `config.load` 없이 쓰는 `workspace`·`redmine.key_env`(설정이 깨져도 `hteam test` 가 돈다, 설계 4.2). `workspace.slot_env`·`task_env`·`run_hook`·`claim_final`·`testgate.child_env` 의 `cfg` 는 `Config` 또는 이것이다.
- `dispatch.launch(…, cwd: Path | None = None, env: dict[str, str] | None = None)`(Task 4): `--cwd` 는 cwd(없으면 `p.root`), env 가 있으면 이름 순서로 `--env=KEY=VALUE`. 리뷰어도 같은 인자.
- 대기 사유(Task 4): `start` 의 waiting `reason` 과 `start-ready` 의 `waiting[].reason` 에 `slot`(빈 슬롯 없음)·`slot_setup`(준비 중). 그 HteamError code 는 `no_free_slot`·`slot_preparing`(exit 3).
- 관제 자식 키(Task 4·5·8, 설계 8.8): 슬롯 준비·놓기는 `slot:<N>`, worktree 마무리 full 은 지금 `final`, Redmine 전송은 `redmine`.
- `drive.DECIDE_KINDS` 에 Task 4 가 `workspace_failed`, Task 5 가 `merge_conflict` 를 더한다.
- `redmine.py`(Task 8): `enqueue(p, cfg, st_or_tid, event, *, notes, issue=None)`, `sync(p, cfg) -> dict`(`sync.lock` 을 쥔 전송자 하나만 보낸다), `read_key(p, cfg) -> str | None`, `mask(text, key) -> str`, `summary(p, cfg) -> dict`. 사건 이름 `start`·`done`·`changes`·`approve`·`merged`·`closed`·`drop`.

### 공유 시험 도구(Task 3 이 helpers.py 에 넣는다)

뒤 태스크의 시험이 쓰는 이름이다(블록 원문은 Task 3 Step 1).

- `WS_CONFIG`: `BASE_CONFIG` 뒤에 `[workspace] mode = "worktree"`, `slots = 2`, `[workspace.env] HT_PORT = "81{slot}0"`.
- `TeamCase.slot_root(n) -> Path`: `state/slots/slot-<n>`(시험 프로젝트는 저장소 루트라 작업 루트 = 슬롯 폴더).
- `TeamCase.slots() -> dict`: `state/slots.json`(없으면 `{"slots": {}}`).
- `TeamCase.git_at(root, *args) -> str`: 다른 작업 트리에서 git.
- `TeamCase.act(did, action)`: agent-act 의 `--root` 를 그 Dispatch 의 `cwd`(프로젝트 안일 때)로 한다. 그래서 `act_work`·`act_review` 가 슬롯에서도 그대로 쓰인다.
- helpers.py 의 클래스 메서드를 더하는 편집은 늘 `def _parse(stdout: str, stderr: str) -> dict:` 한 줄을 찾을 내용으로 하고 바꿀 내용은 새 메서드(들여쓰기 네 칸, `TeamCase` 안)와 빈 두 줄 뒤 그 줄이다. 모듈 상수는 `VALID_BODY = """## Target` 한 줄을 찾아 그 앞에 둔다. 그래서 어느 태스크의 helpers 편집도 앞 태스크의 편집과 상관없이 맞는다.

## 태스크 순서와 의존

1(herdr-orch 0.3.0 `--env`·`HORCH_MIN`) → [S2, 컨트롤러] → 2(설정과 사양) → 3(작업 공간 코어) → 4(작업 공간 흐름 1: 배정·시작·작업 루트) → 5(작업 공간 흐름 2: 병합·충돌·놓기·마무리·명령) → 6(테스트 관문 `full_if`·key_env) → 7(리뷰 프롬프트·워커 사양 문구) → 8(Redmine) → 9(init·문서·doctor·0.5.0) → 10(실환경 확인·전체 시험·브랜치 리뷰).

- 브리프의 열 태스크를 그대로 두고 두 군데를 옮겼다. (1) `HORCH_MIN = "0.3.0"` 을 Task 9 에서 Task 1 로 옮겼다. herdr-team 의 `test_versions_match` 가 `HORCH_MIN` 이 함께 배포하는 herdr-orch 버전과 같기를 요구해, herdr-orch 를 0.3.0 으로 올리는 커밋에서 함께 바꿔야 그 사이 시험이 통과한다(6단계와 같은 까닭). (2) 브리프 Task 6 의 "작업 루트 cwd·슬롯 env·`HTEAM_SLOT`" 을 Task 4 로 옮겼다. 작업 공간 태스크의 리뷰 관문은 태스크 브랜치의 커밋을 슬롯에서 세고 돌려야 하므로(설계 5.10.4), 그것 없이는 Task 4 의 리뷰 흐름 시험(슬롯의 작업 커밋 → 관문 → 리뷰어)이 `no_work_commit` 로 끝난다. Task 6 은 `full_if`·key_env·developer 테스트 절 줄만 맡는다. 리뷰 프롬프트의 작업 공간 줄(5.10.4·5.10.5 의 첫째·셋째 줄)도 Task 4 에 둔다(Task 7 은 작업 공간과 상관없는 문구).
- S2(설계 15.2)는 Task 1 커밋 바로 뒤에 컨트롤러가 한다. 절차는 Task 10 Step 2 이고, 결과가 "Codex 셸이 값을 보지 못한다" 면 Task 1 에 덧붙임 커밋(`shell_environment_policy.set` 인자)을, 그래도 빠지는 정책이면 Task 9 의 doctor 경고를 더한다.
- 2 는 herdr-orch 와 무관하다. 3 은 2 의 `Config.workspace` 를 쓴다. 4 는 1 의 `--env`, 2 의 `covers`·worktree 모드 crew 검사·`test_settings`, 3 의 `workspace.py`·표시 파일·`slot prepare` 를 쓴다. 5 는 4 의 시작·작업 루트·상태 `workspace` 를 쓴다. 6 은 2 의 `GateConfig.full_if`·`Config.redmine`·`test_settings`, 3 의 `child_env`, 4 의 작업 루트 관문 위에 얹힌다. 7 은 2 의 `Spec.issue`·`Config.redmine` 을 쓴다. 8 은 2 의 `[redmine]`·`issue`, 5 의 병합 성공 지점, 6 의 key_env 빼기, 7 의 이슈 줄을 쓴다. 9 는 1–8 의 이름(decide kind, 큐 명령 `slot reset`, status 필드)을 문서에 적는다. 10 은 1–9 를 모두 쓴다.
- 각 태스크의 "찾을 내용"은 앞 태스크를 모두 적용한 뒤의 파일이다. 계획의 시험·도구·템플릿 블록은 de385e7 을 새로 복사한 작업 트리에 Task 1–9 를 차례로 적용해 모두 정확히 한 번씩 맞는 것을 확인했다(자체 검토, 보고서 참고). 각 태스크 Step 2 의 Expected 는 de385e7 에 그 태스크의 Step 1 블록만 적용한 트리(구현 코드 없음)에서 쟀다. Task 4 부터는 Task 3 의 공유 시험 도구 편집 셋을, Task 5 는 Task 4 의 `ws_start`·`DECIDE_KINDS` 기대값 편집도 먼저 적용했다(각 Step 2 에 적었다). 앞 태스크를 건너뛰고 쟀으므로 숫자는 순서대로 적용한 트리와 다를 수 있다. 앞 태스크의 구현이 있으면 실패 수와 대표 메시지가 달라진다(대개 앞 태스크 기능이 없어 생긴 오류(`bad_config`, `unknown command`, `ImportError`)가 그 태스크 기능의 실패로 바뀐다).

---

### Task 1: herdr-orch 0.3.0 — `worker-start --env`, 스키마 v4 `dispatches.env`, `launch-guard` 의 exec 직전 적용, `HORCH_MIN` 0.3.0

orch 설계 14장 전부를 만든다. herdr-team 7단계의 작업 공간(설계 5.10)은 워커·리뷰어마다 다른 환경 변수(시험 DB 포트 등)를 준다. `hc run` 으로 띄운 터미널은 부른 셸의 환경을 물려받지 않으므로(6단계 실환경 확인), horch 가 `worker-start --env KEY=VALUE`(되풀이) 값을 Dispatch 에 기록하고 `launch-guard` 가 가드 등록을 마친 뒤 `os.execvp` 바로 앞에서 `os.environ` 에 더한다. 프리앰블과 에이전트 인자에는 넣지 않는다. `--task --retry` 는 `--env` 가 없으면 그 Task 의 마지막 Dispatch 값을 물려받는다(orch 설계 14.1). 기록은 스키마 v4 의 `dispatches.env`(JSON 객체, 없으면 NULL)이고 `worker-list`·`worker-show` 행에 `env` 로 보인다(14.2). 버전 세 곳을 0.3.0 으로 올리고, herdr-team 의 `test_versions_match` 가 `HORCH_MIN` 이 함께 배포하는 herdr-orch 버전과 같기를 요구하므로 `HORCH_MIN = "0.3.0"` 도 이 커밋에서 바꾼다(헤더 Global Constraints). herdr-team 이 `--env` 를 쓰는 것은 Task 4 다.

Codex 셸 도구가 `--env` 값을 보는지는 사전 검증 S2(설계 15.2, Task 10)가 본다. 이 태스크는 값을 환경에만 넣는다: Codex 인자에 더하는 것은 지금처럼 `HC_TERMINAL_ID` 의 `-c shell_environment_policy.set.HC_TERMINAL_ID=…` 하나다(`guard.inject_codex_env`). S2 에서 보지 못하면 Task 10 이 그 결과로 고친다(설계 15.2 S2).

**Files:**
- Modify: `herdr-orch/lib/horch/store.py`(v4), `herdr-orch/lib/horch/workers.py`(`parse_env`, `start`·`_create`·`_task_for` 의 env, 행의 `env`), `herdr-orch/lib/horch/persist.py`(`start_on` 이 앞 고정 Dispatch 의 env 를 옮겨 적는다), `herdr-orch/lib/horch/guard.py`(exec 직전 적용), `herdr-orch/lib/horch/cli.py`(`--env`, 검사), `herdr-orch/lib/horch/skill.md`(한 줄), `herdr-orch/lib/horch/paths.py`(`VERSION`), `herdr-orch/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`(herdr-orch 항목), `herdr-team/lib/hteam/horch.py`(`HORCH_MIN`)
- Modify(시험 도구): `herdr-orch/tests/fakes/claude`, `herdr-orch/tests/fakes/codex`(`FAKE_AGENT_ENV` 가 고른 환경 변수도 출력)
- Test: `herdr-orch/tests/test_env.py`(새로), `herdr-orch/tests/test_persist.py`·`herdr-orch/tests/test_meta.py`·`herdr-orch/tests/test_cli.py`(버전), `herdr-team/tests/test_base.py`(설치 기록 고르기의 버전, horch 버전 접두사), `herdr-team/tests/test_cli.py`(주석)

**Interfaces:**
- Consumes: `workers.start`·`_create`·`_task_for`·`_row_json`·`_launch`, `persist.start_on`·`inspect`, `guard.run`·`claim`·`inject_codex_env`, `store.Store`·`_migrate`, `cli._check_worker_start`·`_with_store`.
- Produces:
  - CLI `worker-start --env KEY=VALUE`(`action="append"`, 되풀이. 값이 `-` 로 시작해도 되게 호출자는 `--env=KEY=VALUE` 로 붙여 쓴다). `KEY=VALUE` 는 첫 `=` 에서 나눈다(값에 `=` 가 있어도 된다). 빈 값도 된다.
  - 검사(`cli._check_worker_start` 가 저장소를 열기 전에 한다. 어기면 아무것도 만들지 않고 hc 를 부르지 않고 exit 2 `usage`). 차례와 문구(원문):
    1. `--terminal` 과 같이 쓰면 지금의 `given` 목록에 `--env` 를 더한다: `--terminal 과 --env 은 같이 쓸 수 없다(그 터미널에 떠 있는 세션의 값을 그대로 쓴다)`(다른 옵션과 함께면 지금처럼 `, ` 로 잇는다).
    2. 33개 이상: `--env 는 32개까지다({n}개)`
    3. 항목마다 차례로: `=` 가 없으면 `--env 는 KEY=VALUE 꼴이다: {항목!r}` / 이름이 `^[A-Za-z_][A-Za-z0-9_]*$` 가 아니면 `--env 이름 {이름!r} 은 영문자·숫자·_ 로 쓰고 숫자로 시작하지 않는다` / `HC_`·`HORCH_` 로 시작하면 `--env 이름 {이름} 은 HC_·HORCH_ 로 시작할 수 없다(가드와 판별이 쓴다)` / 값에 `\n`·`\r`·`\0` 이 있거나 UTF-8 로 1024바이트를 넘으면 `--env {이름} 의 값은 줄바꿈·NUL 없는 1 KiB(UTF-8 1024바이트) 이하다` / 앞에 나온 이름이면 `--env {이름} 가 두 번 나왔다`
  - `workers.ENV_MAX = 32`, `workers.ENV_VALUE_MAX = 1024`, `workers.ENV_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")`, `workers.parse_env(items: list[str]) -> dict[str, str] | None`: 위 2–3 의 검사(`HorchError("usage", …, USAGE)`). 항목이 없으면 None, 있으면 받은 차례의 dict.
  - `workers.start(…, env: dict[str, str] | None = None)`: `_create` 에 넘긴다. `--keep-open`·`--tab`·`--hidden` 과 함께 쓸 수 있다(고정 터미널의 첫 환경이다, 14.1).
  - 기록(14.2): `dispatches.env` 에 `json.dumps(env, ensure_ascii=False)`, env 가 None 이면 NULL. `--task --retry` 이고 env 가 None 이면 그 Task 의 마지막 시도(`ORDER BY attempt DESC LIMIT 1`, `_task_for` 가 이미 읽는 행)의 `env` 텍스트를 그대로 쓴다(NULL 이면 NULL). `--task` 에 `--retry` 가 없으면(앞 시도가 `abandoned`·`released`) 물려받지 않는다: 주면 그 값, 아니면 NULL(14.1 은 `--task --retry` 만 적었다). 물려받기는 Dispatch 를 만드는 같은 트랜잭션에서 한다.
  - `persist.start_on`(`--terminal`)은 `agent`·`model`·`effort`·`agent_args`·`cwd`·`terminal_argv` 처럼 `env` 도 앞 고정 Dispatch 의 값을 옮겨 적는다(떠 있는 세션의 환경이 그것이다. 새로 바꾸지 않는다).
  - 행(`workers._row_json`, 그래서 `worker-list`·`worker-show`·release·abandon 결과의 Dispatch): `env`(dict | None).
  - `launch_failed` 행의 `next`(재시도 argv)에는 `--env` 를 넣지 않는다(`--retry` 가 물려받는다).
  - 적용(14.3): `guard.run` 이 `claim` 을 마친 뒤 그 Dispatch 의 `env` 를 읽어 두고, 저장소를 닫고 시그널을 되돌린 뒤 `os.execvp` 바로 앞에서 `os.environ.update(그 dict)`(같은 이름은 덮어쓴다). 프리앰블·에이전트 argv·`inject_codex_env` 는 바꾸지 않는다.
  - 스키마 v4(`store.SCHEMA_VERSION = 4`): DDL 의 `dispatches` 끝에 `env TEXT`. `_migrate` 의 누적 단계 `if version < 4:` — `PRAGMA table_info(dispatches)` 에 `env` 가 없을 때만 `ALTER TABLE dispatches ADD COLUMN env TEXT`, 그다음 `schema_version` 4. 기존 행은 NULL.
  - 버전: `herdr-orch/lib/horch/paths.py` `VERSION = "0.3.0"`, `herdr-orch/.claude-plugin/plugin.json`·`.claude-plugin/marketplace.json` 의 herdr-orch `"version": "0.3.0"`, `herdr-team/lib/hteam/horch.py` `HORCH_MIN = "0.3.0"  # hteam 이 받는 가장 낮은 herdr-orch 버전(워커 환경 변수 --env, 0.3.0)`.
  - skill.md: 코디네이터 루프 3 에 `--env` 한 줄(Step 3 의 Edit 블록 원문).
  - 시험 도구: 가짜 claude·codex 는 `FAKE_AGENT_ENV`(쉼표로 나눈 이름 목록)가 있을 때만 출력에 `"env": {이름: 값 또는 null}` 을 더한다. 없으면 지금 출력 그대로다(`test_guard` 의 정확한 비교가 그대로 맞는다).

**Rules:**

1. 검사(14.1): `_check_worker_start(args)` 에서 `--terminal` 충돌(위 1)을 지금 충돌 검사와 같은 자리에서 보고, 그 뒤 `args.env_map = workers.parse_env(args.env)` 로 2–3 을 본다. 모두 `Store` 를 열기 전이다(`_dispatch` 가 지금처럼 `worker-start` 검사를 먼저 한다).
2. 기록(14.2): `_with_store` 의 `worker-start` 갈래가 `workers.start(…, env=args.env_map)` 를 부른다(`--terminal` 갈래는 env 를 받지 않는다). `_create` 는 INSERT 에 `env` 열을 더한다. `_task_for` 가 마지막 시도 행을 읽을 때 `env` 도 읽어 `retry and env is None` 이면 그 텍스트를 쓴다.
3. 적용(14.3): `guard.run` 의 차례는 `claim` → env 읽기(`store.one("SELECT env FROM dispatches WHERE id=?")`) → `inject_codex_env` → `store.close()` → SIGPIPE·SIGXFSZ 되돌리기 → `os.environ.update(json.loads(env))`(env 가 NULL 이면 하지 않는다) → `os.execvp`. 가드가 거부하면(claim 실패) 환경을 바꾸지 않는다.
4. 스키마(14.2): 새 DB 는 DDL 로 바로 v4. 옛 DB 는 `if version < 2`·`if version < 3`·`if version < 4` 를 차례로 거친다(`elif` 가 아니다). v1·v2 로 되돌린 시험 DB 에는 `env` 열이 이미 있을 수 있어 없는 때만 더한다.
5. 한계(14.4, 고치지 않는다): 값은 SQLite 와 `worker-show` 출력에 남는다. 비밀값을 넘기지 않는다(herdr-team 은 포트·경로 같은 값만 넘긴다, 설계 4.2 의 이름 검사).

- [ ] **Step 1: 실패하는 테스트 작성**

**Create** `herdr-orch/tests/test_env.py`

```python
"""워커 환경 변수(herdr-orch 설계 14장, 0.3.0): worker-start --env, 스키마 v4 dispatches.env, launch-guard 의 exec 직전 적용,
--task --retry 의 물려받기, worker-list·worker-show 의 env."""
import json
import subprocess
import sys
import unittest

from tests.helpers import BIN, HorchCase
from horch.store import SCHEMA_VERSION, Store

WATCH = "HT_PORT,HTEAM_SLOT,HT_URL,HT_EMPTY"  # 가짜 에이전트가 보고할 이름(FAKE_AGENT_ENV)


class EnvCase(HorchCase):
    """소유자 t100(spA·tbA). 소유자는 working 이라 깨우기 글을 받지 않는다(test_persist 와 같다).
    시험이 보는 이름(WATCH 와 HT_DB)은 바깥 환경에서 지운다: 슬롯 터미널처럼 그 이름이 이미 있는 환경에서 돌려도 결과가 같다
    (HorchCase 는 바깥 환경을 물려받는다)."""

    def setUp(self):
        super().setUp()
        for name in (*WATCH.split(","), "HT_DB"):
            self.env.pop(name, None)
        self.run_id = self.make_owner("t100", "spA", "tbA")
        self.update_terminal("t100", status="working")

    def o(self, *args):
        return self.horch(*args, terminal="t100")

    def start(self, *extra, agent="claude", title="T", spec="do it"):
        return self.o("worker-start", "--agent", agent, "--title", title, "--spec", spec, "--cwd", str(self.tmp), *extra)

    def env_of(self, did):
        """DB 의 dispatches.env(JSON). NULL 이면 None."""
        raw = self.db().execute("SELECT env FROM dispatches WHERE id=?", (did,)).fetchone()["env"]
        return None if raw is None else json.loads(raw)

    def count(self, table="dispatches") -> int:
        return self.db().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def run_guard(self, term, extra=None) -> dict:
        """가짜 hc 가 받은 그 터미널의 argv(launch-guard … -- <에이전트>)를 그 터미널 환경에서 실행한다. 가짜 에이전트 출력."""
        argv = self.hc_state()["terminals"][term]["argv"]
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=30,
                              env=self._env(term, {"FAKE_AGENT_ENV": WATCH, **(extra or {})}))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)

    def shown(self, did) -> dict:
        code, out = self.o("worker-show", "--dispatch", did, "--lines", "0")
        self.assertEqual(code, 0, out)
        return out["worker"]

    def listed(self, did) -> dict:
        code, out = self.o("worker-list")
        self.assertEqual(code, 0, out)
        return {w["id"]: w for w in out["workers"]}[did]


class EnvStartTest(EnvCase):
    def test_env_recorded_and_applied_just_before_exec(self):
        code, out = self.start("--env=HT_PORT=8110", "--env=HTEAM_SLOT=1", "--env=HT_URL=http://x/?a=b", "--env=HT_EMPTY=")
        self.assertEqual(code, 0, out)
        did, term = out["dispatch"], out["terminal"]
        want = {"HT_PORT": "8110", "HTEAM_SLOT": "1", "HT_URL": "http://x/?a=b", "HT_EMPTY": ""}
        self.assertEqual(self.env_of(did), want)  # 첫 = 에서 나눈다. 빈 값도 된다
        self.assertEqual(self.shown(did)["env"], want)
        self.assertEqual(self.listed(did)["env"], want)
        # 프리앰블과 에이전트 인자에는 넣지 않는다(설계 14.3)
        argv = self.hc_state()["terminals"][term]["argv"]
        self.assertFalse([a for a in argv if "HT_PORT" in a or "8110" in a], argv)
        preamble = (self.home / "runs" / self.run_id / "dispatches" / did / "preamble.md").read_text(encoding="utf-8")
        self.assertNotIn("HT_PORT", preamble)
        # 가드가 exec 한 에이전트는 그 값을 본다. 부른 쪽 환경의 같은 이름은 덮어쓴다
        got = self.run_guard(term, {"HT_PORT": "1"})
        self.assertEqual((got["fake"], got["terminal"]), ("claude", term))
        self.assertEqual(got["env"], want)

    def test_no_env_is_null_and_adds_nothing(self):
        # 회귀(0.2.0 과 같다): --env 가 없으면 기록은 NULL, 행의 env 는 null, 에이전트 환경에 더한 것이 없다
        code, out = self.start()
        self.assertEqual(code, 0, out)
        did, term = out["dispatch"], out["terminal"]
        self.assertIsNone(self.env_of(did))
        self.assertIsNone(self.shown(did)["env"])
        self.assertIn("env", self.listed(did))
        self.assertIsNone(self.listed(did)["env"])
        got = self.run_guard(term)
        self.assertEqual(got["env"], {"HT_PORT": None, "HTEAM_SLOT": None, "HT_URL": None, "HT_EMPTY": None})

    def test_codex_gets_env_in_environment_not_args(self):
        # Codex 인자는 지금처럼 HC_TERMINAL_ID 하나만 더한다. --env 값은 환경에만 있다(S2 는 실환경 Task 10)
        code, out = self.start("--env=HT_PORT=8110", agent="codex")
        self.assertEqual(code, 0, out)
        got = self.run_guard(out["terminal"])
        self.assertEqual(got["fake"], "codex")
        self.assertEqual(got["argv"][:2], ["-c", f'shell_environment_policy.set.HC_TERMINAL_ID="{out["terminal"]}"'])
        self.assertFalse([a for a in got["argv"] if "HT_PORT" in a], got["argv"])
        self.assertEqual(got["env"]["HT_PORT"], "8110")

    def test_limits_are_accepted(self):
        items = [f"--env=K{i}=v" for i in range(31)] + ["--env=_LONG=" + "x" * 1024]
        code, out = self.start(*items)
        self.assertEqual(code, 0, out)
        env = self.env_of(out["dispatch"])
        self.assertEqual(len(env), 32)
        self.assertEqual(len(env["_LONG"]), 1024)
        code, out = self.start("--env=lower_case=1")  # 소문자 이름도 된다(herdr-team 은 대문자만 쓴다, 설계 4.2)
        self.assertEqual(code, 0, out)

    def test_bad_env_is_usage_and_creates_nothing(self):
        cases = {
            "no_equals": ["--env=HT_PORT"],
            "empty_name": ["--env==v"],
            "digit_first": ["--env=1A=x"],
            "dash": ["--env=A-B=x"],
            "hc_prefix": ["--env=HC_TERMINAL_ID=t9"],
            "horch_prefix": ["--env=HORCH_POLL=1"],
            "newline": ["--env=A=x\ny"],
            "carriage_return": ["--env=A=x\ry"],
            "too_long": ["--env=A=" + "x" * 1025],
            "too_long_utf8": ["--env=A=" + "가" * 342],  # 342자, 1026바이트
            "duplicate": ["--env=A=1", "--env=A=2"],
            "too_many": [f"--env=K{i}=v" for i in range(33)],
        }
        before = self.count()
        for name, items in cases.items():
            with self.subTest(case=name):
                code, out = self.start(*items)
                self.assertEqual((code, out["error"]["code"]), (2, "usage"), out)
        self.assertEqual(self.count(), before)
        self.assertEqual(self.count("tasks"), 0)
        self.assertFalse([c for c in self.hc_calls() if c[:1] == ["run"]])

    def test_messages(self):
        code, out = self.start("--env=HT_PORT=1", "--env=HT_PORT=2")
        self.assertIn("HT_PORT", out["error"]["message"])
        code, out = self.start("--env=HC_X=1")
        self.assertIn("HC_·HORCH_", out["error"]["message"])
        code, out = self.start(*[f"--env=K{i}=v" for i in range(33)])
        self.assertIn("32", out["error"]["message"])


class EnvRetryTest(EnvCase):
    def test_retry_inherits_last_env_unless_given(self):
        self.fail_hc("run", "spawn_failed")
        code, out = self.start("--env=HT_PORT=8110", "--env=HTEAM_SLOT=1")
        self.assertEqual((code, out["error"]["code"]), (1, "launch_failed"))
        task, d1 = out["task"], out["dispatch"]
        self.assertEqual(self.env_of(d1), {"HT_PORT": "8110", "HTEAM_SLOT": "1"})  # hc run 전에 기록한다
        row = self.listed(d1)
        self.assertEqual(row["attention"], "launch_failed")
        self.assertFalse([a for a in row["next"] if a.startswith("--env")], row["next"])  # 재시도가 물려받는다
        self.clear_hc_fail("run")
        # --env 없는 --retry: 그 Task 의 마지막 Dispatch 값
        code, r2 = self.o("worker-start", "--agent", "claude", "--task", task, "--retry", "--cwd", str(self.tmp))
        self.assertEqual(code, 0, r2)
        self.assertEqual(self.env_of(r2["dispatch"]), {"HT_PORT": "8110", "HTEAM_SLOT": "1"})
        self.assertEqual(self.run_guard(r2["terminal"])["env"]["HT_PORT"], "8110")
        # --env 를 주면 그 값(합치지 않고 바꾼다)
        db = self.db()
        db.execute("UPDATE dispatches SET state='launch_failed' WHERE id=?", (r2["dispatch"],))
        db.commit()
        code, r3 = self.o("worker-start", "--agent", "claude", "--task", task, "--retry", "--cwd", str(self.tmp),
                          "--env=HT_DB=5481")
        self.assertEqual(code, 0, r3)
        self.assertEqual(self.env_of(r3["dispatch"]), {"HT_DB": "5481"})
        # --retry 없는 --task(앞 시도가 abandoned)는 물려받지 않는다(설계 14.1 은 --task --retry 만)
        db.execute("UPDATE dispatches SET state='abandoned' WHERE id=?", (r3["dispatch"],))
        db.commit()
        code, r4 = self.o("worker-start", "--agent", "claude", "--task", task, "--cwd", str(self.tmp))
        self.assertEqual(code, 0, r4)
        self.assertIsNone(self.env_of(r4["dispatch"]))

    def test_retry_of_dispatch_without_env_stays_null(self):
        self.fail_hc("run", "spawn_failed")
        code, out = self.start()
        self.assertEqual(code, 1, out)
        self.clear_hc_fail("run")
        code, r2 = self.o("worker-start", "--agent", "claude", "--task", out["task"], "--retry", "--cwd", str(self.tmp))
        self.assertEqual(code, 0, r2)
        self.assertIsNone(self.env_of(r2["dispatch"]))


class EnvPersistTest(EnvCase):
    def test_keep_open_env_and_terminal(self):
        code, out = self.o("worker-start", "--keep-open", "--agent", "claude", "--title", "T1", "--spec", "첫 번째",
                           "--cwd", str(self.tmp), "--env=HT_PORT=8110")
        self.assertEqual(code, 0, out)
        d1, term = out["dispatch"], out["terminal"]
        self.assertEqual(self.env_of(d1), {"HT_PORT": "8110"})  # 고정 터미널의 첫 환경
        code, res = self.horch("done", "--dispatch", d1, "--outcome", "succeeded", "--summary", "끝", terminal=term)
        self.assertEqual(code, 0, res)
        self.update_terminal(term, status="done", turn=3)
        before = self.count()
        # 살아 있는 세션의 환경은 바꾸지 못한다: --terminal 과 --env 는 같이 쓸 수 없다
        code, res = self.o("worker-start", "--terminal", term, "--title", "T2", "--spec", "두 번째", "--env=HT_PORT=1")
        self.assertEqual((code, res["error"]["code"]), (2, "usage"), res)
        self.assertIn("--env", res["error"]["message"])
        self.assertEqual(self.count(), before)
        # 같은 터미널에 넣은 Dispatch 는 그 세션의 환경(앞 고정 Dispatch 의 값)을 기록한다
        code, res = self.o("worker-start", "--terminal", term, "--title", "T2", "--spec", "두 번째")
        self.assertEqual(code, 0, res)
        self.assertEqual(self.env_of(res["dispatch"]), {"HT_PORT": "8110"})
        self.assertEqual(self.shown(res["dispatch"])["env"], {"HT_PORT": "8110"})


class SchemaV4Test(HorchCase):
    def open(self) -> Store:
        s = Store(self.home)
        self.addCleanup(s.close)
        return s

    def test_new_db_is_v4(self):
        s = self.open()
        self.assertEqual(SCHEMA_VERSION, 4)
        self.assertEqual(s.one("SELECT value FROM meta WHERE key='schema_version'")["value"], "4")
        self.assertIn("env", {r["name"] for r in s.all("PRAGMA table_info(dispatches)")})

    def test_migrates_v3_to_v4(self):
        s = self.open()
        s.run("INSERT INTO runs(id, objective, created_at, updated_at) VALUES ('run-1','o','t','t')")
        s.run("INSERT INTO tasks(id, run_id, title, spec, created_at) VALUES ('task-1','run-1','T','S','t')")
        s.run("INSERT INTO dispatches(id, task_id, run_id, attempt, agent, cwd, terminal, state, created_at) "
              "VALUES ('dsp-1','task-1','run-1',1,'claude','/x','t9','active','t')")
        s.run("ALTER TABLE dispatches DROP COLUMN env")
        s.run("UPDATE meta SET value='3' WHERE key='schema_version'")
        s.close()
        s2 = self.open()
        self.assertEqual(s2.one("SELECT value FROM meta WHERE key='schema_version'")["value"], "4")
        self.assertIsNone(s2.one("SELECT env FROM dispatches WHERE id='dsp-1'")["env"])  # 기존 행은 NULL


class EnvSkillTest(HorchCase):
    def test_skill_mentions_env(self):
        proc = subprocess.run([sys.executable, str(BIN), "--home", str(self.home), "skill"],
                              capture_output=True, text=True, env=self.env, timeout=30)
        self.assertEqual(proc.returncode, 0)
        for needle in ("`--env KEY=VALUE`", "32개까지", "`hc run` 터미널은 부른 셸의 환경을 물려받지 않는다",
                       "비밀값을 넘기지 않는다", "`--task --retry` 에 주지 않으면 그 Task 의 마지막 값을 쓰고",
                       "`--terminal` 과는 같이 쓸 수 없다"):
            self.assertIn(needle, proc.stdout)


if __name__ == "__main__":
    unittest.main()
```

**Replace** `herdr-orch/tests/fakes/claude`

```python
#!/usr/bin/env python3
"""테스트용 가짜 claude. 받은 argv 와 HC_TERMINAL_ID 를 JSON 으로 출력한다.
FAKE_AGENT_ENV(쉼표로 나눈 이름)가 있으면 그 이름의 환경 값도 "env" 로 출력한다(0.3.0 --env 시험. 없으면 지금 출력 그대로)."""
import json
import os
import sys

out = {"fake": "claude", "argv": sys.argv[1:], "terminal": os.environ.get("HC_TERMINAL_ID")}
names = os.environ.get("FAKE_AGENT_ENV")
if names:
    out["env"] = {k: os.environ.get(k) for k in names.split(",") if k}
print(json.dumps(out))
```

**Replace** `herdr-orch/tests/fakes/codex`

```python
#!/usr/bin/env python3
"""테스트용 가짜 codex. --help 에 --no-daemon 을 보이고, 그 밖에는 argv 를 JSON 으로 출력한다.
FAKE_AGENT_ENV(쉼표로 나눈 이름)가 있으면 그 이름의 환경 값도 "env" 로 출력한다(0.3.0 --env 시험. 없으면 지금 출력 그대로)."""
import json
import os
import sys

if sys.argv[1:2] == ["--help"]:
    print("Usage: codex [OPTIONS]\n      --no-daemon")
    sys.exit(0)
out = {"fake": "codex", "argv": sys.argv[1:], "terminal": os.environ.get("HC_TERMINAL_ID")}
names = os.environ.get("FAKE_AGENT_ENV")
if names:
    out["env"] = {k: os.environ.get(k) for k in names.split(",") if k}
print(json.dumps(out))
```

**Edit** `herdr-orch/tests/test_persist.py`

```python
        self.assertEqual(SCHEMA_VERSION, 3)
        self.assertEqual(s.one("SELECT value FROM meta WHERE key='schema_version'")["value"], "3")
```

```python
        # v4(0.3.0, herdr-orch 설계 14.2)도 v3 열·인덱스를 그대로 둔다
        self.assertGreaterEqual(SCHEMA_VERSION, 3)
        self.assertEqual(s.one("SELECT value FROM meta WHERE key='schema_version'")["value"], str(SCHEMA_VERSION))
```

**Edit** `herdr-orch/tests/test_persist.py`

```python
        self.assertEqual(s2.one("SELECT value FROM meta WHERE key='schema_version'")["value"], "3")
```

```python
        # 누적 마이그레이션: v2 → v3 → v4(herdr-orch 설계 14.2)
        self.assertEqual(s2.one("SELECT value FROM meta WHERE key='schema_version'")["value"], str(SCHEMA_VERSION))
```

**Edit** `herdr-orch/tests/test_meta.py`

```python
        self.assertEqual(VERSION, "0.2.0")  # 고정 터미널(herdr-orch 설계 13장)
```

```python
        self.assertEqual(VERSION, "0.3.0")  # 워커 환경 변수(herdr-orch 설계 14장)
```

**Edit** `herdr-orch/tests/test_cli.py`

```python
        self.assertEqual(out, {"ok": True, "version": "0.2.0"})
```

```python
        self.assertEqual(out, {"ok": True, "version": "0.3.0"})
```

**Edit** `herdr-team/tests/test_base.py`

```python
            self.assertEqual(h.ok("version")["version"][:4], "0.2.")  # 함께 배포하는 herdr-orch 0.2.0
```

```python
            self.assertEqual(h.ok("version")["version"][:4], "0.3.")  # 함께 배포하는 herdr-orch 0.3.0
```

**Edit** `herdr-team/tests/test_base.py`

```python
        old = self.install("old", "0.1.2")
        user = self.install("user", "0.2.0")
        other = self.install("other", "0.2.9")
        mine = self.install("mine", "0.2.0")
        local = self.install("local", "0.2.1")
```

```python
        old = self.install("old", "0.2.0")
        user = self.install("user", "0.3.0")
        other = self.install("other", "0.3.9")
        mine = self.install("mine", "0.3.0")
        local = self.install("local", "0.3.1")
```

**Edit** `herdr-team/tests/test_base.py`

```python
            entries = [{"scope": "user", "installPath": str(old), "version": "0.1.2"},
```

```python
            entries = [{"scope": "user", "installPath": str(old), "version": "0.2.0"},
```

**Edit** `herdr-team/tests/test_base.py`

```python
            self.assertIn("쓰지 않은 설치: herdr-orch@herdr-team user 0.1.2(0.2.0 보다 낮다)", ctx.exception.message)
```

```python
            self.assertIn("쓰지 않은 설치: herdr-orch@herdr-team user 0.2.0(0.3.0 보다 낮다)", ctx.exception.message)
```

**Edit** `herdr-team/tests/test_base.py`

```python
        # 그 항목만 이유와 함께 빼고 뒤의 정상 후보를 고른다
        good = self.install("good", "0.2.0")
```

```python
        # 그 항목만 이유와 함께 빼고 뒤의 정상 후보를 고른다
        good = self.install("good", "0.3.0")
```

**Edit** `herdr-team/tests/test_base.py`

```python
        good = self.install("good", "0.2.0")
        odd = self.install("odd", "1.2.²")
```

```python
        good = self.install("good", "0.3.0")
        odd = self.install("odd", "1.2.²")
```

**Edit** `herdr-team/tests/test_cli.py`

```python
        # hteam 이 설치 기록에서 받는 가장 낮은 herdr-orch 는 함께 배포하는 herdr-orch 와 같다(고정 터미널, 0.2.0)
```

```python
        # hteam 이 설치 기록에서 받는 가장 낮은 herdr-orch 는 함께 배포하는 herdr-orch 와 같다(워커 환경 변수 --env, 0.3.0)
```

- [ ] **Step 2: 실패 확인**

Run: `cd herdr-orch && python3 -m unittest tests.test_env tests.test_persist tests.test_meta tests.test_cli tests.test_guard 2>&1 | tail -5` 그다음 `cd herdr-team && python3 -m unittest tests.test_base tests.test_cli 2>&1 | tail -5`
Expected: herdr-orch `Ran 97 tests` / `FAILED (failures=10, errors=3)`. 대표 메시지: `AssertionError: 2 != 0 : {'ok': False, 'error': {'code': 'usage', 'message': 'unrecognized arguments: --env=HT_PORT=8110', 'hint': ''}}`(옵션이 없다, 4건), `AssertionError: Tuples differ: (2, 'usage') != (1, 'launch_failed')`(재시도 시험), `AssertionError: 'HC_·HORCH_' not found in 'unrecognized arguments: --env=HC_X=1'`, `AssertionError: 3 != 4`(SCHEMA_VERSION), `sqlite3.OperationalError: no such column: env`(오류 3건: 행의 env, v4 마이그레이션 시험), `AssertionError: '0.2.0' != '0.3.0'`(test_meta·test_cli), skill 문구의 `AssertionError: '`--env KEY=VALUE`' not found`. `test_bad_env_is_usage_and_creates_nothing` 은 옵션이 없어도 usage 라 이 단계에서도 통과한다(문구는 `test_messages` 가 본다). `test_persist`(SchemaV3Test 는 기대값만 바꿔 통과)와 `test_guard`(가짜 에이전트 출력이 그대로)는 이 단계에서도 통과한다. herdr-team `Ran 21 tests` / `FAILED (failures=2)`(`AssertionError: '0.2.' != '0.3.'`, 설치 기록 고르기의 `AssertionError: HteamError not raised`. `test_versions_match` 는 Step 3 이 marketplace·`HORCH_MIN` 을 함께 올리므로 이 단계에서는 통과한다). HEAD 에 이 태스크의 Step 1 블록만 적용한 트리에서 쟀다. 계획을 쓸 때 스크래치의 시범 구현(계획에 넣지 않았다)으로 `tests.test_env`·`test_persist`·`test_meta`·`test_cli`·`test_guard`·`test_workers_start`·`test_workers_manage`·`test_store`(183개)와 herdr-team `test_base`·`test_cli` 가 통과하는 것을 확인했다.

- [ ] **Step 3: 구현**

Rules 1–5 와 Interfaces 대로 `store.py`·`workers.py`·`persist.py`·`guard.py`·`cli.py`·`paths.py`, 두 plugin 기록(`herdr-orch/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` 의 herdr-orch 항목), `herdr-team/lib/hteam/horch.py` 를 고친다. hc 는 `hcio.py` 에서만 부른다(이 태스크는 hc 호출을 더하지 않는다). skill.md 는 아래 블록 그대로다.

**Edit** `herdr-orch/lib/horch/skill.md`

```markdown
   `worker-start` 결과의 `warning`(배치 문제)과 `warnings`(목록, 예: 영수증 기록 실패)가 있으면 사용자에게 알린다.
```

```markdown
   `worker-start` 결과의 `warning`(배치 문제)과 `warnings`(목록, 예: 영수증 기록 실패)가 있으면 사용자에게 알린다.
   워커 에이전트에 환경 변수를 주려면 `--env KEY=VALUE` 를 되풀이한다(32개까지. `hc run` 터미널은 부른 셸의 환경을 물려받지 않는다). 가드가 에이전트를 실행하기 직전에 넣고 Dispatch 기록과 `worker-show` 의 `env` 에 남으므로 비밀값을 넘기지 않는다. `--task --retry` 에 주지 않으면 그 Task 의 마지막 값을 쓰고, `--terminal` 과는 같이 쓸 수 없다.
```

- [ ] **Step 4: 통과 확인**

Run: `cd herdr-orch && python3 -m unittest tests.test_env tests.test_persist tests.test_meta tests.test_cli tests.test_guard 2>&1 | tail -3`, 저장소 루트에서 `bash herdr-orch/tests/run.sh 2>&1 | tail -3`(1–2분), 그다음 `cd herdr-team && python3 -m unittest tests.test_base tests.test_cli 2>&1 | tail -3`
Expected: 모두 `OK`(0.2.0 시험이 그대로 통과한다: `--env` 가 없으면 env 는 NULL 이고 가드 동작이 같다).

- [ ] **Step 5: 정적 확인과 커밋**

```bash
python3 - <<'PY'
import ast, pathlib
for f in ["herdr-orch/lib/horch/store.py", "herdr-orch/lib/horch/workers.py", "herdr-orch/lib/horch/persist.py",
          "herdr-orch/lib/horch/guard.py", "herdr-orch/lib/horch/cli.py", "herdr-orch/lib/horch/paths.py",
          "herdr-team/lib/hteam/horch.py", "herdr-orch/tests/fakes/claude", "herdr-orch/tests/fakes/codex",
          "herdr-orch/tests/test_env.py", "herdr-orch/tests/test_persist.py", "herdr-orch/tests/test_meta.py",
          "herdr-orch/tests/test_cli.py", "herdr-team/tests/test_base.py", "herdr-team/tests/test_cli.py"]:
    ast.parse(pathlib.Path(f).read_text(encoding="utf-8"), feature_version=(3, 11))
PY
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews'
FILES="herdr-orch/lib/horch herdr-orch/.claude-plugin/plugin.json .claude-plugin/marketplace.json herdr-team/lib/hteam/horch.py herdr-orch/tests/fakes/claude herdr-orch/tests/fakes/codex herdr-orch/tests/test_env.py herdr-orch/tests/test_persist.py herdr-orch/tests/test_meta.py herdr-orch/tests/test_cli.py herdr-team/tests/test_base.py herdr-team/tests/test_cli.py"
git add -- $FILES
git commit -m "feat(herdr-orch): 0.3.0 워커 환경 변수(worker-start --env, 스키마 v4 dispatches.env, launch-guard 의 exec 직전 적용, --retry 물려받기), HORCH_MIN 0.3.0" \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- $FILES
```

Expected: ast 오류 없음, grep 빈 출력, 커밋 하나. 구현자는 여기서 멈춘다(컨트롤러가 `scripts/codex-review.sh commit <sha>`).

---

### Task 2: 설정과 사양 — `[workspace]`·`[redmine]` 검사, worktree 모드의 고정 에이전트·승인 직무 검사, 사양·tasks.toml 의 `issue`, `[test]` 의 `tester_paths`·`full_if` 형식, 템플릿 주석 예시

설계 4.1·4.2 의 7단계 설정(`[workspace]`, `[redmine]`), 5.1·5.2 의 `issue`, 5.2 묶음 규칙 1 의 7단계 문장, 5.7 의 `tester_paths`·`full_if` 형식을 만든다. 이 태스크는 값을 읽고 검사해 다른 태스크가 쓸 모양(`config.Workspace`·`config.Redmine`·`Config.workspace`·`Config.redmine`, `Spec.issue`, `GateConfig.tester_paths`·`full_if`)만 만든다. 그 값으로 슬롯을 돌리거나(Task 3–5) `full_if` 로 full 을 돌리거나(Task 6) 이슈 줄을 보이거나(Task 7) Redmine 을 바꾸는(Task 8) 일은 하지 않는다. 표가 없으면 `Config.workspace` 는 shared 기본값, `Config.redmine` 은 None 이고 나머지 출력은 0.4.0 그대로다. 묶음 규칙 1 은 `tester_paths` 가 있을 때만 바뀐다. `tester_paths`·`full_if` 는 돌릴 명령을 바꾸지 않으므로 확정 식별값(`testgate.digest`)에 넣지 않는다(이미 한 확정이 그대로 맞는다). 템플릿 `config.toml` 에는 두 표를 주석 예시로만 둔다(init 이 묻는다, 설계 9.1 의 4a 는 Task 9).

**Files:**
- Modify: `herdr-team/lib/hteam/config.py`(`Workspace`·`Redmine`, `[workspace]`·`[redmine]` 검사, worktree 모드의 crew·승인 직무 검사, `Config.workspace`·`Config.redmine`, 검사 없이 읽는 `TestSettings`·`test_settings`·`redmine_key_env`), `herdr-team/lib/hteam/specs.py`(`ISSUE_RE`·`issue_value`, `Spec.issue`, issue 검사), `herdr-team/lib/hteam/plan.py`(tasks.toml `issue` 형식·사양 front matter 복사, 묶음 규칙 1 의 `tester_paths`), `herdr-team/lib/hteam/testgate.py`(`KEYS`, `GateConfig.tester_paths`·`full_if`, 형식 문구, `confirm_section`), `herdr-team/templates/config.toml`(주석 예시)
- Test: `herdr-team/tests/test_config.py`·`herdr-team/tests/test_state_specs.py`·`herdr-team/tests/test_plan.py`·`herdr-team/tests/test_testgate.py`(새 클래스 덧붙이기)

**Interfaces:**
- Consumes: `config.validate`·`build`·`load`·`_table`·`_str_list`·`_pos_int`·`_nonempty`, `globs.owns_problem`, `specs.parse`·`problems`·`render`, `plan._fields`·`validate`·`group_problems`·`_spec_text`·`_roundtrip`·`digest`, `testgate.config_problems`·`parse_config`·`normalized`·`digest`·`confirm_section`.
- Produces:
  - `config.py` 상수: `WORKSPACE_MODES = ("shared", "worktree")`, `WORKSPACE_ROLES = ("developer", "tester")`(기본 roles), `WORKSPACE_KEYS = ("mode", "roles", "slots", "setup", "teardown", "setup_timeout_min", "env")`, `ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")`, `ENV_NAME_PREFIXES = ("HTEAM_", "HC_", "HORCH_")`, `ENV_NAME_WORDS = ("KEY", "SECRET", "TOKEN")`, `ENV_VALUE_MAX = 1024`(UTF-8 바이트), `WORKSPACE_ENV_MAX = 31`(워커에는 `HTEAM_SLOT` 을 더해 horch `--env` 로 넘기므로 Task 1 의 `ENV_MAX = 32` 보다 하나 적다, Codex 계획 리뷰 r1), `REDMINE_KEYS = ("url", "key_env", "env_file", "status")`, `REDMINE_STATUS = ("start", "done", "changes", "closed")`, `ENV_VAR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")`(`key_env`).
  - `config.Workspace`(frozen dataclass, 모든 필드 기본값): `mode: str = "shared"`, `roles: tuple[str, ...] = WORKSPACE_ROLES`, `slots: int = 2`, `setup: str | None = None`, `teardown: str | None = None`, `setup_timeout_min: int = 20`, `env: dict[str, str] = field(default_factory=dict)`(값의 `{slot}` 은 그대로). 속성 `on -> bool`(`mode == "worktree"`), 메서드 `covers(role: str) -> bool`(`on and role in roles`).
  - `config.Redmine`(frozen dataclass): `url: str`(끝의 `/` 를 모두 뗀 값), `key_env: str`, `env_file: str | None`, `status: dict[str, int]`(`start`·`done`·`changes`·`closed`).
  - `Config` 에 필드 `workspace: Workspace = field(default_factory=Workspace)`, `redmine: Redmine | None = None` 를 맨 뒤에 더한다. `build` 가 채운다: `[workspace]` 가 없으면 `Workspace()`, 있으면 그 값(키가 없으면 기본값. `roles` 가 없으면 `WORKSPACE_ROLES` 가운데 `[roles]` 에 정의된 것만 설정 순서가 아니라 `WORKSPACE_ROLES` 순서로). `[redmine]` 이 없으면 None.
  - 검사 문구(원문, 해당하는 것을 모두 모아 지금처럼 `bad_config` exit 2. `data.errors` 목록):
    - `[workspace] 는 표여야 한다`, `[workspace.env] 는 표여야 한다`, `[redmine] 는 표여야 한다`(지금 `_table` 꼴)
    - `workspace.mode 는 shared·worktree 다`
    - `workspace.roles 는 비지 않은 직무 이름 목록이다`(목록이 아니거나 비었거나 비지 않은 문자열이 아닌 항목. 설계에 원문이 없어 crew 의 문구에 맞췄다)
    - `workspace.roles 에 정의되지 않은 직무가 있다: <목록>`(목록은 쓴 순서, `, ` 로 잇는다)
    - `workspace.slots 는 1–9 정수다`, `workspace.setup 은 비지 않은 문자열이다`, `workspace.teardown 은 비지 않은 문자열이다`, `workspace.setup_timeout_min 은 1–120 정수다`(정수는 bool 이 아니다)
    - `workspace.env.<이름>: 이름은 대문자·숫자·_ 이고 HTEAM_·HC_·HORCH_ 로 시작하지 않으며 KEY·SECRET·TOKEN 을 담지 않는다`
    - `workspace.env.<이름>: 값은 줄바꿈 없는 1 KiB 이하 문자열이다`(문자열이 아님, `splitlines` 가 나누는 줄바꿈이 있음, NUL(`\x00`)이 있음, UTF-8 1024 바이트 넘음. 빈 문자열은 된다. NUL 은 subprocess 환경과 horch `--env` 검사가 받지 않는다, Codex 계획 리뷰 r1)
    - `workspace.env 는 31개 이하다(HTEAM_SLOT 을 더해 horch --env 32개 안이다)`(`[workspace.env]` 표의 항목이 `WORKSPACE_ENV_MAX` 보다 많을 때 한 줄. 항목마다의 검사는 그대로 한다)
    - `workspace: 모르는 키 <정렬한 키>`
    - worktree 모드에서만: `crew.<이름>: <직무> 는 작업 공간 직무다(worktree 모드에서는 임시 워커만 맡는다)`(그 고정 에이전트의 roles 가운데 작업 공간 직무마다, roles 순서), `user_approval_roles 의 <직무> 는 작업 공간 직무다(worktree 모드에서는 승인 직무로 두지 않는다)`(목록 순서)
    - `redmine.url 은 http·https URL 이다`, `redmine.key_env 는 환경 변수 이름이다`, `redmine.env_file 은 프로젝트 안 상대 경로다`, `redmine.status 는 start·done·changes·closed 네 양의 정수다`, `redmine: 모르는 키 <정렬한 키>`
  - 테스트 실행 설정(Rules 11, Codex 계획 리뷰 r1. `hteam test` 는 설정이 깨져도 돈다):
    - `config.RedmineKey`(frozen dataclass): `key_env: str`.
    - `config.TestSettings`(frozen dataclass): `workspace: Workspace = field(default_factory=Workspace)`, `redmine: RedmineKey | None = None`. `Config` 와 같은 이름의 두 속성만 가진다. 테스트 명령·setup·teardown 의 환경과 위치를 정하는 함수(Task 3 의 `workspace.slot_env`·`task_env`·`run_hook`, Task 5 의 `claim_final`, `testgate.child_env`)는 `cfg.workspace` 와 `cfg.redmine.key_env` 만 쓰므로 `Config` 대신 이것을 받아도 된다.
    - `config.redmine_key_env(p) -> str | None`: config.toml 을 `tomllib` 로 읽어 `redmine` 표의 `key_env` 가 `ENV_VAR_RE` 에 맞는 문자열이면 그 이름. 파일 없음·읽기 실패·TOML 오류·표 없음·형식 틀림이면 None. `validate` 를 부르지 않고 예외를 내지 않는다.
    - `config.test_settings(p) -> TestSettings`: config.toml 을 검사 없이 한 번 읽는다(읽지 못하면 빈 표로 본다). `workspace` 는 `[workspace]` 표가 Rules 2 의 검사(그 표만. 다른 표와 Rules 3 은 보지 않는다)를 통과하면 `build` 와 같은 `Workspace`, 아니면(표 없음·표가 아님·그 표의 오류) `Workspace()`. `redmine` 은 `redmine_key_env(p)` 가 있으면 `RedmineKey(그 이름)`, 없으면 None. 예외를 내지 않는다.
  - `specs.ISSUE_RE = re.compile(r"#?([0-9]{1,9})")`, `specs.issue_value(value) -> str | None`: bool 이면 None, int 면 `str(value)` 로 본 뒤, 문자열이면 `ISSUE_RE.fullmatch(value.strip())` 의 숫자(앞 `#` 를 뗀 값, 앞자리 0 은 그대로), 아니면 None. 사양 front matter 와 tasks.toml 이 같이 쓴다.
  - `specs.Spec.issue: str | None = None`(`depends_on` 다음 필드). `parse` 가 `issue_value(front.get("issue"))` 로 채운다. `front["issue"]` 는 쓴 값 그대로다.
  - `specs.problems` 문구(원문): `issue 는 숫자 1–9자리 이슈 번호다(앞의 # 는 뗀다): <repr(쓴 값)>`(front matter 에 `issue` 가 있는데 `Spec.issue` 가 None). `start`·`specs.check` 는 지금처럼 exit 2 `bad_spec`.
  - `plan.ALLOWED` 에 `issue`. `_fields` 문구(원문): `<label>: issue 는 숫자 1–9자리 이슈 번호다(문자열이나 정수, 앞의 # 는 뗀다)`. `plan apply` 가 사양 front matter 의 `plan_key` 줄 다음에 `issue: <issue_value>` 한 줄을 쓴다(없으면 쓰지 않는다). 태스크 digest(`plan.digest(task)`)는 tasks.toml 의 태스크 표 그대로라 `issue` 가 든다(이미 적용한 태스크에 나중에 넣으면 `plan_changed` exit 2).
  - `plan.group_problems(keys, fresh, tester_paths=None)`: 규칙 1 의 기대 owns 는 `tester_paths` 가 None 이면 지금 그대로 `["tests/{k}/**", "docs/qa/{k}.md"]`, 있으면 `[p.replace("{key}", k) for p in tester_paths] + [f"docs/qa/{k}.md"]`. 문구는 `{k}: tester 태스크 owns 는 정확히 [<기대 owns 를 차례로 "…" 로 감싸 ", " 로 이은 것>] 다`(기본 경로면 지금 문구와 글자까지 같다). 둘째 인자까지만 주는 지금 호출(`test_interview`)은 그대로 된다.
  - `testgate.KEYS = ("quick", "full", "timeout_min", "ok_exit", "exclusive", "tester_paths", "full_if")`. `GateConfig` 에 `tester_paths: tuple[str, ...] | None = None`, `full_if: tuple[str, ...] = ()` 를 맨 뒤에 더한다(다섯 인자 생성은 그대로 된다). `normalized`·`digest` 는 다섯 값 그대로다.
  - `testgate.config_problems` 문구(원문, 지금 문제 뒤에 이 차례로): `[test]: tester_paths 는 {key} 를 한 번씩 담은 경로 목록이다`(목록이 아니거나 비었거나, 항목이 문자열이 아니거나 `{key}` 를 정확히 한 번 담지 않는다. 하나라도 그러면 이 한 줄만), `[test]: tester_paths <repr(항목)>: <globs.owns_problem 이유>`(항목의 `{key}` 를 `key` 로 바꿔 owns 값 규칙 4.1 을 본다), `[test]: full_if 는 glob 목록이다`(목록이 아니거나 비지 않은 문자열이 아닌 항목. 빈 목록은 된다), `[test]: full_if <repr(항목)>: <globs.owns_problem 이유>`.
  - `testgate.confirm_section(cfg)`: 다섯 줄 뒤에 `tester_paths` 가 None 이 아니면 `tester_paths = <json.dumps(list, ensure_ascii=False)>`, `full_if` 가 비지 않았으면 `full_if = <같은 꼴>` 줄을 더한다(설계 5.7 "확정 질문의 `## 테스트 명령` 절에는 있으면 함께 보인다").
  - `templates/config.toml`: `[overflow]` 와 `[defaults]` 사이의 주석 예시(Step 1 의 Edit 블록 원문). `# [workspace]`·`# [redmine]` 줄부터 빈 줄 전까지는 `# ` 를 떼면 TOML 이다.

**Rules:**

1. 검사 차례(설계 4.2): `validate` 의 지금 검사(`_crew` 까지) 뒤에 `_workspace` → (worktree 모드면) 작업 공간 직무 검사 → `_redmine` 을 부른다. 모두 `errors` 에 모은다(앞 오류가 있어도 계속 본다). 문구 차례는 Interfaces 의 차례(같은 종류 안에서는 표의 키 순서)다. 시험은 차례가 아니라 들어 있는지와 개수를 본다.
2. `[workspace]`(설계 4.1·4.2): 표가 아니면 그 한 줄로 끝낸다. `mode` 가 없으면 shared, 있으면 `WORKSPACE_MODES` 안이어야 한다. `roles` 가 있으면 비지 않은 직무 이름 목록이고 각 이름이 `[roles]` 에 있어야 한다. `slots`(1–9)·`setup_timeout_min`(1–120)은 bool 이 아닌 정수다. `setup`·`teardown` 은 있으면 비지 않은 문자열(`strip` 뒤)이다. `env` 가 있으면 표이고 항목마다 이름(`ENV_NAME_RE` 에 맞고 `ENV_NAME_PREFIXES` 로 시작하지 않고 `ENV_NAME_WORDS` 를 부분 문자열로도 담지 않는다)과 값(문자열, 한 줄, NUL 없음, UTF-8 1024 바이트 이하)을 따로 본다. 한 항목에 둘 다 틀리면 두 줄이다. 항목이 `WORKSPACE_ENV_MAX`(31)보다 많으면 개수 문구 한 줄을 더한다(워커·리뷰어·테스트에는 `HTEAM_SLOT` 이 더해져 horch `--env` 상한 32 를 넘지 않게. 설정 검사를 통과한 뒤 setup 까지 마치고 워커를 띄울 때 usage 로 막히지 않는다). 모르는 키는 `WORKSPACE_KEYS` 밖이다. `mode = "shared"` 거나 `mode` 가 없어도 나머지 키는 같은 검사를 한다(검사만 하고 쓰지 않는다, 설계 4.1).
3. 작업 공간 직무 검사(설계 4.2·5.10.6, Codex 설계 리뷰 r1): `mode == "worktree"` 일 때만, 작업 공간 직무(검사를 통과한 `roles` 또는 기본값을 정의된 직무로 거른 것)에 대해 `[crew.*]` 의 표마다 `roles` 가 문자열 목록이면 그 가운데 작업 공간 직무마다 `crew.<이름>: …` 한 줄, `user_approval_roles` 가 문자열 목록이면 그 가운데 작업 공간 직무마다 한 줄. shared 면 보지 않는다.
4. 기본 roles: `roles` 키가 없으면 `WORKSPACE_ROLES` 가운데 `[roles]` 에 정의된 직무만이다(tester 직무가 없는 프로젝트는 `("developer",)`, 둘 다 없으면 빈 튜플이고 그러면 worktree 모드여도 슬롯에서 도는 직무가 없다. 설계에 없는 경우라 오류로 하지 않는다). `[workspace]` 표가 아예 없으면 `Workspace()`(roles 기본값 그대로. shared 라 쓰이지 않는다).
5. `[redmine]`(설계 4.1·4.2·8.12): 표가 있으면 `url`·`key_env`·`status` 는 반드시 있고 `env_file` 은 선택이다. `url`: 문자열, 공백 문자가 없고, `urllib.parse.urlsplit` 의 scheme 이 `http`·`https`, netloc 이 비지 않았다. 없거나 틀리면 그 문구. `key_env`: `ENV_VAR_RE` 에 맞는 문자열. `env_file`: 비지 않은 한 줄 문자열이고, `~` 로 시작하지 않고, `PurePosixPath` 가 절대 경로가 아니고 `..` 마디가 없다. `status`: 키가 정확히 `REDMINE_STATUS` 넷인 표이고 값마다 `_pos_int`. 모르는 키는 `REDMINE_KEYS` 밖이다. `build` 의 `url` 은 `rstrip("/")`, 다른 값은 그대로, `status` 는 `{k: status[k] for k in REDMINE_STATUS}`.
6. 사양 `issue`(설계 5.1): `parse` 는 `issue` 를 다른 front matter 처럼 문자열로 두고 `Spec.issue = specs.issue_value(...)` 를 채운다. `problems` 는 `"issue" in spec.front and spec.issue is None` 이면 Interfaces 문구 한 줄을 더한다(빈 값 `issue:` 도 틀린 값이다). 이 태스크는 `issue` 를 워커 사양·리뷰 프롬프트·일괄 승인 줄에 보이지 않는다(Task 7·8).
7. tasks.toml `issue`(설계 5.2): `_fields` 가 `"issue" in t and specs.issue_value(t["issue"]) is None` 이면 문구를 더한다. `_spec_text` 는 `issue` 가 있으면 `specs.render(…, front={"issue": specs.issue_value(t["issue"])})`(그래서 줄은 `plan_key` 다음). `_roundtrip` 의 기대 front 에 `issue` 가 있으면 `want["issue"] = specs.issue_value(t["issue"])` 를 더한다. digest 는 손대지 않는다(태스크 표에 이미 든다).
8. 묶음 규칙 1(설계 5.2 의 7단계 문장): `validate` 는 `test` 가 표이고 형식 검사를 통과했을 때(그래서 묶음 규칙을 볼 때) `tester_paths = test.get("tester_paths")` 를 `group_problems(keys, fresh, tester_paths)` 에 넘긴다. QA 보고서 경로 `docs/qa/{key}.md` 는 바꾸지 않는다(묶음 후속이 읽는다, 설계 8.4). 규칙 2·3·4 는 그대로다.
9. `[test]` 의 두 키(설계 5.7): `config_problems` 가 Interfaces 의 문구로 형식을 본다(다른 문제와 함께 모은다). `parse_config` 는 `tester_paths` 를 튜플(없으면 None)로, `full_if` 를 튜플(없으면 `()`)로 둔다. 두 키는 `normalized`·`digest` 에 넣지 않는다. `confirm_section` 에만 보인다. `hteam test`·리뷰 관문은 이 태스크에서 두 키를 쓰지 않는다(`full_if` 실행은 Task 6).
10. 템플릿(설계 4.1 "템플릿에는 주석 예시만 둔다"): 주석 블록은 Step 1 의 원문 그대로다. 예시 env 이름은 프로젝트 이름이 없는 `APP_DB_PORT`·`APP_E2E_PORT_BASE` 다(설계의 `KCP_…` 는 요청 프로젝트의 이름이라 일반 이름으로 바꿨다). 템플릿의 고정 에이전트(production 의 developer, test 의 tester)는 그대로라, worktree 예시를 그대로 풀면 Rules 3 의 검사가 막는다. 주석이 그 직무를 crew·승인 직무에서 빼라고 적는다(init 이 제안한다, 설계 9.1 의 4a).
11. 테스트 실행 설정(설계 4.2 "설정을 읽지 않는 명령(… 5단계의 `test` …)은 설정이 깨져도 동작한다", 5.7 의 7단계 작업 공간 줄과 key_env 줄, Codex 계획 리뷰 r1): `hteam test` 는 7단계에도 `config.load` 를 부르지 않는다. 그래도 작업 공간 태스크의 테스트는 슬롯 env 가, 마무리 full 은 슬롯이, 테스트 환경은 key_env 빼기가 필요하므로 그 값만 `test_settings(p)` 로 검사 없이 읽는다. 이 태스크는 함수만 만들고, 쓰는 곳은 Task 4(`record_task` 의 슬롯 env)·Task 5(`run_final` 의 슬롯)·Task 6(`execute` 의 key_env 빼기)이다. 관제·준비·놓기 자식처럼 `config.load` 로 이미 설정을 가진 곳은 그 `Config` 를 그대로 넘긴다. `[workspace]` 표가 깨졌으면 shared 로 본다(그때는 관제도 설정을 읽지 못해 멈춰 있다. 계획 끝 한계). key_env 는 `[redmine]` 의 다른 키가 틀려도 이름만 맞으면 뺀다(키가 테스트 명령으로 가지 않는 쪽을 고른다).

- [ ] **Step 1: 실패하는 테스트 작성**

**Append** `herdr-team/tests/test_config.py`

```python
import tomllib  # noqa: E402  (7단계 덧붙임)

WS_TABLE = """
[workspace]
mode = "worktree"
roles = ["developer"]
slots = 3
setup = "make setup"
teardown = "make down"
setup_timeout_min = 5

[workspace.env]
APP_DB_PORT = "548{slot}9"
APP_NAME = "앱 {slot}"
"""

REDMINE_TABLE = """
[redmine]
url = "https://redmine.example.com/"
key_env = "REDMINE_API_KEY"
env_file = ".env"
status = { start = 2, done = 3, changes = 4, closed = 5 }
"""

NAME_RULE = "이름은 대문자·숫자·_ 이고 HTEAM_·HC_·HORCH_ 로 시작하지 않으며 KEY·SECRET·TOKEN 을 담지 않는다"
VALUE_RULE = "값은 줄바꿈 없는 1 KiB 이하 문자열이다"
ENV_COUNT_RULE = "workspace.env 는 31개 이하다(HTEAM_SLOT 을 더해 horch --env 32개 안이다)"


class WorkspaceConfigTest(TeamCase):
    """[workspace](설계 4.1·4.2·5.10, 7단계). 표가 없으면 shared 기본값이고 0.4.0 과 같다."""

    def load(self, text: str):
        self.init_project(config=text, commit=False)
        return config.load(Project(self.proj))

    def errors(self, text: str) -> list[str]:
        with self.assertRaises(HteamError) as ctx:
            self.load(text)
        self.assertEqual((ctx.exception.code, ctx.exception.exit_code), ("bad_config", 2))
        return ctx.exception.data["errors"]

    def test_no_table_is_shared_default(self):
        cfg = self.load(BASE_CONFIG)
        ws = cfg.workspace
        self.assertEqual(ws, config.Workspace())
        self.assertEqual((ws.mode, ws.roles, ws.slots, ws.setup, ws.teardown, ws.setup_timeout_min, ws.env),
                         ("shared", ("developer", "tester"), 2, None, None, 20, {}))
        self.assertFalse(ws.on)
        self.assertEqual([r for r in cfg.roles if ws.covers(r)], [])
        self.assertIsNone(cfg.redmine)
        with self.assertRaises(Exception):
            ws.mode = "worktree"  # 고정 값이다(frozen)

    def test_worktree_values(self):
        ws = self.load(BASE_CONFIG + WS_TABLE).workspace
        self.assertEqual((ws.mode, ws.roles, ws.slots, ws.setup, ws.teardown, ws.setup_timeout_min),
                         ("worktree", ("developer",), 3, "make setup", "make down", 5))
        self.assertEqual(ws.env, {"APP_DB_PORT": "548{slot}9", "APP_NAME": "앱 {slot}"})  # {slot} 은 그대로 둔다
        self.assertTrue(ws.on)
        self.assertEqual([r for r in ("planner", "developer", "tester") if ws.covers(r)], ["developer"])

    def test_default_roles_are_the_defined_ones(self):
        ws = self.load(BASE_CONFIG + '\n[workspace]\nmode = "worktree"\n').workspace
        self.assertEqual((ws.roles, ws.slots, ws.setup_timeout_min, ws.env), (("developer", "tester"), 2, 20, {}))
        no_tester = BASE_CONFIG.replace('[roles.tester]\ntitle = "테스트"\nowns = ["tests/**", "docs/qa/**"]\n', "")
        ws = self.load(no_tester + '\n[workspace]\nmode = "worktree"\n').workspace
        self.assertEqual(ws.roles, ("developer",))  # 기본 roles 가운데 설정에 있는 직무만
        self.assertFalse(ws.covers("tester"))

    def test_shared_checks_but_does_not_use(self):
        # shared 면 나머지 키는 검사만 한다(설계 4.1). 고정 에이전트·승인 직무 검사는 worktree 에서만 한다
        text = CREW_CONFIG.replace("user_approval_roles = []", 'user_approval_roles = ["developer"]')
        cfg = self.load(text + WS_TABLE.replace('mode = "worktree"', 'mode = "shared"'))
        self.assertFalse(cfg.workspace.on)
        self.assertFalse(cfg.workspace.covers("developer"))
        self.assertEqual((cfg.workspace.slots, cfg.workspace.roles), (3, ("developer",)))
        self.assertEqual(self.errors(BASE_CONFIG + "\n[workspace]\nslots = 0\n"), ["workspace.slots 는 1–9 정수다"])

    def test_errors_are_collected(self):
        long_value = "x" * 1025
        text = BASE_CONFIG + f"""
[workspace]
mode = "worktrees"
roles = ["developer", "ghost", "nope"]
slots = 10
setup = " "
teardown = 3
setup_timeout_min = 121
colour = "red"
alpha = 1

[workspace.env]
lower = "1"
HTEAM_X = "1"
HC_X = "1"
HORCH_X = "1"
API_KEY = "1"
MY_SECRET = "1"
GH_TOKEN = "1"
MULTI = "a\\nb"
NUM = 5
LONG = "{long_value}"
OK_PORT = "81{{slot}}0"
"""
        errs = self.errors(text)
        want = ["workspace.mode 는 shared·worktree 다",
                "workspace.roles 에 정의되지 않은 직무가 있다: ghost, nope",
                "workspace.slots 는 1–9 정수다",
                "workspace.setup 은 비지 않은 문자열이다",
                "workspace.teardown 은 비지 않은 문자열이다",
                "workspace.setup_timeout_min 은 1–120 정수다",
                "workspace: 모르는 키 alpha, colour",
                *[f"workspace.env.{n}: {NAME_RULE}" for n in ("lower", "HTEAM_X", "HC_X", "HORCH_X", "API_KEY",
                                                              "MY_SECRET", "GH_TOKEN")],
                *[f"workspace.env.{n}: {VALUE_RULE}" for n in ("MULTI", "NUM", "LONG")]]
        for expected in want:
            self.assertIn(expected, errs)
        self.assertEqual(len([e for e in errs if e.startswith("workspace")]), len(want), errs)
        self.assertFalse([e for e in errs if "OK_PORT" in e], errs)

    def test_value_limit_is_utf8_bytes(self):
        ok = "가" * 341 + "x"  # 1024 바이트
        cfg = self.load(BASE_CONFIG + f'\n[workspace]\n[workspace.env]\nA_PORT = "{ok}"\nEMPTY = ""\n')
        self.assertEqual(len(cfg.workspace.env["A_PORT"].encode("utf-8")), 1024)
        self.assertEqual(cfg.workspace.env["EMPTY"], "")
        self.assertEqual(self.errors(BASE_CONFIG + f'\n[workspace]\n[workspace.env]\nA_PORT = "{"가" * 342}"\n'),
                         [f"workspace.env.A_PORT: {VALUE_RULE}"])

    def test_env_count_leaves_room_for_hteam_slot(self):
        # 워커에는 HTEAM_SLOT 을 더해 horch --env 로 넘긴다(상한 32, orch 설계 14.1). 그래서 [workspace.env] 는 31개까지다
        many = "".join(f'A{i}_PORT = "1"\n' for i in range(31))
        ws = self.load(BASE_CONFIG + '\n[workspace]\nmode = "worktree"\n[workspace.env]\n' + many).workspace
        self.assertEqual(len(ws.env), 31)
        self.assertEqual(self.errors(BASE_CONFIG + '\n[workspace]\nmode = "worktree"\n[workspace.env]\n' + many
                                     + 'A31_PORT = "1"\n'), [ENV_COUNT_RULE])

    def test_nul_in_value_is_refused(self):
        # TOML 의 \u0000 은 문자열로 읽힌다. subprocess 환경과 horch --env 가 받지 않으므로 설정 검사에서 막는다
        self.assertEqual(self.errors(BASE_CONFIG + '\n[workspace]\n[workspace.env]\nA_PORT = "81\\u00000"\n'),
                         [f"workspace.env.A_PORT: {VALUE_RULE}"])

    def test_shapes(self):
        self.assertIn("[workspace] 는 표여야 한다", self.errors("workspace = 1\n" + BASE_CONFIG))
        self.assertIn("[workspace.env] 는 표여야 한다", self.errors(BASE_CONFIG + "\n[workspace]\nenv = 1\n"))
        for roles in ('"developer"', "[]", '["developer", 3]', '[" "]'):
            with self.subTest(roles=roles):
                self.assertEqual(self.errors(BASE_CONFIG + f"\n[workspace]\nroles = {roles}\n"),
                                 ["workspace.roles 는 비지 않은 직무 이름 목록이다"])
        for value in ("true", '"2"', "0", "1.5"):
            with self.subTest(slots=value):
                self.assertEqual(self.errors(BASE_CONFIG + f"\n[workspace]\nslots = {value}\n"),
                                 ["workspace.slots 는 1–9 정수다"])
        ws = self.load(BASE_CONFIG + "\n[workspace]\nslots = 9\nsetup_timeout_min = 120\n").workspace
        self.assertEqual((ws.slots, ws.setup_timeout_min), (9, 120))
        self.assertEqual(self.errors(BASE_CONFIG + "\n[workspace]\nsetup_timeout_min = 0\n"),
                         ["workspace.setup_timeout_min 은 1–120 정수다"])

    def test_worktree_refuses_crew_and_approval_roles(self):
        text = CREW_CONFIG.replace("user_approval_roles = []", 'user_approval_roles = ["developer"]')
        errs = self.errors(text + '\n[workspace]\nmode = "worktree"\n')
        self.assertEqual(sorted(errs), sorted([
            "crew.production: developer 는 작업 공간 직무다(worktree 모드에서는 임시 워커만 맡는다)",
            "crew.test: tester 는 작업 공간 직무다(worktree 모드에서는 임시 워커만 맡는다)",
            "user_approval_roles 의 developer 는 작업 공간 직무다(worktree 모드에서는 승인 직무로 두지 않는다)"]))
        # 작업 공간 직무를 갖지 않은 고정 에이전트는 된다(roles 를 developer 로 좁히고 생산 에이전트에서 뺐다)
        narrowed = CREW_CONFIG.replace('roles = ["planner", "developer"]', 'roles = ["planner"]')
        cfg = self.load(narrowed + '\n[workspace]\nmode = "worktree"\nroles = ["developer"]\n')
        self.assertEqual(list(cfg.crew), ["production", "test"])
        self.assertTrue(cfg.workspace.covers("developer"))
        self.assertFalse(cfg.workspace.covers("tester"))


class RedmineConfigTest(TeamCase):
    """[redmine](설계 4.1·4.2·8.12, 7단계). 표가 없으면 연동이 꺼진다."""

    def load(self, text: str):
        self.init_project(config=text, commit=False)
        return config.load(Project(self.proj))

    def errors(self, text: str) -> list[str]:
        with self.assertRaises(HteamError) as ctx:
            self.load(text)
        self.assertEqual((ctx.exception.code, ctx.exception.exit_code), ("bad_config", 2))
        return ctx.exception.data["errors"]

    @staticmethod
    def table(**over) -> str:
        """[redmine] 표. over 의 값은 TOML 값 글자 그대로이고 None 이면 그 키를 뺀다."""
        values = {"url": '"https://redmine.example.com"', "key_env": '"REDMINE_API_KEY"',
                  "status": "{ start = 2, done = 3, changes = 4, closed = 5 }"}
        values.update(over)
        return "\n[redmine]\n" + "".join(f"{k} = {v}\n" for k, v in values.items() if v is not None)

    def test_values(self):
        rm = self.load(BASE_CONFIG + REDMINE_TABLE).redmine
        self.assertEqual((rm.url, rm.key_env, rm.env_file, rm.status),
                         ("https://redmine.example.com", "REDMINE_API_KEY", ".env",
                          {"start": 2, "done": 3, "changes": 4, "closed": 5}))
        with self.assertRaises(Exception):
            rm.url = "https://other.example"  # 고정 값이다(frozen)
        rm = self.load(BASE_CONFIG + self.table(url='"http://10.0.0.5:3000/redmine/"')).redmine
        self.assertEqual((rm.url, rm.env_file), ("http://10.0.0.5:3000/redmine", None))
        self.assertIsNone(self.load(BASE_CONFIG).redmine)

    def test_errors(self):
        url_rule = "redmine.url 은 http·https URL 이다"
        key_rule = "redmine.key_env 는 환경 변수 이름이다"
        file_rule = "redmine.env_file 은 프로젝트 안 상대 경로다"
        status_rule = "redmine.status 는 start·done·changes·closed 네 양의 정수다"
        cases = [
            ({"url": '"ftp://x.example"'}, url_rule), ({"url": '"redmine.example.com"'}, url_rule),
            ({"url": '"https://"'}, url_rule), ({"url": '"https://a b.example"'}, url_rule), ({"url": "3"}, url_rule),
            ({"url": None}, url_rule),
            ({"key_env": '"1KEY"'}, key_rule), ({"key_env": '"A-B"'}, key_rule), ({"key_env": '""'}, key_rule),
            ({"key_env": None}, key_rule),
            ({"env_file": '"/etc/redmine.env"'}, file_rule), ({"env_file": '"../.env"'}, file_rule),
            ({"env_file": '"a/../../.env"'}, file_rule), ({"env_file": '""'}, file_rule),
            ({"env_file": '"~/.env"'}, file_rule), ({"env_file": "1"}, file_rule),
            ({"status": "{ start = 2, done = 3, changes = 4 }"}, status_rule),
            ({"status": "{ start = 2, done = 3, changes = 4, closed = 0 }"}, status_rule),
            ({"status": "{ start = 2, done = 3, changes = 4, closed = 5, other = 6 }"}, status_rule),
            ({"status": "{ start = 2, done = 3, changes = 4, closed = true }"}, status_rule),
            ({"status": "3"}, status_rule), ({"status": None}, status_rule),
            ({"project": '"kcp"'}, "redmine: 모르는 키 project"),
        ]
        for over, want in cases:
            with self.subTest(over=over):
                self.assertEqual(self.errors(BASE_CONFIG + self.table(**over)), [want])
        self.assertEqual(self.errors("redmine = 1\n" + BASE_CONFIG), ["[redmine] 는 표여야 한다"])
        self.assertEqual(self.load(BASE_CONFIG + self.table(env_file='"config/redmine.env"')).redmine.env_file,
                         "config/redmine.env")


class TestSettingsReadTest(TeamCase):
    """hteam test 가 쓰는 설정(Rules 11, 설계 4.2: hteam test 는 설정이 깨져도 돈다. Codex 계획 리뷰 r1): config.toml 을
    검사 없이 읽고 예외를 내지 않는다. 슬롯 env 를 정하는 [workspace] 와 뺄 key_env 이름만 본다."""

    def read(self, text: str | None):
        """config.toml 을 text 로 쓰고(None 이면 지운다) (test_settings, redmine_key_env)."""
        self.init_project(config=text or BASE_CONFIG, commit=False)
        if text is None:
            (self.team / "config.toml").unlink()
        p = Project(self.proj)
        return config.test_settings(p), config.redmine_key_env(p)

    def test_valid_config_gives_the_same_values(self):
        got, name = self.read(BASE_CONFIG + WS_TABLE + REDMINE_TABLE)
        self.assertEqual(got.workspace, config.load(Project(self.proj)).workspace)
        self.assertEqual((got.redmine, name), (config.RedmineKey("REDMINE_API_KEY"), "REDMINE_API_KEY"))

    def test_errors_elsewhere_do_not_matter(self):
        text = (BASE_CONFIG.replace("max_parallel = 4", "max_parallel = 0") + WS_TABLE
                + REDMINE_TABLE.replace('url = "https://redmine.example.com/"', 'url = "ftp://x"'))
        got, name = self.read(text)
        with self.assertRaises(HteamError):
            config.load(Project(self.proj))  # 전체 검사는 실패한다
        self.assertEqual((got.workspace.mode, got.workspace.slots, got.workspace.env["APP_DB_PORT"]),
                         ("worktree", 3, "548{slot}9"))
        self.assertEqual((got.redmine, name), (config.RedmineKey("REDMINE_API_KEY"), "REDMINE_API_KEY"))

    def test_unreadable_or_broken_tables_fall_back(self):
        cases = {"no_file": None, "toml": "max_parallel = [\n", "no_tables": BASE_CONFIG,
                 "bad_workspace": BASE_CONFIG + '\n[workspace]\nmode = "worktree"\nslots = 10\n',
                 "workspace_not_table": "workspace = 1\n" + BASE_CONFIG,
                 "bad_key_env": BASE_CONFIG + '\n[redmine]\nkey_env = "1KEY"\n',
                 "redmine_not_table": "redmine = 1\n" + BASE_CONFIG}
        for case, text in cases.items():
            with self.subTest(case=case):
                self.assertEqual(self.read(text), (config.TestSettings(), None))


class TemplateSevenExampleTest(unittest.TestCase):
    """템플릿 config.toml 의 [workspace]·[redmine] 주석 예시(설계 4.1 7단계): 주석이라 켜지지 않고, 풀면 검사를 통과한다."""

    def setUp(self):
        self.text = (ROOT / "templates" / "config.toml").read_text(encoding="utf-8")

    def block(self, header: str) -> str:
        """header 줄부터 `# ` 로 시작하는 줄이 끝날 때까지 `# ` 를 뗀 TOML."""
        lines = self.text.splitlines()
        out = []
        for line in lines[lines.index(header):]:
            if not line.startswith("# "):
                break
            out.append(line[2:])
        return "\n".join(out) + "\n"

    def test_comment_only(self):
        raw = tomllib.loads(self.text)
        self.assertNotIn("workspace", raw)
        self.assertNotIn("redmine", raw)
        cfg = config.build(raw)
        self.assertFalse(cfg.workspace.on)
        self.assertIsNone(cfg.redmine)

    def test_uncommented_example_is_valid(self):
        ws, rm = self.block("# [workspace]"), self.block("# [redmine]")
        raw = tomllib.loads(BASE_CONFIG + "\n" + ws + "\n" + rm)
        self.assertEqual(config.validate(raw), [])
        cfg = config.build(raw)
        self.assertEqual((cfg.workspace.mode, cfg.workspace.roles, cfg.workspace.slots),
                         ("worktree", ("developer", "tester"), 3))
        self.assertEqual(cfg.workspace.env, {"APP_DB_PORT": "548{slot}9", "APP_E2E_PORT_BASE": "7{slot}00"})
        self.assertIn('cp "$HTEAM_MAIN_ROOT/.env" .env', cfg.workspace.setup)
        self.assertEqual((cfg.redmine.key_env, cfg.redmine.env_file), ("REDMINE_API_KEY", ".env"))
        self.assertEqual(cfg.redmine.status, {"start": 2, "done": 3, "changes": 4, "closed": 5})
        # 템플릿의 고정 에이전트는 개발·테스트 직무를 갖는다. worktree 예시를 그대로 풀면 주석대로 검사가 막는다
        errs = config.validate(tomllib.loads(self.text + "\n" + ws))
        self.assertIn("crew.production: developer 는 작업 공간 직무다(worktree 모드에서는 임시 워커만 맡는다)", errs)
        self.assertIn("crew.test: tester 는 작업 공간 직무다(worktree 모드에서는 임시 워커만 맡는다)", errs)
        self.assertIn("worktree 면 roles 의 직무를 [crew.*] 와 user_approval_roles 에서 뺀다", self.text)
```

**Append** `herdr-team/tests/test_state_specs.py`

```python
class IssueSpecTest(TeamCase):
    """사양 front matter 의 issue(설계 5.1, 7단계): 숫자 1–9자리, 앞의 # 는 뗀다. 아니면 사양 검사 exit 2."""

    def setUp(self):
        super().setUp()
        self.init_project(commit=False)
        self.p = Project(self.proj)
        self.cfg = config.load(self.p)

    def test_issue_values(self):
        for raw, want in (("5712", "5712"), ("#5712", "5712"), ("123456789", "123456789"), ("0", "0"),
                          ("007", "007")):
            with self.subTest(raw=raw):
                self.write_spec("T-001", front={"issue": raw}, commit=False)
                spec = specs.check(self.p, self.cfg, "T-001")
                self.assertEqual(spec.issue, want)
                self.assertEqual(spec.front["issue"], raw)  # front matter 값은 쓴 그대로 둔다
        self.write_spec("T-002", commit=False)
        spec = specs.check(self.p, self.cfg, "T-002")
        self.assertIsNone(spec.issue)
        self.assertNotIn("issue", spec.front)

    def test_bad_issue_is_a_spec_problem(self):
        for raw in ("", "#", "57-12", "abc", "1234567890", "##5", "5712a", "- 5", "# 5"):
            with self.subTest(raw=raw):
                self.write_spec("T-001", front={"issue": raw}, commit=False)
                with self.assertRaises(HteamError) as ctx:
                    specs.check(self.p, self.cfg, "T-001")
                self.assertEqual((ctx.exception.code, ctx.exception.exit_code), ("bad_spec", 2))
                self.assertEqual(ctx.exception.data["problems"],
                                 [f"issue 는 숫자 1–9자리 이슈 번호다(앞의 # 는 뗀다): {raw!r}"])
                self.assertIsNone(specs.load(self.p, "T-001").issue)

    def test_issue_value_helper(self):
        for value, want in (("#12", "12"), (" 12 ", "12"), (12, "12"), (0, "0"), (123456789, "123456789"),
                            (1234567890, None), (-1, None), (True, None), (1.5, None), (["1"], None), (None, None)):
            with self.subTest(value=value):
                self.assertEqual(specs.issue_value(value), want)
```

**Append** `herdr-team/tests/test_plan.py`

```python
from hteam import specs  # noqa: E402  (7단계 덧붙임)

ISSUE_RULE = "issue 는 숫자 1–9자리 이슈 번호다(문자열이나 정수, 앞의 # 는 뗀다)"


class IssuePlanTest(TeamCase):
    """tasks.toml 의 issue(설계 5.2, 7단계): 형식 검사, plan apply 가 사양 front matter 로 옮긴다, digest 에 든다."""

    def setUp(self):
        super().setUp()
        self.init_project()
        self.setup_run()
        self.cfg = config.load(Project(self.proj))
        self.path = self.proj / "docs/planning/tasks.toml"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def test_issue_format(self):
        ok = [task("a", owns=["src/a/**"], issue="#5712"), task("b", owns=["src/b/**"], issue=88),
              task("c", owns=["src/c/**"], issue="123456789")]
        self.assertEqual(plan.validate(self.cfg, ok)[0], [])
        for bad in ("57-12", "", "#", "1234567890", True, 1234567890, -1, 1.5, ["1"]):
            with self.subTest(bad=bad):
                self.assertEqual(plan.validate(self.cfg, [task("a", issue=bad)])[0], [f"a: {ISSUE_RULE}"])

    def test_apply_copies_issue_to_spec_front(self):
        self.path.write_text(toml([task("a", owns=["src/a/**"], issue="#5712"),
                                   task("b", owns=["src/b/**"], deps=["a"], issue=88),
                                   task("c", owns=["src/c/**"])]), encoding="utf-8")
        code, out = self.hteam("plan", "apply")
        self.assertEqual(code, 0, out)
        first = (self.proj / ".herdr-team/tasks/T-001.md").read_text(encoding="utf-8")
        self.assertIn("plan_key: a\nissue: 5712\n---\n", first)
        second = (self.proj / ".herdr-team/tasks/T-002.md").read_text(encoding="utf-8")
        self.assertIn("depends_on: T-001\nplan_key: b\nissue: 88\n---\n", second)
        self.assertNotIn("issue:", (self.proj / ".herdr-team/tasks/T-003.md").read_text(encoding="utf-8"))
        p = Project(self.proj)
        self.assertEqual([specs.load(p, t).issue for t in ("T-001", "T-002", "T-003")], ["5712", "88", None])

    def test_issue_added_after_apply_is_refused(self):
        self.path.write_text(toml([task("a")]), encoding="utf-8")
        self.assertEqual(self.hteam("plan", "apply")[0], 0)
        self.path.write_text(toml([task("a", issue=5712)]), encoding="utf-8")
        code, out = self.hteam("plan", "apply", "--append")
        self.assertEqual((code, out["error"]["code"]), (2, "plan_changed"), out)
        code, out = self.hteam("plan", "check", as_=None)
        self.assertEqual((code, out["error"]["code"]), (2, "plan_changed"), out)


# tester 직무가 e2e/** 도 갖는 설정과 tester_paths 두 경로(설계 5.2·5.7, 7단계)
TESTER_PATHS_CONFIG = GROUP_CONFIG.replace('owns = ["tests/**", "docs/qa/**"]',
                                           'owns = ["tests/**", "e2e/**", "docs/qa/**"]')
PATHS_TABLE = TEST_TABLE + 'tester_paths = ["tests/{key}/**", "e2e/{key}/**"]\n'


class TesterPathsTest(TeamCase):
    """묶음 규칙 1 의 tester_paths(설계 5.2 의 7단계 문장): tester owns 는 tester_paths 를 key 로 채운 것과
    docs/qa/{key}.md 다. 없으면 지금 규칙 그대로다."""

    def setUp(self):
        super().setUp()
        self.init_project(config=TESTER_PATHS_CONFIG)
        self.setup_run()
        self.path = self.proj / "docs/planning/tasks.toml"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def tasks(tester_owns):
        return [task("store", owns=["src/store/**"]), task("grp", "tester", tester_owns, deps=["store"])]

    def check(self, tasks, table=PATHS_TABLE):
        self.path.write_text(toml(tasks) + "\n" + table, encoding="utf-8")
        return self.hteam("plan", "check", as_=None)

    def test_paths_fill_the_key(self):
        code, out = self.check(self.tasks(["docs/qa/grp.md", "e2e/grp/**", "tests/grp/**"]))  # 순서 무관
        self.assertEqual((code, out["test"]), (0, True), out)
        code, out = self.check(self.tasks(["tests/grp/**", "docs/qa/grp.md"]))
        self.assertEqual((code, out["error"]["code"]), (2, "plan_invalid"), out)
        self.assertIn('grp: tester 태스크 owns 는 정확히 ["tests/grp/**", "e2e/grp/**", "docs/qa/grp.md"] 다',
                      out["errors"])

    def test_without_tester_paths_the_rule_is_unchanged(self):
        code, out = self.check(self.tasks(["tests/grp/**", "docs/qa/grp.md"]), table=TEST_TABLE)
        self.assertEqual(code, 0, out)
        code, out = self.check(self.tasks(["tests/grp/**", "e2e/grp/**", "docs/qa/grp.md"]), table=TEST_TABLE)
        self.assertEqual((code, out["error"]["code"]), (2, "plan_invalid"), out)
        self.assertIn('grp: tester 태스크 owns 는 정확히 ["tests/grp/**", "docs/qa/grp.md"] 다', out["errors"])

    def test_format_errors_come_with_field_errors(self):
        table = TEST_TABLE + 'tester_paths = ["tests/**"]\nfull_if = "db/**"\n'
        code, out = self.check(self.tasks(["tests/grp/**", "docs/qa/grp.md"]), table=table)
        self.assertEqual((code, out["error"]["code"]), (2, "plan_invalid"), out)
        self.assertEqual(sorted(out["errors"]), ["[test]: full_if 는 glob 목록이다",
                                                 "[test]: tester_paths 는 {key} 를 한 번씩 담은 경로 목록이다"])

    def test_group_problems_keeps_two_argument_call(self):
        keys = {t["key"]: t for t in self.tasks(["tests/grp/**", "docs/qa/grp.md"])}
        self.assertEqual(plan.group_problems(keys, set(keys)), [])
        self.assertEqual(plan.group_problems(keys, set(keys), ["tests/{key}/**", "e2e/{key}/**"]),
                         ['grp: tester 태스크 owns 는 정확히 ["tests/grp/**", "e2e/grp/**", "docs/qa/grp.md"] 다'])
```

**Append** `herdr-team/tests/test_testgate.py`

```python
class SevenKeysTest(unittest.TestCase):
    """[test] 의 tester_paths·full_if(설계 5.7, 7단계): 형식, 기본값, 식별값에 들지 않음, 확정 질문 절."""

    BASE = {"quick": "a {files}", "full": "b"}
    PATHS_RULE = "[test]: tester_paths 는 {key} 를 한 번씩 담은 경로 목록이다"
    GLOB_RULE = "[test]: full_if 는 glob 목록이다"

    def test_parse_and_defaults(self):
        cfg = testgate.parse_config(dict(self.BASE))
        self.assertEqual((cfg.tester_paths, cfg.full_if), (None, ()))
        cfg = testgate.parse_config({**self.BASE, "tester_paths": ["tests/{key}/**", "e2e/{key}/**"],
                                     "full_if": ["db/migrations/**", "package.json"]})
        self.assertEqual((cfg.tester_paths, cfg.full_if),
                         (("tests/{key}/**", "e2e/{key}/**"), ("db/migrations/**", "package.json")))
        self.assertEqual(testgate.parse_config({**self.BASE, "full_if": []}).full_if, ())
        # 다섯 인자로 만드는 GateConfig 는 그대로 된다(새 필드는 뒤에 기본값으로 붙는다)
        old = testgate.GateConfig("a {files}", "b", 30, (0,), False)
        self.assertEqual((old.tester_paths, old.full_if), (None, ()))

    def test_problems(self):
        for bad in ("tests/{key}/**", [], ["tests/**"], ["tests/{key}/{key}/**"], ["tests/{key}/**", 3], [" "]):
            with self.subTest(tester_paths=bad):
                self.assertEqual(testgate.config_problems({**self.BASE, "tester_paths": bad}), [self.PATHS_RULE])
        self.assertEqual(testgate.config_problems({**self.BASE, "tester_paths": ["tests/{key}/[a]/**", "/e2e/{key}/**"]}),
                         ["[test]: tester_paths 'tests/{key}/[a]/**': [] 를 쓸 수 없다",
                          "[test]: tester_paths '/e2e/{key}/**': / 로 시작하거나 끝날 수 없다"])
        for bad in ("db/**", ["db/**", 3], [""], [" "]):
            with self.subTest(full_if=bad):
                self.assertEqual(testgate.config_problems({**self.BASE, "full_if": bad}), [self.GLOB_RULE])
        self.assertEqual(testgate.config_problems({**self.BASE, "full_if": ["db/[x]", "src//a"]}),
                         ["[test]: full_if 'db/[x]': [] 를 쓸 수 없다",
                          "[test]: full_if 'src//a': 빈 마디나 . · .. 마디를 쓸 수 없다"])
        good = {**self.BASE, "tester_paths": ["tests/{key}/**", "e2e/x{key}/**"],
                "full_if": ["db/migrations/**", "package.json", "**/*.sql"]}
        self.assertEqual(testgate.config_problems(good), [])
        # 다른 문제와 함께 모으고 새 키 문제는 뒤에 온다
        self.assertEqual(testgate.config_problems({"quick": "a", "full": "b", "tester_paths": "x", "full_if": 1}),
                         ["[test]: quick 은 {files} 를 정확히 한 번 담는다", self.PATHS_RULE, self.GLOB_RULE])

    def test_digest_ignores_new_keys(self):
        plain = testgate.parse_config(dict(self.BASE))
        more = testgate.parse_config({**self.BASE, "tester_paths": ["tests/{key}/**"], "full_if": ["db/**"]})
        self.assertEqual(testgate.digest(more), testgate.digest(plain))
        self.assertEqual(testgate.normalized(more), testgate.normalized(plain))

    def test_confirm_section_shows_new_keys_when_present(self):
        cfg = testgate.parse_config({**self.BASE, "tester_paths": ["tests/{key}/**", "e2e/{key}/**"],
                                     "full_if": ["db/**"]})
        self.assertEqual(testgate.confirm_section(cfg),
                         "## 테스트 명령\n" + testgate.CONFIRM_LINE + "\n```toml\nquick = \"a {files}\"\nfull = \"b\"\n"
                         "timeout_min = 30\nok_exit = [0]\nexclusive = false\n"
                         "tester_paths = [\"tests/{key}/**\", \"e2e/{key}/**\"]\nfull_if = [\"db/**\"]\n```")
        only = testgate.parse_config({**self.BASE, "full_if": ["db/**"]})
        self.assertTrue(testgate.confirm_section(only).endswith("exclusive = false\nfull_if = [\"db/**\"]\n```"))
        self.assertTrue(testgate.confirm_section(testgate.parse_config(dict(self.BASE))).endswith(
            "exclusive = false\n```"))


class SevenKeysApprovalTest(GateCase):
    """tester_paths·full_if 를 더해도 사용자 확정은 그대로 맞는다(설계 5.7 "이미 한 확정이 그대로 맞는다")."""

    def test_adding_new_keys_keeps_the_confirmation(self):
        self.use_gate()
        self.commit("docs/planning/tasks.toml", '[test]\nquick = "fake-test {files}"\nfull = "fake-test --all"\n'
                    'tester_paths = ["tests/{key}/**"]\nfull_if = ["db/**"]\n', "plan: [test] 7단계 키")
        with mock.patch.dict(os.environ, self.env, clear=True):
            gate = testgate.gate_state(self.p)
            cfg = testgate.load_config(self.p)
        self.assertEqual(gate["state"], "approved", gate)
        self.assertEqual((cfg.tester_paths, cfg.full_if), (("tests/{key}/**",), ("db/**",)))
```

**Edit** `herdr-team/templates/config.toml`

```toml
[overflow]
enabled = true

[defaults]
```

```toml
[overflow]
enabled = true

# 7단계 선택 기능. 주석을 풀면 켜진다(없으면 꺼져 지금과 같다). init 이 묻고 승인한 것만 쓴다(설계 9.1).
# 작업 공간(설계 5.10): 개발 단계 직무(roles) 태스크를 슬롯 worktree(.herdr-team/state/slots/slot-<N>)의 태스크 브랜치에서
# 돌리고 accept 때 관제가 기준 브랜치에 병합한다. worktree 면 roles 의 직무를 [crew.*] 와 user_approval_roles 에서 뺀다
# (임시 워커만 맡는다). setup·teardown 은 슬롯 작업 루트에서 /bin/sh 로 돈다(환경에 [workspace.env] 값과 HTEAM_SLOT,
# HTEAM_MAIN_ROOT, HTEAM_SLOT_ROOT). 시험 도구·린트 설정에서 .herdr-team/ 를 뺀다(슬롯 사본이 섞이지 않게).
# [workspace]
# mode = "worktree"                 # 없으면 "shared"(지금과 같다)
# roles = ["developer", "tester"]
# slots = 3                         # 동시에 쓰는 슬롯 수(1–9, 기본 2)
# setup = "pnpm install --frozen-lockfile && cp \"$HTEAM_MAIN_ROOT/.env\" .env && pnpm db:up"
# teardown = "pnpm db:down"
# setup_timeout_min = 20
# [workspace.env]                   # 값의 {slot} 은 슬롯 번호(메인 폴더 0). 이름에 KEY·SECRET·TOKEN 을 쓰지 않는다
# APP_DB_PORT = "548{slot}9"
# APP_E2E_PORT_BASE = "7{slot}00"

# Redmine(설계 8.12): 사양의 issue 가 가리키는 이슈의 상태·노트를 관제가 바꾼다(워커·리뷰어는 바꾸지 않는다). API 키 값은
# 이 파일에 쓰지 않는다. env_file 은 git 이 추적하지 않는 파일이어야 한다.
# [redmine]
# url = "https://redmine.example.com"
# key_env = "REDMINE_API_KEY"       # API 키를 담은 환경 변수 이름
# env_file = ".env"                 # 있으면 키를 이 파일(KEY=VALUE 줄)에서 읽는다
# status = { start = 2, done = 3, changes = 4, closed = 5 }   # 진행·작업완료·수정 요청·종료 상태 번호

[defaults]
```

- [ ] **Step 2: 실패 확인**

Run: `cd herdr-team && python3 -m unittest tests.test_config tests.test_state_specs tests.test_plan tests.test_testgate 2>&1 | tail -6`
Expected: `Ran 193 tests` / `FAILED (failures=48, errors=41)`(subTest 마다 센다). 실패는 모두 새 클래스(`WorkspaceConfigTest`·`RedmineConfigTest`·`TestSettingsReadTest`·`TemplateSevenExampleTest`·`IssueSpecTest`·`IssuePlanTest`·`TesterPathsTest` 의 셋·`SevenKeysTest`·`SevenKeysApprovalTest`)다. 대표 메시지: `AssertionError: HteamError not raised`(37건, 검사가 없다. NUL 값 포함), `AttributeError: module 'hteam.config' has no attribute 'test_settings'`(9건), `AttributeError: module 'hteam.specs' has no attribute 'issue_value'`, `AttributeError: 'Config' object has no attribute 'workspace'`, `AttributeError: 'Spec' object has no attribute 'issue'`, `AssertionError: Lists differ: ['[test]: 모르는 키 tester_paths'] != ['[test]: tester_paths 는 {key} 를 한 번씩 담은 경로 목록이다']`, `TypeError: group_problems() takes 2 positional arguments but 3 were given`, `['a: 모르는 필드 issue', …] != []`. `TesterPathsTest.test_without_tester_paths_the_rule_is_unchanged` 는 회귀 시험이라 이 단계에서도 통과한다. HEAD 에 이 태스크의 Step 1 블록만 적용한 트리에서 쟀다(계획 작성 때 스크래치의 시범 구현으로 이 시험들과 `test_interview`·`test_setup` 이 모두 통과하는 것을 확인했다. 시범 코드는 계획에 넣지 않았다).

- [ ] **Step 3: 구현**

Rules 1–10 과 Interfaces 대로 `config.py`·`specs.py`·`plan.py`·`testgate.py` 를 고친다. 템플릿은 Step 1 의 Edit 그대로다. `config.Workspace`·`Redmine` 은 `dataclasses.dataclass(frozen=True)`(dict 기본값은 `field(default_factory=dict)`)다. `Config` 의 두 필드는 맨 뒤에 기본값과 함께 두어 다른 생성 자리가 없게 한다(`build` 만 만든다). `plan.validate` 는 묶음 규칙을 부를 때만 `tester_paths` 를 꺼낸다(형식 검사를 통과한 뒤라 목록이다). `testgate.normalized` 는 고치지 않는다. 이 태스크는 `workspace`·`redmine` 값을 쓰는 동작(슬롯·관문·Redmine)을 넣지 않는다.

- [ ] **Step 4: 통과 확인**

Run: `cd herdr-team && python3 -m unittest tests.test_config tests.test_state_specs tests.test_plan tests.test_testgate tests.test_interview tests.test_setup 2>&1 | tail -3` 그다음 `bash herdr-team/tests/run.sh 2>&1 | tail -3`(저장소 루트에서, 백그라운드로 하나만, 10–15분)
Expected: 둘 다 `OK`(설정이 없을 때의 0.4.0 시험이 그대로 통과한다: 기존 사양·plan·`[test]` 출력과 확정 질문 절이 같다).

- [ ] **Step 5: 정적 확인과 커밋**

```bash
python3 - <<'PY'
import ast, pathlib
for f in ["herdr-team/lib/hteam/config.py", "herdr-team/lib/hteam/specs.py", "herdr-team/lib/hteam/plan.py",
          "herdr-team/lib/hteam/testgate.py", "herdr-team/tests/test_config.py", "herdr-team/tests/test_state_specs.py",
          "herdr-team/tests/test_plan.py", "herdr-team/tests/test_testgate.py"]:
    ast.parse(pathlib.Path(f).read_text(encoding="utf-8"), feature_version=(3, 11))
PY
python3 -c "import tomllib; tomllib.loads(open('herdr-team/templates/config.toml', encoding='utf-8').read())"
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews'
git add -- herdr-team/lib/hteam/config.py herdr-team/lib/hteam/specs.py herdr-team/lib/hteam/plan.py herdr-team/lib/hteam/testgate.py herdr-team/templates/config.toml herdr-team/tests/test_config.py herdr-team/tests/test_state_specs.py herdr-team/tests/test_plan.py herdr-team/tests/test_testgate.py
git commit -m "feat(herdr-team): [workspace]·[redmine] 설정 검사, 사양·tasks.toml 의 issue, [test] 의 tester_paths·full_if 형식" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/lib/hteam/config.py herdr-team/lib/hteam/specs.py herdr-team/lib/hteam/plan.py herdr-team/lib/hteam/testgate.py herdr-team/templates/config.toml herdr-team/tests/test_config.py herdr-team/tests/test_state_specs.py herdr-team/tests/test_plan.py herdr-team/tests/test_testgate.py
```

Expected: ast·TOML 오류 없음, grep 빈 출력. 구현자는 여기서 멈춘다(컨트롤러가 `scripts/codex-review.sh commit <sha>`).

---

### Task 3: 작업 공간 코어 — `workspace.py`(슬롯 상태·잠금·폴더·브랜치·표시 파일·setup/teardown·`slot prepare`), 두 루트의 `find_project`·훅, `testgate.child_env`

설계 5.10.2 와 5.10.3 의 2–4(준비)를 만든다. 슬롯은 `<프로젝트>/.herdr-team/state/slots/slot-<N>` 의 git worktree(저장소 전체)이고, 작업 루트는 그 아래 프로젝트의 하위 경로(`gitio.top_prefix`)다. 상태는 `state/slots.json` 하나에 두고 프로젝트 잠금 안에서 엄격하게 읽고 원자적으로 쓴다. 준비(`hteam slot prepare T`, 관제가 자식으로 띄운다, Task 4)는 Task 4 의 `start` 가 써 둔 예약(`preparing`)을 읽어 폴더(`git worktree add --detach`)·브랜치(`git switch -c herdr/T <base>`)·표시 파일(작업 루트의 `.herdr-team/state/slot.json`)·setup 을 하고 `ready: true` 를 남긴다. 준비 내내 슬롯 잠금 `state/slots/slot-<N>.lock` 을 쥐므로 관제는 그 잠금을 비차단으로 시도해 자식이 살았는지 안다(설계 5.10.3 끝 문단). 새로 잡은 슬롯 폴더가 더러우면 슬롯을 태스크 없는 `dirty` 로 두고 예약을 푼다(Codex 설계 리뷰 r2). setup 은 작업 루트에서 테스트 명령과 같은 실행 규칙(새 세션, 그룹 종료, 시간 상한, 로그)으로 돈다. `paths.find_project` 와 훅은 찾은 폴더의 표시 파일이 맞으면 상태 루트를 메인으로, 작업 루트를 슬롯으로 나눈다. 그래서 슬롯 안의 shim·훅의 역할 판별·`hteam test`·`hteam ask-user` 가 메인의 상태를 쓴다. 훅의 "`.herdr-team/state/` 를 고치지 않는다" 규칙은 자기 작업 루트 아래를 빼고 보고, 자기 작업 루트의 `.herdr-team/state/`(표시 파일)는 막는다(Codex 설계 리뷰 r1).

decide 는 이 태스크가 올리지 않는다. `slot prepare` 의 실패 출력에 `kind`(`slot_dirty`·`branch_exists`·`setup_failed`)를 실어 두면 Task 4 의 관제가 자식 결과로 `workspace_failed` 를 올린다. 예약을 쓰는 쪽(`start`)과 슬롯을 `busy` 로 바꾸는 쪽은 Task 4, 놓기·reset 은 Task 5 다. 이 태스크의 시험은 예약을 Task 4 와 같은 꼴로 `slots.json` 에 직접 쓴다. 헤더 "공유 시험 도구" 의 helpers.py 편집 셋도 이 태스크가 넣는다.

**Files:**
- Create: `herdr-team/lib/hteam/workspace.py`, `herdr-team/tests/test_workspace.py`
- Modify: `herdr-team/lib/hteam/paths.py`(`Project(root, work_root=None)`, 슬롯 경로, `project_at`, `find_project`), `herdr-team/lib/hteam/gitio.py`(worktree·switch·branch·common dir), `herdr-team/lib/hteam/testgate.py`(`child_env`), `herdr-team/lib/hteam/cli.py`(`COMMAND_MODULES` 의 `workspace`), `herdr-team/hooks/hteam_hook.py`(두 루트, 편집 보호), `herdr-team/tests/helpers.py`(공유 시험 도구)
- Test: `herdr-team/tests/test_workspace.py`(새로), `herdr-team/tests/test_hooks.py`(Append)

**Interfaces:**
- Consumes: Task 2 의 `config.Workspace`(`on`, `setup`, `teardown`, `setup_timeout_min`, `env`)와 `Config.workspace`·`config.TestSettings`, `state.project_lock`·`edit`·`require`·`move`·`check_id`·`ID_RE`, `roles.require_drive`, `gitio.run`·`dirty`·`top_prefix`, `testgate.kill_group`·`read_tail`·`DROP_ENV`, `util.write_atomic`·`write_json`·`now`·`die_at`, `paths.find_project`.
- Produces:
  - `paths.Project(root, work_root=None)`: `root` 는 상태 루트(메인 프로젝트, 지금 그대로 `resolve()`), `work_root` 는 작업 루트(`resolve()`, 기본 `root`). 새 경로: `slots_file = state/slots.json`, `slots_dir = state/slots`, `slot_logs = state/slots/logs`, `git_lock = state/git.lock`. 다른 경로(상태·태스크·horch home·sessions 등)는 모두 `root` 기준 그대로다.
  - `paths.project_at(folder) -> Project`: `folder` 는 `.herdr-team/config.toml` 이 있는 폴더. `workspace.marker(folder)` 가 dict 면 `Project(marker["main_root"], work_root=folder)`, 아니면 `Project(folder)`. `find_project(arg)` 는 찾은 폴더(`--root` 든 cwd 에서 위로 찾은 것이든)를 이것으로 바꾼다(오류 문구·code 는 지금 그대로).
  - `workspace.py`:
    - 상수: `MARKER_REL = ".herdr-team/state/slot.json"`, `SLOT_STATES = ("free", "preparing", "busy", "dirty")`, `SLOT_DEFAULT = {"state": "free", "task": None, "branch": None, "base_branch": None, "base": None, "setup_done": None, "since": None}`, `MINUTE_S = 60`(setup·teardown 시간 상한 = `setup_timeout_min × MINUTE_S`초. 시험이 줄인다), `DIRTY_SHOWN = 20`.
    - `branch_of(tid) -> str`: `herdr/<tid>`.
    - `load(p) -> dict`: `state/slots.json`. 없으면 `{"slots": {}}`. JSON 이 아니거나 최상위가 dict 가 아니거나 `slots` 가 dict 가 아니거나 항목이 dict 가 아니면 exit 1 `bad_slots_file`(`state/slots.json 을 읽지 못했다: <이유>`, hint `파일을 직접 고치거나 치운 뒤 다시 한다(덮어쓰지 않았다)`). 덮어쓰지 않는다.
    - `entry(data, n) -> dict`: `{**SLOT_DEFAULT, **data["slots"].get(str(n), {})}`(새 dict).
    - `save(p, data) -> None`: `util.write_json`(임시 파일 + `os.replace`). 호출자가 프로젝트 잠금을 쥔다.
    - `held_by(data, tid) -> int | None`: `task == tid` 인 슬롯 번호(가장 작은 것).
    - `folder(p, n) -> Path`: `p.slots_dir / f"slot-{n}"`. `work_root(p, n) -> Path`: `folder(p, n) / gitio.top_prefix(p.root)`(프로젝트가 저장소 루트면 폴더 그대로).
    - `task_root(p, st) -> Path`: `Path(st["workspace"]["root"])`, `workspace` 가 없으면 `p.root`.
    - `slot_env(cfg, n) -> dict[str, str]`: `[workspace.env]` 값의 `{slot}` 을 `str(n)` 으로 바꾼 것 + `HTEAM_SLOT = str(n)`. 이 모듈의 `cfg` 는 `config.Config` 또는 Task 2 의 `config.TestSettings` 다(`cfg.workspace` 와 `cfg.redmine.key_env` 만 쓴다).
    - `task_env(p, cfg, st) -> dict[str, str]`: `st` 에 `workspace` 가 있으면 `slot_env(cfg, st["workspace"]["slot"])`, 없고 `cfg.workspace.on` 이면 `slot_env(cfg, 0)`(메인 폴더, 설계 5.7 7단계), shared 면 `{}`.
    - `slot_lock(p, n, *, nowait=False)`: 컨텍스트 관리자. `state/slots/slot-<N>.lock` 에 `fcntl.flock(LOCK_EX)`. nowait 면 `LOCK_NB` 이고 못 쥐면 exit 3 `slot_locked`(`slot-<N> 을 다른 hteam 자식(준비·놓기·마무리 full)이 쓰는 중이다`, hint `끝나면 관제가 다시 본다`).
    - `slot_busy(p, n) -> bool`: `slot_lock(p, n, nowait=True)` 를 잠깐 쥐어 본다. 못 쥐면 True.
    - `write_marker(root, main_root, n, tid) -> None`: `<root>/.herdr-team/state/slot.json` = `{"main_root": str(main_root), "slot": n, "task": tid}`(폴더를 만든다, 원자적).
    - `marker(root) -> dict | None`: 표시 파일이 `{"main_root": 절대 경로 str, "slot": 1–9 int(bool 아님), "task": state.ID_RE 에 맞는 str}` 이고, `main_root/.herdr-team/config.toml` 이 파일이고, `gitio.common_dir(main_root) == gitio.common_dir(root)`(둘 다 None 이 아님)이면 `{"main_root", "slot", "task"}`. 없거나 깨졌거나 하나라도 어긋나면 None(설계 5.10.2: 폴더를 옮겼으면 무시한다).
    - `run_hook(p, cfg, n, kind, tid) -> dict`: `kind` 는 `"setup"`·`"teardown"`, 명령은 `cfg.workspace.<kind>`(None 이면 부르지 않는다). 결과 `{"kind", "status": "passed"|"failed"|"timeout"|"unrunnable", "exit": int|None, "seconds": float, "log": <p.root 기준 posix 경로>, "tail": str}`. 로그 `state/slots/logs/slot-<N>-<kind>-<%Y%m%d-%H%M%S>.log`(첫 줄 `$ <명령>`). 환경 `testgate.child_env(cfg, {**slot_env(cfg, n), "HTEAM_MAIN_ROOT": str(p.root), "HTEAM_SLOT_ROOT": str(work_root(p, n))})`.
    - `prepare(p, cfg, tid) -> dict`(Rules 4–9): 성공 `{"task", "slot", "root": <작업 루트 str>, "branch", "base_branch", "base", "setup": <run_hook 결과> | None, "ready": true}`.
    - 오류(data 는 출력 최상위에 합친다):
      - exit 3 `slot_not_reserved`: `<T> 가 준비할 슬롯 예약이 없다(state/slots.json 에 preparing 인 <T> 슬롯이 없다)`, hint `hteam start <T> 가 슬롯을 예약한다`.
      - exit 3 `slot_locked`(위).
      - exit 3 `slot_dirty`: `slot-<N> 폴더에 커밋 안 된 변경이 있어 <T> 를 준비하지 않았다: <앞 다섯 경로, 쉼표>`, hint `사용자가 버려도 된다고 하면 hteam slot reset <N>`, data `{"slot": N, "kind": "slot_dirty", "files": [앞 20개]}`.
      - exit 3 `branch_exists`: `브랜치 herdr/<T> 가 이미 있다. 새 브랜치를 만들지 않았다`, hint `남은 브랜치를 어떻게 할지 사용자에게 묻는다`, data `{"slot": N, "kind": "branch_exists", "branch": "herdr/<T>"}`.
      - exit 1 `setup_failed`: `slot-<N> setup 이 <status>(exit <exit>)로 끝났다. 로그: <log>`, data `{"slot": N, "kind": "setup_failed", "status", "exit", "log", "tail"}`.
      - git 실패는 지금 `git_failed`(exit 1) 그대로.
  - CLI `hteam slot prepare T`(관제만): 관제가 아니면 exit 5 `drive_only`(지금 `roles.require_drive`), `T` 꼴이 아니면 exit 2 `bad_task_id`, `config.load` 뒤 `cfg.workspace.on` 이 아니면 exit 3 `workspace_off`(`작업 공간이 꺼져 있다(config.toml [workspace] mode = "worktree" 가 아니다)`). 파서는 `slot` 아래 하위 명령(`prepare`. Task 5 가 `release`·`reset` 을 더한다).
  - `gitio`(이 태스크가 쓰는 것만): `worktree_add(root, folder, commit)`(`git worktree add --detach <folder> <commit>`), `switch_new(root, branch, start)`(`git switch -c`), `switch(root, branch)`, `switch_detach(root)`(`git switch --detach`), `branch_exists(root, name) -> bool`(`git show-ref --verify --quiet refs/heads/<name>`, exit 1 은 False), `branch_tip(root, name) -> str | None`, `current_branch(root) -> str | None`(`git symbolic-ref -q --short HEAD`, detached 면 None), `delete_branch(root, name, *, force=False)`(`git branch -d|-D`), `common_dir(root) -> str | None`(`git rev-parse --git-common-dir` 을 root 기준으로 푼 실제 경로, 저장소가 아니면 None).
  - `testgate.child_env(cfg=None, extra=None) -> dict[str, str]`: `os.environ` 에서 `DROP_ENV` 를 뺀 것에 extra 를 더한다. `cfg` 는 `config.Config`·`config.TestSettings`(Task 2) 또는 None(`hteam test` 는 `config.load` 를 부르지 않는다, 설계 4.2). 이 태스크에서는 cfg 를 쓰지 않는다(Task 6 이 `cfg.redmine.key_env` 를 뺀다). `execute` 는 지금 `_env()` 자리에서 `child_env(None)` 을 쓴다(동작 그대로).
  - 훅: `main()` 이 `Project(root)` 대신 `project_at(root)` 로 프로젝트를 만든다. `where` 의 상대 경로 기준은 `cwd`, 없으면 `p.work_root`. `_in_state(p, real, rel)` 은 Rules 10.
  - 시험용 죽음·멈춤 지점(`HTEAM_TEST_DIE_AT`·`HTEAM_TEST_PAUSE_AT`): `slot_prepare_locked`(슬롯 잠금을 쥔 직후), `slot_worktree_added`(worktree add 뒤), `slot_branch_made`(브랜치를 만들거나 바꾼 뒤, 표시 파일 전), `slot_setup_done`(`setup_done` 을 쓴 뒤, `ready` 전).
- 잠금: 준비는 슬롯 잠금(내내) → 프로젝트 잠금(`slots.json` 을 다시 읽고 고치는 짧은 구간만) → 태스크 잠금(`launch_failed` 를 쓸 때). 슬롯 잠금을 쥔 채 git·setup 을 하는 동안에는 프로젝트 잠금을 쥐지 않는다. setup·teardown 자식은 잠금 기술자를 물려받지 않는다(`subprocess.Popen` 의 `close_fds` 기본값. 데몬을 띄우는 setup 이 잠금을 쥔 채 남지 않게).

**Rules:**

1. 슬롯 상태(설계 5.10.2): `state/slots.json` 은 `{"slots": {"<N>": 기록}}` 하나다. 없는 번호는 `free`(`entry` 의 기본값). 기록의 `state` 는 `SLOT_STATES` 가운데 하나이고 준비가 끝난 예약에는 `ready: true` 를 더한다(`preparing` 인 채). 읽기는 `load`(엄격), 쓰기는 프로젝트 잠금 안의 `save` 다. 읽지 못하면 아무것도 쓰지 않고 `bad_slots_file`.
2. 경로(5.10.2): 폴더는 `folder(p, n)`, 작업 루트는 `work_root(p, n)`. 프로젝트가 저장소 하위 폴더면 슬롯은 저장소 전체의 worktree 이고 작업 루트는 그 아래 같은 하위 경로다. `.herdr-team/state/` 는 git 제외라 메인 폴더의 `git status` 에 슬롯이 보이지 않는다.
3. 환경(5.7·5.10.3 의 4): `slot_env`·`task_env` 는 Interfaces 그대로. setup·teardown 환경은 테스트 환경 규칙(뺄 변수 `DROP_ENV`, Task 6 이 `[redmine] key_env` 를 더한다)에 슬롯 env, `HTEAM_SLOT`, `HTEAM_MAIN_ROOT`, `HTEAM_SLOT_ROOT` 를 더한 것이다.
4. 준비 시작(5.10.3 끝 문단): `prepare` 는 프로젝트 잠금 안에서 `held_by(load(p), tid)` 로 슬롯 번호를 찾고 놓는다(없으면 `slot_not_reserved`). 그 슬롯의 잠금을 `nowait` 로 쥔다(못 쥐면 `slot_locked`: 다른 준비 자식이 산다). 쥔 뒤(죽음 지점 `slot_prepare_locked`) 프로젝트 잠금 안에서 기록을 다시 읽어 `task == tid` 이고 `state == "preparing"` 인지 본다(아니면 `slot_not_reserved`). 이 확인은 `slots.json` 을 고치는 Rules 5–8 의 쓰기마다 다시 한다(그 사이 drop·reset 이 기록을 바꿨으면 쓰지 않고 `slot_not_reserved`).
5. 폴더(5.10.3 의 2): 폴더가 없으면 `gitio.worktree_add(p.root, folder, 기록의 base)`(죽음 지점 `slot_worktree_added`). 폴더가 있고 지금 브랜치가 `herdr/<T>` 가 아니면(새로 잡은 슬롯) `gitio.dirty(folder, ["."])` 를 본다. 무시되지 않은 변경이 있으면 프로젝트 잠금 안에서 그 기록을 `{**SLOT_DEFAULT, "state": "dirty", "setup_done": <그대로>, "since": now()}` 로 쓰고(태스크 없음. 예약이 풀려 그 태스크는 `pending` 그대로이고 다른 슬롯을 잡을 수 있다, Codex 설계 리뷰 r2) `slot_dirty` 로 끝낸다. 폴더의 파일은 건드리지 않는다. 지금 브랜치가 이미 `herdr/<T>` 면(준비 자식이 브랜치 뒤에 죽었다) 이 확인을 건너뛴다(자기 슬롯의 변경은 리뷰 사전 검사가 다룬다, 6.1 4).
6. 브랜치(5.10.3 의 3): 지금 브랜치가 `herdr/<T>` 면 그대로 둔다. 아니고 그 브랜치가 없으면 `gitio.switch_new(folder, "herdr/<T>", 기록의 base)`. 있으면, 태스크 상태에 `workspace` 가 있을 때(이미 시작한 태스크의 복구·수정 라운드)만 `gitio.switch(folder, "herdr/<T>")` 이고, 없으면 `branch_exists` 다: 프로젝트 잠금 안에서 기록을 `free`(태스크 없음, `setup_done` 그대로)로, 태스크 잠금 안에서 태스크를 `launch_failed`(사건 `slot_branch_exists`, 라운드 없음)로 쓴다. 폴더는 남긴다. 죽음 지점 `slot_branch_made`. 그다음 `write_marker(work_root, p.root, n, tid)`.
7. setup(5.10.3 의 4): `cfg.workspace.setup` 이 있고 기록의 `setup_done != tid` 면 `run_hook(p, cfg, n, "setup", tid)`. `passed` 면 프로젝트 잠금 안에서 `setup_done = tid`(죽음 지점 `slot_setup_done`). 그 밖(`failed`·`timeout`·`unrunnable`)이면 `gitio.switch_detach(folder)` 하고 `branch_tip(folder, "herdr/<T>") == 기록의 base`(아직 커밋이 없다)일 때만 `delete_branch(…, force=True)` 한 뒤(같은 태스크를 다시 시작할 때 남은 빈 브랜치가 `branch_exists` 로 막지 않게), 기록을 `{**SLOT_DEFAULT, "since": now()}`(free, `setup_done` None: 반쯤 된 환경이라 다음 태스크가 다시 돈다)로, 태스크를 `launch_failed`(사건 `slot_setup_failed`, `slot`, 라운드 없음)로 쓰고 `setup_failed` 로 끝낸다. 폴더와 무시된 파일은 남긴다. setup 이 없거나 이미 그 태스크가 했으면 결과의 `setup` 은 None.
8. 끝(5.10.3 끝 문단): 프로젝트 잠금 안에서 기록에 `ready: true` 를 쓰고 성공 결과를 돌려준다. 같은 예약을 다시 준비해도(관제가 자식을 다시 띄움) 결과가 같다: 브랜치가 이미 `herdr/<T>` 이고 `setup_done == tid` 라 git·setup 을 다시 하지 않는다.
9. `run_hook`(5.10.3 의 4, 5.7 의 실행): 로그 폴더를 만들고 `["/bin/sh", "-c", 명령]` 을 `cwd=work_root(p, n)`, `stdin=DEVNULL`, stdout·stderr 를 로그 하나로, `start_new_session=True`, 환경은 Rules 3 으로 띄운다. `setup_timeout_min × MINUTE_S` 초가 지나면 `testgate.kill_group` 하고 `timeout`(exit None), 126·127 은 `unrunnable`, 0 은 `passed`, 그 밖은 `failed`. 중단(`BaseException`)이면 그룹을 끝내고 다시 올린다. `tail` 은 `testgate.read_tail(log)`. 실행하지 못하면(`OSError`) `unrunnable`(exit None, 로그에 이유 한 줄).
10. 훅(9.4, 5.10.2 마지막 두 줄): `find_root` 는 지금 그대로(표준 라이브러리만, 찾은 폴더). `main()` 은 `_load()` 뒤 `project_at(root)` 로 프로젝트를 만든다(슬롯이면 상태 루트 = 메인). 그래서 세션 캐시(`state/sessions`)·역할 판별·관제 생존·outbox 는 메인의 것이다. 편집 보호 `_in_state`: `p.work_root != p.root` 이고 경로가 자기 작업 루트 안이면 그 루트 기준 상대 경로가 `.herdr-team/state` 이거나 그 아래일 때만 막는다(표시 파일). 자기 작업 루트 밖이면 지금 규칙(상태 루트의 `state/` 안이면 막는다. 다른 슬롯은 메인 `state/slots/` 안이라 막힌다). 메인의 제품 편집 금지는 그대로(메인 터미널만, 슬롯과 상관없다). 대소문자·firmlink 철자는 지금 `_below` 로 같은 폴더를 본다.
11. 회귀(헤더 "기본값"): 표시 파일이 없는 폴더는 `Project(folder)` 그대로(`work_root == root`), 훅 판정·`testgate` 환경도 그대로다. shared 설정의 `slot prepare` 는 `workspace_off` 이고 `slots.json` 을 만들지 않는다.

핵심 조각(그대로 옮기지 않아도 된다) — 준비의 잠금과 다시 시작(Rules 4–8):

```python
def prepare(p, cfg, tid: str) -> dict:
    with state.project_lock(p):
        n = held_by(load(p), tid)
    if n is None:
        raise _not_reserved(tid)
    with slot_lock(p, n, nowait=True):      # 못 쥐면 slot_locked: 준비 자식이 살아 있다(관제는 기다린다)
        die_at("slot_prepare_locked")
        rec = _mine(p, n, tid)              # 프로젝트 잠금 안에서 다시 읽기: task == tid, state == preparing
        top, root, branch = folder(p, n), work_root(p, n), branch_of(tid)
        ours = top.is_dir() and gitio.current_branch(top) == branch     # 앞 자식이 브랜치까지 했다
        if not top.exists():
            gitio.worktree_add(p.root, top, rec["base"])
            die_at("slot_worktree_added")
        elif not ours and (files := gitio.dirty(top, ["."])):
            _set_aside(p, n, tid, files)    # dirty·태스크 없음(예약을 푼다) → slot_dirty
        if not ours:
            if not gitio.branch_exists(top, branch):
                gitio.switch_new(top, branch, rec["base"])
            elif state.require(p, tid).get("workspace"):
                gitio.switch(top, branch)   # 이미 시작한 태스크(복구·수정 라운드)
            else:
                _refuse_branch(p, n, tid)   # free + launch_failed → branch_exists
            die_at("slot_branch_made")
        write_marker(root, p.root, n, tid)
        result = None
        if cfg.workspace.setup and rec["setup_done"] != tid:
            result = run_hook(p, cfg, n, "setup", tid)
            if result["status"] != "passed":
                _setup_failed(p, n, tid, rec, result)   # detach, 빈 브랜치 지움, free, launch_failed → setup_failed
            _update(p, n, tid, setup_done=tid)
            die_at("slot_setup_done")
        _update(p, n, tid, ready=True)
    return {"task": tid, "slot": n, "root": str(root), "branch": branch, "base_branch": rec["base_branch"],
            "base": rec["base"], "setup": result, "ready": True}
```

핵심 조각 — 훅의 두 루트 편집 보호(Rules 10):

```python
def _in_state(p, real: Path, rel: str | None) -> bool:
    if p.work_root != p.root:               # 슬롯 세션(표시 파일)
        own = _below(real, p.work_root)
        if own is not None:                 # 자기 작업 루트 안: 그 루트의 .herdr-team/state/(표시 파일)만 막는다
            folded = own.casefold()
            return folded == STATE_DIR or folded.startswith(STATE_DIR + "/")
    folded = (rel or "").casefold()         # 그 밖: 상태 루트의 state/(다른 슬롯 포함)
    return folded == STATE_DIR or folded.startswith(STATE_DIR + "/") or _below(real, p.state) is not None
```

- [ ] **Step 1: 실패하는 테스트 작성**

공유 시험 도구(헤더). 뒤 태스크의 시험도 이것을 쓴다.

**Edit** `herdr-team/tests/helpers.py`

```python
VALID_BODY = """## Target
```

```python
# 작업 공간(7단계, 설계 5.10): 개발·테스트 직무(기본 roles)를 슬롯 둘의 worktree 에서 돌린다. 슬롯 env 는 HT_PORT 하나
WS_CONFIG = BASE_CONFIG + """
[workspace]
mode = "worktree"
slots = 2

[workspace.env]
HT_PORT = "81{slot}0"
"""

VALID_BODY = """## Target
```

**Edit** `herdr-team/tests/helpers.py`

```python
    def act(self, did: str, action: dict) -> tuple[int, dict]:
        """Dispatch did 의 워커 터미널에서 가짜 에이전트 동작을 한다(tests/fakes/agent-act)."""
        row = self.dispatch_row(did)
        preamble = self.horch_home / "runs" / row["run_id"] / "dispatches" / did / "preamble.md"
        env = dict(self.env)
        env["HC_TERMINAL_ID"] = row["terminal"]
        proc = subprocess.run([sys.executable, str(FAKES / "agent-act"), "--root", str(self.proj),
```

```python
    def act(self, did: str, action: dict) -> tuple[int, dict]:
        """Dispatch did 의 워커 터미널에서 가짜 에이전트 동작을 한다(tests/fakes/agent-act). 파일·git 은 그 Dispatch 의
        cwd 에서 한다(작업 공간 태스크면 슬롯의 작업 루트, 7단계). cwd 가 프로젝트 밖이면 프로젝트 루트다."""
        row = self.dispatch_row(did)
        preamble = self.horch_home / "runs" / row["run_id"] / "dispatches" / did / "preamble.md"
        env = dict(self.env)
        env["HC_TERMINAL_ID"] = row["terminal"]
        cwd = Path(row["cwd"]).resolve() if row.get("cwd") else None
        root = cwd if cwd is not None and cwd.is_relative_to(self.proj) else self.proj
        proc = subprocess.run([sys.executable, str(FAKES / "agent-act"), "--root", str(root),
```

**Edit** `herdr-team/tests/helpers.py`

```python
def _parse(stdout: str, stderr: str) -> dict:
```

```python
    # --- 작업 공간(7단계, 설계 5.10) ---
    def slot_root(self, n: int) -> Path:
        """슬롯 n 의 작업 루트. 시험 프로젝트는 저장소 루트라 슬롯 폴더 그대로다(설계 5.10.2)."""
        return self.state_dir / "slots" / f"slot-{n}"

    def slots(self) -> dict:
        """state/slots.json. 없으면 {"slots": {}}(모든 슬롯이 free)."""
        path = self.state_dir / "slots.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"slots": {}}

    def git_at(self, root, *args: str) -> str:
        """다른 작업 트리(슬롯)에서 git 을 부른다. 실패하면 시험 실패."""
        proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, env=self.env)
        if proc.returncode != 0:
            raise AssertionError(f"git -C {root} {args} 실패: {proc.stderr}")
        return proc.stdout


def _parse(stdout: str, stderr: str) -> dict:
```

**Create** `herdr-team/tests/test_workspace.py`

```python
"""작업 공간 코어(7단계, 설계 5.10.2–5.10.3): slots.json·슬롯 잠금·경로·env, `hteam slot prepare`(worktree·브랜치·표시 파일·
setup), setup·teardown 실행, 표시 파일로 나누는 두 루트(find_project), testgate.child_env.

시험은 실제 git worktree 를 시험이 만든 임시 저장소 안에 만든다. 예약(설계 5.10.3 의 1)은 Task 4 의 start 가 쓰는 꼴로
slots.json 에 직접 쓴다."""
import contextlib
import json
import os
import subprocess
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import BASE_CONFIG, WS_CONFIG, TeamCase
from hteam import config, paths, state, testgate, workspace
from hteam.errors import HteamError
from hteam.paths import Project

# setup 도우미(시험 폴더 밖 $OUT_DIR/setup.sh): 받은 환경을 한 줄로 남기고 무시된 폴더(node_modules)에 표시를 쌓는다.
# $OUT_DIR/fail 이 있으면 실패한다
SETUP_SH = """[ -f "$OUT_DIR/fail" ] && { echo "설치 실패: $HTEAM_SLOT"; exit 7; }
printf '%s|%s|%s|%s|%s|%s|%s\\n' "$HTEAM_SLOT" "$HT_PORT" "$HTEAM_MAIN_ROOT" "$HTEAM_SLOT_ROOT" "$(pwd -P)" \\
  "${HTEAM_ROLE-없음}" "${HC_TERMINAL_ID-없음}" >> "$OUT_DIR/setup.txt"
mkdir -p node_modules && echo "$HTEAM_SLOT" >> node_modules/marker
"""


def ws_config(setup: str | None = 'sh "$OUT_DIR/setup.sh"', extra: str = "") -> str:
    """WS_CONFIG 의 [workspace] 에 setup(TOML 리터럴 문자열)과 extra 줄을 더한다."""
    lines = (f"setup = '{setup}'\n" if setup else "") + extra
    return WS_CONFIG.replace("slots = 2\n", "slots = 2\n" + lines)


def other_repo(tmp: Path, env: dict) -> Path:
    """다른 git 저장소의 herdr-team 프로젝트(표시 파일이 가리키면 common dir 이 달라 무시해야 한다)."""
    other = tmp / "other"
    (other / ".herdr-team").mkdir(parents=True)
    (other / ".herdr-team" / "config.toml").write_text(BASE_CONFIG, encoding="utf-8")
    for args in (("init", "-q", "-b", "main"), ("add", "--", ".herdr-team"), ("commit", "-q", "-m", "init")):
        subprocess.run(["git", "-C", str(other), *args], check=True, capture_output=True, env=env)
    return other


class SlotCase(TeamCase):
    """작업 공간 프로젝트(WS_CONFIG + setup 도우미, node_modules 는 git 제외)와 관제 Run."""

    config_text = None  # None 이면 ws_config()

    def setUp(self):
        super().setUp()
        self.out = self.tmp / "out"
        self.out.mkdir()
        (self.out / "setup.sh").write_text(SETUP_SH, encoding="utf-8")
        self.env["OUT_DIR"] = str(self.out)
        self.init_project(self.config_text or ws_config())
        self.commit(".gitignore", ".herdr-team/state/\nnode_modules/\n", "chore: node_modules 제외")
        self.setup_run()

    def use_config(self, text: str) -> None:
        (self.team / "config.toml").write_text(text, encoding="utf-8")

    def reserve(self, tid: str, n: int = 1, role: str = "developer") -> str:
        """Task 4 의 start 가 쓰는 예약(설계 5.10.3 의 1): pending 태스크와 slots.json 의 preparing 기록. setup_done 은 그
        슬롯의 앞 값 그대로다. 기준 커밋(메인 HEAD)을 돌려준다."""
        state.create(Project(self.proj), tid, role)
        data = self.slots()
        old = data["slots"].get(str(n), {})
        base = self.head()
        data["slots"][str(n)] = {"state": "preparing", "task": tid, "branch": f"herdr/{tid}", "base_branch": "main",
                                 "base": base, "setup_done": old.get("setup_done"), "since": "2026-11-12T00:00:00Z"}
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "slots.json").write_text(json.dumps(data), encoding="utf-8")
        return base

    def prepare(self, tid: str, **kw) -> tuple[int, dict]:
        return self.hteam("slot", "prepare", tid, **kw)

    def setup_lines(self) -> list[str]:
        path = self.out / "setup.txt"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def marker_of(self, root: Path) -> dict | None:
        path = root / ".herdr-team" / "state" / "slot.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def wait_file(self, path: Path, limit: float = 30.0) -> None:
        deadline = time.monotonic() + limit
        while not path.exists():
            if time.monotonic() > deadline:
                self.fail(f"{limit}초 안에 {path} 가 생기지 않았다")
            time.sleep(0.05)


class SlotStateTest(TeamCase):
    """slots.json·경로·env·잠금(설계 5.10.2·5.10.3·5.7 7단계)."""

    def setUp(self):
        super().setUp()
        self.init_project(WS_CONFIG)
        self.p = Project(self.proj)

    def test_project_paths(self):
        self.assertEqual(self.p.work_root, self.p.root)
        self.assertEqual((self.p.slots_file, self.p.slots_dir, self.p.slot_logs, self.p.git_lock),
                         (self.state_dir / "slots.json", self.state_dir / "slots", self.state_dir / "slots" / "logs",
                          self.state_dir / "git.lock"))
        other = Project(self.proj, work_root=self.state_dir / "slots" / "slot-1")
        self.assertEqual((other.root, other.work_root, other.state),
                         (self.proj, self.state_dir / "slots" / "slot-1", self.state_dir))

    def test_load_entry_save_and_corrupt(self):
        self.assertEqual(workspace.load(self.p), {"slots": {}})
        self.assertEqual(workspace.entry({"slots": {}}, 2), dict(workspace.SLOT_DEFAULT))
        self.assertEqual(workspace.SLOT_DEFAULT, {"state": "free", "task": None, "branch": None, "base_branch": None,
                                                  "base": None, "setup_done": None, "since": None})
        data = {"slots": {"2": {"state": "busy", "task": "T-003", "branch": "herdr/T-003", "base_branch": "main",
                                "base": "abc", "setup_done": "T-003", "since": "2026-11-12T00:00:00Z"}}}
        with state.project_lock(self.p):
            workspace.save(self.p, data)
        self.assertEqual(workspace.load(self.p), data)
        self.assertEqual(workspace.entry(workspace.load(self.p), 2)["task"], "T-003")
        self.assertEqual((workspace.held_by(data, "T-003"), workspace.held_by(data, "T-004")), (2, None))
        for bad in ("{깨짐", "[]", '{"slots": []}', '{"slots": {"1": "busy"}}'):
            with self.subTest(bad=bad):
                self.p.slots_file.write_text(bad, encoding="utf-8")
                with self.assertRaises(HteamError) as cm:
                    workspace.load(self.p)
                self.assertEqual((cm.exception.code, cm.exception.exit_code), ("bad_slots_file", 1))
                self.assertEqual(self.p.slots_file.read_text(encoding="utf-8"), bad)  # 덮어쓰지 않는다

    def test_env_roots_and_branch(self):
        cfg = config.load(self.p)
        self.assertEqual(workspace.slot_env(cfg, 1), {"HT_PORT": "8110", "HTEAM_SLOT": "1"})
        slot_task = {"id": "T-001", "workspace": {"slot": 2, "branch": "herdr/T-001", "base_branch": "main",
                                                  "root": "/x/slot-2", "merge": None}}
        self.assertEqual(workspace.task_env(self.p, cfg, slot_task), {"HT_PORT": "8120", "HTEAM_SLOT": "2"})
        # worktree 모드에서 메인 폴더에서 도는 태스크는 슬롯 0 값이다(설계 5.7 7단계)
        self.assertEqual(workspace.task_env(self.p, cfg, {"id": "T-002"}), {"HT_PORT": "8100", "HTEAM_SLOT": "0"})
        self.assertEqual(workspace.task_root(self.p, slot_task), Path("/x/slot-2"))
        self.assertEqual(workspace.task_root(self.p, {"id": "T-002"}), self.p.root)
        self.assertEqual(workspace.folder(self.p, 3), self.state_dir / "slots" / "slot-3")
        self.assertEqual(workspace.work_root(self.p, 3), self.state_dir / "slots" / "slot-3")
        self.assertEqual(workspace.branch_of("T-012"), "herdr/T-012")

    def test_slot_lock_nowait_and_busy(self):
        self.assertFalse(workspace.slot_busy(self.p, 1))
        with workspace.slot_lock(self.p, 1):
            self.assertTrue(workspace.slot_busy(self.p, 1))
            self.assertFalse(workspace.slot_busy(self.p, 2))  # 슬롯마다 따로다
            with self.assertRaises(HteamError) as cm:
                with workspace.slot_lock(self.p, 1, nowait=True):
                    pass
            self.assertEqual((cm.exception.code, cm.exception.exit_code), ("slot_locked", 3))
        self.assertFalse(workspace.slot_busy(self.p, 1))
        self.assertTrue((self.state_dir / "slots" / "slot-1.lock").exists())


class PrepareTest(SlotCase):
    """`hteam slot prepare T`(설계 5.10.3 의 2–4)."""

    def test_prepare_makes_worktree_branch_marker_and_runs_setup(self):
        base = self.reserve("T-001")
        code, out = self.prepare("T-001")
        self.assertEqual(code, 0, out)
        slot = self.slot_root(1)
        self.assertEqual((out["task"], out["slot"], out["root"], out["branch"], out["base_branch"], out["base"],
                          out["ready"]), ("T-001", 1, str(slot), "herdr/T-001", "main", base, True))
        self.assertEqual((out["setup"]["kind"], out["setup"]["status"], out["setup"]["exit"]), ("setup", "passed", 0))
        self.assertEqual(self.git_at(slot, "symbolic-ref", "--short", "HEAD").strip(), "herdr/T-001")
        self.assertEqual(self.git_at(slot, "rev-parse", "HEAD").strip(), base)
        self.assertEqual(self.marker_of(slot), {"main_root": str(self.proj), "slot": 1, "task": "T-001"})
        rec = self.slots()["slots"]["1"]
        self.assertEqual((rec["state"], rec["task"], rec["setup_done"], rec.get("ready")),
                         ("preparing", "T-001", "T-001", True))
        # setup 은 작업 루트에서, 슬롯 env·HTEAM_* 를 받고, 관제·워커 표시 변수 없이 돈다
        self.assertEqual(self.setup_lines(), ["|".join(["1", "8110", str(self.proj), str(slot), str(slot), "없음", "없음"])])
        logs = sorted((self.state_dir / "slots" / "logs").glob("slot-1-setup-*.log"))
        self.assertEqual(len(logs), 1)
        self.assertEqual(out["setup"]["log"], logs[0].relative_to(self.proj).as_posix())
        self.assertTrue(logs[0].read_text(encoding="utf-8").startswith('$ sh "$OUT_DIR/setup.sh"\n'))
        self.assertEqual(self.git("status", "--porcelain"), "")  # 슬롯 폴더는 git 제외 경로(.herdr-team/state/) 안이다
        self.assertIn(f"worktree {slot}\n", self.git("worktree", "list", "--porcelain"))
        self.assertEqual(self.task_state("T-001")["status"], "pending")  # 준비는 태스크를 띄우지 않는다(Task 4 의 start)

    def test_rerun_skips_and_reuse_keeps_folder(self):
        self.reserve("T-001")
        self.assertEqual(self.prepare("T-001")[0], 0)
        slot = self.slot_root(1)
        code, out = self.prepare("T-001")  # 같은 예약을 다시 준비(관제가 준비 자식을 다시 띄웠다): git·setup 을 다시 하지 않는다
        self.assertEqual(code, 0, out)
        self.assertIsNone(out["setup"])
        self.assertEqual(len(self.setup_lines()), 1)
        # 놓은 뒤 다른 태스크가 같은 슬롯을 다시 쓴다(놓기는 Task 5. 여기서는 그 결과를 흉내 낸다: detach 와 새 예약)
        self.git_at(slot, "switch", "--detach")
        self.commit("src/new.py", "x = 1\n", "feat: 기준 브랜치가 나아갔다")
        base = self.reserve("T-002")
        code, out = self.prepare("T-002")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["setup"]["status"], "passed")  # setup_done 이 T-001 이라 다시 돈다
        self.assertEqual(len(self.setup_lines()), 2)
        self.assertEqual(self.git_at(slot, "symbolic-ref", "--short", "HEAD").strip(), "herdr/T-002")
        self.assertEqual(self.git_at(slot, "rev-parse", "HEAD").strip(), base)
        self.assertTrue((slot / "src" / "new.py").is_file())
        self.assertEqual((slot / "node_modules" / "marker").read_text(encoding="utf-8"), "1\n1\n")  # 무시된 파일은 남는다
        self.assertEqual(self.slots()["slots"]["1"]["setup_done"], "T-002")
        self.assertEqual(self.marker_of(slot)["task"], "T-002")

    def test_dirty_new_slot_is_set_aside(self):
        self.reserve("T-001")
        self.assertEqual(self.prepare("T-001")[0], 0)
        slot = self.slot_root(1)
        self.git_at(slot, "switch", "--detach")
        (slot / "junk.txt").write_text("남은 파일\n", encoding="utf-8")
        self.reserve("T-002")
        code, out = self.prepare("T-002")
        self.assertEqual(code, 3, out)
        self.assertEqual((out["error"]["code"], out["kind"], out["slot"]), ("slot_dirty", "slot_dirty", 1))
        self.assertIn("junk.txt", out["files"])
        self.assertIn("hteam slot reset 1", out["error"]["hint"])
        rec = self.slots()["slots"]["1"]
        self.assertEqual((rec["state"], rec["task"], rec.get("ready")), ("dirty", None, None))
        self.assertEqual(rec["setup_done"], "T-001")
        self.assertIsNone(workspace.held_by(self.slots(), "T-002"))  # 예약을 풀었다(다른 슬롯을 잡을 수 있다)
        self.assertEqual(self.task_state("T-002")["status"], "pending")
        self.assertTrue((slot / "junk.txt").exists())  # 지우지 않는다(slot reset 은 사용자 확인 뒤, Task 5)

    def test_existing_branch_is_refused(self):
        self.git("branch", "herdr/T-001")
        self.reserve("T-001")
        code, out = self.prepare("T-001")
        self.assertEqual(code, 3, out)
        self.assertEqual((out["error"]["code"], out["kind"], out["slot"], out["branch"]),
                         ("branch_exists", "branch_exists", 1, "herdr/T-001"))
        rec = self.slots()["slots"]["1"]
        self.assertEqual((rec["state"], rec["task"]), ("free", None))
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["rounds"], st["history"][-1]["event"]),
                         ("launch_failed", [], "slot_branch_exists"))
        self.assertEqual(self.git("rev-parse", "herdr/T-001").strip(), self.head())  # 남은 브랜치는 그대로(사용자가 정한다)
        self.assertTrue(self.slot_root(1).is_dir())

    def test_setup_failure_frees_slot_and_marks_launch_failed(self):
        (self.out / "fail").write_text("", encoding="utf-8")
        self.reserve("T-001")
        code, out = self.prepare("T-001")
        self.assertEqual(code, 1, out)
        self.assertEqual((out["error"]["code"], out["kind"], out["slot"], out["status"], out["exit"]),
                         ("setup_failed", "setup_failed", 1, "failed", 7))
        self.assertIn("설치 실패: 1", out["tail"])
        self.assertTrue((self.proj / out["log"]).is_file())
        rec = self.slots()["slots"]["1"]
        self.assertEqual((rec["state"], rec["task"], rec["setup_done"]), ("free", None, None))
        slot = self.slot_root(1)
        self.assertTrue(slot.is_dir())  # 폴더는 남긴다(설계 5.10.3 끝 문단)
        self.assertEqual(self.git_at(slot, "rev-parse", "--abbrev-ref", "HEAD").strip(), "HEAD")  # detached
        self.assertEqual(self.git("branch", "--list", "herdr/*"), "")  # 커밋 없는 빈 브랜치는 지운다
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["rounds"], st["history"][-1]["event"]), ("launch_failed", [], "slot_setup_failed"))
        # 고친 뒤 다시 예약하면(다른 슬롯이어도) 같은 이름의 브랜치로 준비된다
        (self.out / "fail").unlink()
        self.reserve("T-001", 2)
        code, out = self.prepare("T-001")
        self.assertEqual(code, 0, out)
        self.assertEqual((out["slot"], out["branch"]), (2, "herdr/T-001"))

    def test_death_after_branch_resumes(self):
        self.reserve("T-001")
        code, _ = self.prepare("T-001", env={"HTEAM_TEST_DIE_AT": "slot_branch_made"})
        self.assertEqual(code, 137)
        slot = self.slot_root(1)
        rec = self.slots()["slots"]["1"]
        self.assertEqual((rec["state"], rec["task"], rec.get("ready")), ("preparing", "T-001", None))
        self.assertIsNone(self.marker_of(slot))
        self.assertEqual(self.setup_lines(), [])
        code, out = self.prepare("T-001")  # 관제가 슬롯 잠금이 풀린 것을 보고 다시 띄운 준비 자식
        self.assertEqual(code, 0, out)
        self.assertEqual(self.git_at(slot, "symbolic-ref", "--short", "HEAD").strip(), "herdr/T-001")
        self.assertEqual(self.marker_of(slot)["task"], "T-001")
        self.assertEqual(len(self.setup_lines()), 1)
        self.assertTrue(self.slots()["slots"]["1"]["ready"])

    def test_prepare_holds_the_slot_lock(self):
        self.reserve("T-001")
        gate = self.tmp / "gate"
        proc = self.hteam_bg("slot", "prepare", "T-001",
                             env={"HTEAM_TEST_PAUSE_AT": "slot_prepare_locked", "HTEAM_TEST_PAUSE_FILE": str(gate)})
        self.wait_file(self.tmp / "gate.reached")
        p = Project(self.proj)
        self.assertTrue(workspace.slot_busy(p, 1))  # 관제가 보는 것: 자식이 살아 있다
        code, out = self.prepare("T-001")
        self.assertEqual((code, out["error"]["code"]), (3, "slot_locked"), out)
        gate.touch()
        code, out = self.finish(proc)
        self.assertEqual(code, 0, out)
        self.assertFalse(workspace.slot_busy(p, 1))

    def test_drive_only_and_unreserved(self):
        self.reserve("T-001")
        code, out = self.prepare("T-001", as_="main")
        self.assertEqual((code, out["error"]["code"]), (5, "drive_only"), out)
        code, out = self.prepare("T-009")
        self.assertEqual((code, out["error"]["code"]), (3, "slot_not_reserved"), out)
        code, out = self.prepare("x-1")
        self.assertEqual((code, out["error"]["code"]), (2, "bad_task_id"), out)
        self.assertFalse(self.slot_root(1).exists())  # 아무것도 만들지 않았다


class HookRunTest(SlotCase):
    """setup·teardown 실행(설계 5.10.3 의 4, 5.10.6 놓기의 teardown): 작업 루트, 환경, 로그, 시간 상한."""

    def test_teardown_runs_in_work_root_with_slot_env(self):
        self.reserve("T-001")
        self.assertEqual(self.prepare("T-001")[0], 0)
        self.use_config(ws_config(extra="teardown = 'echo \"$HTEAM_SLOT $HT_PORT ${HTEAM_ROLE-없음} $(pwd -P)\" "
                                         "> \"$OUT_DIR/teardown.txt\"'\n"))
        p = Project(self.proj)
        cfg = config.load(p)
        with mock.patch.dict(os.environ, {"OUT_DIR": str(self.out), "HTEAM_ROLE": "drive", "HC_TERMINAL_ID": "t9"}):
            res = workspace.run_hook(p, cfg, 1, "teardown", "T-001")
        self.assertEqual((res["kind"], res["status"], res["exit"]), ("teardown", "passed", 0))
        self.assertEqual((self.out / "teardown.txt").read_text(encoding="utf-8").strip(),
                         f"1 8110 없음 {self.slot_root(1)}")
        self.assertRegex(res["log"], r"^\.herdr-team/state/slots/logs/slot-1-teardown-\d{8}-\d{6}\.log$")

    def test_timeout_kills_the_group(self):
        self.reserve("T-001")
        self.assertEqual(self.prepare("T-001")[0], 0)
        self.use_config(ws_config("sleep 30", extra="setup_timeout_min = 1\n"))
        p = Project(self.proj)
        cfg = config.load(p)
        started = time.monotonic()
        with mock.patch.object(workspace, "MINUTE_S", 0.2):
            res = workspace.run_hook(p, cfg, 1, "setup", "T-001")
        self.assertEqual((res["status"], res["exit"]), ("timeout", None))
        self.assertLess(time.monotonic() - started, 10)


class SubdirSlotTest(SlotCase):
    """프로젝트가 저장소의 하위 폴더(app/)면 슬롯은 저장소 전체의 worktree 이고 작업 루트는 그 아래 app/ 다(설계 5.10.2)."""

    def setUp(self):
        TeamCase.setUp(self)
        self.repo = self.proj
        self.proj = self.repo / "app"
        self.proj.mkdir()
        self.out = self.tmp / "out"
        self.out.mkdir()
        self.env["OUT_DIR"] = str(self.out)
        self.init_project(ws_config(None))
        self.setup_run()

    def test_work_root_is_the_same_subfolder(self):
        self.reserve("T-001")
        code, out = self.prepare("T-001")
        self.assertEqual(code, 0, out)
        top = self.slot_root(1)
        work = top / "app"
        self.assertEqual(out["root"], str(work))
        self.assertTrue((top / "README.md").is_file())  # 저장소 전체의 worktree
        self.assertTrue((work / ".herdr-team" / "config.toml").is_file())
        self.assertEqual(self.marker_of(work), {"main_root": str(self.proj), "slot": 1, "task": "T-001"})
        self.assertIsNone(self.marker_of(top))
        self.assertEqual(workspace.work_root(Project(self.proj), 1), work)
        p = paths.find_project(str(work))
        self.assertEqual((p.root, p.work_root), (self.proj, work))


class FindProjectTest(TeamCase):
    """표시 파일로 나누는 두 루트(설계 5.10.2): 슬롯에서 찾아도 상태 루트는 메인이다."""

    def setUp(self):
        super().setUp()
        self.init_project(WS_CONFIG)
        self.setup_run()
        self.slot = self.slot_root(1)
        self.git("worktree", "add", "-q", "--detach", str(self.slot), "HEAD")
        self.mark({"main_root": str(self.proj), "slot": 1, "task": "T-001"})

    def mark(self, value) -> None:
        path = self.slot / ".herdr-team" / "state" / "slot.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")

    def test_marker_splits_state_and_work_roots(self):
        self.assertEqual(workspace.marker(self.slot), {"main_root": str(self.proj), "slot": 1, "task": "T-001"})
        for arg in (str(self.slot), None):
            with self.subTest(arg=arg), contextlib.chdir(self.slot / ".herdr-team"):
                p = paths.find_project(arg)
                self.assertEqual((p.root, p.work_root, p.state), (self.proj, self.slot, self.state_dir))
        main = paths.find_project(str(self.proj))
        self.assertEqual((main.root, main.work_root), (self.proj, self.proj))
        self.assertEqual(paths.project_at(self.slot).root, self.proj)

    def test_cli_in_slot_uses_main_state(self):
        # 슬롯 안에서 부른 hteam 이 메인의 run.json 으로 관제를 확인하고 메인의 slots.json 을 본다
        code, out = self.hteam("slot", "prepare", "T-009", cwd=self.slot)
        self.assertEqual((code, out["error"]["code"]), (3, "slot_not_reserved"), out)

    def test_bad_markers_are_ignored(self):
        other = other_repo(self.tmp, self.env)
        cases = ["{깨짐", [],
                 {"main_root": str(other), "slot": 1, "task": "T-001"},       # 다른 저장소(common dir 이 다르다)
                 {"main_root": str(self.tmp / "none"), "slot": 1, "task": "T-001"},
                 {"main_root": "proj", "slot": 1, "task": "T-001"},           # 상대 경로
                 {"main_root": str(self.proj), "slot": "1", "task": "T-001"},
                 {"main_root": str(self.proj), "slot": True, "task": "T-001"},
                 {"main_root": str(self.proj), "slot": 1, "task": "x"}]
        for value in cases:
            with self.subTest(value=value):
                self.mark(value)
                self.assertIsNone(workspace.marker(self.slot))
                p = paths.find_project(str(self.slot))
                self.assertEqual((p.root, p.work_root), (self.slot, self.slot))


class SharedRegressionTest(TeamCase):
    """작업 공간이 꺼진 프로젝트는 0.4.0 그대로다(헤더 "기본값")."""

    def setUp(self):
        super().setUp()
        self.init_project()
        self.setup_run()

    def test_shared_project_paths_env_and_prepare(self):
        p = paths.find_project(str(self.proj))
        self.assertEqual((p.root, p.work_root), (self.proj, self.proj))
        cfg = config.load(p)
        self.assertEqual(workspace.task_env(p, cfg, {"id": "T-001"}), {})
        state.create(p, "T-001", "developer")
        code, out = self.hteam("slot", "prepare", "T-001")
        self.assertEqual((code, out["error"]["code"]), (3, "workspace_off"), out)
        self.assertFalse((self.state_dir / "slots.json").exists())
        env = {"HTEAM_ROLE": "drive", "HTEAM_LAUNCH": "n", "HC_TERMINAL_ID": "t9", "KEEP_ME": "1"}
        with mock.patch.dict(os.environ, env):
            plain = testgate.child_env(None)
            more = testgate.child_env(cfg, {"EXTRA": "x"})
        for name in ("HTEAM_ROLE", "HTEAM_LAUNCH", "HC_TERMINAL_ID"):
            self.assertNotIn(name, plain)
            self.assertNotIn(name, more)
        self.assertEqual((plain["KEEP_ME"], more["KEEP_ME"], more["EXTRA"]), ("1", "1", "x"))
        self.assertNotIn("EXTRA", plain)


if __name__ == "__main__":
    unittest.main()
```

**Append** `herdr-team/tests/test_hooks.py`

```python
class SlotHookTest(HookCase):
    """작업 공간 슬롯(7단계, 설계 5.10.2): 훅은 표시 파일로 상태 루트(메인)와 작업 루트(슬롯)를 나눈다. 슬롯의 제품 파일은
    고칠 수 있고, 자기 슬롯의 표시 파일·다른 슬롯·메인의 state/ 는 막는다."""

    def setUp(self):
        super().setUp()
        self.slot1, self.slot2 = (self.state_dir / "slots" / f"slot-{n}" for n in (1, 2))
        for n, slot in ((1, self.slot1), (2, self.slot2)):
            self.git("worktree", "add", "-q", "--detach", str(slot), "HEAD")
            self.mark(slot, {"main_root": str(self.proj), "slot": n, "task": f"T-00{n}"})

    @staticmethod
    def mark(slot, value) -> None:
        path = slot / ".herdr-team" / "state" / "slot.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def in_slot(self, event, payload, slot, **kw):
        """슬롯에서 뜬 Claude 세션의 훅: CLAUDE_PROJECT_DIR 와 cwd 가 그 작업 루트다."""
        return self.hook(event, {"cwd": str(slot), **payload}, env={"CLAUDE_PROJECT_DIR": str(slot)}, **kw)

    def write(self, path, slot, **kw):
        return self.in_slot("guard", {"tool_name": "Write", "session_id": "w1", "tool_input": {"file_path": str(path)}},
                            slot, **kw)

    def test_slot_session_uses_main_state(self):
        worker = self.worker()
        self.assertIsNone(self.write(self.slot1 / "src" / "a.py", self.slot1, terminal=worker))
        self.assertEqual(self.cached("w1"), "worker")  # 세션 캐시는 메인의 state/sessions 에 있다
        self.assertFalse((self.slot1 / ".herdr-team" / "state" / "sessions").exists())

    def test_slot_worker_edit_rules(self):
        worker = self.worker()
        cases = [(self.slot1 / "src" / "a.py", None),                          # 자기 작업 루트의 제품 파일
                 (self.slot1 / ".herdr-team" / "state" / "slot.json", "deny"),  # 자기 작업 루트의 표시 파일
                 (self.slot2 / "src" / "a.py", "deny"),                         # 다른 슬롯(메인 state/ 안)
                 (self.state_dir / "run.json", "deny"),                         # 메인의 상태
                 (self.proj / "src" / "a.py", None)]                            # 메인 폴더 제품 파일(사양의 규칙이다, 5.10.5)
        for path, want in cases:
            with self.subTest(path=path):
                self.assertEqual(self.decision(self.write(path, self.slot1, terminal=worker)), want)
        # 상대 경로는 훅 입력의 cwd(작업 루트) 기준이다
        rel = {"tool_name": "Write", "session_id": "w1", "tool_input": {"file_path": "src/b.py"}}
        self.assertIsNone(self.in_slot("guard", rel, self.slot1, terminal=worker))
        rel["tool_input"]["file_path"] = ".herdr-team/state/x.json"
        self.assertEqual(self.decision(self.in_slot("guard", rel, self.slot1, terminal=worker)), "deny")

    def test_main_folder_session_still_guards_slots(self):
        # 표시 파일이 없는 메인 폴더 세션에게 슬롯은 state/ 안이다. 메인의 제품 편집 금지는 그대로다(회귀)
        out = self.hook("guard", {"tool_name": "Write", "session_id": "w2",
                                  "tool_input": {"file_path": str(self.slot1 / "src" / "a.py")}}, terminal=self.worker())
        self.assertEqual(self.decision(out), "deny")
        self.assertEqual(self.decision(self.edit("src/app.py", terminal=MAIN)), "deny")

    def test_marker_of_another_repo_is_ignored(self):
        other = self.tmp / "other"
        (other / ".herdr-team").mkdir(parents=True)
        (other / ".herdr-team" / "config.toml").write_text("max_parallel = 1\n", encoding="utf-8")
        for args in (("init", "-q", "-b", "main"), ("add", "--", ".herdr-team"), ("commit", "-q", "-m", "init")):
            subprocess.run(["git", "-C", str(other), *args], check=True, capture_output=True, env=self.env)
        self.mark(self.slot1, {"main_root": str(other), "slot": 1, "task": "T-001"})
        worker = self.worker()
        # 슬롯을 따로 된 프로젝트로 본다: 메인 state/ 는 그 프로젝트 밖이라 이 규칙으로 막지 않고, 슬롯 자신의 state/ 는 막는다
        self.assertIsNone(self.write(self.state_dir / "run.json", self.slot1, terminal=worker))
        self.assertEqual(self.decision(self.write(self.slot1 / ".herdr-team" / "state" / "x", self.slot1, terminal=worker)),
                         "deny")
```

- [ ] **Step 2: 실패 확인**

Run: `cd herdr-team && python3 -m unittest tests.test_workspace tests.test_hooks 2>&1 | tail -6`
Expected: `Ran 61 tests` / `FAILED (failures=3, errors=1)`. 대표 메시지: `ImportError: cannot import name 'workspace' from 'hteam'`(test_workspace 모듈 전체가 오류 하나), `AssertionError: None != 'deny'`(슬롯 세션이 다른 슬롯·메인 state/ 를 고칠 수 있다, subTest 둘: `slot-2/src/a.py`, `state/run.json`), `AssertionError: None != 'worker'`(세션 캐시가 슬롯의 state/ 에 생긴다). `SlotHookTest` 의 나머지 둘(메인 폴더 세션, 다른 저장소 표시 파일)과 test_hooks 의 기존 시험 56개는 이 단계에서도 통과한다(회귀). HEAD 에 이 태스크의 Step 1 블록(공유 시험 도구 포함)만 적용한 트리에서 쟀다(Task 1·2 구현 없음). 계획 작성 때 스크래치의 시범 구현(Task 2 의 `Config.workspace` 최소 모양 포함, 계획에 넣지 않았다)으로 test_workspace 19개와 test_hooks 60개가 통과하고 test_testgate·test_base·test_start·test_lifecycle·test_review·test_crew 가 그대로 통과하는 것을 확인했다.

- [ ] **Step 3: 구현**

Rules 1–11 과 Interfaces 대로 `workspace.py` 를 새로 쓰고 `paths.py`·`gitio.py`·`testgate.py`·`cli.py`·`hooks/hteam_hook.py` 를 고친다. git 은 `gitio.py` 에서만 부른다(`workspace.py` 는 `gitio` 함수만 쓴다). `workspace.py` 는 `paths` 를 가져오지 않는다(`paths.project_at` 이 `workspace.marker` 를 함수 안에서 늦게 가져온다: 모든 모듈이 `paths` 를 가져오므로 순환을 만들지 않는다). 훅의 `_load()` 는 `project_at` 도 가져온다. `cli.py` 의 `COMMAND_MODULES` 끝에 `"workspace"` 를 더하고 `workspace.register(sub)` 가 `slot` 파서와 `prepare` 하위 파서를 만든다. 기존 `testgate._env()` 를 부르던 곳은 `child_env(None)` 으로 바꾼다(동작 그대로).

- [ ] **Step 4: 통과 확인**

Run: `cd herdr-team && python3 -m unittest tests.test_workspace tests.test_hooks tests.test_testgate tests.test_base 2>&1 | tail -3`
Expected: `OK`. 그다음 저장소 루트에서 `bash herdr-team/tests/run.sh 2>&1 | tail -3`(백그라운드, 10–15분) Expected: `OK`(공유 시험 도구의 `act` 는 cwd 가 프로젝트 루트인 지금 Dispatch 에서 그대로다).

- [ ] **Step 5: 정적 확인과 커밋**

```bash
python3 - <<'PY'
import ast, pathlib
for f in ["herdr-team/lib/hteam/workspace.py", "herdr-team/lib/hteam/paths.py", "herdr-team/lib/hteam/gitio.py",
          "herdr-team/lib/hteam/testgate.py", "herdr-team/lib/hteam/cli.py", "herdr-team/hooks/hteam_hook.py",
          "herdr-team/tests/helpers.py", "herdr-team/tests/test_workspace.py", "herdr-team/tests/test_hooks.py"]:
    ast.parse(pathlib.Path(f).read_text(encoding="utf-8"), feature_version=(3, 11))
PY
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews'
FILES="herdr-team/lib/hteam/workspace.py herdr-team/lib/hteam/paths.py herdr-team/lib/hteam/gitio.py herdr-team/lib/hteam/testgate.py herdr-team/lib/hteam/cli.py herdr-team/hooks/hteam_hook.py herdr-team/tests/helpers.py herdr-team/tests/test_workspace.py herdr-team/tests/test_hooks.py"
git add -- $FILES
git commit -m "feat(herdr-team): 작업 공간 코어(slots.json·슬롯 잠금·worktree·브랜치·표시 파일·setup/teardown·slot prepare, 두 루트의 find_project·훅)" \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- $FILES
```

Expected: ast 오류 없음, grep 빈 출력, 커밋 하나. 구현자는 여기서 멈춘다(컨트롤러가 `scripts/codex-review.sh commit <sha>`).

---

### Task 4: 작업 공간 흐름 1 — 배정의 0, start 의 슬롯 예약·대기·busy, horch `--cwd`·`--env`, 작업 공간 절, 슬롯 안의 리뷰·관문, 관제의 준비 자식·`workspace_failed`

설계 5.9.4 의 0, 5.10.1, 5.10.3 의 1·5 와 끝 두 문단, 5.10.4, 5.10.5, 5.7 의 7단계 작업 공간 문단, 6.1 의 7단계 줄, 8.8·8.11 의 준비 줄을 만든다. `[workspace] mode = "worktree"` 의 작업 공간 직무(Task 2 의 `covers`) 태스크는 늘 임시 워커이고(고정 에이전트는 그 직무를 갖지 못한다), `start` 가 프로젝트 잠금 안에서 슬롯을 잡는다: 이 태스크의 슬롯이 없으면 가장 작은 `free` 슬롯에 예약(`preparing`)만 쓰고 owns 를 남긴 채 기다리고(대기 사유 `slot_setup`, 빈 슬롯이 없으면 `slot`), 관제가 그 예약마다 준비 자식 `hteam slot prepare T`(Task 3)를 띄우고, 준비가 끝난(`ready`) 예약을 다음 `start` 가 `busy` 로 바꾸고 태스크 상태에 `workspace` 를 쓴 뒤 5.4 의 3 이후(새 라운드, 사양, horch)를 한다. 예약도 owns 잠금을 쥔다(Codex 설계 리뷰 r1). horch 는 작업·리뷰어 모두 `--cwd <작업 루트> --env=<슬롯 env>` 로 부른다(Task 1). 워커 사양에는 작업 공간 절(5.10.5 원문)을, 리뷰 프롬프트 `## 태스크` 에는 그 첫째·셋째 줄을 넣는다. 리뷰의 git 조회(대상 커밋·바뀐 파일·사전 검사·변조 기준점)·관문 테스트(cwd 와 슬롯 env·`HTEAM_SLOT`)·리뷰 파일과 그 커밋·이전 리뷰 읽기는 그 태스크의 작업 루트에서 한다. 슬롯 안에서 부른 워커의 `hteam test T` 도 같다. 준비 자식이 실패하면 관제가 decide `workspace_failed`(`setup_failed`·`slot_dirty`·`branch_exists`)를 올린다. 메인 폴더가 detached HEAD 면 예약하지 않고 `workspace_failed`(`base_moved`)다.

병합·놓기·drop·`slot reset`·`status` 의 `workspace`·마무리 full·`merge_conflict` 는 Task 5 다. 이 태스크는 accept 를 바꾸지 않는다(시험의 accept 도 없다). `full_if` 는 Task 6, 이슈 줄은 Task 7 이고, 이 태스크의 작업 루트 규칙 위에 얹힌다. 브리프 Task 6 의 "작업 루트 cwd·슬롯 env·`HTEAM_SLOT`" 을 여기로 옮겼다(헤더 "태스크 순서와 의존"). 헤더 "공유 시험 도구" 의 `ws_start` 도 이 태스크가 넣는다(Task 5·6·8 의 시험이 쓴다).

**Files:**
- Modify: `herdr-team/lib/hteam/crew.py`(place 의 0), `herdr-team/lib/hteam/tasks.py`(`_prepare_start` 의 슬롯 잡기, `lock_conflicts` 의 예약, `start`·`start_command`·`start_ready` 의 대기 사유, `run_work`·`fix` 의 작업 루트, `fix` 의 슬롯 확인), `herdr-team/lib/hteam/workspace.py`(`view`, `env_args`), `herdr-team/lib/hteam/dispatch.py`(`launch` 의 cwd·env), `herdr-team/lib/hteam/review.py`(작업 루트, 리뷰어 cwd·env), `herdr-team/lib/hteam/testgate.py`(작업 루트, `execute`·`attempt`·`run_quick` 의 cwd·env), `herdr-team/lib/hteam/compose.py`(작업 공간 절·리뷰 줄, 작업 루트의 이전 리뷰·린트), `herdr-team/lib/hteam/drive.py`(`DECIDE_KINDS`, `slot_step`, 준비 자식 거두기, 틱·재확인 자리, decide `files` 의 작업 루트 산출물), `herdr-team/templates/review-prompt.md`(`{{workspace}}` 자리), `herdr-team/tests/helpers.py`(`ws_start`, 공유 시험 도구)
- Test: `herdr-team/tests/test_workspace_flow.py`(새로), `herdr-team/tests/test_drive.py`(`DECIDE_KINDS` 기대값 Edit)

**Interfaces:**
- Consumes: Task 1 의 `worker-start --env=KEY=VALUE`(되풀이)·`--task --retry` 의 env·`worker-show` 행의 `env`, Task 2 의 `cfg.workspace.covers(role)`·`on`·`slots`·`env`, Task 3 의 `workspace.load`·`entry`·`save`·`held_by`·`branch_of`·`SLOT_DEFAULT`·`work_root`·`task_root`·`slot_env`·`task_env`·`slot_busy`, `paths.Project(root, work_root=)`·`project_at`, `gitio.current_branch`, `hteam slot prepare T` 의 성공 출력 `{task, slot, root, branch, base_branch, base, setup, ready}` 과 실패(`slot_dirty`·`branch_exists`·`setup_failed`·`slot_locked`·`slot_not_reserved`, data 의 `kind`·`slot`·`files`·`branch`·`status`·`exit`·`log`·`tail`), `testgate.child_env(cfg, extra)`, Task 2 의 `config.test_settings`, 6단계의 `Drive.spawn`·`reap_jobs`·`decide`·`log`·`_files`·`_grounds`·`start_ready`·`reconcile`·`procedure_failed`, `outbox.open_decide`, `paths.report_rel`·`review_rel`.
- Produces:
  - `crew.place(p, cfg, role, worker, *, crew_name=None)`: 맨 앞에서 `cfg.workspace.covers(role)` 면 `dict(TEMP)`(5.9.4 의 0). `crew_name`(같은 라운드 복구)이 와도 같다.
  - `start` 의 슬롯 잡기 오류(exit 3, `_prepare_start` 가 낸다. 문구 원문):
    - `slot_preparing`: `작업 공간 slot-{n} 을 준비하는 중이다(관제가 hteam slot prepare 를 돌린다)`, hint `준비가 끝나면 관제가 띄운다`.
    - `no_free_slot`: `빈 작업 공간 슬롯이 없다(slots = {cfg.workspace.slots})`, hint `슬롯이 비면 관제가 띄운다`.
    - `base_detached`: `메인 폴더가 detached HEAD 라 {tid} 의 작업 공간 슬롯을 잡지 않았다(기준 브랜치가 없다). 메인 폴더를 기준 브랜치로 되돌린 뒤 다시 시작한다`, hint `메인 폴더에서 git switch <기준 브랜치> 뒤 hteam start {tid}`.
  - `tasks.fix` 의 슬롯 확인(Rules 12, Codex 계획 리뷰 r1): `cfg.workspace.covers(spec.role)` 인 태스크면 `first`(상태)를 읽고 `allowed(first)` 를 본 바로 뒤, 이전 Dispatch 를 정리하거나(`_close_round`) 무엇을 쓰기 전에 `workspace.load(p)` 에서 그 태스크가 쥔 슬롯(`held_by`)의 기록이 `busy` 인지 본다. 아니면 아무것도 바꾸지 않고 exit 3 `slot_not_held`: `{tid} 는 작업 공간 슬롯을 쥐고 있지 않다(슬롯 준비가 끝나지 않았거나 실패했다). fix 는 슬롯 밖에서 새 라운드를 열지 않는다`, hint `hteam start {tid}`, data `{"status": <상태>, "slot": <쥔 슬롯 번호 또는 null>}`. shared·작업 공간 직무가 아닌 태스크는 보지 않는다(`slots.json` 을 읽지 않는다).
  - `tasks.START_WAIT` 에 `slot_preparing: "slot_setup"`, `no_free_slot: "slot"`. `WAIT_TAIL` 에 `slot_setup: "준비가 끝나면 관제가 띄운다"`, `slot: "슬롯이 비면 관제가 띄운다"`. `WAIT_CODES` 에 `slot_preparing: "slot_setup"`, `no_free_slot: "slot"`, `base_detached: "decide"`. `start_command` 는 이 둘(`slot_preparing`·`no_free_slot`)을 처음 시작(pending)뿐 아니라 라운드 없는 `launch_failed`(준비 실패 뒤)에서도 waiting 으로 바꾼다. 결과 예: `{"ok": true, "id": "T-001", "status": "waiting", "reason": "slot_setup", "message": "T-001: 작업 공간 slot-1 을 준비하는 중이다(관제가 hteam slot prepare 를 돌린다). pending 으로 두었다. 준비가 끝나면 관제가 띄운다"}`.
  - 예약 기록(Task 3 노트의 꼴, `state/slots.json`): `{"state": "preparing", "task": T, "branch": "herdr/T", "base_branch": <git symbolic-ref --short HEAD>, "base": <메인 HEAD sha>, "setup_done": <그 슬롯의 앞 값>, "since": now()}`. 태스크 상태에는 같은 쓰기 구간에서 `owns` 만 쓴다(`pending` 그대로, 라운드 없음).
  - busy 로 바꿀 때: 슬롯 기록 `{**기록, "state": "busy", "since": now()}` 에서 `ready` 를 뗀다. 태스크 상태 `workspace = {"slot": n, "branch": 기록의 branch, "base_branch": 기록의 base_branch, "root": str(workspace.work_root(p, n)), "merge": null}`, `base` 가 None 이면 기록의 `base`. 새 라운드의 `round_base` 는 작업 루트의 HEAD(`gitio.head(<작업 루트>)`). fix 의 새 라운드도 같다.
  - `tasks.lock_conflicts(p, tid, owns)`: `state.LOCKING` 상태에 더해, `workspace.load(p)` 의 기록 가운데 `task` 가 있는 슬롯을 쥔 태스크(`pending` 이어도)를 잠금을 가진 것으로 본다(그 태스크 상태의 `owns`). 닫힌 태스크(`state.CLOSED`: 병합 뒤 놓기 전에 슬롯이 아직 `busy` 인 done, drop 뒤)는 세지 않는다(잠금은 병합까지, 설계 5.10.6). `slots.json` 이 없으면 지금 그대로. 깨졌으면 `bad_slots_file`(exit 1, 덮어쓰지 않는다).
  - `workspace.view(p, st) -> Project`: `Project(p.root, work_root=workspace.task_root(p, st))`. `workspace.env_args(env: dict) -> list[str]`: 이름 순서의 `--env=KEY=VALUE`.
  - `dispatch.launch(p, h, tid, pick, *, …, cwd: Path | None = None, env: dict[str, str] | None = None)`: 새로 띄우기·같은 Task 다시 띄우기(`--task --retry`)의 `--cwd` 는 `cwd or p.root`, env 가 있으면 `env_args(env)` 를 더한다(빈 dict·None 이면 없음). `--terminal`(같은 터미널) 갈래에는 넣지 않는다(작업 공간 직무는 고정 에이전트가 없다, horch 도 usage).
  - `compose.work_spec(p, cfg, spec, rd, owns, st=None)`: `st` 에 `workspace` 가 있으면 인수인계 줄 다음, 작업 규칙(worker-rules.md) 앞에 작업 공간 절(`compose.workspace_section(cfg, st)`). 원문(5.10.5. `<작업 루트>` 는 `workspace.root`, 기준은 `base_branch`, 셋째 줄은 `[workspace.env]` 가 있을 때만, 이름 순서로 `` `KEY=VALUE` `` 를 `, ` 로 잇고 `HTEAM_SLOT` 은 넣지 않는다):

    ```
    ## 작업 공간
    - 이 태스크는 슬롯 worktree `<작업 루트>` 에서 한다. 브랜치는 `herdr/T-xxx`(기준 `<기준 브랜치>`)다. 이 폴더 밖(메인 폴더, 다른 슬롯)의 파일을 고치지 않는다.
    - 커밋은 이 브랜치에 한다. 병합·push·브랜치 바꾸기·rebase 는 하지 않는다. 리뷰가 승인하면 관제가 병합한다.
    - 시험 환경(이 슬롯 전용): `HT_PORT=8110`. 다른 값을 쓰지 않는다.
    ```

    둘째 줄은 Task 5 가 기준 병합 라운드에서 바꾼다(그래서 `st` 를 통째로 받는다). Task 7 의 이슈 줄은 이 절 다음, 작업 규칙 앞이다.
  - `compose.review_workspace(cfg, st) -> str`: 작업 공간 태스크면 `"\n- " + 첫째 줄 + ("\n- " + 셋째 줄 if env)`, 아니면 `""`. 템플릿 `review-prompt.md` 의 `- 이전 리뷰: {{prior}}{{request}}` 줄을 `- 이전 리뷰: {{prior}}{{request}}{{workspace}}` 로 바꾼다(Step 3. Task 7 의 찾을 내용 세 줄은 건드리지 않는다). `compose.review_prompt(p, cfg, spec, rd, att, rounds=None)` 는 상태를 읽어(`state.load(p, spec.id)`, 없으면 작업 공간이 아닌 것으로) `workspace` 값을 채운다.
  - 작업 루트에서 하는 것(이 태스크가 `p.root` 를 `p.work_root` 로 바꾸는 자리. 들어가는 함수가 `p = workspace.view(p, st)` 로 다시 묶는다. 상태·로그·확정 기록·`[test]` 설정·`--root`·`p.work_file(…).relative_to(p.root)` 는 `p.root` 그대로):
    - `review.py`: `target_commits`·`changed_files`·`prechecks`(differs·dirty)·`_precheck_fail`(반려 파일 쓰기·dirty·커밋)·`_changes`·`baseline`·`tamper_check`·`_launch_attempt`(결과 파일 지우기)·`_read_verdict`·`_evidence`·`_finish`(최종 파일·`r{n}-a*.md` 지우기·커밋). 들어가는 곳: `review`·`review_finish`·`_new_attempt`.
    - `testgate.py`: `code_head`·`quick_files`(작업 루트에 파일로 있는 것)·`check_committed`·`dirty_files`·`execute` 의 cwd. 들어가는 곳: `run_task`·`gate_results`·`retry_results`·`record_task`. `[test]` 설정(`load_config`)은 메인 프로젝트의 커밋된 HEAD 에서 읽는다(아래 Rules 7).
    - `compose.py`: `work_spec` 의 이전 리뷰 파일 확인, `review_prompt` 의 이전 리뷰 목록, `design_section`·`text_section` 의 린트(작업 트리 파일 읽기).
    - `tasks.py`: `_prepare_start`·`fix` 의 `round_base`, `run_work` 의 horch `cwd`·`env`.
  - `testgate.execute(p, command, log, timeout_s, ok_exit, args=(), shown=None, *, cwd=None, env=None)`: cwd 는 `cwd or p.work_root`, 환경은 `child_env(None, env)`. `attempt(…, *, cwd=None, env=None)`·`run_quick(p, cfg, files, name, *, cwd=None, env=None)` 는 그대로 넘긴다. 태스크 관문(`record_task`)은 `env = workspace.task_env(p, config.test_settings(p), st)` 다(Task 2 Rules 11: `hteam test` 와 리뷰 관문이 같이 지나는 자리라 `config.load` 를 부르지 않는다. 설정이 깨져도 `hteam test` 가 돈다, 설계 4.2. shared 면 빈 dict 이라 지금과 같다).
  - 리뷰어: `_launch_attempt` 가 `dispatch.launch(…, cwd=p.work_root, env=workspace.slot_env(cfg, n) if 작업 공간 태스크 else None)`. 작업: `run_work` 도 같다(같은 라운드 복구 포함).
  - 관제(drive.py):
    - `DECIDE_KINDS` 끝에 `"workspace_failed"`.
    - decide `files` 의 작업 루트 산출물(Rules 13, Codex 계획 리뷰 r1): `Drive._work_files(st, *rels) -> list[str]` 는 태스크 산출물을 그 태스크의 작업 루트(`workspace.task_root(p, st)`)에서 찾아 있는 것만 메인 루트 기준 posix 경로(`(task_root / rel).relative_to(p.root)`, 슬롯이면 `.herdr-team/state/slots/slot-<N>/<rel>`)로 낸다. 산출물은 지금 코드에서 작업 트리에 생기는 둘이다: 보고서 `paths.report_rel(tid)`(`docs/tasks/T-xxx/report.md`, 워커가 쓴다)와 리뷰 결과·hteam 반려 파일 `paths.review_rel(tid, n)`(`docs/reviews/T-xxx/rN.md`, `review._finish`·`_precheck_fail` 이 작업 루트에 쓴다). `_files(*rels)` 는 지금처럼 메인 루트에서 본다: 사양 `.herdr-team/tasks/T-xxx.md`(`_grounds` 의 첫째), `GROUNDS`(기획 문서), 직무 문서·`project.md`, `docs/planning/tasks.toml`, 슬롯 로그(`state/slots/logs/…`). 바꾸는 자리: escalation·`worker_failed`·`worker_question` 의 `self._files(*self._grounds(tid))` 는 `self._files(<사양>) + self._work_files(st, report_rel(tid))`(차례는 지금 그대로: 사양, 보고서, 그다음 GROUNDS…), `_max_rounds`·`hteam_changes` 의 repeat_test_failure 는 `self._work_files(st, review_rel(tid, st["round"]))`. 작업 공간 태스크가 아니거나 병합한 뒤(`task_root` 가 `p.root`)면 지금과 같은 목록이다.
    - `Drive.slot_step() -> None`: `slots.json` 의 `preparing` 이고 `ready` 가 아닌 기록마다(번호 순), 키 `slot:<N>` 의 자식이 없고, 그 태스크에 열린 decide 가 없고(`outbox.open_decide`), `workspace.slot_busy(p, n)` 가 거짓이면 `spawn(f"slot:{n}", ["slot", "prepare", T])` 하고 로그 `slot-<N> <T> 준비 시작`.
    - `reap_jobs` 의 `slot:<N>` 갈래 → `Drive._slot_done(n, tid, code, data)`(격리 키 `job:slot:<N>`. `tid` 는 자식 인자의 셋째, data 는 stdout 의 마지막 JSON 객체):
      - 성공: 로그 `slot-<N> <T> 준비 ready`(`setup` 이 None 이 아니면 `slot-<N> <T> 준비 ready(setup passed)`) 뒤 `start_ready()`(격리 키 `start_ready`).
      - `setup_failed`: decide `workspace_failed`, task T, summary 는 자식 오류 문구, `files=self._files(log)`, `commands=["hteam start T"]`, `detail={"kind", "slot", "status", "exit", "log"}`, `tail`.
      - `slot_dirty`: decide `workspace_failed`, **task None**(그 태스크는 다른 슬롯을 잡을 수 있어야 한다. 태스크에 decide 를 쓰면 start-ready 가 그 태스크를 건너뛴다, 설계 5.10.3 의 2), summary 는 자식 오류 문구, `commands=["hteam slot reset <N>"]`, `detail={"kind", "slot", "files", "task"}`. 그 뒤 `start_ready()`.
      - `branch_exists`: decide `workspace_failed`, task T, `commands=["hteam start T"]`, `detail={"kind", "slot", "branch"}`.
      - `slot_locked`·`slot_not_reserved`: 로그 `slot-<N> <T> 준비 건너뜀(<code>)` 만.
      - 그 밖의 오류·출력 없음: `procedure_failed(T, HteamError(code, message))`(지금 관제 절차 실패와 같다).
      - 실패 셋(`setup_failed`·`slot_dirty`·`branch_exists`)은 로그 `slot-<N> <T> 준비 <code>`.
    - 자리: 틱의 큐 뒤 `start_ready` 다음(요청을 실행한 틱만)과 재확인의 `start_ready` 다음에 `isolated("slots", self.slot_step)`.
    - `base_detached`(start 의 오류): `tasks.start` 가 잠금을 모두 놓은 뒤 `Drive(p).decide("workspace_failed", tid, <문구>, commands=[f"hteam start {tid}"], detail={"kind": "base_moved", "detached": True})` 를 올리고 같은 오류를 다시 올린다(관제 안에서만 불리는 큐 명령이다. drain 의 `Drive(p).decide` 와 같은 자리).
  - drive.log 줄(설계 8.11 `slot-<N> <T> <단계> <결과>`): `잡기 preparing`(start 가 예약을 쓸 때, `tasks` 가 `Drive(p).log`), `준비 시작`·`준비 ready`·`준비 ready(setup passed)`·`준비 <code>`·`준비 건너뜀(<code>)`(관제), `사용 busy`(start 가 busy 로 바꿀 때). Task 5 가 `놓기 …` 를 더한다.
- 잠금: 슬롯 잡기는 `_prepare_start` 의 프로젝트 잠금 → 태스크 잠금 안에서 `slots.json` 을 읽고 쓴다(헤더 순서. 슬롯 잠금은 잡지 않는다). decide·로그는 잠금을 모두 놓은 뒤다.

**Rules:**

1. 배정(5.9.4 의 0): `crew.place` 의 맨 앞. 4.2 의 검사(Task 2)가 작업 공간 직무를 가진 고정 에이전트를 막으므로 설정 파일로는 그런 구성이 없지만, `place` 는 설정을 다시 보지 않고 늘 임시 워커를 고른다.
2. 슬롯 잡기(5.10.3 의 1, 끝 문단): `_prepare_start` 가 상태·잠금(`_check_locks`)·결정 관문·동시 수 상한·배정을 지난 뒤, `cfg.workspace.covers(spec.role)` 면 `slots.json` 을 읽는다(엄격).
   1. 이 태스크의 슬롯(`held_by`)이 없으면: 메인 폴더 브랜치(`gitio.current_branch(p.root)`)가 None 이면 아무것도 쓰지 않고 `base_detached`(Rules 8). 아니면 `free` 인 가장 작은 번호(1–`slots`, `dirty`·`preparing`·`busy` 는 건너뛴다)에 예약 기록을 쓰고 태스크 상태에 `owns` 를 쓴 뒤 `slot_preparing` 으로 끝난다. 빈 슬롯이 없으면 아무것도 쓰지 않고 `no_free_slot`.
   2. 있고 `preparing` 이고 `ready` 가 아니면 `slot_preparing`(아무것도 쓰지 않는다).
   3. 있고 `preparing`·`ready` 면 그 기록을 `busy` 로, 태스크 상태에 `workspace`(Interfaces)를 쓰고 이어 5.4 의 3 이후를 한다.
   4. 있고 `busy` 면(수정 라운드·같은 라운드 복구) 그대로 이어 한다.
   - `state.edit` 은 블록이 예외로 끝나면 쓰지 않으므로, 1 의 예약은 블록 안에서 기록과 `owns` 를 쓰고 블록을 정상으로 빠져나온 뒤 오류를 올린다(아래 조각). 2 와 오류인 1 은 쓸 것이 없다.
3. 잠금(Codex 설계 리뷰 r1): 예약을 쥔 `pending` 태스크도 owns 잠금을 쥔다(`lock_conflicts`). 그래서 owns 가 겹치는 두 태스크가 같은 옛 기준에서 각각 브랜치를 준비하지 않는다. 대기 사유는 지금처럼 `lock`(`owns_locked` 의 문구에 그 태스크 ID). 슬롯 기록의 `task` 가 닫힌 태스크(`done`·`dropped`)면 잠금이 아니다: 병합이 끝나 `done` 이 된 뒤 놓기(Task 5)가 슬롯을 `free` 로 쓰기 전에도 후행 태스크가 시작한다. 예약은 `free` 기록만 잡는다(`dirty`·`preparing`·`busy` 는 건너뛴다. Task 5 의 마무리 full 은 `busy` 로 쓴다).
4. horch(5.10.3 의 5, 5.10.4): 작업(`run_work`)과 리뷰어(`_launch_attempt`)는 작업 공간 태스크면 `cwd = <작업 루트>`, `env = workspace.slot_env(cfg, slot)`(값의 `{slot}` 을 채운 `[workspace.env]` + `HTEAM_SLOT`)로 띄운다. 같은 라운드 복구(`--task --retry`)·fix 의 새 라운드도 같은 인자다(horch 가 물려받아도 hteam 이 늘 넘긴다). shared·메인 폴더 태스크는 지금 그대로(`--cwd <프로젝트 루트>`, `--env` 없음).
5. 사양(5.10.5, 5.5 의 8): 작업 공간 절은 인수인계 줄과 작업 규칙 사이다. env 가 없으면 셋째 줄을 뺀다. 리뷰 프롬프트에는 첫째·셋째 줄을 `## 태스크` 의 이전 리뷰 줄 뒤에 글머리 줄로 넣는다.
6. 작업 루트(5.10.2 두 루트, 5.10.4, 6.1 7단계 줄): 태스크의 git 조회·작업 트리 파일 읽기·쓰기·커밋은 그 태스크의 작업 루트(`workspace.view(p, st).work_root`)에서 한다. 리뷰 파일 커밋 `[T-xxx] review rN:` 과 관문 반려 커밋은 태스크 브랜치에 쌓인다(병합 때 기준 브랜치로 들어간다, Task 5). 변조 기준점은 슬롯의 HEAD·작업 트리다: 메인 폴더나 다른 슬롯의 커밋은 이 슬롯의 HEAD 를 움직이지 않으므로 변조가 아니다. 상태(`state/`)·테스트 기록·로그·확정 기록은 늘 메인의 것이다(5.7 7단계 줄). 슬롯 안에서 부른 `hteam test T` 는 `find_project` 가 메인 상태를 돌려주고(Task 3), 위치는 `p.work_root`(찾은 폴더)가 아니라 태스크 상태의 `workspace.root` 로 정한다.
7. 관문(5.7 7단계 작업 공간 문단): 작업 공간 태스크의 테스트는 cwd 가 작업 루트이고 환경은 `child_env(None, workspace.task_env(p, config.test_settings(p), st))`(그 슬롯의 env 와 `HTEAM_SLOT`. 설정은 검사 없이 읽는다, Task 2 Rules 11). worktree 모드의 메인 폴더 태스크(작업 공간 직무가 아닌데 관문이 있는 경우)는 슬롯 0 값이다. `[test]` 설정은 지금처럼 커밋된 HEAD 에서 읽되 메인 프로젝트(상태 루트)의 HEAD 다: 설정은 기획 태스크가 기준 브랜치에 커밋하고(메인 폴더), 확정 기록은 그 식별값이다. 태스크 브랜치는 그보다 뒤처질 수 있다.
8. detached HEAD(5.10.1): 처음 시작하는 작업 공간 태스크의 기준 브랜치가 없으면 예약하지 않는다. `tasks.start` 가 잠금 밖에서 decide `workspace_failed`(`detail.kind` 는 `base_moved`, `detached: true`)를 올린 뒤 `base_detached` 를 올린다. 열린 decide 가 있는 동안 start-ready 는 그 태스크를 띄우지 않는다(대기 사유 `decide`, `WAIT_CODES`). 메인이 고친 뒤 부르는 `hteam start T` 는 열린 decide 를 보지 않는다(지금 규칙).
9. 준비 자식(5.10.3 끝 두 문단, 8.8): 관제는 `slot_step` 으로 예약마다 준비를 띄운다(한 슬롯에 하나: 키 `slot:<N>` 과 슬롯 잠금 비차단 시도). 관제가 죽어 자식만 남았으면 슬롯 잠금이 쥐어져 있어 기다리고, 자식도 죽었으면 다음 재확인이 다시 띄운다(준비는 이어 하기 안전, Task 3 Rules 8). 그 태스크에 열린 decide 가 있으면 띄우지 않는다(같은 실패를 되풀이하지 않게).
10. 준비 실패(5.10.3 의 2·4, 5.10.8): 거두기 규칙은 Interfaces. `setup_failed`·`branch_exists` 는 Task 3 이 슬롯을 `free`, 태스크를 라운드 없는 `launch_failed` 로 썼다. decide 가 태스크에 붙어 start-ready 가 곧바로 다시 띄우지 않는다. 메인이 사용자와 고친 뒤 `hteam start T` 를 부르면 다시 예약한다(`start_command` 가 라운드 없는 `launch_failed` 도 waiting 으로). `slot_dirty` 는 슬롯이 `dirty`·태스크 없음이 되고 태스크는 `pending` 이라 바로 다음 슬롯을 잡을 수 있다(decide 는 태스크 없이 한 번. 그 슬롯은 dirty 라 다시 잡히지 않는다).
11. 회귀(헤더 "기본값"): `cfg.workspace.covers` 가 거짓이면 이 태스크의 모든 갈래를 지나지 않는다: `slots.json` 을 읽지도 쓰지도 않고(`lock_conflicts` 는 파일이 없으면 지금 그대로), horch 인자·사양·프롬프트·관문 위치가 지금과 같다(`{{workspace}}` 는 빈 글, `p.work_root == p.root`).
12. fix 는 슬롯을 잡지 않는다(5.10.3, 6.4, Codex 계획 리뷰 r1): 준비 실패(`setup_failed`·`branch_exists`)는 라운드·`workspace` 없는 `launch_failed` 이고 `FIX_FROM` 에 든다. 그대로 fix 하면 `_prepare_start` 를 거치지 않아 슬롯 env·작업 공간 절 없이 메인 폴더에서 워커가 뜬다. 그래서 작업 공간 직무 태스크의 fix 는 그 태스크가 `busy` 슬롯을 쥘 때만 하고, 아니면 상태를 바꾸기 전에 `slot_not_held` 로 거부한다(Interfaces). 다시 시작은 `hteam start T`(Rules 2 가 슬롯을 다시 잡는다)다. 관제의 자동 fix 는 이 경우를 부르지 않는다: 라운드 없는 `launch_failed` 는 `Drive._launch_failed` 가 건너뛰고, 준비 실패 decide 의 commands 는 `hteam start T` 다. 병합 충돌 뒤의 `changes`·작업 중·리뷰 반려는 슬롯이 `busy` 라 지금처럼 fix 한다.
13. decide 근거 파일(8.10 "decide 의 files 만 읽는다", 5.10.2 두 루트): 병합 전 작업 공간 태스크의 보고서·리뷰 파일은 슬롯에만 있으므로 관제 decide 의 `files` 는 그 슬롯 경로다(Interfaces 의 `_work_files`). 메인은 메인 루트 기준 경로를 그대로 연다. 사양·기획 문서·직무 문서·설정·로그는 메인 것이다.

핵심 조각(그대로 옮기지 않아도 된다) — `_prepare_start` 의 슬롯 잡기(Rules 2. 프로젝트 잠금·태스크 잠금 안, 배정 뒤):

```python
wait = None
if cfg.workspace.covers(spec.role):
    data = workspace.load(p)
    n = workspace.held_by(data, tid)
    if n is None:
        branch = gitio.current_branch(p.root)
        n = None if branch is None else next(
            (i for i in range(1, cfg.workspace.slots + 1) if workspace.entry(data, i)["state"] == "free"), None)
        if branch is None:
            wait = _base_detached(tid)
        elif n is None:
            wait = _no_free_slot(cfg)
        else:
            data["slots"][str(n)] = {**workspace.SLOT_DEFAULT, "state": "preparing", "task": tid,
                                     "branch": workspace.branch_of(tid), "base_branch": branch,
                                     "base": gitio.head(p.root),
                                     "setup_done": workspace.entry(data, n)["setup_done"], "since": now()}
            workspace.save(p, data)
            st["owns"] = owns            # 예약이 owns 잠금을 쥔다(lock_conflicts 가 본다)
            wait, reserved = _preparing(n), n
    else:
        rec = workspace.entry(data, n)
        if rec["state"] == "preparing" and not rec.get("ready"):
            wait = _preparing(n)
        elif rec["state"] == "preparing":
            data["slots"][str(n)] = {k: v for k, v in {**rec, "state": "busy", "since": now()}.items() if k != "ready"}
            workspace.save(p, data)
            st["workspace"] = {"slot": n, "branch": rec["branch"], "base_branch": rec["base_branch"],
                               "root": str(workspace.work_root(p, n)), "merge": None}
            st["base"] = st["base"] or rec["base"]
            busied = n
# (with state.edit 블록 끝) 블록을 정상으로 나가야 예약과 owns 가 저장된다. 그 뒤(프로젝트 잠금 밖) 로그를 쓰고 올린다
if wait is not None:
    raise wait                          # slot_preparing·no_free_slot·base_detached(base_detached 는 start 가 decide 를 먼저)
```

핵심 조각 — 준비 자식 거두기(Rules 9·10):

```python
def _slot_done(self, n: int, tid: str, code: int, data: dict | None) -> None:
    err = (data or {}).get("error") or {}
    if code == 0 and data and data.get("ok"):
        self.log(f"slot-{n} {tid} 준비 ready" + ("(setup passed)" if data.get("setup") else ""))
        self.isolated("start_ready", self.start_ready)
        return
    kind = err.get("code")
    if kind in ("slot_locked", "slot_not_reserved"):
        self.log(f"slot-{n} {tid} 준비 건너뜀({kind})")
        return
    if kind not in ("setup_failed", "slot_dirty", "branch_exists"):
        self.procedure_failed(tid, HteamError(kind or "failed", err.get("message") or f"exit {code}: 출력이 없다"))
        return
    self.log(f"slot-{n} {tid} 준비 {kind}")
    if kind == "slot_dirty":
        self.decide("workspace_failed", None, err["message"], commands=[f"hteam slot reset {n}"],
                    detail={"kind": kind, "slot": n, "files": data.get("files") or [], "task": tid})
        self.isolated("start_ready", self.start_ready)
    elif kind == "setup_failed":
        self.decide("workspace_failed", tid, err["message"], files=self._files(data["log"]),
                    commands=[f"hteam start {tid}"], tail=data.get("tail") or "",
                    detail={k: data.get(k) for k in ("kind", "slot", "status", "exit", "log")})
    else:
        self.decide("workspace_failed", tid, err["message"], commands=[f"hteam start {tid}"],
                    detail={"kind": kind, "slot": n, "branch": data.get("branch")})
```

- [ ] **Step 1: 실패하는 테스트 작성**

헤더 "공유 시험 도구" 의 `ws_start`(Task 5·6·8 의 시험도 쓴다):

**Edit** `herdr-team/tests/helpers.py`

```python
def _parse(stdout: str, stderr: str) -> dict:
```

```python
    def ws_start(self, tid: str) -> dict:
        """작업 공간 태스크를 관제 쪽에서 처음 띄운다(설계 5.10.3): start(슬롯 예약, waiting slot_setup) → slot prepare(관제의
        준비 자식 자리) → start(슬롯 busy, 워커). 마지막 start 출력을 돌려준다."""
        code, out = self.hteam("start", tid)
        self.assertEqual((code, out.get("status"), out.get("reason")), (0, "waiting", "slot_setup"), out)
        code, out = self.hteam("slot", "prepare", tid)
        self.assertEqual(code, 0, out)
        code, out = self.hteam("start", tid)
        self.assertEqual((code, out.get("status")), (0, "working"), out)
        return out


def _parse(stdout: str, stderr: str) -> dict:
```

**Create** `herdr-team/tests/test_workspace_flow.py`

```python
"""작업 공간 흐름 1(7단계, 설계 5.9.4 의 0, 5.10.1·5.10.3·5.10.4·5.10.5, 5.7·6.1 의 7단계 줄, 8.8·8.11): 배정, start 의
슬롯 예약·준비 대기·busy, horch 의 --cwd·--env, 워커 사양의 작업 공간 절, 슬롯 안의 리뷰·관문·리뷰 커밋·변조 기준점·리뷰어,
관제의 준비 자식과 decide workspace_failed. 병합·놓기·drop·reset·status·마무리 full 은 test_workspace_merge(Task 5)."""
import json
import subprocess
import sys
import tomllib
import unittest

from tests.helpers import BASE_CONFIG, CREW_CONFIG, WS_CONFIG, TeamCase
from tests.test_drive_events import EventCase
from hteam import config, crew, state
from hteam.paths import Project

# 워커 사양의 작업 공간 절(설계 5.10.5 블록 원문. 작업 루트·태스크·포트를 채운다)
SECTION = ("## 작업 공간\n"
           "- 이 태스크는 슬롯 worktree `{root}` 에서 한다. 브랜치는 `herdr/{tid}`(기준 `main`)다. 이 폴더 밖(메인 폴더, 다른 슬롯)의 "
           "파일을 고치지 않는다.\n"
           "- 커밋은 이 브랜치에 한다. 병합·push·브랜치 바꾸기·rebase 는 하지 않는다. 리뷰가 승인하면 관제가 병합한다.\n"
           "- 시험 환경(이 슬롯 전용): `HT_PORT={port}`. 다른 값을 쓰지 않는다.")
# 리뷰 프롬프트 `## 태스크` 의 작업 공간 줄(설계 5.10.5: 첫째 줄과 셋째 줄)
REVIEW_LINES = ("\n- 이 태스크는 슬롯 worktree `{root}` 에서 한다. 브랜치는 `herdr/{tid}`(기준 `main`)다. 이 폴더 밖(메인 폴더, "
                "다른 슬롯)의 파일을 고치지 않는다.\n- 시험 환경(이 슬롯 전용): `HT_PORT={port}`. 다른 값을 쓰지 않는다.")
DETACHED = ("메인 폴더가 detached HEAD 라 T-001 의 작업 공간 슬롯을 잡지 않았다(기준 브랜치가 없다). 메인 폴더를 기준 브랜치로 "
            "되돌린 뒤 다시 시작한다")
# 관문 명령: 받은 슬롯 env 를 $FAKE_DIR/env.txt 에 남긴 뒤 가짜 테스트(cwd 는 가짜가 test-args.jsonl 에 남긴다)
ENV_QUICK = 'mkdir -p "$FAKE_DIR"; printf "%s %s\\n" "$HTEAM_SLOT" "$HT_PORT" >> "$FAKE_DIR/env.txt"; fake-test {files}'
NO_ENV_CONFIG = WS_CONFIG.replace('\n[workspace.env]\nHT_PORT = "81{slot}0"\n', "\n")
SETUP_FAIL_CONFIG = WS_CONFIG.replace("slots = 2\n", 'slots = 2\nsetup = "echo 설치 실패; exit 3"\n')
# 슬롯 잠금을 다른 프로세스가 쥔다(앞 관제가 남긴 준비 자식처럼). 시험이 표준 입력을 닫을 때 놓는다
HOLD_SLOT = ("import fcntl, sys; fh = open(sys.argv[1], 'a+'); fcntl.flock(fh, fcntl.LOCK_EX); "
             "print('held', flush=True); sys.stdin.read()")


class WsCase(TeamCase):
    """작업 공간 프로젝트(WS_CONFIG: developer·tester 가 작업 공간 직무, 슬롯 둘, HT_PORT)와 관제 Run, 태스크 T-001(src/a/**)."""

    config_text = WS_CONFIG

    def setUp(self):
        super().setUp()
        self.init_project(self.config_text)
        self.setup_run()
        self.p = Project(self.proj)
        self.write_spec("T-001", owns="src/a/**")

    def start(self, tid: str = "T-001") -> tuple[int, dict]:
        return self.hteam("start", tid)

    def record(self, n: int) -> dict:
        return self.slots()["slots"].get(str(n), {})

    def round_spec(self, tid: str = "T-001", n: int = 1) -> str:
        return (self.state_dir / "tasks" / tid / f"r{n}-work.md").read_text(encoding="utf-8")

    def logged(self, text: str) -> int:
        path = self.drive_dir / "drive.log"
        lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
        return sum(1 for line in lines if line.split(" ", 1)[-1] == text)

    def work(self, tid: str = "T-001", rel: str = "src/a/app.py") -> None:
        code, out = self.act_work(tid, {rel: "print('a')\n"})
        self.assertEqual(code, 0, out)

    def env_lines(self) -> list[str]:
        path = self.tmp / "fake" / "env.txt"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def slot_head(self, n: int = 1) -> str:
        return self.git_at(self.slot_root(n), "rev-parse", "HEAD").strip()


class ReserveTest(WsCase):
    """start 의 슬롯 잡기(설계 5.10.3 의 1·끝 문단): 예약만 쓰고 기다린다. 예약이 owns 잠금을 쥔다."""

    def test_first_start_reserves_smallest_free_slot_and_waits(self):
        base = self.head()
        code, out = self.start()
        self.assertEqual((code, out["status"], out["reason"]), (0, "waiting", "slot_setup"), out)
        self.assertEqual(out["message"], "T-001: 작업 공간 slot-1 을 준비하는 중이다(관제가 hteam slot prepare 를 돌린다). "
                                         "pending 으로 두었다. 준비가 끝나면 관제가 띄운다")
        rec = self.record(1)
        self.assertEqual({k: rec.get(k) for k in ("state", "task", "branch", "base_branch", "base", "setup_done")},
                         {"state": "preparing", "task": "T-001", "branch": "herdr/T-001", "base_branch": "main",
                          "base": base, "setup_done": None})
        self.assertRegex(rec["since"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertNotIn("ready", rec)
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["round"], st["rounds"], st["owns"]), ("pending", 0, [], ["src/a/**"]))
        self.assertNotIn("workspace", st)
        self.assertFalse(self.slot_root(1).exists())  # 폴더·브랜치·setup 은 준비 자식이 한다(start 가 하지 않는다)
        code, out = self.horch("worker-list")
        self.assertEqual(out["workers"], [])
        self.assertEqual(self.logged("slot-1 T-001 잡기 preparing"), 1)

    def test_start_again_while_preparing_changes_nothing(self):
        self.start()
        before = self.slots()
        code, out = self.start()
        self.assertEqual((code, out["status"], out["reason"]), (0, "waiting", "slot_setup"), out)
        self.assertEqual(self.slots(), before)
        self.assertEqual(self.logged("slot-1 T-001 잡기 preparing"), 1)

    def test_reservation_holds_owns_lock(self):
        self.write_spec("T-002", owns="src/a/b/**")
        self.start("T-001")  # 예약만(pending). 같은 옛 기준에서 두 태스크가 브랜치를 준비하지 않게(Codex 설계 리뷰 r1)
        self.assertEqual((self.task_state("T-001")["status"], self.record(1).get("task")), ("pending", "T-001"))
        code, out = self.start("T-002")
        self.assertEqual((code, out["status"], out["reason"]), (0, "waiting", "lock"), out)
        self.assertIn("T-001", out["message"])
        self.assertIsNone(self.record(2).get("task"))
        self.assertEqual(self.task_state("T-002")["status"], "pending")

    def test_dirty_slot_is_not_taken(self):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "slots.json").write_text(json.dumps({"slots": {"1": {
            "state": "dirty", "task": None, "branch": None, "base_branch": None, "base": None, "setup_done": None,
            "since": "2026-11-12T00:00:00Z"}}}), encoding="utf-8")
        code, out = self.start()
        self.assertEqual((code, out["reason"]), (0, "slot_setup"), out)
        self.assertEqual((self.record(1)["state"], self.record(2)["state"], self.record(2)["task"]),
                         ("dirty", "preparing", "T-001"))

    def test_no_free_slot_waits_slot(self):
        for tid, owns in (("T-002", "src/b/**"), ("T-003", "src/c/**")):
            self.write_spec(tid, owns=owns)
        self.start("T-001")
        self.start("T-002")
        code, out = self.start("T-003")
        self.assertEqual((code, out["status"], out["reason"]), (0, "waiting", "slot"), out)
        self.assertEqual(out["message"], "T-003: 빈 작업 공간 슬롯이 없다(slots = 2). pending 으로 두었다. "
                                         "슬롯이 비면 관제가 띄운다")
        self.assertEqual({n: self.record(n).get("task") for n in (1, 2)}, {1: "T-001", 2: "T-002"})
        st = self.task_state("T-003")
        self.assertEqual((st["status"], st["owns"]), ("pending", []))  # 예약하지 않았으니 owns 잠금도 없다

    def test_start_ready_reasons(self):
        for tid, owns in (("T-002", "src/b/**"), ("T-003", "src/c/**")):
            self.write_spec(tid, owns=owns)
        for tid in ("T-001", "T-002", "T-003"):
            state.create(self.p, tid, "developer")
        code, out = self.hteam("start-ready")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["started"], [])
        self.assertEqual([(w["task"], w["reason"]) for w in out["waiting"]],
                         [("T-001", "slot_setup"), ("T-002", "slot_setup"), ("T-003", "slot")])

    def test_detached_head_is_workspace_failed(self):
        self.git("checkout", "-q", "--detach")
        code, out = self.start()
        self.assertEqual((code, out["error"]["code"], out["error"]["message"]), (3, "base_detached", DETACHED), out)
        self.assertEqual(self.slots(), {"slots": {}})
        dec = [e for e in self.outbox_items() if e["type"] == "decide"]
        self.assertEqual([(e["kind"], e["task"], e["summary"], e["detail"], e["commands"]) for e in dec],
                         [("workspace_failed", "T-001", DETACHED, {"kind": "base_moved", "detached": True},
                           ["hteam start T-001"])])
        self.assertEqual(self.task_state("T-001")["decide"], dec[0]["id"])
        code, out = self.hteam("start-ready")  # 열린 decide 가 있는 동안 start-ready 는 띄우지 않는다(5.4)
        self.assertEqual([(w["task"], w["reason"]) for w in out["waiting"]], [("T-001", "decide")])
        self.assertEqual(len([e for e in self.outbox_items() if e["type"] == "decide"]), 1)


class LaunchTest(WsCase):
    """준비가 끝난 예약의 start(설계 5.10.3 의 5): busy, 태스크 상태의 workspace, horch --cwd·--env, 사양의 작업 공간 절."""

    def test_ready_start_goes_busy_and_launches_in_slot(self):
        base = self.head()
        out = self.ws_start("T-001")
        root = self.slot_root(1)
        self.assertEqual((self.record(1)["state"], self.record(1)["task"]), ("busy", "T-001"))
        self.assertNotIn("ready", self.record(1))
        st = self.task_state("T-001")
        self.assertEqual(st["workspace"], {"slot": 1, "branch": "herdr/T-001", "base_branch": "main",
                                           "root": str(root), "merge": None})
        self.assertEqual((st["base"], st["rounds"][0]["round_base"]), (base, self.slot_head()))
        row = self.dispatch_row(out["dispatch"])
        self.assertEqual((row["cwd"], json.loads(row["env"])), (str(root), {"HT_PORT": "8110", "HTEAM_SLOT": "1"}))
        self.assertEqual(self.git_at(root, "branch", "--show-current").strip(), "herdr/T-001")
        self.assertEqual(self.logged("slot-1 T-001 사용 busy"), 1)

    def test_work_spec_has_workspace_section_before_rules(self):
        self.ws_start("T-001")
        text = self.round_spec()
        self.assertIn(SECTION.format(root=self.slot_root(1), tid="T-001", port="8110") + "\n\n## 소유 경로와 작업 규칙", text)
        self.assertLess(text.index("## 선행 태스크"), text.index("## 작업 공간"))
        self.assertEqual(text.count("## 작업 공간"), 1)

    def test_two_tasks_run_in_two_slots(self):
        self.write_spec("T-002", owns="src/b/**")
        one = self.ws_start("T-001")
        two = self.ws_start("T-002")
        rows = [self.dispatch_row(x["dispatch"]) for x in (one, two)]
        self.assertEqual([(r["cwd"], json.loads(r["env"])["HT_PORT"]) for r in rows],
                         [(str(self.slot_root(1)), "8110"), (str(self.slot_root(2)), "8120")])
        self.assertIn("`HT_PORT=8120`", self.round_spec("T-002"))
        self.assertEqual(self.git_at(self.slot_root(2), "branch", "--show-current").strip(), "herdr/T-002")

    def test_closed_task_on_busy_slot_does_not_hold_lock(self):
        self.write_spec("T-002", owns="src/a/b/**")
        self.ws_start("T-001")
        with state.edit(self.p, "T-001") as st:  # 병합 뒤 놓기 전(Task 5): done 인데 슬롯 기록은 아직 busy 다
            st["status"] = "done"
        code, out = self.start("T-002")  # 잠금은 병합까지다. 슬롯을 쥔 닫힌 태스크는 owns 잠금을 쥐지 않는다
        self.assertEqual((code, out["status"], out["reason"]), (0, "waiting", "slot_setup"), out)
        self.assertEqual((self.record(1)["task"], self.record(2)["task"]), ("T-001", "T-002"))

    def test_same_round_recovery_keeps_cwd_and_env(self):
        code, out = self.start()
        code, out = self.hteam("slot", "prepare", "T-001")
        self.assertEqual(code, 0, out)
        self.fail_hc("run", "boom")
        code, out = self.start()
        self.assertEqual((code, out["error"]["code"]), (1, "launch_failed"), out)
        self.assertEqual((self.task_state("T-001")["status"], self.record(1)["state"]), ("launch_failed", "busy"))
        with self._hc_locked() as hc:
            hc["fail"].clear()
        code, out = self.start()
        self.assertEqual((code, out["mode"], out["status"]), (0, "retry", "working"), out)
        row = self.dispatch_row(out["dispatch"])
        self.assertEqual((row["cwd"], json.loads(row["env"])), (str(self.slot_root(1)), {"HT_PORT": "8110", "HTEAM_SLOT": "1"}))


class NoEnvTest(WsCase):
    """[workspace.env] 가 없으면 작업 공간 절의 셋째 줄을 뺀다(설계 5.10.5). horch 에는 HTEAM_SLOT 만 넘긴다."""

    config_text = NO_ENV_CONFIG

    def test_section_without_env_line(self):
        out = self.ws_start("T-001")
        text = self.round_spec()
        self.assertIn("- 커밋은 이 브랜치에 한다. 병합·push·브랜치 바꾸기·rebase 는 하지 않는다. 리뷰가 승인하면 관제가 병합한다."
                      "\n\n## 소유 경로와 작업 규칙", text)
        self.assertNotIn("시험 환경(이 슬롯 전용)", text)
        self.assertEqual(json.loads(self.dispatch_row(out["dispatch"])["env"]), {"HTEAM_SLOT": "1"})


class SlotReviewTest(WsCase):
    """리뷰의 작업 루트(설계 5.10.4·6.1 7단계 줄): 대상 커밋·관문·리뷰 파일 커밋·변조 기준점·리뷰어 cwd·env 가 슬롯이다."""

    def test_review_runs_in_slot_and_commits_on_task_branch(self):
        self.ws_start("T-001")
        root, main_head = self.slot_root(1), self.head()
        self.work()
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out["status"]), (0, "reviewing"), out)
        att = self.attempt("T-001")
        self.assertEqual([c["subject"] for c in att["inputs"]["commits"]], ["[T-001] r1 작업"])
        self.assertEqual(att["inputs"]["files"], ["docs/tasks/T-001/report.md", "src/a/app.py"])
        self.assertEqual(att["baseline"]["head"], self.slot_head())
        rrow = self.dispatch_row(att["dispatch"])
        self.assertEqual((rrow["cwd"], json.loads(rrow["env"])), (str(root), {"HT_PORT": "8110", "HTEAM_SLOT": "1"}))
        prompt = (self.state_dir / "tasks" / "T-001" / "r1-review-a1.md").read_text(encoding="utf-8")
        self.assertIn("- 이전 리뷰: 없음" + REVIEW_LINES.format(root=root, tid="T-001", port="8110") + "\n\n## 리뷰 대상 커밋",
                      prompt)
        code, out = self.act_review("T-001", "APPROVE")
        self.assertEqual(code, 0, out)
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual((code, out["status"]), (0, "approved"), out)
        self.assertEqual(self.git_at(root, "log", "-1", "--format=%s").strip(), "[T-001] review r1: APPROVE")
        self.assertTrue((root / "docs" / "reviews" / "T-001" / "r1.md").is_file())
        self.assertFalse((self.proj / "docs" / "reviews").exists())
        self.assertEqual(self.head(), main_head)  # 메인 폴더 브랜치에는 아직 아무것도 들지 않았다(병합은 Task 5)

    def test_main_folder_commit_during_review_is_not_tamper(self):
        self.ws_start("T-001")
        self.work()
        self.hteam("review", "T-001")
        self.commit("README.md", "# proj\n사람이 고침\n", "사람: README")  # 슬롯 밖(메인 폴더)의 커밋: 슬롯 HEAD 는 그대로다
        self.act_review("T-001", "APPROVE")
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual((code, out["status"]), (0, "approved"), out)

    def test_review_gate_runs_in_slot_with_slot_env(self):
        self.use_gate(quick=ENV_QUICK)
        self.ws_start("T-001")
        self.work()
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out["status"], out["tests"]), (0, "reviewing", {"quick": "passed"}), out)
        self.assertEqual([c["cwd"] for c in self.gate_calls()], [str(self.slot_root(1))])
        self.assertEqual(self.env_lines(), ["1 8110"])
        rec = json.loads((self.state_dir / "tests" / "T-001.json").read_text(encoding="utf-8"))
        self.assertEqual((rec["quick"]["files"], rec["quick"]["dirty"], rec["quick"]["head"]),
                         (["src/a/app.py"], [], self.slot_head()))

    def test_gate_rejection_is_committed_on_task_branch(self):
        self.use_gate(quick=ENV_QUICK)
        self.gate_modes("fail", "fail")
        self.ws_start("T-001")
        main_head = self.head()
        self.work()
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out["status"], out["source"]), (0, "changes", "hteam"), out)
        root = self.slot_root(1)
        self.assertEqual(self.git_at(root, "log", "-1", "--format=%s").strip(), "[T-001] review r1: REQUEST_CHANGES")
        self.assertTrue((root / "docs" / "reviews" / "T-001" / "r1.md").is_file())
        self.assertEqual(self.head(), main_head)

    def test_worker_hteam_test_from_slot(self):
        self.use_gate(quick=ENV_QUICK)
        self.ws_start("T-001")
        root = self.slot_root(1)
        self.work()
        code, out = self.hteam("test", "T-001", as_=None, cwd=root)  # 워커가 슬롯에서 shim 처럼 부른다(--root 없이)
        self.assertEqual((code, out["status"], out["files"]), (0, "passed", ["src/a/app.py"]), out)
        self.assertEqual(self.gate_calls()[-1]["cwd"], str(root))
        self.assertEqual(self.env_lines(), ["1 8110"])
        self.assertTrue((self.state_dir / "tests" / "T-001.json").is_file())  # 기록은 메인 상태(설계 5.7 7단계)
        self.assertFalse((root / ".herdr-team" / "state" / "tests").exists())

    def test_fix_round_stays_in_slot(self):
        self.ws_start("T-001")
        root = self.slot_root(1)
        self.work()
        self.hteam("review", "T-001")
        self.act_review("T-001", "REQUEST_CHANGES")
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual(out["status"], "changes", out)
        code, out = self.hteam("fix", "T-001")
        self.assertEqual((code, out["status"], out["round"]), (0, "working", 2), out)
        self.assertEqual(self.task_state("T-001")["rounds"][-1]["round_base"], self.slot_head())
        text = self.round_spec(n=2)
        self.assertIn(SECTION.format(root=root, tid="T-001", port="8110"), text)
        self.assertIn("`docs/reviews/T-001/r1.md` 리뷰를 읽고 막는 지적", text)  # 이전 리뷰는 슬롯에만 있다
        row = self.dispatch_row(out["dispatch"])
        self.assertEqual((row["cwd"], json.loads(row["env"])["HTEAM_SLOT"]), (str(root), "1"))
        self.assertEqual((self.record(1)["state"], self.record(1)["task"]), ("busy", "T-001"))


class PlaceTest(TeamCase):
    """crew.place 의 0(설계 5.9.4): worktree 모드의 작업 공간 직무는 늘 임시 워커다."""

    def test_workspace_role_is_always_temp(self):
        self.init_project(BASE_CONFIG)
        p = Project(self.proj)
        ws = config.build(tomllib.loads(CREW_CONFIG + '\n[workspace]\nmode = "worktree"\n'))
        self.assertEqual(crew.place(p, ws, "developer", "claude"), {"kind": "temp", "crew": None})
        self.assertEqual(crew.place(p, ws, "planner", "claude")["kind"], "crew")  # 작업 공간 직무가 아니면 그대로
        shared = config.build(tomllib.loads(CREW_CONFIG))
        self.assertEqual(crew.place(p, shared, "developer", "claude")["kind"], "crew")


class SharedRegressionTest(TeamCase):
    """회귀(헤더 "기본값"): [workspace] 가 없으면 horch 에 --env 가 없고 --cwd 는 프로젝트 루트, 상태에 workspace 가 없다."""

    config_text = BASE_CONFIG

    def test_shared_start_and_review_unchanged(self):
        self.init_project(self.config_text)
        self.setup_run()
        self.write_spec("T-001")
        code, out = self.hteam("start", "T-001")
        self.assertEqual((code, out["status"]), (0, "working"), out)
        row = self.dispatch_row(out["dispatch"])
        self.assertEqual((row["cwd"], row.get("env")), (str(self.proj), None))
        st = self.task_state("T-001")
        self.assertNotIn("workspace", st)
        self.assertEqual(st["rounds"][0]["round_base"], self.head())
        self.assertFalse((self.state_dir / "slots.json").exists())
        spec = (self.state_dir / "tasks" / "T-001" / "r1-work.md").read_text(encoding="utf-8")
        self.assertNotIn("## 작업 공간", spec)
        self.assertNotIn("이 태스크는 슬롯 worktree", spec)
        code, out = self.act_work("T-001")
        self.assertEqual(code, 0, out)
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out["status"]), (0, "reviewing"), out)
        rrow = self.dispatch_row(self.attempt("T-001")["dispatch"])
        self.assertEqual((rrow["cwd"], rrow.get("env")), (str(self.proj), None))
        prompt = (self.state_dir / "tasks" / "T-001" / "r1-review-a1.md").read_text(encoding="utf-8")
        self.assertNotIn("이 태스크는 슬롯 worktree", prompt)
        self.assertIn("- 이전 리뷰: 없음\n\n## 리뷰 대상 커밋", prompt)


class SharedModeTableTest(SharedRegressionTest):
    """mode = "shared" 를 적고 env 를 둬도 같다(설계 4.1: shared 면 나머지 키는 검사만 하고 쓰지 않는다)."""

    config_text = BASE_CONFIG + '\n[workspace]\nmode = "shared"\nslots = 3\n\n[workspace.env]\nHT_PORT = "81{slot}0"\n'


class DrivePrepareTest(EventCase):
    """관제의 준비 자식(설계 5.10.3 끝 두 문단, 8.8·8.11): slot_step 이 preparing 예약마다 `hteam slot prepare T`(키
    slot:<N>)를 띄우고, 거둘 때 성공이면 start-ready 가 띄우고 실패면 decide workspace_failed 다."""

    config = WS_CONFIG

    def hold_slot(self, n: int):
        """다른 프로세스가 슬롯 잠금을 쥔다(앞 관제가 남긴 준비 자식처럼). release() 가 놓는다."""
        path = self.state_dir / "slots" / f"slot-{n}.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen([sys.executable, "-c", HOLD_SLOT, str(path)], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, text=True)

        def release() -> None:
            if not proc.stdin.closed:
                proc.stdin.close()
            proc.wait(timeout=30)
            if not proc.stdout.closed:
                proc.stdout.close()

        self.addCleanup(release)
        self.assertEqual(proc.stdout.readline().strip(), "held")
        return release

    def test_slot_step_prepares_then_start_ready_launches(self):
        code, out = self.hteam("start", "T-001")
        self.assertEqual((code, out.get("reason")), (0, "slot_setup"), out)
        self.d.slot_step()
        self.assertEqual(self.d.jobs["slot:1"]["args"], ["slot", "prepare", "T-001"])
        self.d.slot_step()  # 그 키의 자식이 있으면 또 띄우지 않는다
        self.assertEqual(list(self.d.jobs), ["slot:1"])
        self.wait_jobs()
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["workspace"]["slot"]), ("working", 1))
        for line in ("slot-1 T-001 잡기 preparing", "slot-1 T-001 준비 시작", "slot-1 T-001 준비 ready",
                     "slot-1 T-001 사용 busy"):
            self.assertEqual(self.logged(line), 1, line)
        self.assertEqual(self.decides(), [])

    def test_live_prepare_child_is_waited_then_restarted(self):
        self.hteam("start", "T-001")
        release = self.hold_slot(1)
        self.d.slot_step()
        self.assertEqual(self.d.jobs, {})  # 다른 준비 자식이 산다(슬롯 잠금): 기다린다
        release()
        self.d.reconcile()  # 재확인이 준비를 다시 띄운다(관제가 준비 중에 죽었다, 5.10.3 끝 문단)
        self.assertIn("slot:1", self.d.jobs)
        self.wait_jobs()
        self.assertEqual(self.task_state("T-001")["status"], "working")

    def test_dirty_new_slot_decides_without_task_and_takes_next_slot(self):
        top = self.slot_root(1)
        top.parent.mkdir(parents=True, exist_ok=True)
        self.git("worktree", "add", "-q", "--detach", str(top), "HEAD")
        (top / "junk.txt").write_text("남은 파일\n", encoding="utf-8")
        self.hteam("start", "T-001")
        self.d.slot_step()
        self.wait_jobs()
        dec = self.decides()
        self.assertEqual([(e["kind"], e["task"], e["detail"]) for e in dec],
                         [("workspace_failed", None, {"kind": "slot_dirty", "slot": 1, "files": ["junk.txt"],
                                                      "task": "T-001"})])
        self.assertEqual(dec[0]["commands"], ["hteam slot reset 1"])
        self.assertTrue(dec[0]["summary"].startswith("slot-1 폴더에 커밋 안 된 변경이 있어 T-001 를 준비하지 않았다"), dec[0])
        slots = self.slots()["slots"]
        self.assertEqual((slots["1"]["state"], slots["1"]["task"]), ("dirty", None))
        self.assertEqual((slots["2"]["state"], slots["2"]["task"]), ("preparing", "T-001"))  # 거둔 뒤 start-ready 가 다음 슬롯
        self.assertNotIn("decide", self.task_state("T-001"))
        self.assertEqual(self.logged("slot-1 T-001 준비 slot_dirty"), 1)

    def test_branch_exists_decides_on_task(self):
        self.git("branch", "herdr/T-001")
        self.hteam("start", "T-001")
        self.d.slot_step()
        self.wait_jobs()
        dec = self.decides()
        self.assertEqual([(e["kind"], e["task"], e["detail"], e["commands"]) for e in dec],
                         [("workspace_failed", "T-001", {"kind": "branch_exists", "slot": 1, "branch": "herdr/T-001"},
                           ["hteam start T-001"])])
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["rounds"], st["decide"]), ("launch_failed", [], dec[0]["id"]))
        # 슬롯을 쥐지 않은 작업 공간 태스크의 fix 는 상태를 바꾸기 전에 거부한다(메인 폴더에서 워커를 띄우지 않는다, Rules 12)
        code, out = self.hteam("fix", "T-001", "--note=다시 한다")
        self.assertEqual((code, out["error"]["code"], out["error"]["hint"]), (3, "slot_not_held", "hteam start T-001"), out)
        self.assertEqual(self.task_state("T-001"), st)
        self.assertFalse([c for c in self.hc_calls() if c[:1] == ["run"]])
        self.git("branch", "-D", "herdr/T-001")  # 사용자가 남은 브랜치를 지웠다. start 는 지금처럼 슬롯을 다시 잡는다
        code, out = self.hteam("start", "T-001")
        self.assertEqual((code, out["status"], out["reason"]), (0, "waiting", "slot_setup"), out)
        self.assertEqual((self.slots()["slots"]["1"]["state"], self.slots()["slots"]["1"]["task"]), ("preparing", "T-001"))

    def test_decide_files_point_at_the_slot_copy(self):
        # 병합 전 보고서는 슬롯에만 있다. decide files 는 메인이 열 수 있는 슬롯 경로다(Rules 13, Codex 계획 리뷰 r1)
        self.hteam("start", "T-001")
        self.d.slot_step()
        self.wait_jobs()
        did = self.work_dispatch("T-001")
        code, out = self.act_work("T-001", outcome="failed")
        self.assertEqual(code, 0, out)
        self.d.handle(self.done_msg(did, "failed", summary="빌드가 안 된다"))
        (e,) = self.decides()
        report = ".herdr-team/state/slots/slot-1/docs/tasks/T-001/report.md"
        self.assertEqual((e["kind"], e["files"]), ("worker_failed", [".herdr-team/tasks/T-001.md", report]))
        self.assertTrue((self.proj / report).is_file())
        self.assertFalse((self.proj / "docs/tasks/T-001/report.md").exists())


class DriveSetupFailTest(EventCase):
    """setup 실패(설계 5.10.3 의 4): 슬롯 free, 태스크 launch_failed(라운드 없음), decide workspace_failed(setup_failed, 로그
    끝). 그 decide 가 열린 동안 start-ready 는 다시 띄우지 않는다. 메인의 start 는 다시 예약한다."""

    config = SETUP_FAIL_CONFIG

    def test_setup_failure_decides_once_and_blocks_start_ready(self):
        self.hteam("start", "T-001")
        self.d.slot_step()
        self.wait_jobs()
        dec = self.decides()
        self.assertEqual(len(dec), 1, dec)
        e = dec[0]
        self.assertEqual((e["kind"], e["task"], sorted(e["detail"])), ("workspace_failed", "T-001",
                                                                       ["exit", "kind", "log", "slot", "status"]))
        self.assertEqual((e["detail"]["kind"], e["detail"]["slot"], e["detail"]["status"], e["detail"]["exit"]),
                         ("setup_failed", 1, "failed", 3))
        self.assertTrue(e["detail"]["log"].startswith(".herdr-team/state/slots/logs/slot-1-setup-"), e)
        self.assertEqual(e["files"], [e["detail"]["log"]])
        self.assertIn("설치 실패", e["tail"])
        self.assertTrue(e["summary"].startswith("slot-1 setup 이 failed(exit 3)로 끝났다."), e)
        self.assertEqual(e["commands"], ["hteam start T-001"])
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["rounds"], st["decide"]), ("launch_failed", [], e["id"]))
        self.assertEqual(self.slots()["slots"]["1"]["state"], "free")
        self.assertEqual(self.logged("slot-1 T-001 준비 setup_failed"), 1)
        code, out = self.hteam("fix", "T-001", "--note=다시 한다")  # 슬롯 없이 메인 폴더에서 띄우지 않는다(Rules 12)
        self.assertEqual((code, out["error"]["code"]), (3, "slot_not_held"), out)
        self.assertEqual(self.task_state("T-001"), st)
        self.assertFalse([c for c in self.hc_calls() if c[:1] == ["run"]])
        res = self.d.start_ready()  # 라운드 없는 launch_failed 를 곧바로 다시 띄우지 않는다(열린 decide)
        self.assertEqual([(w["task"], w["reason"]) for w in res["waiting"]], [("T-001", "decide")])
        self.d.slot_step()
        self.assertEqual(self.d.jobs, {})
        self.assertEqual(len(self.decides()), 1)
        code, out = self.hteam("start", "T-001")  # 사용자가 setup 을 고친 뒤 메인이 다시 시작한다: 처음처럼 예약하고 기다린다
        self.assertEqual((code, out["status"], out["reason"]), (0, "waiting", "slot_setup"), out)
        self.assertEqual((self.slots()["slots"]["1"]["state"], self.slots()["slots"]["1"]["task"]), ("preparing", "T-001"))
        self.d.slot_step()  # decide 가 열린 동안 관제는 그 태스크를 자동으로 다루지 않는다(메인 규칙: 처리한 뒤 answer 로 닫는다)
        self.assertEqual(self.d.jobs, {})
        self.answer(e["id"])
        self.d.slot_step()
        self.assertEqual(self.d.jobs["slot:1"]["args"], ["slot", "prepare", "T-001"])


if __name__ == "__main__":
    unittest.main()
```

`DECIDE_KINDS` 를 통째로 고정한 지금 시험(Task 5 가 그 뒤에 `merge_conflict` 를 더한다):

**Edit** `herdr-team/tests/test_drive.py`

```python
                                              "unknown_regression", "token_update"))
```

```python
                                              "unknown_regression", "token_update", "workspace_failed"))
```

- [ ] **Step 2: 실패 확인**

Run: `cd herdr-team && python3 -m unittest tests.test_workspace_flow tests.test_drive 2>&1 | tail -5`
Expected: `Ran 57 tests` / `FAILED (failures=17, errors=10)`. 대표 메시지: `AssertionError: Tuples differ: (0, 'working', None) != (0, 'waiting', 'slot_setup')`(`ws_start` 의 첫 start 가 지금처럼 워커를 띄운다, 11건), `KeyError: 'reason'`(4건)·`KeyError: 'error'`, `AttributeError: 'Drive' object has no attribute 'slot_step'`(5건. 준비 실패 뒤 fix 거부·decide files 의 슬롯 경로 시험도 여기서 멈춘다), `argument cmd: invalid choice: 'slot'`, `{'kind': 'crew', …} != {'kind': 'temp', 'crew': None}`, `Tuples differ: ('wor[109 chars]aps', 'unknown_regression', 'token_update') != (…, 'workspace_failed')`(test_drive). HEAD 에 공유 시험 도구(Task 3 의 helpers 편집 셋)와 이 태스크의 Step 1 블록만 적용한 트리에서 쟀다(Task 1–3 구현 없음). 회귀 시험 둘(`SharedRegressionTest`·`SharedModeTableTest`)은 이 단계에서도 통과한다. 계획 작성 때 Task 1·3 의 시범 구현 위에 이 태스크의 시범 구현(계획에 넣지 않았다)으로 이 56개가 `OK` 인 것을 확인했다.

- [ ] **Step 3: 구현**

Rules 1–11 과 Interfaces 대로 `crew.py`·`tasks.py`·`workspace.py`·`dispatch.py`·`review.py`·`testgate.py`·`compose.py`·`drive.py` 를 고친다. git 은 `gitio.py` 로만, horch 는 `horch.py`·`dispatch.py` 로만 부른다. `p.root` → `p.work_root` 바꾸기는 Interfaces 의 "작업 루트에서 하는 것" 목록만 한다(상태·로그·확정 기록·자식의 `--root` 는 그대로). 템플릿은 아래 Edit 하나다(`util.fill` 은 모르는 자리를 KeyError 로 내므로 compose 가 `workspace` 를 넘기는 구현과 같이 바꾼다. Task 7 과 같은 까닭으로 Step 1 이 아니라 여기 둔다):

**Edit** `herdr-team/templates/review-prompt.md`

```markdown
- 이전 리뷰: {{prior}}{{request}}
```

```markdown
- 이전 리뷰: {{prior}}{{request}}{{workspace}}
```

- [ ] **Step 4: 통과 확인**

Run: `cd herdr-team && python3 -m unittest tests.test_workspace_flow tests.test_workspace tests.test_drive 2>&1 | tail -3` 그다음 `cd herdr-team && python3 -m unittest tests.test_start tests.test_review tests.test_testgate tests.test_drive_events tests.test_crew tests.test_lifecycle 2>&1 | tail -3`(작업 루트 바꾸기가 shared 경로를 바꾸지 않았는지, 10분 안팎)
Expected: 둘 다 `OK`.

- [ ] **Step 5: 정적 확인과 커밋**

```bash
python3 - <<'PY'
import ast, pathlib
for f in ["herdr-team/lib/hteam/crew.py", "herdr-team/lib/hteam/tasks.py", "herdr-team/lib/hteam/workspace.py",
          "herdr-team/lib/hteam/dispatch.py", "herdr-team/lib/hteam/review.py", "herdr-team/lib/hteam/testgate.py",
          "herdr-team/lib/hteam/compose.py", "herdr-team/lib/hteam/drive.py", "herdr-team/tests/helpers.py",
          "herdr-team/tests/test_workspace_flow.py", "herdr-team/tests/test_drive.py"]:
    ast.parse(pathlib.Path(f).read_text(encoding="utf-8"), feature_version=(3, 11))
PY
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews'
git add -- herdr-team/lib/hteam herdr-team/templates/review-prompt.md herdr-team/tests/helpers.py herdr-team/tests/test_workspace_flow.py herdr-team/tests/test_drive.py
git commit -m "feat(herdr-team): 작업 공간 흐름 1(슬롯 예약·준비 대기·busy, horch --cwd·--env, 작업 공간 절, 슬롯 안의 리뷰·관문, 준비 자식·workspace_failed)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/lib/hteam herdr-team/templates/review-prompt.md herdr-team/tests/helpers.py herdr-team/tests/test_workspace_flow.py herdr-team/tests/test_drive.py
```

Expected: ast 오류 없음, grep 빈 출력. 구현자는 여기서 멈춘다(컨트롤러가 `scripts/codex-review.sh commit <sha>`).

---

### Task 5: 작업 공간 흐름 2 — accept 의 `--no-ff` 병합·충돌·거부, 기준 병합 라운드, 놓기, 준비 중 drop, 마무리 full 의 슬롯, `slot reset`, `status` 의 `workspace`

설계 5.10.6–5.10.8 과 6.4 의 7단계 줄을 만든다. 작업 공간 태스크의 accept 는 `approved` → 병합 → `done` 이다. 관제가 프로젝트 잠금과 git 잠금(`state/git.lock`) 안에서 메인 폴더의 기준 브랜치에 `git merge --no-ff -m "[T-xxx] merge: <제목>" herdr/T-xxx` 한다. 충돌이면 `git merge --abort` 와 그 성공을 확인한 뒤 태스크를 `changes` 로 두고 라운드 기록에 `merge_conflict`, 상태에 풀어야 할 기준 병합 `base_merge`, `base` 를 그 기준 sha 로 옮긴 뒤 decide `merge_conflict` 를 올린다. 거부(index 에 올린 변경, 병합이 덮을 커밋 안 된 파일, `index.lock`)는 상태를 바꾸지 않고 다음 재확인에 다시 하고, 10분 넘게 거부되면 `workspace_failed`(`merge_blocked`)를 한 번 올린다. 메인 폴더에 끝나지 않은 병합(`MERGE_HEAD`)이 있거나 메인 폴더 브랜치가 기준 브랜치가 아니면 시도하지 않고 바로 `workspace_failed`(`merge_blocked`·`base_moved`)다. 기준 병합 라운드는 사양의 작업 공간 절 둘째 줄이 병합 지시이고, 리뷰 시작이 그 기준을 부모로 가진 `[T-xxx]` 커밋을 보면 `base_merge` 를 지운다. 바뀐 파일·사전 검사·관문은 옮긴 base 와 태스크 브랜치의 차이만 본다. 병합 뒤와 drop 뒤에는 관제 자식 `hteam slot release T` 가 슬롯 잠금을 쥐고 teardown → 작업 트리 검사 → `git switch --detach` → (병합한 브랜치면) `git branch -d` → `free` 를 하고(슬롯에 끝나지 않은 병합이 있거나 버린 태스크 슬롯에 커밋 안 된 변경이 있으면 switch 하지 않고 `dirty`), 재확인이 끊긴 놓기를 잇는다. 준비가 끝나지 않은 예약은 drop 이 바로 푼다. worktree 모드의 마무리 full 은 빈 슬롯 하나에서 기준 HEAD 로 setup → full → teardown 을 한다(메인 폴더에서 시험을 돌리지 않는다). 메인 큐 명령 `hteam slot reset <N>` 은 `dirty` 이고 태스크 없는 슬롯만 `git reset --hard`·`git clean -fd` 뒤 `free` 로 쓴다. `hteam status` 는 worktree 모드에서만 `workspace` 를 보인다.

설계 5.10.9 의 기록만 한 한계(준비 중 drop 의 늦은 완료, 관제가 병합 커밋을 만든 뒤 태스크를 `done` 으로 쓰기 전에 죽음)는 고치지 않는다. 다만 이 계획에서는 준비가 끝나지 않은 예약을 drop 이 바로 지우므로(Rules 9) Task 3 의 준비 자식이 늦게 끝나도 슬롯 기록에 쓰지 않는다(Task 3 Rules 4).

**Files:**
- Modify: `herdr-team/lib/hteam/workspace.py`(`merge`, `release`, `reset`, `claim_final`·`free_final`, `status_view`, `releasable`, CLI `slot release`·`slot reset`), `herdr-team/lib/hteam/gitio.py`(merge·abort·`MERGE_HEAD`·unmerged·parents·reset·clean, `switch_detach` 의 commit), `herdr-team/lib/hteam/tasks.py`(accept 의 병합, drop 의 예약 풀기, fix 의 `base_merge`·`merge_resume`), `herdr-team/lib/hteam/review.py`(리뷰 시작의 `base_merge` 지우기, 병합 커밋의 바뀐 파일), `herdr-team/lib/hteam/compose.py`(기준 병합 줄), `herdr-team/lib/hteam/testgate.py`(worktree 모드의 `run_final`), `herdr-team/lib/hteam/drive.py`(`DECIDE_KINDS`, `accept_task`·`after_accept`·`merge_refused`, `release_step`, 놓기 자식 결과, `reconcile`·`reconcile_task`, `final_done`), `herdr-team/lib/hteam/queue.py`(`slot reset`), `herdr-team/lib/hteam/roles.py`(`DRIVE_ONLY_MESSAGE`), `herdr-team/lib/hteam/coord.py`(`status` 의 `workspace`)
- Test: `herdr-team/tests/test_workspace_merge.py`(새로), `herdr-team/tests/test_drive.py`·`herdr-team/tests/test_queue.py`(기대값 Edit)

**Interfaces:**
- Consumes: Task 2 의 `Config.workspace`(`on`, `covers`, `slots`, `teardown`), Task 3 의 `workspace.load`·`save`·`entry`·`held_by`·`folder`·`work_root`·`task_root`·`slot_env`·`slot_lock`·`slot_busy`·`run_hook`·`SLOT_DEFAULT`·`MARKER_REL`·`branch_of`, `gitio.current_branch`·`switch_detach`·`branch_exists`·`delete_branch`·`worktree_add`·`diff_names`·`head`·`dirty`, `paths.Project.git_lock`·`slots_dir`, `testgate.child_env`, Task 4 의 태스크 상태 `workspace = {slot, branch, base_branch, root, merge}`, 작업 루트의 리뷰(`target_commits` 등이 `workspace.task_root(p, st)` 에서 돈다), 작업 공간 절(사양 둘째 줄 "- 커밋은 이 브랜치에 한다. 병합·push·브랜치 바꾸기·rebase 는 하지 않는다. 리뷰가 승인하면 관제가 병합한다."), `testgate.execute(…, cwd=, env=)`, 관제의 준비 자식 키 `slot:<N>`(`["slot", "prepare", T]`), `DECIDE_KINDS` 의 `workspace_failed`, `ws_start`(공유 시험 도구), 6단계의 `state.project_lock`·`edit`·`move`, `util.flock`·`now`·`age_seconds`·`die_at`, `Drive.decide`·`log`·`progress`·`spawn`·`running`·`_fix_cmd`, `queue.route`·`recorded`·`EXECUTORS`.
- Produces:
  - `workspace.MERGE_BLOCKED_S = 600`. `merge(p, cfg, st) -> dict`(Rules 1–3): 호출자(`tasks.accept`)가 프로젝트 잠금을 쥔다. 이 함수가 `util.flock(p.git_lock)` 을 쥔다. 결과 `{"result": "merged", "sha": <병합 커밋>}` 또는 `{"result": "conflict", "base": <병합 직전 메인 HEAD>, "files": [<충돌 파일, 프로젝트 기준, 정렬>]}`. 거부는 예외(아래 셋, 상태를 바꾸지 않는다). `gitio` 는 모듈로 불러 `gitio.<함수>` 로 부른다(시험이 `gitio.merge_abort` 를 바꾼다).
  - 오류(exit 3, data 는 출력 최상위):
    - `merge_pending`: `<T> 병합이 거부됐다(관제가 다음 재확인에 다시 한다): <git 출력 첫 줄 200자>`, hint `메인 폴더의 index 에 올린 변경·커밋 안 된 파일·index.lock 을 확인한다`, data `{"kind": "merge_pending", "slot", "output": <git 출력 끝 600자>, "first": <이번이 첫 거부면 true>}`.
    - `merge_blocked`: `메인 폴더에 끝나지 않은 병합(MERGE_HEAD)이 있어 <T> 를 병합하지 않았다` 또는(abort 를 확인하지 못함) `<T> 병합 충돌을 되돌리지 못했다(git merge --abort 뒤에도 MERGE_HEAD 가 남았다)`, hint `사용자가 메인 폴더의 병합 상태를 정리한 뒤 관제가 다시 병합한다`, data `{"kind": "merge_blocked", "slot", "output"}`.
    - `base_moved`: `메인 폴더 브랜치가 <지금 브랜치 또는 "detached HEAD"> 라 <T> 를 기준 브랜치 <기준> 에 병합하지 않았다`, hint `메인 폴더를 기준 브랜치로 되돌릴지 사용자에게 묻는다`, data `{"kind": "base_moved", "slot", "branch": <지금 브랜치 또는 null>, "base_branch"}`.
  - `tasks.accept(…)` 결과: 병합하면 `{"task", "status": "done", "warnings", "merge": <sha>}`, 충돌이면 `{"task", "status": "changes", "warnings", "merge_conflict": {"base", "files"}}`(exit 0). 위 세 오류는 그대로 올라간다(exit 3). 작업 공간 태스크가 아니면 지금 그대로(`merge` 키 없음).
  - 태스크 상태: `merge_wait = {"since": <첫 거부 시각 UTC>, "asked": [<올린 workspace_failed 의 kind>]}`(거부 동안만, 병합·충돌이면 지운다), `base_merge`(기준 병합 라운드 동안), 라운드 기록 `merge_conflict = {"base", "files"}`, 새 라운드 기록 `base_merge`(그 라운드가 풀 sha)·`merge_resume`(true, 슬롯의 `MERGE_HEAD` 가 그 sha 일 때만). history 사건: 병합 `accept`(`merge: <sha>`), 충돌 `merge_conflict`(`base`, `files`).
  - `workspace.release(p, cfg, tid) -> dict`(Rules 7): 결과 `{"task", "slot": N | null, "state": "free"|"dirty"|null, "teardown": <run_hook 결과> | null, "branch_deleted": bool, "dirty": [<경로 앞 20개>]}`. `state: "dirty"` 면 `dirty` 는 슬롯의 `gitio.dirty(folder, ["."])`(끝나지 않은 병합이면 충돌 파일과 병합이 올린 파일도 든다)이고 `branch_deleted` 는 false 다. 그 태스크가 쥔 슬롯이 없으면 `{"task", "slot": null, "state": null, "teardown": null, "branch_deleted": false, "dirty": []}`(exit 0). 태스크가 `done`·`dropped` 가 아니면 exit 3 `task_open`(`<T> 는 <상태> 다. 슬롯은 병합하거나 버린 뒤에 놓는다`). 슬롯 잠금은 nowait(못 쥐면 Task 3 의 `slot_locked`).
  - `workspace.reset(p, cfg, n, *, request=None) -> dict`: 결과 `{"slot": N, "state": "free"}`. 오류: exit 2 `bad_slot`(`슬롯 번호는 1–<slots> 다: <값>`), exit 3 `slot_not_dirty`(`slot-<N> 은 <state>(<태스크 또는 "태스크 없음">)라 reset 하지 않는다(dirty 이고 태스크가 없을 때만)`), Task 3 의 `slot_locked`·`workspace_off`. 슬롯 기록에 `reset_request`(큐 요청 id)를 남긴다(재실행 막기).
  - `workspace.claim_final(p, cfg) -> tuple[int, str]`(프로젝트 잠금 안, `free` 이거나 `{"state": "busy", "task": null, "use": "final"}` 인데 잠금이 풀린 가장 작은 번호를 `{**SLOT_DEFAULT, "state": "busy", "use": "final", "base": <메인 HEAD>, "since"}` 로 쓰고 (번호, base)), 없으면 exit 3 `no_free_slot`(`빈 슬롯이 없다(slot-1–<slots> 을 모두 쓰는 중이다). 마무리 full 은 슬롯이 비면 다시 한다`). `free_final(p, n)`(그 기록을 `{**SLOT_DEFAULT, "since"}` 로).
  - `workspace.status_view(p, cfg) -> dict`: `{"mode": "worktree", "slots": [{"n", "state", "task", "branch"}]}`(1–`slots` 와 기록에 있는 번호, 번호순). `workspace.releasable(p) -> list[tuple[int, str]]`: 기록의 `task` 가 `done`·`dropped` 이고 기록이 `busy` 이거나 `ready` 인 `preparing` 인 (번호, 태스크).
  - CLI(`workspace.register` 의 `slot` 파서에 더한다): `hteam slot release T`(관제만: 밖이면 exit 5 `drive_only`, shared 면 Task 3 의 `workspace_off`), `hteam slot reset <N>`(큐 명령: 관제(와 자식)면 바로, 메인이면 `queue.route(p, "slot reset", {"slot": <int>}, …, check=<번호·모드 검사>)`. `<N>` 은 문자열로 받아 검사한다).
  - `gitio`: `merge_no_ff(root, branch, message) -> subprocess.CompletedProcess`(`git merge --no-ff -m <message> <branch>`, check 없이), `merge_head(root) -> str | None`(`git rev-parse -q --verify MERGE_HEAD`, 없으면 None. worktree 는 그 worktree 의 것), `unmerged(root) -> list[str]`(`git diff --name-only --diff-filter=U -z`, 최상위 기준), `merge_abort(root) -> None`(`git merge --abort`, 실패해도 예외를 내지 않는다. 확인은 부르는 쪽이 `merge_head` 로), `parents(root, sha) -> list[str]`, `reset_hard(root)`, `clean_untracked(root)`(`git clean -fd`, 무시된 파일은 남는다), `switch_detach(root, commit=None)`(Task 3 함수에 커밋 인자를 더한다: `git switch --detach [<commit>]`).
  - `review.changed_files(p, commits, base=None)`(`p` 는 Task 4 의 `workspace.view(p, st)`): `base` 가 있으면 대상 커밋 가운데 부모가 둘 이상인 커밋은 그 커밋의 바뀐 경로 가운데 `gitio.diff_names(p.work_root, base, "HEAD")` 에 든 것만 센다(Rules 6). 부르는 쪽(`review`·`testgate` 의 `changed_files`·`quick_files`·`code_head`)이 `st["base"]` 를 넘긴다.
  - `compose.workspace_section(cfg, st, rd=None)`(Task 4 함수에 `rd` 를 더한다. `work_spec` 이 만드는 라운드를 넘긴다): `BASE_MERGE_LINE = "- 이 라운드는 기준 커밋 `{sha}` 를 이 브랜치에 병합한다: `git merge --no-ff --no-commit {sha}` 뒤 충돌을 풀고 푼 파일을 `git add -- <파일>` 한다. `git diff --cached --name-only` 가 병합과 푼 파일만 담는지 본 뒤 경로를 지정하지 않은 `git commit -m \"[{tid}] 기준 병합: {sha7}\"` 로 커밋한다(병합 중에는 git 이 경로 지정 커밋을 받지 않는다. 이 커밋만 작업 규칙 5.5 의 경로 지정 예외다). 그 밖의 병합·rebase·push 는 하지 않는다."`(`\"` 는 Python 문자열 안의 큰따옴표), `MERGE_RESUME = "앞 워커가 시작한 병합이 남아 있다. 이어서 푼다."`. 라운드 기록에 `base_merge` 가 있으면 작업 공간 절 둘째 줄을 `BASE_MERGE_LINE` 으로 바꾸고, `merge_resume` 이면 그 줄 끝에 빈칸 하나와 `MERGE_RESUME` 을 붙인다.
  - 관제: `DECIDE_KINDS` 끝에 `merge_conflict`(Task 4 의 `workspace_failed` 뒤). `Drive.merge_refused(tid, exc)`, `Drive.release_step()`, `Drive._release_done(n, tid, code, data)`(data 는 자식 stdout 의 마지막 JSON 객체). `reap_jobs` 의 `slot:<N>` 갈래(Task 4)는 자식 인자의 둘째가 `release` 면 `_release_done`, 아니면 Task 4 의 `_slot_done` 이다(격리 키 `job:slot:<N>` 그대로).
  - decide(설계 8.10 모양):
    - `merge_conflict`: summary `기준 브랜치 <기준> 에 병합하다 충돌했다(<n>개 파일: <앞 다섯, 쉼표>). 되돌렸다`, `detail {"base", "files"}`, commands `[self._fix_cmd(st, "<충돌을 어떻게 풀지 사용자 지시>"), "hteam drop <T>"]`(상한이면 `--force-round` 가 붙는다).
    - `workspace_failed`(병합 쪽): summary 는 위 오류 message, `detail {"kind", "slot", …오류 data}`, commands 없음(설계 7.7: 사용자에게 묻는다).
  - drive.log(설계 8.11): `<T> 병합 <sha 7자>`, `<T> 병합 거부: <git 출력 첫 줄 120자>`(첫 거부만), `<T> 병합 충돌: <파일 앞 다섯, 쉼표>`, `<T> 병합 못 함(<kind>): <message 120자>`, `slot-<N> <T> 놓기 시작`, `slot-<N> <T> 놓기 <free|dirty>`(teardown 이 passed 가 아니면 뒤에 ` (teardown <status>)`), `slot-<N> <T> 놓기 실패: <code>: <message 120자>`, `마지막 전체 테스트: 빈 슬롯이 없어 다음 확인 때 다시 한다`.
  - progress: teardown 실패 `slot-<N> <T> teardown 이 <status>(exit <exit>)로 끝났다(놓기는 마쳤다). 로그: <log>`, dirty `slot-<N> 에 커밋 안 된 변경이 남아 dirty 로 두었다(<T> 를 버렸다): <앞 다섯, 쉼표>. 사용자가 버려도 된다고 하면 hteam slot reset <N>`(태스크가 `done` 이면 괄호가 `<T> 는 병합했다`, 바뀐 경로가 없으면 `<앞 다섯>` 자리가 `git switch 가 거부했다`).
  - `queue.QUEUE_COMMANDS` 에 `"slot reset"`(`"agent reset"` 다음), `EXECUTORS["slot reset"]`, `recorded` 의 `slot reset`(그 슬롯 기록의 `reset_request` 가 요청 id 면 `{"recovered": true, "slot": N, "state": <기록 state>}`). `roles.DRIVE_ONLY_MESSAGE` 의 목록 `…, agent reset, slot reset, test-confirm 이다`.
  - `hteam status`: `cfg.workspace.on` 일 때만 `workspace`(`status_view`). `slots.json` 을 읽지 못하면 `workspace: {"mode": "worktree", "slots": []}` 와 `warnings` 의 `작업 공간 기록: <message>`(status 는 실패하지 않는다).
  - `hteam test --full`(worktree 모드): 결과·`final.json` 의 `full` 에 `slot`. `head` 는 그 슬롯에서 돌린 커밋(메인 HEAD). setup 실패면 exit 1 `setup_failed`(Task 3 과 같은 data, `slot`·`kind`), 빈 슬롯이 없으면 exit 3 `no_free_slot`.
  - 시험용 죽음 지점: `slot_release_teardown`(teardown 뒤, detach 전), `slot_release_detached`(detach·브랜치 정리 뒤, 기록 전).
- 잠금: 병합은 프로젝트 → git → 태스크(`tasks.accept` 의 지금 순서 안). 놓기·reset·마무리 full 은 슬롯 잠금(nowait) → 프로젝트 잠금(기록을 고치는 짧은 구간). 프로젝트 잠금을 쥔 쪽(`claim_final`, 관제의 `release_step`)은 슬롯 잠금을 비차단으로만 본다(`slot_busy`).

**Rules:**

1. 병합 위치(6.4 의 7단계 줄): `tasks.accept` 는 지금 순서(확인 → 살아 있는 워커 거부 → 작업 Dispatch 정리) 뒤 프로젝트 잠금 안에서, 상태 쓰기 전에 `st.get("workspace")` 이고 `workspace.merge` 가 아직 없는(`merge` 가 null) 태스크면 `workspace.merge(p, cfg, cur)` 를 부른다. 작업 공간 직무는 승인 직무가 될 수 없으므로(4.2) 이 태스크의 `to` 는 늘 `done` 이다. 관제 판정 경로(`Drive.accept_task`)·큐 accept(`queue._x_accept`)·관제 안의 CLI accept 가 모두 이 한 곳을 지난다. 성공 결과면 같은 태스크 잠금 쓰기에서 `workspace.merge = sha`, `merge_wait` 를 지우고 `done`(사건 `accept`, `merge`). 이 쓰기 직후가 병합 성공 지점이다(Task 8 은 관제 쪽 `Drive.after_accept` 의 `res["merge"]` 갈래에 Redmine `merged` 사건을 둔다).
1a. 병합 뒤의 작업 루트(Task 4 노트): `workspace.task_root(p, st)` 는 `st["workspace"]["merge"]` 가 있으면 `p.root` 다(Task 3 함수에 갈래를 더한다). 병합한 태스크의 보고서·리뷰 파일은 병합 커밋으로 기준 브랜치에 있고, 슬롯은 놓은 뒤 다른 태스크가 다시 쓴다. 그래서 accept 뒤의 읽기(묶음 후속 `followups`, 관제의 보고서·리뷰 파일 읽기, Redmine 노트의 아티팩트 URL)는 메인 폴더를 본다.
2. `merge`(5.10.6): git 잠금을 쥔다. ① `gitio.merge_head(p.root)` 가 있으면 시도하지 않고 `merge_blocked`. ② `gitio.current_branch(p.root) != ws["base_branch"]` 면 `base_moved`. ③ `base = gitio.head(p.root)`, `gitio.merge_no_ff(p.root, ws["branch"], f"[{T}] merge: {사양 제목}")`. exit 0 이면 `merged`(sha 는 새 HEAD). ④ exit 0 이 아니고 `merge_head` 가 생겼으면 충돌: 충돌 파일을 `unmerged` 로 모으고 `merge_abort` 한 뒤 `merge_head` 가 아직 있으면 `merge_blocked`(abort 실패), 없으면 `conflict`. ⑤ 그 밖(병합이 시작되지 않았다: index 에 올린 변경, 덮을 커밋 안 된 파일, `index.lock`)은 `merge_pending`. 출력은 stderr·stdout 을 합친 글이다. 메시지 문구를 해석하지 않는다(로캘을 타지 않게 `MERGE_HEAD` 로 가른다).
3. 거부 기록: `tasks.accept` 는 `merge` 의 세 오류를 받으면 태스크 잠금 안에서 `merge_wait` 가 없을 때만 `{"since": now(), "asked": []}` 를 쓰고(상태·라운드는 바꾸지 않는다) data 에 `first`(이번에 만들었는지)를 더해 그대로 올린다.
4. 충돌 전이(5.10.6): `conflict` 결과면 같은 태스크 잠금 쓰기에서 라운드 기록 `merge_conflict = {base, files}`, `base_merge = base`, `base = base`, `merge_wait` 지우기, `approved` → `changes`(사건 `merge_conflict`). `workspace.merge` 는 null 그대로, 슬롯은 태스크가 쥔 채다(`busy`). 결과 `{"status": "changes", "merge_conflict": {…}}`.
5. 관제(8.6·8.10): `accept_task` 는 `merge_pending`·`merge_blocked`·`base_moved` 를 관제 절차 실패로 올리지 않고 `merge_refused(tid, exc)` 로 넘긴다: `merge_pending` 이면 `first` 일 때만 로그 `<T> 병합 거부: …`, `merge_wait.since` 가 `MERGE_BLOCKED_S` 보다 오래됐고 `asked` 에 `merge_blocked` 가 없으면 decide `workspace_failed`(kind `merge_blocked`, summary `<T> 병합이 10분 넘게 거부됐다: <output 첫 줄>`, detail 에 `output`)를 올리고 `asked` 에 더한다(decide 를 쓴 뒤 `asked` 를 저장한다. 그 사이 중단되면 다음 재확인이 같은 decide 를 한 번 더 올릴 수 있지만 잃지 않는다, Codex 계획 리뷰 r1). `merge_blocked`·`base_moved` 는 로그 `<T> 병합 못 함(<kind>): …` 와, `asked` 에 그 kind 가 없을 때만 decide `workspace_failed`(summary 는 오류 message) 한 번. 태스크는 `approved` 그대로라 decide 가 열린 동안 재확인이 accept 를 다시 하지 않고(지금 `open_decide` 규칙), 답한 뒤 재확인(8.7 표의 `approved` → accept)이 다시 병합한다. `after_accept` 는 `res["merge"]` 면 로그 `<T> 병합 <sha 7자>`, `res["merge_conflict"]` 면 로그 `<T> 병합 충돌: …` 와 decide `merge_conflict` 를 올린 뒤 지금 처리(직무별 다음 자리, start-ready)를 하고, 끝에 `release_step()`. `reconcile_task` 의 `changes` 갈래는 라운드 기록에 `merge_conflict` 가 있으면 자동 fix 를 하지 않는다: 이 충돌의 decide 가 outbox 에 없으면(지금 있는 `outbox.read_outbox(p)` 에 `type == "decide"`·`kind == "merge_conflict"`·`task == T`·`detail == 라운드 기록의 merge_conflict` 인 항목이 없으면) decide `merge_conflict` 를 올리고(병합 충돌 전이 뒤 decide 전에 관제가 죽은 경우), 있으면 그대로 둔다(메인이 fix·drop 한다). `decide_round == round` 로 가리지 않는다: 그 표시는 같은 라운드의 다른 decide(답한 `worker_question` 등)에도 남는다(Codex 계획 리뷰 r1). 새 상태 필드는 쓰지 않는다.
6. 기준 병합 라운드(5.10.6): `tasks.fix` 가 새 라운드 기록을 쓸 때(지금 잠금 안) 태스크 상태에 `base_merge` 가 있으면 라운드에 `base_merge` 를 옮기고, 그 슬롯의 `gitio.merge_head(<작업 루트>) == base_merge` 면 `merge_resume: true` 를 쓴다. 사양은 Interfaces 의 `compose` 규칙으로 만든다(같은 라운드 복구는 저장된 사양 그대로). 리뷰 시작(6.1, `--retry` 가 아닌 새 시도. 사전 검사보다 먼저): 상태에 `base_merge` 가 있고 대상 커밋 가운데 `gitio.parents(<작업 루트>, sha)` 에 그 sha 가 든 커밋이 있으면 태스크 잠금 안에서 `base_merge` 를 지운다(사전 검사·관문 결과와 상관없다). 그래서 워커가 커밋 전에 죽어 새 라운드가 열려도 표시가 남아 같은 지시를 받는다. 바뀐 파일(`review.changed_files`, 그것을 쓰는 사전 검사·관문의 quick 파일·`code_head`)은 부모가 둘 이상인 커밋에서 `diff_names(<작업 루트>, st["base"], "HEAD")` 에 든 경로만 센다(설계 "지금 기준과 태스크 브랜치의 차이만"). 사전 검사의 owns 밖 판정은 지금처럼 `differs(base, HEAD)` 라 다른 태스크·사람이 기준에 넣은 변경은 잡히지 않는다.
7. 놓기(5.10.6, `workspace.release`): 프로젝트 잠금 안에서 `held_by` 로 그 태스크의 슬롯을 찾는다(없으면 할 일 없음). 태스크가 `done`·`dropped` 가 아니면 `task_open`. 슬롯 잠금(nowait)을 쥔 뒤 기록이 아직 그 태스크의 것인지 다시 본다. ① `cfg.workspace.teardown` 이 있으면 `run_hook(p, cfg, n, "teardown", tid)`(실패해도 계속, 결과를 출력에. 죽음 지점 `slot_release_teardown`). ② 작업 트리 검사(switch 보다 먼저, Codex 계획 리뷰 r1): 슬롯 폴더에 끝나지 않은 병합(`gitio.merge_head(folder)`, 예: 기준 병합 라운드 도중의 drop)이 있거나, 태스크가 `dropped` 이고 `gitio.dirty(folder, ["."])` 가 있으면 ⑤ 로 간다. git 은 병합 중 `switch` 를 거부하므로("cannot switch branch while merging") switch 를 먼저 하면 슬롯이 `busy` 로 남고 재확인이 같은 실패를 되풀이한다. ③ 깨끗하면 슬롯 폴더에서 `gitio.switch_detach(folder)`. 이 switch 가 실패해도(`git_failed`) ⑤ 로 간다(다시 시도하지 않는다). 태스크가 `done` 이고 `branch_exists` 면 메인 폴더에서 `delete_branch(p.root, branch)`(`-d`. 실패하면 `branch_deleted: false` 로 두고 계속). `dropped` 면 브랜치를 남긴다. 죽음 지점 `slot_release_detached`. ④ 프로젝트 잠금 안에서 기록을 다시 보고 `{**SLOT_DEFAULT, "since"}`(free. `setup_done` 은 null: teardown 했으니 다음 태스크가 setup 을 다시 한다). ⑤ 남기기: switch·브랜치 지우기를 하지 않고(브랜치·병합 상태·파일을 그대로 둔다) 프로젝트 잠금 안에서 기록을 `{**SLOT_DEFAULT, "state": "dirty", "since"}`(태스크 연결을 푼다)로 쓴다. 알림은 설계 5.10.6 "버린 태스크의 슬롯에 커밋 안 된 변경이 있으면 `dirty` 로 두고 progress 로 알린다" 그대로 Rules 8 의 progress(dirty) 한 번이다(기록이 태스크 없는 `dirty` 라 `releasable` 에 다시 들지 않는다). 정리는 메인이 사용자 확인 뒤 부르는 `slot reset <N>` 이다(Rules 11 의 `reset_hard` 가 `MERGE_HEAD` 도 지운다. git 2.50 에서 확인했다). 슬롯 폴더와 무시된 파일은 지우지 않는다. 다시 불러도 같은 결과로 잇는다(teardown 은 다시 돈다).
8. 관제의 놓기(8.8): `release_step()` 은 `workspace.releasable(p)` 의 (번호, 태스크)마다 `slot:<N>` 자식이 없고 `slot_busy` 가 아니면 `spawn(f"slot:{n}", ["slot", "release", T])` 와 로그 `slot-<N> <T> 놓기 시작`. `after_accept` 끝, 큐 `drop` 실행 뒤(`queue._x_drop` 이 결과를 돌려주기 전에 격리 `release:<T>` 로), 재확인의 태스크별 처리 뒤(격리 `slots`, `batches` 앞)에서 부른다. 그래서 놓기 도중 관제나 자식이 죽어도 다음 재확인이 잇는다(태스크가 `done`·`dropped` 인데 슬롯이 `busy`). 거두기(`_release_done`): exit 0 이면 로그 `slot-<N> <T> 놓기 <state>`, teardown 이 passed 가 아니면 progress(teardown 실패), `dirty` 면 progress(dirty). `slot_locked` 는 아무것도 하지 않는다(다음 재확인). 그 밖은 로그 `놓기 실패`.
9. drop(5.10.6·5.10.9): `tasks.drop` 의 마지막 전이(`_closing` 의 프로젝트 잠금 안)에서 그 태스크가 쥔 슬롯 기록이 `ready` 없는 `preparing` 이면 `{**SLOT_DEFAULT, "setup_done": <그대로>, "since"}` 로 바로 푼다(준비 자식을 기다리지 않는다. 늦게 끝난 자식은 Task 3 Rules 4 로 쓰지 않는다. 그 자식이 만든 브랜치·setup 결과는 남는다: 한계). `busy` 나 `ready` 인 `preparing` 은 그대로 두고 관제의 놓기(Rules 8)가 teardown 과 함께 놓는다. `slots.json` 을 읽지 못하면 drop 이 `bad_slots_file` 로 끝난다(엄격 읽기). Redmine `drop` 사건(Task 8)은 dropped 쓰기 직후다.
10. 마무리 full(5.10.7): `testgate.run_final` 은 `config.test_settings(p)`(Task 2 Rules 11. `hteam test --full` 은 `config.load` 를 부르지 않는다, 설계 4.2)의 `workspace.on` 이면 메인 폴더에서 돌리지 않는다. 아래의 `cfg` 는 그 `TestSettings` 다. `claim_final` → 그 슬롯 잠금(nowait) → 폴더가 없으면 `worktree_add(p.root, folder, base)`, 있으면 `switch_detach(folder, base)` → setup(있으면. 실패면 `free_final` 하고 `setup_failed`, teardown 은 돌리지 않는다: 준비와 같다) → full(`attempt` 를 `cwd=work_root(p, n)`, `env=slot_env(cfg, n)` 으로) → teardown(있으면, 결과는 쓰지 않는다) → `free_final`. 기록은 지금 꼴에 `head = base`, `head_moved`(끝날 때 메인 HEAD 가 다르면 그 sha), `dirty`(작업 루트 기준), `slot` 을 더한다. 빈 슬롯이 없으면 `no_free_slot`. 관제 `final_done`: exit 3 `no_free_slot` 이면 로그만 남기고 끝낸다(다음 재확인의 `finish_step` 이 다시 띄운다). exit 1 `setup_failed` 면 decide `workspace_failed`(task 없음, kind `setup_failed`, `tail`)를 올리고 지금 실패처럼 `final_failed`·`final_decide` 를 쓴다(답하기 전에는 다시 돌리지 않는다). shared 면 지금 그대로(메인 폴더).
11. `slot reset`(5.10.8): `reset` 은 모드 검사(shared 면 `workspace_off`) → 번호 검사(1–`slots` 의 정수 문자열, 아니면 `bad_slot`) → 슬롯 잠금(nowait) → 프로젝트 잠금 안에서 기록이 `dirty` 이고 `task` 가 없을 때만 슬롯 폴더에서 `reset_hard` 와 `clean_untracked` 를 한 뒤 `{**SLOT_DEFAULT, "since", "reset_request": request}`. 되돌릴 수 없으므로 메인은 사용자 확인 뒤에만 부른다(Task 9 의 메인 규칙). 큐 실행(`_x_slot_reset`)은 `request=req["id"]` 를 넘기고, `recorded` 는 그 슬롯 기록의 `reset_request` 로 복구한다.
12. status(5.10.8): 위 Interfaces. `[workspace]` 가 없거나 shared 면 키가 없다.
13. 회귀(헤더 "기본값"): shared 프로젝트의 accept 는 병합하지 않고(결과에 `merge` 없음, 메인 HEAD 에 병합 커밋 없음) `done`, 상태에 `workspace`·`merge_wait` 가 없다. `slots.json`·`state/slots/` 를 만들지 않는다. 마무리 full 은 메인 폴더(`slot` 없음). `slot reset`·`slot release` 는 `workspace_off`.

핵심 조각(그대로 옮기지 않아도 된다) — 병합과 충돌 전이(Rules 1–4):

```python
def merge(p, cfg, st: dict) -> dict:
    ws, tid = st["workspace"], st["id"]
    with flock(p.git_lock):
        if gitio.merge_head(p.root):
            raise _blocked(tid, ws, f"메인 폴더에 끝나지 않은 병합(MERGE_HEAD)이 있어 {tid} 를 병합하지 않았다", "")
        cur = gitio.current_branch(p.root)
        if cur != ws["base_branch"]:
            raise _base_moved(tid, ws, cur)
        base = gitio.head(p.root)
        proc = gitio.merge_no_ff(p.root, ws["branch"], f"[{tid}] merge: {specs.load(p, tid).title}")
        output = ((proc.stderr or "") + (proc.stdout or "")).strip()
        if proc.returncode == 0:
            return {"result": "merged", "sha": gitio.head(p.root)}
        if not gitio.merge_head(p.root):           # 병합이 시작되지 않았다: 거부(다시 시도한다)
            raise _pending(tid, ws, output)
        prefix = gitio.top_prefix(p.root)
        files = sorted(gitio.from_top(prefix, f) for f in gitio.unmerged(p.root))
        gitio.merge_abort(p.root)
        if gitio.merge_head(p.root):               # 되돌렸는지 확인한다(설계 5.10.6)
            raise _blocked(tid, ws, f"{tid} 병합 충돌을 되돌리지 못했다(git merge --abort 뒤에도 MERGE_HEAD 가 남았다)", output)
        return {"result": "conflict", "base": base, "files": files}

# tasks.accept 의 프로젝트 잠금 안
if cur_ws := st.get("workspace"):
    try:
        outcome = workspace.merge(p, cfg, st)
    except HteamError as exc:
        if exc.code in ("merge_pending", "merge_blocked", "base_moved"):
            with state.edit(p, tid) as cur:
                first = "merge_wait" not in cur
                cur.setdefault("merge_wait", {"since": now(), "asked": []})
            exc.data["first"] = first
        raise
with state.edit(p, tid, expect={st["status"]}) as cur:
    ...
    cur.pop("merge_wait", None)
    if outcome and outcome["result"] == "conflict":
        conflict = {"base": outcome["base"], "files": outcome["files"]}
        cur["rounds"][-1]["merge_conflict"] = conflict
        cur["base_merge"] = cur["base"] = outcome["base"]
        state.move(cur, "changes", "merge_conflict", **conflict)
    else:
        if outcome:
            cur["workspace"]["merge"] = outcome["sha"]
        state.move(cur, to, "accept", **({"merge": outcome["sha"]} if outcome else {}), **_req(request))
```

핵심 조각 — 관제의 거부 처리(Rules 5):

```python
def merge_refused(self, tid: str, exc: HteamError) -> None:
    kind = exc.code if exc.code != "merge_pending" else "merge_blocked"
    st = state.require(self.p, tid)
    wait = st.get("merge_wait") or {"since": now(), "asked": []}
    if exc.code == "merge_pending":
        if exc.data.get("first"):
            self.log(f"{tid} 병합 거부: {_first_line(exc.data.get('output'))[:120]}")
        if age_seconds(wait["since"]) <= workspace.MERGE_BLOCKED_S:
            return
        summary = f"{tid} 병합이 10분 넘게 거부됐다: {_first_line(exc.data.get('output'))}"
    else:
        self.log(f"{tid} 병합 못 함({exc.code}): {exc.message[:120]}")
        summary = exc.message
    if kind in wait["asked"]:
        return
    self.decide("workspace_failed", tid, summary, detail={**exc.data, "kind": kind})  # 먼저 알린다(잃지 않는다)
    with state.edit(self.p, tid) as cur:  # 그 뒤 표시. 그 사이 중단되면 다음 재확인이 한 번 더 알릴 수 있다(계획 끝 한계)
        cur.setdefault("merge_wait", wait)["asked"] = [*cur["merge_wait"].get("asked", []), kind]
```

- [ ] **Step 1: 실패하는 테스트 작성**

**Create** `herdr-team/tests/test_workspace_merge.py`

```python
"""작업 공간 흐름 2(7단계, 설계 5.10.6–5.10.8): accept 의 --no-ff 병합·충돌(merge_conflict, base_merge, base 이동)·거부
(merge_pending, 10분 뒤 workspace_failed merge_blocked)·MERGE_HEAD·base_moved, 기준 병합 라운드(사양 지시, base_merge 지우기,
기준 변경이 owns 밖·quick 에 섞이지 않음), 놓기(teardown → detach → 브랜치 지우기 → free, 버린 태스크의 dirty, 재확인의 이어
하기), 준비 중 drop, slot reset(큐 명령), 마무리 full 의 슬롯, status 의 workspace, shared 회귀.

실제 git worktree 를 시험 임시 저장소 안에 만든다. 관제는 이 프로세스 안(make_drive)이고 놓기 자식은 실제 hteam 하위 프로세스다
(설계 8.8)."""
import json
import subprocess
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from tests.helpers import BASE_CONFIG, WS_CONFIG, TeamCase
from hteam import gitio, queue, state, workspace
from hteam.paths import Project

# setup·teardown 도우미(시험 폴더 밖 $OUT_DIR): 슬롯·작업 루트를 남긴다. setup 은 무시된 폴더(node_modules)에 표시를 쌓는다
SETUP_SH = """[ -f "$OUT_DIR/setup-fail" ] && { echo "설치 실패: $HTEAM_SLOT"; exit 7; }
printf '%s|%s\\n' "$HTEAM_SLOT" "$(pwd -P)" >> "$OUT_DIR/setup.txt"
mkdir -p node_modules && echo "$HTEAM_SLOT" >> node_modules/marker
"""
TEARDOWN_SH = """printf '%s|%s|%s\\n' "$HTEAM_SLOT" "$(pwd -P)" "$HT_PORT" >> "$OUT_DIR/teardown.txt"
[ -f "$OUT_DIR/teardown-fail" ] && { echo "정리 실패"; exit 4; }
exit 0
"""
BASE_MERGE = ("- 이 라운드는 기준 커밋 `{sha}` 를 이 브랜치에 병합한다: `git merge --no-ff --no-commit {sha}` 뒤 충돌을 풀고 "
              "푼 파일을 `git add -- <파일>` 한다. `git diff --cached --name-only` 가 병합과 푼 파일만 담는지 본 뒤 경로를 "
              "지정하지 않은 `git commit -m \"[{tid}] 기준 병합: {sha7}\"` 로 커밋한다(병합 중에는 git 이 경로 지정 커밋을 "
              "받지 않는다. 이 커밋만 작업 규칙 5.5 의 경로 지정 예외다). 그 밖의 병합·rebase·push 는 하지 않는다.")
RESUME = "앞 워커가 시작한 병합이 남아 있다. 이어서 푼다."
NORMAL_SECOND = "리뷰가 승인하면 관제가 병합한다"  # 작업 공간 절 둘째 줄(Task 4, 설계 5.10.5)의 끝


def ws_config(extra: str = "") -> str:
    """WS_CONFIG 의 [workspace] 에 setup·teardown(TOML 리터럴 문자열)과 extra 줄을 더한다."""
    lines = "setup = 'sh \"$OUT_DIR/setup.sh\"'\nteardown = 'sh \"$OUT_DIR/teardown.sh\"'\n" + extra
    return WS_CONFIG.replace("slots = 2\n", "slots = 2\n" + lines)


def ago(seconds: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


class MergeCase(TeamCase):
    """작업 공간 프로젝트(setup·teardown 도우미, node_modules 는 git 제외)와 이 프로세스 안의 관제. 기준 브랜치 main 에
    src/a/core.py("a")·docs/other.md("o") 가 있고, T-001(developer, owns src/a/**) 사양이 커밋돼 있다."""

    config_text = None  # None 이면 ws_config()
    gate = False

    def setUp(self):
        super().setUp()
        self.out = self.tmp / "out"
        self.out.mkdir()
        (self.out / "setup.sh").write_text(SETUP_SH, encoding="utf-8")
        (self.out / "teardown.sh").write_text(TEARDOWN_SH, encoding="utf-8")
        self.env["OUT_DIR"] = str(self.out)
        self.init_project(self.config_text or ws_config())
        self.commit(".gitignore", ".herdr-team/state/\nnode_modules/\n", "chore: node_modules 제외")
        self.commit("src/a/core.py", "a\n", "chore: core")
        self.commit("docs/other.md", "o\n", "chore: other")
        if self.gate:
            self.use_gate()
        self.run_id = self.setup_run()
        self.p = Project(self.proj)
        self.write_spec("T-001", owns="src/a/**")
        self._patcher = self.in_drive()  # self.env(OUT_DIR·FAKE_DIR)를 다 채운 뒤 건다. 관제의 자식이 물려받는다
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self.d = self.make_drive()

    def tearDown(self):
        for job in list(self.d.jobs.values()):
            if job["proc"].poll() is None:
                job["proc"].kill()
            job["proc"].wait(timeout=30)
        super().tearDown()

    # --- 흐름 ---
    def approved(self, tid: str = "T-001", files: dict | None = None, *, ws: bool = True) -> None:
        """시작(작업 공간이면 ws_start) → 작업 커밋·done → review → 리뷰어 APPROVE → review-finish = approved."""
        if ws:
            self.ws_start(tid)
        else:
            code, out = self.hteam("start", tid)
            self.assertEqual(code, 0, out)
        code, out = self.act_work(tid, files if files is not None else {"src/a/x.py": "x = 1\n"})
        self.assertEqual(code, 0, out)
        code, out = self.hteam("review", tid)
        self.assertEqual((code, out.get("status")), (0, "reviewing"), out)
        code, out = self.act_review(tid, "APPROVE")
        self.assertEqual(code, 0, out)
        code, out = self.hteam("review-finish", tid)
        self.assertEqual((code, out.get("status")), (0, "approved"), out)

    def wait_jobs(self, limit: float = 60.0) -> None:
        deadline = time.monotonic() + limit
        while True:
            self.d.reap_jobs()
            if not self.d.jobs:
                return
            if time.monotonic() > deadline:
                self.fail(f"자식이 끝나지 않았다: {sorted(self.d.jobs)}")
            time.sleep(0.05)

    def worker_base_merge(self, base: str, resolved: dict, *, commit: bool = True) -> None:
        """작업 워커의 기준 병합(사양 지시대로, 슬롯 1): --no-commit 병합(충돌) → 푼 파일 git add → 경로 지정 없는 커밋."""
        slot = self.slot_root(1)
        proc = subprocess.run(["git", "-C", str(slot), "merge", "--no-ff", "--no-commit", base], capture_output=True,
                              text=True, env=self.env)
        self.assertNotEqual(proc.returncode, 0, proc.stdout)  # 충돌로 멈춘다
        if not commit:
            return
        for rel, text in resolved.items():
            (slot / rel).write_text(text, encoding="utf-8")
            self.git_at(slot, "add", "--", rel)
        self.git_at(slot, "commit", "-q", "-m", f"[T-001] 기준 병합: {base[:7]}")

    # --- 보기 ---
    def record(self, n: int) -> dict:
        return {**workspace.SLOT_DEFAULT, **self.slots()["slots"].get(str(n), {})}

    def subjects(self, n: int = 1) -> list[str]:
        return self.git("log", "--first-parent", f"-{n}", "--format=%s").splitlines()

    def parents(self, rev: str = "HEAD") -> list[str]:
        return self.git("rev-list", "--parents", "-n", "1", rev).split()[1:]

    def detached(self, root) -> bool:
        return self.git_at(root, "rev-parse", "--abbrev-ref", "HEAD").strip() == "HEAD"

    def has_branch(self, name: str) -> bool:
        return bool(self.git("branch", "--list", name).strip())

    def merging(self, root) -> bool:
        return subprocess.run(["git", "-C", str(root), "rev-parse", "-q", "--verify", "MERGE_HEAD"], capture_output=True,
                              env=self.env).returncode == 0

    def lines(self, name: str) -> list[str]:
        path = self.out / name
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def decides(self, kind: str | None = None) -> list[dict]:
        return [e for e in self.outbox_items() if e["type"] == "decide" and (kind is None or e["kind"] == kind)]

    def progress(self) -> list[str]:
        return [e["body"] for e in self.outbox_items() if e["type"] == "progress"]

    def log_text(self) -> str:
        path = self.drive_dir / "drive.log"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def spec_text(self, n: int, tid: str = "T-001") -> str:
        return (self.state_dir / "tasks" / tid / f"r{n}-work.md").read_text(encoding="utf-8")


class MergeTest(MergeCase):
    """accept 의 병합 성공과 놓기(설계 5.10.6, 6.4 의 7단계 줄)."""

    def test_accept_merges_no_ff_then_releases_the_slot(self):
        self.approved()
        tip = self.git("rev-parse", "herdr/T-001").strip()
        before = self.head()
        res = self.d.accept_task("T-001")
        head = self.head()
        self.assertEqual((res["status"], res["merge"]), ("done", head), res)
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["workspace"]["merge"]), ("done", head))
        self.assertNotIn("merge_wait", st)
        # 병합 뒤 그 태스크의 파일은 기준 브랜치(메인 폴더)에서 읽는다. 슬롯은 놓은 뒤 다른 태스크가 다시 쓴다(Rules 1a)
        self.assertEqual(workspace.task_root(Project(self.proj), st), self.proj)
        self.assertEqual(self.subjects(1), ["[T-001] merge: 앱 만들기"])
        self.assertEqual(self.parents(), [before, tip])  # --no-ff: 기준과 태스크 브랜치, 부모 둘
        self.assertEqual((self.proj / "src/a/x.py").read_text(encoding="utf-8"), "x = 1\n")
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertIn(f"T-001 병합 {head[:7]}", self.log_text())
        self.assertIn("slot:1", self.d.jobs)  # after_accept 가 놓기 자식을 띄웠다
        self.wait_jobs()
        rec = self.record(1)
        self.assertEqual((rec["state"], rec["task"], rec["setup_done"]), ("free", None, None))
        slot = self.slot_root(1)
        self.assertTrue((slot / "node_modules" / "marker").is_file())  # 슬롯 폴더와 무시된 파일은 지우지 않는다
        self.assertTrue(self.detached(slot))
        self.assertFalse(self.has_branch("herdr/T-001"))  # 병합한 브랜치는 지운다
        self.assertEqual(self.lines("teardown.txt"), [f"1|{slot}|8110"])  # setup 과 같은 환경(슬롯 env)
        log = self.log_text()
        self.assertIn("slot-1 T-001 놓기 시작", log)
        self.assertIn("slot-1 T-001 놓기 free", log)

    def test_release_after_cli_accept_and_after_a_dead_release_child(self):
        self.approved()
        code, out = self.hteam("accept", "T-001")  # 관제 안의 CLI accept 는 병합까지(놓기는 관제가 한다)
        self.assertEqual((code, out["status"]), (0, "done"), out)
        self.assertEqual(out["merge"], self.head())
        self.assertEqual((self.record(1)["state"], self.record(1)["task"]), ("busy", "T-001"))
        code, out = self.hteam("slot", "release", "T-001", env={"HTEAM_TEST_DIE_AT": "slot_release_teardown"})
        self.assertEqual(code, 137, out)
        self.assertEqual((self.record(1)["state"], self.record(1)["task"]), ("busy", "T-001"))
        self.d.reconcile()  # 태스크는 done 인데 슬롯은 busy: 재확인이 놓기를 잇는다
        self.assertIn("slot:1", self.d.jobs)
        self.wait_jobs()
        self.assertEqual((self.record(1)["state"], self.record(1)["task"]), ("free", None))
        self.assertEqual(len(self.lines("teardown.txt")), 2)  # 이어 한 놓기는 teardown 을 다시 돈다
        self.assertFalse(self.has_branch("herdr/T-001"))
        code, out = self.hteam("slot", "release", "T-001")  # 이미 놓았다
        self.assertEqual((code, out["slot"], out["state"]), (0, None, None), out)

    def test_teardown_failure_is_reported_and_release_goes_on(self):
        self.approved()
        (self.out / "teardown-fail").write_text("", encoding="utf-8")
        self.d.accept_task("T-001")
        self.wait_jobs()
        self.assertEqual(self.record(1)["state"], "free")
        [line] = [b for b in self.progress() if "teardown" in b]
        self.assertTrue(line.startswith("slot-1 T-001 teardown 이 failed(exit 4)로 끝났다(놓기는 마쳤다). 로그: "), line)
        self.assertIn("slot-1 T-001 놓기 free (teardown failed)", self.log_text())

    def test_release_refuses_open_tasks_and_main(self):
        self.approved()
        code, out = self.hteam("slot", "release", "T-001")  # 아직 approved: 놓지 않는다
        self.assertEqual((code, out["error"]["code"]), (3, "task_open"), out)
        code, out = self.hteam("slot", "release", "T-001", as_="main")
        self.assertEqual((code, out["error"]["code"]), (5, "drive_only"), out)


class ConflictTest(MergeCase):
    """충돌: abort·changes·base_merge·base 이동·decide merge_conflict, 기준 병합 라운드(설계 5.10.6)."""

    gate = True

    def conflicted(self) -> str:
        """T-001 이 core.py 를 고쳐 승인된 사이 사람이 기준 브랜치에서 같은 줄과 owns 밖 파일을 고쳤다. accept 가 충돌한다.
        충돌 때의 기준 HEAD 를 돌려준다."""
        self.approved(files={"src/a/core.py": "task\n"})
        self.commit("src/a/core.py", "main\n", "사람: core")
        base = self.commit("docs/other.md", "o2\n", "사람: other")
        self.res = self.d.accept_task("T-001")
        return base

    def test_conflict_aborts_moves_base_and_decides(self):
        base = self.conflicted()
        conflict = {"base": base, "files": ["src/a/core.py"]}
        self.assertEqual((self.res["status"], self.res["merge_conflict"]), ("changes", conflict), self.res)
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["round"], st["base_merge"], st["base"]), ("changes", 1, base, base))
        self.assertEqual(st["rounds"][-1]["merge_conflict"], conflict)
        self.assertIsNone(st["workspace"]["merge"])
        self.assertEqual(self.head(), base)  # 되돌렸다
        self.assertFalse(self.merging(self.proj))
        self.assertEqual(self.git("status", "--porcelain"), "")
        [dec] = self.decides("merge_conflict")
        self.assertEqual((dec["task"], dec["detail"]), ("T-001", conflict))
        self.assertEqual(dec["commands"], ['hteam fix T-001 --note "<충돌을 어떻게 풀지 사용자 지시>"', "hteam drop T-001"])
        self.assertIn("T-001 병합 충돌: src/a/core.py", self.log_text())
        self.assertEqual((self.record(1)["state"], self.record(1)["task"]), ("busy", "T-001"))  # 슬롯은 태스크가 쥔다
        self.assertEqual(self.d.jobs, {})  # 놓지 않는다
        self.d.reconcile()  # 열린 decide: 관제가 스스로 fix 하지 않는다
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["round"]), ("changes", 1))

    def cli_conflicted(self) -> str:
        """conflicted() 와 같은 충돌을 관제 안의 CLI accept 로 만든다: 충돌 전이는 쓰고 decide 는 올리지 않는다(after_accept 를
        거치지 않는다). 충돌 전이 뒤 decide 를 올리기 전에 관제가 죽은 것과 같다. 충돌 때의 기준 HEAD 를 돌려준다."""
        self.approved(files={"src/a/core.py": "task\n"})
        self.commit("src/a/core.py", "main\n", "사람: core")
        base = self.commit("docs/other.md", "o2\n", "사람: other")
        code, out = self.hteam("accept", "T-001")
        self.assertEqual((code, out["status"]), (0, "changes"), out)
        self.assertEqual(self.decides("merge_conflict"), [])
        return base

    def test_conflict_without_decide_is_decided_by_reconcile(self):
        base = self.cli_conflicted()
        self.d.reconcile()
        [dec] = self.decides("merge_conflict")
        self.assertEqual((dec["task"], dec["detail"]), ("T-001", {"base": base, "files": ["src/a/core.py"]}))
        self.assertEqual(self.task_state("T-001")["round"], 1)  # 자동 fix 를 하지 않는다
        self.d.reconcile()  # 이번에는 outbox 에 이 충돌의 decide 가 있다
        self.assertEqual(len(self.decides("merge_conflict")), 1)

    def test_answered_question_in_the_round_does_not_hide_the_conflict(self):
        # 같은 라운드에 답한 다른 decide(worker_question)의 decide_round 가 남아 있어도 재확인이 충돌 decide 를 올린다
        # (outbox 의 kind·task·detail 로 가린다, Codex 계획 리뷰 r1)
        self.ws_start("T-001")
        oid = self.d.decide("worker_question", "T-001", "어느 쪽으로 하나", question="어느 쪽으로 하나")
        (self.state_dir / "answers").mkdir(parents=True, exist_ok=True)
        (self.state_dir / "answers" / f"{oid}.json").write_text(
            json.dumps({"id": oid, "answer": "앞쪽", "at": "2026-11-12T00:00:00Z"}), encoding="utf-8")
        self.assertEqual(self.task_state("T-001")["decide_round"], 1)
        code, out = self.act_work("T-001", {"src/a/core.py": "task\n"})
        self.assertEqual(code, 0, out)
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out.get("status")), (0, "reviewing"), out)
        self.assertEqual(self.act_review("T-001", "APPROVE")[0], 0)
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual((code, out.get("status")), (0, "approved"), out)
        self.commit("src/a/core.py", "main\n", "사람: core")
        code, out = self.hteam("accept", "T-001")  # 충돌 전이만 쓴다(decide 없음)
        self.assertEqual((code, out["status"]), (0, "changes"), out)
        st = self.task_state("T-001")
        self.assertEqual((st["round"], st["decide_round"]), (1, 1))  # 앞 질문의 표시가 남았다
        self.d.reconcile()
        [dec] = self.decides("merge_conflict")
        self.assertEqual(dec["detail"]["files"], ["src/a/core.py"])
        self.assertEqual(self.task_state("T-001")["round"], 1)

    def test_base_merge_round_instruction_review_and_merge(self):
        base = self.conflicted()
        self.assertIn(NORMAL_SECOND, self.spec_text(1))
        code, out = self.hteam("fix", "T-001", "--note=우리 쪽(task)과 main 을 합친다")
        self.assertEqual((code, out.get("round")), (0, 2), out)
        self.assertEqual((self.record(1)["state"], self.record(1)["task"]), ("busy", "T-001"))  # 같은 슬롯·같은 브랜치
        rd = self.task_state("T-001")["rounds"][-1]
        self.assertEqual((rd["base_merge"], rd.get("merge_resume")), (base, None))
        r2 = self.spec_text(2)
        self.assertIn(BASE_MERGE.format(sha=base, sha7=base[:7], tid="T-001"), r2)
        self.assertNotIn(NORMAL_SECOND, r2)
        self.assertNotIn(RESUME, r2)
        self.worker_base_merge(base, {"src/a/core.py": "task+main\n"})
        code, out = self.act_work("T-001", {})  # 보고서만 고친 r2 작업 커밋과 done
        self.assertEqual(code, 0, out)
        calls = len(self.gate_calls())
        code, out = self.hteam("review", "T-001")
        # 기준에서 들어온 docs/other.md 는 owns 밖 변경으로 잡히지 않는다(사전 검사 통과)
        self.assertEqual((code, out.get("status")), (0, "reviewing"), out)
        self.assertNotIn("base_merge", self.task_state("T-001"))  # 기준을 부모로 가진 [T-001] 커밋을 봤다
        self.assertEqual(len(self.gate_calls()), calls + 1)  # code_head 가 바뀌어 quick 을 다시 돌았다
        self.assertEqual(self.gate_calls()[-1]["args"], ["src/a/core.py"])  # quick 은 기준과 브랜치의 차이만
        code, out = self.act_review("T-001", "APPROVE")
        self.assertEqual(code, 0, out)
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual((code, out["status"]), (0, "approved"), out)
        res = self.d.accept_task("T-001")
        self.assertEqual(res["status"], "done", res)
        self.assertEqual(self.subjects(1), ["[T-001] merge: 앱 만들기"])
        self.assertEqual((self.proj / "src/a/core.py").read_text(encoding="utf-8"), "task+main\n")
        self.assertEqual((self.proj / "docs/other.md").read_text(encoding="utf-8"), "o2\n")

    def test_left_merge_head_keeps_base_merge_and_adds_resume(self):
        base = self.conflicted()
        self.assertEqual(self.hteam("fix", "T-001", "--note=합친다")[0], 0)
        self.worker_base_merge(base, {}, commit=False)  # 병합을 시작하고 커밋 전에 끝났다
        code, out = self.act_work("T-001", {}, outcome="failed", commit=False)
        self.assertEqual(code, 0, out)
        code, out = self.hteam("fix", "T-001", "--note=이어서 한다")
        self.assertEqual((code, out.get("round")), (0, 3), out)
        st = self.task_state("T-001")
        self.assertEqual((st["base_merge"], st["rounds"][-1]["merge_resume"]), (base, True))
        self.assertIn(BASE_MERGE.format(sha=base, sha7=base[:7], tid="T-001") + " " + RESUME, self.spec_text(3))

    def test_abort_that_leaves_merge_head_is_merge_blocked(self):
        self.approved(files={"src/a/core.py": "task\n"})
        self.commit("src/a/core.py", "main\n", "사람: core")
        with mock.patch.object(gitio, "merge_abort", lambda root: None):  # abort 가 듣지 않았다
            self.assertIsNone(self.d.accept_task("T-001"))
        [dec] = self.decides("workspace_failed")
        self.assertEqual((dec["task"], dec["detail"]["kind"]), ("T-001", "merge_blocked"))
        st = self.task_state("T-001")
        self.assertEqual(st["status"], "approved")
        self.assertNotIn("base_merge", st)
        self.assertEqual(self.decides("merge_conflict"), [])
        self.git("merge", "--abort")


class RefuseTest(MergeCase):
    """거부·MERGE_HEAD·base_moved(설계 5.10.6): 상태를 바꾸지 않고 다시 시도, 10분 뒤 한 번 올린다."""

    def test_refused_merge_waits_then_is_blocked_once(self):
        self.approved(files={"src/a/new.py": "n = 1\n"})
        (self.proj / "src/a/new.py").write_text("사람이 둔 파일\n", encoding="utf-8")  # 병합이 덮을 커밋 안 된 파일
        before = self.head()
        self.assertIsNone(self.d.accept_task("T-001"))
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["merge_wait"]["asked"]), ("approved", []))
        self.assertEqual(self.head(), before)
        self.assertFalse(self.merging(self.proj))
        self.assertEqual(self.decides(), [])
        self.assertEqual(self.log_text().count("T-001 병합 거부:"), 1)
        self.assertIsNone(self.d.accept_task("T-001"))
        self.assertEqual(self.log_text().count("T-001 병합 거부:"), 1)  # 첫 거부만 남긴다
        code, out = self.hteam("accept", "T-001")
        self.assertEqual((code, out["error"]["code"]), (3, "merge_pending"), out)
        self.assertIn("src/a/new.py", out["output"])
        with state.edit(self.p, "T-001") as cur:
            cur["merge_wait"]["since"] = ago(workspace.MERGE_BLOCKED_S + 1)
        self.assertIsNone(self.d.accept_task("T-001"))
        [dec] = self.decides("workspace_failed")
        self.assertEqual((dec["task"], dec["detail"]["kind"]), ("T-001", "merge_blocked"))
        self.assertTrue(dec["summary"].startswith("T-001 병합이 10분 넘게 거부됐다: "), dec["summary"])
        self.assertIsNone(self.d.accept_task("T-001"))
        self.assertEqual(len(self.decides("workspace_failed")), 1)  # 한 번만
        (self.proj / "src/a/new.py").unlink()
        res = self.d.accept_task("T-001")
        self.assertEqual(res["status"], "done", res)
        self.assertNotIn("merge_wait", self.task_state("T-001"))

    def test_unfinished_merge_in_main_is_blocked_at_once(self):
        self.approved()
        before = self.head()
        (self.proj / ".git" / "MERGE_HEAD").write_text(before + "\n", encoding="utf-8")
        self.assertIsNone(self.d.accept_task("T-001"))
        [dec] = self.decides("workspace_failed")
        self.assertEqual(dec["detail"]["kind"], "merge_blocked")
        self.assertEqual(dec["summary"], "메인 폴더에 끝나지 않은 병합(MERGE_HEAD)이 있어 T-001 를 병합하지 않았다")
        self.assertEqual((self.task_state("T-001")["status"], self.head()), ("approved", before))
        (self.proj / ".git" / "MERGE_HEAD").unlink()
        self.assertEqual(self.d.accept_task("T-001")["status"], "done")

    def test_main_folder_on_another_branch_is_base_moved(self):
        self.approved()
        self.git("switch", "-q", "-c", "side")
        self.assertIsNone(self.d.accept_task("T-001"))
        [dec] = self.decides("workspace_failed")
        self.assertEqual((dec["detail"]["kind"], dec["detail"]["branch"], dec["detail"]["base_branch"]),
                         ("base_moved", "side", "main"))
        self.assertEqual(self.task_state("T-001")["status"], "approved")
        self.assertIn("T-001 병합 못 함(base_moved): ", self.log_text())
        self.git("switch", "-q", "main")
        self.assertEqual(self.d.accept_task("T-001")["status"], "done")
        self.assertEqual(self.git("branch", "--show-current").strip(), "main")


class DropReleaseTest(MergeCase):
    """drop 뒤 놓기와 준비 중 drop(설계 5.10.6·5.10.9)."""

    def test_dropped_task_keeps_its_branch_and_frees_the_slot(self):
        self.ws_start("T-001")
        self.assertEqual(self.act_work("T-001", {"src/a/x.py": "x\n"})[0], 0)
        code, out = self.hteam("drop", "T-001")
        self.assertEqual((code, out["status"]), (0, "dropped"), out)
        self.d.reconcile()
        self.wait_jobs()
        rec = self.record(1)
        self.assertEqual((rec["state"], rec["task"]), ("free", None))
        self.assertTrue(self.has_branch("herdr/T-001"))  # 버린 태스크의 브랜치는 기록으로 남긴다
        self.assertTrue(self.detached(self.slot_root(1)))
        self.assertEqual(len(self.lines("teardown.txt")), 1)

    def test_dropped_task_with_uncommitted_changes_leaves_the_slot_dirty(self):
        self.ws_start("T-001")
        (self.slot_root(1) / "src/a/tmp.py").write_text("tmp\n", encoding="utf-8")
        code, out = self.hteam("drop", "T-001", "--force")
        self.assertEqual((code, out["status"]), (0, "dropped"), out)
        self.d.reconcile()
        self.wait_jobs()
        rec = self.record(1)
        self.assertEqual((rec["state"], rec["task"]), ("dirty", None))
        [line] = [b for b in self.progress() if b.startswith("slot-1 에 커밋 안 된 변경이 남아")]
        self.assertEqual(line, "slot-1 에 커밋 안 된 변경이 남아 dirty 로 두었다(T-001 를 버렸다): src/a/tmp.py. "
                               "사용자가 버려도 된다고 하면 hteam slot reset 1")
        self.assertIn("slot-1 T-001 놓기 dirty", self.log_text())

    def test_drop_during_base_merge_leaves_the_slot_dirty_for_reset(self):
        # 기준 병합 라운드 도중(슬롯에 MERGE_HEAD) drop: git 은 병합 중 switch 를 거부하므로 switch 하지 않고 dirty 로 남긴다
        # (Rules 7, Codex 계획 리뷰 r1). 재확인은 놓기를 되풀이하지 않고 slot reset 이 정리한다
        self.approved(files={"src/a/core.py": "task\n"})
        self.commit("src/a/core.py", "main\n", "사람: core")
        base = self.commit("docs/other.md", "o2\n", "사람: other")
        self.assertEqual(self.d.accept_task("T-001")["status"], "changes")
        self.assertEqual(self.hteam("fix", "T-001", "--note=합친다")[0], 0)
        self.worker_base_merge(base, {}, commit=False)  # 워커가 병합을 시작한 채 끝났다(충돌이 남았다)
        slot = self.slot_root(1)
        self.assertTrue(self.merging(slot))
        code, out = self.hteam("drop", "T-001", "--force")
        self.assertEqual((code, out["status"]), (0, "dropped"), out)
        self.d.reconcile()
        self.wait_jobs()
        rec = self.record(1)
        self.assertEqual((rec["state"], rec["task"]), ("dirty", None))
        self.assertTrue(self.merging(slot))  # 병합 상태·브랜치·파일은 그대로 둔다(사용자가 보고 정한다)
        self.assertEqual(self.git_at(slot, "branch", "--show-current").strip(), "herdr/T-001")
        [line] = [b for b in self.progress() if b.startswith("slot-1 에 커밋 안 된 변경이 남아")]
        self.assertIn("dirty 로 두었다(T-001 를 버렸다): ", line)
        self.assertIn("src/a/core.py", line)
        self.assertTrue(line.endswith("사용자가 버려도 된다고 하면 hteam slot reset 1"), line)
        self.assertEqual(self.log_text().count("slot-1 T-001 놓기 dirty"), 1)
        self.d.reconcile()  # 태스크 없는 dirty 슬롯은 놓을 것이 아니다(같은 실패를 되풀이하지 않는다)
        self.assertEqual(self.d.jobs, {})
        self.assertEqual(len(self.lines("teardown.txt")), 1)
        code, out = self.hteam("slot", "reset", "1")
        self.assertEqual((code, out["slot"], out["state"]), (0, 1, "free"), out)
        self.assertFalse(self.merging(slot))  # git reset --hard 가 끝나지 않은 병합도 지운다
        self.assertEqual(self.git_at(slot, "status", "--porcelain").strip(), "")

    def test_drop_while_preparing_frees_the_reservation(self):
        code, out = self.hteam("start", "T-001")
        self.assertEqual((code, out.get("reason")), (0, "slot_setup"), out)
        self.assertEqual((self.record(1)["state"], self.record(1)["task"]), ("preparing", "T-001"))
        code, out = self.hteam("drop", "T-001")
        self.assertEqual((code, out["status"]), (0, "dropped"), out)
        rec = self.record(1)
        self.assertEqual((rec["state"], rec["task"]), ("free", None))  # 준비 자식을 기다리지 않고 바로 푼다
        code, out = self.hteam("slot", "prepare", "T-001")  # 늦게 도는 준비 자식은 기록에 쓰지 않는다
        self.assertEqual((code, out["error"]["code"]), (3, "slot_not_reserved"), out)
        self.assertEqual(self.record(1)["state"], "free")

    def test_drop_after_prepare_runs_teardown(self):
        self.assertEqual(self.hteam("start", "T-001")[0], 0)
        self.assertEqual(self.hteam("slot", "prepare", "T-001")[0], 0)
        self.assertTrue(self.record(1)["ready"])
        code, out = self.hteam("drop", "T-001")
        self.assertEqual((code, out["status"]), (0, "dropped"), out)
        self.assertEqual(self.record(1)["task"], "T-001")  # setup 을 했으니 놓기(teardown)가 푼다
        self.d.reconcile()
        self.wait_jobs()
        self.assertEqual((self.record(1)["state"], self.record(1)["task"]), ("free", None))
        self.assertEqual(len(self.lines("teardown.txt")), 1)


class SlotResetTest(MergeCase):
    """hteam slot reset <N>(설계 5.10.8, 큐 명령 7.1)."""

    def dirty_slot(self):
        self.ws_start("T-001")
        slot = self.slot_root(1)
        (slot / "src/a/tmp.py").write_text("tmp\n", encoding="utf-8")
        (slot / "src/a/core.py").write_text("고친 채 둠\n", encoding="utf-8")
        self.assertEqual(self.hteam("drop", "T-001", "--force")[0], 0)
        self.d.reconcile()
        self.wait_jobs()
        self.assertEqual(self.record(1)["state"], "dirty")
        return slot

    def test_reset_cleans_a_dirty_slot_but_keeps_ignored_files(self):
        slot = self.dirty_slot()
        code, out = self.hteam("slot", "reset", "1")
        self.assertEqual((code, out["slot"], out["state"]), (0, 1, "free"), out)
        self.assertFalse((slot / "src/a/tmp.py").exists())
        self.assertEqual((slot / "src/a/core.py").read_text(encoding="utf-8"), "a\n")
        self.assertTrue((slot / "node_modules" / "marker").is_file())  # 무시된 파일은 남긴다(git clean -fd)
        self.assertEqual((self.record(1)["state"], self.record(1)["task"]), ("free", None))
        code, out = self.hteam("slot", "reset", "1")
        self.assertEqual((code, out["error"]["code"]), (3, "slot_not_dirty"), out)

    def test_reset_refuses_busy_slots_and_bad_numbers(self):
        self.ws_start("T-001")
        code, out = self.hteam("slot", "reset", "1")
        self.assertEqual((code, out["error"]["code"]), (3, "slot_not_dirty"), out)
        self.assertEqual((self.record(1)["state"], self.record(1)["task"]), ("busy", "T-001"))
        for bad in ("0", "3", "x"):
            with self.subTest(bad=bad):
                code, out = self.hteam("slot", "reset", bad)
                self.assertEqual((code, out["error"]["code"]), (2, "bad_slot"), out)

    def test_main_puts_reset_on_the_queue(self):
        self.dirty_slot()
        code, out = self.hteam("slot", "reset", "1", as_="main", env={"HTEAM_QUEUE_WAIT_S": "0.3"})
        self.assertEqual((code, out.get("status")), (0, "queued"), out)
        reqs = [json.loads(f.read_text(encoding="utf-8")) for f in sorted((self.drive_dir / "queue").iterdir())
                if queue.REQUEST_RE.match(f.name)]
        self.assertEqual([(r["command"], r["args"]) for r in reqs], [("slot reset", {"slot": 1})])
        self.d.run_queue()
        self.assertEqual(self.record(1)["state"], "free")
        self.assertEqual(self.record(1)["reset_request"], reqs[0]["id"])
        self.assertEqual(queue.recorded(self.p, {**reqs[0], "started_at": "2026-11-12T00:00:00Z"}),
                         {"recovered": True, "slot": 1, "state": "free"})


class FinalSlotTest(MergeCase):
    """worktree 모드의 마무리 full(설계 5.10.7): 빈 슬롯에서 기준 HEAD 로 setup → full → teardown."""

    gate = True

    def test_final_full_runs_in_a_free_slot(self):
        head = self.head()
        code, out = self.hteam("test", "--full")
        self.assertEqual((code, out["status"], out["head"], out["slot"]), (0, "passed", head, 1), out)
        slot = self.slot_root(1)
        call = self.gate_calls()[-1]
        self.assertEqual((call["args"], call["cwd"]), (["--all"], str(slot)))  # 메인 폴더에서 돌리지 않는다
        self.assertEqual(self.lines("setup.txt"), [f"1|{slot}"])
        self.assertEqual(self.lines("teardown.txt"), [f"1|{slot}|8110"])
        self.assertEqual((self.record(1)["state"], self.record(1)["task"]), ("free", None))
        self.assertTrue(self.detached(slot))
        self.assertEqual(self.git_at(slot, "rev-parse", "HEAD").strip(), head)
        final = json.loads((self.state_dir / "tests" / "final.json").read_text(encoding="utf-8"))["full"]
        self.assertEqual((final["head"], final["slot"]), (head, 1))

    def test_no_free_slot_waits_for_the_next_check(self):
        busy = {"state": "busy", "task": "T-009", "branch": "herdr/T-009", "base_branch": "main", "base": self.head(),
                "setup_done": "T-009", "since": "2026-11-12T00:00:00Z"}
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "slots.json").write_text(json.dumps({"slots": {"1": busy, "2": {**busy, "state": "dirty",
                                                                                             "task": None}}}))
        code, out = self.hteam("test", "--full")
        self.assertEqual((code, out["error"]["code"]), (3, "no_free_slot"), out)
        self.d.final_done(code, out, "")
        self.assertEqual(self.decides(), [])
        self.assertIn("마지막 전체 테스트: 빈 슬롯이 없어 다음 확인 때 다시 한다", self.log_text())

    def test_setup_failure_is_workspace_failed(self):
        (self.out / "setup-fail").write_text("", encoding="utf-8")
        code, out = self.hteam("test", "--full")
        self.assertEqual((code, out["error"]["code"], out["kind"], out["slot"]), (1, "setup_failed", "setup_failed", 1))
        self.assertEqual((self.record(1)["state"], self.record(1)["task"]), ("free", None))
        self.assertEqual(self.lines("teardown.txt"), [])  # setup 이 실패하면 teardown 은 돌지 않는다(준비와 같다)
        self.d.final_done(code, out, "")
        [dec] = self.decides("workspace_failed")
        self.assertEqual((dec["task"], dec["detail"]["kind"]), (None, "setup_failed"))
        self.assertIn("설치 실패: 1", dec["tail"])


class WorkspaceStatusTest(MergeCase):
    """hteam status 의 workspace(설계 5.10.8)."""

    def test_status_shows_slots(self):
        self.ws_start("T-001")
        code, out = self.hteam("status", as_="main")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["workspace"], {"mode": "worktree", "slots": [
            {"n": 1, "state": "busy", "task": "T-001", "branch": "herdr/T-001"},
            {"n": 2, "state": "free", "task": None, "branch": None}]})
        (self.state_dir / "slots.json").write_text("{깨짐", encoding="utf-8")
        code, out = self.hteam("status", as_="main")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["workspace"], {"mode": "worktree", "slots": []})
        self.assertTrue(any(w.startswith("작업 공간 기록: ") for w in out["warnings"]), out.get("warnings"))


class SharedMergeTest(MergeCase):
    """회귀(헤더 "기본값"): shared 는 병합하지 않고, 슬롯 기록·status 의 workspace·슬롯 명령이 없다."""

    config_text = BASE_CONFIG
    gate = True

    def test_shared_accept_is_unchanged(self):
        self.approved(ws=False)
        before = self.head()
        res = self.d.accept_task("T-001")
        self.assertEqual(res["status"], "done", res)
        self.assertNotIn("merge", res)
        self.assertEqual(self.head(), before)  # 병합 커밋이 없다
        self.assertEqual(len(self.parents()), 1)
        st = self.task_state("T-001")
        self.assertNotIn("workspace", st)
        self.assertNotIn("merge_wait", st)
        self.assertEqual(self.d.jobs, {})
        self.assertFalse((self.state_dir / "slots.json").exists())
        self.assertFalse((self.state_dir / "slots").exists())
        code, out = self.hteam("status", as_="main")
        self.assertNotIn("workspace", out)
        for args in (("slot", "reset", "1"), ("slot", "release", "T-001")):
            with self.subTest(args=args):
                code, out = self.hteam(*args)
                self.assertEqual((code, out["error"]["code"]), (3, "workspace_off"), out)

    def test_shared_final_full_runs_in_the_main_folder(self):
        code, out = self.hteam("test", "--full")
        self.assertEqual((code, out["status"]), (0, "passed"), out)
        self.assertNotIn("slot", out)
        self.assertEqual(self.gate_calls()[-1]["cwd"], str(self.proj))


if __name__ == "__main__":
    unittest.main()
```

**Edit** `herdr-team/tests/test_drive.py`

```python
                                              "unknown_regression", "token_update", "workspace_failed"))
```

```python
                                              "unknown_regression", "token_update", "workspace_failed",
                                              "merge_conflict"))
```

**Edit** `herdr-team/tests/test_drive.py`

```python
              "review --retry, design-decide, scope, agent reset, test-confirm 이다")
```

```python
              "review --retry, design-decide, scope, agent reset, slot reset, test-confirm 이다")
```

**Edit** `herdr-team/tests/test_queue.py`

```python
              "review --retry, design-decide, scope, agent reset, test-confirm 이다")
```

```python
              "review --retry, design-decide, scope, agent reset, slot reset, test-confirm 이다")
```

- [ ] **Step 2: 실패 확인**

Run: `cd herdr-team && python3 -m unittest tests.test_workspace_merge tests.test_drive tests.test_queue 2>&1 | tail -5`
Expected: `Ran 56 tests` / `FAILED (failures=8, errors=1)`(subTest 마다 센다). 오류 하나는 새 모듈의 `ImportError: cannot import name 'workspace' from 'hteam'`(Task 3 의 모듈이 없다. 구현이 있으면 이 모듈의 시험 27개가 기능 실패로 바뀐다), 실패는 `test_time_constants_and_kinds` 의 `Tuples differ: (… 'token_update') != (… 'token_update', 'workspace_failed', 'merge_conflict')` 하나와 `test_drive_only_commands`·`test_drive_only_commands_from_main` 의 `… agent reset, test-confirm 이다') != (… agent reset, slot reset, test-confirm 이다')` 일곱이다. HEAD 에 공유 시험 도구 편집(Task 3 의 셋, Task 4 의 `ws_start`)과 Task 4 의 `DECIDE_KINDS` 기대값 Edit 과 이 태스크의 Step 1 블록만 적용한 트리에서 쟀다(앞 태스크 구현 없음).

- [ ] **Step 3: 구현**

Rules 1–13 과 Interfaces 대로 `workspace.py`·`gitio.py`·`tasks.py`·`review.py`·`compose.py`·`testgate.py`·`drive.py`·`queue.py`·`roles.py`·`coord.py` 를 고친다. git 은 `gitio.py` 에서만 부른다(`workspace.py` 는 `gitio` 를 모듈로 부른다). 병합은 `tasks.accept` 한 곳이고, 관제 쪽 처리(로그·decide·놓기 자식)는 `Drive.accept_task`·`after_accept`·`merge_refused`·`release_step` 이 한다. `slot` 파서(Task 3 의 `workspace.register`)에 `release`·`reset` 을 더한다. `reset` 은 큐 명령이라 `queue.route` 를 거친다(`crew._cmd_agent_reset` 과 같은 꼴). Task 4 가 `review.changed_files`·`target_commits`·`testgate` 의 git 조회에 작업 루트를 넘긴 자리에 `base=` 를 더한다.

- [ ] **Step 4: 통과 확인**

Run: `cd herdr-team && python3 -m unittest tests.test_workspace_merge tests.test_workspace tests.test_drive tests.test_queue tests.test_lifecycle 2>&1 | tail -3` 그다음 `bash herdr-team/tests/run.sh 2>&1 | tail -3`(저장소 루트에서, 백그라운드로 하나만, 10–15분)
Expected: 둘 다 `OK`(shared 프로젝트의 accept·drop·마무리 시험이 그대로 통과한다).

- [ ] **Step 5: 정적 확인과 커밋**

```bash
python3 - <<'PY'
import ast, pathlib
for f in ["herdr-team/lib/hteam/workspace.py", "herdr-team/lib/hteam/gitio.py", "herdr-team/lib/hteam/tasks.py",
          "herdr-team/lib/hteam/review.py", "herdr-team/lib/hteam/compose.py", "herdr-team/lib/hteam/testgate.py",
          "herdr-team/lib/hteam/drive.py", "herdr-team/lib/hteam/queue.py", "herdr-team/lib/hteam/roles.py",
          "herdr-team/lib/hteam/coord.py", "herdr-team/tests/test_workspace_merge.py", "herdr-team/tests/test_drive.py",
          "herdr-team/tests/test_queue.py"]:
    ast.parse(pathlib.Path(f).read_text(encoding="utf-8"), feature_version=(3, 11))
PY
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews'
git add -- herdr-team/lib/hteam herdr-team/tests/test_workspace_merge.py herdr-team/tests/test_drive.py herdr-team/tests/test_queue.py
git commit -m "feat(herdr-team): 작업 공간 병합·충돌·기준 병합 라운드·놓기·마무리 full 슬롯·slot reset·status workspace" \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" \
  -- herdr-team/lib/hteam herdr-team/tests/test_workspace_merge.py herdr-team/tests/test_drive.py herdr-team/tests/test_queue.py
```

Expected: ast 오류 없음, grep 빈 출력. 구현자는 여기서 멈춘다(컨트롤러가 `scripts/codex-review.sh commit <sha>`).

---

### Task 6: 테스트 관문 `full_if`(판정·사전 거부·기록·재사용·반려), 리뷰 프롬프트와 워커 사양의 줄, 테스트·setup 환경에서 `[redmine] key_env` 빼기

설계 5.7 의 "7단계 `full_if`" 문단, 6.1 의 4a, 5.7 끝의 key_env 줄(8.12 의 키 규칙), 13장의 한계 줄을 만든다. developer 태스크가 바꾼 경로(`changed_files`: 대상 커밋이 건드린 모든 경로. `gitio.commit_files` 가 `diff-tree --no-renames` 라 지운 파일과 옮긴 파일의 옛 경로·새 경로가 다 든다. 보고서 경로와 프로젝트 밖 `../` 는 뺀다) 가운데 하나라도 `[test] full_if` glob 에 맞으면 `hteam test T-xxx` 와 리뷰 관문이 quick 대신 full 을 한 번 돈다. quick 의 파일 목록(`quick_files`)은 지금 작업 트리에 있는 파일만 남기므로 판정에 쓰지 않는다(Codex 설계 리뷰 r1). 이 full 도 quick 사전 거부(`no_work_commit`·`uncommitted_owned`)를 먼저 해서 커밋한 내용으로 돈 결과만 남는다. 기록은 `full` 키이고 재사용은 tester 의 full 과 같다(같은 라운드·code_head·식별값이면 상태와 관계없이 다시 쓴다). 실패·시간 초과는 quick 실패처럼 리뷰어 없이 hteam 이 반려하고, 관제는 반려 사유 note 로 fix 하며 같은 실패가 두 라운드 이어지면 `repeat_test_failure` 다. `full_if` 는 식별값(`digest`)에 들지 않으므로 `full_if` 만 바꾼 뒤의 `review --retry` 는 앞 시도의 quick 결과를 그대로 쓸 수 있다(설계 13장 한계, 고치지 않는다). 그리고 테스트 명령과 작업 공간 setup·teardown 의 환경에서 `[redmine] key_env` 변수를 뺀다(설계 5.7 끝, 8.12 의 키).

작업 공간 태스크의 `full_if` full 은 Task 4 의 작업 루트 규칙(cwd 는 그 슬롯의 작업 루트, 환경에 슬롯 env·`HTEAM_SLOT`, git 조회는 태스크 브랜치) 그대로 돈다. 이 태스크는 실행 위치를 바꾸지 않으므로 슬롯 시험을 따로 두지 않는다(setup 환경 시험 하나만 Task 3·4 의 슬롯 준비를 쓴다).

**Files:**
- Modify: `herdr-team/lib/hteam/testgate.py`(`full_if_matches`, `matched_text`, `record_task` 의 matched, `run_task`·`gate_results` 의 full_if 갈래, `gate_failed`, `child_env` 의 key_env), `herdr-team/lib/hteam/review.py`(`GATE_FULL_PROBLEM`, `gate_problem`, `_gate_text` 의 full, 관문 반려 갈래), `herdr-team/lib/hteam/compose.py`(`FULL_IF_LINE`, `FULL_IF_TESTS`, `test_block`·`tests_section`), `herdr-team/lib/hteam/drive.py`(`GATE_FULL_NOTE`, `hteam_changes`, `_same_gate_failure`)
- Test: `herdr-team/tests/test_testgate.py`·`herdr-team/tests/test_review.py`·`herdr-team/tests/test_drive_events.py`·`herdr-team/tests/test_start.py`(Append)

**Interfaces:**
- Consumes: Task 2 의 `testgate.GateConfig.full_if: tuple[str, ...]`(없으면 빈 튜플, `digest` 에 들지 않는다)과 `config.Config.redmine`(`Redmine.key_env`), Task 3 의 `testgate.child_env(cfg, extra=None)`, Task 2 의 `config.test_settings`·`TestSettings`·`redmine_key_env`(Rules 11: `hteam test` 는 `config.load` 를 부르지 않는다), Task 4 의 테스트 실행 규칙(테스트 명령을 돌리는 곳이 작업 루트와 `workspace.task_env(p, config.test_settings(p), st)` 를 `execute` 에 넘긴다), 지금의 `testgate.check_committed`·`record_task`·`gate_results`·`retry_results`·`describe`·`summary`, `review._precheck_fail`·`_gate_text`, `compose.test_block`·`tests_section`·`GROUP_FILES_SHOWN`, `drive.Drive.hteam_changes`·`_same_gate_failure`, `globs.matches_any`.
- Produces:
  - `testgate.full_if_matches(p, cfg: GateConfig, st: dict, commits: list[dict]) -> list[str]`: 직무(`st["role"]`)가 `developer` 이고 `cfg.full_if` 가 비지 않았을 때만 본다. 아니면 `[]`. `changed_files(p, commits)` 가운데 `_report(path, tid)`(태스크 보고서 폴더·`docs/qa/`)가 아니고 `../` 로 시작하지 않으며 `matches_any(path, cfg.full_if)` 인 것, 정렬.
  - `testgate.matched_text(matched: list[str]) -> str`: 앞 15개를 `show()` 로 `, ` 이어 붙이고 넘으면 ` 외 N개`. 반려 파일·프롬프트가 같이 쓴다.
  - `testgate.record_task(p, cfg, st, commits, kind, matched=None) -> dict`: `matched` 가 있으면(full_if full) 실행 전에 `check_committed` 를 하고(quick 과 같은 거부) 기록에 `reason: "full_if"`, `matched` 를 더한다. 그 밖은 지금 그대로(`--full` 로 직접 돌린 full 은 `check_committed` 를 하지 않고 `reason` 이 없다).
  - `testgate.run_task(p, tid, kind)`: kind 가 `quick` 이고 `full_if_matches` 가 비지 않으면 `record_task(…, "full", matched=…)` 를 하고 결과 `kind` 는 `"full"`. 출력 `{"task", "kind": "full", "round", "head", "config", "command", "log", "status", "exit", "seconds", "tail", "reason": "full_if", "matched", "dirty", "at"}`. exit 는 지금처럼 status 가 `passed`·`flaky`·`skipped` 면 0, 아니면 1.
  - `testgate.gate_results(p, st, role, commits)`: developer 이고 `full_if_matches` 가 비지 않으면 저장된 `full` 이 같은 라운드(`st["round"] or 1`)·같은 code_head·같은 식별값이면(상태와 관계없이) 그것을, 아니면 `record_task(…, "full", matched=…)` 를 쓰고 `{"head", "config", "full": <기록>, "full_if": <matched>}` 를 돌려준다. `full_if` 키는 이번 대상 커밋으로 잰 matched 다(재사용한 기록이 `--full` 로 직접 돈 것이어도 있다). 확정 전 건너뛰기(`skipped: "unapproved"`)는 지금처럼 이것보다 먼저다. tester 와 매치 없는 developer 는 지금 그대로. `retry_results` 는 바꾸지 않는다(같은 입력이면 앞 시도의 `inputs.tests` 를 그대로, 다르면 `gate_results`).
  - `testgate.gate_failed(tests: dict | None) -> bool`: developer 관문을 리뷰어 없이 반려할 결과인가: quick 이 있고 `passed`·`flaky`·`skipped` 가 아니거나, `full_if` 가 있고 full 이 `passed`·`flaky`·`skipped` 가 아니다. tester 결과(`full_if` 키 없음)는 반려하지 않는다. 지금의 `failed_quick` 을 이것으로 바꾼다(부르는 곳은 `review.py` 둘뿐이다).
  - `testgate.child_env(cfg, extra=None)`: Task 3 의 동작에 더해 `cfg` 의 `redmine` 이 있으면 `cfg.redmine.key_env` 이름을 뺀다(`cfg` 는 `config.Config` 또는 Task 2 의 `config.TestSettings`. 둘 다 `redmine.key_env` 가 그 이름이다). 빼기는 extra 를 더한 뒤 마지막에 한다(어떤 경로로도 그 이름이 테스트 명령·setup·teardown 에 가지 않는다). 부르는 곳(Codex 계획 리뷰 r1): 테스트 명령 `execute` 는 `child_env(config.test_settings(p), env)` 다. `hteam test`(quick·full·마무리 full)와 리뷰 관문이 함께 지나는 자리라 `config.load` 를 부르지 않는다: `hteam test` 는 7단계에도 설정이 깨져도 지금처럼 돌고(설계 4.2·5.7 의 5단계 규칙 그대로, 회귀 시험 `BrokenConfigGateTest`), `[redmine]` 의 다른 키가 틀려도 `key_env` 이름이 맞으면 그 이름을 뺀다(`KeyEnvBrokenConfigTest`). 리뷰 관문은 리뷰가 이미 `config.load` 로 검사를 통과시킨 설정이라 같은 이름이다. 작업 공간 `run_hook` 은 받은 `cfg`(준비·놓기 자식은 `config.load` 의 `Config`, 마무리 full 은 Task 5 의 `TestSettings`)로 `child_env(cfg, …)` 를 부른다(Task 3 에 `child_env(None, …)` 로 남은 곳이 있으면 이 태스크가 바꾼다).
  - 문구(원문):
    - `review.GATE_FULL_PROBLEM = "hteam 테스트 관문: full_if 경로를 바꿔 돌린 전체 테스트(full)가 통과하지 못했다."`, `review.gate_problem(tests) -> str`(`tests.get("full_if")` 면 `GATE_FULL_PROBLEM`, 아니면 지금 `GATE_PROBLEM`).
    - 반려 파일(full): 지금 `_gate_text` 와 같은 틀에서 `## 지적 사항` 의 P1 이 `GATE_FULL_PROBLEM`, `## 테스트 관문` 줄이 `testgate.describe(full, "full")` 의 줄들 다음 `full_if 에 맞은 경로: <matched_text>`, 출력 끝은 full 의 tail. 나머지(머리, "고친 뒤 `<SHIM> test T-xxx` 로 다시 확인한다.", 탓이 아닐 때 문장, VERDICT)는 그대로.
    - `drive.GATE_FULL_NOTE = "테스트 관문 반려: full_if 로 돌린 full 이 통과하지 못했다({file} 의 출력 끝을 본다)"`.
    - repeat 요약: `"같은 {kind} 테스트 실패로 hteam 사전 검사가 두 라운드 연속 반려했다"`(kind 는 `quick`·`full`. quick 문구는 지금 그대로다).
    - `compose.FULL_IF_TESTS = "hteam 이 \`docs/planning/tasks.toml\` 의 \`[test]\` 명령으로 전체 테스트(full)를 돌렸다. 이 태스크가 바꾼 파일 가운데 \`[test] full_if\` 에 맞은 것: {paths}"`.
    - `compose.FULL_IF_LINE = f"- 이 태스크가 \`[test] full_if\` 경로를 바꾸면 \`{SHIM} test {{task_id}}\` 가 quick 대신 전체 테스트를 돈다(오래 걸리면 \`run_in_background\`)."`(설계 5.7 원문에 SHIM 과 끝 마침표만 더했다).
  - 기록(`state/tests/T-xxx.json` 의 `full`, 헤더 "기록·필드"): tester full 과 같은 꼴에 `reason: "full_if"`, `matched: [<경로>]`.

  ```json
  {"full": {"round": 1, "head": "9c1e…", "config": "5d2a…", "command": "fake-test --all",
            "log": ".herdr-team/state/tests/logs/T-001-r1-full-20261112-101500.log", "status": "passed", "exit": 0,
            "seconds": 0.2, "tail": "…", "reason": "full_if", "matched": ["src/db/schema.py"], "dirty": [],
            "at": "2026-11-12T10:15:01+09:00"}}
  ```

**Rules:**

1. 판정(설계 5.7 7단계): `full_if_matches` 는 대상 커밋(`work_commits`, 리뷰 대상 커밋과 같다)의 `changed_files` 로 잰다. 지운 경로와 옮긴 파일의 옛 경로도 든다(`commit_files` 가 `--no-renames` 다. 새로 넣는 규칙은 없다). quick 파일 목록은 쓰지 않는다. 보고서 경로(`_report`)와 `../` 는 뺀다. 직무는 상태의 `role` 로 본다(글자 그대로 `developer`. tester 는 이미 full 을 돈다).
2. `hteam test T-xxx`(인자 없음, 지금 kind `quick`): developer 이고 매치가 있으면 full 한 번. `check_committed` 를 먼저 한다(커밋 없음 `no_work_commit`, 소유 경로의 커밋 안 된 변경 `uncommitted_owned`, exit 2, 아무것도 돌리지 않고 기록하지 않는다). 실행은 `attempt(p, cfg, cfg.full, f"{tid}-r{N}-full")`(재시도 없음: full 은 한 번만 돈다). `hteam test T-xxx --full` 은 지금 그대로다(사전 거부 없음, `reason` 없음).
3. 리뷰 관문(설계 6.1 4a): `gate_results` 의 developer 갈래 맨 앞에서 매치를 잰다. 매치가 있으면 Interfaces 의 재사용 규칙(tester 와 같다: 같은 라운드·code_head·식별값, 상태와 관계없이)으로 full 을 쓰거나 돌린다. 매치가 없으면 지금 quick 갈래(통과 기록만 재사용).
4. 반려: `review._review` 의 두 자리(`working` 의 새 리뷰, `--retry` 가 다시 돈 관문)에서 `failed_quick` 대신 `gate_failed` 로 보고, `_precheck_fail(…, [gate_problem(tests)], tests, …)` 를 부른다. `_gate_text` 는 `tests.get("full_if")` 면 full 갈래(Interfaces 문구)다. 라운드 기록의 `prechecks` 는 `[GATE_FULL_PROBLEM]`, `tests` 는 관문 결과, history 사건 `precheck` 의 `tests` 는 `{"full": "failed"}`(지금 `summary` 그대로).
5. 관제(설계 8.6): `hteam_changes` 는 `prechecks == [GATE_FULL_PROBLEM]` 이면 note `GATE_FULL_NOTE.format(file=review_rel(tid, round))` 로 fix 한다. `_same_gate_failure` 는 최근 두 판정 라운드가 모두 hteam 반려이고 `prechecks` 가 같은 관문 문구 하나(`[GATE_PROBLEM]` 또는 `[GATE_FULL_PROBLEM]`)이며 그 종류(quick·full)의 tail 이 숫자만 빼고 같으면 그 종류를 돌려준다(아니면 None). decide 요약은 repeat 요약 문구에 그 종류를 넣는다. quick 이 한 라운드, full 이 다음 라운드면 repeat 이 아니다.
6. 리뷰 프롬프트(설계 6.2): `tests_section` 은 `tests.get("full_if")` 면 `## hteam 테스트 결과` 머리 다음 `FULL_IF_TESTS`(paths 는 `matched_text`) 한 줄과 `describe(full, "full")` 줄들이다(`templates/review-tests.md` 는 quick 문장이라 쓰지 않는다. 템플릿은 바꾸지 않는다). 그 밖은 지금 그대로. `verify_rule` 은 바꾸지 않는다(관문 결과가 있으므로 `VERIFY_GATED`).
7. 워커 사양(설계 5.7 끝 문장, 5.5): `test_block` 은 developer 이고 확정한 HEAD `[test]` 에 `full_if` 가 있으면 developer 블록의 둘째 줄("- done 전에 …다시 돌린다.") 바로 뒤에 `FULL_IF_LINE`(task_id 를 채운다)을 넣는다. tester·확정 대기 블록과 `full_if` 가 없는 developer 블록은 지금 그대로다.
8. 환경(설계 5.7 끝, 8.12): `child_env` 의 key_env 빼기(Interfaces). 테스트 명령(quick·full·마무리 full)과 작업 공간 setup·teardown 이 모두 `child_env` 를 거친다. `[redmine]` 이 없으면 지금과 같다(그 이름의 변수도 그대로 넘어간다). 테스트 명령 쪽은 설정을 검사 없이 읽으므로(`config.test_settings`) 설정이 깨진 프로젝트에서도 `hteam test` 가 `bad_config` 로 막히지 않는다(설계 4.2 "설정을 읽지 않는 명령(… 5단계의 `test` …)은 설정이 깨져도 동작한다").
9. 한계(설계 5.7 13장 줄, 고치지 않는다): `full_if` 는 식별값에 들지 않는다. `full_if` 만 바꾼 뒤의 `review --retry` 는 앞 시도의 결과를 그대로 쓸 수 있다(새 라운드부터 full 을 고른다). 같은 라운드에 developer 가 `--full` 로 직접 돌린 full 기록도 같은 키라 관문이 재사용한다.

핵심 조각(그대로 옮기지 않아도 된다) — 관문의 developer 갈래:

```python
saved = records(p, tid)
if role == DEVELOPER_ROLE and (matched := full_if_matches(p, cfg, st, commits)):
    full = saved.get("full")  # tester 와 같은 재사용: 같은 라운드·code_head·식별값이면 상태와 관계없이
    if not (isinstance(full, dict) and full.get("round") == (st.get("round") or 1) and full.get("head") == head
            and full.get("config") == value):
        full = record_task(p, cfg, st, commits, "full", matched=matched)  # 먼저 check_committed
    return {**out, "full": full, "full_if": matched}
```

- [ ] **Step 1: 실패하는 테스트 작성**

**Append** `herdr-team/tests/test_testgate.py`

```python
from tests.helpers import BASE_CONFIG, WS_CONFIG
from hteam import config  # noqa: E402

# [redmine] 표(설계 4.1). 이 태스크의 시험은 key_env 만 쓴다(주소는 쓰지 않는 닫힌 포트)
REDMINE_TABLE = """
[redmine]
url = "http://127.0.0.1:9"
key_env = "REDMINE_API_KEY"
status = { start = 2, done = 3, changes = 4, closed = 5 }
"""
# full 이 받은 두 변수를 FAKE_DIR/env.txt 에 남긴다(없으면 "없음")
ENV_FULL = 'mkdir -p "$FAKE_DIR" && printf "%s|%s" "${REDMINE_API_KEY-없음}" "${HT_KEEP-없음}" > "$FAKE_DIR/env.txt"'


class FullIfTest(GateCase):
    """`[test] full_if`(설계 5.7 7단계): developer 가 바꾼 경로가 맞으면 `hteam test T` 가 quick 대신 full 을 한 번 돈다."""

    def setUp(self):
        super().setUp()
        self.use_gate(extra='full_if = ["src/db/**", "migrations/*.sql"]\n')

    def test_quick_until_a_full_if_path_changes(self):
        self.started()
        self.commit("src/app.py", "a\n", "[T-001] app")
        code, out = self.run_test("T-001")
        self.assertEqual((code, out["kind"], out["status"], out.get("reason")), (0, "quick", "passed", None), out)
        self.commit("src/db/schema.py", "s\n", "[T-001] 스키마")
        code_sha = self.head()
        code, out = self.run_test("T-001")
        self.assertEqual((code, out["kind"], out["status"], out["reason"], out["matched"]),
                         (0, "full", "passed", "full_if", ["src/db/schema.py"]), out)
        self.assertEqual((out["command"], out["head"], out["round"]), ("fake-test --all", code_sha, 1), out)
        self.assertEqual([c["args"] for c in self.gate_calls()], [["src/app.py"], ["--all"]])
        self.assertTrue(out["log"].startswith(".herdr-team/state/tests/logs/T-001-r1-full-"), out["log"])
        saved = self.record()
        self.assertEqual({k: saved["full"][k] for k in ("round", "head", "status", "reason", "matched")},
                         {"round": 1, "head": code_sha, "status": "passed", "reason": "full_if",
                          "matched": ["src/db/schema.py"]})
        self.assertEqual(saved["quick"]["status"], "passed")  # 앞 quick 기록은 그대로 남는다

    def test_deleted_and_moved_paths_count(self):
        # 지운 파일·옮긴 파일의 옛 경로도 바꾼 경로다(quick 파일은 지금 있는 파일만이라 판정에 쓰지 않는다, Codex 설계 리뷰 r1)
        self.commit("src/db/a.py", "a\n", "chore: a")
        self.commit("src/db/b.py", "b\n", "chore: b")
        self.started()
        self.git("rm", "-q", "src/db/a.py")
        self.git("mv", "src/db/b.py", "src/b.py")
        self.git("commit", "-q", "-m", "[T-001] 지우고 옮김")
        code, out = self.run_test("T-001")
        self.assertEqual((code, out["kind"], out["matched"]), (0, "full", ["src/db/a.py", "src/db/b.py"]), out)
        self.commit("migrations/001.sql", "create\n", "[T-001] 마이그레이션")
        code, out = self.run_test("T-001")
        self.assertEqual(out["matched"], ["migrations/001.sql", "src/db/a.py", "src/db/b.py"], out)

    def test_report_paths_do_not_count(self):
        self.use_gate(extra='full_if = ["docs/**"]\n')
        self.started()
        self.commit("src/app.py", "a\n", "[T-001] app")
        self.commit("docs/tasks/T-001/report.md", "## r1\n", "[T-001] 보고서")
        self.commit("docs/qa/x.md", "qa\n", "[T-001] QA")
        code, out = self.run_test("T-001")
        self.assertEqual((code, out["kind"], out.get("matched")), (0, "quick", None), out)

    def test_full_if_refuses_uncommitted_owned_like_quick(self):
        self.started()
        self.commit("src/db/schema.py", "s\n", "[T-001] 스키마")
        (self.proj / "src/db/schema.py").write_text("고침\n")
        code, out = self.run_test("T-001")
        self.assertEqual((code, out["error"]["code"]), (2, "uncommitted_owned"), out)
        self.assertIn("src/db/schema.py", out["error"]["message"])
        self.assertEqual((self.gate_calls(), self.record()), ([], {}))

    def test_failed_full_if_runs_once_and_exits_1(self):
        self.started()
        self.commit("src/db/schema.py", "s\n", "[T-001] 스키마")
        self.gate_modes("fail", "pass")
        code, out = self.run_test("T-001")
        self.assertEqual((code, out["kind"], out["status"], out["exit"]), (1, "full", "failed", 1), out)
        self.assertEqual(len(self.gate_calls()), 1)  # full 은 한 번만 돈다(quick 처럼 다시 돌리지 않는다)
        self.assertEqual(self.record()["full"]["status"], "failed")

    def test_only_developer_and_only_without_full_flag(self):
        self.use_gate(extra='full_if = ["src/**", "tests/**"]\n')
        self.started("T-002", owns=("tests/grp/**", "docs/qa/grp.md"), role="tester")
        self.commit("tests/grp/test_a.py", "t\n", "[T-002] 묶음 테스트")
        code, out = self.run_test("T-002")
        self.assertEqual((code, out["kind"], out.get("reason")), (0, "quick", None), out)
        self.started()
        self.commit("src/a.py", "a\n", "[T-001] a")
        code, out = self.run_test("T-001", "--full")  # 직접 돌린 full 은 지금 그대로(사전 거부 없음, reason 없음)
        self.assertEqual((code, out["kind"], out.get("reason"), out.get("matched")), (0, "full", None, None), out)
        self.assertNotIn("reason", self.record("T-001")["full"])


class FullIfOffTest(GateCase):
    """회귀: [test] 에 full_if 가 없으면 developer 의 `hteam test T` 는 바꾼 경로와 관계없이 지금처럼 quick 이다."""

    def setUp(self):
        super().setUp()
        self.use_gate()

    def test_without_full_if_nothing_changes(self):
        self.started()
        self.commit("src/db/schema.py", "s\n", "[T-001] 스키마")
        code, out = self.run_test("T-001")
        self.assertEqual((code, out["kind"], out["files"]), (0, "quick", ["src/db/schema.py"]), out)
        self.assertNotIn("reason", out)
        self.assertNotIn("full", self.record())


class _KeyEnvCase(GateCase):
    redmine = ""

    def setUp(self):
        TeamCase.setUp(self)
        self.init_project(BASE_CONFIG + self.redmine)
        self.p = Project(self.proj)
        self.use_gate(full=ENV_FULL)

    def full_saw(self) -> str:
        code, out = self.run_test("--full", env={"REDMINE_API_KEY": "k-secret", "HT_KEEP": "keep"})
        self.assertEqual((code, out["status"]), (0, "passed"), out)
        return (self.tmp / "fake" / "env.txt").read_text(encoding="utf-8")


class KeyEnvTest(_KeyEnvCase):
    """테스트 명령 환경에서 [redmine] key_env 를 뺀다(설계 5.7 끝, 8.12). 다른 변수는 그대로 넘어간다."""
    redmine = REDMINE_TABLE

    def test_test_command_does_not_get_the_redmine_key(self):
        self.assertEqual(self.full_saw(), "없음|keep")


class KeyEnvSharedTest(_KeyEnvCase):
    """회귀: [redmine] 이 없으면 그 이름의 변수도 지금처럼 넘어간다."""

    def test_without_redmine_the_variable_passes(self):
        self.assertEqual(self.full_saw(), "k-secret|keep")


class KeyEnvBrokenConfigTest(_KeyEnvCase):
    """설정이 깨져도(여기서는 [redmine] 의 url) hteam test 는 돌고 key_env 이름은 뺀다(Task 2 Rules 11, Codex 계획 리뷰 r1)."""
    redmine = REDMINE_TABLE.replace('url = "http://127.0.0.1:9"', 'url = "ftp://127.0.0.1:9"')

    def test_broken_config_still_drops_the_key(self):
        with self.assertRaises(HteamError):
            config.load(self.p)  # 전체 검사는 실패한다
        self.assertEqual(self.full_saw(), "없음|keep")


class BrokenConfigGateTest(GateCase):
    """회귀: hteam test 는 config.toml 을 검사하지 않는다(설계 4.2·5.7 의 5단계 규칙, Codex 계획 리뷰 r1). 새 표가 없는
    프로젝트에서 다른 키가 틀렸거나 TOML 이 깨져도 확정된 quick·full 이 지금처럼 돈다(bad_config 가 아니다)."""

    def check(self, text: str) -> None:
        self.use_gate()
        self.started()
        self.commit("src/a.py", "a\n", "[T-001] a")
        (self.team / "config.toml").write_text(text, encoding="utf-8")
        for args in (("T-001",), ("--full",)):
            with self.subTest(args=args):
                code, out = self.run_test(*args)
                self.assertEqual((code, out.get("status")), (0, "passed"), out)

    def test_other_key_broken(self):
        self.check(BASE_CONFIG.replace("max_parallel = 4", "max_parallel = 0"))

    def test_toml_broken(self):
        self.check("max_parallel = [\n")


class KeyEnvSetupTest(TeamCase):
    """작업 공간 setup 도 같은 환경 규칙이다(설계 5.10.3 의 4, 8.12): key_env 는 빠지고 슬롯 번호는 들어간다."""

    def test_setup_does_not_get_the_redmine_key(self):
        setup = ('printf "%s|%s" "${REDMINE_API_KEY-없음}" "${HTEAM_SLOT-없음}" '
                 '> "$HTEAM_MAIN_ROOT/.herdr-team/state/setup-env.txt"')
        self.init_project(WS_CONFIG.replace("slots = 2\n", f"slots = 2\nsetup = {json.dumps(setup)}\n") + REDMINE_TABLE)
        self.setup_run()
        self.write_spec("T-001")
        env = {"REDMINE_API_KEY": "k-secret"}
        code, out = self.hteam("start", "T-001", env=env)
        self.assertEqual((code, out.get("status"), out.get("reason")), (0, "waiting", "slot_setup"), out)
        code, out = self.hteam("slot", "prepare", "T-001", env=env)
        self.assertEqual(code, 0, out)
        self.assertEqual((self.state_dir / "setup-env.txt").read_text(encoding="utf-8"), "없음|1")
```

**Append** `herdr-team/tests/test_review.py`

```python
from hteam import review


class FullIfGateTest(GateCase):
    """리뷰 관문의 `full_if`(설계 5.7 7단계, 6.1 4a): 바꾼 경로가 맞으면 quick 대신 full 을 한 번, 실패면 리뷰어 없이 반려."""

    def setUp(self):
        super().setUp()
        self.use_gate(extra='full_if = ["src/db/**"]\n')  # 식별값은 그대로라 앞 확정이 맞는다

    def changed(self, files=None):
        self.started()
        code, out = self.act_work("T-001", files or {"src/db/schema.py": "x = 1\n"})
        self.assertEqual(code, 0, out)

    def test_full_if_path_runs_full_once(self):
        self.changed()
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out["status"], out["tests"]), (0, "reviewing", {"full": "passed"}), out)
        self.assertEqual([c["args"] for c in self.gate_calls()], [["--all"]])
        text = self.prompt()
        for needle in ("## hteam 테스트 결과\nhteam 이 `docs/planning/tasks.toml` 의 `[test]` 명령으로 전체 테스트(full)를 "
                       "돌렸다. 이 태스크가 바꾼 파일 가운데 `[test] full_if` 에 맞은 것: src/db/schema.py\n- full: 통과 (",
                       '- full 명령: "fake-test --all"', "- full 로그: .herdr-team/state/tests/logs/T-001-r1-full-",
                       "1. 사양의 Acceptance 를 실제로 충족하는가. " + compose.VERIFY_GATED):
            self.assertIn(needle, text)
        self.assertNotIn("관련된 테스트(quick)", text)
        tests = self.attempt("T-001")["inputs"]["tests"]
        self.assertEqual((tests["full_if"], tests["full"]["reason"], tests["full"]["matched"]),
                         (["src/db/schema.py"], "full_if", ["src/db/schema.py"]))
        st = self.task_state("T-001")
        self.assertEqual((st["history"][-1]["event"], st["history"][-1]["tests"]), ("review", {"full": "passed"}))

    def test_full_if_failure_rejects_without_reviewer(self):
        self.changed()
        self.gate_modes("fail", "pass")
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out["status"], out["source"], out["tests"]),
                         (0, "changes", "hteam", {"full": "failed"}), out)
        self.assertEqual(len(self.gate_calls()), 1)
        text = (self.proj / "docs/reviews/T-001/r1.md").read_text(encoding="utf-8")
        for needle in ("# T-001 r1 리뷰 (출처: hteam 테스트 관문)\n\n리뷰어를 띄우지 않았다.",
                       "## 지적 사항\n- [P1] hteam 테스트 관문: full_if 경로를 바꿔 돌린 전체 테스트(full)가 통과하지 못했다.\n\n"
                       "## 테스트 관문\n- full: 실패 (",
                       ', exit 1)\n- full 명령: "fake-test --all"\n- full 로그: .herdr-team/state/tests/logs/T-001-r1-full-',
                       "\n- full_if 에 맞은 경로: src/db/schema.py\n\n출력 끝:\n```\n",
                       "FAIL tests/a.test.ts > 더하기\n```\n\n고친 뒤 `.herdr-team/bin/hteam test T-001` 로 다시 확인한다.",
                       "\n\nVERDICT: REQUEST_CHANGES\n"):
            self.assertIn(needle, text)
        st = self.task_state("T-001")
        rd = st["rounds"][0]
        self.assertEqual((rd["review_source"], rd["prechecks"], rd["reviews"], rd["tests"]["full"]["status"]),
                         ("hteam", [review.GATE_FULL_PROBLEM], [], "failed"))
        self.assertEqual(review.GATE_FULL_PROBLEM,
                         "hteam 테스트 관문: full_if 경로를 바꿔 돌린 전체 테스트(full)가 통과하지 못했다.")
        self.assertEqual((st["history"][-1]["event"], st["history"][-1]["tests"]), ("precheck", {"full": "failed"}))
        self.assertEqual(self.review_workers(), [])

    def test_worker_full_record_is_reused(self):
        self.changed()
        self.assertEqual(self.hteam("test", "T-001", as_=None)[0], 0)  # 워커의 hteam test 가 full 을 돌렸다
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out["status"], out["tests"], len(self.gate_calls())),
                         (0, "reviewing", {"full": "passed"}, 1), out)

    def test_failed_worker_record_is_reused_and_rejects(self):
        # tester full 과 같은 재사용: 같은 라운드·code_head·식별값이면 상태와 관계없이 다시 쓴다(설계 5.7 7단계)
        self.changed()
        self.gate_modes("fail")
        self.assertEqual(self.hteam("test", "T-001", as_=None)[0], 1)
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out["status"], out["tests"], len(self.gate_calls())),
                         (0, "changes", {"full": "failed"}, 1), out)

    def test_other_paths_keep_quick(self):
        self.changed({"src/app.py": "print(1)\n"})
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out["tests"]), (0, {"quick": "passed"}), out)
        self.assertIn("관련된 테스트(quick)를 돌렸다.\n- quick: 통과 (", self.prompt())
        self.assertNotIn("full_if", self.prompt())
```

**Append** `herdr-team/tests/test_drive_events.py`

```python
class FullIfEventTest(EventCase):
    """관제의 full_if 관문 반려(설계 8.6, 5.7 7단계): quick 실패처럼 사유 note 로 fix, 두 라운드 같은 실패면 repeat."""

    def test_full_if_rejection_fixes_then_repeat_raises_decide(self):
        self.use_gate(extra='full_if = ["src/**"]\n')
        self.gate_modes("fail", "fail")  # 라운드마다 full 한 번
        self.rearm()
        self.start()
        self.worked()
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["round"]), ("working", 2))
        self.assertEqual(st["rounds"][-1]["note"],
                         "테스트 관문 반려: full_if 로 돌린 full 이 통과하지 못했다(docs/reviews/T-001/r1.md 의 출력 끝을 본다)")
        self.worked()
        (e,) = self.decides()
        self.assertEqual((e["kind"], e["summary"]),
                         ("repeat_test_failure", "같은 full 테스트 실패로 hteam 사전 검사가 두 라운드 연속 반려했다"))
        self.assertEqual(e["files"], ["docs/reviews/T-001/r2.md"])
        self.assertEqual(self.task_state("T-001")["status"], "changes")
```

**Append** `herdr-team/tests/test_start.py`

```python
class FullIfLineTest(StartCase):
    """워커 사양 developer 테스트 절의 full_if 줄(설계 5.7 7단계 끝 문장): [test] 에 full_if 가 있을 때만, developer 만."""

    LINE = ("- 이 태스크가 `[test] full_if` 경로를 바꾸면 `.herdr-team/bin/hteam test T-001` 가 quick 대신 전체 테스트를 돈다"
            "(오래 걸리면 `run_in_background`).")

    def spec_text(self, tid="T-001"):
        cfg = config.load(self.p)
        with mock.patch.dict(os.environ, self.env, clear=True):
            return compose.work_spec(self.p, cfg, specs.load(self.p, tid), {"round": 1}, ["src/**"])

    def test_line_only_with_full_if_and_only_for_developer(self):
        self.write_spec("T-001")
        self.write_spec("T-002", "tester", owns="tests/grp/**, docs/qa/grp.md")
        self.use_gate()
        self.assertNotIn("full_if", self.spec_text())  # 회귀: 없으면 지금 문구 그대로
        self.use_gate(extra='full_if = ["src/db/**"]\n')
        text = self.spec_text()
        self.assertIn("실패하면 고쳐서 커밋하고 다시 돌린다.\n" + self.LINE + "\n- 테스트가 소유 경로에 만드는 산출물", text)
        self.assertEqual(text.count("full_if"), 1)
        self.assertNotIn("full_if", self.spec_text("T-002"))
```

- [ ] **Step 2: 실패 확인**

Run: `cd herdr-team && python3 -m unittest tests.test_testgate tests.test_review.FullIfGateTest tests.test_drive_events.FullIfEventTest tests.test_start.FullIfLineTest 2>&1 | tail -5`
Expected: `Ran 53 tests` / `FAILED (failures=3, errors=14)`. 대표 메시지: `hteam.errors.HteamError: docs/planning/tasks.toml [test] 검증 실패: [test]: 모르는 키 full_if`(14건. `full_if` 를 쓰는 클래스의 setUp 이 확정 기록을 쓸 때 지금 `[test]` 검사가 거부한다. `test_review` 의 `GateCase.tester` 도우미가 `tester` 로 시험에 잡혀 그 하나가 셈에 든다), `AssertionError: 'k-secret|keep' != '없음|keep'`(key_env 를 빼지 않는다), `AssertionError: HteamError not raised`(`KeyEnvBrokenConfigTest`: 지금 검사는 `[redmine]` 을 모른다), `AssertionError: Tuples differ: (0, 'working', None) != (0, 'waiting', 'slot_setup')`(지금은 `[workspace]` 를 모르는 표로 넘겨 바로 띄운다). 회귀 시험(`FullIfOffTest`, `KeyEnvSharedTest`, 설정이 깨져도 `hteam test` 가 도는 `BrokenConfigGateTest` 둘)과 기존 `test_testgate` 시험은 이 단계에서도 통과한다. HEAD 에 공유 시험 도구와 이 태스크의 Step 1 블록만 적용한 트리에서 쟀다(Task 2–4 구현 없음). Task 2–4 를 구현한 트리에서는 `full_if` 형식 오류가 이 태스크 기능의 실패(`('quick', …) != ('full', …)`, `KeyError: 'reason'`, `{'quick': 'passed'} != {'full': 'passed'}` 등)로 바뀐다.

- [ ] **Step 3: 구현**

Rules 1–9 와 Interfaces 대로 `testgate.py`·`review.py`·`compose.py`·`drive.py` 를 고친다. git 은 `gitio` 로만, 테스트 명령은 `testgate.py` 의 `execute` 로만 돈다. `failed_quick` 을 `gate_failed` 로 바꾸고 `review.py` 의 두 자리를 함께 고친다. `child_env` 를 부르는 곳이 설정을 넘기는지(Task 3 의 `run_hook` 은 받은 `cfg`, Task 4 의 테스트 실행 `execute` 는 `config.test_settings(p)`) 확인한다. `hteam test` 가 지나는 자리에서는 `config.load` 를 부르지 않는다(Task 2 Rules 11, `BrokenConfigGateTest`). 템플릿(`templates/review-tests.md`)은 바꾸지 않는다.

- [ ] **Step 4: 통과 확인**

Run: `cd herdr-team && python3 -m unittest tests.test_testgate tests.test_review tests.test_drive_events tests.test_start 2>&1 | tail -3` 그다음 `bash herdr-team/tests/run.sh 2>&1 | tail -3`(저장소 루트에서, 백그라운드로 하나만, 10–15분)
Expected: 둘 다 `OK`(`full_if`·`[redmine]` 이 없는 기존 시험은 그대로 통과한다).

- [ ] **Step 5: 정적 확인과 커밋**

```bash
python3 - <<'PY'
import ast, pathlib
for f in ["herdr-team/lib/hteam/testgate.py", "herdr-team/lib/hteam/review.py", "herdr-team/lib/hteam/compose.py",
          "herdr-team/lib/hteam/drive.py", "herdr-team/tests/test_testgate.py", "herdr-team/tests/test_review.py",
          "herdr-team/tests/test_drive_events.py", "herdr-team/tests/test_start.py"]:
    ast.parse(pathlib.Path(f).read_text(encoding="utf-8"), feature_version=(3, 11))
PY
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews'
git add -- herdr-team/lib/hteam/testgate.py herdr-team/lib/hteam/review.py herdr-team/lib/hteam/compose.py herdr-team/lib/hteam/drive.py herdr-team/tests/test_testgate.py herdr-team/tests/test_review.py herdr-team/tests/test_drive_events.py herdr-team/tests/test_start.py
git commit -m "feat(herdr-team): 테스트 관문 full_if(판정·사전 거부·기록·재사용·반려), 테스트·setup 환경의 Redmine 키 빼기" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/lib/hteam/testgate.py herdr-team/lib/hteam/review.py herdr-team/lib/hteam/compose.py herdr-team/lib/hteam/drive.py herdr-team/tests/test_testgate.py herdr-team/tests/test_review.py herdr-team/tests/test_drive_events.py herdr-team/tests/test_start.py
```

Expected: ast 오류 없음, grep 빈 출력. 구현자는 여기서 멈춘다(컨트롤러가 `scripts/codex-review.sh commit <sha>`).

---

### Task 7: 리뷰 프롬프트·워커 사양 문구(우선순위 줄, 프로젝트 점검표 `review-extra.md`, 이슈 줄, 라운드 절 2)

설계 6.2 의 "7단계 프롬프트 추가" 네 항목과 5.5 의 8·작업 규칙 줄, 8.12 의 이슈 줄을 만든다. 모두 플러그인 템플릿·조립 코드라 이미 세팅한 프로젝트에도 `hteam upgrade` 없이 적용된다(설계 6.2). 리뷰 프롬프트는 실행 정책 첫 줄 뒤에 우선순위 줄(리뷰 파일 경로·형식·판정 표기와 git 쓰기 금지는 프로젝트 문서보다 앞선다)을, 기준 절 뒤에 메인 프로젝트 작업 트리의 `.herdr-team/review-extra.md` 를 `## 프로젝트 점검표` 절로(6000자 상한), 태스크 줄 뒤에 이슈 줄을 넣는다. 라운드 절(`templates/review-round.md`)의 2 는 재검증 범위를 넓힌다(요청 R3). 워커 사양은 작업 규칙에 우선순위 줄(보고서 경로·커밋 형식·done 방법은 이 사양이 앞선다)을, 작업 규칙 바로 앞에 이슈 줄을 넣는다. 이슈 줄은 `[redmine]` 이 있으면 "관제가 바꾼다" 형태, 없으면 짧은 형태다(8.12). 작업 공간 절(5.10.5)과 리뷰 프롬프트의 작업 공간 줄은 Task 4 몫이다. 이 태스크는 이슈 줄의 자리만 정한다: 워커 사양에서 작업 공간 절(있으면) 다음, 작업 규칙 바로 앞이다. `AGENTS.section.md` 의 우선순위·이슈 줄은 Task 9 다.

기본값은 지금 그대로다: `review-extra.md` 가 없고 태스크에 `issue` 가 없으면 리뷰 프롬프트가 지금과 다른 곳은 우선순위 줄과 라운드 절 2 뿐이고, 워커 사양이 다른 곳은 작업 규칙의 우선순위 줄뿐이다(회귀 시험).

**Files:**
- Modify: `herdr-team/lib/hteam/compose.py`(이슈 줄 `issue_line`, 점검표 `review_extra`, `review_prompt` 의 `issue`·`extra` 자리와 경고, `work_spec` 의 이슈 줄), `herdr-team/lib/hteam/review.py`(`_launch_attempt` 가 점검표 경고를 출력 `warnings` 에 더한다), `herdr-team/templates/review-prompt.md`(우선순위 줄, `{{issue}}`, `{{extra}}`), `herdr-team/templates/review-round.md`(2), `herdr-team/templates/worker-rules.md`(우선순위 줄)
- Test: `herdr-team/tests/test_review.py`(Append: `ReviewPromptP7Test`·`RedmineReviewPromptTest`), `herdr-team/tests/test_wording.py`(Append: `PromptTemplateP7Test`·`WorkSpecP7Test`)

**Interfaces:**
- Consumes: Task 2 의 `specs.Spec.issue`(숫자 문자열, 앞 `#` 를 뗀 값, 없으면 None)와 `config.Config.redmine`(`Redmine | None`). 지금 코드의 `compose.review_prompt`·`work_spec`·`round_section`, `review._launch_attempt`, `util.fill`.
- Produces(`compose.py`):
  - `ISSUE_LINE = "이 태스크는 이슈 #{issue} 이다."`
  - `REDMINE_ISSUE_LINE = "이 태스크는 Redmine 이슈 #{issue} 이다. 이슈 상태와 노트는 관제가 바꾼다. 워커·리뷰어는 Redmine 을 바꾸지 않는다(프로젝트 문서에 다른 규칙이 있어도)."`(설계 8.12 원문)
  - `issue_line(cfg, spec) -> str | None`: `spec.issue` 가 없으면 None. `cfg.redmine` 이 있으면 `REDMINE_ISSUE_LINE`, 없으면 `ISSUE_LINE` 을 `issue` 로 채운 한 줄(글머리 없음).
  - `REVIEW_EXTRA = ".herdr-team/review-extra.md"`(프로젝트 루트 기준), `REVIEW_EXTRA_MAX = 6000`(글자 수, `len(str)`).
  - `EXTRA_WARNING = "`.herdr-team/review-extra.md` 를 읽지 못해 리뷰 프롬프트에 프로젝트 점검표를 넣지 않았다: {why}"`(`why` 는 `f"{type(exc).__name__}: {exc}"` 를 한 줄로, 200자까지).
  - `review_extra(p) -> tuple[str, str | None]`: (절, 경고). 파일 `p.root / REVIEW_EXTRA` 를 UTF-8(엄격)로 읽는다(작업 트리. 커밋 여부와 상관없다. 작업 공간 태스크여도 상태 루트 `p.root` 의 파일이다: 설계 6.2 "메인 프로젝트 작업 트리"). 없으면 `("", None)`. 읽지 못하면(`UnicodeDecodeError`, `OSError`: 디렉터리·권한) `("", EXTRA_WARNING.format(why=…))`. 읽으면 끝 공백을 뗀다(`rstrip()`). 비면 `("", None)`. 6000자를 넘으면 앞 6000자 뒤에 줄을 바꿔 `(뒤 N자 생략)`(N 은 뗀 글자 수). 절은 `"## 프로젝트 점검표\n" + 본문 + "\n\n"`.
  - `review_prompt(p, cfg, spec, rd, att, rounds=None, warnings=None) -> str`: 템플릿 자리 `issue`(이슈 줄이 있으면 `"\n- " + 이슈 줄`, 없으면 `""`)와 `extra`(`review_extra(p)` 의 절)를 더 채운다. `warnings` 가 리스트면 점검표 경고를 거기 더한다(없으면 버린다). 지금 호출(위치 인자 여섯)은 그대로 된다.
  - `work_spec(p, cfg, spec, rd, owns)`: 인수인계 줄(있으면) 뒤, 작업 규칙(`worker-rules.md`) 바로 앞에 빈 줄과 이슈 줄. Task 4 의 작업 공간 절은 인수인계 줄과 이슈 줄 사이에 온다(순서: 선행 태스크 → 인수인계 줄 → 작업 공간 절 → 이슈 줄 → 작업 규칙, 설계 5.5 의 7·8).
- Produces(`review.py`): `_launch_attempt` 가 프롬프트를 새로 쓸 때(`not prompt.is_file()`) `compose.review_prompt(…, warnings=<리스트>)` 로 받은 경고를 그 호출 결과의 `warnings`(dispatch 결과의 `warnings` 뒤)에 더한다. 그래서 `hteam review T` 의 출력 `warnings` 에 한 줄이 남는다(관제가 띄운 리뷰 자식이면 그 자식 출력 파일). 프롬프트가 이미 있으면(복구) 다시 읽지 않고 경고도 없다.
- Produces(템플릿, 원문은 Step 3 블록):
  - `review-prompt.md`: 실행 정책 첫 줄 뒤에 `- 이 프롬프트의 리뷰 파일 경로·형식·판정 표기와 git 쓰기 금지는 프로젝트 문서(AGENTS.md, CLAUDE.md 등)의 다른 규칙보다 앞선다. 코드·문구·디자인 기준은 프로젝트 문서도 따른다.`(설계 6.2 원문). 태스크 줄 끝에 `{{issue}}`. 기준 절 끝(`{{request_rule}}` 뒤 빈 줄)과 `## 등급과 판정` 사이에 `{{extra}}`.
  - `review-round.md` 의 2: `2. 새 커밋이 새 P1 을 만들었는지. 고친 함수·데이터를 읽는 다른 호출처와 출력 경로(다른 화면, 내보내기, 다른 API·작업)도 본다. 고친 방법이 만든 새 경계 조건(잠금 대기의 누적, 시각·순서, 늦은 응답)도 본다.`(설계 6.2 원문. "세 가지만 본다"·1·3·판정 규칙은 그대로)
  - `worker-rules.md`: 소유 경로 안내 문단과 번호 규칙 1 사이에 문단 `보고서 경로, 커밋 형식, done 방법은 이 사양이 프로젝트 문서(AGENTS.md, CLAUDE.md 등)의 다른 규칙보다 앞선다(Orca 시절 문서의 다른 보고서 경로·이슈 트래커 갱신 규칙과 부딪칠 때).`(설계 5.5 원문). 끝 규칙 6 은 그대로다(테스트 절이 규칙 6 바로 뒤에 오는 지금 시험이 그대로 통과한다).

**Rules:**

1. 우선순위 줄(설계 6.2·5.5): 두 문장 모두 템플릿 원문이다. Codex 리뷰어는 프로젝트 `AGENTS.md` 를 스스로 읽으므로 그 문서의 다른 검증 규칙(다른 보고서 경로, 이슈 트래커 갱신, 다른 판정 표기)과 부딪칠 때 이 줄이 정한다. 조건 없이 늘 넣는다.
2. 프로젝트 점검표(6.2): `review_extra` 대로. scaffold 는 파일을 만들지 않는다(프로젝트가 쓴다, README 는 Task 9). 기준 절 다음이고 테스트 절(`{{tests}}`)·라운드 절보다 앞이다. 본문은 가공하지 않는다(글머리·코드 블록 그대로).
3. 이슈 줄(8.12, 6.2, 5.5 의 8): `spec.issue` 가 있을 때만. 리뷰 프롬프트는 `## 태스크` 의 첫 줄(태스크 줄) 바로 다음 글머리 줄, 워커 사양은 작업 규칙 바로 앞의 문단이다. `[redmine]` 유무는 그 프롬프트·사양을 만들 때의 설정이다(이미 쓴 사양·프롬프트는 바꾸지 않는다).
4. 라운드 절 2(6.2, 요청 R3): 템플릿 원문 교체만. 자리(`{{…}}`)는 바뀌지 않는다.
5. 기본값: 점검표 파일이 없고 `issue` 가 없으면 자리 `issue`·`extra` 는 빈 문자열이라 줄·빈 줄이 늘지 않는다(`\n\n\n` 이 생기지 않는다).

- [ ] **Step 1: 실패하는 테스트 작성**

**Append** `herdr-team/tests/test_review.py`

```python
from tests.helpers import BASE_CONFIG, TeamCase  # noqa: E402  (Append 블록, 7단계)
from hteam.paths import Project  # noqa: E402

P7_REDMINE = ('\n[redmine]\nurl = "https://redmine.example.com"\nkey_env = "REDMINE_API_KEY"\n'
              'status = { start = 2, done = 3, changes = 4, closed = 5 }\n')
REVIEW_PRIORITY = ("- 이 프롬프트의 리뷰 파일 경로·형식·판정 표기와 git 쓰기 금지는 프로젝트 문서(AGENTS.md, CLAUDE.md 등)의 다른 "
                   "규칙보다 앞선다. 코드·문구·디자인 기준은 프로젝트 문서도 따른다.")
CRITERIA_END = "4. 수정 라운드면 이전 리뷰의 P1 지적이 모두 반영됐는가.\n\n"
TASK_LINE = "— [developer] 앱 만들기\n"


class ReviewPromptP7Test(ReviewCase):
    """7단계 리뷰 프롬프트 추가(설계 6.2): 우선순위 줄, 프로젝트 점검표, 이슈 줄, 라운드 절 2."""

    def prompt(self, n=1, k=1):
        return (self.state_dir / f"tasks/T-001/r{n}-review-a{k}.md").read_text(encoding="utf-8")

    def test_priority_line_follows_first_policy_line(self):
        self.reviewing()
        self.assertIn("<execution_policy>\n- 리뷰만 한다. 쓰는 파일은 REVIEW_FILE 하나다. 다른 파일을 만들거나 고치거나 지우지 "
                      "않는다.\n" + REVIEW_PRIORITY + "\n- git 쓰기(add·commit", self.prompt())

    def test_defaults_add_no_checklist_or_issue(self):
        # 회귀: review-extra.md·issue 가 없으면 기준 절 바로 뒤가 등급과 판정이고 태스크 줄 바로 뒤가 사양 줄이다
        out = self.reviewing()
        text = self.prompt()
        self.assertIn(CRITERIA_END + "## 등급과 판정\n", text)
        self.assertIn(TASK_LINE + "- 사양: `.herdr-team/tasks/T-001.md`\n", text)
        self.assertNotIn("## 프로젝트 점검표", text)
        self.assertNotIn("이슈 #", text)
        self.assertNotIn("\n\n\n", text)
        self.assertFalse([w for w in out.get("warnings", []) if "review-extra.md" in w], out)

    def test_checklist_after_criteria_and_issue_after_task_line(self):
        self.commit(".herdr-team/review-extra.md", "- 행 잠금 뒤 DB 시각을 다시 읽는가\n- 늦은 응답을 버리는가\n\n",
                    "chore: 점검표")
        self.reviewing(front={"issue": "#5712"})
        text = self.prompt()
        self.assertIn(CRITERIA_END + "## 프로젝트 점검표\n- 행 잠금 뒤 DB 시각을 다시 읽는가\n- 늦은 응답을 버리는가\n\n"
                      "## 등급과 판정\n", text)
        self.assertEqual(text.count("## 프로젝트 점검표"), 1)
        self.assertIn(TASK_LINE + "- 이 태스크는 이슈 #5712 이다.\n- 사양: `.herdr-team/tasks/T-001.md`\n", text)
        self.assertNotIn("Redmine", text)  # [redmine] 이 없으면 짧은 형태(설계 8.12)
        self.assertNotIn("\n\n\n", text)

    def test_uncommitted_checklist_is_read_from_the_work_tree(self):
        (self.team / "review-extra.md").write_text("- 작업 트리의 점검표\n", encoding="utf-8")
        self.reviewing()
        self.assertIn("## 프로젝트 점검표\n- 작업 트리의 점검표\n\n## 등급과 판정\n", self.prompt())

    def test_long_checklist_is_cut(self):
        self.commit(".herdr-team/review-extra.md", "가" * 6100 + "\n", "chore: 점검표")
        self.reviewing()
        text = self.prompt()
        self.assertIn("## 프로젝트 점검표\n" + "가" * 6000 + "\n(뒤 100자 생략)\n\n## 등급과 판정\n", text)
        self.assertNotIn("가" * 6001, text)

    def test_unreadable_checklist_is_left_out_with_a_warning(self):
        (self.team / "review-extra.md").write_bytes(b"\xff\xfe broken")
        self.git("add", "--", ".herdr-team/review-extra.md")
        self.git("commit", "-q", "-m", "chore: 깨진 점검표", "--", ".herdr-team/review-extra.md")
        out = self.reviewing()
        text = self.prompt()
        self.assertNotIn("## 프로젝트 점검표", text)
        self.assertIn(CRITERIA_END + "## 등급과 판정\n", text)
        warned = [w for w in out.get("warnings", []) if "review-extra.md" in w]
        self.assertEqual(len(warned), 1, out)
        self.assertIn("`.herdr-team/review-extra.md` 를 읽지 못해 리뷰 프롬프트에 프로젝트 점검표를 넣지 않았다: ", warned[0])

    def test_round_two_item_two_widens_the_recheck(self):
        self.reviewing()
        self.act_review("T-001", "REQUEST_CHANGES", text=P1_REVIEW)
        self.assertEqual(self.hteam("review-finish", "T-001")[1]["status"], "changes")
        self.assertEqual(self.hteam("fix", "T-001")[0], 0)
        self.assertEqual(self.act_work("T-001", {"src/app.py": "print('r2')\n"})[0], 0)
        code, out = self.hteam("review", "T-001")
        self.assertEqual(code, 0, out)
        text = self.prompt(n=2)
        self.assertIn("이번 라운드는 세 가지만 본다.\n1. r1 의 P1 지적마다", text)
        self.assertIn("\n2. 새 커밋이 새 P1 을 만들었는지. 고친 함수·데이터를 읽는 다른 호출처와 출력 경로(다른 화면, 내보내기, "
                      "다른 API·작업)도 본다. 고친 방법이 만든 새 경계 조건(잠금 대기의 누적, 시각·순서, 늦은 응답)도 본다.\n"
                      "3. r1 이후 바뀌지 않은 코드에서", text)
        self.assertIn(REVIEW_PRIORITY, text)
        self.assertNotIn("\n\n\n", text)


class RedmineReviewPromptTest(ReviewCase):
    """[redmine] 이 있으면 이슈 줄이 관제가 이슈를 바꾼다고 적는다(설계 8.12·6.2)."""

    def setUp(self):
        TeamCase.setUp(self)
        self.init_project(config=BASE_CONFIG + P7_REDMINE)
        self.setup_run()
        self.p = Project(self.proj)

    def test_issue_line_says_drive_owns_the_issue(self):
        self.reviewing(front={"issue": "5712"})
        text = (self.state_dir / "tasks/T-001/r1-review-a1.md").read_text(encoding="utf-8")
        self.assertIn(TASK_LINE + "- 이 태스크는 Redmine 이슈 #5712 이다. 이슈 상태와 노트는 관제가 바꾼다. 워커·리뷰어는 Redmine 을 "
                      "바꾸지 않는다(프로젝트 문서에 다른 규칙이 있어도).\n- 사양: `.herdr-team/tasks/T-001.md`\n", text)
        work = (self.state_dir / "tasks/T-001/r1-work.md").read_text(encoding="utf-8")
        self.assertIn("\n\n이 태스크는 Redmine 이슈 #5712 이다. 이슈 상태와 노트는 관제가 바꾼다.", work)
```

**Append** `herdr-team/tests/test_wording.py`

```python
from tests.helpers import BASE_CONFIG, CREW_CONFIG  # noqa: E402  (Append 블록, 7단계)

P7_REDMINE = ('\n[redmine]\nurl = "https://redmine.example.com"\nkey_env = "REDMINE_API_KEY"\n'
              'status = { start = 2, done = 3, changes = 4, closed = 5 }\n')
WORK_PRIORITY = ("보고서 경로, 커밋 형식, done 방법은 이 사양이 프로젝트 문서(AGENTS.md, CLAUDE.md 등)의 다른 규칙보다 앞선다"
                 "(Orca 시절 문서의 다른 보고서 경로·이슈 트래커 갱신 규칙과 부딪칠 때).")
REVIEW_PRIORITY = ("- 이 프롬프트의 리뷰 파일 경로·형식·판정 표기와 git 쓰기 금지는 프로젝트 문서(AGENTS.md, CLAUDE.md 등)의 다른 "
                   "규칙보다 앞선다. 코드·문구·디자인 기준은 프로젝트 문서도 따른다.")
ROUND_TWO = ("2. 새 커밋이 새 P1 을 만들었는지. 고친 함수·데이터를 읽는 다른 호출처와 출력 경로(다른 화면, 내보내기, 다른 "
             "API·작업)도 본다. 고친 방법이 만든 새 경계 조건(잠금 대기의 누적, 시각·순서, 늦은 응답)도 본다.")
RULES_HEAD = "## 소유 경로와 작업 규칙\n"


class PromptTemplateP7Test(unittest.TestCase):
    """7단계 템플릿 문구(설계 6.2·5.5): 리뷰 프롬프트 우선순위 줄과 자리, 라운드 절 2, 작업 규칙의 우선순위 줄."""

    def test_review_prompt_priority_line_and_slots(self):
        text = read("templates/review-prompt.md")
        self.assertIn("<execution_policy>\n- 리뷰만 한다. 쓰는 파일은 REVIEW_FILE 하나다. 다른 파일을 만들거나 고치거나 지우지 "
                      "않는다.\n" + REVIEW_PRIORITY + "\n- git 쓰기", text)
        self.assertIn("— [{{role}}] {{title}}{{issue}}\n- 사양: `{{spec_path}}`\n", text)
        self.assertIn("{{request_rule}}\n\n{{extra}}## 등급과 판정\n", text)

    def test_round_item_two(self):
        text = read("templates/review-round.md")
        self.assertIn("\n" + ROUND_TWO + "\n3. r{{prev}} 이후 바뀌지 않은 코드에서", text)
        self.assertNotIn("2. 새 커밋이 새 P1 을 만들었는지.\n", text)
        self.assertIn("이번 라운드는 세 가지만 본다.", text)

    def test_worker_rules_priority_paragraph(self):
        text = read("templates/worker-rules.md")
        self.assertIn("새 태스크로 나눈다).\n\n" + WORK_PRIORITY + "\n\n1. 같은 작업 폴더에서", text)
        self.assertTrue(text.rstrip().endswith("(리뷰 사전 검사가 수정 라운드로 돌려보낸다)."))


class WorkSpecP7Test(TeamCase):
    """워커 사양의 7단계 줄(설계 5.5 의 8·작업 규칙, 8.12): 작업 규칙의 우선순위 줄, 작업 규칙 바로 앞의 이슈 줄."""

    def setUp(self):
        super().setUp()
        self.init_project()
        self.p = Project(self.proj)

    def spec(self, front=None, config_text=None) -> str:
        if config_text is not None:
            (self.team / "config.toml").write_text(config_text, encoding="utf-8")
        self.write_spec("T-001", "developer", front=front, commit=False)
        cfg = config.load(self.p)
        return compose.work_spec(self.p, cfg, specs.load(self.p, "T-001"), {"round": 1}, cfg.owns("developer"))

    def test_defaults_add_only_the_priority_paragraph(self):
        # 회귀: issue 가 없으면 선행 태스크 절 바로 뒤가 작업 규칙이다
        text = self.spec()
        self.assertIn("## 선행 태스크\n없음.\n\n" + RULES_HEAD, text)
        self.assertNotIn("이슈 #", text)
        self.assertEqual(text.count(WORK_PRIORITY), 1)
        self.assertNotIn("\n\n\n", text)

    def test_issue_line_right_before_the_rules(self):
        text = self.spec(front={"issue": "5712"})
        self.assertIn("## 선행 태스크\n없음.\n\n이 태스크는 이슈 #5712 이다.\n\n" + RULES_HEAD, text)
        self.assertEqual(text.count("이슈 #5712"), 1)
        self.assertNotIn("\n\n\n", text)

    def test_issue_hash_is_dropped(self):
        text = self.spec(front={"issue": "#5712"})
        self.assertIn("\n\n이 태스크는 이슈 #5712 이다.\n\n" + RULES_HEAD, text)
        self.assertNotIn("##5712", text)

    def test_redmine_issue_line(self):
        text = self.spec(front={"issue": "5712"}, config_text=BASE_CONFIG + P7_REDMINE)
        self.assertIn("\n\n이 태스크는 Redmine 이슈 #5712 이다. 이슈 상태와 노트는 관제가 바꾼다. 워커·리뷰어는 Redmine 을 바꾸지 "
                      "않는다(프로젝트 문서에 다른 규칙이 있어도).\n\n" + RULES_HEAD, text)

    def test_redmine_without_issue_adds_nothing(self):
        text = self.spec(config_text=BASE_CONFIG + P7_REDMINE)
        self.assertIn("## 선행 태스크\n없음.\n\n" + RULES_HEAD, text)
        self.assertNotIn("Redmine", text)

    def test_issue_line_comes_after_the_handoff_line(self):
        (self.proj / "docs/handoff").mkdir(parents=True)
        (self.proj / "docs/handoff/production.md").write_text("# 인수인계\n", encoding="utf-8")
        text = self.spec(front={"issue": "5712"}, config_text=CREW_CONFIG)
        self.assertIn("남은 일이 적혀 있다.\n\n이 태스크는 이슈 #5712 이다.\n\n" + RULES_HEAD, text)
```

- [ ] **Step 2: 실패 확인**

Run: `cd herdr-team && python3 -m unittest tests.test_review.ReviewPromptP7Test tests.test_review.RedmineReviewPromptTest tests.test_wording 2>&1 | tail -5`
Expected: `Ran 32 tests`, `FAILED (failures=15)`. 대표 메시지: `AssertionError: '<execution_policy>\n- 리뷰만 한다. … 지우지 않는다.\n- 이 프롬프트의 리뷰 파일 경로·형식·판정 표기와 …' not found in …`(우선순위 줄, 프롬프트·템플릿), `'4. 수정 라운드면 … 반영됐는가.\n\n## 프로젝트 점검표\n- 행 잠금 뒤 DB 시각을 다시 읽는가\n…' not found in …`, `'## 프로젝트 점검표\n가가…\n(뒤 100자 생략)…' not found`, `AssertionError: 0 != 1 : {'ok': True, 'task': 'T-001', … 'status': 'reviewing', …}`(읽지 못한 점검표의 경고 없음), `'— [developer] 앱 만들기\n- 이 태스크는 Redmine 이슈 #5712 이다. …' not found`, `'## 선행 태스크\n없음.\n\n이 태스크는 이슈 #5712 이다.\n\n## 소유 경로와 작업 규칙\n' not found`, `'\n2. 새 커밋이 새 P1 을 만들었는지. 고친 함수·데이터를 읽는 …' not found`(라운드 절 2), `'새 태스크로 나눈다).\n\n보고서 경로, 커밋 형식, done 방법은 …' not found`(작업 규칙 우선순위 줄). 회귀 시험 둘(`test_defaults_add_no_checklist_or_issue`, `test_redmine_without_issue_adds_nothing`)과 지금 `test_wording` 시험 열다섯은 통과한다. HEAD 에 이 태스크의 Step 1 블록만 적용한 트리에서 쟀다(Task 2 의 `Spec.issue`·`Config.redmine` 도 없다. Task 2 구현이 있으면 대표 메시지는 같고 이슈 `#` 떼기만 Task 2 가 맡는다). 계획 작성 때 스크래치의 시범 구현(Interfaces 만)으로 이 시험 32개가 통과하는 것을 확인했다(시범 코드는 넣지 않았다).

- [ ] **Step 3: 구현**

Interfaces·Rules 대로 `compose.py`·`review.py` 를 고친다. 템플릿은 아래 블록 그대로다(문구가 계약이다). 템플릿 자리(`{{issue}}`·`{{extra}}`)와 `review_prompt` 의 `fill` 인자는 같은 커밋에 넣는다(`util.fill` 은 모르는 자리를 KeyError 로 낸다).

**Edit** `herdr-team/templates/review-prompt.md`

```markdown
- 리뷰만 한다. 쓰는 파일은 REVIEW_FILE 하나다. 다른 파일을 만들거나 고치거나 지우지 않는다.
```

```markdown
- 리뷰만 한다. 쓰는 파일은 REVIEW_FILE 하나다. 다른 파일을 만들거나 고치거나 지우지 않는다.
- 이 프롬프트의 리뷰 파일 경로·형식·판정 표기와 git 쓰기 금지는 프로젝트 문서(AGENTS.md, CLAUDE.md 등)의 다른 규칙보다 앞선다. 코드·문구·디자인 기준은 프로젝트 문서도 따른다.
```

**Edit** `herdr-team/templates/review-prompt.md`

```markdown
- {{task_id}} 라운드 {{round}} 리뷰 시도 {{attempt}} — [{{role}}] {{title}}
```

```markdown
- {{task_id}} 라운드 {{round}} 리뷰 시도 {{attempt}} — [{{role}}] {{title}}{{issue}}
```

**Edit** `herdr-team/templates/review-prompt.md`

```markdown
4. 수정 라운드면 이전 리뷰의 P1 지적이 모두 반영됐는가.{{request_rule}}

## 등급과 판정
```

```markdown
4. 수정 라운드면 이전 리뷰의 P1 지적이 모두 반영됐는가.{{request_rule}}

{{extra}}## 등급과 판정
```

**Edit** `herdr-team/templates/review-round.md`

```markdown
2. 새 커밋이 새 P1 을 만들었는지.
```

```markdown
2. 새 커밋이 새 P1 을 만들었는지. 고친 함수·데이터를 읽는 다른 호출처와 출력 경로(다른 화면, 내보내기, 다른 API·작업)도 본다. 고친 방법이 만든 새 경계 조건(잠금 대기의 누적, 시각·순서, 늦은 응답)도 본다.
```

**Edit** `herdr-team/templates/worker-rules.md`

```markdown
보고서 `{{report}}` 는 늘 고쳐도 된다. 그 밖의 파일을 고쳐야 하면 멈추고 프리앰블의 ask 명령으로 메인에게 묻는다(관제가 메인에 올리고, 메인이 답하거나 새 태스크로 나눈다).
```

```markdown
보고서 `{{report}}` 는 늘 고쳐도 된다. 그 밖의 파일을 고쳐야 하면 멈추고 프리앰블의 ask 명령으로 메인에게 묻는다(관제가 메인에 올리고, 메인이 답하거나 새 태스크로 나눈다).

보고서 경로, 커밋 형식, done 방법은 이 사양이 프로젝트 문서(AGENTS.md, CLAUDE.md 등)의 다른 규칙보다 앞선다(Orca 시절 문서의 다른 보고서 경로·이슈 트래커 갱신 규칙과 부딪칠 때).
```

- [ ] **Step 4: 통과 확인**

Run: `cd herdr-team && python3 -m unittest tests.test_review tests.test_start tests.test_wording 2>&1 | tail -3` 그다음 `bash herdr-team/tests/run.sh 2>&1 | tail -3`(저장소 루트에서, 백그라운드로 하나만, 10–15분)
Expected: 둘 다 `OK`. 지금 시험의 문구 고정(`4. 수정 라운드면 … 반영됐는가.\n\n## 등급과 판정\n`, `(리뷰 사전 검사가 수정 라운드로 돌려보낸다).\n\n## 테스트\n`, `review-round.md` 의 자리 목록)은 자리가 비면 그대로라 고치지 않아도 통과한다.

- [ ] **Step 5: 정적 확인과 커밋**

```bash
python3 - <<'PY'
import ast, pathlib
for f in ["herdr-team/lib/hteam/compose.py", "herdr-team/lib/hteam/review.py", "herdr-team/tests/test_review.py",
          "herdr-team/tests/test_wording.py"]:
    ast.parse(pathlib.Path(f).read_text(encoding="utf-8"), feature_version=(3, 11))
PY
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews'
FILES="herdr-team/lib/hteam/compose.py herdr-team/lib/hteam/review.py herdr-team/templates/review-prompt.md herdr-team/templates/review-round.md herdr-team/templates/worker-rules.md herdr-team/tests/test_review.py herdr-team/tests/test_wording.py"
git add -- $FILES
git commit -m "feat(herdr-team): 리뷰 프롬프트 우선순위 줄·프로젝트 점검표·이슈 줄·라운드 절 2, 워커 사양 우선순위·이슈 줄" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- $FILES
```

Expected: ast 오류 없음, grep 빈 출력. 구현자는 여기서 멈춘다(컨트롤러가 `scripts/codex-review.sh commit <sha>`).

---

### Task 8: Redmine 연동(사건 큐, 닫는 때, `hteam redmine-sync`, 키 읽기·가리기, status·doctor, `#N`)

설계 8.12 전부와 8.8·8.11 의 Redmine 줄, 9.2 의 Redmine 점검, 5.1 의 "회귀 수정·묶음 정리 태스크는 원인 태스크의 `issue` 를 물려받는다", 11.4 일괄 승인 줄과 progress 태스크 줄의 `#N` 을 만든다. 선택 기능이다: `config.toml` 에 `[redmine]`(Task 2 의 `Config.redmine`)이 있을 때만 켜지고, 태스크 사양에 `issue`(Task 2 의 `Spec.issue`)가 있을 때만 그 이슈를 바꾼다. 이슈 상태와 노트는 관제(프로그램)만 바꾼다. 워커·리뷰어는 Redmine 을 바꾸지 않는다(그래서 API 키가 프롬프트에 들어가지 않는다). 관제는 사건마다 `state/redmine/queue/<순번>.json` 을 원자적으로 쓰기만 하고, HTTP 는 전송 자식 `hteam redmine-sync` 하나가 새 모듈 `redmine.py` 에서만 한다(헤더의 모듈 경계). 키는 전송 자식과 doctor 만 읽는다. 시험의 Redmine 은 시험 프로세스 안의 `http.server` 가짜 서버다(실제 Redmine·네트워크를 쓰지 않는다).

이 태스크는 Task 2(`Config.redmine`·`Spec.issue`·tasks.toml `issue` 의 plan apply 복사), Task 3(`workspace.task_root`), Task 4–5(작업 공간 시작·병합 — 병합 노트 시험 하나가 쓴다), Task 6(`testgate.child_env` 가 `key_env` 를 뺀다), Task 7(이슈 줄)이 앞에 있다고 본다. 테스트 명령·setup·teardown 환경에서 `key_env` 를 빼는 것은 Task 6 이 이미 했다(이 태스크는 다시 하지 않는다).

**Files:**
- Create: `herdr-team/lib/hteam/redmine.py`, `herdr-team/tests/test_redmine.py`
- Modify: `herdr-team/lib/hteam/paths.py`(Redmine 경로), `herdr-team/lib/hteam/drive.py`(사건 자리·`redmine_step`·`redmine_done`·tick·reap_jobs, `create_task` 의 `issue`, `_make_followups` 의 물려받기, `apply_plan` progress 의 `#N`), `herdr-team/lib/hteam/tasks.py`(`run_work` 의 start 사건, `drop` 의 drop 사건), Task 5 의 병합 성공 지점(merged 사건), `herdr-team/lib/hteam/approval.py`(`link` 의 `root`, `_line` 의 `#N`, `_apply` 의 닫기), `herdr-team/lib/hteam/coord.py`(status 의 `redmine`), `herdr-team/lib/hteam/setup.py`(doctor 의 Redmine 점검), `herdr-team/lib/hteam/cli.py`(COMMAND_MODULES 의 `redmine`)
- Test: `herdr-team/tests/test_redmine.py`(새로), `herdr-team/tests/test_approval.py`·`herdr-team/tests/test_drive_flows.py`(Append)

**Interfaces:**
- Consumes: `config.Config.redmine`(`url`·`key_env`·`env_file`·`status`), `specs.load(p, tid).issue`·`.depends_on`·`.front["plan_key"]`·`specs.render(front=…)`, `state.all_states`·`state.require`·`state.current_round`·`state.latest_attempt`, `workspace.task_root(p, st)`(Task 3), `approval.AGENT_NAMES`, `review.FINDINGS_RE`·`review.BROAD_P1_RE`·`review.NONE_LINE_RE`, `paths.report_rel`·`review_rel`, `roles.require_drive`, `util.now`·`age_seconds`·`write_atomic`·`write_json`·`read_json`·`flock`, `gitio.tracked`, `Drive.spawn`·`running`·`log`·`progress`·`isolated`, `testgate.TESTER_ROLE`, Task 5 의 병합 성공 지점과 상태 `workspace.base_branch`·`workspace.merge`.
- Produces:
  - `paths.Project` 의 새 경로: `redmine_dir`(`state/redmine`), `redmine_queue`(`state/redmine/queue`), `redmine_failed`(`state/redmine/failed`), `redmine_lock`(`state/redmine/queue.lock`), `redmine_sync_lock`(`state/redmine/sync.lock`, 전송자 하나만, Rules 6), `redmine_seq`(`state/redmine/seq`), `redmine_status`(`state/redmine/status.json`). 만드는 것은 `enqueue`·`sync` 다(꺼져 있으면 폴더를 만들지 않는다).
  - `redmine.py` 상수: `EVENTS = {"start": "start", "done": "done", "changes": "changes", "approve": None, "merged": None, "closed": "closed", "drop": None}`(사건 → `[redmine].status` 의 키, None 은 상태를 바꾸지 않는다), `RETRY_S = (60, 120, 300, 600)`(그 뒤는 600), `GIVE_UP_S = 86400`, `TIMEOUT_S = 10`(PUT), `DOCTOR_TIMEOUT_S = 5`(GET), `SUMMARY_MAX = 300`, `P1_LINES = 5`, `P1_WIDTH = 200`, `MASK = "***"`, `BUSY_TEXT = "다른 hteam redmine-sync 가 보내는 중이라 보내지 않았다(state/redmine/sync.lock)"`.
  - `redmine.issue_of(p, tid) -> str | None`: 그 태스크 사양의 `issue`(사양을 읽지 못하면 None).
  - `redmine.enqueue(p, cfg, st_or_tid, event, *, notes: str, issue: str | None = None) -> dict | None`: 헤더 계약의 `enqueue(p, cfg, st_or_tid, event, **fields)` 다(fields 는 `notes`·`issue`). `cfg.redmine` 이 None 이거나 issue(주지 않으면 `issue_of`)가 None 이면 아무것도 쓰지 않고 None. 아니면 큐 항목을 쓰고 돌려준다. 모르는 사건은 exit 2 `bad_redmine_event`(관제 내부 오류).
  - 큐 항목(헤더 "기록·필드에 더하는 것"): `{"seq": 7, "issue": "5712", "task": "T-001", "event": "changes", "status_id": 4, "notes": "…", "at": "2026-11-12T01:02:03Z"}`, 다시 보낼 때 `tries`(보낸 횟수)·`next_at`(UTC)·`last_error`(가린 글) 를 더한다. failed 항목은 같은 꼴에 `error`(가린 글).
  - `redmine.close_for(p, cfg, tid) -> list[dict]`: 태스크 tid 가 `done` 이 된 뒤 닫을 이슈마다 `closed` 항목을 쓰고 그 목록을 돌려준다(Rules 4). `cfg.redmine` 이 None 이면 빈 목록. 태스크가 `done` 이 되는 두 경로(관제의 `Drive.after_accept`, 사용자 일괄 승인·결정 복구의 `approval._apply`)가 이 한 함수를 부른다(Rules 2 의 7, Codex 계획 리뷰 r1).
  - `redmine.due(p) -> bool`: 지금 보낼 항목이 있나(같은 이슈의 맨 앞 항목 가운데 `next_at` 이 없거나 지났거나, 읽지 못하는 항목이 있다).
  - `redmine.read_key(p, cfg) -> str | None`, `redmine.mask(text: str, key: str | None) -> str`(key 가 있으면 그 값을 모두 `***` 로).
  - `redmine.sync(p, cfg) -> dict`: 전송(Rules 6). 결과 `{"busy": false, "sent": [항목 요약], "failed": [항목 요약], "retry": [항목 요약], "pending": <남은 큐 수>}`. 실행 내내 `p.redmine_sync_lock` 을 비차단 `fcntl.flock`(`LOCK_EX | LOCK_NB`)으로 쥔다. 못 쥐면(다른 `hteam redmine-sync` 가 보내는 중이다. 예: 관제가 다시 떠 새 관제의 자식이 앞 관제가 남긴 자식과 겹친다) 큐를 읽지도 보내지도 않고 `{"busy": true, "message": "다른 hteam redmine-sync 가 보내는 중이라 보내지 않았다(state/redmine/sync.lock)", "sent": [], "failed": [], "retry": [], "pending": <queue 의 *.json 수>}` 를 돌려준다(Codex 계획 리뷰 r1). 항목 요약은 `{"seq", "issue", "event", "status"}`(+ failed·retry 는 `"error"`). `status` 는 HTTP 상태 정수 또는 `"연결 실패"`·`"키 없음"`·`"읽기 실패"`. 읽지 못한 항목의 `issue`·`event` 는 `"?"`.
  - `redmine.summary(p, cfg) -> dict`: `{"enabled": true, "pending": <queue 의 *.json 수>, "failed": <failed 의 파일 수>, "last_error": <status.json 의 last_error 또는 null>}`. 키는 들지 않는다.
  - `redmine.checks(p, cfg) -> list[dict]`: doctor 점검 셋(Rules 9).
  - `state/redmine/status.json`: 전송 한 번이 끝날 때 `{"at": <UTC>, "last_error": <글 또는 null>}`. 이번 전송에 실패(failed·retry)가 있으면 그 마지막 글(`#<N> <사건> <상태>: <글 200자>`, 가림. 키 없음이면 키 없음 글), 실패 없이 하나라도 보냈으면 null, 아무것도 보내지 않았으면 앞 값을 그대로 둔다. 느슨하게 읽는다(깨졌으면 last_error null).
  - CLI `hteam redmine-sync`(관제만. 관제 밖은 exit 5 `drive_only`): `[redmine]` 이 없으면 exit 2 `redmine_off`(`config.toml 에 [redmine] 이 없다(Redmine 연동이 꺼져 있다)`). 성공 exit 0 과 `sync` 결과(보내기 실패가 있어도, `busy` 여도 0).
  - `Drive.redmine_step() -> None`(틱 단계, `reap_jobs` 바로 뒤): `[redmine]` 이 있고 `due(p)` 이고 자식 `redmine` 이 없으면 `self.spawn("redmine", ["redmine-sync"])`.
  - `Drive.redmine_done(code: int, out: dict, err: str) -> None`(`reap_jobs` 가 키 `redmine` 자식에 부른다): failed·retry 항목마다 drive.log `redmine #<N> <사건> 실패 <상태>`(설계 8.11), failed 항목마다 progress `Redmine 이슈 #<N> 갱신 실패(<사건>, <상태>): <error 200자>. .herdr-team/state/redmine/failed/<NNNNNN>.json 에 남겼다`. code 가 0 이 아니면 drive.log `redmine-sync 실패(exit <code>): <err 끝 200자>`. `busy` 결과는 목록이 비어 아무것도 쓰지 않는다(다음 틱의 `redmine_step` 이 다시 띄운다).
  - `Drive.create_task(…, issue: str | None = None)`: 있으면 사양 front matter 에 `issue`(`plan: append` 와 함께 쓸 수 있다).
  - `approval.link(p, tid, root=None)`: 보고서를 `root`(없으면 `p.root`)에서 읽는다. 규칙은 그대로(마지막 claude.ai URL, `design_system_url`·디자인 시스템 URL 제외, 없으면 보고서 경로).
  - 일괄 승인 줄: `- T-001 #5712 r1 [디자인] 로그인 화면: <링크>`(issue 가 있을 때만 ID 뒤 ` #N`). progress `기획 적용:` 의 태스크 줄: `T-002 #5712 [developer] 저장 모듈`. 둘 다 `[redmine]` 과 상관없다(설계 5.1 "일괄 승인 줄에 보인다" 는 `[redmine]` 조건이 없다).
  - `hteam status`: `[redmine]` 이 있을 때만 `"redmine": summary(p, cfg)`.
  - doctor 점검(경고만, `[redmine]` 이 있을 때만): `redmine_key`, `redmine_api`, `redmine_env_file`(`env_file` 이 있을 때만).
  - 노트 문구(원문, 설계 8.12 표. `<직무 title>` 은 `cfg.role_title`, `<Claude·Codex>`·`<리뷰어>` 는 `approval.AGENT_NAMES`):
    - start: `herdr-team: T-xxx rN 작업을 시작했다(<직무 title>, <Claude·Codex>).`
    - done: `T-xxx rN 작업을 마쳤다. 요약: <done summary 앞 300자>. 보고서: <보고서 경로>`
    - changes: `T-xxx rN 리뷰: 수정 요청(<리뷰어 또는 hteam>). 막는 지적: <P1 줄들>. 리뷰: <docs/reviews/T-xxx/rN.md>`(P1 줄은 최대 5개, 줄마다 앞 목록 표시 `- `·끝 마침표 하나를 떼고 200자, ` / ` 로 잇는다. 없으면 `(없음)`)
    - approve: `T-xxx rN 리뷰: 승인(<리뷰어>).` 보고서에 claude.ai 아티팩트 URL 이 있으면 뒤에 ` 아티팩트: <URL>`
    - merged: `기준 브랜치 <이름> 에 병합했다(<sha 7자>).`
    - closed: 묶음이면 `묶음 <key> 테스트(T-yyy)가 끝나 종료한다.`(key 는 tester 사양의 `plan_key`, 없으면 tester ID), 아니면 `T-xxx 가 끝나 종료한다.`
    - drop: `T-xxx 를 버렸다.`

**Rules:**

1. 큐 쓰기(설계 8.12 의 전송 첫 문장): `enqueue` 는 `state/redmine/queue.lock` 의 flock 안에서 순번을 정한다(`seq` 파일의 수 + 1. 파일이 없거나 읽지 못하면 `queue/`·`failed/` 의 가장 큰 번호 + 1). `seq` 를 먼저 쓰고 항목을 임시 파일 + `os.replace` 로 `queue/<NNNNNN>.json`(6자리)에 쓴다. 그 잠금 안에서 다른 잠금을 잡지 않는다. `status_id` 는 `cfg.redmine.status[EVENTS[event]]`(None 이면 null). `at` 은 `util.now()`. 키는 큐에 쓰지 않는다.
2. 사건 자리(관제 안에서만 불린다. 그 자리의 상태 전이를 쓴 직후이고 원래 다음 일 전이다. 설계 8.12 한계: 그 사이에 죽으면 사건이 빠진다):
   1. start: `tasks.run_work` 가 `state.move(st, "working", "launched", …)` 를 쓴 owned 블록을 마친 직후(임시 워커·고정 에이전트·같은 라운드 복구·이어 붙이기 모두. 그래서 start·fix·수정 대기열 드레인·관제 fix 가 같은 자리를 지난다). 노트의 N 은 그 라운드, 에이전트는 라운드의 `agent`. 닫은 이슈의 태스크에 새 라운드가 시작되면 이 사건이 상태를 `start` 로 되돌린다(따로 하지 않는다).
   2. done: `Drive.on_work_done` 의 succeeded 갈래에서 `start_review` 전(상태가 working 일 때만. 아니면 지금처럼 돌아간다). 요약은 worker_done 본문의 `summary`, 보고서는 본문의 `report_path`(없으면 `report_rel(tid)`).
   3. changes(리뷰어): `Drive.finish_review` 의 `res["status"] == "changes"` 갈래에서 `_reviewer_changes` 전. 리뷰어는 그 라운드의 마지막 리뷰 시도 `agent`(`approval.AGENT_NAMES`, 없으면 `리뷰어`). P1 줄은 `<task_root>/docs/reviews/T-xxx/rN.md` 의 `## 지적 사항` 절(`review.FINDINGS_RE`)에서 `review.BROAD_P1_RE` 에 맞고 `review.NONE_LINE_RE` 가 아닌 줄(읽지 못하면 `(없음)`).
   4. changes(hteam 반려): `Drive.on_review_result` 의 code 0·`status == "changes"` 갈래에서 `hteam_changes` 전. 이름은 `hteam`, P1 줄은 그 라운드 기록의 `prechecks` 그대로(사전 검사 문제, 관문 반려의 `review.GATE_PROBLEM`, Task 6 의 `full_if` full 반려 `GATE_FULL_PROBLEM`).
   5. approve: `Drive.finish_review` 의 `res["status"] == "approved"` 갈래에서 `accept_task` 전. 아티팩트는 `approval.link(p, tid, root=workspace.task_root(p, st))` 가 `https://claude.ai/` 로 시작할 때만(11.4 와 같은 규칙, 작업 공간 태스크는 병합 전이라 작업 루트의 보고서를 읽는다).
   6. merged: `tasks.accept` 안, Task 5 의 `workspace.merge(p, cfg, st)` 가 `{"result": "merged"}` 를 돌려주고 태스크 상태의 `workspace.merge` 에 병합 커밋 sha 를 쓴 직후(병합은 늘 `tasks.accept` 한 곳에서 일어난다. 관제 판정·큐 accept·관제 안의 CLI accept 가 모두 지난다, Task 5 Rules 1). 이름은 상태의 `workspace.base_branch`.
   7. closed: `Drive.after_accept` 가 `res["status"] == "done"` 이면 직무별 다음 자리(`apply_plan`·`batch_done`) 뒤, `start_ready` 전에 `redmine.close_for(p, cfg, tid)`. 묶음 처리가 만든 회귀 수정·정리 태스크가 먼저 생겨야 그 이슈를 미룬다(Rules 4). 승인 직무(designer·director 등)는 사용자 일괄 승인으로 `done` 이 된다: `design-decide`(큐 실행 `_x_design_decide`)와 관제 재확인의 결정 복구가 부르는 `approval._apply` 는 `tasks.accept` 를 직접 부르고 `after_accept` 를 거치지 않는다(Codex 계획 리뷰 r1). 그래서 `_apply` 는 `config.load(p)` 를 한 번 읽고 `accept` 루프에서 `tasks.accept` 가 `status == "done"` 을 돌려준 태스크마다 바로 `redmine.close_for(p, cfg, task)` 를 부른다(같은 함수 하나. 닫을 수 있는가는 Rules 4 그대로라 묶음·같은 이슈의 미루기도 같다). `_apply` 는 관제 안(큐 실행·재확인)에서만 돈다. 이미 끝나 `passed` 로 넘긴 태스크는 다시 닫지 않는다(그 사이 죽어 빠진 사건은 설계 8.12 한계).
   8. drop: `tasks.drop` 이 `dropped` 를 쓴 블록을 마친 직후.
3. 노트는 Interfaces 의 문구 원문이다. 사건마다 `enqueue(p, cfg, st, event, notes=…)` 한 번. 키는 노트·로그·outbox 어디에도 넣지 않는다.
4. 닫는 때(설계 8.12, 사용자 결정) — `close_for(p, cfg, tid)`:
   - 볼 이슈: tid 가 tester(상태 직무가 `testgate.TESTER_ROLE`)면 사양 `depends_on` 가운데 상태 직무가 developer 인 것의 issue(그 순서) → tid 자신의 issue. 아니면 tid 자신의 issue. None 은 빼고 처음 나온 순서로 하나씩.
   - 닫을 수 있다(이슈 N): issue 가 N 인 모든 태스크(상태가 있는 것, 사양을 읽지 못하면 뺀다)가 `done`·`dropped` 이고, 그 가운데 `done` 이고 어느 tester 태스크(상태 직무 tester)의 사양 `depends_on` 에 든 태스크마다 그 tester 들 가운데 `done` 인 것이 하나 있다(묶음 tester 가 drop 되면 그 묶음의 이슈를 닫지 않는다. 사람이 닫는다).
   - 닫을 수 있는 N 마다 `closed` 항목(task 는 tid). 노트: tid 가 tester 이고 N 이 위 첫째 목록(depends_on 의 developer 와 tid)에서 왔으면 묶음 문구(key 는 tid 사양의 `plan_key`, 없으면 tid), 아니면 `<tid> 가 끝나 종료한다.`
   - 같은 이슈를 가진 다른 태스크가 끝나지 않아 미룬 이슈는 그 태스크가 done 이 될 때 그 태스크의 `close_for` 가 다시 본다(따로 기록하지 않는다). 그래서 같은 이슈를 두 번 닫을 수 있다(새 태스크가 다시 열었다가 끝난 경우. 설계 한계의 "노트가 섞인다" 와 같다).
5. issue 물려받기(설계 5.1): `_make_followups` 의 회귀 수정은 원인 태스크(`causes[0]`)의 `issue_of`, 묶음 정리는 그 직무 항목을 낸 태스크(`owners`)가 하나일 때만 그 태스크의 `issue_of` 를 `create_task(issue=…)` 로 넘긴다(원인이 여럿이면 넣지 않는다). 메인이 `unknown_regression` 으로 만드는 회귀 수정(7.7 의 `hteam task new`)은 범위 밖이다.
6. 전송(`sync`, 설계 8.12 의 전송·키):
   1. `queue/*.json` 을 순번 순으로 본다. 읽지 못하거나 꼴이 틀린 항목(dict 가 아님, `seq` 정수·`issue` 숫자 문자열·`event`·`notes`·`at` 문자열이 아님)은 그 파일 그대로 `failed/` 로 옮기고 failed 에 `{"seq": <파일 이름의 수>, "issue": "?", "event": "?", "status": "읽기 실패", "error": "큐 항목을 읽지 못했다: <까닭>"}`.
   2. 이미 막힌 이슈(이번 전송에서 앞 항목이 남았다)면 건너뛴다. `next_at` 이 지금보다 뒤면 그 이슈를 막고 건너뛴다.
   3. 키(`read_key`)가 없으면 보내지 않고 다시 보낼 항목으로(4 의 retry, 상태 `"키 없음"`, 글 `Redmine API 키를 찾지 못했다(<env_file 의 <key_env> | 환경 변수 <key_env>>)`).
   4. 보내기: `PUT <url>/issues/<N>.json`, 본문 `{"issue": {"status_id": <id>, "notes": <노트>}}`(status_id 가 null 이면 `{"issue": {"notes": <노트>}}`), 머리 `Content-Type: application/json`·`X-Redmine-API-Key: <키>`, `urllib.request.urlopen(…, timeout=TIMEOUT_S)`(프록시는 urllib 기본 동작). 2xx 면 항목을 지우고 sent. 4xx 면 `error`(`HTTP <code>: <본문>`)를 더해 `failed/` 로 옮기고 failed(그 이슈를 막지 않는다: 남은 앞 항목이 없으므로 뒤 항목을 보낸다). 오류 글의 차례(Codex 계획 리뷰 r1): 응답 본문 **전체**(5xx 도, 연결 실패의 까닭도)에서 먼저 `mask` 로 키를 가린 **뒤** 앞 200자로 자른다. 자른 뒤 가리면 200자 경계에 걸린 키는 온전한 문자열이 아니라 가려지지 않고 앞부분이 남는다(실패 파일·출력·progress·`status.json` 으로 간다). 5xx·연결 실패(`URLError`·`OSError`·시간 초과, 상태 `"연결 실패"`, 글 `연결 실패: <까닭>`)는 retry: `tries` + 1, `next_at = 지금 + RETRY_S[min(앞 tries, 3)]`, `last_error`(가림)를 써 두고 그 이슈를 막는다. 다만 항목의 `at` 이 `GIVE_UP_S` 를 넘었으면 retry 대신 `error`(`24시간 동안 보내지 못했다: <글>`)로 `failed/` 로 옮기고 failed.
   5. 끝나면 `status.json` 을 쓴다(Interfaces 의 last_error 규칙). 결과를 돌려준다(pending 은 남은 큐 수).
   - 같은 이슈의 뒤 항목은 앞 항목이 남아 있는 동안 보내지 않는다(설계 8.12). 다른 이슈는 막지 않는다. 전송자는 한 번에 하나다: 관제의 자식 키 `redmine`(8.8)은 한 관제 안에서만 막으므로, 관제가 다시 떠 앞 관제의 자식이 살아 있어도 둘이 같은 큐를 돌지 않게 `sync` 가 실행 내내 `sync.lock` 을 비차단으로 쥐고 못 쥐면 `busy` 로 바로 끝난다(Interfaces, Codex 계획 리뷰 r1). 늦은 `start` 가 다른 전송자의 `done` 뒤에 가서 이슈 상태가 되돌아가는 일이 없다. 전송이 성공한 뒤 항목을 지우기 전에 죽으면 같은 노트가 두 번 간다(설계 한계, 고치지 않는다).
7. 키(`read_key`): `env_file` 이 있으면 `p.root / env_file` 만 읽는다: 빈 줄·`#` 줄을 빼고 `KEY=VALUE` 줄(`=` 앞을 strip 해 `key_env` 와 같은 첫 줄), 값은 strip 한 뒤 길이 2 이상이고 앞뒤가 같은 따옴표(`"`·`'`)면 한 겹 벗긴다. 파일을 읽지 못하거나 그 이름이 없으면 None. `env_file` 이 없으면 관제 환경의 `key_env`. 빈 값은 None. 키는 전송 자식과 doctor 만 읽는다(관제 본체·`enqueue`·status 는 읽지 않는다).
8. 관제(설계 8.8·8.11): `Drive.tick` 은 `reap_jobs` 와 두 번째 `heartbeat` 사이에 `redmine_step` 을 한다(격리 키 `redmine`). `reap_jobs` 는 키 `redmine` 자식을 `job:redmine` 격리 안에서 `redmine_done(code, _last_json(out) or {}, err)` 로 처리한다. `redmine_step` 은 꺼져 있으면 아무것도 하지 않는다(폴더도 만들지 않는다).
9. doctor(설계 9.2): 설정을 한 번 읽고(읽지 못하면 Redmine 점검을 하지 않는다) `[redmine]` 이 있으면 `redmine.checks` 를 지금 점검 목록 끝(`codex_browser` 뒤)에 더한다. 셋 다 `level: "warning"`:
   - `redmine_key`: 키를 찾았나. detail `키를 찾았다(<env_file> | 환경 변수 <key_env>)` / `키를 찾지 못했다: <env_file> 의 <key_env> | 환경 변수 <key_env>`. 값은 보이지 않는다.
   - `redmine_api`: 키가 있으면 `GET <url>/users/current.json`(머리 `X-Redmine-API-Key`, `DOCTOR_TIMEOUT_S`)이 200 인가. detail `200`·`HTTP <code>`·`연결 실패: <까닭>`(가림). 키가 없으면 ok false 와 `키가 없어 보지 않았다`.
   - `redmine_env_file`(env_file 이 있을 때만): `gitio.tracked(p.root, env_file)` 가 거짓이면 ok. 추적하면 detail `git 이 추적하는 파일이다. .gitignore 에 넣고 git rm --cached -- <env_file> 한다`.
10. status(설계 8.12): `coord.status` 는 설정을 읽었고 `cfg.redmine` 이 있을 때만 `out["redmine"] = redmine.summary(p, cfg)`. 키를 읽지 않는다(키 없음은 `last_error` 로 보인다).
11. `#N`: `approval._line` 은 사양의 issue 가 있으면 `f"- {id} #{issue} r{round} [{직무 title}] {title}: {link}"`, 없으면 지금 그대로. `Drive.apply_plan` 의 progress 태스크 줄은 `f"{sp.id}{' #' + sp.issue if sp.issue else ''} [{sp.role}] {sp.title}"`(그 뒤 ` ← …` 는 그대로).
12. 회귀(설계 1장 "기본값은 지금 동작 그대로"): `[redmine]` 이 없으면 `state/redmine/` 을 만들지 않고, 자식을 띄우지 않고, status 에 `redmine` 키가 없고, doctor 에 `redmine_*` 점검이 없다. `[redmine]` 이 있어도 issue 가 없는 태스크는 큐에 아무것도 쓰지 않는다.

핵심 조각(그대로 옮기지 않아도 된다) — 전송 순서와 재시도(Rules 6):

```python
def sync(p, cfg) -> dict:
    p.redmine_dir.mkdir(parents=True, exist_ok=True)
    with open(p.redmine_sync_lock, "a") as fh:      # 전송자 하나만: 실행 내내 쥔다(관제가 다시 떠도 둘이 돌지 않는다)
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"busy": True, "message": BUSY_TEXT, "sent": [], "failed": [], "retry": [],
                    "pending": len(list(p.redmine_queue.glob("*.json")))}
        return {"busy": False, **_send_all(p, cfg)}


def _put(cfg, item: dict, key: str) -> tuple[int | str, str]:
    """PUT 하나. (HTTP 상태 또는 "연결 실패", 가린 뒤 자른 오류 글)."""
    try:
        with urllib.request.urlopen(_request(cfg, item, key), timeout=TIMEOUT_S) as resp:
            return resp.status, ""
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        return exc.code, f"HTTP {exc.code}: {mask(body, key)[:200]}"   # 전체를 가린 뒤 자른다(자르고 가리면 키 앞부분이 남는다)
    except (urllib.error.URLError, OSError) as exc:
        return "연결 실패", f"연결 실패: {mask(str(exc), key)[:200]}"


def _send_all(p, cfg) -> dict:
    key, out, blocked, last = read_key(p, cfg), {"sent": [], "failed": [], "retry": []}, set(), None
    for path in sorted(p.redmine_queue.glob("*.json")):
        item, why = _read_item(path)
        if item is None:
            _move(path, p.redmine_failed / path.name, None)            # 파일 그대로 옮긴다
            out["failed"].append({"seq": int(path.stem), "issue": "?", "event": "?", "status": "읽기 실패",
                                  "error": f"큐 항목을 읽지 못했다: {why}"})
            continue
        issue = item["issue"]
        if issue in blocked or (item.get("next_at") and age_seconds(item["next_at"]) < 0):
            blocked.add(issue)
            continue
        status, error = ("키 없음", _no_key_text(cfg)) if key is None else _put(cfg, item, key)
        if isinstance(status, int) and 200 <= status < 300:
            path.unlink()
            out["sent"].append(_brief(item, status))
        elif isinstance(status, int) and 400 <= status < 500:
            _fail(p, path, item, mask(error, key))
            out["failed"].append(_brief(item, status, mask(error, key)))
        elif age_seconds(item["at"]) >= GIVE_UP_S:
            _fail(p, path, item, f"24시간 동안 보내지 못했다: {mask(error, key)}")
            out["failed"].append(_brief(item, status, mask(error, key)))
        else:
            tries = int(item.get("tries") or 0)
            item.update(tries=tries + 1, next_at=_later(RETRY_S[min(tries, len(RETRY_S) - 1)]),
                        last_error=mask(error, key))
            write_json(path, item)
            blocked.add(issue)
            out["retry"].append(_brief(item, status, item["last_error"]))
        if status == "키 없음":
            last = _no_key_text(cfg)
        elif not (isinstance(status, int) and status < 300):
            last = f"#{issue} {item['event']} {status}: {mask(error, key)[:200]}"
    if out["failed"] or out["retry"] or out["sent"]:   # 아무것도 보내지 않았으면 앞 값을 둔다
        _write_status(p, last)                         # 실패가 없으면 last 는 None(보냈다)
    return {**out, "pending": len(list(p.redmine_queue.glob("*.json")))}
```

핵심 조각 — 닫을 수 있는가(Rules 4):

```python
def _closable(p, issue: str, states: list[dict]) -> bool:
    mine = [s for s in states if issue_of(p, s["id"]) == issue]
    if not mine or any(s["status"] not in ("done", "dropped") for s in mine):
        return False
    testers = [(s, specs.load(p, s["id"]).depends_on) for s in states if s.get("role") == TESTER_ROLE]
    for s in mine:
        if s["status"] != "done":
            continue
        covering = [t for t, deps in testers if s["id"] in deps]
        if covering and not any(t["status"] == "done" for t in covering):
            return False
    return True
```

- [ ] **Step 1: 실패하는 테스트 작성**

**Create** `herdr-team/tests/test_redmine.py`

```python
"""Redmine 연동(설계 8.12, 7단계): 사건 큐, 닫는 때, 전송 자식 `hteam redmine-sync`, 키 읽기·가리기, status·doctor.

Redmine 은 이 프로세스 안의 가짜 HTTP 서버다(요청을 남기고 이슈마다 응답 코드를 정한다). 관제는 이 프로세스 안에서 만든다
(make_drive). 리뷰·전송 자식은 실제 hteam 하위 프로세스다(설계 8.8). 큐 항목의 꼴은 계획 헤더의 "기록·필드에 더하는 것" 이다."""
import json
import re
import socket
import threading
import time
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from tests.helpers import BASE_CONFIG, WS_CONFIG, TeamCase
from tests.test_drive_flows import FlowCase
from hteam.paths import Project

KEY = "rk-SECRET-7f3a9c1e5b"  # 시험용 가짜 키. 큐·로그·outbox·상태·docs 어디에도 나오면 안 된다
KEY_ENV = "HT_REDMINE_KEY"
STATUS = "status = { start = 2, done = 3, changes = 4, closed = 5 }"
LOCAL_ISO = r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d"
PROXY_ENV = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")


def redmine_table(url: str, env_file: str | None = None) -> str:
    lines = ["", "[redmine]", f'url = "{url}"', f'key_env = "{KEY_ENV}"']
    if env_file:
        lines.append(f'env_file = "{env_file}"')
    lines.append(STATUS)
    return "\n".join(lines) + "\n"


def utc(offset_s: float = 0) -> str:
    """지금부터 offset_s 초 뒤(음수면 앞) UTC 시각(util.now 꼴)."""
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_s)).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(text: str) -> float:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


class FakeRedmine:
    """PUT /issues/<N>.json·GET /users/current.json 을 받는 가짜 Redmine. codes[이슈] 는 그 이슈에 차례로 낼 응답 코드
    (다 쓰면 204). 요청마다 {method, path, key, body, type} 를 남긴다. 4xx·5xx 본문에는 받은 키를 넣는다(가리기 시험).
    pads[이슈] 는 그 본문에서 키 앞에 둘 글자 수(200자 자르기 경계 시험). hold() 뒤의 PUT 은 요청을 남긴 뒤 release() 까지
    응답을 미룬다(entered 는 PUT 을 하나라도 받았는지)."""

    def __init__(self):
        self.requests: list[dict] = []
        self.codes: dict[str, list[int]] = {}
        self.pads: dict[str, int] = {}
        self.gate: threading.Event | None = None
        self.entered = threading.Event()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _reply(self, code: int, body: bytes = b"") -> None:
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                key = self.headers.get("X-Redmine-API-Key")
                outer.requests.append({"method": "GET", "path": self.path, "key": key, "body": None, "type": None})
                ok = key == KEY and self.path == "/users/current.json"
                self._reply(200 if ok else 401, b'{"user": {"id": 1}}' if ok else b'{"errors": ["no"]}')

            def do_PUT(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                key = self.headers.get("X-Redmine-API-Key")
                outer.requests.append({"method": "PUT", "path": self.path, "key": key,
                                       "body": json.loads(raw or b"null"), "type": self.headers.get("Content-Type")})
                outer.entered.set()
                if outer.gate is not None:
                    outer.gate.wait(30)
                issue = self.path.removeprefix("/issues/").removesuffix(".json")
                todo = outer.codes.get(issue) or []
                code = todo.pop(0) if todo else 204
                text = "x" * outer.pads.get(issue, 0) + f"bad key {key}"
                self._reply(code, b"" if code < 300 else json.dumps({"errors": [text]}).encode())

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def hold(self) -> None:
        self.gate = threading.Event()

    def release(self) -> None:
        if self.gate is not None:
            self.gate.set()

    def close(self) -> None:
        self.release()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=10)

    def puts(self) -> list[dict]:
        return [r for r in self.requests if r["method"] == "PUT"]


class RedmineMixin:
    """가짜 서버와 큐 폴더 도구. 가짜 서버는 127.0.0.1 이라 프록시를 거치지 않게 한다(no_proxy)."""

    def start_server(self) -> FakeRedmine:
        self.server = FakeRedmine()
        self.addCleanup(self.server.close)
        for name in PROXY_ENV:
            self.env.pop(name, None)
        self.env["no_proxy"] = self.env["NO_PROXY"] = "127.0.0.1,localhost"
        return self.server

    @property
    def redmine_dir(self) -> Path:
        return self.state_dir / "redmine"

    def _items(self, sub: str) -> list[dict]:
        folder = self.redmine_dir / sub
        return [json.loads(f.read_text(encoding="utf-8")) for f in sorted(folder.glob("*.json"))] if folder.is_dir() \
            else []

    def queued(self) -> list[dict]:
        return self._items("queue")

    def failed(self) -> list[dict]:
        return self._items("failed")

    def events(self) -> list[tuple]:
        return [(i["event"], i["issue"], i["status_id"], i["notes"]) for i in self.queued()]

    def put_item(self, seq: int, issue: str, event: str = "start", status_id: int | None = 2, notes: str = "노트",
                 **extra) -> dict:
        folder = self.redmine_dir / "queue"
        folder.mkdir(parents=True, exist_ok=True)
        item = {"seq": seq, "issue": issue, "task": "T-001", "event": event, "status_id": status_id, "notes": notes,
                "at": utc(), **extra}
        (folder / f"{seq:06d}.json").write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
        return item

    def leaks(self, secret: str = KEY) -> list[str]:
        """secret(기본은 키 값)이 든 파일(상태 폴더 전체와 docs). 비어야 한다(설계 8.12: 큐·로그·outbox·프롬프트에 쓰지 않는다)."""
        found = []
        for root in (self.state_dir, self.proj / "docs"):
            if not root.is_dir():
                continue
            for path in root.rglob("*"):
                if path.is_file() and secret.encode() in path.read_bytes():
                    found.append(str(path.relative_to(self.proj)))
        return found

    def log_lines(self) -> list[str]:
        path = self.state_dir / "drive" / "drive.log"
        return path.read_text(encoding="utf-8").splitlines() if path.is_file() else []


class SyncTest(RedmineMixin, TeamCase):
    """전송 자식 `hteam redmine-sync`(설계 8.12 의 전송): 큐 항목은 시험이 직접 쓴다."""

    def setUp(self):
        super().setUp()
        self.start_server()
        self.init_project(BASE_CONFIG + redmine_table(self.server.url))
        self.setup_run()
        self.env[KEY_ENV] = KEY

    def sync(self) -> tuple[int, dict]:
        return self.hteam("redmine-sync")

    def status(self) -> dict:
        code, out = self.hteam("status", as_="main")
        self.assertEqual(code, 0, out)
        return out

    def test_sends_in_order_and_deletes_sent_items(self):
        self.put_item(1, "5712", "start", 2, "시작 노트")
        self.put_item(2, "5712", "approve", None, "승인 노트")  # 상태를 바꾸지 않는 사건은 notes 만 보낸다
        self.put_item(3, "77", "done", 3, "끝 노트")
        code, out = self.sync()
        self.assertEqual(code, 0, out)
        self.assertEqual([e["seq"] for e in out["sent"]], [1, 2, 3])
        self.assertEqual((out["failed"], out["retry"], out["pending"]), ([], [], 0))
        puts = self.server.puts()
        self.assertEqual([r["path"] for r in puts], ["/issues/5712.json", "/issues/5712.json", "/issues/77.json"])
        self.assertEqual([r["body"] for r in puts], [{"issue": {"status_id": 2, "notes": "시작 노트"}},
                                                     {"issue": {"notes": "승인 노트"}},
                                                     {"issue": {"status_id": 3, "notes": "끝 노트"}}])
        self.assertEqual({r["key"] for r in puts}, {KEY})
        self.assertTrue(all(r["type"].startswith("application/json") for r in puts), puts)
        self.assertEqual(self.queued(), [])
        self.assertEqual(self.status()["redmine"], {"enabled": True, "pending": 0, "failed": 0, "last_error": None})
        self.assertEqual(self.leaks(), [])

    def test_client_error_moves_item_to_failed_with_key_masked(self):
        self.server.codes["998"] = [422]
        self.put_item(1, "998", "start", 2, "a")
        self.put_item(2, "998", "done", 3, "b")
        code, out = self.sync()
        self.assertEqual(code, 0, out)
        self.assertEqual([(e["seq"], e["issue"], e["event"], e["status"]) for e in out["failed"]],
                         [(1, "998", "start", 422)])
        self.assertEqual([e["seq"] for e in out["sent"]], [2])  # 앞 항목이 failed 로 빠져 남지 않았다
        [bad] = self.failed()
        self.assertEqual((bad["seq"], bad["issue"], bad["event"], bad["notes"]), (1, "998", "start", "a"))
        self.assertIn("422", bad["error"])
        self.assertIn("***", bad["error"])  # 응답 본문의 키 값을 가렸다
        self.assertNotIn(KEY, json.dumps(out, ensure_ascii=False))
        self.assertEqual(self.queued(), [])
        st = self.status()["redmine"]
        self.assertEqual((st["pending"], st["failed"]), (0, 1))
        self.assertIn("422", st["last_error"])
        self.assertEqual(self.leaks(), [])

    def test_server_error_keeps_item_and_holds_later_items_of_that_issue(self):
        self.server.codes["1"] = [503]
        self.put_item(1, "1", "start", 2, "a")
        self.put_item(2, "1", "done", 3, "b")
        self.put_item(3, "2", "start", 2, "c")
        before = time.time()
        code, out = self.sync()
        self.assertEqual(code, 0, out)
        self.assertEqual([(e["seq"], e["issue"], e["status"]) for e in out["retry"]], [(1, "1", 503)])
        self.assertEqual([e["seq"] for e in out["sent"]], [3])  # 다른 이슈는 막지 않는다
        self.assertEqual(out["pending"], 2)
        self.assertEqual([r["path"] for r in self.server.puts()], ["/issues/1.json", "/issues/2.json"])
        first, second = self.queued()
        self.assertEqual((first["seq"], first["tries"]), (1, 1))
        self.assertAlmostEqual(parse_utc(first["next_at"]) - before, 60, delta=5)
        self.assertIn("503", first["last_error"])
        self.assertEqual(second["seq"], 2)
        self.assertNotIn("tries", second)  # 같은 이슈의 뒤 항목은 보내지 않았다
        code, out = self.sync()  # 아직 다시 보낼 때가 아니다
        self.assertEqual(code, 0, out)
        self.assertEqual((out["sent"], out["retry"], out["failed"]), ([], [], []))
        self.assertEqual(len(self.server.puts()), 2)
        self.assertIn("503", self.status()["redmine"]["last_error"])

    def test_retry_intervals_grow_to_ten_minutes(self):
        for tries, wait in ((0, 60), (1, 120), (2, 300), (3, 600), (7, 600)):
            with self.subTest(tries=tries):
                for f in (self.redmine_dir / "queue").glob("*.json"):
                    f.unlink()
                self.server.codes["1"] = [503]
                self.put_item(1, "1", tries=tries, next_at=utc(-1), last_error="앞 실패")
                before = time.time()
                code, out = self.sync()
                self.assertEqual(code, 0, out)
                [item] = self.queued()
                self.assertEqual(item["tries"], tries + 1)
                self.assertAlmostEqual(parse_utc(item["next_at"]) - before, wait, delta=5)

    def test_gives_up_after_24_hours(self):
        self.server.codes["1"] = [503]
        self.put_item(1, "1", at=utc(-25 * 3600), tries=5, next_at=utc(-1), last_error="앞 실패")
        code, out = self.sync()
        self.assertEqual(code, 0, out)
        self.assertEqual([(e["seq"], e["status"]) for e in out["failed"]], [(1, 503)])
        self.assertEqual(self.queued(), [])
        [bad] = self.failed()
        self.assertIn("24시간", bad["error"])

    def test_connection_failure_is_retried(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]  # 닫은 포트: 연결이 거부된다
        (self.team / "config.toml").write_text(BASE_CONFIG + redmine_table(f"http://127.0.0.1:{port}"),
                                               encoding="utf-8")
        self.put_item(1, "1")
        code, out = self.sync()
        self.assertEqual(code, 0, out)
        self.assertEqual([(e["seq"], e["status"]) for e in out["retry"]], [(1, "연결 실패")])
        [item] = self.queued()
        self.assertEqual(item["tries"], 1)
        self.assertIn("연결 실패", item["last_error"])

    def test_missing_key_sends_nothing(self):
        del self.env[KEY_ENV]
        self.put_item(1, "1")
        code, out = self.sync()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.server.requests, [])
        self.assertEqual([(e["seq"], e["status"]) for e in out["retry"]], [(1, "키 없음")])
        [item] = self.queued()
        self.assertEqual(item["tries"], 1)
        self.assertIn(KEY_ENV, self.status()["redmine"]["last_error"])

    def test_env_file_is_read_and_one_quote_layer_stripped(self):
        (self.team / "config.toml").write_text(BASE_CONFIG + redmine_table(self.server.url, ".env"), encoding="utf-8")
        self.env[KEY_ENV] = "env-value-not-used"  # env_file 이 있으면 그 파일에서 읽는다
        cases = ((f'{KEY_ENV}="{KEY}"', KEY), (f"{KEY_ENV}='{KEY}'", KEY), (f"{KEY_ENV}={KEY}", KEY),
                 (f"{KEY_ENV}=\"'{KEY}'\"", f"'{KEY}'"))
        for line, want in cases:
            with self.subTest(line=line):
                (self.proj / ".env").write_text(f"# 주석\nOTHER=1\n{line}\n", encoding="utf-8")
                self.server.requests.clear()
                self.put_item(1, "1")
                code, out = self.sync()
                self.assertEqual(code, 0, out)
                self.assertEqual([r["key"] for r in self.server.puts()], [want])

    def test_unreadable_item_moves_to_failed(self):
        folder = self.redmine_dir / "queue"
        folder.mkdir(parents=True)
        (folder / "000001.json").write_text("{깨짐", encoding="utf-8")
        self.put_item(2, "1")
        code, out = self.sync()
        self.assertEqual(code, 0, out)
        self.assertEqual([e["seq"] for e in out["sent"]], [2])
        self.assertEqual([(e["seq"], e["status"]) for e in out["failed"]], [(1, "읽기 실패")])
        self.assertTrue((self.redmine_dir / "failed" / "000001.json").is_file())
        self.assertFalse((folder / "000001.json").exists())

    def test_one_sender_at_a_time(self):
        # 관제가 다시 떠 앞 관제의 전송 자식이 살아 있어도 둘이 같은 큐를 돌지 않는다(sync.lock, Codex 계획 리뷰 r1)
        self.put_item(1, "5712", "start", 2, "a")
        self.put_item(2, "5712", "done", 3, "b")
        self.put_item(3, "77", "start", 2, "c")
        self.server.hold()
        first = self.hteam_bg("redmine-sync")
        deadline = time.monotonic() + 30
        while not self.server.entered.wait(0.05):  # 첫 전송자가 첫 요청을 보내고 응답을 기다린다(잠금을 쥐었다)
            self.assertIsNone(first.poll(), "첫 전송자가 요청 전에 끝났다")
            self.assertLess(time.monotonic(), deadline)
        code, out = self.sync()
        self.assertEqual(code, 0, out)
        self.assertEqual((out.get("busy"), out["sent"], out["failed"], out["retry"], out["pending"]), (True, [], [], [], 3))
        self.assertEqual(out["message"], "다른 hteam redmine-sync 가 보내는 중이라 보내지 않았다(state/redmine/sync.lock)")
        self.assertEqual(len(self.server.puts()), 1)  # 두 번째는 아무것도 보내지 않았다
        self.server.release()
        code, out = self.finish(first)
        self.assertEqual((code, out.get("busy")), (0, False), out)
        self.assertEqual([e["seq"] for e in out["sent"]], [1, 2, 3])
        self.assertEqual([(r["path"], r["body"]["issue"]["notes"]) for r in self.server.puts()],
                         [("/issues/5712.json", "a"), ("/issues/5712.json", "b"), ("/issues/77.json", "c")])  # 큐 순번 차례
        self.assertEqual(self.queued(), [])

    def test_drive_only_and_needs_redmine_table(self):
        code, out = self.hteam("redmine-sync", as_="main")
        self.assertEqual((code, out["error"]["code"]), (5, "drive_only"), out)
        (self.team / "config.toml").write_text(BASE_CONFIG, encoding="utf-8")
        code, out = self.hteam("redmine-sync")
        self.assertEqual((code, out["error"]["code"]), (2, "redmine_off"), out)


class EventsCase(RedmineMixin, TeamCase):
    """관제 사건(설계 8.12 의 표): 관제를 이 프로세스 안에서 만들고 워커·리뷰어는 agent-act 가 한다."""

    config = BASE_CONFIG

    def setUp(self):
        super().setUp()
        self.start_server()
        self.env[KEY_ENV] = KEY
        self.init_project(self.config + redmine_table(self.server.url))
        self.setup_run()
        self.p = Project(self.proj)
        self._patcher = None
        self.rearm()

    def tearDown(self):
        for job in list(self.d.jobs.values()):  # 남은 자식을 끝낸 뒤 시험 폴더를 지운다
            if job["proc"].poll() is None:
                job["proc"].kill()
            job["proc"].wait(timeout=30)
        super().tearDown()

    def rearm(self) -> None:
        """self.env 를 바꾼 뒤 관제 환경을 다시 건다(관제가 띄우는 자식은 이 환경을 물려받는다)."""
        if self._patcher is not None:
            self._patcher.stop()
        else:
            self.addCleanup(lambda: self._patcher.stop())
        self._patcher = self.in_drive()
        self._patcher.start()
        self.d = self.make_drive()

    def start(self, tid: str = "T-001") -> dict:
        code, out = self.hteam("start", tid)
        self.assertEqual(code, 0, out)
        return out

    def done_msg(self, did: str, outcome: str = "succeeded", summary: str = "끝") -> dict:
        row = self.dispatch_row(did)
        return self.message("worker_done", did, {"dispatch": did, "task": row["task_id"], "outcome": outcome,
                                                 "summary": summary, "report_path": row["report_path"],
                                                 "files_modified": []})

    def wait_jobs(self, limit: float = 60.0) -> None:
        deadline = time.monotonic() + limit
        while True:
            self.d.reap_jobs()
            if not self.d.jobs:
                return
            if time.monotonic() > deadline:
                self.fail(f"자식이 끝나지 않았다: {sorted(self.d.jobs)}")
            time.sleep(0.05)

    def worked(self, tid: str = "T-001", summary: str = "끝", **kw) -> None:
        did = self.work_dispatch(tid)
        code, out = self.act_work(tid, **kw)
        self.assertEqual(code, 0, out)
        self.d.handle(self.done_msg(did, summary=summary))
        self.wait_jobs()

    def reviewed(self, tid: str = "T-001", verdict: str | None = "APPROVE", **kw) -> None:
        did = self.attempt(tid)["dispatch"]
        code, out = self.act_review(tid, verdict, **kw)
        self.assertEqual(code, 0, out)
        self.d.handle(self.done_msg(did))
        self.wait_jobs()


class EventTest(EventsCase):
    def test_round_events_from_start_to_close(self):
        self.write_spec("T-001", front={"issue": "#5712"})  # 앞의 # 는 뗀다(설계 5.1)
        self.start()
        self.worked(summary="가" * 400)
        long = "r1-F1 [P1] src/app.py:1 — " + "길다" * 120 + "."
        lines = [long] + [f"r1-F{i} [P1] src/app.py:{i} — 틀림 {i}." for i in range(2, 7)]
        self.reviewed(verdict="REQUEST_CHANGES",
                      text="## 지적 사항\n" + "".join(f"- {line}\n" for line in lines) + "## 후속\n- r1-F9 [P2] 이름.\n")
        self.worked(report="## r2\n- 아티팩트: https://claude.ai/artifact/abc-9\n")
        self.reviewed(verdict="APPROVE")
        self.assertEqual(self.task_state("T-001")["status"], "done")
        shown = [line.rstrip(".")[:200] for line in lines[:5]]  # 줄 끝 마침표 하나를 떼고 200자, 최대 5줄
        self.assertEqual(self.events(), [
            ("start", "5712", 2, "herdr-team: T-001 r1 작업을 시작했다(개발, Claude)."),
            ("done", "5712", 3, "T-001 r1 작업을 마쳤다. 요약: " + "가" * 300 + ". 보고서: docs/tasks/T-001/report.md"),
            ("changes", "5712", 4, "T-001 r1 리뷰: 수정 요청(Codex). 막는 지적: " + " / ".join(shown)
             + ". 리뷰: docs/reviews/T-001/r1.md"),
            ("start", "5712", 2, "herdr-team: T-001 r2 작업을 시작했다(개발, Claude)."),
            ("done", "5712", 3, "T-001 r2 작업을 마쳤다. 요약: 끝. 보고서: docs/tasks/T-001/report.md"),
            ("approve", "5712", None, "T-001 r2 리뷰: 승인(Codex). 아티팩트: https://claude.ai/artifact/abc-9"),
            ("closed", "5712", 5, "T-001 가 끝나 종료한다."),
        ])
        self.assertEqual([i["seq"] for i in self.queued()], list(range(1, 8)))
        self.assertTrue(all(i["task"] == "T-001" and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", i["at"])
                            for i in self.queued()), self.queued())
        self.assertEqual(self.server.requests, [])  # 관제는 큐에 쓰기만 한다
        self.assertEqual(self.leaks(), [])
        self.d.redmine_step()  # 전송 자식이 순서대로 보낸다
        self.wait_jobs()
        puts = self.server.puts()
        self.assertEqual([r["body"]["issue"].get("status_id") for r in puts], [2, 3, 4, 2, 3, None, 5])
        self.assertEqual({r["path"] for r in puts}, {"/issues/5712.json"})
        self.assertEqual(self.queued(), [])
        self.assertEqual(self.leaks(), [])

    def test_hteam_rejection_is_changes_from_hteam(self):
        self.use_gate()
        self.gate_modes("fail", "fail")
        self.rearm()
        self.write_spec("T-001", front={"issue": "5712"})
        self.start()
        self.worked()
        events = self.events()
        self.assertEqual([e[0] for e in events], ["start", "done", "changes", "start"])
        self.assertEqual(events[2], ("changes", "5712", 4, "T-001 r1 리뷰: 수정 요청(hteam). 막는 지적: hteam 테스트 관문: "
                                                           "quick 이 통과하지 못했다. 리뷰: docs/reviews/T-001/r1.md"))
        self.assertEqual(events[3][3], "herdr-team: T-001 r2 작업을 시작했다(개발, Claude).")

    def test_drop_is_a_note_only(self):
        self.write_spec("T-001", front={"issue": "5712"})
        self.start()
        code, out = self.hteam("drop", "T-001", "--force")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.events(), [("start", "5712", 2, "herdr-team: T-001 r1 작업을 시작했다(개발, Claude)."),
                                         ("drop", "5712", None, "T-001 를 버렸다.")])

    def test_task_without_issue_writes_nothing(self):
        self.write_spec("T-001")
        self.start()
        self.worked()
        self.reviewed()
        self.assertEqual(self.task_state("T-001")["status"], "done")
        self.assertEqual(self.queued(), [])
        self.d.redmine_step()
        self.assertEqual(self.d.jobs, {})


class MergeEventTest(EventsCase):
    """작업 공간 태스크의 병합 노트(설계 8.12 표의 병합, 5.10.6)."""

    config = WS_CONFIG

    def test_merge_note_between_approve_and_close(self):
        self.write_spec("T-001", front={"issue": "5712"})
        code, out = self.hteam("start", "T-001")
        self.assertEqual((code, out.get("status"), out.get("reason")), (0, "waiting", "slot_setup"), out)
        code, out = self.hteam("slot", "prepare", "T-001")
        self.assertEqual(code, 0, out)
        self.start()  # 준비가 끝난 슬롯으로 띄운다
        self.worked()
        self.reviewed()
        st = self.task_state("T-001")
        self.assertEqual(st["status"], "done")
        sha = st["workspace"]["merge"]
        events = self.events()
        self.assertEqual([e[0] for e in events], ["start", "done", "approve", "merged", "closed"])
        self.assertEqual(events[3], ("merged", "5712", None, f"기준 브랜치 main 에 병합했다({sha[:7]})."))


class CloseTest(RedmineMixin, FlowCase):
    """닫는 때(설계 8.12, 사용자 결정): 관제의 accept 뒤(after_accept, res status done)에 정한다. 상태는 시험이 직접 쓴다."""

    config = BASE_CONFIG + redmine_table("http://127.0.0.1:9")

    def done(self, tid: str) -> None:
        self.d.after_accept(tid, {"status": "done", "warnings": []})

    def closes(self) -> list[tuple]:
        return [(i["issue"], i["task"], i["notes"]) for i in self.queued() if i["event"] == "closed"]

    def bundle(self, *, tester_status: str = "done") -> None:
        self.task("T-001", front={"issue": "101"})
        self.task("T-002", front={"issue": "102"})
        self.task("T-003", "tester", tester_status, depends="T-001, T-002", front={"plan_key": "calc-test", "issue": "103"},
                  owns=["tests/calc-test/**", "docs/qa/calc-test.md"])

    def test_tester_done_closes_bundle_issues(self):
        self.bundle(tester_status="working")
        self.review("T-003", 1)
        self.done("T-001")
        self.done("T-002")
        self.assertEqual(self.closes(), [])  # 묶음 tester 가 끝날 때 닫는다
        self.set_state("T-003", status="done")
        self.done("T-003")
        note = "묶음 calc-test 테스트(T-003)가 끝나 종료한다."
        self.assertEqual(self.closes(), [("101", "T-003", note), ("102", "T-003", note), ("103", "T-003", note)])
        self.assertEqual({i["status_id"] for i in self.queued() if i["event"] == "closed"}, {5})

    def test_same_issue_waits_for_the_unfinished_task(self):
        self.task("T-001", front={"issue": "7"})
        self.task("T-002", status="working", front={"issue": "7"})
        self.task("T-003", status="dropped", front={"issue": "7"})  # 버린 태스크는 막지 않는다
        self.done("T-001")
        self.assertEqual(self.closes(), [])
        self.set_state("T-002", status="done")
        self.done("T-002")
        self.assertEqual(self.closes(), [("7", "T-002", "T-002 가 끝나 종료한다.")])

    def test_dropped_tester_leaves_bundle_issue_open(self):
        self.task("T-001", front={"issue": "9"})
        self.task("T-002", "tester", "dropped", depends="T-001", front={"plan_key": "k", "issue": "10"},
                  owns=["tests/k/**", "docs/qa/k.md"])
        self.done("T-001")
        self.assertEqual(self.closes(), [])  # 묶음 tester 가 drop 되면 사람이 닫는다

    def test_regression_task_inherits_issue_and_holds_the_close(self):
        self.bundle()
        item = "r1-F4 [P1] tests/calc-test/test_flow.py::test_add 가 실패한다 — 원인은 T-001 의 add 부호다(T-003 묶음)"
        self.review("T-003", 1, regressions=f"- {item}")
        self.done("T-003")
        self.assertEqual(self.ids(), ["T-001", "T-002", "T-003", "T-004"])
        self.assertEqual(self.spec("T-004").issue, "101")  # 회귀 수정은 원인 태스크의 issue 를 물려받는다(설계 5.1)
        note = "묶음 calc-test 테스트(T-003)가 끝나 종료한다."
        self.assertEqual(self.closes(), [("102", "T-003", note), ("103", "T-003", note)])  # 101 은 회귀 수정이 끝날 때
        self.set_state("T-004", status="done")
        self.done("T-004")
        self.assertEqual(self.closes()[-1], ("101", "T-004", "T-004 가 끝나 종료한다."))

    def test_cleanup_task_inherits_issue_only_from_one_source(self):
        self.bundle()
        self.review("T-001", 1, followups="- r1-F2 [P2] src/t-001/a.py:3 — 중복.")
        self.review("T-003", 1)
        self.done("T-003")
        [cleanup] = [t for t in self.ids() if t not in ("T-001", "T-002", "T-003")]
        self.assertEqual((self.spec(cleanup).title, self.spec(cleanup).issue), ("묶음 정리: calc-test", "101"))

    def test_cleanup_task_from_two_sources_has_no_issue(self):
        self.bundle()
        self.review("T-001", 1, followups="- r1-F2 [P2] src/t-001/a.py:3 — 중복.")
        self.review("T-002", 1, followups="- r1-F1 [P3] src/t-002/b.py:1 — 이름이 길다.")
        self.review("T-003", 1)
        self.done("T-003")
        [cleanup] = [t for t in self.ids() if t not in ("T-001", "T-002", "T-003")]
        self.assertIsNone(self.spec(cleanup).issue)


class DriveStepTest(EventsCase):
    """관제의 전송 자식(설계 8.8·8.11·8.12): 큐가 비지 않았고 전송 자식이 없을 때 하나만 띄운다."""

    def test_spawns_one_child_and_reports_failures(self):
        self.server.codes.update({"999": [404], "5": [503]})
        self.put_item(1, "999", "start", 2, "a")
        self.put_item(2, "5", "start", 2, "b")
        self.d.redmine_step()
        self.assertEqual(list(self.d.jobs), ["redmine"])
        self.d.redmine_step()  # 자식이 도는 동안 하나 더 띄우지 않는다
        self.assertEqual(list(self.d.jobs), ["redmine"])
        self.wait_jobs()
        lines = self.log_lines()
        self.assertTrue(any(re.fullmatch(rf"{LOCAL_ISO} redmine #999 start 실패 404", ln) for ln in lines), lines)
        self.assertTrue(any(re.fullmatch(rf"{LOCAL_ISO} redmine #5 start 실패 503", ln) for ln in lines), lines)
        progress = [e["body"] for e in self.outbox_items() if e["type"] == "progress"]
        self.assertEqual(len(progress), 1, progress)  # 4xx 만 알린다(다시 보낼 항목은 로그만)
        self.assertTrue(progress[0].startswith("Redmine 이슈 #999 갱신 실패(start, 404): "), progress)
        self.assertIn(".herdr-team/state/redmine/failed/000001.json", progress[0])
        self.d.redmine_step()  # 남은 항목은 아직 다시 보낼 때가 아니다
        self.assertEqual(self.d.jobs, {})
        self.assertEqual(self.leaks(), [])

    def test_key_cut_at_200_chars_is_masked_whole(self):
        # 키가 응답 본문의 200자 경계에 걸쳐도 가린 뒤 자르므로 앞부분이 어디에도 남지 않는다(Rules 6 의 4, Codex 계획 리뷰 r1)
        long_key = "rk-LONG-" + "0123456789abcdef" * 2  # 40자
        self.env[KEY_ENV] = long_key
        self.rearm()
        self.server.codes["998"] = [422]
        self.server.pads["998"] = 154  # 본문 {"errors": ["x…bad key <키>"]} 에서 키가 175자째에 시작해 200자 경계에 걸친다
        self.put_item(1, "998", "start", 2, "a")
        self.d.redmine_step()
        self.wait_jobs()
        fragment = long_key[:12]
        [bad] = self.failed()
        self.assertIn("***", bad["error"])
        self.assertNotIn(fragment, bad["error"])
        [line] = [e["body"] for e in self.outbox_items() if e["type"] == "progress"]
        self.assertTrue(line.startswith("Redmine 이슈 #998 갱신 실패(start, 422): "), line)
        self.assertNotIn(fragment, line)
        self.assertEqual(self.leaks(fragment), [])  # 실패 파일·자식 출력·status.json·outbox·drive.log 어디에도 없다

    def test_no_child_without_items(self):
        self.d.redmine_step()
        self.assertEqual(self.d.jobs, {})

    def test_tick_runs_redmine_step_after_reaping(self):
        steps = ("heartbeat", "check_mail", "run_queue", "start_ready", "reap_jobs", "redmine_step", "reset_step",
                 "view_step", "reconcile")
        calls: list[str] = []
        with ExitStack() as stack:
            for name in steps:
                stack.enter_context(mock.patch.object(self.d, name, side_effect=lambda n=name: calls.append(n)))
            self.d.tick()
        self.assertEqual(calls, ["heartbeat", "check_mail", "run_queue", "reap_jobs", "redmine_step", "heartbeat",
                                 "reset_step", "view_step", "reconcile"])


class OffTest(RedmineMixin, TeamCase):
    """회귀: [redmine] 이 없으면 0.4.0 과 같다(큐 폴더·status 키·자식·doctor 점검이 없다)."""

    def test_without_redmine_table_nothing_changes(self):
        self.init_project()
        self.setup_run()
        self.write_spec("T-001", front={"issue": "5712"})
        with self.in_drive():
            d = self.make_drive()
            code, out = self.hteam("start", "T-001")
            self.assertEqual(code, 0, out)
            d.redmine_step()
            self.assertEqual(d.jobs, {})
        self.assertFalse(self.redmine_dir.exists())
        code, out = self.hteam("status", as_="main")
        self.assertEqual(code, 0, out)
        self.assertNotIn("redmine", out)
        code, out = self.hteam("doctor", as_="main")
        self.assertEqual(code, 0, out)
        self.assertFalse([c for c in out["checks"] if c["name"].startswith("redmine")])


class DoctorTest(RedmineMixin, TeamCase):
    """doctor 의 Redmine 점검(설계 9.2, 경고만): 키를 찾는지(값은 보이지 않는다), GET /users/current.json, env_file 추적."""

    def setUp(self):
        super().setUp()
        self.start_server()
        self.init_project(BASE_CONFIG + redmine_table(self.server.url, ".env"))

    def checks(self) -> dict:
        code, out = self.hteam("doctor", as_="main")
        self.assertEqual(code, 0, out)  # Redmine 점검은 경고라 healthy 를 바꾸지 않는다
        self.assertNotIn(KEY, json.dumps(out, ensure_ascii=False))
        return {c["name"]: c for c in out["checks"] if c["name"].startswith("redmine")}

    def test_key_api_and_env_file(self):
        (self.proj / ".env").write_text(f'{KEY_ENV}="{KEY}"\n', encoding="utf-8")
        checks = self.checks()
        self.assertEqual(set(checks), {"redmine_key", "redmine_api", "redmine_env_file"})
        self.assertEqual({c["level"] for c in checks.values()}, {"warning"})
        self.assertTrue(all(c["ok"] for c in checks.values()), checks)
        self.assertEqual([(r["method"], r["path"], r["key"]) for r in self.server.requests],
                         [("GET", "/users/current.json", KEY)])
        self.git("add", "--", ".env")
        self.git("commit", "-q", "-m", "env", "--", ".env")
        checks = self.checks()
        self.assertFalse(checks["redmine_env_file"]["ok"])  # git 이 추적하는 env_file 은 경고

    def test_missing_key_skips_api(self):
        (self.proj / ".env").write_text("OTHER=1\n", encoding="utf-8")
        checks = self.checks()
        self.assertFalse(checks["redmine_key"]["ok"])
        self.assertIn(KEY_ENV, checks["redmine_key"]["detail"])
        self.assertFalse(checks["redmine_api"]["ok"])
        self.assertEqual(self.server.requests, [])

    def test_key_from_environment_without_env_file(self):
        (self.team / "config.toml").write_text(BASE_CONFIG + redmine_table(self.server.url), encoding="utf-8")
        self.env[KEY_ENV] = KEY
        checks = self.checks()
        self.assertEqual(set(checks), {"redmine_key", "redmine_api"})
        self.assertTrue(checks["redmine_key"]["ok"] and checks["redmine_api"]["ok"], checks)


class MaskTest(unittest.TestCase):
    def test_mask_and_constants(self):
        from hteam import redmine
        self.assertEqual(redmine.mask(f"a {KEY} b {KEY}", KEY), "a *** b ***")
        self.assertEqual(redmine.mask("a", None), "a")
        self.assertEqual((redmine.RETRY_S, redmine.GIVE_UP_S, redmine.TIMEOUT_S), ((60, 120, 300, 600), 86400, 10))


if __name__ == "__main__":
    unittest.main()
```

**Append** `herdr-team/tests/test_approval.py`

```python
REDMINE_QUEUE_ONLY = """
[redmine]
url = "http://127.0.0.1:9"
key_env = "HT_REDMINE_KEY"
status = { start = 2, done = 3, changes = 4, closed = 5 }
"""


class RedmineDecisionTest(DecisionCase):
    """사용자 일괄 승인(design-decide)으로 done 이 된 승인 직무 태스크도 이슈를 닫는다(설계 8.12 의 닫는 때, Task 8 Rules 2 의 7,
    Codex 계획 리뷰 r1). approval._apply 는 관제의 after_accept 를 거치지 않는다. 큐에 쓰기만 본다(전송하지 않는다)."""
    config = APPROVAL + REDMINE_QUEUE_ONLY

    def test_decision_accept_queues_the_close(self):
        self.task("T-001", "awaiting_user", title="로그인 화면")
        self.write_spec("T-001", "designer", title="로그인 화면", owns="docs/design/screens/t-001/**",
                        front={"issue": "5712"}, commit=False)
        self.assertEqual(self.review()[1].get("id"), "out-0001")
        code, out = self.decide("out-0001", {})
        self.assertEqual(code, 0, out)
        self.assertEqual(self.task_state("T-001")["status"], "done")
        folder = self.state_dir / "redmine" / "queue"
        items = [json.loads(f.read_text(encoding="utf-8")) for f in sorted(folder.glob("*.json"))] \
            if folder.is_dir() else []
        self.assertEqual([(i["event"], i["issue"], i["task"], i["status_id"], i["notes"]) for i in items],
                         [("closed", "5712", "T-001", 5, "T-001 가 끝나 종료한다.")])


class IssueLineTest(ApprovalCase):
    """일괄 승인 줄의 이슈 번호(설계 5.1·8.12, 7단계): issue 가 있는 태스크만 ID 뒤에 `#N`. [redmine] 과 상관없다."""

    def test_issue_number_follows_task_id(self):
        self.task("T-001", "awaiting_user", title="로그인 화면")
        self.task("T-002", "awaiting_user", title="목록 화면")
        self.write_spec("T-001", "designer", title="로그인 화면", owns="docs/design/screens/t-001/**",
                        front={"issue": "5712"}, commit=False)
        render = approval.render(self.p, config.load(self.p),
                                 [state.load(self.p, "T-001"), state.load(self.p, "T-002")])
        self.assertIn("- T-001 #5712 r1 [디자인] 로그인 화면: docs/tasks/T-001/report.md", render["context"])
        self.assertIn("- T-002 r1 [디자인] 목록 화면: docs/tasks/T-002/report.md", render["context"])
```

**Append** `herdr-team/tests/test_drive_flows.py`

```python
class PlanIssueProgressTest(FlowCase):
    """기획 적용 progress 의 태스크 줄 이슈 번호(설계 8.12, 7단계). tasks.toml 의 issue 는 Task 2 가 사양으로 옮긴다."""

    def test_progress_line_shows_issue(self):
        plan = PLAN_TWO.replace('title = "저장 모듈"\n', 'title = "저장 모듈"\nissue = 5712\n')
        self.commit("docs/planning/tasks.toml", plan, "[T-001] 기획")
        self.task("T-001", "planner")
        self.d.apply_plan("T-001")
        self.assertEqual(self.progress(),
                         ["기획 적용: T-002 #5712 [developer] 저장 모듈; T-003 [developer] 할 일 화면 ← T-002"])
```

- [ ] **Step 2: 실패 확인**

Run: `cd herdr-team && python3 -m unittest tests.test_redmine tests.test_approval.IssueLineTest tests.test_approval.RedmineDecisionTest tests.test_drive_flows.PlanIssueProgressTest 2>&1 | tail -5`
Expected: `Ran 34 tests` / `FAILED (failures=29, errors=11)`(subTest 마다 센다). 대표 메시지: `AssertionError: 2 != 0 : {'ok': False, 'error': {'code': 'usage', 'message': "argument cmd: invalid choice: 'redmine-sync' …`(16건), `AttributeError: 'Drive' object has no attribute 'redmine_step'`, `AttributeError: 'Spec' object has no attribute 'issue'`, `ImportError: cannot import name 'redmine' from 'hteam'`, `KeyError: 'redmine_key'`, `AssertionError: Tuples differ: (0, 'working', None) != (0, 'waiting', 'slot_setup')`, `AssertionError: Lists differ: [] != [('start', '5712', 2, 'herdr-team: T-001 r…`(관제 흐름은 HEAD 에서 끝까지 돌고 큐만 비었다), `AssertionError: Lists differ: [] != [('closed', '5712', 'T-001', 5, 'T-001 가 끝나 종료한다.')]`(`RedmineDecisionTest`: design-decide 는 HEAD 에서 돌고 닫기만 없다), `AssertionError: … 첫 전송자가 요청 전에 끝났다`(`test_one_sender_at_a_time`: `redmine-sync` 가 없어 바로 끝난다). HEAD 에 공유 시험 도구와 이 태스크의 Step 1 블록만 적용한 트리에서 쟀다(앞 태스크 구현 없음). 앞 태스크(Task 2–7)를 구현한 트리에서는 `Spec.issue`·`slot_setup` 갈래가 이 태스크 기능의 실패(큐가 빈다)로 바뀐다.

- [ ] **Step 3: 구현**

Rules 1–12 와 Interfaces 대로 `redmine.py` 를 만들고 `paths.py`·`drive.py`·`tasks.py`·Task 5 의 병합 성공 지점·`approval.py`·`coord.py`·`setup.py`·`cli.py` 를 고친다. HTTP 는 `redmine.py` 에서만 부른다. `redmine.py` 는 `approval`·`review`·`workspace` 를 함수 안에서 가져온다(`approval` 이 `tasks` 를 쓰고 `tasks.run_work` 가 `redmine` 을 쓴다. 가져오는 순서가 꼬이지 않게). `redmine-sync` 의 CLI 는 `roles.require_drive(p)` 를 먼저 하고 설정을 읽는다.

- [ ] **Step 4: 통과 확인**

Run: `cd herdr-team && python3 -m unittest tests.test_redmine tests.test_approval tests.test_drive_flows tests.test_drive_events tests.test_drive tests.test_setup tests.test_coord 2>&1 | tail -3` 그다음 `bash herdr-team/tests/run.sh 2>&1 | tail -3`(저장소 루트에서, 백그라운드로 하나만, 10–15분)
Expected: 둘 다 `OK`(`[redmine]` 이 없는 기존 시험이 그대로 통과한다. `TickTest` 의 틱 순서 시험은 `redmine_step` 을 가짜로 바꾸지 않으므로 그대로다).

- [ ] **Step 5: 정적 확인과 커밋**

```bash
python3 - <<'PY'
import ast, pathlib
for f in ["herdr-team/lib/hteam/redmine.py", "herdr-team/lib/hteam/paths.py", "herdr-team/lib/hteam/drive.py",
          "herdr-team/lib/hteam/tasks.py", "herdr-team/lib/hteam/workspace.py", "herdr-team/lib/hteam/approval.py",
          "herdr-team/lib/hteam/coord.py", "herdr-team/lib/hteam/setup.py", "herdr-team/lib/hteam/cli.py",
          "herdr-team/tests/test_redmine.py", "herdr-team/tests/test_approval.py", "herdr-team/tests/test_drive_flows.py"]:
    ast.parse(pathlib.Path(f).read_text(encoding="utf-8"), feature_version=(3, 11))
PY
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews'
git add -- herdr-team/lib/hteam herdr-team/tests/test_redmine.py herdr-team/tests/test_approval.py herdr-team/tests/test_drive_flows.py
git commit -m "feat(herdr-team): Redmine 연동(사건 큐, 닫는 때, redmine-sync, 키 읽기·가리기, status·doctor, #N)" \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" \
  -- herdr-team/lib/hteam herdr-team/tests/test_redmine.py herdr-team/tests/test_approval.py herdr-team/tests/test_drive_flows.py
```

Expected: ast 오류 없음, grep 빈 출력. 구현자는 여기서 멈춘다(컨트롤러가 `scripts/codex-review.sh commit <sha>`).

---

### Task 9: init·메인 규칙·문서 — init 4a, `CLAUDE.section.md`(decide 두 줄·`index.lock`·Redmine), `AGENTS.section.md`·작업 규칙의 작업 공간·이슈·우선순위 줄, doctor 의 worktree 점검, README, 0.5.0

설계 9.1 의 4a, 9.2 의 7단계 줄(worktree 점검), 7.7 의 decide 두 줄·메인 규칙 줄, 5.10.9·14장의 7단계 줄, 15.3 의 7 의 8번을 만든다. init 스킬은 4단계 승인 표에 작업 공간·Redmine 두 줄을 더한다(둘 다 기본 끔, Redmine 키 값은 묻지도 받지도 않는다). 메인 규칙(`templates/CLAUDE.section.md`)은 decide 처리 기준 표에 `merge_conflict`·`workspace_failed`(설계 7.7 표 원문)를, 메인 규칙에 `index.lock` 다시 시도와 Redmine 두 줄을 더하고, push 줄은 프로젝트가 고를 줄이라 HTML 주석 예시로만 둔다(설계 7.7). 큐 명령 목록에 `slot reset`(설계 5.10.8 의 요청 큐 명령)을, "위치" 에 슬롯·점검표·Redmine 기록을 더한다. Codex 규칙(`templates/AGENTS.section.md`)과 작업 규칙(`templates/worker-rules.md`)에 작업 공간·이슈 줄을, AGENTS 절에는 우선순위 줄도 더한다(작업 규칙의 우선순위 줄은 Task 7 이 넣었다). doctor 는 worktree 모드면 git 2.23 이상·첫 커밋(오류)과 dirty 슬롯(경고)을 본다(Redmine 점검은 Task 8). README 는 작업 공간·점검표·Redmine 절, 시험 도구에서 `.herdr-team/` 빼기, `tester_paths`·`full_if`, herdr-orch `--env`, 보안 주의의 7단계 줄(14장), "0.4.0 → 0.5.0" 을 더한다. herdr-team 버전을 0.5.0 으로 올린다(`HORCH_MIN` 0.3.0 은 Task 1 이 올렸다).

`hteam upgrade`(설계 9.6)는 이번 변경에도 그대로 맞다: `CLAUDE.section.md`·`AGENTS.section.md` 는 이미 세팅한 프로젝트의 `CLAUDE.md`·`AGENTS.md` 절을 바꾸지 않고 `manual` 로 알린다(절 전문이 템플릿과 달라지므로 `_section_manual` 이 두 파일을 적는다). `worker-rules.md` 는 복사하지 않는 플러그인 템플릿이라(`setup.FILES` 에 없다) 플러그인을 올리면 바로 적용된다. `FILES`·`UPGRADE`·`UPGRADE_NEXT` 는 바꾸지 않는다.

**Files:**
- Modify: `herdr-team/skills/init/SKILL.md`(4a, 하지 않는 것), `herdr-team/templates/CLAUDE.section.md`, `herdr-team/templates/AGENTS.section.md`, `herdr-team/templates/worker-rules.md`, `herdr-team/lib/hteam/setup.py`(`_workspace_checks`, doctor), `herdr-team/lib/hteam/gitio.py`(`version`), `README.md`, `herdr-team/lib/hteam/paths.py`(VERSION), `herdr-team/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`(herdr-team 항목)
- Test: `herdr-team/tests/test_wording.py`(Edit 넷, Append), `herdr-team/tests/test_setup.py`(Append, shim 버전 Edit 하나), `herdr-team/tests/test_cli.py`(Edit 둘)

**Interfaces:**
- Consumes: Task 2 의 `config.Config.workspace`(`on`), Task 3 의 `workspace.load(p)`(엄격, `bad_slots_file`)·`entry(data, n)`·`paths.Project.slots_file`, 공유 시험 도구 `WS_CONFIG`. 지금 코드의 `setup.doctor`·`_check`, `gitio.is_repo`·`has_head`·`run`. 이름(문서에 적는다): decide kind `merge_conflict`·`workspace_failed`(Task 4·5), 큐 명령 `slot reset`(Task 5), `hteam status` 의 `redmine.failed`(Task 8), 슬롯 폴더·브랜치·로그 경로(Task 3), `state/redmine/`(Task 8).
- Produces:
  - `gitio.version(root) -> tuple[str, tuple[int, int, int] | None]`: `git -C <root> --version` 출력의 첫 줄과, 그 안 첫 `(\d+)\.(\d+)(?:\.(\d+))?` 를 정수 셋으로(셋째가 없으면 0). 찾지 못하면 둘째 값 None. git 이 없거나 실패하면 지금 `run` 의 HteamError 그대로.
  - `setup._workspace_checks(root: Path) -> list[dict]`: 설정을 읽지 못하거나(`HteamError`) `cfg.workspace.on` 이 아니면 `[]`. worktree 모드면 차례로 셋(`_check` 꼴):
    - `workspace_git`(error): `shutil.which("git")` 이 없으면 넣지 않는다(앞 `git` 점검이 이미 오류다). `gitio.version(root)` 의 정수가 `(2, 23, 0)` 이상이면 ok, detail `git <x.y.z>`. 아니면 ok false, detail `worktree 모드에는 git 2.23 이상이 필요하다(git switch·git worktree): 지금 <첫 줄>`. version 이 HteamError 면 ok false, detail 은 그 message.
    - `workspace_head`(error): `gitio.is_repo(root)` 가 아니면 ok false `git 저장소가 아니다. worktree 모드는 git 저장소와 첫 커밋이 필요하다`. `gitio.has_head(root)` 가 False 면 ok false `커밋이 없다. worktree 모드는 첫 커밋에서 슬롯을 만든다: git commit --allow-empty -m init`. True 면 ok `첫 커밋이 있다`. HteamError 면 ok false, detail 은 그 message. (git 이 없으면 넣지 않는다.)
    - `workspace_slots`(warning): `workspace.load(Project(root))` 에서 `state == "dirty"` 인 번호(작은 것부터). 없으면 ok `dirty 슬롯이 없다`. 있으면 ok false, detail `dirty 슬롯: <N>(.herdr-team/state/slots/slot-<N>)[, …]. 커밋 안 된 변경이 남았다. git -C <슬롯 폴더> status 로 보고, 사용자가 버려도 된다고 하면 hteam slot reset <번호>`. `bad_slots_file` 이면 ok false, detail 은 그 message 그대로(Task 3 의 `state/slots.json 을 읽지 못했다: <이유>`).
  - `setup.doctor(root)`: `_codex_browser` 다음에 `_workspace_checks` 를 더한다. 오류 판정(필수 점검 실패면 exit 1 `unhealthy`)은 지금 그대로라 `workspace_git`·`workspace_head` 실패는 exit 1, `workspace_slots` 는 경고다. shared(기본)면 새 점검이 없다(0.4.0 과 같은 `checks`).
  - 버전 0.5.0: `herdr-team/lib/hteam/paths.py` 의 `VERSION`, `herdr-team/.claude-plugin/plugin.json` 의 `version`, `.claude-plugin/marketplace.json` 의 herdr-team 항목 `version`.
  - 문구(원문은 Step 3 블록): init 4a 세 줄과 하지 않는 것 한 줄, 메인 규칙 두 줄과 push 주석 예시, decide 표 두 줄, 큐 목록의 `slot reset`, 위치 두 곳, AGENTS 절 넷, 작업 규칙 둘(규칙 1·3 의 끝 문장), README 절들.

**Rules:**

1. init 4a(설계 9.1): 4단계의 같은 표·같은 승인(AskUserQuestion 한 번)에 두 줄을 더한다. 둘 다 기본은 끔이다. 작업 공간 줄은 병렬 개발이 필요한지(동시에 개발 태스크를 둘 이상, 시험이 DB·포트를 쓰는지) 보고 슬롯 수·setup·teardown·env 를 제안하고, worktree 모드면 작업 공간 직무를 `[crew.*]` 에서 빼고 시험 도구 설정에서 `.herdr-team/` 를 빼자고 함께 제안한다(설계 4.2, 5.10.9). 켜면 적용 뒤 doctor 를 다시 돌려 worktree 점검을 본다. Redmine 줄은 URL·키를 담은 환경 변수 이름이나 `env_file`·상태 번호만 받고 키 값은 묻지도 받지도 않는다. 승인한 것만 `[workspace]`·`[redmine]` 으로 쓴다.
2. 메인 규칙(설계 7.7): decide 표 끝(`token_update` 다음)에 두 줄. 설계 표의 `merge_conflict` 줄 끝의 설계 절 번호(", 5.10.6")는 템플릿에 넣지 않는다(다른 줄도 설계 절을 적지 않는다). 메인 규칙 줄 둘은 decide 로 만든 태스크 줄 바로 뒤, push 줄은 그 뒤 HTML 주석 안이다(주석 밖에 같은 문장이 없다).
3. 큐 명령 목록(설계 7.1·5.10.8): `slot reset` 은 메인에서 부르면 요청 큐로 가는 명령이라 메인 규칙과 README 의 목록에 더한다.
4. AGENTS 절: Codex 는 프로젝트 `AGENTS.md` 를 스스로 읽으므로(설계 6.2) 공통 절에 우선순위 줄(설계 5.5·6.2 의 두 우선순위 문장을 워커·리뷰어 공통으로 합친 것)과 이슈 줄, 작업 워커 절에 작업 공간 줄(설계 5.10.5 의 첫 두 줄), 리뷰어 절에 작업 공간 리뷰 줄(5.10.4)을 둔다.
5. 작업 규칙(`worker-rules.md`): 모든 워커 사양에 들어가므로 설정이 없을 때 뜻이 달라지지 않게 조건부로 쓴다("사양에 작업 공간 절이 있으면", "관제가 바꾼다고 적혀 있으면"). 새 문단을 만들지 않고 규칙 1·3 의 끝에 문장을 더한다(Task 7 의 우선순위 문단 바로 뒤가 규칙 1 이고 규칙 6 이 끝인 것을 Task 7 시험이 본다. 번호도 바꾸지 않는다). `Redmine`·`## 작업 공간` 같은 설정에 기대는 낱말을 쓰지 않는다.
6. doctor(설계 9.2): Interfaces 그대로. git 은 `gitio.py` 에서만 부른다(`version`). 슬롯 상태는 `workspace.load` 로만 읽는다(직접 파일을 열지 않는다).
7. README: Step 3 의 Edit 블록 원문. 버전 표는 `marketplace.json` 과 같다(시험이 본다).

- [ ] **Step 1: 실패하는 테스트 작성**

**Edit** `herdr-team/tests/test_wording.py`

```python
DECIDE_KINDS = ("worker_failed", "worker_question", "escalation", "max_rounds", "repeat_test_failure", "test_config",
                "planning_gaps", "unknown_regression", "token_update")
```

```python
DECIDE_KINDS = ("worker_failed", "worker_question", "escalation", "max_rounds", "repeat_test_failure", "test_config",
                "planning_gaps", "unknown_regression", "token_update",
                "merge_conflict", "workspace_failed")  # 7단계 작업 공간(설계 5.10.8·7.7)
```

**Edit** `herdr-team/tests/test_wording.py`

```python
    def test_decide_table_has_the_nine_kinds(self):
```

```python
    def test_decide_table_has_the_kinds(self):
```

**Edit** `herdr-team/tests/test_wording.py`

```python
                "- 큐 명령(`start`, `start-ready`, `fix`, `accept`, `drop`, `review --retry`, `design-decide`, `scope`, "
                "`agent reset`, `test-confirm`)은 관제 큐를 거친다.",
```

```python
                "- 큐 명령(`start`, `start-ready`, `fix`, `accept`, `drop`, `review --retry`, `design-decide`, `scope`, "
                "`agent reset`, `test-confirm`, `slot reset`)은 관제 큐를 거친다.",
```

**Edit** `herdr-team/tests/test_wording.py`

```python
                       "### 관제 복구", "`[drive] auto_up = false`", "herdr-orch 0.2.0 이상", "#### 0.3.0 → 0.4.0",
```

```python
                       "### 관제 복구", "`[drive] auto_up = false`", "herdr-orch 0.3.0 이상", "#### 0.3.0 → 0.4.0",
```

**Append** `herdr-team/tests/test_wording.py`

```python
# --- 7단계 문구(설계 7.7·9.1 의 4a·5.5·6.2·8.12·14장, Task 9) ---
P7_MERGE_ROW = ('| `merge_conflict` | 충돌 파일을 사용자에게 보이고 묻는다. 고치기로 하면 `hteam fix T-xxx --note "<충돌을 어떻게 '
                '풀지 사용자 지시>"`(상한이면 `--force-round`. 기준 병합 지시는 hteam 이 사양에 넣는다), 버리기로 하면 '
                '`hteam drop T-xxx` |')
P7_WORKSPACE_ROW = ("| `workspace_failed` | `detail.kind` 로 가른다. `setup_failed` 는 로그 끝을 보이고 사용자가 setup 이나 환경을 "
                    "고친 뒤 `hteam start T-xxx`. `slot_dirty` 는 그 슬롯의 `git status` 를 보이고, 사용자가 버려도 된다고 하면 "
                    "`hteam slot reset <N>`. `branch_exists`·`base_moved`·`merge_blocked` 는 git 상태를 보이고 사용자에게 "
                    "묻는다(메인 폴더를 기준 브랜치로 되돌리기, 남은 브랜치 지우기 등은 사용자가 정한다) |")
P7_INDEX_LOCK = "- `git commit` 이 `index.lock` 오류로 실패하면 몇 초 뒤 같은 명령을 다시 한다(관제의 병합과 겹쳤다)."
P7_REDMINE_RULE = ("- Redmine 을 쓰는 프로젝트(`[redmine]`)면 이슈 상태·노트는 관제가 바꾼다. 메인도 바꾸지 않는다. "
                   "`hteam status` 의 `redmine.failed` 가 늘면 사용자에게 알린다.")
P7_PUSH = ("- 사용자가 묶음이 끝난 뒤 push 하라고 정했으면 `done` 의 마지막 전체 테스트가 통과했을 때 push 한다"
           "(플러그인은 push 하지 않는다).")
P7_AGENTS_PRIORITY = ("- 프리앰블·사양·리뷰 프롬프트가 정한 보고서·리뷰 파일 경로와 형식, 커밋 형식, 판정 표기, done 방법, git 쓰기 "
                      "금지는 이 저장소의 다른 문서(AGENTS.md 의 다른 절, CLAUDE.md 등)의 규칙보다 앞선다(다른 보고서 경로·이슈 "
                      "트래커 갱신 규칙과 부딪칠 때). 코드·문구·디자인 기준은 프로젝트 문서도 따른다.")
P7_AGENTS_ISSUE = ("- 이슈 트래커는 사양·리뷰 프롬프트의 이슈 줄을 따른다. 관제가 바꾼다고 적혀 있으면 이슈 상태·노트를 바꾸지 "
                   "않는다(이 저장소 문서에 다른 갱신 규칙이 있어도).")
P7_AGENTS_WORKSPACE = ("- 사양에 `## 작업 공간` 절이 있으면 그 슬롯 worktree 에서만 일하고 그 브랜치에 커밋한다. 그 폴더 밖(메인 "
                       "폴더, 다른 슬롯)의 파일을 고치지 않는다. 병합·push·브랜치 바꾸기·rebase 는 그 절이 시킨 것만 한다(리뷰가 "
                       "승인하면 관제가 병합한다).")
P7_AGENTS_REVIEWER = ("- 리뷰 프롬프트가 슬롯 worktree 를 가리키면 그 폴더에서 리뷰한다(파일 읽기·git 조회·확인 명령 모두. 메인 "
                      "폴더에는 아직 병합되지 않았다).")
P7_RULES_WORKSPACE = ("사양에 작업 공간 절(슬롯 worktree 와 브랜치)이 있으면 그 폴더에서만 일하고 그 브랜치에 커밋한다. 그 폴더 "
                      "밖(메인 폴더, 다른 슬롯)은 고치지 않고, 병합·push·브랜치 바꾸기·rebase 는 그 절이 시킨 것만 한다.")
P7_RULES_ISSUE = ("이슈 트래커의 이슈 상태·노트는 사양의 이슈 줄을 따른다. 관제가 바꾼다고 적혀 있으면 바꾸지 않는다(프로젝트 "
                  "문서에 다른 갱신 규칙이 있어도).")


class MainRulesP7Test(unittest.TestCase):
    """7단계 메인 규칙(설계 7.7): decide 두 줄, index.lock 다시 시도, Redmine 줄, push 는 주석 예시, 큐의 slot reset, 위치."""

    def setUp(self):
        self.main = read("templates/CLAUDE.section.md")

    def between(self, start: str, end: str | None = None) -> str:
        i = self.main.index(start)
        return self.main[i:self.main.index(end, i) if end else len(self.main)]

    def test_decide_rows_at_the_end_of_the_table(self):
        table = self.between("### decide 처리 기준\n", "### 질문 표시 규칙\n")
        rows = [ln for ln in table.splitlines() if ln.startswith("| `")]
        self.assertEqual(rows[-2:], [P7_MERGE_ROW, P7_WORKSPACE_ROW])
        self.assertTrue(rows[-3].startswith("| `token_update` |"))

    def test_main_rule_lines(self):
        rules = self.between("### 메인 규칙\n", "### decide 처리 기준\n")
        self.assertIn("`hteam answer` 로 닫는다.\n" + P7_INDEX_LOCK + "\n" + P7_REDMINE_RULE + "\n", rules)

    def test_push_line_is_only_a_comment_example(self):
        comment = self.between("<!-- 프로젝트가 고를 줄(예)", "-->")
        self.assertIn(P7_PUSH, comment)
        self.assertEqual(self.main.count(P7_PUSH), 1)  # 주석 밖에는 없다(프로젝트가 고른다)
        self.assertLess(self.main.index(P7_REDMINE_RULE), self.main.index("<!-- 프로젝트가 고를 줄(예)"))

    def test_locations(self):
        where = self.between("### 위치\n")
        for needle in ("관제 `[drive]`, 작업 공간 `[workspace]`, Redmine `[redmine]`)",
                       "- 작업 공간 슬롯 `.herdr-team/state/slots/slot-<N>`(태스크 브랜치 `herdr/T-xxx`, 슬롯 상태 "
                       "`.herdr-team/state/slots.json`), 리뷰 프로젝트 점검표 `.herdr-team/review-extra.md`(있으면 리뷰 "
                       "프롬프트에 붙는다), Redmine 전송 기록 `.herdr-team/state/redmine/`."):
            self.assertIn(needle, where)


class AgentsRulesP7Test(unittest.TestCase):
    """Codex 규칙(AGENTS.md 절)과 작업 규칙의 작업 공간·이슈·우선순위 줄(설계 15.3 의 7 의 8, 5.5, 6.2, 8.12)."""

    @staticmethod
    def part(text: str, title: str) -> str:
        start = text.index(f"## {title}\n")
        nxt = text.find("\n## ", start + 1)
        return text[start:nxt if nxt != -1 else len(text)]

    def test_agents_section(self):
        agents = read("templates/AGENTS.section.md")
        common = self.part(agents, "공통")
        self.assertIn("(관제가 메인에 올리고, 메인이 답한다).\n" + P7_AGENTS_PRIORITY + "\n" + P7_AGENTS_ISSUE + "\n", common)
        self.assertIn("같은 작업 폴더에서 다른 워커가 동시에 일한다.\n" + P7_AGENTS_WORKSPACE + "\n",
                      self.part(agents, "작업 워커"))
        self.assertIn("다른 파일을 만들거나 고치거나 지우지 않는다.\n" + P7_AGENTS_REVIEWER + "\n", self.part(agents, "리뷰어"))

    def test_worker_rules(self):
        rules = read("templates/worker-rules.md")
        self.assertIn("`git add .` 를 쓰지 않는다. " + P7_RULES_WORKSPACE + "\n2. 커밋은 경로를 지정한다", rules)
        self.assertIn("남은 위험, 가정. " + P7_RULES_ISSUE + "\n4. ", rules)
        # 모든 워커 사양에 들어가는 글이다. 설정에 기대는 낱말(Redmine, 절 머리)을 쓰지 않아 설정이 없으면 뜻이 그대로다
        self.assertNotIn("Redmine", rules)
        self.assertNotIn("## 작업 공간", rules)


class InitSkillP7Test(unittest.TestCase):
    """init 4단계의 작업 공간·Redmine 줄(설계 9.1 의 4a)."""

    def test_rows_in_the_same_table(self):
        init = read("skills/init/SKILL.md")
        step = init[init.index("## 4. 판단이 필요한 한 단계\n"):init.index("## 5. 관제\n")]
        for needle in ("- 작업 공간(`[workspace]`, 기본 끔): 병렬 개발이 필요한지 본다(동시에 개발 태스크를 둘 이상 돌리고 시험이 "
                       "DB·포트를 쓰는지).", '`mode = "worktree"`', "`[crew.*]` 의 `roles` 에서 빼고 `user_approval_roles` 에 두지 "
                       "않는다", "시험 도구 설정(vitest·jest·ESLint·`tsconfig.json`·pytest 등)에서 `.herdr-team/` 를 빼자고 함께 "
                       "제안한다", "`workspace_git`·`workspace_head`", "- Redmine 연동(`[redmine]`, 기본 끔):", "`key_env`",
                       "`env_file`", "**API 키 값은 묻지도 받지도 않는다.**", "- 작업 공간·Redmine 은 승인한 것만"):
            self.assertIn(needle, step)
        self.assertLess(step.index("- 작업 공간(`[workspace]`"), step.index("- AskUserQuestion 한 번으로 승인받는다."))
        self.assertIn("- Redmine API 키 값을 묻거나 받거나 `config.toml` 에 쓰기.", init[init.index("## 하지 않는 것\n"):])


class ReadmeP7Test(unittest.TestCase):
    """README 의 7단계 절(설계 15.3 의 7 의 8, 5.10.9·14장 7단계 줄)."""

    def setUp(self):
        self.text = (REPO / "README.md").read_text(encoding="utf-8")

    def test_version_table_matches_plugins(self):
        market = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        for entry in market["plugins"]:
            self.assertIn(f"| `{entry['name']}` | {entry['version']} |", self.text)
        self.assertIn("- herdr-team 을 쓰려면 herdr-orch 0.3.0 이상도 함께 설치한다.", self.text)

    def test_sections(self):
        for needle in ("### 작업 공간(선택, 병렬 개발)", "### 리뷰 점검표와 우선순위", "### Redmine 연동(선택)",
                       "시험 도구 설정에서 `.herdr-team/` 를 뺀다", "`hteam slot reset <N>`", "`.herdr-team/review-extra.md`",
                       "`tester_paths`", "`full_if`", "`git worktree remove <폴더>`", "`worker-start --env KEY=VALUE`",
                       "`slot reset`)은 파일 큐", "키 값은 init 이 묻지 않는다"):
            self.assertIn(needle, self.text)
        recovery = self.text.index("### 관제 복구")
        for title in ("### 작업 공간(선택, 병렬 개발)", "### 리뷰 점검표와 우선순위", "### Redmine 연동(선택)"):
            self.assertLess(self.text.index(title), recovery)

    def test_security_lines(self):
        sec = self.text[self.text.index("### herdr-team 보안 주의"):self.text.index("### 이미 세팅한 프로젝트 업그레이드")]
        for needle in ("작업 공간 setup·teardown 은 `config.toml` 의 셸 문자열이고 관제 권한", "슬롯 워커도 같은 사용자 권한으로 돌아",
                       "`hteam slot reset` 은 슬롯의 커밋 안 된 변경을 지운다", "Redmine API 키는 전송 자식만 읽고",
                       "`env_file` 은 git 제외여야 한다"):
            self.assertIn(needle, sec)

    def test_upgrade_section(self):
        self.assertLess(self.text.index("#### 0.4.0 → 0.5.0"), self.text.index("#### 0.3.0 → 0.4.0"))
        part = self.text[self.text.index("#### 0.4.0 → 0.5.0"):self.text.index("#### 0.3.0 → 0.4.0")]
        for needle in ("플러그인만 올리면 된다(herdr-orch 0.3.0 과 함께). 새 기능은 설정으로 켜고, 켜지 않으면 0.4.0 과 같이 돈다.",
                       "`[workspace]`", "`[redmine]`", "`manual`", "`merge_conflict`·`workspace_failed`"):
            self.assertIn(needle, part)
```

**Append** `herdr-team/tests/test_setup.py`

```python
from tests.helpers import WS_CONFIG  # noqa: E402  (Append 블록, 7단계)


class WorkspaceDoctorTest(TeamCase):
    """doctor 의 worktree 점검(설계 9.2 의 7단계 줄): git 2.23 이상·첫 커밋(오류), dirty 슬롯(경고). shared 면 점검이 없다."""

    def checks(self, env=None):
        code, out = self.hteam("doctor", as_="main", env=env)
        return code, out, {c["name"]: c for c in out["checks"]}

    def test_shared_has_no_workspace_checks(self):
        # 회귀: [workspace] 가 없으면 0.4.0 과 같은 점검 목록이다
        self.init_project()
        code, out, checks = self.checks()
        self.assertEqual(code, 0, out)
        self.assertEqual([n for n in checks if n.startswith("workspace_")], [])

    def test_worktree_mode_passes(self):
        self.init_project(WS_CONFIG)
        code, out, checks = self.checks()
        self.assertEqual(code, 0, out)
        self.assertEqual([n for n in checks if n.startswith("workspace_")],
                         ["workspace_git", "workspace_head", "workspace_slots"])
        self.assertEqual((checks["workspace_git"]["ok"], checks["workspace_git"]["level"]), (True, "error"))
        self.assertRegex(checks["workspace_git"]["detail"], r"^git \d+\.\d+\.\d+$")
        self.assertEqual((checks["workspace_head"]["ok"], checks["workspace_head"]["detail"]), (True, "첫 커밋이 있다"))
        self.assertEqual((checks["workspace_slots"]["ok"], checks["workspace_slots"]["level"],
                          checks["workspace_slots"]["detail"]), (True, "warning", "dirty 슬롯이 없다"))

    def test_old_git_is_an_error(self):
        self.init_project(WS_CONFIG)
        wrap = self.tmp / "oldgit"
        wrap.mkdir()
        real = shutil.which("git", path=self.env["PATH"])
        (wrap / "git").write_text('#!/bin/sh\nfor a in "$@"; do\n  if [ "$a" = --version ]; then echo "git version 2.20.1"; '
                                  f'exit 0; fi\ndone\nexec "{real}" "$@"\n', encoding="utf-8")
        (wrap / "git").chmod(0o755)
        code, out, checks = self.checks(env={"PATH": f"{wrap}{os.pathsep}{self.env['PATH']}"})
        self.assertEqual((code, out["error"]["code"]), (1, "unhealthy"), out)
        self.assertEqual((checks["workspace_git"]["ok"], checks["workspace_git"]["detail"]),
                         (False, "worktree 모드에는 git 2.23 이상이 필요하다(git switch·git worktree): 지금 git version 2.20.1"))
        bad = {c["name"] for c in out["checks"] if not c["ok"] and c["level"] == "error"}
        self.assertEqual(bad, {"workspace_git"})

    def test_no_first_commit_is_an_error(self):
        self.init_project(WS_CONFIG, commit=False)
        self.git("update-ref", "-d", "HEAD")  # HEAD 가 가리키는 브랜치를 지운다: 커밋이 없는 저장소와 같다
        code, out, checks = self.checks()
        self.assertEqual((code, out["error"]["code"]), (1, "unhealthy"), out)
        self.assertEqual((checks["workspace_head"]["ok"], checks["workspace_head"]["detail"]),
                         (False, "커밋이 없다. worktree 모드는 첫 커밋에서 슬롯을 만든다: git commit --allow-empty -m init"))
        bad = {c["name"] for c in out["checks"] if not c["ok"] and c["level"] == "error"}
        self.assertEqual(bad, {"workspace_head"})

    def test_dirty_slot_is_a_warning(self):
        self.init_project(WS_CONFIG)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        free = {"task": None, "branch": None, "base_branch": None, "base": None, "setup_done": None,
                "since": "2026-11-12T00:00:00Z"}
        (self.state_dir / "slots.json").write_text(json.dumps({"slots": {
            "1": {**free, "state": "busy", "task": "T-001", "branch": "herdr/T-001", "base_branch": "main",
                  "base": self.head(), "setup_done": "T-001"},
            "2": {**free, "state": "dirty"}}}), encoding="utf-8")
        code, out, checks = self.checks()
        self.assertEqual(code, 0, out)  # 경고는 doctor 를 실패시키지 않는다
        slot = checks["workspace_slots"]
        self.assertEqual((slot["ok"], slot["level"]), (False, "warning"))
        self.assertEqual(slot["detail"], "dirty 슬롯: 2(.herdr-team/state/slots/slot-2). 커밋 안 된 변경이 남았다. "
                         "git -C <슬롯 폴더> status 로 보고, 사용자가 버려도 된다고 하면 hteam slot reset <번호>")

    def test_unreadable_slots_file_is_a_warning(self):
        self.init_project(WS_CONFIG)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "slots.json").write_text("{깨짐", encoding="utf-8")
        code, out, checks = self.checks()
        self.assertEqual(code, 0, out)
        slot = checks["workspace_slots"]
        self.assertEqual((slot["ok"], slot["level"]), (False, "warning"))
        self.assertTrue(slot["detail"].startswith("state/slots.json 을 읽지 못했다: "), slot)
```

**Edit** `herdr-team/tests/test_setup.py`

```python
        self.assertEqual(json.loads(out.stdout)["version"], "0.4.0")
```

```python
        self.assertEqual(json.loads(out.stdout)["version"], "0.5.0")
```

**Edit** `herdr-team/tests/test_cli.py`

```python
        self.assertEqual((code, out["ok"], out["version"]), (0, True, "0.4.0"))
```

```python
        self.assertEqual((code, out["ok"], out["version"]), (0, True, "0.5.0"))
```

**Edit** `herdr-team/tests/test_cli.py`

```python
        self.assertEqual({VERSION, plugin["version"], entry["version"]}, {"0.4.0"})
```

```python
        self.assertEqual({VERSION, plugin["version"], entry["version"]}, {"0.5.0"})
```

- [ ] **Step 2: 실패 확인**

Run: `cd herdr-team && python3 -m unittest tests.test_wording tests.test_setup.WorkspaceDoctorTest tests.test_setup.ScaffoldTest.test_shim_finds_plugin tests.test_cli 2>&1 | tail -5`
Expected: `Ran 39 tests` / `FAILED (failures=16, errors=6)`. 대표 메시지: `AssertionError: Tuples differ: ('wor[127 chars]ression', 'token_update') != ('wor[127 chars]ression', 'token_update', 'merge_conflict', 'workspace_failed')`(decide 표), `AssertionError: Lists differ: ['| ‹unknown_regression 줄›'] != ['| ‹merge_conflict 줄›', …]`, `AssertionError: '- 큐 명령(… slot reset)은 관제 큐를 거친다.' not found`(따옴표 안 백틱은 줄였다), `ValueError: substring not found`(push 주석 예시·README 업그레이드 절 자리, 오류 둘), `KeyError: 'workspace_slots'`·`KeyError: 'error'`(doctor 에 점검이 없어 healthy 로 끝난다, 오류 넷), `AssertionError: Lists differ: [] != ['workspace_git', 'workspace_head', 'workspace_slots']`, `AssertionError: '- herdr-team 을 쓰려면 herdr-orch 0.3.0 이상도 함께 설치한다.' not found`, `AssertionError: '### 작업 공간(선택, 병렬 개발)' not found`, `AssertionError: Tuples differ: (0, True, '0.4.0') != (0, True, '0.5.0')`, `AssertionError: Items in the first set but not the second:`(버전), `AssertionError: '0.4.0' != '0.5.0'`(shim). 회귀 시험 `test_shared_has_no_workspace_checks` 와 바꾸지 않은 기존 문구 시험은 이 단계에서도 통과한다. HEAD 에 공유 시험 도구와 이 태스크의 Step 1 블록만 적용한 트리에서 쟀다(Task 1–8 구현 없음. 그래서 `WS_CONFIG` 의 `[workspace]` 는 아직 아무 뜻이 없고 doctor 점검이 없어 실패한다). 계획을 쓸 때 스크래치에서 HEAD + 공유 시험 도구 + Task 7 의 블록 + 이 태스크의 블록(Step 1·3) + 시범 구현(doctor·`gitio.version`·버전 세 곳과 Task 1 의 herdr-orch 버전·`HORCH_MIN`, 엄격 읽기만 하는 시범 `workspace.load`. 계획에 넣지 않았다)으로 `tests.test_setup`·`tests.test_cli`·`tests.test_wording` 의 이 태스크 시험이 모두 통과하는 것을 확인했다(Task 7 의 `PromptTemplateP7Test` 도 통과한다. `WorkSpecP7Test` 는 Task 7 구현이 있어야 통과한다).

- [ ] **Step 3: 구현**

Rules 1–7 과 Interfaces 대로 `gitio.py`(`version`)·`setup.py`(`_workspace_checks`, doctor) 를 고치고, 버전 세 곳을 `0.5.0` 으로 바꾼다(`herdr-team/lib/hteam/paths.py` 의 `VERSION = "0.5.0"`, `herdr-team/.claude-plugin/plugin.json` 의 `"version": "0.5.0"`, `.claude-plugin/marketplace.json` 의 herdr-team 항목 `"version": "0.5.0"`). 문구 파일은 아래 블록 그대로다.

**Edit** `herdr-team/skills/init/SKILL.md`

```markdown
- AskUserQuestion 한 번으로 승인받는다. 선택지 "전부 승인 (추천)", "바꾸지 않고 진행". 일부 제외는 Other 로 받는다.
```

```markdown
- 작업 공간(`[workspace]`, 기본 끔): 병렬 개발이 필요한지 본다(동시에 개발 태스크를 둘 이상 돌리고 시험이 DB·포트를 쓰는지). 필요하면 `mode = "worktree"` 와 슬롯 수(`slots`, 1–9), 슬롯 준비·정리 명령(`setup`·`teardown`, 셸 문자열. 관제 권한으로 슬롯 폴더에서 돈다), 슬롯별 환경 변수(`[workspace.env]`, 값의 `{slot}` 은 슬롯 번호. 이름에 `KEY`·`SECRET`·`TOKEN` 을 쓰지 않는다)를 제안한다. 켜면 개발·테스트 직무(`roles`, 기본 developer·tester) 태스크가 `.herdr-team/state/slots/slot-<N>` worktree 의 `herdr/T-xxx` 브랜치에서 돌고, 리뷰가 승인하면 관제가 기준 브랜치에 병합한다. 그 직무는 임시 워커만 맡으므로 `[crew.*]` 의 `roles` 에서 빼고 `user_approval_roles` 에 두지 않는다. 시험 도구 설정(vitest·jest·ESLint·`tsconfig.json`·pytest 등)에서 `.herdr-team/` 를 빼자고 함께 제안한다(슬롯 사본이 메인 폴더 안에 있다). 켜기로 하면 적용한 뒤 `.herdr-team/bin/hteam doctor` 를 다시 실행해 `workspace_git`·`workspace_head` 를 본다(git 2.23 이상, 첫 커밋). 필요 없으면 표에 "쓰지 않음" 으로 적고 `[workspace]` 를 넣지 않는다.
- Redmine 연동(`[redmine]`, 기본 끔): Redmine 이슈로 일하는 프로젝트인지 묻는다. 쓰면 URL(`url`), API 키를 담은 환경 변수 이름(`key_env`)이나 키를 읽을 파일(`env_file`, git 이 추적하지 않는 파일), 상태 번호(`status = { start, done, changes, closed }`)를 받는다. **API 키 값은 묻지도 받지도 않는다.** 사용자가 키를 붙여 넣으면 쓰지 않고, 그 환경 변수나 `env_file` 에 직접 두라고 안내한다. 이슈 상태·노트는 관제가 바꾼다(워커·리뷰어·메인은 바꾸지 않는다). 쓰지 않으면 `[redmine]` 을 넣지 않는다.
- 작업 공간·Redmine 은 승인한 것만 `.herdr-team/config.toml` 의 `[workspace]`·`[redmine]` 표로 쓴다(config.toml 의 주석 예시와 같은 꼴).
- AskUserQuestion 한 번으로 승인받는다. 선택지 "전부 승인 (추천)", "바꾸지 않고 진행". 일부 제외는 Other 로 받는다.
```

**Edit** `herdr-team/skills/init/SKILL.md`

```markdown
- 사용자 전역 Claude·Codex 설정 고치기, 승인받지 않은 Claude 권한 우회.
```

```markdown
- 사용자 전역 Claude·Codex 설정 고치기, 승인받지 않은 Claude 권한 우회.
- Redmine API 키 값을 묻거나 받거나 `config.toml` 에 쓰기.
```

**Edit** `herdr-team/templates/CLAUDE.section.md`

```markdown
- decide 를 처리하며 만든 태스크(회귀 수정, `[test]` 고치기, 증분 기획)도 같은 순서(task new → 채우기 → 커밋 → start)를 마친 뒤 decide 를 `hteam answer` 로 닫는다.
```

```markdown
- decide 를 처리하며 만든 태스크(회귀 수정, `[test]` 고치기, 증분 기획)도 같은 순서(task new → 채우기 → 커밋 → start)를 마친 뒤 decide 를 `hteam answer` 로 닫는다.
- `git commit` 이 `index.lock` 오류로 실패하면 몇 초 뒤 같은 명령을 다시 한다(관제의 병합과 겹쳤다).
- Redmine 을 쓰는 프로젝트(`[redmine]`)면 이슈 상태·노트는 관제가 바꾼다. 메인도 바꾸지 않는다. `hteam status` 의 `redmine.failed` 가 늘면 사용자에게 알린다.
<!-- 프로젝트가 고를 줄(예). 쓰려면 주석 표시를 지우고 위 목록에 둔다:
- 사용자가 묶음이 끝난 뒤 push 하라고 정했으면 `done` 의 마지막 전체 테스트가 통과했을 때 push 한다(플러그인은 push 하지 않는다).
-->
```

**Edit** `herdr-team/templates/CLAUDE.section.md`

```markdown
`agent reset`, `test-confirm`)은 관제 큐를 거친다.
```

```markdown
`agent reset`, `test-confirm`, `slot reset`)은 관제 큐를 거친다.
```

**Edit** `herdr-team/templates/CLAUDE.section.md`

```markdown
| `token_update` | 관제가 기계적으로 하지 못한 디자인 보강 토큰 반영이다. UI 기반 개발 태스크가 done 이면 토큰 갱신 태스크(UI 기반과 같은 owns, `depends_on` 에 보강 태스크)를 만들고, 아직 시작하지 않은 화면 구현 태스크의 `depends_on` 에 더해 커밋한다. working 이면 `hteam scope`, 리뷰 중이면 결과를 기다린 뒤 정한다 |
```

```markdown
| `token_update` | 관제가 기계적으로 하지 못한 디자인 보강 토큰 반영이다. UI 기반 개발 태스크가 done 이면 토큰 갱신 태스크(UI 기반과 같은 owns, `depends_on` 에 보강 태스크)를 만들고, 아직 시작하지 않은 화면 구현 태스크의 `depends_on` 에 더해 커밋한다. working 이면 `hteam scope`, 리뷰 중이면 결과를 기다린 뒤 정한다 |
| `merge_conflict` | 충돌 파일을 사용자에게 보이고 묻는다. 고치기로 하면 `hteam fix T-xxx --note "<충돌을 어떻게 풀지 사용자 지시>"`(상한이면 `--force-round`. 기준 병합 지시는 hteam 이 사양에 넣는다), 버리기로 하면 `hteam drop T-xxx` |
| `workspace_failed` | `detail.kind` 로 가른다. `setup_failed` 는 로그 끝을 보이고 사용자가 setup 이나 환경을 고친 뒤 `hteam start T-xxx`. `slot_dirty` 는 그 슬롯의 `git status` 를 보이고, 사용자가 버려도 된다고 하면 `hteam slot reset <N>`. `branch_exists`·`base_moved`·`merge_blocked` 는 git 상태를 보이고 사용자에게 묻는다(메인 폴더를 기준 브랜치로 되돌리기, 남은 브랜치 지우기 등은 사용자가 정한다) |
```

**Edit** `herdr-team/templates/CLAUDE.section.md`

```markdown
관제 `[drive]`), 태스크 사양
```

```markdown
관제 `[drive]`, 작업 공간 `[workspace]`, Redmine `[redmine]`), 태스크 사양
```

**Edit** `herdr-team/templates/CLAUDE.section.md`

```markdown
- 관제 기록 `.herdr-team/state/drive/drive.log`, 고정 에이전트 상태 `.herdr-team/state/crew.json`, 인수인계 `docs/handoff/<이름>.md`.
```

```markdown
- 관제 기록 `.herdr-team/state/drive/drive.log`, 고정 에이전트 상태 `.herdr-team/state/crew.json`, 인수인계 `docs/handoff/<이름>.md`.
- 작업 공간 슬롯 `.herdr-team/state/slots/slot-<N>`(태스크 브랜치 `herdr/T-xxx`, 슬롯 상태 `.herdr-team/state/slots.json`), 리뷰 프로젝트 점검표 `.herdr-team/review-extra.md`(있으면 리뷰 프롬프트에 붙는다), Redmine 전송 기록 `.herdr-team/state/redmine/`.
```

**Edit** `herdr-team/templates/AGENTS.section.md`

```markdown
- 대화형으로 사용자에게 묻지 않는다. 막히면 프리앰블의 ask 명령으로 메인에게 묻는다(관제가 메인에 올리고, 메인이 답한다).
```

```markdown
- 대화형으로 사용자에게 묻지 않는다. 막히면 프리앰블의 ask 명령으로 메인에게 묻는다(관제가 메인에 올리고, 메인이 답한다).
- 프리앰블·사양·리뷰 프롬프트가 정한 보고서·리뷰 파일 경로와 형식, 커밋 형식, 판정 표기, done 방법, git 쓰기 금지는 이 저장소의 다른 문서(AGENTS.md 의 다른 절, CLAUDE.md 등)의 규칙보다 앞선다(다른 보고서 경로·이슈 트래커 갱신 규칙과 부딪칠 때). 코드·문구·디자인 기준은 프로젝트 문서도 따른다.
- 이슈 트래커는 사양·리뷰 프롬프트의 이슈 줄을 따른다. 관제가 바꾼다고 적혀 있으면 이슈 상태·노트를 바꾸지 않는다(이 저장소 문서에 다른 갱신 규칙이 있어도).
```

**Edit** `herdr-team/templates/AGENTS.section.md`

```markdown
- `git stash`·`git reset`·`git checkout -- <파일>`·`git add -A`·`git add .` 를 쓰지 않는다. 같은 작업 폴더에서 다른 워커가 동시에 일한다.
```

```markdown
- `git stash`·`git reset`·`git checkout -- <파일>`·`git add -A`·`git add .` 를 쓰지 않는다. 같은 작업 폴더에서 다른 워커가 동시에 일한다.
- 사양에 `## 작업 공간` 절이 있으면 그 슬롯 worktree 에서만 일하고 그 브랜치에 커밋한다. 그 폴더 밖(메인 폴더, 다른 슬롯)의 파일을 고치지 않는다. 병합·push·브랜치 바꾸기·rebase 는 그 절이 시킨 것만 한다(리뷰가 승인하면 관제가 병합한다).
```

**Edit** `herdr-team/templates/AGENTS.section.md`

```markdown
- 리뷰 프롬프트의 `REVIEW_FILE` 하나만 쓴다. 다른 파일을 만들거나 고치거나 지우지 않는다.
```

```markdown
- 리뷰 프롬프트의 `REVIEW_FILE` 하나만 쓴다. 다른 파일을 만들거나 고치거나 지우지 않는다.
- 리뷰 프롬프트가 슬롯 worktree 를 가리키면 그 폴더에서 리뷰한다(파일 읽기·git 조회·확인 명령 모두. 메인 폴더에는 아직 병합되지 않았다).
```

**Edit** `herdr-team/templates/worker-rules.md`

```markdown
1. 같은 작업 폴더에서 다른 워커가 동시에 일한다. 남의 변경을 되돌리지 않는다. `git stash`·`git reset`·`git checkout -- <파일>`·`git add -A`·`git add .` 를 쓰지 않는다.
```

```markdown
1. 같은 작업 폴더에서 다른 워커가 동시에 일한다. 남의 변경을 되돌리지 않는다. `git stash`·`git reset`·`git checkout -- <파일>`·`git add -A`·`git add .` 를 쓰지 않는다. 사양에 작업 공간 절(슬롯 worktree 와 브랜치)이 있으면 그 폴더에서만 일하고 그 브랜치에 커밋한다. 그 폴더 밖(메인 폴더, 다른 슬롯)은 고치지 않고, 병합·push·브랜치 바꾸기·rebase 는 그 절이 시킨 것만 한다.
```

**Edit** `herdr-team/templates/worker-rules.md`

```markdown
3. 보고서 `{{report}}` 에 이번 라운드 `## r{{round}}` 절을 더한다: 바꾼 파일, 이유, 검증 명령과 출력 원문, 남은 위험, 가정.
```

```markdown
3. 보고서 `{{report}}` 에 이번 라운드 `## r{{round}}` 절을 더한다: 바꾼 파일, 이유, 검증 명령과 출력 원문, 남은 위험, 가정. 이슈 트래커의 이슈 상태·노트는 사양의 이슈 줄을 따른다. 관제가 바꾼다고 적혀 있으면 바꾸지 않는다(프로젝트 문서에 다른 갱신 규칙이 있어도).
```

**Edit** `README.md`

```markdown
| `herdr-orch` | 0.2.0 | Claude·Codex 워커를 Herdr pane 으로 띄우고 메일함으로 질문·보고를 주고받는 `horch` CLI 와 스킬 |
| `herdr-team` | 0.4.0 | `herdr-orch` 위의 직무 팀. 사용자는 메인 Claude 세션과 대화하고, 기획·디자인·개발·테스트는 직무 에이전트가 맡고, 산출물은 반대쪽 모델(Claude ↔ Codex)이 리뷰한다 |
```

```markdown
| `herdr-orch` | 0.3.0 | Claude·Codex 워커를 Herdr pane 으로 띄우고 메일함으로 질문·보고를 주고받는 `horch` CLI 와 스킬 |
| `herdr-team` | 0.5.0 | `herdr-orch` 위의 직무 팀. 사용자는 메인 Claude 세션과 대화하고, 기획·디자인·개발·테스트는 직무 에이전트가 맡고, 산출물은 반대쪽 모델(Claude ↔ Codex)이 리뷰한다 |
```

**Edit** `README.md`

```markdown
| git | 태스크 사양과 산출물 커밋 | |
```

```markdown
| git | 태스크 사양과 산출물 커밋. 작업 공간(worktree 모드)은 2.23 이상 | |
```

**Edit** `README.md`

```markdown
- herdr-team 을 쓰려면 herdr-orch 0.2.0 이상도 함께 설치한다.
```

```markdown
- herdr-team 을 쓰려면 herdr-orch 0.3.0 이상도 함께 설치한다.
```

**Edit** `README.md`

```markdown
  - 프로젝트 안: `.herdr-team/`, `CLAUDE.md`·`AGENTS.md` 의 `<!-- herdr-team -->` 절.
```

```markdown
  - 프로젝트 안: `.herdr-team/`, `CLAUDE.md`·`AGENTS.md` 의 `<!-- herdr-team -->` 절.
  - 작업 공간을 썼으면 슬롯 폴더(`.herdr-team/state/slots/slot-<N>`)는 git worktree 다. `.herdr-team/` 를 지우기 전에 `git worktree remove <폴더>` 로 지우거나, 지운 뒤 `git worktree prune` 을 한다. 남은 `herdr/T-xxx` 브랜치(버린 태스크)도 손으로 지운다.
```

**Edit** `README.md`

```markdown
  - 관제 자동 부활: `.herdr-team/state/auto-up.log`
```

```markdown
  - 관제 자동 부활: `.herdr-team/state/auto-up.log`
  - 작업 공간 setup·teardown: `.herdr-team/state/slots/logs/`
  - Redmine 전송 실패: `.herdr-team/state/redmine/failed/`(`hteam status` 의 `redmine`)
```

**Edit** `README.md`

```markdown
세션 비우기(`terminal-reset`), 고정 터미널 닫기(`terminal-close`)가 있다.
```

```markdown
세션 비우기(`terminal-reset`), 고정 터미널 닫기(`terminal-close`)가 있다. 0.3.0 부터 워커 환경 변수(`worker-start --env KEY=VALUE`, 되풀이)를 받는다. `launch-guard` 가 에이전트를 실행하기 바로 전에 그 환경에 넣는다(`hc run` 으로 띄운 터미널은 부른 셸의 환경을 물려받지 않는다). 값은 저장소와 `worker-show` 출력에 남으므로 비밀값을 넘기지 않는다.
```

**Edit** `README.md`

```markdown
`agent reset`, `test-confirm`)은 파일 큐
```

```markdown
`agent reset`, `test-confirm`, `slot reset`)은 파일 큐
```

**Edit** `README.md`

```markdown
tester owns 는 정확히 `["tests/<key>/**", "docs/qa/<key>.md"]`, tester 는 developer 에만 의존
```

```markdown
tester owns 는 정확히 `["tests/<key>/**", "docs/qa/<key>.md"]`(`[test] tester_paths` 가 있으면 그 경로들의 `{key}` 를 key 로 채운 것과 `docs/qa/<key>.md`), tester 는 developer 에만 의존
```

**Edit** `README.md`

```markdown
  exclusive = false     # 선택. DB·포트를 같이 써서 동시에 돌면 깨지면 true
```

```markdown
  exclusive = false     # 선택. DB·포트를 같이 써서 동시에 돌면 깨지면 true
  tester_paths = ["tests/{key}/**"]   # 선택. 묶음 tester 태스크의 시험 경로 형식({key} 를 항목마다 한 번)
  full_if = ["db/migrations/**"]      # 선택. developer 태스크가 이 경로를 바꾸면 quick 대신 full 을 돈다
```

**Edit** `README.md`

```markdown
(기록 `.herdr-team/state/tests/`, 로그 `.herdr-team/state/tests/logs/`).
```

```markdown
(기록 `.herdr-team/state/tests/`, 로그 `.herdr-team/state/tests/logs/`). developer 태스크가 바꾼 경로(지우거나 옮긴 파일 포함)가 `full_if` 에 맞으면 리뷰 관문과 `hteam test T-xxx` 가 quick 대신 full 을 한 번 돌고, 실패하면 quick 실패처럼 리뷰어 없이 돌려보낸다. `tester_paths`·`full_if` 는 돌릴 명령을 바꾸지 않으므로 다시 확정하지 않아도 된다.
```

**Edit** `README.md`

```markdown
- 한계: 테스트는 다른 워커가 일하는 같은 작업 폴더에서 돈다(커밋 안 된 다른 파일은 `dirty` 로 가른다).
```

```markdown
- 한계: 테스트는 다른 워커가 일하는 같은 작업 폴더에서 돈다(커밋 안 된 다른 파일은 `dirty` 로 가른다. 작업 공간을 켜면 개발·테스트 태스크의 시험은 그 슬롯에서 따로 돈다).
```

**Edit** `README.md`

````markdown
### 관제 복구
````

````markdown
### 작업 공간(선택, 병렬 개발)

- 개발 태스크 여럿을 동시에 돌리고 시험이 실제 DB·포트를 쓰는 프로젝트용이다. 한 폴더에서 함께 돌면 시험이 부딪치고 다른 태스크의 덜 된 코드가 quick 에 섞인다. 켜지 않으면(`[workspace]` 가 없거나 `mode = "shared"`) 지금처럼 한 폴더에서 돈다.
- 켜기(`.herdr-team/config.toml`, init 이 묻는다):

  ```toml
  [workspace]
  mode = "worktree"
  roles = ["developer", "tester"]   # 작업 공간 직무(기본)
  slots = 3                         # 동시에 쓰는 슬롯 수(1–9, 기본 2)
  setup = "pnpm install --frozen-lockfile && pnpm db:up"   # 선택. 슬롯을 새 태스크가 잡을 때 슬롯 폴더에서 한 번
  teardown = "pnpm db:down"         # 선택. 슬롯을 놓을 때
  setup_timeout_min = 20            # 선택(1–120)
  [workspace.env]                   # 선택. 값의 {slot} 은 슬롯 번호(메인 폴더는 0)
  APP_DB_PORT = "548{slot}9"
  ```

- 슬롯: 작업 공간 직무의 태스크는 처음 시작할 때 빈 슬롯 `.herdr-team/state/slots/slot-<N>`(저장소 전체의 git worktree)을 잡고, 메인 폴더의 지금 브랜치(기준 브랜치)에서 딴 `herdr/T-xxx` 브랜치에서 일한다. 슬롯은 병합하거나 버릴 때까지 그 태스크가 쥔다. 수정 라운드의 새 워커, 리뷰어, 관문 테스트도 같은 슬롯에서 돈다. 빈 슬롯이 없으면 기다린다.
- 그 직무는 임시 워커만 맡는다(라운드마다 새 세션). `[crew.*]` 의 `roles` 나 `user_approval_roles` 에 두면 설정 오류다. 기획·디자인은 지금처럼 메인 폴더에서 기준 브랜치에 바로 커밋한다.
- 환경: 워커·리뷰어·시험 명령·setup·teardown 은 그 슬롯의 `[workspace.env]` 값과 `HTEAM_SLOT` 을 받는다. setup·teardown 은 `HTEAM_MAIN_ROOT`(메인 프로젝트)·`HTEAM_SLOT_ROOT`(슬롯 작업 루트)도 받는다. 이름에는 `KEY`·`SECRET`·`TOKEN` 을 쓰지 않는다(Codex 셸 환경 정책이 뺄 수 있다). 로그는 `.herdr-team/state/slots/logs/`.
- 병합: 리뷰가 승인하면 관제가 메인 폴더에서 `git merge --no-ff` 로 기준 브랜치에 병합한 뒤 done 으로 둔다(병합 커밋 `[T-xxx] merge: <제목>`). owns 잠금과 의존은 병합까지 간다. 메인 폴더의 커밋과 겹쳐 거부되면 관제가 다시 시도하고, 10분 넘게 거부되면 메인에 알린다. 병합한 뒤 teardown 을 하고 슬롯을 비워 다음 태스크가 다시 쓴다(슬롯 폴더와 `node_modules` 같은 무시된 파일은 남긴다).
- 충돌: 병합이 충돌하면 되돌리고 그 태스크를 수정 라운드로 돌린다. 메인이 사용자에게 충돌 파일을 보이고 고칠지 버릴지 묻는다. 고치면 다음 라운드 워커가 기준 커밋을 그 브랜치에 병합해 충돌을 풀고, 리뷰를 다시 거친 뒤 관제가 병합한다.
- 메인 폴더에서 `git commit` 이 `index.lock` 으로 실패하면 몇 초 뒤 다시 한다(관제의 병합과 겹쳤다).
- 시험 도구 설정에서 `.herdr-team/` 를 뺀다: 슬롯 폴더가 메인 폴더 안에 있어 메인 폴더에서 직접 시험·린트를 돌리거나 IDE 가 색인하면 슬롯 사본이 섞인다. 예: vitest `exclude`, jest `testPathIgnorePatterns`, ESLint `ignores`, `tsconfig.json` 의 `exclude`, pytest `norecursedirs`. worktree 모드에서는 마지막 전체 테스트도 빈 슬롯에서 돈다(hteam 은 메인 폴더에서 시험을 돌리지 않는다).
- 더러운 슬롯: 버린 태스크의 슬롯에 커밋 안 된 변경이 남으면 그 슬롯을 쓰지 않는다. 메인이 사용자에게 `git -C <슬롯> status` 를 보이고, 버려도 된다고 하면 `hteam slot reset <N>`(되돌릴 수 없다)으로 비운다. `hteam doctor` 도 dirty 슬롯을 경고한다.
- 한계: 따로 리뷰를 통과한 두 태스크가 합쳐서 깨지는 경우는 묶음 tester 와 마지막 full 이 잡는다(한 폴더일 때보다 늦게 드러날 수 있다). 슬롯마다 설치가 따로라 처음 setup 이 오래 걸리고 디스크를 쓴다. hteam 이 SIGKILL 로 끝나면 setup 이 띄운 프로세스(DB 등)가 남을 수 있다. 여러 태스크가 한 줄씩 더하는 공용 등록 파일은 owns 를 나누지 않으면 그 태스크들이 한 줄로 선다(기능별 파일로 나누기를 권한다).

### 리뷰 점검표와 우선순위

- 프로젝트 점검표: `.herdr-team/review-extra.md` 가 있으면 리뷰 프롬프트에 `## 프로젝트 점검표` 절로 들어간다(앞 6000자). 프로젝트가 되풀이해 겪은 결함(행 잠금 뒤 한 번 읽은 DB 시각, 늦은 응답, 같은 자원 경로의 잠금 공유 등)을 매 리뷰에서 보게 할 때 쓴다. herdr-team 은 이 파일을 만들지 않는다(프로젝트가 쓰고 커밋한다). 읽지 못하면(UTF-8 이 아님 등) 절 없이 리뷰하고 경고를 남긴다.
- 우선순위: 리뷰 프롬프트의 리뷰 파일 경로·형식·판정 표기와 git 쓰기 금지, 워커 사양의 보고서 경로·커밋 형식·done 방법은 프로젝트 문서(AGENTS.md, CLAUDE.md 등)의 다른 규칙보다 앞선다. 코드·문구·디자인 기준은 프로젝트 문서도 따른다. 다른 보고서 경로나 이슈 트래커 갱신 규칙을 적어 둔 기존 문서와 부딪칠 때 이것이 정한다.
- 수정 라운드의 리뷰는 고친 함수·데이터를 읽는 다른 호출처와 출력 경로, 고친 방법이 만든 새 경계 조건(잠금 대기의 누적, 시각·순서, 늦은 응답)도 본다.

### Redmine 연동(선택)

- Redmine 이슈로 일하는 프로젝트용이다. `config.toml` 에 `[redmine]` 이 있을 때만 켜진다:

  ```toml
  [redmine]
  url = "https://redmine.example.com"
  key_env = "REDMINE_API_KEY"   # API 키를 담은 환경 변수 이름
  env_file = ".env"             # 선택. 있으면 이 파일(KEY=VALUE 줄)에서 key_env 를 읽는다. git 제외 파일이어야 한다
  status = { start = 2, done = 3, changes = 4, closed = 5 }   # Redmine 상태 번호
  ```

- 태스크 사양 front matter(또는 `docs/planning/tasks.toml` 의 태스크)에 `issue: 5712` 를 두면 그 이슈의 상태와 노트를 관제(프로그램)가 바꾼다. 워커·리뷰어·메인은 Redmine 을 바꾸지 않는다(API 키가 LLM 프롬프트에 들어가지 않는다).
- 바꾸는 때: 작업 라운드를 시작하면 `start`, 작업이 끝나면 `done`, 리뷰가 수정을 요청하면 `changes`, 리뷰 승인·병합·drop 은 노트만, 이슈를 닫을 때 `closed`. 묶음 tester 태스크가 끝나면 그 묶음의 이슈를 한꺼번에 닫고, 묶음 밖 태스크는 그 태스크가 끝날 때 닫는다. 같은 이슈를 가진 다른 태스크가 남았으면 닫지 않는다.
- 전송: 관제가 사건을 `.herdr-team/state/redmine/queue/` 에 쓰고 전송 자식(`hteam redmine-sync`)이 차례로 보낸다. 연결 실패·5xx 는 1·2·5·10분 간격으로 24시간까지 다시 보내고, 4xx(없는 이슈, 막힌 상태 전이, 권한)는 `failed/` 로 옮기고 알린다. `hteam status` 의 `redmine`(`pending`·`failed`·`last_error`)으로 본다. 키를 찾는지와 연결은 `hteam doctor` 가 본다.
- 키 값은 init 이 묻지 않는다. 환경 변수나 `env_file` 에 직접 둔다. 키는 큐·로그·outbox·프롬프트·테스트 명령 환경에 들어가지 않는다.
- 한계: Redmine 워크플로가 막는 전이(닫은 이슈를 다시 진행중으로)는 실패 기록만 남는다. 이슈 하나를 여러 태스크가 나누면 노트가 섞인다. 묶음 tester 가 drop 되면 그 묶음의 이슈를 닫지 않는다. 이슈를 만들거나 Redmine 에서 일을 가져오지 않는다. 관제가 사건 중간에 죽으면 노트가 빠지거나 두 번 갈 수 있다(빠진 종료는 사람이 닫는다).

### 관제 복구
````

**Edit** `README.md`

```markdown
- 리뷰 보기 pane 에서 친 키는 리뷰어에 들어간다(위 "리뷰 보기 pane"). 리뷰 보기 pane 의 입력을 막는 장치는 없다.
```

```markdown
- 리뷰 보기 pane 에서 친 키는 리뷰어에 들어간다(위 "리뷰 보기 pane"). 리뷰 보기 pane 의 입력을 막는 장치는 없다.
- 작업 공간 setup·teardown 은 `config.toml` 의 셸 문자열이고 관제 권한(사용자 권한, 샌드박스 없음)으로 돈다. `[test]` 처럼 확정 기록을 두지 않는다(`config.toml` 은 사용자 파일로 본다). 워커가 작업 트리의 `config.toml` 을 바꾸는 것은 막지 못한다.
- 슬롯 워커도 같은 사용자 권한으로 돌아 메인 폴더나 다른 슬롯을 고칠 수 있다. 사양의 작업 공간 절은 실수 방지이고 경계가 아니다. `hteam slot reset` 은 슬롯의 커밋 안 된 변경을 지운다(메인은 사용자가 확인한 뒤에만 부른다).
- Redmine API 키는 전송 자식만 읽고 프롬프트·로그·outbox·워커·테스트 환경에 넣지 않는다. 노트에는 작업 요약과 리뷰 지적 요약이 들어가 Redmine 서버로 나간다(워커가 쓴 글이 외부 서버에 남는다). `env_file` 은 git 제외여야 한다(추적하면 doctor 가 알린다).
```

**Edit** `README.md`

```markdown
#### 0.3.0 → 0.4.0
```

```markdown
#### 0.4.0 → 0.5.0

플러그인만 올리면 된다(herdr-orch 0.3.0 과 함께). 새 기능은 설정으로 켜고, 켜지 않으면 0.4.0 과 같이 돈다.

1. 플러그인을 올리는 것만으로 적용되는 것: 리뷰 프롬프트의 우선순위 줄과 수정 라운드 재검증 문구, 워커 사양의 우선순위 줄, `.herdr-team/review-extra.md`(만들면 리뷰에 붙는다).
2. 설정으로 켜는 것: `config.toml` 의 `[workspace]`(작업 공간)·`[redmine]`(Redmine), `docs/planning/tasks.toml` `[test]` 의 `tester_paths`·`full_if`, 태스크의 `issue`. 템플릿(`herdr-team/templates/config.toml`)의 주석 예시를 옮긴다.
3. 작업 공간이나 Redmine 을 켜면 `.herdr-team/bin/hteam upgrade` 의 `manual` 대로 `CLAUDE.md`·`AGENTS.md` 의 `<!-- herdr-team -->` 절을 `herdr-team/templates/CLAUDE.section.md`·`AGENTS.section.md` 와 견줘 고친다(새 decide `merge_conflict`·`workspace_failed` 처리 기준, `index.lock` 다시 시도, Redmine 줄, 작업 공간·이슈·우선순위 줄, 큐 명령 `slot reset`).
4. 작업 공간을 켜면 작업 공간 직무를 `[crew.*]` 의 `roles` 와 `user_approval_roles` 에서 빼고(남기면 설정 오류로 알린다), 시험 도구 설정에서 `.herdr-team/` 를 뺀다(위 "작업 공간").

#### 0.3.0 → 0.4.0
```

- [ ] **Step 4: 통과 확인**

Run: `cd herdr-team && python3 -m unittest tests.test_wording tests.test_setup tests.test_cli tests.test_design_docs 2>&1 | tail -3` 그다음 `bash herdr-team/tests/run.sh 2>&1 | tail -3`(저장소 루트에서, 백그라운드로 하나만, 10–15분)
Expected: 둘 다 `OK`(Task 7 의 `PromptTemplateP7Test`·`WorkSpecP7Test` 도 그대로 통과한다: 우선순위 문단 바로 뒤가 규칙 1 이고 규칙 6 이 끝이다).

- [ ] **Step 5: 정적 확인과 커밋**

```bash
python3 - <<'PY'
import ast, pathlib
for f in ["herdr-team/lib/hteam/setup.py", "herdr-team/lib/hteam/gitio.py", "herdr-team/lib/hteam/paths.py",
          "herdr-team/tests/test_wording.py", "herdr-team/tests/test_setup.py", "herdr-team/tests/test_cli.py"]:
    ast.parse(pathlib.Path(f).read_text(encoding="utf-8"), feature_version=(3, 11))
PY
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews'
FILES="herdr-team/skills/init/SKILL.md herdr-team/templates/CLAUDE.section.md herdr-team/templates/AGENTS.section.md herdr-team/templates/worker-rules.md herdr-team/lib/hteam/setup.py herdr-team/lib/hteam/gitio.py herdr-team/lib/hteam/paths.py herdr-team/.claude-plugin/plugin.json .claude-plugin/marketplace.json README.md herdr-team/tests/test_wording.py herdr-team/tests/test_setup.py herdr-team/tests/test_cli.py"
git add -- $FILES
git commit -m "feat(herdr-team): init·메인 규칙·문서의 작업 공간·Redmine(4a, decide 두 줄, index.lock, AGENTS·작업 규칙 줄, doctor worktree 점검, README), 0.5.0" \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- $FILES
```

Expected: ast 오류 없음, grep 빈 출력. 구현자는 여기서 멈춘다(컨트롤러가 `scripts/codex-review.sh commit <sha>`).

---

### Task 10: 실환경 확인 — S2, 작업 공간 흐름(슬롯 둘·병합·재사용·충돌·tester·마무리), 가짜 Redmine, shared 회귀, 결과 기록, 전체 시험, 브랜치 리뷰

설계 15.2 의 7단계를 본다. 사전 검증 S2(horch `--env` 로 띄운 Codex 워커의 셸 도구가 그 값을 보는지)는 **Task 1 커밋 바로 뒤에 컨트롤러가 한다**(설계 15.2 "S2(구현 계획 첫 태스크 뒤)"). 절차는 이 태스크의 Step 2 이고, 결과에 따라 Task 1 에 덧붙임 커밋을 하거나 Task 9 의 doctor 경고를 정한다(Step 2 의 갈래). 나머지(Step 3–13)는 Task 1–9 를 모두 마친 뒤 한다. 버리는 시험 프로젝트 둘(작업 공간·Redmine 을 켠 것, 아무것도 켜지 않은 shared 회귀용)에서 실제 Claude 메인·실제 임시 워커(비용을 줄이려 developer·tester 는 Claude sonnet, 리뷰어는 반대쪽 Codex)로 돌린다. 결과는 설계 15.4 에 `#### 7단계` 로 적고, 마지막에 두 전체 시험 모음과 브랜치 전체 Codex 리뷰(main 병합 전, CLAUDE.md)를 한다. 코드는 결함을 고칠 때만 바꾼다(고치면 그 결함을 재현하는 시험을 먼저 더하고, 고친 커밋마다 `scripts/codex-review.sh commit HEAD`). main 병합은 하지 않는다(컨트롤러가 한다).

보지 않는 것: 사용자 Redmine 의 실제 이슈(사용자에게 묻는다. 묻지 않고 하지 않는다, 설계 15.2 의 2), hc core 재시작, 고정 에이전트 흐름(6단계에서 봤다. shared 회귀는 6단계 실환경 2–3 의 축소판만), 슬롯 셋 이상.

**Files:**
- Modify: `docs/superpowers/specs/2026-11-05-herdr-team-design.md`(머리 상태 줄 "7단계는 구현·실환경 확인을 마쳤다(병합 대기)", 15.4 에 `#### 7단계`)
- Modify: 결함이 나온 파일과 그 시험(있을 때만). S2 가 Step 2 의 갈래 (b) 면 `herdr-orch/lib/horch/guard.py` 와 `herdr-orch/tests/test_env.py`

**Interfaces:**
- Consumes: Task 1–9 의 herdr-orch 0.3.0·herdr-team 0.5.0, 실제 `hc`·`herdr-app`·`claude`·`codex`·`git`
- Produces: S2 결과(설계 15.4 와 이 계획 끝 "확인하지 못한 것" 을 고친다), 실환경 확인 기록(설계 15.4), 전체 시험 결과, 브랜치 리뷰 반영

안전 규칙(이 태스크 내내, 6단계 Task 12 와 같다):
- 시험 폴더는 컨트롤러가 준 세션 스크래치패드 아래(`<세션 스크래치패드>/hteam-e2e-p7`, 이하 `$E2E`)에만 만든다. 이 저장소와 사용자의 다른 프로젝트는 건드리지 않는다. git worktree 는 시험 프로젝트 안에서만 생긴다(이 저장소에 만들지 않는다).
- **플러그인을 설치하지 않는다.** `claude plugin …` 을 쓰지 않는다. 시험 메인 Claude 는 `claude --plugin-dir "$REPO_ROOT/herdr-team"` 로 연다. Claude 워커·리뷰어는 시험 프로젝트 설정 `[agents.claude].args` 에 `--plugin-dir=<REPO_ROOT>/herdr-team` 를 넣는다. `hc run` 터미널은 부른 셸 환경을 물려받지 않으므로(6단계 실환경) 6단계와 같은 대체 인자를 시험 프로젝트 설정에만 넣는다: `[agents.claude].args` 에 `--settings=<E2E>/claude-settings.json`, `[agents.codex].args` 에 `-c` `shell_environment_policy.set.HERDR_TEAM_PLUGIN_ROOT="<REPO_ROOT>/herdr-team"` 와 `HERDR_ORCH_BIN` 같은 줄. 시험 터미널 환경에 `DISABLE_AUTOUPDATER=1`.
- 전역 파일: Step 1 이 `~/.claude/settings.json`, `~/.claude/plugins/*.json` 전체, `~/.codex/config.toml`, `~/.claude.json` 의 sha256 과 사본을 남기고(읽기만 한다) Step 12 가 견주고 diff 를 남긴다. 바뀌어도 되는 것: `~/.codex/config.toml` 의 시험 폴더 신뢰 항목, `~/.claude.json` 의 시험 폴더 프로젝트 항목과 Claude 가 실행마다 고치는 시작 기록(시작 횟수·캐시 등. S1 처럼 슬롯 폴더의 새 프로젝트 항목이 생기지 않는지 본다). 그 밖의 생성·삭제·수정은 실패로 적고 사용자에게 알린다. 스냅숏으로 덮어쓰지 않는다. `~/.codex/config.toml` 의 `shell_environment_policy` 는 바꾸지 않는다(S2 는 `-c` 로 시험한다).
- 사용자의 hc core 를 멈추거나 다시 띄우지 않는다(`hc server stop`·`restart`·`hc update` 금지). 새 `HC_SESSION` 금지. 시험이 만든 터미널·탭·space 만 kill·rm·닫는다. 시험용 `hc run` 은 늘 `--no-notify`.
- 폴더 신뢰 창: Claude 는 "Yes, I trust this folder", Codex 는 "Trust and continue"(이 폴더만). **"Trust all" 류는 절대 고르지 않는다.** 키는 운영자(이 태스크를 하는 에이전트)만 누른다.
- 운영자가 시험 메인에 글을 넣을 때는 `env -u HC_TERMINAL_ID hc send <메인> "<글>"`(감싸지 않는다). AskUserQuestion 은 `hc read <메인> --lines 60` 으로 보고 `hc keys` 로 고른다. **Codex 터미널은 `hc read --lines N`(N>0)으로 읽지 않는다**(Codex 를 done 에서 idle 로 바꾼다, X3b). Codex 는 `hc get` 의 status·turn·title 만 본다.
- 기다릴 때 sleep 으로 붙잡지 않는다: 도구의 감시(Monitor 의 until 루프)로 조건(파일·`hteam status` 출력·`hc get` 값)을 기다린다. 끝나면 남은 감시·백그라운드 프로세스가 없게 한다.
- Redmine 키는 시험용 가짜 값(`e2e-key-<임의 16자>`)이다. 이 값을 이 저장소·계획·설계 문서에 쓰지 않는다(15.4 에는 "가짜 키" 로만 적는다).
- 매 단계 뒤 작업 폴더를 저장소 루트로 돌린다. 시험 산출물은 이 저장소에 커밋하지 않는다. 셸 상태가 이어지지 않는 도구면 각 단계 앞에 Step 1 의 변수를 다시 정의한다.

- [ ] **Step 1: 변수, 시험 폴더, 전역 파일 스냅숏**

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"; H="$REPO_ROOT/herdr-team/bin/hteam"; O="$REPO_ROOT/herdr-orch/bin/horch"
E2E="<세션 스크래치패드>/hteam-e2e-p7"; mkdir -p "$E2E/s2" "$E2E/ws" "$E2E/shared" "$E2E/pre" "$E2E/post" "$E2E/marks"
python3 - "$E2E/pre" <<'PY'
import glob, hashlib, json, os, shutil, sys
home, out = os.path.expanduser("~"), sys.argv[1]
files = [os.path.join(home, ".claude", "settings.json"), os.path.join(home, ".codex", "config.toml"),
         os.path.join(home, ".claude.json"), *sorted(glob.glob(os.path.join(home, ".claude", "plugins", "*.json")))]
manifest = {}
for f in files:
    if os.path.isfile(f):
        manifest[f] = hashlib.sha256(open(f, "rb").read()).hexdigest()
        shutil.copyfile(f, os.path.join(out, os.path.relpath(f, home).replace(os.sep, "__")))
    else:
        manifest[f] = None
json.dump(manifest, open(os.path.join(out, "manifest.json"), "w"), indent=1)
print(len(manifest), "개:", ", ".join(os.path.relpath(f, home) for f in manifest))
PY
hc ls --all --json > "$E2E/pre/hc-ls.json"
{ hc --version; herdr-app --version; claude --version; codex --version; git --version; python3 --version; } > "$E2E/pre/versions.txt" 2>&1
printf '%s\n' '{"env": {"HERDR_TEAM_PLUGIN_ROOT": "'"$REPO_ROOT"'/herdr-team", "HERDR_ORCH_BIN": "'"$O"'", "DISABLE_AUTOUPDATER": "1"}}' > "$E2E/claude-settings.json"
```

Expected: `manifest.json`(파일마다 sha256, 없던 파일은 null)과 사본, `hc-ls.json`, 버전 여섯 줄(git 2.23 이상).

- [ ] **Step 2: 사전 검증 S2(컨트롤러가 Task 1 커밋 바로 뒤에 한다)**

horch 만으로 본다(herdr-team 없이). 시험 셸 터미널 하나를 Run 소유자로 쓰고, 그 셸에서 `horch worker-start --agent codex --env` 로 Codex 워커를 띄워 셸 도구가 값을 보는지 확인한다.

```bash
mkdir -p "$E2E/s2/work" && git -C "$E2E/s2/work" init -q -b main && git -C "$E2E/s2/work" commit -q --allow-empty -m init
herdr-app do space.new --name hteam-e2e-p7-s2 --folder "$E2E/s2/work"
```

Expected: `{"space", "tab", "terminal"}`. 셸 터미널을 `$S2T` 로 적는다. 그 셸에서(운영자가 `env -u HC_TERMINAL_ID hc send "$S2T" "…"` 로 넣는다) 세 번 띄운다. 사양은 셋 다 같다: `셸에서 printf '%s' "$HT_S2" > s2-<이름>.txt 를 실행하고(값이 비어도 파일을 만든다), 다른 것은 하지 않고 프리앰블의 done 명령을 --outcome succeeded --summary s2 로 부른다.`

```bash
"$O" --home "$E2E/s2/horch" run-create --objective s2
"$O" --home "$E2E/s2/horch" worker-start --agent codex --title s2-default --cwd "$E2E/s2/work" --env HT_S2=8110 \
  --agent-arg=--dangerously-bypass-approvals-and-sandbox --spec "<위 사양, 이름 default>"
"$O" --home "$E2E/s2/horch" worker-start --agent codex --title s2-include --cwd "$E2E/s2/work" --env HT_S2=8110 \
  --agent-arg=--dangerously-bypass-approvals-and-sandbox --agent-arg=-c \
  '--agent-arg=shell_environment_policy.include_only=["PATH","HOME"]' --spec "<위 사양, 이름 include>"
"$O" --home "$E2E/s2/horch" worker-start --agent codex --title s2-inherit --cwd "$E2E/s2/work" --env HT_S2=8110 \
  --agent-arg=--dangerously-bypass-approvals-and-sandbox --agent-arg=-c \
  '--agent-arg=shell_environment_policy.inherit="core"' --spec "<위 사양, 이름 inherit>"
```

각 워커가 끝나면(`horch check --wait` 의 worker_done, 또는 Monitor 로 파일을 기다린다) `s2-default.txt`·`s2-include.txt`·`s2-inherit.txt` 의 내용을 본다. Codex 폴더 신뢰 창이 뜨면 "Trust and continue" 를 고른다. 끝나면 세 워커를 `worker-release` 하고 시험 space 를 닫는다(`herdr-app do space.close`, 남은 터미널은 `hc rm`).

갈래(결과를 설계 15.4 의 `#### 7단계` 의 S2 줄과 이 계획 끝 "확인하지 못한 것" 에 적는다):
- (a) 셋 다 `8110` 이면 더 하지 않는다.
- (b) 하나라도 비었으면 Codex 에는 값을 `-c shell_environment_policy.set.<이름>=<JSON 문자열>` 인자로도 넘긴다(설계 15.2 S2): `herdr-orch/lib/horch/guard.py` 의 `inject_codex_env` 가 Dispatch env 의 이름마다 그 인자를 `HC_TERMINAL_ID` 인자 뒤에 더한다(이름 순서). 먼저 `herdr-orch/tests/test_env.py` 에 codex 가짜 에이전트 argv 의 `-c shell_environment_policy.set.HT_S2="8110"` 를 보는 시험을 더하고(RED) 고친 뒤 `bash herdr-orch/tests/run.sh`, 커밋 `fix(herdr-orch): Codex 셸에 --env 값을 shell_environment_policy.set 으로도 넘긴다(S2)`, 커밋 리뷰. 그다음 같은 세 워커로 다시 본다.
- (c) (b) 뒤에도 빈 설정이 있으면(그 정책이 `set` 도 막으면) Task 9 의 doctor 에 경고를 더한다: worktree 모드이고 `[workspace.env]` 가 있으며 `~/.codex/config.toml`(읽기만)의 `shell_environment_policy` 가 그 설정이면 `codex_env_policy`(경고) `Codex 의 shell_environment_policy(<키>) 가 [workspace.env] 값을 Codex 셸에서 뺄 수 있다. 사용자 설정을 확인한다`. Task 9 가 이미 커밋됐으면 같은 절차(시험 먼저, 커밋, 리뷰)로 덧붙인다.

- [ ] **Step 3: 작업 공간 시험 프로젝트(포트를 여는 시험, setup·teardown, 가짜 Redmine)**

```bash
cd "$E2E/ws"
git init -q -b main
mkdir -p src/a src/b tests scripts
cat > README.md <<'EOF'
# ws

작업 공간 실환경 확인용 시험 프로젝트(표준 라이브러리 Python).
EOF
cat > src/__init__.py <<'EOF'
EOF
cat > src/a/__init__.py <<'EOF'
EOF
cat > src/b/__init__.py <<'EOF'
EOF
cat > src/a/core.py <<'EOF'
def name():
    return "a"
EOF
cat > scripts/related.py <<'EOF'
"""[test] 도우미(시험용). quick: 인자 파일마다 관련 unittest 파일(테스트 파일이면 그것, src/x/y.py 면 src/x/test_y.py)을
돌린다. --all 이면 src/**/test_*.py 와 tests/**/test_*.py 전부. 실행 전에 HT_PORT 로 포트를 하나 열어 둔다(슬롯마다 달라야
동시에 돌아도 부딪치지 않는다). 연 포트와 cwd 를 메인 프로젝트의 .herdr-team/state/e2e-marks/ 에 남긴다.

메인 루트: 테스트 명령 환경에는 HTEAM_MAIN_ROOT 가 없다(setup·teardown 에만 있다). git common dir 의 부모로 찾는다(슬롯
worktree 든 메인 폴더든 메인 저장소 폴더다. 이 시험 프로젝트는 저장소 루트다).

멈춤 지점: 포트를 연 뒤 표시 파일을 남기고, e2e-marks/hold 가 있는 동안 테스트를 돌리지 않고 포트를 쥔 채 기다린다(최대
HOLD_MAX_S). 운영자가 hold 를 지우면 이어 한다. 그래서 두 슬롯의 테스트가 둘 다 포트를 연 상태를 표시 파일로 확인할 수
있고, 리뷰 관문의 quick 이 끝나지 않아 그 태스크가 운영자가 풀기 전에 승인·병합되지 않는다."""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

HOLD_MAX_S = 20 * 60  # [test] timeout_min(기본 30분)보다 짧게


def main_root() -> Path:
    out = subprocess.run(["git", "rev-parse", "--git-common-dir"], capture_output=True, text=True).stdout.strip()
    return Path(out).resolve().parent if out else Path(".").resolve()


def pick(args):
    found = set()
    for raw in args:
        path = Path(raw)
        if path.suffix != ".py":
            continue
        if path.name.startswith("test_"):
            found.add(path)
        elif path.parts[:1] == ("src",) and (path.parent / f"test_{path.name}").exists():
            found.add(path.parent / f"test_{path.name}")
    return sorted(found)


def main(args):
    port = int(os.environ.get("HT_PORT", "0"))
    marks = main_root() / ".herdr-team" / "state" / "e2e-marks"
    marks.mkdir(parents=True, exist_ok=True)
    with socket.socket() as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", port))  # 다른 슬롯과 같은 포트면 여기서 실패한다
        srv.listen()
        (marks / f"test-{os.environ.get('HTEAM_SLOT', 'none')}-{os.getpid()}.txt").write_text(
            f"cwd={os.getcwd()} port={srv.getsockname()[1]} args={args} at={int(time.time())}\n")
        deadline = time.monotonic() + HOLD_MAX_S
        while (marks / "hold").exists() and time.monotonic() < deadline:  # 포트를 쥔 채 운영자를 기다린다
            time.sleep(0.2)
        files = sorted(Path("src").glob("**/test_*.py")) + sorted(Path("tests").glob("**/test_*.py")) \
            if args == ["--all"] else pick(args)
        if not files:
            print("관련 테스트 없음")
            return 0
        names = [str(f.with_suffix("")).replace("/", ".") for f in files]
        return subprocess.call([sys.executable, "-m", "unittest", "-v", *names])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
EOF
cat > scripts/slot-setup.sh <<'EOF'
#!/bin/sh
# 작업 공간 setup(시험용): 슬롯·작업 루트·포트를 메인 상태 폴더의 표시 파일에 남긴다(슬롯 작업 트리를 더럽히지 않는다)
mkdir -p "$HTEAM_MAIN_ROOT/.herdr-team/state/e2e-marks"
printf 'setup slot=%s root=%s port=%s\n' "$HTEAM_SLOT" "$HTEAM_SLOT_ROOT" "$HT_PORT" >> "$HTEAM_MAIN_ROOT/.herdr-team/state/e2e-marks/slots.log"
EOF
cat > scripts/slot-teardown.sh <<'EOF'
#!/bin/sh
printf 'teardown slot=%s\n' "$HTEAM_SLOT" >> "$HTEAM_MAIN_ROOT/.herdr-team/state/e2e-marks/slots.log"
EOF
chmod +x scripts/slot-setup.sh scripts/slot-teardown.sh
printf '.env\n' > .gitignore
printf 'REDMINE_API_KEY="%s"\n' "e2e-key-$(python3 -c 'import secrets;print(secrets.token_hex(8))')" > .env
git add -- README.md src scripts .gitignore
git commit -qm "chore: 바탕"
cat > "$E2E/fake-redmine.py" <<'EOF'
"""가짜 Redmine(시험용). PUT /issues/<N>.json 을 requests.jsonl 에 남기고 204. 이슈 999 는 404, 998 은 422. GET
/users/current.json 은 키가 맞으면 200. 키 값은 기록하지 않고 맞았는지만 남긴다."""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG, KEY = sys.argv[1], sys.argv[2]


class H(BaseHTTPRequestHandler):
    def _log(self, body):
        with open(LOG, "a") as fh:
            fh.write(json.dumps({"method": self.command, "path": self.path, "key_ok": self.headers.get("X-Redmine-API-Key") == KEY,
                                 "body": body}, ensure_ascii=False) + "\n")

    def do_GET(self):
        self._log(None)
        self.send_response(200 if self.headers.get("X-Redmine-API-Key") == KEY else 401)
        self.end_headers()
        self.wfile.write(b'{"user": {"id": 1}}')

    def do_PUT(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        self._log(body)
        code = 404 if self.path.startswith("/issues/999") else 422 if self.path.startswith("/issues/998") else 204
        self.send_response(code)
        self.end_headers()


ThreadingHTTPServer(("127.0.0.1", int(sys.argv[3])), H).serve_forever()
EOF
echo "표준 라이브러리 Python 작은 라이브러리 두 모듈(src/a, src/b). 작업 공간(worktree 슬롯 둘)과 Redmine 연동 실환경 확인용으로 작게 만든다." > "$E2E/ws-desc.txt"
cd "$REPO_ROOT"
```

Expected: 커밋 하나. `.env` 는 git 제외. 가짜 Redmine 은 Step 4 에서 시험 터미널로 띄운다.

- [ ] **Step 4: 시험 space, 가짜 Redmine, 시험 메인 Claude, init(설계 9.1 의 4a)**

```bash
herdr-app do space.new --name hteam-e2e-p7 --folder "$E2E/ws"
hc run --bg --json --no-parent --no-notify --keep --name hteam-e7-redmine --cwd "$E2E" -- \
  python3 "$E2E/fake-redmine.py" "$E2E/redmine-requests.jsonl" "$(sed -n 's/^REDMINE_API_KEY="\(.*\)"$/\1/p' "$E2E/ws/.env")" 18765
```

Expected: space 의 `{"space", "tab", "terminal"}`(셸 터미널을 `$M` 으로 적는다), 가짜 Redmine 터미널 주소(`$RM`). 그 셸에 `env -u HC_TERMINAL_ID hc send "$M" "cd '$E2E/ws' && export DISABLE_AUTOUPDATER=1 && claude --plugin-dir '$REPO_ROOT/herdr-team'"`. 신뢰 창이면 "Yes, I trust this folder". 그다음 `env -u HC_TERMINAL_ID hc send "$M" "/herdr-team:init $(cat "$E2E/ws-desc.txt")"`.

승인 표(AskUserQuestion)에서 고를 것: 고정 에이전트 없음(`[crew.*]` 없음. 작업 공간 직무는 고정 에이전트가 될 수 없다, 4.2), director·designer 없음(`user_approval_roles = []`), `[roles.developer]`·`[roles.tester]` 는 `worker = "claude"`·`claude_model = "sonnet"`, 작업 공간 줄은 "쓴다"(슬롯 2, setup `sh scripts/slot-setup.sh`, teardown `sh scripts/slot-teardown.sh`, env `HT_PORT = "81{slot}0"`), Redmine 줄은 "쓴다"(URL `http://127.0.0.1:18765`, `key_env = "REDMINE_API_KEY"`, `env_file = ".env"`, 상태 `start = 2, done = 3, changes = 4, closed = 5`). 키 값을 묻지 않는지 본다(묻으면 결함으로 적는다). 표가 다르게 나오면 메인과 대화해 위 구성으로 맞춘다.

확인(운영자 셸에서 `"$H" --root "$E2E/ws" status` 와 `"$H" --root "$E2E/ws" doctor`):
- `config.toml` 에 `[workspace]`(mode worktree, slots 2, setup·teardown, env)와 `[redmine]`. `status` 의 `workspace.mode: "worktree"`, `slots` 두 개 `free`, `redmine.enabled: true`, `pending: 0`.
- doctor: git 2.23 이상·첫 커밋 통과, Redmine 키 찾음(값은 보이지 않는다), `GET /users/current.json` 200, `env_file` 추적 안 됨. 가짜 서버 기록에 GET 한 줄(`key_ok: true`).
- init 이 시험 도구 설정에서 `.herdr-team/` 를 빼자고 제안했는지(이 시험 프로젝트는 unittest 라 해당 설정이 없다. 제안 문구만 본다).
- 그다음 운영자가 시험 프로젝트의 `.herdr-team/config.toml` 에 Step 1 의 대체 인자(`[agents.claude].args` 의 `--plugin-dir`·`--settings`, `[agents.codex].args` 의 `-c shell_environment_policy.set.…` 두 줄)를 더하고 커밋한다(시험 프로젝트 파일만).

- [ ] **Step 5: 개발 태스크 둘이 슬롯 1·2 에서 동시에(설계 15.2 의 7단계 1)**

먼저 운영자가 테스트 멈춤 표시를 만든다(시험 도우미 `related.py` 의 멈춤 지점. 두 슬롯의 테스트가 실행 속도와 상관없이 겹치게 한다): `mkdir -p "$E2E/ws/.herdr-team/state/e2e-marks" && touch "$E2E/ws/.herdr-team/state/e2e-marks/hold"`.

메인에 요청(비용을 줄이려 기획 태스크 없이 메인이 사양을 쓴다, 7.7): "개발 태스크 셋과 묶음 테스트 하나를 만든다. T-001: `src/a/core.py` 에 `greet(x)` 를 더하고 `src/a/test_core.py`(owns `src/a/**`, issue 101). T-002: `src/b/calc.py` 에 `add(a, b)` 와 `src/b/test_calc.py`(owns `src/b/**`, issue 102). T-003: `src/a/core.py` 의 `name()` 이 `"A"` 를 돌려주게(owns `src/a/**`, depends_on 없음, issue 103). 묶음 테스트 T-004(tester, depends_on T-001·T-002, owns `tests/<key>/**`·`docs/qa/<key>.md`, issue 104). `docs/planning/tasks.toml` 의 `[test]` 는 quick `python3 scripts/related.py {files}`, full `python3 scripts/related.py --all`. 사양을 모두 커밋하고 T-001·T-002·T-004 를 start 한다(T-004 는 의존이 끝나면 관제가 띄운다). T-003 은 사양만 두고 지금 시작하지 않는다(Step 7 에서 시작한다)." `[test]` 확정 질문에는 `확정한다 (추천)`. T-003 을 지금 시작하지 않는 까닭: 처음부터 시작 대기열에 두면 T-001 이 끝나자마자 관제가 띄워 운영자가 기준 브랜치를 고치기 전에 병합까지 끝날 수 있다(Step 7 의 충돌이 실행 속도에 기댄다). 상태 없는 사양은 start-ready 가 띄우지 않는다.

멈춤 풀기: 감시(Monitor 의 until 루프)로 `e2e-marks/test-1-*.txt` 와 `test-2-*.txt` 가 둘 다 생길 때까지 기다린다. 두 테스트는 포트를 연 채 표시를 남기고 `hold` 가 있는 동안 기다리므로, 둘 다 있으면 두 포트(8110·8120)가 함께 열려 있다. 그때 `hc get` 으로 두 워커가 살아 있는지 보고 `rm "$E2E/ws/.herdr-team/state/e2e-marks/hold"` 한다.

확인:
- `status` 의 `workspace.slots`: T-001·T-002 가 슬롯 1·2 에(`preparing` → `busy`). T-003 은 상태가 없다(시작하지 않았다). drive.log 에 `slot-1 T-001 준비 …`·`slot-1 T-001 setup passed`(문구는 Task 4 의 원문) 같은 줄, `e2e-marks/slots.log` 에 `setup slot=1 … port=8110`·`setup slot=2 … port=8120`.
- 두 워커의 `hc get` cwd 가 각 슬롯의 작업 루트(`$E2E/ws/.herdr-team/state/slots/slot-1`, `slot-2`), 신뢰 창 없이 Claude 입력란이 떴다(S1). `horch worker-show` 의 `env` 에 `HT_PORT`·`HTEAM_SLOT`.
- 워커가 슬롯 밖을 고치지 않았다: 메인 폴더 `git status --porcelain` 가 비었다(사양 커밋 뒤). 각 슬롯의 `git -C <슬롯> branch --show-current` 가 `herdr/T-001`·`herdr/T-002`.
- quick 이 슬롯에서 돌았다: `e2e-marks/test-1-*.txt` 의 `cwd=…/slot-1 port=8110`, `test-2-*.txt` 의 `cwd=…/slot-2 port=8120`(표시 파일은 메인의 `e2e-marks/` 에 있다. 슬롯 안 `.herdr-team/state/e2e-marks/` 에는 없다), 두 테스트가 함께 포트를 쥔 채 멈췄다가(멈춤 풀기 전 두 표시) 풀린 뒤 포트 충돌 없이 통과.
- Codex 리뷰어의 `hc get` cwd 가 슬롯이고 리뷰 파일 커밋 `[T-001] review r1:` 이 `herdr/T-001` 에 있다(메인 브랜치에는 아직 없다).
- Redmine: `redmine-requests.jsonl` 에 #101·#102 의 `status_id: 2`(시작 노트 `herdr-team: T-001 r1 작업을 시작했다(개발, Claude).`), done 뒤 `status_id: 3`. 모든 줄 `key_ok: true`.

- [ ] **Step 6: accept 의 `--no-ff` 병합과 슬롯 재사용**

확인:
- T-001 승인 뒤 메인 폴더 `git log --first-parent -3 --format=%s main` 에 `[T-001] merge: <제목>`, 그 커밋의 부모가 둘. 태스크 상태 `workspace.merge` 가 그 sha, `status: done`. drive.log `T-001 병합 <sha 7자>`, Redmine #101 노트 `기준 브랜치 main 에 병합했다(<sha 7자>).`
- 놓기: `slots.log` 에 `teardown slot=1`, 슬롯 1 이 `free`, `git -C <슬롯 1> status` 가 detached HEAD, `git branch --list herdr/T-001` 이 비었다(지웠다).
- T-002 도 같은 병합·놓기를 지난다. 두 태스크가 done 이 되면 T-004(tester)를 관제가 띄운다(Step 8). 슬롯 재사용은 Step 7 의 T-003 이 본다.

- [ ] **Step 7: 충돌(`merge_conflict`)과 기준 병합 라운드**

차례를 고정한다(실행 속도에 기대지 않는다):

1. 운영자가 멈춤 표시를 다시 만든다: `touch "$E2E/ws/.herdr-team/state/e2e-marks/hold"`. 이제 T-003 의 quick(워커의 `hteam test`, 리뷰 관문)은 포트를 연 채 기다리므로 T-003 은 운영자가 풀기 전에 승인·병합되지 않는다(Step 8 의 T-004 full 이 그 사이 돌면 그것도 기다린다).
2. 메인에 "T-003 을 시작한다" 를 시킨다. 감시로 `"$H" --root "$E2E/ws" status` 의 `workspace.slots` 에 T-003 이 `busy` 로 보일 때까지 기다린다(예약 때 `slots.json` 의 그 슬롯 `base` 가 정해진다. 그 값이 지금 메인 HEAD 와 같은지 본다). T-003 은 놓인 슬롯(가장 작은 free, 보통 1)을 다시 쓴다: `slots.log` 에 그 슬롯의 `setup` 이 다시 돈다(태스크가 바뀌었으므로), 슬롯 폴더는 같은 경로다.
3. 그다음 운영자가 메인 폴더에서 기준 브랜치에 직접 같은 줄을 고쳐 커밋한다(사람의 커밋을 흉내 낸다. owns 잠금 밖이라 hteam 이 막지 않는다. 설계 15.2 의 "owns 밖 같은 파일" 을 이렇게 만든다):

```bash
cd "$E2E/ws" && sed -i '' 's/return "a"/return "a1"/' src/a/core.py && git commit -qam "사람: name 을 a1 로" && cd "$REPO_ROOT"
```

4. 커밋 뒤에 `rm "$E2E/ws/.herdr-team/state/e2e-marks/hold"` 로 푼다. T-003 의 기준(`base`)은 이 커밋 앞이고 병합은 이 커밋 뒤라 충돌이 늘 난다.

확인:
- T-003 승인 뒤 accept 의 병합이 충돌한다: drive.log 에 충돌 줄, 메인 폴더에 `MERGE_HEAD` 가 없다(`git merge --abort` 확인), T-003 `status: changes`, 상태의 `base_merge` 가 기준 HEAD sha, `base` 가 그 sha, 라운드 기록 `merge_conflict: {base, files: ["src/a/core.py"]}`. 메인 watch 에 decide `merge_conflict` 가 오고 메인이 사용자(운영자)에게 충돌 파일을 보인다.
- 운영자가 메인에 "`A` 를 쓴다(우리 쪽)" 라고 답한다 → 메인이 `hteam fix T-003 --note="…"`. 새 라운드 사양의 작업 공간 절 둘째 줄이 기준 병합 지시(`git merge --no-ff --no-commit <sha>` …)이고, 워커가 `[T-003] 기준 병합: <sha 7자>` 커밋을 만든다. 리뷰 시작 뒤 상태의 `base_merge` 가 지워진다. 리뷰 대상에 기준 병합 커밋이 들고 owns 밖 변경으로 반려되지 않는다. 다시 승인되면 병합이 성공하고 done.

- [ ] **Step 8: 묶음 tester(슬롯)와 마무리 full(슬롯), Redmine 닫기**

확인:
- T-004(tester)가 슬롯에서 돈다(`hc get` cwd, 브랜치 `herdr/T-004`). tester full 이 슬롯에서 돌았다(`e2e-marks/test-<n>-*.txt` 의 `args=['--all']`).
- T-004 done 뒤 Redmine 닫기: #101·#102·#104 에 `status_id: 5`(노트 `묶음 <key> 테스트(T-004)가 끝나 종료한다.`). #103(T-003, 묶음 밖)은 T-003 done 때 이미 `status_id: 5`(`T-003 가 끝나 종료한다.`).
- 마무리 full: `free` 슬롯 하나에서 기준 브랜치 HEAD 로 `git switch --detach` → setup → full → teardown(`slots.log` 순서), `state/tests/final.json` 의 `head` 가 그 커밋. 메인 폴더에서 시험이 돌지 않았다(`e2e-marks/test-*` 의 cwd 가 모두 슬롯).
- 4xx: 메인에 "T-005: `src/b/extra.py` 에 상수 `VERSION = 1` 을 더한다(developer, owns `src/b/extra.py`, issue 999)" 를 시켜 돌린다. `redmine-requests.jsonl` 에 #999 PUT 404, `.herdr-team/state/redmine/failed/` 에 항목 하나, progress 한 번, `status` 의 `redmine.failed: 1`·`last_error`. 뒤 사건(done 등)도 404 면 failed 가 늘고 메인 규칙대로 사용자에게 알린다.
- 키가 새지 않는다: `grep -rF "<가짜 키 값>" "$E2E/ws/.herdr-team/state" "$E2E/ws/docs" ~/.codex/sessions 2>/dev/null` 이 비었다(`.env` 밖 어디에도 없다. Codex·Claude 세션 기록 폴더는 시험 날짜 폴더만 본다).

- [ ] **Step 9: shared 회귀(설계 15.2 의 7단계 3)**

```bash
cd "$E2E/shared" && git init -q -b main && mkdir -p src && printf 'def one():\n    return 1\n' > src/one.py && git add -- src && git commit -qm "chore: 바탕" && cd "$REPO_ROOT"
herdr-app do space.new --name hteam-e2e-p7-shared --folder "$E2E/shared"
```

그 셸에서 시험 메인 Claude 를 띄우고 init(작업 공간·Redmine 줄은 "쓰지 않는다", 고정 에이전트 없음). 대체 인자를 Step 4 처럼 넣는다. 메인에 "src/one.py 에 two() 를 더하는 개발 태스크 하나" 를 시켜 리뷰·accept 까지 본다.

확인: `config.toml` 에 `[workspace]`·`[redmine]` 이 없다(주석 예시만). `status` 에 `workspace`·`redmine` 키가 없다. 워커 `hc get` cwd 가 프로젝트 루트, `worker-show` 의 `env` 가 null, 태스크 상태에 `workspace` 가 없다, accept 가 병합 커밋을 만들지 않는다(작업 커밋이 그대로 main 에). `.herdr-team/state/slots*`·`redmine/` 이 없다. 리뷰 프롬프트(`state/tasks/T-001/r1-review-a1.md` 같은 조립 파일)에 우선순위 줄과 라운드 절 문구가 있다(템플릿이라 shared 에도 적용).

- [ ] **Step 10: 기록(15.4)**

`docs/superpowers/specs/2026-11-05-herdr-team-design.md` 15.4 끝에 다음 틀로 적는다(값은 실제로 본 것. 못 본 것은 "보지 못함"):

```markdown
#### 7단계 (2026-11-xx)

환경: hc <버전>, herdr-app <버전>, Claude Code <버전>, codex-cli <버전>(리뷰 모델 gpt-6.1-sol xhigh), git <버전>, Python <버전>. 버리는 시험 프로젝트 둘(작업 공간·Redmine 을 켠 `ws`, 아무것도 켜지 않은 `shared`). 플러그인은 설치하지 않았고 `--plugin-dir` 와 대체 인자(6단계와 같다)를 썼다. 가짜 Redmine(로컬 HTTP, 가짜 키). 전역 파일 비교: <결과>.

- S2: 기본 <값>, `include_only` <값>, `inherit="core"` <값>. 처리: <(a) 그대로 | (b) shell_environment_policy.set 인자(커밋) | (c) doctor 경고(커밋)>.
- 시작: init 승인 표의 작업 공간·Redmine 줄 <그대로 | 고침>, 키 값을 묻지 않음 <예 | 아니오>, doctor <결과>.
- 슬롯 둘 동시: T-001 slot-1, T-002 slot-2, cwd·브랜치 <결과>, 신뢰 창 <없음 | 있음>, worker env <HT_PORT·HTEAM_SLOT>, quick 의 cwd·포트 <8110·8120, 겹친 시각 충돌 없음>, 리뷰어 cwd <슬롯>, 리뷰 커밋 위치 <태스크 브랜치>.
- 병합: `[T-001] merge:` <sha>, 부모 둘, 놓기 teardown·detach·브랜치 지움 <결과>, 슬롯 재사용 <T-003 slot-1, setup 다시>.
- 충돌: decide merge_conflict <파일>, abort 확인, base_merge·base 이동 <결과>, 기준 병합 커밋 <sha>, base_merge 지움 <결과>, 다시 병합 <결과>.
- tester·마무리: T-004 슬롯 <n>, 마무리 full 슬롯 <n>·head <sha>, 메인 폴더 시험 없음 <예>.
- Redmine: 사건별 상태·노트 <표>, 순서 <이슈마다 시작 → 작업완료 → … → 종료>, 4xx failed <n>, 키 누출 <없음>.
- shared 회귀: <결과>.
- 수치: 태스크 <n>개, 라운드 <표>, 전체 시간 <분>, 메인 컨텍스트 <%>.
- 발견한 문제와 처리: <없음 | 문제 → 고친 커밋>.
- 남은 것(사용자에게 알림): `~/.codex/config.toml` 의 시험 폴더 신뢰 항목, `~/.claude.json` 의 시험 폴더 항목, Codex·Claude 세션 기록, 시험 폴더.
```

머리 상태 줄의 "7단계(15.3 의 7)는 설계 중이다(herdr-team 0.5.0·herdr-orch 0.3.0)" 를 "7단계(15.3 의 7)는 구현·실환경 확인을 마쳤다(herdr-team 0.5.0·herdr-orch 0.3.0, 병합 대기)" 로 바꾼다. orch 설계 머리의 "0.3.0(14장, 워커 환경 변수)은 herdr-team 7단계와 한 주기로 설계 중이다" 도 "구현·실환경 확인을 마쳤다(병합 대기)" 로 바꾼다.

- [ ] **Step 11: 정리**

```bash
hc kill "<메인들>" "$RM" "<남은 워커·리뷰어 터미널>" 2>/dev/null; hc rm "<위 터미널과 끝난 터미널들>"
herdr-app do space.close --space "<시험 space 셋>"
herdr-app ls > "$E2E/post/herdr-app-ls.txt"; hc ls --all --json > "$E2E/post/hc-ls.json"
```

Expected: 시험 space 셋이 `herdr-app ls` 에 없다, `hc ls --all` 에 시험 터미널(`hteam-*`, 워커 Dispatch 이름, `hteam-e7-redmine`)이 없다(사용자 것은 `pre/hc-ls.json` 과 같다).

- [ ] **Step 12: 전역 파일 비교**

```bash
python3 - "$E2E/pre" "$E2E/post" <<'PY'
import difflib, glob, hashlib, json, os, sys
pre, post = sys.argv[1], sys.argv[2]
home = os.path.expanduser("~")
old = json.load(open(os.path.join(pre, "manifest.json")))
now = {f: (hashlib.sha256(open(f, "rb").read()).hexdigest() if os.path.isfile(f) else None) for f in old}
for f in sorted(glob.glob(os.path.join(home, ".claude", "plugins", "*.json"))):
    now.setdefault(f, hashlib.sha256(open(f, "rb").read()).hexdigest())
for f in sorted(now):
    if old.get(f) != now[f]:
        print("바뀜" if old.get(f) and now[f] else ("생김" if now[f] else "사라짐"), os.path.relpath(f, home))
        copy = os.path.join(pre, os.path.relpath(f, home).replace(os.sep, "__"))
        if os.path.isfile(copy) and os.path.isfile(f) and not f.endswith(".claude.json"):
            sys.stdout.writelines(difflib.unified_diff(open(copy).readlines(), open(f).readlines(), copy, f))
cj, copy = os.path.join(home, ".claude.json"), os.path.join(pre, ".claude.json")


def paths(x, y, at):
    """x → y 의 바뀐 키 경로(값은 내지 않는다)."""
    if isinstance(x, dict) and isinstance(y, dict):
        for k in sorted(set(x) | set(y), key=str):
            if k not in y:
                yield f"{at}.{k} 사라짐"
            elif k not in x:
                yield f"{at}.{k} 생김"
            elif x[k] != y[k]:
                yield from paths(x[k], y[k], f"{at}.{k}")
    elif x != y:
        yield f"{at} 바뀜"


if os.path.isfile(cj) and os.path.isfile(copy):
    a, b = json.load(open(copy)), json.load(open(cj))
    pa, pb = a.get("projects") or {}, b.get("projects") or {}
    e2e = os.path.realpath(os.path.dirname(os.path.abspath(pre)))
    for key in sorted(pa):  # 기존 프로젝트 항목: 바뀐 키 경로와 사라진 항목(값은 내지 않는다)
        if key not in pb:
            print("~/.claude.json 기존 프로젝트 항목 사라짐:", key)
        elif pa[key] != pb[key]:
            print("~/.claude.json 기존 프로젝트 항목 바뀜:", key, list(paths(pa[key], pb[key], "")))
    for key in sorted(set(pb) - set(pa)):  # 새 항목: 시험 폴더 안만 된다. 슬롯 폴더 항목은 생기면 안 된다(S1)
        real = os.path.realpath(key)
        inside = real == e2e or real.startswith(e2e + os.sep)
        kind = "슬롯 폴더(실패)" if "/.herdr-team/state/slots/" in real + "/" else ("시험 폴더" if inside else "시험 밖(실패)")
        print("~/.claude.json 새 프로젝트 항목:", kind, key)
    print("~/.claude.json 바뀐 최상위 키(projects 밖):",
          sorted(k for k in set(a) | set(b) if k != "projects" and a.get(k) != b.get(k)))
print("비교 끝")
PY
```

Expected: `바뀜 .codex/config.toml`(시험 폴더 신뢰 항목만, diff 로 확인), `~/.claude.json 새 프로젝트 항목` 이 `시험 폴더` 인 `ws`·`shared` 둘뿐(`슬롯 폴더(실패)`·`시험 밖(실패)` 줄이 없다, S1), `기존 프로젝트 항목 사라짐` 줄이 없고 `기존 프로젝트 항목 바뀜` 은 없거나 운영자 세션이 쓰는 이 저장소 항목의 시작 기록류(`lastSessionId`·비용·시각 같은 키 경로)뿐(사용자의 다른 프로젝트 항목이 바뀌면 실패다. 값은 출력하지 않으므로 키 경로로 판단한다), projects 밖의 바뀐 최상위 키는 Claude 시작 기록류뿐, `.claude/settings.json`·`.claude/plugins/*.json` 은 바뀌지 않음(바뀌면 6단계처럼 원인을 적고 사용자에게 알린다), `비교 끝`. 다르면 실패로 적고 사용자에게 알린다.

- [ ] **Step 13: 전체 시험(하나씩, 백그라운드), 결과 커밋, 브랜치 리뷰**

```bash
bash herdr-orch/tests/run.sh
```

Expected: `OK`. 끝난 뒤에만:

```bash
bash herdr-team/tests/run.sh
```

Expected: `OK`. 두 모음을 함께 돌리지 않는다. 실패하면 고치고(재현 시험 먼저) 커밋마다 리뷰한다. 그다음:

```bash
git add -- docs/superpowers/specs/2026-11-05-herdr-team-design.md docs/superpowers/specs/2026-11-04-herdr-orch-design.md
git commit -m "docs: herdr-team 7단계 실환경 확인 결과" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- docs/superpowers/specs/2026-11-05-herdr-team-design.md docs/superpowers/specs/2026-11-04-herdr-orch-design.md
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews'
scripts/codex-review.sh base main
```

Expected: 커밋 하나, grep 빈 출력, 리뷰 pane 주소. `hc wait <주소> --timeout 3600` 을 백그라운드로 걸고 끝나면 `.codex-reviews/base-design-herdr-team-p7.md` 를 읽는다. 지적은 Global Constraints 의 기준(P0·P1, 기본 경로 P2, 회귀)으로 사실을 확인해 고치거나 고치지 않는 이유를 적고, P0·P1 이 남지 않을 때까지 최대 3 라운드 다시 돌린다. 컨트롤러에게 결과(실환경 기록 요약, 시험 결과, 리뷰 지적과 처리)를 보고하고 멈춘다(main 병합은 컨트롤러가 한다).

---

## 설계에서 정하지 않아 계획이 정한 것

설계와 다르게 한 것(이유와 함께, 구현 전에 사용자·리뷰가 볼 수 있게):

- `HORCH_MIN = "0.3.0"` 은 브리프의 Task 9 가 아니라 Task 1 이다(herdr-team `test_versions_match` 가 함께 배포하는 herdr-orch 버전과 같기를 요구한다. 6단계와 같은 까닭).
- 브리프 Task 6 의 "작업 루트 cwd·슬롯 env·`HTEAM_SLOT`" 은 Task 4 다(작업 공간 리뷰 관문이 그것 없이 돌 수 없다). 리뷰 프롬프트의 작업 공간 줄도 Task 4 다.
- `testgate.child_env(cfg=None, extra=None)`: 헤더 계약은 `child_env(cfg, extra=None)`. 테스트 관문이 config.toml 없이 불릴 수 있어 cfg 를 선택 인자로 했다(Task 3). `hteam test` 는 7단계에도 `config.load` 를 부르지 않는다(설계 4.2·5.7 의 5단계 규칙 "설정이 깨져도 동작한다" 그대로, Codex 계획 리뷰 r1 에서 고쳤다). 슬롯 env·마무리 full 의 슬롯·key_env 빼기에 필요한 값만 Task 2 의 `config.test_settings(p)`(`TestSettings`: `workspace`, `redmine.key_env`)가 검사 없이 읽는다: `[workspace]` 표는 그 표의 검사를 통과할 때만 쓰고(아니면 shared), `key_env` 는 `config.redmine_key_env(p)` 로 이름만 맞으면 뺀다(`[redmine]` 의 다른 키가 틀려도). 쓰는 곳은 Task 4 의 `record_task`, Task 5 의 `run_final`, Task 6 의 `execute` 다. `slot_env`·`task_env`·`run_hook`·`claim_final`·`child_env` 는 `cfg.workspace`·`cfg.redmine.key_env` 만 쓰므로 `Config` 와 `TestSettings` 를 다 받는다. 관제·준비·놓기 자식은 지금처럼 `config.load` 의 `Config` 를 넘긴다. 리뷰 관문도 `test_settings` 를 지나지만 리뷰가 이미 검사한 설정이라 값이 같다.
- `[workspace.env]` 는 31개까지, 값에 NUL 이 없어야 한다(Task 2). 설계 4.2 에 개수 상한이 없지만 워커·리뷰어에는 `HTEAM_SLOT` 이 더해져 horch `--env` 상한 32(orch 설계 14.1)를 넘으면 setup 까지 마친 뒤 usage 로 막힌다. NUL 은 subprocess 환경이 받지 않는다(`ValueError`). 문구는 개수 `workspace.env 는 31개 이하다(HTEAM_SLOT 을 더해 horch --env 32개 안이다)`, 값은 설계 문구 그대로(Codex 계획 리뷰 r1).
- 준비 실패의 슬롯·태스크(Task 3): `branch_exists` 와 setup 실패는 슬롯 `free`(폴더 남김), 태스크 라운드 없는 `launch_failed`. setup 실패면 커밋 없는 빈 브랜치(`tip == base`)를 지우고 `git switch --detach` 한다(지우지 않으면 다시 시작이 다른 슬롯에서 `branch_exists` 로 막힌다). `setup_done` 은 None(반쯤 된 환경).
- 준비 자식은 `slots.json` 을 고칠 때마다 예약이 아직 그 태스크의 `preparing` 인지 다시 본다(Task 3). `slot prepare` 는 `preparing` 기록만 준비한다. `workspace_off`(exit 3)·`slot_not_reserved`(exit 3)는 설계에 없는 입력 검사다(shared 프로젝트에서 잘못 불린 자식이 `slots.json` 을 만들지 않게).
- 표시 파일 `marker` 는 설계의 common dir 비교에 더해 `slot` 1–9 정수, `task` 가 태스크 ID, `main_root/.herdr-team/config.toml` 이 있을 것도 본다(Task 3).
- `[workspace]` 기본 roles(Task 2): 표가 있고 `roles` 가 없으면 `developer`·`tester` 가운데 `[roles]` 에 정의된 것만, 둘 다 없으면 빈 튜플. 표가 없으면 기본값 그대로(shared 라 쓰이지 않는다).
- env 값 1 KiB 는 UTF-8 1024바이트로 센다(Task 1 horch `--env`, Task 2 `[workspace.env]` 같다). 이름의 `KEY`·`SECRET`·`TOKEN` 은 부분 문자열로 본다(`MONKEY` 도 막힌다).
- 템플릿 config.toml 의 env 예시 이름은 `APP_DB_PORT`·`APP_E2E_PORT_BASE` 다(설계의 `KCP_…` 는 요청 프로젝트 이름).
- `--retry` 없는 `--task`(앞 시도 abandoned·released)는 env 를 물려받지 않는다(orch 설계 14.1 은 `--task --retry` 만 적었다). `--terminal` Dispatch 는 앞 고정 Dispatch 의 env 를 옮겨 적는다(떠 있는 세션의 기록, Task 1). Codex 에는 env 를 환경으로만 넘긴다(S2 결과로 Task 10 이 바꿀 수 있다).
- 리뷰 프롬프트·워커 사양 템플릿 블록은 Step 1 이 아니라 Step 3 에 있다(Task 7, 6단계와 같다). `util.fill` 이 모르는 자리를 KeyError 로 내므로 템플릿만 먼저 바꾸면 모든 리뷰 시험이 깨져 RED 가 흐려진다.
- 워커 사양 우선순위 줄은 `worker-rules.md` 의 소유 경로 문단과 규칙 1 사이 문단이다(규칙 7 이 아니다: 지금 시험이 규칙 6 바로 뒤 `## 테스트` 를 고정한다, Task 7). 태스크별 이슈 줄은 `compose.work_spec` 이 작업 규칙 바로 앞에 넣는다(인수인계 줄 → 작업 공간 절 → 이슈 줄 → 작업 규칙). Task 9 의 worker-rules.md 줄은 규칙 1·3 끝의 일반 문장이다.
- `full_if`(Task 6): `repeat_test_failure` 를 full_if full 실패에도 건다(quick·full 이 섞이면 같은 실패로 보지 않는다). 저장된 full 기록은 상태와 관계없이 같은 라운드·code_head·식별값이면 다시 쓴다(설계 "tester 의 full 과 같다"). 프롬프트의 full_if 줄은 템플릿이 아니라 compose 상수다. `testgate.failed_quick` 은 `gate_failed` 로 바뀐다.
- Redmine(Task 8): 헤더 계약 `enqueue(…, **fields)` 를 `enqueue(p, cfg, st_or_tid, event, *, notes, issue=None)` 로 좁혔다. 설계 5.1 의 `issue` 물려받기(회귀 수정·묶음 정리 태스크)를 Task 8 에 넣었다(정리 태스크는 항목을 낸 태스크가 하나일 때만, "원인이 여럿이면 넣지 않는다" 를 글자대로). 4xx 와 함께 24시간 포기도 progress 로 한 번 알린다. 메인이 `unknown_regression` 으로 만드는 회귀 수정(`hteam task new`)은 issue 를 물려받지 않는다. `env_file` 이 있으면 그 파일만 읽는다(없거나 이름이 없으면 키 없음. 환경으로 내려가지 않는다). 키 없음도 재시도 간격을 탄다. 24시간은 보내기가 실패한 뒤부터 잰다. `#N` 은 `[redmine]` 과 상관없이 issue 가 있으면 붙는다(5.1).
- CLAUDE 절 decide 표 `merge_conflict` 줄은 설계 7.7 원문 끝의 ", 5.10.6"(설계 절 번호)을 뺐다(다른 줄도 절 번호를 적지 않는다). 메인 규칙·README 의 큐 명령 목록에 `slot reset` 을 더했다. `test_wording.test_decide_table_has_the_nine_kinds` 는 `test_decide_table_has_the_kinds` 로 이름을 바꿨다(Task 9).
- 작업 공간 시작(Task 4): detached HEAD 의 첫 시작은 exit 3 `base_detached` 이고 관제가 decide `workspace_failed`(kind `base_moved`, detail `detached: true`)로 올린다(설계 5.10.8 의 kind 다섯에 detached 가 없어 가장 가까운 `base_moved` 로 둔다). `slot_dirty` 의 decide 는 태스크 없이 올린다(태스크에 붙이면 열린 decide 때문에 start-ready 가 그 태스크를 건너뛰어 설계 5.10.3 의 2 "다른 슬롯이 비면 그것을 잡는다" 가 되지 않는다. detail 에 `task`). 준비 자식(`slot_step`)은 그 태스크에 열린 decide 가 있으면 띄우지 않는다(같은 실패의 되풀이를 막는다. 메인은 지금 규칙대로 `hteam start` 뒤 decide 를 `answer` 로 닫는다). `start_command` 는 라운드 없는 `launch_failed`(준비 실패 뒤)에서도 `slot_preparing`·`no_free_slot` 을 waiting 으로 돌려준다. 준비 자식 성공을 거두면 바로 `start_ready()` 를 한 번 부른다(다음 재확인 60초를 기다리지 않게). `lock_conflicts` 는 `done`·`dropped` 태스크가 쥔 슬롯 기록을 잠금으로 세지 않는다(놓기 동안에도 후행이 바로 시작한다, 잠금은 병합까지). 예약은 `free` 기록만 잡는다.
- `[test]` 설정은 작업 공간 태스크도 메인 프로젝트(상태 루트)의 커밋된 HEAD 에서 읽는다(태스크 브랜치 HEAD 가 아니다. 설정은 기획 태스크가 기준 브랜치에 커밋하고 확정 기록이 그 식별값이며 태스크 브랜치는 뒤처질 수 있다, Task 4). 리뷰 프롬프트의 작업 공간 줄은 `## 태스크` 의 `- 이전 리뷰:` 줄 뒤 글머리 줄 둘이다(템플릿 자리 `{{workspace}}`). 작업 공간 절의 env 줄은 이름 순이고 `HTEAM_SLOT` 은 보이지 않는다(horch `--env` 에는 넣는다).
- 병합(Task 5): 첫 거부 시각만 두지 않고 `merge_wait: {since, asked}` 를 쓴다(10분 거부·`MERGE_HEAD`·`base_moved` 를 각각 한 번만 올리려면 올린 kind 를 남겨야 한다). 병합 갈래는 git 메시지가 아니라 `MERGE_HEAD` 로 가른다(병합이 시작됐으면 충돌, 아니면 거부. 로캘을 타지 않는다). 기준 병합 라운드의 표시는 라운드 기록(`base_merge`·`merge_resume`)으로 사양에 들어간다. "바뀐 파일·사전 검사·관문은 지금 기준과 태스크 브랜치의 차이만 본다" 는 "부모가 둘 이상인 커밋은 `diff(base, HEAD)` 에 든 경로만 센다" 로 한다(병합 커밋의 첫 부모 diff 에는 기준에서 들어온 다른 파일이 들어 quick 이 그것까지 돈다). 관제 안의 CLI `hteam accept` 는 `after_accept` 를 거치지 않으므로 놓기는 다음 재확인이 한다(메인의 accept 는 큐라 바로 놓는다). 마무리 full 의 빈 슬롯 없음은 decide 없이 로그만 남기고 다음 재확인에 다시 한다(설계 "슬롯이 없으면 기다린다"). 병합 뒤 `workspace.task_root` 는 메인 폴더다(놓은 슬롯은 다른 태스크가 다시 쓴다). 놓기 뒤 `setup_done` 은 null 이다(teardown 했으니 다음 태스크가 setup 을 다시 한다).
- 준비 중 drop(Task 5): drop 이 준비가 끝나지 않은(`ready` 없는) 예약을 바로 푼다. 늦게 끝난 준비 자식은 Task 3 의 다시 확인으로 슬롯 기록을 쓰지 않으므로 설계 5.10.9 의 "늦게 끝난 자식이 슬롯을 ready 로 쓸 수 있다" 는 생기지 않는다. 대신 그 자식이 만든 브랜치·setup 결과(teardown 없음)가 남는다(한계로 적는다). `ready` 인 예약과 `busy` 는 관제의 놓기(teardown 포함)가 푼다.
- `roles.DRIVE_ONLY_MESSAGE`(설계 7.1 원문)와 큐 명령 목록에 `slot reset` 을 더했다(설계 5.10.8 이 큐 명령으로 정했다, Task 5·9).
- 준비 실패 뒤 fix(Task 4 Rules 12, Codex 계획 리뷰 r1): 작업 공간 직무 태스크의 `fix` 는 그 태스크가 `busy` 슬롯을 쥘 때만 한다. 아니면(준비 실패의 라운드 없는 `launch_failed` 등) 상태를 바꾸기 전에 exit 3 `slot_not_held`(hint `hteam start T`). 그대로 두면 `fix` 가 `_prepare_start` 를 거치지 않아 슬롯 env·작업 공간 절 없이 메인 폴더에서 워커가 뜬다. 관제의 자동 fix 는 이 경우를 부르지 않는다(`_launch_failed` 가 라운드 없는 것을 건너뛴다).
- decide `files` 의 작업 루트 산출물(Task 4 Rules 13, Codex 계획 리뷰 r1): 보고서(`report_rel`)와 리뷰 결과·hteam 반려 파일(`review_rel`)은 그 태스크의 작업 루트에서 찾아 메인 루트 기준 슬롯 경로(`.herdr-team/state/slots/slot-<N>/<rel>`)로 낸다(`Drive._work_files`). 사양·기획 문서·직무 문서·설정·로그는 메인 경로 그대로다.
- 놓기의 차례(Task 5 Rules 7, Codex 계획 리뷰 r1): teardown → 작업 트리 검사(슬롯의 `MERGE_HEAD`, 버린 태스크의 커밋 안 된 변경) → 깨끗하면 `switch --detach`·`branch -d`·`free`, 아니면 switch 하지 않고 태스크 없는 `dirty`(브랜치·병합 상태 그대로). switch 가 실패해도 `dirty` 로 간다(되풀이하지 않는다). 기준 병합 라운드 도중의 drop 이 슬롯을 `busy` 로 묶지 않는다. 알림은 리뷰 판정 지시서의 "decide `workspace_failed`(slot_dirty)" 가 아니라 설계 5.10.6 의 "버린 태스크의 슬롯에 커밋 안 된 변경이 있으면 `dirty` 로 두고 progress 로 알린다" 를 따랐다(계획과 설계가 다르면 설계가 맞다). 병합한 태스크인데 남긴 경우(`MERGE_HEAD`·switch 실패) progress 괄호는 `<T> 는 병합했다` 다.
- 병합 거부 알림의 차례(Task 5 Rules 5, Codex 계획 리뷰 r1): `workspace_failed` decide 를 쓴 뒤 `merge_wait.asked` 를 저장한다(앞 계획은 반대였다. 그 사이 중단되면 알림이 영영 빠졌다).
- 충돌 알림의 복구(Task 5 Rules 5, Codex 계획 리뷰 r1): 재확인은 `decide_round == round` 가 아니라 지금 있는 `outbox.read_outbox` 에서 그 태스크의 `merge_conflict` decide 가 라운드 기록의 `merge_conflict`(`base`·`files`)와 같은 detail 로 있는지 본다(같은 라운드의 다른 decide 가 남긴 표시에 가려지지 않는다). 새 상태 필드는 더하지 않았다.
- Redmine 전송자 하나(Task 8, Codex 계획 리뷰 r1): `hteam redmine-sync` 는 실행 내내 `state/redmine/sync.lock` 을 비차단으로 쥐고 못 쥐면 보내지 않고 `busy: true`(exit 0)로 끝난다. 관제의 자식 키 `redmine` 은 한 관제 안에서만 막으므로 관제가 다시 떴을 때 앞 관제의 자식과 겹치지 않게 한다. 잠금 순서는 `sync.lock` → `queue.lock` 만 된다.
- Redmine 오류 글(Task 8 Rules 6 의 4, Codex 계획 리뷰 r1): HTTP 오류 본문·연결 실패 까닭은 전체에서 키를 가린 뒤 200자로 자른다(자른 뒤 가리면 경계에 걸린 키의 앞부분이 남는다).
- 승인 직무의 닫기(Task 8 Rules 2 의 7, Codex 계획 리뷰 r1): `approval._apply`(design-decide·결정 복구)가 `tasks.accept` 로 `done` 을 만든 태스크마다 `redmine.close_for` 를 부른다(`after_accept` 와 같은 함수 하나).
- 실환경 시험 도우미(Task 10, Codex 계획 리뷰 r1): `related.py` 는 메인 루트를 `git rev-parse --git-common-dir` 의 부모로 찾는다(테스트 명령 환경에는 `HTEAM_MAIN_ROOT` 가 없다. 제품 env 계약은 바꾸지 않는다). 포트를 연 뒤 메인 `e2e-marks/hold` 가 있는 동안 기다리는 멈춤 지점을 두어, 두 슬롯 테스트가 함께 포트를 연 상태를 표시 파일로 확인한 뒤 풀고, 충돌 재현용 T-003 은 Step 7 에서 시작해 운영자가 기준 브랜치를 고친 뒤에야 관문을 지나게 한다. 그래서 Step 5 의 "T-003 이 owns 잠금으로 기다린다" 실환경 확인은 뺐다(예약의 owns 잠금은 Task 4 의 `test_reservation_holds_owns_lock` 이 본다). 전역 파일 비교는 `~/.claude.json` 의 `projects` 를 항목별로 견주어 기존 항목의 바뀐 키 경로·사라진 항목을 보이고(값은 내지 않는다) 새 항목은 시험 폴더만 받는다.

설계에 원문이 없어 계획이 정한 문구·값(각 태스크 Interfaces 에 원문. Codex 계획 리뷰 r1 에서 더한 것: Task 2 의 `WORKSPACE_ENV_MAX`·개수 문구·`TestSettings`·`RedmineKey`·`test_settings`·`redmine_key_env`, Task 4 의 `slot_not_held` 문구·`Drive._work_files`, Task 5 의 놓기 progress 괄호 갈래, Task 8 의 `BUSY_TEXT`·`busy` 결과·`redmine_sync_lock`, Task 10 의 `related.py` 멈춤 지점 `e2e-marks/hold`·`HOLD_MAX_S`):

- herdr-orch(Task 1): `--env` usage 문구 여섯과 검사 차례, `workers.ENV_MAX`·`ENV_VALUE_MAX`·`ENV_KEY_RE`·`parse_env`, 가짜 에이전트의 `FAKE_AGENT_ENV`, skill.md 한 줄.
- 설정·사양(Task 2): `[workspace]`·`[redmine]` 의 표·모르는 키·roles 문구, 사양 `issue` 문구 `issue 는 숫자 1–9자리 이슈 번호다(앞의 # 는 뗀다): <값>`, tasks.toml issue 문구, `[test]` 의 `tester_paths`·`full_if` 항목 문구, `confirm_section` 의 두 키 줄, 상수 `WORKSPACE_*`·`ENV_NAME_*`·`REDMINE_*`·`specs.issue_value`, `plan.group_problems(…, tester_paths=None)`. url·env_file 검사의 세부(공백 없음, `~`·절대 경로·`..` 금지). issue 의 앞자리 0 은 그대로.
- 작업 공간 코어(Task 3): `slot_not_reserved`·`slot_locked`·`slot_dirty`·`branch_exists`·`setup_failed`·`workspace_off`·`bad_slots_file` 문구와 hint, 실패 data(`kind`·`slot`·`files`·`branch`·`status`·`exit`·`log`·`tail`), `MINUTE_S`·`DIRTY_SHOWN`·`SLOT_DEFAULT`, 죽음 지점 넷, history 사건 `slot_branch_exists`·`slot_setup_failed`, `paths.project_at`, `workspace.write_marker`, gitio 함수 이름.
- 작업 공간 흐름 1(Task 4): `slot_preparing`·`no_free_slot`·`base_detached` 문구, 대기 꼬리 둘, drive.log 단계 낱말(`잡기`·`준비`·`사용`), decide `workspace_failed` 의 commands·detail 모양, `Drive.slot_step`·`_slot_done`, `workspace.view`·`env_args`, `compose.workspace_section`·`review_workspace`.
- 작업 공간 흐름 2(Task 5): `merge_pending`·`merge_blocked`·`base_moved`·`task_open`·`bad_slot`·`slot_not_dirty`·마무리 `no_free_slot` 문구, decide summary 둘, drive.log 병합·놓기 줄과 progress 두 줄, CLI `hteam slot release T`, 죽음 지점 둘, `compose.BASE_MERGE_LINE`·`MERGE_RESUME`, 슬롯 기록의 `use`·`reset_request`.
- 테스트 관문(Task 6): `GATE_FULL_PROBLEM`·`GATE_FULL_NOTE`·`FULL_IF_TESTS`·`FULL_IF_LINE`, 반려 파일의 `full_if 에 맞은 경로:` 줄, repeat 요약 문구, 워커 사양 줄 자리(developer 블록 둘째 줄 뒤).
- 리뷰 문구(Task 7): 점검표 경고 문구와 출력 자리(review 결과 `warnings`), 점검표 자르기 꼴, 템플릿 자리 `{{issue}}`·`{{extra}}`, `compose.ISSUE_LINE`·`REDMINE_ISSUE_LINE`·`issue_line`·`REVIEW_EXTRA`·`review_extra`.
- Redmine(Task 8): `redmine.py` 상수·함수, `state/redmine/status.json`, `redmine_off`·`bad_redmine_event`, progress·drive.log·키 없음·HTTP 오류 문구, doctor detail, 노트의 P1 줄 잇기(` / `, 없으면 `(없음)`), closed 노트의 key 는 tester 사양 `plan_key`(없으면 tester ID), `#N` 자리(ID 바로 뒤), `last_error` 규칙, 사건 자리, 닫을 수 있음의 판정.
- init·문서(Task 9): doctor `workspace_git`·`workspace_head`·`workspace_slots` 문구, `gitio.version`, init 4a 문장과 "하지 않는 것" 한 줄, AGENTS 절 넷, worker-rules 두 문장, CLAUDE 절 push 주석 머리, README 절 제목과 본문 전부.

알려진 한계(Codex 계획 리뷰 r1 에서 고치지 않기로 한 것과 고치며 남은 것. 구현에서 고치지 않는다):

- 준비 자식의 실패를 관제가 거두기 전에 관제가 죽고 그 자식이 실패하면 새 관제는 그 실패를 decide 로 올리지 못한다(관제 사망과 준비 실패가 겹치는 가장자리). 결과: `setup_failed`·`branch_exists` 는 라운드 없는 `launch_failed` 라 start-ready 가 한 번 다시 준비하고, 그 두 번째 실패는 새 관제가 거둬 decide 로 올린다. 준비 중 발견한 dirty 슬롯은 decide 없이 `dirty` 로 남고 `status` 의 `workspace` 에 보인다(r1 A1·B4).
- `workspace.roles` 에 planner 같은 직무도 넣을 수 있다. 설계 4.2 는 "정의되지 않은 직무" 만 거부하고 roles 를 사용자가 정하게 했다(기본은 developer·tester). 설계가 정한 범위라 계획에서 막지 않는다(r1 A2).
- `hteam test` 의 설정 읽기(`test_settings`): `[workspace]` 표가 깨졌으면 shared 로 보고 메인 폴더 env 없이 돈다(작업 공간 태스크는 `workspace.root` 에서 돌고 `HTEAM_SLOT` 만 받는다, 마무리 full 은 메인 폴더). 그때는 관제도 설정을 읽지 못해 멈춰 있고 메인이 고친다.
- 병합 거부 decide 를 쓴 뒤 `asked` 를 저장하기 전에 관제가 죽으면 다음 재확인이 같은 `workspace_failed` 를 한 번 더 올린다(빠지지는 않는다).
- 충돌 알림 복구는 outbox 의 `merge_conflict` detail(`base`·`files`)로 가린다. 같은 태스크가 다른 라운드에서 같은 기준·같은 파일로 다시 충돌하면(기준이 그동안 움직이지 않았고 워커가 기준 병합을 하지 않고 승인된 경우) 앞 decide 를 이번 것으로 보고 다시 올리지 않는다.
- 작업 공간 직무 태스크를 shared 모드에서 시작한 뒤 worktree 모드로 바꾸면 그 태스크의 fix 는 `slot_not_held` 로 거부된다(설계에 모드 바꾸기 규칙이 없다. 메인이 drop 하고 새로 만든다).
- 다른 전송자가 `sync.lock` 을 쥐고 있는 동안 관제는 틱마다 `busy` 로 바로 끝나는 전송 자식을 띄운다(보내지 않으므로 순서·중복에는 영향이 없다).

확인하지 못한 것(실환경 Task 10 또는 구현 때 본다):

- 실제 Codex 셸이 `--env` 값을 보는지(S2, 기본 설정과 사용자 `shell_environment_policy` 가 있을 때). 계획 단계에서 실제 Codex 를 띄우지 않았다(Task 10 Step 2, 컨트롤러가 Task 1 뒤).
- 실제 Claude 가 슬롯 cwd 에서 뜰 때 `CLAUDE_PROJECT_DIR` 이 작업 루트인지(훅의 `find_root` 가 기대는 값), 슬롯 폴더에 신뢰 창이 뜨지 않는지(S1 은 신뢰한 프로젝트 아래 새 폴더로 봤다).
- git 2.23 미만, 대소문자를 가리지 않는 파일 시스템에서 `--root` 철자가 git 이 아는 철자와 다를 때의 common dir 비교, 사용자가 슬롯 폴더만 지운 뒤의 `git worktree add`(방어 코드 없음).
- `git merge` 가 "untracked working tree files would be overwritten" 로 거부할 때 `MERGE_HEAD` 를 남기지 않는 것(git 동작으로 알고 시험이 본다. 계획 단계에서 Task 5 시범 구현을 돌리지 못했다).
- Task 5·8 의 시험은 Task 2–4 구현 없이 시범 구현을 돌리지 못했다(블랙박스 계약만으로 썼다). 구현 태스크에서 처음 돌릴 때 Task 4 와의 맞물림이 드러날 수 있다. Task 1·2·3·4·6·7·9 는 스크래치의 시범 구현으로 그 태스크 시험이 통과하는 것을 봤다(시범 코드는 계획에 넣지 않았다).
- 실제 Redmine 의 422·403 본문 꼴(실환경도 가짜 서버로만 본다. 사용자 Redmine 은 사용자에게 묻는다).
