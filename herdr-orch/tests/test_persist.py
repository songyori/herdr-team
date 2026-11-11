"""고정 터미널(herdr-orch 설계 13장, 0.2.0): 스키마 v3, --keep-open·--terminal·--tab·--hidden, 판정, --keep-terminal."""
import json
import os
import sqlite3
import subprocess
import sys
import unittest
from unittest import mock

from tests.helpers import BIN, HorchCase
from horch import hcio, liveness, procs, workers
from horch.store import SCHEMA_VERSION, Store

CONT = "이 세션은 앞 태스크를 이어 받았을 수 있다. 앞 대화의 Task·Dispatch ID 는 쓰지 않는다. 이 프리앰블의 ID 만 쓴다."
V3_COLUMNS = ("persistent", "terminal_argv", "start_turn", "delivery", "seen_at")


class PersistCase(HorchCase):
    """소유자 t100(spA·tbA)과 고정 터미널 도우미. 소유자는 working 이라 깨우기 글을 받지 않는다."""

    def setUp(self):
        super().setUp()
        self.run_id = self.make_owner("t100", "spA", "tbA")
        self.update_terminal("t100", status="working")

    def o(self, *args, env=None):
        return self.horch(*args, terminal="t100", env=env)

    def row(self, did) -> dict:
        return dict(self.db().execute("SELECT * FROM dispatches WHERE id=?", (did,)).fetchone())

    def count(self, table) -> int:
        return self.db().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def keep_open(self, *extra, agent="claude", title="T1", spec="첫 번째") -> dict:
        code, out = self.o("worker-start", "--keep-open", "--agent", agent, "--title", title, "--spec", spec,
                           "--cwd", str(self.tmp), *extra)
        self.assertEqual(code, 0, out)
        return out

    def settle(self, did, term) -> None:
        code, out = self.horch("done", "--dispatch", did, "--outcome", "succeeded", "--summary", "끝", terminal=term)
        self.assertEqual(code, 0, out)

    def ready(self, term, status="done", turn=3) -> None:
        self.update_terminal(term, status=status, turn=turn)

    def first(self, *extra, agent="claude") -> tuple[str, str]:
        """고정 터미널을 띄우고 첫 Dispatch 를 settled 로, 터미널을 done·turn 3 으로 둔다. (Dispatch, 터미널)."""
        out = self.keep_open(*extra, agent=agent)
        self.settle(out["dispatch"], out["terminal"])
        self.ready(out["terminal"])
        return out["dispatch"], out["terminal"]

    def put(self, term, *extra, title="T2", spec="두 번째", env=None):
        return self.o("worker-start", "--terminal", term, "--title", title, "--spec", spec, *extra, env=env)

    def sent_to(self, term) -> list[dict]:
        return [s for s in self.hc_sent() if s["terminal"] == term]

    def reserve(self, term, pid, started) -> None:
        db = self.db()
        db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                   (f"reset:{term}", f"{pid}|{started}|2026-01-01T00:00:00Z"))
        db.commit()

    def preamble(self, did) -> str:
        return (self.home / "runs" / self.run_id / "dispatches" / did / "preamble.md").read_text(encoding="utf-8")

    def store(self) -> Store:
        s = Store(self.home)
        self.addCleanup(s.close)
        return s


