# herdr-team

Herdr(herdr-app 창 + herdr-core `hc`) 위에서 멀티 에이전트를 조정하는 Claude Code 플러그인 마켓플레이스다.

## herdr-orch

Run 소유자가 Claude·Codex 워커를 Herdr pane 으로 띄우고, SQLite 메일함으로 질문·보고를 주고받는 `horch` CLI 와 스킬 `herdr-orchestration`. 0.2.0 부터 고정 터미널(`worker-start --keep-open`·`--terminal`: 같은 세션에 다음 Dispatch 를 넣는다), 세션 비우기(`terminal-reset`), 고정 터미널 닫기(`terminal-close`)가 있다.

- 요구사항: Python 3.11 이상, herdr-core `hc`, herdr-app, Claude Code, (Codex 워커를 쓰면) Codex CLI
- 설치: Claude Code 에서 `/plugin marketplace add <이 저장소>` 다음 `/plugin install herdr-orch@herdr-team`
- 점검: `herdr-orch/bin/horch doctor`
- 사용법: `herdr-orch/bin/horch skill`
- 설계: `docs/superpowers/specs/2026-11-04-herdr-orch-design.md`
- 테스트: `bash herdr-orch/tests/run.sh`(가짜 hc·herdr-app·claude·codex 사용, 실제 Herdr 상태를 건드리지 않는다)

## herdr-team

`herdr-orch` 위에 만든 직무 팀 플러그인. 메인(사용자와 대화하고 판단한다), 관제(`hteam drive`, 정해진 절차를 돌리는 프로그램), 직무 태스크를 하는 고정 에이전트와 임시 워커(planner·director·designer·developer·tester)가 일하고, 산출물은 반대쪽 모델(Claude ↔ Codex)이 교차 리뷰한다. 화면 프로젝트는 디자인 디렉터(레퍼런스·톤 시안·디자인 시스템)와 designer(화면·래스터 에셋)가 사용자 일괄 승인을 거쳐 디자인을 확정한다.

- 요구사항: Python 3.11 이상, herdr-core `hc`, herdr-app, Claude Code, Codex CLI(`image_generation` 기능을 켠 것. `hteam image` 가 쓴다), Node/npx(리뷰어 브라우저 `hteam-browser` 가 첫 실행에 `chrome-devtools-mcp@1.10.1` 을 내려받는다). herdr-orch 0.2.0 이상도 함께 설치한다.
- 설치: `/plugin marketplace add <이 저장소>` 다음 `/plugin install herdr-orch@herdr-team`, `/plugin install herdr-team@herdr-team`. 범위는 프로젝트(`--scope project`, 팀이 같이 쓴다) 또는 사용자(`--scope user`) 중에서 고른다.
- 명령(Claude Code 슬래시 명령)
  - `/herdr-team:init <프로젝트 설명>`: 새 프로젝트를 세팅한다(`.herdr-team/`, `CLAUDE.md`·`AGENTS.md` 절). 직무 owns·고정 에이전트 구성·도구·권한은 표로 제안하고 승인받은 것만 적용한 뒤 관제를 띄운다.
  - `/herdr-team:up`: 수동 복구. 관제와 watch 를 올리고 열린 질문을 다시 묻는다. 관제는 보통 메인 세션 훅이 자동으로 다시 띄운다(아래 "관제 복구").
  - `/herdr-team:image`: designer 의 래스터 에셋을 `hteam image` 로 만든다.
- 점검: `.herdr-team/bin/hteam doctor`
- 설계: `docs/superpowers/specs/2026-11-05-herdr-team-design.md`
- 테스트: `bash herdr-team/tests/run.sh`(가짜 hc·herdr-app·claude·codex 사용)

### 관제와 고정 에이전트

