"""작업 공간 흐름 2(7단계, 설계 5.10.6–5.10.8): accept 의 --no-ff 병합·충돌(merge_conflict, base_merge, base 이동)·거부
(merge_pending, 10분 뒤 workspace_failed merge_blocked)·MERGE_HEAD·base_moved, 기준 병합 라운드(사양 지시, base_merge 지우기,
기준 변경이 owns 밖·quick 에 섞이지 않음), 놓기(teardown → detach → 브랜치 지우기 → free, 버린 태스크의 dirty, 재확인의 이어
하기), 준비 중 drop, slot reset(큐 명령), 마무리 full 의 슬롯, status 의 workspace, shared 회귀.

실제 git worktree 를 시험 임시 저장소 안에 만든다. 관제는 이 프로세스 안(make_drive)이고 놓기 자식은 실제 hteam 하위 프로세스다
(설계 8.8)."""
import json
import shutil
import subprocess
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from tests.helpers import BASE_CONFIG, WS_CONFIG, TeamCase
from hteam import gitio, queue, state, workspace
from hteam.paths import Project

# setup·teardown 도우미(시험 폴더 밖 $OUT_DIR): 슬롯·작업 루트를 남긴다. setup 은 무시된 폴더(node_modules)에 표시를 쌓는다
SETUP_SH = """[ -f "$OUT_DIR/setup-fail" ] && { echo "설치 실패: $HTEAM_SLOT"; exit 7; }
printf '%s|%s\\n' "$HTEAM_SLOT" "$(pwd -P)" >> "$OUT_DIR/setup.txt"
mkdir -p node_modules && echo "$HTEAM_SLOT" >> node_modules/marker
"""
TEARDOWN_SH = """printf '%s|%s|%s\\n' "$HTEAM_SLOT" "$(pwd -P)" "$HT_PORT" >> "$OUT_DIR/teardown.txt"
[ -f "$OUT_DIR/teardown-fail" ] && { echo "정리 실패"; exit 4; }
exit 0
"""
BASE_MERGE = ("- 이 라운드는 기준 커밋 `{sha}` 를 이 브랜치에 병합한다: `git merge --no-ff --no-commit {sha}` 뒤 충돌을 풀고 "
              "푼 파일을 `git add -- <파일>` 한다. `git diff --cached --name-only` 가 병합과 푼 파일만 담는지 본 뒤 경로를 "
              "지정하지 않은 `git commit -m \"[{tid}] 기준 병합: {sha7}\"` 로 커밋한다(병합 중에는 git 이 경로 지정 커밋을 "
              "받지 않는다. 이 커밋만 작업 규칙 5.5 의 경로 지정 예외다). 그 밖의 병합·rebase·push 는 하지 않는다.")
RESUME = "앞 워커가 시작한 병합이 남아 있다. 이어서 푼다."
NORMAL_SECOND = "리뷰가 승인하면 관제가 병합한다"  # 작업 공간 절 둘째 줄(Task 4, 설계 5.10.5)의 끝


def ws_config(extra: str = "") -> str:
    """WS_CONFIG 의 [workspace] 에 setup·teardown(TOML 리터럴 문자열)과 extra 줄을 더한다."""
    lines = "setup = 'sh \"$OUT_DIR/setup.sh\"'\nteardown = 'sh \"$OUT_DIR/teardown.sh\"'\n" + extra
    return WS_CONFIG.replace("slots = 2\n", "slots = 2\n" + lines)


