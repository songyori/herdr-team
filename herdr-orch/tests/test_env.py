"""워커 환경 변수(herdr-orch 설계 14장, 0.3.0): worker-start --env, 스키마 v4 dispatches.env, launch-guard 의 exec 직전 적용,
--task --retry 의 물려받기, worker-list·worker-show 의 env."""
import json
import subprocess
import sys
import unittest

from tests.helpers import BIN, HorchCase
from horch.store import SCHEMA_VERSION, Store

WATCH = "HT_PORT,HTEAM_SLOT,HT_URL,HT_EMPTY"  # 가짜 에이전트가 보고할 이름(FAKE_AGENT_ENV)


class EnvCase(HorchCase):
    """소유자 t100(spA·tbA). 소유자는 working 이라 깨우기 글을 받지 않는다(test_persist 와 같다).
    시험이 보는 이름(WATCH 와 HT_DB)은 바깥 환경에서 지운다: 슬롯 터미널처럼 그 이름이 이미 있는 환경에서 돌려도 결과가 같다
    (HorchCase 는 바깥 환경을 물려받는다)."""

    def setUp(self):
        super().setUp()
        for name in (*WATCH.split(","), "HT_DB"):
            self.env.pop(name, None)
        self.run_id = self.make_owner("t100", "spA", "tbA")
        self.update_terminal("t100", status="working")

    def o(self, *args):
        return self.horch(*args, terminal="t100")

    def start(self, *extra, agent="claude", title="T", spec="do it"):
        return self.o("worker-start", "--agent", agent, "--title", title, "--spec", spec, "--cwd", str(self.tmp), *extra)

    def env_of(self, did):
        """DB 의 dispatches.env(JSON). NULL 이면 None."""
        raw = self.db().execute("SELECT env FROM dispatches WHERE id=?", (did,)).fetchone()["env"]
        return None if raw is None else json.loads(raw)

    def count(self, table="dispatches") -> int:
        return self.db().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def run_guard(self, term, extra=None) -> dict:
        """가짜 hc 가 받은 그 터미널의 argv(launch-guard … -- <에이전트>)를 그 터미널 환경에서 실행한다. 가짜 에이전트 출력."""
        argv = self.hc_state()["terminals"][term]["argv"]
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=30,
                              env=self._env(term, {"FAKE_AGENT_ENV": WATCH, **(extra or {})}))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)

    def shown(self, did) -> dict:
        code, out = self.o("worker-show", "--dispatch", did, "--lines", "0")
        self.assertEqual(code, 0, out)
        return out["worker"]

    def listed(self, did) -> dict:
        code, out = self.o("worker-list")
        self.assertEqual(code, 0, out)
        return {w["id"]: w for w in out["workers"]}[did]


