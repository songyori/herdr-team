---
name: init
description: >
  새 프로젝트에 herdr-team(메인·관제·고정 에이전트, Claude ↔ Codex 교차 리뷰)을 세팅한다.
  트리거: "/herdr-team:init <프로젝트 설명>". 설명 없이 부르면 한 줄로 묻는다.
argument-hint: "<프로젝트 설명>"
---

# /herdr-team:init

이 세션은 **메인**이다. 단계 순서를 바꾸지 않는다. 명령은 적힌 그대로 실행한다.

아래 `HTEAM` 은 `python3 "${CLAUDE_PLUGIN_ROOT}/bin/hteam"` 이다. 3단계 이후에는 프로젝트 shim `.herdr-team/bin/hteam` 을 쓴다. 모든 명령은 JSON 한 개를 출력한다.

## 1. 설명 확인
인자: `$ARGUMENTS`

비어 있으면 "어떤 프로젝트인지 한두 문장으로 알려 달라"고 묻고 멈춘다.

## 2. 점검
`HTEAM doctor` 를 실행한다.
- `git_repo` 경고면 `git init` 뒤 `git commit --allow-empty -m "chore: init"` 을 실행한다.
- exit 1(`unhealthy`)이면 `checks` 에서 `ok: false`·`level: error` 항목과 detail 을 표로 보여 주고 멈춘다.
- `codex_image_generation`·`chrome_devtools_mcp`·`codex_browser` 경고는 멈추지 않는다. 6단계 보고에 적는다(`codex_browser` 는 `[agents.codex].args` 에서 우회나 `hteam-browser` 정의를 지웠을 때 뜬다).

## 3. 스캐폴드
설명 원문을 스크래치 파일에 쓰고 `HTEAM scaffold --description-file <그 파일>` 을 실행한다. 출력의 `created`·`skipped` 를 기억한다.

출력의 `setup_mode` 가 false 면 이 프로젝트는 이미 세팅을 마쳤다(`setup-done`). 사용자에게 그렇게 알리고, 다시 세팅하려면 묻는다. 다시 세팅하면 `.herdr-team/state/setup-done` 을 지우고 scaffold 를 다시 실행한다. 그대로 두면 4단계에서 제품 파일(`.mcp.json` 등)을 고치는 것을 훅이 막는다. 그때는 그런 항목을 적용하지 않고 표에 "setup-mode 아님"으로 남긴다.

## 4. 판단이 필요한 한 단계
프로젝트 설명과 저장소 구조를 보고 표 하나로 제안한다.

| 구분 | 이름 | 이유 | 바꿀 것 |
|---|---|---|---|