def ago(seconds: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


class MergeCase(TeamCase):
    """작업 공간 프로젝트(setup·teardown 도우미, node_modules 는 git 제외)와 이 프로세스 안의 관제. 기준 브랜치 main 에
    src/a/core.py("a")·docs/other.md("o") 가 있고, T-001(developer, owns src/a/**) 사양이 커밋돼 있다."""

    config_text = None  # None 이면 ws_config()
    gate = False

    def setUp(self):
        super().setUp()
        self.out = self.tmp / "out"
        self.out.mkdir()
        (self.out / "setup.sh").write_text(SETUP_SH, encoding="utf-8")
        (self.out / "teardown.sh").write_text(TEARDOWN_SH, encoding="utf-8")
        self.env["OUT_DIR"] = str(self.out)
        self.init_project(self.config_text or ws_config())
        self.commit(".gitignore", ".herdr-team/state/\nnode_modules/\n", "chore: node_modules 제외")
        self.commit("src/a/core.py", "a\n", "chore: core")
        self.commit("docs/other.md", "o\n", "chore: other")
        if self.gate:
            self.use_gate()
        self.run_id = self.setup_run()
        self.p = Project(self.proj)
        self.write_spec("T-001", owns="src/a/**")
        self._patcher = self.in_drive()  # self.env(OUT_DIR·FAKE_DIR)를 다 채운 뒤 건다. 관제의 자식이 물려받는다
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self.d = self.make_drive()

    def tearDown(self):
        for job in list(self.d.jobs.values()):
            if job["proc"].poll() is None:
                job["proc"].kill()
            job["proc"].wait(timeout=30)
        super().tearDown()

    # --- 흐름 ---
    def approved(self, tid: str = "T-001", files: dict | None = None, *, ws: bool = True) -> None:
        """시작(작업 공간이면 ws_start) → 작업 커밋·done → review → 리뷰어 APPROVE → review-finish = approved."""
        if ws:
            self.ws_start(tid)
        else:
            code, out = self.hteam("start", tid)
            self.assertEqual(code, 0, out)
        code, out = self.act_work(tid, files if files is not None else {"src/a/x.py": "x = 1\n"})
        self.assertEqual(code, 0, out)
        code, out = self.hteam("review", tid)
        self.assertEqual((code, out.get("status")), (0, "reviewing"), out)
        code, out = self.act_review(tid, "APPROVE")
        self.assertEqual(code, 0, out)
        code, out = self.hteam("review-finish", tid)
        self.assertEqual((code, out.get("status")), (0, "approved"), out)

    def wait_jobs(self, limit: float = 60.0) -> None:
        deadline = time.monotonic() + limit
        while True:
            self.d.reap_jobs()
            if not self.d.jobs:
                return
            if time.monotonic() > deadline:
                self.fail(f"자식이 끝나지 않았다: {sorted(self.d.jobs)}")
            time.sleep(0.05)

    def worker_base_merge(self, base: str, resolved: dict, *, commit: bool = True) -> None:
        """작업 워커의 기준 병합(사양 지시대로, 슬롯 1): --no-commit 병합(충돌) → 푼 파일 git add → 경로 지정 없는 커밋."""
        slot = self.slot_root(1)
        proc = subprocess.run(["git", "-C", str(slot), "merge", "--no-ff", "--no-commit", base], capture_output=True,
                              text=True, env=self.env)
        self.assertNotEqual(proc.returncode, 0, proc.stdout)  # 충돌로 멈춘다
        if not commit:
            return
        for rel, text in resolved.items():
            (slot / rel).write_text(text, encoding="utf-8")
            self.git_at(slot, "add", "--", rel)
        self.git_at(slot, "commit", "-q", "-m", f"[T-001] 기준 병합: {base[:7]}")

    # --- 보기 ---
    def record(self, n: int) -> dict:
        return {**workspace.SLOT_DEFAULT, **self.slots()["slots"].get(str(n), {})}

    def subjects(self, n: int = 1) -> list[str]:
        return self.git("log", "--first-parent", f"-{n}", "--format=%s").splitlines()

    def parents(self, rev: str = "HEAD") -> list[str]:
        return self.git("rev-list", "--parents", "-n", "1", rev).split()[1:]

    def detached(self, root) -> bool:
        return self.git_at(root, "rev-parse", "--abbrev-ref", "HEAD").strip() == "HEAD"

    def has_branch(self, name: str) -> bool:
        return bool(self.git("branch", "--list", name).strip())

    def merging(self, root) -> bool:
        return subprocess.run(["git", "-C", str(root), "rev-parse", "-q", "--verify", "MERGE_HEAD"], capture_output=True,
                              env=self.env).returncode == 0

    def lines(self, name: str) -> list[str]:
        path = self.out / name
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def decides(self, kind: str | None = None) -> list[dict]:
        return [e for e in self.outbox_items() if e["type"] == "decide" and (kind is None or e["kind"] == kind)]

    def progress(self) -> list[str]:
        return [e["body"] for e in self.outbox_items() if e["type"] == "progress"]

    def log_text(self) -> str:
        path = self.drive_dir / "drive.log"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def spec_text(self, n: int, tid: str = "T-001") -> str:
        return (self.state_dir / "tasks" / tid / f"r{n}-work.md").read_text(encoding="utf-8")


class MergeTest(MergeCase):
    """accept 의 병합 성공과 놓기(설계 5.10.6, 6.4 의 7단계 줄)."""

    def test_accept_merges_no_ff_then_releases_the_slot(self):
        self.approved()
        tip = self.git("rev-parse", "herdr/T-001").strip()
        before = self.head()
        res = self.d.accept_task("T-001")
        head = self.head()
        self.assertEqual((res["status"], res["merge"]), ("done", head), res)
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["workspace"]["merge"]), ("done", head))
        self.assertNotIn("merge_wait", st)
        # 병합 뒤 그 태스크의 파일은 기준 브랜치(메인 폴더)에서 읽는다. 슬롯은 놓은 뒤 다른 태스크가 다시 쓴다(Rules 1a)
        self.assertEqual(workspace.task_root(Project(self.proj), st), self.proj)
        self.assertEqual(self.subjects(1), ["[T-001] merge: 앱 만들기"])
        self.assertEqual(self.parents(), [before, tip])  # --no-ff: 기준과 태스크 브랜치, 부모 둘
        self.assertEqual((self.proj / "src/a/x.py").read_text(encoding="utf-8"), "x = 1\n")
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertIn(f"T-001 병합 {head[:7]}", self.log_text())
        self.assertIn("slot:1", self.d.jobs)  # after_accept 가 놓기 자식을 띄웠다
        self.wait_jobs()
        rec = self.record(1)
        self.assertEqual((rec["state"], rec["task"], rec["setup_done"]), ("free", None, None))
        slot = self.slot_root(1)
        self.assertTrue((slot / "node_modules" / "marker").is_file())  # 슬롯 폴더와 무시된 파일은 지우지 않는다
        self.assertTrue(self.detached(slot))
        self.assertFalse(self.has_branch("herdr/T-001"))  # 병합한 브랜치는 지운다
        self.assertEqual(self.lines("teardown.txt"), [f"1|{slot}|8110"])  # setup 과 같은 환경(슬롯 env)
        log = self.log_text()
        self.assertIn("slot-1 T-001 놓기 시작", log)
        self.assertIn("slot-1 T-001 놓기 free", log)

    def test_merged_task_retest_runs_in_main_with_slot_zero_env(self):
        # 병합한 태스크의 작업 루트는 메인 폴더다. 그 재시험의 env 도 메인 폴더 값(슬롯 0)이다: 놓은 슬롯은 다른 태스크가 다시
        # 쓰므로 옛 슬롯 값이면 같은 DB·포트를 건드린다(설계 5.7, Codex 브랜치 리뷰 P2)
        self.use_gate(full='mkdir -p "$FAKE_DIR"; printf "%s %s\\n" "$HTEAM_SLOT" "$HT_PORT" >> "$FAKE_DIR/env.txt"; '
                           'fake-test --all')
        self.approved()
        self.assertEqual(self.d.accept_task("T-001")["status"], "done")
        self.wait_jobs()
        code, out = self.hteam("test", "T-001", "--full")
        self.assertEqual((code, out["status"]), (0, "passed"), out)
        self.assertEqual(self.gate_calls()[-1]["cwd"], str(self.proj))
        self.assertEqual((self.tmp / "fake" / "env.txt").read_text(encoding="utf-8").splitlines(), ["0 8100"])

    def test_release_after_cli_accept_and_after_a_dead_release_child(self):
        self.approved()
        code, out = self.hteam("accept", "T-001")  # 관제 안의 CLI accept 는 병합까지(놓기는 관제가 한다)
        self.assertEqual((code, out["status"]), (0, "done"), out)
        self.assertEqual(out["merge"], self.head())
        self.assertEqual((self.record(1)["state"], self.record(1)["task"]), ("busy", "T-001"))
        code, out = self.hteam("slot", "release", "T-001", env={"HTEAM_TEST_DIE_AT": "slot_release_teardown"})
        self.assertEqual(code, 137, out)
        self.assertEqual((self.record(1)["state"], self.record(1)["task"]), ("busy", "T-001"))
        self.d.reconcile()  # 태스크는 done 인데 슬롯은 busy: 재확인이 놓기를 잇는다
        self.assertIn("slot:1", self.d.jobs)
        self.wait_jobs()
        self.assertEqual((self.record(1)["state"], self.record(1)["task"]), ("free", None))
        self.assertEqual(len(self.lines("teardown.txt")), 2)  # 이어 한 놓기는 teardown 을 다시 돈다
        self.assertFalse(self.has_branch("herdr/T-001"))
        code, out = self.hteam("slot", "release", "T-001")  # 이미 놓았다
        self.assertEqual((code, out["slot"], out["state"]), (0, None, None), out)

    def test_teardown_failure_is_reported_and_release_goes_on(self):
        self.approved()
        (self.out / "teardown-fail").write_text("", encoding="utf-8")
        self.d.accept_task("T-001")
        self.wait_jobs()
        self.assertEqual(self.record(1)["state"], "free")
        [line] = [b for b in self.progress() if "teardown" in b]
        self.assertTrue(line.startswith("slot-1 T-001 teardown 이 failed(exit 4)로 끝났다(놓기는 마쳤다). 로그: "), line)
        self.assertIn("slot-1 T-001 놓기 free (teardown failed)", self.log_text())

    def test_release_refuses_open_tasks_and_main(self):
        self.approved()
        code, out = self.hteam("slot", "release", "T-001")  # 아직 approved: 놓지 않는다
        self.assertEqual((code, out["error"]["code"]), (3, "task_open"), out)
        code, out = self.hteam("slot", "release", "T-001", as_="main")
        self.assertEqual((code, out["error"]["code"]), (5, "drive_only"), out)


class HandoffTest(MergeCase):
    """놓기가 끝난 슬롯을 다음 재확인까지 비워 두지 않는다(최종 리뷰 M1): 놓기 자식이 free 를 쓰면 관제가 그 자리에서
    start-ready 를 돌려 빈 슬롯을 기다리던 태스크가 슬롯을 예약하고, 그 준비 자식도 바로 뜬다."""

    config_text = ws_config().replace("slots = 2\n", "slots = 1\n")

    def test_waiting_task_takes_the_slot_when_release_ends(self):
        self.write_spec("T-002", owns="src/b/**")
        self.approved()
        code, out = self.hteam("start", "T-002")
        self.assertEqual((code, out["status"], out["reason"]), (0, "waiting", "slot"), out)
        self.assertEqual(self.d.accept_task("T-001")["status"], "done")
        self.assertIn("slot:1", self.d.jobs)  # 놓기 자식
        self.wait_jobs()  # 재확인(reconcile)을 부르지 않는다
        log = self.log_text()
        self.assertIn("slot-1 T-001 놓기 free", log)
        self.assertIn("slot-1 T-002 준비 시작", log)
        self.assertEqual(self.record(1)["task"], "T-002")
        self.assertEqual(self.task_state("T-002")["workspace"]["slot"], 1)


