# herdr-team

[Herdr](https://herdr.dev)(herdr-app 창 + herdr-core `hc`) 위에서 멀티 에이전트를 조정하는 Claude Code 플러그인 마켓플레이스다. 플러그인 두 개가 들어 있다.

| 플러그인 | 버전 | 하는 일 |
|---|---|---|
| `herdr-orch` | 0.3.0 | Claude·Codex 워커를 Herdr pane 으로 띄우고 메일함으로 질문·보고를 주고받는 `horch` CLI 와 스킬 |
| `herdr-team` | 0.6.0 | `herdr-orch` 위의 직무 팀. 사용자는 메인 Claude 세션과 대화하고, 기획·디자인·개발·테스트는 직무 에이전트가 맡고, 산출물은 반대쪽 모델(Claude ↔ Codex)이 리뷰한다 |

- 문서, 명령 출력, 에이전트끼리 주고받는 글은 한국어다.
- 개인 프로젝트이고 0.x 버전이다. 버전이 바뀌면 설정과 동작이 바뀔 수 있다(아래 "이미 세팅한 프로젝트 업그레이드").
- macOS 에서 확인했다. Linux·Windows 는 확인하지 않았다.
- **주의: herdr-team 은 Codex 를 늘 샌드박스·승인 우회로 돌린다.** 워커가 사용자 권한과 자격 증명을 그대로 쓴다. 신뢰하는 저장소에서만 쓴다(아래 "herdr-team 보안 주의").

## 요구사항

| 항목 | 쓰는 곳 | 확인한 버전 |
|---|---|---|
| Herdr: herdr-app, herdr-core `hc` | 에이전트 터미널과 창 | herdr-app 0.1.14, hc 0.1.19 |
| Claude Code(로그인한 것) | 메인 세션, Claude 워커·리뷰어 | 2.1.322 |
| Codex CLI(로그인한 것) | Codex 워커·리뷰어 | codex-cli 0.167.0 |
| Python 3.11 이상 | `horch`·`hteam`(표준 라이브러리만 쓴다) | 3.14.6 |
| git | 태스크 사양과 산출물 커밋. 작업 공간(worktree 모드)은 2.23 이상 | |
| Node/npx | Codex 리뷰어 브라우저 `hteam-browser`(첫 실행에 `chrome-devtools-mcp@1.10.1` 을 내려받는다) | |

- herdr-team 을 쓰려면 herdr-orch 0.3.0 이상도 함께 설치한다.
- 선택 항목이 둘 있다. 없어도 나머지는 돈다.
  - Codex `image_generation` 기능: designer 의 래스터 에셋(`hteam image`)을 만든다. `codex features enable image_generation` 으로 켠다.
  - Chrome DevTools MCP: 디자인 디렉터가 레퍼런스 화면을 캡처한다. 없으면 링크만 남긴다.
- herdr-orch 만 쓰면 Codex CLI 는 Codex 워커를 띄울 때만 필요하고 Node 는 필요 없다.
- 비용: herdr-team 은 Claude 세션과 Codex 세션 여러 개를 동시에 오래 띄운다. 템플릿 기본 모델은 다음과 같다. 모델은 `init` 이 제안하는 표에서 바꾸거나 나중에 `.herdr-team/config.toml` 에서 고친다.
  - 고정 에이전트: Claude `opus`(생산·리서치), Codex `gpt-6.1-sol`(테스트).
  - 임시 워커(고정 에이전트가 바쁠 때 등): 직무 표(`[roles.<직무>]`)의 모델을 쓴다. planner·director·developer 는 Claude `opus`, designer 는 Claude `sonnet`, tester 는 Codex `gpt-6.1-sol` 이다.
  - 리뷰어: Claude 가 한 작업은 Codex `gpt-6.1-sol` 이, tester(Codex)의 작업은 Claude `sonnet` 이 리뷰한다.
  - effort: 모두 `xhigh`.

## 설치

### 1. Herdr

```sh
curl -fsSL https://releases.herdr.dev/app/install.sh | sh
```

이 명령이 앱과 `hc` 를 함께 설치한다.
- macOS: 앱은 `~/Applications/Herdr.app` 에, `herdr-app`·`hc` 는 `~/.local/bin` 에 설치된다.
- `~/.local/bin` 이 `PATH` 에 있어야 한다.
- 같은 명령을 다시 실행하면 업데이트된다.
- 자세한 안내는 [herdr.dev](https://herdr.dev) 에 있다.

### 2. Claude Code 와 Codex CLI

각 공식 안내대로 설치하고 로그인한다. Codex 는 `codex login` 으로 로그인한다. 이미지 에셋을 쓰려면 위 `image_generation` 도 켠다.

### 3. 플러그인

터미널에서:

```sh
claude plugin marketplace add songyori/herdr-team
claude plugin install herdr-orch@herdr-team
claude plugin install herdr-team@herdr-team   # 직무 팀까지 쓸 때
```

Claude Code 안에서는 `/plugin marketplace add songyori/herdr-team` 다음 `/plugin install herdr-orch@herdr-team`, `/plugin install herdr-team@herdr-team` 를 실행한다.

- 범위: 기본은 사용자 범위(`--scope user`)다. 한 프로젝트를 팀이 같이 쓰려면 그 프로젝트 폴더에서 세 명령 모두에 `--scope project` 를 붙인다.
- 두 플러그인은 같은 범위로 설치한다. herdr-team 은 그 프로젝트에 맞는 herdr-orch 설치를 찾는다. 사용자 범위 설치는 늘 찾고, project·local 범위 설치는 그 프로젝트 안에서만 찾는다.
- 설치하기 전에 열어 둔 Claude Code 세션은 다시 연다.

## 시작하기(herdr-team)

1. Herdr 앱에서 터미널을 열고 프로젝트 폴더로 간다. herdr-team 은 Herdr 터미널 안에서만 돈다.
2. 그 터미널에서 `claude` 를 실행한다. 이 세션이 메인이다.
3. `/herdr-team:init <프로젝트 설명>` 을 실행한다. init 은 다음 순서로 세팅한다.
   1. 점검: 빠진 도구가 있으면 표로 보이고 멈춘다. git 저장소가 아니면 `git init` 과 빈 커밋을 한다.
   2. 세팅 파일 생성: `.herdr-team/`, `CLAUDE.md`·`AGENTS.md` 의 herdr-team 절, `.gitignore` 줄을 만든다. 있는 파일은 덮어쓰지 않는다.
   3. 제안 표: 직무별로 맡을 파일, 고정 에이전트 구성과 모델, 도구, 권한을 표로 제안한다. 사용자가 승인한 것만 적용한다. Claude 권한 우회도 여기서 승인할 때만 들어간다.
   4. 관제 띄우기: 관제 탭(`herdr-team 관제`)을 띄우고 세팅 파일을 커밋한다.
4. init 이 끝나면 메인 세션을 새로 연다(메인 규칙은 세션을 시작할 때 읽힌다). 새 세션에서 만들 것을 말한다. 메인이 기획 태스크를 만들어 넘긴다. 다음 일은 메인 세션에서 사용자에게 묻는다.
   - 기획자·디렉터의 질문
   - 디자인 일괄 승인
   - 테스트 명령 확정
   - 관제가 판단을 맡긴 일
5. 진행 상황은 메인이 알린다. 직접 보려면 `.herdr-team/bin/hteam status` 를 실행한다.
6. 관제가 꺼지면 메인 세션 훅이 다시 띄운다. 직접 올리려면 `/herdr-team:up` 을 실행한다.

## 업데이트

```sh
claude plugin marketplace update herdr-team
claude plugin update herdr-orch@herdr-team
claude plugin update herdr-team@herdr-team
```

- 업데이트한 뒤 Claude Code 세션을 다시 연다.
- 이미 세팅한 프로젝트는 버전에 따라 손으로 옮길 것이 있다(아래 "이미 세팅한 프로젝트 업그레이드").
- 복사해 둔 규칙 파일은 `.herdr-team/bin/hteam upgrade` 로 새 템플릿으로 바꾼다.

## 삭제

```sh
claude plugin uninstall herdr-team@herdr-team
claude plugin uninstall herdr-orch@herdr-team
claude plugin marketplace remove herdr-team
```

- 프로젝트 범위로 설치했으면 `uninstall` 에 `--scope project` 를 붙인다.
- 관제와 에이전트 터미널은 Herdr 에서 닫는다.
- 다음은 지우지 않고 남는다. 필요 없으면 손으로 지운다.
  - 프로젝트 안: `.herdr-team/`, `CLAUDE.md`·`AGENTS.md` 의 `<!-- herdr-team -->` 절.
  - 작업 공간을 썼으면 슬롯 폴더(`.herdr-team/state/slots/slot-<N>`)는 git worktree 다. `.herdr-team/` 를 지우기 전에 `git worktree remove <폴더>` 로 지우거나, 지운 뒤 `git worktree prune` 을 한다. 남은 `herdr/T-xxx` 브랜치(버린 태스크)도 손으로 지운다.
  - 프로젝트 밖: `${XDG_STATE_HOME:-~/.local/state}/herdr-team/`(테스트 명령 확정 기록), `~/.cache/herdr-team/`(레퍼런스 캡처와 이미지).

## 문제 해결

- 점검: herdr-team 은 프로젝트에서 `.herdr-team/bin/hteam doctor` 를 실행한다(init 전에는 init 이 점검한다). herdr-orch 는 플러그인 폴더의 `bin/horch doctor` 를 실행한다. 둘 다 빠진 도구와 그 이유를 JSON 으로 알려 준다.
- 기록:
  - 관제: `.herdr-team/state/drive/drive.log`
  - 관제 자동 부활: `.herdr-team/state/auto-up.log`
  - 작업 공간 setup·teardown: `.herdr-team/state/slots/logs/`
  - Redmine 전송 실패: `.herdr-team/state/redmine/failed/`(`hteam status` 의 `redmine`)
- 버그와 제안은 [Issues](https://github.com/songyori/herdr-team/issues) 에 남긴다. `doctor` 출력과 사용한 버전을 같이 적는다.

## 문서와 개발

- 설계: `docs/superpowers/specs/`(herdr-orch, herdr-team 설계 문서). 구현 계획: `docs/superpowers/plans/`.
- 테스트: `bash herdr-orch/tests/run.sh`, `bash herdr-team/tests/run.sh`. 가짜 hc·herdr-app·claude·codex 를 써서 실제 Herdr 상태를 건드리지 않는다.
- 개발 절차와 Codex 교차 검증 규칙은 `CLAUDE.md` 에 있다.
- 라이선스: MIT(각 플러그인의 `plugin.json`).

## herdr-orch

Run 소유자가 Claude·Codex 워커를 Herdr pane 으로 띄우고, SQLite 메일함으로 질문·보고를 주고받는 `horch` CLI 와 스킬 `herdr-orchestration`. 0.2.0 부터 고정 터미널(`worker-start --keep-open`·`--terminal`: 같은 세션에 다음 Dispatch 를 넣는다), 세션 비우기(`terminal-reset`), 고정 터미널 닫기(`terminal-close`)가 있다. 0.3.0 부터 워커 환경 변수(`worker-start --env KEY=VALUE`, 되풀이)를 받는다. `launch-guard` 가 에이전트를 실행하기 바로 전에 그 환경에 넣는다(`hc run` 으로 띄운 터미널은 부른 셸의 환경을 물려받지 않는다). 값은 저장소와 `worker-show` 출력에 남으므로 비밀값을 넘기지 않는다. Codex 워커에는 `-c shell_environment_policy.set.<이름>=<값>` 인자로도 넘긴다(사용자 Codex 설정의 `inherit` 가 값을 빼지 않게. `include_only` 를 쓰면 그래도 빠진다).

- 요구사항·설치: 위 "요구사항"·"설치". herdr-orch 만 쓰면 herdr-team 은 설치하지 않아도 된다.
- 쓰는 법: Herdr 터미널에서 연 Claude Code 세션에 Codex·Claude 워커로 일을 맡기고 결과를 받아 오라고 하면, 스킬 `herdr-orchestration` 이 `horch` 사용법을 읽고 워커를 띄운다.
- 점검: `herdr-orch/bin/horch doctor`(저장소 기준 경로. 설치했으면 플러그인 폴더의 `bin/horch`)
- 사용법: `herdr-orch/bin/horch skill`
- 설계: `docs/superpowers/specs/2026-11-04-herdr-orch-design.md`
- 테스트: `bash herdr-orch/tests/run.sh`(가짜 hc·herdr-app·claude·codex 사용, 실제 Herdr 상태를 건드리지 않는다)

## herdr-team

`herdr-orch` 위에 만든 직무 팀 플러그인. 메인(사용자와 대화하고 판단한다), 관제(`hteam drive`, 정해진 절차를 돌리는 프로그램), 직무 태스크를 하는 고정 에이전트와 임시 워커(planner·director·designer·developer·tester)가 일하고, 산출물은 반대쪽 모델(Claude ↔ Codex)이 교차 리뷰한다. 화면 프로젝트는 디자인 디렉터(레퍼런스·톤 시안·디자인 시스템)와 designer(화면·래스터 에셋)가 사용자 일괄 승인을 거쳐 디자인을 확정한다.

- 요구사항·설치: 위 "요구사항"·"설치". 처음 쓰는 순서는 위 "시작하기(herdr-team)".
- 명령(Claude Code 슬래시 명령)
  - `/herdr-team:init <프로젝트 설명>`: 새 프로젝트를 세팅한다(`.herdr-team/`, `CLAUDE.md`·`AGENTS.md` 절). 직무 owns·고정 에이전트 구성·도구·권한은 표로 제안하고 승인받은 것만 적용한 뒤 관제를 띄운다.
  - `/herdr-team:up`: 수동 복구. 관제와 watch 를 올리고 열린 질문을 다시 묻는다. 관제는 보통 메인 세션 훅이 자동으로 다시 띄운다(아래 "관제 복구").
  - `/herdr-team:image`: designer 의 래스터 에셋을 `hteam image` 로 만든다.
- 점검: `.herdr-team/bin/hteam doctor`
- 설계: `docs/superpowers/specs/2026-11-05-herdr-team-design.md`
- 테스트: `bash herdr-team/tests/run.sh`(가짜 hc·herdr-app·claude·codex 사용)

### 관제와 고정 에이전트

- 메인: 사용자가 연 Claude 세션. 사용자 요청을 기획 태스크 사양으로 써서 커밋하고 `hteam start` 한다. 산출물을 만들지 않고 `horch`·`hteam drive` 를 직접 부르지 않는다(훅이 막는다). `hteam watch` 를 늘 하나 띄워 두고, 관제가 올린 decide 를 `CLAUDE.md` 의 판단 기준대로 처리한 뒤 `hteam answer` 로 닫는다.
  - 메인은 사용자에게 언제나 선택 창(AskUserQuestion)으로 묻는다. 평문 질문은 Stop 훅이 한 번 막는다.
  - 작업 공간 태스크가 기준의 새 커밋을 받아야 하면 `hteam fix T-xxx --base-merge` 로 기준 병합 라운드를 연다(메인에 부탁한다).
- 관제(`hteam drive`): 관제 탭(`herdr-team 관제`)에서 도는 Python 프로그램(Claude 가 아니다). horch Run 을 갖고 디스패치, 리뷰, accept·fix, 묶음 후속, 마무리, 디자인 보강, 세션 리셋, 복구를 정해진 절차로 돌린다. 판단이 필요한 일(워커 질문, 실패, 최대 라운드, 회귀의 원인 등)만 outbox `decide` 로 메인에 올린다. 기록은 `.herdr-team/state/drive/drive.log`.
- 요청 큐: horch 를 건드리는 메인 명령(`start`, `start-ready`, `fix`, `accept`, `drop`, `review --retry`, `design-decide`, `scope`, `agent reset`, `test-confirm`, `slot reset`)은 파일 큐(`.herdr-team/state/drive/queue/`)로 관제에 넘어간다. 관제가 90초 안에 실행하면 그 결과를, 아니면 `status: queued` 를 돌려주고 결과는 watch 의 `result` 로 온다. 관제가 꺼져 있으면 큐에 넣지 않고 `drive_down` 으로 거부한다.
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

- 묶음: 함께 끝내고 함께 검증하는 기능 단위. tester 태스크 하나와 그 `depends_on` 의 developer 태스크들(3–6개 권장)이고, 묶음 이름은 tester 태스크의 key 다. planner 가 `docs/planning/tasks.toml` 에 묶는다. `[test]` 표가 있으면 `hteam plan check` 가 묶음 규칙을 검사한다: tester owns 는 정확히 `["tests/<key>/**", "docs/qa/<key>.md"]`(`[test] tester_paths` 가 있으면 그 경로들의 `{key}` 를 key 로 채운 것과 `docs/qa/<key>.md`), tester 는 developer 에만 의존, developer 는 tester 에 의존하지 않음, 문서 전용이 아닌 developer 는 정확히 한 묶음.
- `[test]` 쓰는 법(`docs/planning/tasks.toml` 의 최상위 표, 커밋한 HEAD 의 것만 쓴다):

  ```toml
  [test]
  quick = "npx vitest related --run --passWithNoTests {files}"   # 바뀐 파일과 관련된 테스트. {files} 를 정확히 한 번
  full = "npx vitest run"                                        # 전체 테스트
  timeout_min = 30      # 선택. 한 번 실행의 상한(분)
  ok_exit = [0]         # 선택. pytest 는 [0, 5]
  exclusive = false     # 선택. DB·포트를 같이 써서 동시에 돌면 깨지면 true
  tester_paths = ["tests/{key}/**"]   # 선택. 묶음 tester 태스크의 시험 경로 형식({key} 를 항목마다 한 번)
  full_if = ["db/migrations/**"]      # 선택. developer 태스크가 이 경로를 바꾸면 quick 대신 full 을 돈다
  ```

- 확정: `[test]` 명령은 리뷰 전에 관제 환경에서 자동으로 돈다. 그래서 사용자가 확정한 `[test]` 만 돈다. 기획 확정 질문(또는 관제의 확정 질문)에 hteam 이 `## 테스트 명령` 절을 붙이고, 첫 선택지로 답하면 메인이 확정 기록(프로젝트 밖 `${XDG_STATE_HOME:-~/.local/state}/herdr-team/projects/<id>/test-approvals.json`)에 남긴다. 확정하지 않았으면 리뷰는 관문 없이 진행하고 알린다(`hteam status` 의 `test_gate`). `[test]` 를 바꾸면 다시 확정한다. 확정 기록이 빠졌으면 메인이 `hteam test-confirm` 으로 관제에 다시 묻게 한다.
- 관문: developer 리뷰는 quick 이 통과하지 못하면 리뷰어를 띄우지 않고 돌려보낸다(라운드를 쓴다). tester 리뷰는 full 을 한 번 돌리고(워커가 같은 코드로 돌린 기록이면 다시 쓴다) 리뷰어가 묶음 전체를 본다. full 실패는 자동 반려하지 않고 리뷰어가 테스트 코드의 잘못(P1)과 제품 회귀(`## 회귀`)로 나눈다. 워커는 같은 명령을 `.herdr-team/bin/hteam test T-xxx [--full]` 로 돌린다(기록 `.herdr-team/state/tests/`, 로그 `.herdr-team/state/tests/logs/`). developer 태스크가 바꾼 경로(지우거나 옮긴 파일 포함)가 `full_if` 에 맞으면 리뷰 관문과 `hteam test T-xxx` 가 quick 대신 full 을 한 번 돌고, 실패하면 quick 실패처럼 리뷰어 없이 돌려보낸다. `tester_paths`·`full_if` 는 돌릴 명령을 바꾸지 않으므로 다시 확정하지 않아도 된다.
- 수렴형 리뷰: 지적마다 `rN-Fk` 번호와 등급을 붙이고 P1 만 막는다(P2·P3 는 `## 후속`, 사양에 없는 요구는 `## 기획 누락`). 라운드 2 부터 리뷰어는 이전 P1 의 해결과 새 커밋만 본다. hteam 이 `## 지적 사항` 의 P1 줄과 `## 이전 지적 확인` 의 미해결 줄 수로 판정을 맞춘다(바꾸면 리뷰 파일과 커밋 본문에 적는다).
- followups: 묶음 tester 태스크가 끝나면 관제가 `hteam followups T-xxx`(읽기 전용)로 회귀·후속·기획 누락을 모아 회귀 수정 태스크, 직무별 묶음 정리 태스크, decide 를 만든다. 원인이 하나로 정해지지 않는 회귀와 기획 누락은 메인이 정한다. 모든 태스크가 끝나면 묶음 밖 후속(`--rest`)과 마지막 `hteam test --full` 을 한 뒤 끝을 알린다.
- 한계: 테스트는 다른 워커가 일하는 같은 작업 폴더에서 돈다(커밋 안 된 다른 파일은 `dirty` 로 가른다. 작업 공간을 켜면 개발·테스트 태스크의 시험은 그 슬롯에서 따로 돈다). quick 의 관련 테스트는 테스트 도구의 판단에 기댄다. 회귀는 한 묶음 늦게 발견될 수 있다. 테스트 기록은 잠그지 않고 로그는 지우지 않는다. hteam 이 SIGKILL 로 끝나면 테스트 프로세스가 남을 수 있다.

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
- 환경: 워커·리뷰어·시험 명령·setup·teardown 은 그 슬롯의 `[workspace.env]` 값과 `HTEAM_SLOT` 을 받는다. setup·teardown 은 `HTEAM_MAIN_ROOT`(메인 프로젝트)·`HTEAM_SLOT_ROOT`(슬롯 작업 루트)도 받는다. 이름에는 `KEY`·`SECRET`·`TOKEN` 을 쓰지 않는다(Codex 셸 환경 정책이 뺄 수 있다). 사용자 Codex 설정의 `shell_environment_policy.include_only` 는 이 값을 Codex 셸에서 뺀다(`hteam doctor` 가 `codex_env_policy` 로 경고한다). 로그는 `.herdr-team/state/slots/logs/`.
- 병합: 리뷰가 승인하면 관제가 메인 폴더에서 `git merge --no-ff` 로 기준 브랜치에 병합한 뒤 done 으로 둔다(병합 커밋 `[T-xxx] merge: <제목>`). owns 잠금과 의존은 병합까지 간다. 메인 폴더의 커밋과 겹쳐 거부되면 관제가 다시 시도하고, 10분 넘게 거부되면 메인에 알린다. git 훅이 병합 커밋을 거부하면 기다리지 않고 바로 알린다(훅을 건너뛰지 않는다). 병합한 뒤 teardown 을 하고 슬롯을 비워 다음 태스크가 다시 쓴다(슬롯 폴더와 `node_modules` 같은 무시된 파일은 남긴다).
- 충돌: 병합이 충돌하면 되돌리고 그 태스크를 수정 라운드로 돌린다. 메인이 사용자에게 충돌 파일을 보이고 고칠지 버릴지 묻는다. 고치면 다음 라운드 워커가 기준 커밋을 그 브랜치에 병합해 충돌을 풀고, 리뷰를 다시 거친 뒤 관제가 병합한다.
- 메인 폴더에서 `git commit` 이 `index.lock` 으로 실패하면 몇 초 뒤 다시 한다(관제의 병합과 겹쳤다).
- 시험 도구 설정에서 `.herdr-team/` 를 뺀다: 슬롯 폴더가 메인 폴더 안에 있어 메인 폴더에서 직접 시험·린트를 돌리거나 IDE 가 색인하면 슬롯 사본이 섞인다. 예: vitest `exclude`, jest `testPathIgnorePatterns`, ESLint `ignores`, `tsconfig.json` 의 `exclude`, pytest `norecursedirs`. worktree 모드에서는 마지막 전체 테스트도 빈 슬롯에서 돈다(hteam 은 메인 폴더에서 시험을 돌리지 않는다).
- 더러운 슬롯: 버린 태스크의 슬롯에 커밋 안 된 변경이 남으면 그 슬롯을 쓰지 않는다. 메인이 사용자에게 `git -C <슬롯> status` 를 보이고, 버려도 된다고 하면 `hteam slot reset <N>`(되돌릴 수 없다)으로 비운다. `hteam doctor` 도 dirty 슬롯을 경고한다. 병합한 태스크가 남긴 추적 안 된 파일·바뀐 추적 파일도 슬롯에 남아, 그 슬롯을 다시 쓸 때 `slot_dirty` 가 된다. 시험·setup 이 만드는 파일(예: `__pycache__/`, 리포트 폴더)은 git 제외로 두고, setup 은 추적 파일을 바꾸지 않게 한다.
- 한계: 따로 리뷰를 통과한 두 태스크가 합쳐서 깨지는 경우는 묶음 tester 와 마지막 full 이 잡는다(한 폴더일 때보다 늦게 드러날 수 있다). git 훅이 병합 커밋을 거부하면 관제가 재확인마다 다시 병합해 본다(훅을 고치면 저절로 이어 간다). 그동안 메인 폴더가 잠깐 병합됐다 되돌려지고 훅이 매번 돌며, 훅이 도는 동안 메인 폴더의 경로 지정 커밋이 실패할 수 있다. 슬롯마다 설치가 따로라 처음 setup 이 오래 걸리고 디스크를 쓴다. hteam 이 SIGKILL 로 끝나면 setup 이 띄운 프로세스(DB 등)가 남을 수 있다. 여러 태스크가 한 줄씩 더하는 공용 등록 파일은 owns 를 나누지 않으면 그 태스크들이 한 줄로 선다(기능별 파일로 나누기를 권한다).

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
- 전송: 관제가 사건을 `.herdr-team/state/redmine/queue/` 에 쓰고 전송 자식(`hteam redmine-sync`)이 차례로 보낸다. 연결 실패·5xx 는 1·2·5·10분 간격으로 24시간까지 다시 보내고, 4xx(없는 이슈, 막힌 상태 전이, 권한)와 3xx(리다이렉트는 따르지 않는다. `url` 을 최종 주소로 둔다)는 `failed/` 로 옮기고 알린다. `hteam status` 의 `redmine`(`pending`·`failed`·`last_error`)으로 본다. 키를 찾는지와 연결은 `hteam doctor` 가 본다.
- 키 값은 init 이 묻지 않는다. 환경 변수나 `env_file` 에 직접 둔다. 키는 큐·로그·outbox·프롬프트·테스트 명령 환경에 들어가지 않는다.
- `env_file`(git 제외 파일)을 권한다. `env_file` 이 없으면 관제가 키를 읽도록 Herdr 터미널의 기본 환경에 키를 둬야 하고, 같은 환경으로 뜨는 워커·리뷰어 셸도 그 변수를 본다(워커가 `env` 를 돌리면 모델 맥락에 들어간다). `hteam doctor` 의 키 점검은 메인 터미널 환경을 보므로 `env_file` 이 없으면 관제 환경과 다를 수 있다.
- 한계: Redmine 워크플로가 막는 전이(닫은 이슈를 다시 진행중으로)는 실패 기록만 남는다. 이슈 하나를 여러 태스크가 나누면 노트가 섞인다. 묶음 tester 가 drop 되면 그 묶음의 이슈를 닫지 않는다. 이슈를 만들거나 Redmine 에서 일을 가져오지 않는다. 관제가 사건 중간에 죽으면 노트가 빠지거나 두 번 갈 수 있다(빠진 종료는 사람이 닫는다).

### 관제 복구

- 자동 부활: 메인 세션 훅(세션 시작, 그리고 매 프롬프트 60초 간격)이 관제 pid 파일과 heartbeat(`.herdr-team/state/drive/drive.pid`·`heartbeat`)를 보고, 프로세스가 죽었으면 `hteam up` 을 분리 실행한다. 메인은 답변 첫 줄에 사용자에게 알린다. 새 관제는 같은 Run 을 넘겨받고 남은 요청 파일·ack 안 된 메시지·상태 파일로 이어 간다. 꺼진 동안의 큐 명령은 거부되므로 메인이 잠시 뒤 다시 한다.
- 끄기: `.herdr-team/config.toml` 의 `[drive] auto_up = false`(안내만 한다). 키가 없으면 켜진다.
- 기록: `.herdr-team/state/auto-up.log`(자동 실행한 `hteam up` 출력), `auto-up.json`(마지막 확인·실행 시각과 안내), `.herdr-team/state/drive/drive.log`(관제).
- 다시 띄운 관제가 10분 안에 다시 꺼지거나 뜨지 못하면 다시 띄우지 않고 안내만 한다(로그를 보고 `/herdr-team:up`). 같은 안내는 바뀌었거나 세션을 새로 열 때만 다시 한다(실제로 다시 띄운 안내는 늘 한다).
- 멈춘 관제: 프로세스는 살아 있는데 heartbeat 가 2분 넘게 멈췄으면 다시 띄우지 않고 안내만 한다. 큐 명령은 `drive_hung` 으로 거부된다. 관제 탭의 출력을 본다.
- 수동 복구 `/herdr-team:up`: 자동 부활이 꺼져 있거나 훅이 안내했을 때, 메인을 다시 열어 열린 질문(decide 포함)을 다시 물을 때.
- 한계: 메인 세션 밖에서 죽으면 다음 메인 프롬프트(최대 60초 간격)나 세션 시작까지 모른다. 죽은 관제 터미널은 관제 탭에 남는다.

### herdr-team 보안 주의

- Codex 는 늘 샌드박스·승인 우회(`--dangerously-bypass-approvals-and-sandbox`, 템플릿 기본)로 돈다. Claude 권한 우회(`--permission-mode=bypassPermissions`)는 `init` 에서 사용자가 승인했을 때만 `.herdr-team/config.toml` 에 들어간다. 우회가 있으면 워커·리뷰어(고정 에이전트 포함)가 사용자의 git·클라우드 자격 증명과 셸 환경을 그대로 쓴다.
- `hteam image`(designer 의 래스터 에셋)도 `codex exec` 를 우회로 돌린다(image_gen 결과 파일을 읽으려고, 설계 14장). 프롬프트는 이미지 생성만 시키고 결과는 검사한 PNG 만 게시한다.
- 리뷰어 브라우저: Codex 리뷰어는 격리·헤드리스 `hteam-browser` 로 화면을 렌더한다(사용자 Chrome 의 쿠키·로그인을 쓰지 않는다). 다만 우회로 돌므로 리뷰어가 읽는 워커 코드·웹 페이지의 글이 명령을 실행시킬 수 있다. Claude 리뷰어는 격리되지 않은 사용자 자신의 Chrome DevTools MCP 를 쓰므로 페이지 스크립트가 그 브라우저 프로필에서 돈다. 필요하면 프로젝트 `.mcp.json` 에 `--isolated=true` 정의를 둔다.
- 레퍼런스 캡처와 이미지는 저장소 밖 캐시 `~/.cache/herdr-team/{refs,images}` 에 둔다.
- hteam 이 띄우는 codex 에서는 사용자의 `chrome-devtools` MCP 서버만 끈다(`hteam-browser` 와 같은 일을 한다). 사용자의 다른 MCP 서버는 끄지 않는다.
- 테스트 명령(`[test]` 의 quick·full)은 `/bin/sh -c` 로 도는 임의의 셸 문자열이다. 확정하면 리뷰 관문과 마무리의 `hteam test --full` 이 관제의 권한(메인 세션과 같은 사용자 권한, 샌드박스 없음)으로 돌린다. Codex 워커가 쓴 명령이 그렇게 돌면 권한이 넓어진다. 확정은 실수 방지(모르는 새 명령이 리뷰 전에 자동으로 도는 것을 막는다)이고 보안 경계가 아니다(프로젝트 안 상태를 일부러 바꾸는 워커는 막지 못한다). 명령을 읽고 확정하고, 신뢰하지 않는 저장소에서는 확정하지 않는다. 테스트 출력 끝(60줄)은 리뷰 프롬프트와 quick 반려 리뷰 파일(커밋된다)에 들어간다. 비밀값을 출력하는 테스트는 그 값을 저장소에 남긴다.
- 관제 자동 부활은 사용자가 따로 하지 않아도 메인 세션 훅이 메인 세션의 권한·환경으로 `hteam up` 을 실행하고, 관제는 그 권한으로 돌며 워커를 `[agents.*].args`(우회 포함)로 띄운다. 띄우는 것은 처음 띄운 관제와 같은 명령이다. 끄려면 `[drive] auto_up = false`.
- 리뷰 보기 pane 에서 친 키는 리뷰어에 들어간다(위 "리뷰 보기 pane"). 리뷰 보기 pane 의 입력을 막는 장치는 없다.
- 작업 공간 setup·teardown 은 `config.toml` 의 셸 문자열이고 관제 권한(사용자 권한, 샌드박스 없음)으로 돈다. `[test]` 처럼 확정 기록을 두지 않는다(`config.toml` 은 사용자 파일로 본다). 워커가 작업 트리의 `config.toml` 을 바꾸는 것은 막지 못한다.
- 슬롯 워커도 같은 사용자 권한으로 돌아 메인 폴더나 다른 슬롯을 고칠 수 있다. 사양의 작업 공간 절은 실수 방지이고 경계가 아니다. `hteam slot reset` 은 슬롯의 커밋 안 된 변경을 지운다(메인은 사용자가 확인한 뒤에만 부른다).
- Redmine API 키는 전송 자식만 읽고 프롬프트·로그·outbox·테스트 명령 환경에 넣지 않는다. `env_file` 이 없으면 키가 관제와 같은 기본 환경에 있어 워커·리뷰어 셸도 그 변수를 본다(`env_file` 을 권한다. 그 파일도 프로젝트 안이라 워커가 읽을 수는 있다. 실수 방지이고 경계가 아니다). 노트에는 작업 요약과 리뷰 지적 요약이 들어가 Redmine 서버로 나간다(워커가 쓴 글이 외부 서버에 남는다). `env_file` 은 git 제외여야 한다(추적하면 doctor 가 알린다).

### 이미 세팅한 프로젝트 업그레이드

scaffold 는 있는 파일을 덮어쓰지 않는다. 앞 버전에서 세팅한 프로젝트는 새 기능을 손으로 옮겨야 하고, 옮기지 않으면 조용히 빠진다(예: `[roles.director]` 가 없으면 디자인 디렉터 단계와 시스템 보강이 없다).

#### 0.5.0 → 0.6.0

herdr-orch 는 그대로(0.3.0)다.

1. 플러그인을 올리는 것만으로 적용되는 것: 질문 표시(훅이 거부하지 않고 표를 선택 창 미리보기에 넣는다, 긴 표는 메인 옆 '질문 보기' pane), 평문 질문 검사, `hteam fix --base-merge`, 병합 지시문·리뷰 안내 줄, 완료 요약.
2. `.herdr-team/bin/hteam upgrade` 의 `manual` 대로 `CLAUDE.md` 의 `<!-- herdr-team -->` 절을 `herdr-team/templates/CLAUDE.section.md` 와 견줘 고친다(메인 규칙 새 줄 셋: 평문 질문, 기준 병합, 업그레이드 뒤 새 세션. 질문 표시 규칙의 바뀐 두 줄).
3. 메인 세션을 새로 연다(메인 규칙은 세션을 시작할 때 읽힌다).

#### 0.4.0 → 0.5.0

플러그인만 올리면 된다(herdr-orch 0.3.0 과 함께). 새 기능은 설정으로 켜고, 켜지 않으면 0.4.0 과 같이 돈다.

1. 플러그인을 올리는 것만으로 적용되는 것: 리뷰 프롬프트의 우선순위 줄과 수정 라운드 재검증 문구, 워커 사양의 우선순위 줄, `.herdr-team/review-extra.md`(만들면 리뷰에 붙는다).
2. 설정으로 켜는 것: `config.toml` 의 `[workspace]`(작업 공간)·`[redmine]`(Redmine), `docs/planning/tasks.toml` `[test]` 의 `tester_paths`·`full_if`, 태스크의 `issue`. 템플릿(`herdr-team/templates/config.toml`)의 주석 예시를 옮긴다.
3. 작업 공간이나 Redmine 을 켜면 `.herdr-team/bin/hteam upgrade` 의 `manual` 대로 `CLAUDE.md`·`AGENTS.md` 의 `<!-- herdr-team -->` 절을 `herdr-team/templates/CLAUDE.section.md`·`AGENTS.section.md` 와 견줘 고친다(새 decide `merge_conflict`·`workspace_failed` 처리 기준, `index.lock` 다시 시도, Redmine 줄, 작업 공간·이슈·우선순위 줄, 큐 명령 `slot reset`).
4. 작업 공간을 켜면 작업 공간 직무를 `[crew.*]` 의 `roles` 와 `user_approval_roles` 에서 빼고(남기면 설정 오류로 알린다), 시험 도구 설정에서 `.herdr-team/` 를 뺀다(위 "작업 공간").

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

워커는 사람 없이 돈다. `--agent-arg` 로 권한 우회(Claude `--permission-mode`, Codex 샌드박스 우회. herdr-team 은 Codex 우회를 늘 넘긴다)를 넘기면 워커가 사용자의 자격 증명(git, 클라우드 인증, 셸 환경)을 그대로 쓴다. Codex 워커는 `--cwd` 폴더를 그 실행에서만 신뢰한 것으로 띄우고(폴더 신뢰 창 없이) 시작 업데이트 확인을 끈다. 신뢰한 폴더는 그 폴더의 Codex 설정이 코드를 실행할 수 있다. 신뢰할 수 있는 저장소에서만 쓴다. horch 의 권한 확인은 실수 방지용이지 보안 경계가 아니다.
