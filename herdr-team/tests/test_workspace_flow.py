"""작업 공간 흐름 1(7단계, 설계 5.9.4 의 0, 5.10.1·5.10.3·5.10.4·5.10.5, 5.7·6.1 의 7단계 줄, 8.8·8.11): 배정, start 의
슬롯 예약·준비 대기·busy, horch 의 --cwd·--env, 워커 사양의 작업 공간 절, 슬롯 안의 리뷰·관문·리뷰 커밋·변조 기준점·리뷰어,
관제의 준비 자식과 decide workspace_failed. 병합·놓기·drop·reset·status·마무리 full 은 test_workspace_merge(Task 5)."""
import json
import re
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path

from tests.helpers import BASE_CONFIG, CREW_CONFIG, WS_CONFIG, TeamCase
from tests.test_drive_events import EventCase
from hteam import config, crew, state
from hteam.paths import Project

# 워커 사양의 작업 공간 절(설계 5.10.5 블록 원문. 작업 루트·태스크·포트를 채운다)
SECTION = ("## 작업 공간\n"
           "- 이 태스크는 슬롯 worktree `{root}` 에서 한다. 브랜치는 `herdr/{tid}`(기준 `main`)다. 이 폴더 밖(메인 폴더, 다른 슬롯)의 "
           "파일을 고치지 않는다.\n"
           "- 커밋은 이 브랜치에 한다. 병합·push·브랜치 바꾸기·rebase 는 하지 않는다. 리뷰가 승인하면 관제가 병합한다.\n"
           "- 시험 환경(이 슬롯 전용): `HT_PORT={port}`. 다른 값을 쓰지 않는다.")
# 리뷰 프롬프트 `## 태스크` 의 작업 공간 줄(설계 5.10.5: 첫째 줄과 셋째 줄)
REVIEW_LINES = ("\n- 이 태스크는 슬롯 worktree `{root}` 에서 한다. 브랜치는 `herdr/{tid}`(기준 `main`)다. 이 폴더 밖(메인 폴더, "
                "다른 슬롯)의 파일을 고치지 않는다.\n- 시험 환경(이 슬롯 전용): `HT_PORT={port}`. 다른 값을 쓰지 않는다.")
DETACHED = ("메인 폴더가 detached HEAD 라 T-001 의 작업 공간 슬롯을 잡지 않았다(기준 브랜치가 없다). 메인 폴더를 기준 브랜치로 "
            "되돌린 뒤 다시 시작한다")
# 관문 명령: 받은 슬롯 env 를 $FAKE_DIR/env.txt 에 남긴 뒤 가짜 테스트(cwd 는 가짜가 test-args.jsonl 에 남긴다)
ENV_QUICK = 'mkdir -p "$FAKE_DIR"; printf "%s %s\\n" "$HTEAM_SLOT" "$HT_PORT" >> "$FAKE_DIR/env.txt"; fake-test {files}'
NO_ENV_CONFIG = WS_CONFIG.replace('\n[workspace.env]\nHT_PORT = "81{slot}0"\n', "\n")
SETUP_FAIL_CONFIG = WS_CONFIG.replace("slots = 2\n", 'slots = 2\nsetup = "echo 설치 실패; exit 3"\n')
# 슬롯 잠금을 다른 프로세스가 쥔다(앞 관제가 남긴 준비 자식처럼). 시험이 표준 입력을 닫을 때 놓는다
HOLD_SLOT = ("import fcntl, sys; fh = open(sys.argv[1], 'a+'); fcntl.flock(fh, fcntl.LOCK_EX); "
             "print('held', flush=True); sys.stdin.read()")


class WsCase(TeamCase):
    """작업 공간 프로젝트(WS_CONFIG: developer·tester 가 작업 공간 직무, 슬롯 둘, HT_PORT)와 관제 Run, 태스크 T-001(src/a/**)."""

    config_text = WS_CONFIG

    def setUp(self):
        super().setUp()
        self.init_project(self.config_text)
        self.setup_run()
        self.p = Project(self.proj)
        self.write_spec("T-001", owns="src/a/**")

    def start(self, tid: str = "T-001") -> tuple[int, dict]:
        return self.hteam("start", tid)

    def record(self, n: int) -> dict:
        return self.slots()["slots"].get(str(n), {})

    def round_spec(self, tid: str = "T-001", n: int = 1) -> str:
        return (self.state_dir / "tasks" / tid / f"r{n}-work.md").read_text(encoding="utf-8")

    def logged(self, text: str) -> int:
        path = self.drive_dir / "drive.log"
        lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
        return sum(1 for line in lines if line.split(" ", 1)[-1] == text)

    def work(self, tid: str = "T-001", rel: str = "src/a/app.py") -> None:
        code, out = self.act_work(tid, {rel: "print('a')\n"})
        self.assertEqual(code, 0, out)

    def env_lines(self) -> list[str]:
        path = self.tmp / "fake" / "env.txt"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def slot_head(self, n: int = 1) -> str:
        return self.git_at(self.slot_root(n), "rev-parse", "HEAD").strip()