class SchemaV3Test(HorchCase):
    def open(self) -> Store:
        s = Store(self.home)
        self.addCleanup(s.close)
        return s

    def test_new_db_is_v3(self):
        s = self.open()
        # v4(0.3.0, herdr-orch 설계 14.2)도 v3 열·인덱스를 그대로 둔다
        self.assertGreaterEqual(SCHEMA_VERSION, 3)
        self.assertEqual(s.one("SELECT value FROM meta WHERE key='schema_version'")["value"], str(SCHEMA_VERSION))
        cols = {r["name"] for r in s.all("PRAGMA table_info(dispatches)")}
        for c in V3_COLUMNS:
            self.assertIn(c, cols)
        self.assertIn("send_key", {r["name"] for r in s.all("PRAGMA table_info(messages)")})
        self.assertIn("dispatch_one_per_terminal", {r["name"] for r in s.all("PRAGMA index_list(dispatches)")})
        self.assertIn("send_key_once", {r["name"] for r in s.all("PRAGMA index_list(messages)")})

    def test_migrates_v2_to_v3(self):
        s = self.open()
        s.run("DROP INDEX dispatch_one_per_terminal")
        s.run("DROP INDEX send_key_once")
        for c in V3_COLUMNS:
            s.run(f"ALTER TABLE dispatches DROP COLUMN {c}")
        s.run("ALTER TABLE messages DROP COLUMN send_key")
        s.run("UPDATE meta SET value='2' WHERE key='schema_version'")
        s.run("INSERT INTO runs(id, objective, created_at, updated_at) VALUES ('run-1','o','t','t')")
        s.run("INSERT INTO tasks(id, run_id, title, spec, created_at) VALUES ('task-1','run-1','T','S','t')")
        s.run("INSERT INTO dispatches(id, task_id, run_id, attempt, agent, cwd, terminal, state, created_at) "
              "VALUES ('dsp-1','task-1','run-1',1,'claude','/x','t9','active','t')")
        s.close()
        s2 = self.open()
        # 누적 마이그레이션: v2 → v3 → v4(herdr-orch 설계 14.2)
        self.assertEqual(s2.one("SELECT value FROM meta WHERE key='schema_version'")["value"], str(SCHEMA_VERSION))
        row = s2.one("SELECT * FROM dispatches WHERE id='dsp-1'")
        self.assertEqual((row["persistent"], row["terminal_argv"], row["start_turn"], row["delivery"], row["seen_at"]),
                         (0, None, None, None, None))
        self.assertIn("dispatch_one_per_terminal", {r["name"] for r in s2.all("PRAGMA index_list(dispatches)")})
        self.assertIn("send_key_once", {r["name"] for r in s2.all("PRAGMA index_list(messages)")})

    def test_one_running_dispatch_per_terminal(self):
        s = self.open()
        with s.tx():
            s.run("INSERT INTO runs(id, objective, created_at, updated_at) VALUES ('run-1','o','t','t')")
            for t in ("task-1", "task-2", "task-3", "task-4"):
                s.run("INSERT INTO tasks(id, run_id, title, spec, created_at) VALUES (?, 'run-1','T','S','t')", (t,))
        ins = ("INSERT INTO dispatches(id, task_id, run_id, attempt, agent, cwd, terminal, state, created_at) "
               "VALUES (?, ?, 'run-1', 1, 'claude', '/', ?, ?, 't')")
        with s.tx():
            s.run(ins, ("dsp-1", "task-1", "t7", "settled"))
            s.run(ins, ("dsp-2", "task-2", "t7", "active"))
            s.run(ins, ("dsp-3", "task-3", None, "launching"))
            s.run(ins, ("dsp-4", "task-4", None, "launching"))
        with self.assertRaises(sqlite3.IntegrityError):
            with s.tx():
                s.run("UPDATE dispatches SET terminal='t7', state='launching' WHERE id='dsp-3'")


class KeepOpenTest(PersistCase):
    def test_keep_open_labels_and_terminal_argv(self):
        out = self.keep_open()
        self.assertEqual((out["state"], out["placement"], out["warning"]), ("active", "pane", None))
        t = self.hc_state()["terminals"][out["terminal"]]
        self.assertEqual(t["labels"], {"herdr.space": "spA", "herdr.tab": "tbA", "horch.run": self.run_id,
                                       "horch.dispatch": out["dispatch"], "horch.persistent": "1"})
        row = self.row(out["dispatch"])
        self.assertEqual(row["persistent"], 1)
        self.assertEqual(json.loads(row["terminal_argv"]), json.loads(row["launch_argv"]))
        self.assertEqual(json.loads(row["terminal_argv"]), t["argv"])
        self.assertIsNone(row["start_turn"])

    def test_tab_attaches_to_given_tab_in_owner_space(self):
        out = self.keep_open("--tab", "tbCrew_1-a")
        t = self.hc_state()["terminals"][out["terminal"]]
        self.assertEqual((t["labels"]["herdr.space"], t["labels"]["herdr.tab"]), ("spA", "tbCrew_1-a"))
        self.assertEqual((out["placement"], out["warning"]), ("pane", None))

    def test_hidden_has_no_herdr_labels(self):
        for extra in (("--keep-open", "--hidden"), ("--hidden",)):
            with self.subTest(extra=extra):
                code, out = self.o("worker-start", *extra, "--agent", "codex", "--title", "R", "--spec", "s",
                                   "--cwd", str(self.tmp))
                self.assertEqual(code, 0, out)
                self.assertEqual((out["placement"], out["warning"]), ("hidden", None))
                labels = self.hc_state()["terminals"][out["terminal"]]["labels"]
                self.assertNotIn("herdr.space", labels)
                self.assertNotIn("herdr.tab", labels)
                self.assertEqual(labels.get("horch.persistent"), "1" if "--keep-open" in extra else None)
                self.assertEqual(self.row(out["dispatch"])["persistent"], 1 if "--keep-open" in extra else 0)

    def test_plain_start_is_not_persistent(self):
        out = self.start_worker(owner="t100")
        row = self.row(out["dispatch"])
        self.assertEqual((row["persistent"], row["terminal_argv"], row["start_turn"], row["delivery"]), (0, None, None, None))
        self.assertNotIn("horch.persistent", self.hc_state()["terminals"][out["terminal"]]["labels"])

    def test_tab_needs_owner_space(self):
        self.make_owner("t101", None, None)
        code, out = self.horch("worker-start", "--keep-open", "--tab", "tbX", "--agent", "claude", "--title", "t",
                               "--spec", "s", "--cwd", str(self.tmp), terminal="t101")
        self.assertEqual((code, out["error"]["code"]), (2, "no_owner_space"))

    def test_option_conflicts_are_usage(self):
        _, term = self.first()
        before = self.count("dispatches")
        cases = [
            ("--keep-open", "--terminal", term, "--agent", "claude", "--title", "t", "--spec", "s"),
            ("--keep-open", "--tab", "tbX", "--hidden", "--agent", "claude", "--title", "t", "--spec", "s"),
            ("--keep-open", "--tab", "bad/tab", "--agent", "claude", "--title", "t", "--spec", "s"),
            ("--keep-open", "--tab", "x" * 65, "--agent", "claude", "--title", "t", "--spec", "s"),
            ("--title", "t", "--spec", "s", "--cwd", str(self.tmp)),  # --terminal 이 없으면 --agent 가 있어야 한다
        ]
        for opt in (("--agent", "claude"), ("--model", "m"), ("--effort", "e"), ("--agent-arg=--x",),
                    ("--cwd", str(self.tmp)), ("--tab", "tbX"), ("--hidden",)):
            cases.append(("--terminal", term, "--title", "t", "--spec", "s", *opt))
        for args in cases:
            with self.subTest(args=args):
                code, out = self.o("worker-start", *args)
                self.assertEqual((code, out["error"]["code"]), (2, "usage"), out)
        self.assertEqual(self.count("dispatches"), before)


