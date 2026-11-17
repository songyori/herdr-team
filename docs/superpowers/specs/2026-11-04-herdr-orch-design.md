# herdr-orch 설계

- 날짜: 2026-11-04
- 상태: 0.1.x(1–12장)는 구현·실환경 확인을 마치고 병합했다(0.1.2). 0.2.0(13장, 고정 터미널)은 herdr-team 6단계와 한 주기로 구현·실환경 확인을 마치고 병합했다(2026-11-11). 0.3.0(14장, 워커 환경 변수)은 herdr-team 7단계와 한 주기로 구현·실환경 확인을 마치고 병합했다(2026-11-12). 0.4.0(15장, 부모 터미널)은 herdr-team 11단계와 한 주기로 구현·실환경 확인을 마치고 병합했다(2026-11-16). 0.5.0(16장, Claude 상태 대리 보고와 백그라운드 일)은 herdr-team 12단계(herdr-team 0.7.2)와 한 주기로 설계 중이다(2026-11-17. 처음에 herdr-team 에 두기로 한 것을 옮겼다).
- 범위: herdr-team 저장소의 첫 플러그인 `herdr-orch`

## 1. 목적

Orca orchestration 이 Orca 런타임 안에 가진 감독형 멀티 에이전트 조정 기능을 Herdr(herdr-app 창 + herdr-core `hc`) 위에 구현한다. 코디네이터 에이전트가 Claude·Codex 워커를 띄우고, 메일함으로 질문·보고를 주고받고, 워커가 끝나면 정리한다.

다음 플러그인 `herdr-team`(orca-team 에 해당: 메인·코디네이터·직무 워커, 직무별 모델, 병렬 실행, Codex 교차 리뷰)이 이 계층 위에 만들어진다. herdr-orch 는 herdr-team 이 쓰는 기능만 갖는다.

Orca 와 orca-team 코드에 의존하지 않는다. 개념만 참고한다.

## 2. 결정 사항

| 항목 | 결정 | 이유 |
|---|---|---|
| 분할 | herdr-orch 를 먼저 설계·구현·검증하고 herdr-team 은 별도 설계 | 경계가 깔끔하고 오케스트레이션 계층을 따로 검증할 수 있다 |
| 워커 배치 | Run 소유자(코디네이터)의 탭에 pane 으로 붙인다 | herdr-team 이 코디네이터를 "team" 탭에 띄우면 메인 탭은 깨끗하고 team 탭에서 워커 전부를 본다 |
| 기능 범위 | Run, worker-start, 메일함, ask/reply, worker_done, escalation, 생존 판정, release/retain/abandon | orca-team 이 Orca 에서 실제로 쓴 기능이다 |
| 워커 에이전트 | Claude 와 Codex | Codex 리뷰어도 워커로 띄워 team 탭에서 보이게 한다 |
| 구조 | SQLite 저장소 + `hc send` 깨우기, 데몬 없음 | 코디네이터가 죽어도 메일함이 남고 죽을 상주 프로세스가 없다 |

## 3. 용어

- **Run**: 감독 단위이자 코디네이터 메일함. 소유 터미널이 하나 있거나 없다.
- **소유자**: Run 에 묶인 터미널(코디네이터). 터미널 하나는 Run 하나에만, Run 하나는 터미널 하나에만 묶인다.
- **Task**: 할 일 하나. spec 본문을 갖는다.
- **Dispatch**: Task 를 수행하는 워커 실행 1회. 워커 터미널 하나와 짝이다. 0.2.0 부터 고정 터미널 하나가 Dispatch 여러 개를 차례로 맡을 수 있다(13장).
- **Message**: 메일함(`run:<id>` 또는 `dispatch:<id>`)에 쌓이는 기록.
- **Delivery**: 메일함에서 한 번에 넘겨주는 메시지 묶음(최대 50건). ack 전까지 같은 묶음을 다시 준다.
- **호출자**: `horch` 를 실행한 hc 터미널. `$HC_TERMINAL_ID` 로 정한다.
- **실행자**: `worker-start` 를 실행 중인 horch 프로세스.

## 4. 구성 요소와 파일 배치

Python 3.11 이상, 표준 라이브러리만 쓴다.

```
.claude-plugin/marketplace.json          마켓플레이스 "herdr-team"
herdr-orch/
  .claude-plugin/plugin.json
  bin/horch                              실행 파일. lib 를 sys.path 에 넣고 cli.main 호출
  lib/horch/
    cli.py        명령 파싱, JSON 출력, exit 코드
    errors.py     HorchError 와 exit 코드
    paths.py      저장 루트 결정, horch 절대 경로·명령, 버전
    ids.py        ID 와 시각 생성
    procs.py      프로세스 생존 확인(pid + 시작 시각)
    store.py      SQLite 연결, 스키마, 마이그레이션, 트랜잭션
    auth.py       호출자 확인(소유자·워커·외부)
    runs.py       run-create, run-use, status
    guard.py      launch-guard: 워커 터미널에서 에이전트보다 먼저 돌며 등록 후 exec
    hcio.py       hc 를 부르는 유일한 모듈: run, get, ls, read, send, kill, rm, server status. 0.2.0: keys, label, events(13.7)
    herdr.py      herdr-app 을 부르는 유일한 모듈: status
    agents.py     Claude·Codex 실행 명령 생성
    preamble.py   워커 프리앰블 생성
    mailbox.py    메일함 쓰기, Delivery, ack, 대기, 깨우기
    comms.py      send, check, reply, ask, escalate, done 명령
    workers.py    worker-start, list, show, release, retain, abandon, launching 조정
    liveness.py   생존 판정과 observed 메시지
    doctor.py     doctor 점검
    relay.py      0.5.0: Claude 상태 대리 보고, Stop 기록, relay-status(16장)
    skill.md      `horch skill` 이 출력하는 사용법
  hooks/hooks.json, hooks/horch_hook.py  0.5.0: Claude 훅(16.2)
  skills/herdr-orchestration/SKILL.md    스텁: `horch skill` 을 실행하라는 안내
  tests/
    fakes/hc, fakes/herdr-app            호출을 기록하고 정해진 응답을 주는 가짜
    test_*.py, run.sh
```

- 스킬 이름은 `herdr-orchestration` 이다. Orca 의 전역 스킬 `orchestration` 과 겹치지 않게 한다.
- `SKILL.md` 는 자기 폴더 기준 `../../bin/horch skill` 을 실행하라고만 적는다. `horch skill` 은 출력 첫 줄에 `horch` 의 절대 경로를 적고, 에이전트는 이후 그 경로를 쓴다.

### 저장 위치

- 루트: 모든 명령이 받는 `--home <경로>`, 없으면 `$HERDR_ORCH_HOME`, 없으면 `${XDG_STATE_HOME:-~/.local/state}/herdr-orch`. 권한 0700.
- DB: `<루트>/orch.db` (WAL 모드).
- Dispatch 파일: `<루트>/runs/<run>/dispatches/<dispatch>/` 아래 `spec.md`, `preamble.md`, `receipt.json`. 원본은 DB 이고 파일은 실행 직전에 DB 에서 만든다.
- 워커 프리앰블의 모든 horch 명령에는 `horch` 절대 경로와 `--home <확정한 절대 루트>` 를 넣는다. 워커의 환경 변수와 PATH 가 달라도 같은 DB 를 연다.

## 5. 데이터 모델

ID 는 접두사 + 소문자 hex 8자리다: `run-1a2b3c4d`, `task-…`, `dsp-…`. `dsp-` ID 는 hc 터미널 이름으로도 쓴다(hc 이름 규칙 `a-z 0-9 - _`, 32자 이하를 지킨다). 메시지와 Delivery 는 정수 자동 증가 ID 다. 시각은 UTC ISO 8601(`2026-11-04T13:05:09Z`).

```
meta(key PK, value)                            schema_version
runs(id PK, objective, owner_space, owner_tab, created_at, updated_at)
bindings(terminal PK, run_id UNIQUE, argv)     소유 관계. 없으면 그 Run 은 소유자 없음. argv 는 묶을 때 hc get 으로 읽은 소유자 터미널의 argv(JSON)
tasks(id PK, run_id, title, spec, status, outcome, created_at, settled_at)
dispatches(id PK, task_id, run_id, attempt, agent, model, effort, cwd,
           terminal, state, outcome, summary, report_path, files_modified,
           launch_argv, agent_args, launcher_pid, launcher_started, created_at, settled_at, closed_at)
                                               agent_args: 호출자가 준 --agent-arg 목록(JSON). 재시도 안내가 그대로 넘긴다
                                               INDEX ON dispatches(task_id, attempt): 최신 시도 조회
                                               UNIQUE INDEX ON dispatches(task_id)
                                                 WHERE state IN ('launching','active'): Task 당 실행 중 Dispatch 하나
messages(id PK, run_id, mailbox, sender, type, subject, body, reply_to,
         dispatch_id, ask_key, created_at, delivery_id)
                                               UNIQUE(dispatch_id, ask_key): question 만 ask_key 를 갖는다
deliveries(id PK, mailbox, created_at, acked_at)
waiters(mailbox, pid, pid_started, terminal, started_at)   check --wait 중인 프로세스
observations(dispatch_id, kind, key, created_at, PK(dispatch_id, kind, key))
```

- `launch_argv` 는 `hc run` 의 `--` 뒤 argv(가드 명령, JSON)다. 생존 판정이 hc 의 `argv` 와 비교한다.
- `launcher_pid`·`launcher_started` 는 실행자의 pid 와 프로세스 시작 시각이다. pid 와 시작 시각이 모두 같은 프로세스가 살아 있어야 "살아 있다"고 본다(pid 재사용 방지). `waiters` 도 같은 규칙이다.
- 소유자 터미널은 `bindings` 로만 정한다.
- 0.2.0 의 열(`persistent`, `terminal_argv`, `start_turn`, `delivery`, `seen_at`)과 인덱스 `dispatch_one_per_terminal` 은 13.3.

### 상태 전이

Task: `open` → `settled`(Dispatch 의 done 으로, outcome 은 succeeded 또는 failed). settled 된 Task 는 다시 열지 않는다. 다시 할 일은 새 Task 로 만든다.

Dispatch:

| 지금 | 다음 | 계기 |
|---|---|---|
| `launching` | `active` | 가드 등록(8장 가드), 또는 실행자가 hc run 성공을 기록(조건부 쓰기). 먼저 한 쪽만 효과 |
| `launching` | `launch_failed` | 실행자가 hc run 실패를 기록, 또는 조정에서 실행자 사망 확인(둘 다 조건부 쓰기) |
| `active` | `settled` | 워커의 `done` |
| `active` | `abandoned` | `worker-abandon` |
| `settled`, `retained`, `abandoned` | `released` | `worker-release` |
| `settled` | `retained` | `worker-retain` |

### launching 조정

`launching` Dispatch 는 다음 때 조정한다: `worker-list`, `worker-show`, 소유자의 `check --wait`(5초마다), `worker-start --task --retry`.

1. 실행자가 살아 있으면 그대로 둔다.
2. 실행자가 죽었으면 `launch_failed` 로 바꾼다.

시간이 지났다는 것만으로 실패로 확정하지 않는다. 상태를 바꾸는 쓰기는 모두 조건부다: `UPDATE ... WHERE id = ? AND state = 'launching'`. 실행자, 가드, 소유자가 동시에 바꾸려 해도 먼저 바꾼 쪽만 효과가 있고, 이미 넘어간 Dispatch 를 되돌리지 않는다.

### 실행 가드(펜스)

워커 터미널의 프로그램은 에이전트가 아니라 `horch launch-guard` 다(8장). 가드는 에이전트를 실행하기 전에 DB 에서 자기 터미널을 등록하고, 등록에 성공해야만 에이전트를 `exec` 한다. 등록과 `launch_failed` 판정은 같은 행에 대한 조건부 쓰기라 정확히 한쪽만 성공한다.

- 가드가 먼저 등록하면 Dispatch 는 `active` 이고, 이후 조정은 아무것도 바꾸지 않는다.
- 조정이 먼저 `launch_failed` 로 바꾸면, 늦게 뜬 터미널의 가드는 등록에 실패해 에이전트를 실행하지 않고 끝난다.

그래서 실행자가 `hc run` 직후 죽고 재시도가 새 Dispatch 를 띄운 뒤 첫 터미널이 늦게 생겨도, 그 터미널에서는 에이전트가 돌지 않는다. 한 Task 에서 동시에 도는 에이전트는 최대 하나다(재시도는 이전 Dispatch 가 `launch_failed`·`abandoned`·`released` 일 때만 허용되므로).

가드가 거부해 끝난 터미널은 `worker-list` 와 소유자의 `check --wait` 가 `hc rm` 으로 지운다(라벨 `horch.dispatch` 가 가리키는 Dispatch 가 `launch_failed` 이고 hc 상태가 `finished` 인 것만).

### 재시도

`worker-start --task <id>` 는 `open` Task 에만 새 Dispatch 를 만든다. 그 Task 의 이전 Dispatch 를 먼저 조정한 뒤 다음일 때만 허용한다.

- 이전 Dispatch 가 없다.
- 이전 Dispatch 가 `abandoned` 또는 `released`.
- 이전 Dispatch 가 `launch_failed` 이고 `--retry` 가 있다.

`launching`, `active`, `settled`, `retained` 면 exit 3. 조정은 실행자 프로세스만 본다(`ps`). `ps` 로 확인할 수 없으면 실행자가 살아 있다고 보고 `launching` 으로 두므로 결과는 exit 3(`task_busy`)이다.

## 6. 호출자와 권한

호출자는 `$HC_TERMINAL_ID` 다. 없으면 터미널 없는 외부 호출자다.

| 명령 | 허용 호출자 |
|---|---|
| `run-create` | hc 터미널이고, `launching`·`active` Dispatch 의 터미널이 아님(중첩 금지) |
| `run-use --id R` | 위와 같고, 아래 "넘겨받기" 조건을 만족 |
| `worker-start`, `worker-list`, `worker-show`, `check`(Run 메일함), `send --to dispatch:`, `reply`, `worker-release`, `worker-retain`, `worker-abandon` | 그 Run 의 소유자 |
| `send --to run:R` | 소유자가 아닌 누구나. 보낸이는 `active` Dispatch 의 터미널이면 `dispatch:<id>`, 아니면 `external:<터미널 또는 none>` |
| `ask`, `done`, `escalate`, `check --dispatch D` | D 의 터미널 자신(아래 "워커 확인") |
| `skill`, `doctor`, `status` | 누구나 |

소유자 명령은 `--run` 을 받지 않는다. 호출자의 binding 이 Run 을 정한다. 권한이 없으면 exit 5 다.

### 넘겨받기(run-use)

`BEGIN IMMEDIATE` 트랜잭션 안에서 R 의 binding 을 다시 읽고 판단한다. 잠금을 쥔 채 하는 소유자 판정(`hc get`)은 3초로 자른다. 시간이 지나면 `unverifiable` 로 보고 `--force` 없이는 거부한다(다른 프로세스의 `busy_timeout` 5초보다 짧게).

| R 의 소유자 | 결과 |
|---|---|
| 없음 | 허용 |
| 호출자 자신 | 허용(아무것도 바꾸지 않음) |
| 다른 터미널, 판정 `exited` 또는 `lost` | 허용 |
| 다른 터미널, 판정 `live` | 거부(exit 3) |
| 다른 터미널, 판정 `unverifiable` | 거부(exit 3). `--force` 가 있으면 허용 |

호출자가 이미 다른 Run 에 묶여 있으면 그 binding 은 지워지고 그 Run 은 소유자 없음이 된다. 넘겨받으면 `owner_space`·`owner_tab` 을 호출자의 `herdr.space`·`herdr.tab` 라벨로 바꾼다(라벨이 없으면 NULL). 이미 떠 있는 워커는 옮기지 않는다. 이후 새 워커만 새 탭에 붙는다.

### 워커 확인

신원 확인과 상태 검사를 나눈다.

신원: D 의 `terminal` 이 기록돼 있고 `$HC_TERMINAL_ID` 와 같으면 통과(D 의 상태와 상관없이). 아니면 exit 5. 가드가 에이전트보다 먼저 터미널을 등록하므로, 에이전트가 부르는 시점에는 항상 기록돼 있다. hc 를 부르지 않는다.

상태(신원 통과 뒤):

- `ask`, `escalate`, `check --dispatch`: D 가 `active` 여야 한다. 아니면 exit 3.
- `done`: 7장 "같은 호출을 다시 하면" 을 따른다.

### 이것은 보안 경계가 아니다

권한 확인은 협조적인 에이전트의 실수(다른 Dispatch ID 를 복사해 쓰기, 워커가 소유자 명령을 부르기)를 막는다. 같은 사용자로 도는 워커는 환경 변수를 바꾸거나 DB 를 직접 고칠 수 있다. 워커끼리, 워커와 코디네이터 사이를 보안상 격리하지 않는다.

## 7. 명령

모든 명령은 전역 옵션 `--home <경로>` 를 받는다. 모든 명령(`skill`, `launch-guard` 제외)은 JSON 한 개를 stdout 에 쓴다. `launch-guard` 는 pane 안에서 돌며 거부 사유를 한 줄 글로 남긴다. 성공은 `{"ok": true, ...}`, 실패는 `{"ok": false, "error": {"code", "message", "hint"}}` 다.

| 명령 | 인자 | 결과 |
|---|---|---|
| `run-create` | `--objective` | `{run}`. 호출자를 소유자로 묶고 `hc get` 의 `herdr.space`·`herdr.tab` 라벨을 소유 탭으로 기록 |
| `run-use` | `--id`, `--force` | `{run, previous_owner}` |
| `worker-start` | `--spec <텍스트>` 또는 `--spec-file <경로>`, `--title`, `--agent claude\|codex`, `--model`, `--effort`, `--cwd`(기본 호출자 cwd), `--agent-arg`(반복), `--task <id>`, `--retry` | `{task, dispatch, terminal, placement}`. `--task` 가 없으면 spec 과 `--title` 이 필수다. `--task` 가 있으면 그 Task 의 spec·제목을 쓰고, spec·`--title` 을 같이 주면 exit 2 |
| `worker-list` | `--state <상태>`(반복, 7개 상태 중 하나. 아니면 exit 2) | Dispatch 행 목록. 각 행에 `verdict`, `attention`, `next`(다음에 실행할 명령). `launch_failed` 의 재시도 안내(`--model`·`--effort`·`--agent-arg` 를 그대로 넘김)는 그 Task 의 최신 시도이고 Task 가 `open` 일 때만 준다 |
| `worker-show` | `--dispatch`, `--lines N`(기본 40, 0 이면 화면 생략) | 행 하나, `hc get` 요약, `hc read --lines N` 화면 |
| `send` | `--to run:<id>\|dispatch:<id>`, `--subject`, `--body` | `{message}`. 종류는 항상 `status` |
| `check` | `--dispatch D`(워커), `--wait`, `--timeout-ms`(기본 900000), `--ack <delivery>` | `{delivery, messages, count, reason}` |
| `reply` | `--id <question>`, `--body` | `{message, duplicate}` |
| `ask` | `--dispatch`, `--question`, `--key`(기본: 본문의 SHA-256 앞 16자), `--timeout-ms`(기본 540000), `--resume <question>` | `{question, answer, reused}`. 시간이 지나면 exit 4 와 `{question}` |
| `launch-guard` | `--dispatch`, `--` 뒤 에이전트 명령 | 워커 터미널 안에서만 쓴다(8장이 붙인다). 등록에 성공하면 에이전트로 `exec` 하고, 실패하면 이유를 터미널에 출력하고 exit 3 |
| `done` | `--dispatch`, `--outcome succeeded\|failed`, `--summary`, `--report-path`, `--files-modified`(반복) | `{dispatch, duplicate}` |
| `escalate` | `--dispatch`, `--body` | `{message}` |
| `worker-release` | `--dispatch` | `{dispatch}` |
| `worker-retain` | `--dispatch` | `{dispatch}` |
| `worker-abandon` | `--dispatch`, `--kill` | `{dispatch}` |
| `status` | 없음 | 호출자 binding, Run 요약, 열린 Delivery, 읽지 않은 메시지 수, 답 없는 질문(`launching`·`active` Dispatch 의 것만) |
| `doctor` | 없음 | 점검 목록(10장) |
| `skill` | 없음 | 사용법 텍스트 |

`send --to dispatch:D` 는 D 가 소유자의 Run 에 속하고 `active` 일 때만 받는다(아니면 exit 3). 0.2.0 의 `send --key` 는 13.9.