class ReserveTest(WsCase):
    """start 의 슬롯 잡기(설계 5.10.3 의 1·끝 문단): 예약만 쓰고 기다린다. 예약이 owns 잠금을 쥔다."""

    def test_first_start_reserves_smallest_free_slot_and_waits(self):
        base = self.head()
        code, out = self.start()
        self.assertEqual((code, out["status"], out["reason"]), (0, "waiting", "slot_setup"), out)
        self.assertEqual(out["message"], "T-001: 작업 공간 slot-1 을 준비하는 중이다(관제가 hteam slot prepare 를 돌린다). "
                                         "pending 으로 두었다. 준비가 끝나면 관제가 띄운다")
        rec = self.record(1)
        self.assertEqual({k: rec.get(k) for k in ("state", "task", "branch", "base_branch", "base", "setup_done")},
                         {"state": "preparing", "task": "T-001", "branch": "herdr/T-001", "base_branch": "main",
                          "base": base, "setup_done": None})
        self.assertRegex(rec["since"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertNotIn("ready", rec)
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["round"], st["rounds"], st["owns"]), ("pending", 0, [], ["src/a/**"]))
        self.assertNotIn("workspace", st)
        self.assertFalse(self.slot_root(1).exists())  # 폴더·브랜치·setup 은 준비 자식이 한다(start 가 하지 않는다)
        code, out = self.horch("worker-list")
        self.assertEqual(out["workers"], [])
        self.assertEqual(self.logged("slot-1 T-001 잡기 preparing"), 1)

    def test_start_again_while_preparing_changes_nothing(self):
        self.start()
        before = self.slots()
        code, out = self.start()
        self.assertEqual((code, out["status"], out["reason"]), (0, "waiting", "slot_setup"), out)
        self.assertEqual(self.slots(), before)
        self.assertEqual(self.logged("slot-1 T-001 잡기 preparing"), 1)

    def test_reservation_holds_owns_lock(self):
        self.write_spec("T-002", owns="src/a/b/**")
        self.start("T-001")  # 예약만(pending). 같은 옛 기준에서 두 태스크가 브랜치를 준비하지 않게(Codex 설계 리뷰 r1)
        self.assertEqual((self.task_state("T-001")["status"], self.record(1).get("task")), ("pending", "T-001"))
        code, out = self.start("T-002")
        self.assertEqual((code, out["status"], out["reason"]), (0, "waiting", "lock"), out)
        self.assertIn("T-001", out["message"])
        self.assertIsNone(self.record(2).get("task"))
        self.assertEqual(self.task_state("T-002")["status"], "pending")

    def test_dirty_slot_is_not_taken(self):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "slots.json").write_text(json.dumps({"slots": {"1": {
            "state": "dirty", "task": None, "branch": None, "base_branch": None, "base": None, "setup_done": None,
            "since": "2026-11-12T00:00:00Z"}}}), encoding="utf-8")
        code, out = self.start()
        self.assertEqual((code, out["reason"]), (0, "slot_setup"), out)
        self.assertEqual((self.record(1)["state"], self.record(2)["state"], self.record(2)["task"]),
                         ("dirty", "preparing", "T-001"))

    def test_no_free_slot_waits_slot(self):
        for tid, owns in (("T-002", "src/b/**"), ("T-003", "src/c/**")):
            self.write_spec(tid, owns=owns)
        self.start("T-001")
        self.start("T-002")
        code, out = self.start("T-003")
        self.assertEqual((code, out["status"], out["reason"]), (0, "waiting", "slot"), out)
        self.assertEqual(out["message"], "T-003: 빈 작업 공간 슬롯이 없다(slots = 2). pending 으로 두었다. "
                                         "슬롯이 비면 관제가 띄운다")
        self.assertEqual({n: self.record(n).get("task") for n in (1, 2)}, {1: "T-001", 2: "T-002"})
        st = self.task_state("T-003")
        self.assertEqual((st["status"], st["owns"]), ("pending", []))  # 예약하지 않았으니 owns 잠금도 없다

    def test_start_ready_reasons(self):
        for tid, owns in (("T-002", "src/b/**"), ("T-003", "src/c/**")):
            self.write_spec(tid, owns=owns)
        for tid in ("T-001", "T-002", "T-003"):
            state.create(self.p, tid, "developer")
        code, out = self.hteam("start-ready")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["started"], [])
        self.assertEqual([(w["task"], w["reason"]) for w in out["waiting"]],
                         [("T-001", "slot_setup"), ("T-002", "slot_setup"), ("T-003", "slot")])

    def test_detached_head_is_workspace_failed(self):
        self.git("checkout", "-q", "--detach")
        code, out = self.start()
        self.assertEqual((code, out["error"]["code"], out["error"]["message"]), (3, "base_detached", DETACHED), out)
        self.assertEqual(self.slots(), {"slots": {}})
        dec = [e for e in self.outbox_items() if e["type"] == "decide"]
        self.assertEqual([(e["kind"], e["task"], e["summary"], e["detail"], e["commands"]) for e in dec],
                         [("workspace_failed", "T-001", DETACHED, {"kind": "base_moved", "detached": True},
                           ["hteam start T-001"])])
        self.assertEqual(self.task_state("T-001")["decide"], dec[0]["id"])
        code, out = self.hteam("start-ready")  # 열린 decide 가 있는 동안 start-ready 는 띄우지 않는다(5.4)
        self.assertEqual([(w["task"], w["reason"]) for w in out["waiting"]], [("T-001", "decide")])
        self.assertEqual(len([e for e in self.outbox_items() if e["type"] == "decide"]), 1)


