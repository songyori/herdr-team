"""Redmine 연동(설계 8.12, 7단계): 사건 큐, 닫는 때, 전송 자식 `hteam redmine-sync`, 키 읽기·가리기, status·doctor.

Redmine 은 이 프로세스 안의 가짜 HTTP 서버다(요청을 남기고 이슈마다 응답 코드를 정한다). 관제는 이 프로세스 안에서 만든다
(make_drive). 리뷰·전송 자식은 실제 hteam 하위 프로세스다(설계 8.8). 큐 항목의 꼴은 계획 헤더의 "기록·필드에 더하는 것" 이다."""
import fcntl
import json
import re
import socket
import threading
import time
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from tests.helpers import BASE_CONFIG, WS_CONFIG, TeamCase
from tests.test_drive_flows import FlowCase
from hteam.paths import Project

KEY = "rk-SECRET-7f3a9c1e5b"  # 시험용 가짜 키. 큐·로그·outbox·상태·docs 어디에도 나오면 안 된다
KEY_ENV = "HT_REDMINE_KEY"
STATUS = "status = { start = 2, done = 3, changes = 4, closed = 5 }"
LOCAL_ISO = r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d"
PROXY_ENV = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")


def redmine_table(url: str, env_file: str | None = None) -> str:
    lines = ["", "[redmine]", f'url = "{url}"', f'key_env = "{KEY_ENV}"']
    if env_file:
        lines.append(f'env_file = "{env_file}"')
    lines.append(STATUS)
    return "\n".join(lines) + "\n"


def utc(offset_s: float = 0) -> str:
    """지금부터 offset_s 초 뒤(음수면 앞) UTC 시각(util.now 꼴)."""
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_s)).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(text: str) -> float:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


class FakeRedmine:
    """PUT /issues/<N>.json·GET /users/current.json 을 받는 가짜 Redmine. codes[이슈] 는 그 이슈에 차례로 낼 응답 코드
    (다 쓰면 204). 요청마다 {method, path, key, body, type} 를 남긴다. 4xx·5xx 본문에는 받은 키를 넣는다(가리기 시험).
    pads[이슈] 는 그 본문에서 키 앞에 둘 글자 수(200자 자르기 경계 시험). lock_path 를 정하면 PUT 을 받을 때마다 그 파일의
    flock 을 비차단으로 시도해, 보내는 쪽이 쥐고 있었는지를 lock_held 에 남긴다(시간에 기대지 않는 전송자 하나 시험)."""

    def __init__(self):
        self.requests: list[dict] = []
        self.codes: dict[str, list[int]] = {}
        self.pads: dict[str, int] = {}
        self.lock_path: Path | None = None
        self.lock_held: list[bool] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _reply(self, code: int, body: bytes = b"") -> None:
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                key = self.headers.get("X-Redmine-API-Key")
                outer.requests.append({"method": "GET", "path": self.path, "key": key, "body": None, "type": None})
                ok = key == KEY and self.path == "/users/current.json"
                self._reply(200 if ok else 401, b'{"user": {"id": 1}}' if ok else b'{"errors": ["no"]}')

            def do_PUT(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                key = self.headers.get("X-Redmine-API-Key")
                outer.requests.append({"method": "PUT", "path": self.path, "key": key,
                                       "body": json.loads(raw or b"null"), "type": self.headers.get("Content-Type")})
                if outer.lock_path is not None:  # 보내는 프로세스가 sync.lock 을 쥔 채 보내는지
                    with open(outer.lock_path, "a") as fh:
                        try:
                            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        except BlockingIOError:
                            outer.lock_held.append(True)
                        else:
                            fcntl.flock(fh, fcntl.LOCK_UN)
                            outer.lock_held.append(False)
                issue = self.path.removeprefix("/issues/").removesuffix(".json")
                todo = outer.codes.get(issue) or []
                code = todo.pop(0) if todo else 204
                text = "x" * outer.pads.get(issue, 0) + f"bad key {key}"
                self._reply(code, b"" if code < 300 else json.dumps({"errors": [text]}).encode())

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=10)

    def puts(self) -> list[dict]:
        return [r for r in self.requests if r["method"] == "PUT"]


