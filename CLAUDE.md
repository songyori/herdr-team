# herdr-team

Herdr(herdr-app 창 + herdr-core `hc`) 위에서 멀티 에이전트 오케스트레이션을 돌리는 Claude Code 플러그인 저장소다.

- `herdr-orch`: 오케스트레이션 계층(Run, 워커 실행, 메일함, ask/reply, worker_done). Orca orchestration 에 해당한다.
- `herdr-team`: 직무 팀 계층(메인·코디네이터·직무 워커, 직무별 모델, Codex 교차 리뷰). `herdr-orch` 위에 만든다.

Orca 와 orca-team 코드에 의존하지 않는다. 개념만 참고한다.

## 개발 절차

브레인스토밍 → 설계(`docs/superpowers/specs/`) → 구현 계획(`docs/superpowers/plans/`) → 태스크별 구현 → 브랜치 최종 리뷰 → 실환경 확인 → main 병합.
작업 브랜치에서 하고 main 에 직접 커밋하지 않는다.

## Codex 교차 검증

Claude 가 만든 산출물은 Codex 가 검증한다. 다음 네 시점에 반드시 돌린다.

| 시점 | 대상 | 명령 |
|---|---|---|
| 설계 문서 작성·자체 검토 뒤, 사용자 검토 전 | 설계 문서 | `scripts/codex-review.sh doc <이름> <프롬프트 파일>` |
| 구현 계획 작성 뒤, 실행 전 | 계획 문서 | 위와 같다 |
| 태스크 커밋마다 | 그 커밋 | `scripts/codex-review.sh commit <sha>` |
| main 병합 전 | 브랜치 전체 | `scripts/codex-review.sh base main` |

- 리뷰는 셸 백그라운드가 아니라 Herdr pane 에서 돌린다. 스크립트가 호출한 터미널과 같은 space 의 "리뷰" 탭에 pane 을 띄우고 터미널 주소를 출력한다. 화면은 지금 탭에 머문다. 끝나면 pane 이 닫히고, 마지막 리뷰가 끝나면 "리뷰" 탭도 사라진다.
- 리뷰가 끝나기를 붙잡고 기다리지 않는다. `hc wait <주소> --timeout 3600` 을 백그라운드로 걸어 끝났다는 알림만 받고, 그동안 다른 일을 한다.
- 결과는 `.codex-reviews/<이름>.md`, 전체 출력은 `.log`, 종료 코드는 `.exit` 에 남는다. 커밋 리뷰 이름은 `commit-<sha 7자>`, 브랜치 리뷰는 `base-<브랜치>` 다.

- 문서 리뷰 프롬프트는 문서 경로와 함께 다음을 묻는다: 잘못된 가정, 빠진 실패 경로, 문서 안의 모순, 구현할 수 없는 요구, 범위 과잉. 심각도(P0–P3)와 근거 위치를 붙이게 한다.
- 결과는 `.codex-reviews/` 에 남긴다(커밋하지 않는다).
- 지적은 그대로 따르지 않는다. 항목마다 코드나 문서로 사실인지 확인한 뒤 고치거나, 고치지 않는 이유를 적는다.
- P0·P1 이 남지 않을 때까지 고치고 다시 돌린다. 최대 3 라운드다. 3 라운드 뒤에도 남으면 사용자에게 묻는다.
- 사용자에게 보고할 때 Codex 가 무엇을 지적했고 무엇을 고쳤는지, 무엇을 왜 고치지 않았는지 적는다.