class LaunchTest(WsCase):
    """준비가 끝난 예약의 start(설계 5.10.3 의 5): busy, 태스크 상태의 workspace, horch --cwd·--env, 사양의 작업 공간 절."""

    def test_ready_start_goes_busy_and_launches_in_slot(self):
        base = self.head()
        out = self.ws_start("T-001")
        root = self.slot_root(1)
        self.assertEqual((self.record(1)["state"], self.record(1)["task"]), ("busy", "T-001"))
        self.assertNotIn("ready", self.record(1))
        st = self.task_state("T-001")
        self.assertEqual(st["workspace"], {"slot": 1, "branch": "herdr/T-001", "base_branch": "main",
                                           "root": str(root), "merge": None})
        self.assertEqual((st["base"], st["rounds"][0]["round_base"]), (base, self.slot_head()))
        row = self.dispatch_row(out["dispatch"])
        self.assertEqual((row["cwd"], json.loads(row["env"])), (str(root), {"HT_PORT": "8110", "HTEAM_SLOT": "1"}))
        self.assertEqual(self.git_at(root, "branch", "--show-current").strip(), "herdr/T-001")
        self.assertEqual(self.logged("slot-1 T-001 사용 busy"), 1)

    def test_work_spec_has_workspace_section_before_rules(self):
        self.ws_start("T-001")
        text = self.round_spec()
        self.assertIn(SECTION.format(root=self.slot_root(1), tid="T-001", port="8110") + "\n\n## 소유 경로와 작업 규칙", text)
        self.assertLess(text.index("## 선행 태스크"), text.index("## 작업 공간"))
        self.assertEqual(text.count("## 작업 공간"), 1)

    def test_two_tasks_run_in_two_slots(self):
        self.write_spec("T-002", owns="src/b/**")
        one = self.ws_start("T-001")
        two = self.ws_start("T-002")
        rows = [self.dispatch_row(x["dispatch"]) for x in (one, two)]
        self.assertEqual([(r["cwd"], json.loads(r["env"])["HT_PORT"]) for r in rows],
                         [(str(self.slot_root(1)), "8110"), (str(self.slot_root(2)), "8120")])
        self.assertIn("`HT_PORT=8120`", self.round_spec("T-002"))
        self.assertEqual(self.git_at(self.slot_root(2), "branch", "--show-current").strip(), "herdr/T-002")

    def test_closed_task_on_busy_slot_does_not_hold_lock(self):
        self.write_spec("T-002", owns="src/a/b/**")
        self.ws_start("T-001")
        with state.edit(self.p, "T-001") as st:  # 병합 뒤 놓기 전(Task 5): done 인데 슬롯 기록은 아직 busy 다
            st["status"] = "done"
        code, out = self.start("T-002")  # 잠금은 병합까지다. 슬롯을 쥔 닫힌 태스크는 owns 잠금을 쥐지 않는다
        self.assertEqual((code, out["status"], out["reason"]), (0, "waiting", "slot_setup"), out)
        self.assertEqual((self.record(1)["task"], self.record(2)["task"]), ("T-001", "T-002"))

    def test_same_round_recovery_keeps_cwd_and_env(self):
        code, out = self.start()
        code, out = self.hteam("slot", "prepare", "T-001")
        self.assertEqual(code, 0, out)
        self.fail_hc("run", "boom")
        code, out = self.start()
        self.assertEqual((code, out["error"]["code"]), (1, "launch_failed"), out)
        self.assertEqual((self.task_state("T-001")["status"], self.record(1)["state"]), ("launch_failed", "busy"))
        with self._hc_locked() as hc:
            hc["fail"].clear()
        code, out = self.start()
        self.assertEqual((code, out["mode"], out["status"]), (0, "retry", "working"), out)
        row = self.dispatch_row(out["dispatch"])
        self.assertEqual((row["cwd"], json.loads(row["env"])), (str(self.slot_root(1)), {"HT_PORT": "8110", "HTEAM_SLOT": "1"}))

    # 슬롯의 .git 이 사라졌으면 워커를 그 폴더에 띄우지 않는다: git 이 위로 올라가 메인 HEAD 를 round_base 로 적고 워커가 메인
    # 저장소 안의 그 폴더에서 커밋한다(C2 와 같은 뿌리). 라운드·상태·slots.json 을 쓰기 전에 거부한다
    def frozen(self) -> tuple:
        """거부 뒤 그대로여야 하는 것: 태스크 상태, slots.json, 메인 HEAD·브랜치, hc run 호출 수."""
        return (self.task_state("T-001"), self.slots(), self.head(), self.git("branch", "--show-current").strip(),
                len([c for c in self.hc_calls() if c[:1] == ["run"]]))

    def test_recovery_start_refuses_slot_that_is_not_a_worktree(self):
        self.start()
        self.assertEqual(self.hteam("slot", "prepare", "T-001")[0], 0)
        self.fail_hc("run", "boom")
        code, out = self.start()
        self.assertEqual((code, out["error"]["code"]), (1, "launch_failed"), out)
        with self._hc_locked() as hc:
            hc["fail"].clear()
        (self.slot_root(1) / ".git").unlink()
        before = self.frozen()
        self.assertEqual((before[0]["status"], before[1]["slots"]["1"]["state"]), ("launch_failed", "busy"))
        code, out = self.start()  # 같은 라운드 복구(busy 슬롯)
        self.assertEqual((code, out["error"]["code"], out["slot"]), (1, "slot_not_worktree", 1), out)
        self.assertEqual(self.frozen(), before)
        code, out = self.hteam("start-ready")  # 관제의 다시 띄우기도 같다
        self.assertEqual((code, out["error"]["code"]), (1, "start_failed"), out)
        self.assertEqual([(f["task"], f["error"]["code"]) for f in out["failed"]], [("T-001", "slot_not_worktree")])
        self.assertEqual(self.frozen(), before)

    def test_first_start_refuses_ready_slot_that_is_not_a_worktree(self):
        self.start()
        self.assertEqual(self.hteam("slot", "prepare", "T-001")[0], 0)
        (self.slot_root(1) / ".git").unlink()
        before = self.frozen()
        self.assertEqual((before[0]["status"], before[0]["rounds"], before[1]["slots"]["1"]["state"]),
                         ("pending", [], "preparing"))
        code, out = self.start()  # 준비가 끝난 예약(ready)을 busy 로 바꾸기 전에 거부한다
        self.assertEqual((code, out["error"]["code"], out["slot"]), (1, "slot_not_worktree", 1), out)
        self.assertEqual(self.frozen(), before)
        self.assertNotIn("workspace", self.task_state("T-001"))


class NoEnvTest(WsCase):
    """[workspace.env] 가 없으면 작업 공간 절의 셋째 줄을 뺀다(설계 5.10.5). horch 에는 HTEAM_SLOT 만 넘긴다."""

    config_text = NO_ENV_CONFIG

    def test_section_without_env_line(self):
        out = self.ws_start("T-001")
        text = self.round_spec()
        self.assertIn("- 커밋은 이 브랜치에 한다. 병합·push·브랜치 바꾸기·rebase 는 하지 않는다. 리뷰가 승인하면 관제가 병합한다."
                      "\n\n## 소유 경로와 작업 규칙", text)
        self.assertNotIn("시험 환경(이 슬롯 전용)", text)
        self.assertEqual(json.loads(self.dispatch_row(out["dispatch"])["env"]), {"HTEAM_SLOT": "1"})


