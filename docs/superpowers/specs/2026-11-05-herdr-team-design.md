# herdr-team 설계

작성 2026-11-05. 상태: 설계 확정 전(Codex 교차 검증과 사용자 검토 대기).

## 1. 목적과 범위

herdr-team 은 Herdr(herdr-app 창 + herdr-core `hc`) 위에서 직무 팀으로 소프트웨어를 만드는 Claude Code 플러그인이다. 사용자는 메인 세션과 대화하고, 코디네이터가 일을 나눠 직무 워커(기획·디자인 디렉터·디자인·개발·테스트)를 팀 탭의 pane 으로 띄운다. 워커의 결과는 반대쪽 모델(Claude ↔ Codex)이 리뷰한다.

- 실행·메일함·생존 판정은 herdr-orch(`horch`, 이 저장소의 다른 플러그인)를 쓴다. herdr-team 은 그 위의 팀 계층이다.
- orca-team(`setup-with-orca` 저장소, 0.4.1)의 개념을 옮긴다. 코드는 가져다 쓰지 않는다(의존 없음). 개념 대응은 부록 A.
- 범위: orca-team 0.4.1 의 기능 전부(3계층, 직무·모델 설정, 태스크 그래프와 병렬 시작, owns 잠금, 교차 리뷰와 수정 라운드, 기획 인터뷰, 사용자 승인 직무와 디자인 일괄 승인, 디자인 디렉터, 이미지 생성, AI 티 금지 목록과 자동 검사). 구현은 세 단계로 나눈다(15장).

### 사용자 결정 (2026-11-05)

| 주제 | 결정 |
|---|---|
| 첫 버전 범위 | orca-team 0.4 전부 |
| 대화 상대 | 3계층. 사용자는 메인과만 대화한다. 메인은 horch Run 에 묶이지 않는다 |
| 리뷰어 | horch 워커 pane 으로 띄운다(화면 없는 exec 가 아님) |
| 워커 에이전트 | 직무마다 `claude` 또는 `codex`. 리뷰는 항상 반대쪽 에이전트 |
| 이미지 | 직무가 아니다. Codex 가 만들고 요청한 Claude 워커가 검토한다 |
| 레퍼런스 캡처 | Chrome DevTools MCP |
| 구조 | 팀 CLI `hteam` 이 horch 를 부른다(horch 확장이나 스킬만으로 하지 않는다) |

## 2. 용어

- **메인**: 사용자가 연 Claude 세션. 사용자와 대화하는 유일한 주체.
- **코디네이터**: 팀 탭에서 도는 Claude 세션. horch Run 의 소유자.
- **워커**: 태스크 한 라운드를 하는 에이전트 pane. 작업 워커와 리뷰어가 있다.
- **태스크(T-xxx)**: hteam 의 작업 단위. 라운드(r1, r2, …)마다 새 워커가 한다.
- **라운드**: 작업 워커 한 번 + 리뷰 한 번. 작업과 리뷰는 각각 horch Task 하나다.
- **owns**: 태스크가 고치고 커밋할 수 있는 경로 glob.
- **팀 탭**: 같은 space 에 프로젝트마다 하나 있는 Herdr 탭. 코디네이터와 워커 pane 이 여기 붙는다.
- **outbox**: 코디네이터 → 메인 방향의 파일 메시지 줄.

## 3. 구성

### 3.1 플러그인과 파일

이 저장소의 마켓플레이스(`herdr-team`)에 두 플러그인이 있다.

```
herdr-orch/          (있음) bin/horch, lib/horch/
herdr-team/          (새로)
  .claude-plugin/plugin.json
  bin/hteam                    진입점(Python 3.11+, 표준 라이브러리만)
  lib/hteam/                   CLI 모듈
  hooks/hooks.json, hooks/hteam_hook.py
  skills/{init,up,image}/SKILL.md
  templates/                   대상 프로젝트에 복사할 파일(3.4)
  scripts/codex-run.sh         Codex exec 래퍼(12장)
  tests/
```

`hteam` 이 `horch` 를 찾는 순서: 환경 변수 `HERDR_ORCH_BIN` → herdr-team 플러그인 루트의 형제 `../herdr-orch/bin/horch` → Claude Code `installed_plugins.json` 의 herdr-orch 설치 경로. 못 찾으면 exit 12. hteam 은 horch 를 늘 `--home <프로젝트>/.herdr-team/state/horch` 로 부른다.

### 3.2 실행 주체

| 주체 | 위치 | 띄우는 쪽 | 수명 | 하는 일 |
|---|---|---|---|---|
| 메인 | 사용자 탭의 Claude | 사용자 | 사용자 세션 | 대화, `hteam tell`, `hteam watch` 를 늘 백그라운드로, 질문 중계 |
| 코디네이터 | 팀 탭의 Claude(`[coordinator]` 모델) | `hteam up` | 오래 산다. 죽으면 다시 띄우고 Run 을 넘겨받는다 | 분해, 디스패치, 리뷰 처리, 수정·완료, 워커 질문 답, 메인에 질문 |
| 작업 워커 | 팀 탭 pane | `hteam start`·`start-ready`·`fix` | 한 라운드 | 사양대로 일하고 owns 안에 커밋, 보고서, `horch done` |
| 리뷰어 | 팀 탭 pane | `hteam review` | 한 리뷰 | 리뷰 파일을 쓰고 `horch done` |

메인이 Run 에 묶이지 않는 이유: horch 는 Run 소유자를 깨울 때 그 입력창에 글을 넣는다(`hc send`). 사용자가 치던 글이나 AskUserQuestion 선택과 섞이면 안 된다. 메인은 외부 발신자로만 Run 에 쓴다(`horch send --to run:R`, herdr-orch 설계 6장).

### 3.3 hteam 과 horch 의 분담

| hteam | horch |
|---|---|
| 설정, 직무, 태스크 사양·상태, 태스크 그래프, owns 잠금, 병렬 시작, 워커 사양 조립, 리뷰 판정·변조 검사, 수정 라운드, outbox·질문 중계, init·up·doctor | Run, 워커 pane 실행(가드·펜스), 메일함(send·check·ack), ask/reply/escalate/done, observed(blocked·error·idle·exited·lost), 생존 판정, retain·release·abandon |

herdr-orch 에 하나를 더한다(1단계에 포함, 하위 호환): 워커 터미널에서 부른 `horch status` 의 `dispatch` 에 `task`(horch Task ID)와 `title` 을 더한다. 워커 역할 판별(9.4)이 쓴다.

hteam 이 hc·herdr-app 을 직접 부르는 곳은 코디네이터 실행·생존 확인과 팀 탭 이름 붙이기뿐이다(`lib/hteam/herdr.py` 한 모듈). 워커 실행은 언제나 horch 를 거친다.

### 3.4 대상 프로젝트 파일

```
.herdr-team/
  config.toml          설정(4장). 이 파일이 있으면 herdr-team 프로젝트다
  project.md           init 설명
  coordinator.md       코디네이터 사용법(8장)
  roles/<직무>.md      직무 문서
  design-rules.md      AI 티 금지 목록(11.5)
  bin/hteam            shim: 플러그인을 찾아 실행
  tasks/T-xxx.md       태스크 사양(커밋한다)
  state/               git 제외
    horch/             horch 저장 루트
    run.json           {run_id, coordinator_terminal, coordinator_argv, team_space, team_tab, launched_at}
    tasks/T-xxx.json   태스크 상태(5.3)
    tasks/T-xxx/       라운드별 조립한 사양과 리뷰 프롬프트
    plan.json          plan apply 기록(key → T-id, digest)
    outbox.jsonl, outbox.cursor, answers/, answered.json
    sessions/<session id>   훅의 역할 판별 캐시
    setup-mode, plugin-root, hook-errors.log
docs/planning/  spec.md contracts.md tasks.toml interview.md
docs/tasks/T-xxx/report.md
docs/reviews/T-xxx/rN.md
docs/design/  direction.md references.md board/ pilots/ system/ screens/<화면>/
docs/qa/
```

shim 은 플러그인 루트를 `HERDR_TEAM_PLUGIN_ROOT` → `state/plugin-root`(등록된 설치 경로이거나 디렉터리 마켓플레이스일 때만 믿는다) → `installed_plugins.json` 순서로 찾는다. 못 찾으면 exit 12.

## 4. 설정 (`.herdr-team/config.toml`)

```toml
max_parallel = 4
user_approval_roles = ["designer"]

[coordinator]
model = "opus"
effort = "xhigh"

[review]
max_rounds = 3

[defaults]
worker = "claude"
claude_model = "sonnet"
claude_effort = "xhigh"
codex_model = "gpt-6.1-sol"
codex_effort = "high"

[agents.claude]
args = []
[agents.codex]
args = ["--disable=hooks"]

[image]
codex_model = "gpt-6.1-sol"
codex_effort = "medium"

[roles.planner]
title = "기획"
claude_model = "opus"
claude_effort = "xhigh"
codex_model = "gpt-6.1-sol"
codex_effort = "high"
owns = ["docs/planning/**"]

[roles.director]
title = "디자인 디렉터"
claude_model = "opus"
claude_effort = "xhigh"
codex_model = "gpt-6.1-sol"
codex_effort = "high"
owns = ["docs/design/**", "assets/**"]

[roles.designer]
title = "디자인"
claude_model = "sonnet"
claude_effort = "xhigh"
codex_model = "gpt-6.1-sol"
codex_effort = "medium"
owns = ["docs/design/**", "assets/**"]

[roles.developer]
title = "개발"
claude_model = "opus"
claude_effort = "xhigh"
codex_model = "gpt-6-astra"
codex_effort = "xhigh"
owns = ["src/**"]

[roles.tester]
title = "테스트"
claude_model = "sonnet"
claude_effort = "xhigh"
codex_model = "gpt-6.1-sol"
codex_effort = "high"
owns = ["tests/**", "docs/qa/**"]
```

### 4.1 값의 뜻과 결정 규칙

