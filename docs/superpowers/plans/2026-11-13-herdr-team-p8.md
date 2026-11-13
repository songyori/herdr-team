# herdr-team 8단계(실사용 보고 결함) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 설계 15.3 의 8번을 만든다. 7단계를 쓰기 시작한 프로젝트가 보고한 결함을 고친다(설계 1장 "보고 처리 (8단계)" 표). 메인 질문 확인 훅이 같은 응답의 글을 찾지 못해 거부하는 것, 메인의 평문 질문이 뒤이은 관제 메시지에 묻혀 지나가는 것, 작업 공간 태스크가 기준 브랜치의 새 커밋을 받을 길이 없는 것, init 뒤 메인 세션을 새로 열라는 안내가 없는 것이다. herdr-team 0.5.0 → 0.6.0, herdr-orch 는 그대로다.

**Architecture:** 훅 스크립트(`herdr-team/hooks/hteam_hook.py`)의 PreToolUse 질문 확인은 처음 읽어 못 찾은 질문만 짧게 다시 읽는다. Stop 훅은 입력의 `last_assistant_message` 에서 질문·부탁 줄을 찾아 한 번 막는다(지금의 watch 검사와 합친다). `hteam fix` 에 `--base-merge` 를 더해 충돌 경로가 쓰던 기준 병합 라운드 장치(`base_merge`·`base`, 워커 사양 둘째 줄, 리뷰 시작의 표시 지우기)를 메인이 열게 한다. 그 부작용 대처로 병합 지시문, 리뷰 프롬프트 한 줄, 완료 요약의 기준을 고친다. 나머지는 템플릿·스킬·README·버전이다.

**Tech Stack:** Python 3.11+ 표준 라이브러리(json, re, time, subprocess, unittest), git 2.23 이상, Claude Code 훅 입력(PreToolUse `transcript_path`, Stop `last_assistant_message`·`stop_hook_active`).

**설계 문서:** `docs/superpowers/specs/2026-11-05-herdr-team-design.md`(이하 "설계"). 8단계 범위는 설계 15.3 의 8번이다. 함께 볼 절: 1장(8단계 사용자 결정 표, 보고 처리 표), 5.10.4(병합 커밋 리뷰 안내), 5.10.6(기준 병합 라운드, 메인이 여는 기준 병합), 5.10.9(8단계 한계), 6.4(`fix`), 7.7(8단계 메인 규칙 줄), 8.4 의 7(완료 요약), 9.1 의 6(init 보고), 9.4(PreToolUse·Stop 줄), 9.6(upgrade `next`), 15.1(8단계 시험), 15.2(8단계 실환경).

**코드가 기준이다.** 이 계획의 수정은 모두 지금 HEAD(브랜치 `design/herdr-team-p8`. 코드는 main 1981a44 와 같고 설계 문서만 다르다)의 코드에 대한 부분 수정이다. 새 모듈은 없다.

**계획 방식(사용자 결정, 6·7단계와 같다):** 시험은 전부, 구현은 규칙·인터페이스. 태스크마다 시험 코드는 전부 블록으로 쓴다. 구현은 `**Interfaces:**`(함수 시그니처와 반환, CLI 인자·exit 코드·오류 code·문구 원문, 상태 필드)와 `**Rules:**`(동작 규칙)로 적고 코드는 구현자가 쓴다.

**편집 표기:** `**Append** \`경로\`` 는 파일 끝에 덧붙인다. `**Edit** \`경로\`` 다음 두 코드 블록은 "찾을 내용"과 "바꿀 내용"이다. 찾을 내용은 적용하는 그 시점의 파일에서 정확히 한 번 나온다.

## Global Constraints

