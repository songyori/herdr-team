"""메인 연결(설계 7장): render 검사, notify·watch·answer·applied·reask·tell, ask-user."""
import json
import time
import unittest

from tests.helpers import COORD, TeamCase
from hteam import outbox, state
from hteam.errors import HteamError
from hteam.paths import Project


def render(**kw):
    obj = {"header": "저장 위치", "question": "할 일을 어디에 저장할까요?\n예: 브라우저 저장소면 서버가 필요 없다",
           "options": [{"label": "localStorage (추천)", "description": "추천 사유: 첫 버전에 서버가 없다"},
                       {"label": "서버 DB", "description": "기기 간 동기화가 된다"}],
           "multiSelect": False}
    obj.update(kw)
    return obj


class RenderTest(unittest.TestCase):
    def errors(self, obj):
        with self.assertRaises(HteamError) as ctx:
            outbox.validate_render(obj, "질문")
        self.assertEqual((ctx.exception.code, ctx.exception.exit_code), ("bad_render", 2))
        return "\n".join(ctx.exception.data["errors"])

    def test_valid_and_default_header(self):
        obj = render()
        del obj["header"]
        out = outbox.validate_render(obj, "기획")
        self.assertEqual((out["header"], out["multiSelect"]), ("기획", False))
        self.assertNotIn("context", out)
        self.assertEqual(outbox.validate_render(render(context="표"), "x")["context"], "표")

    def test_rules(self):
        self.assertIn("header 는 12자", self.errors(render(header="가" * 13)))
        self.assertIn("두 줄", self.errors(render(question="한 줄만")))
        self.assertIn("'예: '", self.errors(render(question="질문\n보기")))
        self.assertIn("300자", self.errors(render(question="가" * 301 + "\n예: 보기")))
        self.assertIn("context 는 4000자", self.errors(render(context="가" * 4001)))
        self.assertIn("options 는 2–4개", self.errors(render(options=[{"label": "a (추천)", "description": "추천 사유: x"}])))
        opts = [{"label": "a", "description": "추천 사유: x"}, {"label": "b", "description": "y"}]
        self.assertIn("'(추천)'", self.errors(render(options=opts)))
        opts = [{"label": "a (추천)", "description": "x"}, {"label": "b", "description": "y"}]
        self.assertIn("추천 사유:", self.errors(render(options=opts)))
        opts = [{"label": "a (추천)", "description": "추천 사유: x"}, {"label": "가" * 31, "description": "y"}]
        self.assertIn("options[1].label", self.errors(render(options=opts)))
        self.assertIn("multiSelect", self.errors(render(multiSelect=True)))
        self.assertIn("모르는 필드: extra", self.errors(render(extra=1)))


class LinkCase(TeamCase):
    def setUp(self):
        super().setUp()
        self.init_project()
        self.run_id = self.setup_run()
        self.p = Project(self.proj)
        self.env["HTEAM_ORPHAN_CHECK"] = "0.1"

    def notify_q(self, **kw):
        code, out = self.hteam("notify", "--type", "question", "--json", "-", stdin=json.dumps(render(**kw)))
        self.assertEqual(code, 0, out)
        return out["id"]

    def run_messages(self):
        code, out = self.horch("check", terminal=COORD)
        self.assertEqual(code, 0, out)
        return out["messages"]


