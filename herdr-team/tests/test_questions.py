"""8단계 질문 보기(설계 7.4a): hteam question-view(메인 옆 보기 pane 을 열고 정리한다)와 question-pager(전문을 보이고
답이 오거나 질문이 닫히면 끝난다). 가짜 hc·herdr-app 을 쓴다."""
import fcntl
import json
import subprocess
import sys
import time
import unittest

from tests.helpers import BIN, MAIN, TeamCase
from hteam import outbox, state
from hteam.paths import Project

LONG = "## 긴 표\n" + "\n".join(f"| {i} |" for i in range(40))


class QuestionCase(TeamCase):
    def setUp(self):
        super().setUp()
        self.init_project()
        self.setup_run()
        self.p = Project(self.proj)
        self.qdir = self.state_dir / "questions"

    def question(self, ctx=LONG, header="시험"):
        item = outbox.append(self.p, {"type": "question", "from": "drive", "render": outbox.validate_render(
            {"question": "시험 질문?\n예: 확인", "header": header, "context": ctx,
             "options": [{"label": "가 (추천)", "description": "추천 사유: x"}, {"label": "나", "description": "y"}]},
            "질문")})
        self.qdir.mkdir(parents=True, exist_ok=True)
        (self.qdir / f"{item['id']}.md").write_text(f"# 질문 보기 {item['id']}: {header}\n\n{ctx}\n", encoding="utf-8")
        return item["id"]

    def write_answer(self, oid):
        (self.state_dir / "answers").mkdir(parents=True, exist_ok=True)
        (self.state_dir / "answers" / f"{oid}.json").write_text(
            json.dumps({"id": oid, "answer": "가 (추천)", "at": "2026-11-13T00:00:00Z"}), encoding="utf-8")

    def splits(self):
        return [json.loads(c[2]) for c in self.herdr_calls() if c[:2] == ["do", "pane.split"]]

    def closes(self):
        return [json.loads(c[2]) for c in self.herdr_calls() if c[:2] == ["do", "pane.close"]]

    def removed(self):
        return [c[1] for c in self.hc_calls() if c[:1] == ["rm"]]

    def record(self, oid):
        path = self.qdir / f"{oid}.view.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def wait_for(self, check, limit=20.0):
        deadline = time.monotonic() + limit
        while True:
            got = check()
            if got:
                return got
            self.assertLess(time.monotonic(), deadline, "기다린 것이 오지 않았다")
            time.sleep(0.1)

    def view_bg(self, oid, terminal=MAIN):
        return self.hteam_bg("question-view", oid, as_="main", terminal=terminal)