- Python 3.11 이상, 표준 라이브러리만. 외부 패키지 금지. 커밋 전에 바꾼 `.py` 와 `herdr-team/hooks/hteam_hook.py` 를 `python3 -m py_compile` 로 확인한다.
- 모듈 경계(지금 그대로): git 은 `herdr-team/lib/hteam/gitio.py` 에서만 부른다(이미 있는 `branch_tip`·`is_ancestor`·`merge_head`·`parents`·`head` 를 쓴다). 훅은 지금처럼 hteam 모듈을 훅이 실제로 돌 때만 가져온다.
- 모든 명령은 stdout 에 JSON 한 개를 쓴다: 성공 `{"ok": true, ...}`, 실패 `{"ok": false, "error": {"code", "message", "hint"}, ...}`. exit 코드: 0 성공, 1 실패, 2 입력 오류, 3 상태 충돌, 4 대기 초과, 5 권한 없음, 12 의존 없음.
- 잠금 순서는 지금 그대로다: 슬롯 → 프로젝트 → git → finish → 태스크. 질문 확인 훅은 `context-denied.lock` 을 쥔 채 기다린다(설계 9.4).
- 사용자·워커 글은 `--옵션=값` 한 인자로 넘긴다(`--note=`). 커밋은 늘 경로 지정. 예외는 설계 5.10.6 의 기준 병합 커밋 하나(워커가 한다)와 관제의 `git merge --no-ff` 다.
- 설계의 8단계 값(그대로 쓴다):
  - 훅 상수: `CONTEXT_WAIT_S = 2.0`, `CONTEXT_POLL_S = 0.05`. `FINGERPRINT = 80`, `CONTEXT_DENY_MAX = 3`, `TAIL_BYTES = 1 << 20` 은 그대로다. 새 멈춤 지점 이름 `context_first_miss`(첫 읽기에서 못 찾은 질문이 있을 때, 다시 읽기 전).
  - 평문 질문: 줄 끝(뒤의 공백·`)`·`*`·`.` 를 뗀 뒤)이 `?`·`？`·`까요` 이거나, 줄 어디든 `주세요`·`주시면`·`주십시오`·`주시겠어요`·`주셔야` 가 있는 줄. 펜스 코드 블록(```` ``` ````·`~~~` 로 여닫는 줄 사이)과 그 여닫는 줄, 인라인 코드(`` `…` ``), 앞 공백을 뗀 뒤 `>` 로 시작하는 줄은 보지 않는다. 막는 글 원문: `herdr-team: 마지막 글에 사용자에게 묻거나 부탁하는 말이 있다: "<그 줄을 앞뒤 공백을 떼고 120자>". 평문 질문은 뒤이은 관제 메시지에 묻혀 지나간다. 사용자의 답·결정·행동이 필요하면 AskUserQuestion 으로 다시 묻는다(질문 하나, 선택지 2–4개, 추천 하나). 질문이 아니면 그대로 턴을 끝낸다.`
  - `fix --base-merge` 오류: exit 2 `not_workspace`(`T-xxx 는 작업 공간 태스크가 아니다(--base-merge 는 슬롯에서 도는 태스크만)`), exit 3 `merge_in_progress`(`앞 워커가 시작한 병합이 슬롯에 남아 있다. --base-merge 없이 fix 해 그 병합을 먼저 끝낸다`), exit 3 `base_current`(`기준 브랜치의 새 커밋이 없다`), exit 3 `no_base_branch`(`기준 브랜치 <이름> 이 메인 폴더에 없다`). 검사 순서: 지금 `fix` 의 상태·라운드 검사(`allowed`) → `not_workspace` → `merge_in_progress` → `no_base_branch` → `base_current`. 모두 이전 워커를 정리하기 전이고 아무것도 쓰지 않는다.
  - 병합 지시문(워커 사양 작업 공간 절 둘째 줄): 이어 풀기가 아닌 라운드는 `병합한다: ` 뒤에 `먼저 \`git status\` 를 보고 이 태스크의 커밋하지 않은 변경이 있으면 경로 지정 커밋으로 커밋한다(index 에 올린 변경이 있으면 git 이 병합을 거부한다). 그다음 ` 을 넣는다. 이어 풀기 라운드(`merge_resume`)는 지금 문장 그대로에 `앞 워커가 시작한 병합이 남아 있다. 이어서 푼다.` 를 붙인다.
  - 리뷰 안내 줄: `병합 커밋 <sha 7자, ", " 로 이음>은 기준 브랜치의 변경을 이 브랜치에 들여온 것이다. 그 커밋이 들여온 다른 태스크의 변경은 이 태스크의 변경으로 리뷰하지 않는다(그 태스크의 리뷰를 이미 거쳤다). 이 태스크의 변경은 아래 바뀐 파일과 그 커밋의 충돌 해결이다. 리뷰 범위의 다른 규칙(라운드 확인 범위, 묶음 리뷰)은 그대로다.`
- 시험용 환경 변수는 새로 더하지 않는다(멈춤 지점은 지금의 `HTEAM_TEST_PAUSE_AT`·`HTEAM_TEST_PAUSE_FILE`).
- 문서·메시지·주석은 한국어. 명령·코드 식별자는 원문. 템플릿에 물결표 범위(`\d~\d`)를 쓰지 않는다.
- 저장소는 공개돼 있다. 커밋 전에 `git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews'` 가 아무것도 찾지 않아야 한다.
- 버전: Task 4 가 herdr-team 을 `0.6.0` 으로 올린다(`herdr-team/lib/hteam/paths.py` 의 `VERSION`, `herdr-team/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` 의 herdr-team 항목). `HORCH_MIN` 은 `0.3.0` 그대로, herdr-orch 는 바꾸지 않는다.
- 기본값은 지금 동작 그대로다. 달라지는 것은 설계가 정한 넷뿐이다: 질문 확인 훅의 대기, Stop 의 평문 질문 검사, 병합 지시문 문장, 완료 요약의 기준 커밋. 그 밖의 출력·상태·명령은 0.5.0 과 같다.
- 작업 브랜치 `design/herdr-team-p8` 에서 한다. main 에 직접 커밋하지 않는다. main 병합은 이 계획 밖이다(컨트롤러가 한다).
- 테스트: 저장소 루트에서 `bash herdr-team/tests/run.sh`(전체 10–15분). 태스크 중간에는 모듈이나 `-k` 로 고른다(`run.sh` 는 인자를 `unittest discover` 에 넘긴다). **전체 모음은 백그라운드로 하나씩 돌린다. 다른 무거운 일과 함께 돌리지 않는다(이 기계는 함께 돌면 exit 137 로 죽는다).** herdr-orch 는 바꾸지 않으므로 Task 5 에서 한 번만 돌린다.
- **Codex 교차 검증(CLAUDE.md):** 이 계획은 실행 전에 컨트롤러가 `scripts/codex-review.sh doc <이름> <프롬프트 파일>` 로 검토받는다. 각 태스크의 마지막 단계는 커밋이다. **구현자는 커밋에서 멈춘다.** 그 뒤 컨트롤러가 `scripts/codex-review.sh commit <sha>` 를 돌리고(`hc wait <주소> --timeout 3600` 백그라운드), 지적을 코드로 확인해 고치거나 고치지 않는 까닭을 적는다. 리뷰 지적은 P0·P1, 기본 경로의 P2, 회귀를 고치고 가장자리 경우는 알려진 한계로 적는다(사용자 결정).

## File Structure

| 파일 | 바뀌는 것 | 태스크 |
|---|---|---|
| `herdr-team/hooks/hteam_hook.py` | 질문 확인 대기(`CONTEXT_WAIT_S`·`CONTEXT_POLL_S`, 멈춤 지점), Stop 평문 질문 검사(`plain_question`) | 1, 2 |
| `herdr-team/lib/hteam/tasks.py` | `fix(..., base_merge=False)` 거부 검사와 `base_merge`·`base` 쓰기, `fix` CLI 의 `--base-merge`, 큐 args | 3 |
| `herdr-team/lib/hteam/queue.py` | `_x_fix` 가 `base_merge` 를 넘긴다 | 3 |
| `herdr-team/lib/hteam/compose.py` | 병합 지시문 두 형태, `merge_commit_line`, 리뷰 프롬프트에 그 줄(지금 `workspace` 자리에 이어 붙인다. 템플릿은 그대로) | 3 |
| `herdr-team/lib/hteam/drive.py` | `_changed_files` 의 기준을 첫 라운드 `round_base` 로 | 3 |
| `herdr-team/templates/CLAUDE.section.md` | 메인 규칙 줄 셋(평문 질문 Task 2, 기준 병합 Task 3, 업그레이드 Task 4) | 2, 3, 4 |
| `herdr-team/skills/init/SKILL.md` | 마무리 보고의 새 세션 안내, "하지 않는 것" 의 첫 업무 줄 | 4 |
| `herdr-team/lib/hteam/setup.py` | `UPGRADE_NEXT` 끝 문장 | 4 |
| `README.md` | 질문 표시·평문 질문·기준 병합 안내, "0.5.0 → 0.6.0", init 뒤 새 세션 | 4 |
| `herdr-team/lib/hteam/paths.py`, `herdr-team/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` | 0.6.0 | 4 |
| `herdr-team/tests/test_hooks.py`, `test_workspace_merge.py`, `test_drive_flows.py`, `test_setup.py`, `test_cli.py` | 시험 | 1–4 |
| `docs/superpowers/specs/2026-11-05-herdr-team-design.md` | 15.4 의 8단계 실환경 결과, 머리말 상태 | 5 |

---

### Task 1: 질문 확인 훅 대기 (설계 9.4 PreToolUse)

**Files:**
- Modify: `herdr-team/hooks/hteam_hook.py`(상수, `_context_guard_locked`)
- Test: `herdr-team/tests/test_hooks.py`

**Interfaces:**
- 상수(파일 위쪽 `FINGERPRINT`·`CONTEXT_DENY_MAX` 옆): `CONTEXT_WAIT_S = 2.0  # 같은 응답의 글이 transcript 에 늦게 쓰인다(설계 9.4 8단계, 실험 약 0.11초)`, `CONTEXT_POLL_S = 0.05`.
- `_context_guard_locked(p, payload, asked)` 의 바뀐 흐름: 지금처럼 `items` 를 고르고 transcript 를 한 번 읽어 `unshown` 을 만든다. `unshown` 이 비면 `None`. 비지 않으면 `die_at("context_first_miss")` 를 부른 뒤 `time.monotonic()` 기준 `CONTEXT_WAIT_S` 가 지나기 전까지 `CONTEXT_POLL_S` 마다 `_transcript_text` 를 다시 읽어 `unshown` 을 그 안에서 아직 못 찾은 것으로 줄인다. 다시 읽기가 `None`(읽을 수 없음)이면 지금 첫 읽기와 같이 `None`(통과). 다 찾으면 `None`. 시간이 다 되면 남은 `unshown` 만으로 지금의 거부(횟수 기록·거부 글)를 한다.

**Rules:**
- 기다림은 `context-denied.lock` 을 쥔 채다(지금 `_context_guard_locked` 가 잠금 안에서 돈다). 거부 기록은 기다림이 끝난 뒤 한 번만 쓴다.
- 처음에 모두 찾으면 멈춤 지점에도 닿지 않고 기다리지 않는다.
- 거부 글·상한·탈출구 문구는 바꾸지 않는다.

- [ ] **Step 1: 시험 쓰기**

**Append** `herdr-team/tests/test_hooks.py`

```python
class ContextWaitTest(HookCase):
    """8단계(설계 9.4): Claude Code 는 같은 응답의 글을 PreToolUse 훅이 시작한 뒤에 transcript 에 쓴다(실험에서 약 0.11초).
    처음 읽어 못 찾은 질문은 CONTEXT_WAIT_S 동안 다시 읽은 뒤에만 거부한다."""

    def ask(self, n):
        text = f"질문 {n} 을 확정할까요?\n예: 확정이면 진행한다"
        ctx = f"## 맥락 {n}\n" + f"질문 {n} 의 배경 설명이다. 앞 80자가 넘게 길다. " * 3
        self.drive_question({"question": text, "context": ctx,
                             "options": [{"label": "확정 (추천)", "description": "추천 사유: 빠진 것이 없다"},
                                         {"label": "수정", "description": "고칠 곳을 말한다"}]})
        return text, ctx

    @staticmethod
    def line(text):
        return json.dumps({"type": "assistant", "message": {"id": "msg_1", "content": [{"type": "text", "text": text}]}},
                          ensure_ascii=False) + "\n"

    def transcript(self):
        path = self.tmp / "t.jsonl"
        path.write_text(self.line("앞 응답의 글"), encoding="utf-8")
        return path

    @staticmethod
    def payload(transcript, *texts):
        return {"tool_name": "AskUserQuestion", "transcript_path": str(transcript),
                "tool_input": {"questions": [{"question": t} for t in texts]}}

    def paused(self, payload):
        """첫 읽기에서 못 찾은 뒤(멈춤 지점 context_first_miss) 멈춘 훅과 그 문 파일."""
        self.hook("session-start", terminal=MAIN)  # 역할 캐시를 먼저 만든다
        gate = self.tmp / "gate"
        proc = self.hook_bg("guard", payload, terminal=MAIN,
                            env={"HTEAM_TEST_PAUSE_AT": "context_first_miss", "HTEAM_TEST_PAUSE_FILE": str(gate)})
        deadline = time.monotonic() + 20
        while not gate.with_name("gate.reached").exists():
            self.assertLess(time.monotonic(), deadline)
            self.assertIsNone(proc.poll(), "멈춤 지점 전에 끝났다")
            time.sleep(0.05)
        return proc, gate

    def denied(self):
        path = self.state_dir / "context-denied.json"
        return json.loads(path.read_text())["denied"] if path.exists() else {}

    def test_constants(self):
        hook = load_hook()
        self.assertEqual((hook.CONTEXT_WAIT_S, hook.CONTEXT_POLL_S, hook.FINGERPRINT, hook.CONTEXT_DENY_MAX),
                         (2.0, 0.05, 80, 3))

    def test_text_written_after_the_first_read_is_found(self):
        text, ctx = self.ask(1)
        transcript = self.transcript()
        proc, gate = self.paused(self.payload(transcript, text))
        with open(transcript, "a", encoding="utf-8") as fh:  # 같은 응답의 글이 늦게 쓰였다
            fh.write(self.line("표를 먼저 보인다.\n\n" + ctx))
        gate.touch()
        out, err = proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, 0, err)
        self.assertEqual(out.strip(), "")  # 통과(거부 JSON 없음)
        self.assertEqual(self.denied(), {})

    def test_never_written_is_denied_after_the_wait(self):
        text, _ = self.ask(1)
        transcript = self.transcript()
        self.hook("session-start", terminal=MAIN)
        start = time.monotonic()
        out = self.hook("guard", self.payload(transcript, text), terminal=MAIN)
        self.assertGreaterEqual(time.monotonic() - start, 2.0)
        self.assertEqual(self.decision(out), "deny")
        self.assertIn("[out-0001]", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertEqual(self.denied(), {"out-0001": 1})

    def test_found_at_first_read_does_not_wait(self):
        text, ctx = self.ask(1)
        transcript = self.transcript()
        with open(transcript, "a", encoding="utf-8") as fh:
            fh.write(self.line(ctx))
        self.hook("session-start", terminal=MAIN)
        gate = self.tmp / "gate"
        proc = self.hook_bg("guard", self.payload(transcript, text), terminal=MAIN,
                            env={"HTEAM_TEST_PAUSE_AT": "context_first_miss", "HTEAM_TEST_PAUSE_FILE": str(gate)})
        out, err = proc.communicate(timeout=20)  # 멈춤 지점에 닿으면 문이 없어 여기서 시간 초과다
        self.assertEqual((proc.returncode, out.strip()), (0, ""), err)
        self.assertFalse(gate.with_name("gate.reached").exists())

    def test_only_the_late_question_is_waited_for(self):
        (t1, c1), (t2, _) = self.ask(1), self.ask(2)
        transcript = self.transcript()
        proc, gate = self.paused(self.payload(transcript, t1, t2))
        with open(transcript, "a", encoding="utf-8") as fh:
            fh.write(self.line(c1))
        gate.touch()
        out, err = proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, 0, err)
        reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("[out-0002]", reason)
        self.assertNotIn("[out-0001]", reason)
        self.assertEqual(self.denied(), {"out-0002": 1})
```

- [ ] **Step 2: 시험이 실패하는지 본다**

Run: `bash herdr-team/tests/run.sh -k ContextWaitTest`
Expected: FAIL. `test_constants` 는 `AttributeError: ... 'CONTEXT_WAIT_S'`, `test_text_written_after_the_first_read_is_found` 는 멈춤 지점에 닿지 않아 "멈춤 지점 전에 끝났다".

- [ ] **Step 3: 구현**

`herdr-team/hooks/hteam_hook.py` 에 Interfaces·Rules 대로 상수와 다시 읽기를 넣는다. `time` 을 쓰면 파일 위쪽 import 에 더한다.

- [ ] **Step 4: 시험이 통과하는지 본다**

Run: `bash herdr-team/tests/run.sh -k ContextWaitTest` → PASS.
Run: `bash herdr-team/tests/run.sh tests.test_hooks` → 모두 PASS(기존 거부 시험은 거부마다 2초씩 길어진다. `test_context_denied_updates_do_not_race` 의 `communicate(timeout=30)` 안에 든다).

- [ ] **Step 5: 커밋**

```bash
python3 -m py_compile herdr-team/hooks/hteam_hook.py
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews'
git add -- herdr-team/hooks/hteam_hook.py herdr-team/tests/test_hooks.py
git commit -m "fix(herdr-team): 질문 확인 훅이 같은 응답의 글을 2초 동안 다시 읽은 뒤에만 거부

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/hooks/hteam_hook.py herdr-team/tests/test_hooks.py
```

---

### Task 2: 평문 질문 Stop 검사와 메인 규칙 줄 (설계 9.4 Stop, 7.7)

**Files:**
- Modify: `herdr-team/hooks/hteam_hook.py`(`plain_question`, `stop`)
- Modify: `herdr-team/templates/CLAUDE.section.md`
- Test: `herdr-team/tests/test_hooks.py`, `herdr-team/tests/test_setup.py`

**Interfaces:**
- `plain_question(message) -> str | None`: Global Constraints 의 평문 질문 규칙으로 처음 찾은 줄을 앞뒤 공백을 떼고 120자로 자른 글. `message` 가 문자열이 아니거나 찾지 못하면 `None`. 순수 함수다(파일·hteam 모듈을 읽지 않는다).
- `stop(p, payload)` 의 바뀐 흐름:
  1. `stop_hook_active`·`setup-mode`·메인 아님이면 `None`(지금 그대로).
  2. `question = plain_question(payload.get("last_assistant_message"))`. 있으면 막는 글(Global Constraints 원문)을 만든다.
  3. 지금의 watch 검사(Herdr 터미널 밖, `run_id` 없음, 관제 꺼짐이고 미전달 없음, watch 살아 있음이면 watch 글 없음)를 그대로 한다.
  4. 글이 하나라도 있으면 `{"decision": "block", "reason": "\n\n".join([질문 글, watch 글] 가운데 있는 것)}`, 없으면 `None`.
- `CLAUDE.section.md` 의 메인 규칙: "사용자 요청은 기획 태스크로 넘긴다" 번호 목록(1–4) 바로 뒤에 이 줄을 한 줄로 더한다.

```
- 사용자의 답·결정·행동(고르기, 확인, 로그인, 확인 창 승인 등)이 필요하면 언제나 AskUserQuestion 으로 묻는다(질문 하나, 선택지 2–4개, 추천 하나. 자유 답은 Other 로 받는다). 진행 보고 글에 질문이나 부탁을 섞지 않는다. 평문 질문은 턴을 끝내고, 뒤이은 관제 메시지가 메인을 다시 깨워 질문이 밀려 지나간다(어디에도 기록되지 않는다). AskUserQuestion 은 답할 때까지 화면에 남고 그동안 관제는 따로 돈다. 마지막 글에 질문·부탁이 있으면 Stop 훅이 한 번 막는다.
```

**Rules:**
- 평문 질문 검사는 Herdr 터미널 밖이거나 `run_id` 가 없어도 한다(메인 규칙은 관제와 관계없다). watch 검사의 조건은 바꾸지 않는다.
- `last_assistant_message` 가 없는 입력(옛 Claude Code)은 지금과 같다.
- 막는 것은 한 번뿐이다(다음 Stop 은 `stop_hook_active`).

- [ ] **Step 1: 시험 쓰기**

**Append** `herdr-team/tests/test_hooks.py`

```python
class PlainQuestionStopTest(HookCase):
    """8단계(설계 9.4 Stop, 7.7): 메인이 평문으로 묻고 턴을 끝내면 한 번 막는다. 뒤이은 관제 메시지가 메인을 다시 깨워
    질문이 밀려 지나간다(kakao 07:42 사례)."""

    def setUp(self):
        super().setUp()
        (self.state_dir / "run.json").unlink()  # watch 검사가 끼지 않게(run_id 없음)

    def stop(self, message, **extra):
        return self.hook("stop", {"last_assistant_message": message, **extra}, terminal=MAIN)

    def test_plain_questions_are_blocked_once(self):
        kakao = ("기획을 확정했습니다.\n\n**#5682 종료 위험:** 묶음 5 전체 시험이 통과하면 닫힙니다. "
                 "막아야 하면 시험이 끝나기 전에 말씀해 주세요.\n- 막는 방법은 태스크를 덧붙이는 것입니다.\n"
                 "관제 메시지는 백그라운드에서 계속 받고 있습니다.")
        login = "T-003 워커가 로그인 화면에서 멈췄습니다. 사용자께서 직접 로그인해 주셔야 이어 갈 수 있습니다."
        long_line = ("길다 " * 40 + "할까요?").strip()
        cases = ((kakao, "**#5682 종료 위험:** 묶음 5 전체 시험이 통과하면 닫힙니다. 막아야 하면 시험이 끝나기 전에 말씀해 주세요."),
                 ("정리했습니다.\n이대로 진행할까요?", "이대로 진행할까요?"),
                 ("두 안이 있습니다.\n어느 쪽이 괜찮을까요", "어느 쪽이 괜찮을까요"),
                 (login, login),
                 ("결과를 확인해주세요.", "결과를 확인해주세요."),
                 (long_line, long_line[:120]))
        for message, line in cases:
            with self.subTest(line=line[:20]):
                out = self.stop(message)
                self.assertEqual(out and out["decision"], "block", message)
                self.assertIn(f"마지막 글에 사용자에게 묻거나 부탁하는 말이 있다: \"{line}\".", out["reason"])
                self.assertIn("AskUserQuestion 으로 다시 묻는다(질문 하나, 선택지 2–4개, 추천 하나)", out["reason"])
                self.assertIn("질문이 아니면 그대로 턴을 끝낸다.", out["reason"])
                self.assertIsNone(self.stop(message, stop_hook_active=True))  # 한 번만 막는다

    def test_reports_code_and_quotes_are_not_questions(self):
        for message in ("T-002 가 리뷰 승인 뒤 main 에 병합됐습니다. 제품 회귀는 없었습니다.",
                        "다음 명령을 썼습니다: `git status --porcelain=v1 ?`",
                        "```\nif x?\n  echo 주세요\n```\n끝났습니다.",
                        "~~~\n괜찮을까요\n~~~\n끝났습니다.",
                        "> 워커가 물었다: 계속할까요?\n답을 넘겼습니다.",
                        ""):
            with self.subTest(message=message[:20]):
                self.assertIsNone(self.stop(message))

    def test_setup_mode_other_roles_and_missing_message_are_not_checked(self):
        (self.state_dir / "setup-mode").write_text("x")
        self.assertIsNone(self.stop("이대로 진행할까요?"))
        (self.state_dir / "setup-mode").unlink()
        self.assertIsNone(self.hook("stop", {"session_id": "c", "last_assistant_message": "진행할까요?"}, drive=True))
        self.assertIsNone(self.hook("stop", {"session_id": "w", "last_assistant_message": "진행할까요?"},
                                    terminal=self.worker()))
        self.assertIsNone(self.hook("stop", {}, terminal=MAIN))
        self.assertIsNone(self.hook("stop", {"last_assistant_message": ["진행할까요?"]}, terminal=MAIN))

    def test_outside_herdr_and_without_run_is_checked_too(self):
        out = self.hook("stop", {"session_id": "out1", "last_assistant_message": "진행할까요?"})
        self.assertEqual(out["decision"], "block")
        self.assertNotIn("watch", out["reason"])

    def test_plain_question_is_a_pure_function(self):
        hook = load_hook()
        self.assertEqual(hook.plain_question("보고\n진행할까요?"), "진행할까요?")
        self.assertEqual(hook.plain_question("(정해 주세요)"), "(정해 주세요)")
        self.assertIsNone(hook.plain_question("끝났습니다."))
        self.assertIsNone(hook.plain_question(None))


class PlainQuestionWatchTest(HookCase):
    def test_watch_and_question_reasons_come_together(self):
        out = self.hook("stop", {"last_assistant_message": "진행할까요?"}, terminal=MAIN)
        self.assertEqual(out["decision"], "block")
        self.assertIn("watch 가 꺼져 있다", out["reason"])
        self.assertIn("\"진행할까요?\"", out["reason"])
        self.assertLess(out["reason"].index("\"진행할까요?\""), out["reason"].index("watch 가 꺼져 있다"))
        out = self.hook("stop", {"last_assistant_message": "끝났습니다."}, terminal=MAIN)
        self.assertEqual(out["decision"], "block")  # watch 검사는 지금 그대로
        self.assertNotIn("묻거나 부탁하는", out["reason"])
```

**Edit** `herdr-team/tests/test_setup.py`

```python
    def test_skill_recovery_contract(self):
```

```python
    def test_plain_question_rule_in_main(self):
        # 설계 7.7 8단계: 평문 질문은 뒤이은 관제 메시지에 묻혀 지나간다. Stop 훅이 이 줄을 검사한다(9.4)
        main = (ROOT / "templates/CLAUDE.section.md").read_text(encoding="utf-8")
        self.assertIn("사용자의 답·결정·행동(고르기, 확인, 로그인, 확인 창 승인 등)이 필요하면 언제나 AskUserQuestion 으로 "
                      "묻는다(질문 하나, 선택지 2–4개, 추천 하나. 자유 답은 Other 로 받는다). 진행 보고 글에 질문이나 부탁을 "
                      "섞지 않는다.", main)
        self.assertIn("마지막 글에 질문·부탁이 있으면 Stop 훅이 한 번 막는다.", main)
        self.assertLess(main.index("4. `.herdr-team/bin/hteam start T-xxx`"), main.index("언제나 AskUserQuestion 으로 묻는다"))

    def test_skill_recovery_contract(self):
```

- [ ] **Step 2: 시험이 실패하는지 본다**

Run: `bash herdr-team/tests/run.sh -k PlainQuestion` → FAIL(`test_plain_questions_are_blocked_once` 는 `None != 'block'`, 순수 함수 시험은 `AttributeError`).
Run: `bash herdr-team/tests/run.sh -k test_plain_question_rule_in_main` → FAIL.

- [ ] **Step 3: 구현**

`plain_question` 과 `stop` 을 Interfaces·Rules 대로 바꾸고, `CLAUDE.section.md` 에 줄을 더한다. `stop` 의 docstring 에 8단계 검사를 한 줄 더한다.

- [ ] **Step 4: 시험이 통과하는지 본다**

Run: `bash herdr-team/tests/run.sh tests.test_hooks tests.test_setup` → 모두 PASS(기존 `StopTest` 는 `last_assistant_message` 가 없어 그대로다. scaffold 가 템플릿을 복사하는 시험은 새 줄을 그대로 복사한다).

- [ ] **Step 5: 커밋**

```bash
python3 -m py_compile herdr-team/hooks/hteam_hook.py
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews'
git add -- herdr-team/hooks/hteam_hook.py herdr-team/templates/CLAUDE.section.md herdr-team/tests/test_hooks.py herdr-team/tests/test_setup.py
git commit -m "feat(herdr-team): 메인이 평문으로 묻고 턴을 끝내면 Stop 훅이 한 번 막고 AskUserQuestion 으로 묻게 한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/hooks/hteam_hook.py herdr-team/templates/CLAUDE.section.md herdr-team/tests/test_hooks.py herdr-team/tests/test_setup.py
```

---

### Task 3: `hteam fix --base-merge` 와 부작용 대처 (설계 5.10.4, 5.10.6, 6.4, 8.4, 7.7)

**Files:**
- Modify: `herdr-team/lib/hteam/tasks.py`(`fix`, `register` 의 fix 파서, `_cmd_fix`)
- Modify: `herdr-team/lib/hteam/queue.py`(`_x_fix`)
- Modify: `herdr-team/lib/hteam/compose.py`(`BASE_MERGE_LINE`·`workspace_section`, `merge_commit_line`, 리뷰 프롬프트 조립)
- Modify: `herdr-team/lib/hteam/drive.py`(`_changed_files`)
- Modify: `herdr-team/templates/CLAUDE.section.md`
- Test: `herdr-team/tests/test_workspace_merge.py`, `herdr-team/tests/test_drive_flows.py`, `herdr-team/tests/test_setup.py`

**Interfaces:**
- `tasks.fix(p, tid, *, note, supplement, force_round, cli, ..., base_merge: bool = False) -> dict`(키워드 하나를 더한다. 나머지 시그니처 그대로).
  - `base_merge` 면 `allowed(first)` 와 작업 공간 직무의 `_require_slot`·`require_worktree` 검사 뒤, 입력 검사(owns·잠금)·이전 워커 정리 전에 기준 병합 대상을 정한다: 상태에 `workspace` 가 없으면 `not_workspace`. `gitio.merge_head(workspace.task_root(p, first))` 가 있으면 `merge_in_progress`. `gitio.branch_tip(p.root, first["workspace"]["base_branch"])` 가 `None` 이면 `no_base_branch`. 그 sha 가 `gitio.is_ancestor(<작업 루트>, sha, gitio.head(<작업 루트>))` 면 `base_current`. 오류 code·exit·문구는 Global Constraints 그대로. 오류의 `data` 에 `{"base": sha}`(정해졌을 때)를 둔다.
  - 새 라운드를 쓰는 `_closing` 저장에서 `_new_round` 전에 `st["base_merge"] = st["base"] = sha`. 지금 코드가 그 뒤 `rd["base_merge"]` 와 `merge_resume` 을 정한다(`merge_resume` 은 `merge_in_progress` 거부 때문에 `--base-merge` 라운드에서는 생기지 않는다).
  - fix 사건: `_begin(..., "fix", ..., base_merge=sha)`(base_merge 일 때만 키가 있다).
- CLI: `hteam fix T [--note …] [--supplement …] [--base-merge] [--force-round] [--force] [--round N] [--model …] [--effort …] [--worker …]`. `--base-merge` 는 `action="store_true"`, help `작업 공간 태스크의 기준 병합 라운드(설계 5.10.6)`. 큐 요청 `args` 에 `"base_merge": true`(줄 때만). `_cmd_fix` 의 큐 앞 `check` 는 `--base-merge` 이고 상태에 `workspace` 가 없으면 `not_workspace` 로 바로 거부한다(큐에 넣지 않는다).
- `queue._x_fix`: `tasks.fix(..., base_merge=bool(a.get("base_merge")))`.
- `compose.BASE_MERGE_LINE`: 이어 풀기가 아닌 형태(Global Constraints 의 "먼저 `git status` …" 문장을 넣은 것). `compose.BASE_MERGE_RESUME_LINE`: 지금 `BASE_MERGE_LINE` 원문. `workspace_section` 은 `rd["merge_resume"]` 이면 `BASE_MERGE_RESUME_LINE + " " + MERGE_RESUME`, 아니면 `BASE_MERGE_LINE`.
- `compose.merge_commit_line(p, st, commits) -> str`: `st` 에 `workspace` 가 없으면 `""`. `commits`(`{"sha", "subject"}` 목록) 가운데 `gitio.parents(p.work_root, sha)` 가 둘 이상인 것의 sha 7자를 순서대로 `", "` 로 이어 Global Constraints 의 리뷰 안내 줄을 만든다. 없으면 `""`.
- 리뷰 프롬프트: 지금 `workspace=review_workspace(cfg, st)` 자리에 줄이 있으면 `review_workspace(cfg, st) + "\n- " + merge_commit_line(...)` 를 넣는다(`## 태스크` 의 작업 공간 줄 뒤. 템플릿은 그대로).
- `drive.Drive._changed_files`: 비교 기준을 `first["rounds"][0].get("round_base") or first["base"]` 로(라운드가 없으면 `base`).
- `CLAUDE.section.md`: "진행 중 태스크에 범위를 더할 때" 줄 바로 뒤에 한 줄을 더한다.

```
- 작업 공간 태스크가 기준 브랜치의 새 커밋(나중에 병합된 회귀 수정 등)을 받아야 하면 `.herdr-team/bin/hteam fix T-xxx --base-merge --note "<이유>"` 를 한다. 일하는 중이면 그 워커를 닫고 새 라운드가 병합부터 한다. 워커에게 병합·rebase 를 직접 지시하지 않는다(사전 검사가 기준에서 들어온 파일을 소유 경로 밖 변경으로 반려한다).
```

**Rules:**
- 거부는 모두 이전 워커를 정리하기 전이고 상태·슬롯·사양을 바꾸지 않는다.
- 이미 `base_merge` 가 있고 슬롯에 `MERGE_HEAD` 가 없으면 새 sha 로 바꾼다(충돌 경로가 남긴 표시).
- `--base-merge` 없는 `fix` 의 동작(충돌 경로의 기준 병합 라운드 포함)은 병합 지시문의 새 문장 말고는 그대로다.
- 리뷰 안내 줄은 작업 공간 태스크에만, 대상 커밋에 병합 커밋이 있을 때만 붙는다.

- [ ] **Step 1: 시험 쓰기**

**Edit** `herdr-team/tests/test_workspace_merge.py`

```python
BASE_MERGE = ("- 이 라운드는 기준 커밋 `{sha}` 를 이 브랜치에 병합한다: `git merge --no-ff --no-commit {sha}` 뒤 충돌을 풀고 "
              "푼 파일을 `git add -- <파일>` 한다. `git diff --cached --name-only` 가 병합과 푼 파일만 담는지 본 뒤 경로를 "
              "지정하지 않은 `git commit -m \"[{tid}] 기준 병합: {sha7}\"` 로 커밋한다(병합 중에는 git 이 경로 지정 커밋을 "
              "받지 않는다. 이 커밋만 작업 규칙 5.5 의 경로 지정 예외다). 그 밖의 병합·rebase·push 는 하지 않는다.")