0.2.0 의 옵션과 명령(`--keep-open`, `--terminal`, `--tab`, `--hidden`, `--keep-terminal`, `terminal-close`, `terminal-reset`)과 새 오류 code 는 13.4–13.9.

### 같은 호출을 다시 하면

출력을 받기 전에 프로세스가 죽어도 다시 부를 수 있게 한다.

- `done`: D 가 `active` 면 완료를 기록한다. D 에 이미 완료 기록(outcome)이 있으면 현재 상태(`settled`·`retained`·`released`)와 상관없이 outcome·summary·report_path·files_modified 를 비교한다. 같으면 기존 결과와 `duplicate: true`(exit 0), 하나라도 다르면 exit 3. 완료 기록 없이 `active` 가 아니면(`abandoned` 등) exit 3.
- `reply`: 그 질문에 이미 reply 가 있고 본문이 같으면 기존 결과와 `duplicate: true`. 다르면 exit 3.
- `ask`: 질문은 (Dispatch, key) 로 하나다(DB 유일 제약). 같은 key 의 질문이 있으면 새로 만들지 않고 그 질문을 쓴다(`reused: true`). 이미 답이 있으면 바로 답을 돌려준다. 그래서 질문을 쓴 직후든 답을 받은 직후든, 죽은 뒤 같은 명령으로 같은 질문과 답을 받는다. 같은 본문으로 새 답을 원하면 다른 `--key` 를 준다. 같은 key 에 다른 본문을 주면 exit 3.
- `worker-release`: 이미 `released` 면 exit 0.

### exit 코드

| 코드 | 의미 |
|---|---|
| 0 | 성공 |
| 1 | 일반 실패, 또는 hc 로 확인할 수 없음 |
| 2 | 입력 오류 |
| 3 | 상태 충돌(잘못된 전이, 내용이 다른 재호출, 살아 있는 소유자, 가드 등록 실패) |
| 4 | 대기 시간 초과(`ask`). `check --wait` 의 시간 초과는 exit 0, `reason: "timeout"` |
| 5 | 권한 없음 |
| 12 | 의존 프로그램 없음(`hc`, `herdr-app`, 에이전트 실행 파일) |

## 8. 워커 실행

### worker-start 절차

1. 호출자가 소유자인지 확인한다.
2. `BEGIN IMMEDIATE` 트랜잭션에서 Task(새로 만들면 spec 본문까지 저장, 또는 `--task`)와 Dispatch(`launching`, `attempt` 증가, `launcher_pid`·`launcher_started`)를 만들고 커밋한다. `--task` 면 5장 재시도의 허용 검사(Task 가 `open`, 최신 Dispatch 상태)와 `attempt` 결정을 이 트랜잭션 안에서 다시 읽어 한다. 트랜잭션 밖의 앞선 조정 결과는 참고일 뿐이다. 그래도 같은 Task 에 실행 중 Dispatch 가 생기려 하면 부분 유일 인덱스가 막고 exit 3.
3. DB 에서 `spec.md` 와 프리앰블 `preamble.md` 를 만든다(임시 파일에 쓰고 rename).
4. 에이전트 실행 파일이 PATH 에 있는지 본다. 없으면 `launch_failed` 와 exit 12.
5. hc 로 띄운다. 터미널의 프로그램은 가드이고, 가드가 에이전트 명령을 이어 실행한다.

   ```
   hc run --bg --json --no-parent --no-notify --name <dispatch> --cwd <cwd>
     --label herdr.space=<소유 space> --label herdr.tab=<소유 탭>
     --label horch.run=<run> --label horch.dispatch=<dispatch>
     -- <python3 절대 경로> <horch 절대 경로> --home <루트> launch-guard --dispatch <dispatch>
     -- <에이전트 명령>
   ```

   - `--no-parent`: 코디네이터가 끝나도 워커가 살아 있고, hc 가 코디네이터 입력란에 알림을 넣지 않는다.
   - 0.4.0: `--parent <T>` 를 받으면 `--no-parent` 대신 `--parent <T> --outlive-parent` 다(15장). 위 두 까닭은 이제 `--outlive-parent`(부모 프로그램이 끝나거나 `hc kill` 돼도 산다)와 `--no-notify` 가 따로 막는다. 다만 앱에서 부모를 끝내거나 부모의 pane·탭을 닫으면 pane 없는 자식은 `--outlive-parent` 여도 함께 끝난다. 이것은 `--no-parent` 만 막는다(15.1 의 `--hidden`). `--parent` 가 없으면 지금 그대로다.
   - 소유 탭이 NULL 이면(소유자가 Herdr 창 밖 터미널) herdr 라벨 없이 띄우고 `placement: "none"` 과 경고를 돌려준다.
6. 결과를 `receipt.json` 으로 쓴다.
   - 성공: hc 가 돌려준 주소로 `terminal` 을 채우고 `active` 로 바꾼다(조건부 쓰기: `state = 'launching'` 일 때만). 가드가 먼저 등록했으면 상태를 그대로 두고 주소만 대조한다. 다르면 exit 1.
   - 실패: `launch_failed` 로 바꾼다(조건부 쓰기). 그 사이 가드가 등록했으면(`active`) 실패가 아니므로 성공으로 돌려준다. 바꿨으면 exit 1.

2단계 커밋 뒤 실행자가 죽으면 Dispatch 는 `launching` 으로 남고, 다음 조정이 `launch_failed` 로 바꾼다. 그 뒤에 늦게 생긴 터미널은 가드가 막는다.

### 가드

`horch launch-guard --dispatch D -- <에이전트 명령>` 은 워커 터미널 안에서 다음을 한다.

1. `$HC_TERMINAL_ID` 를 읽는다. 없으면 exit 3.
2. `BEGIN IMMEDIATE` 트랜잭션에서 D 를 읽는다.
   - `launching` 이면 `terminal = $HC_TERMINAL_ID`, `active` 로 바꾸고 커밋한다.
   - `active` 이고 `terminal` 이 자신이면 그대로 진행한다(실행자가 먼저 기록한 경우).
   - 그 밖(`launch_failed`, `abandoned`, 다른 터미널의 `active` 등)이면 이유를 출력하고 exit 3.
3. 에이전트 명령의 첫 인자 이름이 `codex` 면 그 바로 뒤에 `-c shell_environment_policy.set.HC_TERMINAL_ID="<자기 주소>"` 를 넣는다. Codex 설정이 `shell_environment_policy.inherit = "core"` 면 Codex 가 실행하는 셸에서 `$HC_TERMINAL_ID` 가 사라지기 때문이다(사전 검증 S2 에서 확인).
4. `os.execvp` 로 에이전트 명령을 실행한다. 가드 프로세스가 에이전트로 바뀌므로 터미널의 실행 프로그램은 에이전트다.

가드는 Codex 샌드박스 밖(Codex 가 시작되기 전)에서 돈다.

### 에이전트 명령

- Claude: `claude [--model M] [--effort E] [추가 인자...] -- "<프리앰블>"`
  - 처음 보는 폴더에서는 폴더 신뢰 확인 창에서 멈춘다(사전 검증 S1). 워커 `--cwd` 는 사용자가 이미 신뢰한 폴더를 쓴다.
- Codex: `codex --no-daemon -s workspace-write -a never --add-dir <저장 루트> [-m M] [-c model_reasoning_effort=E] -c check_for_update_on_startup=false -c 'projects={"<cwd 실경로>"={trust_level="trusted"}}' [추가 인자...] -- "<프리앰블>"`
  - 시작 창 막기(6단계 실환경, codex-cli 0.167.0): 처음 보는 폴더면 폴더 신뢰 창("Trust and continue"), 새 판이 있으면 업데이트 창이 뜨고 그동안 상태 보고가 없다. 숨은 워커는 사람이 볼 수도 없다. 그래서 `--cwd` 의 실경로를 이 실행에서만 신뢰하고(`~/.codex/config.toml` 은 쓰지 않는다, 실험에서 그대로였다) 시작 업데이트 확인을 끈다. Codex 는 신뢰를 실경로로 찾는다(macOS 에서 `/tmp` 아래 경로로 주면 그 실경로(`/private` 로 시작)의 신뢰 창이 떴다). `projects."<경로>".trust_level` 점 키는 경로에 점이 있으면 듣지 않아 인라인 표 한 값으로 넘긴다(경로는 JSON 문자열 꼴. TOML 기본 문자열로도 읽힌다). 저장소 하위 폴더를 `--cwd` 로 줘도 그 경로 신뢰로 창이 없었다. 추가 인자가 뒤에 오므로 호출자가 같은 키를 덮을 수 있다.
  - `--no-daemon`: 없으면 Codex 의 명령이 hc 밖에서 돌아 `$HC_TERMINAL_ID` 가 없다.
  - `--add-dir`: Codex 샌드박스에서 저장소 DB 에 쓰게 한다.
  - `-a never`: 사람 없이 돈다. 샌드박스 밖 명령은 묻지 않고 실패한다.
  - 호출자가 추가 인자로 샌드박스·승인을 직접 고르면(`-s`·`--sandbox`, `-a`·`--ask-for-approval`, `--dangerously-bypass-approvals-and-sandbox` 등) 겹치는 기본 `-s workspace-write`·`-a never` 는 넣지 않는다. 겹치면 Codex 가 시작 전에 exit 2 로 끝난다(브랜치 리뷰에서 재현).
  - 플러그인 hook 이 새로 생기거나 바뀌면 Codex 는 시작할 때 "Hooks need review" 확인 창에서 멈춘다(사전 검증 S2). 설정 키 `bypass_hook_trust` 는 대화형 Codex 에 듣지 않고, 실행 옵션 `--dangerously-bypass-hook-trust` 만 듣는다. 그러나 이 옵션은 검토하지 않은 hook 을 실행해, 깨진 hook 이 워커의 셸 명령을 모두 막을 수 있다(실환경 확인: Node 버전이 맞지 않는 context-mode hook). 그래서 워커에는 `--disable=hooks`(hook 을 끄고 확인 창도 없앤다, codex-cli 0.166 에서 확인)를 권한다. horch 는 이 옵션도 스스로 넣지 않는다. 호출자가 `--agent-arg=--disable=hooks` 로 넘긴다(herdr-team 은 사용자 설정에 따라 넘긴다). 처음 보는 폴더의 Codex 폴더 신뢰 창은 이 옵션으로도 사라지지 않는다. 위 시작 창 막기의 `projects` 값이 그 창을 없앤다.
- 프리앰블 앞의 `--` 는 추가 인자가 값을 여러 개 받는 옵션(Claude `--add-dir <dirs...>` 등)으로 끝나도 프리앰블을 그 값으로 먹지 않게 한다(두 CLI 모두 `--` 뒤 프롬프트를 받는다, 2026-11-05 확인).
- 추가 인자(`--agent-arg`)는 호출자가 정한다. horch 는 권한 우회 플래그를 스스로 넣지 않는다.
- 모델·effort 를 생략하면 에이전트 기본값이다. 값은 검사하지 않고 그대로 넘긴다.

### 프리앰블

다음을 담는다(한국어, 명령은 `horch` 절대 경로와 `--home` 을 포함한 그대로).

1. 너는 herdr-orch 워커다. Task ID, Dispatch ID.
2. 먼저 spec 파일(`spec.md` 절대 경로)을 읽고 그 일만 한다.
3. 막히면 `horch ask --dispatch D --question "..."`. 답이 올 때까지 기다린다. exit 4 면 `--resume <질문 id>` 로 다시 기다린다. 출력을 못 받았으면 같은 명령을 다시 실행한다. 같은 질문을 새로 하려면 다른 `--key` 를 준다. ask·check·done 은 재호출 안전이고, escalate 는 다시 보내면 같은 보고가 한 번 더 간다. 대화형 질문 도구(AskUserQuestion 등)는 쓰지 않는다. 사람이 보지 않는다.
4. 새 파일을 시작하기 전, 테스트를 돌린 뒤, done 직전에 `horch check --dispatch D` 로 코디네이터 메시지를 읽는다. 처리한 뒤 `--ack <delivery>` 하고 `count` 가 0 이 될 때까지 반복한다.
5. 범위 밖 문제나 진행할 수 없으면 `horch escalate --dispatch D --body "..."`.
6. 끝나면 `horch done --dispatch D --outcome succeeded|failed --summary "<세 문장>"`, 해당하면 `--report-path`, `--files-modified`. 실패를 문장으로만 쓰지 않는다. 출력을 못 받았으면 같은 인자로 다시 실행한다. done 뒤에는 새 일을 시작하지 않고 대기한다.
7. horch 는 셸 명령으로 실행한다(다른 도구, 예: Codex 의 node_repl 에는 `$HC_TERMINAL_ID` 가 없어 거부된다, 실환경 확인). horch 로 다른 워커를 띄우지 않는다.

## 9. 메시지 흐름

### 쓰기

- `send`, `reply`, `escalate`, `ask`, `done` 은 메시지를 한 트랜잭션에서 쓴다. `done` 은 같은 트랜잭션에서 Dispatch 와 Task 를 `settled` 로 바꾼다.
- 종류: `status`, `question`(ask), `reply`, `worker_done`, `escalation`, `observed`.
- `reply` 는 질문을 보낸 Dispatch 의 메일함으로 가지만, `check` 에는 나오지 않는다. reply 는 `ask`(또는 `ask --resume`)로만 받는다. 그래서 Delivery 재전달과 ask 의 답 수신이 부딪히지 않는다.

### check 와 Delivery

1. 메일함에 ack 안 된 Delivery 가 있으면 그 묶음을 그대로 돌려준다(재전달).
2. 없으면 아직 묶이지 않은 메시지(reply 제외)를 오래된 순으로 최대 50건 묶어 새 Delivery 를 만든다. `count` 는 묶음의 메시지 수다.
3. `--ack <id>` 는 그 Delivery 를 ack 한 뒤 1–2단계로 다음 묶음을 돌려준다. Run 메일함이면 ack·묶기 트랜잭션 안에서 호출자가 아직 소유자인지 다시 본다(아니면 exit 5). 같은 Delivery 를 두 번 ack 해도 오류가 아니다.
4. `--wait` 는 묶을 메시지가 생길 때까지 1초 간격으로 DB 를 본다. 종류로 거르지 않는다. 깨어나면 1–2단계를 한다. 시간이 지나면 `{delivery: null, messages: [], count: 0, reason: "timeout"}`. 폴링 중 DB 잠금(locked·busy)은 그 회차만 건너뛰고 다음 회차에 다시 본다.
5. `--wait` 동안 `waiters` 에 자기 pid 와 시작 시각을 등록하고 끝날 때 지운다.
6. 한 메일함을 여러 프로세스가 동시에 check 해도 된다. 같은 묶음을 함께 받고, ack 는 한 번만 효과가 있다.

### ask

1. 7장 규칙대로 (Dispatch, key) 의 질문을 찾거나 만든다. 새 질문이면 `question` 메시지를 Run 메일함에 쓰고 소유자를 깨운다.
2. 그 질문을 `reply_to` 로 가진 `reply` 를 1초 간격으로 찾는다. 찾으면 답을 돌려준다. reply 는 지우거나 표시하지 않으므로 같은 질문으로 몇 번이든 다시 받을 수 있다.
3. 기다리는 동안 60초마다 소유자를 아래 "깨우기" 규칙대로 다시 깨운다(살아 있는 waiter 가 있거나 `working`·`blocked` 이면 건너뛴다).
4. 시간이 지나면 exit 4 와 질문 ID. `--resume <id>` 는 1단계 없이 2–3단계만 한다.
5. 기다리는 동안 Dispatch 가 `active` 가 아니게 되면(abandon) exit 3 으로 끝난다.

### 깨우기

메시지를 쓴 뒤 받는 터미널(Run 메일함이면 소유자, Dispatch 메일함이면 워커)을 깨운다. 단 `reply` 는 깨우지 않는다. reply 는 `check` 에 나오지 않고, 받는 워커는 `ask` 로 1초마다 확인하고 있다.

- 그 메일함에 살아 있는 waiter 가 있으면 깨우지 않는다. 기다리던 프로세스가 직접 받는다.
- 받는 터미널의 `hc get` 상태가 `idle` 이면 `hc send --if idle <터미널> "[horch] 새 메시지가 있다. 확인: <horch> --home <루트> check[ --dispatch D]"`.
- 상태가 `done` 이면 같은 글을 `--if` 없이 보낸다. 상태 보고가 없으면(null, 시작 확인 창) 보내지 않는다(`skipped_unknown`). `done` 은 "턴을 마쳤지만 사람이 아직 안 봄" 이고, 아무도 보지 않는 pane 의 Claude 는 계속 `done` 에 머문다(사전 검증 S3). `hc send --if` 는 `idle`·`working` 만 받는다. 조회와 전송 사이에 `working` 이 되면 글은 입력 대기열에 들어가 그 턴 뒤에 처리되고, `blocked` 가 되면 hc 가 보내지 않는다.
- 상태가 `error` 면 같은 글을 `--if` 없이 보낸다(hc 는 error 인 에이전트에 입력을 보내 이어가게 한다). `working`·`blocked` 이면 보내지 않는다.
- 깨우기 실패는 무시하고 결과의 `wake` 필드에 적는다. 메시지는 저장소에 남는다.
- 환경 변수 `CODEX_SANDBOX` 가 있으면(Codex 샌드박스 안) hc 를 부르지 않고 `wake: "skipped_sandbox"` 로 적는다. 사전 검증 S2 에서 Codex `workspace-write` 샌드박스가 hc 소켓을 막는 것을 확인했다(`cannot start core: Operation not permitted`).

깨우기는 보조 수단이다. 메시지를 놓치지 않는 것은 다음 계약이 보장한다.

- **코디네이터**: `launching`·`active` Dispatch 나 답 없는 질문이 있는 동안 `check --wait` 를 항상 백그라운드로 띄워 둔다. 메시지를 처리한 뒤, 그리고 턴을 끝내기 전에 다시 띄운다. `horch skill` 이 이 계약을 적는다.
- **워커**: 프리앰블 4항의 체크포인트.
- **질문**: ask 가 기다리는 동안 3항대로 다시 깨운다.

### observed

소유자의 `check --wait` 는 기다리는 동안 5초마다 그 Run 의 `launching`(조정)·`active` Dispatch 를 판정한다(10장: `hc ls` 에는 `argv` 가 없으므로 대상마다 `hc get`). 판정은 메일함 확인을 막지 않는다: 한 번의 틱은 폴링 간격 안에서만 새 판정을 시작하고, 판정 하나의 `hc get` 은 최대 5초(남은 대기 시간보다 짧게)로 자른다. 다 돌지 못한 Dispatch 는 다음 틱과 다음 `check --wait` 호출에서 이어서 본다(진행 위치는 `meta` 에 Run 마다 둔다). 거부 터미널 정리도 확인 전 후보와 지울 목록을 틱 사이에 이어 가고, 두 목록이 모두 비었을 때만 `hc ls --all` 을 다시 한다. 판정 중 예상 밖 오류가 나도 대기는 계속한다(stderr 에 한 줄, stdout 은 JSON 하나 그대로). 판정이 메시지를 쓰기 직전에는 그 Dispatch 가 아직 같은 터미널의 `active` 인지 트랜잭션 안에서 다시 본다. `turn` 이 없으면 blocked·error 를 기록하지 않는다. `launch_failed` Dispatch 가 있으면 `hc ls --all --json` 으로 가드가 거부한 터미널을 찾아 정리한다(5장). 다음 경우 `observations` 에 넣고, 새로 넣었을 때만 `observed` 메시지를 Run 메일함에 쓴다.

| kind | 조건 | key |
|---|---|---|
| `blocked` | hc 상태 `blocked` | 그 turn 번호 |
| `error` | hc 상태 `error` | 그 turn 번호 |
| `idle` | 판정 `live`, hc 상태 `idle` 또는 `done`(아무도 보지 않는 Claude 는 `done` 에 머문다), turn 1 이상. done 없이 턴을 마친 워커 | 그 turn 번호 |
| `exited` | 판정 `exited` | `exited` |
| `lost` | 판정 `lost` | `lost` |

같은 사건은 key 로 한 번만 보낸다.

## 10. 생존 판정과 복구

원칙: 멈추기, 버리기, 재시도, 넘겨받기는 끝났다는 확실한 증거가 있을 때만 한다. 확인할 수 없으면 "모름" 으로 두고 바꾸지 않는다.

`hc ls --all --json`(종료된 터미널 포함)과 `hc get` 으로 판정한다.