class ConflictTest(MergeCase):
    """충돌: abort·changes·base_merge·base 이동·decide merge_conflict, 기준 병합 라운드(설계 5.10.6)."""

    gate = True

    def conflicted(self) -> str:
        """T-001 이 core.py 를 고쳐 승인된 사이 사람이 기준 브랜치에서 같은 줄과 owns 밖 파일을 고쳤다. accept 가 충돌한다.
        충돌 때의 기준 HEAD 를 돌려준다."""
        self.approved(files={"src/a/core.py": "task\n"})
        self.commit("src/a/core.py", "main\n", "사람: core")
        base = self.commit("docs/other.md", "o2\n", "사람: other")
        self.res = self.d.accept_task("T-001")
        return base

    def test_conflict_aborts_moves_base_and_decides(self):
        base = self.conflicted()
        conflict = {"base": base, "files": ["src/a/core.py"]}
        self.assertEqual((self.res["status"], self.res["merge_conflict"]), ("changes", conflict), self.res)
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["round"], st["base_merge"], st["base"]), ("changes", 1, base, base))
        self.assertEqual(st["rounds"][-1]["merge_conflict"], conflict)
        self.assertIsNone(st["workspace"]["merge"])
        self.assertEqual(self.head(), base)  # 되돌렸다
        self.assertFalse(self.merging(self.proj))
        self.assertEqual(self.git("status", "--porcelain"), "")
        [dec] = self.decides("merge_conflict")
        self.assertEqual((dec["task"], dec["detail"]), ("T-001", conflict))
        self.assertEqual(dec["commands"], ['hteam fix T-001 --note "<충돌을 어떻게 풀지 사용자 지시>"', "hteam drop T-001"])
        self.assertIn("T-001 병합 충돌: src/a/core.py", self.log_text())
        self.assertEqual((self.record(1)["state"], self.record(1)["task"]), ("busy", "T-001"))  # 슬롯은 태스크가 쥔다
        self.assertEqual(self.d.jobs, {})  # 놓지 않는다
        self.d.reconcile()  # 열린 decide: 관제가 스스로 fix 하지 않는다
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["round"]), ("changes", 1))

    def test_recorded_rerere_resolution_is_still_a_conflict(self):
        # rerere(enabled·autoupdate)에 같은 충돌의 해결이 기록돼 있으면 git 이 그 해결을 스테이징해 충돌 파일이 비지만 exit 1·
        # MERGE_HEAD 가 남는다. 훅 거부로 오판하지 않게 hteam 의 병합은 그 실행에만 rerere 를 끈다(리뷰 반영 2 I2)
        self.git("config", "rerere.enabled", "true")
        self.git("config", "rerere.autoupdate", "true")
        self.approved(files={"src/a/core.py": "task\n"})
        base = self.commit("src/a/core.py", "main\n", "사람: core")
        proc = subprocess.run(["git", "-C", str(self.proj), "merge", "--no-ff", "-m", "사람의 병합", "herdr/T-001"],
                              capture_output=True, text=True, env=self.env)
        self.assertNotEqual(proc.returncode, 0, proc.stdout)  # 사람이 같은 충돌을 한 번 풀어 rerere 가 기록했다
        (self.proj / "src/a/core.py").write_text("사람이 푼 것\n", encoding="utf-8")
        self.git("add", "--", "src/a/core.py")
        self.git("commit", "-q", "--no-edit")
        self.git("reset", "-q", "--hard", base)  # 그 병합은 버렸다
        self.assertTrue(any((self.proj / ".git" / "rr-cache").iterdir()))
        res = self.d.accept_task("T-001")
        conflict = {"base": base, "files": ["src/a/core.py"]}
        self.assertEqual((res["status"], res["merge_conflict"]), ("changes", conflict), res)
        self.assertEqual(self.decides("workspace_failed"), [])
        self.assertEqual(self.head(), base)
        self.assertFalse(self.merging(self.proj))
        self.assertEqual(self.git("config", "rerere.enabled").strip(), "true")  # 사용자 설정은 바꾸지 않는다

    def cli_conflicted(self) -> str:
        """conflicted() 와 같은 충돌을 관제 안의 CLI accept 로 만든다: 충돌 전이는 쓰고 decide 는 올리지 않는다(after_accept 를
        거치지 않는다). 충돌 전이 뒤 decide 를 올리기 전에 관제가 죽은 것과 같다. 충돌 때의 기준 HEAD 를 돌려준다."""
        self.approved(files={"src/a/core.py": "task\n"})
        self.commit("src/a/core.py", "main\n", "사람: core")
        base = self.commit("docs/other.md", "o2\n", "사람: other")
        code, out = self.hteam("accept", "T-001")
        self.assertEqual((code, out["status"]), (0, "changes"), out)
        self.assertEqual(self.decides("merge_conflict"), [])
        return base

    def test_conflict_without_decide_is_decided_by_reconcile(self):
        base = self.cli_conflicted()
        self.d.reconcile()
        [dec] = self.decides("merge_conflict")
        self.assertEqual((dec["task"], dec["detail"]), ("T-001", {"base": base, "files": ["src/a/core.py"]}))
        self.assertEqual(self.task_state("T-001")["round"], 1)  # 자동 fix 를 하지 않는다
        self.d.reconcile()  # 이번에는 outbox 에 이 충돌의 decide 가 있다
        self.assertEqual(len(self.decides("merge_conflict")), 1)

    def test_answered_question_in_the_round_does_not_hide_the_conflict(self):
        # 같은 라운드에 답한 다른 decide(worker_question)의 decide_round 가 남아 있어도 재확인이 충돌 decide 를 올린다
        # (outbox 의 kind·task·detail 로 가린다, Codex 계획 리뷰 r1)
        self.ws_start("T-001")
        oid = self.d.decide("worker_question", "T-001", "어느 쪽으로 하나", question="어느 쪽으로 하나")
        (self.state_dir / "answers").mkdir(parents=True, exist_ok=True)
        (self.state_dir / "answers" / f"{oid}.json").write_text(
            json.dumps({"id": oid, "answer": "앞쪽", "at": "2026-11-12T00:00:00Z"}), encoding="utf-8")
        self.assertEqual(self.task_state("T-001")["decide_round"], 1)
        code, out = self.act_work("T-001", {"src/a/core.py": "task\n"})
        self.assertEqual(code, 0, out)
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out.get("status")), (0, "reviewing"), out)
        self.assertEqual(self.act_review("T-001", "APPROVE")[0], 0)
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual((code, out.get("status")), (0, "approved"), out)
        self.commit("src/a/core.py", "main\n", "사람: core")
        code, out = self.hteam("accept", "T-001")  # 충돌 전이만 쓴다(decide 없음)
        self.assertEqual((code, out["status"]), (0, "changes"), out)
        st = self.task_state("T-001")
        self.assertEqual((st["round"], st["decide_round"]), (1, 1))  # 앞 질문의 표시가 남았다
        self.d.reconcile()
        [dec] = self.decides("merge_conflict")
        self.assertEqual(dec["detail"]["files"], ["src/a/core.py"])
        self.assertEqual(self.task_state("T-001")["round"], 1)

    def test_base_merge_round_instruction_review_and_merge(self):
        base = self.conflicted()
        self.assertIn(NORMAL_SECOND, self.spec_text(1))
        code, out = self.hteam("fix", "T-001", "--note=우리 쪽(task)과 main 을 합친다")
        self.assertEqual((code, out.get("round")), (0, 2), out)
        self.assertEqual((self.record(1)["state"], self.record(1)["task"]), ("busy", "T-001"))  # 같은 슬롯·같은 브랜치
        rd = self.task_state("T-001")["rounds"][-1]
        self.assertEqual((rd["base_merge"], rd.get("merge_resume")), (base, None))
        r2 = self.spec_text(2)
        self.assertIn(BASE_MERGE.format(sha=base, sha7=base[:7], tid="T-001"), r2)
        self.assertNotIn(NORMAL_SECOND, r2)
        self.assertNotIn(RESUME, r2)
        self.worker_base_merge(base, {"src/a/core.py": "task+main\n"})
        code, out = self.act_work("T-001", {})  # 보고서만 고친 r2 작업 커밋과 done
        self.assertEqual(code, 0, out)
        calls = len(self.gate_calls())
        code, out = self.hteam("review", "T-001")
        # 기준에서 들어온 docs/other.md 는 owns 밖 변경으로 잡히지 않는다(사전 검사 통과)
        self.assertEqual((code, out.get("status")), (0, "reviewing"), out)
        self.assertNotIn("base_merge", self.task_state("T-001"))  # 기준을 부모로 가진 [T-001] 커밋을 봤다
        self.assertEqual(len(self.gate_calls()), calls + 1)  # code_head 가 바뀌어 quick 을 다시 돌았다
        self.assertEqual(self.gate_calls()[-1]["args"], ["src/a/core.py"])  # quick 은 기준과 브랜치의 차이만
        code, out = self.act_review("T-001", "APPROVE")
        self.assertEqual(code, 0, out)
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual((code, out["status"]), (0, "approved"), out)
        res = self.d.accept_task("T-001")
        self.assertEqual(res["status"], "done", res)
        self.assertEqual(self.subjects(1), ["[T-001] merge: 앱 만들기"])
        self.assertEqual((self.proj / "src/a/core.py").read_text(encoding="utf-8"), "task+main\n")
        self.assertEqual((self.proj / "docs/other.md").read_text(encoding="utf-8"), "o2\n")

    def test_left_merge_head_keeps_base_merge_and_adds_resume(self):
        base = self.conflicted()
        self.assertEqual(self.hteam("fix", "T-001", "--note=합친다")[0], 0)
        self.worker_base_merge(base, {}, commit=False)  # 병합을 시작하고 커밋 전에 끝났다
        code, out = self.act_work("T-001", {}, outcome="failed", commit=False)
        self.assertEqual(code, 0, out)
        code, out = self.hteam("fix", "T-001", "--note=이어서 한다")
        self.assertEqual((code, out.get("round")), (0, 3), out)
        st = self.task_state("T-001")
        self.assertEqual((st["base_merge"], st["rounds"][-1]["merge_resume"]), (base, True))
        self.assertIn(BASE_MERGE.format(sha=base, sha7=base[:7], tid="T-001") + " " + RESUME, self.spec_text(3))

    def test_abort_that_leaves_merge_head_is_merge_blocked(self):
        self.approved(files={"src/a/core.py": "task\n"})
        self.commit("src/a/core.py", "main\n", "사람: core")
        with mock.patch.object(gitio, "merge_abort", lambda root: None):  # abort 가 듣지 않았다
            self.assertIsNone(self.d.accept_task("T-001"))
        [dec] = self.decides("workspace_failed")
        self.assertEqual((dec["task"], dec["detail"]["kind"]), ("T-001", "merge_blocked"))
        st = self.task_state("T-001")
        self.assertEqual(st["status"], "approved")
        self.assertNotIn("base_merge", st)
        self.assertEqual(self.decides("merge_conflict"), [])
        self.git("merge", "--abort")

    def test_base_merge_that_keeps_the_task_side_reruns_quick(self):
        # 충돌을 태스크 쪽 내용으로 풀면 병합 커밋의 바뀐 파일(기준 쪽 docs/other.md)이 path_reader 에서 모두 걸러진다. 그래도
        # 병합한 트리는 새 기준을 담으므로 병합 전 quick 통과를 다시 쓰지 않는다(Codex 커밋 리뷰 P2, 리뷰 반영 H3)
        base = self.conflicted()
        self.assertEqual(self.hteam("fix", "T-001", "--note=우리 쪽(task)을 지킨다")[0], 0)
        self.worker_base_merge(base, {"src/a/core.py": "task\n"})
        merge = self.git_at(self.slot_root(1), "rev-parse", "HEAD").strip()
        self.assertEqual(self.act_work("T-001", {})[0], 0)  # 보고서만 고친 r2 작업 커밋
        calls = len(self.gate_calls())
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out.get("status")), (0, "reviewing"), out)
        self.assertEqual(len(self.gate_calls()), calls + 1)  # 병합 전 통과 기록을 다시 쓰지 않았다
        self.assertEqual(self.gate_calls()[-1]["args"], ["src/a/core.py"])
        quick = json.loads((self.state_dir / "tests" / "T-001.json").read_text(encoding="utf-8"))["quick"]
        self.assertEqual(quick["head"], merge)  # code_head 가 기준 병합 커밋이다