```

```python
# 이어 풀기 라운드(merge_resume)의 둘째 줄은 7단계 원문 그대로다. 남은 변경이 그 병합이라 먼저 커밋하라고 하지 않는다
BASE_MERGE_RESUME = ("- 이 라운드는 기준 커밋 `{sha}` 를 이 브랜치에 병합한다: `git merge --no-ff --no-commit {sha}` 뒤 충돌을 "
                     "풀고 푼 파일을 `git add -- <파일>` 한다. `git diff --cached --name-only` 가 병합과 푼 파일만 담는지 본 뒤 "
                     "경로를 지정하지 않은 `git commit -m \"[{tid}] 기준 병합: {sha7}\"` 로 커밋한다(병합 중에는 git 이 경로 "
                     "지정 커밋을 받지 않는다. 이 커밋만 작업 규칙 5.5 의 경로 지정 예외다). 그 밖의 병합·rebase·push 는 하지 "
                     "않는다.")
# 8단계(설계 5.10.6): 그 밖의 기준 병합 라운드는 병합 전에 커밋 안 된 변경을 먼저 커밋한다(working 에서 연 --base-merge)
BASE_MERGE = BASE_MERGE_RESUME.replace(
    "병합한다: `git merge", "병합한다: 먼저 `git status` 를 보고 이 태스크의 커밋하지 않은 변경이 있으면 경로 지정 커밋으로 "
    "커밋한다(index 에 올린 변경이 있으면 git 이 병합을 거부한다). 그다음 `git merge")
