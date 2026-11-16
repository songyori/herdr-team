# herdr-team 11단계 보강(메인이 바뀐 뒤 다시 묶기) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 설계 15.3 의 11 의 6(1장 "사용자 결정 (2026-11-16, 11단계 보강)")을 만든다. 메인이 다른 터미널로 바뀌면(`run.json` 의 `main_terminal` 이 바뀜) 앞 메인 아래 남은 관제와 고정 에이전트 작업 터미널을 새 메인 아래로 다시 띄운다. 관제는 한가할 때 스스로 끝나 지금의 다시 띄우기 길(watch `orphaned` → `/herdr-team:up`, 자동 부활)로 새 메인 아래 다시 뜬다(8.13). 고정 에이전트는 리셋의 clear 단계에서 같은 터미널을 비우는 대신 닫아, 다음 태스크가 새 메인 아래 새 세션으로 띄운다(5.9.7 의 4). 버전은 그대로 0.7.1 이고 herdr-orch 는 바꾸지 않는다.

**Architecture:** (1) `outbox.moved_main(p, parent, space)` 하나가 확인 규칙(설계 8.13 확인의 2–4)을 갖는다: `main_parent` 가 주소 M, M ≠ parent, `hc get M`(3초)이 live·`address` ≠ parent·라벨 `herdr.space` == space 면 M. 관제와 리셋이 함께 쓴다. (2) 관제: Run 연결(8.2 의 4)의 `hc get` 에서 자기 parent 를 기억하고, 틱 10 `rehome_step` 이 60초마다 확인해 같은 M 이 두 번 연달아 후보면 정한다. 정한 뒤 틱 끝마다 `main_parent` 가 아직 M 이고 한가하고 메인 watch 가 돌면 `rehome.json` → progress → 로그 뒤 True 를 내고 `main` 이 exit 0 으로 끝난다. 새 관제는 Run 연결 뒤 시작 재확인 전에 `rehome.json` 의 앞 관제 터미널을 정리한다. (3) 고정 에이전트: `crew._clear` 의 첫 시도에서 `_parent_changed` 면 `clear_error = "parent_changed"` 로 지금의 닫기 갈래에 간다. 그 닫기가 실패하면 `rehome = "failed"` 를 두고, 그 뒤의 리셋 단계(같은 틱의 틱 7 이나 다음 틱)가 parent 를 보지 않고 `terminal-reset` 한다. (4) `up`·watch·훅·메인 규칙·`hteam status` 는 바꾸지 않는다.

**Tech Stack:** Python 3.11+ 표준 라이브러리(json, os, time, unittest). 가짜 hc(`herdr-orch/tests/fakes/hc`: `get` 이 `parent`·`state`·`address`·`labels` 를 돌려준다)와 가짜 herdr-app(`herdr-team/tests/fakes/herdr-app`). 둘 다 바꾸지 않는다.

**설계 문서:** `docs/superpowers/specs/2026-11-05-herdr-team-design.md`(이하 "설계"). 보강 범위는 설계 15.3 의 11 의 6 이다. 함께 볼 절: 1장(11단계 확인한 것의 "실환경 1차" 줄들, "사용자 결정 (2026-11-16, 11단계 보강)" 표), 3.2(표 위 문단과 11단계 보강 줄), 3.3(herdr.py 의 다시 묶기 호출), 3.4(`rehome.json`), 5.9.1(`resetting` 의 `clear_error`·`rehome`), 5.9.2 의 2, 5.9.7 의 4(11단계 보강 묶음), 5.9.8 표(관제가 죽었다), 7.3(11단계 보강 줄), 7.7(11단계 문단 끝), 8.2 의 4·6·7, 8.5(틱 10, 상수 `REHOME_CHECK_S`·`REHOME_MIN_UP_S`), 8.11(11단계 보강 로그), 8.13(전부), 9.3 의 6·7, 9.5(11단계 보강 문단, 한계), 9.6(11단계 README 의 (4)·(5)), 13장(11단계 보강 한계), 15.1(11단계 보강 시험), 15.2(11단계 2차 7–10), 16장(11단계 보강).

**코드가 기준이다.** 수정은 모두 지금 HEAD(브랜치 `herdr-team-p11`. 11단계 본 구현 Task 1–5 커밋 745f5e6·419b6ae·5507c24·697fad4·55232b5, 수정 5b7ea1b, 보강 설계 3e1723c·40a8be8)의 코드에 대한 부분 수정이다. 새 모듈은 없다. 1차 계획 `docs/superpowers/plans/2026-11-16-herdr-team-p11.md` 는 고치지 않는다.

**계획 방식(1차 계획과 같다):** 시험은 전부 코드 블록으로 쓴다. 구현도 모두 찾을 내용·바꿀 내용 블록으로 적는다(규칙은 `**Rules:**`). README 는 들어갈 글을 그대로 적는다.

**편집 표기:** `**Edit** \`경로\`` 다음 두 코드 블록은 "찾을 내용"과 "바꿀 내용"이다. 찾을 내용은 적용하는 그 시점의 파일에서 정확히 한 번 나온다(태스크 순서대로 적용한다).

**설계와 다르게 정한 것(이 계획의 결정):**
- 시험용 환경 변수 `HTEAM_REHOME_CHECK_S`·`HTEAM_REHOME_MIN_UP_S` 를 둔다(없으면 설계 상수 60·600초). `HTEAM_BIND_RETRY_S`·`HTEAM_DRIVE_WAIT_MS` 처럼 관제 프로세스 시험(exit 0, drive.pid 지우기)이 600초를 기다리지 않게 한다. 시험 helpers 의 `DROP_ENV` 에 넣어 사용자 환경이 새지 않게 한다.
- 확인 2–4 를 `outbox.moved_main` 하나에 두고 관제(8.13)와 리셋(5.9.7 의 4)이 함께 쓴다. 설계가 리셋 쪽을 "8.13 의 확인 4 와 같은 규칙" 이라 적은 것을 코드 하나로 한다. 리셋은 space 로 entry 의 `space`, 관제는 run.json 의 `team_space` 를 준다.
- 한가함 (2) "결과 없는 요청 파일" 은 새 함수 `queue.waiting(p)` 로 본다.
- 다시 묶기 닫기 실패 규칙(`rehome = "failed"` → 같은 틱의 리셋 단계나 다음 틱에 `terminal-reset`)은 첫 시도뿐 아니라, 관제가 다시 떠서 남은 `clear_error = "parent_changed"` 로 닫기를 잇다가 실패한 때도 같다. 설계 5.9.7 은 다시 뜬 관제가 "닫기부터 한다(지금 규칙 그대로)" 까지만 적었다. 그 닫기 실패를 닫기 세 번 규칙으로 보내면 보기 위한 묶음 때문에 decide 가 오른다.
- 다시 묶기 확인은 `hteam drive` 가 Run 에 묶인 관제 객체에서만 돈다(`bound_at`). 다른 곳에서 만든 `Drive` 객체(crew·tasks 의 로그용 등)는 틱을 돌아도 아무것도 하지 않는다.
- `rehome.json` 정리 로그의 `left(<까닭>)` 까닭: 끝나지 않은 hc 상태 낱말(`live` 등), `관제 라벨 없음`, hc·herdr-app 오류 문구(`hc get 실패: timeout` 등).
- watch 의 "새 줄이 없으면 첫 확인에서 바로 관제 생존을 본다(그 뒤 10초마다)"(설계 7.3) 는 지금 코드(`last = 0.0`)가 이미 그렇다. 코드는 그대로 두고 시험만 더한다.
- README 는 9.6 이 적은 업그레이드 절의 (4)·(5) 에 더해, 구조 절 "Herdr 묶음" 줄과 자동 부활의 한계 줄에 다시 묶기 한 문장씩을 더한다(같은 사실을 쓰는 곳이 바뀌지 않은 채 남지 않게).
- 끝내기 직전 접수된 큐 요청 시험은 `test_drive.py` 에 둔다(설계 15.1 이 시험 위치를 적지 않았다. 다시 묶기 끝내기 뒤의 일이다). 그 시험은 큐에 남은 요청(`.abandoned` 포함)과 새 관제의 처리만 본다. 메인 쪽 `queued` 응답은 기존 `test_queue.py` 의 `test_wait_timeout_is_queued_and_result_goes_to_outbox`(생존 확인을 지나 요청을 쓴 뒤 처리할 관제가 없어 시간이 다 됐다)가 본다. 메인은 관제가 왜 처리하지 않았는지 모르고 같은 대기 시간 초과 길을 타므로, 생존 확인 직후에 끝내기를 끼워 넣는 동기화 시험(제출 코드에 멈춤 지점이 필요하다)은 두지 않는다(Codex 계획 리뷰 r1).

## Global Constraints

- Python 3.11 이상, 표준 라이브러리만. 커밋 전에 바꾼 `.py` 를 `python3 -m py_compile` 로 확인한다.
- 11단계 보강 값(그대로 쓴다):
  - 상수(`herdr-team/lib/hteam/drive.py`, 설계 8.5 표): `REHOME_CHECK_S = 60`, `REHOME_MIN_UP_S = 600`. 시험용 `HTEAM_REHOME_CHECK_S`·`HTEAM_REHOME_MIN_UP_S`.
  - 파일 `.herdr-team/state/drive/rehome.json`(`Project.rehome_file`) = `{"at": <UTC Z>, "terminal": <끝나는 관제 터미널>, "parent": <그 parent 또는 null>, "main": <M>}`. 원자적으로 쓴다(`write_json`).
  - 로그(설계 8.11): `관제 다시 묶기: 메인이 <M> 로 바뀌었다(관제 parent <parent 또는 없음>). 한가하고 watch 가 돌 때 끝낸다`, `관제 종료: rehome: <parent 또는 없음> → <M>`, `앞 관제 터미널 <t> 정리: removed|gone|left(<까닭>)`, `<이름> 리셋: new_terminal(parent_changed)`, `<이름> 리셋: 다시 묶기 닫기 실패(<code>), 같은 터미널을 비운다`. 기록 실패: `rehome.json 을 쓰지 못했다: <오류>. 앞 관제 터미널은 관제 탭에 남는다`, `다시 묶기 progress 를 쓰지 못했다: <타입>: <오류>`.
  - outbox progress(설계 8.13): `관제를 새 메인 터미널(<M>) 아래로 다시 띄우려고 끝냈다. watch 가 orphaned 로 끝나면 /herdr-team:up 으로 다시 띄운다. 도는 워커는 그대로다`.
  - crew.json 의 `resetting`: `clear_error = "parent_changed"`, 다시 묶기 닫기 실패 뒤 `rehome = "failed"`(그때 `clear_error` 는 지운다). `close_failures` 는 세지 않는다.
  - 격리 키 `rehome`(틱 10 과 다시 뜬 뒤 정리). `hteam drive` 결과에 `rehome`(새 메인 주소, 다시 묶기로 끝났을 때만).
- 바꾸지 않는 것: `setup.up`, `outbox.watch`(코드), 훅, `templates/CLAUDE.section.md`·스킬·직무 문서, `hteam status`, herdr-orch 와 가짜 hc·herdr-app, 판별 코드(`outbox.require_main`, `roles._label_role`), 버전(이미 herdr-team 0.7.1, herdr-orch 0.4.0).
- 문서·메시지·주석은 한국어. 명령·코드 식별자·hc 의 영문 오류 문구는 원문.
- 저장소는 공개돼 있다. 커밋 전에 `git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews'` 가 아무것도 찾지 않아야 한다.
- 작업 브랜치 `herdr-team-p11` 에서 한다. main 에 직접 커밋하지 않는다. 커밋은 늘 경로 지정, 메시지 끝에 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- 테스트: 모듈을 `(cd herdr-team && python3 -m unittest tests.test_a tests.test_b)` 로 고른다. 전체는 저장소 루트에서 `bash herdr-team/tests/run.sh`(약 22분), `bash herdr-orch/tests/run.sh`(약 2분). 두 전체 시험을 동시에 돌리지 않는다. 기다릴 때 sleep 폴링하지 않고 백그라운드 알림을 받는다. 시험은 가짜 hc·herdr-app 만 쓰고 실제 Herdr 를 건드리지 않는다.
- **Codex 교차 검증(CLAUDE.md):** 이 계획은 실행 전에 `scripts/codex-review.sh doc` 로 검토받는다. 각 태스크의 마지막 단계는 커밋이다. 그 뒤 `scripts/codex-review.sh commit <sha>` 를 돌리고(`hc wait <주소> --timeout 3600` 백그라운드), 지적을 코드로 확인해 고치거나 고치지 않는 이유를 적는다. 리뷰 수정 범위는 P0·P1, 기본 경로의 P2, 회귀다. 가장자리 경우는 알려진 한계로 적는다.

## File Structure

| 파일 | 바뀌는 것 | 태스크 |
|---|---|---|
| `herdr-team/lib/hteam/paths.py` | `rehome_file` | 1 |
| `herdr-team/lib/hteam/queue.py` | `waiting(p)` | 1 |
| `herdr-team/lib/hteam/outbox.py` | `moved_main(p, parent, space)`, `MISSING` 가져오기 | 1 |
| `herdr-team/lib/hteam/herdr.py` | 모듈 설명(다시 묶기의 hc 호출) | 1 |
| `herdr-team/lib/hteam/drive.py` | 상수 둘, 자기 parent 기억, `mail_quiet`, 틱 10 `rehome_step`, 끝내기, `_tidy_rehome`, `main` 의 exit 0 | 1 |
| `herdr-team/tests/helpers.py` | `DROP_ENV` 에 시험용 환경 변수 둘 | 1 |
| `herdr-team/tests/test_drive.py` | 상수, 틱 순서, 관제 프로세스 시험, `RehomeTest`, `RehomeTidyTest` | 1 |
| `herdr-team/tests/test_setup.py` | 다시 띄우기(`up` 이 새 메인 아래), 경합 시험 보강 | 1 |
| `herdr-team/tests/test_mainlink.py` | `RehomeWatchTest`(progress 다음 orphaned) | 1 |
| `herdr-team/tests/test_autoup.py` | 다시 묶기로 끝난 관제는 REVIVED | 1 |
| `herdr-team/lib/hteam/crew.py` | `_parent_changed`, `_clear` 의 다시 묶기 갈래와 닫기 실패 | 2 |
| `herdr-team/tests/test_crew_reset.py` | `RehomeResetTest` | 2 |
| `README.md` | Herdr 묶음 줄, 자동 부활 한계 줄, "0.7.0 → 0.7.1" 의 (4)·(5) | 3 |
| `herdr-team/tests/test_setup.py` | README 시험 | 3 |
| `docs/superpowers/specs/2026-11-05-herdr-team-design.md`, `2026-11-04-herdr-orch-design.md` | 머리말 상태, 15.4 의 11단계 실환경 결과(1차·2차) | 5 |