class SlotReviewTest(WsCase):
    """리뷰의 작업 루트(설계 5.10.4·6.1 7단계 줄): 대상 커밋·관문·리뷰 파일 커밋·변조 기준점·리뷰어 cwd·env 가 슬롯이다."""

    def test_review_runs_in_slot_and_commits_on_task_branch(self):
        self.ws_start("T-001")
        root, main_head = self.slot_root(1), self.head()
        self.work()
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out["status"]), (0, "reviewing"), out)
        att = self.attempt("T-001")
        self.assertEqual([c["subject"] for c in att["inputs"]["commits"]], ["[T-001] r1 작업"])
        self.assertEqual(att["inputs"]["files"], ["docs/tasks/T-001/report.md", "src/a/app.py"])
        self.assertEqual(att["baseline"]["head"], self.slot_head())
        rrow = self.dispatch_row(att["dispatch"])
        self.assertEqual((rrow["cwd"], json.loads(rrow["env"])), (str(root), {"HT_PORT": "8110", "HTEAM_SLOT": "1"}))
        prompt = (self.state_dir / "tasks" / "T-001" / "r1-review-a1.md").read_text(encoding="utf-8")
        self.assertIn("- 이전 리뷰: 없음" + REVIEW_LINES.format(root=root, tid="T-001", port="8110") + "\n\n## 리뷰 대상 커밋",
                      prompt)
        code, out = self.act_review("T-001", "APPROVE")
        self.assertEqual(code, 0, out)
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual((code, out["status"]), (0, "approved"), out)
        self.assertEqual(self.git_at(root, "log", "-1", "--format=%s").strip(), "[T-001] review r1: APPROVE")
        self.assertTrue((root / "docs" / "reviews" / "T-001" / "r1.md").is_file())
        self.assertFalse((self.proj / "docs" / "reviews").exists())
        self.assertEqual(self.head(), main_head)  # 메인 폴더 브랜치에는 아직 아무것도 들지 않았다(병합은 Task 5)

    def test_other_slot_task_owns_are_not_excluded_from_tamper(self):
        # 다른 슬롯의 워커는 이 작업 트리를 바꾸지 않는다. 그 태스크의 owns 를 이 슬롯의 변조 검사에서 빼지 않는다(Codex 커밋
        # 리뷰 b916c8c P1: T-002 가 src/b/** 를 쥔 동안 T-001 리뷰어가 자기 슬롯의 src/b 를 고쳐 커밋해도 승인됐다)
        self.write_spec("T-002", owns="src/b/**")
        self.ws_start("T-001")
        self.ws_start("T-002")  # 기준점에 진행 중(slot-2)
        self.work()
        self.hteam("review", "T-001")
        self.act_review("T-001", "APPROVE", extra={"write": {"src/b/x.py": "리뷰어가 고침\n"}, "commit": "리뷰어 커밋"})
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual((code, out["error"]["code"]), (1, "review_tampered"), out)
        self.assertEqual((out["tamper"]["paths"], out["tamper"]["excluded_tasks"]), (["src/b/x.py"], []))

    def test_fix_round_review_prompt_state_files_open_from_slot(self):
        # 리뷰어 cwd 는 슬롯이다. 상태 루트에만 있는 이번 라운드 작업 사양과 관문 로그는 슬롯에서 메인 루트로 가는 상대 경로로
        # 준다(Codex 커밋 리뷰 b916c8c P2, 2차 G1: 절대 경로를 넣지 않는다). 저장소 파일(보고서·이전 리뷰)은 작업 루트 기준이다
        self.use_gate()
        self.ws_start("T-001")
        self.work()
        self.hteam("review", "T-001")
        self.act_review("T-001", "REQUEST_CHANGES")
        self.assertEqual(self.hteam("review-finish", "T-001")[1]["status"], "changes")
        code, out = self.hteam("fix", "T-001", "--note=로그를 남긴다")
        self.assertEqual((code, out["round"]), (0, 2), out)
        self.assertEqual(self.act_work("T-001", {"src/a/app.py": "print('b')\n"})[0], 0)
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out["status"]), (0, "reviewing"), out)
        cwd = Path(self.dispatch_row(self.attempt("T-001")["dispatch"])["cwd"])
        self.assertEqual(cwd, self.slot_root(1))
        prompt = (self.state_dir / "tasks" / "T-001" / "r2-review-a1.md").read_text(encoding="utf-8")
        work = re.search(r"^- 이번 라운드 작업 사양: `([^`]+)`$", prompt, re.M).group(1)
        log = re.search(r"^- quick 로그: (\S+)$", prompt, re.M).group(1)
        self.assertEqual(work, "../../../../.herdr-team/state/tasks/T-001/r2-work.md")
        self.assertTrue(log.startswith("../../../../.herdr-team/state/tests/logs/T-001-r2-quick-a1-"), log)
        for path in (work, log):
            self.assertTrue((cwd / path).is_file(), path)
        self.assertIn("- 워커 보고서: `docs/tasks/T-001/report.md`\n- 이전 리뷰: `docs/reviews/T-001/r1.md`", prompt)
        # 메인 절대 경로는 작업 공간 줄(설계 5.10.5 의 슬롯 폴더)에만 있다
        rest = prompt.replace(REVIEW_LINES.format(root=self.slot_root(1), tid="T-001", port="8110"), "")
        for main in {str(self.proj), str(self.p.root)}:
            self.assertNotIn(main, rest)

    def test_slot_prompts_point_team_files_at_main_copy(self):
        # 상태 루트(메인)의 팀 파일이 기준이다(설계 5.10.2). 슬롯을 딴 뒤 메인에서 고친 사양·직무 문서를 슬롯 cwd 에서 연다.
        # 직무 문서 본문의 `.herdr-team/` 팀 파일도 메인 사본을 가리킨다. shim(`.herdr-team/bin/hteam`)은 슬롯 것을 부른다(2차 G2)
        doc = self.team / "roles" / "developer.md"
        doc.write_text("# developer 직무 문서\n- `.herdr-team/project.md` 를 읽는다. 시험은 `.herdr-team/bin/hteam test` 로.\n",
                       encoding="utf-8")
        self.ws_start("T-001")
        root = self.slot_root(1)
        self.assertIn("- `../../../../.herdr-team/project.md` 를 읽는다. 시험은 `.herdr-team/bin/hteam test` 로.",
                      self.round_spec())
        self.assertEqual((root / "../../../../.herdr-team/project.md").read_text(encoding="utf-8"), "테스트 프로젝트\n")
        self.work()
        spec = (self.team / "tasks" / "T-001.md").read_text(encoding="utf-8")
        self.commit(".herdr-team/tasks/T-001.md", spec + "\n고친 Acceptance\n", "spec: T-001 고침")  # 메인에서 고쳤다
        doc.write_text("# developer 직무 문서(고침)\n", encoding="utf-8")
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out["status"]), (0, "reviewing"), out)
        prompt = (self.state_dir / "tasks" / "T-001" / "r1-review-a1.md").read_text(encoding="utf-8")
        spec_at = re.search(r"^- 사양: `([^`]+)`$", prompt, re.M).group(1)
        role_at = re.search(r"^- 직무 문서: `([^`]+)`$", prompt, re.M).group(1)
        self.assertEqual((spec_at, role_at), ("../../../../.herdr-team/tasks/T-001.md",
                                              "../../../../.herdr-team/roles/developer.md"))
        self.assertIn("고친 Acceptance", (root / spec_at).read_text(encoding="utf-8"))
        self.assertEqual((root / role_at).read_text(encoding="utf-8"), "# developer 직무 문서(고침)\n")
        self.assertNotIn("고친 Acceptance", (root / ".herdr-team" / "tasks" / "T-001.md").read_text(encoding="utf-8"))

    def test_slot_review_reads_main_checklist(self):
        # 프로젝트 점검표는 메인 프로젝트 작업 트리의 것이다(설계 6.2. 커밋하지 않아 슬롯에는 없다). 본문 안의 팀 파일 경로는
        # 기준 절처럼 메인 사본을 가리킨다(Task 4 리뷰 반영 2차 G2 의 규칙)
        self.ws_start("T-001")
        root = self.slot_root(1)
        (self.team / "review-extra.md").write_text("- `.herdr-team/project.md` 의 규칙을 다시 본다\n", encoding="utf-8")
        self.work()
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out["status"]), (0, "reviewing"), out)
        prompt = (self.state_dir / "tasks" / "T-001" / "r1-review-a1.md").read_text(encoding="utf-8")
        self.assertIn("## 프로젝트 점검표\n- `../../../../.herdr-team/project.md` 의 규칙을 다시 본다\n\n## 등급과 판정\n",
                      prompt)
        self.assertFalse((root / ".herdr-team" / "review-extra.md").exists())
        self.assertTrue((root / "../../../../.herdr-team/project.md").is_file())

    def test_main_folder_commit_during_review_is_not_tamper(self):
        self.ws_start("T-001")
        self.work()
        self.hteam("review", "T-001")
        self.commit("README.md", "# proj\n사람이 고침\n", "사람: README")  # 슬롯 밖(메인 폴더)의 커밋: 슬롯 HEAD 는 그대로다
        self.act_review("T-001", "APPROVE")
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual((code, out["status"]), (0, "approved"), out)

    def test_review_gate_runs_in_slot_with_slot_env(self):
        self.use_gate(quick=ENV_QUICK)
        self.ws_start("T-001")
        self.work()
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out["status"], out["tests"]), (0, "reviewing", {"quick": "passed"}), out)
        self.assertEqual([c["cwd"] for c in self.gate_calls()], [str(self.slot_root(1))])
        self.assertEqual(self.env_lines(), ["1 8110"])
        rec = json.loads((self.state_dir / "tests" / "T-001.json").read_text(encoding="utf-8"))
        self.assertEqual((rec["quick"]["files"], rec["quick"]["dirty"], rec["quick"]["head"]),
                         (["src/a/app.py"], [], self.slot_head()))

    def test_gate_rejection_is_committed_on_task_branch(self):
        self.use_gate(quick=ENV_QUICK)
        self.gate_modes("fail", "fail")
        self.ws_start("T-001")
        main_head = self.head()
        self.work()
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out["status"], out["source"]), (0, "changes", "hteam"), out)
        root = self.slot_root(1)
        self.assertEqual(self.git_at(root, "log", "-1", "--format=%s").strip(), "[T-001] review r1: REQUEST_CHANGES")
        self.assertTrue((root / "docs" / "reviews" / "T-001" / "r1.md").is_file())
        self.assertEqual(self.head(), main_head)
        text = self.git_at(root, "show", "HEAD:docs/reviews/T-001/r1.md")  # 커밋된 내용(병합으로 기준 브랜치에도 든다)
        for main in {str(self.proj), str(self.p.root)}:
            self.assertNotIn(main, text)  # 사용자 프로젝트 이력에 절대 경로를 남기지 않는다(2차 G1)
        log = re.search(r"^- quick 로그: (\S+)$", text, re.M).group(1)
        self.assertTrue(log.startswith("../../../../.herdr-team/state/tests/logs/"), log)
        self.assertTrue((root / log).is_file(), log)  # 다음 라운드 워커(cwd 는 슬롯)가 이 반려 파일의 로그를 연다

    def test_worker_hteam_test_from_slot(self):
        self.use_gate(quick=ENV_QUICK)
        self.ws_start("T-001")
        root = self.slot_root(1)
        self.work()
        code, out = self.hteam("test", "T-001", as_=None, cwd=root)  # 워커가 슬롯에서 shim 처럼 부른다(--root 없이)
        self.assertEqual((code, out["status"], out["files"]), (0, "passed", ["src/a/app.py"]), out)
        self.assertEqual(self.gate_calls()[-1]["cwd"], str(root))
        self.assertEqual(self.env_lines(), ["1 8110"])
        self.assertTrue((self.state_dir / "tests" / "T-001.json").is_file())  # 기록은 메인 상태(설계 5.7 7단계)
        self.assertFalse((root / ".herdr-team" / "state" / "tests").exists())

    def test_worker_hteam_test_logs_open_from_slot(self):
        # 슬롯에서 부른 hteam test 의 로그 경로는 그 cwd 에서 열린다(메인 루트로 가는 상대 경로). 기록 파일은 상태 루트 기준
        # 그대로다(2차 G3)
        self.use_gate()
        self.gate_modes("fail", "fail", "fail", "pass")
        self.ws_start("T-001")
        root = self.slot_root(1)
        self.work()
        code, out = self.hteam("test", "T-001", as_=None, cwd=root)
        self.assertEqual(out["status"], "failed", out)
        self.assertNotEqual(code, 0)
        self.assertTrue(out["log"].startswith("../../../../.herdr-team/state/tests/logs/"), out)
        self.assertTrue((root / out["log"]).is_file(), out["log"])
        code, out = self.hteam("test", "T-001", as_=None, cwd=root)  # 1차 실패, 2차 통과(flaky): 첫 실행 로그도 같다
        self.assertEqual((code, out["status"]), (0, "flaky"), out)
        for log in (out["log"], out["first"]["log"]):
            self.assertTrue(log.startswith("../../../../") and (root / log).is_file(), log)
        rec = json.loads((self.state_dir / "tests" / "T-001.json").read_text(encoding="utf-8"))
        self.assertTrue(rec["quick"]["log"].startswith(".herdr-team/state/tests/logs/"), rec)
        code, out = self.hteam("test", "T-001", as_=None)  # 메인 폴더에서 부르면 지금처럼 상태 루트 기준
        self.assertTrue(out["log"].startswith(".herdr-team/state/tests/logs/"), out)

    def test_review_refuses_slot_that_is_not_a_worktree(self):
        # 슬롯의 .git 이 사라졌으면 그 폴더에 git 을 부르지 않는다: git 이 위로 올라가 메인 저장소를 잡는다(workspace.own_worktree)
        self.ws_start("T-001")
        self.work()
        main_head = self.head()
        (self.slot_root(1) / ".git").unlink()
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out["error"]["code"], out["slot"]), (1, "slot_not_worktree", 1), out)
        self.assertEqual((self.head(), self.task_state("T-001")["status"]), (main_head, "working"))
        self.assertFalse((self.slot_root(1) / "docs" / "reviews").exists())

    def test_fix_round_stays_in_slot(self):
        self.ws_start("T-001")
        root = self.slot_root(1)
        self.work()
        self.hteam("review", "T-001")
        self.act_review("T-001", "REQUEST_CHANGES")
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual(out["status"], "changes", out)
        code, out = self.hteam("fix", "T-001")
        self.assertEqual((code, out["status"], out["round"]), (0, "working", 2), out)
        self.assertEqual(self.task_state("T-001")["rounds"][-1]["round_base"], self.slot_head())
        text = self.round_spec(n=2)
        self.assertIn(SECTION.format(root=root, tid="T-001", port="8110"), text)
        self.assertIn("`docs/reviews/T-001/r1.md` 리뷰를 읽고 막는 지적", text)  # 이전 리뷰는 슬롯에만 있다
        row = self.dispatch_row(out["dispatch"])
        self.assertEqual((row["cwd"], json.loads(row["env"])["HTEAM_SLOT"]), (str(root), "1"))
        self.assertEqual((self.record(1)["state"], self.record(1)["task"]), ("busy", "T-001"))

    def test_fix_refuses_slot_that_is_not_a_worktree(self):
        # 슬롯의 .git 이 사라졌으면 fix 는 새 라운드를 열지 않는다: 열면 git 이 위로 올라가 메인 HEAD 를 round_base 로 적고
        # 워커가 메인 저장소 안의 그 폴더에서 뜬다(Codex 브랜치 리뷰 P2). 이전 워커 정리·라운드 생성 전에 거부한다
        self.ws_start("T-001")
        self.work()
        self.hteam("review", "T-001")
        self.act_review("T-001", "REQUEST_CHANGES")
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual(out["status"], "changes", out)
        st = self.task_state("T-001")
        main_head, runs = self.head(), len([c for c in self.hc_calls() if c[:1] == ["run"]])
        (self.slot_root(1) / ".git").unlink()
        code, out = self.hteam("fix", "T-001")
        self.assertEqual((code, out["error"]["code"], out["slot"]), (1, "slot_not_worktree", 1), out)
        self.assertEqual(self.task_state("T-001"), st)
        self.assertEqual((self.head(), self.git("branch", "--show-current").strip()), (main_head, "main"))
        self.assertEqual(len([c for c in self.hc_calls() if c[:1] == ["run"]]), runs)  # horch worker-start 없음
        self.assertFalse((self.state_dir / "tasks" / "T-001" / "r2-work.md").exists())


