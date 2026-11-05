---
name: up
description: >
  herdr-team 프로젝트에서 메인 세션을 다시 열었을 때 코디네이터와 watch 를 되살리고 열린 질문을 다시 묻는다.
  트리거: "/herdr-team:up", SessionStart 안내.
---

# /herdr-team:up

이 세션은 메인이다. 아래 `hteam` 은 `.herdr-team/bin/hteam` 이다.

1. `hteam status` 를 실행한다.
2. `coordinator.alive` 와 `coordinator.starting` 이 모두 false 면 `hteam up --wait-run 180` 을 Bash `timeout: 240000` 으로 실행한다.
   - exit 4 면 코디네이터 pane 이 확인 창(폴더 신뢰 등)에서 멈췄을 수 있다. 사용자에게 그 pane 을 보라고 알린다. 키를 대신 누르지 않는다.
   - exit 3 `coordinator_unverifiable` 이면 기록된 코디네이터 터미널(`terminal`)의 상태를 확인할 수 없다(기록은 그대로 두었다). 사용자에게 그 pane 이 끝났는지 묻는다. 끝났다고 하면 `hteam up --force --wait-run 180`, 아니면 그대로 둔다.
   - exit 3 `launch_raced` 면 다른 `hteam up` 이 동시에 코디네이터를 띄웠거나 코디네이터가 bind 했다. `hteam up --wait-run 180` 을 한 번 더 실행한다(살아 있으면 다시 띄우지 않는다).
   - exit 1 `launch_uncertain` 이면 코디네이터가 떴는지 확인하지 못했다. 사용자에게 팀 탭에 `name` pane 이 있는지 보라고 알린다. 떴다면 스스로 bind 한다. 아니면 180초 뒤 `hteam up` 이 새로 띄운다.
   - exit 1 `bad_run_file` 이면 `.herdr-team/state/run.json` 이 손상됐다. 고치지 말고 사용자에게 알린다(hint 를 그대로 전한다).
3. `watch_alive` 가 false 면 Bash `run_in_background: true` 로 `hteam watch` 를 띄운다. `unread_outbox` 가 0 보다 크면 watch 가 바로 끝나며 밀린 메시지를 준다.
4. `open_questions` 가 비어 있지 않으면 `hteam reask` 를 실행한다. 출력 `messages` 는 watch 와 같은 형식이다. CLAUDE.md 의 "질문 표시 규칙"대로 하나씩 묻고 답을 `hteam answer <id> "<답>"` 으로 돌려준다. reask 는 watch 가 이미 전한 질문만 다시 준다.
5. 보고한다: 코디네이터 상태, 진행 중 태스크(id, 직무, 상태, 라운드) 표, `config_error` 가 있으면 그 내용.