class RedmineMixin:
    """가짜 서버와 큐 폴더 도구. 가짜 서버는 127.0.0.1 이라 프록시를 거치지 않게 한다(no_proxy)."""

    def start_server(self) -> FakeRedmine:
        self.server = FakeRedmine()
        self.addCleanup(self.server.close)
        for name in PROXY_ENV:
            self.env.pop(name, None)
        self.env["no_proxy"] = self.env["NO_PROXY"] = "127.0.0.1,localhost"
        return self.server

    @property
    def redmine_dir(self) -> Path:
        return self.state_dir / "redmine"

    def _items(self, sub: str) -> list[dict]:
        folder = self.redmine_dir / sub
        return [json.loads(f.read_text(encoding="utf-8")) for f in sorted(folder.glob("*.json"))] if folder.is_dir() \
            else []

    def queued(self) -> list[dict]:
        return self._items("queue")

    def failed(self) -> list[dict]:
        return self._items("failed")

    def events(self) -> list[tuple]:
        return [(i["event"], i["issue"], i["status_id"], i["notes"]) for i in self.queued()]

    def put_item(self, seq: int, issue: str, event: str = "start", status_id: int | None = 2, notes: str = "노트",
                 **extra) -> dict:
        folder = self.redmine_dir / "queue"
        folder.mkdir(parents=True, exist_ok=True)
        item = {"seq": seq, "issue": issue, "task": "T-001", "event": event, "status_id": status_id, "notes": notes,
                "at": utc(), **extra}
        (folder / f"{seq:06d}.json").write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
        return item

    def leaks(self, secret: str = KEY) -> list[str]:
        """secret(기본은 키 값)이 든 파일(상태 폴더 전체와 docs). 비어야 한다(설계 8.12: 큐·로그·outbox·프롬프트에 쓰지 않는다)."""
        found = []
        for root in (self.state_dir, self.proj / "docs"):
            if not root.is_dir():
                continue
            for path in root.rglob("*"):
                if path.is_file() and secret.encode() in path.read_bytes():
                    found.append(str(path.relative_to(self.proj)))
        return found

    def log_lines(self) -> list[str]:
        path = self.state_dir / "drive" / "drive.log"
        return path.read_text(encoding="utf-8").splitlines() if path.is_file() else []