class PlaceTest(TeamCase):
    """crew.place 의 0(설계 5.9.4): worktree 모드의 작업 공간 직무는 늘 임시 워커다."""

    def test_workspace_role_is_always_temp(self):
        self.init_project(BASE_CONFIG)
        p = Project(self.proj)
        ws = config.build(tomllib.loads(CREW_CONFIG + '\n[workspace]\nmode = "worktree"\n'))
        self.assertEqual(crew.place(p, ws, "developer", "claude"), {"kind": "temp", "crew": None})
        self.assertEqual(crew.place(p, ws, "planner", "claude")["kind"], "crew")  # 작업 공간 직무가 아니면 그대로
        shared = config.build(tomllib.loads(CREW_CONFIG))
        self.assertEqual(crew.place(p, shared, "developer", "claude")["kind"], "crew")


class SharedRegressionTest(TeamCase):
    """회귀(헤더 "기본값"): [workspace] 가 없으면 horch 에 --env 가 없고 --cwd 는 프로젝트 루트, 상태에 workspace 가 없다."""

    config_text = BASE_CONFIG

    def test_shared_start_and_review_unchanged(self):
        self.init_project(self.config_text)
        self.setup_run()
        self.write_spec("T-001")
        code, out = self.hteam("start", "T-001")
        self.assertEqual((code, out["status"]), (0, "working"), out)
        row = self.dispatch_row(out["dispatch"])
        self.assertEqual((row["cwd"], row.get("env")), (str(self.proj), None))
        st = self.task_state("T-001")
        self.assertNotIn("workspace", st)
        self.assertEqual(st["rounds"][0]["round_base"], self.head())
        self.assertFalse((self.state_dir / "slots.json").exists())
        spec = (self.state_dir / "tasks" / "T-001" / "r1-work.md").read_text(encoding="utf-8")
        self.assertNotIn("## 작업 공간", spec)
        self.assertNotIn("이 태스크는 슬롯 worktree", spec)
        code, out = self.act_work("T-001")
        self.assertEqual(code, 0, out)
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out["status"]), (0, "reviewing"), out)
        rrow = self.dispatch_row(self.attempt("T-001")["dispatch"])
        self.assertEqual((rrow["cwd"], rrow.get("env")), (str(self.proj), None))
        prompt = (self.state_dir / "tasks" / "T-001" / "r1-review-a1.md").read_text(encoding="utf-8")
        self.assertNotIn("이 태스크는 슬롯 worktree", prompt)
        self.assertIn("- 이전 리뷰: 없음\n\n## 리뷰 대상 커밋", prompt)


