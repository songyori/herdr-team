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

## 보안 주의

워커는 사람 없이 돈다. `--agent-arg` 로 권한 우회(Claude `--permission-mode`, Codex 샌드박스 우회)를 넘기면 워커가 사용자의 자격 증명(git, 클라우드 인증, 셸 환경)을 그대로 쓴다. 신뢰할 수 있는 저장소에서만 쓴다. horch 의 권한 확인은 실수 방지용이지 보안 경계가 아니다.