---

### Task 1: 관제 다시 묶기 (설계 8.13, 8.2 의 4·6·7, 8.5 의 10)

**Files:**
- Modify: `herdr-team/lib/hteam/paths.py:46-47`, `herdr-team/lib/hteam/queue.py:186-189`, `herdr-team/lib/hteam/outbox.py:20`, `:307-314`, `herdr-team/lib/hteam/herdr.py:1-2`
- Modify: `herdr-team/lib/hteam/drive.py:10-11`, `:47-49`, `:54`, `:202`, `:298-320`(`check_mail`), `:1848-1863`(`tick`), `:1984-1991`(`_connect` 의 `bind`), `:2008`(`_hangup` 앞), `:2012-2054`(`main`)
- Test: `herdr-team/tests/helpers.py:113`, `herdr-team/tests/test_drive.py`(`ConstantsTest`, `DriveStartTest`, `TickTest`, 새 `RehomeTest`·`RehomeTidyTest`), `herdr-team/tests/test_setup.py`(`UpDriveTest`), `herdr-team/tests/test_mainlink.py`(새 `RehomeWatchTest`), `herdr-team/tests/test_autoup.py`(`DecideTest`)

**Interfaces:**
- Produces: `outbox.moved_main(p, parent: str | None, space: str | None) -> str | None`, `queue.waiting(p) -> bool`, `Project.rehome_file`.
- Produces: `drive.REHOME_CHECK_S`, `drive.REHOME_MIN_UP_S`, `Drive.terminal`·`parent`·`parent_known`·`bound_at`·`last_rehome`·`rehome_seen`·`rehome_to`·`mail_quiet`, `Drive.rehome_step() -> bool`, `Drive._rehome_candidate() -> str | None`, `Drive._read_parent() -> bool`, `Drive.tick() -> bool`(다시 묶기로 끝낼 때만 True), `drive._tidy_rehome(p, d, term)`, `hteam drive` 결과의 `rehome`.
- Consumed by: Task 2 의 `crew._parent_changed` 가 `outbox.moved_main` 을 쓴다.

**Rules:**
- 확인(60초마다): Run 에 묶인 지 600초(`bound_at`, monotonic) → `main_parent` 가 M → 자기 parent 를 알고 M 이 그것과 다르다(모르면 `hc get <자기>` 3초로 한 번 읽는다. 또 실패하면 그 확인은 아무것도 하지 않는다) → `moved_main`. 하나라도 아니면 후보와 정한 것을 지운다. M 이 parent 와 같으면 hc 를 부르지 않는다.
- 같은 M 이 두 번 연달아 후보일 때만 정한다(로그 한 줄). 후보가 바뀌면 다시 센다.
- 끝내기(정한 뒤 틱 끝마다): `main_parent` 가 아직 M(아니면 정한 것을 지운다) → 한가함 넷(이번 틱 메일 확인이 성공했고 메시지 없음, `queue.waiting` 거짓, `jobs`·`retry_reviews` 없음, `resetting` 인 crew entry 없음) → `outbox.watch_alive`. 아니면 기다리기만 한다(상한 없음).
- 차례: `rehome.json`(실패해도 계속) → progress(실패해도 계속) → 로그 `관제 종료: rehome: …` → True. `main` 은 그 틱 뒤 `{run_id, mode, ticks, rehome}` 로 돌아가 exit 0 이고 `finally` 가 drive.pid 를 지운다.
- 다시 뜬 뒤: Run 연결과 탭 이름 뒤, 시작 재확인 전에 `_tidy_rehome`. 파일이 없으면 아무것도 하지 않는다. `terminal` 이 자기 터미널이면 hc 를 부르지 않는다. 어느 쪽이든 파일을 지운다. 의존 프로그램 없음(exit 12)은 그대로 올린다.
- 도는 워커·리뷰어·보기 pane 은 한가함에 넣지 않고 옮기지 않는다. `up`·watch·훅은 바꾸지 않는다.

- [ ] **Step 1: 시험 쓰기**

**Edit** `herdr-team/tests/helpers.py`

```python
            "HTEAM_RESET_TIMEOUT_MS", "CODEX_HOME")
```

```python
            "HTEAM_RESET_TIMEOUT_MS", "CODEX_HOME", "HTEAM_REHOME_CHECK_S", "HTEAM_REHOME_MIN_UP_S")
```

**Edit** `herdr-team/tests/test_drive.py`

```python
from hteam import drive, state, util
```

```python
from hteam import drive, herdr, outbox, procs, state, util
```

**Edit** `herdr-team/tests/test_drive.py`

```python
                         (10000, 1.0, 5.0, 60, 120, 180, 90, 0.2, 60, 1800, 1800, 1800, 1800, 3, 10000, 3, 60, 3, 5.0))
```

```python
                         (10000, 1.0, 5.0, 60, 120, 180, 90, 0.2, 60, 1800, 1800, 1800, 1800, 3, 10000, 3, 60, 3, 5.0))
        # 11단계 보강(설계 8.5 의 표, 8.13): 다시 묶기 확인 간격, Run 에 묶인 뒤 다시 묶지 않는 시간
        self.assertEqual((drive.REHOME_CHECK_S, drive.REHOME_MIN_UP_S), (60, 600))
```

**Edit** `herdr-team/tests/test_drive.py`

```python
                self.assertRegex(self.log_lines()[-1], rf"^{LOCAL_ISO} 관제 종료: SystemExit: {code}$")
                self.assertFalse((self.drive_dir / "drive.pid").exists())


class TickTest(DriveCase):
    """틱 순서와 격리(설계 8.5). 단계 몸통은 뒤 태스크가 채운다. 여기서는 순서·heartbeat·격리·check 를 본다."""

    STEPS = ("heartbeat", "check_mail", "run_queue", "start_ready", "reap_jobs", "reset_step", "view_step", "reconcile")
```

```python
                self.assertRegex(self.log_lines()[-1], rf"^{LOCAL_ISO} 관제 종료: SystemExit: {code}$")
                self.assertFalse((self.drive_dir / "drive.pid").exists())

    def test_rehome_ends_with_exit_0_and_releases_pid(self):
        # 11단계 보강(설계 8.13, 8.2 의 7): 메인이 바뀌었고 한가하고 메인 watch 가 돌면 다시 묶기로 exit 0 이다. 자기 parent 는
        # Run 연결의 hc get 이 읽는다. 시간 상수는 시험 환경 변수로 줄인다(기본 60·600초)
        self.update_terminal(DRIVE, parent="t2")  # 앞 메인 아래 띄운 관제
        self.set_run(main_terminal=MAIN)
        (self.state_dir / "watch.pid").write_text(json.dumps(procs.me()))
        code, out, _ = self.drive(env={"HTEAM_DRIVE_TICKS": "5", "HTEAM_REHOME_CHECK_S": "0", "HTEAM_REHOME_MIN_UP_S": "0"})
        self.assertEqual((code, out.get("rehome"), out.get("ticks")), (0, MAIN, 2), out)
        self.assertFalse((self.drive_dir / "drive.pid").exists())
        rec = json.loads((self.drive_dir / "rehome.json").read_text())
        self.assertEqual((rec["terminal"], rec["parent"], rec["main"]), (DRIVE, "t2", MAIN))
        self.assertRegex(self.log_lines()[-1], rf"^{LOCAL_ISO} 관제 종료: rehome: t2 → {MAIN}$")
        # 같은 터미널에서 다시 뜬 관제(이 시험): rehome.json 의 터미널이 자기 것이라 지우지 않고 파일만 지운다
        code, out, _ = self.drive()
        self.assertEqual((code, out.get("rehome")), (0, None), out)
        self.assertFalse((self.drive_dir / "rehome.json").exists())
        self.assertIn(DRIVE, self.hc_state()["terminals"])

    def test_new_drive_tidies_the_rehomed_terminal_before_reconcile(self):
        # 11단계 보강(설계 8.13 의 "다시 뜬 뒤", 8.2 의 6): up 이 run.json 의 drive_terminal 을 새 주소로 바꿨어도 rehome.json
        # 으로 앞 관제를 안다. 끝난 관제 터미널을 지우고 파일을 지운다
        self.add_terminal("t300", argv=DRIVE_ARGV, state="finished",
                          labels={"herdr.space": "spA", "herdr.tab": "tbTeam", "hteam.role": "drive"})
        (self.drive_dir / "rehome.json").write_text(json.dumps({"at": util.now(), "terminal": "t300", "parent": "t2",
                                                               "main": MAIN}))
        code, out, _ = self.drive()
        self.assertEqual(code, 0, out)
        self.assertNotIn("t300", self.hc_state()["terminals"])
        self.assertFalse((self.drive_dir / "rehome.json").exists())
        lines = self.log_lines()
        start = next(i for i, line in enumerate(lines) if "관제 시작(t100)" in line)
        self.assertRegex(lines[start + 1], rf"^{LOCAL_ISO} 앞 관제 터미널 t300 정리: removed$")  # 시작 재확인 전


class TickTest(DriveCase):
    """틱 순서와 격리(설계 8.5). 단계 몸통은 뒤 태스크가 채운다. 여기서는 순서·heartbeat·격리·check 를 본다."""

    STEPS = ("heartbeat", "check_mail", "run_queue", "start_ready", "reap_jobs", "reset_step", "view_step", "reconcile",
             "rehome_step")
```

**Edit** `herdr-team/tests/test_drive.py`

```python
    def test_tick_order_and_reconcile_interval(self):
        calls = self.stub(*self.STEPS)
        self.d.tick()
        self.assertEqual(calls, ["heartbeat", "check_mail", "run_queue", "reap_jobs", "heartbeat", "reset_step",
                                 "view_step", "reconcile"])
        calls.clear()
        self.d.tick()  # 마지막 재확인 뒤 60초 안: 재확인하지 않는다
        self.assertEqual(calls, ["heartbeat", "check_mail", "run_queue", "reap_jobs", "heartbeat", "reset_step",
                                 "view_step"])
        calls.clear()
        self.d.last_reconcile -= 61
        self.d.tick()
        self.assertEqual(calls[-1], "reconcile")
```

```python
    def test_tick_order_and_reconcile_interval(self):
        calls = self.stub(*self.STEPS)
        self.assertFalse(self.d.tick())
        self.assertEqual(calls, ["heartbeat", "check_mail", "run_queue", "reap_jobs", "heartbeat", "reset_step",
                                 "view_step", "reconcile", "rehome_step"])  # 11단계 보강: 틱 10 은 다시 묶기(8.13)
        calls.clear()
        self.d.tick()  # 마지막 재확인 뒤 60초 안: 재확인하지 않는다
        self.assertEqual(calls, ["heartbeat", "check_mail", "run_queue", "reap_jobs", "heartbeat", "reset_step",
                                 "view_step", "rehome_step"])
        calls.clear()
        self.d.last_reconcile -= 61
        self.d.tick()
        self.assertEqual(calls[-2:], ["reconcile", "rehome_step"])

    def test_tick_reports_the_rehome_end_and_isolates_it(self):
        # 다시 묶기로 끝낼 때만 True(관제 루프가 exit 0 으로 나간다, 8.2 의 7). 실패는 격리되어 끝내지 않는다
        self.stub(*self.STEPS[:-1])
        with mock.patch.object(self.d, "rehome_step", return_value=True):
            self.assertTrue(self.d.tick())
        with mock.patch.object(self.d, "rehome_step", side_effect=RuntimeError("x")):
            self.assertFalse(self.d.tick())
        self.assertTrue(any(re.search(rf"^{LOCAL_ISO} rehome 실패: RuntimeError: x$", line) for line in self.log_lines()),
                        self.log_lines())
```

**Edit** `herdr-team/tests/test_drive.py`

```python


if __name__ == "__main__":
    unittest.main()
```