class SyncTest(RedmineMixin, TeamCase):
    """전송 자식 `hteam redmine-sync`(설계 8.12 의 전송): 큐 항목은 시험이 직접 쓴다."""

    def setUp(self):
        super().setUp()
        self.start_server()
        self.init_project(BASE_CONFIG + redmine_table(self.server.url))
        self.setup_run()
        self.env[KEY_ENV] = KEY

    def sync(self) -> tuple[int, dict]:
        return self.hteam("redmine-sync")

    def status(self) -> dict:
        code, out = self.hteam("status", as_="main")
        self.assertEqual(code, 0, out)
        return out

    def test_sends_in_order_and_deletes_sent_items(self):
        self.put_item(1, "5712", "start", 2, "시작 노트")
        self.put_item(2, "5712", "approve", None, "승인 노트")  # 상태를 바꾸지 않는 사건은 notes 만 보낸다
        self.put_item(3, "77", "done", 3, "끝 노트")
        code, out = self.sync()
        self.assertEqual(code, 0, out)
        self.assertEqual([e["seq"] for e in out["sent"]], [1, 2, 3])
        self.assertEqual((out["failed"], out["retry"], out["pending"]), ([], [], 0))
        puts = self.server.puts()
        self.assertEqual([r["path"] for r in puts], ["/issues/5712.json", "/issues/5712.json", "/issues/77.json"])
        self.assertEqual([r["body"] for r in puts], [{"issue": {"status_id": 2, "notes": "시작 노트"}},
                                                     {"issue": {"notes": "승인 노트"}},
                                                     {"issue": {"status_id": 3, "notes": "끝 노트"}}])
        self.assertEqual({r["key"] for r in puts}, {KEY})
        self.assertTrue(all(r["type"].startswith("application/json") for r in puts), puts)
        self.assertEqual(self.queued(), [])
        self.assertEqual(self.status()["redmine"], {"enabled": True, "pending": 0, "failed": 0, "last_error": None})
        self.assertEqual(self.leaks(), [])

    def test_client_error_moves_item_to_failed_with_key_masked(self):
        self.server.codes["998"] = [422]
        self.put_item(1, "998", "start", 2, "a")
        self.put_item(2, "998", "done", 3, "b")
        code, out = self.sync()
        self.assertEqual(code, 0, out)
        self.assertEqual([(e["seq"], e["issue"], e["event"], e["status"]) for e in out["failed"]],
                         [(1, "998", "start", 422)])
        self.assertEqual([e["seq"] for e in out["sent"]], [2])  # 앞 항목이 failed 로 빠져 남지 않았다
        [bad] = self.failed()
        self.assertEqual((bad["seq"], bad["issue"], bad["event"], bad["notes"]), (1, "998", "start", "a"))
        self.assertIn("422", bad["error"])
        self.assertIn("***", bad["error"])  # 응답 본문의 키 값을 가렸다
        self.assertNotIn(KEY, json.dumps(out, ensure_ascii=False))
        self.assertEqual(self.queued(), [])
        st = self.status()["redmine"]
        self.assertEqual((st["pending"], st["failed"]), (0, 1))
        self.assertIn("422", st["last_error"])
        self.assertEqual(self.leaks(), [])

    def test_server_error_keeps_item_and_holds_later_items_of_that_issue(self):
        self.server.codes["1"] = [503]
        self.put_item(1, "1", "start", 2, "a")
        self.put_item(2, "1", "done", 3, "b")
        self.put_item(3, "2", "start", 2, "c")
        before = time.time()
        code, out = self.sync()
        self.assertEqual(code, 0, out)
        self.assertEqual([(e["seq"], e["issue"], e["status"]) for e in out["retry"]], [(1, "1", 503)])
        self.assertEqual([e["seq"] for e in out["sent"]], [3])  # 다른 이슈는 막지 않는다
        self.assertEqual(out["pending"], 2)
        self.assertEqual([r["path"] for r in self.server.puts()], ["/issues/1.json", "/issues/2.json"])
        first, second = self.queued()
        self.assertEqual((first["seq"], first["tries"]), (1, 1))
        self.assertAlmostEqual(parse_utc(first["next_at"]) - before, 60, delta=5)
        self.assertIn("503", first["last_error"])
        self.assertEqual(second["seq"], 2)
        self.assertNotIn("tries", second)  # 같은 이슈의 뒤 항목은 보내지 않았다
        code, out = self.sync()  # 아직 다시 보낼 때가 아니다
        self.assertEqual(code, 0, out)
        self.assertEqual((out["sent"], out["retry"], out["failed"]), ([], [], []))
        self.assertEqual(len(self.server.puts()), 2)
        self.assertIn("503", self.status()["redmine"]["last_error"])

    def test_retry_intervals_grow_to_ten_minutes(self):
        for tries, wait in ((0, 60), (1, 120), (2, 300), (3, 600), (7, 600)):
            with self.subTest(tries=tries):
                for f in (self.redmine_dir / "queue").glob("*.json"):
                    f.unlink()
                self.server.codes["1"] = [503]
                self.put_item(1, "1", tries=tries, next_at=utc(-1), last_error="앞 실패")
                before = time.time()
                code, out = self.sync()
                self.assertEqual(code, 0, out)
                [item] = self.queued()
                self.assertEqual(item["tries"], tries + 1)
                self.assertAlmostEqual(parse_utc(item["next_at"]) - before, wait, delta=5)

    def test_gives_up_after_24_hours(self):
        self.server.codes["1"] = [503]
        self.put_item(1, "1", at=utc(-25 * 3600), tries=5, next_at=utc(-1), last_error="앞 실패")
        code, out = self.sync()
        self.assertEqual(code, 0, out)
        self.assertEqual([(e["seq"], e["status"]) for e in out["failed"]], [(1, 503)])
        self.assertEqual(self.queued(), [])
        [bad] = self.failed()
        self.assertIn("24시간", bad["error"])

    def test_connection_failure_is_retried(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]  # 닫은 포트: 연결이 거부된다
        (self.team / "config.toml").write_text(BASE_CONFIG + redmine_table(f"http://127.0.0.1:{port}"),
                                               encoding="utf-8")
        self.put_item(1, "1")
        code, out = self.sync()
        self.assertEqual(code, 0, out)
        self.assertEqual([(e["seq"], e["status"]) for e in out["retry"]], [(1, "연결 실패")])
        [item] = self.queued()
        self.assertEqual(item["tries"], 1)
        self.assertIn("연결 실패", item["last_error"])

    def test_missing_key_sends_nothing(self):
        del self.env[KEY_ENV]
        self.put_item(1, "1")
        code, out = self.sync()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.server.requests, [])
        self.assertEqual([(e["seq"], e["status"]) for e in out["retry"]], [(1, "키 없음")])
        [item] = self.queued()
        self.assertEqual(item["tries"], 1)
        self.assertIn(KEY_ENV, self.status()["redmine"]["last_error"])

    def test_env_file_is_read_and_one_quote_layer_stripped(self):
        (self.team / "config.toml").write_text(BASE_CONFIG + redmine_table(self.server.url, ".env"), encoding="utf-8")
        self.env[KEY_ENV] = "env-value-not-used"  # env_file 이 있으면 그 파일에서 읽는다
        cases = ((f'{KEY_ENV}="{KEY}"', KEY), (f"{KEY_ENV}='{KEY}'", KEY), (f"{KEY_ENV}={KEY}", KEY),
                 (f"{KEY_ENV}=\"'{KEY}'\"", f"'{KEY}'"))
        for line, want in cases:
            with self.subTest(line=line):
                (self.proj / ".env").write_text(f"# 주석\nOTHER=1\n{line}\n", encoding="utf-8")
                self.server.requests.clear()
                self.put_item(1, "1")
                code, out = self.sync()
                self.assertEqual(code, 0, out)
                self.assertEqual([r["key"] for r in self.server.puts()], [want])

    def test_unreadable_item_moves_to_failed(self):
        folder = self.redmine_dir / "queue"
        folder.mkdir(parents=True)
        (folder / "000001.json").write_text("{깨짐", encoding="utf-8")
        self.put_item(2, "1")
        code, out = self.sync()
        self.assertEqual(code, 0, out)
        self.assertEqual([e["seq"] for e in out["sent"]], [2])
        self.assertEqual([(e["seq"], e["status"]) for e in out["failed"]], [(1, "읽기 실패")])
        self.assertTrue((self.redmine_dir / "failed" / "000001.json").is_file())
        self.assertFalse((folder / "000001.json").exists())

    def test_one_sender_at_a_time(self):
        # 관제가 다시 떠 앞 관제의 전송 자식이 살아 있어도 둘이 같은 큐를 돌지 않는다(sync.lock, Codex 계획 리뷰 r1).
        # 앞 전송자 대신 시험이 sync.lock 을 쥔다. 실제 HTTP 제한 시간과 경쟁하지 않는다(Codex 계획 리뷰 r2)
        self.put_item(1, "5712", "start", 2, "a")
        self.put_item(2, "5712", "done", 3, "b")
        self.put_item(3, "77", "start", 2, "c")
        lock = self.redmine_dir / "sync.lock"
        with open(lock, "a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            code, out = self.sync()
            self.assertEqual(code, 0, out)
            self.assertEqual((out.get("busy"), out["sent"], out["failed"], out["retry"], out["pending"]),
                             (True, [], [], [], 3))
            self.assertEqual(out["message"], "다른 hteam redmine-sync 가 보내는 중이라 보내지 않았다(state/redmine/sync.lock)")
            self.assertEqual(self.server.puts(), [])  # 잠금을 쥔 쪽이 있으면 아무것도 보내지 않는다
            self.assertEqual(len(self.queued()), 3)
        self.server.lock_path = lock  # 보내는 동안 내내 sync.lock 을 쥐는지 PUT 마다 본다
        code, out = self.sync()
        self.assertEqual((code, out.get("busy")), (0, False), out)
        self.assertEqual(self.server.lock_held, [True, True, True])
        self.assertEqual([e["seq"] for e in out["sent"]], [1, 2, 3])
        self.assertEqual([(r["path"], r["body"]["issue"]["notes"]) for r in self.server.puts()],
                         [("/issues/5712.json", "a"), ("/issues/5712.json", "b"), ("/issues/77.json", "c")])  # 큐 순번 차례
        self.assertEqual(self.queued(), [])

    def test_drive_only_and_needs_redmine_table(self):
        code, out = self.hteam("redmine-sync", as_="main")
        self.assertEqual((code, out["error"]["code"]), (5, "drive_only"), out)
        (self.team / "config.toml").write_text(BASE_CONFIG, encoding="utf-8")
        code, out = self.hteam("redmine-sync")
        self.assertEqual((code, out["error"]["code"]), (2, "redmine_off"), out)


class EventsCase(RedmineMixin, TeamCase):
    """관제 사건(설계 8.12 의 표): 관제를 이 프로세스 안에서 만들고 워커·리뷰어는 agent-act 가 한다."""

    config = BASE_CONFIG

    def setUp(self):
        super().setUp()
        self.start_server()
        self.env[KEY_ENV] = KEY
        self.init_project(self.config + redmine_table(self.server.url))
        self.setup_run()
        self.p = Project(self.proj)
        self._patcher = None
        self.rearm()

    def tearDown(self):
        for job in list(self.d.jobs.values()):  # 남은 자식을 끝낸 뒤 시험 폴더를 지운다
            if job["proc"].poll() is None:
                job["proc"].kill()
            job["proc"].wait(timeout=30)
        super().tearDown()

    def rearm(self) -> None:
        """self.env 를 바꾼 뒤 관제 환경을 다시 건다(관제가 띄우는 자식은 이 환경을 물려받는다)."""
        if self._patcher is not None:
            self._patcher.stop()
        else:
            self.addCleanup(lambda: self._patcher.stop())
        self._patcher = self.in_drive()
        self._patcher.start()
        self.d = self.make_drive()

    def start(self, tid: str = "T-001") -> dict:
        code, out = self.hteam("start", tid)
        self.assertEqual(code, 0, out)
        return out

    def done_msg(self, did: str, outcome: str = "succeeded", summary: str = "끝") -> dict:
        row = self.dispatch_row(did)
        return self.message("worker_done", did, {"dispatch": did, "task": row["task_id"], "outcome": outcome,
                                                 "summary": summary, "report_path": row["report_path"],
                                                 "files_modified": []})

    def wait_jobs(self, limit: float = 60.0) -> None:
        deadline = time.monotonic() + limit
        while True:
            self.d.reap_jobs()
            if not self.d.jobs:
                return
            if time.monotonic() > deadline:
                self.fail(f"자식이 끝나지 않았다: {sorted(self.d.jobs)}")
            time.sleep(0.05)

    def worked(self, tid: str = "T-001", summary: str = "끝", **kw) -> None:
        did = self.work_dispatch(tid)
        code, out = self.act_work(tid, **kw)
        self.assertEqual(code, 0, out)
        self.d.handle(self.done_msg(did, summary=summary))
        self.wait_jobs()

    def reviewed(self, tid: str = "T-001", verdict: str | None = "APPROVE", **kw) -> None:
        did = self.attempt(tid)["dispatch"]
        code, out = self.act_review(tid, verdict, **kw)
        self.assertEqual(code, 0, out)
        self.d.handle(self.done_msg(did))
        self.wait_jobs()


class EventTest(EventsCase):
    def test_round_events_from_start_to_close(self):
        self.write_spec("T-001", front={"issue": "#5712"})  # 앞의 # 는 뗀다(설계 5.1)
        self.start()
        self.worked(summary="가" * 400)
        long = "r1-F1 [P1] src/app.py:1 — " + "길다" * 120 + "."
        lines = [long] + [f"r1-F{i} [P1] src/app.py:{i} — 틀림 {i}." for i in range(2, 7)]
        self.reviewed(verdict="REQUEST_CHANGES",
                      text="## 지적 사항\n" + "".join(f"- {line}\n" for line in lines) + "## 후속\n- r1-F9 [P2] 이름.\n")
        self.worked(report="## r2\n- 아티팩트: https://claude.ai/artifact/abc-9\n")
        self.reviewed(verdict="APPROVE")
        self.assertEqual(self.task_state("T-001")["status"], "done")
        shown = [line.rstrip(".")[:200] for line in lines[:5]]  # 줄 끝 마침표 하나를 떼고 200자, 최대 5줄
        self.assertEqual(self.events(), [
            ("start", "5712", 2, "herdr-team: T-001 r1 작업을 시작했다(개발, Claude)."),
            ("done", "5712", 3, "T-001 r1 작업을 마쳤다. 요약: " + "가" * 300 + ". 보고서: docs/tasks/T-001/report.md"),
            ("changes", "5712", 4, "T-001 r1 리뷰: 수정 요청(Codex). 막는 지적: " + " / ".join(shown)
             + ". 리뷰: docs/reviews/T-001/r1.md"),
            ("start", "5712", 2, "herdr-team: T-001 r2 작업을 시작했다(개발, Claude)."),
            ("done", "5712", 3, "T-001 r2 작업을 마쳤다. 요약: 끝. 보고서: docs/tasks/T-001/report.md"),
            ("approve", "5712", None, "T-001 r2 리뷰: 승인(Codex). 아티팩트: https://claude.ai/artifact/abc-9"),
            ("closed", "5712", 5, "T-001 가 끝나 종료한다."),
        ])
        self.assertEqual([i["seq"] for i in self.queued()], list(range(1, 8)))
        self.assertTrue(all(i["task"] == "T-001" and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", i["at"])
                            for i in self.queued()), self.queued())
        self.assertEqual(self.server.requests, [])  # 관제는 큐에 쓰기만 한다
        self.assertEqual(self.leaks(), [])
        self.d.redmine_step()  # 전송 자식이 순서대로 보낸다
        self.wait_jobs()
        puts = self.server.puts()
        self.assertEqual([r["body"]["issue"].get("status_id") for r in puts], [2, 3, 4, 2, 3, None, 5])
        self.assertEqual({r["path"] for r in puts}, {"/issues/5712.json"})
        self.assertEqual(self.queued(), [])
        self.assertEqual(self.leaks(), [])

    def test_hteam_rejection_is_changes_from_hteam(self):
        self.use_gate()
        self.gate_modes("fail", "fail")
        self.rearm()
        self.write_spec("T-001", front={"issue": "5712"})
        self.start()
        self.worked()
        events = self.events()
        self.assertEqual([e[0] for e in events], ["start", "done", "changes", "start"])
        self.assertEqual(events[2], ("changes", "5712", 4, "T-001 r1 리뷰: 수정 요청(hteam). 막는 지적: hteam 테스트 관문: "
                                                           "quick 이 통과하지 못했다. 리뷰: docs/reviews/T-001/r1.md"))
        self.assertEqual(events[3][3], "herdr-team: T-001 r2 작업을 시작했다(개발, Claude).")

    def test_drop_is_a_note_only(self):
        self.write_spec("T-001", front={"issue": "5712"})
        self.start()
        code, out = self.hteam("drop", "T-001", "--force")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.events(), [("start", "5712", 2, "herdr-team: T-001 r1 작업을 시작했다(개발, Claude)."),
                                         ("drop", "5712", None, "T-001 를 버렸다.")])

    def test_task_without_issue_writes_nothing(self):
        self.write_spec("T-001")
        self.start()
        self.worked()
        self.reviewed()
        self.assertEqual(self.task_state("T-001")["status"], "done")
        self.assertEqual(self.queued(), [])
        self.d.redmine_step()
        self.assertEqual(self.d.jobs, {})