```

**Edit** `herdr-team/tests/test_workspace_merge.py`

```python
        self.assertIn(BASE_MERGE.format(sha=base, sha7=base[:7], tid="T-001") + " " + RESUME, self.spec_text(3))
```

```python
        self.assertIn(BASE_MERGE_RESUME.format(sha=base, sha7=base[:7], tid="T-001") + " " + RESUME, self.spec_text(3))
        self.assertNotIn("먼저 `git status`", self.spec_text(3))
```

**Edit** `herdr-team/tests/test_workspace_merge.py`

```python
class RefuseTest(MergeCase):
```

```python
class BaseMergeCommandTest(MergeCase):
    """8단계(설계 5.10.6): 메인이 여는 기준 병합 `hteam fix T --base-merge`. 충돌 경로의 기준 병합 라운드를 다시 쓴다."""

    def other_task_merged(self, rel: str = "docs/other.md", text: str = "o2\n") -> str:
        """다른 태스크가 기준 브랜치에 병합된 것과 같다: 메인 폴더 main 에 owns 밖 파일 커밋. 그 sha."""
        return self.commit(rel, text, "[T-009] merge: 다른 태스크")

    def merge_in_slot(self, base: str) -> str:
        """새 라운드 워커가 지시대로 한 기준 병합(충돌 없음): --no-commit 병합 → 경로 지정 없는 커밋. 병합 커밋 sha."""
        slot = self.slot_root(1)
        self.git_at(slot, "merge", "--no-ff", "--no-commit", base)
        self.git_at(slot, "commit", "-q", "-m", f"[T-001] 기준 병합: {base[:7]}")
        return self.git_at(slot, "rev-parse", "HEAD").strip()

    def prompt(self, n: int) -> str:
        return (self.state_dir / "tasks" / "T-001" / f"r{n}-review-a1.md").read_text(encoding="utf-8")

    def test_working_task_gets_a_base_merge_round(self):
        self.ws_start("T-001")
        base = self.other_task_merged()
        code, out = self.hteam("fix", "T-001", "--base-merge", "--note=T-009 의 수정을 받아 다시 시험한다")
        self.assertEqual((code, out.get("round")), (0, 2), out)
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["base_merge"], st["base"]), ("working", base, base))
        self.assertEqual(st["rounds"][-1]["base_merge"], base)
        self.assertNotIn("merge_resume", st["rounds"][-1])
        fix = [h for h in st["history"] if h.get("event") == "fix"][-1]
        self.assertEqual(fix["base_merge"], base)
        r2 = self.spec_text(2)
        self.assertIn(BASE_MERGE.format(sha=base, sha7=base[:7], tid="T-001"), r2)
        self.assertIn("T-009 의 수정을 받아 다시 시험한다", r2)
        self.assertNotIn(NORMAL_SECOND, r2)
        self.assertEqual((self.record(1)["state"], self.record(1)["task"]), ("busy", "T-001"))  # 같은 슬롯·같은 브랜치
        merge = self.merge_in_slot(base)
        code, out = self.act_work("T-001", {"src/a/x.py": "x = 1\n"})
        self.assertEqual(code, 0, out)
        code, out = self.hteam("review", "T-001")
        # 기준에서 들어온 docs/other.md 는 owns 밖 변경으로 잡히지 않는다(kakao T-008 은 여기서 반려됐다)
        self.assertEqual((code, out.get("status")), (0, "reviewing"), out)
        self.assertNotIn("base_merge", self.task_state("T-001"))
        prompt = self.prompt(2)
        self.assertIn(f"병합 커밋 {merge[:7]}은 기준 브랜치의 변경을 이 브랜치에 들여온 것이다. 그 커밋이 들여온 다른 태스크의 "
                      "변경은 이 태스크의 변경으로 리뷰하지 않는다(그 태스크의 리뷰를 이미 거쳤다).", prompt)
        self.assertIn("리뷰 범위의 다른 규칙(라운드 확인 범위, 묶음 리뷰)은 그대로다.", prompt)
        code, out = self.act_review("T-001", "APPROVE")
        self.assertEqual(code, 0, out)
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual((code, out["status"]), (0, "approved"), out)
        res = self.d.accept_task("T-001")
        self.assertEqual(res["status"], "done", res)
        self.assertEqual(self.subjects(1), ["[T-001] merge: 앱 만들기"])
        self.assertEqual((self.proj / "src/a/x.py").read_text(encoding="utf-8"), "x = 1\n")
        self.assertEqual((self.proj / "docs/other.md").read_text(encoding="utf-8"), "o2\n")

    def test_merge_by_the_worker_without_base_merge_is_still_rejected(self):
        # kakao T-008: 메인이 범위 추가로 병합을 지시했다. base 가 그대로라 기준에서 들어온 파일이 owns 밖 변경이다. 이 동작은
        # 그대로 두고 메인 규칙(7.7)과 --base-merge 로 피한다(설계 8단계 보고 처리)
        self.ws_start("T-001")
        base = self.other_task_merged()
        self.merge_in_slot(base)
        code, out = self.act_work("T-001", {"src/a/x.py": "x = 1\n"})
        self.assertEqual(code, 0, out)
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out.get("status")), (0, "changes"), out)
        review = (self.slot_root(1) / "docs/reviews/T-001/r1.md").read_text(encoding="utf-8")
        self.assertIn("owns 밖 경로의 내용이 base 와 다르다: docs/other.md", review)

    def test_up_to_date_task_is_refused_and_nothing_changes(self):
        self.ws_start("T-001")
        before = self.task_state("T-001")
        code, out = self.hteam("fix", "T-001", "--base-merge")
        self.assertEqual((code, out["error"]["code"]), (3, "base_current"), out)
        self.assertEqual(self.task_state("T-001"), before)  # 워커를 닫지 않았다

    def test_unfinished_merge_in_the_slot_is_refused(self):
        self.ws_start("T-001")
        slot = self.slot_root(1)
        (slot / "src/a/core.py").write_text("task\n", encoding="utf-8")
        self.git_at(slot, "commit", "-q", "-m", "[T-001] core", "--", "src/a/core.py")
        first = self.commit("src/a/core.py", "main\n", "사람: core")
        proc = subprocess.run(["git", "-C", str(slot), "merge", "--no-ff", "--no-commit", first], capture_output=True,
                              text=True, env=self.env)
        self.assertNotEqual(proc.returncode, 0, proc.stdout)  # 충돌로 멈춘 병합이 남았다
        self.assertTrue(self.merging(slot))
        self.other_task_merged()
        before = self.task_state("T-001")
        code, out = self.hteam("fix", "T-001", "--base-merge")
        self.assertEqual((code, out["error"]["code"]), (3, "merge_in_progress"), out)
        self.assertEqual(self.task_state("T-001"), before)
        self.git_at(slot, "merge", "--abort")

    def test_conflict_base_merge_is_replaced_by_the_newer_base(self):
        self.approved(files={"src/a/core.py": "task\n"})
        self.commit("src/a/core.py", "main\n", "사람: core")
        first = self.commit("docs/other.md", "o2\n", "사람: other")
        self.assertEqual(self.d.accept_task("T-001")["status"], "changes")
        self.assertEqual(self.task_state("T-001")["base_merge"], first)
        newer = self.other_task_merged("docs/more.md", "m\n")
        code, out = self.hteam("fix", "T-001", "--base-merge", "--note=최신 기준까지 받는다")
        self.assertEqual((code, out.get("round")), (0, 2), out)
        st = self.task_state("T-001")
        self.assertEqual((st["base_merge"], st["base"], st["rounds"][-1]["base_merge"]), (newer, newer, newer))
        self.assertIn(BASE_MERGE.format(sha=newer, sha7=newer[:7], tid="T-001"), self.spec_text(2))

    def test_main_folder_task_is_not_a_workspace_task(self):
        self.write_spec("T-002", "planner", owns="docs/planning/**")
        state.create(self.p, "T-002", "planner")
        code, out = self.hteam("start", "T-002")
        self.assertEqual(code, 0, out)
        before = self.task_state("T-002")
        code, out = self.hteam("fix", "T-002", "--base-merge")
        self.assertEqual((code, out["error"]["code"]), (2, "not_workspace"), out)
        self.assertEqual(self.task_state("T-002"), before)

    def test_main_puts_base_merge_on_the_queue(self):
        self.ws_start("T-001")
        base = self.other_task_merged()
        code, out = self.hteam("fix", "T-001", "--base-merge", "--note=다시 시험", as_="main",
                               env={"HTEAM_QUEUE_WAIT_S": "0.3"})
        self.assertEqual((code, out.get("status")), (0, "queued"), out)
        reqs = [json.loads(f.read_text(encoding="utf-8")) for f in sorted((self.drive_dir / "queue").iterdir())
                if queue.REQUEST_RE.match(f.name)]
        self.assertEqual([(r["command"], r["args"]) for r in reqs],
                         [("fix", {"task": "T-001", "note": "다시 시험", "base_merge": True})])
        self.d.run_queue()
        st = self.task_state("T-001")
        self.assertEqual((st["round"], st["base_merge"], st["base"]), (2, base, base))

    def test_review_without_merge_commit_has_no_merge_line(self):
        self.approved()
        self.assertNotIn("들여온 것이다", self.prompt(1))

    def test_merge_line_is_only_for_workspace_tasks(self):
        from hteam import compose
        self.ws_start("T-001")
        merge = self.merge_in_slot(self.other_task_merged())
        st = self.task_state("T-001")
        view = workspace.view(self.p, st)
        commits = [{"sha": merge, "subject": "[T-001] 기준 병합"}]
        self.assertIn(f"병합 커밋 {merge[:7]}은", compose.merge_commit_line(view, st, commits))
        shared = {k: v for k, v in st.items() if k != "workspace"}
        self.assertEqual(compose.merge_commit_line(self.p, shared, commits), "")
        self.assertEqual(compose.merge_commit_line(view, st, []), "")