- 메인: 사용자가 연 Claude 세션. 사용자 요청을 기획 태스크 사양으로 써서 커밋하고 `hteam start` 한다. 산출물을 만들지 않고 `horch`·`hteam drive` 를 직접 부르지 않는다(훅이 막는다). `hteam watch` 를 늘 하나 띄워 두고, 관제가 올린 decide 를 `CLAUDE.md` 의 판단 기준대로 처리한 뒤 `hteam answer` 로 닫는다.
- 관제(`hteam drive`): 관제 탭(`herdr-team 관제`)에서 도는 Python 프로그램(Claude 가 아니다). horch Run 을 갖고 디스패치, 리뷰, accept·fix, 묶음 후속, 마무리, 디자인 보강, 세션 리셋, 복구를 정해진 절차로 돌린다. 판단이 필요한 일(워커 질문, 실패, 최대 라운드, 회귀의 원인 등)만 outbox `decide` 로 메인에 올린다. 기록은 `.herdr-team/state/drive/drive.log`.
- 요청 큐: horch 를 건드리는 메인 명령(`start`, `start-ready`, `fix`, `accept`, `drop`, `review --retry`, `design-decide`, `scope`, `agent reset`, `test-confirm`)은 파일 큐(`.herdr-team/state/drive/queue/`)로 관제에 넘어간다. 관제가 90초 안에 실행하면 그 결과를, 아니면 `status: queued` 를 돌려주고 결과는 watch 의 `result` 로 온다. 관제가 꺼져 있으면 큐에 넣지 않고 `drive_down` 으로 거부한다.
- 고정 에이전트: `config.toml` 의 `[crew.<이름>]`(직무 목록, `agent` claude·codex, 모델)마다 하나씩 있는 오래 사는 작업 세션. 같은 세션이 그 직무 태스크와 수정 라운드를 이어 맡는다(에이전트 탭 `herdr-team <제목>` 의 왼쪽 pane). 묶음이 끝나면 인수인계 `docs/handoff/<이름>.md` 를 쓰고 제자리에서 `/clear` 로 비운다(Codex 는 `/clear <이름>`). 비웠다는 신호가 10초 안에 없으면 새 터미널로 띄운다. 상태는 `.herdr-team/state/crew.json`.
- 임시 워커: 맡을 고정 에이전트가 없거나, 바쁘거나(`[overflow] enabled = true` 일 때), 태스크의 작업 에이전트가 그 고정 에이전트와 다르면 라운드마다 관제 탭 pane 에 새로 띄운다.
- 한계: 고정 에이전트 컨텍스트는 한 묶음 동안 쌓인다. 에이전트마다 모델이 하나라 designer 태스크도 생산 에이전트 모델로 돈다. 넣은 입력이 사라졌는지는 60초가 지나야 안다. hc core 재시작 뒤 이어지는지는 확인하지 않았다.

### 리뷰 보기 pane