class MergeEventTest(EventsCase):
    """작업 공간 태스크의 병합 노트(설계 8.12 표의 병합, 5.10.6)."""

    config = WS_CONFIG

    def test_merge_note_between_approve_and_close(self):
        self.write_spec("T-001", front={"issue": "5712"})
        code, out = self.hteam("start", "T-001")
        self.assertEqual((code, out.get("status"), out.get("reason")), (0, "waiting", "slot_setup"), out)
        code, out = self.hteam("slot", "prepare", "T-001")
        self.assertEqual(code, 0, out)
        self.start()  # 준비가 끝난 슬롯으로 띄운다
        self.worked()
        self.reviewed()
        st = self.task_state("T-001")
        self.assertEqual(st["status"], "done")
        sha = st["workspace"]["merge"]
        events = self.events()
        self.assertEqual([e[0] for e in events], ["start", "done", "approve", "merged", "closed"])
        self.assertEqual(events[3], ("merged", "5712", None, f"기준 브랜치 main 에 병합했다({sha[:7]})."))


class CloseTest(RedmineMixin, FlowCase):
    """닫는 때(설계 8.12, 사용자 결정): 관제의 accept 뒤(after_accept, res status done)에 정한다. 상태는 시험이 직접 쓴다."""

    config = BASE_CONFIG + redmine_table("http://127.0.0.1:9")

    def done(self, tid: str) -> None:
        self.d.after_accept(tid, {"status": "done", "warnings": []})

    def closes(self) -> list[tuple]:
        return [(i["issue"], i["task"], i["notes"]) for i in self.queued() if i["event"] == "closed"]

    def bundle(self, *, tester_status: str = "done") -> None:
        self.task("T-001", front={"issue": "101"})
        self.task("T-002", front={"issue": "102"})
        self.task("T-003", "tester", tester_status, depends="T-001, T-002", front={"plan_key": "calc-test", "issue": "103"},
                  owns=["tests/calc-test/**", "docs/qa/calc-test.md"])

    def test_tester_done_closes_bundle_issues(self):
        self.bundle(tester_status="working")
        self.review("T-003", 1)
        self.done("T-001")
        self.done("T-002")
        self.assertEqual(self.closes(), [])  # 묶음 tester 가 끝날 때 닫는다
        self.set_state("T-003", status="done")
        self.done("T-003")
        note = "묶음 calc-test 테스트(T-003)가 끝나 종료한다."
        self.assertEqual(self.closes(), [("101", "T-003", note), ("102", "T-003", note), ("103", "T-003", note)])
        self.assertEqual({i["status_id"] for i in self.queued() if i["event"] == "closed"}, {5})

    def test_same_issue_waits_for_the_unfinished_task(self):
        self.task("T-001", front={"issue": "7"})
        self.task("T-002", status="working", front={"issue": "7"})
        self.task("T-003", status="dropped", front={"issue": "7"})  # 버린 태스크는 막지 않는다
        self.done("T-001")
        self.assertEqual(self.closes(), [])
        self.set_state("T-002", status="done")
        self.done("T-002")
        self.assertEqual(self.closes(), [("7", "T-002", "T-002 가 끝나 종료한다.")])

    def test_dropped_tester_leaves_bundle_issue_open(self):
        self.task("T-001", front={"issue": "9"})
        self.task("T-002", "tester", "dropped", depends="T-001", front={"plan_key": "k", "issue": "10"},
                  owns=["tests/k/**", "docs/qa/k.md"])
        self.done("T-001")
        self.assertEqual(self.closes(), [])  # 묶음 tester 가 drop 되면 사람이 닫는다

    def test_regression_task_inherits_issue_and_holds_the_close(self):
        self.bundle()
        item = "r1-F4 [P1] tests/calc-test/test_flow.py::test_add 가 실패한다 — 원인은 T-001 의 add 부호다(T-003 묶음)"
        self.review("T-003", 1, regressions=f"- {item}")
        self.done("T-003")
        self.assertEqual(self.ids(), ["T-001", "T-002", "T-003", "T-004"])
        self.assertEqual(self.spec("T-004").issue, "101")  # 회귀 수정은 원인 태스크의 issue 를 물려받는다(설계 5.1)
        note = "묶음 calc-test 테스트(T-003)가 끝나 종료한다."
        self.assertEqual(self.closes(), [("102", "T-003", note), ("103", "T-003", note)])  # 101 은 회귀 수정이 끝날 때
        self.set_state("T-004", status="done")
        self.done("T-004")
        self.assertEqual(self.closes()[-1], ("101", "T-004", "T-004 가 끝나 종료한다."))

    def test_cleanup_task_inherits_issue_only_from_one_source(self):
        self.bundle()
        self.review("T-001", 1, followups="- r1-F2 [P2] src/t-001/a.py:3 — 중복.")
        self.review("T-003", 1)
        self.done("T-003")
        [cleanup] = [t for t in self.ids() if t not in ("T-001", "T-002", "T-003")]
        self.assertEqual((self.spec(cleanup).title, self.spec(cleanup).issue), ("묶음 정리: calc-test", "101"))

    def test_cleanup_task_from_two_sources_has_no_issue(self):
        self.bundle()
        self.review("T-001", 1, followups="- r1-F2 [P2] src/t-001/a.py:3 — 중복.")
        self.review("T-002", 1, followups="- r1-F1 [P3] src/t-002/b.py:1 — 이름이 길다.")
        self.review("T-003", 1)
        self.done("T-003")
        [cleanup] = [t for t in self.ids() if t not in ("T-001", "T-002", "T-003")]
        self.assertIsNone(self.spec(cleanup).issue)