```python


class RehomeTest(DriveCase):
    """관제 다시 묶기(11단계 보강, 설계 8.13·8.5 의 10): 메인이 바뀌면(main_terminal) 같은 새 메인이 확인 두 번(60초 간격)
    연달아 후보일 때 정하고, 한가하고 메인 watch 가 돌 때 rehome.json·progress·로그를 남기고 끝낸다(관제 루프는 exit 0)."""

    def setUp(self):
        super().setUp()
        self.env.update({"HTEAM_DRIVE_WAIT_MS": "50"})
        patcher = self.in_drive()
        patcher.start()
        self.addCleanup(patcher.stop)
        # 앞 메인 t2(탭을 닫아 끝났다) 아래 띄운 관제. 새 메인 MAIN 의 watch 가 main_terminal 을 썼다
        self.add_terminal("t2", argv=["claude"], state="finished", labels={"herdr.space": "spA", "herdr.tab": "tbMain2"})
        self.update_terminal(DRIVE, parent="t2")
        self.set_run(main_terminal=MAIN)
        self.watching()
        self.d = self.fresh()

    def watching(self) -> None:
        """메인 watch 가 돈다(watch.pid 는 살아 있는 이 시험 프로세스. Stop 훅과 같은 기록, 9.4)."""
        (self.state_dir / "watch.pid").write_text(json.dumps(procs.me()))

    def fresh(self, parent="t2", up=None):
        """Run 에 묶인 지 up 초(기본 REHOME_MIN_UP_S + 1) 된 관제 객체. Run 연결의 hc get 이 parent 를 읽었다."""
        d = self.make_drive()
        d.bound_at = time.monotonic() - (drive.REHOME_MIN_UP_S + 1 if up is None else up)
        d.parent, d.parent_known = parent, True
        return d

    @staticmethod
    def step(d, quiet=True) -> bool:
        """틱 끝의 다시 묶기 단계 한 번. 확인 간격(60초)이 지난 것으로 둔다. quiet 는 이번 틱의 메일 확인이 비었는가."""
        d.last_rehome, d.mail_quiet = None, quiet
        return d.rehome_step()

    @staticmethod
    def end(d, quiet=True) -> bool:
        """정한 뒤의 틱 끝(확인 간격 안: 확인은 하지 않고 끝낼지만 본다)."""
        d.last_rehome, d.mail_quiet = time.monotonic(), quiet
        return d.rehome_step()

    def decided(self, d) -> None:
        self.assertFalse(self.step(d, quiet=False))
        self.assertFalse(self.step(d, quiet=False))  # 정했지만 바빠서 끝내지 않았다
        self.assertEqual(d.rehome_to, MAIN)

    def never(self, d) -> None:
        """두 번 확인해도 정하지 않고 끝내지 않는다."""
        start = len(self.log_lines())
        self.assertFalse(self.step(d))
        self.assertFalse(self.step(d))
        self.assertIsNone(d.rehome_to)
        self.assertFalse((self.drive_dir / "rehome.json").exists())
        self.assertEqual([x for x in self.log_lines()[start:] if "다시 묶기" in x or "rehome" in x], [])

    def test_two_checks_then_ends_when_quiet_and_watched(self):
        for parent in ("t2", None):  # parent 가 없는 관제(메인이 지워져 --no-parent 로 뜬 관제, 9.3 의 3)도 다르다
            with self.subTest(parent=parent):
                (self.drive_dir / "rehome.json").unlink(missing_ok=True)
                d = self.fresh(parent)
                start = len(self.log_lines())
                self.assertFalse(self.step(d))  # 한 번만 후보: 아직 정하지 않는다
                self.assertFalse((self.drive_dir / "rehome.json").exists())
                self.assertTrue(self.step(d))
                was = parent or "없음"
                lines = self.log_lines()[start:]
                self.assertEqual(len(lines), 2, lines)
                self.assertRegex(lines[0], rf"^{LOCAL_ISO} 관제 다시 묶기: 메인이 {MAIN} 로 바뀌었다\(관제 parent {was}\)\. "
                                           r"한가하고 watch 가 돌 때 끝낸다$")
                self.assertRegex(lines[1], rf"^{LOCAL_ISO} 관제 종료: rehome: {was} → {MAIN}$")
                rec = json.loads((self.drive_dir / "rehome.json").read_text())
                self.assertEqual((rec["terminal"], rec["parent"], rec["main"]), (DRIVE, parent, MAIN))
                self.assertRegex(rec["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
                last = self.outbox_items()[-1]
                self.assertEqual((last["type"], last["body"]),
                                 ("progress", f"관제를 새 메인 터미널({MAIN}) 아래로 다시 띄우려고 끝냈다. watch 가 orphaned "
                                              "로 끝나면 /herdr-team:up 으로 다시 띄운다. 도는 워커는 그대로다"))

    def test_checks_only_every_60_seconds(self):
        self.d.mail_quiet = True
        self.assertFalse(self.d.rehome_step())
        self.assertFalse(self.d.rehome_step())  # 60초 안: 확인하지 않아 두 번째 후보가 아니다
        self.assertIsNone(self.d.rehome_to)
        self.d.last_rehome -= drive.REHOME_CHECK_S + 1
        self.assertTrue(self.d.rehome_step())

    def test_unknown_parent_is_read_once_with_hc(self):
        # Run 연결의 hc get 이 실패했다: 확인 때 hc get(3초)으로 한 번 읽는다(parent 는 띄울 때만 정해진다)
        self.d.parent, self.d.parent_known = None, False
        before = len([c for c in self.hc_calls() if c[:2] == ["get", DRIVE]])
        self.assertFalse(self.step(self.d))
        self.assertTrue(self.step(self.d))
        self.assertEqual(self.d.parent, "t2")
        self.assertEqual(len([c for c in self.hc_calls() if c[:2] == ["get", DRIVE]]), before + 1)

    def test_no_candidate_does_nothing(self):
        self.add_terminal("t3", argv=["claude"], state="finished", labels={"herdr.space": "spA", "herdr.tab": "tbMain3"})
        self.add_terminal("t4", name="main-b", argv=["claude"], labels={"herdr.space": "spA", "herdr.tab": "tbMain4"},
                          status="idle")
        self.add_terminal("t5", argv=["claude"], labels={"herdr.space": "spB", "herdr.tab": "tbMain5"}, status="idle")
        self.add_terminal("t6", argv=["claude"], labels={"herdr.tab": "tbMain6"}, status="idle")
        cases = (("main_terminal 없음", None, "t2"), ("형식이 틀림", "t1;rm", "t2"), ("끝난 메인", "t3", "t2"),
                 ("지운 메인(이 기계의 hc 가 모르는 주소)", "t404", "t2"), ("같은 터미널의 다른 이름", "main-b", "t4"),
                 ("다른 space", "t5", "t2"), ("space 라벨 없음", "t6", "t2"))
        for why, main, parent in cases:
            with self.subTest(why=why):
                self.set_run(main_terminal=main)
                self.never(self.fresh(parent))
        self.set_run(main_terminal="t2")
        before = len(self.hc_calls())
        self.never(self.fresh("t2"))  # 메인이 parent 와 같다: run.json 만 읽고 hc 를 부르지 않는다
        self.assertEqual(len(self.hc_calls()), before)
        self.set_run(main_terminal=MAIN)
        self.never(self.fresh(up=drive.REHOME_MIN_UP_S - 5))  # Run 에 묶인 지 10분 안
        text = (self.state_dir / "run.json").read_text()
        (self.state_dir / "run.json").write_text("{broken")  # run.json 을 읽지 못한다
        self.never(self.fresh())
        (self.state_dir / "run.json").write_text(text)
        self.fail_hc("get", "timeout")
        self.never(self.fresh())  # hc get M 실패
        d = self.fresh(None)
        d.parent_known = False
        self.never(d)  # 자기 parent 를 모르고 hc get 도 실패한다

    def test_count_restarts_when_main_moves(self):
        self.add_terminal("t7", argv=["claude"], labels={"herdr.space": "spA", "herdr.tab": "tbMain7"}, status="idle")
        self.assertFalse(self.step(self.d))  # MAIN 이 처음 후보
        self.set_run(main_terminal="t7")  # 메인을 넘겨받는 중이다
        self.assertFalse(self.step(self.d))  # 후보가 바뀌었다: 다시 센다
        self.assertIsNone(self.d.rehome_to)
        self.assertTrue(self.step(self.d))
        self.assertRegex(self.log_lines()[-1], rf"^{LOCAL_ISO} 관제 종료: rehome: t2 → t7$")

    def test_main_change_after_the_decision_clears_it(self):
        self.add_terminal("t7", argv=["claude"], labels={"herdr.space": "spA", "herdr.tab": "tbMain7"}, status="idle")
        self.decided(self.d)
        self.set_run(main_terminal="t7")
        self.assertFalse(self.end(self.d))  # 파일만 읽고 정한 것을 지운다
        self.assertIsNone(self.d.rehome_to)
        self.assertFalse((self.drive_dir / "rehome.json").exists())
        self.assertFalse(self.step(self.d))  # 확인부터 다시 한다
        self.assertTrue(self.step(self.d))
        self.assertEqual(json.loads((self.drive_dir / "rehome.json").read_text())["main"], "t7")

    def test_waits_while_busy_or_unwatched(self):
        d = self.d
        self.decided(d)
        queue = self.drive_dir / "queue"
        request = queue / "000001.json"
        crew_file = self.state_dir / "crew.json"

        def put_request():
            queue.mkdir(parents=True, exist_ok=True)
            request.write_text(json.dumps({"id": "q-000001", "command": "start-ready", "args": {}, "at": util.now()}))

        def resetting():
            crew_file.write_text(json.dumps({"production": {"resetting": {"step": "handoff", "dispatch": "dsp-x"}}}))

        busy = (("이번 틱의 메시지(미룬 메시지는 test_held_mail_keeps_the_drive_busy)", lambda: None, lambda: None, False),
                ("결과 없는 큐 요청", put_request, request.unlink, True),
                ("도는 자식", lambda: d.jobs.update({"review:T-001": {}}), d.jobs.clear, True),
                ("미룬 리뷰", lambda: d.retry_reviews.add("T-001"), d.retry_reviews.clear, True),
                ("리셋 중인 고정 에이전트", resetting, crew_file.unlink, True),
                ("메인 watch 없음", (self.state_dir / "watch.pid").unlink, self.watching, True))
        for why, make, undo, quiet in busy:
            with self.subTest(why=why):
                make()
                self.assertFalse(self.end(d, quiet=quiet))
                self.assertEqual(d.rehome_to, MAIN)  # 정한 것은 그대로 두고 기다린다(상한 없음)
                self.assertFalse((self.drive_dir / "rehome.json").exists())
                undo()
        self.assertTrue(self.end(d))

    def test_ends_even_if_the_record_or_progress_fails(self):
        cases = ((mock.patch.object(drive, "write_json", side_effect=OSError("디스크가 찼다")),
                  "rehome.json 을 쓰지 못했다: 디스크가 찼다. 앞 관제 터미널은 관제 탭에 남는다"),
                 (mock.patch.object(outbox, "append", side_effect=OSError("디스크가 찼다")),
                  "다시 묶기 progress 를 쓰지 못했다: OSError: 디스크가 찼다"))
        for patch, line in cases:
            with self.subTest(line=line):
                d = self.fresh()
                with patch:
                    self.assertFalse(self.step(d))
                    self.assertTrue(self.step(d))  # 쓰지 못해도 끝낸다(watch 는 orphaned 로 안다)
                lines = self.log_lines()
                self.assertTrue(any(x.endswith(line) for x in lines), lines)
                self.assertRegex(lines[-1], rf"^{LOCAL_ISO} 관제 종료: rehome: t2 → {MAIN}$")

    def test_mail_check_sets_quiet(self):
        d = self.d
        d.check_mail()
        self.assertTrue(d.mail_quiet)
        code, sent = self.horch("send", "--to", f"run:{self.run_id}", "--subject", "s", "--body=x", terminal=MAIN)
        self.assertEqual(code, 0, sent)
        with mock.patch.object(d, "handle"):
            d.check_mail()
        self.assertFalse(d.mail_quiet)
        d.check_mail()  # 앞 묶음을 --ack 로 확인했고 새 메시지가 없다
        self.assertTrue(d.mail_quiet)
        with mock.patch.dict(os.environ, {"HC_TERMINAL_ID": "t999"}), self.assertRaises(Exception):
            d.check_mail()  # 확인 실패(Run 소유자가 아니다)
        self.assertFalse(d.mail_quiet)

    def test_held_mail_keeps_the_drive_busy(self):
        # 미룬 메시지(8.6: 상태에 아직 없는 진행 중 Dispatch)가 있으면 check_mail 이 그 묶음을 ack 하지 않고 horch 가 다음
        # 확인에서 같은 묶음을 다시 준다. 그동안 한가하지 않아 끝내지 않는다(mail_quiet 는 check_mail 이 정한다)
        d = self.d
        self.decided(d)
        code, sent = self.horch("send", "--to", f"run:{self.run_id}", "--subject", "s", "--body=x", terminal=MAIN)
        self.assertEqual(code, 0, sent)

        def tick_end() -> bool:
            d.last_rehome = time.monotonic()  # 확인 간격 안: 끝낼지만 본다
            return d.rehome_step()

        with mock.patch.object(d, "handle", return_value=True) as handle:  # 처리기가 미룬다(ack 하지 않는다)
            for _ in range(2):
                d.check_mail()
                self.assertFalse(d.mail_quiet)
                self.assertFalse(tick_end())
        self.assertEqual([c.args[0]["id"] for c in handle.call_args_list], [sent["message"]] * 2)  # 같은 묶음이 다시 왔다
        self.assertEqual(d.rehome_to, MAIN)  # 정한 것은 그대로 두고 기다린다
        self.assertFalse((self.drive_dir / "rehome.json").exists())
        with mock.patch.object(d, "handle", return_value=None):
            d.check_mail()  # 이번에는 처리한다(이 틱에는 메시지가 있었다)
        self.assertFalse(tick_end())
        d.check_mail()  # 앞 묶음을 --ack 로 확인했고 새 메시지가 없다
        self.assertTrue(tick_end())

    def test_request_racing_the_end_is_run_by_the_next_drive(self):
        # 메인 명령이 관제 생존 확인을 지난 뒤 요청 파일을 쓰기 전에 관제가 빈 큐를 보고 끝났다(설계 8.13 의 끊긴 시간). 요청은
        # 큐에 남고 메인은 기다리다 queued 로 그만둔다(.abandoned). 다시 뜬 관제가 처리해 outbox result 로 알린다(7.1)
        self.assertFalse(self.step(self.d))
        self.assertTrue(self.step(self.d))
        queue = self.drive_dir / "queue"
        queue.mkdir(parents=True, exist_ok=True)
        (queue / "000001.json").write_text(json.dumps({"id": "q-000001", "command": "start-ready", "args": {},
                                                       "at": util.now()}))
        (queue / "000001.abandoned").touch()
        self.assertEqual(self.make_drive().run_queue(), ["q-000001"])
        self.assertEqual([e["request"] for e in self.outbox_items() if e["type"] == "result"], ["q-000001"])
        self.assertEqual(sorted(f.name for f in queue.iterdir()), [])


class RehomeTidyTest(DriveCase):
    """다시 뜬 관제의 앞 관제 터미널 정리(11단계 보강, 설계 8.13 의 "다시 뜬 뒤", 8.2 의 6)."""

    def setUp(self):
        super().setUp()
        patcher = self.in_drive()
        patcher.start()
        self.addCleanup(patcher.stop)
        self.d = self.make_drive()
        self.old()

    def old(self) -> None:
        """다시 묶기로 끝난 앞 관제 터미널(끝났고 관제 라벨이 있다)."""
        self.add_terminal("t300", argv=DRIVE_ARGV, state="finished",
                          labels={"herdr.space": "spA", "herdr.tab": "tbTeam", "hteam.role": "drive"})

    def tidy(self, terminal="t300") -> list[str]:
        """rehome.json 을 두고 정리한 뒤 새 로그 줄. 어느 쪽이든 파일을 지운다(한 번만 본다)."""
        (self.drive_dir / "rehome.json").write_text(json.dumps({"at": util.now(), "terminal": terminal, "parent": "t2",
                                                               "main": MAIN}))
        start = len(self.log_lines())
        drive._tidy_rehome(self.p, self.d, DRIVE)
        self.assertFalse((self.drive_dir / "rehome.json").exists())
        return self.log_lines()[start:]

    def test_finished_drive_terminal_pane_is_closed_then_removed(self):
        seen = []
        real_rm = herdr.rm
        with mock.patch.object(herdr, "pane_of", return_value="pt300"), \
                mock.patch.object(herdr, "close_pane", side_effect=lambda pane, timeout=10: seen.append(("close", pane))), \
                mock.patch.object(herdr, "rm", side_effect=lambda t, timeout=10: seen.append(("rm", t)) or real_rm(t)):
            lines = self.tidy()
        self.assertEqual(seen, [("close", "pt300"), ("rm", "t300")])  # 6.5 의 3 과 같은 순서
        self.assertNotIn("t300", self.hc_state()["terminals"])
        self.assertEqual(len(lines), 1, lines)
        self.assertRegex(lines[0], rf"^{LOCAL_ISO} 앞 관제 터미널 t300 정리: removed$")

    def test_without_pane_is_removed_then_gone(self):
        lines = self.tidy()  # 가짜 herdr-app ls 는 끝난 터미널을 내지 않는다(pane 이 없다)
        self.assertRegex(lines[0], rf"^{LOCAL_ISO} 앞 관제 터미널 t300 정리: removed$")
        self.assertNotIn("t300", self.hc_state()["terminals"])
        self.assertEqual([c for c in self.herdr_calls() if c[:2] == ["do", "pane.close"]], [])
        lines = self.tidy()  # 이미 없다(not_found)
        self.assertRegex(lines[0], rf"^{LOCAL_ISO} 앞 관제 터미널 t300 정리: gone$")

    def test_other_states_are_left(self):
        cases = (("live", {"state": "live"}, None), ("관제 라벨 없음", {"labels": {"herdr.space": "spA"}}, None),
                 ("hc get 실패: timeout", {}, ("get", "timeout")), ("hc rm 실패: busy", {}, ("rm", "busy")))
        for why, fields, failing in cases:
            with self.subTest(why=why):
                self.old()
                if fields:
                    self.update_terminal("t300", **fields)
                if failing:
                    self.fail_hc(*failing)
                lines = self.tidy()
                with self._hc_locked() as st:
                    st["fail"].clear()
                self.assertIn("t300", self.hc_state()["terminals"])  # 지우지 않는다(9.3 의 6 대로 관제 탭에 남는다)
                self.assertEqual(len(lines), 1, lines)
                self.assertRegex(lines[0], rf"^{LOCAL_ISO} 앞 관제 터미널 t300 정리: left\({re.escape(why)}\)$")

    def test_no_file_or_own_terminal_does_nothing(self):
        before = len(self.hc_calls())
        drive._tidy_rehome(self.p, self.d, DRIVE)  # 파일이 없다: 관제가 죽었다 다시 떴다
        self.assertEqual(self.log_lines(), [])
        self.assertEqual(self.tidy(DRIVE), [])  # 자기 터미널(같은 터미널에서 다시 떴다): 지우지 않고 파일만 지운다
        self.assertEqual(len(self.hc_calls()), before)
        self.assertIn(DRIVE, self.hc_state()["terminals"])


if __name__ == "__main__":
    unittest.main()
```

