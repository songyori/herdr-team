"""작업 공간 코어(7단계, 설계 5.10.2–5.10.3): slots.json·슬롯 잠금·경로·env, `hteam slot prepare`(worktree·브랜치·표시 파일·
setup), setup·teardown 실행, 표시 파일로 나누는 두 루트(find_project), testgate.child_env.

시험은 실제 git worktree 를 시험이 만든 임시 저장소 안에 만든다. 예약(설계 5.10.3 의 1)은 Task 4 의 start 가 쓰는 꼴로
slots.json 에 직접 쓴다."""
import contextlib
import json
import os
import subprocess
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import BASE_CONFIG, WS_CONFIG, TeamCase
from hteam import config, paths, state, testgate, workspace
from hteam.errors import HteamError
from hteam.paths import Project

# setup 도우미(시험 폴더 밖 $OUT_DIR/setup.sh): 받은 환경을 한 줄로 남기고 무시된 폴더(node_modules)에 표시를 쌓는다.
# $OUT_DIR/fail 이 있으면 실패한다
SETUP_SH = """[ -f "$OUT_DIR/fail" ] && { echo "설치 실패: $HTEAM_SLOT"; exit 7; }
printf '%s|%s|%s|%s|%s|%s|%s\\n' "$HTEAM_SLOT" "$HT_PORT" "$HTEAM_MAIN_ROOT" "$HTEAM_SLOT_ROOT" "$(pwd -P)" \\
  "${HTEAM_ROLE-없음}" "${HC_TERMINAL_ID-없음}" >> "$OUT_DIR/setup.txt"
mkdir -p node_modules && echo "$HTEAM_SLOT" >> node_modules/marker
"""


def ws_config(setup: str | None = 'sh "$OUT_DIR/setup.sh"', extra: str = "") -> str:
    """WS_CONFIG 의 [workspace] 에 setup(TOML 리터럴 문자열)과 extra 줄을 더한다."""
    lines = (f"setup = '{setup}'\n" if setup else "") + extra
    return WS_CONFIG.replace("slots = 2\n", "slots = 2\n" + lines)


def other_repo(tmp: Path, env: dict) -> Path:
    """다른 git 저장소의 herdr-team 프로젝트(표시 파일이 가리키면 common dir 이 달라 무시해야 한다)."""
    other = tmp / "other"
    (other / ".herdr-team").mkdir(parents=True)
    (other / ".herdr-team" / "config.toml").write_text(BASE_CONFIG, encoding="utf-8")
    for args in (("init", "-q", "-b", "main"), ("add", "--", ".herdr-team"), ("commit", "-q", "-m", "init")):
        subprocess.run(["git", "-C", str(other), *args], check=True, capture_output=True, env=env)
    return other


class SlotCase(TeamCase):
    """작업 공간 프로젝트(WS_CONFIG + setup 도우미, node_modules 는 git 제외)와 관제 Run."""

    config_text = None  # None 이면 ws_config()

    def setUp(self):
        super().setUp()
        self.out = self.tmp / "out"
        self.out.mkdir()
        (self.out / "setup.sh").write_text(SETUP_SH, encoding="utf-8")
        self.env["OUT_DIR"] = str(self.out)
        self.init_project(self.config_text or ws_config())
        self.commit(".gitignore", ".herdr-team/state/\nnode_modules/\n", "chore: node_modules 제외")
        self.setup_run()

    def use_config(self, text: str) -> None:
        (self.team / "config.toml").write_text(text, encoding="utf-8")

    def reserve(self, tid: str, n: int = 1, role: str = "developer") -> str:
        """Task 4 의 start 가 쓰는 예약(설계 5.10.3 의 1): pending 태스크와 slots.json 의 preparing 기록. setup_done 은 그
        슬롯의 앞 값 그대로다. 기준 커밋(메인 HEAD)을 돌려준다."""
        state.create(Project(self.proj), tid, role)
        data = self.slots()
        old = data["slots"].get(str(n), {})
        base = self.head()
        data["slots"][str(n)] = {"state": "preparing", "task": tid, "branch": f"herdr/{tid}", "base_branch": "main",
                                 "base": base, "setup_done": old.get("setup_done"), "since": "2026-11-12T00:00:00Z"}
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "slots.json").write_text(json.dumps(data), encoding="utf-8")
        return base

    def prepare(self, tid: str, **kw) -> tuple[int, dict]:
        return self.hteam("slot", "prepare", tid, **kw)

    def setup_lines(self) -> list[str]:
        path = self.out / "setup.txt"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def marker_of(self, root: Path) -> dict | None:
        path = root / ".herdr-team" / "state" / "slot.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def wait_file(self, path: Path, limit: float = 30.0) -> None:
        deadline = time.monotonic() + limit
        while not path.exists():
            if time.monotonic() > deadline:
                self.fail(f"{limit}초 안에 {path} 가 생기지 않았다")
            time.sleep(0.05)