class NotifyWatchTest(LinkCase):
    def test_notify_appends_outbox(self):
        code, out = self.hteam("notify", "--type", "progress", "--body", "준비 완료")
        self.assertEqual((code, out["id"]), (0, "out-0001"))
        self.assertEqual(self.notify_q(), "out-0002")
        lines = [json.loads(x) for x in (self.state_dir / "outbox.jsonl").read_text().splitlines()]
        self.assertEqual([(e["type"], e["from"], e["answered"]) for e in lines],
                         [("progress", "coordinator", False), ("question", "coordinator", False)])
        self.assertEqual(lines[1]["render"]["header"], "저장 위치")
        code, out = self.hteam("notify", "--type", "question", "--body", "x")
        self.assertEqual((code, out["error"]["code"]), (2, "usage"))
        code, out = self.hteam("notify", "--type", "question", "--json", "-", stdin="{")
        self.assertEqual((code, out["error"]["code"]), (2, "bad_render"))
        code, out = self.hteam("notify", "--type", "progress", "--body", "x", as_="main")
        self.assertEqual(code, 5)

    def test_watch_returns_new_items_then_moves_cursor(self):
        self.hteam("notify", "--type", "progress", "--body", "하나")
        code, out = self.hteam("watch", as_="main")
        self.assertEqual((code, out["count"], out["messages"][0]["body"]), (0, 1, "하나"), out)
        self.assertEqual((self.state_dir / "outbox.cursor").read_text().strip(), "1")
        proc = self.hteam_bg("watch", as_="main")
        time.sleep(0.5)
        self.assertIsNone(proc.poll())  # 새 항목이 없으면 기다린다
        code, again = self.hteam("watch", as_="main")
        self.assertEqual((code, again["error"]["code"]), (3, "watch_running"))
        self.hteam("notify", "--type", "done", "--body", "둘")
        code, out = self.finish(proc, timeout=10)
        self.assertEqual((code, [m["body"] for m in out["messages"]]), (0, ["둘"]))
        self.assertFalse((self.state_dir / "watch.pid").exists())

    def test_watch_orphaned_when_coordinator_ends(self):
        self.update_terminal(COORD, state="finished")
        code, out = self.hteam("watch", as_="main", timeout=10)
        self.assertEqual((code, out["status"]), (0, "orphaned"))

    def test_works_with_broken_config(self):
        (self.team / "config.toml").write_text("max_parallel = [")
        code, out = self.hteam("notify", "--type", "progress", "--body", "x")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.hteam("watch", as_="main")[0], 0)


class AnswerTest(LinkCase):
    def test_tell_sends_main_message(self):
        code, out = self.hteam("tell", "로그인 화면을 만들어 줘\n자세히는…", as_="main")
        self.assertEqual(code, 0, out)
        msg = self.run_messages()[0]
        self.assertEqual((msg["subject"], msg["sender"]), ("[main] 로그인 화면을 만들어 줘", "external:t1"))

    def test_answer_question_persists_then_sends_and_resends(self):
        oid = self.notify_q()
        code, out = self.hteam("answer", oid, "localStorage (추천)", as_="main")
        self.assertEqual((code, out["sent"]), (0, True), out)
        self.assertEqual(json.loads((self.state_dir / "answers" / f"{oid}.json").read_text())["answer"],
                         "localStorage (추천)")
        self.assertEqual(self.hteam("answer", oid, "localStorage (추천)", as_="main")[0], 0)  # 끊겨 다시 보냄
        subjects = [m["subject"] for m in self.run_messages()]
        self.assertEqual(subjects, [f"[main] reply {oid}"] * 2)
        code, out = self.hteam("answer", oid, "다른 답", as_="main")
        self.assertEqual((code, out["error"]["code"]), (3, "already_answered"))
        code, out = self.hteam("answer", "out-0099", "x", as_="main")
        self.assertEqual((code, out["error"]["code"]), (2, "unknown_question"))
        self.hteam("notify", "--type", "progress", "--body", "x")
        code, out = self.hteam("answer", "out-0002", "x", as_="main")
        self.assertEqual((code, out["error"]["code"]), (2, "not_a_question"))

    def test_tell_records_main_terminal_and_needs_one(self):
        self.hteam("tell", "a", as_="main")
        self.assertEqual(json.loads((self.state_dir / "run.json").read_text())["main_terminals"], ["t1"])
        code, out = self.hteam("tell", "a", as_=None)
        self.assertEqual((code, out["error"]["code"]), (5, "no_terminal"))

    def test_applied_and_reask(self):
        first = self.notify_q()
        self.hteam("watch", as_="main")  # first 를 출력했다
        second = self.notify_q(header="둘째")
        code, out = self.hteam("reask", as_="main")
        self.assertEqual((code, [m["id"] for m in out["messages"]]), (0, [first]))  # second 는 watch 가 준다
        self.hteam("answer", first, "a", as_="main")
        self.assertEqual(self.hteam("reask", as_="main")[1]["messages"], [])
        self.assertEqual(self.hteam("applied", first)[0], 0)
        self.assertIn(first, json.loads((self.state_dir / "applied.json").read_text()))
        self.assertEqual([q["id"] for q in outbox.open_questions(self.p)], [second])


