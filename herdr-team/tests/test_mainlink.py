"""메인 연결(설계 7장): render 검사, outbox·watch·answer·reask, decide 닫기와 워커 회신, ask-user, 없앤 명령."""
import json
import os
import threading
import time
import unittest
from unittest import mock

from tests.helpers import DRIVE, TeamCase
from hteam import outbox, state, testgate
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
        self.env["HTEAM_QUEUE_POLL_S"] = "0.05"

    def question(self, **kw) -> str:
        """관제가 올린 질문(설계 7.2 의 question). 0.4.0 에는 notify 명령이 없다. 관제가 안에서 쓰는 것과 같다."""
        return outbox.append(self.p, {"type": "question", "from": "drive", "render": outbox.validate_render(render(**kw),
                                                                                                          "질문")})["id"]

    def progress(self, body: str = "하나", type_: str = "progress") -> str:
        return outbox.append(self.p, {"type": type_, "from": "drive", "body": body})["id"]

    def run_messages(self):
        code, out = self.horch("check", terminal=DRIVE)
        self.assertEqual(code, 0, out)
        return out["messages"]

    def answer_file(self, oid: str) -> dict | None:
        path = self.state_dir / "answers" / f"{oid}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def requests(self) -> list[str]:
        folder = self.drive_dir / "queue"
        return sorted(f.name for f in folder.iterdir() if f.name.endswith(".json") and ".result" not in f.name) \
            if folder.exists() else []

    def wait_until(self, cond, what: str, limit: float = 20.0) -> None:
        deadline = time.monotonic() + limit
        while not cond():
            self.assertLess(time.monotonic(), deadline, what)
            time.sleep(0.05)

    def run_queue(self) -> list:
        with self.in_drive():
            return self.make_drive().run_queue()


class OutboxWatchTest(LinkCase):
    def test_watch_returns_new_items_then_moves_cursor(self):
        self.progress("하나")
        code, out = self.hteam("watch", as_="main")
        self.assertEqual((code, out["count"], out["messages"][0]["body"]), (0, 1, "하나"), out)
        self.assertEqual((self.state_dir / "outbox.cursor").read_text().strip(), "1")
        proc = self.hteam_bg("watch", as_="main")
        time.sleep(0.5)
        self.assertIsNone(proc.poll())  # 새 항목이 없으면 기다린다
        code, again = self.hteam("watch", as_="main")
        self.assertEqual((code, again["error"]["code"]), (3, "watch_running"))
        self.progress("둘", "done")
        code, out = self.finish(proc, timeout=10)
        self.assertEqual((code, [m["body"] for m in out["messages"]]), (0, ["둘"]))
        self.assertFalse((self.state_dir / "watch.pid").exists())

    def test_watch_orphaned_only_when_drive_is_down(self):
        # 관제 생존은 pid·heartbeat 로 본다(설계 7.3, 8.2). 멈춤(hung)이면 끝내지 않는다
        self.write_heartbeat(age_s=300)
        proc = self.hteam_bg("watch", as_="main")
        time.sleep(0.6)
        self.assertIsNone(proc.poll())
        self.progress("멈춘 동안 온 것")
        code, out = self.finish(proc, timeout=10)
        self.assertEqual((code, out["count"]), (0, 1), out)
        (self.drive_dir / "drive.pid").unlink()
        code, out = self.hteam("watch", as_="main", timeout=10)
        self.assertEqual((code, out["status"]), (0, "orphaned"), out)
        self.update_terminal(DRIVE, state="finished")  # 관제 터미널이 끝나도 판정은 pid 다
        self.write_drive_pid()
        self.write_heartbeat()
        proc = self.hteam_bg("watch", as_="main")
        time.sleep(0.6)
        self.assertIsNone(proc.poll())
        self.progress("셋")
        self.assertEqual(self.finish(proc, timeout=10)[0], 0)

    def test_works_with_broken_config(self):
        (self.team / "config.toml").write_text("max_parallel = [")
        self.progress("x")
        self.assertEqual(self.hteam("watch", as_="main")[0], 0)