| 판정 | 조건 |
|---|---|
| `lost` | hc 상태 `live` 이고, `reason` 이 `stopped_by_restart` 이거나 hc 의 `argv` 가 기록한 argv(Dispatch 는 `launch_argv`, 소유자는 `bindings.argv`)와 다름 |
| `live` | hc 상태 `live` 이고 `lost` 가 아님. 아직 상태를 보고하지 않은(부팅 중) 에이전트도 `live` 다 |
| `exited` | hc 상태 `finished` |
| `unverifiable` | hc 호출 실패, 또는 목록에 주소가 없음(이미 `hc rm` 됐거나 다른 코어) |

상태 보고가 없다는 것만으로는 `lost` 가 아니다. 사전 검증 S4(2026-11-04, 격리 `HC_SESSION` 코어, hc 0.1.18)에서 확인한 사실: `--keep` 터미널은 코어 재시작 직후 `reason: "stopped_by_restart"`, `pid: null` 이고, 유예 시간 뒤 복구 셸이 뜨면 `reason` 은 null 로 돌아가고 `argv` 가 셸(`["/bin/zsh","-l"]`)로 바뀐다. 주소와 이름, 라벨은 그대로다. `hc ls` 에는 `argv` 가 없으므로 판정은 대상마다 `hc get` 을 부른다.

### 상황별 처리

- **워커가 done 없이 끝남**: `observed exited` 를 받은 코디네이터가 `worker-abandon` 한 뒤 `worker-start --task <id>` 로 다시 띄운다.
- **워커가 done 없이 멈춤**: 턴을 마치고 `idle`·`done` 인데 `done` 명령을 부르지 않은 워커는 턴마다 한 번 `observed idle` 을 보낸다(실환경 확인에서 3분 넘게 신호 없이 멈춘 일이 있었다). `worker-list` 는 `attention: "idle"`, `next: worker-show --lines 40`. 코디네이터가 화면을 보고 `send --to dispatch:D` 로 이어가게 하거나(9장 깨우기가 입력을 보낸다) 사용자에게 알린다.
- **워커가 blocked**: `observed blocked` 만 보낸다. horch 는 키를 누르지 않는다. 코디네이터가 사람에게 넘길지 정한다.
- **워커가 시작 확인 창에서 멈춤**: Claude 폴더 신뢰, Codex hook 검토 창 동안에는 에이전트가 상태를 보고하지 않는다(`status` 가 null, 사전 검증 S1·S2). 그래서 `blocked` 로 보이지 않는다. `worker-list` 는 판정이 `live` 인데 상태 보고가 없는 `active` 워커를 `attention: "no_status"`, `next: worker-show --lines 40` 으로 보인다. 띄운 직후 첫 보고 전에도 잠깐 그렇다. horch 는 키를 누르지 않는다. 1분 넘게 이어지면 코디네이터가 화면을 보고 사용자에게 알린다.
- **워커가 error**: `observed error`. 코디네이터가 `worker-show --lines 80` 으로 화면을 읽고, 이어갈 수 있으면 `send --to dispatch:D` 로 지시한다(9장 깨우기가 error 인 워커에 입력을 보낸다). 이어갈 수 없으면 `worker-abandon --kill` 뒤 `worker-start --task` 로 다시 띄운다.
- **`worker-abandon`**: 판정이 `exited`·`lost` 면 `abandoned`. `live` 면 `--kill` 이 있어야 하고 `hc kill` 뒤 `abandoned`. `unverifiable` 은 거부(exit 1). 복구 셸(`lost`)은 남아 있으므로 `worker-release` 로 정리한다.
- **`worker-release`**: `settled`·`retained`·`abandoned` 를 받는다(고정 Dispatch 는 터미널을 남긴다, 13.5). 다음 순서로 하고, 각 단계는 이미 된 상태를 성공으로 본다.
  0. `hc get` 의 라벨 `horch.dispatch` 가 이 Dispatch 가 아니면(주소가 다른 터미널을 가리킴) 아무것도 지우지 않고 exit 1(`terminal_mismatch`).
  1. 판정이 `live`·`lost` 면 `hc kill`. 이미 `finished` 거나 hc 가 not_found 를 주면 넘어간다.
  2. `hc rm`. not_found 면 넘어간다. kind `live`(kill 직후 아직 살아 있음)일 때만 잠깐 다시 시도한다.
  3. `released`, `closed_at` 기록.
  hc 호출이 다른 이유로 실패하면 상태를 바꾸지 않고 exit 1. 다시 실행하면 이어서 한다. 프로그램이 끝나면 Herdr 가 pane 을 닫는다.
- **코디네이터가 죽음**: 새 터미널에서 `run-use --id R`(6장 넘겨받기). ack 안 된 Delivery 는 새 소유자에게 다시 간다.
- **동시 쓰기**: WAL, `busy_timeout` 5초, 쓰기는 `BEGIN IMMEDIATE`. 저장소를 열 때는 스키마를 만들거나 올려야 할 때만 쓰기 잠금을 잡는다. 잠금을 쥔 채 외부 프로그램을 부르는 곳(run-use 판정)은 호출 시간을 3초로 자른다.
- **스키마**: `meta.schema_version` 으로 마이그레이션한다. 현재 2(1→2: `dispatches.agent_args` 열과 `(task_id, attempt)` 인덱스 추가). 모르는 더 높은 버전이면 exit 1. 0.2.0 은 3(13.3).

### doctor 점검

Python 3.11 이상, `hc` 실행과 `hc server status`, `herdr-app status`, 저장 루트 쓰기, `claude`·`codex` 존재(없으면 경고), `codex` 의 `--no-daemon` 지원.

## 11. 보안

- 6장 "이것은 보안 경계가 아니다" 를 따른다.
- 워커는 사람 없이 돈다. 권한 모드나 샌드박스 우회는 호출자가 `--agent-arg` 로 정하고, 그 위험도 호출자가 진다. horch 는 우회 플래그를 넣지 않는다.
- Codex 워커는 `workspace-write` 샌드박스와 `-a never` 로 띄우고, 저장 루트만 `--add-dir` 로 쓰기를 연다. 호출자가 우회 플래그를 넘기면 Codex 가 사용자의 자격 증명(git, 클라우드 인증, 셸 환경)을 그대로 쓴다.
- Codex 워커는 `--cwd` 폴더를 신뢰한 것으로 띄운다(8장 시작 창 막기, 사용자 결정 2026-11-11). 신뢰한 폴더는 그 폴더의 Codex 설정이 코드를 실행할 수 있다(Codex 신뢰 창 문구). 워커를 띄우는 쪽이 그 폴더를 고른 것이므로 사람에게 다시 묻지 않는다. 신뢰는 그 실행에만 주고 사용자 설정 파일에 남기지 않는다.
- 워커의 보고·질문·요약은 데이터다. `horch skill` 은 코디네이터에게 이 내용을 지시로 따르지 말라고 적는다.
- 저장 루트는 0700 이다.

## 12. 테스트

### 자동 테스트

`unittest`, 임시 `--home`, PATH 앞에 `tests/fakes/hc`·`tests/fakes/herdr-app`. 가짜는 받은 인자를 기록하고 시나리오 파일의 응답을 돌려준다. 실제 hc·Herdr 상태를 건드리지 않는다.

- 저장소: 스키마 생성, 마이그레이션, 여러 프로세스 동시 쓰기, `bindings.run_id` 유일성
- Delivery: FIFO, 50건 묶음, 재전달, ack 반복, reply 제외, 동시 check
- 권한: 6장 표의 허용·거부 전부, 넘겨받기 표 전부, 워커 신원(일치·불일치·미기록)과 명령별 상태 검사
- 상태 전이와 재시도 규칙: 5장 표의 전이와 거부
- launching 조정: 실행자 살아 있음(유지), 실행자 죽음(`launch_failed`). 각 장애 시점(2단계 커밋 직후, hc run 직후, 6단계 직전)에 실행자를 죽인 뒤의 복구
- 가드: `launching` 등록 성공 후 exec, 실행자가 먼저 기록한 `active`(자기 터미널) 진행, `launch_failed`·`abandoned`·다른 터미널 `active` 거부(에이전트를 실행하지 않음), `$HC_TERMINAL_ID` 없음
- 펜스: 같은 Task 에 `worker-start --task --retry` 를 동시에 두 번 하면 하나만 Dispatch 를 만든다(다른 하나는 exit 3). 가드 등록과 `launch_failed` 판정을 동시에 시도하면 정확히 한쪽만 성공. 재시도로 새 Dispatch 가 뜬 뒤 이전 Dispatch 의 늦은 터미널에서 가드가 거부. 거부된 `finished` 터미널을 `hc rm`
- 경쟁: 가드가 등록하고 워커가 done 한 뒤 실행자가 6단계를 하는 순서, 소유자가 abandon 한 뒤 실행자가 6단계를 하는 순서, hc run 이 실패를 돌려줬는데 가드가 이미 등록한 경우
- 재호출: done 같은 내용·다른 내용(settled·retained·released 각각), reply 같은 내용·다른 내용, ask 같은 key(질문 직후·답 받은 뒤)·다른 key·같은 key 다른 본문, release 반복
- ask: 답, 시간 초과(exit 4), `--resume`, 다시 깨우기, abandon 중 종료
- 깨우기: waiter 있음/없음/죽음, `idle`/`done`/`error`/`working`/`blocked`
- worker-list attention: 상태 보고 없는 `live` `active` 워커는 `no_status`, 턴을 마친 `idle`·`done` 워커는 `idle`
- observed: 다섯 kind(blocked·error·idle·exited·lost)와 중복 제거, `hc ls --all` 사용
- worker-show: `--lines` 로 `hc read` 화면 포함
- 생존 판정 네 가지
- worker-start: 에이전트 명령 조립(Claude·Codex, `--home` 포함 프리앰블), 라벨, 배치 없음, 실행 실패

### 사전 검증(구현 계획 첫 태스크)

실제 Herdr 의 버리는 space 에서 한다. 사용자의 herdr-core 는 재시작하지 않는다.

| ID | 확인할 것 | 실패하면 |
|---|---|---|
| S1 | `herdr.space`·`herdr.tab` 라벨과 `--no-parent` 로 띄운 hc 터미널이 그 탭에 pane 으로 붙는가. 가드가 `exec` 한 Claude 가 Herdr 에서 에이전트로 보이고 상태를 보고하는가 | 구현을 멈추고 배치·실행 방식을 다시 설계한다(이 문서를 고친 뒤 진행) |
| S2 | 가드가 `exec` 한 `codex --no-daemon` 워커가 hc 에 상태를 보고하는가. 가드가 넣은 `-c shell_environment_policy.set.HC_TERMINAL_ID=...` 로 Codex 셸에 `$HC_TERMINAL_ID` 가 보이는가. `CODEX_SANDBOX` 가 설정되는가 | 상태 보고가 없으면 Codex 워커의 `observed blocked`·`error` 를 포기한다. `$HC_TERMINAL_ID` 주입이 안 되면 Codex 워커 지원을 빼고 이 문서를 고친다. `CODEX_SANDBOX` 가 없으면 샌드박스 감지를 빼고 hc 호출 실패로 처리한다 |
| S3 | `idle` 인 Claude·Codex 에 `hc send --if idle` 이 사용자 메시지로 들어가는가 | 끝남(2026-11-05). Claude 는 `done` 에 머물러 실패했고, 9장 깨우기가 `done` 이면 `--if` 없이 보내도록 바꿨다(아래 결과) |
| S4 | 끝남(2026-11-04). 10장 생존 판정표에 결과를 반영했다 | — |

S2 중 이미 확인한 것(2026-11-04, `codex exec -s workspace-write --add-dir`, codex-cli 0.166.0): `--add-dir` 경로의 SQLite 쓰기는 된다. 샌드박스 안에서 hc 소켓은 막힌다. 사용자 Codex 설정(`inherit = "core"`)에서는 `$HC_TERMINAL_ID` 가 셸에 전달되지 않는다.

#### 사전 검증 결과 (2026-11-05, hc 0.1.18, codex-cli 0.166.0)

- S1: 통과. 라벨을 붙인 터미널이 그 탭의 별도 pane 으로 붙었다(`herdr-app ls`. 창이 새 프레임을 그리지 않아 스크린샷으로는 확인하지 못했다). 가드식 exec 뒤 `status.app` = `claude-code`, `argv` 는 띄운 argv 그대로다.
  - 처음 보는 폴더에서 Claude 는 폴더 신뢰 확인 창에서 멈춘다. 이때 `status` 는 `blocked` 가 아니라 null 이다. 기본 선택이 "No, exit" 라 Enter 만 누르면 Claude 가 끝난다.
- S2: 통과. Codex 셸의 `HC_TERMINAL_ID` 가 그 터미널 주소와 같다. `--add-dir` DB 쓰기가 된다. `CODEX_SANDBOX` = `seatbelt`. Codex 는 `status.app` = `codex` 로 상태를 보고한다.
  - 플러그인 hook 이 바뀐 뒤 새 Codex 는 "Hooks need review" 확인 창에서 멈춘다. 이때도 상태 보고가 없다. `--dangerously-bypass-hook-trust` 로 띄우면 확인 창 없이 `idle` 을 보고한다(설정 키 `-c bypass_hook_trust=true` 는 듣지 않았다).
- S3: Claude 실패, Codex 통과. 턴을 마친 Claude 는 아무도 pane 을 보지 않으면 core 상태가 `done` 에 머물러 `hc send --if idle` 이 `status_mismatch` 로 거부된다. `--if` 없는 `hc send` 는 들어가고 Claude 가 대답한다(입력은 `<hc from="<보낸 터미널>">…</hc>` 로 감싸져 보인다). Codex 는 `done` 뒤 스스로 `idle` 을 보고해 `--if idle` 이 들어갔다.
  - 대응(사용자 결정, 2026-11-05): 9장 깨우기가 `done` 이면 `--if` 없이 보낸다. 시작 확인 창은 10장 `no_status` 로 드러낸다.

### 실환경 확인

버리는 space 에서 코디네이터(Claude) 하나와 워커 둘(Claude 개발자, Codex 리뷰어)로 작은 태스크를 끝까지 돌린다. pane 이 생기고, ask/reply 가 오가고, done 이 Run 메일함에 오고, release 로 pane 이 닫히는지 본다.

#### 실환경 확인 결과 (2026-11-05)

hc 0.1.18, Claude Code 2.1.318(코디네이터 Opus, 워커 haiku), codex-cli 0.166.0. 버리는 git 저장소와 `horch-e2e` space, 별도 `--home` 저장 루트에서 돌렸다. 코디네이터 시작부터 마지막 release 까지 약 7분 걸렸다.

- pane 배치: 통과. `worker-start` 결과는 `placement: "pane"` 이다. `herdr-app ls` 에서 워커 터미널 셋(Claude 1, Codex 2)이 모두 코디네이터와 같은 탭의 pane 으로 붙었다. 라벨은 `herdr.space`·`herdr.tab`·`horch.run`·`horch.dispatch` 다. `herdr-app shot` 은 창이 새 프레임을 그리지 않아 다른 space 의 옛 프레임이 찍혔다. 그래서 스크린샷으로는 확인하지 못했다(사전 검증 S1 과 같다).
- ask/reply: 통과(Claude 워커). `question` 을 쓰고 5초 뒤 코디네이터가 `reply` 했다. 워커의 `ask` 는 약 7초 만에 답("hello 로 해")을 받았다. Codex 워커는 재시도 때 `hello.py` 가 이미 있어 ask 를 거치지 않았다. 그래서 Codex 쪽 ask 는 확인하지 못했다.
- worker_done(Claude·Codex): Claude 는 통과했다. 시작 36초 뒤 `succeeded` 가 왔고, 코디네이터가 커밋과 출력을 직접 확인했다. Codex 는 1차 시도가 환경 문제(아래 2)로 done 을 보내지 못했다. 같은 Task 를 다시 띄운 2차 시도(`attempt` 2)에서 `succeeded` 가 Run 메일함에 왔다(`docs/review.md` 한 줄).
- release 로 pane 닫힘: 통과. `worker-release` 뒤 워커 터미널이 `hc ls --all` 에서 사라지고, 탭에는 코디네이터와 space 기본 셸만 남았다. 마지막 `worker-list` 에서 Dispatch 셋이 모두 `released` 다(abandon 한 1차 시도 포함, 아래 4). `status` 는 `unread` 0, 답 없는 질문 없음이다.
- 발견한 문제와 처리:
  1. 시작 확인 창(운영자가 키로 넘김, 세 번). 코디네이터의 Claude 폴더 신뢰 창, Codex 폴더 신뢰 창(`--dangerously-bypass-hook-trust` 로는 건너뛰지 못한다. 신뢰 결정은 Codex 사용자 설정에 저장된다), Codex "Hooks need review" 창("Continue without trusting")이다. 확인 창 동안 `worker-show` 는 `attention: "no_status"` 를 보였고, 코디네이터는 스킬대로 키를 누르지 않고 사람에게 알렸다. 같은 폴더의 Claude 워커는 코디네이터가 이미 신뢰한 폴더라 창이 뜨지 않았다.
  2. 환경 문제(horch 결함 아님). 사용자 Codex 의 context-mode 플러그인 2.1.0 hook 은 Node 24.15 이상이 필요한데 설치된 Node 는 22 다. 이 hook 은 `NODE_TOO_OLD` 로 실패하면서 셸 명령을 모두 막았다. `--dangerously-bypass-hook-trust` 가 바뀐(미신뢰) hook 을 돌게 한 것이다. Codex 는 셸 대신 node_repl MCP 도구로 horch 를 불렀다. 그 프로세스에는 `HC_TERMINAL_ID` 가 없어 `check`·`ask`·`escalate`·`done` 이 모두 `not_this_worker` 로 거부됐다. 처리: 운영자가 코디네이터에게 알렸고, 코디네이터가 `worker-abandon --kill` 뒤 같은 Task 를 bypass 인자 없이 다시 띄웠다. hook 검토 창에서 "Continue without trusting" 을 고르자 셸이 동작했고 통과했다.
  3. 남은 공백(미처리). 워커가 done 없이 턴을 마치고 `idle` 이 되면 horch 는 아무 신호도 내지 않는다. `observed` 는 blocked·error·exited·lost 만 보내고, `worker-show` 의 `attention` 은 null 이었다. 코디네이터는 운영자가 알릴 때까지 3분 넘게 기다렸다.
  4. 코디네이터가 abandon 한 Dispatch 를 release 하지 않고 끝냈다. `worker-list` 의 `next` 는 `worker-release` 였다. 스킬 6항은 abandon 을 "정리"라 부르고, 8항은 "`settled`·`abandoned` Dispatch 를 모두 정리했을 때 끝낸다" 고 쓴다. 그래서 abandon 만으로 정리가 끝났다고 읽을 수 있다. 운영자가 요청하자 release 가 끝난 터미널을 `hc rm` 했다.
  5. 하네스의 GateGuard hook 이 코디네이터와 Claude 워커의 첫 Bash·Write 를 막았다. 둘 다 요구한 사실을 적고 다시 실행해 이어갔다.
  6. 사소한 것. `doctor` 의 `herdr_app` detail 이 `{` 다(`herdr-app status` 의 JSON 첫 줄만 담는다). `HC_TERMINAL_ID` 가 없을 때 `not_this_worker` 메시지는 "이 터미널(없음)" 이고 hint 가 비어 있다.
- 후속 조치(2026-11-05): 2 는 Codex 워커에 `--dangerously-bypass-hook-trust` 대신 `--disable=hooks` 를 권하도록 8장과 스킬을 바꿨다. 3 은 사용자 결정으로 `observed idle` 을 더했다(9장·10장). 4 는 스킬에서 abandon 을 "정리"라 부르지 않고 `abandoned` 도 `worker-release` 해야 끝난다고 적었다. 6 은 doctor detail 과 not_this_worker 힌트를 고쳤다.
- `observed idle` 실환경 확인(2026-11-05): 소유자 터미널에서 haiku 워커 하나에 done 없이 멈추라는 spec 을 줬다. 워커는 첫 턴 뒤 hc 상태 `done`, `turn` 1(정수)을 보고했다. 소유자의 `check --wait` 가 첫 판정에서 바로 `observed` `{"kind": "idle", "key": "1", "status": "done"}` 을 받았고, `worker-list` 는 `attention: "idle"`, `next: worker-show --lines 40` 을 보였다. `worker-abandon --kill` 과 `worker-release` 로 정리했다.

### Codex 교차 검증

`CLAUDE.md` 규칙대로 설계·계획·태스크 커밋·브랜치 전체를 Codex 가 검토한다.

## 13. 0.2.0: 고정 터미널 (2026-11-10)