class DriveStepTest(EventsCase):
    """관제의 전송 자식(설계 8.8·8.11·8.12): 큐가 비지 않았고 전송 자식이 없을 때 하나만 띄운다."""

    def test_spawns_one_child_and_reports_failures(self):
        self.server.codes.update({"999": [404], "5": [503]})
        self.put_item(1, "999", "start", 2, "a")
        self.put_item(2, "5", "start", 2, "b")
        self.d.redmine_step()
        self.assertEqual(list(self.d.jobs), ["redmine"])
        self.d.redmine_step()  # 자식이 도는 동안 하나 더 띄우지 않는다
        self.assertEqual(list(self.d.jobs), ["redmine"])
        self.wait_jobs()
        lines = self.log_lines()
        self.assertTrue(any(re.fullmatch(rf"{LOCAL_ISO} redmine #999 start 실패 404", ln) for ln in lines), lines)
        self.assertTrue(any(re.fullmatch(rf"{LOCAL_ISO} redmine #5 start 실패 503", ln) for ln in lines), lines)
        progress = [e["body"] for e in self.outbox_items() if e["type"] == "progress"]
        self.assertEqual(len(progress), 1, progress)  # 4xx 만 알린다(다시 보낼 항목은 로그만)
        self.assertTrue(progress[0].startswith("Redmine 이슈 #999 갱신 실패(start, 404): "), progress)
        self.assertIn(".herdr-team/state/redmine/failed/000001.json", progress[0])
        self.d.redmine_step()  # 남은 항목은 아직 다시 보낼 때가 아니다
        self.assertEqual(self.d.jobs, {})
        self.assertEqual(self.leaks(), [])

    def test_key_cut_at_200_chars_is_masked_whole(self):
        # 키가 응답 본문의 200자 경계에 걸쳐도 가린 뒤 자르므로 앞부분이 어디에도 남지 않는다(Rules 6 의 4, Codex 계획 리뷰 r1)
        long_key = "rk-LONG-" + "0123456789abcdef" * 2  # 40자
        self.env[KEY_ENV] = long_key
        self.rearm()
        self.server.codes["998"] = [422]
        self.server.pads["998"] = 154  # 본문 {"errors": ["x…bad key <키>"]} 에서 키가 175자째에 시작해 200자 경계에 걸친다
        self.put_item(1, "998", "start", 2, "a")
        self.d.redmine_step()
        self.wait_jobs()
        fragment = long_key[:12]
        [bad] = self.failed()
        self.assertIn("***", bad["error"])
        self.assertNotIn(fragment, bad["error"])
        [line] = [e["body"] for e in self.outbox_items() if e["type"] == "progress"]
        self.assertTrue(line.startswith("Redmine 이슈 #998 갱신 실패(start, 422): "), line)
        self.assertNotIn(fragment, line)
        self.assertEqual(self.leaks(fragment), [])  # 실패 파일·자식 출력·status.json·outbox·drive.log 어디에도 없다

    def test_no_child_without_items(self):
        self.d.redmine_step()
        self.assertEqual(self.d.jobs, {})

    def test_tick_runs_redmine_step_after_reaping(self):
        steps = ("heartbeat", "check_mail", "run_queue", "start_ready", "reap_jobs", "redmine_step", "reset_step",
                 "view_step", "reconcile")
        calls: list[str] = []
        with ExitStack() as stack:
            for name in steps:
                stack.enter_context(mock.patch.object(self.d, name, side_effect=lambda n=name: calls.append(n)))
            self.d.tick()
        self.assertEqual(calls, ["heartbeat", "check_mail", "run_queue", "reap_jobs", "redmine_step", "heartbeat",
                                 "reset_step", "view_step", "reconcile"])


