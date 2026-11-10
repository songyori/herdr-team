"""하네스 검증: 실제 horch 로 띄운 워커를 가짜 에이전트(agent-act)가 프리앰블의 done 명령으로 끝낸다."""
import unittest

from tests.helpers import DRIVE, TeamCase


class HarnessTest(TeamCase):
    def test_agent_act_commits_and_done(self):
        self.init_project()
        self.setup_run()
        code, out = self.horch("worker-start", "--agent", "claude", "--title", "T-001 r1 작업", "--spec", "s",
                               "--cwd", str(self.proj), terminal=DRIVE)
        self.assertEqual(code, 0, out)
        self.assertEqual(out["placement"], "pane")
        code, res = self.act(out["dispatch"], {
            "write": {"src/app.py": "print(1)\n"}, "report": "## r1\n", "report_path": "docs/tasks/T-001/report.md",
            "commit": "[T-001] 작업", "done": {"outcome": "succeeded", "summary": "끝",
                                             "report_path": "docs/tasks/T-001/report.md"}})
        self.assertEqual(code, 0, res)
        self.assertEqual(res["dispatch"]["state"], "settled")
        self.assertEqual(self.git("log", "-1", "--format=%s").strip(), "[T-001] 작업")
        self.assertEqual(self.git("show", "--name-only", "--format=", "HEAD").split(),
                         ["docs/tasks/T-001/report.md", "src/app.py"])
        self.assertEqual(self.dispatch_row(out["dispatch"])["state"], "settled")

    def test_agent_act_review_file_without_commit(self):
        self.init_project()
        self.setup_run()
        _, out = self.horch("worker-start", "--agent", "codex", "--title", "T-001 r1 리뷰 a1", "--spec", "s",
                            "--cwd", str(self.proj), terminal=DRIVE)
        code, res = self.act(out["dispatch"], {"review": {"file": "docs/reviews/T-001/r1-a1.md",
                                                          "verdict": "APPROVE"}})
        self.assertEqual((code, res), (0, {"ok": True, "done": None}))
        text = (self.proj / "docs/reviews/T-001/r1-a1.md").read_text()
        self.assertTrue(text.rstrip().endswith("VERDICT: APPROVE"))
        self.assertEqual(self.dispatch_row(out["dispatch"])["state"], "active")


    def test_outer_git_and_death_points_do_not_leak_into_tests(self):
        import os
        from unittest import mock
        outer = {k: "/outer" for k in ("GIT_INDEX_FILE", "GIT_CONFIG_GLOBAL", "GIT_OBJECT_DIRECTORY",
                                       "HORCH_TEST_DIE_AT", "HTEAM_TEST_DIE_AT", "XDG_CACHE_HOME")}
        with mock.patch.dict(os.environ, outer):
            case = TeamCase("run")
            case.setUp()
            self.addCleanup(case.tearDown)
        self.assertEqual([k for k in outer if k in case.env], [])
        self.assertEqual(case.git("rev-parse", "--is-inside-work-tree").strip(), "true")

    def test_background_hteam_is_reaped(self):
        self.init_project()
        self.setup_run()
        proc = self.hteam_bg("watch", as_="main")  # outbox 가 비어 기다린다
        self._reap(proc)
        self.assertIsNotNone(proc.returncode)  # 죽였고 거뒀다


if __name__ == "__main__":
    unittest.main()