herdr-team 0.4.0 의 고정 에이전트(같은 세션이 여러 태스크를 이어 맡는다)를 위해 더한다. 0.1.x 동작은 그대로다: 고정 터미널을 쓰지 않는 Dispatch 는 지금처럼 새 터미널에서 돌고, `worker-release` 가 그 터미널을 끄고 지운다. 이 장은 herdr-team 6단계 설계(`2026-11-05-herdr-team-design.md` 5.9)와 같은 주기에 구현한다.

근거는 실제 세션 실험 X1–X6·X3b(2026-11-10, hc 0.1.19, Claude Code 2.1.322, codex-cli 0.167.0)다. 이 장에서 "X1" 처럼 적은 것은 그 실험이다.

### 13.1 실험이 정한 사실

| 사실 | 실험 | 이 장의 규칙 |
|---|---|---|
| done 으로 끝난 Claude 세션에 여러 줄 프리앰블을 `hc send` 로 넣으면 제출되고 앞 맥락을 기억한다 | X1 | 같은 터미널에 다시 넣을 수 있다(13.4) |
| 같은 Dispatch 로 `done` 을 다시 부르면 `done_conflict`(exit 3)다 | X1 | 다시 넣을 때마다 새 Dispatch 를 만든다 |
| 아무도 보지 않는 Claude·Codex 는 턴이 끝나면 입력이 올 때까지 `done` 에 머문다. `--if idle` 은 `status_mismatch` 로 거부된다 | X1, X3b | 상태가 `done` 이면 조건 없이 보낸다 |
| 셸 터미널(상태를 보고하지 않는다)이나 `HC_TERMINAL_ID` 가 없는 호출에서 보낸 글은 `<hc from=…>` 로 감싸지 않는다. 상태를 보고하는 에이전트 터미널에서 보낼 때만 감싼다 | X1 | 다시 넣는 글은 `HC_TERMINAL_ID` 를 뺀 환경으로 보낸다 |
| 감싼 `/clear` 는 실행되지 않는다. Codex 는 감싼 `/new` 에 비운 척까지 한다 | X2, X3 | 슬래시 명령은 늘 `hc keys` 로 친다 |
| 입력이 사라져도 send 결과는 `started:true` 이고 turn 이 오를 수 있다 | X3 | 들어갔는지는 `started` 가 아니라 turn 과 Dispatch 활동으로 본다(13.6) |
| Claude `/clear`: keys 로 0.25초, 0.1–0.3초 안에 `idle`·turn+1. 바로 넣은 입력도 처리된다 | X2 | `terminal-reset`(13.8) |
| Codex `/clear`: 메뉴 없이 새 대화. 13번 모두 입력 유실 없음. 명령 뒤 첫 turn 사건(`idle`, turn+1)이 1.5–1.8초 뒤 온다. `/clear <이름>` 은 새 대화 이름과 제목을 정한다 | X3b | `terminal-reset --name` |
| Codex `/new` 는 git 저장소에서 작업 트리 메뉴를 띄우고, 그동안 넣은 글이 메뉴 선택에 먹혀 사라진다 | X3 | `/new` 는 쓰지 않는다 |
| `hc read --lines N`(N>0)은 스크롤 입력을 보내 Codex 를 `done` 에서 `idle` 로 바꾼다. `--lines 0` 은 바꾸지 않는다 | X3b | horch 는 판정에 화면을 읽지 않는다. 호출자의 상태 확인은 `worker-show --lines 0` |
| 라벨로 붙인 터미널은 그 탭 줄의 오른쪽 끝에 붙는다 | X4 | `--tab` 으로 에이전트 탭에 붙인다. 좌우 정리는 호출자가 한다(herdr-team 5.9) |
| `release` 는 지금 0.8초 만에 고정 터미널을 끄고 지운다 | X1 | 고정 Dispatch 의 release 는 터미널을 남긴다(13.5) |

### 13.2 용어

- **고정 터미널**: `worker-start --keep-open` 으로 띄운 워커 터미널. 그 Dispatch 가 끝나도 터미널을 남기고, 다음 Dispatch 를 같은 터미널에 넣는다. 라벨 `horch.persistent=1` 이 붙는다.
- **고정 Dispatch**: 고정 터미널에서 도는 Dispatch(`--keep-open` 의 첫 Dispatch 와 `--terminal` 로 넣은 Dispatch). `persistent = 1`.
- 3장의 "Dispatch: 워커 터미널 하나와 짝이다" 는 0.2.0 부터 "고정 터미널 하나가 Dispatch 여러 개를 차례로 맡을 수 있다. 한 터미널에 진행 중(`launching`·`active`) Dispatch 는 하나다" 로 읽는다.

### 13.3 데이터 모델(스키마 v3)

`dispatches` 에 열을 더한다.

| 열 | 뜻 |
|---|---|
| `persistent INTEGER NOT NULL DEFAULT 0` | 고정 Dispatch 면 1 |
| `terminal_argv TEXT` | 그 터미널의 hc `argv`(JSON). 생존 판정이 이것과 견준다. `--keep-open` 은 `launch_argv` 를 그대로, `--terminal` 은 그 터미널의 앞 고정 Dispatch 값을 옮긴다 |
| `start_turn INTEGER` | 입력을 보내기 직전에 읽은 그 터미널의 turn. 새 터미널(`hc run`)은 NULL(0 으로 본다) |
| `delivery TEXT` | 보내기 기록(JSON, 13.4 의 6) |
| `seen_at TEXT` | 이 Dispatch 로 워커 명령(`check --dispatch`·`ask`·`escalate`·`done`·`send`)이 처음 신원 확인을 통과한 시각 |

`messages` 에 `send_key TEXT` 열과 부분 유일 인덱스 `send_key_once ON messages(mailbox, send_key) WHERE send_key IS NOT NULL` 을 더한다(`send --key`, 13.9).

- 새 부분 유일 인덱스 `dispatch_one_per_terminal ON dispatches(terminal) WHERE state IN ('launching','active') AND terminal IS NOT NULL`: 한 터미널에 진행 중 Dispatch 는 하나다. 지금의 `dispatch_terminal` 인덱스(유일 아님)는 그대로 둔다.
- 마이그레이션은 누적으로 고친다: `if v < 2: …` 다음 `if v < 3: …`. v2 → v3 은 `dispatches` 의 다섯 열과 `messages.send_key` 를 `ALTER TABLE ADD COLUMN` 하고 두 인덱스를 만든 뒤 `schema_version` 을 3 으로 쓴다. v2 의 행은 모두 `persistent = 0` 이다. v2 에서는 Dispatch 하나가 터미널 하나와 짝이라 인덱스를 만들 때 겹치는 행이 없다. 10장 "스키마" 줄의 "현재 2" 는 "현재 3" 이 된다.
- `launch_argv` 는 `hc run` 으로 띄운 Dispatch 에만 있다. `--terminal` Dispatch 는 NULL 이다.

### 13.4 `worker-start --keep-open` 과 `--terminal`

옵션:

| 옵션 | 뜻 | 같이 쓸 수 없는 것(exit 2 `usage`) |
|---|---|---|
| `--keep-open` | 새 터미널을 고정 터미널로 띄운다. 결과에 `terminal` | `--terminal` |
| `--terminal <주소>` | 이 Run 의 살아 있는 고정 터미널에 새 Dispatch 를 넣는다 | `--keep-open`, `--agent`, `--model`, `--effort`, `--agent-arg`, `--cwd`, `--tab`, `--hidden` |
| `--tab <탭 id>` | 소유자의 space 에서 이 탭에 붙인다(라벨 `herdr.space=<owner_space>`, `herdr.tab=<id>`). Herdr 가 모르는 id 면 새 탭이 생긴다. 사용자 초점은 바뀌지 않는다(X4) | `--hidden`, `--terminal` |
| `--hidden` | herdr 라벨 없이 띄운다. 화면에 나오지 않는다(크기 200×120, X4) | `--tab`, `--terminal` |

- `--agent` 는 `--terminal` 이 없을 때만 필수다. `--terminal` 은 그 터미널의 에이전트·모델·effort·인자·cwd 를 앞 고정 Dispatch 에서 옮겨 기록한다(떠 있는 세션을 그대로 쓰므로 바꿀 수 없다).
- `--tab` 인데 소유자 Run 에 `owner_space` 가 없으면 exit 2 `no_owner_space`. `--tab` 값은 `[A-Za-z0-9_-]` 1–64자(아니면 exit 2 `usage`).
- 결과의 `placement`: `pane`(소유 탭 또는 `--tab`), `hidden`, `none`(소유 탭 없음, 지금 그대로), `same_terminal`(`--terminal`).
- `--keep-open` 의 나머지는 8장 절차 그대로다. 다른 점: `persistent = 1`, `terminal_argv = launch_argv`, 라벨에 `horch.persistent=1` 을 더한다. 프리앰블은 지금처럼 에이전트 argv 의 마지막 인자다.

`--terminal <t>` 절차:

1. 호출자가 소유자인지 확인한다(아니면 exit 5 `not_owner`). `--task` 가 있으면 5장 재시도 규칙을 그대로 쓴다.
2. 터미널 확인(트랜잭션 밖). `hc get <t>`(5초) 실패는 exit 1 `hc_failed`(아무것도 만들지 않는다). 다음이면 exit 3 이고 아무것도 만들지 않는다.

   | 조건 | code | data |
   |---|---|---|
   | `not_found`, `finished`, `stopped_by_restart`, argv 가 `terminal_argv` 와 다름 | `terminal_gone` | `verdict` |
   | 라벨 `horch.run` 이 호출자 Run 이 아니거나 `horch.persistent` 가 없음, 또는 DB 에 그 터미널의 고정 Dispatch 가 없음 | `not_persistent_terminal` | |
   | 그 터미널에 `launching`·`active` Dispatch 가 있음, 또는 `terminal-reset` 이 진행 중(13.8) | `terminal_busy` | `dispatch` |
   | 상태가 `idle`·`done` 이 아님(`working`, `blocked`, `error`, 보고 없음) | `terminal_not_ready` | `status`, `turn` |

3. `BEGIN IMMEDIATE` 트랜잭션에서 소유자를 다시 확인하고, 그 터미널의 리셋 예약(13.8 의 3, 살아 있는 프로세스의 것)이 없는지 다시 본 뒤 Task(또는 `--task`)와 Dispatch(`launching`, `persistent = 1`, `terminal = <t>`, `terminal_argv`, 옮긴 에이전트 값, `launcher_pid`·`launcher_started`)를 만든다. 리셋 예약이 있거나 `dispatch_one_per_terminal` 에 걸리면 아무것도 만들지 않고 exit 3 `terminal_busy`. 리셋 예약 확인과 Dispatch 예약이 한 트랜잭션이라 리셋과 재투입이 서로 배제된다(13.8).
4. `spec.md`·`preamble.md` 를 쓴다(8장). 프리앰블 첫 항목 뒤에 한 줄을 더한다: "이 세션은 앞 태스크를 이어 받았을 수 있다. 앞 대화의 Task·Dispatch ID 는 쓰지 않는다. 이 프리앰블의 ID 만 쓴다." 0.2.0 은 모든 Dispatch 의 프리앰블 4항 "코디네이터 메시지" 를 "소유자 메시지" 로 바꾼다.
5. `hc get <t>` 로 상태와 turn 을 다시 읽는다. 2 의 조건 가운데 `terminal_gone`·`not_persistent_terminal`·`terminal_not_ready` 와, 이 Dispatch 가 아닌 진행 중 Dispatch·리셋 예약(`terminal_busy`)을 다시 본다. 3 에서 만든 자기 Dispatch 는 빼고 본다. 걸리면 Dispatch 를 `launch_failed` 로 두고 그 code 로 끝난다. 아니면 그 turn 을 `start_turn` 으로, `delivery = {"attempted": true, "turn_before": <turn>}` 을 먼저 기록한다(조건부 쓰기, `launching` 일 때만).
6. 프리앰블 글 전체를 보낸다: `HC_TERMINAL_ID` 를 뺀 환경으로 `hc send <t> <글> --json`(상태가 `idle` 이면 `--if idle` 을 붙이고, `done` 이면 붙이지 않는다). 결과는 7 에서 `delivery` 에 쓴다: `{attempted: true, via: "send", if: "idle"|null, status_before, turn_before, started, status, turn, at}`. `attempted` 는 지우지 않는다.
   - `status_mismatch`(그 사이 `working`·`blocked` 가 됐다. hc 는 아무것도 치지 않는다): 한 트랜잭션에서 `delivery` 에 `{attempted: true, typed: false, error}` 를 쓰고 Dispatch 를 `launch_failed` 로 둔 뒤 exit 3 `terminal_not_ready`.
   - 그 밖의 hc 실패(시간 초과, 응답 유실): 들어갔을 수 있다(hc 도움말: "send 가 실패해도 들어갔을 수 있다"). 7 에서 `active` 로 두고 `delivery` 에 `{attempted: true, uncertain: true, error}` 를 쓰고 `warnings` 에 `delivery_uncertain` 을 넣는다. 들어가지 않았으면 13.6 의 `not_started` 가 알린다.
7. 보내기 결과(`delivery`)와 `active` 전이를 한 트랜잭션에서 쓴다(조건부 쓰기, `launching` 일 때만). 둘 사이에 죽는 틈이 없다. 라벨을 `hc label <t> horch.dispatch=<새 id>` 로 바꾼다. 실패하면 `warnings` 에 `label_failed` 를 넣고 계속한다(고정 터미널의 정리는 이 라벨에 기대지 않는다, 13.5).
   - 워커가 먼저 온 경우(Codex 커밋 리뷰 847e971): 보낸 입력이 7 보다 먼저 처리돼 이 Dispatch 의 워커 명령(`check --dispatch`·`ask`·`escalate`·`done`)이 신원 확인을 통과하면, 그 Dispatch 가 `--terminal` Dispatch(`persistent = 1`, `launch_argv` NULL)이고 `launching` 이며 `delivery.attempted` 가 있을 때 조건부 쓰기(`launching` 일 때만)로 `active` 로 넘기고 명령을 이어 간다(새 터미널의 가드 등록과 같은 자리). `attempted` 전이면 지금처럼 `dispatch_not_active` 로 거부한다. 7 의 조건부 쓰기가 행을 바꾸지 못했고 지금 상태가 `active` 면 `delivery` 결과만 쓰고 성공으로 끝낸다. 그 밖의 상태(워커가 이미 `done` 했다 등)면 쓰지 않고 지금 상태를 결과에 낸다.
8. 결과 `{task, dispatch, terminal, state: "active", placement: "same_terminal", start_turn, delivery, warnings}`.
- 고정 Dispatch 의 `launch_failed` 는 `worker-list`·`worker-show` 의 재시도 안내(`next`)를 주지 않는다(attention 은 `launch_failed` 그대로). 배치(`--keep-open`·`--tab`·`--hidden`·`--terminal`)를 저장하지 않으므로 배치를 아는 호출자가 다시 띄운다(Codex 커밋 리뷰 847e971).

실행자가 죽었을 때(5장 launching 조정에 더한다): 고정 Dispatch 가 `launching` 이고 실행자가 죽었으면, `delivery.attempted` 가 없으면(보내기 전에 죽었다) 지금처럼 `launch_failed` 다. 있으면(보냈을 수 있다. 결과 기록은 `active` 전이와 한 트랜잭션이라 `launching` 으로 남은 것은 결과를 쓰기 전이다) 순간 상태로 실패를 정하지 않는다. 죽은 실행자의 `hc send` 가 아직 끝나지 않았거나 들어간 입력이 아직 시작하지 않았을 수 있고(X1: 정상 제출도 `started:true, status:done, turn:1` 이었다), 고정 터미널에는 새 터미널의 가드 같은 늦은 실행 막기가 없기 때문이다. 6 의 응답 유실과 같게 `active` 로 두고 `delivery` 에 `{attempted: true, uncertain: true, error: "executor_died"}` 를 쓴다(조건부 쓰기). 그다음은 전달 판정이 정한다: turn 이 `start_turn` 보다 오르거나 이 Dispatch 의 워커 명령(`seen_at`)·`done` 이 오면 들어간 것이고, 60초 뒤에도 turn 그대로·활동 없음이면 `not_started` 관찰이 호출자에게 알린다(13.6). hc 를 부르지 않는다. 그래서 `attempted` 뒤의 결과는 늘 `active`(확실하거나 불확실한) 하나다.

### 13.5 release, abandon, terminal-close

- `worker-release --dispatch D [--keep-terminal]`: 고정 Dispatch 는 터미널을 끄지도 지우지도 않는다(`--keep-terminal` 을 주든 안 주든). hc 를 부르지 않으므로 `terminal_mismatch` 도 없다. `released`·`closed_at` 만 쓴다. 고정이 아닌 Dispatch 에 `--keep-terminal` 을 주면 exit 2 `usage`(그 터미널을 닫을 길이 없어진다). 고정이 아닌 Dispatch 는 지금 그대로다.
- `worker-abandon --dispatch D [--keep-terminal] [--kill]`: 고정 Dispatch 이고 판정이 `live` 면 `--keep-terminal` 이 있어야 한다. 그러면 터미널은 두고 `abandoned` 만 쓴다(세션은 그대로 살아 있다). 없으면 exit 3 `worker_alive`(hint `--keep-terminal` 또는 `terminal-close --abandon`). 고정 Dispatch 에 `--kill` 을 주면 exit 2 `usage`(고정 터미널은 `terminal-close` 로 닫는다). `exited`·`lost` 는 지금처럼 플래그 없이 `abandoned` 다.
- 새 명령 `terminal-close --terminal <t> [--abandon]`(소유자):
  1. `hc get <t>`. `not_found` 면 이미 닫힌 것이다: 그 터미널의 끝나지 않은 고정 Dispatch 를 아래 4 처럼 정리하고 `{terminal, closed: false, reason: "not_found"}`(exit 0). 그 밖의 hc 실패는 exit 1 `hc_failed`.
  2. 라벨 `horch.run` 이 호출자 Run 이고 `horch.persistent=1` 이어야 한다(아니면 exit 3 `not_persistent_terminal`).
  3. 그 터미널에 `launching`·`active` Dispatch 가 있으면 `--abandon` 이 있어야 한다(아니면 exit 3 `terminal_busy`, data `dispatch`).
  4. `hc kill`(live 일 때) → `hc rm`(kind `live` 일 때만 잠깐 다시) → 한 트랜잭션에서 진행 중 Dispatch 를 `abandoned`, 그 터미널의 `settled`·`retained`·`abandoned` Dispatch 를 모두 `released` 로 쓴다. kill·rm 이 실패하면 상태를 바꾸지 않고 exit 1. 다시 부르면 이어 한다.
  - 터미널 예약(Codex 커밋 리뷰 c6d82d2): 3 의 진행 중 Dispatch 검사는 13.8 의 3 과 같은 터미널 예약(`meta` 의 `reset:<t>`, 값 끝에 종류 `close`)을 쓰는 `BEGIN IMMEDIATE` 트랜잭션 안에서 하고, 그 예약을 kill 전에 잡아 끝날 때까지(성공·실패 모두) 쥔 뒤 자기 값일 때만 지운다. 그동안 `worker-start --terminal`·`terminal-reset` 은 exit 3 `terminal_busy` 이고, 살아 있는 다른 예약이 있으면 닫기도 exit 3 `terminal_busy` 다. 검사와 kill 사이에 새 Dispatch 가 들어와 `--abandon` 없이 닫히는 일을 막는다. `not_found`(1)는 hc 를 부르지 않으므로 예약 없이 기록만 정리한다.
  5. 결과 `{terminal, closed: true, abandoned: <dispatch 또는 null>, released: [<id>…]}`.
- 고정 Dispatch 의 `--terminal` 실패(`launch_failed`)는 터미널을 만들지 않았으므로 5장의 거부 터미널 정리 대상이 아니다. 정리는 hc 이름과 라벨 `horch.dispatch` 가 모두 그 `launch_failed` Dispatch 인 `finished` 터미널만 지운다. 고정 터미널의 이름은 첫 Dispatch ID 이고 라벨은 Dispatch 가 `active` 가 된 뒤에만 바뀌므로 걸리지 않는다. 첫 Dispatch 가 `launch_failed` 인 고정 터미널(가드가 거부했다)은 지금처럼 정리한다.

### 13.6 생존·idle·전달 판정