class TerminalStartTest(PersistCase):
    def test_done_terminal_sends_without_if_and_untagged(self):
        d1, term = self.first("--model", "opus", "--effort", "high", "--agent-arg=--permission-mode=plan")
        code, out = self.put(term)
        self.assertEqual(code, 0, out)
        d2 = out["dispatch"]
        self.assertEqual((out["state"], out["placement"], out["terminal"], out["start_turn"]),
                         ("active", "same_terminal", term, 3))
        sent = self.sent_to(term)
        self.assertEqual(len(sent), 1)
        self.assertEqual((sent[0]["if"], sent[0]["tagged"]), (None, False))
        self.assertEqual(sent[0]["text"], self.preamble(d2))
        delivery = out["delivery"]
        for key, value in (("attempted", True), ("via", "send"), ("if", None), ("status_before", "done"),
                           ("turn_before", 3), ("started", True), ("status", "done"), ("turn", 3)):
            self.assertEqual(delivery[key], value, key)
        self.assertTrue(delivery["at"])
        one, two = self.row(d1), self.row(d2)
        self.assertEqual((two["persistent"], two["terminal"], two["state"], two["start_turn"]), (1, term, "active", 3))
        self.assertIsNone(two["launch_argv"])
        self.assertEqual(json.loads(two["delivery"]), delivery)
        for key in ("terminal_argv", "agent", "model", "effort", "agent_args", "cwd"):
            self.assertEqual(two[key], one[key], key)
        labels = self.hc_state()["terminals"][term]["labels"]
        self.assertEqual((labels["horch.dispatch"], labels["horch.persistent"], labels["horch.run"]),
                         (d2, "1", self.run_id))
        task = self.db().execute("SELECT title, spec FROM tasks WHERE id=?", (out["task"],)).fetchone()
        self.assertEqual((task["title"], task["spec"]), ("T2", "두 번째"))
        self.assertEqual(out["warnings"], [])

    def test_idle_terminal_uses_if_idle(self):
        _, term = self.first()
        self.ready(term, status="idle", turn=5)
        code, out = self.put(term)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.sent_to(term)[-1]["if"], "idle")
        self.assertEqual((out["start_turn"], out["delivery"]["if"], out["delivery"]["status_before"]), (5, "idle", "idle"))

    def test_send_is_untagged_even_from_tagged_environment(self):
        _, term = self.first()
        code, out = self.put(term)  # 소유자 터미널(HC_TERMINAL_ID=t100)에서 부른다
        self.assertEqual(code, 0, out)
        self.assertFalse(self.sent_to(term)[-1]["tagged"])

    def test_preamble_continuation_line_and_owner_wording(self):
        d1, term = self.first()
        _, out = self.put(term)
        lines = self.preamble(out["dispatch"]).splitlines()
        i = next(n for n, line in enumerate(lines) if line.startswith("1. "))
        self.assertEqual(lines[i + 1].strip(), CONT)
        for did in (d1, out["dispatch"]):
            text = self.preamble(did)
            self.assertIn("소유자 메시지", text)
            self.assertNotIn("코디네이터 메시지", text)
        self.assertNotIn(CONT, self.preamble(d1))

    def test_rejections_create_nothing(self):
        cases = {
            "not_found": (3, "terminal_gone", {"verdict": "not_found"}),
            "finished": (3, "terminal_gone", {"verdict": "exited"}),
            "restart": (3, "terminal_gone", {"verdict": "lost"}),
            "argv": (3, "terminal_gone", {"verdict": "lost"}),
            "other_run": (3, "not_persistent_terminal", {}),
            "no_label": (3, "not_persistent_terminal", {}),
            "working": (3, "terminal_not_ready", {"status": "working", "turn": 3}),
            "blocked": (3, "terminal_not_ready", {"status": "blocked", "turn": 3}),
            "error": (3, "terminal_not_ready", {"status": "error", "turn": 3}),
            "no_status": (3, "terminal_not_ready", {"status": None, "turn": 3}),
            "hc_timeout": (1, "hc_failed", {}),
        }
        for case, (want_code, want, data) in cases.items():
            with self.subTest(case=case):
                _, term = self.first()
                if case == "not_found":
                    st = self.hc_state()
                    del st["terminals"][term]
                    self.set_hc_state(st)
                elif case == "finished":
                    self.update_terminal(term, state="finished")
                elif case == "restart":
                    self.update_terminal(term, reason="stopped_by_restart")
                elif case == "argv":
                    self.update_terminal(term, argv=["sh"])
                elif case == "other_run":
                    labels = dict(self.hc_state()["terminals"][term]["labels"], **{"horch.run": "run-other"})
                    self.update_terminal(term, labels=labels)
                elif case == "no_label":
                    labels = dict(self.hc_state()["terminals"][term]["labels"])
                    labels.pop("horch.persistent")
                    self.update_terminal(term, labels=labels)
                elif case == "no_status":
                    self.update_terminal(term, status=None)
                elif case == "hc_timeout":
                    self.fail_hc("get", "timeout")
                else:
                    self.update_terminal(term, status=case)
                tasks, dispatches = self.count("tasks"), self.count("dispatches")
                code, out = self.put(term)
                self.clear_hc_fail("get")
                self.assertEqual((code, out["error"]["code"]), (want_code, want), out)
                for key, value in data.items():
                    self.assertEqual(out[key], value, key)
                self.assertEqual((self.count("tasks"), self.count("dispatches")), (tasks, dispatches))
                self.assertEqual(self.sent_to(term), [])

    def test_plain_dispatch_terminal_is_not_persistent(self):
        out = self.start_worker(owner="t100")
        self.settle(out["dispatch"], out["terminal"])
        self.ready(out["terminal"])
        code, res = self.put(out["terminal"])
        self.assertEqual((code, res["error"]["code"]), (3, "not_persistent_terminal"))

    def test_busy_terminal(self):
        out = self.keep_open()
        self.ready(out["terminal"])  # 첫 Dispatch 가 아직 active 다
        code, res = self.put(out["terminal"])
        self.assertEqual((code, res["error"]["code"], res["dispatch"]), (3, "terminal_busy", out["dispatch"]))

    def test_live_reset_reservation_blocks_and_dead_one_does_not(self):
        _, term = self.first()
        pid, started = procs.me()  # 이 시험 프로세스는 살아 있다
        self.reserve(term, pid, started)
        code, res = self.put(term)
        self.assertEqual((code, res["error"]["code"]), (3, "terminal_busy"))
        self.reserve(term, 999999, "never")
        code, res = self.put(term)
        self.assertEqual(code, 0, res)

    def test_second_look_excludes_own_dispatch_and_catches_change(self):
        _, term = self.first()
        code, out = self.put(term)  # 정상 재투입: 다시 보기가 자기 Dispatch 때문에 terminal_busy 가 되지 않는다
        self.assertEqual(code, 0, out)
        self.settle(out["dispatch"], term)
        self.ready(term, turn=4)
        real = hcio.get
        calls = []

        def flip(t, timeout=None):
            info = real(t, timeout=timeout)
            calls.append(t)
            if len(calls) == 1:  # 첫 확인 뒤 사람이 친 글로 일을 시작했다
                self.update_terminal(term, status="working")
            return info

        with mock.patch.dict(os.environ, {**self.env, "HC_TERMINAL_ID": "t100"}, clear=True), \
                mock.patch.object(hcio, "get", side_effect=flip):
            store = self.store()
            from horch.errors import HorchError
            from horch import persist
            with self.assertRaises(HorchError) as cm:
                persist.start_on(store, self.run_id, term, spec="s3", title="T3", task_id=None, retry=False)
        self.assertEqual(cm.exception.code, "terminal_not_ready")
        failed = self.db().execute("SELECT state FROM dispatches d JOIN tasks t ON t.id=d.task_id "
                                   "WHERE t.title='T3'").fetchone()
        self.assertEqual(failed["state"], "launch_failed")
        self.assertEqual(len(self.sent_to(term)), 1)  # 앞 재투입 한 번뿐

    def test_status_mismatch_marks_launch_failed(self):
        _, term = self.first()
        self.ready(term, status="idle")
        with self._hc_locked() as st:
            st["on_send"] = {term: "mismatch"}
        code, out = self.put(term)
        self.assertEqual((code, out["error"]["code"]), (3, "terminal_not_ready"), out)
        row = self.row(out["dispatch"])
        self.assertEqual(row["state"], "launch_failed")
        delivery = json.loads(row["delivery"])
        self.assertEqual((delivery["attempted"], delivery["typed"]), (True, False))
        self.assertIn("status_mismatch", delivery["error"])

    def test_lost_response_is_uncertain_active(self):
        _, term = self.first()
        self.fail_hc("send", "timeout")
        code, out = self.put(term)
        self.assertEqual(code, 0, out)
        self.assertEqual(out["state"], "active")
        self.assertIn("delivery_uncertain", out["warnings"])
        self.assertEqual((out["delivery"]["attempted"], out["delivery"]["uncertain"]), (True, True))
        self.assertEqual(self.row(out["dispatch"])["state"], "active")

    def test_label_failure_is_warning(self):
        d1, term = self.first()
        self.fail_hc("label", "timeout")
        code, out = self.put(term)
        self.assertEqual(code, 0, out)
        self.assertIn("label_failed", out["warnings"])
        self.assertEqual(self.hc_state()["terminals"][term]["labels"]["horch.dispatch"], d1)

    def test_task_retry_on_same_terminal(self):
        _, term = self.first()
        with self._hc_locked() as st:
            st["on_send"] = {term: "mismatch"}
        _, failed = self.put(term)
        with self._hc_locked() as st:
            st["on_send"] = {}
        code, out = self.o("worker-start", "--terminal", term, "--task", failed["task"])
        self.assertEqual((code, out["error"]["code"]), (3, "retry_required"))
        code, out = self.o("worker-start", "--terminal", term, "--task", failed["task"], "--retry")
        self.assertEqual(code, 0, out)
        row = self.row(out["dispatch"])
        self.assertEqual((row["attempt"], row["terminal"], row["persistent"]), (2, term, 1))
        self.assertEqual(self.sent_to(term)[-1]["text"], self.preamble(out["dispatch"]))
        # abandon 뒤에는 --retry 없이 같은 Task 를 다시 넣는다(입력 유실 재투입, herdr-team 5.9.8)
        code, res = self.o("worker-abandon", "--dispatch", out["dispatch"], "--keep-terminal")
        self.assertEqual(code, 0, res)
        code, again = self.o("worker-start", "--terminal", term, "--task", failed["task"])
        self.assertEqual(code, 0, again)
        self.assertEqual(self.row(again["dispatch"])["attempt"], 3)

    def test_sender_between_dispatches_is_external(self):
        _, term = self.first()
        code, out = self.horch("send", "--to", f"run:{self.run_id}", "--body", "사이 글", terminal=term)
        self.assertEqual(code, 0, out)
        msg = self.db().execute("SELECT sender, dispatch_id FROM messages WHERE id=?", (out["message"],)).fetchone()
        self.assertEqual((msg["sender"], msg["dispatch_id"]), (f"external:{term}", None))