**Edit** `herdr-team/tests/test_setup.py`

```python
        self.assertEqual(self.hc_state()["terminals"][out["terminal"]]["parent"], MAIN)
        self.assertEqual(self.run_json()["main_terminal"], "t2")
```

```python
        self.assertEqual(self.hc_state()["terminals"][out["terminal"]]["parent"], MAIN)
        self.assertEqual(self.run_json()["main_terminal"], "t2")
        # 11단계 보강(설계 8.13 의 다시 띄우기): 새 관제는 처음부터 앞 메인 아래로 떴다. Run 에 묶인 지 10분이 지난 확인에서
        # t2 가 다시 묶기 후보다(10분 안에는 아니다). 자기 parent 는 hc get 으로 한 번 읽는다
        from hteam import drive
        with self.in_drive():
            d = self.make_drive()
            d.terminal, d.bound_at = out["terminal"], time.monotonic() - drive.REHOME_MIN_UP_S + 5
            self.assertIsNone(d._rehome_candidate())
            d.bound_at = time.monotonic() - drive.REHOME_MIN_UP_S - 1
            self.assertEqual((d._rehome_candidate(), d.parent, d.parent_known), ("t2", MAIN, True))

    # --- 11단계 보강: 다시 묶기로 끝난 관제를 새 메인 아래 다시 띄운다(설계 8.13 의 다시 띄우기, 9.3 의 7) ---
    def test_rehomed_drive_is_relaunched_under_the_new_main(self):
        from hteam import drive
        self.add_terminal("t2", argv=["claude"], labels={"herdr.space": "spA", "herdr.tab": "tbMain2"}, status="idle")
        self.set_run(main_terminal="t2")  # 새 메인의 watch 가 썼다
        self.update_terminal(DRIVE, state="finished")  # 다시 묶기로 끝난 앞 관제(Run 에 묶인 뒤 꺼졌다)
        rehome = json.dumps({"at": "2026-11-16T00:00:00Z", "terminal": DRIVE, "parent": MAIN, "main": "t2"})
        (self.drive_dir / "rehome.json").write_text(rehome)
        self.kill_drive()
        code, out = self.hteam("up", as_=None, terminal="t2")
        self.assertEqual((code, out["status"], out["launched"]), (0, "launched", True), out)  # starting 이 아니다
        term = self.hc_state()["terminals"][out["terminal"]]
        call = self.run_calls()[-1]
        self.assertEqual((call[call.index("--parent") + 1], term["parent"], self.run_json()["main_terminal"]),
                         ("t2", "t2", "t2"))
        self.assertEqual((self.drive_dir / "rehome.json").read_text(), rehome)  # up 은 그대로다(새 관제가 정리한다)
        with self.in_drive():
            d = self.make_drive()
            d.terminal, d.bound_at = out["terminal"], time.monotonic() - drive.REHOME_MIN_UP_S - 1
            d.parent, d.parent_known = term["parent"], True
            before = len(self.hc_calls())
            self.assertIsNone(d._rehome_candidate())  # 새 관제는 parent 가 main_terminal 과 같다: 되풀이하지 않는다
            self.assertEqual(len(self.hc_calls()), before)  # run.json 만 읽는다
```

**Edit** `herdr-team/tests/test_mainlink.py`

```python
class RenderGuardTest(unittest.TestCase):
```

```python
class RehomeWatchTest(LinkCase):
    """11단계 보강(설계 8.13·7.3): 다시 묶기로 끝난 관제의 progress 를 메인 watch 가 먼저 주고, 메인이 다시 띄운 watch 는 첫
    확인에서 바로 orphaned 로 끝난다(Run 에 묶인 뒤 꺼진 관제라 starting 이 아니다). 메인은 규칙대로 /herdr-team:up 을 한다."""

    def test_progress_first_then_orphaned_at_the_first_check(self):
        from hteam import drive
        self.add_terminal("t2", argv=["claude"], labels={"herdr.space": "spA", "herdr.tab": "tbMain2"}, status="idle")
        proc = self.hteam_bg("watch", as_=None, terminal="t2")  # 새 메인(t2)의 watch 가 main_terminal 을 쓴다

        def main_terminal():
            return json.loads((self.state_dir / "run.json").read_text()).get("main_terminal")
        self.wait_until(lambda: main_terminal() == "t2", "새 메인의 watch 가 main_terminal 을 쓰지 않았다")
        with self.in_drive():
            d = self.make_drive()  # 앞 메인(MAIN) 아래 띄워 Run 에 묶인 지 10분이 지난 관제
            d.bound_at, d.parent, d.parent_known = time.monotonic() - drive.REHOME_MIN_UP_S - 1, MAIN, True
            d.mail_quiet = True
            self.assertFalse(d.rehome_step())
            d.last_rehome = None
            self.assertTrue(d.rehome_step())  # 메인 watch 가 돈다(watch.pid)
        code, out = self.finish(proc, timeout=10)
        self.assertEqual((code, out["count"]), (0, 1), out)
        self.assertIn("/herdr-team:up", out["messages"][0]["body"])
        (self.drive_dir / "drive.pid").unlink()  # 관제 프로세스가 끝나며 지운다(8.2 의 7)
        code, out = self.hteam("watch", as_=None, terminal="t2", env={"HTEAM_ORPHAN_CHECK": "30"}, timeout=10)
        self.assertEqual((code, out.get("status")), (0, "orphaned"), out)


class RenderGuardTest(unittest.TestCase):
```

**Edit** `herdr-team/tests/test_autoup.py`

```python
        self.set_record(spawned_at=ago(700))
        self.assertEqual(decide(self.p, time.monotonic() + 12), ("spawn", REVIVED))
```

```python
        self.set_record(spawned_at=ago(700))
        self.assertEqual(decide(self.p, time.monotonic() + 12), ("spawn", REVIVED))

    def test_rehomed_drive_is_revived_not_failed(self):
        # 11단계 보강(설계 9.5·8.13): 다시 묶기는 Run 에 묶인 지 REHOME_MIN_UP_S 뒤 첫 후보, REHOME_CHECK_S 뒤 두 번째 후보에서야
        # 끝나므로 자동 부활이 띄운 시각(spawned_at, Run 연결과 몇 초 차이)의 RETRY_WINDOW_S 창 밖이다. 결정 규칙은 그대로다
        self.assertGreaterEqual(drive.REHOME_MIN_UP_S, autoup.RETRY_WINDOW_S)
        self.dead()
        (self.drive_dir / "rehome.json").write_text(json.dumps({"at": now(), "terminal": DRIVE, "parent": MAIN,
                                                               "main": "t2"}))
        self.set_record(spawned_at=ago(drive.REHOME_MIN_UP_S + drive.REHOME_CHECK_S))
        self.assertEqual(decide(self.p, time.monotonic() + 12), ("spawn", REVIVED))
```

- [ ] **Step 2: 시험이 실패하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_drive.ConstantsTest tests.test_drive.DriveStartTest tests.test_drive.TickTest tests.test_drive.RehomeTest tests.test_drive.RehomeTidyTest tests.test_setup.UpDriveTest tests.test_mainlink.RehomeWatchTest tests.test_autoup.DecideTest)`
Expected: FAIL(`REHOME_CHECK_S`·`REHOME_MIN_UP_S`·`rehome_step`·`_rehome_candidate`·`_tidy_rehome` 가 없고, 관제가 다시 묶기로 끝나지 않는다).

- [ ] **Step 3: 경로·큐·outbox·herdr 설명**

**Edit** `herdr-team/lib/hteam/paths.py`

```python
        self.workers_file = self.drive_dir / "workers.json"
        self.jobs_dir = self.drive_dir / "jobs"
```

```python
        self.workers_file = self.drive_dir / "workers.json"
        self.jobs_dir = self.drive_dir / "jobs"
        self.rehome_file = self.drive_dir / "rehome.json"  # 다시 묶기로 끝난 관제 터미널(11단계 보강, 설계 8.13)
```

**Edit** `herdr-team/lib/hteam/queue.py`

```python
def _request_files(p) -> list:
    if not p.queue_dir.is_dir():
        return []
    return sorted((f for f in p.queue_dir.iterdir() if REQUEST_RE.match(f.name)), key=lambda f: f.name)
```

```python
def _request_files(p) -> list:
    if not p.queue_dir.is_dir():
        return []
    return sorted((f for f in p.queue_dir.iterdir() if REQUEST_RE.match(f.name)), key=lambda f: f.name)


def waiting(p) -> bool:
    """결과 없는 요청 파일이 있다(관제가 아직 실행하지 않았거나 review_busy 로 미뤘다). 관제 다시 묶기의 한가함(설계 8.13)."""
    return any(not _result_path(f).exists() for f in _request_files(p))
```

**Edit** `herdr-team/lib/hteam/outbox.py`

```python
from .errors import CONFLICT, DENIED, FAIL, USAGE, HteamError
```

```python
from .errors import CONFLICT, DENIED, FAIL, MISSING, USAGE, HteamError
```

**Edit** `herdr-team/lib/hteam/outbox.py`

```python
    return value if isinstance(value, str) and MAIN_PARENT_RE.fullmatch(value) else None
```

```python
    return value if isinstance(value, str) and MAIN_PARENT_RE.fullmatch(value) else None