class SlotStateTest(TeamCase):
    """slots.json·경로·env·잠금(설계 5.10.2·5.10.3·5.7 7단계)."""

    def setUp(self):
        super().setUp()
        self.init_project(WS_CONFIG)
        self.p = Project(self.proj)

    def test_project_paths(self):
        self.assertEqual(self.p.work_root, self.p.root)
        self.assertEqual((self.p.slots_file, self.p.slots_dir, self.p.slot_logs, self.p.git_lock),
                         (self.state_dir / "slots.json", self.state_dir / "slots", self.state_dir / "slots" / "logs",
                          self.state_dir / "git.lock"))
        other = Project(self.proj, work_root=self.state_dir / "slots" / "slot-1")
        self.assertEqual((other.root, other.work_root, other.state),
                         (self.proj, self.state_dir / "slots" / "slot-1", self.state_dir))

    def test_load_entry_save_and_corrupt(self):
        self.assertEqual(workspace.load(self.p), {"slots": {}})
        self.assertEqual(workspace.entry({"slots": {}}, 2), dict(workspace.SLOT_DEFAULT))
        self.assertEqual(workspace.SLOT_DEFAULT, {"state": "free", "task": None, "branch": None, "base_branch": None,
                                                  "base": None, "setup_done": None, "since": None})
        data = {"slots": {"2": {"state": "busy", "task": "T-003", "branch": "herdr/T-003", "base_branch": "main",
                                "base": "abc", "setup_done": "T-003", "since": "2026-11-12T00:00:00Z"}}}
        with state.project_lock(self.p):
            workspace.save(self.p, data)
        self.assertEqual(workspace.load(self.p), data)
        self.assertEqual(workspace.entry(workspace.load(self.p), 2)["task"], "T-003")
        self.assertEqual((workspace.held_by(data, "T-003"), workspace.held_by(data, "T-004")), (2, None))
        for bad in ("{깨짐", "[]", '{"slots": []}', '{"slots": {"1": "busy"}}'):
            with self.subTest(bad=bad):
                self.p.slots_file.write_text(bad, encoding="utf-8")
                with self.assertRaises(HteamError) as cm:
                    workspace.load(self.p)
                self.assertEqual((cm.exception.code, cm.exception.exit_code), ("bad_slots_file", 1))
                self.assertEqual(self.p.slots_file.read_text(encoding="utf-8"), bad)  # 덮어쓰지 않는다

    def test_env_roots_and_branch(self):
        cfg = config.load(self.p)
        self.assertEqual(workspace.slot_env(cfg, 1), {"HT_PORT": "8110", "HTEAM_SLOT": "1"})
        slot_task = {"id": "T-001", "workspace": {"slot": 2, "branch": "herdr/T-001", "base_branch": "main",
                                                  "root": "/x/slot-2", "merge": None}}
        self.assertEqual(workspace.task_env(self.p, cfg, slot_task), {"HT_PORT": "8120", "HTEAM_SLOT": "2"})
        # worktree 모드에서 메인 폴더에서 도는 태스크는 슬롯 0 값이다(설계 5.7 7단계)
        self.assertEqual(workspace.task_env(self.p, cfg, {"id": "T-002"}), {"HT_PORT": "8100", "HTEAM_SLOT": "0"})
        self.assertEqual(workspace.task_root(self.p, slot_task), Path("/x/slot-2"))
        self.assertEqual(workspace.task_root(self.p, {"id": "T-002"}), self.p.root)
        self.assertEqual(workspace.folder(self.p, 3), self.state_dir / "slots" / "slot-3")
        self.assertEqual(workspace.work_root(self.p, 3), self.state_dir / "slots" / "slot-3")
        self.assertEqual(workspace.branch_of("T-012"), "herdr/T-012")

    def test_own_worktree(self):
        """슬롯 폴더에 git 을 하기 전의 확인: 그 폴더가 자기 worktree 의 맨 위인가(아니면 git 이 위로 올라가 메인을 본다)."""
        top = workspace.folder(self.p, 1)
        self.assertFalse(workspace.own_worktree(top))  # 없다
        top.mkdir(parents=True)
        self.assertFalse(workspace.own_worktree(top))  # 메인 저장소 안의 그냥 폴더
        top.rmdir()
        self.git("worktree", "add", "-q", "--detach", str(top), "HEAD")
        self.assertTrue(workspace.own_worktree(top))
        (top / "sub").mkdir()
        self.assertFalse(workspace.own_worktree(top / "sub"))  # worktree 안의 하위 폴더는 맨 위가 아니다
        (top / ".git").unlink()
        self.assertFalse(workspace.own_worktree(top))  # .git 을 지웠다

    def test_slot_lock_nowait_and_busy(self):
        self.assertFalse(workspace.slot_busy(self.p, 1))
        with workspace.slot_lock(self.p, 1):
            self.assertTrue(workspace.slot_busy(self.p, 1))
            self.assertFalse(workspace.slot_busy(self.p, 2))  # 슬롯마다 따로다
            with self.assertRaises(HteamError) as cm:
                with workspace.slot_lock(self.p, 1, nowait=True):
                    pass
            self.assertEqual((cm.exception.code, cm.exception.exit_code), ("slot_locked", 3))
        self.assertFalse(workspace.slot_busy(self.p, 1))
        self.assertTrue((self.state_dir / "slots" / "slot-1.lock").exists())