class EnvStartTest(EnvCase):
    def test_env_recorded_and_applied_just_before_exec(self):
        code, out = self.start("--env=HT_PORT=8110", "--env=HTEAM_SLOT=1", "--env=HT_URL=http://x/?a=b", "--env=HT_EMPTY=")
        self.assertEqual(code, 0, out)
        did, term = out["dispatch"], out["terminal"]
        want = {"HT_PORT": "8110", "HTEAM_SLOT": "1", "HT_URL": "http://x/?a=b", "HT_EMPTY": ""}
        self.assertEqual(self.env_of(did), want)  # 첫 = 에서 나눈다. 빈 값도 된다
        self.assertEqual(self.shown(did)["env"], want)
        self.assertEqual(self.listed(did)["env"], want)
        # 프리앰블과 에이전트 인자에는 넣지 않는다(설계 14.3)
        argv = self.hc_state()["terminals"][term]["argv"]
        self.assertFalse([a for a in argv if "HT_PORT" in a or "8110" in a], argv)
        preamble = (self.home / "runs" / self.run_id / "dispatches" / did / "preamble.md").read_text(encoding="utf-8")
        self.assertNotIn("HT_PORT", preamble)
        # 가드가 exec 한 에이전트는 그 값을 본다. 부른 쪽 환경의 같은 이름은 덮어쓴다
        got = self.run_guard(term, {"HT_PORT": "1"})
        self.assertEqual((got["fake"], got["terminal"]), ("claude", term))
        self.assertEqual(got["env"], want)

    def test_no_env_is_null_and_adds_nothing(self):
        # 회귀(0.2.0 과 같다): --env 가 없으면 기록은 NULL, 행의 env 는 null, 에이전트 환경에 더한 것이 없다
        code, out = self.start()
        self.assertEqual(code, 0, out)
        did, term = out["dispatch"], out["terminal"]
        self.assertIsNone(self.env_of(did))
        self.assertIsNone(self.shown(did)["env"])
        self.assertIn("env", self.listed(did))
        self.assertIsNone(self.listed(did)["env"])
        got = self.run_guard(term)
        self.assertEqual(got["env"], {"HT_PORT": None, "HTEAM_SLOT": None, "HT_URL": None, "HT_EMPTY": None})

    def test_codex_gets_env_in_environment_and_policy_set(self):
        # 사용자 shell_environment_policy 가 inherit = "core" 면 Codex 셸이 환경의 값을 보지 못한다(사전 검증 S2).
        # 그래서 Codex 에는 HC_TERMINAL_ID 뒤에 이름 순서로 -c shell_environment_policy.set.<이름>=<JSON 문자열> 도 더한다
        code, out = self.start("--env=HT_PORT=8110", '--env=HT_URL=http://x/"y"', agent="codex")
        self.assertEqual(code, 0, out)
        got = self.run_guard(out["terminal"])
        self.assertEqual(got["fake"], "codex")
        self.assertEqual(got["argv"][:6], ["-c", f'shell_environment_policy.set.HC_TERMINAL_ID="{out["terminal"]}"',
                                           "-c", 'shell_environment_policy.set.HT_PORT="8110"',
                                           "-c", 'shell_environment_policy.set.HT_URL="http://x/\\"y\\""'])
        self.assertEqual((got["env"]["HT_PORT"], got["env"]["HT_URL"]), ("8110", 'http://x/"y"'))

    def test_claude_gets_env_in_environment_only(self):
        # Claude 의 인자는 바뀌지 않는다(값은 환경에만 있다)
        code, out = self.start("--env=HT_PORT=8110")
        self.assertEqual(code, 0, out)
        got = self.run_guard(out["terminal"])
        self.assertFalse([a for a in got["argv"] if "HT_PORT" in a], got["argv"])
        self.assertEqual(got["env"]["HT_PORT"], "8110")

    def test_limits_are_accepted(self):
        items = [f"--env=K{i}=v" for i in range(31)] + ["--env=_LONG=" + "x" * 1024]
        code, out = self.start(*items)
        self.assertEqual(code, 0, out)
        env = self.env_of(out["dispatch"])
        self.assertEqual(len(env), 32)
        self.assertEqual(len(env["_LONG"]), 1024)
        code, out = self.start("--env=lower_case=1")  # 소문자 이름도 된다(herdr-team 은 대문자만 쓴다, 설계 4.2)
        self.assertEqual(code, 0, out)

    def test_bad_env_is_usage_and_creates_nothing(self):
        cases = {
            "no_equals": ["--env=HT_PORT"],
            "empty_name": ["--env==v"],
            "digit_first": ["--env=1A=x"],
            "dash": ["--env=A-B=x"],
            "hc_prefix": ["--env=HC_TERMINAL_ID=t9"],
            "horch_prefix": ["--env=HORCH_POLL=1"],
            "newline": ["--env=A=x\ny"],
            "carriage_return": ["--env=A=x\ry"],
            "too_long": ["--env=A=" + "x" * 1025],
            "too_long_utf8": ["--env=A=" + "가" * 342],  # 342자, 1026바이트
            "duplicate": ["--env=A=1", "--env=A=2"],
            "too_many": [f"--env=K{i}=v" for i in range(33)],
        }
        before = self.count()
        for name, items in cases.items():
            with self.subTest(case=name):
                code, out = self.start(*items)
                self.assertEqual((code, out["error"]["code"]), (2, "usage"), out)
        self.assertEqual(self.count(), before)
        self.assertEqual(self.count("tasks"), 0)
        self.assertFalse([c for c in self.hc_calls() if c[:1] == ["run"]])

    def test_messages(self):
        code, out = self.start("--env=HT_PORT=1", "--env=HT_PORT=2")
        self.assertIn("HT_PORT", out["error"]["message"])
        code, out = self.start("--env=HC_X=1")
        self.assertIn("HC_·HORCH_", out["error"]["message"])
        code, out = self.start(*[f"--env=K{i}=v" for i in range(33)])
        self.assertIn("32", out["error"]["message"])