| 곳 | 지금(0.1.x) | 0.2.0 |
|---|---|---|
| `liveness.verdict` 의 기대 argv | Dispatch 의 `launch_argv` | `terminal_argv` 가 있으면 그것, 없으면 `launch_argv` |
| `idle_turn` | 상태 `idle`·`done` 이고 turn ≥ 1 | 상태 `idle`·`done` 이고 turn > `start_turn`(NULL 은 0) |
| `worker-release` | 라벨 확인 → kill → rm | 고정 Dispatch 는 hc 를 부르지 않는다 |
| `worker-abandon` | live 면 `--kill` 필요 | 고정 Dispatch 는 13.5 |
| `_describe`·`attention` | Dispatch 마다 터미널을 본다 | 같다. 고정 Dispatch 의 `settled`·`abandoned` 는 `next` 가 `worker-release`(상태만 바꾼다) |
| 보낸이(`send --to run:`) | 터미널의 진행 중 Dispatch, 없으면 `external:` | 같다. 고정 터미널이 Dispatch 사이에 보낸 글은 `external:<t>`(X1) |
| `status` 의 `dispatch` | 터미널의 진행 중 Dispatch | 같다(인덱스로 하나다) |

새 관찰 `not_started`(고정 Dispatch 중 `--terminal` 로 넣은 것만, 9장 observed 표에 더한다):

- 조건: `active` 이고, 보낸 뒤(`delivery.at`, 없으면 `created_at`) 60초(`NOT_STARTED_S`)가 지났고, hc 상태가 `idle`·`done` 이고, turn == `start_turn` 이고, `seen_at` 이 비었고, 이 Dispatch 가 보낸 메시지가 없다. 상태가 `working` 이면 일하는 중으로 본다(관찰 없음). 상태 보고가 없으면 `no_status` attention 으로 남긴다.
- key 는 `start_turn`. body 는 다른 observed 와 같은 꼴에 `start_turn`·`turn`·`delivery` 를 더한다.
- horch 는 다시 보내지 않는다. 다시 넣을지는 호출자가 정한다(`worker-abandon --keep-terminal` 뒤 `--terminal` 로 새 Dispatch).
- `seen_at` 은 워커 명령의 신원 확인을 통과할 때 비어 있으면 그 시각을 쓴다(한 번의 조건부 쓰기).

### 13.7 hcio

`hcio` 에 더하는 것(hc 를 부르는 곳은 여전히 이 모듈뿐이다).

| 함수 | hc 명령 | 시간 |
|---|---|---|
| `send(t, text, if_status=None, untagged=False, timeout=30)` | `hc send T <글> [--if S] --json`. `untagged` 면 환경에서 `HC_TERMINAL_ID` 를 뺀다 | 30초 |
| `keys(t, keys, timeout=10)` | `hc keys T <키…> --json`. 이름 있는 키와 글자(`/ c l e a r enter`) | 10초 |
| `label(t, pairs, timeout=10)` | `hc label T k=v …` | 10초 |
| `events(t)` | `hc events --json --terminal T` 를 띄우고 줄마다 사실 변화(JSON)를 준다. 호출자가 마감을 정하고 끝나면 프로세스를 끝낸다 | 호출자 |
| `kill(t, timeout=30)` | 지금 함수에 시간 인자를 더한다 | 30초 |

가짜 hc(`tests/fakes/hc`)에 `keys`·`label`·`events` 를 더한다. `send` 는 `--if`·`started`·`status`·`turn`·감싸기 여부(받은 환경에 `HC_TERMINAL_ID` 가 있었는지)를 기록한다. 시나리오로 `/clear` 를 받으면 turn 을 올리고 `idle` 로 바꾸는 것, turn 사건을 늦게 주거나 주지 않는 것, 보낸 글을 버리는 것(입력 유실)을 흉내 낸다.

### 13.8 `terminal-reset`

`terminal-reset --terminal <t> [--name <이름>] [--timeout-ms N]`(소유자, 기본 10000): 고정 터미널의 세션을 제자리에서 비운다. 프로세스·터미널 주소·pane·제목은 그대로다.

1. 13.4 의 2 와 같은 확인을 한다(`terminal_gone`·`not_persistent_terminal`·`terminal_busy`·`terminal_not_ready`). 에이전트는 그 터미널의 마지막 고정 Dispatch 의 `agent` 다.
2. `--name` 은 Codex 에만 쓴다. `^[a-z][a-z0-9-]{0,31}$` 가 아니면 exit 2 `usage`. Claude 에 주면 무시하고 `warnings` 에 `name_ignored`(Claude 는 띄울 때 준 `--name` 제목이 `/clear` 뒤에도 남는다, X6).
3. 리셋 예약: `BEGIN IMMEDIATE` 트랜잭션에서 그 터미널에 `launching`·`active` Dispatch 가 없고 살아 있는 다른 예약이 없는지 다시 본 뒤 `meta` 에 `reset:<t> = <pid>|<시작 시각>|<at>|reset` 을 쓴다(걸리면 exit 3 `terminal_busy`). 같은 key 를 `terminal-close` 도 종류 `close` 로 쓴다(13.5 의 4). 예약이 있고 그 프로세스가 살아 있는 동안 `worker-start --terminal`(13.4 의 3 이 같은 트랜잭션 꼴로 본다)·다른 `terminal-reset`·`terminal-close` 는 exit 3 `terminal_busy` 다. 종류가 없는 옛 값은 `reset` 으로 본다. 끝나면(성공·실패 모두) 값이 자기 pid·시작 시각일 때만 지운다(조건부 쓰기). 죽은 프로세스의 예약은 없는 것으로 본다.
4. `events(t)` 구독을 먼저 붙이고 `turn_before`(지금 turn)를 읽는다. 구독을 띄우지 못하면 아래 5 의 대체 신호만 쓴다.
5. `keys(t, ["/", "c", "l", "e", "a", "r", "enter"])`. Codex 에 `--name` 이 있으면 `enter` 앞에 빈칸과 이름 글자를 하나씩 넣는다(X3b C1 에서 `/clear p6x-next` 가 이름을 붙였다. 빈칸의 키 이름은 hc 의 키 표를 따른다). 감싼 send 나 `/new` 는 쓰지 않는다. keys 가 실패하면 exit 1 `hc_failed`.
6. 기다림: 구독의 turn 사건 가운데 turn 이 `turn_before` 보다 크고 상태가 `idle` 인 첫 사건을 마감까지 기다린다. 대체 신호로 0.2초마다 `hc get` 을 보고 turn > `turn_before` 이고 상태 `idle` 이면 끝난 것으로 본다(둘 중 먼저 온 것). Claude 는 0.1–0.3초, Codex 는 1.5–1.8초였다(X2, X3b). 실제 `hc events --json` 은 첫 줄이 스냅숏 `{channel, seq, terminals}` 이고 그 뒤는 JSON-RPC 알림 `{"method": "event", "params": {type, terminal, seq, data}}` 다(turn 의 data `{state, turn}`, state 는 그 turn 이 끝난 뒤 상태다. 2026-11-10 확인). 줄 해석은 `hcio` 가 하고(turn 사건에 상태가 없으면 마지막 status 사건의 상태), heartbeat·missed·그 밖의 종류는 건너뛴다. 마감이 지나 시간 초과로 정하기 전에 이미 온 사건을 기다리지 않고 한 번 더 다 읽는다(느린 폴링 `hc get` 이 마감을 넘기는 동안 온 신호, Codex 커밋 리뷰 c6d82d2). 상태는 `idle` 만 받는다: 보통 턴은 done 으로 끝난다. done 을 받으면 보통 글로 처리된 /clear 를 비운 것으로 본다(X2·X3b).
7. 성공: `{terminal, agent, turn, status, title, seconds, signal: "event"|"poll"}`(exit 0). 호출자는 이 `turn` 이 다음 `--terminal` 의 기준이 된다는 것을 안다(비우기 자체가 turn 을 하나 올린다, X2·X3b).
8. 마감까지 신호가 없으면 exit 4 `reset_timeout`(data `{turn_before, last: {status, turn, title}}`). horch 는 더 하지 않는다. 비웠는지 알 수 없으므로 호출자가 터미널을 닫고 새로 띄운다(herdr-team 5.9).

### 13.9 명령·오류 정리

7장 명령 표에 더하는 것:

| 명령 | 인자 | 결과 |
|---|---|---|
| `worker-start` | 13.4 의 `--keep-open`, `--terminal`, `--tab`, `--hidden` | `{task, dispatch, terminal, state, placement, …}` |
| `worker-release` | `--keep-terminal` | `{dispatch}` |
| `worker-abandon` | `--keep-terminal` | `{dispatch, verdict}` |
| `terminal-close` | `--terminal`, `--abandon` | `{terminal, closed, abandoned, released}` |
| `terminal-reset` | `--terminal`, `--name`, `--timeout-ms` | `{terminal, agent, turn, status, title, seconds, signal}` |

`send --key <K>`(0.2.0, 선택): 검사 순서는 소유자 확인(`dispatch:` 는 D 가 소유자 Run 의 Dispatch 인지) → key 조회 → 나머지 검사다. 같은 메일함·같은 key 의 메시지가 이미 있으면 D 의 지금 상태(`active` 가 아니어도)와 상관없이 새로 쓰지 않고 그 메시지와 `duplicate: true` 를 돌려준다(깨우지도 않는다). 본문·제목이 다르면 exit 3 `send_key_conflict`. key 의 메시지가 없을 때만 `active` 검사(exit 3)와 쓰기를 한다. key 는 1–64자 `[A-Za-z0-9._:-]`(아니면 exit 2 `usage`). 저장은 `messages.send_key` 열과 부분 유일 인덱스 `send_key_once ON messages(mailbox, send_key) WHERE send_key IS NOT NULL`(13.3 의 v3 에 더한다). 호출자가 요청 id 로 같은 전송을 다시 해도 한 번만 간다(herdr-team 의 `scope`).

6장 권한 표: `terminal-close`·`terminal-reset` 은 그 Run 의 소유자다. `worker-list`·`worker-show` 행에 `persistent`, `start_turn`, `delivery`, `seen_at` 을 더한다(`worker-list --state` 의 선택지는 그대로 7개).

새 오류 code:

| code | exit | 때 |
|---|---|---|
| `terminal_gone` | 3 | 고정 터미널이 없거나 끝났거나 다른 프로그램이다 |
| `not_persistent_terminal` | 3 | 이 Run 의 고정 터미널이 아니다 |
| `terminal_busy` | 3 | 진행 중 Dispatch 나 리셋·닫기가 있다 |
| `terminal_not_ready` | 3 | 상태가 `idle`·`done` 이 아니다(보내지 않았다) |
| `reset_timeout` | 4 | 비우기 신호가 마감까지 오지 않았다 |
| `no_owner_space` | 2 | `--tab` 인데 소유 space 가 없다 |
| `send_key_conflict` | 3 | `send --key` 의 같은 key 로 다른 제목·본문을 보냈다 |

exit 코드 표(7장)는 그대로다(새 값 없음).

### 13.10 테스트

- 스키마: v2 DB 를 열면 v3 으로 올라가고 기존 행은 `persistent = 0`, 인덱스가 같은 터미널의 두 번째 진행 중 Dispatch 를 막는다.
- `--keep-open`: 라벨 `horch.persistent=1`, `terminal_argv = launch_argv`, `--tab`·`--hidden` 라벨과 `placement`.
- `--terminal`: 옵션 충돌(exit 2), 2 의 거부 표 전부, 5 의 다시 보기가 자기 Dispatch 를 빼고 정상 재투입이 통과함, 리셋 예약과 Dispatch 예약의 배제(한쪽만 성공), `idle` 이면 `--if idle`·`done` 이면 조건 없음(가짜 hc 가 받은 인자), 감싸지 않음(환경에 `HC_TERMINAL_ID` 없음), `start_turn` 이 보내기 직전 turn, `status_mismatch` 면 `launch_failed`, 응답 유실이면 `active` 와 `delivery_uncertain`, 라벨 갱신, 프리앰블의 이어 받기 줄.
- 실행자 사망: 보내기 전(`launch_failed`), `attempted` 뒤 결과 기록 전(`active` 와 `uncertain`, 그 뒤 turn 이 오르면 관찰 없음·그대로면 60초 뒤 `not_started`), 결과와 `active` 를 함께 쓴 뒤(`active` 그대로).
- 판정: 고정 Dispatch 의 생존을 `terminal_argv` 로, `idle_turn` 이 `start_turn` 기준(다시 넣자마자 거짓 idle 이 나오지 않음), `not_started` 의 조건(60초, turn 그대로, `seen_at` 없음, 메시지 없음)과 `working` 이면 관찰 없음.
- `send --key`: 같은 key 두 번은 메시지 하나와 `duplicate: true`(두 번째 때 D 가 `settled`·`retained` 여도), 본문이 다르면 `send_key_conflict`, key 의 메시지가 없고 D 가 `active` 가 아니면 지금처럼 exit 3, key 없는 send 는 지금 그대로.
- release·abandon·terminal-close: 고정 Dispatch 의 release 가 hc 를 부르지 않음, abandon 의 `--keep-terminal`·`--kill` 규칙, terminal-close 의 `--abandon`·`not_found`·kill 실패 재시도.
- terminal-reset: keys 인자(`/clear`, Codex 이름), turn 사건 대기, 대체 신호(`hc get` 폴링), 마감 exit 4, 진행 중 표시가 `--terminal` 을 막음, 진행 중 Dispatch·`working` 이면 거부.
- 0.1.x 테스트는 그대로 통과한다(고정이 아닌 Dispatch 의 release 가 kill·rm).
- 버전 세 곳(`paths.VERSION`, `herdr-orch/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` 의 herdr-orch 항목)이 0.2.0 으로 같다. herdr-team 의 `HORCH_MIN` 은 0.2.0 이 된다.
- 실환경은 herdr-team 6단계 실환경 확인(그 설계 15.2)에서 함께 본다. 사용자 hc core 는 멈추거나 다시 띄우지 않는다.

### 13.11 한계

- hc core 재시작 뒤 고정 터미널과 진행 중 Dispatch 가 이어지는지는 확인하지 않았다(실험 X7 을 하지 않았다). 10장 판정대로 복구 셸로 바뀐 터미널은 `lost` 이고 `--terminal` 은 `terminal_gone` 이다.
- v2 → v3 마이그레이션은 같은 터미널 주소의 `launching`·`active` Dispatch 가 둘이면 `dispatch_one_per_terminal` 을 만들지 못해 저장소를 열 수 없다. 13.3 은 v2 에 그런 행이 없다고 본다(hc 가 주소를 다시 쓰고 옛 Dispatch 가 `active` 로 남았을 때만 생긴다). hc 가 주소를 다시 쓰는지는 herdr-team 6단계 실환경 확인(Task 12)에서 본다(태스크 리뷰 Minor 3, 고치지 않음).
- 입력 유실은 60초 뒤 `not_started` 로만 안다. 그 사이 워커는 아무것도 하지 않는다.
- `terminal-reset` 은 비우기를 turn 신호로만 확인한다. 화면이나 대화 기록을 읽지 않는다. 신호가 왔는데 비우지 못한 경우(바뀐 CLI 화면 등)는 잡지 못한다.
- `terminal-reset` 의 대체 신호 `hc get`(호출마다 3초)은 남은 시간으로 줄이지 않는다. 마감 직전에 시작한 호출이 마감을 3초까지 넘길 수 있고, 그 호출이 본 신호는 성공으로 받는다(Codex 계획 리뷰 r1, 기록만).
- 감싸지 않은 send 는 사람이 친 글처럼 들어간다. hc 의 보낸 쪽 추적(`<hc from>`)을 쓰지 않는다.
- hc 가 아직 `launching`·`active` 인 Dispatch 의 주소를 새 터미널에 다시 쓰면, 그 터미널의 가드 등록이 `dispatch_one_per_terminal` 에 걸려 오류로 끝나고 새 워커가 뜨지 않는다(그 Dispatch 는 `launch_failed` 가 된다). 주소는 늘어나는 값으로 보이므로(t12w → t133) core 재시작(X7) 뒤에만 생길 수 있다. 마이그레이션 한계와 뿌리가 같다. hc 주소 재사용은 herdr-team 6단계 실환경 확인(Task 12)에서 본다(최종 리뷰, 기록만).

## 14. 0.3.0: 워커 환경 변수 (2026-11-11)

herdr-team 7단계의 작업 공간(그 설계 5.10)은 워커·리뷰어마다 다른 환경 변수(시험 DB 포트 등)를 준다. `hc run` 으로 띄운 터미널은 부른 셸의 환경을 물려받지 않는다(herdr-team 6단계 실환경 확인). 그래서 horch 가 값을 Dispatch 에 기록하고, `launch-guard` 가 에이전트를 exec 하기 직전에 그 값을 환경에 넣는다.

### 14.1 `worker-start --env`

- `--env KEY=VALUE`(되풀이, 32개까지). KEY 는 `^[A-Za-z_][A-Za-z0-9_]*$` 이고 `HC_`·`HORCH_` 로 시작하지 않는다(가드와 판별이 쓰는 변수). VALUE 는 줄바꿈·NUL 이 없는 1 KiB 이하 문자열이다. 같은 KEY 가 두 번이거나 형식이 틀리면 exit 2 `usage`.
- `--terminal` 과 같이 쓰면 exit 2 `usage`(살아 있는 세션의 환경은 바꾸지 못한다). `--keep-open` 과는 쓸 수 있다(그 고정 터미널의 첫 환경이다).
- `--task --retry`: `--env` 를 주면 그 값을, 주지 않으면 그 Task 의 마지막 Dispatch 의 값을 쓴다.

### 14.2 기록(스키마 v4)

- `dispatches.env TEXT`(JSON 객체, 없으면 NULL). v3 → v4 는 `ALTER TABLE ADD COLUMN` 하나와 `schema_version` 4 다(누적 마이그레이션 `if v < 4`).
- `worker-list`·`worker-show` 행에 `env` 를 더한다.

### 14.3 적용

- `launch-guard` 가 가드 등록을 마친 뒤 `os.execvp` 직전에 `os.environ` 에 더한다(같은 이름은 덮어쓴다). 프리앰블에는 넣지 않는다. Claude 의 인자에도 넣지 않는다.
- Codex 는 셸 도구에 넘길 환경을 `shell_environment_policy`(`inherit`, 이름 필터, `include_only`·`exclude`)로 정한다. 버전과 사용자 설정에 따라 이름에 `KEY`·`SECRET`·`TOKEN` 이 든 변수나 허용 목록 밖 변수가 빠질 수 있다(Codex 설계 리뷰 r1). herdr-team 은 그런 이름을 쓰지 않게 검사한다(그 설계 4.2). Codex 셸이 값을 보는지는 기본 설정과 사용자 정책이 있을 때 모두 사전 검증 S2 로 확인한다(그 설계 15.2).
- S2 결과(2026-11-11, `codex exec` 로 대신 쟀다. 그날 대화형 Codex 는 사용자 플러그인 훅 오류로 셸 명령이 막혀 잴 수 없었다): 사용자 설정 `inherit = "core"` 와 `-c shell_environment_policy.inherit="core"` 에서는 환경의 값이 Codex 셸에 보이지 않았다. `-c shell_environment_policy.set.<이름>=<값>` 을 더하면 보였다. `include_only` 를 쓰면 `set` 값도 빠졌다. 그래서 Codex 에는 `HC_TERMINAL_ID` 인자 뒤에 Dispatch env 의 이름 순서로 `-c shell_environment_policy.set.<이름>=<JSON 문자열>` 도 더한다(`guard.inject_codex_env`). `include_only` 정책은 herdr-team doctor 가 경고한다(그 설계 9.2).

### 14.4 테스트·버전·한계

- 테스트: `--env` 형식 오류와 `--terminal` 충돌(exit 2), 가짜 hc 가 받은 `launch-guard` 가 exec 한 프로세스의 환경, retry 의 값 물려받기, v3 DB 를 열면 v4 로 올라가고 기존 행은 `env` NULL.
- 버전 세 곳(`paths.VERSION`, `herdr-orch/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`)을 0.3.0 으로 맞춘다. herdr-team 의 `HORCH_MIN` 은 0.3.0 이 된다.
- 한계: 값은 저장소(SQLite)와 `worker-show` 출력에 남는다. 비밀값을 넘기지 않는다(herdr-team 은 포트·경로 같은 값만 넘긴다).

## 15. 0.4.0: 부모 터미널 (2026-11-16)

herdr-team 11단계(그 설계 1장 11단계 결정·확인한 것, 3.2)는 Herdr Agents 목록에서 프로젝트 터미널을 메인 세션 아래로 묶는다. Herdr 앱은 hc parent 가 있는 터미널을 부모 아래 sub-agent 로 그린다. horch 는 워커를 늘 `--no-parent` 로 띄워(8장) 모두 맨 위에 나왔다. 호출자가 부모를 고르게 한다. hc parent 는 띄울 때 한 번 정해지고 나중에 바꾸는 명령이 없다(hc schema).