class SharedBaseMergeTest(MergeCase):
    config_text = BASE_CONFIG

    def test_shared_task_is_not_a_workspace_task(self):
        code, out = self.hteam("start", "T-001")
        self.assertEqual(code, 0, out)
        self.commit("docs/other.md", "o2\n", "[T-009] 다른 태스크")
        before = self.task_state("T-001")
        code, out = self.hteam("fix", "T-001", "--base-merge")
        self.assertEqual((code, out["error"]["code"]), (2, "not_workspace"), out)
        self.assertEqual(self.task_state("T-001"), before)
        code, out = self.hteam("fix", "T-001", "--base-merge", as_="main", env={"HTEAM_QUEUE_WAIT_S": "0.3"})
        self.assertEqual((code, out["error"]["code"]), (2, "not_workspace"), out)  # 큐에 넣기 전에 거부한다
        self.assertFalse(any(queue.REQUEST_RE.match(f.name) for f in (self.drive_dir / "queue").glob("*")))


class RefuseTest(MergeCase):
```

**Edit** `herdr-team/tests/test_drive_flows.py`

```python
    def test_changed_files_skip_team_folder_and_stop_at_15(self):
```

```python
    def test_changed_files_start_at_the_first_round_even_if_base_moved(self):
        # 8단계(설계 8.4 의 7): 기준 병합(5.10.6)이 base 를 옮겨도 첫 라운드 이후의 앞 변경이 빠지지 않는다
        first = self.head()
        self.task("T-001", base=first)
        self.commit("src/early.py", "x\n", "[T-001] 앞 변경")
        moved = self.commit("src/late.py", "y\n", "[T-001] 뒤 변경")
        with state.edit(self.p, "T-001") as st:
            st["base"] = moved
        self.d.finish_step()
        lines = self.done_items()[0]["body"].splitlines()
        self.assertEqual(lines[-1], "바뀐 주요 파일: src/early.py, src/late.py")

    def test_changed_files_skip_team_folder_and_stop_at_15(self):