def moved_main(p, parent: str | None, space: str | None) -> str | None:
    """메인이 바뀐 뒤 다시 묶을 주소(설계 8.13 확인의 2–4, 5.9.7 의 4 11단계 보강). main_parent 가 주소 M 이고, M 이 parent(없으면
    null)와 다르고, hc get M(3초)이 성공해 state 가 live 이고 그 address 가 parent 와 다르고(같은 터미널을 다른 꼴로 적은 경우),
    라벨 herdr.space 가 space 와 같으면 M. 하나라도 아니거나 hc 로 확인하지 못하면 None(끝났거나 지운 메인, 이 기계의 hc 가
    모르는 주소, 다른 space 의 메인 아래로는 다시 묶지 않는다). M 이 parent 와 같으면 hc 를 부르지 않는다."""
    main = main_parent(p)
    if main is None or main == parent or not space:
        return None
    try:
        info = herdr.get(main, timeout=3)
    except HteamError as exc:
        if exc.exit_code == MISSING:
            raise
        return None
    labels = info.get("labels") if isinstance(info.get("labels"), dict) else {}
    address = info.get("address")
    if info.get("state") != "live" or not address or address == parent or labels.get("herdr.space") != space:
        return None
    return main
```

**Edit** `herdr-team/lib/hteam/herdr.py`

```python
리뷰 보기 pane(6.5: hc run 의 hc attach(11단계), pane.close, 보기 터미널 hc rm)뿐이다. 워커 실행은 늘 horch 를 거친다."""
```

```python
리뷰 보기 pane(6.5: hc run 의 hc attach(11단계), pane.close, 보기 터미널 hc rm), 11단계 보강의 다시 묶기(8.13·5.9.7: parent·메인
확인의 get, 다시 묶기로 끝난 관제 터미널의 pane.close·hc rm)뿐이다. 워커 실행은 늘 horch 를 거친다."""
```

- [ ] **Step 4: 관제(drive.py)**

**Edit** `herdr-team/lib/hteam/drive.py`

```python
만드는 태스크와 중복 방지(8.9), 끝나지 않은 일괄 승인 결정 이어 하기와 답 파일에만 있는 결정 실행(7.4·11.4, 8.7 의 7).
"""
```

```python
만드는 태스크와 중복 방지(8.9), 끝나지 않은 일괄 승인 결정 이어 하기와 답 파일에만 있는 결정 실행(7.4·11.4, 8.7 의 7).
11단계 보강(8.13): 메인이 바뀐 뒤 다시 묶기(자기 parent 기억, 틱 10 의 확인과 한가할 때 끝내기, 다시 뜬 뒤 앞 관제 터미널 정리).
"""
```

**Edit** `herdr-team/lib/hteam/drive.py`

```python
BIND_TRIES = 3  # Run 연결 재시도
BIND_RETRY_S = 5.0
```

```python
BIND_TRIES = 3  # Run 연결 재시도
BIND_RETRY_S = 5.0
REHOME_CHECK_S = 60  # 다시 묶기 확인 간격(11단계 보강, 설계 8.13)
REHOME_MIN_UP_S = 600  # Run 에 묶인 뒤 다시 묶지 않는 시간(되풀이 막기. 자동 부활의 RETRY_WINDOW_S 와 같다, 8.13)
```

**Edit** `herdr-team/lib/hteam/drive.py`

```python
TITLE = "herdr-team 관제"  # 관제 탭 이름과 관제 pane 제목(8.2 의 5)
```

```python
TITLE = "herdr-team 관제"  # 관제 탭 이름과 관제 pane 제목(8.2 의 5)

# 다시 묶기(11단계 보강, 설계 8.13·8.11 원문)
REHOME_DECIDED = "관제 다시 묶기: 메인이 {main} 로 바뀌었다(관제 parent {parent}). 한가하고 watch 가 돌 때 끝낸다"
REHOME_PROGRESS = ("관제를 새 메인 터미널({main}) 아래로 다시 띄우려고 끝냈다. watch 가 orphaned 로 끝나면 /herdr-team:up 으로 "
                   "다시 띄운다. 도는 워커는 그대로다")
```

**Edit** `herdr-team/lib/hteam/drive.py`

```python
        self.pending_marks: dict[str, tuple[str, int]] = {}  # 리뷰 자식이 도는 태스크의 미룬 decide 표시(out id, 라운드)
```

```python
        self.pending_marks: dict[str, tuple[str, int]] = {}  # 리뷰 자식이 도는 태스크의 미룬 decide 표시(out id, 라운드)
        # 다시 묶기(11단계 보강, 설계 8.13). terminal 은 자기 터미널($HC_TERMINAL_ID), parent 는 Run 연결의 hc get 이 읽은 자기
        # parent(parent_known 이 False 면 모름), bound_at 은 Run 에 묶인 monotonic 시각(None 이면 Run 에 묶이지 않은 관제 객체)
        self.terminal: str | None = os.environ.get("HC_TERMINAL_ID", "").strip() or None
        self.parent: str | None = None
        self.parent_known = False
        self.bound_at: float | None = None
        self.last_rehome: float | None = None  # 마지막 확인(monotonic). 처음은 None(첫 틱이 확인한다)
        self.rehome_seen: str | None = None  # 지난 확인의 후보
        self.rehome_to: str | None = None  # 정한 새 메인(같은 후보를 두 번 연달아 봤다)
        self.mail_quiet = False  # 이번 틱의 메일 확인이 성공했고 메시지가 없었다(한가함 (1))
```

**Edit** `herdr-team/lib/hteam/drive.py`

```python
        ms = int(env_float("HTEAM_DRIVE_WAIT_MS", WAIT_MS))
        args = ["check", "--wait", "--timeout-ms", str(ms)]
```

```python
        self.mail_quiet = False  # 다시 묶기의 한가함(8.13): 확인이 성공했고 메시지가 없을 때만 참
        ms = int(env_float("HTEAM_DRIVE_WAIT_MS", WAIT_MS))
        args = ["check", "--wait", "--timeout-ms", str(ms)]
```

**Edit** `herdr-team/lib/hteam/drive.py`

```python
        self._ack = None if held else delivery
```

```python
        self._ack = None if held else delivery
        self.mail_quiet = not data.get("messages")  # ack 할 묶음도 미룬 메시지도 없다(앞 묶음은 이번 --ack 로 확인됐다)
```

**Edit** `herdr-team/lib/hteam/drive.py`

```python
    def tick(self) -> None:
        """설계 8.5 의 틱 순서. 단계마다 격리한다(reap_jobs·reset_step·view_step 은 그 안에서 항목마다). 거둔 뒤 Redmine 전송
        자식을 띄운다(설계 8.8·8.12)."""
```

```python
    def tick(self) -> bool:
        """설계 8.5 의 틱 순서. 단계마다 격리한다(reap_jobs·reset_step·view_step 은 그 안에서 항목마다). 거둔 뒤 Redmine 전송
        자식을 띄운다(설계 8.8·8.12). 끝의 틱 10 은 다시 묶기(8.13)이고, 다시 묶기로 끝낼 때만 True 다(관제 루프가 끝난다)."""
```

**Edit** `herdr-team/lib/hteam/drive.py`

```python
        if self.last_reconcile is None or time.monotonic() - self.last_reconcile >= RECONCILE_S:
            self.last_reconcile = time.monotonic()
            self.isolated("reconcile", self.reconcile)
```

```python
        if self.last_reconcile is None or time.monotonic() - self.last_reconcile >= RECONCILE_S:
            self.last_reconcile = time.monotonic()
            self.isolated("reconcile", self.reconcile)
        return self.isolated("rehome", self.rehome_step) is True

    # --- 다시 묶기(11단계 보강, 8.13) ---
    def rehome_step(self) -> bool:
        """틱 10(설계 8.13): REHOME_CHECK_S 마다 후보를 보고, 같은 M 이 두 번 연달아 후보면 다시 묶기로 정한다(로그 한 줄).
        정했으면 틱 끝마다 main_parent 가 아직 M 이고 한가하고 메인 watch 가 돌 때 끝낸다(rehome.json·progress·로그 뒤 True:
        관제가 exit 0 으로 끝난다). 계속 바쁘거나 watch 가 없으면 기다리기만 한다(상한 없음). Run 에 묶이지 않은 관제 객체
        (bound_at 없음)는 아무것도 하지 않는다."""
        if self.bound_at is None:
            return False
        every = env_float("HTEAM_REHOME_CHECK_S", REHOME_CHECK_S)
        if self.last_rehome is None or time.monotonic() - self.last_rehome >= every:
            self.last_rehome = time.monotonic()
            found = self._rehome_candidate()
            if found is None:
                self.rehome_seen = self.rehome_to = None
            elif found != self.rehome_seen:  # 처음 보거나 바뀌었다(메인을 넘겨받는 중): 다시 센다
                self.rehome_seen, self.rehome_to = found, None
            elif self.rehome_to is None:
                self.rehome_to = found
                self.log(REHOME_DECIDED.format(main=found, parent=self.parent or "없음"))
        if self.rehome_to is None:
            return False
        if outbox.main_parent(self.p) != self.rehome_to:  # 정한 뒤 메인이 또 바뀌었다: 확인부터 다시 한다
            self.rehome_seen = self.rehome_to = None
            return False
        if not self._quiet() or not outbox.watch_alive(self.p):
            return False
        return self._rehome_exit(self.rehome_to)

    def _rehome_candidate(self) -> str | None:
        """다시 묶기 확인(8.13 의 1–4): Run 에 묶인 지 REHOME_MIN_UP_S 가 지났고, main_parent 가 주소 M 이고, 자기 parent 를
        알고 M 이 그것과 다르고, hc get M 이 같은 space 의 산 터미널이면 M(outbox.moved_main). 아니면 None. M 이 parent 와
        같으면 hc 를 부르지 않는다(run.json 만 읽는다). 자기 parent 를 모르면 hc get(3초)으로 한 번 읽는다."""
        up = time.monotonic() - self.bound_at if self.bound_at is not None else None
        if up is None or up < env_float("HTEAM_REHOME_MIN_UP_S", REHOME_MIN_UP_S):
            return None
        main = outbox.main_parent(self.p)
        if main is None or (self.parent_known and main == self.parent):
            return None
        if not self.parent_known and not self._read_parent():
            return None
        return outbox.moved_main(self.p, self.parent, outbox._run(self.p).get("team_space"))

    def _read_parent(self) -> bool:
        """자기 parent 를 hc get(3초)으로 읽는다(Run 연결의 hc get 이 실패했다). parent 는 띄울 때만 정해지므로 읽으면 다시
        읽지 않는다. 읽었으면 True."""
        if not self.terminal:
            return False
        try:
            info = herdr.get(self.terminal, timeout=3)
        except HteamError as exc:
            if exc.exit_code == MISSING:
                raise
            return False
        self.parent, self.parent_known = outbox._parent_ref(info.get("parent")), True
        return True

    def _quiet(self) -> bool:
        """한가함(8.13 끝내기의 (1)–(4)): 이번 틱의 메일 확인이 성공했고 메시지가 없었다, 결과 없는 요청 파일이 없다, 도는
        자식(8.8)과 미룬 리뷰(8.7 의 4)가 없다, 리셋 중인(resetting) 고정 에이전트가 없다. 도는 워커·리뷰어·보기 pane 은 보지
        않는다(옮기지 않는다. 그 메시지는 Run 메일함에 남아 새 관제가 받는다)."""
        from . import crew, queue  # 둘 다 이 모듈을 쓴다
        if not self.mail_quiet or self.jobs or self.retry_reviews or queue.waiting(self.p):
            return False
        return not any(isinstance(e, dict) and e.get("resetting") for e in crew.load(self.p).values())

    def _rehome_exit(self, main: str) -> bool:
        """끝내기 차례(8.13): rehome.json(새 관제가 앞 관제 터미널을 정리한다) → progress → 로그. 기록이나 progress 를 쓰지
        못해도 끝낸다(watch 는 orphaned 로 안다. rehome.json 이 없으면 앞 터미널은 9.3 의 6 대로 관제 탭에 남는다)."""
        try:
            write_json(self.p.rehome_file, {"at": now(), "terminal": self.terminal, "parent": self.parent, "main": main})
        except OSError as exc:
            self.log(f"rehome.json 을 쓰지 못했다: {exc}. 앞 관제 터미널은 관제 탭에 남는다")
        try:
            self.progress(REHOME_PROGRESS.format(main=main))
        except Exception as exc:  # noqa: BLE001  watch 는 orphaned 로 안다
            self.log(f"다시 묶기 progress 를 쓰지 못했다: {type(exc).__name__}: {exc}")
        self.log(f"관제 종료: rehome: {self.parent or '없음'} → {main}")
        return True
```

**Edit** `herdr-team/lib/hteam/drive.py`

```python
        try:
            argv = herdr.get(term).get("argv")
        except HteamError:
            argv = None
```

```python
        try:
            info = herdr.get(term)
        except HteamError:
            info = None
        argv = info.get("argv") if info is not None else None
        if info is not None:  # 11단계 보강(8.13): 같은 hc get 의 parent 를 자기 parent 로 기억한다(읽지 못하면 모름)
            d.parent, d.parent_known = outbox._parent_ref(info.get("parent")), True
```

**Edit** `herdr-team/lib/hteam/drive.py`

```python
def _hangup(*_) -> None:
    raise SystemExit(129)
```

```python
def _tidy_rehome(p, d: Drive, term: str) -> None:
    """다시 뜬 관제(설계 8.13 의 "다시 뜬 뒤", 8.2 의 6): rehome.json 의 앞 관제 터미널이 자기 터미널이 아니면 정리하고 로그
    `앞 관제 터미널 <t> 정리: removed|gone|left(<까닭>)` 한 줄. run.json 의 drive_terminal 은 up 이 새 주소로 바꿨으므로 앞
    관제는 이 파일로만 안다. 어느 쪽이든 파일을 지운다(한 번만 본다. 지우기 전에 죽으면 다음 관제가 같은 일을 한다, 멱등).
    파일이 없으면(관제가 죽었다 다시 떴다) 아무것도 하지 않는다. 죽어서 남은 관제 터미널은 지우지 않는다(9.3 의 6)."""
    if not p.rehome_file.exists():
        return
    rec = read_json(p.rehome_file, None)
    old = rec.get("terminal") if isinstance(rec, dict) else None
    if isinstance(old, str) and old.strip() and old != term:
        d.log(f"앞 관제 터미널 {old} 정리: {_remove_drive_terminal(old)}")
    p.rehome_file.unlink(missing_ok=True)


