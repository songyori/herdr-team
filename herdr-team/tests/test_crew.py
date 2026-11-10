"""고정 에이전트 1(설계 5.9.1–5.9.6, 5.4 의 6단계 문단, 5.5 의 7, 8.6·8.7 의 고정 에이전트 줄): crew.json, 배정, 처음 띄우기,
같은 터미널에 넣기, start 의 waiting, 수정 대기열·드레인·큐 맞추기, --force, 인수인계 줄, 관제의 worker_done·exited 처리,
재확인의 터미널 확인, status 의 crew. 리셋·인수인계·입력 유실은 test_crew_reset.py(Task 8)."""
import hashlib
import json
import re
import time
from datetime import datetime, timedelta

from tests.helpers import BASE_CONFIG, CREW_CONFIG, DRIVE, TeamCase
from hteam import compose, config, crew, specs, state
from hteam.paths import Project

LOCAL_ISO = r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d"
WAIT_RESET = "생산 에이전트가 리셋(인수인계) 중이거나 리셋을 기다린다"
WAIT_BUSY = "생산 에이전트가 바쁘고 임시 워커가 꺼져 있다([overflow] enabled = false)"
NO_TEST_CREW = CREW_CONFIG.split("[crew.test]")[0]  # 생산 에이전트만(tester 직무에는 고정 에이전트가 없다)
WORKER_ACTIVE = ("T-001: 고정 에이전트가 아직 이 태스크를 하고 있을 수 있다(working). worker_done 을 기다린다. 지금 고쳐야 하면 "
                 "--force(세션을 닫고 새 세션으로 띄운다)")
HANDOFF_LINE = ("먼저 `docs/handoff/production.md` 를 읽는다. 생산 에이전트가 이 프로젝트에서 정한 결정과 규칙, 남은 일이 "
                "적혀 있다.")


def ago(seconds: float) -> str:
    """로컬 오프셋 ISO 8601 초 단위(crew.json 의 시각, 설계 5.9.1) seconds 초 전."""
    return (datetime.now().astimezone() - timedelta(seconds=seconds)).isoformat(timespec="seconds")