class AnswerTest(LinkCase):
    def test_question_answer_is_a_file_and_is_not_sent(self):
        oid = self.question()
        code, out = self.hteam("answer", oid, "localStorage (추천)", as_="main")
        self.assertEqual(out, {"ok": True, "id": oid, "type": "question", "test_confirmed": False}, out)
        self.assertEqual(code, 0)
        self.assertEqual(self.answer_file(oid)["answer"], "localStorage (추천)")
        self.assertEqual(self.run_messages(), [])  # 0.3.0 의 `[main] reply` 글은 없다
        self.assertEqual(self.hteam("answer", oid, "localStorage (추천)", as_="main")[0], 0)  # 같은 답은 그대로
        code, out = self.hteam("answer", oid, "다른 답", as_="main")
        self.assertEqual((code, out["error"]["code"]), (3, "already_answered"))
        code, out = self.hteam("answer", "out-0099", "x", as_="main")
        self.assertEqual((code, out["error"]["code"]), (2, "unknown_question"))
        self.assertEqual(outbox.open_questions(self.p), [])

    def test_kinds_that_are_not_answered(self):
        for type_ in ("progress", "result", "done"):
            oid = self.progress("x", type_)
            code, out = self.hteam("answer", oid, "x", as_="main")
            self.assertEqual((code, out["error"]["code"], out["error"]["message"]),
                             (2, "not_answerable", f"{oid} 은 {type_} 항목이라 답하지 않는다"), out)
        oid = outbox.append(self.p, {"type": "approval", "from": "drive", "batch": "dr-0001",
                                     "render": outbox.validate_render(render(), "승인")})["id"]
        code, out = self.hteam("answer", oid, "모두 승인 (추천)", as_="main")
        self.assertEqual((code, out["error"]["code"], out["error"]["message"]),
                         (2, "use_design_decide", f"{oid} 은 일괄 승인 질문이다. 태스크별 결정을 "
                                                  f"`hteam design-decide {oid} --json -` 으로 넘긴다"), out)
        self.assertIsNone(self.answer_file(oid))

    def test_reask_and_open_questions(self):
        first = self.question()
        self.hteam("watch", as_="main")  # first 를 출력했다
        second = self.question(header="둘째")
        code, out = self.hteam("reask", as_="main")
        self.assertEqual((code, [m["id"] for m in out["messages"]]), (0, [first]))  # second 는 watch 가 준다
        self.hteam("answer", first, "a", as_="main")
        self.assertEqual(self.hteam("reask", as_="main")[1]["messages"], [])
        self.assertEqual([q["id"] for q in outbox.open_questions(self.p)], [second])

    def test_hyphen_leading_answer(self):
        oid = self.question()
        code, out = self.hteam("answer", oid, "--", "--no-cache", as_="main")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.answer_file(oid)["answer"], "--no-cache")