class SharedModeTableTest(SharedRegressionTest):
    """mode = "shared" 를 적고 env 를 둬도 같다(설계 4.1: shared 면 나머지 키는 검사만 하고 쓰지 않는다)."""

    config_text = BASE_CONFIG + '\n[workspace]\nmode = "shared"\nslots = 3\n\n[workspace.env]\nHT_PORT = "81{slot}0"\n'


class DrivePrepareTest(EventCase):
    """관제의 준비 자식(설계 5.10.3 끝 두 문단, 8.8·8.11): slot_step 이 preparing 예약마다 `hteam slot prepare T`(키
    slot:<N>)를 띄우고, 거둘 때 성공이면 start-ready 가 띄우고 실패면 decide workspace_failed 다."""

    config = WS_CONFIG

    def hold_slot(self, n: int):
        """다른 프로세스가 슬롯 잠금을 쥔다(앞 관제가 남긴 준비 자식처럼). release() 가 놓는다."""
        path = self.state_dir / "slots" / f"slot-{n}.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen([sys.executable, "-c", HOLD_SLOT, str(path)], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, text=True)

        def release() -> None:
            if not proc.stdin.closed:
                proc.stdin.close()
            proc.wait(timeout=30)
            if not proc.stdout.closed:
                proc.stdout.close()

        self.addCleanup(release)
        self.assertEqual(proc.stdout.readline().strip(), "held")
        return release

    def test_slot_step_prepares_then_start_ready_launches(self):
        code, out = self.hteam("start", "T-001")
        self.assertEqual((code, out.get("reason")), (0, "slot_setup"), out)
        self.d.slot_step()
        self.assertEqual(self.d.jobs["slot:1"]["args"], ["slot", "prepare", "T-001"])
        self.d.slot_step()  # 그 키의 자식이 있으면 또 띄우지 않는다
        self.assertEqual(list(self.d.jobs), ["slot:1"])
        self.wait_jobs()
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["workspace"]["slot"]), ("working", 1))
        for line in ("slot-1 T-001 잡기 preparing", "slot-1 T-001 준비 시작", "slot-1 T-001 준비 ready",
                     "slot-1 T-001 사용 busy"):
            self.assertEqual(self.logged(line), 1, line)
        self.assertEqual(self.decides(), [])

    def test_reservation_written_by_start_ready_is_prepared_in_the_same_tick(self):
        # accept 뒤 start-ready 가 새로 쓴 예약의 준비 자식은 그 start-ready 끝에서 띄운다(다음 재확인까지 최대 60초 기다리지
        # 않는다. Task 4 태스크 리뷰 Minor 1)
        self.write_spec("T-002", owns="src/a/**")
        self.hteam("start", "T-001")
        self.d.slot_step()
        self.wait_jobs()
        self.assertEqual(self.task_state("T-001")["status"], "working")
        code, out = self.hteam("start", "T-002")
        self.assertEqual((code, out.get("reason")), (0, "lock"), out)
        with state.edit(self.p, "T-001") as st:  # 승인했다(병합·놓기는 Task 5)
            st["status"] = "done"
        self.d.after_accept("T-001", {"status": "done"})
        self.assertEqual((self.slots()["slots"]["2"]["state"], self.slots()["slots"]["2"]["task"]), ("preparing", "T-002"))
        self.assertEqual(self.d.jobs["slot:2"]["args"], ["slot", "prepare", "T-002"])
        self.wait_jobs()
        self.assertEqual(self.task_state("T-002")["status"], "working")

    def test_live_prepare_child_is_waited_then_restarted(self):
        self.hteam("start", "T-001")
        release = self.hold_slot(1)
        self.d.slot_step()
        self.assertEqual(self.d.jobs, {})  # 다른 준비 자식이 산다(슬롯 잠금): 기다린다
        release()
        self.d.reconcile()  # 재확인이 준비를 다시 띄운다(관제가 준비 중에 죽었다, 5.10.3 끝 문단)
        self.assertIn("slot:1", self.d.jobs)
        self.wait_jobs()
        self.assertEqual(self.task_state("T-001")["status"], "working")

    def test_dirty_new_slot_decides_without_task_and_takes_next_slot(self):
        top = self.slot_root(1)
        top.parent.mkdir(parents=True, exist_ok=True)
        self.git("worktree", "add", "-q", "--detach", str(top), "HEAD")
        (top / "junk.txt").write_text("남은 파일\n", encoding="utf-8")
        self.hteam("start", "T-001")
        self.d.slot_step()
        self.wait_jobs()
        dec = self.decides()
        self.assertEqual([(e["kind"], e["task"], e["detail"]) for e in dec],
                         [("workspace_failed", None, {"kind": "slot_dirty", "slot": 1, "files": ["junk.txt"],
                                                      "task": "T-001"})])
        self.assertEqual(dec[0]["commands"], ["hteam slot reset 1"])
        self.assertTrue(dec[0]["summary"].startswith("slot-1 폴더에 커밋 안 된 변경이 있어 T-001 를 준비하지 않았다"), dec[0])
        slots = self.slots()["slots"]
        self.assertEqual((slots["1"]["state"], slots["1"]["task"]), ("dirty", None))
        # 거둔 뒤 start-ready 가 다음 슬롯을 잡고, 그 끝의 slot_step 이 곧바로 준비한다(같은 거두기 동안 띄워진다)
        self.assertEqual((slots["2"]["state"], slots["2"]["task"]), ("busy", "T-001"))
        st = self.task_state("T-001")
        self.assertNotIn("decide", st)
        self.assertEqual((st["status"], st["workspace"]["slot"]), ("working", 2))
        self.assertEqual(self.logged("slot-1 T-001 준비 slot_dirty"), 1)
        self.assertEqual(self.logged("slot-2 T-001 준비 시작"), 1)

    def test_branch_exists_decides_on_task(self):
        self.git("branch", "herdr/T-001")
        self.hteam("start", "T-001")
        self.d.slot_step()
        self.wait_jobs()
        dec = self.decides()
        self.assertEqual([(e["kind"], e["task"], e["detail"], e["commands"]) for e in dec],
                         [("workspace_failed", "T-001", {"kind": "branch_exists", "slot": 1, "branch": "herdr/T-001"},
                           ["hteam start T-001"])])
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["rounds"], st["decide"]), ("launch_failed", [], dec[0]["id"]))
        # 슬롯을 쥐지 않은 작업 공간 태스크의 fix 는 상태를 바꾸기 전에 거부한다(메인 폴더에서 워커를 띄우지 않는다, Rules 12)
        code, out = self.hteam("fix", "T-001", "--note=다시 한다")
        self.assertEqual((code, out["error"]["code"], out["error"]["hint"]), (3, "slot_not_held", "hteam start T-001"), out)
        self.assertEqual(self.task_state("T-001"), st)
        self.assertFalse([c for c in self.hc_calls() if c[:1] == ["run"]])
        self.git("branch", "-D", "herdr/T-001")  # 사용자가 남은 브랜치를 지웠다. start 는 지금처럼 슬롯을 다시 잡는다
        code, out = self.hteam("start", "T-001")
        self.assertEqual((code, out["status"], out["reason"]), (0, "waiting", "slot_setup"), out)
        self.assertEqual((self.slots()["slots"]["1"]["state"], self.slots()["slots"]["1"]["task"]), ("preparing", "T-001"))

    def test_decide_files_point_at_the_slot_copy(self):
        # 병합 전 보고서는 슬롯에만 있다. decide files 는 메인이 열 수 있는 슬롯 경로다(Rules 13, Codex 계획 리뷰 r1)
        self.hteam("start", "T-001")
        self.d.slot_step()
        self.wait_jobs()
        did = self.work_dispatch("T-001")
        code, out = self.act_work("T-001", outcome="failed")
        self.assertEqual(code, 0, out)
        self.d.handle(self.done_msg(did, "failed", summary="빌드가 안 된다"))
        (e,) = self.decides()
        report = ".herdr-team/state/slots/slot-1/docs/tasks/T-001/report.md"
        self.assertEqual((e["kind"], e["files"]), ("worker_failed", [".herdr-team/tasks/T-001.md", report]))
        self.assertTrue((self.proj / report).is_file())
        self.assertFalse((self.proj / "docs/tasks/T-001/report.md").exists())