def _remove_drive_terminal(terminal: str) -> str:
    """다시 묶기로 끝난 관제 터미널 지우기: hc get(3초)이 finished 이고 라벨 hteam.role=drive 면 pane 이 있으면(pane_of)
    pane.close, 그다음 hc rm(6.5 의 3 과 같은 순서). removed, 이미 없으면(not_found) gone. live(Herdr 재시작 뒤 --keep 이 셸로
    바꿈 등)·라벨 없음·hc 실패·닫기나 rm 실패는 지우지 않고 left(<까닭>)."""
    try:
        info = herdr.get(terminal, timeout=3)
    except HteamError as exc:
        if exc.exit_code == MISSING:
            raise
        return "gone" if exc.data.get("kind") == "not_found" else f"left({exc.message})"
    if info.get("state") != "finished":
        return f"left({info.get('state') or '상태 모름'})"
    labels = info.get("labels") if isinstance(info.get("labels"), dict) else {}
    if labels.get("hteam.role") != "drive":
        return "left(관제 라벨 없음)"
    try:
        pane = herdr.pane_of(terminal)  # 앱 조회 실패도 None: pane 이 없다고 보고 hc rm 한다(6.5 의 보기 닫기와 같다, 13장)
        if pane:
            herdr.close_pane(pane)
        herdr.rm(terminal)
    except HteamError as exc:
        if exc.exit_code == MISSING:
            raise
        return f"left({exc.message})"
    return "removed"


def _hangup(*_) -> None:
    raise SystemExit(129)
```

**Edit** `herdr-team/lib/hteam/drive.py`

```python
    """설계 8.2 의 시작 순서. HTEAM_DRIVE_TICKS(시험)가 있으면 그만큼 틱을 돈 뒤 끝낸다."""
```

```python
    """설계 8.2 의 시작 순서. HTEAM_DRIVE_TICKS(시험)가 있으면 그만큼 틱을 돈 뒤 끝낸다. 다시 묶기(8.13)로 끝내면 결과에
    rehome(새 메인 주소)을 담고 exit 0 이다(로그는 rehome_step 이 남겼다)."""
```

**Edit** `herdr-team/lib/hteam/drive.py`

```python
        mode, run_id = _connect(p, d, term, nonce)
```

```python
        mode, run_id = _connect(p, d, term, nonce)
        d.bound_at = time.monotonic()  # 다시 묶기 확인의 1(Run 에 묶인 지 REHOME_MIN_UP_S, 8.13)
```

**Edit** `herdr-team/lib/hteam/drive.py`

```python
        d.log(f"관제 시작({term}): {mode}")
        d.last_reconcile = time.monotonic()
```

```python
        d.log(f"관제 시작({term}): {mode}")
        d.isolated("rehome", lambda: _tidy_rehome(p, d, term))  # 다시 묶기로 끝난 앞 관제 터미널(8.13, 시작 재확인 전)
        d.last_reconcile = time.monotonic()
```

**Edit** `herdr-team/lib/hteam/drive.py`

```python
        while True:
            d.tick()
            ticks += 1
```

```python
        while True:
            ended = d.tick()
            ticks += 1
            if ended:  # 11단계 보강(8.13): 다시 묶기로 끝낸다. finally 가 drive.pid 를 지운다(8.2 의 7)
                return {"run_id": run_id, "mode": mode, "ticks": ticks, "rehome": d.rehome_to}
```

- [ ] **Step 5: 시험이 통과하는지 본다**

Run: `(cd herdr-team && python3 -m py_compile lib/hteam/drive.py lib/hteam/outbox.py lib/hteam/queue.py lib/hteam/paths.py lib/hteam/herdr.py tests/helpers.py && python3 -m unittest tests.test_drive tests.test_setup tests.test_mainlink tests.test_autoup tests.test_queue tests.test_drive_flows tests.test_drive_events tests.test_crew_reset)`
Expected: PASS. 틱에 단계를 더했으므로 관제 흐름 시험(`test_drive_flows`·`test_drive_events`)과 리셋 시험도 함께 본다.

- [ ] **Step 6: 커밋**

```bash
git add herdr-team/lib/hteam/drive.py herdr-team/lib/hteam/outbox.py herdr-team/lib/hteam/queue.py \
  herdr-team/lib/hteam/paths.py herdr-team/lib/hteam/herdr.py herdr-team/tests/helpers.py herdr-team/tests/test_drive.py \
  herdr-team/tests/test_setup.py herdr-team/tests/test_mainlink.py herdr-team/tests/test_autoup.py
git commit -m "feat(herdr-team): 관제 다시 묶기 — 메인이 바뀌면 한가할 때 끝나 새 메인 아래 다시 뜬다(설계 8.13)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/lib/hteam/drive.py herdr-team/lib/hteam/outbox.py \
  herdr-team/lib/hteam/queue.py herdr-team/lib/hteam/paths.py herdr-team/lib/hteam/herdr.py herdr-team/tests/helpers.py \
  herdr-team/tests/test_drive.py herdr-team/tests/test_setup.py herdr-team/tests/test_mainlink.py \
  herdr-team/tests/test_autoup.py
```

그 뒤 `scripts/codex-review.sh commit <sha>`(Global Constraints).

---

### Task 2: 고정 에이전트 리셋 때 새 터미널 (설계 5.9.7 의 4, 5.9.1)

**Files:**
- Modify: `herdr-team/lib/hteam/crew.py:633-635`(`_clear` 앞에 `_parent_changed`, `_clear` 설명), `:642`(첫 시도 앞의 다시 묶기 갈래), `:666-667`(닫기 실패)
- Test: `herdr-team/tests/test_crew_reset.py`(끝에 `RehomeResetTest`)

**Interfaces:**
- Consumes: `outbox.moved_main`(Task 1), `outbox.main_parent`, `outbox._parent_ref`, `herdr.get`.
- Produces: `crew._parent_changed(p, e: dict) -> bool`. crew.json 의 `resetting.clear_error = "parent_changed"`, `resetting.rehome = "failed"`.

**Rules:**
- 다시 묶기 확인은 clear 단계의 첫 시도에서만 한다: `close_failures == 0`, `clear_error` 없음, `rehome` 없음. 차례는 `main_parent`(None 이면 hc 를 부르지 않는다) → `hc get <작업 터미널>`(3초) → `moved_main(p, 그 parent, entry 의 space)`.
- 맞으면 `clear_error = "parent_changed"` 를 먼저 쓰고 지금의 닫기(`horch terminal-close --terminal <t>`, `--abandon` 없음)로 간다. 성공하면 `_reset_done(new_terminal(parent_changed), terminal·terminal_argv·work_pane = null)`.
- `parent_changed` 닫기가 실패하면(첫 시도든, 다시 뜬 관제가 남은 `clear_error` 로 잇든) `clear_error` 를 지우고 `rehome = "failed"` 를 쓴다. `close_failures` 는 세지 않는다. 그 뒤의 리셋 단계는 parent 를 보지 않고 `terminal-reset` 이다. 인수인계 worker_done 을 틱 2 의 메일 확인이 처리해 닫기가 실패했으면 같은 틱의 리셋 단계(틱 7)가 곧바로 하고, 리셋 단계나 재확인(`handoff_check`)에서 실패했으면 다음 틱이다. 실패한 틱을 건너뛰지 않는다: 닫지 못한 터미널을 비우는 것은 지금의 제자리 비우기와 같아 기다릴 까닭이 없다(Codex 계획 리뷰 r1). 그 비우기가 실패하면 지금의 닫기 세 번 규칙이다.
- hc 실패·M 이 live 아님·다른 space·같은 parent 면 지금처럼 `terminal-reset` 이다(묶음은 리셋을 막지 않는다). 다음 태스크의 새 세션·탭 이름·배치·인수인계 줄은 지금 코드(5.9.2, 5.5 의 7)가 한다.

- [ ] **Step 1: 시험 쓰기**

**Edit** `herdr-team/tests/test_crew_reset.py`

```python
        self.assertNotEqual(self.work_dispatch("T-002"), first)  # 다시 넣었다
```

```python
        self.assertNotEqual(self.work_dispatch("T-002"), first)  # 다시 넣었다


import contextlib  # noqa: E402  (11단계 보강의 시험 도구)
import re  # noqa: E402
import time  # noqa: E402

from tests.test_crew import HANDOFF_LINE  # noqa: E402
from hteam import herdr  # noqa: E402


class RehomeResetTest(ResetCase):
    """11단계 보강(설계 5.9.7 의 4, 15.1): 메인이 바뀌었으면(작업 터미널 parent ≠ main_terminal M, M 은 같은 space 의 산
    터미널) 리셋의 clear 단계가 같은 터미널을 비우지 않고 닫는다. 다음 태스크가 새 메인 아래 새 세션으로 띄우고 인수인계
    파일을 읽는다. self.t 는 main_terminal 없이 띄운 세션(parent 없음, 0.7.0 에서 띄운 세션과 같다)이다."""

    def setUp(self):
        super().setUp()
        self.set_run(main_terminal=MAIN)

    def horch_args(self, run) -> list[list[str]]:
        """관제 객체로 run(d) 를 하고 그동안 horch 에 넘긴 인자를 돌려준다."""
        seen = []
        with self.in_drive():
            d = self.make_drive()
            real = d.horch().call

            def spy(*args, **kw):
                seen.append(list(args))
                return real(*args, **kw)

            with mock.patch.object(d.horch(), "call", side_effect=spy):
                run(d)
        return seen

    def finish_handoff(self, n=1, get=None) -> list[list[str]]:
        """리셋 표시 → 인수인계 → 워커가 인수인계 n 을 커밋하고 done → 관제가 worker_done 을 처리한다(clear 단계). get 이
        있으면 worker_done 처리 동안 hteam 의 hc get(herdr.get)을 그것으로 바꾼다(horch 는 그대로). horch 인자를 돌려준다."""
        self.mark()
        self.step()
        did = self.handoff_did()
        code, out = self.act(did, {"write": {"docs/handoff/production.md": f"# 결정 {n}\n"},
                                   "commit": "[handoff] production: 인수인계",
                                   "done": {"outcome": "succeeded", "summary": "썼다"}})
        self.assertEqual(code, 0, out)
        msg = self.message("worker_done", did, self.done_body(did))
        with mock.patch.object(herdr, "get", side_effect=get) if get else contextlib.nullcontext():
            return self.horch_args(lambda d: d.handle(msg))

    @staticmethod
    def calls_of(args, word) -> list[list[str]]:
        return [a for a in args if a[:1] == [word]]

    def test_parent_changed_closes_and_next_task_opens_under_main(self):
        args = self.finish_handoff()
        self.assertEqual(self.calls_of(args, "terminal-close"), [["terminal-close", "--terminal", self.t]])  # --abandon 없이
        self.assertEqual(self.calls_of(args, "terminal-reset"), [])
        self.assertEqual(self.keys(), [])  # /clear 를 치지 않았다
        e = self.entry()
        self.assertEqual((e["terminal"], e["terminal_argv"], e["work_pane"], e["resetting"], e["reset_pending"],
                          e["since_reset"], e["reset_tasks"]), (None, None, None, None, False, 0, []))
        self.assertRegex(e["last_reset_at"], r"[+-]\d\d:\d\d$")
        self.assertNotIn(self.t, self.terminals())  # terminal-close 가 끄고 지웠다
        self.assertTrue(any("production 리셋: new_terminal(parent_changed)" in x for x in self.log_lines()),
                        self.log_lines())
        out = self.started("T-002")  # 다음 태스크가 5.9.2 로 새 세션을 띄운다
        new = out["terminal"]
        self.assertNotEqual(new, self.t)
        info = self.terminals()[new]
        self.assertEqual((info["parent"], "--outlive-parent" in info["flags"], info["labels"]["herdr.tab"]),
                         (MAIN, True, self.tab()))
        self.assertIn(HANDOFF_LINE, (self.state_dir / "tasks/T-002/r1-work.md").read_text(encoding="utf-8"))  # 5.5 의 7
        self.assertEqual(self.entry()["terminal"], new)
        # 메인이 또 옮겼다: parent 가 있는 세션도 다음 리셋이 새 터미널로 띄운다
        self.work("T-002")
        self.free("T-002")
        self.ready(new)
        self.add_terminal("t5", argv=["claude"], labels={"herdr.space": "spA", "herdr.tab": "tbMain5"}, status="idle")
        self.set_run(main_terminal="t5")
        args = self.finish_handoff(2)
        self.assertEqual(self.calls_of(args, "terminal-close"), [["terminal-close", "--terminal", new]])
        self.assertIsNone(self.entry()["terminal"])
        self.assertEqual(len([x for x in self.log_lines() if "production 리셋: new_terminal(parent_changed)" in x]), 2)

    def test_same_parent_or_unverifiable_main_clears_in_place(self):
        real = herdr.get

        def work_get_fails(terminal, timeout=10):
            if terminal == self.t:
                raise HteamError("hc_timeout", "hc get 가 3초 안에 끝나지 않았다", 1)
            return real(terminal, timeout=timeout)

        self.add_terminal("t50", argv=["claude"], state="finished", labels={"herdr.space": "spA", "herdr.tab": "tbM"})
        self.add_terminal("t51", argv=["claude"], labels={"herdr.space": "spB", "herdr.tab": "tbM"}, status="idle")
        self.add_terminal("t52", argv=["claude"], labels={"herdr.tab": "tbM"}, status="idle")
        self.add_terminal("t53", name="main-b", argv=["claude"], labels={"herdr.space": "spA", "herdr.tab": "tbM"},
                          status="idle")
        cases = (("같은 parent", MAIN, MAIN, None), ("작업 터미널 hc get 실패", MAIN, None, work_get_fails),
                 ("끝난 메인", "t50", None, None), ("지운 메인", "t404", None, None), ("다른 space", "t51", None, None),
                 ("space 라벨 없음", "t52", None, None), ("같은 터미널의 다른 이름", "main-b", "t53", None))
        for n, (why, main, parent, get) in enumerate(cases, start=1):
            with self.subTest(why=why):
                self.set_run(main_terminal=main)
                self.update_terminal(self.t, parent=parent)
                before = len(self.keys())
                args = self.finish_handoff(n, get)
                self.assertEqual(len(self.keys()), before + 1)  # /clear 로 같은 터미널을 비웠다(지금 그대로)
                self.assertEqual(self.calls_of(args, "terminal-close"), [])
                e = self.entry()
                self.assertEqual((e["terminal"], e["resetting"], e["reset_pending"]), (self.t, None, False))
        self.assertFalse(any("parent_changed" in x for x in self.log_lines()), self.log_lines())

    def test_close_failure_clears_the_same_terminal_in_the_same_tick(self):
        # 인수인계 worker_done 을 틱 2 의 메일 확인이 처리한다. 닫기가 실패해 rehome = failed 를 두면 같은 틱의 리셋 단계
        # (틱 7)가 parent 를 다시 보지 않고 같은 터미널을 비운다(실패한 틱을 건너뛰지 않는다. 리셋 단계나 재확인에서 실패했으면
        # 다음 틱이다). 틱 하나로 terminal-close 실패 → 같은 터미널 terminal-reset 순서를 본다
        self.env["HTEAM_DRIVE_WAIT_MS"] = "50"  # 빈 메일 확인을 짧게
        self.mark()
        self.step()
        self.fail_hc("kill", "timeout")  # terminal-close 가 실패한다
        gets, real = [], herdr.get

        def spy_get(terminal, timeout=10):
            gets.append(terminal)
            return real(terminal, timeout=timeout)

        def one_tick(d):
            with mock.patch.object(d, "handle"):  # 앞 단계의 메시지(T-001 의 worker_done 등)는 처리하지 않고 확인한다
                d.check_mail()
                d.check_mail()
            self.write_handoff()  # 인수인계 워커가 커밋하고 done 한다(Run 메일함에 worker_done)
            d.last_reconcile = time.monotonic()  # 이 틱에는 재확인이 돌지 않는다(worker_done 은 메일 확인이 처리한다)
            with mock.patch.object(herdr, "get", side_effect=spy_get):
                self.assertFalse(d.tick())

        args = self.horch_args(one_tick)
        self.assertEqual([a[:3] for a in args if a[:1] in (["terminal-close"], ["terminal-reset"])],
                         [["terminal-close", "--terminal", self.t], ["terminal-reset", "--terminal", self.t]])
        self.assertEqual(gets.count(self.t), 1)  # 작업 터미널 parent 는 첫 시도에서 한 번만 봤다
        e = self.entry()
        self.assertEqual((e["terminal"], e["resetting"], e["reset_pending"], e["close_failures"]),
                         (self.t, None, False, 0))
        self.assertEqual(self.keys(), [["/", "c", "l", "e", "a", "r", "enter"]])
        lines = self.log_lines()
        fail = next(i for i, x in enumerate(lines)
                    if re.search(r"production 리셋: 다시 묶기 닫기 실패\(.+\), 같은 터미널을 비운다$", x))
        self.assertTrue(any("production 리셋: reset(turn " in x for x in lines[fail + 1:]), lines)
        self.assertEqual(self.decides(), [])

    def test_reset_failure_after_the_close_failure_follows_the_close_rule(self):
        self.fail_hc("kill", "timeout")
        self.finish_handoff()
        self.on_clear("none")  # 같은 터미널 비우기도 turn 사건이 없다
        self.step()
        e = self.entry()
        self.assertEqual((e["resetting"]["clear_error"], e["resetting"]["rehome"], e["close_failures"], e["terminal"]),
                         ("reset_timeout", "failed", 1, self.t))  # 지금의 exit 4 갈래(닫기 세 번 뒤 decide)

    def test_resumed_parent_changed_closes_first(self):
        # clear_error = "parent_changed" 를 쓴 뒤 닫기 전에 관제가 죽었다. 다시 뜬 관제는 parent 를 다시 보지 않고 닫기부터
        # 한다(지금 규칙 그대로)
        self.mark()
        self.step()
        did = self.handoff_did()
        self.write_handoff()
        self.assertEqual(self.horch("worker-release", "--dispatch", did)[0], 0)
        self.set_entry(resetting={"step": "clear", "dispatch": did, "at": ago(5), "clear_error": "parent_changed"})
        with mock.patch.object(herdr, "get", wraps=herdr.get) as get:
            self.step()
        get.assert_not_called()
        e = self.entry()
        self.assertEqual((e["terminal"], e["resetting"], e["reset_pending"]), (None, None, False))
        self.assertEqual(self.keys(), [])
        self.assertTrue(any("production 리셋: new_terminal(parent_changed)" in x for x in self.log_lines()),
                        self.log_lines())