class DecideAnswerTest(LinkCase):
    """decide 는 답 파일로 닫는다(설계 7.4, 8.10). 워커 질문이면 먼저 요청 큐 reply 로 워커에게 보낸다."""

    def decide(self, kind="escalation", task="T-001", **extra) -> str:
        with self.in_drive():
            return self.make_drive().decide(kind, task, "요약", files=["docs/tasks/T-001/report.md"],
                                            commands=[".herdr-team/bin/hteam drop T-001"], **extra)

    def asking_worker(self) -> tuple[str, str, int]:
        """일하는 작업 워커가 horch ask 로 질문을 남겼다(답을 기다리다 시간 초과). (Dispatch, 터미널, 질문 id)."""
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        self.assertEqual(self.hteam("start", "T-001")[0], 0)
        did = self.work_dispatch("T-001")
        term = self.dispatch_row(did)["terminal"]
        code, out = self.horch("ask", "--dispatch", did, "--question", "설정 파일은 어디에 둘까", "--timeout-ms", "100",
                               terminal=term)
        self.assertEqual(code, 4, out)
        return did, term, out["question"]

    def test_plain_decide_is_closed_by_the_answer_file(self):
        oid = self.decide()
        self.assertEqual([(q["id"], q["type"]) for q in outbox.open_questions(self.p)], [(oid, "decide")])
        self.hteam("watch", as_="main")
        self.assertEqual([m["id"] for m in self.hteam("reask", as_="main")[1]["messages"]], [oid])
        code, out = self.hteam("answer", oid, "T-001 를 drop 했다", as_="main")
        self.assertEqual(out, {"ok": True, "id": oid, "type": "decide", "closed": True, "replied": False}, out)
        self.assertEqual(self.answer_file(oid)["answer"], "T-001 를 drop 했다")
        self.assertEqual(outbox.open_questions(self.p), [])
        self.assertEqual(self.requests(), [])  # 회신이 없으면 큐를 거치지 않는다
        code, out = self.hteam("answer", oid, "다시", as_="main")
        self.assertEqual((code, out["error"]["code"]), (3, "already_answered"), out)

    def test_worker_question_reply_goes_through_the_queue(self):
        did, term, qid = self.asking_worker()
        oid = self.decide("worker_question", question="설정 파일은 어디에 둘까", message_id=qid)
        proc = self.hteam_bg("answer", oid, "src/config 에 둔다", as_="main", env={"HTEAM_QUEUE_WAIT_S": "30"})
        self.wait_until(lambda: self.requests() or proc.poll() is not None, "reply 요청")
        req = json.loads((self.drive_dir / "queue" / self.requests()[0]).read_text())
        self.assertEqual((req["command"], req["args"]),
                         ("reply", {"message_id": qid, "body": "src/config 에 둔다", "task": "T-001"}), req)
        self.assertIsNone(self.answer_file(oid))  # 회신 결과를 받기 전에는 닫지 않는다
        self.run_queue()
        code, out = self.finish(proc)
        self.assertEqual((code, out["closed"], out["replied"]), (0, True, True), out)
        self.assertIsInstance(out["reply"], int)
        self.assertEqual(self.answer_file(oid)["answer"], "src/config 에 둔다")
        code, out = self.horch("ask", "--dispatch", did, "--resume", str(qid), "--timeout-ms", "100", terminal=term)
        self.assertEqual((code, out["answer"]), (0, "src/config 에 둔다"), out)

    def test_refused_reply_closes_the_decide(self):
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        oid = self.decide("escalation", message_id=999999)  # 처리에 실패한 워커 질문(8.5): 없는 질문 id
        proc = self.hteam_bg("answer", oid, "답", as_="main", env={"HTEAM_QUEUE_WAIT_S": "30"})
        self.wait_until(lambda: self.requests() or proc.poll() is not None, "reply 요청")
        self.run_queue()
        code, out = self.finish(proc)
        self.assertEqual((code, out["error"]["code"]), (3, "reply_failed"), out)
        msg = out["error"]["message"]
        self.assertTrue(msg.startswith("워커에게 답을 보내지 못했다(unknown_question: "), msg)
        self.assertTrue(msg.endswith('). 워커가 끝났으면 답을 지시로 넣어 hteam fix T-001 --note "<답>", 아직 일하는 중이면 '
                                     'hteam scope T-001 "<답>" 로 전한다. 이 decide 는 닫았다'), msg)
        self.assertEqual(self.answer_file(oid)["answer"], "답")
        self.assertEqual(outbox.open_questions(self.p), [])

    def test_drive_down_keeps_the_decide_open(self):
        _, _, qid = self.asking_worker()
        oid = self.decide("worker_question", message_id=qid)
        (self.drive_dir / "drive.pid").unlink()
        code, out = self.hteam("answer", oid, "답", as_="main")
        self.assertEqual((code, out["error"]["code"]), (1, "drive_down"), out)
        self.assertIsNone(self.answer_file(oid))
        self.assertEqual([q["id"] for q in outbox.open_questions(self.p)], [oid])  # 다시 답할 수 있다

    def test_queue_timeout_closes_the_decide(self):
        _, _, qid = self.asking_worker()
        oid = self.decide("worker_question", message_id=qid)
        code, out = self.hteam("answer", oid, "답", as_="main", env={"HTEAM_QUEUE_WAIT_S": "0.3"})
        self.assertEqual((code, out["closed"], out["replied"], out["status"], out["request"]),
                         (0, True, None, "queued", "q-000001"), out)
        self.assertEqual(self.answer_file(oid)["answer"], "답")
        self.run_queue()
        [res] = [e for e in self.outbox_items() if e["type"] == "result"]
        self.assertEqual((res["command"], res["result"]["ok"]), ("reply", True), res)

    def test_status_lists_open_decides(self):
        oid = self.decide()
        code, out = self.hteam("status", as_="main")
        self.assertEqual(code, 0, out)
        self.assertEqual([(q["id"], q["type"], q.get("kind"), q.get("task")) for q in out["open_questions"]],
                         [(oid, "decide", "escalation", "T-001")])


