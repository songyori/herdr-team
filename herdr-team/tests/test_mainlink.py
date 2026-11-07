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


class AppliedRecordTest(LinkCase):
    def test_corrupt_applied_record_is_kept_and_reported(self):
        from hteam import coord
        oid = self.notify_q()
        self.assertEqual(self.hteam("answer", oid, "a", as_="main")[0], 0)
        path = self.state_dir / "applied.json"
        path.write_text("{broken")
        code, out = self.hteam("applied", oid)
        self.assertEqual((code, out["error"]["code"]), (1, "bad_side_file"), out)
        self.assertEqual(path.read_text(), "{broken")  # 빈 기록으로 덮어쓰지 않았다
        msg = {"id": 9, "type": "status", "subject": f"[main] reply {oid}", "body": "a", "sender": "external:t1"}
        info = coord.annotate(self.p, msg, [], "horch")["hteam"]
        self.assertEqual((info["kind"], info["reply_to"], info["duplicate"]), ("main", oid, None))
        self.assertIn("이미 적용했는지 모른다", info["hint"])
        # 일괄 승인 답이어도 design_review 가 붙지 않는다. 손으로 반영(accept·fix)하지 않게 분명히 말한다
        self.assertIn("이 답을 처리하지 않고 applied 도 적지 않는다", info["hint"])


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
        self.assertEqual(self.hteam("ask-user", "--task", "T-001", "--ack", "out-0001", as_=None,
                                    terminal=self.term)[0], 0)  # ack 도 작업 워커 터미널에서만
        self.assertEqual(self.hteam("ask-user", "--task", "T-001", "--pending", as_=None)[1]["pending"], [])
        code, out = self.hteam("ask-user", "--task", "T-001", "--history", as_=None)
        self.assertEqual(out["history"][0]["answer"], "서버 DB")
        self.assertTrue(out["history"][0]["acked"])

    def test_corrupt_ack_record_is_not_overwritten(self):
        # 손상된 반영 기록을 빈 기록으로 읽으면 ack 한 번이 기록 전체를 덮어써 --pending 이 반영한 답을 다시 낸다
        self.ask()
        self.assertEqual(self.hteam("answer", "out-0001", "서버 DB", as_="main")[0], 0)
        path = self.state_dir / "ask-acks.json"
        path.write_text("{", encoding="utf-8")
        for args in (("--pending",), ("--history",)):
            code, out = self.hteam("ask-user", "--task", "T-001", *args, as_=None)
            self.assertEqual((code, out["error"]["code"]), (1, "bad_side_file"), out)
        code, out = self.hteam("ask-user", "--task", "T-001", "--ack", "out-0001", as_=None, terminal=self.term)
        self.assertEqual((code, out["error"]["code"]), (1, "bad_side_file"), out)
        self.assertEqual(path.read_text(encoding="utf-8"), "{")

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

    def test_after_skipped_when_stdout_fails(self):
        # 출력하지 못하면 _after(watch 커서)를 부르지 않는다. 그래야 전하지 못한 항목을 다음 watch 가 다시 준다.
        import contextlib
        from unittest import mock
        from hteam import cli

        class Broken:
            def write(self, _):
                raise BrokenPipeError("닫힌 파이프")

            def flush(self):
                pass

        called = []
        parser = cli.Parser(prog="hteam")
        parser.set_defaults(func=lambda args: {"count": 1, "_after": lambda: called.append(1)})
        with mock.patch.object(cli, "build_parser", return_value=parser), contextlib.redirect_stdout(Broken()):
            with self.assertRaises(BrokenPipeError):
                cli.main([])
        self.assertEqual(called, [])


def outbox_line(oid, body="하나", **kw):
    entry = {"id": oid, "at": "2026-01-01T00:00:00Z", "type": "progress", "body": body, "from": "coordinator",
             "answered": False, **kw}
    return json.dumps(entry, ensure_ascii=False).encode("utf-8")