- 직무별 owns: `.herdr-team/config.toml` 의 `[roles.*].owns`. 예: Next.js 면 developer `["src/**", "app/**", "package.json"]`.
- 직무: 기본 직무는 planner·director·designer·developer·tester 다. 화면이 없는 프로젝트(CLI·라이브러리 등)면 `[roles.director]`·`[roles.designer]` 와 `user_approval_roles` 의 `"designer"` 를 빼고 `.herdr-team/roles/director.md`·`.herdr-team/roles/designer.md` 를 지우자고 제안한다. 화면이 있으면 디자인 디렉터 단계(레퍼런스·톤 시안·디자인 시스템을 사용자에게 차례로 묻는다)를 거치고, 레퍼런스 캡처에 Chrome DevTools MCP 를 쓴다는 것을 표에 적는다. 추가 직무는 기본 직무로 부족할 때만 둔다. `.herdr-team/roles/<직무>.md`(기본 직무 문서와 같은 절 구성)와 config 항목을 같이 만든다.
- 고정 에이전트 구성(`[crew.<이름>]`, `[overflow]`): 한 세션이 그 직무 태스크와 수정 라운드를 이어 맡는다(묶음이 끝나면 인수인계를 쓰고 세션을 비운다). 템플릿은 `production`(planner·designer·developer), `research`(director), `test`(tester)다. production·research 는 Claude, test 는 Codex 다. 테스트는 생산과 다른 모델이 수용 기준으로 짜고 그 리뷰는 반대쪽인 Claude 가 한다. 한 직무는 한 에이전트에만 둔다. 지운 직무는 `roles` 에서도 뺀다(화면이 없으면 `research` 를 지우고 `production` 에서 designer 를 뺀다). 에이전트마다 모델이 하나라 그 에이전트의 모든 직무 태스크가 그 모델로 돈다(비용을 표에 적는다). Codex 로 일하는 고정 에이전트(`agent = "codex"`)는 그 직무 표에도 `worker = "codex"` 가 있어야 태스크를 받는다. director·designer 를 가진 에이전트는 claude 만 된다. `[overflow] enabled`(기본 true)는 고정 에이전트가 바쁠 때 준비된 독립 태스크를 임시 워커로 돌린다.
- 필요한 도구(Chrome DevTools MCP 등). 이미 설치된 것은 넣지 않는다. 넣는다면 프로젝트 범위(`.mcp.json`)로만 넣는다. Claude 리뷰어는 워커 화면을 사용자 자신의 Chrome DevTools MCP 로 렌더한다(격리된 `hteam-browser` 가 아니다). 페이지 스크립트가 그 브라우저 프로필에서 돌므로, 원하면 프로젝트 `.mcp.json` 에 격리 정의(`--isolated=true`)를 두자고 제안한다.
- Claude 권한 모드(`[agents.claude].args`): 워커는 사람 없이 돌므로 `--permission-mode=bypassPermissions` 가 필요할 수 있다. `[agents.claude].args` 는 Claude 워커·리뷰어(고정 에이전트 포함)를 띄울 때마다 붙는다(관제는 Claude 가 아니다). 넣으면 워커·리뷰어가 확인 없이 사용자의 git·클라우드 자격 증명과 셸 환경을 그대로 쓴다는 위험을 표에 적는다. 사용자가 승인했을 때만 넣는다.
- Codex 는 늘 샌드박스·승인 우회로 돈다(`[agents.codex].args` 의 `--dangerously-bypass-approvals-and-sandbox`, 템플릿 기본). 표에서 묻지 않고 위험만 한 줄로 적는다: Codex 워커·리뷰어가 사용자 권한·자격 증명·네트워크를 그대로 쓴다, 리뷰어가 읽는 워커 코드·웹 페이지의 글이 명령을 실행시킬 수 있다, 저장소 밖 변경은 변조 검사가 잡지 못한다, 사용자 Codex 설정의 다른 MCP 서버도 승인 없이 쓸 수 있다(hteam 은 같은 일을 하는 `chrome-devtools` 만 hteam 이 띄우는 codex 에서 끈다. 다른 이름은 범위 밖이다). 그 덕에 리뷰어가 기본 설정의 `hteam-browser`(chrome-devtools, 헤드리스·격리)로 화면을 렌더하고 개발 서버를 띄운다. `hteam image`(designer 의 래스터 에셋)도 `codex exec` 를 우회로 돌린다(image_gen 결과 파일을 읽으려고, 14장). 프롬프트는 이미지 생성만 시키고 결과는 검사한 PNG 만 게시한다.
- 작업 공간(`[workspace]`, 기본 끔): 병렬 개발이 필요한지 본다(동시에 개발 태스크를 둘 이상 돌리고 시험이 DB·포트를 쓰는지). 필요하면 `mode = "worktree"` 와 슬롯 수(`slots`, 1–9), 슬롯 준비·정리 명령(`setup`·`teardown`, 셸 문자열. 관제 권한으로 슬롯 폴더에서 돈다), 슬롯별 환경 변수(`[workspace.env]`, 값의 `{slot}` 은 슬롯 번호. 이름에 `KEY`·`SECRET`·`TOKEN` 을 쓰지 않는다)를 제안한다. 켜면 개발·테스트 직무(`roles`, 기본 developer·tester) 태스크가 `.herdr-team/state/slots/slot-<N>` worktree 의 `herdr/T-xxx` 브랜치에서 돌고, 리뷰가 승인하면 관제가 기준 브랜치에 병합한다. 그 직무는 임시 워커만 맡으므로 `[crew.*]` 의 `roles` 에서 빼고 `user_approval_roles` 에 두지 않는다. 시험 도구 설정(vitest·jest·ESLint·`tsconfig.json`·pytest 등)에서 `.herdr-team/` 를 빼자고 함께 제안한다(슬롯 사본이 메인 폴더 안에 있다). 켜기로 하면 적용한 뒤 `.herdr-team/bin/hteam doctor` 를 다시 실행해 `workspace_git`·`workspace_head` 를 본다(git 2.23 이상, 첫 커밋). 필요 없으면 표에 "쓰지 않음" 으로 적고 `[workspace]` 를 넣지 않는다.
- Redmine 연동(`[redmine]`, 기본 끔): Redmine 이슈로 일하는 프로젝트인지 묻는다. 쓰면 URL(`url`), API 키를 담은 환경 변수 이름(`key_env`, 늘 둔다), 키를 파일에 두면 그 파일(`env_file`, git 이 추적하지 않는 파일. 그 파일의 `key_env` 이름 줄에서 읽는다), 상태 번호(`status = { start, done, changes, closed }`)를 받는다. **API 키 값은 묻지도 받지도 않는다.** 사용자가 키를 붙여 넣으면 쓰지 않고, 그 환경 변수나 `env_file` 에 직접 두라고 안내한다. 이슈 상태·노트는 관제가 바꾼다(워커·리뷰어·메인은 바꾸지 않는다). 쓰지 않으면 `[redmine]` 을 넣지 않는다.
- 작업 공간·Redmine 은 승인한 것만 `.herdr-team/config.toml` 의 `[workspace]`·`[redmine]` 표로 쓴다(config.toml 의 주석 예시와 같은 꼴).
- AskUserQuestion 한 번으로 승인받는다. 선택지 "전부 승인 (추천)", "바꾸지 않고 진행". 일부 제외는 Other 로 받는다.
- 승인된 항목을 적용한다. 실패해도 멈추지 않고 결과를 표에 남긴다.
- 바꾸는 곳은 이 프로젝트 안뿐이다. 사용자 전역 설정(`~/.claude/`, `~/.claude.json`, `~/.codex/`)을 고치지 않는다. Codex 의 폴더 신뢰와 우회는 전역 설정에 쓰지 않는다. 신뢰는 horch 가 실행마다 넘기고, 우회는 이 프로젝트의 `[agents.codex].args` 에 있다.