class RemovedCommandTest(LinkCase):
    def test_removed_commands_are_usage_errors(self):
        for args, kwargs in ((("tell", "x"), {"as_": "main"}), (("notify", "--type", "progress", "--body", "x"), {}),
                             (("applied", "out-0001"), {}), (("wait",), {}), (("which", "dsp-1"), {}),
                             (("design-review", "--decide", "out-0001"), {})):
            with self.subTest(args=args):
                code, out = self.hteam(*args, **kwargs)
                self.assertEqual((code, out["error"]["code"]), (2, "usage"), out)
        self.assertFalse((self.state_dir / "outbox.jsonl").exists())
        self.assertEqual(self.run_messages(), [])


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


class TestConfirmTest(LinkCase):
    """테스트 명령 확정(설계 5.7): 확정 질문의 `## 테스트 명령` 절·식별값, 메인 answer 의 확정 기록(Run 에 보내지 않는다)."""

    def setUp(self):
        super().setUp()
        self.env["HTEAM_ASK_TIMEOUT"] = "0.5"
        self.write_spec("T-001", "planner")
        state.create(self.p, "T-001", "planner")
        self.assertEqual(self.hteam("start", "T-001")[0], 0)
        self.term = self.dispatch_row(self.work_dispatch("T-001"))["terminal"]
        self.plan = self.proj / "docs/planning/tasks.toml"
        self.plan.parent.mkdir(parents=True, exist_ok=True)

    def ask(self, obj=None):
        return self.hteam("ask-user", "--task", "T-001", "--json", "-", "--test-confirm", as_=None, terminal=self.term,
                          stdin=json.dumps(obj or render(context="## 계획 핵심\n- 할 일 앱")))

    def entries(self):
        return [json.loads(x) for x in (self.state_dir / "outbox.jsonl").read_text().splitlines()]

    def approvals(self):
        with mock.patch.dict(os.environ, self.env, clear=True):
            return [a["digest"] for a in testgate.read_approvals(self.p)], testgate.approvals_path(self.p)

    def drive_question(self) -> str:
        """관제의 `[test]` 확정 질문(설계 8.4): 커밋된 HEAD 의 [test] 로 `## 테스트 명령` 절과 식별값을 붙인다."""
        with mock.patch.dict(os.environ, self.env, clear=True):
            fields = outbox.test_confirm(outbox.validate_render(render(), "질문"), testgate.require_config(self.p))
            return outbox.append(self.p, {"type": "question", "from": "drive", **fields})["id"]

    def test_ask_user_attaches_section_and_first_option_confirms(self):
        self.plan.write_text('[test]\nquick = " npx vitest related --run {files}"\nfull = "npx vitest run"\n',
                             encoding="utf-8")  # 커밋 전(작업 트리)이다
        code, out = self.ask()
        self.assertEqual((code, out["status"]), (4, "waiting"), out)
        entry = self.entries()[-1]
        want = testgate.digest(testgate.parse_config({"quick": "npx vitest related --run {files}", "full": "npx vitest run"}))
        self.assertEqual(entry["test_digest"], want)
        self.assertEqual(entry["render"]["context"], "## 계획 핵심\n- 할 일 앱\n\n## 테스트 명령\n" + testgate.CONFIRM_LINE +
                         '\n```toml\nquick = "npx vitest related --run {files}"\nfull = "npx vitest run"\n'
                         "timeout_min = 30\nok_exit = [0]\nexclusive = false\n```")
        code, out = self.hteam("answer", entry["id"], "localStorage (추천)", terminal=DRIVE, as_=None)
        self.assertEqual(code, 5, out)  # 관제 터미널은 답하지 못한다(기록도 없다)
        self.assertEqual(self.approvals()[0], [])
        code, out = self.hteam("answer", entry["id"], "localStorage (추천)", as_="main")
        self.assertEqual((code, out["test_confirmed"]), (0, True), out)
        digests, path = self.approvals()
        self.assertEqual(digests, [want])
        self.assertFalse(str(path).startswith(str(self.proj)))

    def test_ask_user_refusals(self):
        code, out = self.ask()
        self.assertEqual((code, out["error"]["code"]), (2, "no_test_config"), out)
        self.plan.write_text('[test]\nquick = "x"\nfull = "y"\n', encoding="utf-8")
        code, out = self.ask()
        self.assertEqual((code, out["error"]["code"]), (2, "bad_test_config"), out)
        self.plan.write_text('[test]\nquick = "x {files}"\nfull = "y"\n', encoding="utf-8")
        code, out = self.ask(render(context="가" * 3900))
        self.assertEqual((code, out["error"]["code"]), (2, "bad_render"), out)
        self.assertIn("4000자를 넘는다", out["error"]["message"])
        self.assertFalse((self.state_dir / "outbox.jsonl").exists())

    def test_drive_question_only_first_option_confirms_and_is_not_sent(self):
        self.use_gate(approve=False)
        gate = self.hteam("status")[1]["test_gate"]
        self.assertEqual(gate["state"], "unapproved")
        self.assertIn("hteam test-confirm", gate["hint"])  # 0.4.0 은 관제가 묻고, 메인은 큐로 다시 올린다
        self.assertNotIn("notify", gate["hint"])
        first = self.drive_question()
        self.assertTrue(self.entries()[-1]["render"]["context"].startswith("## 테스트 명령\n"))
        code, out = self.hteam("answer", first, "서버 DB", as_="main")
        self.assertEqual((code, out["test_confirmed"]), (0, False), out)
        self.assertEqual(self.approvals()[0], [])
        second = self.drive_question()
        for _ in range(2):  # 같은 답을 두 번 해도 기록은 하나다
            code, out = self.hteam("answer", second, "localStorage (추천)", as_="main")
            self.assertEqual((code, out["test_confirmed"]), (0, True), out)
        self.assertEqual(len(self.approvals()[0]), 1)
        self.assertEqual(self.run_messages(), [])  # Run 에 보내지 않는다(설계 7.4)
        gate = self.hteam("status")[1]["test_gate"]
        self.assertEqual((gate["state"], gate["digest"], gate["error"]), ("approved", self.approvals()[0][0], None))

    def test_broken_record_stops_the_answer(self):
        self.use_gate(approve=False)
        oid = self.drive_question()
        path = self.approvals()[1]
        path.parent.mkdir(parents=True)
        path.write_text("[1, 2]", encoding="utf-8")
        code, out = self.hteam("answer", oid, "localStorage (추천)", as_="main")
        self.assertEqual((code, out["error"]["code"]), (1, "bad_test_approvals"), out)
        self.assertIn(str(path), out["error"]["message"])
        self.assertEqual(path.read_text(encoding="utf-8"), "[1, 2]")
        self.assertIsNone(self.answer_file(oid))
        self.assertEqual(self.hteam("status")[1]["test_gate"]["state"], "error")


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
        with mock.patch.object(herdr, "get", side_effect=HteamError("hc_failed", "x", data={"kind": "not_found"})):
            self.assertEqual(herdr.probe("t9", ["claude"]), "unverifiable")

    def test_hc_missing_or_not_runnable_is_unverifiable(self):
        # hc 가 없으면 get 은 exit 12, 실행할 수 없으면(권한 등) hc_failed. probe 는 둘 다 모름이다(horch hcio 와 같다).
        from hteam import herdr
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
    entry = {"id": oid, "at": "2026-01-01T00:00:00Z", "type": "progress", "body": body, "from": "drive",
             "answered": False, **kw}
    return json.dumps(entry, ensure_ascii=False).encode("utf-8")