class RefuseTest(MergeCase):
    """거부·MERGE_HEAD·base_moved(설계 5.10.6): 상태를 바꾸지 않고 다시 시도, 10분 뒤 한 번 올린다."""

    def test_refused_merge_waits_then_is_blocked_once(self):
        self.approved(files={"src/a/new.py": "n = 1\n"})
        (self.proj / "src/a/new.py").write_text("사람이 둔 파일\n", encoding="utf-8")  # 병합이 덮을 커밋 안 된 파일
        before = self.head()
        self.assertIsNone(self.d.accept_task("T-001"))
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["merge_wait"]["asked"]), ("approved", []))
        self.assertEqual(self.head(), before)
        self.assertFalse(self.merging(self.proj))
        self.assertEqual(self.decides(), [])
        self.assertEqual(self.log_text().count("T-001 병합 거부:"), 1)
        self.assertIsNone(self.d.accept_task("T-001"))
        self.assertEqual(self.log_text().count("T-001 병합 거부:"), 1)  # 첫 거부만 남긴다
        code, out = self.hteam("accept", "T-001")
        self.assertEqual((code, out["error"]["code"]), (3, "merge_pending"), out)
        self.assertIn("src/a/new.py", out["output"])
        with state.edit(self.p, "T-001") as cur:
            cur["merge_wait"]["since"] = ago(workspace.MERGE_BLOCKED_S + 1)
        self.assertIsNone(self.d.accept_task("T-001"))
        [dec] = self.decides("workspace_failed")
        self.assertEqual((dec["task"], dec["detail"]["kind"]), ("T-001", "merge_blocked"))
        self.assertTrue(dec["summary"].startswith("T-001 병합이 10분 넘게 거부됐다: "), dec["summary"])
        self.assertIsNone(self.d.accept_task("T-001"))
        self.assertEqual(len(self.decides("workspace_failed")), 1)  # 한 번만
        (self.proj / "src/a/new.py").unlink()
        res = self.d.accept_task("T-001")
        self.assertEqual(res["status"], "done", res)
        self.assertNotIn("merge_wait", self.task_state("T-001"))

    def test_user_merge_autostash_does_not_hide_uncommitted_changes(self):
        # 사용자 저장소 설정 merge.autoStash=true 면 git 은 stash → 병합 → 재적용 충돌에도 exit 0 이다. hteam 의 병합은 그
        # 실행에만 autoStash 를 끈다: 겹치는 커밋 안 된 변경이 있으면 거부(merge_pending)로 가고 메인 파일은 그대로다
        self.approved(files={"src/a/core.py": "task\n"})
        self.git("config", "merge.autoStash", "true")  # 시험 임시 저장소의 설정(전역 아님)
        (self.proj / "src/a/core.py").write_text("사람이 고친 줄\n", encoding="utf-8")
        before = self.head()
        self.assertIsNone(self.d.accept_task("T-001"))
        self.assertEqual(self.task_state("T-001")["status"], "approved")
        self.assertEqual(self.head(), before)
        self.assertFalse(self.merging(self.proj))
        self.assertEqual((self.proj / "src/a/core.py").read_text(encoding="utf-8"), "사람이 고친 줄\n")
        self.assertEqual(self.git("status", "--porcelain", "--", "src"), " M src/a/core.py\n")
        self.assertEqual(self.git("stash", "list"), "")
        self.assertEqual(self.log_text().count("T-001 병합 거부:"), 1)
        code, out = self.hteam("accept", "T-001")
        self.assertEqual((code, out["error"]["code"]), (3, "merge_pending"), out)

    def test_unfinished_merge_in_main_is_blocked_at_once(self):
        self.approved()
        before = self.head()
        (self.proj / ".git" / "MERGE_HEAD").write_text(before + "\n", encoding="utf-8")
        self.assertIsNone(self.d.accept_task("T-001"))
        [dec] = self.decides("workspace_failed")
        self.assertEqual(dec["detail"]["kind"], "merge_blocked")
        self.assertEqual(dec["summary"], "메인 폴더에 끝나지 않은 병합(MERGE_HEAD)이 있어 T-001 를 병합하지 않았다")
        self.assertEqual((self.task_state("T-001")["status"], self.head()), ("approved", before))
        (self.proj / ".git" / "MERGE_HEAD").unlink()
        self.assertEqual(self.d.accept_task("T-001")["status"], "done")

    def test_main_folder_on_another_branch_is_base_moved(self):
        self.approved()
        self.git("switch", "-q", "-c", "side")
        self.assertIsNone(self.d.accept_task("T-001"))
        [dec] = self.decides("workspace_failed")
        self.assertEqual((dec["detail"]["kind"], dec["detail"]["branch"], dec["detail"]["base_branch"]),
                         ("base_moved", "side", "main"))
        self.assertEqual(self.task_state("T-001")["status"], "approved")
        self.assertIn("T-001 병합 못 함(base_moved): ", self.log_text())
        self.git("switch", "-q", "main")
        self.assertEqual(self.d.accept_task("T-001")["status"], "done")
        self.assertEqual(self.git("branch", "--show-current").strip(), "main")

    def test_hook_rejected_merge_is_blocked_at_once(self):
        # commit-msg 훅이 병합 커밋을 거부하면 MERGE_HEAD 가 남고 충돌 파일은 없다. 충돌이 아니라 병합 거부다: 기다려도
        # 풀리지 않으므로 바로 merge_blocked 를 한 번 올리고 상태·base 를 바꾸지 않는다(리뷰 반영 H7). --no-verify 는 쓰지 않는다
        self.approved()
        st0 = self.task_state("T-001")
        hook = self.proj / ".git" / "hooks" / "commit-msg"  # 슬롯 worktree 도 같은 훅을 쓰므로 작업 커밋 뒤에 둔다
        hook.parent.mkdir(exist_ok=True)
        hook.write_text('#!/bin/sh\necho "x" >> "$OUT_DIR/hook.txt"\necho "커밋 메시지 규칙 위반: $(head -n 1 "$1")" >&2\n'
                        'exit 1\n', encoding="utf-8")
        hook.chmod(0o755)
        before = self.head()
        self.assertIsNone(self.d.accept_task("T-001"))
        self.assertEqual(len(self.lines("hook.txt")), 1)  # 훅을 건너뛰지 않았다
        [dec] = self.decides("workspace_failed")
        self.assertEqual((dec["task"], dec["detail"]["kind"], dec["detail"]["slot"]), ("T-001", "merge_blocked", 1))
        self.assertTrue(dec["summary"].startswith("T-001 병합 커밋을 git 훅이 거부했다"), dec["summary"])
        self.assertIn("커밋 메시지 규칙 위반: [T-001] merge: 앱 만들기", dec["tail"])
        self.assertEqual(self.decides("merge_conflict"), [])
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["round"], st["base"]), ("approved", st0["round"], st0["base"]))
        self.assertNotIn("base_merge", st)
        self.assertEqual(self.head(), before)
        self.assertFalse(self.merging(self.proj))
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertIsNone(self.d.accept_task("T-001"))
        self.assertEqual(len(self.decides("workspace_failed")), 1)  # 한 번만
        hook.unlink()
        self.assertEqual(self.d.accept_task("T-001")["status"], "done")

    def test_hook_error_survives_a_long_merge_output(self):
        # 70개 파일을 자동 병합하면 stdout 의 `Auto-merging` 줄이 tail(60줄)을 채운다. 훅의 stderr 끝을 따로 둔다(리뷰 반영 2 I3)
        names = [f"src/a/m{i:02}.py" for i in range(70)]
        for rel in names:
            (self.proj / rel).write_text("1\n2\n3\n4\n5\n6\n7\n", encoding="utf-8")
        self.git("add", "--", "src/a")
        self.git("commit", "-q", "-m", "chore: 파일 70개")
        self.approved(files={rel: "task\n2\n3\n4\n5\n6\n7\n" for rel in names})
        for rel in names:
            (self.proj / rel).write_text("1\n2\n3\n4\n5\n6\nmain\n", encoding="utf-8")
        self.git("commit", "-q", "-am", "사람: 끝 줄")
        hook = self.proj / ".git" / "hooks" / "commit-msg"
        hook.parent.mkdir(exist_ok=True)
        hook.write_text('#!/bin/sh\necho "훅 오류 첫 줄: 병합 메시지 규칙" >&2\necho "훅 오류 둘째 줄: 이슈 번호가 없다" >&2\n'
                        "exit 1\n", encoding="utf-8")
        hook.chmod(0o755)
        self.assertIsNone(self.d.accept_task("T-001"))
        [dec] = self.decides("workspace_failed")
        self.assertEqual(dec["detail"]["kind"], "merge_blocked")
        self.assertIn("훅 오류 첫 줄: 병합 메시지 규칙\n훅 오류 둘째 줄: 이슈 번호가 없다", dec["tail"])
        self.assertNotIn("Auto-merging", dec["tail"])
        self.assertIn("): 훅 오류 첫 줄: 병합 메시지 규칙", dec["summary"])
        self.assertFalse(self.merging(self.proj))
        hook.unlink()