class QuestionViewTest(QuestionCase):
    def test_opens_the_pager_next_to_main_and_cleans_up_when_it_ends(self):
        oid = self.question()
        proc = self.view_bg(oid)
        rec = self.wait_for(lambda: self.record(oid))
        [split] = self.splits()
        self.assertEqual((split["direction"], split["pane"]), ("right", f"p{MAIN}"))
        self.assertEqual(split["argv"][2:], ["--root", str(self.p.root), "question-pager", oid])
        self.assertEqual((rec["main"], rec["pid"]), (MAIN, proc.pid))
        self.assertEqual(rec["pane"], f"p{rec['terminal']}")
        time.sleep(1.0)
        self.assertIsNone(proc.poll())  # 보기 터미널이 끝나기를 기다린다
        self.update_terminal(rec["terminal"], state="finished")
        out, err = proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, 0, err)
        self.assertEqual(json.loads(out)["view"], "closed")
        self.assertIsNone(self.record(oid))
        self.assertIn(rec["terminal"], self.removed())

    def test_answered_missing_file_busy_and_outside_herdr_do_not_open(self):
        answered = self.question()
        self.write_answer(answered)
        missing = self.question()
        (self.qdir / f"{missing}.md").unlink()
        busy = self.question()
        for oid, want, env in ((answered, "answered", None), (missing, "no_file", None),
                               (self.question(), "no_main", {"HC_TERMINAL_ID": ""})):
            with self.subTest(want=want):
                code, out = self.hteam("question-view", oid, as_="main", env=env)
                self.assertEqual((code, out["view"]), (0, want), out)
        with open(self.qdir / f"{busy}.lock", "w") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            code, out = self.hteam("question-view", busy, as_="main")
        self.assertEqual((code, out["view"]), (0, "busy"), out)
        self.assertEqual(self.splits(), [])

    def test_live_view_of_the_same_main_is_not_opened_again(self):
        oid = self.question()
        self.view_bg(oid)
        self.wait_for(lambda: self.record(oid))
        code, out = self.hteam("question-view", oid, as_="main")
        self.assertEqual((code, out["view"]), (0, "exists"), out)
        self.assertEqual(len(self.splits()), 1)

    def test_live_view_of_another_main_moves_next_to_the_current_main(self):
        oid = self.question()
        first = self.view_bg(oid)
        old = self.wait_for(lambda: self.record(oid))
        self.add_terminal("t2", argv=["claude"], labels={"herdr.space": "spA", "herdr.tab": "tbMain2"}, status="idle")
        second = self.view_bg(oid, terminal="t2")
        new = self.wait_for(lambda: (self.record(oid) or {}).get("main") == "t2" and self.record(oid))
        self.assertIn({"pane": old["pane"]}, self.closes())  # 옛 메인 옆 보기를 닫았다
        self.assertEqual(self.splits()[-1]["pane"], "pt2")
        first.communicate(timeout=30)  # 옛 보기 명령은 자기 터미널이 끝나 정리하고 끝난다
        self.assertEqual(self.record(oid)["terminal"], new["terminal"])  # 새 기록은 지우지 않는다
        self.update_terminal(new["terminal"], state="finished")
        second.communicate(timeout=30)
        self.assertIsNone(self.record(oid))

    def test_start_sweeps_views_of_closed_questions_and_gone_terminals(self):
        answered = self.question()
        self.add_terminal("t50", argv=["python3"], labels={"herdr.space": "spA", "herdr.tab": "tbMain"})
        (self.qdir / f"{answered}.view.json").write_text(json.dumps(
            {"pane": "pt50", "terminal": "t50", "main": MAIN, "at": "2026-11-13T00:00:00Z", "pid": 1}))
        self.write_answer(answered)
        gone = self.question()
        (self.qdir / f"{gone}.view.json").write_text(json.dumps(
            {"pane": "pt999", "terminal": "t999", "main": MAIN, "at": "2026-11-13T00:00:00Z", "pid": 1}))
        new = self.question()
        self.view_bg(new)
        self.wait_for(lambda: self.record(new))
        self.assertIsNone(self.record(answered))
        self.assertIn({"pane": "pt50"}, self.closes())  # 살아 있던 보기는 닫고 지운다
        self.assertIn("t50", self.removed())
        self.assertIsNone(self.record(gone))  # 없는 터미널(not_found)은 기록만 지운다

    def test_sweep_keeps_the_record_when_the_terminal_cannot_be_read(self):
        kept = self.question()
        self.write_answer(kept)
        (self.qdir / f"{kept}.view.json").write_text(json.dumps(
            {"pane": "pt60", "terminal": "t60", "main": MAIN, "at": "2026-11-13T00:00:00Z", "pid": 1}))
        self.fail_hc("get", "boom")
        code, out = self.hteam("question-view", self.question(), as_="main", env={"HC_TERMINAL_ID": ""})
        self.assertEqual((code, out["view"]), (0, "no_main"), out)
        self.assertIsNotNone(self.record(kept))

    def test_finished_terminal_of_this_question_is_removed_before_reopening(self):
        oid = self.question()
        self.add_terminal("t70", argv=["python3"], state="finished")
        (self.qdir / f"{oid}.view.json").write_text(json.dumps(
            {"pane": "pt70", "terminal": "t70", "main": MAIN, "at": "2026-11-13T00:00:00Z", "pid": 1}))
        self.view_bg(oid)
        new = self.wait_for(lambda: (self.record(oid) or {}).get("terminal") not in (None, "t70") and self.record(oid))
        self.assertIn("t70", self.removed())
        self.assertEqual(new["main"], MAIN)

    def test_close_failure_keeps_the_record_for_the_next_sweep(self):
        kept = self.question()
        self.add_terminal("t80", argv=["python3"], labels={"herdr.space": "spA", "herdr.tab": "tbMain"})
        (self.qdir / f"{kept}.view.json").write_text(json.dumps(
            {"pane": "pt80", "terminal": "t80", "main": MAIN, "at": "2026-11-13T00:00:00Z", "pid": 1}))
        self.write_answer(kept)
        self.fail_hc("herdr-app pane.close", "boom")
        code, out = self.hteam("question-view", self.question(), as_="main", env={"HC_TERMINAL_ID": ""})
        self.assertEqual((code, out["view"]), (0, "no_main"), out)
        self.assertIsNotNone(self.record(kept))

    def test_split_failure_and_missing_pane_only_log(self):
        self.fail_hc("herdr-app pane.split", "boom")
        code, out = self.hteam("question-view", self.question(), as_="main")
        self.assertEqual((code, out["view"]), (0, "split_failed"), out)
        self.add_terminal("t3", argv=["claude"], status="idle")  # Herdr 라벨이 없어 herdr-app ls 에 없다
        code, out = self.hteam("question-view", self.question(), as_="main", terminal="t3")
        self.assertEqual((code, out["view"]), (0, "no_pane"), out)


