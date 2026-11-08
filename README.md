# herdr-team

Herdr(herdr-app 창 + herdr-core `hc`) 위에서 멀티 에이전트를 조정하는 Claude Code 플러그인 마켓플레이스다.

## herdr-orch

코디네이터 에이전트가 Claude·Codex 워커를 Herdr pane 으로 띄우고, SQLite 메일함으로 질문·보고를 주고받는 `horch` CLI 와 스킬 `herdr-orchestration`.

- 요구사항: Python 3.11 이상, herdr-core `hc`, herdr-app, Claude Code, (Codex 워커를 쓰면) Codex CLI
- 설치: Claude Code 에서 `/plugin marketplace add <이 저장소>` 다음 `/plugin install herdr-orch@herdr-team`
- 점검: `herdr-orch/bin/horch doctor`
- 사용법: `herdr-orch/bin/horch skill`
- 설계: `docs/superpowers/specs/2026-11-04-herdr-orch-design.md`
- 테스트: `bash herdr-orch/tests/run.sh`(가짜 hc·herdr-app·claude·codex 사용, 실제 Herdr 상태를 건드리지 않는다)

## herdr-team

`herdr-orch` 위에 만든 직무 팀 플러그인. 메인(사용자와 대화), 코디네이터(조정), 직무 워커(planner·director·designer·developer·tester)가 일하고, 산출물은 Codex 가 교차 리뷰한다. 화면 프로젝트는 디자인 디렉터(레퍼런스·톤 시안·디자인 시스템)와 designer(화면·래스터 에셋)가 사용자 일괄 승인을 거쳐 디자인을 확정한다.

- 요구사항: Python 3.11 이상, herdr-core `hc`, herdr-app, Claude Code, Codex CLI(`image_generation` 기능을 켠 것. `hteam image` 가 쓴다), Node/npx(리뷰어 브라우저 `hteam-browser` 가 첫 실행에 `chrome-devtools-mcp@1.10.1` 을 내려받는다). herdr-orch 0.1.2 이상도 함께 설치한다.
- 설치: `/plugin marketplace add <이 저장소>` 다음 `/plugin install herdr-orch@herdr-team`, `/plugin install herdr-team@herdr-team`. 범위는 프로젝트(`--scope project`, 팀이 같이 쓴다) 또는 사용자(`--scope user`) 중에서 고른다.
- 명령(Claude Code 슬래시 명령)
  - `/herdr-team:init <프로젝트 설명>`: 새 프로젝트를 세팅한다(`.herdr-team/`, `CLAUDE.md`·`AGENTS.md` 절). 도구·권한은 표로 제안하고 승인받은 것만 적용한다.
  - `/herdr-team:up`: 수동 복구. 코디네이터와 watch 를 올리고 열린 질문을 다시 묻는다. 코디네이터는 보통 메인 세션 훅이 자동으로 다시 띄운다(아래 "코디네이터 복구").
  - `/herdr-team:image`: designer 의 래스터 에셋을 `hteam image` 로 만든다.
- 점검: `.herdr-team/bin/hteam doctor`
- 설계: `docs/superpowers/specs/2026-11-05-herdr-team-design.md`
- 테스트: `bash herdr-team/tests/run.sh`(가짜 hc·herdr-app·claude·codex 사용)

### 문구 규칙

- `.herdr-team/text-rules.md`(작성·리뷰 공통 규칙)와 planner 가 기획 때 정하는 `docs/planning/voice.md`(문체·호칭·라벨·용어집). designer·developer 는 서비스 문구(UI 라벨·버튼·오류·알림), 정책 문서(`docs/policy/`), 사용자 문서(`README.md`, `docs/user/`)를 쓸 때 지키고 보고서에 `### 문구 점검` 을 둔다. 정책·사용자 문서는 developer 가 맡는다(템플릿 developer owns 에 `README.md`·`docs/user/**`·`docs/policy/**`).
- 리뷰: `text-rules.md` 가 있고 한글 문구가 든 파일을 바꾼 태스크면 직무와 관계없이 리뷰 프롬프트에 "문구 기준" 절이 붙는다. 태스크가 추가한 줄의 의심 위치(오탈자, 이중피동, 번역투, 상투어, hedging, 챗봇 잔재, 쉼표, 용어집의 쓰지 않는 표기, 높임법 섞임)를 경고로 넣는다. 자동 불합격은 없고 판정은 리뷰어가 text-rules §5 로 한다.

### 디자인 규칙과 리뷰

- `.herdr-team/design-rules.md`: §1 AI 티 금지 목록 10개, §2–§7(접근성 WCAG 2.2 AA, 색, 글자, 레이아웃, 표면·동작, 상태), 즉시 차단 항목 10개(보고서에 예외를 적어도 리뷰가 P1). UI 를 바꾼 태스크는 보고서에 `### 디자인 점검` 을 둔다.
- 리뷰 디자인 절(director 직무가 있는 프로젝트의 director·designer·developer 태스크): 기준 1–9. 이 태스크가 만든 문제만 `(새로 생김)`·`(회귀)`·`(기존)` 으로 나눠 지적하고, diff 의 지운 줄을 읽고, 빠진 상태를 찾고, 즉시 차단 항목은 P1, 고칠 방향은 싼 것부터.
- 자동 검사(경고): diff 의 지운 줄에서 줄어든 접근성·글자 신호와 추가한 줄의 확대 막기·`focus-visible` 없는 포커스 제거(designdiff) 먼저, 바뀐 파일의 이모지·왼쪽 강조 테두리·파랑·보라 그라디언트(내용 검사) 뒤, 합쳐 50건까지. 리뷰어가 볼 경고는 `.herdr-team/bin/hteam lint --task T` 로 미리 본다(`findings` 는 디자인, `text_findings` 는 문구).