class ExecutorDeathTest(PersistCase):
    """--terminal 실행자가 죽은 자리(13.4 실행자 사망 규칙). 조정은 다음 소유자 명령(reconcile_launching)이 한다."""

    def die(self, term, point) -> str:
        code, _ = self.put(term, env={"HORCH_TEST_DIE_AT": point})
        self.assertEqual(code, 137)
        return self.db().execute("SELECT id FROM dispatches WHERE terminal=? ORDER BY created_at DESC, rowid DESC",
                                 (term,)).fetchone()["id"]

    def reconcile(self):
        with mock.patch.dict(os.environ, self.env, clear=True):
            workers.reconcile_launching(self.store(), self.run_id)

    def test_before_attempt_is_launch_failed(self):
        _, term = self.first()
        did = self.die(term, "terminal_created")
        self.assertEqual(self.row(did)["state"], "launching")
        self.reconcile()
        row = self.row(did)
        self.assertEqual((row["state"], row["delivery"]), ("launch_failed", None))
        self.assertEqual(self.sent_to(term), [])

    def test_after_attempt_is_uncertain_active(self):
        for point, sent in (("terminal_attempted", 0), ("terminal_sent", 1)):
            with self.subTest(point=point):
                _, term = self.first()
                did = self.die(term, point)
                self.assertEqual(len(self.sent_to(term)), sent)
                self.reconcile()
                row = self.row(did)
                delivery = json.loads(row["delivery"])
                self.assertEqual(row["state"], "active")
                self.assertEqual((delivery["attempted"], delivery["uncertain"], delivery["error"]),
                                 (True, True, "executor_died"))
                self.assertEqual(row["start_turn"], 3)

    def test_after_result_stays_active(self):
        _, term = self.first()
        did = self.die(term, "terminal_recorded")
        self.reconcile()
        row = self.row(did)
        self.assertEqual(row["state"], "active")
        self.assertNotIn("uncertain", json.loads(row["delivery"]))

    def test_uncertain_then_not_started_or_turn(self):
        for turn_moves in (False, True):
            with self.subTest(turn_moves=turn_moves):
                _, term = self.first()
                did = self.die(term, "terminal_attempted")
                self.reconcile()
                db = self.db()
                db.execute("UPDATE dispatches SET created_at='2000-01-01T00:00:00Z' WHERE id=?", (did,))
                db.commit()
                if turn_moves:
                    self.update_terminal(term, status="working", turn=3)
                with mock.patch.dict(os.environ, self.env, clear=True):
                    liveness.observe(self.store(), self.run_id)
                kinds = [json.loads(r["body"])["kind"] for r in self.db().execute(
                    "SELECT body FROM messages WHERE type='observed' AND dispatch_id=?", (did,))]
                self.assertEqual(kinds, [] if turn_moves else ["not_started"])