class MainOnlyTest(LinkCase):
    """tell·answer 는 메인 터미널만(부작용 전에 검사). 코디네이터·워커(지난 워커 포함)는 exit 5."""

    def run_json(self):
        return json.loads((self.state_dir / "run.json").read_text())

    def test_coordinator_cannot_answer_own_question(self):
        oid = self.notify_q()
        code, out = self.hteam("answer", oid, "x")  # 코디네이터 환경 + COORD 터미널
        self.assertEqual((code, out["error"]["code"]), (5, "not_main"), out)
        self.assertFalse((self.state_dir / "answers" / f"{oid}.json").exists())
        self.assertNotIn("main_terminals", self.run_json())
        self.assertEqual([q["id"] for q in outbox.open_questions(self.p)], [oid])

    def test_coordinator_terminal_or_role_refused(self):
        code, out = self.hteam("tell", "a", as_=None, terminal=COORD)  # HTEAM_ROLE 없는 코디네이터 터미널
        self.assertEqual((code, out["error"]["code"]), (5, "not_main"), out)
        code, out = self.hteam("tell", "a", as_="main", env={"HTEAM_ROLE": "coordinator"})
        self.assertEqual((code, out["error"]["code"]), (5, "not_main"), out)
        # bind 전(run.json 에 터미널이 아직 없음)의 코디네이터 터미널은 hteam up 이 붙인 hc 라벨로 가린다(설계 9.3)
        self.add_terminal("t5", argv=["claude"], labels={"hteam.role": "coordinator"})
        code, out = self.hteam("tell", "a", as_=None, terminal="t5")
        self.assertEqual((code, out["error"]["code"]), (5, "not_main"), out)
        self.assertNotIn("main_terminals", self.run_json())
        self.assertEqual(self.run_messages(), [])

    def test_unverifiable_terminal_refused(self):
        self.fail_hc("get", "boom")
        code, out = self.hteam("tell", "a", as_="main")
        self.assertEqual((code, out["error"]["code"]), (1, "main_unverified"), out)
        self.assertNotIn("main_terminals", self.run_json())

    def test_unparseable_run_json_is_not_overwritten(self):
        (self.state_dir / "run.json").write_text("{", encoding="utf-8")
        code, out = self.hteam("tell", "a", as_="main")
        self.assertEqual((code, out["error"]["code"]), (1, "bad_run_file"), out)
        self.assertEqual((self.state_dir / "run.json").read_text(), "{")


class WorkerGuardTest(LinkCase):
    def setUp(self):
        super().setUp()
        self.env["HTEAM_ASK_TIMEOUT"] = "0.3"
        self.write_spec("T-001", "planner")
        state.create(self.p, "T-001", "planner")
        self.assertEqual(self.hteam("start", "T-001")[0], 0)
        self.term = self.dispatch_row(self.work_dispatch("T-001"))["terminal"]

    def ask(self):
        return self.hteam("ask-user", "--task", "T-001", "--json", "-", as_=None, terminal=self.term,
                          stdin=json.dumps(render()))

    def test_worker_cannot_answer_own_ask_or_tell(self):
        code, out = self.ask()
        self.assertEqual(code, 4, out)
        code, out = self.hteam("answer", "out-0001", "self", as_=None, terminal=self.term)
        self.assertEqual((code, out["error"]["code"]), (5, "not_main"), out)
        self.assertFalse((self.state_dir / "answers" / "out-0001.json").exists())
        code, out = self.hteam("ask-user", "--task", "T-001", "--wait", "out-0001", as_=None, terminal=self.term)
        self.assertEqual(code, 4, out)
        code, out = self.hteam("tell", "[x] hi", as_=None, terminal=self.term)
        self.assertEqual((code, out["error"]["code"]), (5, "not_main"), out)
        self.assertNotIn("main_terminals", json.loads((self.state_dir / "run.json").read_text()))
        self.assertEqual(self.run_messages(), [])

    def test_past_worker_terminal_refused(self):
        # Dispatch 가 끝나면 horch status 는 dispatch 를 주지 않는다. 그래도 워커 터미널이면 메인이 아니다.
        code, out = self.act_work("T-001", files={"docs/planning/a.md": "a\n"})
        self.assertEqual(code, 0, out)
        code, out = self.horch("status", terminal=self.term)
        self.assertIsNone(out["dispatch"], out)
        code, out = self.hteam("tell", "[main] 지시", as_=None, terminal=self.term)
        self.assertEqual((code, out["error"]["code"]), (5, "not_main"), out)
        self.assertNotIn("main_terminals", json.loads((self.state_dir / "run.json").read_text()))

    def test_ack_checks_caller(self):
        self.ask()
        self.assertEqual(self.hteam("answer", "out-0001", "서버 DB", as_="main")[0], 0)
        code, out = self.hteam("ask-user", "--task", "T-001", "--ack", "out-0001", as_="main")
        self.assertEqual((code, out["error"]["code"]), (5, "not_this_worker"), out)
        self.assertFalse((self.state_dir / "ask-acks.json").exists())
        code, out = self.hteam("ask-user", "--task", "T-001", "--ack", "out-0001", as_=None, terminal=self.term)
        self.assertEqual(code, 0, out)

    def test_open_questions_skips_corrupt_task_state(self):
        self.ask()
        (self.state_dir / "tasks" / "T-001.json").write_text("{", encoding="utf-8")
        warnings = []
        self.assertEqual(outbox.open_questions(self.p, warnings=warnings), [])
        self.assertTrue(any("T-001" in w for w in warnings), warnings)
        code, out = self.hteam("reask", as_="main")
        self.assertEqual((code, out["messages"]), (0, []), out)
        self.assertTrue(any("T-001" in w for w in out["warnings"]), out)