### 코디네이터 복구

- 자동 부활: 메인 세션 훅(세션 시작, 그리고 매 프롬프트 60초 간격)이 코디네이터 터미널을 확인하고, 확실히 끝났거나(exited) 셸로 바뀌었으면(lost) `hteam up` 을 분리 실행한다. 메인은 답변 첫 줄에 사용자에게 알린다. 꺼진 동안 `hteam tell` 로 넘긴 요청은 Run 메일함에 쌓였다가 새 코디네이터가 처리한다.
- 끄기: `.herdr-team/config.toml` 의 `[coordinator] auto_up = false`(안내만 한다). 키가 없으면 켜진다.
- 기록: `.herdr-team/state/auto-up.log`(자동 실행한 `hteam up` 출력), `auto-up.json`(마지막 확인·실행 시각과 안내).
- 다시 띄운 코디네이터가 10분 안에 다시 꺼지거나 뜨지 못하면 다시 띄우지 않고 안내만 한다(로그를 보고 `/herdr-team:up`). 같은 안내는 바뀌었거나 세션을 새로 열 때만 다시 한다(실제로 다시 띄운 안내는 늘 한다).
- 수동 복구 `/herdr-team:up`: 자동 부활이 꺼져 있거나, 훅이 확인하지 못했다고 안내했을 때(hc 조회 실패, `hc rm` 으로 지운 터미널: 사용자에게 그 pane 이 끝났는지 확인한 뒤 `--force`), 메인을 다시 열어 열린 질문을 다시 물을 때.
- 한계: 살아 있지만 멈춘 코디네이터(권한 창 대기 등)는 알지 못한다. 메인 세션 밖에서 죽으면 다음 메인 프롬프트(최대 60초 간격)나 세션 시작까지 모른다. 죽은 코디네이터 터미널은 팀 탭에 남는다.

### herdr-team 보안 주의

- Claude 권한 우회(`--permission-mode=bypassPermissions`)와 Codex 샌드박스 우회는 `init` 에서 사용자가 승인했을 때만 `.herdr-team/config.toml` 에 들어간다. 승인하면 워커·리뷰어·코디네이터가 사용자의 git·클라우드 자격 증명과 셸 환경을 그대로 쓴다.
- `hteam image`(designer 의 래스터 에셋)는 이 승인과 관계없이 `codex exec` 를 샌드박스 우회로 돌린다(image_gen 결과 파일을 읽으려고, 설계 14장). 프롬프트는 이미지 생성만 시키고 결과는 검사한 PNG 만 게시한다.
- 리뷰어 브라우저: Codex 리뷰어는 격리·헤드리스 `hteam-browser` 로 화면을 렌더한다(사용자 Chrome 의 쿠키·로그인을 쓰지 않는다). 다만 우회를 승인하면 리뷰어가 읽는 워커 코드·웹 페이지의 글이 명령을 실행시킬 수 있다. Claude 리뷰어는 격리되지 않은 사용자 자신의 Chrome DevTools MCP 를 쓰므로 페이지 스크립트가 그 브라우저 프로필에서 돈다. 필요하면 프로젝트 `.mcp.json` 에 `--isolated=true` 정의를 둔다.
- 레퍼런스 캡처와 이미지는 저장소 밖 캐시 `~/.cache/herdr-team/{refs,images}` 에 둔다.
- hteam 이 띄우는 codex 에서는 사용자의 `chrome-devtools` MCP 서버만 끈다(`hteam-browser` 와 같은 일을 한다). 사용자의 다른 MCP 서버는 끄지 않는다.
- 코디네이터 자동 부활은 사용자가 따로 하지 않아도 메인 세션 훅이 메인 세션의 권한·환경으로 `hteam up` 을 실행하고, 코디네이터는 `[agents.claude].args`(승인한 우회 포함)로 뜬다. 띄우는 것은 이미 승인한 코디네이터와 같은 명령이다. 끄려면 `[coordinator] auto_up = false`.

### 이미 세팅한 프로젝트 업그레이드

scaffold 는 있는 파일을 덮어쓰지 않는다. 앞 버전에서 세팅한 프로젝트는 새 기능을 손으로 옮겨야 하고, 옮기지 않으면 조용히 빠진다(예: `[roles.director]` 가 없으면 디자인 디렉터 단계와 시스템 보강이 없다).

#### 0.1.x → 0.2.0

1. 플러그인만 올려도 적용되는 것: 리뷰 디자인 절의 새 기준과 diff 자동 검사(director 직무가 있는 프로젝트), 코디네이터 자동 부활(`[coordinator] auto_up` 키가 없으면 켜진다. 끄려면 `auto_up = false`). 옛 `design-rules.md`(§ 제목이 없는 금지 목록)는 리뷰가 §1·즉시 차단 항목만 본다.
2. 새 파일: 프로젝트 루트에서 `.herdr-team/bin/hteam scaffold --description-file .herdr-team/project.md` 를 다시 하면 `.herdr-team/text-rules.md` 가 생긴다. 이 파일이 있어야 리뷰에 문구 절이 붙는다.
3. 손으로 합칠 것(워커가 새 규칙으로 쓰게, `herdr-team/templates/` 의 같은 이름 파일과 비교한다. 프로젝트에서 고친 곳은 합친다)
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