class JudgmentTest(PersistCase):
    def second(self) -> tuple[str, str]:
        _, term = self.first()
        code, out = self.put(term)
        self.assertEqual(code, 0, out)
        return out["dispatch"], term

    def age_delivery(self, did) -> None:
        db = self.db()
        row = db.execute("SELECT delivery FROM dispatches WHERE id=?", (did,)).fetchone()
        delivery = json.loads(row["delivery"])
        delivery["at"] = "2000-01-01T00:00:00Z"
        db.execute("UPDATE dispatches SET delivery=? WHERE id=?", (json.dumps(delivery), did))
        db.commit()

    def observed(self, did) -> list[dict]:
        with mock.patch.dict(os.environ, self.env, clear=True):
            liveness.observe(self.store(), self.run_id)
        return [json.loads(r["body"]) for r in self.db().execute(
            "SELECT body FROM messages WHERE type='observed' AND dispatch_id=? ORDER BY id", (did,))]

    def workers_by_id(self) -> dict:
        code, out = self.o("worker-list")
        self.assertEqual(code, 0, out)
        return {w["id"]: w for w in out["workers"]}

    def test_liveness_uses_terminal_argv(self):
        did, term = self.second()
        self.assertEqual(self.workers_by_id()[did]["verdict"], "live")
        self.update_terminal(term, argv=["sh"])
        self.assertEqual(self.workers_by_id()[did]["verdict"], "lost")

    def test_idle_baseline_is_start_turn(self):
        did, term = self.second()
        self.assertEqual(self.observed(did), [])  # 다시 넣자마자(turn 3 == start_turn) 거짓 idle 이 없다
        self.assertIsNone(self.workers_by_id()[did]["attention"])
        self.update_terminal(term, status="done", turn=4)
        self.assertEqual([(b["kind"], b["key"]) for b in self.observed(did)], [("idle", "4")])
        self.assertEqual(self.workers_by_id()[did]["attention"], "idle")

    def test_not_started_conditions(self):
        did, term = self.second()
        self.age_delivery(did)
        bodies = self.observed(did)
        self.assertEqual([(b["kind"], b["key"]) for b in bodies], [("not_started", "3")])
        body = bodies[0]
        self.assertEqual((body["start_turn"], body["turn"], body["terminal"], body["status"]), (3, 3, term, "done"))
        self.assertEqual(body["delivery"]["turn_before"], 3)
        self.assertEqual(len(self.observed(did)), 1)  # 같은 사건은 한 번

    def test_not_started_not_raised(self):
        cases = ("recent", "working", "no_status", "turn_moved", "seen", "message")
        for case in cases:
            with self.subTest(case=case):
                did, term = self.second()
                if case != "recent":
                    self.age_delivery(did)
                if case == "working":
                    self.update_terminal(term, status="working")
                elif case == "no_status":
                    self.update_terminal(term, status=None)
                elif case == "turn_moved":
                    self.update_terminal(term, status="done", turn=4)
                elif case == "seen":
                    code, out = self.horch("check", "--dispatch", did, terminal=term)
                    self.assertEqual(code, 0, out)
                elif case == "message":
                    code, out = self.horch("send", "--to", f"run:{self.run_id}", "--body", "진행 중", terminal=term)
                    self.assertEqual(code, 0, out)
                kinds = [b["kind"] for b in self.observed(did)]
                self.assertNotIn("not_started", kinds)
                if case == "no_status":
                    self.assertEqual(self.workers_by_id()[did]["attention"], "no_status")

    def test_first_keep_open_dispatch_never_not_started(self):
        out = self.keep_open()
        db = self.db()
        db.execute("UPDATE dispatches SET created_at='2000-01-01T00:00:00Z' WHERE id=?", (out["dispatch"],))
        db.commit()
        self.update_terminal(out["terminal"], status="idle", turn=0)
        self.assertNotIn("not_started", [b["kind"] for b in self.observed(out["dispatch"])])

    def test_seen_at_set_once_by_worker_commands(self):
        did, term = self.second()
        self.assertIsNone(self.row(did)["seen_at"])
        code, out = self.horch("check", "--dispatch", did, terminal=term)
        self.assertEqual(code, 0, out)
        first = self.row(did)["seen_at"]
        self.assertTrue(first)
        db = self.db()
        db.execute("UPDATE dispatches SET seen_at='2000-01-01T00:00:00Z' WHERE id=?", (did,))
        db.commit()
        code, out = self.horch("escalate", "--dispatch", did, "--body", "막힘", terminal=term)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.row(did)["seen_at"], "2000-01-01T00:00:00Z")  # 비어 있을 때만 쓴다

    def test_seen_at_by_done_and_send(self):
        for cmd in ("done", "send"):
            with self.subTest(cmd=cmd):
                did, term = self.second()
                if cmd == "done":
                    self.settle(did, term)
                else:
                    self.horch("send", "--to", f"run:{self.run_id}", "--body", "x", terminal=term)
                self.assertTrue(self.row(did)["seen_at"])

    def test_worker_rows_have_new_fields(self):
        did, term = self.second()
        row = self.workers_by_id()[did]
        self.assertEqual((row["persistent"], row["start_turn"], row["seen_at"]), (True, 3, None))
        self.assertEqual(row["delivery"]["turn_before"], 3)
        code, shown = self.o("worker-show", "--dispatch", did, "--lines", "0")
        self.assertEqual(code, 0, shown)
        self.assertEqual((shown["worker"]["persistent"], shown["worker"]["start_turn"]), (True, 3))
        plain = self.start_worker(owner="t100")
        prow = self.workers_by_id()[plain["dispatch"]]
        self.assertEqual((prow["persistent"], prow["start_turn"], prow["delivery"], prow["seen_at"]),
                         (False, None, None, None))
        self.assertEqual(self.workers_by_id()[did]["state"], "active")