class AskUserTest(LinkCase):
    def setUp(self):
        super().setUp()
        self.env["HTEAM_ASK_TIMEOUT"] = "0.5"
        self.write_spec("T-001", "planner")
        state.create(self.p, "T-001", "planner")
        self.assertEqual(self.hteam("start", "T-001")[0], 0)
        self.term = self.dispatch_row(self.work_dispatch("T-001"))["terminal"]

    def ask(self, *extra, obj=None):
        return self.hteam("ask-user", "--task", "T-001", *extra, "--json", "-", as_=None, terminal=self.term,
                          stdin=json.dumps(obj or render()))

    def test_timeout_then_wait_ack_pending_history(self):
        code, out = self.ask()
        self.assertEqual((code, out["status"], out["id"]), (4, "waiting", "out-0001"), out)
        entry = json.loads((self.state_dir / "outbox.jsonl").read_text().splitlines()[0])
        self.assertEqual((entry["type"], entry["from"], entry["round"]), ("ask", "T-001", 1))
        code, out = self.ask()
        self.assertEqual((code, out["error"]["code"], out["id"]), (3, "question_open", "out-0001"))
        self.assertEqual([q["id"] for q in outbox.open_questions(self.p)], ["out-0001"])
        self.assertEqual(self.hteam("answer", "out-0001", "서버 DB", as_="main")[0], 0)
        code, out = self.hteam("answer", "out-0001", "다시", as_="main")
        self.assertEqual((code, out["error"]["code"]), (3, "already_answered"))
        code, out = self.hteam("ask-user", "--task", "T-001", "--wait", "out-0001", as_=None)
        self.assertEqual((code, out["answer"]), (0, "서버 DB"))
        code, out = self.hteam("ask-user", "--task", "T-001", "--pending", as_=None)
        self.assertEqual([i["id"] for i in out["pending"]], ["out-0001"])
        self.assertEqual(self.hteam("ask-user", "--task", "T-001", "--ack", "out-0001", as_=None)[0], 0)
        self.assertEqual(self.hteam("ask-user", "--task", "T-001", "--pending", as_=None)[1]["pending"], [])
        code, out = self.hteam("ask-user", "--task", "T-001", "--history", as_=None)
        self.assertEqual(out["history"][0]["answer"], "서버 DB")
        self.assertTrue(out["history"][0]["acked"])

    def test_answer_arrives_while_waiting(self):
        self.env["HTEAM_ASK_TIMEOUT"] = "20"
        proc = self.hteam_bg("ask-user", "--task", "T-001", "--json", "-", as_=None, terminal=self.term,
                             stdin=json.dumps(render()))
        deadline = time.monotonic() + 10
        while not (self.state_dir / "outbox.jsonl").exists():
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.05)
        self.hteam("answer", "out-0001", "localStorage (추천)", as_="main")
        code, out = self.finish(proc, timeout=20)
        self.assertEqual((code, out["answer"]), (0, "localStorage (추천)"), out)
        self.assertEqual(outbox.open_questions(self.p), [])

    def test_only_planner_director_and_own_terminal(self):
        code, out = self.hteam("ask-user", "--task", "T-001", "--json", "-", as_="main", stdin=json.dumps(render()))
        self.assertEqual((code, out["error"]["code"]), (5, "not_this_worker"))
        self.write_spec("T-002", "tester")
        state.create(self.p, "T-002", "tester")
        code, out = self.hteam("ask-user", "--task", "T-002", "--json", "-", as_=None, terminal=self.term,
                               stdin=json.dumps(render()))
        self.assertEqual((code, out["error"]["code"]), (3, "not_ask_role"))
        code, out = self.ask(obj=render(options=[]))
        self.assertEqual((code, out["error"]["code"]), (2, "bad_render"))

    def test_ask_of_finished_task_is_not_open(self):
        self.ask()
        with state.edit(self.p, "T-001") as st:
            state.move(st, "reviewing", "review")
        self.assertEqual(outbox.open_questions(self.p), [])