class MainOnlyTest(LinkCase):
    """answer·watch·reask 는 메인 터미널만(부작용 전에 검사). 관제·워커(지난 워커 포함)는 exit 5."""

    def test_drive_cannot_answer_its_own_question(self):
        oid = self.question()
        code, out = self.hteam("answer", oid, "x")  # 관제 환경 + DRIVE 터미널
        self.assertEqual((code, out["error"]["code"]), (5, "not_main"), out)
        self.assertIsNone(self.answer_file(oid))
        self.assertEqual([q["id"] for q in outbox.open_questions(self.p)], [oid])

    def test_drive_terminal_or_role_refused(self):
        code, out = self.hteam("reask", as_=None, terminal=DRIVE)  # HTEAM_ROLE 없는 관제 터미널
        self.assertEqual((code, out["error"]["code"]), (5, "not_main"), out)
        code, out = self.hteam("reask", as_="main", env={"HTEAM_ROLE": "drive"})
        self.assertEqual((code, out["error"]["code"]), (5, "not_main"), out)
        # Run 에 묶이기 전(run.json 에 터미널이 아직 없음)의 관제 터미널은 hteam up 이 붙인 hc 라벨로 가린다(설계 9.3)
        self.add_terminal("t5", argv=["hteam-drive"], labels={"hteam.role": "drive"})
        code, out = self.hteam("reask", as_=None, terminal="t5")
        self.assertEqual((code, out["error"]["code"]), (5, "not_main"), out)

    def test_unverifiable_terminal_refused(self):
        self.fail_hc("get", "boom")
        code, out = self.hteam("reask", as_="main")
        self.assertEqual((code, out["error"]["code"]), (1, "main_unverified"), out)

    def test_unparseable_run_json_is_not_overwritten(self):
        (self.state_dir / "run.json").write_text("{", encoding="utf-8")
        code, out = self.hteam("answer", "out-0001", "a", as_="main")
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

    def test_worker_cannot_answer_its_own_ask(self):
        code, out = self.ask()
        self.assertEqual(code, 4, out)
        code, out = self.hteam("answer", "out-0001", "self", as_=None, terminal=self.term)
        self.assertEqual((code, out["error"]["code"]), (5, "not_main"), out)
        self.assertIsNone(self.answer_file("out-0001"))
        code, out = self.hteam("ask-user", "--task", "T-001", "--wait", "out-0001", as_=None, terminal=self.term)
        self.assertEqual(code, 4, out)
        code, out = self.hteam("reask", as_=None, terminal=self.term)
        self.assertEqual((code, out["error"]["code"]), (5, "not_main"), out)

    def test_past_worker_terminal_refused(self):
        # Dispatch 가 끝나면 horch status 는 dispatch 를 주지 않는다. 그래도 워커 터미널이면 메인이 아니다.
        code, out = self.act_work("T-001", files={"docs/planning/a.md": "a\n"})
        self.assertEqual(code, 0, out)
        code, out = self.horch("status", terminal=self.term)
        self.assertIsNone(out["dispatch"], out)
        code, out = self.hteam("reask", as_=None, terminal=self.term)
        self.assertEqual((code, out["error"]["code"]), (5, "not_main"), out)

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