class DriveSetupFailTest(EventCase):
    """setup 실패(설계 5.10.3 의 4): 슬롯 free, 태스크 launch_failed(라운드 없음), decide workspace_failed(setup_failed, 로그
    끝). 그 decide 가 열린 동안 start-ready 는 다시 띄우지 않는다. 메인의 start 는 다시 예약한다."""

    config = SETUP_FAIL_CONFIG

    def test_setup_failure_decides_once_and_blocks_start_ready(self):
        self.hteam("start", "T-001")
        self.d.slot_step()
        self.wait_jobs()
        dec = self.decides()
        self.assertEqual(len(dec), 1, dec)
        e = dec[0]
        self.assertEqual((e["kind"], e["task"], sorted(e["detail"])), ("workspace_failed", "T-001",
                                                                       ["exit", "kind", "log", "slot", "status"]))
        self.assertEqual((e["detail"]["kind"], e["detail"]["slot"], e["detail"]["status"], e["detail"]["exit"]),
                         ("setup_failed", 1, "failed", 3))
        self.assertTrue(e["detail"]["log"].startswith(".herdr-team/state/slots/logs/slot-1-setup-"), e)
        self.assertEqual(e["files"], [e["detail"]["log"]])
        self.assertIn("설치 실패", e["tail"])
        self.assertTrue(e["summary"].startswith("slot-1 setup 이 failed(exit 3)로 끝났다."), e)
        self.assertEqual(e["commands"], ["hteam start T-001"])
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["rounds"], st["decide"]), ("launch_failed", [], e["id"]))
        self.assertEqual(self.slots()["slots"]["1"]["state"], "free")
        self.assertEqual(self.logged("slot-1 T-001 준비 setup_failed"), 1)
        code, out = self.hteam("fix", "T-001", "--note=다시 한다")  # 슬롯 없이 메인 폴더에서 띄우지 않는다(Rules 12)
        self.assertEqual((code, out["error"]["code"]), (3, "slot_not_held"), out)
        self.assertEqual(self.task_state("T-001"), st)
        self.assertFalse([c for c in self.hc_calls() if c[:1] == ["run"]])
        res = self.d.start_ready()  # 라운드 없는 launch_failed 를 곧바로 다시 띄우지 않는다(열린 decide)
        self.assertEqual([(w["task"], w["reason"]) for w in res["waiting"]], [("T-001", "decide")])
        self.d.slot_step()
        self.assertEqual(self.d.jobs, {})
        self.assertEqual(len(self.decides()), 1)
        code, out = self.hteam("start", "T-001")  # 사용자가 setup 을 고친 뒤 메인이 다시 시작한다: 처음처럼 예약하고 기다린다
        self.assertEqual((code, out["status"], out["reason"]), (0, "waiting", "slot_setup"), out)
        self.assertEqual((self.slots()["slots"]["1"]["state"], self.slots()["slots"]["1"]["task"]), ("preparing", "T-001"))
        self.d.slot_step()  # decide 가 열린 동안 관제는 그 태스크를 자동으로 다루지 않는다(메인 규칙: 처리한 뒤 answer 로 닫는다)
        self.assertEqual(self.d.jobs, {})
        self.answer(e["id"])
        self.d.slot_step()
        self.assertEqual(self.d.jobs["slot:1"]["args"], ["slot", "prepare", "T-001"])

    def test_start_options_after_setup_failure_reach_the_worker(self):
        # 준비 실패 뒤(라운드 없는 launch_failed) start 의 --model 도 pending 처럼 남겨 start-ready 가 쓴다. 문구는 실제
        # 상태다(Codex 커밋 리뷰 b916c8c P2, 태스크 리뷰 Minor 3)
        self.hteam("start", "T-001")
        self.d.slot_step()
        self.wait_jobs()
        (e,) = self.decides()
        self.p.config.write_text(WS_CONFIG, encoding="utf-8")  # 사용자가 setup 을 고쳤다
        code, out = self.hteam("start", "T-001", "--model", "sonnet")
        self.assertEqual((code, out["status"], out["reason"]), (0, "waiting", "slot_setup"), out)
        self.assertEqual(out["message"], "T-001: 작업 공간 slot-1 을 준비하는 중이다(관제가 hteam slot prepare 를 돌린다). "
                                         "launch_failed(라운드 없음) 그대로 두었다. 준비가 끝나면 관제가 띄운다")
        code, out = self.hteam("start", "T-001")  # 옵션 없이 다시 와도 앞서 받은 옵션을 잃지 않는다
        self.assertEqual((code, out["status"]), (0, "waiting"), out)
        self.answer(e["id"])
        self.d.slot_step()
        self.wait_jobs()
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["rounds"][-1]["model"]), ("working", "sonnet"))
        self.assertEqual(self.dispatch_row(st["rounds"][-1]["work"]["dispatch"])["model"], "sonnet")
        self.assertNotIn("start_cli", st)


if __name__ == "__main__":
    unittest.main()