class HerdrVerdictTest(unittest.TestCase):
    """hteam 의 생존 판정은 horch liveness.verdict 와 같아야 한다(설계 9.3)."""

    def test_same_as_horch(self):
        from tests.helpers import REPO
        from hteam import herdr
        src = (REPO / "herdr-orch/lib/horch/liveness.py").read_text()  # horch 의 판정 함수를 그대로 실행해 비교한다
        ns = {}
        exec(compile(src.replace("from . import hcio", "hcio = None"), "liveness", "exec"), ns)
        argv = ["claude"]
        cases = [None, {"state": "finished"}, {"state": "live", "argv": argv}, {"state": "live", "argv": ["x"]},
                 {"state": "live"}, {"state": "live", "argv": None}, {"state": "live", "reason": "stopped_by_restart"},
                 {"state": "weird"}]
        for info in cases:
            for expected in (argv, None):
                self.assertEqual(herdr.verdict(info, expected), ns["verdict"](info, expected), (info, expected))

    def test_probe_not_found_is_unverifiable(self):
        from hteam import herdr
        from unittest import mock
        with mock.patch.object(herdr, "get", side_effect=HteamError("hc_failed", "x", data={"kind": "not_found"})):
            self.assertEqual(herdr.probe("t9", ["claude"]), "unverifiable")

    def test_hc_missing_or_not_runnable_is_unverifiable(self):
        # hc 가 없으면 get 은 exit 12, 실행할 수 없으면(권한 등) hc_failed. probe 는 둘 다 모름이다(horch hcio 와 같다).
        from hteam import herdr
        from unittest import mock
        for exc, code, exit_code in ((FileNotFoundError("hc"), "hc_missing", 12),
                                     (PermissionError("hc"), "hc_failed", 1)):
            with mock.patch.object(herdr.subprocess, "run", side_effect=exc):
                with self.assertRaises(HteamError) as ctx:
                    herdr.get("t9")
                self.assertEqual((ctx.exception.code, ctx.exception.exit_code), (code, exit_code))
                self.assertEqual(herdr.probe("t9", ["claude"]), "unverifiable")


class AfterHookTest(unittest.TestCase):
    """cli 규약: 결과의 `_after` 는 JSON 을 출력한 뒤에 부른다. 실패해도 출력한 결과와 exit 코드는 그대로다."""

    def run_main(self, make_result):
        """make_result(out) 가 돌려준 결과로 cli.main 을 돌린다. out 은 stdout 을 받는 StringIO 다."""
        import contextlib
        import io
        from unittest import mock
        from hteam import cli
        out, err = io.StringIO(), io.StringIO()
        parser = cli.Parser(prog="hteam")
        parser.set_defaults(func=lambda args: make_result(out))
        with mock.patch.object(cli, "build_parser", return_value=parser), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            code = cli.main([])
        return code, out.getvalue(), err.getvalue()

    def test_after_runs_once_after_output(self):
        seen = []
        code, out, _ = self.run_main(lambda buf: {"count": 1, "_after": lambda: seen.append(buf.getvalue())})
        self.assertEqual((code, len(seen)), (0, 1))
        lines = seen[0].strip().splitlines()
        self.assertEqual(len(lines), 1)  # _after 가 불린 때 이미 결과 한 줄이 나가 있었다
        self.assertEqual(json.loads(lines[0]), {"ok": True, "count": 1})  # _after 는 출력에 들어가지 않는다
        self.assertEqual(out, seen[0])

    def test_after_failure_keeps_result_and_exit_code(self):
        def boom():
            raise OSError("디스크가 찼다")

        code, out, err = self.run_main(lambda buf: {"count": 2, "_after": boom})
        self.assertEqual(code, 0)
        lines = out.strip().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0]), {"ok": True, "count": 2})
        self.assertIn("디스크가 찼다", err)
        self.assertNotIn("Traceback", err)


if __name__ == "__main__":
    unittest.main()