```

- [ ] **Step 2: 시험이 실패하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_crew_reset.RehomeResetTest)`
Expected: FAIL(`test_parent_changed_closes_and_next_task_opens_under_main`·`test_close_failure_…`·`test_reset_failure_after_…`: 지금은 /clear 로 같은 터미널을 비운다). `test_same_parent_…` 와 `test_resumed_parent_changed_closes_first` 는 지금 동작을 고정하는 시험이라 지금도 통과한다.

- [ ] **Step 3: crew.py**

**Edit** `herdr-team/lib/hteam/crew.py`

```python
def _clear(d, name: str) -> None:
    """비우기와 닫기 재시도(clear 단계, 어디서 죽어도 이어 한다). 비우기 신호가 없거나 실패하면 비웠다고 믿지 않고 터미널을
    닫는다(다음 태스크가 새 세션을 띄운다). 닫지 못하면 다음 틱에 닫기만 다시 하고, 세 번째면 decide 뒤 터미널을 잊는다."""
```

```python
def _parent_changed(p, e: dict) -> bool:
    """리셋의 다시 묶기(설계 5.9.7 의 4, 11단계 보강): main_parent 가 주소 M 이고, 작업 터미널의 parent(hc get 3초, 없으면
    null)가 M 이 아니고, hc get M 이 entry 의 space 에 산 터미널이다(outbox.moved_main, 8.13 의 확인 4 와 같은 규칙). 하나라도
    아니거나 hc 로 확인하지 못하면 False(지금처럼 같은 터미널을 비운다. 묶음은 보기 위한 것이라 리셋을 막지 않는다)."""
    if outbox.main_parent(p) is None:
        return False
    try:
        info = herdr.get(e["terminal"], timeout=3)
    except HteamError as exc:
        if exc.exit_code == MISSING:
            raise
        return False
    return outbox.moved_main(p, outbox._parent_ref(info.get("parent")), e["space"]) is not None


def _clear(d, name: str) -> None:
    """비우기와 닫기 재시도(clear 단계, 어디서 죽어도 이어 한다). 비우기 신호가 없거나 실패하면 비웠다고 믿지 않고 터미널을
    닫는다(다음 태스크가 새 세션을 띄운다). 닫지 못하면 다음 틱에 닫기만 다시 하고, 세 번째면 decide 뒤 터미널을 잊는다.
    11단계 보강(5.9.7 의 4): 첫 시도에서 메인이 바뀌었으면(_parent_changed) 비우지 않고 닫는다(parent_changed). 그 닫기가
    실패하면 rehome = failed 로 두고, 그 뒤의 리셋 단계(같은 틱의 틱 7 이나 다음 틱)가 parent 를 보지 않고 같은 터미널을
    비운다."""
```

**Edit** `herdr-team/lib/hteam/crew.py`

```python
    if e["close_failures"] == 0 and reason is None:  # 아직 비우기를 하지 않았다
```

```python
    if e["close_failures"] == 0 and reason is None and not res.get("rehome") and _parent_changed(p, e):
        # 메인이 바뀌었다: 비우지 않고 닫아 다음 태스크가 새 메인 아래 새 세션으로 띄운다(인수인계 파일은 그대로 읽는다)
        reason = "parent_changed"
        res = {**res, "clear_error": reason}
        _set(p, name, resetting=res)  # 닫기 전에 죽으면 다시 뜬 관제가 닫기부터 한다
    if e["close_failures"] == 0 and reason is None:  # 아직 비우기를 하지 않았다
```

**Edit** `herdr-team/lib/hteam/crew.py`

```python
        return _reset_done(d, name, f"new_terminal({reason})", terminal=None, terminal_argv=None, work_pane=None)
    n = e["close_failures"] + 1
```

```python
        return _reset_done(d, name, f"new_terminal({reason})", terminal=None, terminal_argv=None, work_pane=None)
    if reason == "parent_changed":  # 다시 묶기의 닫기는 되풀이하지 않는다: 그 뒤의 리셋 단계가 parent 를 보지 않고 비운다
        err = data.get("error") or {}
        _set(p, name, resetting={**{k: v for k, v in res.items() if k != "clear_error"}, "rehome": "failed"})
        d.log(f"{name} 리셋: 다시 묶기 닫기 실패({err.get('code') or f'exit_{code}'}), 같은 터미널을 비운다")
        return None
    n = e["close_failures"] + 1
```

- [ ] **Step 4: 시험이 통과하는지 본다**

Run: `(cd herdr-team && python3 -m py_compile lib/hteam/crew.py && python3 -m unittest tests.test_crew_reset tests.test_crew tests.test_drive)`
Expected: PASS. 기존 리셋 시험(`main_terminal` 없음)은 그대로 같은 터미널을 비운다.

- [ ] **Step 5: 커밋**

```bash
git add herdr-team/lib/hteam/crew.py herdr-team/tests/test_crew_reset.py
git commit -m "feat(herdr-team): 고정 에이전트 리셋 때 메인이 바뀌었으면 새 터미널로 띄운다(설계 5.9.7 의 4)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/lib/hteam/crew.py herdr-team/tests/test_crew_reset.py
```

그 뒤 `scripts/codex-review.sh commit <sha>`.

---

### Task 3: README (설계 9.6 의 11단계 (4)·(5))

**Files:**
- Modify: `README.md:166`(Herdr 묶음 줄), `:276`(자동 부활 한계 줄), "#### 0.7.0 → 0.7.1" 의 "올린 뒤 달라지는 것"
- Test: `herdr-team/tests/test_setup.py`(`TemplateContractTest.test_new_main_session_after_init_and_upgrade` 의 README 줄)

**Rules:**
- 업그레이드 절 (4)·(5) 는 설계 9.6 의 11단계 줄 그대로다: 살아 있던 고정 에이전트 작업 터미널은 다음 리셋이 새 터미널로 띄울 때까지(lost 도 같다) 맨 위에 남고, 바로 묶으려면 `hteam agent reset <이름>`. 메인을 옮기면 관제가 10분·한가함·watch 조건으로 끝나 `/herdr-team:up` 으로 다시 뜨고, 고정 에이전트는 다음 리셋 때 새 터미널로 뜬다. 같은 터미널에서 `/exit` 뒤 다시 열면 그대로다. 같은 폴더에 Claude 세션이 둘이면 나중에 watch 를 띄운 세션이 메인이 된다(메인 세션은 하나만 연다).
- 업그레이드 순서 1–6 과 앞 버전 절은 바꾸지 않는다. 버전 표·버전 파일은 이미 0.7.1 이다. `CLAUDE.section.md`·`hteam upgrade` 의 `next` 는 바꾸지 않는다(7.7 의 11단계 문단 끝).

- [ ] **Step 1: 시험 쓰기**

**Edit** `herdr-team/tests/test_setup.py`

```python
                       "맨 위에 남는다"):
            self.assertIn(needle, p11)
```

```python
                       "맨 위에 남는다", "`hteam agent reset <이름>`", "10분", "`/herdr-team:up`",
                       "다음 리셋 때 새 터미널로 뜬다", "나중에 watch 를 띄운 세션이 메인이 된다"):  # (4)·(5): 11단계 보강
            self.assertIn(needle, p11)
```

**Edit** `herdr-team/tests/test_setup.py`

```python
        for needle in ("메인 세션 아래 한 단계로 보인다", "`main_terminal`", "`--outlive-parent`", "숨은 리뷰어"):
            self.assertIn(needle, team)
```

```python
        for needle in ("메인 세션 아래 한 단계로 보인다", "`main_terminal`", "`--outlive-parent`", "숨은 리뷰어",
                       "스스로 끝나 새 메인 아래 다시 뜬다", "다음 리셋 때 비우지 않고 새 터미널로 뜬다",
                       "다시 묶기로 끝난 것은 새 관제가 지운다"):  # 11단계 보강(설계 8.13·5.9.7)
            self.assertIn(needle, team)
```