class SendTest(LinkCase):
    def test_hyphen_leading_text_is_body(self):
        oid = self.notify_q()
        code, out = self.hteam("answer", oid, "--", "--no-cache", as_="main")
        self.assertEqual(code, 0, out)
        code, out = self.hteam("tell", "--", "-x 로 해 줘", as_="main")
        self.assertEqual(code, 0, out)
        self.assertEqual([m["body"] for m in self.run_messages()], ["--no-cache", "-x 로 해 줘"])

    def test_unsent_answer_stays_visible_until_resent(self):
        oid = self.notify_q()
        self.hteam("watch", as_="main")
        run = json.loads((self.state_dir / "run.json").read_text())
        good = run["run_id"]
        run["run_id"] = "run-bogus"
        (self.state_dir / "run.json").write_text(json.dumps(run))
        code, out = self.hteam("answer", oid, "a", as_="main")
        self.assertEqual(code, 1, out)  # 보내지 못했다
        open_ = outbox.open_questions(self.p)
        self.assertEqual([(q["id"], q.get("unsent"), q.get("answer")) for q in open_], [(oid, True, "a")])
        self.assertIn(f"answer {oid}", open_[0]["hint"])
        code, out = self.hteam("reask", as_="main")
        self.assertEqual([(m["id"], m.get("unsent")) for m in out["messages"]], [(oid, True)])
        run["run_id"] = good
        (self.state_dir / "run.json").write_text(json.dumps(run))
        code, out = self.hteam("answer", oid, "a", as_="main")
        self.assertEqual(code, 0, out)
        self.assertTrue(json.loads((self.state_dir / "answers" / f"{oid}.json").read_text())["sent_at"])
        self.assertEqual(outbox.open_questions(self.p), [])

    def test_tell_starting_with_reply_is_not_a_reply_subject(self):
        import re
        code, out = self.hteam("tell", "reply out-0001 은 취소하고 B 로 해 줘", as_="main")
        self.assertEqual(code, 0, out)
        msg = self.run_messages()[0]
        self.assertIsNone(re.match(r"^\[main\] reply (out-\d+)", msg["subject"]), msg["subject"])
        self.assertEqual(msg["body"], "reply out-0001 은 취소하고 B 로 해 줘")

    def test_applied_rejects_unknown_id(self):
        code, out = self.hteam("applied", "out-0099")
        self.assertEqual((code, out["error"]["code"]), (2, "unknown_question"), out)
        self.assertFalse((self.state_dir / "applied.json").exists())