- 고정 에이전트 태스크의 리뷰어는 숨겨 띄우고, 리뷰 동안만 그 에이전트 탭 오른쪽 pane 에 `hc attach` 로 보인다. 리뷰가 끝나면 관제가 그 pane 을 닫는다. 임시 워커 태스크의 리뷰어는 관제 탭 pane 에 뜬다.
- **주의: 그 pane 에서 친 키는 리뷰어에 들어간다**(일반 attach 다). 사람이 리뷰어에게 입력하면 리뷰가 바뀔 수 있다. 보기만 한다. hc attach 의 떼기 키(`ctrl+\`)로 떼면 보기 pane 의 프로그램만 끝나고 리뷰어는 계속 돈다(그 리뷰 동안 관제가 다시 열지 않는다).
- 보기 pane 을 열지 못하거나 pane 이 죽어도 리뷰에는 영향이 없다.

### 문구 규칙

- `.herdr-team/text-rules.md`(작성·리뷰 공통 규칙)와 planner 가 기획 때 정하는 `docs/planning/voice.md`(문체·호칭·라벨·용어집). designer·developer 는 서비스 문구(UI 라벨·버튼·오류·알림), 정책 문서(`docs/policy/`), 사용자 문서(`README.md`, `docs/user/`)를 쓸 때 지키고 보고서에 `### 문구 점검` 을 둔다. 정책·사용자 문서는 developer 가 맡는다(템플릿 developer owns 에 `README.md`·`docs/user/**`·`docs/policy/**`).
- 리뷰: `text-rules.md` 가 있고 한글 문구가 든 파일을 바꾼 태스크면 직무와 관계없이 리뷰 프롬프트에 "문구 기준" 절이 붙는다. 태스크가 추가한 줄의 의심 위치(오탈자, 이중피동, 번역투, 상투어, hedging, 챗봇 잔재, 쉼표, 용어집의 쓰지 않는 표기, 높임법 섞임)를 경고로 넣는다. 자동 불합격은 없고 판정은 리뷰어가 text-rules §5 로 한다.

### 디자인 규칙과 리뷰

- `.herdr-team/design-rules.md`: §1 AI 티 금지 목록 10개, §2–§7(접근성 WCAG 2.2 AA, 색, 글자, 레이아웃, 표면·동작, 상태), 즉시 차단 항목 10개(보고서에 예외를 적어도 리뷰가 P1). UI 를 바꾼 태스크는 보고서에 `### 디자인 점검` 을 둔다.
- 리뷰 디자인 절(director 직무가 있는 프로젝트의 director·designer·developer 태스크): 기준 1–9. 이 태스크가 만든 문제만 `(새로 생김)`·`(회귀)`·`(기존)` 으로 나눠 지적하고, diff 의 지운 줄을 읽고, 빠진 상태를 찾고, 즉시 차단 항목은 P1, 고칠 방향은 싼 것부터.
- 자동 검사(경고): diff 의 지운 줄에서 줄어든 접근성·글자 신호와 추가한 줄의 확대 막기·`focus-visible` 없는 포커스 제거(designdiff) 먼저, 바뀐 파일의 이모지·왼쪽 강조 테두리·파랑·보라 그라디언트(내용 검사) 뒤, 합쳐 50건까지. 리뷰어가 볼 경고는 `.herdr-team/bin/hteam lint --task T` 로 미리 본다(`findings` 는 디자인, `text_findings` 는 문구).

### 묶음 검증

- 묶음: 함께 끝내고 함께 검증하는 기능 단위. tester 태스크 하나와 그 `depends_on` 의 developer 태스크들(3–6개 권장)이고, 묶음 이름은 tester 태스크의 key 다. planner 가 `docs/planning/tasks.toml` 에 묶는다. `[test]` 표가 있으면 `hteam plan check` 가 묶음 규칙을 검사한다: tester owns 는 정확히 `["tests/<key>/**", "docs/qa/<key>.md"]`, tester 는 developer 에만 의존, developer 는 tester 에 의존하지 않음, 문서 전용이 아닌 developer 는 정확히 한 묶음.
- `[test]` 쓰는 법(`docs/planning/tasks.toml` 의 최상위 표, 커밋한 HEAD 의 것만 쓴다):

  ```toml
  [test]
  quick = "npx vitest related --run --passWithNoTests {files}"   # 바뀐 파일과 관련된 테스트. {files} 를 정확히 한 번
  full = "npx vitest run"                                        # 전체 테스트
  timeout_min = 30      # 선택. 한 번 실행의 상한(분)
  ok_exit = [0]         # 선택. pytest 는 [0, 5]
  exclusive = false     # 선택. DB·포트를 같이 써서 동시에 돌면 깨지면 true
  ```

- 확정: `[test]` 명령은 리뷰 전에 관제 환경에서 자동으로 돈다. 그래서 사용자가 확정한 `[test]` 만 돈다. 기획 확정 질문(또는 관제의 확정 질문)에 hteam 이 `## 테스트 명령` 절을 붙이고, 첫 선택지로 답하면 메인이 확정 기록(프로젝트 밖 `${XDG_STATE_HOME:-~/.local/state}/herdr-team/projects/<id>/test-approvals.json`)에 남긴다. 확정하지 않았으면 리뷰는 관문 없이 진행하고 알린다(`hteam status` 의 `test_gate`). `[test]` 를 바꾸면 다시 확정한다. 확정 기록이 빠졌으면 메인이 `hteam test-confirm` 으로 관제에 다시 묻게 한다.
- 관문: developer 리뷰는 quick 이 통과하지 못하면 리뷰어를 띄우지 않고 돌려보낸다(라운드를 쓴다). tester 리뷰는 full 을 한 번 돌리고(워커가 같은 코드로 돌린 기록이면 다시 쓴다) 리뷰어가 묶음 전체를 본다. full 실패는 자동 반려하지 않고 리뷰어가 테스트 코드의 잘못(P1)과 제품 회귀(`## 회귀`)로 나눈다. 워커는 같은 명령을 `.herdr-team/bin/hteam test T-xxx [--full]` 로 돌린다(기록 `.herdr-team/state/tests/`, 로그 `.herdr-team/state/tests/logs/`).
- 수렴형 리뷰: 지적마다 `rN-Fk` 번호와 등급을 붙이고 P1 만 막는다(P2·P3 는 `## 후속`, 사양에 없는 요구는 `## 기획 누락`). 라운드 2 부터 리뷰어는 이전 P1 의 해결과 새 커밋만 본다. hteam 이 `## 지적 사항` 의 P1 줄과 `## 이전 지적 확인` 의 미해결 줄 수로 판정을 맞춘다(바꾸면 리뷰 파일과 커밋 본문에 적는다).
- followups: 묶음 tester 태스크가 끝나면 관제가 `hteam followups T-xxx`(읽기 전용)로 회귀·후속·기획 누락을 모아 회귀 수정 태스크, 직무별 묶음 정리 태스크, decide 를 만든다. 원인이 하나로 정해지지 않는 회귀와 기획 누락은 메인이 정한다. 모든 태스크가 끝나면 묶음 밖 후속(`--rest`)과 마지막 `hteam test --full` 을 한 뒤 끝을 알린다.
- 한계: 테스트는 다른 워커가 일하는 같은 작업 폴더에서 돈다(커밋 안 된 다른 파일은 `dirty` 로 가른다). quick 의 관련 테스트는 테스트 도구의 판단에 기댄다. 회귀는 한 묶음 늦게 발견될 수 있다. 테스트 기록은 잠그지 않고 로그는 지우지 않는다. hteam 이 SIGKILL 로 끝나면 테스트 프로세스가 남을 수 있다.

### 관제 복구

- 자동 부활: 메인 세션 훅(세션 시작, 그리고 매 프롬프트 60초 간격)이 관제 pid 파일과 heartbeat(`.herdr-team/state/drive/drive.pid`·`heartbeat`)를 보고, 프로세스가 죽었으면 `hteam up` 을 분리 실행한다. 메인은 답변 첫 줄에 사용자에게 알린다. 새 관제는 같은 Run 을 넘겨받고 남은 요청 파일·ack 안 된 메시지·상태 파일로 이어 간다. 꺼진 동안의 큐 명령은 거부되므로 메인이 잠시 뒤 다시 한다.
- 끄기: `.herdr-team/config.toml` 의 `[drive] auto_up = false`(안내만 한다). 키가 없으면 켜진다.
- 기록: `.herdr-team/state/auto-up.log`(자동 실행한 `hteam up` 출력), `auto-up.json`(마지막 확인·실행 시각과 안내), `.herdr-team/state/drive/drive.log`(관제).
- 다시 띄운 관제가 10분 안에 다시 꺼지거나 뜨지 못하면 다시 띄우지 않고 안내만 한다(로그를 보고 `/herdr-team:up`). 같은 안내는 바뀌었거나 세션을 새로 열 때만 다시 한다(실제로 다시 띄운 안내는 늘 한다).
- 멈춘 관제: 프로세스는 살아 있는데 heartbeat 가 2분 넘게 멈췄으면 다시 띄우지 않고 안내만 한다. 큐 명령은 `drive_hung` 으로 거부된다. 관제 탭의 출력을 본다.
- 수동 복구 `/herdr-team:up`: 자동 부활이 꺼져 있거나 훅이 안내했을 때, 메인을 다시 열어 열린 질문(decide 포함)을 다시 물을 때.
- 한계: 메인 세션 밖에서 죽으면 다음 메인 프롬프트(최대 60초 간격)나 세션 시작까지 모른다. 죽은 관제 터미널은 관제 탭에 남는다.

### herdr-team 보안 주의

- Claude 권한 우회(`--permission-mode=bypassPermissions`)와 Codex 샌드박스 우회는 `init` 에서 사용자가 승인했을 때만 `.herdr-team/config.toml` 에 들어간다. 승인하면 워커·리뷰어(고정 에이전트 포함)가 사용자의 git·클라우드 자격 증명과 셸 환경을 그대로 쓴다.
- `hteam image`(designer 의 래스터 에셋)는 이 승인과 관계없이 `codex exec` 를 샌드박스 우회로 돌린다(image_gen 결과 파일을 읽으려고, 설계 14장). 프롬프트는 이미지 생성만 시키고 결과는 검사한 PNG 만 게시한다.
- 리뷰어 브라우저: Codex 리뷰어는 격리·헤드리스 `hteam-browser` 로 화면을 렌더한다(사용자 Chrome 의 쿠키·로그인을 쓰지 않는다). 다만 우회를 승인하면 리뷰어가 읽는 워커 코드·웹 페이지의 글이 명령을 실행시킬 수 있다. Claude 리뷰어는 격리되지 않은 사용자 자신의 Chrome DevTools MCP 를 쓰므로 페이지 스크립트가 그 브라우저 프로필에서 돈다. 필요하면 프로젝트 `.mcp.json` 에 `--isolated=true` 정의를 둔다.
- 레퍼런스 캡처와 이미지는 저장소 밖 캐시 `~/.cache/herdr-team/{refs,images}` 에 둔다.
- hteam 이 띄우는 codex 에서는 사용자의 `chrome-devtools` MCP 서버만 끈다(`hteam-browser` 와 같은 일을 한다). 사용자의 다른 MCP 서버는 끄지 않는다.
- 테스트 명령(`[test]` 의 quick·full)은 `/bin/sh -c` 로 도는 임의의 셸 문자열이다. 확정하면 리뷰 관문과 마무리의 `hteam test --full` 이 관제의 권한(메인 세션과 같은 사용자 권한, 샌드박스 없음)으로 돌린다. Codex 워커가 쓴 명령이 그렇게 돌면 권한이 넓어진다. 확정은 실수 방지(모르는 새 명령이 리뷰 전에 자동으로 도는 것을 막는다)이고 보안 경계가 아니다(프로젝트 안 상태를 일부러 바꾸는 워커는 막지 못한다). 명령을 읽고 확정하고, 신뢰하지 않는 저장소에서는 확정하지 않는다. 테스트 출력 끝(60줄)은 리뷰 프롬프트와 quick 반려 리뷰 파일(커밋된다)에 들어간다. 비밀값을 출력하는 테스트는 그 값을 저장소에 남긴다.
- 관제 자동 부활은 사용자가 따로 하지 않아도 메인 세션 훅이 메인 세션의 권한·환경으로 `hteam up` 을 실행하고, 관제는 그 권한으로 돌며 워커를 `[agents.*].args`(승인한 우회 포함)로 띄운다. 띄우는 것은 이미 승인한 관제와 같은 명령이다. 끄려면 `[drive] auto_up = false`.
- 리뷰 보기 pane 에서 친 키는 리뷰어에 들어간다(위 "리뷰 보기 pane"). 리뷰 보기 pane 의 입력을 막는 장치는 없다.

### 이미 세팅한 프로젝트 업그레이드

scaffold 는 있는 파일을 덮어쓰지 않는다. 앞 버전에서 세팅한 프로젝트는 새 기능을 손으로 옮겨야 하고, 옮기지 않으면 조용히 빠진다(예: `[roles.director]` 가 없으면 디자인 디렉터 단계와 시스템 보강이 없다).

#### 0.3.0 → 0.4.0

이전하지 않는다(이전 명령이 없다). 0.4.0 은 코디네이터 대신 관제(`hteam drive`)와 고정 에이전트를 쓴다.

1. 플러그인을 0.4.0(herdr-orch 0.2.0 과 함께)으로 올리면 `config.toml` 의 `[coordinator]` 가 설정 오류가 된다(메인 세션 훅과 `hteam status` 가 알린다).
2. `config.toml` 을 지운 뒤 `/herdr-team:init` 으로 다시 세팅한다. scaffold 는 있는 파일을 덮어쓰지 않으므로 `config.toml` 만 새로 생긴다(다시 세팅하려면 `.herdr-team/state/setup-done` 도 지운다). 또는 `[coordinator]` 를 지우고 템플릿(`herdr-team/templates/config.toml`)의 `[drive]`·`[overflow]`·`[crew.*]` 를 손으로 옮긴다.
3. `.herdr-team/bin/hteam upgrade` 로 직무 문서·규칙 파일을 바꾸고 `git diff -- .herdr-team` 을 확인해 커밋한다. 남은 `.herdr-team/coordinator.md` 는 쓰이지 않는다(upgrade 가 건드리지 않는다. 지워도 된다).
4. `manual` 의 `CLAUDE.md`·`AGENTS.md` 의 `<!-- herdr-team -->` 절을 `herdr-team/templates/CLAUDE.section.md`·`AGENTS.section.md` 와 견줘 고친다(메인 규칙이 관제·요청 큐·decide 처리 기준으로 바뀌었다).
5. 남은 코디네이터 터미널을 끝내고 `/herdr-team:up` 으로 관제를 띄운다.

#### 0.2.0 → 0.3.0

1. 플러그인을 0.3.0 으로 올린다. 리뷰의 수렴형 규칙·판정 맞추기, 워커 사양의 테스트 절, 리뷰 절 템플릿은 이것만으로 적용된다.
2. 프로젝트 루트에서 `.herdr-team/bin/hteam upgrade`(또는 메인에 부탁한다). 복사한 규칙 파일(`coordinator.md`, `design-rules.md`, `text-rules.md`, 직무 문서, shim)을 템플릿으로 바꾼다. 커밋돼 있고 깨끗한 파일만 덮어쓴다(커밋해 둔 사용자 수정도 덮어쓰지만 git 기록에 남아 있어 그 커밋에서 되살릴 수 있다). `config.toml` 은 건드리지 않는다. 커밋하지 않는다.
3. `git diff -- .herdr-team` 을 확인하고 커밋한다. `skipped` 는 까닭대로 정리한 뒤 다시 한다.
4. `manual` 의 `CLAUDE.md`·`AGENTS.md` 의 `<!-- herdr-team -->` 절을 `herdr-team/templates/CLAUDE.section.md`·`AGENTS.section.md` 와 견줘 고친다(절에 끝 표시가 없어 upgrade 가 바꾸지 않는다).
5. 테스트 관문을 쓰려면 `docs/planning/tasks.toml` 에 `[test]` 를 넣고 커밋한다(직접 쓰거나 메인에 증분 기획을 요청한다). 확정 질문에 답해야 돈다(위 "묶음 검증").
6. 코디네이터를 다시 띄운다(코디네이터 터미널을 끝내면 메인 세션 훅이 다시 띄운다. `auto_up = false` 면 `/herdr-team:up`).

#### 0.1.x → 0.2.0

1. 플러그인만 올려도 적용되는 것: 리뷰 디자인 절의 새 기준과 diff 자동 검사(director 직무가 있는 프로젝트), 코디네이터 자동 부활(`[coordinator] auto_up` 키가 없으면 켜진다. 끄려면 `auto_up = false`). 옛 `design-rules.md`(§ 제목이 없는 금지 목록)는 리뷰가 §1·즉시 차단 항목만 본다.
2. 새 파일: 프로젝트 루트에서 `.herdr-team/bin/hteam scaffold --description-file .herdr-team/project.md` 를 다시 하면 `.herdr-team/text-rules.md` 가 생긴다. 이 파일이 있어야 리뷰에 문구 절이 붙는다.
3. 손으로 합칠 것(워커가 새 규칙으로 쓰게, `herdr-team/templates/` 의 같은 이름 파일과 비교한다. 프로젝트에서 고친 곳은 합친다). 복사한 규칙 파일(`.herdr-team/` 아래 문서와 shim)은 0.3.0 의 `hteam upgrade` 로 대신할 수 있다(`config.toml` 은 여전히 손으로)
   - `.herdr-team/design-rules.md`: 템플릿으로 바꾼다(§0–§7, 즉시 차단 항목, 자동 검사, 출처).
   - `.herdr-team/roles/planner.md`(문구 기준 점검표 항목, `voice.md` 산출물과 형식), `director.md`·`designer.md`·`developer.md`(디자인 규칙 §1–§7·즉시 차단 줄, `### 디자인 점검`, 문구 규칙), `.herdr-team/coordinator.md`(`voice.md`).
   - `CLAUDE.md` 의 herdr-team 절(`<!-- herdr-team -->`): 메인 규칙의 자동 부활 줄과 "위치" 의 `voice.md`·문구 줄.
   - `.herdr-team/config.toml`: developer owns 에 `"README.md", "docs/user/**", "docs/policy/**"`(정책·사용자 문서를 developer 가 맡는다). 원하면 `[coordinator]` 에 `auto_up` 줄.
   - 바꾼 뒤 코디네이터를 다시 띄운다(코디네이터는 시작할 때 문서를 읽는다).
4. `docs/planning/voice.md` 는 다음 기획에서 planner 가 만든다(없는 동안 용어집 검사만 건너뛴다).
5. 플러그인을 다시 올린 뒤에는 바뀐 규칙 파일(`text-rules.md`, `design-rules.md`)을 템플릿에서 다시 복사해야 워커에 적용된다.

#### 1·2단계에서 세팅한 프로젝트(0.1.0 전)

1. 새 파일은 프로젝트 루트에서 scaffold 를 다시 하면 생긴다: `.herdr-team/bin/hteam scaffold --description-file .herdr-team/project.md`(설명 파일은 필수 인자다. 있는 `project.md` 는 그대로 둔다). 생기는 것: `.herdr-team/design-rules.md`, `.herdr-team/roles/director.md`, 1단계 프로젝트면 `.herdr-team/roles/designer.md` 도.
2. 손으로 합칠 것(`herdr-team/templates/` 의 같은 이름 파일과 비교한다)
   - `.herdr-team/config.toml`: `[roles.director]` 절과 `[agents.codex].args` 의 `hteam-browser` 한 쌍(`"-c", 'mcp_servers.hteam-browser={…}'`). Codex 리뷰어가 브라우저를 쓰게 하려면 `--dangerously-bypass-approvals-and-sandbox` 도 넣는다(위 보안 주의를 읽고 정한다). 1단계에서 세팅한 화면 프로젝트는 `[roles.designer]` 절도 더하고 `user_approval_roles` 에 `"designer"` 를 넣는다(1단계 설정은 `[roles.designer]` 가 없고 `user_approval_roles = []` 라 designer 태스크가 `unknown_role` 로 실패하고 일괄 승인도 걸리지 않는다).
   - `.herdr-team/roles/designer.md`: `## 시작`, `## 도구`, `## 시스템 적용 규칙`, `## 시스템이 없을 때`, `## 확인한 화면`.
   - `.herdr-team/roles/developer.md`: `## 화면 규칙`.
   - `.herdr-team/roles/planner.md`: `ui-foundation`·`design-direction` 태스크를 두라는 줄.
   - `.herdr-team/coordinator.md`: `## 디자인 시스템 보강`, 직무 목록의 director 줄.
   - `CLAUDE.md` 의 herdr-team 절(`<!-- herdr-team -->`): "질문 표시 규칙"의 두 줄(`render.context` 를 답변 글로 먼저 보이고 같은 응답에서 이어서 AskUserQuestion 을 부른다)과 `stale_question` 줄.

## 보안 주의

워커는 사람 없이 돈다. `--agent-arg` 로 권한 우회(Claude `--permission-mode`, Codex 샌드박스 우회)를 넘기면 워커가 사용자의 자격 증명(git, 클라우드 인증, 셸 환경)을 그대로 쓴다. 신뢰할 수 있는 저장소에서만 쓴다. horch 의 권한 확인은 실수 방지용이지 보안 경계가 아니다.