```

**Edit** `herdr-team/tests/test_setup.py`

```python
    def test_skill_recovery_contract(self):
```

```python
    def test_base_merge_rule_in_main(self):
        # 설계 7.7 8단계: 작업 공간 태스크의 기준 병합은 메인이 --base-merge 로 연다(kakao T-008)
        main = (ROOT / "templates/CLAUDE.section.md").read_text(encoding="utf-8")
        self.assertIn("`.herdr-team/bin/hteam fix T-xxx --base-merge --note \"<이유>\"` 를 한다. 일하는 중이면 그 워커를 닫고 "
                      "새 라운드가 병합부터 한다. 워커에게 병합·rebase 를 직접 지시하지 않는다", main)

    def test_skill_recovery_contract(self):
```

- [ ] **Step 2: 시험이 실패하는지 본다**

Run: `bash herdr-team/tests/run.sh -k BaseMerge` → FAIL(`hteam fix` 가 `--base-merge` 를 모르는 인자로 exit 2, `BASE_MERGE` 문장 없음, `merge_commit_line` 없음).
Run: `bash herdr-team/tests/run.sh -k test_changed_files_start_at_the_first_round_even_if_base_moved` → FAIL(바뀐 파일 줄이 없다).
Run: `bash herdr-team/tests/run.sh -k test_base_merge_rule_in_main` → FAIL.

- [ ] **Step 3: 구현**

Interfaces·Rules 대로 `tasks.py`·`queue.py`·`compose.py`·`drive.py`·`CLAUDE.section.md` 를 고친다.

- [ ] **Step 4: 시험이 통과하는지 본다**

Run: `bash herdr-team/tests/run.sh tests.test_workspace_merge tests.test_drive_flows tests.test_setup tests.test_queue tests.test_review tests.test_workspace_flow` → 모두 PASS.

- [ ] **Step 5: 커밋**

```bash
python3 -m py_compile herdr-team/lib/hteam/tasks.py herdr-team/lib/hteam/queue.py herdr-team/lib/hteam/compose.py herdr-team/lib/hteam/drive.py
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews'
git add -- herdr-team/lib/hteam/tasks.py herdr-team/lib/hteam/queue.py herdr-team/lib/hteam/compose.py herdr-team/lib/hteam/drive.py herdr-team/templates/CLAUDE.section.md herdr-team/tests/test_workspace_merge.py herdr-team/tests/test_drive_flows.py herdr-team/tests/test_setup.py
git commit -m "feat(herdr-team): fix --base-merge 로 메인이 작업 공간 태스크의 기준 병합 라운드를 연다, 병합 전 커밋 먼저 지시, 병합 커밋 리뷰 안내, 완료 요약은 첫 라운드부터

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/lib/hteam/tasks.py herdr-team/lib/hteam/queue.py herdr-team/lib/hteam/compose.py herdr-team/lib/hteam/drive.py herdr-team/templates/CLAUDE.section.md herdr-team/tests/test_workspace_merge.py herdr-team/tests/test_drive_flows.py herdr-team/tests/test_setup.py
```

---

### Task 4: init·upgrade 의 새 세션 안내, 업그레이드 규칙 줄, README, 0.6.0 (설계 9.1, 9.6, 7.7)

**Files:**
- Modify: `herdr-team/skills/init/SKILL.md`, `herdr-team/lib/hteam/setup.py`(`UPGRADE_NEXT`), `herdr-team/templates/CLAUDE.section.md`, `README.md`
- Modify: `herdr-team/lib/hteam/paths.py`, `herdr-team/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`
- Test: `herdr-team/tests/test_setup.py`, `herdr-team/tests/test_cli.py`

**Interfaces:**
- init `## 6. 마무리` 의 3: `보고한다: 준비 완료, 관제 터미널, 고정 에이전트 구성, 적용 결과 표, 경고, "메인 규칙(\`CLAUDE.md\` 의 herdr-team 절)은 세션을 시작할 때 읽힌다. 이 세션을 끝내고 같은 폴더에서 메인 세션을 새로 연 뒤 첫 업무를 준다(관제는 그대로 돈다. 새 세션의 watch 는 Stop 훅이 띄우게 한다)".` `## 하지 않는 것` 의 줄: `- 기획·코드 작업 시작. 첫 업무는 새로 연 메인 세션에서 받는다(이 세션은 init 이 쓴 메인 규칙을 지시로 받지 못했다).`
- `setup.UPGRADE_NEXT` 끝에 ` CLAUDE.md 절을 고쳤으면 메인 세션을 새로 연다(메인 규칙은 세션을 시작할 때 읽힌다).` 를 더한다(앞 문장과 공백 하나).
- `CLAUDE.section.md` 의 업그레이드 줄(`- 플러그인을 올린 뒤 사용자가 업그레이드를 부탁하면 …`) 끝에 ` \`CLAUDE.md\` 절이 바뀌었으면 사용자에게 메인 세션을 새로 열라고 알린다(메인 규칙은 세션을 시작할 때 읽힌다).` 를 더한다.
- README:
  - init 을 설명하는 곳 끝에 "init 이 끝나면 메인 세션을 새로 연다(메인 규칙은 세션을 시작할 때 읽힌다)." 를 더한다. "업데이트" 절의 "업데이트한 뒤 Claude Code 세션을 다시 연다." 는 그대로 둔다.
  - 메인 사용 설명에 두 줄: 메인은 사용자에게 언제나 선택 창(AskUserQuestion)으로 묻는다(평문 질문은 Stop 훅이 한 번 막는다), 작업 공간 태스크가 기준의 새 커밋을 받아야 하면 `hteam fix T-xxx --base-merge`(메인에 부탁한다).
  - "이미 세팅한 프로젝트 업그레이드" 의 "#### 0.4.0 → 0.5.0" 앞에 "#### 0.5.0 → 0.6.0": (1) 플러그인만 올리면 적용되는 것(질문 확인 훅 대기, 평문 질문 검사, `fix --base-merge`, 병합 지시문·리뷰 안내 줄, 완료 요약). (2) `.herdr-team/bin/hteam upgrade` 의 `manual` 대로 `CLAUDE.md` 의 `<!-- herdr-team -->` 절을 `herdr-team/templates/CLAUDE.section.md` 와 견줘 고친다(메인 규칙 새 줄 셋: 평문 질문, 기준 병합, 업그레이드 뒤 새 세션). (3) 메인 세션을 새로 연다.