## 5. 관제
1. `.herdr-team/bin/hteam up --wait-run 180` 을 Bash `timeout: 240000` 으로 실행한다. 관제(`hteam drive`)가 관제 탭(`herdr-team 관제`)에 떠서 Run 을 만든다.
   - exit 4 면 관제가 180초 안에 Run 을 만들지 않았다. 사용자에게 관제 탭을 보고 출력을 알려 달라고 한다. 키를 대신 누르지 않는다.
   - exit 3 `launch_raced` 면 다른 `hteam up` 이 동시에 관제를 띄웠거나 관제가 Run 에 묶였다. `.herdr-team/bin/hteam up --wait-run 180` 을 한 번 더 실행한다(살아 있으면 다시 띄우지 않는다).
   - exit 1 `launch_uncertain` 이면 관제가 떴는지 확인하지 못했다. 사용자에게 관제 탭에 `name` pane(`hteam-drive-…`)이 있는지 보라고 알린다. 떴다면 스스로 Run 에 묶인다. 아니면 180초 뒤 `/herdr-team:up` 이 새로 띄운다.
   - 출력 `status` 가 `hung` 이면 관제 프로세스가 살아 있지만 응답이 없다. 사용자에게 관제 탭을 보라고 알린다.
2. Bash `run_in_background: true` 로 `.herdr-team/bin/hteam watch` 를 띄운다. 이후 watch 가 끝날 때마다 CLAUDE.md 의 "메인 규칙"대로 처리하고 다시 띄운다.

5단계가 어떻게 끝나도(exit 1·3·4 포함) 6단계로 간다. setup-mode 를 켠 채 두지 않는다. 관제가 아직 없으면 6단계 보고에 그 상태와 "`/herdr-team:up` 으로 다시 띄운다"를 적는다.

## 6. 마무리
1. `.herdr-team/bin/hteam setup-done` 을 실행한다.
2. 세팅 파일을 경로를 지정해 커밋한다. 경로는 `CLAUDE.md AGENTS.md .gitignore .herdr-team` 과 4단계에서 바뀐 파일이다: `git add -- <경로> && git commit -m "chore: herdr-team 세팅" -- <경로>`. `.herdr-team/state/` 는 `.gitignore` 로 빠진다.
3. 보고한다: 준비 완료, 관제 터미널, 고정 에이전트 구성, 적용 결과 표, 경고, "다음 메시지로 첫 업무를 주면 된다".

## 하지 않는 것
- `horch` 와 `hteam drive` 직접 호출. 메인이 Run 에 묶이거나 관제가 되면 깨우기 글이 사용자 입력란에 들어온다.
- 기획·코드 작업 시작. 첫 업무는 사용자의 다음 메시지부터다.
- 사용자 전역 Claude·Codex 설정 고치기, 승인받지 않은 Claude 권한 우회.
- Redmine API 키 값을 묻거나 받거나 `config.toml` 에 쓰기.