- `worker`: 작업 워커 에이전트. `claude` 또는 `codex`. 직무에 없으면 `[defaults]`.
- 작업 모델: `worker` 쪽 모델·effort(`claude_*` 또는 `codex_*`).
- 리뷰어: `worker` 의 반대쪽 에이전트와 그쪽 모델·effort.
- 우선순위(값마다 따로): `hteam start`·`fix` 의 `--model`·`--effort`·`--worker` > 태스크 front matter(`worker`, `claude_model` 등) > `[roles.<직무>]` > `[defaults]`.
- `[agents.<에이전트>].args`: 그 에이전트를 띄울 때마다(작업·리뷰·코디네이터) horch `--agent-arg` 로 넘기는 인자(코디네이터는 `hc run` 인자). horch 는 우회 플래그를 스스로 넣지 않으므로 권한 모드는 여기서 정한다. Claude 의 `--permission-mode=bypassPermissions` 는 init 이 위험을 설명하고 사용자가 승인했을 때만 넣는다(9.1).
- `[agents.codex].args` 기본 `--disable=hooks`: Codex 의 hook 검토 창과, 검토하지 않은 hook 이 셸 명령을 막는 문제를 피한다(herdr-orch 실환경 확인 결과).
- `owns`: 비면 안 된다. 태스크 front matter(와 tasks.toml)로 좁힐 수 있고 넓힐 수는 없다. 판정은 보수적이다: 같은 glob, 직무의 고정 경로와 같거나 그 아래인 고정 경로, 직무 glob 이 `**` 이거나 `<고정 접두사>/**` 일 때 고정 접두사가 그것으로 시작하는 glob·경로만 안으로 본다. 와일드카드 없는 경로는 git pathspec 처럼 그 아래 전체를 뜻하므로 `src/a.py` 는 `src/*.py` 안이 아니다. 판단할 수 없으면 거부한다(`plan check`, `start` 가 exit 2). owns 값에는 `[ ] { } , \`, 빈·`.`·`..` 마디, 앞뒤 `/`, 마디 일부인 `**` 를 쓰지 않는다(git 과 다르게 읽히거나 front matter 에서 갈라진다. 어기면 `plan check`·`task new`·사양 검사·설정 검사가 거부한다).
- `max_parallel`: `start-ready` 가 동시에 둘 `working` 태스크 수 상한(1 이상).
- `user_approval_roles`: 리뷰 승인 뒤 `done` 대신 `awaiting_user` 로 가는 직무. `[roles]` 에 있는 직무만.
- `[image]`: `hteam image` 가 쓰는 Codex 모델·effort. 없으면 `[defaults]` 의 `codex_*`.

### 4.2 검사

설정을 읽는 명령은 다음을 검사하고 어기면 exit 2 다.

- `worker` 는 `claude`·`codex` 중 하나.
- `director`·`designer` 직무는 `worker = "claude"` 만(Claude Design 을 쓴다, 11장). front matter 나 `--worker` 로 바꿔도 같다.
- `owns` 비지 않음, `max_parallel` ≥ 1, `max_rounds` ≥ 1, `user_approval_roles` 의 직무가 존재.
- 모델·effort 값은 비지 않은 문자열인지만 검사하고 내용은 그대로 넘긴다(에이전트가 판단). 설정 파일을 읽지 못하면(디렉터리·권한) `bad_config`.

설정을 읽지 않는 명령(`tell`, `notify`, `watch`, `answer`, `ask-user`, `reask`, `status`)은 설정이 깨져도 동작한다. `status` 는 `config_error` 를 보여 준다.

## 5. 태스크

### 5.1 사양 (`.herdr-team/tasks/T-xxx.md`)

```markdown
---
id: T-003
role: developer
title: 로그인 화면 구현
owns: src/auth/**, src/ui/login/**     (선택, 직무 owns 를 좁힌다)
depends_on: T-001, T-002               (선택)
plan_key: login-screen                 (plan apply 가 넣는다)
worker: claude                         (선택)
claude_model: opus                     (선택, 모델·effort 덮어쓰기)
---
## Target
## Change
## Constraints
## Acceptance
```

- ID 는 `T-` + 숫자 3자리 이상. `hteam task new --role R --title …` 가 다음 번호로 만든다.
- 네 절은 비면 안 되고 `<…>` 자리표시만 있어도 안 된다. 어기면 `start` 가 exit 2.
- 사양은 코디네이터가 쓰고 커밋한다(`spec: T-xxx` 커밋). 이 커밋은 리뷰 대상에서 뺀다.

### 5.2 태스크 그래프 (`docs/planning/tasks.toml`)

기획자가 쓴다. 형식은 orca-team 과 같다.

```toml
[[task]]
key = "login-screen"
role = "developer"
title = "로그인 화면 구현"
owns = ["src/auth/**", "src/ui/login/**"]
depends_on = ["design-login", "ui-foundation"]
target = "…"
change = "…"
constraints = "…"
acceptance = ["…", "…"]
```

- `hteam plan check [--file <경로>]`(읽기 전용): 필수 필드, 직무 존재, `key` 형식(`[a-z0-9-]`)과 중복, 모르는 의존, 순환, 조상 관계가 아닌 두 태스크의 owns 겹침, 디렉터 규칙(`[roles.director]` 가 있고 designer 태스크가 있으면 director 태스크가 정확히 하나이고, 에셋 전용이 아닌 designer 는 모두 director 에 직간접으로 의존), 텍스트 필드 안 `## ` 로 시작하는 줄 금지, 태스크 owns 가 직무 owns 안(4.1), `state/plan.json` 이 있으면 `apply --append` 와 같은 호환성(이미 적용한 key 가 빠지거나 내용이 바뀌면 거부. 기획 리뷰 사전 검사도 이것으로 막아 accept 뒤 append 실패를 막는다). 결과에 병렬 깊이 묶음(`groups`). 두 승인 직무 태스크가 의존 관계(직간접)이고 owns 가 겹치면 거부한다: 선행이 `awaiting_user` 로 잠금을 쥔 채 후행을 기다려 일괄 승인이 교착된다. owns 를 나누거나 승인 묶음을 나눈다.
- `hteam plan apply`: 검사를 통과하면 `T-xxx.md` 를 만들고 한 번에 경로 지정 커밋(`[plan] apply: N tasks`). `state/plan.json` 에 key → T-id 와 태스크별 SHA-1 digest. 상태 파일을 `pending` 으로 만든다.
- `hteam plan apply --append`: 새 key 만 더한다. 기존 key 의 내용이 바뀌거나 빠지면 거부(digest 비교). `plan.json` 이 없는데 계획된 태스크가 있으면 거부(exit 2).
- owns 겹침 판정은 보수적이다: 두 glob 의 고정 접두사 중 하나가 다른 하나의 접두사면 겹친다. `**` 는 디렉터리를 넘고, `*`·`?` 는 한 마디 안이다.

### 5.3 상태 (`state/tasks/T-xxx.json`)

| 상태 | 뜻 | 잠금 | 다음 |
|---|---|---|---|
| `pending` | 아직 시작 안 함 | 없음 | `start` |
| `working` | 작업 워커가 돈다 | 있음 | 작업 `worker_done` → `review` |
| `launch_failed` | 띄우기 실패(또는 실행자 사망) | 있음 | `start` 다시 |
| `reviewing` | 리뷰어가 돈다 | 있음 | 리뷰어 `worker_done` → `review-finish` |
| `approved` | 리뷰 승인 | 있음 | `accept` |
| `changes` | 리뷰가 수정 요구 | 있음 | `fix` |
| `awaiting_user` | 승인 직무가 사용자 일괄 승인을 기다림 | 있음 | `design-review` 답 → `accept` 또는 `fix` |
| `done` | 끝 | 없음 | — |
| `dropped` | 버림 | 없음 | — |

상태 파일 필드: `id`, `status`, `round`, `base`(첫 라운드 시작 때 HEAD), `rounds`(라운드별 `{round_base, work: {title, horch_task, dispatch, cleaned}, reviews: [{attempt, title, horch_task, dispatch, file, result, cleaned, tamper}], verdict}`), `launcher`(`{pid, started, key}`), `history`(전이와 시각), `note`. `title` 은 horch Task 제목이자 실행 키다: 작업 `T-xxx rN 작업`, 리뷰 `T-xxx rN 리뷰 aK`.

전이는 상태 파일마다 flock 으로 잠그고 이전 상태를 확인한 뒤 원자적으로 쓴다(임시 파일 + `os.replace`). 상태를 바꾸는 명령은 모두 코디네이터만 부른다(8.3).

의존이 끝났다는 것은 선행 태스크가 `done` 이거나, 선행과 후행이 모두 승인 직무이고 선행이 `awaiting_user` 인 것이다(디자인을 한 번에 승인 받으려고).

### 5.4 시작 (`hteam start T`, `hteam start-ready`)

`hteam start T [--model M] [--effort E] [--worker W]`:

1. 설정과 사양을 검사한다(4.2, 5.1). 상태가 `pending`·`launch_failed` 여야 한다(아니면 exit 3. `done`·`dropped` 는 `task_closed`). 실행 키가 `canceled` 면 복구하지 않는다.
2. 잠금: 이 태스크의 owns 가 잠금을 가진 다른 태스크의 owns 와 겹치면 exit 3.
3. 실행 키(`T-xxx rN 작업`), 실행자 pid·시작 시각, 라운드 번호를 `launch_failed` 와 함께 먼저 쓴다. base 는 태스크를 처음 띄울 때 한 번만(그때 HEAD), round_base 는 그 라운드를 처음 띄울 때 한 번만 쓴다. 같은 라운드를 복구할 때는 둘을 그대로 둔다(그 사이 워커가 커밋했어도 리뷰 대상에서 빠지지 않게). 같은 라운드 복구는 저장된 사양 파일·owns·에이전트·모델도 그대로 쓴다(`--task --retry` 는 horch 에 저장된 사양으로 띄우므로 잠금도 그 owns 여야 한다). 복구에 `--model`·`--effort`·`--worker` 를 주면 exit 2 이고, 바꾸려면 `fix` 로 새 라운드를 띄운다. hteam 은 horch 를 시작 장벽을 둔 자식 프로세스로 부른다: 자식은 먼저 stdin 에서 한 바이트를 기다리고, hteam 은 자식의 pid·시작 시각을 상태 파일에 쓴 다음에야 그 바이트를 보낸다. 자식은 바이트를 받으면 horch 로 exec 하고(pid 가 그대로 horch 프로세스가 된다), EOF 를 받으면(hteam 이 기록 전에 죽음) horch 를 실행하지 않고 끝난다. 그래서 상태 파일에 자식 pid 가 없으면 horch 는 실행되지 않은 것이다. 같은 키의 hteam 실행자나 기록된 horch 자식이 아직 살아 있으면 exit 3 `launching`. 복구는 둘 다 끝난 것을 확인한 뒤에만 한다.
4. 워커 사양을 조립해(5.5) `state/tasks/T-xxx/rN-work.md` 에 쓴다.
5. `horch worker-start --agent <worker> --title "T-xxx rN 작업" --spec-file <그 파일> [--model M] [--effort E] --cwd <프로젝트 루트> [--agent-arg=…]...`(`[agents.<worker>].args`).
   같은 키의 horch Task 가 이미 있으면 새로 만들지 않는다. 상태 파일에 Task 가 기록돼 있지 않으면: 자식 pid 도 없으면 horch 가 실행되지 않았으므로 그냥 새로 띄운다. 자식 pid 가 있으면 그 자식과 이전 실행자가 모두 끝난 것을 확인한 뒤 `horch worker-list` 에서 그 제목으로 찾는다. 찾지 못하면(자식이 시작 바이트를 받기 전에 끝남) 저장된 라운드 정보와 사양을 그대로 쓰고 시작 장벽부터 다시 거쳐 띄운다. 같은 제목이 둘 이상이면 가장 최근 것을 쓰고 나머지는 경고로 보고한다. 그 Task 의 최신 Dispatch 가 `launching`·`active`·`settled`·`retained` 면 새로 띄우지 않고 그것을 이 라운드의 워커로 기록한다(라운드의 에이전트·모델·effort 를 그 Dispatch 기록에 맞춘다. 리뷰어는 그 반대쪽이다). `launch_failed`·`abandoned` 면 `horch worker-start --task <그 Task> --retry --agent … --cwd … [--model …] [--effort …] [--agent-arg=…]...` 로 같은 Task 를 다시 띄운다(horch 펜스가 옛 Dispatch 의 늦은 가드를 막는다).
6. 성공하면 상태를 `working` 으로, horch Task·Dispatch ID 를 라운드 기록에 쓴다. 실패하면 `launch_failed` 와 horch 오류 JSON 을 남기고 exit 1(horch 의 exit 12 는 그대로 12).

`hteam start-ready`: `tasks.toml` 순서(없으면 ID 순)로 `pending`·`launch_failed` 태스크마다 사양 → 의존 → 잠금 → 동시 수 상한(`working` 수 < `max_parallel`)을 차례로 보고 통과한 것을 `start` 한다. 결과에 시작한 태스크와 남은 태스크의 대기 사유(`spec`·`deps`·`lock`·`limit`). 하나가 실패해도 나머지는 계속하고, 하나라도 실패하면 exit 1. `max_parallel` 은 `start-ready` 만 본다(`start`·`fix` 는 보지 않는다). 코디네이터는 accept·fix·drop·승인 답 뒤마다 부른다.

### 5.5 워커 사양 조립

차례로 이어 붙인다.

1. 직무 문서 `roles/<직무>.md`.
2. 태스크 본문(네 절).
3. 선행 태스크: "`docs/planning/contracts.md` 와 선행 태스크의 `docs/tasks/<T>/report.md` 를 먼저 읽는다" 와 선행 목록.
4. owns 와 작업 규칙(아래).
5. 수정 라운드면 수정 블록: "이전 대화는 없다. `report.md` 와 `git log --grep '^\[T-xxx\]'` 를 읽는다", `docs/reviews/T-xxx/r{N-1}.md` 의 모든 지적을 다룬다(파일이 있을 때), 코디네이터 메모(`--note`).

작업 규칙:

- owns 와 `docs/tasks/T-xxx/report.md` 만 고치고 커밋한다. 커밋은 경로를 지정한다: `git add -- <경로> && git commit -m "[T-xxx] …" -- <경로>`. `git stash`·`reset`·`checkout --`·`add -A` 금지.
- `report.md` 에 라운드마다 `## rN` 절: 바꾼 파일, 이유, 검증 명령과 출력 원문, 남은 위험, 가정.
- 막히면 프리앰블의 ask 명령(직무가 planner·director 면 사용자에게 묻는 것은 `hteam ask-user`, 7.5). 대화형 질문 도구는 쓰지 않는다.
- 끝나면 보고서를 커밋하고 프리앰블에 적힌 done 명령(절대 경로·`--home`·`--dispatch` 포함)을 `--outcome succeeded|failed --summary "…" --report-path docs/tasks/T-xxx/report.md` 로 부른다. 출력을 못 받았으면 같은 인자로 다시 부른다(재호출 안전).

horch 프리앰블(herdr-orch 설계 8장)이 이 사양 앞에 붙어 `horch` 명령의 절대 경로와 `--home` 을 알려 준다.

### 5.6 동시 작업의 전제

작업 폴더는 하나다(worktree 없음). 진행 중 태스크끼리 owns 가 겹치지 않게 잠그고, 커밋은 경로를 지정하므로 다른 워커의 바뀐 파일을 담지 않는다. owns 밖 파일을 고쳐야 하면 워커는 `horch ask` 로 코디네이터에게 묻는다(코디네이터는 새 태스크로 나눈다).

## 6. 교차 리뷰

### 6.1 시작 (`hteam review T`)

작업 워커가 `worker_done`(succeeded)을 보내면 코디네이터가 부른다. 리뷰어를 띄우고 바로 돌아온다.

0. 태스크가 `done`·`dropped` 면 무엇보다 먼저 exit 3 `task_closed`(복구도 하지 않는다). 이 라운드에 끝나지 않은(취소되지 않은) 시도 기록이 있으면(앞 호출이 기록 뒤 죽음) 1–5 를 건너뛰고 복구만 한다: 시도 기록에 `launched`(horch 를 부른 표시와 자식 pid)가 없으면 저장된 기준점과 입력으로 프롬프트 파일을 다시 만들어 7 부터 한다. 있으면 5.4 와 같은 규칙으로 기존 리뷰 Dispatch 를 제목으로 찾아 이어 붙이고 8 을 한다(찾은 Dispatch 가 이미 끝났으면 상태를 `reviewing` 으로 바꾼 뒤 코디네이터가 `review-finish` 를 부르게 한다). 찾지 못하면 저장된 시도 번호·기준점·입력을 그대로 두고 프롬프트를 확인해(없으면 다시 만들어) 7 부터 시작 장벽을 다시 거친다. 사전 검사와 새 기준점은 만들지 않는다.
1. 상태가 `working` 이고, 이 태스크에 진행 중 리뷰가 없어야 한다(아니면 exit 3). `hteam review T --retry` 는 `reviewing` 에서 리뷰가 실패·무효로 멈춘 뒤 사용자가 다시 하라고 했을 때만 쓴다(시도 번호를 하나 올리고 시도 상한을 그 한 번만 넘긴다).
2. 작업 Dispatch 를 `horch worker-retain` 한다(리뷰 동안 pane 을 남긴다). 실패해도 계속한다.
3. 리뷰 대상 커밋: base 이후 `[T-xxx]` 로 시작하는 커밋. `spec: T-xxx` 와 `[T-xxx] review rN:` 커밋은 뺀다.
4. 사전 검사. 어기면 리뷰어를 띄우지 않고 `docs/reviews/T-xxx/rN.md` 에 `REQUEST_CHANGES`(출처 `hteam`)를 써서 커밋하고 `changes` 로 간다.
   - 대상 커밋이 없다.
   - owns 와 `docs/tasks/T-xxx/` 밖 경로 가운데 대상 커밋이 건드린 경로의 현재 내용이 base 와 다르다(앞 라운드의 위반을 되돌렸으면 통과한다).
   - planner 태스크인데 `tasks.toml` 이 `plan check` 를 통과하지 못한다(accept 뒤에는 고칠 수 없으므로 여기서 막는다).
   - owns 안에 커밋하지 않은 변경이 있다. 성공 보고 뒤라 워커에게 되돌려 보낼 수 없으므로(retain 된 Dispatch 에는 send 할 수 없다) `changes` 로 보내고 수정 라운드가 커밋한다.
5. 변조 기준점: HEAD 와 추적 파일 내용 해시, 그리고 그때 진행 중인 다른 태스크 목록. `.herdr-team/`, `docs/reviews/`, 다른 진행 중 태스크의 owns·보고서는 뺀다.
6. 끝나지 않은 시도 기록(K)이 이미 있으면(앞 호출이 기록 뒤 죽음) 새로 만들지 않는다: 그 시도의 기준점·결과 파일을 그대로 두고 7 의 복구 규칙(제목으로 찾기)만 한다. 없으면 시도 번호 K 를 정하고, 기준점(5)·결과 경로 `docs/reviews/T-xxx/rN-aK.md`·실행 키·프롬프트를 만들 입력(대상 커밋 목록, 바뀐 파일)을 시도 기록에 먼저 쓴 뒤, 그 결과 경로가 남아 있으면 지우고(지웠다는 표시 `reset` 을 시도 기록에 남긴다. 표시 없이 죽었으면 복구가 리뷰어를 띄우기 전에 다시 지운다. 이미 띄운 시도의 결과 파일은 지우지 않는다), 리뷰 프롬프트를 조립해(6.2) `state/tasks/T-xxx/rN-review-aK.md` 에 쓴다. 5 의 기준점은 새 시도일 때만 만든다. 7 은 5.4 와 같은 시작 장벽으로 부르고, 부르기 직전에 시도 기록에 `launched` 를 쓴다.
7. `horch worker-start --agent <반대쪽> --title "T-xxx rN 리뷰 aK" --spec-file <그 파일> --model … --effort … --cwd <루트> [--agent-arg=…]...`.
8. 상태를 `reviewing` 으로, 리뷰 Dispatch 를 라운드 기록에 쓴다. 실행 키와 복구는 5.4 와 같다(제목 `T-xxx rN 리뷰 aK` 로 찾는다).

### 6.2 리뷰 프롬프트

orca-team 의 리뷰 프롬프트를 옮긴다.

- 실행 정책: 리뷰만 한다. 쓰는 파일은 이 시도의 `docs/reviews/T-xxx/rN-aK.md` 하나. git 쓰기(커밋·체크아웃·스태시 등) 금지. 테스트·빌드 실행은 된다. 질문으로 끝내지 않는다. 다 쓰면 프리앰블의 done 명령을 `--outcome succeeded --summary "<판정>" --report-path docs/reviews/T-xxx/rN-aK.md` 로 부른다.
- 넣는 것: 태스크·사양·직무 문서·보고서 경로, 이전 리뷰 파일, 대상 커밋 목록, 바뀐 파일.
- 기준: 인수 조건을 실제로 충족했는가(직접 실행해 본다), 직무 규칙, 버그·보안·회귀, 이전 지적을 모두 다뤘는가.
- 디자인 절: director·designer·developer 태스크이고 `[roles.director]` 가 있으면 디자인 기준(11장)과 자동 검사 경고(11.6)를 더한다.
- 형식: 지적마다 `[P1|P2|P3] file:line — 문제. 고칠 방향.` 칭찬과 범위 밖 제안은 쓰지 않는다. P1 이 하나라도 있으면 REQUEST_CHANGES. 마지막 줄은 정확히 `VERDICT: APPROVE` 또는 `VERDICT: REQUEST_CHANGES`.

Codex 리뷰어에게는 `AGENTS.md` 의 리뷰어 규칙도 적용된다(9.1). Claude 리뷰어는 이 프롬프트만 따른다.

### 6.3 마무리 (`hteam review-finish T`)

리뷰어가 `worker_done` 을 보내거나 리뷰어가 done 없이 끝났을 때(`observed exited`·`lost`) 코디네이터가 부른다.

1. 상태가 `reviewing` 이어야 한다. 이 시도(K)의 리뷰 Dispatch 만 본다.
2. 리뷰 Dispatch 정리(멱등, `cleaned` 기록): 정리하기 전에 Dispatch 의 상태·outcome 과 종료 원인을 시도 기록에 먼저 영속화하고, 그 기록을 유지한 채 abandon·release 를 한다. 모두 끝난 뒤에만 `cleaned` 를 쓴다. `settled`·`retained`·`abandoned` 면 release. `active` 인데 판정이 `exited`·`lost` 면 `worker-abandon` 뒤 release. `active` 이고 살아 있으면(아직 일하는 중) exit 3 으로 끝낸다(코디네이터가 기다린다).
3. 변조 검사: HEAD 가 fast-forward 가 아니게 움직였거나, 기준점 이후 새 커밋이 제외 경로 밖을 바꿨거나, 추적 파일 내용이 바뀌었으면 변조다. 내용은 git 항목(모드와 객체 ID)으로 견준다: 같은 내용이라도 심볼릭 링크로 바꾸거나 실행 비트를 바꾸면 변조다. 트리·인덱스의 모드는 그대로 견주고, 작업 트리의 실행 비트는 기준점 때의 `core.fileMode` 로 본다(false 면 git 처럼 인덱스의 모드). 상위 폴더가 링크면 git 처럼 그 파일은 없는 것이다. 프로젝트 안의 숨김 플래그(assume-unchanged·skip-worktree, `core.ignoreStat`)가 붙은 파일과 서브모듈은 git diff 가 보지 않아도 작업 트리를 직접 해시해 견준다(서브모듈은 HEAD 와 안의 커밋하지 않은 변경). git 이 내는 경로는 바이트로 읽어 손실 없이 푼다. 제외 경로는 기준점의 진행 중 태스크와, 리뷰 동안 시작된 태스크(상태 기록의 시각으로 찾는다)의 owns·보고서, 그리고 그 태스크들의 `[T-yyy]` 커밋이다. 추적하지 않는 새 파일은 경고만 남긴다. 프로젝트가 git 저장소의 하위 폴더면 변조는 그 폴더 안만 본다: fast-forward 가 아닌 HEAD 이동과 폴더 안 추적 파일의 변경·커밋은 변조이고, 폴더 밖 추적 파일의 변경·커밋은 경고로만 남기며 추적하지 않는 새 파일도 폴더 안만 본다(owns 는 `..` 를 쓸 수 없어 hteam 작업은 폴더 밖을 건드리지 않는다). 사전 검사(6.1 4)는 그대로 태스크의 모든 `[T-xxx]` 커밋을 보고 프로젝트 밖 변경도 owns 밖으로 지적한다. 그래서 git 저장소 하나를 여러 herdr-team 프로젝트가 나눠 쓰며 태스크 ID 가 겹치면 사전 검사가 거짓으로 실패할 수 있고, 그 구성은 지원하지 않는다.
4. 변조면 자동으로 다시 하지 않는다. 바뀐 경로와 HEAD 전후를 `tamper` 에 남기고 상태는 `reviewing` 그대로, exit 1 `review_tampered`. 코디네이터가 메인에 올린다. 사용자가 정리한 뒤 `hteam review T --retry` 가 새 기준점으로 다시 한다.
5. 판정 읽기: 이 시도의 파일 `docs/reviews/T-xxx/rN-aK.md` 의 마지막 `VERDICT:` 줄만 본다(다른 시도의 파일은 보지 않는다). 리뷰어 `outcome` 이 `failed` 이거나, Dispatch 가 done 없이 끝났거나(abandon 됨, `exited`·`lost`), 파일·VERDICT 가 없으면 시도 실패다. 실패한 시도의 파일은 판정에 쓰지 않는다.
6. 시도 실패면 새 리뷰어로 한 번 더 한다(라운드당 자동 시도 2번). 두 번째도 실패하면 상태는 `reviewing` 그대로 exit 1 `review_failed`. 코디네이터가 메인에 올리고(다시 시도 / 버림), 다시 시도면 `hteam review T --retry`.
7. 성공하면 판정과 시도 파일의 해시를 시도 기록에 남긴 뒤 시도 파일을 `docs/reviews/T-xxx/rN.md` 로 옮기고(다른 시도 파일은 지운다) `[T-xxx] review rN: <VERDICT>` 로 경로 지정 커밋한다(추적하지 않는 새 파일 목록은 커밋 본문에). 상태를 `approved` 또는 `changes` 로, 판정을 라운드 기록에. 판정을 남긴 뒤 죽어 다시 부르면 3 의 변조 검사를 다시 하고, 시도 파일이 있으면 그것이, 없으면(이미 옮김) `rN.md` 가 남긴 해시와 같은지 확인하고, 검증한 그 파일만 최종화한다. 다르거나 없으면 시도 실패(6)다.

리뷰어 생사는 horch 가 판정한다. 리뷰어가 `idle`(done 없이 턴을 마침)이면 코디네이터가 `horch send` 로 done 을 요구한다. 그래도 안 되면 `worker-abandon --kill` 하고 `review-finish` 가 시도 실패로 처리한다.

### 6.4 처리 (`accept`, `fix`, `drop`)

- `hteam accept T [--round N]`: `approved` → `done`, 승인 직무면 `awaiting_user`. `awaiting_user` → `done`(사용자 승인 뒤). 작업 Dispatch 를 release 한다(실패하면 경고). 태스크의 작업·리뷰 Dispatch 가 `launching`·`active` 면(리뷰는 retain 실패를 견디므로 승인 뒤에도 작업 워커가 살아 있을 수 있다) 바꾸지 않고 exit 3 이다(owns 잠금을 풀기 전에 `horch worker-abandon --kill` 뒤 `worker-release`, 또는 `drop --force`). `horch worker-list` 를 읽지 못하면 살아 있는 워커가 없음을 확인할 수 없으므로 역시 바꾸지 않고 `horch_failed`(exit 1, horch 가 의존성 없음을 내면 12)로 끝난다.
- `hteam fix T [--note "…"] [--supplement T-yyy] [--force-round] [--round N] [--model …] [--effort …] [--worker …]`: `changes`·`launch_failed`·`working`(작업 워커가 실패로 끝남)·`awaiting_user`(사용자 수정 요청) 에서 새 라운드를 띄운다. 입력 검사(owns 범위·잠금)를 먼저 하고, 이전 라운드의 작업 Dispatch 와 끝나지 않은 리뷰 Dispatch 를 정리한다(기록되지 않은 Dispatch 도 저장된 horch Task 나 실행 키로 찾는다. 정리를 확인한 뒤에만 새 라운드를 쓴다): `settled`·`retained`·`abandoned` 는 바로 release(release 가 살아 있는 터미널도 끈다), `active` 면 `worker-abandon --kill` 뒤 release. `round >= max_rounds` 이면 exit 3 과 `max_rounds`(`--force-round` 는 사용자가 계속하라고 했을 때 한 라운드만 넘긴다). `awaiting_user` 에서의 수정은 상한을 보지 않는다. `--supplement` 는 디렉터 보강을 반영하는 수정이라는 표시다(11.4).
- `hteam drop T [--force]`: 태스크를 `dropped` 로. 끝나지 않은 작업 실행 키와 리뷰 시도 기록을 `canceled` 로 표시한다(이후 `start`·`review` 의 복구 대상이 아니다). `active` Dispatch 가 있으면 `--force` 가 있어야 하고 `worker-abandon --kill` 뒤 release 한다. `settled`·`retained`·`abandoned` 는 release 한다. `launch_failed` 는 건드리지 않는다(horch 가 가드가 거부한 터미널을 정리한다). `launching` 이면 먼저 `horch worker-list` 로 조정하고, 그래도 `launching`(실행자가 살아 있음)이면 exit 3 으로 나중에 다시 하게 한다.
- `fix`·`drop` 의 순서 규칙: 바꾸기 전에 거부할 것을 확인하고(입력, launching, `--force` 없는 active) → 현재 라운드의 끝나지 않은 실행 키·리뷰 시도의 `canceled` 를 먼저 저장하고(취소된 기록이 있는 라운드에는 `start`·`review` 가 Dispatch 를 띄우지 않는다) → 정리 대상을 다시 골라 정리하고 → 그다음에만 새 라운드나 `dropped` 를 쓴다. 정리 대상은 horch 의 실제 상태로 고른다: 모든 라운드의 실행 기록마다 그 horch Task(없으면 실행 키)의 모든 시도 가운데 끝나지 않은 것. `cleaned` 는 기록일 뿐 대상 선택에 쓰지 않는다. 어디서 멈춰도 같은 명령을 다시 부르면 이어 한다.
- `max_rounds` 에 닿으면 코디네이터가 메인에 묻는다(계속 / 버림). 계속이면 `--note` 와 함께 `fix --force-round`(상한을 한 번 넘긴다).
- `--round N`(`accept`·`fix`): 지금 라운드가 N 일 때만 한다(아니면 아무것도 바꾸지 않고 exit 3 `round_changed`). 일괄 승인 결정(11.4)을 다시 할 때 이미 한 항목을 다시 하지 않게 한다. `accept` 는 awaiting_user 인 승인 태스크가 stale(11.4)이면 마지막 전이 때 프로젝트 잠금 아래에서 다시 보고 exit 3 `approval_stale` 로 거부한다.

## 7. 메인과 코디네이터의 연결

### 7.1 메인 → 코디네이터 (`hteam tell`)

`hteam tell "<글>"` 은 메인 터미널에서 `horch send --to run:<run_id> --subject "[main] <첫 줄>" --body "<글>"` 을 부른다. 메인은 Run 소유자가 아니므로 외부 발신자다. 코디네이터가 깨어난다. `tell`·`answer` 는 보내기 전에 메인 터미널(`$HC_TERMINAL_ID`, 없으면 exit 5)을 `run.json` 의 `main_terminals` 에 남긴다(Run 동안 줄이지 않는다. 지운 터미널의 처리 전 메시지가 메인이 아닌 것으로 보이면 안 된다).

### 7.2 코디네이터 → 메인 (`hteam notify`, outbox)

`hteam notify --type progress|question|approval|done --body "…"` 또는 `--json -`(질문). `state/outbox.jsonl` 에 flock 으로 한 줄을 더한다: `{id: "out-NNNN", type, at, body | render, from: "coordinator" | "T-xxx", answered: false}`. 코디네이터만 부른다(planner·director 의 질문은 7.5).

### 7.3 메인의 감시 (`hteam watch`)

메인은 `hteam watch` 를 늘 하나 백그라운드로 띄운다(Claude Code Bash `run_in_background`).

- 2초마다 outbox 를 본다. 커서 뒤 새 항목이 있으면 출력하고 커서를 옮긴 뒤 끝난다(출력한 뒤에야 옮기므로 적어도 한 번 전달된다). Claude Code 의 완료 알림이 메인을 깨운다.
- 코디네이터가 없으면(`run.json` 의 터미널이 끝남) `{status: "orphaned"}` 로 끝난다.
- 메인은 처리한 뒤 다시 띄운다. Stop 훅이 이를 강제한다(9.3).

### 7.4 질문 형식 (`render`)과 답

```json
{"header": "≤12자", "question": "한 줄 질문 ≤300자\n예: 보기 ≤300자",
 "context": "선택 사항, ≤4000자",
 "options": [{"label": "추천안 (추천) ≤30자", "description": "추천 사유: …"}, …],
 "multiSelect": false}
```

선택지는 2–4개이고 추천안이 맨 앞이다. `notify --json` 과 `ask-user` 가 검사한다(어기면 exit 2).

메인은 `context` 를 그대로 보여 준 뒤 AskUserQuestion 을 `render` 로 부르고, 답을 `hteam answer <out-id> "<답>"` 로 보낸다.

- `ask` 항목(7.5): 답 파일 `state/answers/<out-id>.json` 을 원자적으로 만든다(`os.link`). 두 번째 답은 exit 3.
- `question`·`approval` 항목: 답을 먼저 `state/answers/<out-id>.json` 에 남긴 뒤 `horch send --to run:R --subject "[main] reply <out-id>" --body "<답>"`. 보내기가 끊겨 다시 실행하면 같은 답을 다시 보낸다(적어도 한 번). 코디네이터는 답에 따른 일을 마친 뒤 `hteam applied <out-id>` 로 적용을 기록한다(`state/applied.json`). `hteam wait` 는 이미 적용된 `out-id` 의 답만 `duplicate: true` 로 표시한다. 그래서 처리하기 전에 코디네이터가 죽으면 다시 전달된 답(ack 하지 않은 Delivery)은 중복이 아니고 다시 처리된다. 같은 답이 두 번 와서 둘 다 적용 전이면: 한 Delivery 안이면 `hteam wait` 가 뒤 메시지를 `duplicate: true` 로 표시하고, Delivery 가 다르면 둘 다 `duplicate: false` 이므로 코디네이터는 같은 `out-id` 를 한 번만 처리하고 `applied` 를 기록한 뒤 나머지를 무시한다. 일괄 승인 답은 결정 기록(11.4)이 두 번 처리하지 않게 한다.

### 7.5 기획자·디렉터의 직접 질문 (`hteam ask-user`)

`hteam ask-user --task T --json -`(planner·director 의 `working` 태스크만):

- 태스크마다 열린 질문은 하나(아니면 exit 3).
- outbox 에 `ask` 항목을 쓰고 답 파일을 2초마다 본다. 답이 오면 `{answer}` 를 출력하고 끝난다.
- 540초가 지나면 `{status: "waiting", id}` 와 exit 4. 워커는 `hteam ask-user --wait <id>` 로 다시 기다린다. 540초는 Bash 도구 최대 시간 제한(600초) 안에 끝나도록 정했다. 직무 문서는 이 명령을 `timeout` 600000 으로 부르라고 적는다.
- 답 조회는 몇 번이든 된다(`--wait <id>` 는 답이 있으면 바로 돌려준다). 워커는 답을 문서에 적은 뒤 `hteam ask-user --ack <id>` 로 반영을 기록한다. 그래서 답을 읽고 적기 전에 워커가 죽어도 답이 사라지지 않는다.
- `--pending` 은 답이 왔지만 ack 되지 않은 항목, `--history` 는 이 태스크의 모든 질문과 답(이전 라운드 포함). 수정 라운드의 워커는 먼저 둘을 확인한다.
- 답을 적는 곳: planner 는 `docs/planning/interview.md`, director 는 `docs/design/direction.md` 의 결정 기록 절.

### 7.6 재시작 뒤 질문 (`hteam reask`)

`open_questions` 는 답이 없는 `ask` 항목(묻는 태스크가 아직 `working`)과, 답이 없는 `question`·`approval` 항목이다. 메인을 다시 열면 `/herdr-team:up` 이 `hteam reask` 로 이미 출력된 항목을 다시 내보내고 하나씩 묻는다.

## 8. 코디네이터

### 8.1 역할

- 일을 나눈다. 새 요청이면 기획 태스크가 언제나 먼저다.
- 사양을 쓰고 커밋한다. `plan apply` 와 `start-ready` 로 띄운다.
- 리뷰를 돌리고 판정에 따라 accept·fix·drop 한다.
- 워커 질문에 기획 문서로 답한다(`horch reply`). 판단할 수 없으면 `hteam notify --type question --json -` 으로 메인에 묻는다.
- 쓸 수 있는 파일은 `.herdr-team/`(state 제외)뿐이다. 제품 파일을 고치지 않는다. 대화형 질문 도구와 서브에이전트를 쓰지 않는다.

### 8.2 루프와 `hteam wait`

코디네이터는 `hteam wait` 를 늘 하나 백그라운드로 띄운다. `hteam wait [--ack <delivery>]` 는 `horch check --wait --timeout-ms <T> [--ack …]` 를 부르고, 받은 메시지마다 `hteam` 필드를 붙여 출력한다. `hteam wait` 는 전체 대기 시간(기본 3600초) 안에서 `horch check --wait` 를 60초씩 나눠 부르고, 그 사이마다 horch `worker-list` 를 본다. 메시지가 오면 바로 돌려준다. 메시지가 없어도 손볼 일이 생기면 `reason: attention` 으로 돌려준다: `no_status` 가 60초 넘게 이어진 행, `launch_failed` 행. 단 hteam 이 아직 끝내지 않은 태스크(`done`·`dropped` 가 아님)의 현재 라운드·현재 시도 Dispatch 만 센다(버린 태스크나 지난 시도의 실패 행은 알리지 않는다). 그래서 대기 중에 새로 띄운 워커가 시작 확인 창에서 멈춰도(상태 보고가 없어 메시지가 오지 않는다) 늦어도 2분 안에 알 수 있다. 전체 시간이 지나면 `reason: timeout`.

```json
{"delivery": 12, "count": 1, "reason": "message",
 "messages": [{"id": 40, "type": "worker_done", "sender": "dispatch:dsp-…", "body": "…",
               "hteam": {"task": "T-003", "round": 2, "kind": "work", "next": ["hteam", "review", "T-003"]}}]}
```

- `kind`: `work`·`review`·`main`(메인이 보낸 `[main]` 글)·`other`. 제목 `[main]` 은 형식일 뿐이다: 발신자가 `external:<터미널>` 이고 그 터미널이 `main_terminals` 에 있을 때만 `main` 이다. 워커(`dispatch:…`)나 다른 터미널이 보낸 `[main]` 글은 `other`(`not_main`)이고 데이터로 다룬다. 상태 파일에 기록되지 않은 Dispatch 는 horch 제목으로 찾되, 그 horch Task 의 최신 시도이고 현재 실행 기록과 어긋나지 않을 때만 현재 라운드·시도로 본다. 태스크가 이미 `done`·`dropped` 거나 지난 라운드·시도의 메시지면 `stale: true` 이고 `next` 는 없다(ack 만 한다).
- `next`: 권장 다음 명령(argv). 작업 `worker_done` → `review`, 리뷰 `worker_done` → `review-finish`, 작업 `failed` → `fix --note`, `observed idle` → `horch send` 로 이어가라는 안내, `observed exited`·`lost` → 작업이면 `fix`, 리뷰면 `review-finish`, `observed error` → `worker-show --lines 80` 으로 보고 `horch send` 로 이어가거나 `fix`, `question` → `horch reply`, `[main]` → 지시를 읽는다(`duplicate: true` 면 무시). attention `no_status` 가 1분 넘게 이어지면 `worker-show` 로 화면을 보고 메인에 질문으로 올린다(키를 누르지 않는다).
- 메시지를 모두 처리한 뒤 `hteam wait --ack <delivery>` 로 다시 띄운다. 시간이 지나면(`reason: timeout`) `hteam status` 를 보고 `next` 를 따른다.

### 8.3 명령 표

모든 명령은 `--root <프로젝트>`(기본: 현재 폴더에서 위로 `.herdr-team/config.toml` 을 찾음)를 받고, `skill`·`watch` 출력 외에는 stdout 에 JSON 한 개를 쓴다(`{"ok": true, …}` / `{"ok": false, "error": {"code", "message", "hint"}}`). exit 코드는 horch 와 같다: 0 성공, 1 실패·확인 불가, 2 입력 오류, 3 상태 충돌, 4 대기 시간 초과, 5 권한 없음, 12 의존 프로그램 없음.

| 명령 | 부르는 쪽 | 하는 일 |
|---|---|---|
| `doctor` | 누구나 | 점검(9.2) |
| `scaffold --description-file F` | init | 파일 복사(덮어쓰지 않음, 9.1) |
| `up [--wait-run S] [--force]` | 메인 | 코디네이터 확인·실행(9.3) |
| `bind` | 코디네이터 | horch Run 생성 또는 넘겨받기, `run.json` 기록 |
| `status` | 누구나 | 태스크별 상태·잠금·`next`, 코디네이터·watch 생사, 열린 질문 |
| `task new --role R --title T` | 코디네이터 | 다음 ID 로 사양 파일 생성 |
| `plan check [--file F]` / `plan apply [--append]` | 기획자(check) / 코디네이터 | 5.2 |
| `start T` / `start-ready` / `fix T` / `drop T` | 코디네이터 | 5.4, 6.4 |
| `review T [--retry]` / `review-finish T` / `accept T` | 코디네이터 | 6장 |
| `design-review` | 코디네이터 | 11.4 |
| `wait [--ack D]` | 코디네이터 | 8.2 |
| `which <dispatch>` | 코디네이터 | Dispatch → 태스크·라운드·종류 |
| `tell "…"` / `watch` / `answer ID "…"` / `reask` | 메인 | 7장 |
| `notify --type … ` / `applied ID` | 코디네이터 | 7.2, 7.4 |
| `ask-user --task T --json -` / `--wait ID` / `--ack ID` / `--pending` / `--history` | 기획자·디렉터 | 7.5 |
| `image …` | 디자인 워커 | 12장 |
| `lint --task T` | 리뷰(내부) | 11.6 |
| `setup-done` | init | `setup-mode` 해제, `state/setup-done` 표시를 남긴다 |

권한 확인(누가 부를 수 있나)은 실수 방지용이다(보안 경계가 아님). 역할 판별은 9.4 와 같다.

## 9. 시작, 점검, 훅

### 9.1 `/herdr-team:init <설명>`

1. 설명이 비면 한 줄로 묻는다.
2. `hteam doctor`(9.2). 오류면 멈추고 알린다.
3. `hteam scaffold --description-file <임시 파일>`: `.herdr-team/` 일체(설정, 직무 문서, 코디네이터 사용법, 디자인 규칙, shim, `project.md`, `tasks/`), `CLAUDE.md` 에 `<!-- herdr-team -->` 절(메인 규칙, 역할 판별 안내), `AGENTS.md` 에 같은 표시의 절(Codex 워커·리뷰어 규칙), `.gitignore` 에 `.herdr-team/state/`. 있는 파일은 덮어쓰지 않는다(`CLAUDE.md`·`AGENTS.md`·`.gitignore` 는 덧붙이기만 한다). `state/plugin-root` 를 만들고, `state/setup-done` 이 없을 때만 `state/setup-mode` 를 만든다(출력 `setup_mode`). 세팅을 마친 프로젝트를 다시 세팅하려면 `state/setup-done` 을 지우고 scaffold 를 다시 한다.
4. 판단이 필요한 한 단계: 표 하나로 제안하고 AskUserQuestion 한 번으로 승인받는다. 직무별 owns, 추가 직무, 필요한 도구(Chrome DevTools MCP 등), Claude 권한 모드(`[agents.claude].args`. bypass 는 사람 없이 돌 때 필요하지만 워커가 사용자 자격 증명을 그대로 쓴다는 위험을 적는다).
5. `hteam up --wait-run 180` 과 백그라운드 `hteam watch`.
6. `hteam setup-done`, 경로 지정 커밋 `chore: herdr-team 세팅`, 보고.

### 9.2 `hteam doctor`

Python 3.11 이상, git(없으면 `git init` 과 빈 커밋을 권함), `horch` 찾기와 `horch doctor`(hc·herdr-app 포함), 이 터미널이 Herdr 터미널인가(`$HC_TERMINAL_ID`), `claude` 존재, `codex` 존재와 `codex login status`, Codex 래퍼 실행 가능, `codex features` 의 `image_generation`(경고만), Chrome DevTools MCP 설정 여부(경고만).

### 9.3 `hteam up` 과 코디네이터

1. `run.json` 의 코디네이터 터미널이 살아 있으면(horch 생존 판정과 같은 규칙: hc 상태 `live` 이고 argv 가 기록과 같음. hc 조회 실패·argv 없음은 확인 불가) 그대로 둔다. 띄운 지 180초 안이면 `starting`. 확인할 수 없으면 기록과 nonce 를 그대로 두고 exit 3 이다. 사용자가 끝났다고 확인하면 `hteam up --force` 가 새로 띄우고(`pending_launch.force`), 그 코디네이터의 `bind` 가 `run-use --force` 로 넘겨받는다. 이 인계 승인은 bind 가 성공할 때까지 다음 `up` 이 이어 받는다. 새로 띄우는 것은 처음이거나 끝남·소실이 확인됐거나 `--force` 일 때뿐이다. `up` 은 메인만 부른다: 무엇이든 바꾸기 전에 `require_main` 으로 확인하고, 코디네이터·워커·리뷰어 터미널이면 exit 5 다. `run.json` 을 읽지 못하면 아무것도 바꾸지 않고 exit 1 `bad_run_file`.
2. 아니면 `run.json` 에 `pending_launch: {nonce, at}`(무작위 nonce)를 먼저 쓰고 팀 탭에 새 코디네이터를 띄운다. 팀 탭 id 는 `tb` + SHA-1(`herdr-team\n<프로젝트 루트>\n<space>`) 앞 32자로 고정하고(없으면 Herdr 가 새 탭으로 만든다), 이름은 "팀"(`herdr-app do tab.rename`, 실패해도 계속). space 는 메인 터미널의 `herdr.space` 라벨.
   `hc run --bg --json --no-parent --no-notify --keep --name hteam-coord-<6자> --cwd <루트> --label herdr.space=<space> --label herdr.tab=<팀 탭> --label hteam.role=coordinator -- env HTEAM_ROLE=coordinator HTEAM_LAUNCH=<nonce> claude --model <모델> --effort <effort> [agents.claude.args] -- "<코디네이터 프롬프트>"`. 돌아오면 터미널 주소와 argv 를 `run.json` 에 기록한다.
   코디네이터 터미널이 메인 터미널과 같으면 거부한다.
   판정한 뒤 `pending_launch` 를 쓰기 직전에 `run.json` 의 `pending_launch`·`run_id`·`bound_nonce`·`bound_at`·코디네이터 기록이 바뀌었으면(다른 `up` 이 띄웠거나 코디네이터가 bind 했다) 띄우지 않고 exit 3 `launch_raced`.
   `hc run` 이 실패하면: hc 를 실행하지 못했거나, hc 가 거부했고 이름으로 찾아도 터미널이 없으면 이번에 바꾼 키만 되돌린다. 결과를 알 수 없으면(시간 초과·응답 유실) 이름으로 찾아 있으면 기록하고, 없으면 `--wait-run` 동안 그 nonce 의 bind 를 기다린다. 그래도 없으면 `pending_launch` 와 nonce 를 남기고 exit 1 `launch_uncertain`이다. 다음 `up` 은 띄운 지 180초 안이면 `starting`, 지나면 새로 띄운다.
3. 코디네이터 프롬프트: "`hteam bind` 를 실행하고 `.herdr-team/coordinator.md` 를 따른다".
4. `--wait-run S`: `run.json` 에 `run_id` 가 생길 때까지 기다린다.

`hteam bind`(코디네이터): 환경 변수 `HTEAM_ROLE=coordinator` 이고 `HTEAM_LAUNCH` 가 `run.json` 의 `pending_launch.nonce` 와 같을 때만 된다(아니면 exit 5). 그래서 `hteam up` 이 터미널 주소를 기록하기 전에 죽어도 코디네이터가 스스로 묶일 수 있다. `run.json` 에 이전 `run_id` 가 있으면 `horch run-use --id <run_id>`(이전 소유자가 끝났거나 lost 면 넘겨받는다), 없으면 `horch run-create --objective "<project.md 첫 줄>"`. 소유 탭이 팀 탭이 되어 워커가 그 탭에 붙는다. `run.json` 에 코디네이터 터미널·argv 와 `bound_nonce`·`bound_at`(bind 한 시각)을 기록한다. nonce 확인부터 `run-use`·`run-create` 와 이 기록까지 `state/run.lock` 을 쥔다. 그래서 그사이 `up` 은 기다렸다가 `launch_raced` 로 끝나고, 지난 코디네이터가 Run 을 차지한 채 `run.json` 만 새 코디네이터를 가리키는 일이 없다.

`/herdr-team:up`(메인을 다시 열 때): `hteam status` → 코디네이터가 죽었으면 `hteam up` → watch 가 없으면 띄움 → `hteam reask` 로 열린 질문을 하나씩 묻기 → 요약 표.

### 9.4 훅 (`hooks/hooks.json`)

모든 훅은 `.herdr-team/config.toml` 이 없으면 아무것도 하지 않는다. 훅 자체 오류는 막지 않고 `state/hook-errors.log` 에 남긴다.

역할 판별(SessionStart 에서, 확실할 때만 `state/sessions/<session id>` 에 캐시):

- 코디네이터: 환경 변수 `HTEAM_ROLE=coordinator` 이고 `HTEAM_LAUNCH` 가 `run.json` 의 `pending_launch.nonce` 와 같다. `run.json` 에 Run 이 아직 없어도 된다(bind 전).
- 워커: `$HC_TERMINAL_ID` 가 horch 의 active Dispatch 터미널이다(`horch --home … status` 의 `dispatch`). horch 가드는 에이전트를 exec 하기 전에 터미널을 등록하므로 SessionStart 때 이미 보인다. 태스크·종류·직무는 같은 `horch status` 가 주는 `dispatch.title`(`T-xxx rN 작업|리뷰 aK`)과 태스크 사양에서 정한다(3.3 의 herdr-orch 확장).
- 메인: 둘 다 아니다.
- horch 를 부르지 못하거나 결과가 모호하면 캐시하지 않고 다음 프롬프트에서 다시 본다.

| 훅 | 내용 |
|---|---|
| SessionStart | `state/plugin-root` 기록. 메인이면 "너는 메인이다, `/herdr-team:up` 을 실행한다" 와 열린 질문 수를 넣는다. Herdr 터미널 밖(`$HC_TERMINAL_ID` 없음)이면 tell·watch·answer 가 되지 않으니 Herdr 안에서 다시 열라는 안내도 넣는다 |
| PreToolUse (Edit·Write·MultiEdit·NotebookEdit) | 경로는 `..`·심볼릭 링크를 실제 경로로 푼 뒤 본다. 누구나 `state/` 를 고칠 수 없다. 코디네이터는 `.herdr-team/` 밖(프로젝트 밖 포함)을 고칠 수 없다. 메인은 `setup-mode` 가 아니면 제품 파일(`.herdr-team/`·`.claude/`·`docs/superpowers/`·`CLAUDE.md`·`AGENTS.md`·`.gitignore` 밖의 프로젝트 파일)을 고칠 수 없다. 프로젝트 밖은 메인에게 제품 파일이 아니다. 풀 수 없는 경로는 코디네이터·메인 모두 거부한다 |
| PreToolUse (AskUserQuestion) | 코디네이터 → 거부하고 `hteam notify --json` 안내. planner·director 워커 → `hteam ask-user` 안내. 다른 워커 → `horch ask` 안내. 메인 → outbox 질문의 `context` 를 먼저 보여 주지 않았으면 그 질문에 한해 한 번 거부 |
| PreToolUse (Bash) | 메인이 `horch` 를 직접 부르면 거부(`hteam tell` 안내) |
| Stop | 메인이고 코디네이터가 있는데 watch 가 없으면 턴을 끝내지 못하게 하고 watch 를 다시 띄우라고 한다. Herdr 터미널 밖(`$HC_TERMINAL_ID` 없음)의 메인은 watch 를 띄울 수 없어(exit 5) 막지 않는다 |

Codex 워커·리뷰어에는 Claude 훅이 걸리지 않는다. 그쪽은 `AGENTS.md` 의 규칙(owns 밖 커밋 금지, 리뷰어는 리뷰 파일만)과 리뷰 사전 검사·변조 검사로 막는다. Bash 로 하는 파일 수정(`sed -i` 등)은 훅이 막지 못한다(리뷰가 잡는다).

## 10. 기획 인터뷰 (planner)

orca-team 0.3 의 인터뷰를 옮긴다. 직무 문서 `roles/planner.md` 가 규칙을 담는다.

- 짧은 질문을 하나씩 `hteam ask-user` 로 한다. 선택 질문에는 예시·추천안·추천 사유를 붙인다. 앞 답과 모순되면 그것을 따로 묻는다.
- 체크리스트 12항목: 목적과 성공 기준, 사용자와 상황, 범위, 사용자 흐름, 화면 목록, 데이터와 상태, 오류, 비기능 요구, 기술 스택과 실행 환경, 인터페이스 계약, 브랜드 자산과 아는 레퍼런스, 범위 밖. 모두 "결정" 또는 "범위 밖"이 될 때까지 묻는다(질문 수 제한 없음). 기술적으로 뻔한 항목은 묻지 않고 요약의 "자동 결정"에 적는다.
- 마지막 질문은 확정이다. `context` 에 계획 핵심, 자동 결정, 태스크 그래프 표. 선택지 "확정 (추천)" / "수정할 부분 있음".
- 결과물: `docs/planning/spec.md`, `contracts.md`, `tasks.toml`, `interview.md`. 끝내기 전에 `hteam plan check --file docs/planning/tasks.toml` 이 통과해야 한다.
- 수정 라운드의 기획자는 먼저 `ask-user --pending` 과 열린 질문의 `--wait` 를 확인한다.
- 인터뷰는 프로젝트마다 한 번에 하나만(진행 중 planner 태스크가 둘이면 `start` 가 exit 3).

## 11. 디자인

### 11.1 디자인 디렉터 (director)

세 단계를 한 태스크 안에서 차례로 하고, 단계마다 `hteam ask-user` 로 사용자에게 고르게 한다(header 기본 "디자인").

1. **레퍼런스**: 실제 상용·인접 서비스 6–9개를 WebSearch·WebFetch 로 고른다. 화면은 Chrome DevTools MCP 로 연다(새 페이지 → 스크린샷 → 닫기, 자기가 연 페이지만 닫는다). 캡처는 저장소 밖 `~/.cache/herdr-team/refs/<프로젝트>/` 에 둔다. MCP 가 없거나 막히면 링크만 남긴다. 스타일 묶음 3–4개로 Claude Design 레퍼런스 보드를 만들고, `references.md` 와 `board/` 에 원본을 둔다. 사용자가 묶음을 고른다.
2. **톤 시안**: 서로 다른 톤 3안(색·글꼴·밀도·모서리·그림자 중 2가지 이상 다름) × 대표 화면 3개(대표·조밀·입력) = 9프레임을 한 캔버스에. 원본은 `pilots/`. 세부 수정 피드백이면 수정안 1개("확정 / 다시 수정"), 방향 전환이면 새 3안. 확정까지 반복하고 피드백과 결정은 `direction.md` 에.
3. **디자인 시스템**: Claude Design 의 Design System 타입(Artifact `quickstart`·`list scope: types` 로 찾는다). 토큰(밝은 테마 필수), 상태별 미리보기가 있는 컴포넌트(기본·hover·focus·disabled·error), 아이콘 세트(Lucide·Phosphor·Tabler 중 하나)를 담은 README, 대비 4.5:1·3:1. Codex 가 claude.ai 를 볼 수 없으므로 `docs/design/system/`(`tokens.json`, `README.md`, `components/`)에 사본을 둔다. 확정되면 `direction.md` 에 `design_system_url: <URL>` 줄.

디렉터는 래스터 에셋을 만들지 않는다. 승인 직무가 아니다(APPROVE 뒤 바로 `done`). `tasks.toml` 의 디렉터 태스크 owns 는 `["docs/design/direction.md", "docs/design/references.md", "docs/design/board/**", "docs/design/pilots/**", "docs/design/system/**"]` 로 좁힌다(owns 에는 `{…}`·쉼표를 쓰지 않는다. 4.1).

### 11.2 디자인 (designer)

- 화면마다 태스크 하나. owns `docs/design/screens/<화면>/**`, `assets/<화면>/**`.
- 계정 기본이 아니라 프로젝트 디자인 시스템으로 Claude Design 화면을 만든다. 화면 원본을 `docs/design/screens/<화면>/` 에 둔다(Codex 리뷰가 읽는다). 2단계 기본형은 원본(`index.html`·`notes.md`)을 만들고, Artifact 도구를 쓸 수 있으면 같은 화면을 claude.ai 아티팩트로 올려 보고서에 URL 을 적는다. 디자인 시스템·이미지·금지 목록 검사는 3단계다.
- 토큰을 새로 만들지 않는다. 모자란 값은 가장 가까운 토큰을 쓰고 보고서의 `### 시스템 추가 제안` 에 적는다.
- 래스터 에셋은 `hteam image`(12장)로 만들고 직접 보고 확인한 뒤 커밋한다.
- 보고서: 아티팩트 URL, 화면 목록, 시스템 URL, 추가 제안, 금지 목록 점검, 이미지 프롬프트와 수.
- 승인 직무(`user_approval_roles`): Codex 승인 뒤 `awaiting_user`.

### 11.3 개발 화면 규칙 (developer)

UI 기반 태스크가 `tokens.json` 을 CSS 변수·테마로 옮기고 공통 컴포넌트를 만든다. 화면 태스크는 토큰과 공통 컴포넌트만 쓴다(색·크기·간격·모서리·그림자 하드코딩 금지). 모자란 토큰은 만들지 않고 `horch ask` 로 묻는다.

### 11.4 보강과 일괄 승인

- 디자이너 태스크가 모두 `awaiting_user` 가 되면 코디네이터가 최신 라운드 보고서의 추가 제안을 모아 디렉터 보강 태스크 하나를 만든다(owns `docs/design/system/**`, `docs/design/direction.md`). 끝나면 제안한 화면마다 `fix --supplement <보강 태스크>`, UI 기반이 이미 `done` 이면 "토큰 갱신" 개발 태스크를 더한다.
- `hteam design-review`: `awaiting_user` 인 승인 직무 태스크가 하나 이상 있고, 진행 중(`working`·`reviewing`·`approved`·`changes`·`launch_failed`)이거나 지금 바로 시작할 수 있는(의존 충족·잠금 비어 있음) 승인 직무 태스크가 없을 때, 그 순간 `awaiting_user` 인 승인 태스크 전부를 한 묶음으로 outbox 에 `approval` 항목 하나로 쓴다. 승인 태스크 사이에 비승인 태스크가 끼어 있으면(승인 → 비승인 → 승인) 앞 묶음을 먼저 묻고, 뒤 승인 태스크는 다음 묶음이 된다(모든 승인 태스크가 대기 상태가 되기를 기다리면 서로 기다리다 멈춘다). `context` 에 태스크마다 한 줄과 링크(보고서의 마지막 claude.ai 아티팩트 URL, `design_system_url` 은 빼고). 선택지 "모두 승인" / "수정 요청". 같은 태스크·라운드 묶음을 이미 물었으면 exit 3. 기록은 `state/design-review.json`. 한 (태스크, 라운드)는 한 번만 묻는다: 이미 물은 태스크가 답을 기다리는 동안 새로 awaiting_user 가 된 태스크는 다음 묶음이 되고, 수정 라운드는 라운드가 달라 다시 묻는다. 링크가 없으면 보고서 경로를 보인다. 선택지 label 은 render 규칙(7.4)대로 `모두 승인 (추천)` / `수정 요청` 이다. 묶음 기록을 먼저 쓰고 outbox 항목에 묶음 id 를 붙인다. 그 사이 죽으면 다음 호출이 그 묶음을 마저 쓴다(같은 묶음을 찾는 일은 outbox 잠금 안에서 한다. 두 번 묻지 않는다). 선행(직간접)이 그 태스크의 현재 라운드를 연 뒤에 새 라운드를 열었으면 그 태스크는 stale 이다: 옛 선행을 보고 만들었으므로 묻지 않는다(exit 3 `approval_stale`, 읽기만 하는 검사. 기준은 그 라운드의 워커를 새로 띄울 때 본 선행의 끝난 라운드(선행이 `done`·`awaiting_user`·`dropped` 면 그 라운드, 아니면 앞 라운드(`approved` 도 작업 워커가 아직 살아 있을 수 있어 앞 라운드), 그때 상태가 없던 선행은 0), 이 기록이 없는 옛 라운드는 라운드를 연 시각. 시작 예약이 프로젝트 잠금 안에서 본 라운드를 기존 horch Task 없이 새로 띄울 때만 launched 와 같은 저장에 남긴다. 같은 라운드 복구가 기존 Dispatch 를 이어 붙이거나 다시 띄우면 처음 기록을 그대로 둔다). 일괄 승인 결정이 의존 태스크를 함께 고치므로 이것은 결정 밖에서 선행을 고친 경우다.
- 코디네이터가 답을 해석한다: 승인이면 `accept`(`awaiting_user` → `done`), 아니면 해당 태스크 `fix --note`, 그 태스크에 의존하는 승인 태스크도 이어서 `fix`. 수정 요청이 가리키지 않은 태스크는 승인으로 본다(모호하면 다시 묻는다). 해석한 것은 `hteam design-review --decide <out-id> --json -`(`{"fix": {태스크: 사용자 요청}}`, 모두 승인이면 빈 `fix`)로 넘긴다. hteam 은 결정을 한 번 계산해 묶음 기록에 먼저 쓴다: 고칠 태스크(지목된 태스크와 그것에 직간접으로 의존하는 승인 태스크 전부, 다른 묶음 포함, 리뷰 중·승인됨이어도)마다 그때의 라운드와 사용자 요청, 승인할 태스크마다 그때의 라운드. 아직 시작하지 않은 의존 태스크는 고칠 것이 없고(선행이 다시 승인된 뒤 시작한다), 끝난 의존 태스크는 고칠 수 없어 알린다. 그다음 기록대로 `fix --round`·`accept --round` 를 한다. 수정 라운드는 바로 띄우지 않는다(`launch_failed`, queued). `start-ready` 의 의존 검사(승인 직무 선행은 awaiting_user·done 이어야 끝난 것)가 선행의 수정 라운드가 다시 승인될 때까지 기다리게 한다. 다시 부르면(재시작·다시 온 답) 기록대로 이어 하고 기록한 라운드가 지난 항목은 다시 하지 않는다. 결정이 끝나지 않은 동안에는 다른 묶음의 결정과 새 질문을 하지 않고(`decision_pending`) `status` 의 next 가 그 결정을 다시 하는 명령이다. 시작 예약(프로젝트 잠금 안)은 끝나지 않은 결정이 고치는 태스크와 그 의존 태스크를 띄우지 않고, `start-ready` 는 의존도 다시 본다. 결정이 끝나지 않은 동안 결정 밖의 `fix`·`accept` 도 그 결정이 고치는 태스크와 그 의존 태스크를 거부한다(시작과 같은 `held_by_decision` 검사, exit 3 `decision_pending`. `fix` 는 워커를 정리하기 전에 거부한다. 그 결정 자신의 fix·승인 항목은 막지 않는다). 지목된 태스크의 라운드가 다른 결정 때문에 이미 바뀌었으면 처리한 것으로 넘기지 않고 지금 라운드에서 그 요청(과 그 라운드의 앞 요청)으로 다시 고친다. 결정이 태스크를 다시 고칠 때 그 태스크의 지금 라운드가 아직 반영하지 않은 사용자 요청 라운드면(`awaiting_user` 가 아니면) 지목된 태스크든 의존 태스크든 그 요청을 새 라운드에 잇는다(이번 요청 → 앞 요청 → 선행의 요청 순서, 이미 든 요청은 다시 적지 않는다). 지목된 태스크가 끝났으면 결정하지 않는다(`decision_conflict`, 메인에 알린다). done 을 쓴 뒤 applied 전에 멈췄으면 다시 부를 때 applied 를 적는다. 다 하면 hteam 이 `applied` 를 적는다. `hteam wait` 는 답에 `design_review`(묶음 태스크의 `pending`, 결정 상태, 상태를 읽지 못한 `unknown`)를 붙인다. 묶음 태스크의 상태 파일을 읽지 못하면 결정하지 않는다. 메인은 사용자가 `수정 요청` 을 고르면 무엇을 고칠지 물은 뒤 `수정 요청: <내용>` 한 줄로 답한다. 결정으로 연 라운드의 사양은 수정 블록에 "사용자 요청"으로 적는다(결정만 사용자 요청으로 적고, `awaiting_user` 에서의 일반 `fix`·`--supplement` 는 아니다. 일반 `fix` 가 아직 사용자에게 다시 보이지 않은 사용자 요청 라운드를 닫으면(워커 실패 등) 그 요청을 `--note` 와 합쳐 잇고 사용자 요청 라운드로 둔다). 그 라운드 기록에 마지막으로 리뷰된 라운드의 판정과 라운드(`prior_verdict`·`prior_review_round`)를 남겨, 리뷰가 수정 요청이었던 태스크는 사용자 요청과 함께 그 리뷰 지적도 다룬다.

### 11.5 AI 티 금지 목록 (`design-rules.md`)

orca-team 의 금지 규칙 10개를 옮긴다(이모지 장식, 왼쪽 강조 테두리, 파랑·보라 그라디언트 등. 목록 원문은 구현 계획에 적는다). 워커는 보고서에서 스스로 점검하고, 리뷰어가 디자인 절로 다시 본다.

### 11.6 자동 검사 (`hteam lint`)

리뷰 대상에서 바뀐 파일만 본다(`.html .css .scss .js .jsx .ts .tsx .vue .svelte .md .json`, `references.md`·`docs/planning`·`docs/tasks`·`docs/reviews` 제외, 1 MB 넘는 파일 제외). 찾는 것: 이모지(U+1F000–1FAFF, BMP Emoji_Presentation, `X+FE0F`), 2px 이상 왼쪽 강조 테두리(CSS·JSX·Tailwind `border-l/s-N` + 색), 한 그라디언트 안 파랑(190–245°)과 보라(245–300°)(oklch, Tailwind `from/via/to` 포함). 출력 `file:line: 패턴(발췌)`, 50개까지. 리뷰 프롬프트에 경고로만 넣는다(판정은 리뷰어).

## 12. 이미지 (`/herdr-team:image`, `hteam image`)

- 디자인 워커(Claude)가 자기 pane 에서 부른다. 직무가 아니고 pane 도 따로 띄우지 않는다. Codex 가 만들고 부른 Claude 가 결과를 보고 검토한다.
- 인자: `--n 1–8`, `--out <폴더>`(기본 `./generated/`), `--ar`, `--transparent`, `--ref <이미지>`, `--background`, 프롬프트.
- 사전 점검: `codex features` 의 `image_generation`. 없으면 exit 12.
- 이미지마다 실행 폴더 하나, 호출 하나에 이미지 하나. `scripts/codex-run.sh --profile image` 로 `codex exec` 를 부른다. 프롬프트는 Codex 내장 `image_gen` 도구를 쓰고 마지막 줄에 PNG 절대 경로를 쓰게 한다.
- 결과: `result.txt` 마지막 줄의 파일을 `--out` 에 복사한다(덮어쓰지 않고 `-v2` 등). `sips` 로 크기·형식을 확인하고, 투명 배경이 빠졌으면 크로마키로 지운다. 거절은 자동으로 다시 시도하지 않는다.
- `n ≥ 3` 이면 워커가 Bash 백그라운드로 돌린다.

`scripts/codex-run.sh`(orca-team 래퍼의 규칙을 옮긴다):

- 한 번 실행하고 이유를 보고한다(정책 없음, 재시도는 부르는 쪽).
- stdin `/dev/null`, 프롬프트는 파일로, `-C <cwd>`, `--json` 과 `--output-last-message` 함께, effort 는 `-c model_reasoning_effort=`, `[agents.codex].args`(기본 `--disable=hooks`)를 붙인다.
- 프로필: `image` 시간 제한 900초, 진행 신호 없음 한도 300초. 시간 초과면 프로세스 그룹을 죽인다.
- 판정은 exit 코드보다 `status.json` 의 `terminal_event` 를 먼저 본다. exit: 0, 10(시간 초과), 11(멈춤), 12(codex 없음), 1, 2(인자 오류), 130(중단).

## 13. 오류와 복구

`hteam status` 는 태스크마다 `next`(다음 명령)를 준다. 원칙은 herdr-orch 와 같다: 끝났다는 확실한 증거가 있을 때만 바꾸고, 모르면 그대로 둔다.

| 상황 | 처리 |
|---|---|
| 작업 워커 `observed idle`(done 없이 턴을 마침) | 코디네이터가 `horch send --to dispatch:D` 로 이어가거나 done 을 요구한다 |
| 작업 워커 `observed exited`·`lost` | `horch worker-abandon` 뒤 `hteam fix T --note "이전 워커가 done 없이 끝남"` |
| 작업 워커 `observed blocked`(권한 확인 등) | 코디네이터가 `worker-show` 로 화면을 보고 메인에 질문으로 올린다. 키는 누르지 않는다 |
| 작업 워커 `worker_done` failed | `hteam fix T --note "<요약>"`. 상한에 닿으면 사용자에게 |
| 리뷰어가 done 없이 끝남, 결과 파일·VERDICT 없음 | `review-finish` 가 정리(abandon·release)하고 한 번 다시 띄운다. 두 번 실패하면 메인에 질문, 다시 하면 `review --retry` |
| 리뷰 중 제품 변조 | 자동으로 다시 하지 않는다. 증거를 남기고 메인에 질문. 사용자가 정리한 뒤 `review --retry` |
| 실행자가 horch 실행 뒤 기록 전에 죽음 | 다음 `start`·`review` 가 같은 제목의 horch Task 를 찾아 이어 붙인다(5.4) |
| 성공 보고 뒤 커밋 안 된 변경 | 리뷰 사전 검사가 `changes` 로 보낸다. 수정 라운드가 커밋한다 |
| 메인의 답 전송이 끊김 | 다시 보낸다. `hteam wait` 가 `out-id` 로 중복을 표시한다 |
| 질문 답을 읽은 뒤 워커가 죽음 | 답은 ack 전까지 다시 조회된다(`--pending`·`--history`) |
| `launch_failed` | `hteam start T`(같은 라운드, 같은 horch Task 를 `--retry` 로) |
| 이어 붙인 작업 워커가 이미 끝남(기록 전 실행자 사망 뒤 done) | 그 `worker_done` 은 다시 오지 않는다. `start`(`start-ready` 의 `started` 행) 결과의 `next`(`review` 또는 `fix --note`)를 따르고, 라운드 상한이면 `hint` 대로 메인에 묻는다 |
| hteam 커밋이 워커 커밋의 `index.lock` 과 겹침 | 경로 지정 커밋이 10초까지 기다렸다 다시 한다. 그래도 남으면 메인에 알린다(지우지 않는다) |
| 코디네이터가 죽음 | 메인의 `/herdr-team:up` 또는 `hteam up` 이 다시 띄우고 `hteam bind` 가 `run-use` 로 넘겨받는다. ack 안 된 메시지는 다시 온다 |
| 메인이 꺼짐 | `/herdr-team:up` 이 `reask` 로 열린 질문을 다시 묻는다 |
| 설정이 깨짐 | 설정을 읽는 명령은 exit 2. 통신 명령은 계속 동작. `status` 에 `config_error` |
| 상태 파일과 horch 가 어긋남 | `status` 가 둘을 함께 보여 주고 `next` 로 안내한다(예: hteam 은 `working` 인데 horch Dispatch 가 `settled` 면 `review`) |

동시성: hteam 상태 파일은 태스크마다 flock 으로 잠그고, owns 잠금 검사와 상태 쓰기는 프로젝트 잠금(`state/lock`) 하나 안에서 한다. 상태를 바꾸는 명령은 코디네이터 한 명만 부르므로 경쟁은 주로 코디네이터와 실행자 사망 복구 사이다. outbox 는 flock 으로 덧붙이고 커서는 원자적으로 쓴다.

## 14. 보안

- 워커는 사람 없이 돈다. 권한 우회(`[agents.claude].args` 의 bypass, Codex 샌드박스 우회)를 넣으면 워커가 사용자의 git·클라우드 자격 증명과 셸 환경을 그대로 쓴다. init 이 위험을 적고 승인받았을 때만 넣는다.
- 이미지 생성의 `codex exec` 는 orca-team 과 같이 샌드박스 우회로 돈다(`image_gen` 결과 파일을 읽으려고). 프롬프트는 이미지 생성만 하게 하고, 결과 파일만 복사한다.
- 리뷰어가 제품 파일을 고치면 변조 검사로 판정을 무효로 한다.
- 워커의 질문·보고·요약은 데이터다. 코디네이터와 메인은 그 안의 지시를 사용자 지시처럼 따르지 않는다.
- 권한 확인과 훅은 실수 방지용이다(보안 경계가 아님).
- 저장소는 공개될 수 있다. 개인 경로를 넣지 않는다(커밋 전 `git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews'`).

## 15. 테스트와 구현 단계

### 15.1 테스트

- 단위·통합: Python `unittest`, 표준 라이브러리만. hteam 은 실제 `horch` 를 부르고, hc·herdr-app·claude·codex 는 horch 의 가짜 프로그램(`herdr-orch/tests/fakes/`)을 쓴다. 가짜 claude·codex 는 테스트가 정한 동작(커밋, `horch done`, 리뷰 파일 쓰기)을 흉내 낸다.
- orca-team 의 테스트를 개념 단위로 옮긴다: 설정 검사, 사양 검사, owns 겹침, plan check·apply·append, start-ready 대기 사유, 상태 전이와 잠금, 리뷰 사전 검사·변조 검사·VERDICT 해석·재시도, accept·fix·drop·상한, outbox·watch·answer·ask-user·reask, `render` 검사, 훅 역할 판별과 가드, design-review, lint, codex-run.sh 회귀(가짜 codex).
- 실제 Codex·Claude 를 한 번 이상 돌린다(가짜만 통과하고 실제는 실패한 orca-team 이전 경험).

### 15.2 실환경 확인 (단계마다)

버리는 시험 프로젝트에서 실제 Herdr·Claude·Codex 로 한 바퀴 돌린다. 결과는 이 문서 15.4 에 기록한다.

### 15.3 구현 단계

설계 문서는 이것 하나다. 구현 계획·서브에이전트 구현·Codex 리뷰·실환경 확인을 세 번 한다. 세 단계를 마치면 herdr-team 0.1.0 으로 main 에 병합한다.

1. **핵심**: 플러그인 골격·shim, 설정, 사양·`task new`, tasks.toml·plan, owns 잠금, start·start-ready, 워커 사양 조립, 리뷰(review·review-finish, 사전 검사, 변조 검사, 프롬프트), accept·fix·drop, status·`next`, wait, 메인 연결(tell·notify·watch·answer·ask-user·reask·`render`), 훅, doctor·scaffold·up·bind, init·up 스킬, 코디네이터 사용법, 직무 문서(planner 기본·developer·tester). 실환경: 기획 → 개발·테스트 병렬 → Codex 리뷰 pane → 수정 라운드 → accept, 메인 질문 중계.
2. **기획 인터뷰와 승인**: 인터뷰 체크리스트·확정 질문(10장), 승인 직무와 `awaiting_user`, `design-review`, designer 기본. 실환경: 사용자가 인터뷰에 답하고 일괄 승인.
3. **디자인**: 디렉터 3단계(DevTools MCP, Claude Design), designer 전체, 보강 루프, `hteam image`·`codex-run.sh`, 금지 목록·`lint`, 리뷰 디자인 절. 실환경: 디렉터 → 화면 디자인 → 일괄 승인 → 구현.

### 15.4 실환경 확인 결과

(단계마다 채운다.)

#### 1단계 (2026-11-06)

환경: hc 0.1.18, Claude Code 2.1.318, codex-cli 0.166.0, Python 3.14. 버리는 시험 프로젝트("할 일 CLI", 파이썬 표준 라이브러리)를 새 space 에 만들었다. 이 저장소는 디렉터리 마켓플레이스로 시험 프로젝트 범위(project scope)에만 등록·설치했다. 디렉터리 소스라 Claude Code 는 설치 캐시가 아니라 저장소 폴더를 바로 읽었다(`CLAUDE_PLUGIN_ROOT`·`state/plugin-root` 가 저장소의 `herdr-team/`). 그래서 실행 중에 고친 결함이 다음 hteam 호출부터 바로 반영됐다. 메인·코디네이터·Claude 워커는 `--permission-mode=bypassPermissions` 로 돌았다(시험 프로젝트에서만).

- init·doctor·scaffold·up·bind: doctor 통과(경고는 `chrome_devtools_mcp` 하나). scaffold 가 파일 11개를 만들었다. 4단계 표를 AskUserQuestion 한 번으로 승인받아 developer owns 에 `pyproject.toml`·`README.md` 를, `[agents.claude].args` 에 `--permission-mode=bypassPermissions` 를 넣었다(메인이 자격 증명 위험을 표에 적었다). `up --wait-run 180` 이 "팀" 탭(`tab_renamed: true`)에 `hteam.role=coordinator` 라벨로 코디네이터를 띄웠고, 코디네이터가 `bind` 로 Run 을 만들었다. 메인이 watch 를 백그라운드로 띄우고 `setup-done` 뒤 `chore: herdr-team 세팅` 을 커밋했다. Claude 폴더 신뢰 창은 메인에서 한 번 떴고 운영자가 넘겼다. 같은 폴더의 코디네이터·Claude 워커에는 다시 뜨지 않았다.
- 기획 인터뷰 중계(ask-user → watch → AskUserQuestion → answer): 확인했다. 메인 `tell` → 코디네이터가 `task new`, `spec: T-001` 커밋, `start` → 기획자가 `ask-user` 로 저장 위치를 물음(`context` 없음) → 메인 watch 가 끝나 AskUserQuestion → 운영자가 추천안을 고름 → `answer` → 기획자가 `interview.md` 에 적고 `--ack`. tasks.toml 은 developer·tester 두 태스크(의존 없음, owns 분리)와 둘에 의존하는 통합 검증(tester) 하나였고 `plan check` 를 통과했다. 기획 리뷰어는 Codex pane 으로 팀 탭에 떴다.
- 개발·테스트 병렬(start-ready, owns 잠금): 기획 accept 뒤 `plan apply` → `start-ready` 가 T-002(developer)·T-003(tester)을 동시에 띄웠다(`working` 둘, 팀 탭 pane 둘). owns 가 겹치지 않아 잠금 대기는 없었다. 통합 검증 T-004 는 둘이 done 된 뒤 `start-ready` 가 띄웠다.
- Codex 리뷰 pane·review-finish·판정 커밋: 리뷰 다섯 번 모두 Codex pane(`--disable=hooks`)으로 팀 탭에 떴다. review-finish 가 `docs/reviews/T-xxx/rN.md` 와 `[T-xxx] review rN: …` 커밋을 남겼다. 병렬 커밋이 리뷰와 겹친 두 번(T-003 r1 리뷰 중 T-002 r2 커밋, T-002 r2 리뷰 중 T-003 의 리뷰 커밋)은 변조 검사가 진행 중 태스크와 `docs/reviews/**` 를 빼서 통과했다. 처음 보는 폴더라 첫 Codex 리뷰어에서 Codex 폴더 신뢰 창이 떴다(`--disable=hooks` 로도 사라지지 않는다). 운영자가 그 폴더만 신뢰("Trust and continue")로 넘겼고 그 뒤 리뷰어에는 뜨지 않았다.
- 수정 라운드(fix → r2 → 리뷰): 두 갈래 모두 확인했다. 유도: 사용자 역할로 "T-002 r1 을 failed 로 끝내 달라" 를 보내 메인 → 코디네이터 → `horch send` 로 워커에 전달했다. r1 `worker_done` failed → `next` 의 `fix --note` → r2. 자연 발생: r2 의 Codex 리뷰가 REQUEST_CHANGES(P2 둘) → `fix` → r3 → APPROVE. `docs/tasks/T-002/report.md` 에 r1–r3 절이 있다.
- accept·release 로 pane 닫힘: 네 태스크 모두 `done`. 끝난 워커·리뷰어 pane 은 release 로 닫혀 팀 탭에 코디네이터만 남았다. 시험 프로젝트 테스트 58개가 통과했다.
- 열린 질문 확인:
  - `hc get --json` 의 `parent` 는 문자열 주소다(예: `"t45"`). `--no-parent` 로 띄우면 `null` 이다. parent 는 `hc run` 을 부른 쪽의 `HC_TERMINAL_ID` 를 따른다. `outbox.require_main` 은 실제 메인(parent `null`)을 메인으로 받았고, 코디네이터·워커 아래에서 띄운 터미널은 조상 라벨로 거부했다.
  - 터미널 id 는 kill·rm 뒤 다시 쓰이지 않았다(t45–t4b 를 지운 뒤 새 터미널이 t4c·t4d). core 를 다시 띄운 뒤의 재사용은 확인하지 않았다(사용자 core 를 멈추지 않는다).
  - `status`·`wait` 의 `next` 는 코디네이터가 그대로 실행했다(`review`·`review-finish`. `fix` 는 note 를 바꿔서). `worker-show` 힌트 문자열은 Run 소유 터미널의 셸에 그대로 넣어 실행했고 성공했다.
- 발견한 문제와 처리:
  - 리뷰어 규칙 문구(고침): "추적 파일 내용이 바뀌거나 HEAD 가 움직이면 판정이 무효" 를 다른 워커·코디네이터의 커밋까지로 읽은 Codex 리뷰어가 병렬 커밋마다 코디네이터에게 묻거나 escalate 했다(질문 2건, escalation 1건). 리뷰 프롬프트와 `AGENTS.md` 절에 "무효는 리뷰어 자신의 쓰기뿐이고 병렬 커밋으로 HEAD 가 움직이는 것은 정상"이라고 적었다. 고친 뒤에는 병렬 커밋과 겹친 리뷰가 없어 실환경으로 다시 확인하지 못했다. scaffold 는 있는 `AGENTS.md` 를 덮어쓰지 않으므로 이미 세팅한 프로젝트는 그 절을 손으로 고쳐야 한다.
  - 하네스: `herdr-app shot` 은 창이 앞에 없으면 지난 프레임을 그대로 준다. pane 배치는 `herdr-app ls` 로 확인했다. 코디네이터 터미널 밖에서 `hteam status` 를 보면 `horch_error`(not_owner)라 태스크 상태만 보인다(설계대로).
  - 운영 주의: 시험용 `hc run` 에는 `--no-notify` 를 붙인다. 붙이지 않은 확인용 터미널이 끝날 때 종료 알림이 띄운 터미널의 입력란에 들어갔다. 코디네이터 아래에서 띄운 확인 터미널의 종료 소식도 코디네이터에게 갔다(코디네이터는 관계없는 터미널로 보고 넘어갔다).

#### 2단계 (2026-11-07)

환경: hc 0.1.18, Claude Code 2.1.319, codex-cli 0.166.0, Python 3.14, Node 22. 버리는 시험 프로젝트("할 일 목록 웹 페이지", 정적 HTML·JS)를 새 space 에 만들고 플러그인은 시험 프로젝트 범위에만 설치했다(끝나고 제거). 1단계처럼 디렉터리 소스라 실행 중에 고친 저장소 파일이 바로 반영됐다. 메인·코디네이터·Claude 워커는 `--permission-mode=bypassPermissions` 로 돌았다(시험 프로젝트에서만).

- init(designer 직무 유지): doctor 통과(경고는 `chrome_devtools_mcp` 하나). scaffold 가 `.herdr-team/roles/designer.md` 를 포함한 파일 12개를 만들었고 `config.toml` 에 `[roles.designer]`·`user_approval_roles = ["designer"]` 가 있었다. 4단계 표는 designer 를 "유지(목록·통계 화면이 있음)"로 적어 빼자는 제안이 없었다. 제안 두 건(developer owns 에 `index.html`·`package.json`, `[agents.claude].args` 에 `--permission-mode=bypassPermissions`)을 "전부 승인 (추천)" 으로 받았다. `up` 이 "팀" 탭에 코디네이터를 띄웠고 코디네이터가 `bind` 했다. 메인이 watch 를 백그라운드로 띄우고 `chore: herdr-team 세팅` 을 커밋했다.
- 기획 인터뷰(체크리스트 질문, 확정 질문, 수정할 부분 있음 → 다시 확정): 기획자가 `ask-user` 로 한 번에 하나씩 9개를 물었다(사용 환경, 목록 기능, 항목 정보, 통계 내용, 화면 이동, 삭제 방식, 실행 방법, 브랜드, 성공 기준). 모두 예시·추천안·추천 사유가 있었고 운영자는 추천안을 골랐다. 빌드 도구·저장 방식처럼 요청에 이미 있는 것은 묻지 않았다. 비기능 요구와 인터페이스 계약은 `자동 결정` 이었다. 확정 질문은 header "기획 확정", `context` 에 계획 핵심·자동 결정·태스크 그래프 표, 선택지 `확정 (추천)`/`수정할 부분 있음` 이었다. 첫 확정에는 Other 로 수정을 답했다. 계획한 글("완료한 항목 수도")은 통계 질문의 추천안(완료율·막대·전체/완료/남은 개수)에 이미 들어 있었다. 그래서 "완료율이 100%가 되면 축하 문구도" 로 바꿔 답했다. 기획자가 spec·contracts·tasks.toml·interview.md 를 고치고 `plan check` 를 다시 통과시킨 뒤 확정을 다시 물었고 `확정 (추천)` 을 받았다. 기획 리뷰 r1 의 지적(아래)으로 문서를 고친 r2 에서도 기획자가 확정을 다시 물었다. `interview.md` 체크리스트 12항목은 `결정` 10, `자동 결정` 2 였다. tasks.toml 은 화면마다 designer 태스크(`list-screen`·`stats-screen`, owns `docs/design/screens/<화면>/**`·`assets/<화면>/**`)와 둘에 의존하는 `app-core`(developer), 화면별 구현 `list-app`·`stats-app`(developer), `tests`(tester) 6개였다. `plan check` 를 통과했다(4 그룹). 메인은 `context` 가 있는 질문 다섯 개 가운데 셋은 그대로 보였다. 둘(첫 확정 질문, 첫 일괄 승인)은 보이지 않고 물었다. 훅이 한 번 거부했지만 메인은 다시 보이지 않고 물었고, 설계대로 두 번째는 통과했다(아래).
- 기획 리뷰어의 `ask-user --history` 확인: Codex 리뷰어가 `hteam ask-user --task T-001 --history` 로 질문 11개와 답, 수정 요청 뒤의 마지막 확정 답, 그 뒤에 질문이 없음을 확인했다. 확정 질문의 `context` 태스크 그래프를 tasks.toml 과 견주고 `plan check` 를 직접 돌렸다. r1 은 REQUEST_CHANGES(P2: 제목 입력 칸 `maxlength=200` 과 "200자 초과는 오류 문구" 가 충돌)였다. `fix` → r2 에서 기획자가 고치고 확정을 다시 물었다. r2 APPROVE → accept → `plan apply`(6 tasks) → `start-ready` 가 designer 둘을 동시에 띄웠다(팀 탭 pane 둘). 첫 Codex 리뷰어에서 Codex 폴더 신뢰 창이 한 번 떴다(선택지 "Trust and continue"/"Quit". 이 폴더만 신뢰).
- designer 병렬, Codex 리뷰, accept → awaiting_user, approval_not_ready: 두 designer 워커가 Artifact 도구로 화면을 claude.ai 아티팩트로 올리고 보고서에 `- 아티팩트: https://claude.ai/artifact/…` 줄을 남겼다(워커 pane 에서 Artifact 도구가 동작했다). 화면 원본은 `docs/design/screens/<화면>/` 의 `design.md`·`mockup.html` 이었다. 직무 문서의 `index.html`·`notes.md` 와 다른 까닭은 아래 결함이다. 통계 화면은 r1 APPROVE → accept → `awaiting_user`(출력 `next` 가 `design-review`) → `design-review` 가 exit 3 `approval_not_ready`(blockers: 목록 화면 working). 목록 화면은 r1 에서 Codex 가 REQUEST_CHANGES(P2: 버튼 글자 대비)를 줘 `fix` → r2 APPROVE → accept → `awaiting_user`. 그다음 `design-review` 가 `dr-0001`(목록 r2, 통계 r1)을 out-0020 으로 썼다. `context` 는 태스크마다 한 줄과 아티팩트 링크였다. 승인 대기 태스크의 작업 pane 은 accept 때 닫혔다.
- design-review 첫 묶음 → 수정 요청 → design_review 주석 → fix(사용자 요청) + accept: 운영자가 `수정 요청` 을 고르자 메인이 어느 디자인을 어떻게 고칠지 대화로 물었다. "통계 화면의 완료율 숫자를 더 크게" 라고 답하자 메인이 `hteam answer out-0020 "수정 요청: T-003 통계 화면의 완료율 숫자를 더 크게"` 를 보냈다. 코디네이터의 `wait` 결과에 `design_review`(`batch: dr-0001`, `approve_all: false`, `decision: null`, `applied: false`, `unknown: []`, 두 태스크 `pending: true`)와 `--decide` 안내 hint 가 붙었다. 코디네이터가 `design-review --decide out-0020 --json -` 에 `{"fix": {"T-003": "…"}}` 를 넘겼다. hteam 이 결정(`fix` 통계 r1 + 요청, `accept` 목록 r2, `skipped` 없음)을 먼저 기록했다. 그다음 통계 화면에 queued 수정 라운드 r2(`from_user`·`queued`, 사양 수정 블록에 "사용자 요청: …")를 만들고 목록 화면을 accept → `done` 했다. `applied` 도 hteam 이 적었다. `start-ready` 가 r2 를 띄웠고 `app-core` 는 통계 화면을 기다렸다(`deps`). 두 화면 사이에 의존이 없어 의존 태스크를 함께 고치는 경로는 나오지 않았다.
- 둘째 묶음 → 모두 승인 → developer·tester 시작 → 모두 done: 통계 r2 Codex APPROVE → accept → `awaiting_user` → `design-review` 가 `dr-0002`(통계 r2 하나)를 out-0022 로 썼다. 메인이 `context` 를 그대로 보인 뒤 물었고 `모두 승인 (추천)` → `--decide` 에 `{"fix": {}}` → accept → `done`. `start-ready` 가 `app-core` 를 띄웠다(`basis` 는 목록 2·통계 2). 그다음 화면별 구현 둘이 병렬로, 마지막에 tester 가 떴다. 넷 모두 첫 라운드에 APPROVE 였다. 일곱 태스크 모두 `done` 이고 시험 프로젝트 `node --test` 107개가 통과했다. 통계 화면 보고서에 `## r1`·`## r2` 절(사용자 요청과 반영 표)이 있고 `design-review.json` 에 묶음 둘과 결정 둘이 있다. 끝난 워커·리뷰어 pane 은 release 로 닫혀 팀 탭에 코디네이터만 남았다.
- 발견한 문제와 처리:
  - planner 문서가 designer 산출물 이름을 말하지 않았다(고침). 기획자가 designer 태스크의 target·acceptance 에 `design.md`·`mockup.html` 을 지어 적었고 designer 는 직무 문서(`index.html`·`notes.md`) 대신 사양을 따랐다. planner 문서의 tasks.toml 절에 "designer 태스크는 직무 문서의 산출물 이름을 그대로 쓴다" 를 적었다. 시험 프로젝트의 `roles/planner.md` 는 scaffold 때 복사한 것이라 이번 실행에는 반영되지 않았다.
  - 메인의 `context` 표시(에이전트 판단, 고치지 않음): 첫 확정 질문과 첫 일괄 승인에서 메인이 `context` 를 텍스트로 출력하지 않았다. 한 줄 요약을 narration 으로만 남기고 AskUserQuestion 을 불렀다. 훅이 한 번 거부했고 거부 글에 `context` 가 접혀 보였다. 메인은 다시 출력하지 않고 물었고 두 번째는 설계대로 통과했다. 나머지 셋은 그대로 보였다. "한 번만 거부" 를 바꿀지는 3단계에서 정한다.
  - 하네스: 사용자 전역 플러그인의 훅(쓰기 전 사실 확인 게이트)이 워커의 첫 Write 를 거부하는 일이 잦았다(워커가 다시 써서 진행). `hc send` 는 질문 창이 뜬 터미널에 `--force` 없이는 쓰지 않는다(Other 답에 `--force`). Codex 리뷰어는 승인 정책 때문에 브라우저 도구를 쓰지 못해 화면은 코드 대조로만 봤다. `start-ready` 의 `deps` 대기 detail 은 끝난 선행까지 모든 선행을 적는다(1단계부터 그렇다. 판단에는 영향 없음).
- 남은 것(사용자에게 알림): `~/.claude/plugins/cache/herdr-team/` 복사본(uninstall 뒤에도 남는다), `~/.codex/config.toml` 의 시험 폴더 신뢰 항목, `~/.claude.json` 의 시험 폴더 항목, `~/.claude/projects/` 의 시험 세션 기록, 시험 세션들의 스크래치패드, designer 워커가 사용자 claude.ai 계정에 올린 아티팩트 둘(비공개). 플러그인 CLI 가 `~/.claude/plugins/installed_plugins.json` 을 다시 쓰면서 표준이 아닌 최상위 `enabledPlugins` 키(context-mode 가 넣은 것)가 빠졌다(설정 파일의 같은 항목은 그대로다).

## 16. 범위 밖

- git worktree 로 워커 격리(작업 폴더 하나와 owns 잠금으로 한다).
- 다른 머신의 Herdr(원격 core).
- Claude·Codex 밖 에이전트.
- 한 프로젝트에서 기획 인터뷰를 동시에 둘.
- herdr-app mod(패널 UI). 상태는 `hteam status` 와 pane 으로 본다.

## 부록 A. orca-team 대응

| orca-team | herdr-team |
|---|---|
| `orch` CLI | `hteam` CLI |
| Orca Run 메일함(`orca orchestration send/check/reply`) | horch 메일함(`horch send/check/reply`) |
| `orca orchestration worker-start --worktree current` | `horch worker-start`(팀 탭 pane) |
| `worker-retain/release/show`, Orca 생존 판정 | horch `worker-retain/release/show`, `observed` |
| `orca agent launch --surface terminal`(코디네이터) | `hc run` 으로 팀 탭에 코디네이터, `hteam bind` 가 `run-create`·`run-use` |
| `ORCA_TERMINAL_HANDLE` 로 코디네이터 판별 | `$HC_TERMINAL_ID` 와 `run.json`·horch DB 로 판별 |
| Orca 프리앰블 문구로 워커 판별 | horch active Dispatch 터미널로 판별 |
| 리뷰: 화면 없는 `codex exec` | 리뷰: 반대쪽 에이전트의 horch 워커 pane |
| 작업: 항상 Claude | 작업: 직무별 `worker`(claude·codex), 리뷰는 반대쪽 |
| Orca 내장 브라우저 캡처 | Chrome DevTools MCP |
| `.orchestration/` | `.herdr-team/` |
| `/orca-team:init`·`up`·`image` | `/herdr-team:init`·`up`·`image` |
| Codex `--bypass-hook-trust` | `--disable=hooks`(`[agents.codex].args`) |