class PrepareTest(SlotCase):
    """`hteam slot prepare T`(설계 5.10.3 의 2–4)."""

    def test_prepare_makes_worktree_branch_marker_and_runs_setup(self):
        base = self.reserve("T-001")
        code, out = self.prepare("T-001")
        self.assertEqual(code, 0, out)
        slot = self.slot_root(1)
        self.assertEqual((out["task"], out["slot"], out["root"], out["branch"], out["base_branch"], out["base"],
                          out["ready"]), ("T-001", 1, str(slot), "herdr/T-001", "main", base, True))
        self.assertEqual((out["setup"]["kind"], out["setup"]["status"], out["setup"]["exit"]), ("setup", "passed", 0))
        self.assertEqual(self.git_at(slot, "symbolic-ref", "--short", "HEAD").strip(), "herdr/T-001")
        self.assertEqual(self.git_at(slot, "rev-parse", "HEAD").strip(), base)
        self.assertEqual(self.marker_of(slot), {"main_root": str(self.proj), "slot": 1, "task": "T-001"})
        rec = self.slots()["slots"]["1"]
        self.assertEqual((rec["state"], rec["task"], rec["setup_done"], rec.get("ready")),
                         ("preparing", "T-001", "T-001", True))
        # setup 은 작업 루트에서, 슬롯 env·HTEAM_* 를 받고, 관제·워커 표시 변수 없이 돈다
        self.assertEqual(self.setup_lines(), ["|".join(["1", "8110", str(self.proj), str(slot), str(slot), "없음", "없음"])])
        logs = sorted((self.state_dir / "slots" / "logs").glob("slot-1-setup-*.log"))
        self.assertEqual(len(logs), 1)
        self.assertEqual(out["setup"]["log"], logs[0].relative_to(self.proj).as_posix())
        self.assertTrue(logs[0].read_text(encoding="utf-8").startswith('$ sh "$OUT_DIR/setup.sh"\n'))
        self.assertEqual(self.git("status", "--porcelain"), "")  # 슬롯 폴더는 git 제외 경로(.herdr-team/state/) 안이다
        self.assertIn(f"worktree {slot}\n", self.git("worktree", "list", "--porcelain"))
        self.assertEqual(self.task_state("T-001")["status"], "pending")  # 준비는 태스크를 띄우지 않는다(Task 4 의 start)

    def test_rerun_skips_and_reuse_keeps_folder(self):
        self.reserve("T-001")
        self.assertEqual(self.prepare("T-001")[0], 0)
        slot = self.slot_root(1)
        code, out = self.prepare("T-001")  # 같은 예약을 다시 준비(관제가 준비 자식을 다시 띄웠다): git·setup 을 다시 하지 않는다
        self.assertEqual(code, 0, out)
        self.assertIsNone(out["setup"])
        self.assertEqual(len(self.setup_lines()), 1)
        # 놓은 뒤 다른 태스크가 같은 슬롯을 다시 쓴다(놓기는 Task 5. 여기서는 그 결과를 흉내 낸다: detach 와 새 예약)
        self.git_at(slot, "switch", "--detach")
        self.commit("src/new.py", "x = 1\n", "feat: 기준 브랜치가 나아갔다")
        base = self.reserve("T-002")
        code, out = self.prepare("T-002")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["setup"]["status"], "passed")  # setup_done 이 T-001 이라 다시 돈다
        self.assertEqual(len(self.setup_lines()), 2)
        self.assertEqual(self.git_at(slot, "symbolic-ref", "--short", "HEAD").strip(), "herdr/T-002")
        self.assertEqual(self.git_at(slot, "rev-parse", "HEAD").strip(), base)
        self.assertTrue((slot / "src" / "new.py").is_file())
        self.assertEqual((slot / "node_modules" / "marker").read_text(encoding="utf-8"), "1\n1\n")  # 무시된 파일은 남는다
        self.assertEqual(self.slots()["slots"]["1"]["setup_done"], "T-002")
        self.assertEqual(self.marker_of(slot)["task"], "T-002")

    def test_dirty_new_slot_is_set_aside(self):
        self.reserve("T-001")
        self.assertEqual(self.prepare("T-001")[0], 0)
        slot = self.slot_root(1)
        self.git_at(slot, "switch", "--detach")
        (slot / "junk.txt").write_text("남은 파일\n", encoding="utf-8")
        self.reserve("T-002")
        code, out = self.prepare("T-002")
        self.assertEqual(code, 3, out)
        self.assertEqual((out["error"]["code"], out["kind"], out["slot"]), ("slot_dirty", "slot_dirty", 1))
        self.assertIn("junk.txt", out["files"])
        self.assertIn("hteam slot reset 1", out["error"]["hint"])
        rec = self.slots()["slots"]["1"]
        self.assertEqual((rec["state"], rec["task"], rec.get("ready")), ("dirty", None, None))
        self.assertEqual(rec["setup_done"], "T-001")
        self.assertIsNone(workspace.held_by(self.slots(), "T-002"))  # 예약을 풀었다(다른 슬롯을 잡을 수 있다)
        self.assertEqual(self.task_state("T-002")["status"], "pending")
        self.assertTrue((slot / "junk.txt").exists())  # 지우지 않는다(slot reset 은 사용자 확인 뒤, Task 5)

    def test_folder_that_is_not_a_worktree_is_set_aside(self):
        """슬롯 폴더가 남았는데 worktree 가 아니면(.git 이 없다: worktree add 가 mkdir 직후 죽었거나 사용자가 지웠다) git 이
        위로 올라가 메인 저장소를 본다. 메인 작업 트리에 git 쓰기를 하지 않고 슬롯을 dirty 로 둔다(태스크 리뷰 Minor 1)."""
        slot = self.slot_root(1)
        slot.mkdir(parents=True)
        self.reserve("T-001")
        before = (self.git("symbolic-ref", "--short", "HEAD").strip(), self.head())
        code, out = self.prepare("T-001")
        self.assertEqual(code, 3, out)
        self.assertEqual((out["error"]["code"], out["kind"], out["slot"], out["reason"]),
                         ("slot_dirty", "slot_dirty", 1, "not_worktree"))
        self.assertNotIn("files", out)
        self.assertEqual((self.git("symbolic-ref", "--short", "HEAD").strip(), self.head()), before)
        self.assertNotIn("herdr/T-001", self.git("branch", "--list"))
        rec = self.slots()["slots"]["1"]
        self.assertEqual((rec["state"], rec["task"], rec.get("ready")), ("dirty", None, None))
        self.assertIsNone(workspace.held_by(self.slots(), "T-001"))
        self.assertEqual(self.task_state("T-001")["status"], "pending")
        self.assertIsNone(self.marker_of(slot))

    def test_existing_branch_is_refused(self):
        self.git("branch", "herdr/T-001")
        self.reserve("T-001")
        code, out = self.prepare("T-001")
        self.assertEqual(code, 3, out)
        self.assertEqual((out["error"]["code"], out["kind"], out["slot"], out["branch"]),
                         ("branch_exists", "branch_exists", 1, "herdr/T-001"))
        rec = self.slots()["slots"]["1"]
        self.assertEqual((rec["state"], rec["task"]), ("free", None))
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["rounds"], st["history"][-1]["event"]),
                         ("launch_failed", [], "slot_branch_exists"))
        self.assertEqual(self.git("rev-parse", "herdr/T-001").strip(), self.head())  # 남은 브랜치는 그대로(사용자가 정한다)
        self.assertTrue(self.slot_root(1).is_dir())

    def test_setup_failure_frees_slot_and_marks_launch_failed(self):
        (self.out / "fail").write_text("", encoding="utf-8")
        self.reserve("T-001")
        code, out = self.prepare("T-001")
        self.assertEqual(code, 1, out)
        self.assertEqual((out["error"]["code"], out["kind"], out["slot"], out["status"], out["exit"]),
                         ("setup_failed", "setup_failed", 1, "failed", 7))
        self.assertIn("설치 실패: 1", out["tail"])
        self.assertTrue((self.proj / out["log"]).is_file())
        rec = self.slots()["slots"]["1"]
        self.assertEqual((rec["state"], rec["task"], rec["setup_done"]), ("free", None, None))
        slot = self.slot_root(1)
        self.assertTrue(slot.is_dir())  # 폴더는 남긴다(설계 5.10.3 끝 문단)
        self.assertEqual(self.git_at(slot, "rev-parse", "--abbrev-ref", "HEAD").strip(), "HEAD")  # detached
        self.assertEqual(self.git("branch", "--list", "herdr/*"), "")  # 커밋 없는 빈 브랜치는 지운다
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["rounds"], st["history"][-1]["event"]), ("launch_failed", [], "slot_setup_failed"))
        # 고친 뒤 다시 예약하면(다른 슬롯이어도) 같은 이름의 브랜치로 준비된다
        (self.out / "fail").unlink()
        self.reserve("T-001", 2)
        code, out = self.prepare("T-001")
        self.assertEqual(code, 0, out)
        self.assertEqual((out["slot"], out["branch"]), (2, "herdr/T-001"))

    def test_death_after_branch_resumes(self):
        self.reserve("T-001")
        code, _ = self.prepare("T-001", env={"HTEAM_TEST_DIE_AT": "slot_branch_made"})
        self.assertEqual(code, 137)
        slot = self.slot_root(1)
        rec = self.slots()["slots"]["1"]
        self.assertEqual((rec["state"], rec["task"], rec.get("ready")), ("preparing", "T-001", None))
        self.assertIsNone(self.marker_of(slot))
        self.assertEqual(self.setup_lines(), [])
        code, out = self.prepare("T-001")  # 관제가 슬롯 잠금이 풀린 것을 보고 다시 띄운 준비 자식
        self.assertEqual(code, 0, out)
        self.assertEqual(self.git_at(slot, "symbolic-ref", "--short", "HEAD").strip(), "herdr/T-001")
        self.assertEqual(self.marker_of(slot)["task"], "T-001")
        self.assertEqual(len(self.setup_lines()), 1)
        self.assertTrue(self.slots()["slots"]["1"]["ready"])

    def test_prepare_holds_the_slot_lock(self):
        self.reserve("T-001")
        gate = self.tmp / "gate"
        proc = self.hteam_bg("slot", "prepare", "T-001",
                             env={"HTEAM_TEST_PAUSE_AT": "slot_prepare_locked", "HTEAM_TEST_PAUSE_FILE": str(gate)})
        self.wait_file(self.tmp / "gate.reached")
        p = Project(self.proj)
        self.assertTrue(workspace.slot_busy(p, 1))  # 관제가 보는 것: 자식이 살아 있다
        code, out = self.prepare("T-001")
        self.assertEqual((code, out["error"]["code"]), (3, "slot_locked"), out)
        gate.touch()
        code, out = self.finish(proc)
        self.assertEqual(code, 0, out)
        self.assertFalse(workspace.slot_busy(p, 1))

    def test_drive_only_and_unreserved(self):
        self.reserve("T-001")
        code, out = self.prepare("T-001", as_="main")
        self.assertEqual((code, out["error"]["code"]), (5, "drive_only"), out)
        code, out = self.prepare("T-009")
        self.assertEqual((code, out["error"]["code"]), (3, "slot_not_reserved"), out)
        code, out = self.prepare("x-1")
        self.assertEqual((code, out["error"]["code"]), (2, "bad_task_id"), out)
        self.assertFalse(self.slot_root(1).exists())  # 아무것도 만들지 않았다