class CrewCase(TeamCase):
    CONFIG = CREW_CONFIG

    def setUp(self):
        super().setUp()
        self.init_project(self.CONFIG)
        self.run_id = self.setup_run()
        self.p = Project(self.proj)

    # --- 준비 ---
    def task(self, tid, role="developer", **kw):
        """태스크마다 겹치지 않는 owns 를 준다(잠금이 배정보다 먼저 막지 않게)."""
        base = {"developer": "src", "tester": "tests", "planner": "docs/planning"}[role]
        kw.setdefault("owns", f"{base}/{tid.lower()}/**")
        self.write_spec(tid, role, **kw)
        state.create(self.p, tid, role)

    def work(self, tid, outcome="failed"):
        """작업 워커가 owns 안에 커밋하고 done 한다(기본은 실패: 리뷰 없이 fix 할 수 있는 working 으로 남는다)."""
        role = self.task_state(tid)["role"]
        base = {"developer": "src", "tester": "tests", "planner": "docs/planning"}[role]
        code, out = self.act_work(tid, {f"{base}/{tid.lower()}/a.py": f"{tid}\n"}, outcome=outcome)
        self.assertEqual(code, 0, out)

    def started(self, tid, role="developer", **kw) -> dict:
        self.task(tid, role, **kw)
        code, out = self.hteam("start", tid)
        self.assertEqual(code, 0, out)
        return out

    def tab(self, name="production") -> str:
        return "tb" + hashlib.sha1(f"herdr-team\n{self.proj}\nspA\ncrew\n{name}".encode()).hexdigest()[:32]

    def crew_json(self) -> dict:
        path = self.state_dir / "crew.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def entry(self, name="production") -> dict:
        return self.crew_json()[name]

    def set_entry(self, name="production", **fields) -> None:
        """crew.json 의 entry 를 고친다(없으면 빈 entry 를 만든다). 관제가 그 상태에 닿은 것을 흉내 낸다."""
        data = self.crew_json()
        cur = data.get(name) or crew.blank(name)
        cur.update(fields)
        data[name] = cur
        (self.state_dir / "crew.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def ready(self, terminal, status="done", turn=1):
        """고정 터미널이 턴을 마치고 쉰다(아무도 보지 않는 Claude 는 done 에 머문다, X1)."""
        self.update_terminal(terminal, status=status, turn=turn)

    def free(self, tid):
        """관제가 그 작업의 worker_done 을 처리한 것과 같다: 맡은 태스크를 비우고 since_reset 을 센다(설계 5.9.3 끝)."""
        with self.in_drive():
            crew.work_done(self.p, tid, self.work_dispatch(tid))

    def first(self, tid="T-001") -> str:
        """생산 에이전트를 처음 띄워 tid 를 맡기고 일을 마치게 한 뒤 비운다. 작업 터미널 주소를 낸다."""
        out = self.started(tid)
        self.work(tid)
        self.free(tid)
        self.ready(out["terminal"])
        return out["terminal"]

    def rnd(self, tid) -> dict:
        return self.task_state(tid)["rounds"][-1]

    def terminals(self) -> dict:
        return self.hc_state()["terminals"]

    def decides(self) -> list[dict]:
        return [e for e in self.outbox_items() if e["type"] == "decide"]

    def log_lines(self) -> list[str]:
        path = self.drive_dir / "drive.log"
        return path.read_text(encoding="utf-8").splitlines() if path.is_file() else []

    def calls(self, word) -> list[list[str]]:
        return [c for c in self.herdr_calls() if word in c]

    def delay_get(self, terminal, seconds=5.0) -> None:
        """그 터미널의 hc get 만 늦춘다(hteam 의 3초 확인이 시간을 넘긴다: 상태를 확인할 수 없다)."""
        with self._hc_locked() as st:
            st.setdefault("delay", {})[f"get {terminal}"] = seconds

    def undelay(self) -> None:
        with self._hc_locked() as st:
            st["delay"] = {}

    def set_config(self, text) -> None:
        (self.team / "config.toml").write_text(text, encoding="utf-8")

    def main_bg(self, *args):
        """메인이 큐 명령을 넣고 결과를 기다린다(설계 7.1). 요청 파일이 생길 때까지 기다린 뒤 돌려준다."""
        proc = self.hteam_bg(*args, as_="main", env={"HTEAM_QUEUE_WAIT_S": "30", "HTEAM_QUEUE_POLL_S": "0.05"})
        deadline = time.monotonic() + 20
        while not list((self.drive_dir / "queue").glob("[0-9][0-9][0-9][0-9][0-9][0-9].json")):
            self.assertIsNone(proc.poll(), "메인이 큐에 넣기 전에 끝났다")
            self.assertLess(time.monotonic(), deadline, "요청 파일이 생기지 않았다")
            time.sleep(0.05)
        return proc


class CrewStateTest(CrewCase):
    def test_blank_entry_and_load(self):
        self.assertEqual(crew.load(self.p), {})  # 한 번도 띄우지 않은 에이전트는 entry 가 없다(설계 5.9.1)
        blank = crew.blank("production")
        for key, value in (("terminal", None), ("terminal_argv", None), ("work_pane", None), ("view", None),
                           ("task", None), ("dispatch", None), ("queue", []), ("since_reset", 0), ("reset_tasks", []),
                           ("reset_pending", False), ("resetting", None), ("reset_failures", 0), ("close_failures", 0),
                           ("terminal_unknown_since", None), ("terminal_unknown_asked", False), ("layout_error", None),
                           ("layout_retried", False)):
            self.assertEqual(blank[key], value, key)
        with self.in_drive():
            with crew.edit(self.p) as data:
                data["production"] = {**crew.blank("production"), "queue": ["T-001"]}
        self.assertEqual(crew.load(self.p)["production"]["queue"], ["T-001"])
        (self.state_dir / "crew.json").write_text("{깨짐", encoding="utf-8")
        with self.assertRaises(Exception) as ctx:  # 손상된 기록을 빈 기록으로 보지 않는다
            crew.load(self.p)
        self.assertEqual(getattr(ctx.exception, "code", None), "bad_side_file")

    def test_agent_tab_id(self):
        self.assertEqual(crew.agent_tab(self.p.root, "spA", "production"), self.tab())
        self.assertNotEqual(crew.agent_tab(self.p.root, "spA", "test"), self.tab())


class FirstLaunchTest(CrewCase):
    def test_keep_open_on_agent_tab_with_name_and_record(self):
        cfg = CREW_CONFIG.replace('model = "opus"\neffort = "xhigh"\n\n[crew.test]',
                                  'model = "crew-model"\neffort = "crew-effort"\n\n[crew.test]')
        self.set_config(cfg)
        out = self.started("T-001", front={"claude_model": "haiku"})  # 고정 에이전트 태스크의 front matter 모델은 무시한다
        self.assertEqual((out["status"], out["placement"]), ("working", "pane"), out)
        t = out["terminal"]
        info = self.terminals()[t]
        self.assertEqual((info["labels"]["herdr.space"], info["labels"]["herdr.tab"], info["labels"]["horch.persistent"]),
                         ("spA", self.tab(), "1"))
        row = self.dispatch_row(out["dispatch"])
        self.assertEqual((row["persistent"], row["model"], row["effort"]), (1, "crew-model", "crew-effort"))
        self.assertIn("--name=생산 (Claude)", json.loads(row["agent_args"]))  # 제목이 턴·/clear 뒤에도 남는다(X6)
        rd = self.rnd("T-001")
        self.assertEqual((rd["crew"], rd["model"], rd["effort"], rd["model_ignored"]),
                         ("production", "crew-model", "crew-effort", True))
        e = self.entry()
        self.assertEqual((e["terminal"], e["terminal_argv"], e["agent"], e["model"], e["effort"], e["space"], e["tab"],
                          e["task"], e["dispatch"], e["since_reset"], e["reset_tasks"], e["work_pane"]),
                         (t, info["argv"], "claude", "crew-model", "crew-effort", "spA", self.tab(), "T-001",
                          out["dispatch"], 0, [], f"p{t}"))
        self.assertRegex(e["launched_at"], LOCAL_ISO)
        self.assertIn(["do", "tab.rename", "--id", self.tab(), "--name", "herdr-team 생산"], self.herdr_calls())
        self.assertEqual(self.calls("pane.swap"), [])  # 보기 pane 이 없으면 자리를 바꾸지 않는다

    def test_codex_crew_has_no_name_arg(self):
        cfg = CREW_CONFIG.replace('roles = ["tester"]\nagent = "claude"\nmodel = "sonnet"',
                                  'roles = ["tester"]\nagent = "codex"\nmodel = "gpt-6.1-sol"')
        cfg = cfg.replace('[roles.tester]\ntitle = "테스트"', '[roles.tester]\ntitle = "테스트"\nworker = "codex"')
        self.set_config(cfg)
        out = self.started("T-001", "tester")
        row = self.dispatch_row(out["dispatch"])
        self.assertEqual((row["agent"], row["model"], row["persistent"]), ("codex", "gpt-6.1-sol", 1))
        self.assertFalse(any(a.startswith("--name") for a in json.loads(row["agent_args"])))  # Codex 는 첫 리셋부터 /clear <이름>
        self.assertEqual(self.terminals()[out["terminal"]]["labels"]["herdr.tab"], self.tab("test"))
        self.assertEqual(self.entry("test")["agent"], "codex")

    def test_state_saved_before_layout(self):
        self.task("T-001")
        code, out = self.hteam("start", "T-001", env={"HTEAM_TEST_DIE_AT": "crew_saved"})
        self.assertEqual(code, 137, out)  # 상태 저장 뒤, 배치 전에 죽었다
        self.assertEqual(self.task_state("T-001")["status"], "working")
        e = self.entry()
        self.assertTrue(e["terminal"])
        self.assertEqual((e["task"], e["work_pane"]), ("T-001", None))
        self.assertEqual(self.calls("tab.rename"), [])

    def test_view_pane_kept_and_new_work_pane_swapped_left(self):
        view = {"pane": "pt150", "terminal": "t150", "reviewer": "t140", "task": "T-000", "round": 1, "attempt": 1}
        self.add_terminal("t150", argv=["hc", "attach", "t140"], labels={"herdr.space": "spA", "herdr.tab": self.tab()})
        self.set_entry(view=view)  # 앞 세션 태스크의 리뷰를 보고 있다
        out = self.started("T-001")
        t = out["terminal"]
        swaps = self.calls("pane.swap")
        self.assertEqual(len(swaps), 1, self.herdr_calls())
        self.assertEqual(json.loads(swaps[0][2]), {"pane": f"p{t}", "target": "pt150"})
        self.assertEqual(self.hc_state()["layout"][self.tab()], [t, "t150"])  # 작업 pane 이 왼쪽
        e = self.entry()
        self.assertEqual((e["view"], e["work_pane"], e["layout_error"]), (view, f"p{t}", None))

    def view_terminal(self):
        view = {"pane": "pt150", "terminal": "t150", "reviewer": "t140", "task": "T-000", "round": 1, "attempt": 1}
        self.add_terminal("t150", argv=["hc", "attach", "t140"], labels={"herdr.space": "spA", "herdr.tab": self.tab()})
        self.set_entry(view=view)
        return view

    def test_layout_failure_does_not_block_and_retries_once(self):
        self.view_terminal()
        self.fail_hc("herdr-app pane.swap", "boom")
        t = self.first("T-001")
        e = self.entry()
        self.assertEqual((self.task_state("T-001")["status"], e["work_pane"], e["layout_retried"]),
                         ("working", f"p{t}", False))
        self.assertTrue(e["layout_error"])
        self.assertTrue(any("production 배치 실패" in line for line in self.log_lines()), self.log_lines())
        self.assertEqual(len(self.calls("pane.swap")), 1)
        self.started("T-002")  # 다음 태스크를 넣을 때 한 번만 다시 한다
        self.assertEqual(len(self.calls("pane.swap")), 2)
        self.assertTrue(self.entry()["layout_retried"])
        self.work("T-002")
        self.free("T-002")
        self.ready(t, turn=2)
        self.started("T-003")
        self.assertEqual(len(self.calls("pane.swap")), 2)  # 세 번째는 다시 하지 않는다

    def test_layout_retry_success_clears_error(self):
        self.view_terminal()
        self.fail_hc("herdr-app pane.swap", "boom")
        t = self.first("T-001")
        self.clear_hc("herdr-app pane.swap")
        self.started("T-002")
        e = self.entry()
        self.assertEqual((e["layout_error"], e["work_pane"]), (None, f"p{t}"))
        self.assertEqual(self.hc_state()["layout"][self.tab()], [t, "t150"])

    def clear_hc(self, command):
        with self._hc_locked() as st:
            st["fail"].pop(command, None)


class InsertTest(CrewCase):
    def test_second_task_goes_into_same_terminal(self):
        t = self.first("T-001")
        out = self.started("T-002", front={"claude_model": "haiku"})
        self.assertEqual((out["terminal"], out["placement"], out["start_turn"]), (t, "same_terminal", 1), out)
        row = self.dispatch_row(out["dispatch"])
        self.assertEqual((row["persistent"], row["terminal"], row["launch_argv"], row["model"]), (1, t, None, "opus"))
        rd = self.rnd("T-002")
        self.assertEqual((rd["crew"], rd["start_turn"], rd["model_ignored"], rd["delivery"]["attempted"]),
                         ("production", 1, True, True))
        sent = [s for s in self.hc_state()["sent"] if s["terminal"] == t]
        self.assertEqual((len(sent), sent[-1]["tagged"], sent[-1]["if"]), (1, False, None))  # done 이면 조건 없이, 감싸지 않고
        self.assertEqual(self.entry()["task"], "T-002")
        self.assertEqual(len([c for c in self.hc_calls() if c[:1] == ["run"]]), 1)  # 새 터미널을 띄우지 않았다
        spec = (self.state_dir / "tasks/T-002/r1-work.md").read_text(encoding="utf-8")
        self.assertIn("## 선행 태스크", spec)

    def test_idle_session_gets_if_idle(self):
        t = self.first("T-001")
        self.ready(t, status="idle")
        self.started("T-002")
        sent = [s for s in self.hc_state()["sent"] if s["terminal"] == t]
        self.assertEqual(sent[-1]["if"], "idle")

    def test_not_ready_at_send_is_transient_and_start_ready_resends(self):
        t = self.first("T-001")
        with self._hc_locked() as st:
            st["on_send"] = {t: "mismatch"}  # 확인과 보내기 사이에 일을 시작했다
        self.task("T-002")
        code, out = self.hteam("start", "T-002")
        self.assertEqual((code, out["error"]["code"], out["horch"]["error"]["code"]), (1, "launch_failed", "terminal_not_ready"),
                         out)
        self.assertEqual(self.task_state("T-002")["status"], "launch_failed")
        self.assertTrue(self.rnd("T-002")["work"]["transient"])  # 일시 거부 표시(관제 재확인이 decide 를 올리지 않는다)
        with self._hc_locked() as st:
            st["on_send"] = {}
        code, out = self.hteam("start-ready")
        self.assertEqual((code, [s["task"] for s in out["started"]]), (0, ["T-002"]), out)
        self.assertEqual((self.task_state("T-002")["status"], self.rnd("T-002")["work"].get("transient")), ("working", None))
        self.assertEqual(self.dispatch_row(self.work_dispatch("T-002"))["terminal"], t)

    def test_unknown_terminal_is_not_used_and_task_waits(self):
        t = self.first("T-001")
        self.delay_get(t)
        self.task("T-002")
        code, out = self.hteam("start", "T-002")
        self.assertEqual((code, out["status"], out["reason"]), (0, "waiting", "agent"), out)
        self.assertIn(f"생산 에이전트 작업 터미널({t}) 상태를 확인하지 못했다", out["message"])
        self.assertEqual(self.task_state("T-002")["status"], "pending")
        self.assertRegex(self.entry()["terminal_unknown_since"], LOCAL_ISO)
        self.assertEqual(len([c for c in self.hc_calls() if c[:1] == ["run"]]), 1)  # 살아 있을지 모르는 세션 옆에 새로 띄우지 않는다

    def test_busy_session_without_task_goes_to_temp_worker(self):
        t = self.first("T-001")
        self.ready(t, status="working")  # 사람이 친 글로 일하는 중(맡은 태스크는 없다)
        out = self.started("T-002")
        self.assertNotEqual(out["terminal"], t)
        self.assertEqual(self.rnd("T-002")["crew"], "temp")
        self.assertEqual(self.terminals()[out["terminal"]]["labels"]["herdr.tab"], "tbTeam")  # 임시 워커는 관제 탭

    def test_lost_terminal_is_forgotten_and_new_session_launched(self):
        t = self.first("T-001")
        self.update_terminal(t, argv=["zsh"])  # 같은 주소에 다른 프로그램(lost, terminal_argv 와 다름)
        out = self.started("T-002")
        self.assertNotEqual(out["terminal"], t)
        self.assertNotIn(t, self.terminals())  # terminal-close --abandon 이 끄고 지웠다
        self.assertEqual(self.dispatch_row(out["dispatch"])["persistent"], 1)
        e = self.entry()
        self.assertEqual((e["terminal"], e["task"], e["work_pane"]), (out["terminal"], "T-002", f"p{out['terminal']}"))

    def test_finished_terminal_is_forgotten(self):
        t = self.first("T-001")
        self.update_terminal(t, state="finished")
        out = self.started("T-002")
        self.assertNotEqual(out["terminal"], t)
        self.assertEqual(self.entry()["terminal"], out["terminal"])

    def test_uncertain_delivery_stays_working(self):
        t = self.first("T-001")
        self.fail_hc("send", "timeout")  # 응답 유실: 들어갔을 수 있다
        out = self.started("T-002")
        self.assertIn("delivery_uncertain", out["warnings"])
        self.assertEqual(self.task_state("T-002")["status"], "working")
        self.assertTrue(self.rnd("T-002")["delivery"]["uncertain"])
        self.assertEqual(out["terminal"], t)


class PlaceTest(CrewCase):
    def test_role_without_crew_is_temp(self):
        self.set_config(NO_TEST_CREW)
        out = self.started("T-001", "tester")
        self.assertEqual((self.rnd("T-001")["crew"], self.terminals()[out["terminal"]]["labels"]["herdr.tab"]),
                         ("temp", "tbTeam"))
        self.assertEqual(self.dispatch_row(out["dispatch"])["persistent"], 0)

    def test_other_work_agent_is_temp(self):
        out = self.started("T-001", front={"worker": "codex"})  # 작업 에이전트가 고정 에이전트(claude)와 다르다
        self.assertEqual(self.rnd("T-001")["crew"], "temp")
        self.assertEqual(self.dispatch_row(out["dispatch"])["agent"], "codex")
        self.assertNotIn("production", self.crew_json())

    def test_live_session_agent_wins_over_config(self):
        t = self.first("T-001")
        self.set_entry(agent="codex")  # 떠 있는 세션의 에이전트(설정을 바꾼 뒤에도 그 세션은 그대로다)
        out = self.started("T-002")
        self.assertNotEqual(out["terminal"], t)
        self.assertEqual(self.rnd("T-002")["crew"], "temp")

    def test_resetting_waits(self):
        self.set_entry(resetting={"step": "handoff", "dispatch": "dsp-x", "at": ago(1)})
        self.task("T-001")
        code, out = self.hteam("start", "T-001")
        self.assertEqual((code, out["id"], out["status"], out["reason"]), (0, "T-001", "waiting", "agent"), out)
        self.assertEqual(out["message"], f"T-001: {WAIT_RESET}. pending 으로 두었다. 에이전트가 비면 관제가 띄운다")
        self.assertEqual(self.task_state("T-001")["status"], "pending")

    def test_pending_reset_without_task_waits(self):
        self.set_entry(reset_pending=True)  # 리셋은 짧고 다음 세션이 받게 한다(설계 5.9.4 의 4)
        self.task("T-001")
        code, out = self.hteam("start", "T-001")
        self.assertEqual((code, out["status"], out["reason"]), (0, "waiting", "agent"), out)
        self.assertIn(WAIT_RESET, out["message"])

    def test_busy_agent_overflows_to_temp_or_waits(self):
        self.set_entry(task="T-009", dispatch="dsp-x")
        out = self.started("T-001")
        self.assertEqual(self.rnd("T-001")["crew"], "temp")
        self.set_config(CREW_CONFIG + "\n[overflow]\nenabled = false\n")
        self.task("T-002")
        code, out = self.hteam("start", "T-002")
        self.assertEqual((code, out["status"], out["reason"], out["message"]),
                         (0, "waiting", "agent", f"T-002: {WAIT_BUSY}. pending 으로 두었다. 에이전트가 비면 관제가 띄운다"), out)

    def test_queue_counts_as_busy(self):
        self.set_entry(queue=["T-009"])
        self.started("T-001")
        self.assertEqual(self.rnd("T-001")["crew"], "temp")

    def test_place_function_table(self):
        cfg = config.load(self.p)
        with self.in_drive():
            self.assertEqual(crew.place(self.p, cfg, "developer", "claude")["kind"], "crew")
            self.assertEqual(crew.place(self.p, cfg, "developer", "codex")["kind"], "temp")
            self.set_entry(resetting={"step": "clear", "at": ago(1)})
            got = crew.place(self.p, cfg, "planner", "claude")
            self.assertEqual((got["kind"], got["reason"]), ("wait", WAIT_RESET))
            self.assertEqual(crew.place(self.p, cfg, "tester", "claude")["kind"], "crew")


class StartWaitingTest(CrewCase):
    CONFIG = BASE_CONFIG

    def test_pending_with_unmet_deps_waits(self):
        self.task("T-001")
        self.task("T-002", depends="T-001")
        code, out = self.hteam("start", "T-002")
        self.assertEqual((code, out["id"], out["status"], out["reason"]), (0, "T-002", "waiting", "deps"), out)
        self.assertIn("T-001(pending)", out["message"])
        self.assertTrue(out["message"].endswith("pending 으로 두었다. 선행이 끝나면 관제가 띄운다"), out["message"])
        self.assertEqual(self.task_state("T-002")["status"], "pending")

    def test_pending_with_lock_waits(self):
        self.started("T-001")
        self.task("T-002", owns="src/t-001/auth/**")
        code, out = self.hteam("start", "T-002")
        self.assertEqual((code, out["status"], out["reason"]), (0, "waiting", "lock"), out)
        self.assertTrue(out["message"].startswith("T-002: "), out["message"])
        self.assertTrue(out["message"].endswith("pending 으로 두었다. 잠금이 풀리면 관제가 띄운다"), out["message"])

    def test_recovery_still_refuses_with_exit_3(self):
        self.task("T-001")
        self.fail_hc("run", "boom")
        self.assertEqual(self.hteam("start", "T-001")[0], 1)  # 띄우기 실패: launch_failed 로 같은 라운드 복구를 기다린다
        self.task("T-002")
        with state.edit(self.p, "T-002") as st:  # 그 사이 겹치는 소유 경로를 잠근 태스크(손으로 만든 상태)
            st["owns"] = ["src/t-001/**"]
            state.move(st, "working", "test")
        code, out = self.hteam("start", "T-001")  # 같은 라운드 복구는 waiting 이 아니라 지금처럼 exit 3
        self.assertEqual((code, out["error"]["code"]), (3, "owns_locked"), out)
        self.assertEqual(self.task_state("T-001")["status"], "launch_failed")


class StartReadyCrewTest(CrewCase):
    def test_combined_limit_counts_crew_and_temp(self):
        self.set_config(CREW_CONFIG.replace("max_parallel = 4", "max_parallel = 2"))
        self.started("T-001")  # 생산 에이전트
        self.task("T-002")
        self.task("T-003")
        code, out = self.hteam("start-ready")
        self.assertEqual(code, 0, out)
        self.assertEqual([s["task"] for s in out["started"]], ["T-002"], out)  # 넘침으로 임시 워커
        self.assertEqual({w["task"]: w["reason"] for w in out["waiting"]}, {"T-003": "limit"}, out)  # 고정 + 임시 = 2
        self.assertEqual(self.rnd("T-002")["crew"], "temp")

    def test_agent_reason_when_overflow_off(self):
        self.set_config(CREW_CONFIG + "\n[overflow]\nenabled = false\n")
        self.started("T-001")
        self.task("T-002")
        code, out = self.hteam("start-ready")
        self.assertEqual((code, out["started"]), (0, []), out)
        self.assertEqual([(w["task"], w["reason"]) for w in out["waiting"]], [("T-002", "agent")], out)
        self.assertIn("생산", out["waiting"][0]["detail"])
        self.assertEqual(self.task_state("T-002")["status"], "pending")

    def test_recovery_waiting_for_agent_is_agent_busy(self):
        t = self.first("T-001")
        with self._hc_locked() as st:
            st["on_send"] = {t: "mismatch"}
        self.task("T-002")
        self.assertEqual(self.hteam("start", "T-002")[0], 1)  # 일시 거부로 launch_failed
        self.set_entry(task="T-009", dispatch="dsp-x")
        self.set_config(CREW_CONFIG + "\n[overflow]\nenabled = false\n")
        code, out = self.hteam("start", "T-002")  # 같은 라운드 복구가 에이전트를 기다려야 한다
        self.assertEqual((code, out["error"]["code"]), (3, "agent_busy"), out)


class FixQueueTest(CrewCase):
    def test_fix_inserts_into_same_session_when_free(self):
        t = self.first("T-001")
        code, out = self.hteam("fix", "T-001", "--note=표를 고친다")
        self.assertEqual((code, out["round"], out["terminal"]), (0, 2, t), out)
        rd = self.rnd("T-001")
        self.assertEqual((rd["crew"], rd["note"]), ("production", "표를 고친다"))
        first = self.task_state("T-001")["rounds"][0]["work"]["dispatch"]
        self.assertEqual(self.dispatch_row(first)["state"], "released")
        self.assertIn(t, self.terminals())  # 고정 Dispatch 의 release 는 터미널을 남긴다

    def test_other_worker_refused(self):
        self.first("T-001")
        code, out = self.hteam("fix", "T-001", "--worker", "codex")
        self.assertEqual((code, out["error"]["code"], out["error"]["message"]),
                         (2, "usage", "T-001: 고정 에이전트 태스크의 수정 라운드는 작업 에이전트를 바꾸지 못한다"), out)

    def test_busy_agent_queues_and_merges(self):
        t = self.first("T-001")
        self.started("T-002")  # 에이전트가 T-002 를 한다
        code, out = self.hteam("fix", "T-001", "--note=첫째")
        self.assertEqual((code, out), (0, {"ok": True, "id": "T-001", "status": "queued", "agent": "production"}))
        code, _ = self.hteam("fix", "T-001", "--note=둘째", "--force-round")
        self.assertEqual(code, 0)
        self.assertEqual(self.hteam("fix", "T-001", "--note=첫째")[0], 0)  # 같은 줄은 한 번만
        q = self.task_state("T-001")["queued_fix"]
        self.assertEqual((q["note"], q["force_round"], q["supplement"], q["request"]), ("첫째\n둘째", True, None, None))
        self.assertRegex(q["at"], r"Z$")
        self.assertEqual(self.entry()["queue"], ["T-001"])
        self.assertEqual(self.task_state("T-001")["round"], 1)  # 새 라운드는 꺼낼 때 연다
        code, out = self.hteam("status")
        row = next(x for x in out["tasks"] if x["id"] == "T-001")
        self.assertEqual((row["next"], row["hint"]),
                         (None, "수정 라운드가 에이전트 대기열에 있다. 에이전트가 비면 관제가 띄운다"))
        self.assertEqual(self.dispatch_row(self.work_dispatch("T-002"))["terminal"], t)

    def test_own_task_is_not_queued_behind_itself(self):
        out = self.started("T-001")
        t = out["terminal"]
        self.ready(t, status="idle")  # done 을 부르지 않고 턴을 마쳤다(맡은 태스크는 그대로 T-001)
        code, res = self.hteam("fix", "T-001", "--note=이어서")
        self.assertEqual((code, res["round"], res["terminal"]), (0, 2, t), res)
        self.assertEqual(self.dispatch_row(out["dispatch"])["state"], "released")  # abandon --keep-terminal 뒤 release
        self.assertNotIn("queued_fix", self.task_state("T-001"))
        self.assertEqual(self.entry()["queue"], [])

    def test_own_task_is_not_queued_even_behind_another_queued_fix(self):
        """자기 태스크는 다른 태스크의 수정이 이미 줄 서 있어도 대기열에 넣지 않는다(설계 5.9.5). 넣으면 그 태스크가 맡은
        태스크로 남아 드레인이 영영 꺼내지 않는다."""
        self.first("T-001")
        out = self.started("T-002")  # 에이전트가 T-002 를 맡는다
        self.assertEqual(self.hteam("fix", "T-001", "--note=하나")[1]["status"], "queued")
        self.ready(out["terminal"], status="idle", turn=2)  # T-002 를 done 없이 마쳤다(맡은 태스크는 그대로 T-002)
        code, res = self.hteam("fix", "T-002", "--note=이어서")
        self.assertEqual((code, res["round"], res["terminal"]), (0, 2, out["terminal"]), res)
        self.assertNotIn("queued_fix", self.task_state("T-002"))
        self.assertEqual((self.entry()["queue"], self.entry()["task"]), (["T-001"], "T-002"))
        self.assertEqual(self.dispatch_row(out["dispatch"])["state"], "released")

    def test_queued_result_logs_no_round_start(self):
        """라운드를 열지 않은 queued 결과에는 `<T> r<n> 수정 시작` 을 남기지 않는다(설계 8.11): 관제 fix 와 메인 큐 fix 모두.
        관제 fix 이어 하기 표시(drive_fix)는 줄을 서는 쓰기가 지운다(설계 8.7)."""
        self.first("T-001")
        self.started("T-002")  # 에이전트가 바쁘다
        with self.in_drive():
            res = self.make_drive().fix_task("T-001", "관제 지시")
        self.assertEqual((res["status"], res["agent"]), ("queued", "production"), res)
        st = self.task_state("T-001")
        self.assertEqual((st["queued_fix"]["note"], st["round"]), ("관제 지시", 1))
        self.assertNotIn("drive_fix", st)
        proc = self.main_bg("fix", "T-001", "--note=메인 지시")
        with self.in_drive():
            self.assertEqual(self.make_drive().run_queue(), ["q-000001"])
        code, out = self.finish(proc)
        self.assertEqual((code, out["status"]), (0, "queued"), out)
        self.assertEqual(self.task_state("T-001")["queued_fix"]["note"], "관제 지시\n메인 지시")
        lines = [line.split(" ", 1)[1] for line in self.log_lines()]
        self.assertIn("요청 q-000001 fix: 완료", lines)
        self.assertFalse(any("수정 시작" in line for line in lines), lines)

    def test_own_task_still_working_refuses(self):
        out = self.started("T-001")
        self.ready(out["terminal"], status="working")
        code, res = self.hteam("fix", "T-001", "--note=이어서")
        self.assertEqual((code, res["error"]["code"], res["error"]["message"]), (3, "worker_active", WORKER_ACTIVE), res)
        self.assertEqual(self.task_state("T-001")["round"], 1)

    def test_drain_one_per_agent_without_requeue(self):
        t = self.first("T-001")
        self.started("T-002")
        self.work("T-002")
        self.free("T-002")
        self.ready(t, turn=2)
        self.started("T-003")  # 에이전트가 T-003 을 한다
        self.assertEqual(self.hteam("fix", "T-001", "--note=하나")[1]["status"], "queued")
        self.assertEqual(self.hteam("fix", "T-002", "--note=둘")[1]["status"], "queued")
        self.assertEqual(self.entry()["queue"], ["T-001", "T-002"])
        self.work("T-003")
        self.free("T-003")
        self.ready(t, turn=3)
        code, out = self.hteam("start-ready")
        self.assertEqual(code, 0, out)
        self.assertEqual([d["task"] for d in out["drained"]], ["T-001"], out)  # 에이전트마다 한 번에 하나
        self.assertEqual(self.task_state("T-001")["round"], 2)
        self.assertNotIn("queued_fix", self.task_state("T-001"))
        self.assertEqual(self.entry()["queue"], ["T-002"])
        self.assertEqual((self.rnd("T-001")["note"], self.entry()["task"]), ("하나", "T-001"))
        self.assertEqual(self.dispatch_row(self.work_dispatch("T-001"))["terminal"], t)
        self.assertEqual(self.task_state("T-002")["round"], 1)

    def test_drain_alone_in_queue_inserts_directly(self):
        t = self.first("T-001")
        with state.edit(self.p, "T-001") as st:
            st["queued_fix"] = {"note": "다시", "supplement": None, "force_round": False, "at": "2026-01-01T00:00:00Z",
                                "request": None}
        self.set_entry(queue=["T-001"])  # 에이전트는 비었고 대기열에는 이 태스크 하나
        code, out = self.hteam("start-ready")
        self.assertEqual([d["task"] for d in out["drained"]], ["T-001"], out)
        self.assertEqual((self.task_state("T-001")["round"], self.entry()["queue"]), (2, []))
        self.assertEqual(self.dispatch_row(self.work_dispatch("T-001"))["terminal"], t)

    def test_drain_skips_unknown_or_busy_terminal(self):
        t = self.first("T-001")
        with state.edit(self.p, "T-001") as st:
            st["queued_fix"] = {"note": "다시", "supplement": None, "force_round": False, "at": "2026-01-01T00:00:00Z",
                                "request": None}
        self.set_entry(queue=["T-001"])
        self.ready(t, status="working")
        code, out = self.hteam("start-ready")
        self.assertEqual((code, out.get("drained")), (0, []), out)
        self.assertEqual(self.entry()["queue"], ["T-001"])
        self.ready(t, status="blocked")
        self.assertEqual(self.hteam("start-ready")[1].get("drained"), [])
        self.assertEqual(self.task_state("T-001")["round"], 1)

    def test_drain_refused_clears_and_decides(self):
        self.first("T-001")
        self.started("T-002")
        self.assertEqual(self.hteam("fix", "T-001", "--note=고친다")[1]["status"], "queued")
        self.set_config(CREW_CONFIG.replace("max_rounds = 3", "max_rounds = 1"))
        self.free("T-002")
        self.ready(self.entry()["terminal"], turn=2)
        code, out = self.hteam("start-ready")
        self.assertEqual(code, 0, out)
        self.assertNotIn("queued_fix", self.task_state("T-001"))
        self.assertEqual((self.task_state("T-001")["round"], self.entry()["queue"]), (1, []))
        d = [x for x in self.decides() if x["task"] == "T-001"]
        self.assertEqual(len(d), 1, self.decides())
        self.assertEqual(d[0]["kind"], "escalation")
        self.assertIn("관제 절차 실패", d[0]["summary"])
        self.assertIn("(아직 전하지 못한 지시: 고친다)", d[0]["summary"])
        self.assertTrue(any("--force-round" in c for c in d[0]["commands"]), d[0]["commands"])

    def test_queue_sync_repairs_both_ways(self):
        self.task("T-001")
        self.task("T-002")
        for tid in ("T-001", "T-002"):
            with state.edit(self.p, tid) as st:
                st["rounds"] = [{"round": 1, "crew": "production", "work": {"title": f"{tid} r1 작업"}, "reviews": []}]
                st["round"] = 1
        with state.edit(self.p, "T-001") as st:  # 표시를 쓰고 큐에 넣기 전에 죽었다
            st["queued_fix"] = {"note": "a", "supplement": None, "force_round": False, "at": "2026-01-01T00:00:00Z",
                                "request": None}
        self.set_entry(queue=["T-002"])  # 라운드를 연 뒤(queued_fix 를 지운 뒤) 큐에서 빼기 전에 죽었다
        with self.in_drive():
            crew.sync_queues(self.p)
        self.assertEqual(self.entry()["queue"], ["T-001"])

    def test_queue_sync_orders_by_queued_at(self):
        for tid, at in (("T-001", "2026-01-01T00:00:09Z"), ("T-002", "2026-01-01T00:00:01Z")):
            self.task(tid, owns=f"src/{tid}/**")
            with state.edit(self.p, tid) as st:
                st["rounds"] = [{"round": 1, "crew": "production", "work": {"title": f"{tid} r1 작업"}, "reviews": []}]
                st["round"] = 1
                st["queued_fix"] = {"note": "x", "supplement": None, "force_round": False, "at": at, "request": None}
        with self.in_drive():
            crew.sync_queues(self.p)
        self.assertEqual(self.entry()["queue"], ["T-002", "T-001"])

    def test_accept_and_drop_clear_queued_fix(self):
        self.first("T-001")
        self.started("T-002")
        self.hteam("fix", "T-001", "--note=x")
        self.assertEqual(self.entry()["queue"], ["T-001"])
        code, out = self.hteam("drop", "T-001")
        self.assertEqual(code, 0, out)
        self.assertNotIn("queued_fix", self.task_state("T-001"))
        self.assertEqual(self.entry()["queue"], [])
        self.task("T-003", owns="src/c/**")
        with state.edit(self.p, "T-003") as st:
            st["rounds"] = [{"round": 1, "crew": "production", "agent": "claude", "model": "opus", "effort": "xhigh",
                             "work": {"title": "T-003 r1 작업", "horch_task": None, "dispatch": None, "launched": None,
                                      "error": None, "canceled": False, "cleaned": True}, "reviews": [], "verdict": "APPROVE"}]
            st["round"] = 1
            st["owns"] = ["src/c/**"]
            state.move(st, "approved", "review-finish")
            st["queued_fix"] = {"note": "y", "supplement": None, "force_round": False, "at": "2026-01-01T00:00:00Z",
                                "request": None}
        self.set_entry(queue=["T-003"])
        code, out = self.hteam("accept", "T-003")
        self.assertEqual((code, out["status"]), (0, "done"), out)
        self.assertNotIn("queued_fix", self.task_state("T-003"))
        self.assertEqual(self.entry()["queue"], [])

    def test_temp_task_fix_stays_temp(self):
        self.set_entry(task="T-009", dispatch="dsp-x")
        out = self.started("T-001")  # 넘침으로 임시 워커
        self.work("T-001")
        self.set_entry(task=None, dispatch=None)  # 그새 에이전트가 비어도 옮기지 않는다
        code, res = self.hteam("fix", "T-001", "--note=x")
        self.assertEqual(code, 0, res)
        self.assertEqual(self.rnd("T-001")["crew"], "temp")
        self.assertNotEqual(res["terminal"], self.entry().get("terminal"))


class ForceTest(CrewCase):
    def test_fix_force_closes_working_session_and_launches_new(self):
        view = {"pane": "pt150", "terminal": "t150", "reviewer": "t140", "task": "T-000", "round": 1, "attempt": 1}
        out = self.started("T-001")
        t = out["terminal"]
        self.add_terminal("t150", argv=["hc", "attach", "t140"], labels={"herdr.space": "spA", "herdr.tab": self.tab()})
        self.set_entry(view=view)
        self.ready(t, status="working")
        code, res = self.hteam("fix", "T-001", "--force", "--note=새로")
        self.assertEqual(code, 0, res)
        self.assertNotIn(t, self.terminals())  # terminal-close --abandon 이 끄고 지웠다
        self.assertNotEqual(res["terminal"], t)
        rd = self.rnd("T-001")
        self.assertEqual((rd["round"], rd["forced"], rd["crew"]), (2, True, "production"))
        e = self.entry()
        self.assertEqual((e["terminal"], e["task"], e["view"]), (res["terminal"], "T-001", view))  # 세션 교체가 view 를 지우지 않는다
        self.assertEqual(self.dispatch_row(out["dispatch"])["state"], "released")

    def test_fix_force_close_failure_keeps_everything(self):
        out = self.started("T-001")
        t = out["terminal"]
        self.ready(t, status="working")
        self.fail_hc("kill", "timeout")
        code, res = self.hteam("fix", "T-001", "--force", "--note=새로")
        self.assertEqual((code, res["error"]["code"]), (1, "stop_failed"), res)
        self.assertTrue(res["error"]["message"].startswith("T-001: 일하는 중일 수 있는 이전 세션을 닫지 못했다("), res)
        self.assertTrue(res["error"]["message"].endswith(
            "). 다시 띄우지 않았다. 사용자에게 그 에이전트 탭의 작업 pane 을 닫아 달라고 한 뒤 다시 한다"), res)
        self.assertEqual((self.task_state("T-001")["round"], self.entry()["terminal"], self.entry()["task"]), (1, t, "T-001"))
        self.assertIn(t, self.terminals())

    def test_force_on_task_the_agent_left_does_not_touch_session(self):
        t = self.first("T-001")
        self.started("T-002")  # 에이전트는 이제 T-002 를 한다
        self.ready(t, status="working")
        code, res = self.hteam("fix", "T-001", "--force", "--note=x")
        self.assertEqual((code, res.get("status")), (0, "queued"), res)
        self.assertIn(t, self.terminals())
        self.assertEqual(self.terminals()[t]["state"], "live")
        self.assertEqual(self.entry()["task"], "T-002")
        code, res = self.hteam("drop", "T-001", "--force")
        self.assertEqual((code, res["status"]), (0, "dropped"), res)
        self.assertEqual((self.terminals()[t]["state"], self.entry()["terminal"], self.entry()["task"]), ("live", t, "T-002"))

    def test_temp_worker_force_is_ignored(self):
        self.set_entry(task="T-009", dispatch="dsp-x")
        out = self.started("T-001")
        self.update_terminal(out["terminal"], status="working")
        code, res = self.hteam("fix", "T-001", "--force", "--note=x")  # 임시 워커는 지금처럼 abandon --kill 뒤 release
        self.assertEqual((code, res["round"]), (0, 2), res)
        self.assertNotIn("forced", self.rnd("T-001"))
        self.assertEqual(self.dispatch_row(out["dispatch"])["state"], "released")


class DropCrewTest(CrewCase):
    def test_drop_idle_session_keeps_it(self):
        out = self.started("T-001")
        t = out["terminal"]
        self.ready(t, status="idle")
        for args in (("drop", "T-001"),):
            code, res = self.hteam(*args)
            self.assertEqual((code, res["status"]), (0, "dropped"), res)
        self.assertEqual(self.terminals()[t]["state"], "live")  # 쉬는 세션은 닫지 않는다
        self.assertEqual(self.dispatch_row(out["dispatch"])["state"], "released")
        e = self.entry()
        self.assertEqual((e["terminal"], e["task"]), (t, None))

    def test_drop_force_idle_session_keeps_it(self):
        out = self.started("T-001")
        self.ready(out["terminal"], status="done")
        code, res = self.hteam("drop", "T-001", "--force")
        self.assertEqual((code, res["status"]), (0, "dropped"), res)
        self.assertEqual(self.terminals()[out["terminal"]]["state"], "live")

    def test_drop_force_working_session_closes_and_forgets(self):
        out = self.started("T-001")
        t = out["terminal"]
        self.ready(t, status="working")
        code, res = self.hteam("drop", "T-001", "--force")
        self.assertEqual((code, res["status"]), (0, "dropped"), res)
        self.assertNotIn(t, self.terminals())
        self.assertEqual((self.entry()["terminal"], self.entry()["task"]), (None, None))
        self.assertNotIn("hint", res)

    def test_drop_force_close_failure_still_drops_and_forgets(self):
        out = self.started("T-001")
        t = out["terminal"]
        self.ready(t, status="working")
        self.fail_hc("kill", "timeout")
        code, res = self.hteam("drop", "T-001", "--force")
        self.assertEqual((code, res["status"]), (0, "dropped"), res)
        self.assertEqual(res["hint"], "이전 세션을 닫지 못했다. 사용자에게 그 에이전트 탭의 작업 pane 을 닫아 달라고 한다. 닫지 "
                                      "않으면 이전 세션이 지금 풀린 소유 경로를 계속 고칠 수 있다")
        self.assertEqual((self.entry()["terminal"], self.entry()["task"]), (None, None))  # 다음 태스크가 그 세션에 들어가지 않게 잊는다

    def test_drop_working_without_force_refuses(self):
        out = self.started("T-001")
        self.ready(out["terminal"], status="working")
        code, res = self.hteam("drop", "T-001")
        self.assertEqual((code, res["error"]["code"]), (3, "worker_active"), res)


class HandoffLineTest(CrewCase):
    def spec_text(self, tid, role="developer", **front):
        self.write_spec(tid, role, front=front or None, commit=False)
        cfg = config.load(self.p)
        spec = specs.load(self.p, tid)
        return compose.work_spec(self.p, cfg, spec, {"round": 1}, cfg.owns(role))

    def test_line_when_file_exists_for_crew_and_temp_tasks(self):
        self.assertNotIn("docs/handoff", self.spec_text("T-001"))  # 파일이 없으면 없다
        (self.proj / "docs/handoff").mkdir(parents=True)
        (self.proj / "docs/handoff/production.md").write_text("결정\n", encoding="utf-8")  # 커밋 여부는 보지 않는다
        text = self.spec_text("T-002")
        self.assertIn(HANDOFF_LINE + "\n\n", text)
        self.assertLess(text.index("## 선행 태스크"), text.index(HANDOFF_LINE))
        self.assertLess(text.index(HANDOFF_LINE), text.index("- `src/**`"))
        self.assertIn(HANDOFF_LINE, self.spec_text("T-003", worker="codex"))  # 그 직무의 임시 워커 태스크에도

    def test_no_line_for_role_without_crew(self):
        (self.proj / "docs/handoff").mkdir(parents=True)
        (self.proj / "docs/handoff/test.md").write_text("x\n", encoding="utf-8")
        self.assertIn("docs/handoff/test.md", self.spec_text("T-001", "tester"))
        self.set_config(NO_TEST_CREW)
        self.assertNotIn("docs/handoff", self.spec_text("T-002", "tester"))


class DriveCrewEventTest(CrewCase):
    def test_worker_done_frees_agent_and_counts_tasks(self):
        t = self.first("T-001")
        e = self.entry()
        self.assertEqual((e["task"], e["dispatch"], e["since_reset"], e["reset_tasks"]), (None, None, 1, ["T-001"]))
        self.assertEqual(self.hteam("fix", "T-001", "--note=다시")[0], 0)
        self.work("T-001")
        self.free("T-001")
        self.assertEqual(self.entry()["since_reset"], 1)  # 같은 태스크의 수정 라운드는 다시 세지 않는다
        self.ready(t, turn=2)
        self.started("T-002")
        self.work("T-002")
        self.free("T-002")
        self.assertEqual((self.entry()["since_reset"], self.entry()["reset_tasks"]), (2, ["T-001", "T-002"]))

    def test_work_done_of_other_task_keeps_assignment(self):
        self.started("T-001")
        with self.in_drive():
            self.assertIsNone(crew.work_done(self.p, "T-009", "dsp-x"))
        self.assertEqual(self.entry()["task"], "T-001")

    def test_handle_failed_worker_done_frees_agent(self):
        out = self.started("T-001")
        self.work("T-001")
        body = {"dispatch": out["dispatch"], "task": out["task"], "outcome": "failed", "summary": "막혔다",
                "report_path": "docs/tasks/T-001/report.md", "files_modified": []}
        with self.in_drive():
            self.make_drive().handle(self.message("worker_done", out["dispatch"], body))
        e = self.entry()
        self.assertEqual((e["task"], e["since_reset"]), (None, 1))
        self.assertEqual([d["kind"] for d in self.decides() if d["task"] == "T-001"], ["worker_failed"])

    def test_handle_exited_forgets_terminal_and_fixes_in_new_session(self):
        view = {"pane": "pt150", "terminal": "t150", "reviewer": "t140", "task": "T-000", "round": 1, "attempt": 1}
        out = self.started("T-001")
        t = out["terminal"]
        self.add_terminal("t150", argv=["hc", "attach", "t140"], labels={"herdr.space": "spA", "herdr.tab": self.tab()})
        self.set_entry(view=view)
        self.update_terminal(t, state="finished")
        body = {"dispatch": out["dispatch"], "kind": "exited", "key": "exited", "terminal": t, "status": None}
        with self.in_drive():
            self.make_drive().handle(self.message("observed", out["dispatch"], body, sender="horch"))
        st = self.task_state("T-001")
        self.assertEqual(st["round"], 2)
        self.assertIn("이전 작업자가 중간에 끝났다", st["rounds"][-1]["note"])
        e = self.entry()
        self.assertNotEqual(e["terminal"], t)  # 새 세션
        self.assertEqual((e["task"], e["view"]), ("T-001", view))


class TerminalCheckTest(CrewCase):
    def setUp(self):
        super().setUp()
        self.t = self.first("T-001")

    def check(self):
        with self.in_drive():
            crew.check_terminals(self.make_drive())

    def test_dead_terminal_forgotten_once_and_view_kept(self):
        view = {"pane": "pt150", "terminal": "t150", "reviewer": "t140", "task": "T-001", "round": 1, "attempt": 1}
        self.set_entry(view=view)
        self.update_terminal(self.t, state="finished")
        self.check()
        self.check()
        e = self.entry()
        self.assertEqual((e["terminal"], e["work_pane"], e["view"]), (None, None, view))
        self.assertNotIn(self.t, self.terminals())  # terminal-close --abandon 으로 남은 기록을 정리했다
        self.assertEqual(sum("production 작업 터미널이 닫혀 잊음" in line for line in self.log_lines()), 1, self.log_lines())

    def test_lost_by_terminal_argv(self):
        self.update_terminal(self.t, argv=["zsh"])
        self.check()
        self.assertIsNone(self.entry()["terminal"])

    def test_missing_argv_is_filled(self):
        argv = self.terminals()[self.t]["argv"]
        self.set_entry(terminal_argv=None)
        self.check()
        self.assertEqual(self.entry()["terminal_argv"], argv)
        self.assertEqual(self.entry()["terminal"], self.t)

    def test_idle_agent_stuck_decides_once(self):
        old_ms = int((datetime.now() - timedelta(seconds=120)).timestamp() * 1000)
        self.update_terminal(self.t, status="blocked", status_ms=old_ms)
        self.check()
        self.check()
        d = [x for x in self.decides() if "production 에이전트 작업 세션이 태스크 없이" in x["summary"]]
        self.assertEqual(len(d), 1, self.decides())
        self.assertEqual(d[0]["summary"], "production 에이전트 작업 세션이 태스크 없이 blocked 로 멈춰 있다. 사용자에게 그 탭을 보고 "
                                          "넘기거나 작업 pane 을 닫아 달라고 한다(닫으면 관제가 다음 태스크 때 새 세션을 띄운다)")
        self.assertEqual(d[0]["kind"], "escalation")

    def test_recent_stuck_state_waits(self):
        now_ms = int(datetime.now().timestamp() * 1000)
        self.update_terminal(self.t, status="error", status_ms=now_ms)
        self.check()
        self.assertEqual(self.decides(), [])

    def test_unknown_for_thirty_minutes_decides_once_then_clears(self):
        self.delay_get(self.t)
        self.check()
        self.assertRegex(self.entry()["terminal_unknown_since"], LOCAL_ISO)
        self.assertEqual(self.decides(), [])
        self.set_entry(terminal_unknown_since=ago(40 * 60 + 10))
        self.check()
        self.check()
        d = self.decides()
        self.assertEqual(len(d), 1, d)
        self.assertEqual(d[0]["summary"], f"production 에이전트 작업 터미널({self.t}) 상태를 40분 넘게 확인하지 못했다. 새 세션을 "
                                          "띄우지 않고 기다린다. 사용자에게 그 탭을 확인해 달라고 한다")
        self.assertEqual(self.entry()["terminal"], self.t)  # 잊지 않는다
        self.undelay()
        self.check()
        e = self.entry()
        self.assertEqual((e["terminal_unknown_since"], e["terminal_unknown_asked"]), (None, False))

    def test_reconcile_runs_crew_check_and_handles_assigned_task(self):
        self.set_entry(task=None)
        out = self.started("T-002")
        self.update_terminal(out["terminal"], state="finished")  # 사용자가 작업 pane 을 닫았다
        with self.in_drive():
            self.make_drive().reconcile()
        e = self.entry()
        self.assertNotEqual(e["terminal"], out["terminal"])
        st = self.task_state("T-002")
        self.assertEqual(st["round"], 2)
        self.assertIn("이전 작업자가 중간에 끝났다", st["rounds"][-1]["note"])
        self.assertEqual(sum("production 작업 터미널이 닫혀 잊음" in line for line in self.log_lines()), 1)


class StatusCrewTest(CrewCase):
    def test_status_lists_agents(self):
        t = self.first("T-001")
        code, out = self.hteam("status", as_="main")
        self.assertEqual(code, 0, out)
        rows = {r["name"]: r for r in out["crew"]}
        self.assertEqual(list(rows), ["production", "test"])
        prod = rows["production"]
        self.assertEqual((prod["title"], prod["agent"], prod["model"], prod["roles"], prod["terminal"], prod["task"],
                          prod["queue"], prod["reset_pending"], prod["resetting"], prod["since_reset"]),
                         ("생산", "claude", "opus", ["planner", "developer"], t, None, [], False, None, 1))
        self.assertEqual((rows["test"]["terminal"], rows["test"]["agent"], rows["test"]["since_reset"]),
                         (None, "claude", 0))

    def test_status_crew_empty_when_config_broken(self):
        self.set_config("이건 toml 이 아니다 [")
        code, out = self.hteam("status", as_="main")
        self.assertEqual((code, out["crew"]), (0, []), out)


class ReviewFixTest(CrewCase):
    """Task 7 리뷰 고치기(태스크 리뷰 Important 1, Codex 커밋 리뷰 c690922 의 P1 둘·P2 둘)."""

    def test_own_task_insert_refused_then_start_ready_reinserts(self):
        """자기 태스크의 수정을 같은 세션에 넣다가 일시 거부되면 다음 start-ready 가 같은 세션에 다시 넣는다(설계 5.9.3 의 3,
        5.9.5). 뗀 태스크를 에이전트가 맡은 채로 남아 복구가 그 에이전트를 영영 기다리지 않는다."""
        out = self.started("T-001")
        t = out["terminal"]
        self.ready(t, status="idle")  # done 없이 턴을 마쳤다(맡은 태스크는 그대로 T-001)
        with self._hc_locked() as st:
            st["on_send"] = {t: "mismatch"}
        code, res = self.hteam("fix", "T-001", "--note=이어서")
        self.assertEqual((code, res["error"]["code"], res["horch"]["error"]["code"]),
                         (1, "launch_failed", "terminal_not_ready"), res)
        with self._hc_locked() as st:
            st["on_send"] = {}
        code, res = self.hteam("start-ready")
        self.assertEqual((code, [s["task"] for s in res["started"]]), (0, ["T-001"]), res)
        self.assertEqual((self.task_state("T-001")["status"], self.task_state("T-001")["round"]), ("working", 2))
        self.assertEqual(self.dispatch_row(self.work_dispatch("T-001"))["terminal"], t)
        self.assertEqual(self.entry()["task"], "T-001")

    def test_removed_crew_working_session_blocks_temp_fix(self):
        """일하는 고정 세션의 [crew.*] 를 지운 뒤 fix 해도 그 세션이 일하는 동안 임시 워커를 띄우지 않는다(두 워커가 같은
        파일을 고치지 않게). 쉬면 지금처럼 임시 워커로 고친다."""
        out = self.started("T-001")
        t = out["terminal"]
        self.ready(t, status="working")
        self.set_config(BASE_CONFIG)
        code, res = self.hteam("fix", "T-001", "--note=x")
        self.assertEqual((code, res["error"]["code"]), (3, "worker_active"), res)
        self.assertEqual(self.task_state("T-001")["round"], 1)
        self.assertEqual(self.dispatch_row(out["dispatch"])["state"], "active")
        self.assertEqual(len([c for c in self.hc_calls() if c[:1] == ["run"]]), 1)
        self.ready(t, status="idle")
        code, res = self.hteam("fix", "T-001", "--note=x")
        self.assertEqual((code, res["round"]), (0, 2), res)
        self.assertNotEqual(res["terminal"], t)
        self.assertEqual(self.rnd("T-001")["crew"], "temp")
        self.assertEqual(self.dispatch_row(out["dispatch"])["state"], "released")

    def test_immediate_fix_merges_queued_fix(self):
        """대기열에 든 수정이 있는 태스크에 에이전트가 빈 뒤 fix 가 바로 돌면 앞 대기 지시를 잇는다(설계 5.9.5 의 병합 규칙)."""
        t = self.first("T-001")
        self.started("T-002")
        self.assertEqual(self.hteam("fix", "T-001", "--note=첫째", "--force-round")[1]["status"], "queued")
        self.work("T-002")
        self.free("T-002")
        self.ready(t, turn=2)
        code, res = self.hteam("fix", "T-001", "--note=둘째")
        self.assertEqual((code, res["round"], res["terminal"]), (0, 2, t), res)
        st = self.task_state("T-001")
        self.assertEqual(st["rounds"][-1]["note"], "첫째\n둘째")
        self.assertTrue([e for e in st["history"] if e.get("event") == "fix"][-1]["force_round"])
        self.assertNotIn("queued_fix", st)
        self.assertEqual(self.entry()["queue"], [])

    def test_spec_only_task_waiting_on_deps_gets_pending_state(self):
        """상태 파일이 없는 태스크도 기다리게 둘 때 pending 상태를 만든다(start-ready 가 나중에 그 태스크를 본다, 설계 5.4)."""
        self.task("T-001")
        self.write_spec("T-002", owns="src/t-002/**", depends="T-001")
        code, out = self.hteam("start", "T-002")
        self.assertEqual((code, out["status"], out["reason"]), (0, "waiting", "deps"), out)
        self.assertEqual(self.task_state("T-002")["status"], "pending")
        code, out = self.hteam("start-ready")
        self.assertIn(("T-002", "deps"), [(w["task"], w["reason"]) for w in out["waiting"]], out)
