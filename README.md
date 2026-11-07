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
  - `/herdr-team:up`: 세션을 열 때 코디네이터와 watch 를 올리고 열린 질문을 다시 묻는다.
  - `/herdr-team:image`: designer 의 래스터 에셋을 `hteam image` 로 만든다.
- 점검: `.herdr-team/bin/hteam doctor`
- 설계: `docs/superpowers/specs/2026-11-05-herdr-team-design.md`
- 테스트: `bash herdr-team/tests/run.sh`(가짜 hc·herdr-app·claude·codex 사용)

### herdr-team 보안 주의

- Claude 권한 우회(`--permission-mode=bypassPermissions`)와 Codex 샌드박스 우회는 `init` 에서 사용자가 승인했을 때만 `.herdr-team/config.toml` 에 들어간다. 승인하면 워커·리뷰어·코디네이터가 사용자의 git·클라우드 자격 증명과 셸 환경을 그대로 쓴다.
- `hteam image`(designer 의 래스터 에셋)는 이 승인과 관계없이 `codex exec` 를 샌드박스 우회로 돌린다(image_gen 결과 파일을 읽으려고, 설계 14장). 프롬프트는 이미지 생성만 시키고 결과는 검사한 PNG 만 게시한다.
- 리뷰어 브라우저: Codex 리뷰어는 격리·헤드리스 `hteam-browser` 로 화면을 렌더한다(사용자 Chrome 의 쿠키·로그인을 쓰지 않는다). 다만 우회를 승인하면 리뷰어가 읽는 워커 코드·웹 페이지의 글이 명령을 실행시킬 수 있다. Claude 리뷰어는 격리되지 않은 사용자 자신의 Chrome DevTools MCP 를 쓰므로 페이지 스크립트가 그 브라우저 프로필에서 돈다. 필요하면 프로젝트 `.mcp.json` 에 `--isolated=true` 정의를 둔다.
- 레퍼런스 캡처와 이미지는 저장소 밖 캐시 `~/.cache/herdr-team/{refs,images}` 에 둔다.
- hteam 이 띄우는 codex 에서는 사용자의 `chrome-devtools` MCP 서버만 끈다(`hteam-browser` 와 같은 일을 한다). 사용자의 다른 MCP 서버는 끄지 않는다.

### 이미 세팅한 프로젝트 업그레이드

scaffold 는 있는 파일을 덮어쓰지 않는다. 1·2단계에서 세팅한 프로젝트는 새 기능을 손으로 옮겨야 하고, 옮기지 않으면 조용히 빠진다(예: `[roles.director]` 가 없으면 디자인 디렉터 단계와 시스템 보강이 없다).

1. 새 파일은 `hteam scaffold` 를 다시 하면 생긴다: `.herdr-team/design-rules.md`, `.herdr-team/roles/director.md`.
2. 손으로 합칠 것(`herdr-team/templates/` 의 같은 이름 파일과 비교한다)
   - `.herdr-team/config.toml`: `[roles.director]` 절과 `[agents.codex].args` 의 `hteam-browser` 한 쌍(`"-c", 'mcp_servers.hteam-browser={…}'`). Codex 리뷰어가 브라우저를 쓰게 하려면 `--dangerously-bypass-approvals-and-sandbox` 도 넣는다(위 보안 주의를 읽고 정한다).
   - `.herdr-team/roles/designer.md`: `## 시작`, `## 도구`, `## 시스템 적용 규칙`, `## 시스템이 없을 때`, `## 확인한 화면`.
   - `.herdr-team/roles/developer.md`: `## 화면 규칙`.
   - `.herdr-team/roles/planner.md`: `ui-foundation`·`design-direction` 태스크를 두라는 줄.
   - `.herdr-team/coordinator.md`: `## 디자인 시스템 보강`, 직무 목록의 director 줄.
   - `CLAUDE.md` 의 herdr-team 절(`<!-- herdr-team -->`): "질문 표시 규칙"의 두 줄(`render.context` 를 답변 글로 먼저 보이고 같은 응답에서 이어서 AskUserQuestion 을 부른다)과 `stale_question` 줄.

## 보안 주의

워커는 사람 없이 돈다. `--agent-arg` 로 권한 우회(Claude `--permission-mode`, Codex 샌드박스 우회)를 넘기면 워커가 사용자의 자격 증명(git, 클라우드 인증, 셸 환경)을 그대로 쓴다. 신뢰할 수 있는 저장소에서만 쓴다. horch 의 권한 확인은 실수 방지용이지 보안 경계가 아니다.