class KeepTerminalTest(PersistCase):
    def test_release_persistent_keeps_terminal(self):
        for extra in ((), ("--keep-terminal",)):
            with self.subTest(extra=extra):
                d1, term = self.first()
                calls = len(self.hc_calls())
                code, out = self.o("worker-release", "--dispatch", d1, *extra)
                self.assertEqual((code, out["dispatch"]["state"]), (0, "released"), out)
                self.assertEqual(self.hc_state()["terminals"][term]["state"], "live")
                self.assertEqual([c for c in self.hc_calls()[calls:] if c[0] in ("kill", "rm", "get")], [])

    def test_keep_terminal_on_plain_is_usage(self):
        out = self.start_worker(owner="t100")
        self.settle(out["dispatch"], out["terminal"])
        code, res = self.o("worker-release", "--dispatch", out["dispatch"], "--keep-terminal")
        self.assertEqual((code, res["error"]["code"]), (2, "usage"))
        self.assertEqual(self.row(out["dispatch"])["state"], "settled")

    def test_abandon_persistent_rules(self):
        out = self.keep_open()
        did, term = out["dispatch"], out["terminal"]
        code, res = self.o("worker-abandon", "--dispatch", did)
        self.assertEqual((code, res["error"]["code"]), (3, "worker_alive"))
        self.assertIn("--keep-terminal", res["error"]["hint"])
        self.assertIn("terminal-close --abandon", res["error"]["hint"])
        code, res = self.o("worker-abandon", "--dispatch", did, "--kill")
        self.assertEqual((code, res["error"]["code"]), (2, "usage"))
        calls = len(self.hc_calls())
        code, res = self.o("worker-abandon", "--dispatch", did, "--keep-terminal")
        self.assertEqual((code, res["dispatch"]["state"], res["verdict"]), (0, "abandoned", "live"))
        self.assertEqual(self.hc_state()["terminals"][term]["state"], "live")
        self.assertEqual([c for c in self.hc_calls()[calls:] if c[0] == "kill"], [])

    def test_abandon_exited_persistent_needs_no_flag(self):
        out = self.keep_open()
        self.update_terminal(out["terminal"], state="finished")
        code, res = self.o("worker-abandon", "--dispatch", out["dispatch"])
        self.assertEqual((code, res["verdict"]), (0, "exited"))

    def test_settled_persistent_attention_is_release(self):
        d1, _ = self.first()
        code, out = self.o("worker-list")
        row = {w["id"]: w for w in out["workers"]}[d1]
        self.assertEqual(row["attention"], "settled")
        self.assertIn("worker-release", row["next"])