- 버전 `0.6.0` 세 곳(Global Constraints).

- [ ] **Step 1: 시험 쓰기**

**Edit** `herdr-team/tests/test_setup.py`

```python
        self.assertEqual(out["next"], "바뀐 파일을 확인하고(git diff -- .herdr-team) 커밋한다. manual 의 절은 템플릿과 견줘 직접 "
                         "고친다. 직무 문서는 워커 사양에 라운드마다 들어가므로 커밋하면 다음 라운드부터 적용된다. 테스트 관문을 "
                         "쓰려면 docs/planning/tasks.toml 에 [test] 를 넣고 커밋한다(README \"묶음 검증\").")
```

```python
        self.assertEqual(out["next"], "바뀐 파일을 확인하고(git diff -- .herdr-team) 커밋한다. manual 의 절은 템플릿과 견줘 직접 "
                         "고친다. 직무 문서는 워커 사양에 라운드마다 들어가므로 커밋하면 다음 라운드부터 적용된다. 테스트 관문을 "
                         "쓰려면 docs/planning/tasks.toml 에 [test] 를 넣고 커밋한다(README \"묶음 검증\"). CLAUDE.md 절을 "
                         "고쳤으면 메인 세션을 새로 연다(메인 규칙은 세션을 시작할 때 읽힌다).")
```