### 15.1 `worker-start --parent`

- `--parent <터미널>`(선택, hc 주소나 이름. `[A-Za-z0-9_.:-]` 1–64자, 아니면 exit 2 `usage`): 새로 띄우는 워커 터미널의 hc parent. `--keep-open`·`--tab`·`--task --retry`·`--env` 와 쓸 수 있다.
- `--hidden` 이나 `--terminal` 과 함께면 exit 2 `usage` 다(아무것도 만들기 전에, 13.4 의 옵션 검사와 같은 곳). `--terminal` 은 새 터미널을 띄우지 않는다(지금 문구의 목록에 `--parent` 를 더한다). 숨은 터미널은 pane 이 없어 앱에서 부모를 끝내거나(`terminal.kill`) 부모의 pane·탭을 닫으면 `--outlive-parent` 여도 함께 끝난다(그 설계 1장 실험 e1·k1·m1). 문구: `--parent 와 --hidden 은 같이 쓸 수 없다(pane 없는 자식은 부모의 pane·탭을 닫으면 함께 끝난다)`.
- 저장하지 않는다(배치처럼, 13.4). `--task --retry` 로 다시 띄울 때 호출자가 다시 준다. `worker-list`·`worker-show` 의 재시도 안내 argv 에도 넣지 않는다.
- 결과에 `parent`(실제로 쓴 parent. 주지 않았거나 15.3 으로 parent 없이 띄웠으면 null)를 더하고, `receipt.json` 에 받은 `parent` 를 쓴다.
- `--parent` 가 없으면 0.3.0 그대로다(일반 horch 사용자).

### 15.2 hcio

`run_bg(name, cwd, labels, argv, parent=None)`: parent 가 있으면 `hc run --bg --json --parent <T> --outlive-parent --no-notify --name … --cwd …`, 없으면 지금처럼 `--no-parent --no-notify`. `--no-notify` 는 늘 준다(부모를 정해도 부모 입력란에 아무것도 들어가지 않았다, 실험 f1). `--outlive-parent` 면 부모 프로그램이 저절로 끝나도 `hc kill` 로 끝나도 워커가 산다(실험 c1–c3·d1·d2). hc 는 `--parent` 와 `--no-parent` 를 함께 받지 않는다(usage, 실험 q4).

### 15.3 parent 가 없을 때

- 8장 5 의 `hc run` 이 kind `not_found`, message `no terminal "<parent>"`(hc 0.1.20 의 문구)로 실패하면 터미널은 생기지 않았다(실험 g4). `launch_failed` 로 바꾸기 전에 같은 Dispatch·같은 이름으로 parent 없이(`--no-parent`) 한 번 더 띄운다. `receipt.json` 에 `parent_fallback: {parent, error}` 를, 결과 `warnings` 에 `parent_missing` 을 넣는다. 묶음은 보기 위한 것이라 그것 때문에 워커를 못 띄우면 안 된다.
- 다른 실패(다른 not_found 문구, 시간 초과, 그 밖의 kind)는 다시 띄우지 않고 8장 6 대로 `launch_failed` 다. 다시 띄운 것도 실패하면 그 실패로 `launch_failed` 다.
- 끝난(finished) 부모는 hc 가 받는다(실험 q1). horch 는 미리 `hc get` 으로 보지 않는다. 화면 묶음만 보이지 않고 워커는 산다. 호출자가 부모 주소를 고친다(herdr-team 은 메인 명령이 고친다).

### 15.4 테스트·버전·한계

- 테스트(`test_hcio`, `test_workers_start`): `run_bg(parent="t5")` 의 인자가 `--parent t5 --outlive-parent --no-notify` 이고 `--no-parent` 가 없다. parent 가 없으면 지금 인자 그대로다. `worker-start --parent` 가 hc 호출·receipt·결과에 실리고 `--keep-open --tab` 과 함께 된다. `--hidden`·`--terminal` 과 함께거나 형식이 틀리면 exit 2 이고 Task·Dispatch 를 만들지 않는다. 가짜 hc 가 그 parent 를 not_found(그 문구)로 거부하면 parent 없이 한 번 더 띄우고 `parent_missing`·`parent_fallback`·결과 `parent: null` 이다. 다른 not_found 문구나 다른 실패는 다시 띄우지 않는다(hc run 호출 한 번). `--task --retry` 는 parent 를 주면 그 값, 안 주면 parent 없이 띄운다(저장하지 않는다).
- 가짜 hc(`tests/fakes/hc`): `run` 이 `--parent <값>` 을 값 있는 옵션으로 읽어 터미널의 `parent` 에 둔다(`--no-parent` 나 둘 다 없으면 null, 지금 시험이 기대는 동작). `flags` 에 `--outlive-parent` 를 남긴다. 없는 parent 는 kind `not_found`, message `no terminal "<값>"` 으로 실패하고 터미널을 만들지 않는다. `--parent`·`--no-parent` 를 함께 주면 exit 2 usage. `get` 은 `parent` 를 돌려준다.
- 버전 세 곳(`paths.VERSION`, `herdr-orch/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`)을 0.4.0 으로 맞춘다. 스키마는 그대로다(v4). herdr-team 의 `HORCH_MIN` 은 0.4.0 이 된다.
- 한계: 이미 떠 있는 워커의 parent 는 바꾸지 못한다. 부모를 `hc rm` 하면 자식의 parent 는 없는 주소를 가리키고(orphan), 앱이 그것을 어떻게 그리는지는 확인하지 못했다. hc core 정지·재시작 뒤 parent 와 원래 프로그램이 남는지 확인하지 않았다(core 를 멈추지 않는다. 확인한 것은 부모 프로그램 종료와 `hc kill` 이다. 재시작 뒤 복구 셸은 13.11 대로 `lost` 다). not_found 를 문구로 가르므로 hc 가 문구를 바꾸면 다시 띄우지 않고 `launch_failed` 가 된다. 소유 탭이 없는 Run(`placement: none`)에 `--parent` 를 주면 pane 없는 자식이라 부모의 pane·탭 닫기에 함께 끝난다(herdr-team 관제는 늘 관제 탭에서 Run 을 가진다).
- 실환경은 herdr-team 11단계 실환경 확인(그 설계 15.2)에서 함께 본다. 사용자 hc core 는 멈추거나 다시 띄우지 않는다.

## 16. 0.5.0: Claude 상태 대리 보고와 백그라운드 일 (2026-11-17)

herdr-team 12단계(그 설계 1장 12단계 결정·확인한 것)가 찾은 일이다. Claude Code 는 시작 때 한 번 Herdr 에 상태 보고(OSC 7501)를 할 수 있는지 묻고, 2초 안에 답을 받지 못하면 그 세션 내내 보고하지 않는다. 그런 워커는 horch 에 늘 `no_status` 이고, observed idle·blocked 가 나지 않으며, 고정 터미널의 넣기 준비(`idle`·`done`, 13.4)도 통과하지 못한다. 또 워커가 오래 걸리는 시험을 백그라운드(Bash `run_in_background`)로 돌리고 턴을 마치면 hc 는 `idle`·`done` 이라 observed idle 이 나고, 감독은 멈춘 워커로 본다. Orca 는 자기가 깐 Claude 훅으로 상태를 받고, 백그라운드 일이 있으면 턴이 끝나도 작업 중으로 본다.

처음(2026-11-16)에는 이 대책을 herdr-team 훅·관제에 넣기로 했다. 그런데 SIN 프로젝트는 herdr-team 없이 horch 만 쓰고, 그 워커도 보고하지 않았으며, 감독은 horch 의 observed idle 에 기댄다(16.1). herdr-team 에 넣으면 SIN 에는 효과가 없다. 그래서 사용자 결정(2026-11-17)으로 핵심을 herdr-orch 0.5.0 에 둔다. 훅이 보고하지 않는 Claude 세션의 tty 에 7501 을 대신 쓴다(대리 보고). observed idle 은 그 턴을 끝낸 Stop 에 백그라운드 일이 있으면 내지 않는다(백그라운드 인식). herdr-team 0.7.2 는 그 위에서 메인 옵트인·메인 알림·쓰기 실패 처리만 한다(그 설계 8.14).

괄호 안의 "Codex 설계 리뷰 rN" 은 herdr-team 12단계 설계(그 설계 8.14 의 앞 판)의 리뷰 회차다. "Codex 계획 리뷰 rN" 과 "계획 Task 1 의 n" 은 herdr-team 12단계 계획(`docs/superpowers/plans/2026-11-16-herdr-team-p12.md`)의 리뷰 회차와 Task 1 "설계와 다르게 정한 것" 의 번호다. 거기서 정한 대리 보고 규칙을 그대로 옮겼다. 역할은 환경 변수로 정하므로(16.2) herdr-team 훅의 역할 판별을 대리 보고와 나눠 쓰던 문제(계획의 `ROLE`)는 없어졌다.

### 16.1 확인한 것

Claude 쪽 사실(시작 질의와 2초 창, 비차단 stdout, 7501 형식, 훅 사건, `background_tasks`)과 Herdr 쪽 사실(같은 질의 묶음에 바로 순서대로 답한다)의 근거는 herdr-team 설계 1장 "확인한 것 (12단계)" 에 있다. 여기에는 대리 보고가 기대는 것만 적는다.

| 확인한 것 | 근거 | 처리 |
|---|---|---|
| Claude 는 처음 raw 모드를 켤 때 한 번 7501 을 묻고, 2초 안에 답이 없으면 그 세션 내내 보고하지 않는다. 다시 묻게 하는 환경 변수가 없다. `CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1` 은 보고를 끈다 | Claude Code 2.1.325 실행 파일 | 훅으로 대신 쓴다. 시험은 그 변수로 미보고 세션을 만든다 |
| 보고 형식은 `ESC]7501;state=<상태>:app=claude-code[:kind=<종류>][:msg=<base64>]BEL` 이다(상태 idle·working·done·blocked·error, 종류는 blocked 일 때 permission·question·auth). 지우기는 `ESC]7501;state=clear BEL` | 실행 파일 | 같은 형식으로 쓴다(`msg` 는 쓰지 않는다) |
| hc API 에는 터미널 상태를 써넣는 메서드가 없다. 훅 프로세스는 제어 터미널이 없어 `/dev/tty` 를 열지 못한다. 조상 Claude 의 tty 장치(`ps -o tty=`)에 쓴 7501 은 hc 가 그 터미널의 보고로 받는다(보고를 끈 Claude 의 훅이 쓴 `state=idle` 로 `reported: true`) | `hc schema`, 시험 터미널 셋(herdr-team 12단계, 끝난 뒤 지웠다) | tty 장치에 쓴다 |
| `hc get` 에 `reported`, `status_ms`(마지막 상태가 바뀐 때. 보고한 적 없으면 null), `created_ms`, `foreground`(전경 프로세스의 pid) 가 있다 | `hc schema` | 판정과 대상 확인에 쓴다 |
| Stop 훅 입력에 `background_tasks`(`{id, type(shell·subagent·monitor·workflow), status, description, …}`, 없으면 빈 배열)가 있다. 백그라운드 일이 끝나면 Claude 가 시스템 턴을 시작한다(`UserPromptSubmit` 이 `source: system` 으로도 돈다) | 실행 파일의 훅 입력 스키마 | 백그라운드 인식(16.7) |
| SIN 프로젝트는 herdr-team 없이 horch 0.4.0 만 쓴다(자체 스크립트 `orchestration/bin/sin`, 2026-11-16 Orca 에서 옮겼다). 그 워커도 Herdr 에 보고하지 않았다(그 시각 워커 t1tb 의 `reported: false`). 감독은 horch 의 `observed idle` 메시지에 기댄다(`orchestration/runs/inbox.jsonl`) | SIN 프로젝트의 스크립트와 기록, `hc get`(읽기만) | 핵심을 herdr-orch 에 둔다 |
| herdr-orch 0.4.0 에는 훅이 없다. 두 플러그인은 사용자 전역으로 켜져 있다(사용자 Claude 설정 `enabledPlugins` 의 `herdr-orch@herdr-team`·`herdr-team@herdr-team`) | 사용자 Claude 설정 | herdr-orch 훅은 사용자의 모든 Claude 세션에 돈다. 대상이 아니면 셸 한 줄로 끝낸다(16.2) |
| launch-guard 는 워커 환경에 horch 홈을 넣지 않는다(0.3.0 의 `--env` 값만 넣는다) | `lib/horch/guard.py` | `HORCH_HOME` 을 넣는다(16.2) |

### 16.2 대상과 훅

새 파일:

```
herdr-orch/
  hooks/hooks.json       Claude 훅 등록. 명령마다 셸 거르기가 앞에 있다
  hooks/horch_hook.py    훅 진입점: 사건 이름을 받아 relay 를 부른다. 확인기 하위 명령 relay-check
  lib/horch/relay.py     세션 기록·판정·쓰기·확인기·빠른 길, Stop 기록, relay-status
```

대상은 Herdr 터미널 안(`$HC_TERMINAL_ID`)의 Claude 세션 가운데 다음 둘이다. 역할과 홈은 환경 변수로만 정한다(hc·DB 를 묻지 않는다).

| 환경 | 역할 | 홈 |
|---|---|---|
| `HORCH_HOME` 이 있다 | `worker`(horch 가 띄운 워커·리뷰어·고정 터미널 세션. 인수인계도 같은 세션이다) | `HORCH_HOME` |
| `HORCH_HOME` 은 없고 `HORCH_RELAY_HOME` 이 있다 | `main`(옵트인한 사람용 세션, 보통 감독 메인) | `HORCH_RELAY_HOME` |

- 둘 다 있으면 `HORCH_HOME` 이 앞선다. 메인 옵트인을 프로젝트 설정의 `env` 로 하면, 그 폴더에서 horch 가 띄운 워커 Claude 도 그 값을 받기 때문이다. 둘 다 없으면 대상이 아니다. 홈이 절대 경로가 아니면 대상이 아닌 것으로 본다.
- launch-guard(8장 가드)는 가드 등록 뒤 exec 직전에 `HORCH_HOME=<그 Run 의 홈 절대 경로>`(가드가 연 저장 루트)를 환경에 넣는다. Claude·Codex 모두다. Codex 는 14.3 과 같이 `-c shell_environment_policy.set.HORCH_HOME=<JSON 문자열>` 도 더한다(Codex 는 Claude 훅이 없어 지금은 대리 보고 대상이 아니다). Dispatch env(14.1)는 `HORCH_` 로 시작하는 이름을 받지 않으므로 겹치지 않는다. 0.4.0 까지 띄운 워커에는 이 값이 없어 대리 보고가 없다(16.12).
- 메인 옵트인: 사람이 보는 Claude 세션은 그 세션 환경에 `HORCH_RELAY_HOME=<홈 절대 경로>` 가 있으면 대리 보고를 받는다. 보통 프로젝트 `.claude/settings.local.json` 의 `{"env": {"HORCH_RELAY_HOME": "<홈>"}}` 로 넣는다(개인 절대 경로라 git 에서 뺀다). env 는 세션을 시작할 때 읽히므로 넣은 뒤 그 세션을 다시 연다. herdr-team 은 init·`up` 이 이 줄을 쓴다(그 설계 8.14). SIN 처럼 horch 만 쓰는 프로젝트는 같은 줄을 손으로 넣는다. `horch skill`(skill.md)과 README 에 적는다.
- `hooks.json` 의 명령은 모두 `[ -n "$HC_TERMINAL_ID" ] && [ -n "$HORCH_HOME$HORCH_RELAY_HOME" ] || exit 0; exec python3 "${CLAUDE_PLUGIN_ROOT}/hooks/horch_hook.py" <사건>` 꼴이다. 대상이 아닌 세션은 파이썬을 띄우지 않고 셸 한 줄로 끝난다(사용자의 모든 세션, 모든 사건에 돈다, 16.1). 시간 제한은 15초다.
- 사건: `SessionStart`(matcher `startup|resume|clear|compact`), `UserPromptSubmit`, `PreToolUse`(matcher `AskUserQuestion`), `PostToolUse`(matcher 없음, 모든 도구), `PostToolUseFailure`, `PermissionRequest`, `PermissionDenied`, `Elicitation`, `ElicitationResult`, `Stop`, `StopFailure`, `SessionEnd`. 그리고 훅이 분리 실행하는 확인기 `horch_hook.py relay-check <터미널> <pid> <started_ms>`(16.4)다. 확인기는 훅의 환경을 물려받아 같은 역할·홈을 쓴다.
- 훅은 아무것도 막지 않고 아무것도 출력하지 않는다(사건마다 exit 0, stdout 없음). 오류는 사건을 막지 않고 `relay.log` 에 남긴다(16.3).
- 다른 플러그인의 훅 판정은 모른다(Claude Code 는 같은 사건의 훅들을 함께 돌린다). 그래서 둘을 정한다. (1) 워커 역할의 `AskUserQuestion` 은 질문 목록(`blockers`)에 넣지 않는다. horch 워커의 질문은 `horch ask` 메일함으로 가고(8장 프리앰블), herdr-team guard 도 워커의 AskUserQuestion 을 거부한다. 거부된 도구에는 PostToolUse 가 오지 않아 넣으면 `blocked` 가 남는다(Codex 설계 리뷰 r4). 메인 역할만 넣는다. (2) 메인의 Stop 이 다른 플러그인 훅(herdr-team 의 평문 질문 검사·watch 막기·미보고 알림)에 막혀 턴이 이어져도 herdr-orch 는 모른다. 메인 Stop 은 `done` 을 쓰고, 이어지는 턴의 다음 사건이 `working` 을 다시 쓴다(잠깐 `done` 이 보일 수 있다, 16.12). herdr-team 계획의 "Stop 을 막으면 `working`"(계획 Task 1 의 4)은 같은 훅 안이라 할 수 있던 것이고 여기서는 하지 않는다.
- 서브에이전트의 사건(훅 입력에 `agent_id` 가 있다. 같은 Claude 프로세스·터미널이라 조상 검사로는 가르지 못한다)은 기록·판정·Stop 기록·쓰기 어디에도 쓰지 않는다. 메인이 AskUserQuestion 으로 기다리는 동안 백그라운드 서브에이전트의 도구가 끝나 `blocked` 를 `working` 으로 덮지 않게 한다(Codex 설계 리뷰 r2).
- `SessionStart(compact)` 는 맨 앞에서 거른다. 기록을 만들지도, 판정하지도, 쓰지도 않는다(판정 전 기록의 `pending` 도 그대로). 자동 compact 는 턴 중간에 돌고 그 뒤 일을 이어 가므로 `idle` 을 쓰면 horch 가 턴 끝으로 본다. 기록이 없을 때 만들면 확인기가 기본 `pending`(`idle`)을 턴 중간에 쓴다(Codex 설계 리뷰 r2, Codex 계획 리뷰 r1).

### 16.3 기록, 잠금, 로그

모두 홈 아래에 둔다(권한은 홈과 같은 0700). 파일 이름에 쓰기 전에 터미널 주소가 `[A-Za-z0-9_.:-]` 1–64자인지 본다(아니면 대상이 아니다).