class QuestionPagerTest(QuestionCase):
    def pager_bg(self, oid):
        """pager 를 띄우고 출력을 파일로 받는다(끝 줄이 나온 것을 보고 상태를 바꾼다, Codex 계획 리뷰 r1)."""
        out = self.tmp / f"pager-{oid}.txt"
        fh = open(out, "w", encoding="utf-8")
        proc = subprocess.Popen([sys.executable, str(BIN), "question-pager", oid], stdin=subprocess.DEVNULL, stdout=fh,
                                stderr=subprocess.STDOUT, env=self._env("main", None, None), cwd=str(self.proj))
        self.addCleanup(self._stop_pager, proc, fh)
        return proc, out

    @staticmethod
    def _stop_pager(proc, fh):
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=30)
        fh.close()

    def wait_ready(self, out):
        self.wait_for(lambda: "(답하면 이 pane 은 닫힌다)" in out.read_text(encoding="utf-8"))

    def test_prints_the_table_and_ends_when_answered(self):
        oid = self.question(ctx="## 표\n| 가 | 1 |")
        proc, out = self.pager_bg(oid)
        self.wait_ready(out)
        self.assertIsNone(proc.poll())
        self.write_answer(oid)
        self.assertEqual(proc.wait(timeout=30), 0)
        text = out.read_text(encoding="utf-8")
        self.assertIn(f"# 질문 보기 {oid}: 시험\n\n## 표\n| 가 | 1 |", text)
        self.assertTrue(text.rstrip().endswith("(답하면 이 pane 은 닫힌다)"), text)
        self.assertNotIn('"ok"', text)  # JSON 봉투를 쓰지 않는다

    def test_ends_when_the_question_is_no_longer_open(self):
        self.write_spec("T-001", "planner", owns="docs/planning/**")
        state.create(self.p, "T-001", "planner")
        with state.edit(self.p, "T-001") as st:
            st.update(status="working", round=1)
        item = outbox.append(self.p, {"type": "ask", "from": "T-001", "round": 1, "render": outbox.validate_render(
            {"question": "물어볼까요?\n예: 확인", "header": "기획", "context": "표", "options": [
                {"label": "가 (추천)", "description": "추천 사유: x"}, {"label": "나", "description": "y"}]}, "질문")})
        oid = item["id"]
        self.qdir.mkdir(parents=True, exist_ok=True)
        (self.qdir / f"{oid}.md").write_text(f"# 질문 보기 {oid}: 기획\n\n표\n", encoding="utf-8")
        proc, out = self.pager_bg(oid)
        self.wait_ready(out)
        self.assertIsNone(proc.poll())
        with state.edit(self.p, "T-001") as st:
            st["status"] = "dropped"
        self.assertEqual(proc.wait(timeout=30), 0)

    def test_missing_file_says_so_and_ends(self):
        oid = self.question()
        (self.qdir / f"{oid}.md").unlink()
        proc, out = self.pager_bg(oid)
        self.assertEqual(proc.wait(timeout=30), 0)
        self.assertIn("질문 보기 파일이 없다", out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