class OffTest(RedmineMixin, TeamCase):
    """회귀: [redmine] 이 없으면 0.4.0 과 같다(큐 폴더·status 키·자식·doctor 점검이 없다)."""

    def test_without_redmine_table_nothing_changes(self):
        self.init_project()
        self.setup_run()
        self.write_spec("T-001", front={"issue": "5712"})
        with self.in_drive():
            d = self.make_drive()
            code, out = self.hteam("start", "T-001")
            self.assertEqual(code, 0, out)
            d.redmine_step()
            self.assertEqual(d.jobs, {})
        self.assertFalse(self.redmine_dir.exists())
        code, out = self.hteam("status", as_="main")
        self.assertEqual(code, 0, out)
        self.assertNotIn("redmine", out)
        code, out = self.hteam("doctor", as_="main")
        self.assertEqual(code, 0, out)
        self.assertFalse([c for c in out["checks"] if c["name"].startswith("redmine")])


class DoctorTest(RedmineMixin, TeamCase):
    """doctor 의 Redmine 점검(설계 9.2, 경고만): 키를 찾는지(값은 보이지 않는다), GET /users/current.json, env_file 추적."""

    def setUp(self):
        super().setUp()
        self.start_server()
        self.init_project(BASE_CONFIG + redmine_table(self.server.url, ".env"))

    def checks(self) -> dict:
        code, out = self.hteam("doctor", as_="main")
        self.assertEqual(code, 0, out)  # Redmine 점검은 경고라 healthy 를 바꾸지 않는다
        self.assertNotIn(KEY, json.dumps(out, ensure_ascii=False))
        return {c["name"]: c for c in out["checks"] if c["name"].startswith("redmine")}

    def test_key_api_and_env_file(self):
        (self.proj / ".env").write_text(f'{KEY_ENV}="{KEY}"\n', encoding="utf-8")
        checks = self.checks()
        self.assertEqual(set(checks), {"redmine_key", "redmine_api", "redmine_env_file"})
        self.assertEqual({c["level"] for c in checks.values()}, {"warning"})
        self.assertTrue(all(c["ok"] for c in checks.values()), checks)
        self.assertEqual([(r["method"], r["path"], r["key"]) for r in self.server.requests],
                         [("GET", "/users/current.json", KEY)])
        self.git("add", "--", ".env")
        self.git("commit", "-q", "-m", "env", "--", ".env")
        checks = self.checks()
        self.assertFalse(checks["redmine_env_file"]["ok"])  # git 이 추적하는 env_file 은 경고

    def test_missing_key_skips_api(self):
        (self.proj / ".env").write_text("OTHER=1\n", encoding="utf-8")
        checks = self.checks()
        self.assertFalse(checks["redmine_key"]["ok"])
        self.assertIn(KEY_ENV, checks["redmine_key"]["detail"])
        self.assertFalse(checks["redmine_api"]["ok"])
        self.assertEqual(self.server.requests, [])

    def test_key_from_environment_without_env_file(self):
        (self.team / "config.toml").write_text(BASE_CONFIG + redmine_table(self.server.url), encoding="utf-8")
        self.env[KEY_ENV] = KEY
        checks = self.checks()
        self.assertEqual(set(checks), {"redmine_key", "redmine_api"})
        self.assertTrue(checks["redmine_key"]["ok"] and checks["redmine_api"]["ok"], checks)


class MaskTest(unittest.TestCase):
    def test_mask_and_constants(self):
        from hteam import redmine
        self.assertEqual(redmine.mask(f"a {KEY} b {KEY}", KEY), "a *** b ***")
        self.assertEqual(redmine.mask("a", None), "a")
        self.assertEqual((redmine.RETRY_S, redmine.GIVE_UP_S, redmine.TIMEOUT_S), ((60, 120, 300, 600), 86400, 10))


if __name__ == "__main__":
    unittest.main()
