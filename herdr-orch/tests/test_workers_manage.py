import io
import json
import os
import subprocess
import time
import unittest
from unittest import mock

from tests.helpers import HorchCase
from horch import liveness, mailbox, workers
from horch.errors import MISSING, HorchError
from horch.store import Store


class ObserveTest(HorchCase):
    def setUp(self):
        super().setUp()
        self.run_id = self.make_owner("t100")
        self.update_terminal("t100", status="working")
        self.did = self.add_dispatch(self.run_id, status="working")
        patcher = mock.patch.dict(os.environ, self.env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.store = Store(self.home)
        self.addCleanup(self.store.close)

    def kinds(self):
        rows = self.store.all("SELECT body FROM messages WHERE type='observed' ORDER BY id")
        return [(json.loads(r["body"])["kind"], json.loads(r["body"])["key"]) for r in rows]

    def test_blocked_and_error_once_per_turn(self):
        self.update_terminal("t9", status="blocked", turn=3)
        liveness.observe(self.store, self.run_id)
        liveness.observe(self.store, self.run_id)
        self.update_terminal("t9", status="error", turn=4)
        liveness.observe(self.store, self.run_id)
        self.assertEqual(self.kinds(), [("blocked", "3"), ("error", "4")])

    def test_exited_and_lost(self):
        self.update_terminal("t9", reason="stopped_by_restart")
        liveness.observe(self.store, self.run_id)
        self.update_terminal("t9", state="finished", reason=None)
        liveness.observe(self.store, self.run_id)
        liveness.observe(self.store, self.run_id)
        self.assertEqual(self.kinds(), [("lost", "lost"), ("exited", "exited")])

    def test_blocked_without_turn_is_skipped(self):
        self.update_terminal("t9", status="blocked", turn=None)
        liveness.observe(self.store, self.run_id)
        self.assertEqual(self.kinds(), [])
        self.update_terminal("t9", turn=2)
        liveness.observe(self.store, self.run_id)
        self.assertEqual(self.kinds(), [("blocked", "2")])

    def test_no_event_when_dispatch_changes_during_probe(self):
        self.update_terminal("t9", state="finished")
        real = liveness.probe

        def probe_then(sql):
            def wrapped(*a, **kw):
                res = real(*a, **kw)
                db = self.db()
                db.execute(sql, (self.did,))
                db.commit()
                return res
            return wrapped

        # 판정하는 사이 done 으로 settled 가 됐다
        with mock.patch.object(liveness, "probe", probe_then("UPDATE dispatches SET state='settled' WHERE id=?")):
            liveness.observe(self.store, self.run_id)
        self.assertEqual(self.kinds(), [])
        self.assertEqual(self.store.all("SELECT * FROM observations"), [])
        # 판정하는 사이 터미널 기록이 바뀌었다
        self.store.run("UPDATE dispatches SET state='active' WHERE id=?", (self.did,))
        with mock.patch.object(liveness, "probe", probe_then("UPDATE dispatches SET terminal='t77' WHERE id=?")):
            liveness.observe(self.store, self.run_id)
        self.assertEqual(self.kinds(), [])


class SweepTest(HorchCase):
    def setUp(self):
        super().setUp()
        self.run_id = self.make_owner("t100")
        self.dids = [self.add_dispatch(self.run_id, did=f"dsp-0000000{i}", terminal=f"t{10 + i}") for i in (1, 2, 3)]
        for i in (1, 2, 3):
            self.update_terminal(f"t{10 + i}", state="finished")
        self.env["HORCH_SWEEP_INTERVAL"] = "0.3"
        patcher = mock.patch.dict(os.environ, self.env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.store = Store(self.home)
        self.addCleanup(self.store.close)

    def observed(self) -> int:
        return self.store.one("SELECT COUNT(*) AS n FROM messages WHERE type='observed'")["n"]

    def test_budget_spreads_probes_over_ticks(self):
        self.delay_hc("get", 0.4)  # 판정 하나가 틱 예산(0.3초)보다 길다
        sweep = workers.Sweep(self.store, self.run_id)
        counts, more = [], True
        for _ in range(8):
            more = sweep(time.monotonic() + 30)
            counts.append(self.observed())
            if not more:
                break
        self.assertFalse(more)
        self.assertEqual(counts[-1], 3)
        steps = [b - a for a, b in zip([0, *counts], counts)]
        self.assertTrue(all(s <= 1 for s in steps), counts)  # 한 틱에 판정 하나: 남은 것은 다음 틱에

    def test_tick_budget_is_poll_interval(self):
        # 틱 예산은 sweep 간격(5초)이 아니라 폴링 간격(0.3초): 느린 hc 가 메시지 전달을 늦추지 않는다
        with mock.patch.dict(os.environ, {"HORCH_SWEEP_INTERVAL": "5", "HORCH_POLL": "0.3"}):
            self.delay_hc("get", 0.4)
            sweep = workers.Sweep(self.store, self.run_id)
            t0 = time.monotonic()
            more = sweep(time.monotonic() + 30)
            self.assertLess(time.monotonic() - t0, 1.0)
            self.assertTrue(more)
            self.assertEqual(self.observed(), 1)

    def test_position_survives_new_sweep(self):
        # 호출마다 새 Sweep 이어도 회차 위치는 meta 에 남아 마지막 워커까지 간다
        self.delay_hc("get", 0.4)
        for _ in range(3):
            workers.Sweep(self.store, self.run_id)(time.monotonic() + 0.5)
        self.assertEqual(self.observed(), 3)

    def test_refused_cleanup_completes_with_slow_hc_across_ticks(self):
        # 틱 예산(폴링 1초)보다 ls·get·rm 이 각각 느려도(0.6초) 호출 하나는 대기 기한까지 살려 두고,
        # 시작만 틱 예산으로 막는다. 확인을 마친 후보는 다음 틱이 이어서 rm 한다
        failed = self.add_dispatch(self.run_id, did="dsp-0000000f", terminal=None, state="launch_failed")
        self.add_terminal("t70", name=failed, state="finished",
                          labels={"horch.run": self.run_id, "horch.dispatch": failed})
        for cmd in ("ls", "get", "rm"):
            self.delay_hc(cmd, 0.6)
        with mock.patch.dict(os.environ, {"HORCH_POLL": "1"}):
            sweep = workers.Sweep(self.store, self.run_id)
            for _ in range(4):
                sweep(time.monotonic() + 30)
                if "t70" not in self.hc_state()["terminals"]:
                    break
        self.assertNotIn("t70", self.hc_state()["terminals"])
        self.assertIn(["rm", "t70", "--json"], self.hc_calls())

    def test_probe_timeout_bounded_by_wait_deadline(self):
        self.delay_hc("get", 3)
        sweep = workers.Sweep(self.store, self.run_id)
        t0 = time.monotonic()
        sweep(t0 + 0.5)
        self.assertLess(time.monotonic() - t0, 1.5)
        self.assertEqual(self.observed(), 0)  # 시간 초과는 모름: 사건이 아니다

    def test_tick_error_keeps_waiting(self):
        calls = []

        def boom(_deadline):
            calls.append(1)
            raise RuntimeError("boom")

        with mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            res = mailbox.check(self.store, f"run:{self.run_id}", wait=True, timeout_ms=800, on_tick=boom)
        self.assertEqual(res["reason"], "timeout")
        self.assertGreaterEqual(len(calls), 2)
        self.assertEqual(err.getvalue().count("RuntimeError: boom"), 1)  # 같은 오류는 한 번만 남긴다

    def test_tick_hc_missing_ends_wait(self):
        def missing(_deadline):
            raise HorchError("hc_missing", "hc 없음", MISSING)

        with self.assertRaises(HorchError) as cm:
            mailbox.check(self.store, f"run:{self.run_id}", wait=True, timeout_ms=800, on_tick=missing)
        self.assertEqual(cm.exception.code, "hc_missing")


class ManageTest(HorchCase):
    def setUp(self):
        super().setUp()
        self.run_id = self.make_owner("t100")
        self.update_terminal("t100", status="working")
        self.did = self.add_dispatch(self.run_id, status="working")

    def o(self, *args):
        return self.horch(*args, terminal="t100")

    def state(self, did=None):
        return self.db().execute("SELECT state FROM dispatches WHERE id=?", (did or self.did,)).fetchone()["state"]

    def set_state(self, state, did=None):
        db = self.db()
        db.execute("UPDATE dispatches SET state=? WHERE id=?", (state, did or self.did))
        db.commit()

    def test_owner_wait_reports_exit(self):
        self.update_terminal("t9", state="finished")
        code, out = self.o("check", "--wait", "--timeout-ms", "3000")
        self.assertEqual((code, out["reason"]), (0, "message"))
        msg = out["messages"][0]
        self.assertEqual((msg["type"], json.loads(msg["body"])["kind"]), ("observed", "exited"))

    def test_owner_wait_reconciles_launching(self):
        did2 = self.add_dispatch(self.run_id, did="dsp-00000002", terminal=None, state="launching")
        self.o("check", "--wait", "--timeout-ms", "300")
        self.assertEqual(self.state(did2), "launch_failed")

    def test_list_attention_and_filter(self):
        self.update_terminal("t9", state="finished")
        did2 = self.add_dispatch(self.run_id, did="dsp-00000002", terminal="t10", state="settled")
        args = ["--dangerously-bypass-hook-trust", "plain value"]
        self.fail_hc("run", "spawn_failed")
        code, failed = self.o("worker-start", "--agent", "claude", "--title", "R", "--spec", "s",
                              "--cwd", str(self.tmp), "--model", "opus", "--effort", "high", *[f"--agent-arg={a}" for a in args])
        self.assertEqual((code, failed["error"]["code"]), (1, "launch_failed"), failed)
        did3 = failed["dispatch"]
        self.clear_hc_fail("run")
        code, out = self.o("worker-list")
        self.assertEqual(code, 0, out)
        by = {w["id"]: w for w in out["workers"]}
        self.assertEqual(by[self.did]["attention"], "exited_without_done")
        self.assertIn("worker-abandon", by[self.did]["next"])
        self.assertEqual(by[did2]["attention"], "settled")
        self.assertIn("worker-release", by[did2]["next"])
        self.assertEqual(by[did3]["attention"], "launch_failed")
        nxt = by[did3]["next"]
        self.assertIn("--retry", nxt)
        self.assertEqual((nxt[nxt.index("--model") + 1], nxt[nxt.index("--effort") + 1]), ("opus", "high"))
        self.assertEqual([a for a in nxt if a.startswith("--agent-arg=")], [f"--agent-arg={a}" for a in args])
        retry = subprocess.run(nxt, capture_output=True, text=True, env=self._env("t100", None), timeout=30)
        self.assertEqual(retry.returncode, 0, retry.stdout)
        new = json.loads(retry.stdout)["dispatch"]
        row = self.db().execute("SELECT model, effort, agent_args FROM dispatches WHERE id=?", (new,)).fetchone()
        self.assertEqual((row["model"], row["effort"], json.loads(row["agent_args"])), ("opus", "high", args))
        run_call = [c for c in self.hc_calls() if c[0] == "run"][-1]
        i = run_call.index("claude")
        self.assertEqual(run_call[i:i + 7], ["claude", "--model", "opus", "--effort", "high", *args])
        # 재시도가 성공한 뒤 옛 launch_failed 행은 더 재시도를 권하지 않는다
        _, after = self.o("worker-list")
        old = {w["id"]: w for w in after["workers"]}[did3]
        self.assertEqual((old["state"], old["attention"], old["next"]), ("launch_failed", None, None))
        _, only = self.o("worker-list", "--state", "settled")
        self.assertEqual([w["id"] for w in only["workers"]], [did2])

    def test_launch_failed_attention_only_for_open_task(self):
        did2 = self.add_dispatch(self.run_id, did="dsp-00000002", terminal=None, state="launch_failed")
        _, out = self.o("worker-list")
        self.assertEqual({w["id"]: w for w in out["workers"]}[did2]["attention"], "launch_failed")
        db = self.db()
        db.execute("UPDATE tasks SET status='settled' WHERE id='task-00000002'")
        db.commit()
        _, out = self.o("worker-list")
        row = {w["id"]: w for w in out["workers"]}[did2]
        self.assertEqual((row["attention"], row["next"]), (None, None))
        _, shown = self.o("worker-show", "--dispatch", did2, "--lines", "0")
        self.assertEqual((shown["worker"]["attention"], shown["worker"]["next"]), (None, None))

    def test_list_works_on_migrated_v1_db(self):
        db = self.db()
        db.execute("DROP INDEX dispatch_task_attempt")
        db.execute("ALTER TABLE dispatches DROP COLUMN agent_args")
        db.execute("UPDATE meta SET value='1' WHERE key='schema_version'")
        db.commit()
        code, out = self.o("worker-list")
        self.assertEqual(code, 0, out)
        self.assertEqual([w["id"] for w in out["workers"]], [self.did])
        self.assertEqual(out["workers"][0]["agent_args"], [])

    def test_list_query_uses_task_attempt_index(self):
        plan = " ".join(str(tuple(r)) for r in self.db().execute("EXPLAIN QUERY PLAN " + workers._ROWS + " WHERE d.run_id=?",
                                                                (self.run_id,)))
        self.assertIn("dispatch_task_attempt", plan)

    def test_list_state_typo_is_usage(self):
        code, out = self.o("worker-list", "--state", "setled")
        self.assertEqual((code, out["error"]["code"]), (2, "usage"))

    def add_slow_workers(self, delay: float) -> None:
        for i in (2, 3, 4):
            self.add_dispatch(self.run_id, did=f"dsp-0000000{i}", terminal=f"t{10 + i}", status="working")
        self.delay_hc("get", delay)

    def test_owner_wait_sweep_does_not_overshoot_timeout(self):
        self.add_slow_workers(2.0)  # 판정 4개 x 2초: 예산 없이 돌면 8초 넘게 걸린다
        t0 = time.monotonic()
        code, out = self.o("check", "--wait", "--timeout-ms", "1500")
        elapsed = time.monotonic() - t0
        self.assertEqual((code, out.get("reason")), (0, "timeout"), out)
        self.assertLess(elapsed, 2.5)

    def test_owner_wait_returns_message_during_slow_sweep(self):
        self.add_slow_workers(1.5)
        proc = self.horch_bg("check", "--wait", "--timeout-ms", "20000", terminal="t100")
        time.sleep(0.5)
        code, sent = self.horch("send", "--to", f"run:{self.run_id}", "--body", "hi")
        self.assertEqual(code, 0, sent)
        t_sent = time.monotonic()
        code, out = self.finish(proc)
        elapsed = time.monotonic() - t_sent
        self.assertEqual((code, out.get("reason")), (0, "message"), out)
        self.assertEqual([m["body"] for m in out["messages"]], ["hi"])
        self.assertLess(elapsed, 3.0)

    def test_list_no_status_for_live_worker_without_report(self):
        self.update_terminal("t9", status=None)
        _, out = self.o("worker-list")
        row = {w["id"]: w for w in out["workers"]}[self.did]
        self.assertEqual((row["verdict"], row["status"], row["attention"]), ("live", None, "no_status"))
        self.assertEqual(row["next"][-4:], ["--dispatch", self.did, "--lines", "40"])
        self.update_terminal("t9", status="working")
        _, out = self.o("worker-list")
        self.assertIsNone({w["id"]: w for w in out["workers"]}[self.did]["attention"])

    def test_show_with_screen(self):
        st = self.hc_state()
        st["screens"]["t9"] = "화면 내용"
        self.set_hc_state(st)
        code, out = self.o("worker-show", "--dispatch", self.did, "--lines", "20")
        self.assertEqual(code, 0, out)
        self.assertIn("화면 내용", out["worker"]["screen"])
        self.assertEqual(out["worker"]["hc"]["state"], "live")
        _, none = self.o("worker-show", "--dispatch", self.did, "--lines", "0")
        self.assertIsNone(none["worker"]["screen"])

    def test_release_kills_removes_and_is_idempotent(self):
        code, out = self.o("worker-release", "--dispatch", self.did)
        self.assertEqual(code, 3)
        self.set_state("settled")
        code, out = self.o("worker-release", "--dispatch", self.did)
        self.assertEqual((code, out["dispatch"]["state"]), (0, "released"))
        self.assertNotIn("t9", self.hc_state()["terminals"])
        code, out = self.o("worker-release", "--dispatch", self.did)
        self.assertEqual(code, 0)

    def test_release_when_terminal_gone(self):
        self.set_state("abandoned")
        st = self.hc_state()
        del st["terminals"]["t9"]
        self.set_hc_state(st)
        code, out = self.o("worker-release", "--dispatch", self.did)
        self.assertEqual((code, out["dispatch"]["state"]), (0, "released"))

    def test_release_hc_failure_keeps_state(self):
        self.set_state("settled")
        self.fail_hc("get", "timeout")
        code, out = self.o("worker-release", "--dispatch", self.did)
        self.assertEqual((code, out["error"]["code"]), (1, "hc_failed"))
        self.assertEqual(self.state(), "settled")

    def test_release_refuses_terminal_of_other_dispatch(self):
        self.set_state("settled")
        self.update_terminal("t9", labels={"horch.run": self.run_id, "horch.dispatch": "dsp-99999999"})
        code, out = self.o("worker-release", "--dispatch", self.did)
        self.assertEqual((code, out["error"]["code"]), (1, "terminal_mismatch"))
        self.assertEqual(self.hc_state()["terminals"]["t9"]["state"], "live")
        self.assertEqual([c for c in self.hc_calls() if c[0] in ("kill", "rm")], [])
        self.assertEqual(self.state(), "settled")

    def test_release_rm_retries_only_while_live(self):
        self.set_state("settled")
        self.update_terminal("t9", state="finished")
        self.fail_hc("rm", "timeout")
        code, out = self.o("worker-release", "--dispatch", self.did)
        self.assertEqual((code, out["error"]["code"]), (1, "hc_failed"))
        self.assertEqual(len([c for c in self.hc_calls() if c[0] == "rm"]), 1)
        self.fail_hc("rm", "live")
        code, out = self.o("worker-release", "--dispatch", self.did)
        self.assertEqual((code, out["error"]["code"]), (1, "hc_failed"))
        self.assertGreater(len([c for c in self.hc_calls() if c[0] == "rm"]), 3)
        self.assertEqual(self.state(), "settled")

    def test_retain_then_release(self):
        self.set_state("settled")
        code, out = self.o("worker-retain", "--dispatch", self.did)
        self.assertEqual((code, out["dispatch"]["state"]), (0, "retained"))
        code, out = self.o("worker-release", "--dispatch", self.did)
        self.assertEqual(out["dispatch"]["state"], "released")

    def test_abandon_rules(self):
        code, out = self.o("worker-abandon", "--dispatch", self.did)
        self.assertEqual((code, out["error"]["code"]), (3, "worker_alive"))
        code, out = self.o("worker-abandon", "--dispatch", self.did, "--kill")
        self.assertEqual((code, out["dispatch"]["state"], out["verdict"]), (0, "abandoned", "live"))
        self.assertEqual(self.hc_state()["terminals"]["t9"]["state"], "finished")
        did2 = self.add_dispatch(self.run_id, did="dsp-00000002", terminal="t10")
        st = self.hc_state()
        del st["terminals"]["t10"]
        self.set_hc_state(st)
        code, out = self.o("worker-abandon", "--dispatch", did2)
        self.assertEqual((code, out["error"]["code"]), (1, "unverifiable"))

    def test_abandon_exited_without_kill(self):
        self.update_terminal("t9", state="finished")
        code, out = self.o("worker-abandon", "--dispatch", self.did)
        self.assertEqual((code, out["verdict"]), (0, "exited"))

    def test_not_owner(self):
        code, out = self.horch("worker-list", terminal="t9")
        self.assertEqual(code, 5)


if __name__ == "__main__":
    unittest.main()