- 세션 기록 `<홈>/relay/<터미널>.json`: `{terminal, pid, tty, started_ms, decided, pending, last, at, blockers, perm_tools, write_failures}`. 세션 하나가 아니라 Claude 프로세스 하나에 하나다(판정은 프로세스마다 정해진다. `/clear`·compact 는 세션 id 가 바뀌어도 같은 프로세스다). `decided` 는 null(판정 전)·`on`·`off`·`no_tty`·`write_failed` 다. `blockers` 는 아직 풀리지 않은 질문·승인 목록(`{키: 종류}`, 16.5)이다. `perm_tools` 는 승인 키의 도구 이름(`{키: tool_name}`)이다. 키가 해시라 "같은 `tool_name` 의 가장 오래된 `perm:`" 을 찾으려면 따로 둬야 한다(계획 Task 1 의 6). `at` 은 마지막 쓰기 시도 시각(ms)이다. herdr-team 판의 `notified` 는 두지 않는다(메인 알림 여부는 herdr-team 이 따로 둔다, 그 설계 8.14).
- Stop 기록 `<홈>/relay/<터미널>.stops.json`: `{stops: [...]}`(16.7).
- 잠금 `<홈>/relay/<터미널>.lock`(flock): 세션 기록·Stop 기록을 읽고 고치고 tty 에 쓰는 일은 이 잠금 안에서 한다. 한 턴의 도구 호출이 함께 끝나면 PostToolUse 훅이 여럿 함께 돈다(Codex 설계 리뷰 r1). hc 조회(`hc get`, 3초)와 `ps` 는 잠금 밖에서 먼저 한다. 잠금을 잡은 뒤 기록을 다시 읽어 그 사이 바뀌었으면(다른 훅이 먼저 판정했다) 그 값을 따른다. 그래서 잠금은 파일 읽기·쓰기와 짧은 tty 쓰기 동안만 쥔다. 기다림은 10초(`LOCK_WAIT_S`)와 훅 마감(16.6) 가운데 짧은 것까지다. 넘으면 그 사건은 건너뛰고 로그만 남긴다(잠금을 쥔 쪽이 hc 를 기다리지 않으므로 실제로는 생기지 않는다, Codex 설계 리뷰 r3).
- 파일 쓰기는 임시 파일과 rename 으로 원자적이다. 읽기만 하는 쪽(`observe_one`, `worker-list`, `relay-status`)은 잠금을 잡지 않는다.
- 로그 `<홈>/relay.log`: 줄마다 앞에 UTC 시각(`%Y-%m-%dT%H:%M:%SZ`)을 붙인다. 판정 `<시각> <터미널> <pid> on|off|no_tty`, 쓰기 실패 `<시각> <터미널> <pid> 쓰기 실패(<상태>): <오류>`, 전환 `… write_failed`, 다시 확인 `… off(다시 확인: <까닭>)`, 확인기의 전경 불일치 `… 확인기: 전경이 그 Claude 가 아니다(판정·쓰기 없음)`, 늦은 사건 `… 늦은 사건 버림(<사건>): 기록은 <pid> 의 것이다`, 마감 `… 훅 마감(<사건>): 이 사건은 대리 보고하지 않았다`, 훅 오류 `<시각> 오류(<사건>): <타입>: <메시지>`(계획 Task 1 의 12).

### 16.4 기록 만들기와 판정

1. 기록 만들기: 어느 사건에서든 기록이 없거나 기록의 `pid`·`started_ms` 가 지금 Claude 의 것이 아니면 새로 만든다(pid 가 같아도 시작 시각이 다르면 다른 프로세스다, Codex 설계 리뷰 r4). 지금 Claude 는 `hc get $HC_TERMINAL_ID`(3초)의 `foreground.pid` 이고, 그것이 이 훅 프로세스의 조상일 때만 인정한다(다른 터미널·프로세스에 쓰지 않는다).
   - 조상 확인은 훅 프로세스에서 위로 한 칸씩 `ps -o ppid= -o tty= -o lstart= -p <pid>` 로 한다. 프로세스 689개인 기계에서 `ps -A` 한 번은 83ms, `ps -p` 한 번은 4ms 였다. Claude 는 훅의 부모나 그 셸의 부모라 보통 한두 번이다. 같은 줄이 tty·시작 시각도 준다. 훅 프로세스 자신도 조상에 넣는다(계획 Task 1 의 1).
   - 새 기록: `pid`, `tty`(`/dev/<tty>`. `??` 나 실패면 null), `started_ms`(그 프로세스의 시작 시각 `lstart`, 초 단위. 훅이 늦게 돌아도 같다), `decided: null`, `pending: "idle"`, `last: null`, `write_failures: 0`. hc 가 실패하거나 조상이 아니면 만들지 않고 다음 사건에서 다시 한다.
   - 늦은 옛 훅 버리기: 잠금 안에서 다시 읽은 기록이 이 훅의 Claude(잠금 밖에서 확인한 pid·시작 시각)의 것이 아니고, 저장된 쪽 Claude 가 살아 있으면(ps 시작 시각이 같다) 이 사건은 늦게 끝난 옛 훅의 것이다. 세션 기록·Stop 기록·쓰기 모두 없이 로그만 남긴다. 저장된 쪽이 끝났거나 기록이 없을 때만 새로 만든다(Codex 계획 리뷰 r2).
   - 판정 전(`decided: null`) 기록을 새로 만들 때마다(SessionStart 든 다른 사건이든) 잠금을 놓은 뒤 확인기를 표준 입출력 없이 분리 실행한다. SessionStart 의 hc 가 실패한 뒤 다른 사건이 기록을 만들어도 확인기가 돈다(Codex 설계 리뷰 r2).
2. 판정: `decided` 가 null 이면 `started_ms` 에서 `DECIDE_S`(3초)가 지난 뒤에 본다. 3초는 Claude 시작 질의의 2초 창 뒤다. `hc get $HC_TERMINAL_ID`(3초)의 `status_ms` 가 `started_ms` 와 같거나 뒤면 `off` 다(그 세션은 스스로 보고한다). 아니면 `tty` 가 있으면 `on`, 없으면 `no_tty` 다. hc 가 실패하면 판정하지 않고 다음 곳에서 다시 본다. 이미 판정됐으면 그 값을 따른다. 판정은 `relay.log` 에 한 줄 남긴다. 판정하는 곳은 둘이다.
   - 3초가 지난 뒤의 훅 사건 가운데 `UserPromptSubmit` 이 아닌 것(`PreToolUse`·`PostToolUse`·`PermissionRequest`·`Stop` 등). `UserPromptSubmit` 은 그 턴의 Claude 보고보다 먼저 돌 수 있어 판정하지 않는다. 도구 호출(`PreToolUse`)은 턴이 시작된 뒤라, 스스로 보고하는 세션이면 그 턴의 `working` 이 이미 들어가 있다.
   - 확인기(`relay-check <터미널> <pid> <started_ms>`. 시작 시각으로 pid 재사용을 가린다, 계획 Task 1 의 7): 그 시각까지 잔 뒤 본다. 첫 질문이 답을 기다리는 동안에는 다음 훅 사건이 없으므로 확인기가 본다(Codex 설계 리뷰 r5). hc 가 실패하면 1초(`CHECK_EVERY_S`) 간격으로 다시 본다. 판정하거나, 확인기가 뜬 뒤 10초(`CHECK_BUDGET_S`)가 지나면 끝난다(기록이 Claude 시작보다 늦게 생겨도 한 번은 본다).
   - 확인기는 Claude 의 자손이 아니라 조상으로 확인할 수 없다. 그래서 판정에 쓴 바로 그 `hc get` 의 `foreground.pid` 가 기록의 pid 이고 그 pid 의 시작 시각(ps)이 `started_ms` 와 같을 때만 잠금을 잡는다. 아니면 판정도 쓰기도 없이 로그 한 줄을 남기고 끝난다(Codex 계획 리뷰 r1). 전경 확인부터 잠금까지 1초(`FOREGROUND_FRESH_S`)가 넘게 걸렸으면 잠금을 놓고 전경 확인부터 다시 한다(예산 안에서. 잠금도 예산 끝까지만 기다린다). 잠금 안에서는 기록이 아직 그 Claude 의 판정 전 기록이고 그 Claude 가 살아 있는지(ps 시작 시각) 다시 본 뒤에만 판정·쓰기를 한다(Codex 계획 리뷰 r2).
   - 확인기가 전경을 본 뒤 1초 안에 전경이 다른 프로그램으로 바뀌고 Claude 는 살아 있는 경우는 막지 않는다(Codex 계획 리뷰 r3, 고치지 않음). 전경 확인은 기록의 Claude 가 이 터미널의 프로그램인지, 곧 어느 터미널에 쓰는지를 정한다. 쓰는 곳은 그 Claude 의 tty 이고, Herdr 는 그 tty 로 들어온 7501 을 그 터미널의 보고로 받으므로 다른 터미널에는 쓰지 않는다.
   - 훅 경로는 전경을 다시 확인하지 않는다. 훅은 그 Claude 가 낸 사건으로 그 Claude 의 자손으로 돈다. 그래서 기록의 pid 가 훅의 조상이고 시작 시각이 같으면 그 Claude 가 살아 있고 이 사건의 주인이다(사건마다 다시 확인하면 on 세션의 도구 호출마다 `hc get` 이 하나 더 든다, 계획 Task 1 의 8).
3. 판정 전 사건은 쓰지 않는다. 그 사건이 뜻하는 상태(16.5 의 표)를 `pending` 에, 질문·승인은 `blockers` 에 적는다. `on` 으로 정하면 그 자리에서 쓸 상태를 쓴다(판정한 사건이 있으면 그 사건의 상태, 확인기면 `pending`. `blockers` 가 있으면 16.5 의 규칙대로 `blocked`). 그래서 시작 뒤 첫 질문·첫 긴 도구 호출도 판정 시각부터 보인다(Codex 설계 리뷰 r1).

### 16.5 쓰기

`decided = "on"` 일 때만 쓴다. 먼저 사건대로 `blockers` 를 고치고, 그다음 쓸 상태를 정한다. `blockers` 가 비지 않았으면 가장 최근 것의 `blocked`(kind 그대로), 비었으면 그 사건의 상태다. 그래서 같은 턴에 함께 돈 읽기 도구가 끝나도 아직 답하지 않은 질문의 `blocked` 를 덮지 않는다(AskUserQuestion 은 다른 도구와 함께 돌 수 있다, Codex 설계 리뷰 r3). 쓸 상태가 `last` 와 같으면 쓰지 않는다(`clear` 는 늘 쓴다).

| 훅 사건 | `blockers` | 사건의 상태 |
|---|---|---|
| `UserPromptSubmit`(사용자·시스템 턴 모두) | 비운다(새 턴) | `working` |
| `PreToolUse`(AskUserQuestion) | 메인 역할만 더한다: 키 `tool:<tool_use_id>`(없으면 `tool:<tool_input 해시 16자>`, 계획 Task 1 의 14), 종류 `question`. 워커 역할은 더하지 않는다(16.2) | 메인 (`blocked`), 워커 `working` |
| `PermissionRequest` | 더한다: 키 `perm:<tool_name 과 tool_input 의 해시>`, 종류 `permission`(이 사건에는 `tool_use_id` 가 없다). `perm_tools` 에 도구 이름 | (`blocked`) |
| `PermissionDenied`(auto 모드의 거절에만 온다) | 같은 해시의 `perm:` 을 뺀다 | `working` |
| `Elicitation` | 더한다: 키 `elic:<mcp_server_name>:<elicitation_id, 없으면 message 의 해시>`, 종류 `question` | (`blocked`) |
| `ElicitationResult` | 같은 키를 뺀다(`elicitation_id` 가 없으면 그 서버의 가장 오래된 것) | `working` |
| `PostToolUse`·`PostToolUseFailure`(모든 도구) | `tool:<tool_use_id>` 와 같은 해시의 `perm:` 을 뺀다. 같은 해시가 없으면 같은 `tool_name` 의 가장 오래된 `perm:` 을 뺀다(다른 플러그인의 PermissionRequest 훅이 `updatedInput` 으로 입력을 바꾸면 해시가 달라진다, Codex 설계 리뷰 r4) | `working` |
| `Stop` | 비운다(턴이 끝났다) | 메인은 `done`. 워커는 `background_tasks` 가 비지 않으면 `working`, 비면 `done`(Codex 설계 리뷰 r1) |
| `StopFailure` | 비운다 | `error` |
| `SessionStart`(`startup`·`resume`) | 비운다 | `idle`(계획 Task 1 의 5) |
| `SessionStart`(같은 프로세스의 `clear`) | 비운다 | `working` 뒤 곧바로 `idle`(한 번의 쓰기에 둘). `terminal-reset` 의 비우기 확인은 turn 이 오르고 `idle` 인 것을 기다린다(13.8). turn 은 상태가 `working` 을 벗어날 때 오르므로 둘을 쓴다(Codex 설계 리뷰 r1) |
| `SessionStart`(`compact`) | 그대로 | 맨 앞에서 거른다(16.2) |
| `SessionEnd` | 비운다 | `clear`(셸 터미널의 메인이 끝난 뒤 옛 상태가 남지 않게) |

권한 승인과 사람의 거절을 알리는 훅 사건은 없다(`PermissionDenied` 는 auto 모드의 거절에만 온다). 승인하면 그 도구가 끝나 PostToolUse 가 올 때까지, 사람이 거절하면 그 턴이 끝나는(Stop) 때까지 `blocked` 가 남는다(16.12. Codex 설계 리뷰 r3·r4).

- 형식은 Claude 와 같다: `ESC]7501;state=<상태>:app=claude-code[:kind=<종류>]BEL`. `msg`·`title` 은 쓰지 않는다. `os.open(tty, O_WRONLY | O_NOCTTY | O_NONBLOCK)` 로 열어 한 번의 `os.write` 로 쓰고 닫는다.
- 쓰기 전 저장: 쓰기 전에 기록(판정·`blockers`·`pending` 과 쓰기 시도 시각 `at`)을 먼저 저장한다. 저장이 실패하면 tty 에 쓰지 않는다(오류는 로그, 다음 사건이 다시 한다). 처음 `on` 으로 정한 쓰기를 저장하지 못하면, 다음 사건이 자기 쓰기를 Claude 의 보고로 보고 `off` 로 굳기 때문이다(Codex 계획 리뷰 r1). `at` 은 시도 시각이라 쓴 뒤의 저장(`last`)이 실패해도 Stop 의 다시 확인이 자기 쓰기를 Claude 의 보고로 보지 않는다(다음 사건이 같은 상태를 한 번 더 쓴다, 계획 Task 1 의 9).
- 쓴 뒤 `last` 를 고치고 `write_failures` 를 0 으로 둔다. 쓰기가 실패하면(EAGAIN 포함) 같은 사건 안에서 0.1초(`WRITE_PAUSE_S`) 간격으로 두 번(`WRITE_RETRIES`) 더 해 본다(덜 쓴 바이트는 나머지만 쓴다). 그래도 실패하면 사건을 막지 않고 `write_failures` 를 올리며 로그에 남긴다. 턴의 마지막 사건(`Stop`·`StopFailure`·`SessionEnd`)이나 `blocked` 를 쓰려던 사건이 실패했거나, 실패가 세 번(`FAIL_LIMIT`) 이어지면 `decided = "write_failed"` 로 두고 그 뒤 쓰지 않는다. 뒤에 사건이 없어 다시 해 볼 기회가 없고, hc 에는 앞 상태가 남는다(Codex 설계 리뷰 r1·r3). 알리기는 16.8 이다.
- 예외 보완(`_give_up`): 두 경우에 한 번 한다. 턴의 마지막 사건이나 `blocked` 를 쓰려던 사건이 tty 쓰기 전에 예외로 끝났을 때(기록 읽기·hc 조회 등, Codex 설계 리뷰 r4), 그리고 쓰기 실패로 정한 `write_failed` 를 담은 마지막 저장이 실패했을 때다(Codex 계획 리뷰 r3). 잠금 안에서 다시 읽은 기록이 그 훅이 처음 확인한 Claude(pid·`started_ms`)의 것이고 `on` 일 때만 `write_failed` 로 바꾼다. 그 사이 새 Claude 가 만든 기록은 바꾸지 않는다(Codex 계획 리뷰 r3). 판정 전 기록도 바꾸지 않는다(확인기나 다음 사건이 다시 판정한다). 잠금 대기 초과는 로그만 남긴다(계획 Task 1 의 13).
- `Stop` 에서는 같은 잠금 안에서 Stop 기록(16.7)을 먼저 남기고 그다음 tty 에 쓴다. 대리 보고 세션의 idle 은 이 tty 쓰기로 생기므로, horch 가 그 idle 을 볼 때는 그 Stop 의 기록이 이미 있다(같은 turn 의 앞 기록을 고르지 않는다, Codex 설계 리뷰 r5). 두 일의 오류는 따로 잡아, Stop 기록 쓰기가 실패해도 tty 쓰기는 한다(Codex 설계 리뷰 r4).

### 16.6 다시 확인, 빠른 길, 마감

- 다시 확인: `on` 인 세션은 `Stop` 마다 쓰기 전에 `hc get`(3초)을 본다. 상태 기록에 `msg`·`title` 이 있으면 Claude 가 스스로 보고하는 것이다(대리 보고는 이 둘을 쓰지 않는다. Claude 는 일하는 중 보고에 지금 하는 일을 `msg` 로 붙인다). `status_ms` 가 마지막 쓰기 시도(`at`)보다 1초(`REVERIFY_SLACK_MS`) 넘게 뒤이고 그 상태가 `last` 와 달라도 그렇다(판정 때 시작 확인 창이 떠 있어 아직 보고 전이었던 경우 등). 그러면 `decided = "off"` 로 바꾸고 쓰지 않는다. hc 가 실패하면 그대로 쓴다.
- 빠른 길: `decided` 가 `off`·`no_tty`·`write_failed` 이고, 기록의 pid 가 이 훅의 조상이며 그 시작 시각이 `started_ms` 와 같으면, 기록 파일 하나와 ps 몇 번으로 끝낸다(잠금·hc 없음). 워커 역할의 Stop 은 Stop 기록을 남겨야 하므로 빼고, 나머지 모든 사건에 쓴다(계획 Task 1 의 2). 조상이 아니면(Claude 가 바뀌었다) 느린 길로 가서 기록을 다시 만든다(Codex 설계 리뷰 r3). `horch_hook.py` 는 빠른 길을 `relay`·`paths` 만 가져와 본다(DB·hc 모듈을 가져오기 전에).
- 지연: herdr-team 12단계 계획에서 잰 훅 한 번의 중앙값은 off 세션 약 0.10초(파이썬 시작만 0.03초), on 세션 약 0.19초였다(계획 Task 1 의 3). horch 훅도 이 크기를 넘지 않게 하고, 시험의 상한은 1초다. 대상이 아닌 세션은 셸 거르기로 파이썬을 띄우지 않는다(16.2).
- 마감: 훅 시작 + 12초(`HOOK_DEADLINE_S`. hooks.json 의 15초 제한 안)다. 남은 시간이 hc 한 번(`HC_TIMEOUT` 3초)보다 적으면 hc 를 부르지 않는다(hc 실패와 같다). 잠금도 마감까지만 기다린다. ps 한 번의 시간 상한은 `min(PS_TIMEOUT 3초, 남은 시간)` 이고 시간 초과는 실패와 같다. 남은 시간이 없으면 그 사건의 대리 보고를 건너뛰고 로그를 남긴다. 빠른 길도 같은 마감을 받고, 마감이 지났으면 할 일이 없는 것으로 본다(Codex 계획 리뷰 r1·r3, 계획 Task 1 의 10).
- 차례: 기록 읽기 → 빠른 길 → 잠금 밖 hc 조회(새 기록·Stop·판정할 때만) → 잠금 → 기록 다시 읽기(늦은 사건 버리기) → (워커 Stop) Stop 기록 → `blockers`·`pending` → 판정 → (`on` 이고 Stop) 다시 확인 → 쓰기 전 저장 → 쓰기 → 저장.

### 16.7 Stop 기록과 idle 넘기기

Stop 기록: 워커 역할의 `Stop` 은 `decided` 와 상관없이(스스로 보고하는 세션도) 대리 쓰기 전에 `hc get`(3초)으로 지금 `turn` 과 상태를 읽어, 그 턴 끝의 idle 사건이 가질 turn 을 정한다. 상태가 `working` 이면 `turn + 1`, 아니면 `turn` 이다(turn 은 상태가 `working` 을 벗어날 때 오른다). 그리고 `<홈>/relay/<터미널>.stops.json` 의 `stops` 끝에 `{pid, turn, at, background: [{type, status, description 80자}]}` 를 더한다. `background` 는 `background_tasks` 를 줄인 것이고 없으면 빈 목록이다. 최근 20개(`STOPS_KEEP`)만 남긴다. `at` 은 horch 의 시각 문자열(`ids.now`)이다. hc 가 실패하면(마감으로 부르지 않은 것 포함) `turn: null` 이다. 메인 역할은 남기지 않는다(observed 대상이 아니다).

idle 넘기기(`liveness.observe_one`, 9장 observed): idle 사건(key 는 turn)을 쓰기 전에 그 Dispatch 터미널의 Stop 기록에서 고른다. `turn` 이 그 idle 의 turn 과 같고 `at` 이 그 Dispatch 의 `created_at` 과 같거나 뒤인 것 가운데 마지막 것이다(고정 터미널은 Dispatch 가 바뀌어도 turn 이 이어지므로 앞 Dispatch 의 기록을 거른다. `--terminal` 넣기도 새 Dispatch 다). 메시지 시각은 hc 조회 뒤 DB 에 쓴 시각이라 턴을 가리키지 못하므로 turn 으로 고른다(Codex 설계 리뷰 r2). 그 기록의 `background` 가 비지 않았으면 그 turn 의 idle 을 내지 않는다(observations 에 넣지 않고 메시지도 쓰지 않는다). Orca 가 백그라운드 일이 있으면 작업 중으로 두는 것과 같은 자리다. 기록이 없거나 읽지 못하거나 비었으면 지금처럼 낸다.