class DropReleaseTest(MergeCase):
    """drop 뒤 놓기와 준비 중 drop(설계 5.10.6·5.10.9)."""

    def test_dropped_task_keeps_its_branch_and_frees_the_slot(self):
        self.ws_start("T-001")
        self.assertEqual(self.act_work("T-001", {"src/a/x.py": "x\n"})[0], 0)
        code, out = self.hteam("drop", "T-001")
        self.assertEqual((code, out["status"]), (0, "dropped"), out)
        self.d.reconcile()
        self.wait_jobs()
        rec = self.record(1)
        self.assertEqual((rec["state"], rec["task"]), ("free", None))
        self.assertTrue(self.has_branch("herdr/T-001"))  # 버린 태스크의 브랜치는 기록으로 남긴다
        self.assertTrue(self.detached(self.slot_root(1)))
        self.assertEqual(len(self.lines("teardown.txt")), 1)

    def test_dropped_task_with_uncommitted_changes_leaves_the_slot_dirty(self):
        self.ws_start("T-001")
        (self.slot_root(1) / "src/a/tmp.py").write_text("tmp\n", encoding="utf-8")
        code, out = self.hteam("drop", "T-001", "--force")
        self.assertEqual((code, out["status"]), (0, "dropped"), out)
        self.d.reconcile()
        self.wait_jobs()
        rec = self.record(1)
        self.assertEqual((rec["state"], rec["task"]), ("dirty", None))
        [line] = [b for b in self.progress() if b.startswith("slot-1 에 커밋 안 된 변경이 남아")]
        self.assertEqual(line, "slot-1 에 커밋 안 된 변경이 남아 dirty 로 두었다(T-001 를 버렸다): src/a/tmp.py. "
                               "사용자가 버려도 된다고 하면 hteam slot reset 1")
        self.assertIn("slot-1 T-001 놓기 dirty", self.log_text())

    def test_drop_during_base_merge_leaves_the_slot_dirty_for_reset(self):
        # 기준 병합 라운드 도중(슬롯에 MERGE_HEAD) drop: git 은 병합 중 switch 를 거부하므로 switch 하지 않고 dirty 로 남긴다
        # (Rules 7, Codex 계획 리뷰 r1). 재확인은 놓기를 되풀이하지 않고 slot reset 이 정리한다
        self.approved(files={"src/a/core.py": "task\n"})
        self.commit("src/a/core.py", "main\n", "사람: core")
        base = self.commit("docs/other.md", "o2\n", "사람: other")
        self.assertEqual(self.d.accept_task("T-001")["status"], "changes")
        self.assertEqual(self.hteam("fix", "T-001", "--note=합친다")[0], 0)
        self.worker_base_merge(base, {}, commit=False)  # 워커가 병합을 시작한 채 끝났다(충돌이 남았다)
        slot = self.slot_root(1)
        self.assertTrue(self.merging(slot))
        code, out = self.hteam("drop", "T-001", "--force")
        self.assertEqual((code, out["status"]), (0, "dropped"), out)
        self.d.reconcile()
        self.wait_jobs()
        rec = self.record(1)
        self.assertEqual((rec["state"], rec["task"]), ("dirty", None))
        self.assertTrue(self.merging(slot))  # 병합 상태·브랜치·파일은 그대로 둔다(사용자가 보고 정한다)
        self.assertEqual(self.git_at(slot, "branch", "--show-current").strip(), "herdr/T-001")
        [line] = [b for b in self.progress() if b.startswith("slot-1 에 커밋 안 된 변경이 남아")]
        self.assertIn("dirty 로 두었다(T-001 를 버렸다): ", line)
        self.assertIn("src/a/core.py", line)
        self.assertTrue(line.endswith("사용자가 버려도 된다고 하면 hteam slot reset 1"), line)
        self.assertEqual(self.log_text().count("slot-1 T-001 놓기 dirty"), 1)
        self.d.reconcile()  # 태스크 없는 dirty 슬롯은 놓을 것이 아니다(같은 실패를 되풀이하지 않는다)
        self.assertEqual(self.d.jobs, {})
        self.assertEqual(len(self.lines("teardown.txt")), 1)
        code, out = self.hteam("slot", "reset", "1")
        self.assertEqual((code, out["slot"], out["state"]), (0, 1, "free"), out)
        self.assertFalse(self.merging(slot))  # git reset --hard 가 끝나지 않은 병합도 지운다
        self.assertEqual(self.git_at(slot, "status", "--porcelain").strip(), "")

    def test_drop_while_preparing_frees_the_reservation(self):
        code, out = self.hteam("start", "T-001")
        self.assertEqual((code, out.get("reason")), (0, "slot_setup"), out)
        self.assertEqual((self.record(1)["state"], self.record(1)["task"]), ("preparing", "T-001"))
        code, out = self.hteam("drop", "T-001")
        self.assertEqual((code, out["status"]), (0, "dropped"), out)
        rec = self.record(1)
        self.assertEqual((rec["state"], rec["task"]), ("free", None))  # 준비 자식을 기다리지 않고 바로 푼다
        code, out = self.hteam("slot", "prepare", "T-001")  # 늦게 도는 준비 자식은 기록에 쓰지 않는다
        self.assertEqual((code, out["error"]["code"]), (3, "slot_not_reserved"), out)
        self.assertEqual(self.record(1)["state"], "free")

    def test_drop_after_prepare_runs_teardown(self):
        self.assertEqual(self.hteam("start", "T-001")[0], 0)
        self.assertEqual(self.hteam("slot", "prepare", "T-001")[0], 0)
        self.assertTrue(self.record(1)["ready"])
        code, out = self.hteam("drop", "T-001")
        self.assertEqual((code, out["status"]), (0, "dropped"), out)
        self.assertEqual(self.record(1)["task"], "T-001")  # setup 을 했으니 놓기(teardown)가 푼다
        self.d.reconcile()
        self.wait_jobs()
        self.assertEqual((self.record(1)["state"], self.record(1)["task"]), ("free", None))
        self.assertEqual(len(self.lines("teardown.txt")), 1)