class HookRunTest(SlotCase):
    """setup·teardown 실행(설계 5.10.3 의 4, 5.10.6 놓기의 teardown): 작업 루트, 환경, 로그, 시간 상한."""

    def test_teardown_runs_in_work_root_with_slot_env(self):
        self.reserve("T-001")
        self.assertEqual(self.prepare("T-001")[0], 0)
        self.use_config(ws_config(extra="teardown = 'echo \"$HTEAM_SLOT $HT_PORT ${HTEAM_ROLE-없음} $(pwd -P)\" "
                                         "> \"$OUT_DIR/teardown.txt\"'\n"))
        p = Project(self.proj)
        cfg = config.load(p)
        with mock.patch.dict(os.environ, {"OUT_DIR": str(self.out), "HTEAM_ROLE": "drive", "HC_TERMINAL_ID": "t9"}):
            res = workspace.run_hook(p, cfg, 1, "teardown", "T-001")
        self.assertEqual((res["kind"], res["status"], res["exit"]), ("teardown", "passed", 0))
        self.assertEqual((self.out / "teardown.txt").read_text(encoding="utf-8").strip(),
                         f"1 8110 없음 {self.slot_root(1)}")
        self.assertRegex(res["log"], r"^\.herdr-team/state/slots/logs/slot-1-teardown-\d{8}-\d{6}\.log$")

    def test_timeout_kills_the_group(self):
        self.reserve("T-001")
        self.assertEqual(self.prepare("T-001")[0], 0)
        self.use_config(ws_config("sleep 30", extra="setup_timeout_min = 1\n"))
        p = Project(self.proj)
        cfg = config.load(p)
        started = time.monotonic()
        with mock.patch.object(workspace, "MINUTE_S", 0.2):
            res = workspace.run_hook(p, cfg, 1, "setup", "T-001")
        self.assertEqual((res["status"], res["exit"]), ("timeout", None))
        self.assertLess(time.monotonic() - started, 10)