class OutboxReadTest(LinkCase):
    @property
    def outbox_path(self):
        return self.state_dir / "outbox.jsonl"

    def test_unicode_line_separators_stay_in_record(self):
        body = "가 나 다\x85라"
        self.assertEqual(self.hteam("notify", "--type", "progress", "--body", body)[0], 0)
        code, out = self.hteam("watch", as_="main")
        self.assertEqual((code, [m["body"] for m in out.get("messages", [])]), (0, [body]), out)
        code, out = self.hteam("notify", "--type", "progress", "--body", "둘")
        self.assertEqual((code, out.get("id")), (0, "out-0002"), out)

    def test_partial_last_line_and_corrupt_line(self):
        full = outbox_line("out-0002", "가나")
        torn = full[:full.index("나".encode()) + 1]  # 쓰다 만 줄(여러 바이트 글자 중간에서 끊김)
        self.outbox_path.write_bytes(outbox_line("out-0001") + b"\n" + torn)
        code, out = self.hteam("watch", as_="main")
        self.assertEqual((code, [m["id"] for m in out.get("messages", [])]), (0, ["out-0001"]), out)
        self.assertEqual((self.state_dir / "outbox.cursor").read_text().strip(), "1")
        self.assertEqual(self.hteam("reask", as_="main")[0], 0)
        code, out = self.hteam("notify", "--type", "progress", "--body", "셋")
        self.assertEqual((code, out.get("id")), (0, "out-0003"), out)  # 끊긴 줄도 한 줄로 센다(ID 재사용 없음)
        with self.outbox_path.open("ab") as fh:
            fh.write(b"not json\n")
        code, out = self.hteam("notify", "--type", "progress", "--body", "넷")
        self.assertEqual((code, out.get("id")), (0, "out-0005"), out)
        code, out = self.hteam("watch", as_="main")
        self.assertEqual((code, [m["id"] for m in out["messages"]]), (0, ["out-0003", "out-0005"]), out)
        self.assertEqual(len(out["warnings"]), 2, out)  # 2번째(끊긴 줄)와 4번째 줄

    def test_concurrent_notify_ids_unique(self):
        procs = [self.hteam_bg("notify", "--type", "progress", "--body", f"n{i}") for i in range(8)]
        ids = []
        for proc in procs:
            code, out = self.finish(proc, timeout=30)
            self.assertEqual(code, 0, out)
            ids.append(out["id"])
        self.assertEqual(sorted(ids), [f"out-{i:04d}" for i in range(1, 9)])

    def test_reask_uses_one_snapshot(self):
        from unittest import mock
        first = self.notify_q()
        self.hteam("watch", as_="main")
        real = outbox.cursor

        def cursor_then_append(p):
            value = real(p)
            outbox.append(p, {"type": "question", "render": render(header="새 질문"), "from": "coordinator"})
            return value

        with mock.patch.object(outbox, "cursor", side_effect=cursor_then_append):
            out = outbox.reask(self.p)
        self.assertEqual([m["id"] for m in out["messages"]], [first])


class JsonLineTest(unittest.TestCase):
    """horch·hc 출력의 JSON 줄도 LF 로만 나눈다(본문의 U+2028 등이 JSON 을 자르지 않게)."""

    def test_horch_and_hc_output_split_on_lf_only(self):
        from unittest import mock
        from hteam import herdr, horch
        line = json.dumps({"ok": True, "body": "가 나 다\x85라"}, ensure_ascii=False)
        self.assertEqual(horch.parse("잡음\n" + line + "\n")["body"], "가 나 다\x85라")
        done = mock.Mock(returncode=0, stdout=line + "\n", stderr="")
        with mock.patch.object(herdr.subprocess, "run", return_value=done):
            self.assertEqual(herdr.get("t9")["body"], "가 나 다\x85라")