**Edit** `herdr-team/tests/test_setup.py`

```python
    def test_skill_recovery_contract(self):
```

```python
    def test_new_main_session_after_init_and_upgrade(self):
        # 설계 9.1·9.6·7.7 8단계: 메인 규칙은 세션을 시작할 때 읽힌다. kakao 메인은 init 뒤 같은 세션에서 일해 규칙을 받지 못했다
        init = (ROOT / "skills/init/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("메인 규칙(`CLAUDE.md` 의 herdr-team 절)은 세션을 시작할 때 읽힌다. 이 세션을 끝내고 같은 폴더에서 메인 "
                      "세션을 새로 연 뒤 첫 업무를 준다", init)
        self.assertIn("첫 업무는 새로 연 메인 세션에서 받는다", init)
        self.assertNotIn("다음 메시지로 첫 업무를 주면 된다", init)
        self.assertNotIn("첫 업무는 사용자의 다음 메시지부터다", init)
        main = (ROOT / "templates/CLAUDE.section.md").read_text(encoding="utf-8")
        self.assertIn("`CLAUDE.md` 절이 바뀌었으면 사용자에게 메인 세션을 새로 열라고 알린다(메인 규칙은 세션을 시작할 때 "
                      "읽힌다).", main)
        readme = (ROOT.parent / "README.md").read_text(encoding="utf-8")
        self.assertIn("#### 0.5.0 → 0.6.0", readme)
        self.assertLess(readme.index("#### 0.5.0 → 0.6.0"), readme.index("#### 0.4.0 → 0.5.0"))
        self.assertIn("init 이 끝나면 메인 세션을 새로 연다", readme)
        self.assertIn("--base-merge", readme)

    def test_skill_recovery_contract(self):
```

**Edit** `herdr-team/tests/test_cli.py`

```python
        self.assertEqual((code, out["ok"], out["version"]), (0, True, "0.5.0"))
```

```python
        self.assertEqual((code, out["ok"], out["version"]), (0, True, "0.6.0"))
```

**Edit** `herdr-team/tests/test_cli.py`

```python
        self.assertEqual({VERSION, plugin["version"], entry["version"]}, {"0.5.0"})
```

```python
        self.assertEqual({VERSION, plugin["version"], entry["version"]}, {"0.6.0"})
```

- [ ] **Step 2: 시험이 실패하는지 본다**

Run: `bash herdr-team/tests/run.sh -k test_new_main_session_after_init_and_upgrade` → FAIL.
Run: `bash herdr-team/tests/run.sh tests.test_cli` → FAIL(0.5.0).

- [ ] **Step 3: 구현**

Interfaces 대로 스킬·`UPGRADE_NEXT`·템플릿·README·버전을 고친다. README 의 다른 절은 바꾸지 않는다.

- [ ] **Step 4: 시험이 통과하는지 본다**

Run: `bash herdr-team/tests/run.sh tests.test_setup tests.test_cli` → 모두 PASS.
Run(백그라운드, 다른 무거운 일 없이): `bash herdr-team/tests/run.sh` → 모두 PASS.

- [ ] **Step 5: 커밋**

```bash
python3 -m py_compile herdr-team/lib/hteam/setup.py herdr-team/lib/hteam/paths.py
git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews'
git add -- herdr-team/skills/init/SKILL.md herdr-team/lib/hteam/setup.py herdr-team/templates/CLAUDE.section.md README.md herdr-team/lib/hteam/paths.py herdr-team/.claude-plugin/plugin.json .claude-plugin/marketplace.json herdr-team/tests/test_setup.py herdr-team/tests/test_cli.py
git commit -m "docs(herdr-team): init·upgrade 뒤 메인 세션을 새로 열라는 안내, README 0.5.0 → 0.6.0, 버전 0.6.0

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/skills/init/SKILL.md herdr-team/lib/hteam/setup.py herdr-team/templates/CLAUDE.section.md README.md herdr-team/lib/hteam/paths.py herdr-team/.claude-plugin/plugin.json .claude-plugin/marketplace.json herdr-team/tests/test_setup.py herdr-team/tests/test_cli.py
```

---

### Task 5: 실환경 확인과 기록 (설계 15.2 의 8단계, 컨트롤러가 한다)

이 태스크는 컨트롤러가 직접 한다(실제 Herdr 터미널·Claude 세션·Codex 리뷰어를 쓴다). 운영 규칙은 7단계와 같다: 사용자 hc core 를 멈추거나 다시 띄우지 않는다(`hc server stop|restart`, `hc update` 금지), 새 `HC_SESSION`·XDG 상태 경로를 만들지 않는다, 시험이 띄운 터미널·탭만 끝내고 지운다, `hc run` 은 늘 `--no-notify`, 사용자 터미널에 보내지 않는다, 플러그인을 설치·업데이트하지 않는다(`--plugin-dir` 와 `DISABLE_AUTOUPDATER=1`), 사용자 전역 설정을 바꾸지 않는다, 원격 기기에 쓰지 않는다.

- [ ] **Step 1: 메인 질문(15.2 8단계 1)**: 시험 프로젝트(빈 git 저장소에 `hteam scaffold`, 플러그인은 이 저장소 폴더)를 시험 터미널에서 대화형 메인 Claude 세션으로 연다. `render.context` 가 있는 질문 하나를 outbox 에 만든다. 가장 가벼운 방법은 관제가 쓰는 것과 같이 `outbox.append` 로 `question` 항목을 넣는 것이다(시험의 `drive_question` 과 같다). 메인이 같은 응답에서 글을 쓰고 AskUserQuestion 을 불러 첫 시도에 통과하는지 본다(`context-denied.json` 에 그 id 가 없다, transcript 에 거부 글이 없다). 그다음 메인에 "시험이다. 보고 글 끝에 평문으로 '이대로 진행할까요?' 를 묻고 턴을 끝내라" 를 보내 Stop 훅이 한 번 막고 메인이 AskUserQuestion 으로 다시 묻는지, 질문 없는 보고("끝났다고만 답하라")는 막지 않는지 본다.
- [ ] **Step 2: 기준 병합(15.2 8단계 2)**: worktree 모드 시험 프로젝트(7단계 실환경 1 의 축소판, 실제 임시 워커 sonnet, 리뷰어 Codex)에서 developer 태스크 하나가 슬롯에서 일하는 동안 메인 폴더 기준 브랜치에 owns 밖 커밋을 넣는다. 메인 역할 터미널에서 `hteam fix T-001 --base-merge --note=<이유>` 를 큐로 넣는다. 확인할 것: 워커가 닫히고 새 라운드 워커가 지시대로 병합 커밋을 만든다, 리뷰 사전 검사가 통과하고 프롬프트에 안내 줄이 있다, accept 가 기준 브랜치에 병합한다, 완료 요약의 바뀐 파일에 앞 변경이 든다. 새 라운드 워커가 병합 커밋을 만든 뒤 accept 전에 같은 명령은 `base_current` 다.
- [ ] **Step 3: 회귀(15.2 8단계 3)**: 전체 시험(`bash herdr-team/tests/run.sh`, `bash herdr-orch/tests/run.sh`, 하나씩 백그라운드)과 7단계 실환경 1 의 기본 흐름(병렬 두 태스크와 병합) 하나.
- [ ] **Step 4: 기록**: 설계 15.4 에 "8단계 실환경 확인(2026-11-…)" 절을 더한다(본 것, 결과, 발견한 문제와 처리). 머리말 상태 줄을 "8단계(15.3 의 8)는 구현·실환경 확인을 마쳤다(herdr-team 0.6.0, 병합 대기)" 로 바꾼다. 경로 지정 커밋 `docs: herdr-team 8단계 실환경 확인 결과`.
- [ ] **Step 5: 브랜치 리뷰**: 최종 코드 리뷰(서브에이전트, 가장 능력 있는 모델, `review-package $(git merge-base main HEAD) HEAD`)와 `scripts/codex-review.sh base main`(최대 3라운드, P0·P1 이 남지 않을 때까지). 지적은 사용자 결정 기준(기본 경로만)으로 고치거나 한계로 적는다. 그 뒤 main 병합은 사용자에게 묻는다.