class SubdirSlotTest(SlotCase):
    """프로젝트가 저장소의 하위 폴더(app/)면 슬롯은 저장소 전체의 worktree 이고 작업 루트는 그 아래 app/ 다(설계 5.10.2)."""

    def setUp(self):
        TeamCase.setUp(self)
        self.repo = self.proj
        self.proj = self.repo / "app"
        self.proj.mkdir()
        self.out = self.tmp / "out"
        self.out.mkdir()
        self.env["OUT_DIR"] = str(self.out)
        self.init_project(ws_config(None))
        self.setup_run()

    def test_work_root_is_the_same_subfolder(self):
        self.reserve("T-001")
        code, out = self.prepare("T-001")
        self.assertEqual(code, 0, out)
        top = self.slot_root(1)
        work = top / "app"
        self.assertEqual(out["root"], str(work))
        self.assertTrue((top / "README.md").is_file())  # 저장소 전체의 worktree
        self.assertTrue((work / ".herdr-team" / "config.toml").is_file())
        self.assertEqual(self.marker_of(work), {"main_root": str(self.proj), "slot": 1, "task": "T-001"})
        self.assertIsNone(self.marker_of(top))
        self.assertEqual(workspace.work_root(Project(self.proj), 1), work)
        p = paths.find_project(str(work))
        self.assertEqual((p.root, p.work_root), (self.proj, work))