- 대리 보고 세션은 백그라운드가 있는 Stop 을 `working` 으로 써 turn 이 오르지 않으므로 idle 자체가 나지 않는다. 백그라운드 일이 끝나면 Claude 가 시스템 턴을 시작하고, 그 턴의 Stop 이 같은 turn 의 기록을 하나 더 남긴다. 그 turn 의 idle 은 마지막 Stop 뒤에 한 번 나므로 마지막 기록이 맞다(Codex 설계 리뷰 r4).
- 스스로 보고하는 세션은 Stop 에 `idle`·`done` 을 보고해 turn 이 오른다. 그 turn 의 Stop 기록에 백그라운드가 있으면 넘긴다. 백그라운드 일이 끝난 뒤의 시스템 턴은 새 turn 이라 지금처럼 센다.
- 넘긴 turn 은 observations 에 넣지 않으므로 다음 판정이 다시 본다. 같은 기록이면 다시 넘긴다. 같은 turn 의 마지막 기록이 빈 목록으로 바뀌면 그때 낸다.
- `worker-list`·`worker-show` 의 `attention: "idle"` 도 같은 기준으로 내지 않는다(그 행은 attention 이 없다). observed 와 목록이 어긋나지 않게 같은 판정 함수를 쓴다.
- 감독은 따로 할 일이 없다. herdr-team 관제(그 설계 8.6)와 SIN 감독 모두 백그라운드 시험 중에 idle 을 받지 않는다.

### 16.8 쓰기 실패 알리기와 `relay-status`

대리 보고가 첫 쓰기 뒤 실패하면(`write_failed`) hc 에는 마지막 대리 상태(보통 `working`)가 남아 `no_status` 로도 잡히지 않는다(Codex 설계 리뷰 r2). 리뷰어·고정 터미널·인수인계 세션도 같다(Codex 설계 리뷰 r5). 그래서 두 가지를 더한다.

- `worker-list`·`worker-show` 의 `attention` 에 `relay_failed` 를 더한다. 조건은 `active` 이고 판정 `live` 이고 그 Dispatch 터미널의 세션 기록이 `decided: "write_failed"` 인 것이다. 차례는 `exited`·`lost`·`unverifiable` 다음, `blocked`·`error`·`idle`·`no_status` 앞이다(hc 상태가 옛것이라 그 낱말을 믿을 수 없다). `next` 는 `worker-show --dispatch D --lines 40` 이다. 감독이 화면을 보고 이어 가게 하거나, 사용자에게 그 탭을 보게 하거나, `worker-abandon --kill` 뒤 다시 띄운다. horch 는 스스로 아무것도 하지 않는다. herdr-team 관제가 하는 일은 그 설계 8.14 다.
- `horch relay-status --terminal <t>`: 그 터미널의 세션 기록을 JSON 으로 준다. 결과 `{terminal, relay}` 이고 `relay` 는 기록 파일의 내용 그대로다(없거나 읽지 못하면 null). `--terminal` 형식은 16.3 과 같고 틀리면 exit 2 `usage` 다. 읽기 명령이라 누구나 부른다(Run 이 없어도 된다). herdr-team 의 메인 알림·`main_unreported`, 맡은 일 없는 고정 터미널의 판정(그 설계 8.14, 5.9.9)이 쓴다.

### 16.9 명령·문서 정리

7장 명령 표에 더하는 것:

| 명령 | 인자 | 결과 |
|---|---|---|
| `relay-status` | `--terminal` | `{terminal, relay}`(16.8) |

- 6장 권한 표: `relay-status` 는 누구나다(`status` 와 같다).
- `worker-list`·`worker-show` 의 `attention` 값에 `relay_failed` 를 더한다(16.8). `idle` 은 백그라운드 일을 기다리는 turn 에 나오지 않는다(16.7). 행의 다른 필드는 그대로다.
- 10장 상황별 처리에 한 줄을 더한다: "워커의 대리 보고 쓰기 실패: `attention: relay_failed`. 화면을 보고 사용자에게 알리거나 abandon 뒤 다시 띄운다."
- `horch skill`(skill.md)에 짧게 적는다: Claude 워커의 상태는 보고하지 않아도 훅이 대신 보낸다. 백그라운드 일을 기다리는 워커에는 observed idle 이 나지 않는다. `relay_failed` 를 보면 화면을 보고 사용자에게 알린다. 감독 메인의 Needs you 를 받으려면 `HORCH_RELAY_HOME` 줄을 넣고 세션을 다시 연다(16.2). README 도 같다.
- 스키마·exit 코드·오류 code 는 그대로다.

### 16.10 보안

- 훅은 자기 세션의 Claude 가 도는 터미널의 tty 에만, Claude 와 같은 형식의 상태 글(OSC 7501)만 쓴다. 어느 터미널인지는 기록을 만들 때 그 터미널의 전경 프로세스이고 훅의 조상인 Claude 로 정하고, 쓰기 전에는 그 Claude 가 살아 있는지(pid·시작 시각) 본다. 쓰는 사이 같은 터미널에서 Claude 가 잠깐 백그라운드로 가 다른 프로그램이 전경이어도, 같은 터미널의 화면 출력이라 그 프로그램의 입력을 건드리지 않는다(Codex 계획 리뷰 r3). 다른 터미널·사용자 입력에는 쓰지 않는다. 쓰는 글에 워커 글을 넣지 않는다(`msg` 를 쓰지 않는다).
- 훅은 사용자의 모든 Claude 세션에 등록된다(전역 플러그인). 대상이 아닌 세션에서는 셸 한 줄 밖에 하지 않는다. 대상 세션에서도 도구 입력 원문은 저장하지 않는다(해시와 도구 이름, `background_tasks` 의 종류·상태·설명 80자만 남긴다).
- `HORCH_HOME`·`HORCH_RELAY_HOME` 은 환경 변수로 받는 경로다. 그 아래 `relay/` 에 기록을 만들 뿐, 다른 파일을 읽거나 실행하지 않는다. 이것은 보안 경계가 아니다(6장).

### 16.11 테스트

Herdr·Claude 를 부르지 않는다. 가짜 hc(`tests/fakes/hc`)의 `get` 에 `status_ms`·`reported`·`created_ms`·`foreground.pid` 를 더한다(터미널 기록의 키를 그대로 넘긴다). tty 는 시험이 만든 pty 쌍(`os.openpty`)의 slave 경로를 쓰고 master 에서 읽는다. 판정 대기 3초는 시험 환경 변수 `HORCH_TEST_RELAY_DECIDE_S` 로 줄인다.

- 셸 거르기(`test_hooks`): `HC_TERMINAL_ID` 가 없거나 두 홈 변수가 모두 없으면 hooks.json 의 명령이 파이썬을 띄우지 않고 exit 0 이다(PATH 앞에 둔 가짜 python3 가 불리지 않는다). hooks.json 의 사건 목록과 matcher.
- 역할(`test_relay`): `HORCH_HOME` 이면 worker, `HORCH_RELAY_HOME` 만 있으면 main, 둘 다 있으면 worker(`HORCH_HOME` 의 홈). 상대 경로 홈은 대상이 아니다.
- 기록: 어느 사건에서든 기록이 없거나 pid·시작 시각이 다르면 `foreground.pid` 가 훅의 조상일 때만 `<홈>/relay/<터미널>.json` 을 만든다. 같은 pid·시작 시각이면 그대로다(`/clear`). 조상이 아니거나 hc 가 실패하면 만들지 않는다. 판정 전 기록을 새로 만들 때마다 확인기를 분리 실행한다(표준 입출력 없음). 잠금 안에서 살아 있는 다른 Claude 의 기록을 보면 그 사건을 버린다(로그 한 줄). `agent_id` 가 있는 사건과 `SessionStart(compact)` 는 아무것도 하지 않는다.
- 판정: 3초 전과 `UserPromptSubmit` 에서는 판정하지 않고 `pending` 만 고친다. 확인기와 그 뒤의 `PreToolUse`·`PostToolUse`·`Stop` 등에서 `status_ms ≥ started_ms` 면 `off`, null 이거나 앞이면 tty 가 있으면 `on`, 없으면 `no_tty` 다. `on` 으로 정한 자리에서 `pending`(메인의 첫 AskUserQuestion 이면 `blocked`·`question`)을 쓴다. hc 가 실패하면 판정하지 않는다. 두 훅이 함께 판정해도(스레드 둘) 결과가 하나이고 `off` 로 덮이지 않는다. 확인기는 hc 가 처음 실패해도 10초 안에 다시 보고 판정한다(첫 AskUserQuestion 뒤 다른 사건이 없어도 `blocked` 가 써진다). 확인기의 `foreground.pid` 나 시작 시각이 다르면 판정·쓰기가 없다. 전경 확인부터 잠금까지 1초가 넘으면 전경을 다시 본다.
- 쓰기(pty master 에서 읽는다): 사건 표대로 정확한 바이트를 쓴다(`ESC]7501;state=working:app=claude-code BEL`, 메인 AskUserQuestion 의 `kind=question`, PermissionRequest 의 `kind=permission` 등). 워커의 AskUserQuestion 은 `blockers` 에 들지 않는다. 메인 Stop 은 늘 `done`, 워커 Stop 은 `background_tasks` 가 비었으면 `done`, 아니면 `working` 이다. `startup`·`resume` 은 `idle`, 같은 pid 의 `clear` 는 `working` 다음 `idle`, `SessionEnd` 는 `state=clear`, `StopFailure` 는 `error` 다. `last` 와 같은 상태는 쓰지 않는다. AskUserQuestion 과 Read 가 함께 돌 때 Read 의 PostToolUse 가 `blocked` 를 덮지 않는다. PermissionRequest 뒤 같은 도구의 PostToolUse·PermissionDenied 가 푼다. 입력 해시가 달라도 같은 `tool_name` 의 가장 오래된 `perm:` 이 빠진다. Elicitation 은 ElicitationResult 가 푼다. Stop·UserPromptSubmit 이 `blockers` 를 비운다. 쓰기 전 저장이 실패하면 쓰지 않는다. 쓰기 실패(닫힌 slave)는 두 번 더 해 본 뒤 `write_failures` 를 올린다. 세 번 이어지거나 Stop·StopFailure·SessionEnd·`blocked` 쓰기가 실패하면 `write_failed` 다. tty 쓰기 전 예외도 `write_failed` 다(`_give_up`, 그 Claude 의 `on` 기록만). `off`·`no_tty`·`write_failed` 는 아무것도 쓰지 않는다. 잠금은 hc 조회 동안 쥐지 않는다(가짜 hc 를 느리게 해도 다른 훅이 잠금을 기다리지 않는다). 다시 확인: `on` 세션의 Stop 에서 가짜 hc 상태에 `msg` 가 있거나, `status_ms` 가 마지막 쓰기보다 1초 넘게 뒤이고 상태가 다르면 `off` 로 바뀌고 쓰지 않는다. 마감: 남은 시간이 3초보다 적으면 hc 를 부르지 않는다.
- 빠른 길: `off` 세션의 PostToolUse 한 번이 hc 를 부르지 않고 잠금을 잡지 않으며 1초 안에 끝난다. 기록 pid 가 조상이 아니면 기록을 다시 만든다.
- Stop 기록: 워커 Stop 이 `stops.json` 의 끝에 `turn`(가짜 hc 상태가 working 이면 turn+1, 아니면 turn, hc 실패면 null)과 `background`(빈 목록 포함, description 80자, 20개까지)를 더한다. tty 쓰기 앞이다. 기록 쓰기가 실패해도 tty 쓰기는 한다. 메인 Stop 은 남기지 않는다.
- launch-guard(`test_guard`): exec 한 프로세스의 환경에 `HORCH_HOME`(홈 절대 경로)이 있다. Codex argv 에 `-c shell_environment_policy.set.HORCH_HOME=…` 가 있다. `--env` 값과 함께 된다.
- idle 넘기기(`test_liveness`·`test_check`): idle turn 과 같은 turn 이고 Dispatch `created_at` 뒤인 마지막 Stop 기록의 `background` 가 비지 않으면 observed idle 이 없고 observations 에도 들지 않는다. 기록이 없거나 비었거나 Dispatch 앞이면 지금처럼 낸다. 같은 turn 에 기록이 둘이면(대리 보고 세션의 백그라운드 Stop 뒤 빈 Stop) 마지막 것을 쓴다. 넘긴 뒤 같은 turn 에 빈 기록이 더해지면 다음 판정이 idle 을 낸다. `worker-list` 의 `attention` 도 같다.
- `relay_failed`(`test_workers`): 세션 기록이 `write_failed` 인 live `active` Dispatch 의 `attention` 이 `relay_failed` 이고 `next` 가 `worker-show --lines 40` 이다. `exited`·`lost` 가 앞선다. `on`·`off`·`no_tty` 는 지금 attention 그대로다.
- `relay-status`(`test_cli`): 기록이 있으면 그 내용, 없거나 깨졌으면 `relay: null`, 형식이 틀린 터미널은 exit 2. Run 없이 부를 수 있다.
- 버전(`test_meta`): 세 곳이 0.5.0.

### 16.12 버전·한계

- 버전 세 곳(`paths.VERSION`, `herdr-orch/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`)을 0.5.0 으로 맞춘다. DB 스키마는 그대로다(v4. 대리 보고 기록은 파일이다). herdr-team 의 `HORCH_MIN` 은 0.5.0 이 된다(herdr-team 0.7.2).
- 실환경은 herdr-team 12단계 실환경 확인(그 설계 15.2)에서 함께 본다. horch 만 쓰는 Run 으로 하는 확인은 선택이다. 사용자 hc core 는 멈추거나 다시 띄우지 않는다.
- 한계:
  - 근본 원인은 Claude Code 의 한 번만 묻는 시작 질의다. 대리 보고는 그 세션의 보고를 대신할 뿐 Claude 를 고치지 않는다. 상위(Claude Code)에 "시작 질의 실패 뒤 다시 묻기" 를 요청할 수 있다.
  - 대리 보고는 훅 사건과 확인기가 있을 때만 쓴다. 판정 전(프로세스 시작 뒤 3초)에는 상태가 없다. 확인기는 10초 안에서 다시 본다. 그동안 hc 가 계속 실패하거나 확인기가 돌지 못하면 다음 비-`UserPromptSubmit` 사건까지 늦어진다(첫 질문이 답을 기다리는 동안이면 답한 뒤다). 다시 확인은 Stop 에서만 하고 `msg`·`title` 이나 대리 쓰기와 다른 상태 변화가 보여야 끈다. 그래서 늦게 스스로 보고를 시작한 세션은 그것이 보일 때까지 두 쪽이 함께 쓴다(같은 사건에 같은 낱말이라 대부분 해가 없다). 한 턴 안의 긴 생각(도구 없이)은 그 턴 시작의 `working` 이 이어진다. 사용자가 Esc 로 턴을 끊으면 Stop 훅이 돌지 않을 수 있어 `working` 이 남는다(다음 사건이 고친다). 셸 터미널의 메인이 비정상으로 끝나면 `SessionEnd` 가 돌지 않아 옛 상태가 남는다(다음 세션이 판정 뒤 고친다).
  - 훅이 tty 에 쓰는 순간 Claude 가 화면을 쓰는 중이면 Claude 의 제어 순서 중간에 끼어 그 프레임 일부가 잠깐 깨질 수 있다(다음 그리기가 고친다). 대리 보고가 켜진 세션에서만 쓰고 한 사건에 짧은 쓰기 한 번이다.
  - 셸 터미널(메인)에서 앞 Claude 가 남긴 상태와 새 세션의 첫 보고가 같은 낱말이면 `status_ms` 가 바뀌지 않아, 보고하는 세션을 대리 보고로 잘못 판정할 수 있다(두 쪽이 함께 쓴다). 앞 Claude 가 정상으로 끝나면 `state=clear` 를 쓰므로 드물다.
  - 권한 승인과 사람의 거절을 알리는 훅 사건이 없다. 대리 보고 세션에서 사용자가 권한 창을 승인하면 그 도구가 끝날 때까지, 거절하면 그 턴이 끝날 때까지 `blocked`(Needs you)가 남는다. 워커는 보통 권한 우회로 돌아 권한 창이 없다.
  - 다른 플러그인의 훅 판정을 모른다(16.2). 메인 Stop 이 다른 훅에 막혀 턴이 이어지면 다음 사건까지 잠깐 `done` 이 보인다. herdr-team 없이 horch 만 쓰는 워커가 AskUserQuestion 으로 사람을 기다리면 `blocked` 가 아니라 `working` 이다(horch 워커는 `horch ask` 로 묻는다, 8장 프리앰블).
  - 0.5.0 전에 띄운 워커(`HORCH_HOME` 없음), 옵트인하지 않았거나 옵트인 전에 연 메인, 훅도 돌지 않는 세션(시작 확인 창, 훅 오류)은 대리 보고가 없다. 그런 워커는 지금의 `no_status` 다.
  - 워커 셸이 그 안에서 다른 Claude(`claude -p` 등)를 띄우면 그 Claude 도 `HORCH_HOME`·`HC_TERMINAL_ID` 를 물려받는다. 그 훅은 터미널 Claude 의 자손에서 돌아 조상 확인을 통과하므로 같은 기록에 쓴다(안쪽 Claude 의 Stop 이 `done` 을 쓰는 등). herdr-team 판에도 있던 한계다(`HC_TERMINAL_ID` 를 물려받는다).
  - Codex 는 Claude 훅이 없어 대리 보고·백그라운드 인식이 없다(`HORCH_HOME` 만 받는다). Codex 가 같은 시작 질의 문제를 가지는지 확인하지 않았다.
  - 백그라운드 인식은 Claude 가 `background_tasks` 에 넣는 일만 본다(Bash `run_in_background`, 백그라운드 서브에이전트, 모니터 등). `nohup …&` 처럼 Claude 밖에서 띄운 프로세스는 모른다. 백그라운드 일이 끝나지 않고 매달리면 그 워커는 observed idle 없이 기다린다(감독이 따로 시간 상한을 둔다. herdr-team 은 시험의 `timeout_min`).
  - 스스로 보고하는 세션은 Claude 의 `idle`·`done` 보고와 Stop 훅의 기록 사이에 순서가 없다. observed 판정(5초 간격)이 그 사이에 들면 기록이 없어 idle 을 낸다. 대리 보고 세션은 기록을 남긴 뒤에 쓰므로 이 일이 없다.
  - 메일 깨우기(9장)는 상태가 `working`·모름이면 건너뛴다. 대리 보고로 상태가 보이면 지금 동작으로 충분하다고 보고, Orca 같은 다시 전달은 넣지 않았다.
  - 세션 기록 파일이 지워지거나 손상되면, 그 세션의 다음 사건이 기록을 새로 만들며 앞선 대리 쓰기의 `status_ms` 를 Claude 의 보고로 보고 `off` 로 정할 수 있다. 그 뒤 그 세션은 대리 보고가 없다(다시 열면 풀린다. 홈은 horch 만 쓰고 쓰기는 원자적이라 기록만 한다, Codex 계획 리뷰 r3).
  - `HORCH_RELAY_HOME` 을 프로젝트 설정으로 넣으면 그 폴더에서 연 다른 사람용 Claude 세션도 메인 역할로 대리 보고를 받는다(터미널마다 기록이 따로라 서로 섞이지 않는다).

## 17. 범위 밖

gate, 태스크 의존성(DAG), 그룹 주소(`@all` 등), 중첩 워커, 원격 머신(`--on`), heartbeat, Codex·Claude 외 에이전트, 메시지 종류별 대기 필터, `pane.split` 대체 배치, 소유자 실행(herdr-team 이 관제를 띄운다), 팀 보드 Herdr 모드. 0.2.0 에서 "같은 터미널 재사용" 은 고정 터미널로 범위 안이 됐다(13장). 0.2.0 도 범위 밖: hc core 재시작 뒤 고정 터미널 복구 확인(실험 X7 을 하지 않았다), 입력 유실의 자동 재전송(호출자가 정한다), 비우기의 화면 확인. 0.4.0 도 범위 밖: 떠 있는 터미널의 parent 바꾸기(hc 에 없다), parent 저장과 재시도 안내의 parent, 띄우기 전 부모 생존 확인. 0.5.0 도 범위 밖: Codex 의 대리 보고·백그라운드 인식, 보고하지 않는 세션을 다시 띄우는 자동 복구와 Claude 디버그 계측(대리 보고로 바꿨다), 메일 다시 전달(Orca 의 `parkRedelivery`), 다른 플러그인 훅의 판정 알기, `relay_failed` 의 자동 처리(감독이 정한다), Claude Code 자체 수정(상위에 요청할 일).