class WatchLockTest(LinkCase):
    def wait_for(self, cond, what, limit=10.0):
        deadline = time.monotonic() + limit
        while not cond():
            self.assertLess(time.monotonic(), deadline, what)
            time.sleep(0.05)

    def test_exclusive_without_pid_file(self):
        proc = self.hteam_bg("watch", as_="main")
        self.wait_for((self.state_dir / "watch.pid").exists, "watch.pid")
        (self.state_dir / "watch.pid").unlink()  # pid 파일이 사라져도 단일 실행은 잠금이 지킨다
        code, out = self.hteam("watch", as_="main", timeout=5)
        self.assertEqual((code, out["error"]["code"]), (3, "watch_running"), out)
        self.hteam("notify", "--type", "progress", "--body", "하나")
        self.assertEqual(self.finish(proc, timeout=10)[0], 0)

    def test_concurrent_watches_only_one_runs(self):
        procs = [self.hteam_bg("watch", as_="main") for _ in range(3)]
        self.wait_for(lambda: sum(p.poll() is not None for p in procs) >= 2, "두 watch 가 끝난다")
        losers = [p for p in procs if p.poll() is not None]
        self.assertEqual(len(losers), 2)
        for p in losers:
            code, out = self.finish(p)
            self.assertEqual((code, out["error"]["code"]), (3, "watch_running"), out)
        self.hteam("notify", "--type", "progress", "--body", "하나")
        winner = next(p for p in procs if p not in losers)
        code, out = self.finish(winner, timeout=10)
        self.assertEqual((code, [m["body"] for m in out["messages"]]), (0, ["하나"]))

    def test_exclusive_until_cursor_moved(self):
        gate = self.tmp / "gate"
        proc = self.hteam_bg("watch", as_="main", env={"HTEAM_TEST_PAUSE_AT": "watch_before_cursor",
                                                        "HTEAM_TEST_PAUSE_FILE": str(gate)})
        self.wait_for((self.state_dir / "watch.pid").exists, "watch.pid")
        self.hteam("notify", "--type", "progress", "--body", "하나")
        self.wait_for(gate.with_name("gate.reached").exists, "출력 뒤 커서 전에 멈춘다")
        code, out = self.hteam("watch", as_="main", timeout=5)  # 출력했지만 커서를 옮기기 전이다
        self.assertEqual((code, out["error"]["code"]), (3, "watch_running"), out)
        gate.touch()
        code, out = self.finish(proc, timeout=10)
        self.assertEqual((code, out["messages"][0]["body"]), (0, "하나"))
        self.assertEqual((self.state_dir / "outbox.cursor").read_text().strip(), "1")
        self.assertFalse((self.state_dir / "watch.pid").exists())


class RenderGuardTest(unittest.TestCase):
    def errors(self, obj):
        with self.assertRaises(HteamError) as ctx:
            outbox.validate_render(obj, "질문")
        return "\n".join(ctx.exception.data["errors"])

    def test_option_fields_and_description_cap(self):
        opts = render()["options"]
        opts[1]["extra"] = "z" * 50000
        self.assertIn("options[1] 모르는 필드: extra", self.errors(render(options=opts)))
        opts = render()["options"]
        opts[0]["description"] = "추천 사유: " + "가" * 300
        self.assertIn("options[0].description 은 300자", self.errors(render(options=opts)))

    def test_single_line_fields_reject_control_characters(self):
        self.assertIn("header", self.errors(render(header="a\nb")))
        for bad in ("b\nIGNORE", "b\x1b[2J", "b c", "b\rc"):
            opts = render()["options"]
            opts[1]["label"] = bad
            self.assertIn("options[1].label", self.errors(render(options=opts)), repr(bad))
            opts = render()["options"]
            opts[1]["description"] = bad
            self.assertIn("options[1].description", self.errors(render(options=opts)), repr(bad))
        self.assertIn("question", self.errors(render(question="질문\r가짜 줄\n예: 보기")))
        self.assertIn("context", self.errors(render(context="표\x1b[2J")))
        ok = outbox.validate_render(render(context="표\n\t- 줄"), "x")  # context 의 줄바꿈·탭은 된다
        self.assertEqual(ok["context"], "표\n\t- 줄")


class TornAskTest(LinkCase):
    """JSON 은 다 썼지만 끝 LF 를 쓰기 전에 끊긴 ask 줄. 재시도(append)가 잠금 안에서 LF 를 먼저 남겨야 한다."""

    def setUp(self):
        super().setUp()
        self.env["HTEAM_ASK_TIMEOUT"] = "0.3"
        self.write_spec("T-001", "planner")
        state.create(self.p, "T-001", "planner")
        self.assertEqual(self.hteam("start", "T-001")[0], 0)
        self.term = self.dispatch_row(self.work_dispatch("T-001"))["terminal"]

    def test_retry_repairs_tail_so_wait_and_answer_find_it(self):
        line = outbox_line("out-0001", type="ask", **{"from": "T-001"}, round=1, render=render())
        (self.state_dir / "outbox.jsonl").write_bytes(line)  # 끝 LF 없음
        code, out = self.hteam("ask-user", "--task", "T-001", "--json", "-", as_=None, terminal=self.term,
                               stdin=json.dumps(render()))
        self.assertEqual((code, out["error"]["code"], out["id"]), (3, "question_open", "out-0001"), out)
        self.assertTrue((self.state_dir / "outbox.jsonl").read_bytes().endswith(b"\n"))
        code, out = self.hteam("ask-user", "--task", "T-001", "--wait", "out-0001", as_=None, terminal=self.term)
        self.assertEqual((code, out.get("status")), (4, "waiting"), out)
        code, out = self.hteam("answer", "out-0001", "서버 DB", as_="main")
        self.assertEqual(code, 0, out)