class FindProjectTest(TeamCase):
    """표시 파일로 나누는 두 루트(설계 5.10.2): 슬롯에서 찾아도 상태 루트는 메인이다."""

    def setUp(self):
        super().setUp()
        self.init_project(WS_CONFIG)
        self.setup_run()
        self.slot = self.slot_root(1)
        self.git("worktree", "add", "-q", "--detach", str(self.slot), "HEAD")
        self.mark({"main_root": str(self.proj), "slot": 1, "task": "T-001"})

    def mark(self, value) -> None:
        path = self.slot / ".herdr-team" / "state" / "slot.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")

    def test_marker_splits_state_and_work_roots(self):
        self.assertEqual(workspace.marker(self.slot), {"main_root": str(self.proj), "slot": 1, "task": "T-001"})
        for arg in (str(self.slot), None):
            with self.subTest(arg=arg), contextlib.chdir(self.slot / ".herdr-team"):
                p = paths.find_project(arg)
                self.assertEqual((p.root, p.work_root, p.state), (self.proj, self.slot, self.state_dir))
        main = paths.find_project(str(self.proj))
        self.assertEqual((main.root, main.work_root), (self.proj, self.proj))
        self.assertEqual(paths.project_at(self.slot).root, self.proj)

    def test_cli_in_slot_uses_main_state(self):
        # 슬롯 안에서 부른 hteam 이 메인의 run.json 으로 관제를 확인하고 메인의 slots.json 을 본다
        code, out = self.hteam("slot", "prepare", "T-009", cwd=self.slot)
        self.assertEqual((code, out["error"]["code"]), (3, "slot_not_reserved"), out)

    def test_bad_markers_are_ignored(self):
        other = other_repo(self.tmp, self.env)
        cases = ["{깨짐", [],
                 {"main_root": str(other), "slot": 1, "task": "T-001"},       # 다른 저장소(common dir 이 다르다)
                 {"main_root": str(self.tmp / "none"), "slot": 1, "task": "T-001"},
                 {"main_root": "proj", "slot": 1, "task": "T-001"},           # 상대 경로
                 {"main_root": str(self.proj), "slot": "1", "task": "T-001"},
                 {"main_root": str(self.proj), "slot": True, "task": "T-001"},
                 {"main_root": str(self.proj), "slot": 1, "task": "x"}]
        for value in cases:
            with self.subTest(value=value):
                self.mark(value)
                self.assertIsNone(workspace.marker(self.slot))
                p = paths.find_project(str(self.slot))
                self.assertEqual((p.root, p.work_root), (self.slot, self.slot))