class EnvRetryTest(EnvCase):
    def test_retry_inherits_last_env_unless_given(self):
        self.fail_hc("run", "spawn_failed")
        code, out = self.start("--env=HT_PORT=8110", "--env=HTEAM_SLOT=1")
        self.assertEqual((code, out["error"]["code"]), (1, "launch_failed"))
        task, d1 = out["task"], out["dispatch"]
        self.assertEqual(self.env_of(d1), {"HT_PORT": "8110", "HTEAM_SLOT": "1"})  # hc run 전에 기록한다
        row = self.listed(d1)
        self.assertEqual(row["attention"], "launch_failed")
        self.assertFalse([a for a in row["next"] if a.startswith("--env")], row["next"])  # 재시도가 물려받는다
        self.clear_hc_fail("run")
        # --env 없는 --retry: 그 Task 의 마지막 Dispatch 값
        code, r2 = self.o("worker-start", "--agent", "claude", "--task", task, "--retry", "--cwd", str(self.tmp))
        self.assertEqual(code, 0, r2)
        self.assertEqual(self.env_of(r2["dispatch"]), {"HT_PORT": "8110", "HTEAM_SLOT": "1"})
        self.assertEqual(self.run_guard(r2["terminal"])["env"]["HT_PORT"], "8110")
        # --env 를 주면 그 값(합치지 않고 바꾼다)
        db = self.db()
        db.execute("UPDATE dispatches SET state='launch_failed' WHERE id=?", (r2["dispatch"],))
        db.commit()
        code, r3 = self.o("worker-start", "--agent", "claude", "--task", task, "--retry", "--cwd", str(self.tmp),
                          "--env=HT_DB=5481")
        self.assertEqual(code, 0, r3)
        self.assertEqual(self.env_of(r3["dispatch"]), {"HT_DB": "5481"})
        # --retry 없는 --task(앞 시도가 abandoned)는 물려받지 않는다(설계 14.1 은 --task --retry 만)
        db.execute("UPDATE dispatches SET state='abandoned' WHERE id=?", (r3["dispatch"],))
        db.commit()
        code, r4 = self.o("worker-start", "--agent", "claude", "--task", task, "--cwd", str(self.tmp))
        self.assertEqual(code, 0, r4)
        self.assertIsNone(self.env_of(r4["dispatch"]))

    def test_retry_of_dispatch_without_env_stays_null(self):
        self.fail_hc("run", "spawn_failed")
        code, out = self.start()
        self.assertEqual(code, 1, out)
        self.clear_hc_fail("run")
        code, r2 = self.o("worker-start", "--agent", "claude", "--task", out["task"], "--retry", "--cwd", str(self.tmp))
        self.assertEqual(code, 0, r2)
        self.assertIsNone(self.env_of(r2["dispatch"]))


