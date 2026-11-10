---
name: up
description: >
  수동 복구. 관제는 보통 메인 세션 훅이 자동으로 살린다(config.toml `[drive] auto_up`).
  자동 부활이 꺼져 있거나 훅이 안내했을 때, 메인을 다시 열어 열린 질문을 다시 물을 때 쓴다.
  트리거: "/herdr-team:up", 훅 안내.
---

# /herdr-team:up

이 세션은 메인이다. 아래 `hteam` 은 `.herdr-team/bin/hteam` 이다. 관제(`hteam drive`)는 관제 탭에서 도는 프로그램이다. 메인은 `hteam drive` 를 직접 실행하지 않는다(훅이 막는다).

1. `hteam status` 를 실행한다. `run_error` 가 있으면 `.herdr-team/state/run.json` 이 손상됐다. 고치지 말고 그 내용을 사용자에게 알리고 멈춘다(`hteam up` 도 exit 1 `bad_run_file` 로 거부한다). `config_error` 에 `[coordinator]` 가 있으면 0.3.0 설정이다. 사용자에게 알리고 멈춘다(README "0.3.0 → 0.4.0": `config.toml` 을 지운 뒤 `/herdr-team:init`, 또는 템플릿의 `[drive]`·`[overflow]`·`[crew.*]` 로 손으로 바꾼다).
2. `drive.hung` 이 true 면 다시 띄우지 않는다. 관제 프로세스가 살아 있지만 응답이 없다. 사용자에게 관제 탭(`herdr-team 관제`)의 출력을 보라고 알린다.
3. `drive.alive`·`drive.hung`·`drive.starting` 이 모두 false 면 `hteam up --wait-run 180` 을 Bash `timeout: 240000` 으로 실행한다. 출력 `status` 는 `running`(이미 살아 있다), `hung`, `starting`(띄운 지 180초 안이다. `hteam status` 로 다시 본다), `launched` 다.
   - exit 4 면 관제가 180초 안에 Run 을 만들지 않았다. 사용자에게 관제 탭을 보라고 알린다.
   - exit 3 `launch_raced` 면 다른 `hteam up` 이 동시에 관제를 띄웠거나 관제가 Run 에 묶였다. `hteam up --wait-run 180` 을 한 번 더 실행한다(살아 있으면 다시 띄우지 않는다).
   - exit 1 `launch_uncertain` 이면 관제가 떴는지 확인하지 못했다. 사용자에게 관제 탭에 `name` pane(`hteam-drive-…`)이 있는지 보라고 알린다. 떴다면 스스로 Run 에 묶인다. 아니면 180초 뒤 `hteam up` 이 새로 띄운다.
   - exit 1 `bad_run_file` 이면 `.herdr-team/state/run.json` 이 손상됐다. 고치지 말고 사용자에게 알린다(hint 를 그대로 전한다).
4. `watch_alive` 가 false 이고 관제가 꺼지지 않았으면(1 에서 `drive.alive`·`drive.hung`·`drive.starting` 가운데 하나가 true 였거나, 3 이 `running`·`hung`·`starting`·`launched` 로 끝났으면) Bash `run_in_background: true` 로 `hteam watch` 를 띄운다. `unread_outbox` 가 0 보다 크면 watch 가 바로 끝나며 밀린 메시지를 준다. 3 이 관제를 띄우지 못했으면(exit 4·1, 그 밖의 오류) watch 를 띄우지 않고 사용자에게 알린다. 꺼진 관제의 watch 는 곧바로 `orphaned` 로 끝나므로 띄워도 소용이 없다(Stop 훅도 그때는 막지 않는다).
5. `open_questions` 가 비어 있지 않으면 `hteam reask` 를 실행한다. 출력 `messages` 는 watch 와 같은 형식이다. CLAUDE.md 의 "질문 표시 규칙"대로 하나씩 묻고 답을 `hteam answer <id> "<답>"` 으로 돌려준다(일괄 승인은 `hteam design-decide <id> --json -`). decide 는 CLAUDE.md 의 "decide 처리 기준"대로 처리하고 `hteam answer <id> "<처리 내용>"` 으로 닫는다. reask 는 watch 가 이미 전한 질문만 다시 준다.
6. 보고한다: 관제 상태(`drive`), 고정 에이전트(`crew`: 이름, 에이전트, 맡은 태스크, 대기열, 리셋 중인지) 표, 진행 중 태스크(id, 직무, 상태, 라운드) 표, `config_error` 가 있으면 그 내용.