class SlotResetTest(MergeCase):
    """hteam slot reset <N>(설계 5.10.8, 큐 명령 7.1)."""

    def dirty_slot(self):
        self.ws_start("T-001")
        slot = self.slot_root(1)
        (slot / "src/a/tmp.py").write_text("tmp\n", encoding="utf-8")
        (slot / "src/a/core.py").write_text("고친 채 둠\n", encoding="utf-8")
        self.assertEqual(self.hteam("drop", "T-001", "--force")[0], 0)
        self.d.reconcile()
        self.wait_jobs()
        self.assertEqual(self.record(1)["state"], "dirty")
        return slot

    def test_reset_cleans_a_dirty_slot_but_keeps_ignored_files(self):
        slot = self.dirty_slot()
        code, out = self.hteam("slot", "reset", "1")
        self.assertEqual((code, out["slot"], out["state"]), (0, 1, "free"), out)
        self.assertFalse((slot / "src/a/tmp.py").exists())
        self.assertEqual((slot / "src/a/core.py").read_text(encoding="utf-8"), "a\n")
        self.assertTrue((slot / "node_modules" / "marker").is_file())  # 무시된 파일은 남긴다(git clean -fd)
        self.assertEqual((self.record(1)["state"], self.record(1)["task"]), ("free", None))
        code, out = self.hteam("slot", "reset", "1")
        self.assertEqual((code, out["error"]["code"]), (3, "slot_not_dirty"), out)

    def test_reset_refuses_busy_slots_and_bad_numbers(self):
        self.ws_start("T-001")
        code, out = self.hteam("slot", "reset", "1")
        self.assertEqual((code, out["error"]["code"]), (3, "slot_not_dirty"), out)
        self.assertEqual((self.record(1)["state"], self.record(1)["task"]), ("busy", "T-001"))
        for bad in ("0", "3", "x"):
            with self.subTest(bad=bad):
                code, out = self.hteam("slot", "reset", bad)
                self.assertEqual((code, out["error"]["code"]), (2, "bad_slot"), out)

    def test_main_puts_reset_on_the_queue(self):
        self.dirty_slot()
        code, out = self.hteam("slot", "reset", "1", as_="main", env={"HTEAM_QUEUE_WAIT_S": "0.3"})
        self.assertEqual((code, out.get("status")), (0, "queued"), out)
        reqs = [json.loads(f.read_text(encoding="utf-8")) for f in sorted((self.drive_dir / "queue").iterdir())
                if queue.REQUEST_RE.match(f.name)]
        self.assertEqual([(r["command"], r["args"]) for r in reqs], [("slot reset", {"slot": 1})])
        self.d.run_queue()
        self.assertEqual(self.record(1)["state"], "free")
        self.assertEqual(self.record(1)["reset_request"], reqs[0]["id"])
        self.assertEqual(queue.recorded(self.p, {**reqs[0], "started_at": "2026-11-12T00:00:00Z"}),
                         {"recovered": True, "slot": 1, "state": "free"})

    def test_reset_of_a_removed_folder_prunes_the_worktree(self):
        # 사용자가 슬롯 폴더를 치웠다: git 의 worktree 등록이 남으면 다음 worktree add 가 "missing but already registered
        # worktree" 로 실패한다. reset 이 메인 루트에서 git worktree prune 한다(리뷰 반영 H6)
        slot = self.dirty_slot()
        shutil.rmtree(slot)
        code, out = self.hteam("slot", "reset", "1")
        self.assertEqual((code, out["slot"], out["state"]), (0, 1, "free"), out)
        self.write_spec("T-002", owns="src/b/**")
        self.ws_start("T-002")  # 다음 준비가 그 슬롯에 worktree 를 다시 만든다
        self.assertEqual((self.record(1)["state"], self.record(1)["task"]), ("busy", "T-002"))
        self.assertEqual(self.git_at(slot, "branch", "--show-current").strip(), "herdr/T-002")
        self.assertTrue(workspace.own_worktree(slot))


