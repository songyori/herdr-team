"""SQLite 저장소. 쓰기는 tx() 안에서 BEGIN IMMEDIATE 로 한다."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .errors import FAIL, HorchError

SCHEMA_VERSION = 1

DDL = [
    "CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE runs(id TEXT PRIMARY KEY, objective TEXT NOT NULL, owner_space TEXT, owner_tab TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    """CREATE TABLE bindings(terminal TEXT PRIMARY KEY, run_id TEXT NOT NULL UNIQUE REFERENCES runs(id),
        argv TEXT)""",
    """CREATE TABLE tasks(id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), title TEXT NOT NULL,
        spec TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', outcome TEXT, created_at TEXT NOT NULL,
        settled_at TEXT)""",
    """CREATE TABLE dispatches(id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
        run_id TEXT NOT NULL REFERENCES runs(id), attempt INTEGER NOT NULL, agent TEXT NOT NULL, model TEXT,
        effort TEXT, cwd TEXT NOT NULL, terminal TEXT, state TEXT NOT NULL, outcome TEXT, summary TEXT,
        report_path TEXT, files_modified TEXT, launch_argv TEXT, launcher_pid INTEGER, launcher_started TEXT,
        created_at TEXT NOT NULL, settled_at TEXT, closed_at TEXT)""",
    "CREATE UNIQUE INDEX dispatch_one_running ON dispatches(task_id) WHERE state IN ('launching','active')",
    "CREATE INDEX dispatch_terminal ON dispatches(terminal)",
    """CREATE TABLE messages(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, mailbox TEXT NOT NULL,
        sender TEXT NOT NULL, type TEXT NOT NULL, subject TEXT, body TEXT NOT NULL, reply_to INTEGER,
        dispatch_id TEXT, ask_key TEXT, created_at TEXT NOT NULL, delivery_id INTEGER)""",
    "CREATE UNIQUE INDEX question_key ON messages(dispatch_id, ask_key) WHERE ask_key IS NOT NULL",
    "CREATE UNIQUE INDEX one_reply ON messages(reply_to) WHERE type = 'reply'",
    "CREATE INDEX messages_mailbox ON messages(mailbox, delivery_id, id)",
    """CREATE TABLE deliveries(id INTEGER PRIMARY KEY AUTOINCREMENT, mailbox TEXT NOT NULL,
        created_at TEXT NOT NULL, acked_at TEXT)""",
    """CREATE TABLE waiters(mailbox TEXT NOT NULL, pid INTEGER NOT NULL, pid_started TEXT NOT NULL, terminal TEXT,
        started_at TEXT NOT NULL, PRIMARY KEY(mailbox, pid))""",
    """CREATE TABLE observations(dispatch_id TEXT NOT NULL, kind TEXT NOT NULL, key TEXT NOT NULL,
        created_at TEXT NOT NULL, PRIMARY KEY(dispatch_id, kind, key))""",
]


class Store:
    def __init__(self, home: Path):
        self.home = home
        home.mkdir(parents=True, exist_ok=True)
        os.chmod(home, 0o700)
        self.conn = sqlite3.connect(home / "orch.db", isolation_level=None, timeout=5.0)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def _migrate(self) -> None:
        with self.tx():
            version = 0
            if self.one("SELECT name FROM sqlite_master WHERE type='table' AND name='meta'"):
                row = self.one("SELECT value FROM meta WHERE key='schema_version'")
                version = int(row["value"]) if row else 0
            if version > SCHEMA_VERSION:
                raise HorchError("schema_too_new",
                                 f"DB 스키마 {version} 은 이 horch 가 아는 {SCHEMA_VERSION} 보다 새롭다",
                                 FAIL, "horch 를 업데이트한다")
            if version == 0:
                for stmt in DDL:
                    self.conn.execute(stmt)
                self.conn.execute("INSERT INTO meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    def one(self, sql: str, params: tuple | list = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    def all(self, sql: str, params: tuple | list = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def run(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def dispatch_dir(self, run_id: str, dispatch_id: str) -> Path:
        return self.home / "runs" / run_id / "dispatches" / dispatch_id

    def close(self) -> None:
        self.conn.close()


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def row_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None