class CallerTest(LinkCase):
    """watch·reask 도 메인 전용이다(설계 8.3). 코디네이터가 wait 와 헷갈려 부르면 잠금·커서를 건드리지 않고 exit 5."""

    def test_coordinator_watch_and_reask_refused(self):
        self.notify_q()
        code, out = self.hteam("watch", timeout=10)  # 코디네이터 환경
        self.assertEqual((code, out.get("error", {}).get("code")), (5, "not_main"), out)
        code, out = self.hteam("watch", as_=None, terminal=COORD, timeout=10)
        self.assertEqual((code, out.get("error", {}).get("code")), (5, "not_main"), out)
        code, out = self.hteam("reask")
        self.assertEqual((code, out.get("error", {}).get("code")), (5, "not_main"), out)
        self.assertFalse((self.state_dir / "outbox.cursor").exists())
        code, out = self.hteam("watch", as_="main")  # 메인은 잠금 없이 바로 받는다
        self.assertEqual((code, [m["id"] for m in out["messages"]]), (0, ["out-0001"]), out)

    def test_unread_counts_complete_lines_after_cursor(self):
        self.hteam("notify", "--type", "progress", "--body", "하나")
        with (self.state_dir / "outbox.jsonl").open("ab") as fh:
            fh.write(b"not json\n")
        self.hteam("notify", "--type", "progress", "--body", "셋")
        with (self.state_dir / "outbox.jsonl").open("ab") as fh:
            fh.write(b'{"id": "out-0004"')  # 쓰는 중인 마지막 조각은 세지 않는다
        self.assertEqual(outbox.unread(self.p), 3)  # 깨진 줄도 센다(len(read_outbox) 는 2)
        self.assertEqual(self.hteam("watch", as_="main")[0], 0)
        self.assertEqual(outbox.unread(self.p), 0)


class ParentTest(LinkCase):
    """hc parent 를 따라 올라가 워커·코디네이터 터미널 아래에서 띄운 터미널을 메인으로 보지 않는다(최대 10단계)."""

    def tell_from(self, term):
        return self.hteam("tell", "a", as_=None, terminal=term)

    def child(self, address, parent, **kw):
        self.add_terminal(address, **kw)
        self.update_terminal(address, parent=parent)

    def test_child_of_worker_or_coordinator_refused(self):
        self.add_terminal("t50", labels={"horch.run": "r", "horch.dispatch": "dsp-x"})
        self.child("t51", "t50")
        self.child("t52", "t51")
        self.add_terminal("t60", labels={"hteam.role": "coordinator"})
        self.child("t61", "t60")
        for term in ("t51", "t52", "t61"):
            code, out = self.tell_from(term)
            self.assertEqual((code, out.get("error", {}).get("code")), (5, "not_main"), (term, out))
        self.assertEqual(self.run_messages(), [])

    def test_plain_parent_chain_is_main(self):
        self.add_terminal("t70")
        self.update_terminal("t1", parent="t70")
        code, out = self.tell_from("t1")
        self.assertEqual(code, 0, out)

    def test_cycle_or_missing_parent_is_unverified(self):
        self.child("t80", "t81")
        self.child("t81", "t80")
        self.child("t82", "t99")  # 없는 터미널
        for term in ("t80", "t82"):
            code, out = self.tell_from(term)
            self.assertEqual((code, out.get("error", {}).get("code")), (1, "main_unverified"), (term, out))


if __name__ == "__main__":
    unittest.main()