- [ ] **Step 2: 시험이 실패하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_setup.TemplateContractTest)`
Expected: FAIL(README 에 다시 묶기 줄이 없다).

- [ ] **Step 3: README 를 고친다**

**Edit** `README.md`

```markdown
메인 세션을 새 터미널로 옮기면 그 세션의 첫 watch 뒤에 띄우는 터미널부터 새 메인 아래에 든다.
```

```markdown
메인 세션을 새 터미널로 옮기면 그 세션의 첫 watch 뒤에 띄우는 터미널부터 새 메인 아래에 든다. 이미 떠 있던 관제는 Run 에 묶인 지 10분이 지났고 한가하고 새 메인의 watch 가 돌 때 스스로 끝나 새 메인 아래 다시 뜬다(메인이 `/herdr-team:up` 으로 띄운다. 그사이 잠깐 관제가 꺼져 있다). 고정 에이전트 작업 터미널은 다음 리셋 때 비우지 않고 새 터미널로 뜬다(바로 묶으려면 `hteam agent reset <이름>`). 도는 임시 워커·리뷰어·리뷰 보기 pane 은 끝날 때까지 앞 메인 아래에 남는다. 같은 폴더에서 Claude 세션을 둘 열면 나중에 watch 를 띄운 세션이 메인이 된다(메인 세션은 하나만 연다).
```

**Edit** `README.md`

```markdown
죽은 관제 터미널은 관제 탭에 남는다.
```

```markdown
죽은 관제 터미널은 관제 탭에 남는다(다시 묶기로 끝난 것은 새 관제가 지운다).
```

**Edit** `README.md`

```markdown
- 업그레이드 전에 띄운 터미널은 맨 위에 남는다. 살아 있던 고정 에이전트 작업 터미널은 같은 터미널을 다시 쓰므로 그 터미널이 새로 생길 때까지(lost, 리셋이 새 터미널로 띄우는 길) 맨 위에 남는다.
```

```markdown
- 업그레이드 전에 띄운 터미널은 맨 위에 남는다. 살아 있던 고정 에이전트 작업 터미널은 parent 가 없어 다음 리셋이 새 터미널로 띄울 때까지(lost 도 같다) 맨 위에 남는다. 바로 묶으려면 메인에게 `hteam agent reset <이름>` 을 부탁한다.
- 메인을 다른 터미널로 옮기면(메인 탭을 닫고 다른 탭에서 다시 열기) 관제는 Run 에 묶인 지 10분이 지났고 한가하고 새 메인의 watch 가 돌 때 스스로 끝나고, 메인이 `/herdr-team:up` 으로 새 메인 아래 다시 띄운다(그사이 잠깐 "관제가 꺼져 있다" 가 보일 수 있다). 고정 에이전트는 다음 리셋 때 새 터미널로 뜬다. 같은 터미널에서 `/exit` 뒤 다시 열면 그대로다. 같은 폴더에서 Claude 세션을 둘 열면 나중에 watch 를 띄운 세션이 메인이 된다(알려진 동작. 메인 세션은 하나만 연다).
```

- [ ] **Step 4: 시험이 통과하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_setup tests.test_wording tests.test_cli)`
Expected: PASS.

- [ ] **Step 5: 전체 시험(백그라운드, 하나씩)**

Run: `bash herdr-team/tests/run.sh`(Bash `run_in_background: true`, 약 22분, 끝나면 알림을 받는다). 끝난 뒤 `bash herdr-orch/tests/run.sh`(herdr-orch 는 바뀌지 않았지만 같은 가짜 hc 를 쓰는 회귀 확인).
Expected: 둘 다 `OK`(skip 은 지금과 같은 것만). 실패는 고친 뒤 그 모듈만 다시 돌린다.

- [ ] **Step 6: 커밋**

```bash
git add README.md herdr-team/tests/test_setup.py
git commit -m "docs(herdr-team): README 다시 묶기 — 메인을 옮기면 관제·고정 에이전트가 새 메인 아래 다시 뜬다(설계 9.6)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- README.md herdr-team/tests/test_setup.py
```

그 뒤 `scripts/codex-review.sh commit <sha>`.

---

### Task 4: 브랜치 리뷰 (컨트롤러가 한다)

- [ ] **Step 1**: 최종 코드 리뷰(서브에이전트, `main...HEAD`. 11단계 본 구현과 보강을 함께 본다)로 설계 8.13·5.9.7 의 4·8.5 의 10·8.2 의 4·6·7·9.5 의 11단계 보강 문단이 구현과 맞는지 본다. 특히 본다:
  - 끝내기가 한가함 넷과 watch 를 모두 보는지, 정한 뒤 `main_parent` 가 바뀌면 지우는지, 계속 바쁠 때 관제가 그대로 일하는지(rehome_step 이 다른 단계를 막지 않는지).
  - exit 0 길에서 drive.pid 가 지워지고 `관제 종료: rehome:` 이 마지막 줄인지, 예외 길의 `관제 종료: <타입>` 과 겹치지 않는지.
  - 자동 부활이 다시 묶기로 끝난 관제를 FAILED 로 보지 않는지(`REHOME_MIN_UP_S ≥ RETRY_WINDOW_S`), `up` 이 `starting` 으로 막지 않는지.
  - `_tidy_rehome` 가 자기 터미널·죽어서 남은 관제(라벨은 있지만 rehome.json 에 없는 터미널)를 지우지 않는지.
  - 리셋의 `parent_changed` 닫기와 실패 길(`rehome = "failed"`)이 `close_failures`·decide 를 건드리지 않는지, 다시 뜬 관제가 남은 `clear_error` 를 잇는지.
  - hc 를 부르는 곳이 `herdr` 모듈 함수뿐인지(3.3), 확인마다 hc 호출이 많아야 둘인지.
- [ ] **Step 2**: `scripts/codex-review.sh base main`(`hc wait <주소> --timeout 3600` 백그라운드). 지적을 확인해 고치고 다시 돌린다(최대 3라운드, P0·P1 이 남지 않을 때까지). 고친 커밋마다 `scripts/codex-review.sh commit <sha>` 는 하지 않고 브랜치 리뷰 다음 라운드가 본다.

---

### Task 5: 실환경 2차와 기록 (설계 15.2 의 11단계 2차 7–10, 컨트롤러가 한다)

운영 규칙(1차 계획 Task 7 과 같다):
- 사용자 hc core 를 멈추거나 다시 띄우지 않는다(`server.stop`·`server.restart`, `hc server stop|restart`, `hc update` 금지). 새 `HC_SESSION`·XDG 상태 경로를 만들지 않는다.
- 시험 space 하나와 거기서 띄운 터미널만 쓴다. 시험의 `hc run` 은 늘 `--no-notify`. `hc kill`·`hc rm`·앱의 닫기(`tab.close`·`pane.close`)는 시험에서 띄운 터미널·pane·탭에만 한다. 사용자 터미널에 `hc send` 하지 않는다. 사용자 터미널을 parent 로 주지 않는다.
- 플러그인을 설치·업데이트하지 않고 전역 설정을 바꾸지 않는다. 시험 메인은 `claude --plugin-dir <저장소>/herdr-team --plugin-dir <저장소>/herdr-orch` 와 `DISABLE_AUTOUPDATER=1` 로 열고, 시험 메인 셸에 `HERDR_TEAM_PLUGIN_ROOT`·`HERDR_ORCH_BIN` 을 이 브랜치 경로로 넣는다.
- 워커 화면은 Claude 워커만 `hc read` 로 본다. Codex 터미널은 `hc get` 의 status 만 본다.
- 기록(설계 15.4)에는 개인 경로를 쓰지 않는다(`<저장소>`·`<시험 프로젝트>`). 단위 시험 전체 둘을 동시에 돌리지 않는다.

더하는 규칙(실환경 1차에서 배운 것):
- 시험 프로젝트 폴더에서 실험용 Claude 세션을 띄우지 않는다. 그 세션의 Stop 훅이 watch 를 띄워 메인을 가져간다(1차에서 실제로 일어났다, 설계 1장 11단계 확인한 것). 시험 메인 세션은 하나만 연다(Step 1 의 B 는 A 의 탭을 닫은 뒤에 연다). 상태는 시험 운영자 셸에서 `hteam status`·`hc get`·`herdr-app ls`·파일 읽기로 본다.
- 시험 워커의 `--settings` 파일에는 `HERDR_TEAM_PLUGIN_ROOT`·`HERDR_ORCH_BIN` 만 둔다. 자동 업데이트 끄기를 넣으면 Claude 가 hc 상태를 보고하지 않는다(1차에서 봤다).

시험 프로젝트: 1차와 같은 설정(고정 에이전트 하나 `[crew.production]` developer Claude, tester 는 Codex 임시 워커, `[test]` 없음). 새 버리는 저장소에 `hteam scaffold` 로 다시 만든다. 기획은 시험이 쓴 `docs/planning/`·`tasks.toml` 을 커밋해 건너뛴다. 실제 Claude·Codex 워커를 쓴다. 시험 운영자 커밋은 시험 프로젝트에 경로 지정으로 한다.

- [ ] **Step 1: 관제 다시 묶기(15.2 의 11단계 7)**: 시험 메인 A 에서 `/herdr-team:up` 뒤 고정 에이전트 태스크 하나와 임시 워커 태스크 하나를 돌린다(임시 워커 태스크는 A 를 닫는 동안에도 돌도록 spec 을 길게 쓴다). 관제가 Run 에 묶인 지 10분이 지난 뒤(`run.json` 의 `bound_at`) A 의 탭을 앱에서 닫고(시험 탭만) 새 시험 탭에서 시험 메인 B 를 연다. 적는다:
  1. B 의 첫 watch 뒤 `run.json` 의 `main_terminal` 이 B 다.
  2. 관제가 한가할 때 drive.log 에 `관제 다시 묶기: …` 와 `관제 종료: rehome: <A> → <B>` 가 있고, outbox 에 progress 가 있고, `rehome.json` 이 생겼다가 새 관제가 지운다.
  3. B 가 progress 를 전한 뒤 다시 띄운 watch 가 `orphaned` 로 끝나 `/herdr-team:up` 을 하고 새 관제가 뜬다(자동 부활이 먼저 띄웠으면 그렇다고 적는다).
  4. 새 관제의 `hc get`(parent B, die_with_parent, notify), `herdr-app ls` 에서 B 의 `sub_agents` 에 새 관제가 든다.
  5. drive.log `앞 관제 터미널 <t> 정리: removed` 이고 관제 탭에 끝난 pane 이 남지 않는다(`--keep` 관제가 스스로 끝나면 `finished` 로 남는다는 가정, 설계 8.13. `live` 로 남았으면 `left(live)` 와 그 원문을 적는다).
  6. 앞 관제 종료부터 새 관제 Run 연결까지 걸린 시간, 그동안 낸 큐 명령이 `drive_down` 인지, 다시 뜬 뒤 도는 워커의 worker_done 이 처리되는지.
  7. 사용자에게 Agents 목록에서 관제가 B 아래 보이는지 확인을 받는다.
- [ ] **Step 2: 고정 에이전트 다시 묶기(15.2 의 11단계 8)**: 1 뒤 그 에이전트의 리셋을 돌린다(묶음 끝, 또는 B 에게 `hteam agent reset production` 을 부탁한다). drive.log 에 인수인계 뒤 `production 리셋: new_terminal(parent_changed)` 가 있고 `terminal-reset`(`/clear`)은 없는지, 다음 태스크의 새 작업 터미널 parent 가 B 인지, 새 세션이 인수인계 파일을 읽었는지(보고서), 에이전트 탭 이름과 배치(작업 pane 왼쪽, 리뷰 중이면 보기 pane 오른쪽)를 본다. 사용자에게 Agents 목록에서 B 아래 보이는지 확인을 받는다.
- [ ] **Step 3: 되풀이 없음(15.2 의 11단계 9)**: B 에서 `/exit` 뒤 같은 터미널에서 시험 메인을 다시 열고 10분 넘게 둔다. `main_terminal` 이 그대로이고 관제가 끝나지 않는지(drive.log 에 `rehome` 이 없는지) 본다. 고정 에이전트 리셋을 한 번 더 돌려 이번에는 `reset(turn …)`(같은 터미널 비우기)인지 본다.
- [ ] **Step 4: 회귀(15.2 의 11단계 10)**: 전체 시험(`bash herdr-team/tests/run.sh` 를 마친 뒤 `bash herdr-orch/tests/run.sh`, 하나씩 백그라운드).
- [ ] **Step 5: 기록**: 설계 15.4 에 "11단계 (2026-11-16)" 절을 더한다. 1차(1–6: 환경, 본 것, 결과, 발견한 문제와 처리. 메인 탭 닫기 뒤 따로 보인 관제·고정 에이전트와 두 번째 Claude 세션이 메인을 가져간 일은 보강 설계로 이어졌다고 적는다)와 2차(7–10: 위 Step 1–4 의 결과, 한계로 남긴 것)를 함께 적는다. 머리말 상태 줄을 고친다:
  - 설계 머리말의 "10단계(15.3 의 10)는 구현·실환경 확인을 마쳤다(herdr-team 0.7.0, herdr-orch 그대로, 병합 대기). 11단계(15.3 의 11, Herdr Agents 계층)는 구현·브랜치 리뷰·실환경 1차를 마쳤고, 보강(메인이 바뀐 뒤 다시 묶기, 1장 11단계 보강)을 설계 중이다(herdr-team 0.7.1, herdr-orch 0.4.0)." 를 "10단계(15.3 의 10)는 구현·실환경 확인을 마치고 herdr-team 0.7.0 으로 병합했다. 11단계(15.3 의 11, Herdr Agents 계층)는 보강(1장 11단계 보강)까지 구현·실환경 확인을 마쳤다(herdr-team 0.7.1, herdr-orch 0.4.0, 병합 대기)." 로.
  - horch 설계 머리말의 "0.3.0(14장, 워커 환경 변수)은 herdr-team 7단계와 한 주기로 구현·실환경 확인을 마쳤다(병합 대기, 2026-11-12). 0.4.0(15장, 부모 터미널)은 herdr-team 11단계와 한 주기로 설계 중이다(2026-11-16)." 를 "0.3.0(14장, 워커 환경 변수)은 herdr-team 7단계와 한 주기로 구현·실환경 확인을 마치고 병합했다(2026-11-12). 0.4.0(15장, 부모 터미널)은 herdr-team 11단계와 한 주기로 구현·실환경 확인을 마쳤다(병합 대기, 2026-11-…)." 로.
  - 경로 지정 커밋 `docs: herdr-team 11단계 실환경 확인 결과(설계 15.4 의 1차·2차, 머리말 상태)`. 개인 경로 검사를 먼저 한다.
- [ ] **Step 6**: main 병합은 사용자에게 묻는다. 병합 뒤 사용자 프로젝트(kakao·comment-browser)에 0.7.0·0.7.1 안내를 보낼지도 사용자에게 묻는다.