class EnvPersistTest(EnvCase):
    def test_keep_open_env_and_terminal(self):
        code, out = self.o("worker-start", "--keep-open", "--agent", "claude", "--title", "T1", "--spec", "첫 번째",
                           "--cwd", str(self.tmp), "--env=HT_PORT=8110")
        self.assertEqual(code, 0, out)
        d1, term = out["dispatch"], out["terminal"]
        self.assertEqual(self.env_of(d1), {"HT_PORT": "8110"})  # 고정 터미널의 첫 환경
        code, res = self.horch("done", "--dispatch", d1, "--outcome", "succeeded", "--summary", "끝", terminal=term)
        self.assertEqual(code, 0, res)
        self.update_terminal(term, status="done", turn=3)
        before = self.count()
        # 살아 있는 세션의 환경은 바꾸지 못한다: --terminal 과 --env 는 같이 쓸 수 없다
        code, res = self.o("worker-start", "--terminal", term, "--title", "T2", "--spec", "두 번째", "--env=HT_PORT=1")
        self.assertEqual((code, res["error"]["code"]), (2, "usage"), res)
        self.assertIn("--env", res["error"]["message"])
        self.assertEqual(self.count(), before)
        # 같은 터미널에 넣은 Dispatch 는 그 세션의 환경(앞 고정 Dispatch 의 값)을 기록한다
        code, res = self.o("worker-start", "--terminal", term, "--title", "T2", "--spec", "두 번째")
        self.assertEqual(code, 0, res)
        self.assertEqual(self.env_of(res["dispatch"]), {"HT_PORT": "8110"})
        self.assertEqual(self.shown(res["dispatch"])["env"], {"HT_PORT": "8110"})


class SchemaV4Test(HorchCase):
    def open(self) -> Store:
        s = Store(self.home)
        self.addCleanup(s.close)
        return s

    def test_new_db_is_v4(self):
        s = self.open()
        self.assertEqual(SCHEMA_VERSION, 4)
        self.assertEqual(s.one("SELECT value FROM meta WHERE key='schema_version'")["value"], "4")
        self.assertIn("env", {r["name"] for r in s.all("PRAGMA table_info(dispatches)")})

    def test_migrates_v3_to_v4(self):
        s = self.open()
        s.run("INSERT INTO runs(id, objective, created_at, updated_at) VALUES ('run-1','o','t','t')")
        s.run("INSERT INTO tasks(id, run_id, title, spec, created_at) VALUES ('task-1','run-1','T','S','t')")
        s.run("INSERT INTO dispatches(id, task_id, run_id, attempt, agent, cwd, terminal, state, created_at) "
              "VALUES ('dsp-1','task-1','run-1',1,'claude','/x','t9','active','t')")
        s.run("ALTER TABLE dispatches DROP COLUMN env")
        s.run("UPDATE meta SET value='3' WHERE key='schema_version'")
        s.close()
        s2 = self.open()
        self.assertEqual(s2.one("SELECT value FROM meta WHERE key='schema_version'")["value"], "4")
        self.assertIsNone(s2.one("SELECT env FROM dispatches WHERE id='dsp-1'")["env"])  # 기존 행은 NULL


class EnvSkillTest(HorchCase):
    def test_skill_mentions_env(self):
        proc = subprocess.run([sys.executable, str(BIN), "--home", str(self.home), "skill"],
                              capture_output=True, text=True, env=self.env, timeout=30)
        self.assertEqual(proc.returncode, 0)
        for needle in ("`--env KEY=VALUE`", "32개까지", "`hc run` 터미널은 부른 셸의 환경을 물려받지 않는다",
                       "비밀값을 넘기지 않는다", "`--task --retry` 에 주지 않으면 그 Task 의 마지막 값을 쓰고",
                       "`--terminal` 과는 같이 쓸 수 없다"):
            self.assertIn(needle, proc.stdout)


if __name__ == "__main__":
    unittest.main()