class HandoverTest(PersistCase):
    """보내기 표시 뒤 결과 기록 전에 온 워커 명령(Codex 커밋 리뷰 847e971 P1, 설계 13.4 의 7 뒤).
    새 터미널의 가드 등록처럼 launching 을 active 로 넘기고 명령을 이어 간다. 가짜 hc 의 send 를 늦춰 그 틈을 만든다."""

    def start_slow(self, term):
        import time
        self.delay_hc("send", 3)
        proc = self.horch_bg("worker-start", "--terminal", term, "--title", "T2", "--spec", "두 번째", terminal="t100")
        db = self.db()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            row = db.execute("SELECT id, delivery FROM dispatches WHERE terminal=? ORDER BY created_at DESC, rowid DESC "
                             "LIMIT 1", (term,)).fetchone()
            if row and row["delivery"] and json.loads(row["delivery"]).get("attempted"):
                return proc, row["id"]
            time.sleep(0.05)
        proc.kill()
        self.fail("보내기 표시가 기록되지 않았다")

    def test_worker_check_after_attempt_takes_over(self):
        _, term = self.first()
        proc, did = self.start_slow(term)
        self.assertEqual(self.row(did)["state"], "launching")
        code, out = self.horch("check", "--dispatch", did, terminal=term)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.row(did)["state"], "active")
        code, res = self.finish(proc)
        self.assertEqual(code, 0, res)  # 실행자 7단계: 워커가 먼저 넘겼으면 결과만 쓰고 성공이다
        self.assertEqual((res["dispatch"], res["state"]), (did, "active"))
        row = self.row(did)
        delivery = json.loads(row["delivery"])
        self.assertEqual((row["state"], delivery["via"], delivery["started"]), ("active", "send", True))
        self.assertEqual(res["delivery"], delivery)
        self.assertEqual(self.hc_state()["terminals"][term]["labels"]["horch.dispatch"], did)

    def test_worker_done_after_attempt_is_recorded(self):
        _, term = self.first()
        proc, did = self.start_slow(term)
        self.settle(did, term)
        row = self.row(did)
        self.assertEqual((row["state"], row["outcome"]), ("settled", "succeeded"))
        task = self.db().execute("SELECT status FROM tasks WHERE id=?", (row["task_id"],)).fetchone()
        self.assertEqual(task["status"], "settled")
        done = self.db().execute("SELECT COUNT(*) FROM messages WHERE type='worker_done' AND dispatch_id=?",
                                 (did,)).fetchone()[0]
        self.assertEqual(done, 1)
        code, res = self.finish(proc)
        self.assertEqual(code, 0, res)
        self.assertEqual(self.row(did)["state"], "settled")

    def test_worker_call_before_attempt_is_refused(self):
        _, term = self.first()
        code, _ = self.put(term, env={"HORCH_TEST_DIE_AT": "terminal_created"})
        self.assertEqual(code, 137)
        did = self.db().execute("SELECT id FROM dispatches WHERE terminal=? ORDER BY created_at DESC, rowid DESC",
                                (term,)).fetchone()["id"]
        code, out = self.horch("check", "--dispatch", did, terminal=term)
        self.assertEqual((code, out["error"]["code"]), (3, "dispatch_not_active"), out)
        self.assertEqual(self.row(did)["state"], "launching")


class PersistentRetryHintTest(PersistCase):
    def test_launch_failed_persistent_has_no_next(self):
        """고정 Dispatch 의 launch_failed 는 재시도 안내를 주지 않는다(배치를 저장하지 않는다, Codex 커밋 리뷰 847e971 P2)."""
        self.fail_hc("run", "spawn_failed")
        code, out = self.o("worker-start", "--keep-open", "--hidden", "--agent", "codex", "--title", "R", "--spec", "s",
                           "--cwd", str(self.tmp))
        self.assertEqual((code, out["error"]["code"]), (1, "launch_failed"), out)
        self.clear_hc_fail("run")
        code, listed = self.o("worker-list")
        self.assertEqual(code, 0, listed)
        row = {w["id"]: w for w in listed["workers"]}[out["dispatch"]]
        self.assertEqual((row["attention"], row["next"]), ("launch_failed", None))
        code, shown = self.o("worker-show", "--dispatch", out["dispatch"], "--lines", "0")
        self.assertEqual(code, 0, shown)
        self.assertEqual((shown["worker"]["attention"], shown["worker"]["next"]), ("launch_failed", None))


if __name__ == "__main__":
    unittest.main()