class FinalSlotTest(MergeCase):
    """worktree 모드의 마무리 full(설계 5.10.7): 빈 슬롯에서 기준 HEAD 로 setup → full → teardown."""

    gate = True

    def test_final_full_runs_in_a_free_slot(self):
        head = self.head()
        code, out = self.hteam("test", "--full")
        self.assertEqual((code, out["status"], out["head"], out["slot"]), (0, "passed", head, 1), out)
        slot = self.slot_root(1)
        call = self.gate_calls()[-1]
        self.assertEqual((call["args"], call["cwd"]), (["--all"], str(slot)))  # 메인 폴더에서 돌리지 않는다
        self.assertEqual(self.lines("setup.txt"), [f"1|{slot}"])
        self.assertEqual(self.lines("teardown.txt"), [f"1|{slot}|8110"])
        self.assertEqual((self.record(1)["state"], self.record(1)["task"]), ("free", None))
        self.assertTrue(self.detached(slot))
        self.assertEqual(self.git_at(slot, "rev-parse", "HEAD").strip(), head)
        final = json.loads((self.state_dir / "tests" / "final.json").read_text(encoding="utf-8"))["full"]
        self.assertEqual((final["head"], final["slot"]), (head, 1))

    def test_no_free_slot_waits_for_the_next_check(self):
        busy = {"state": "busy", "task": "T-009", "branch": "herdr/T-009", "base_branch": "main", "base": self.head(),
                "setup_done": "T-009", "since": "2026-11-12T00:00:00Z"}
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "slots.json").write_text(json.dumps({"slots": {"1": busy, "2": {**busy, "state": "dirty",
                                                                                             "task": None}}}))
        code, out = self.hteam("test", "--full")
        self.assertEqual((code, out["error"]["code"]), (3, "no_free_slot"), out)
        self.d.final_done(code, out, "")
        self.assertEqual(self.decides(), [])
        self.assertIn("마지막 전체 테스트: 빈 슬롯이 없어 다음 확인 때 다시 한다", self.log_text())

    def test_setup_failure_is_workspace_failed(self):
        (self.out / "setup-fail").write_text("", encoding="utf-8")
        code, out = self.hteam("test", "--full")
        self.assertEqual((code, out["error"]["code"], out["kind"], out["slot"]), (1, "setup_failed", "setup_failed", 1))
        self.assertEqual((self.record(1)["state"], self.record(1)["task"]), ("free", None))
        self.assertEqual(self.lines("teardown.txt"), [])  # setup 이 실패하면 teardown 은 돌지 않는다(준비와 같다)
        self.d.final_done(code, out, "")
        [dec] = self.decides("workspace_failed")
        self.assertEqual((dec["task"], dec["detail"]["kind"]), (None, "setup_failed"))
        self.assertIn("설치 실패: 1", dec["tail"])

    def test_dirty_free_slot_is_not_used(self):
        # free 슬롯에 추적 파일 변경이 남았다: git switch --detach 는 충돌하지 않는 변경을 들고 가므로 그 슬롯에서 full 을
        # 돌리면 슬롯에만 있는 변경으로 거짓 통과한다. 쓰지 않고 dirty 로 둔다(Codex 커밋 리뷰 P2, 리뷰 반영 H2)
        self.assertEqual(self.hteam("test", "--full")[0], 0)  # slot-1 폴더를 만들고 free 로 돌아간다
        slot = self.slot_root(1)
        (slot / "src/a/core.py").write_text("슬롯에만 남은 변경\n", encoding="utf-8")
        data = self.slots()
        data["slots"]["2"] = {"state": "busy", "task": "T-009", "branch": "herdr/T-009", "base_branch": "main",
                              "base": self.head(), "setup_done": "T-009", "since": "2026-11-12T00:00:00Z"}
        (self.state_dir / "slots.json").write_text(json.dumps(data), encoding="utf-8")  # free 슬롯은 slot-1 하나
        calls = len(self.gate_calls())
        code, out = self.hteam("test", "--full")
        self.assertEqual((code, out["error"]["code"], out["kind"], out["slot"]), (3, "slot_dirty", "slot_dirty", 1),
                         out)
        self.assertEqual(out["files"], ["src/a/core.py"])
        self.assertEqual(len(self.gate_calls()), calls)  # full 을 돌리지 않았다
        self.assertEqual(len(self.lines("setup.txt")), 1)  # setup 도 돌리지 않았다
        self.assertEqual((self.record(1)["state"], self.record(1)["task"]), ("dirty", None))
        self.assertEqual((slot / "src/a/core.py").read_text(encoding="utf-8"), "슬롯에만 남은 변경\n")  # 건드리지 않는다
        self.d.final_done(code, out, "")
        [dec] = self.decides("workspace_failed")
        self.assertEqual((dec["task"], dec["detail"]["kind"], dec["detail"]["slot"]), (None, "slot_dirty", 1))


class WorkspaceStatusTest(MergeCase):
    """hteam status 의 workspace(설계 5.10.8)."""

    def test_status_shows_slots(self):
        self.ws_start("T-001")
        code, out = self.hteam("status", as_="main")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["workspace"], {"mode": "worktree", "slots": [
            {"n": 1, "state": "busy", "task": "T-001", "branch": "herdr/T-001"},
            {"n": 2, "state": "free", "task": None, "branch": None}]})
        (self.state_dir / "slots.json").write_text("{깨짐", encoding="utf-8")
        code, out = self.hteam("status", as_="main")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["workspace"], {"mode": "worktree", "slots": []})
        self.assertTrue(any(w.startswith("작업 공간 기록: ") for w in out["warnings"]), out.get("warnings"))

    def test_slot_keys_that_are_not_slot_numbers_are_a_warning(self):
        # 슬롯 키는 1–9 정수 문자열이다. 아니면 bad_slots_file(엄격 읽기)이고 status 는 경고로 보인다(리뷰 반영 H4)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        for key in ("bad", "0", "10", "01"):
            with self.subTest(key=key):
                (self.state_dir / "slots.json").write_text(json.dumps({"slots": {key: {}}}), encoding="utf-8")
                code, out = self.hteam("status", as_="main")
                self.assertEqual(code, 0, out)
                self.assertEqual(out["workspace"], {"mode": "worktree", "slots": []})
                [warning] = [w for w in out["warnings"] if w.startswith("작업 공간 기록: ")]
                self.assertIn("state/slots.json 을 읽지 못했다", warning)