class SharedRegressionTest(TeamCase):
    """작업 공간이 꺼진 프로젝트는 0.4.0 그대로다(헤더 "기본값")."""

    def setUp(self):
        super().setUp()
        self.init_project()
        self.setup_run()

    def test_shared_project_paths_env_and_prepare(self):
        p = paths.find_project(str(self.proj))
        self.assertEqual((p.root, p.work_root), (self.proj, self.proj))
        cfg = config.load(p)
        self.assertEqual(workspace.task_env(p, cfg, {"id": "T-001"}), {})
        state.create(p, "T-001", "developer")
        code, out = self.hteam("slot", "prepare", "T-001")
        self.assertEqual((code, out["error"]["code"]), (3, "workspace_off"), out)
        self.assertFalse((self.state_dir / "slots.json").exists())
        env = {"HTEAM_ROLE": "drive", "HTEAM_LAUNCH": "n", "HC_TERMINAL_ID": "t9", "KEEP_ME": "1"}
        with mock.patch.dict(os.environ, env):
            plain = testgate.child_env(None)
            more = testgate.child_env(cfg, {"EXTRA": "x"})
        for name in ("HTEAM_ROLE", "HTEAM_LAUNCH", "HC_TERMINAL_ID"):
            self.assertNotIn(name, plain)
            self.assertNotIn(name, more)
        self.assertEqual((plain["KEEP_ME"], more["KEEP_ME"], more["EXTRA"]), ("1", "1", "x"))
        self.assertNotIn("EXTRA", plain)


if __name__ == "__main__":
    unittest.main()