class OutboxReadTest(LinkCase):
    @property
    def outbox_path(self):
        return self.state_dir / "outbox.jsonl"

    def test_unicode_line_separators_stay_in_record(self):
        body = "가 나 다\x85라"
        self.progress(body)
        code, out = self.hteam("watch", as_="main")
        self.assertEqual((code, [m["body"] for m in out.get("messages", [])]), (0, [body]), out)
        self.assertEqual(self.progress("둘"), "out-0002")

    def test_partial_last_line_and_corrupt_line(self):
        full = outbox_line("out-0002", "가나")
        torn = full[:full.index("나".encode()) + 1]  # 쓰다 만 줄(여러 바이트 글자 중간에서 끊김)
        self.outbox_path.write_bytes(outbox_line("out-0001") + b"\n" + torn)
        code, out = self.hteam("watch", as_="main")
        self.assertEqual((code, [m["id"] for m in out.get("messages", [])]), (0, ["out-0001"]), out)
        self.assertEqual((self.state_dir / "outbox.cursor").read_text().strip(), "1")
        self.assertEqual(self.hteam("reask", as_="main")[0], 0)
        self.assertEqual(self.progress("셋"), "out-0003")  # 끊긴 줄도 한 줄로 센다(ID 재사용 없음)
        with self.outbox_path.open("ab") as fh:
            fh.write(b"not json\n")
        self.assertEqual(self.progress("넷"), "out-0005")
        code, out = self.hteam("watch", as_="main")
        self.assertEqual((code, [m["id"] for m in out["messages"]]), (0, ["out-0003", "out-0005"]), out)
        self.assertEqual(len(out["warnings"]), 2, out)  # 2번째(끊긴 줄)와 4번째 줄

    def test_concurrent_appends_ids_unique(self):
        ids, errors = [], []

        def one(i):
            try:
                ids.append(outbox.append(self.p, {"type": "progress", "from": "drive", "body": f"n{i}"})["id"])
            except Exception as exc:  # 스레드 안의 실패를 시험으로 넘긴다
                errors.append(exc)

        threads = [threading.Thread(target=one, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(ids), [f"out-{i:04d}" for i in range(1, 9)])

    def test_reask_uses_one_snapshot(self):
        first = self.question()
        self.hteam("watch", as_="main")
        real = outbox.cursor

        def cursor_then_append(p):
            value = real(p)
            outbox.append(p, {"type": "question", "render": render(header="새 질문"), "from": "drive"})
            return value

        with mock.patch.object(outbox, "cursor", side_effect=cursor_then_append):
            out = outbox.reask(self.p)
        self.assertEqual([m["id"] for m in out["messages"]], [first])


class JsonLineTest(unittest.TestCase):
    """horch·hc 출력의 JSON 줄도 LF 로만 나눈다(본문의 U+2028 등이 JSON 을 자르지 않게)."""

    def test_horch_and_hc_output_split_on_lf_only(self):
        from hteam import herdr, horch
        line = json.dumps({"ok": True, "body": "가 나 다\x85라"}, ensure_ascii=False)
        self.assertEqual(horch.parse("잡음\n" + line + "\n")["body"], "가 나 다\x85라")
        done = mock.Mock(returncode=0, stdout=line + "\n", stderr="")
        with mock.patch.object(herdr.subprocess, "run", return_value=done):
            self.assertEqual(herdr.get("t9")["body"], "가 나 다\x85라")


class WatchLockTest(LinkCase):
    def test_exclusive_without_pid_file(self):
        proc = self.hteam_bg("watch", as_="main")
        self.wait_until((self.state_dir / "watch.pid").exists, "watch.pid")
        (self.state_dir / "watch.pid").unlink()  # pid 파일이 사라져도 단일 실행은 잠금이 지킨다
        code, out = self.hteam("watch", as_="main", timeout=5)
        self.assertEqual((code, out["error"]["code"]), (3, "watch_running"), out)
        self.progress("하나")
        self.assertEqual(self.finish(proc, timeout=10)[0], 0)

    def test_concurrent_watches_only_one_runs(self):
        procs = [self.hteam_bg("watch", as_="main") for _ in range(3)]
        self.wait_until(lambda: sum(p.poll() is not None for p in procs) >= 2, "두 watch 가 끝난다")
        losers = [p for p in procs if p.poll() is not None]
        self.assertEqual(len(losers), 2)
        for p in losers:
            code, out = self.finish(p)
            self.assertEqual((code, out["error"]["code"]), (3, "watch_running"), out)
        self.progress("하나")
        winner = next(p for p in procs if p not in losers)
        code, out = self.finish(winner, timeout=10)
        self.assertEqual((code, [m["body"] for m in out["messages"]]), (0, ["하나"]))

    def test_exclusive_until_cursor_moved(self):
        gate = self.tmp / "gate"
        proc = self.hteam_bg("watch", as_="main", env={"HTEAM_TEST_PAUSE_AT": "watch_before_cursor",
                                                        "HTEAM_TEST_PAUSE_FILE": str(gate)})
        self.wait_until((self.state_dir / "watch.pid").exists, "watch.pid")
        self.progress("하나")
        self.wait_until(gate.with_name("gate.reached").exists, "출력 뒤 커서 전에 멈춘다")
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
    """watch·reask 도 메인 전용이다(설계 8.3). 관제가 부르면 잠금·커서를 건드리지 않고 exit 5."""

    def test_drive_watch_and_reask_refused(self):
        self.question()
        code, out = self.hteam("watch", timeout=10)  # 관제 환경
        self.assertEqual((code, out.get("error", {}).get("code")), (5, "not_main"), out)
        code, out = self.hteam("watch", as_=None, terminal=DRIVE, timeout=10)
        self.assertEqual((code, out.get("error", {}).get("code")), (5, "not_main"), out)
        code, out = self.hteam("reask")
        self.assertEqual((code, out.get("error", {}).get("code")), (5, "not_main"), out)
        self.assertFalse((self.state_dir / "outbox.cursor").exists())
        code, out = self.hteam("watch", as_="main")  # 메인은 잠금 없이 바로 받는다
        self.assertEqual((code, [m["id"] for m in out["messages"]]), (0, ["out-0001"]), out)

    def test_unread_counts_complete_lines_after_cursor(self):
        self.progress("하나")
        with (self.state_dir / "outbox.jsonl").open("ab") as fh:
            fh.write(b"not json\n")
        self.progress("셋")
        with (self.state_dir / "outbox.jsonl").open("ab") as fh:
            fh.write(b'{"id": "out-0004"')  # 쓰는 중인 마지막 조각은 세지 않는다
        self.assertEqual(outbox.unread(self.p), 3)  # 깨진 줄도 센다(len(read_outbox) 는 2)
        self.assertEqual(self.hteam("watch", as_="main")[0], 0)
        self.assertEqual(outbox.unread(self.p), 0)


class ParentTest(LinkCase):
    """hc parent 를 따라 올라가 워커·관제 터미널 아래에서 띄운 터미널을 메인으로 보지 않는다(최대 10단계)."""

    def reask_from(self, term):
        return self.hteam("reask", as_=None, terminal=term)

    def child(self, address, parent, **kw):
        self.add_terminal(address, **kw)
        self.update_terminal(address, parent=parent)

    def test_child_of_worker_or_drive_refused(self):
        self.add_terminal("t50", labels={"horch.run": "r", "horch.dispatch": "dsp-x"})
        self.child("t51", "t50")
        self.child("t52", "t51")
        self.add_terminal("t60", labels={"hteam.role": "drive"})
        self.child("t61", "t60")
        for term in ("t51", "t52", "t61"):
            code, out = self.reask_from(term)
            self.assertEqual((code, out.get("error", {}).get("code")), (5, "not_main"), (term, out))

    def test_plain_parent_chain_is_main(self):
        self.add_terminal("t70")
        self.update_terminal("t1", parent="t70")
        code, out = self.reask_from("t1")
        self.assertEqual(code, 0, out)

    def test_cycle_or_missing_parent_is_unverified(self):
        self.child("t80", "t81")
        self.child("t81", "t80")
        self.child("t82", "t99")  # 없는 터미널
        for term in ("t80", "t82"):
            code, out = self.reask_from(term)
            self.assertEqual((code, out.get("error", {}).get("code")), (1, "main_unverified"), (term, out))


if __name__ == "__main__":
    unittest.main()