class NotWorktreeTest(MergeCase):
    """슬롯 폴더가 자기 git worktree 가 아닐 때(.git 이 없다) 놓기·slot reset·마무리 full 은 그 폴더에서 teardown·setup·git
    을 부르지 않는다: 부르면 git 이 위로 올라가 메인 저장소를 잡는다(Codex 커밋 리뷰 P1, 리뷰 반영 H1·H5). 메인의 커밋 안 된
    변경·브랜치·HEAD 가 그대로인지 본다."""

    gate = True

    def break_slot(self, n: int = 1) -> str:
        """슬롯 n 의 .git 을 지우고 메인에 커밋 안 된 변경을 둔다. 메인 HEAD 를 돌려준다."""
        (self.slot_root(n) / ".git").unlink()
        (self.proj / "docs/other.md").write_text("사람이 고치는 중\n", encoding="utf-8")
        return self.head()

    def assert_main_kept(self, head: str) -> None:
        self.assertEqual((self.proj / "docs/other.md").read_text(encoding="utf-8"), "사람이 고치는 중\n")
        self.assertEqual(self.git("branch", "--show-current").strip(), "main")
        self.assertEqual(self.head(), head)

    def test_release_and_reset_leave_the_main_repo_alone(self):
        (self.out / "teardown.sh").write_text("git reset --hard -q\n" + TEARDOWN_SH, encoding="utf-8")
        self.ws_start("T-001")
        self.assertEqual(self.hteam("drop", "T-001", "--force")[0], 0)
        head = self.break_slot()
        code, out = self.hteam("slot", "release", "T-001")
        self.assertEqual((code, out["state"], out["reason"], out["teardown"]), (0, "dirty", "not_worktree", None), out)
        self.assertEqual(self.lines("teardown.txt"), [])  # teardown 을 돌리지 않았다
        self.assertEqual((self.record(1)["state"], self.record(1)["task"]), ("dirty", None))
        self.assert_main_kept(head)
        code, out = self.hteam("slot", "reset", "1")
        self.assertEqual((code, out["error"]["code"], out["slot"]), (1, "slot_not_worktree", 1), out)
        self.assertEqual(self.record(1)["state"], "dirty")
        self.assert_main_kept(head)

    def test_final_full_leaves_the_main_repo_alone(self):
        self.assertEqual(self.hteam("test", "--full")[0], 0)  # slot-1 폴더를 만들고 free 로 돌아간다
        head = self.break_slot()
        calls = len(self.gate_calls())
        code, out = self.hteam("test", "--full")
        self.assertEqual((code, out["error"]["code"], out["slot"], out["reason"]), (3, "slot_dirty", 1, "not_worktree"),
                         out)
        self.assertEqual(len(self.gate_calls()), calls)
        self.assertEqual(len(self.lines("setup.txt")), 1)  # setup 도 돌리지 않았다
        self.assertEqual((self.record(1)["state"], self.record(1)["task"]), ("dirty", None))
        self.assert_main_kept(head)

    def test_teardown_that_removes_git_leaves_the_main_repo_alone(self):
        # teardown 이 슬롯의 .git 을 지우면 훅 전 검사만 통과하고 그 뒤 switch --detach 가 메인을 detached HEAD 로 바꾸고 슬롯은
        # free 로 적혔다(Codex 커밋 리뷰 6084c33 P1, 리뷰 반영 2 I1). teardown 직후 다시 보고 git 없이 dirty(not_worktree)
        (self.out / "teardown.sh").write_text("rm -f .git\n" + TEARDOWN_SH, encoding="utf-8")
        self.ws_start("T-001")
        self.assertEqual(self.act_work("T-001", {"src/a/x.py": "x\n"})[0], 0)
        self.assertEqual(self.hteam("drop", "T-001")[0], 0)
        (self.proj / "docs/other.md").write_text("사람이 고치는 중\n", encoding="utf-8")
        head = self.head()
        self.d.reconcile()
        self.wait_jobs()
        slot1 = [line for line in self.lines("teardown.txt") if line.startswith("1|")]  # slot-2 는 관제의 마무리 full
        self.assertEqual(len(slot1), 1)  # teardown 은 돌았다
        self.assert_main_kept(head)
        self.assertEqual((self.record(1)["state"], self.record(1)["task"]), ("dirty", None))
        self.assertTrue(self.has_branch("herdr/T-001"))
        [line] = [b for b in self.progress() if b.startswith("slot-1 폴더가 teardown 뒤 git worktree 가 아니게 되어")]
        self.assertIn("teardown 뒤 git 은 부르지 않았다", line)
        self.assertIn("slot-1 T-001 놓기 dirty", self.log_text())
        code, out = self.hteam("slot", "release", "T-001")  # 기록이 이 태스크의 것이 아니다: 다시 돌지 않는다
        self.assertEqual((code, out["state"]), (0, None), out)
        self.assertEqual([line for line in self.lines("teardown.txt") if line.startswith("1|")], slot1)

    def test_final_full_setup_that_removes_git_leaves_the_main_repo_alone(self):
        # 마무리 full 의 setup 이 .git 을 지우면 full(과 그 git 조회)이 메인 저장소를 본다. setup 직후 다시 보고 full·teardown
        # 없이 slot_dirty(not_worktree)(리뷰 반영 2 I1)
        (self.out / "setup.sh").write_text("rm -f .git\n" + SETUP_SH, encoding="utf-8")
        (self.proj / "docs/other.md").write_text("사람이 고치는 중\n", encoding="utf-8")
        head = self.head()
        calls = len(self.gate_calls())
        code, out = self.hteam("test", "--full")
        self.assertEqual((code, out["error"]["code"], out["slot"], out["reason"]), (3, "slot_dirty", 1, "not_worktree"),
                         out)
        self.assertIn("setup 뒤", out["error"]["message"])
        self.assertEqual(len(self.gate_calls()), calls)  # full 을 돌리지 않았다
        self.assertEqual(len(self.lines("setup.txt")), 1)
        self.assertEqual(self.lines("teardown.txt"), [])  # teardown 도 그 폴더에서 돌리지 않는다
        self.assertEqual((self.record(1)["state"], self.record(1)["task"]), ("dirty", None))
        self.assert_main_kept(head)


class SharedMergeTest(MergeCase):
    """회귀(헤더 "기본값"): shared 는 병합하지 않고, 슬롯 기록·status 의 workspace·슬롯 명령이 없다."""

    config_text = BASE_CONFIG
    gate = True

    def test_shared_accept_is_unchanged(self):
        self.approved(ws=False)
        before = self.head()
        res = self.d.accept_task("T-001")
        self.assertEqual(res["status"], "done", res)
        self.assertNotIn("merge", res)
        self.assertEqual(self.head(), before)  # 병합 커밋이 없다
        self.assertEqual(len(self.parents()), 1)
        st = self.task_state("T-001")
        self.assertNotIn("workspace", st)
        self.assertNotIn("merge_wait", st)
        self.assertEqual(self.d.jobs, {})
        self.assertFalse((self.state_dir / "slots.json").exists())
        self.assertFalse((self.state_dir / "slots").exists())
        code, out = self.hteam("status", as_="main")
        self.assertNotIn("workspace", out)
        for args in (("slot", "reset", "1"), ("slot", "release", "T-001")):
            with self.subTest(args=args):
                code, out = self.hteam(*args)
                self.assertEqual((code, out["error"]["code"]), (3, "workspace_off"), out)

    def test_shared_final_full_runs_in_the_main_folder(self):
        code, out = self.hteam("test", "--full")
        self.assertEqual((code, out["status"]), (0, "passed"), out)
        self.assertNotIn("slot", out)
        self.assertEqual(self.gate_calls()[-1]["cwd"], str(self.proj))


if __name__ == "__main__":
    unittest.main()
