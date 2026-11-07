"""이미지(설계 12장): scripts/codex-run.sh 의 계약(가짜 codex), `hteam image` 의 결과 검사·게시·크로마키, 사전 점검."""
import json
import os
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zlib
from pathlib import Path
from unittest import mock

from tests.helpers import ROOT, TeamCase
from hteam import browser, image
from hteam.errors import HteamError
from hteam.paths import Project

WRAPPER = ROOT / "scripts" / "codex-run.sh"

# 가짜 codex: --version, features list, mcp get, exec(이벤트 JSONL 을 stdout 에, 최종 메시지를 --output-last-message 파일에).
# FAKE_MODE: ok | turnfail | fail | silent | chatty | image | link | refuse | nopath. image 는 FAKE_PNG 의 파일을, link 는
# 그 파일을 가리키는 심볼릭 링크를 결과로 낸다. FAKE_USER_MCP(stdio | url)면 사용자 설정에 chrome-devtools 가 있다.
# 멈추는 모드는 자기 PID·PGID·자식 PID 를 파일(FAKE_PIDS)에 쓴다. 파일이 생기면 준비가 끝났다.
# PATH 의 `codex` 는 셸 대역(FAKE_SHIM)이다: FAKE_VERSION_HANG 이면 --version 을 셸이 바로 맡아 준비 신호(FAKE_VPIDS)를
# 쓰고 멈춘다(파이썬 시작을 기다리지 않으므로 래퍼의 짧은 버전 대기가 준비 신호보다 먼저 끝나지 않는다). 나머지는 이 파이썬
# 대역을 exec 한다.
FAKE_SHIM = r'''#!/bin/sh
if [ "$1" = "--version" ] && [ -n "${FAKE_VERSION_HANG:-}" ]; then
  stdin=other; [ -c /dev/stdin ] && stdin=chardev
  sleep 307 &
  [ -n "${FAKE_READY_DELAY:-}" ] && sleep "$FAKE_READY_DELAY"   # 준비가 늦는 대역(셸 시작이 빠르다고 가정하지 않는다)
  pgid=$(ps -o pgid= -p $$ | tr -d ' ')
  printf '{"pid": %s, "pgid": %s, "stdin": "%s", "child": %s}\n' "$$" "$pgid" "$stdin" "$!" > "$FAKE_VPIDS.tmp"
  mv "$FAKE_VPIDS.tmp" "$FAKE_VPIDS"
  wait
  exit 0
fi
exec "$FAKE_PYTHON" "$(dirname "$0")/fake_codex.py" "$@"
'''
# 시험이 쥐는 시계: FAKE_SLEEP_GATE 가 있으면 0.2초 잠(래퍼의 버전 대기 한 칸), FAKE_SLEEP_GATE1 이 있으면 1초 잠(감시 주기·
# 그룹 정리 한 칸)은 그 파일(준비 신호)이 생길 때까지(최대 60초) 시작하지 않는다. 래퍼의 버전 대기·진행 신호 없음 제한은 준비 신호 뒤에야 의미를 갖는다
# (Codex 계획 r3, 태스크 리뷰 6). 다른 잠은 그대로 /bin/sleep 이다
FAKE_SLEEP = r'''#!/bin/sh
gate=""
[ "$1" = 0.2 ] && gate="${FAKE_SLEEP_GATE:-}"
[ "$1" = 1 ] && gate="${FAKE_SLEEP_GATE1:-}"
if [ -n "$gate" ]; then
  n=0
  while [ ! -e "$gate" ] && [ "$n" -lt 1200 ]; do /bin/sleep 0.05; n=$((n+1)); done
fi
exec /bin/sleep "$@"
'''
FAKE_CODEX = r'''#!/usr/bin/env python3
import json, os, shutil, subprocess, sys, time
args = sys.argv[1:]
def record(name, **extra):
    path = os.environ[name]
    stdin = "chardev" if os.path.exists("/dev/stdin") and os.stat("/dev/stdin").st_mode & 0o020000 else "other"
    with open(path + ".tmp", "w") as fh:
        json.dump({"pid": os.getpid(), "pgid": os.getpgid(0), "stdin": stdin, **extra}, fh)
    os.replace(path + ".tmp", path)
def hang(name):
    child = subprocess.Popen(["sleep", "307"])
    record(name, child=child.pid)
    while True: time.sleep(1)
if args[:1] == ["--version"]:
    print("codex-cli 9.9.9-fake"); sys.exit(0)
if args[:3] == ["mcp", "get", "chrome-devtools"]:
    kind = os.environ.get("FAKE_USER_MCP")
    if not kind:
        print("Error: No MCP server named 'chrome-devtools' found.", file=sys.stderr); sys.exit(1)
    transport = ({"type": "stdio", "command": "npx", "args": ["-y", "chrome-devtools-mcp@1.10.1"]} if kind == "stdio"
                 else {"type": "streamable_http", "url": "http://127.0.0.1:9/mcp"})
    print(json.dumps({"name": "chrome-devtools", "enabled": True, "transport": transport})); sys.exit(0)
if args[:2] == ["features", "list"]:
    if os.environ.get("FAKE_BAD_PROVIDER") and any(a.startswith("model_provider") for a in args):
        print("Error: Model provider image_backend not found", file=sys.stderr); sys.exit(1)
    print("hooks  stable  true")
    args = [x.replace(" ", "") for x in args]
    on = ("features.image_generation=true" in args or "features={image_generation=true}" in args or "--enable=image_generation" in args
          or any(a == "--enable" and args[k + 1] == "image_generation" for k, a in enumerate(args[:-1])))
    off = "features.image_generation=false" in args or "--disable=image_generation" in args
    print("image_generation  stable  " + ("false" if (os.environ.get("FAKE_NO_IMAGE") and not on) or off else "true")); sys.exit(0)
with open(os.environ["FAKE_ARGV"], "a") as fh:
    fh.write(json.dumps(args) + "\n")
stdin = "chardev" if os.path.exists("/dev/stdin") and os.stat("/dev/stdin").st_mode & 0o020000 else "other"
open(os.environ["FAKE_STDIN"], "w").write(stdin)
out = args[args.index("--output-last-message") + 1]
mode = os.environ.get("FAKE_MODE", "ok")
def event(kind):
    print(json.dumps({"type": kind}, separators=(",", ":")), flush=True)
event("thread.started"); event("turn.started")
if mode == "noevent":
    shutil.copyfile(os.environ["FAKE_PNG"], os.path.join(os.environ["FAKE_GEN"], "ig_ne.png"))
    open(out, "w").write(os.path.join(os.environ["FAKE_GEN"], "ig_ne.png") + "\n"); sys.exit(0)
if mode in ("ok", "image", "link"):
    path = os.environ.get("FAKE_PNG", "")
    made = os.path.join(os.environ["FAKE_GEN"], "ig_%d.png" % len(os.listdir(os.environ["FAKE_GEN"])))
    if mode == "image":
        shutil.copyfile(path, made)
        open(out, "w").write("만들었다\n`" + made + "`\n")
    elif mode == "link":
        os.symlink(path, made)
        open(out, "w").write(made + "\n")
    else:
        open(out, "w").write("FAKE_RESULT_OK\n")
    event("turn.completed"); sys.exit(0)
if mode == "nopath":
    open(out, "w").write("만들었다\n"); event("turn.completed"); sys.exit(0)
if mode in ("turnfail", "refuse"):
    open(out, "w").write("정책상 만들 수 없다\n"); event("turn.failed"); sys.exit(0)
if mode == "fail":
    print("boom", file=sys.stderr); sys.exit(3)
if mode == "silent":
    hang("FAKE_PIDS")
if mode == "chatty":
    record("FAKE_PIDS")
    while True:
        event("item.started"); time.sleep(0.5)
'''


def png_rgb(width, height, pixel, filters=None):
    """8비트 RGB PNG. filters 를 주면 줄마다 그 필터(0–4)로 부호화한다(read_rgba 의 복호화를 시험한다)."""
    import struct
    rows = [bytes(pixel(x, y)[k] for x in range(width) for k in range(3)) for y in range(height)]
    data, prev = b"", bytes(width * 3)
    for y, row in enumerate(rows):
        kind = (filters or [0] * height)[y]
        enc = bytearray()
        for x in range(len(row)):
            a = row[x - 3] if x >= 3 else 0
            b = prev[x]
            c = prev[x - 3] if x >= 3 else 0
            pred = (0, a, b, (a + b) // 2, image._paeth(a, b, c))[kind]
            enc.append((row[x] - pred) & 0xFF)
        data += bytes([kind]) + bytes(enc)
        prev = row

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    return (image.PNG_SIG + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(data)) + chunk(b"IEND", b""))


class FakeCodexMixin:
    def fake_codex(self, root: Path) -> dict:
        bin_dir = root / "fakebin"
        bin_dir.mkdir()
        (bin_dir / "codex").write_text(FAKE_SHIM)
        (bin_dir / "codex").chmod(0o755)
        (bin_dir / "fake_codex.py").write_text(FAKE_CODEX)
        (bin_dir / "sleep").write_text(FAKE_SLEEP)
        (bin_dir / "sleep").chmod(0o755)
        (root / "gen").mkdir()
        self.addCleanup(self.reap_recorded, root)
        return {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "FAKE_ARGV": str(root / "argv.jsonl"),
                "FAKE_STDIN": str(root / "stdin.txt"), "FAKE_GEN": str(root / "gen"),
                "FAKE_PIDS": str(root / "pids.json"), "FAKE_VPIDS": str(root / "vpids.json"), "FAKE_PYTHON": sys.executable,
                "XDG_CACHE_HOME": str(root / "cache")}

    def argvs(self, root: Path) -> list[list[str]]:
        path = root / "argv.jsonl"
        return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []

    def recorded(self, root: Path, name: str = "pids.json", wait: float = 20.0) -> dict:
        """가짜 codex 가 쓴 PID 파일(준비 신호). wait 초 안에 생기지 않으면 실패."""
        path = root / name
        deadline = time.monotonic() + wait
        while not path.exists():
            if time.monotonic() >= deadline:
                self.fail(f"{name} 이 생기지 않았다")
            time.sleep(0.05)
        return json.loads(path.read_text())

    def assert_group_gone(self, info: dict, wait: float = 15.0) -> None:
        """가짜 codex 가 자기 프로세스 그룹의 리더이고(래퍼가 그룹을 줬다), 그 그룹이 자식까지 끝났다."""
        self.assertEqual(info["pgid"], info["pid"])
        self.assertNotEqual(info["pgid"], os.getpgid(0))
        deadline = time.monotonic() + wait
        while True:
            try:
                os.killpg(info["pgid"], 0)
            except ProcessLookupError:
                return
            if time.monotonic() > deadline:
                self.fail(f"프로세스 그룹 {info['pgid']} 이 남았다")
            time.sleep(0.1)

    @staticmethod
    def reap_recorded(root: Path) -> None:
        """실패한 테스트가 남긴 가짜 codex 그룹을 치운다(기록한 그룹만)."""
        for name in ("pids.json", "vpids.json"):
            try:
                pgid = json.loads((root / name).read_text())["pgid"]
            except (OSError, ValueError, KeyError):
                continue
            if pgid > 1 and pgid != os.getpgid(0):
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass


class WrapperTest(FakeCodexMixin, unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="hteam-wrap-")).resolve()
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.root)])
        self.env = {**os.environ, **self.fake_codex(self.root)}
        self.prompt = self.root / "prompt.txt"
        self.prompt.write_text('따옴표 " 백틱 ` 달러 $HOME\n둘째 줄\n\n')
        self.cwd = self.root / "work"
        self.cwd.mkdir()

    def args(self, *extra, run_dir="run"):
        return ["bash", str(WRAPPER), "--profile", "image", "--prompt-file", str(self.prompt),
                "--run-dir", str(self.root / run_dir), "--cwd", str(self.cwd), *extra]

    def run_wrapper(self, *extra, mode="ok", env=None, run_dir="run"):
        return subprocess.run(self.args(*extra, run_dir=run_dir), capture_output=True, text=True,
                              env={**self.env, "FAKE_MODE": mode, **(env or {})}, timeout=90)

    def status(self, run_dir="run"):
        return json.loads((self.root / run_dir / "status.json").read_text())

    def test_wrapper_is_executable_and_parses(self):
        self.assertTrue(os.access(WRAPPER, os.X_OK))
        self.assertEqual(subprocess.run(["bash", "-n", str(WRAPPER)]).returncode, 0)

    def test_ok_keeps_the_contract(self):
        ref = self.root / "ref.png"
        ref.write_bytes(b"png")
        proc = self.run_wrapper("--model", "img-model", "--effort", "medium", "--image", str(ref),
                                "--codex-arg=--disable=hooks")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        st = self.status()
        self.assertEqual((st["state"], st["exit"], st["raw_exit"], st["terminal_event"], st["profile"]),
                         ("ok", 0, 0, "turn.completed", "image"))
        self.assertEqual(st["codex_version"], "codex-cli 9.9.9-fake")
        self.assertEqual(st["cwd"], str(self.cwd))
        self.assertEqual((self.root / "run/result.txt").read_text(), "FAKE_RESULT_OK\n")
        [argv] = self.argvs(self.root)
        self.assertEqual(argv[:2], ["exec", "--skip-git-repo-check"])
        for flag in ("--dangerously-bypass-approvals-and-sandbox", "--json", "--output-last-message", "--disable=hooks"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("-C") + 1], str(self.cwd))
        self.assertEqual(argv[argv.index("--model") + 1], "img-model")
        self.assertEqual(argv[argv.index("-c") + 1], "model_reasoning_effort=medium")
        self.assertLess(argv.index("-i"), argv.index("--json"))  # -i 는 값을 여럿 받는다. 프롬프트를 먹지 않게
        self.assertEqual(argv[-1], '따옴표 " 백틱 ` 달러 $HOME\n둘째 줄')  # 끝 줄바꿈만 빠진다
        self.assertEqual(argv[-2], "--")  # 프롬프트가 `-` 로 시작해도 옵션으로 읽히지 않는다
        self.assertEqual((self.root / "stdin.txt").read_text(), "chardev")  # /dev/null

    def test_status_json_escapes_control_characters(self):
        # 작업 폴더 이름의 줄바꿈·탭·따옴표·역슬래시·제어 문자가 status.json 을 깨지 않는다
        self.cwd = self.root / 'wo"rk\\\n\tx\x01'
        self.cwd.mkdir()
        self.assertEqual(self.run_wrapper().returncode, 0)
        self.assertEqual(self.status()["cwd"], str(self.cwd))

    def test_optional_flags_are_left_out(self):
        self.assertEqual(self.run_wrapper().returncode, 0)
        [argv] = self.argvs(self.root)
        for flag in ("--model", "-c", "-i"):
            self.assertNotIn(flag, argv)

    def test_turn_failed_is_reported_in_status_not_exit(self):
        proc = self.run_wrapper(mode="turnfail")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(self.status()["terminal_event"], "turn.failed")

    def test_abnormal_exit_is_1_with_raw_exit(self):
        proc = self.run_wrapper(mode="fail")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual((self.status()["raw_exit"], self.status()["exit"]), (3, 1))
        self.assertIn("boom", (self.root / "run/progress.log").read_text())

    def test_silence_is_11_and_kills_the_group(self):
        # 진행 신호 없음 2초, 전체 제한 60초: 스케줄링이 늦어도 전체 시간 초과가 먼저 오지 않는다
        # 준비 신호(pids 파일) 전에는 감시 주기가 돌지 않는다(FAKE_SLEEP_GATE): 파이썬 시작이 느려도 흔들리지 않는다
        proc = self.run_wrapper("--timeout", "60", "--heartbeat", "2", mode="silent",
                                env={"FAKE_SLEEP_GATE1": self.env["FAKE_PIDS"]})
        self.assertEqual(proc.returncode, 11, proc.stderr)
        self.assertEqual((self.status()["state"], self.status()["exit"]), ("stalled", 11))
        self.assert_group_gone(self.recorded(self.root))  # 가짜 codex 와 그 자식(sleep)이 그룹째 끝났다

    def test_timeout_is_10(self):
        # 0.5초마다 이벤트를 내므로 진행 신호 없음(6초)은 오지 않고 전체 시간 초과(8초)가 온다
        proc = self.run_wrapper("--timeout", "8", "--heartbeat", "6", mode="chatty")
        self.assertEqual(proc.returncode, 10, proc.stderr)
        self.assertEqual((self.status()["state"], self.status()["terminal_event"]), ("timeout", None))
        self.assert_group_gone(self.recorded(self.root))

    def test_version_hang_is_bounded(self):
        # codex --version 이 멈춰도 감시 밖에서 기다리지 않는다: HTEAM_CODEX_VERSION_WAIT 뒤 그 그룹을 끝내고 버전 없이 간다.
        # 래퍼의 대기 칸(sleep 0.2)은 준비 신호가 생긴 뒤에야 시작하므로(FAKE_SLEEP_GATE) 준비가 늦어도(1초) 시험이 흔들리지
        # 않는다(Codex 계획 r2·r3: 준비 전에 제한이 끝나 흔들렸다)
        proc = subprocess.Popen(self.args(), env={**self.env, "FAKE_MODE": "ok", "FAKE_VERSION_HANG": "1",
                                                  "HTEAM_CODEX_VERSION_WAIT": "1", "FAKE_READY_DELAY": "1",
                                                  "FAKE_SLEEP_GATE": self.env["FAKE_VPIDS"]},
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        _, err = proc.communicate(timeout=60)
        info = self.recorded(self.root, "vpids.json", wait=0)  # 래퍼가 끝났을 때 준비 신호는 이미 있다
        self.assertEqual(proc.returncode, 0, err)
        self.assertIsNone(self.status()["codex_version"])
        self.assertIn("codex --version", err)
        self.assertEqual(info["stdin"], "chardev")  # /dev/null
        self.assert_group_gone(info)
        self.assertEqual(len(self.argvs(self.root)), 1)

    def test_missing_codex_is_12(self):
        env = {"PATH": "/usr/bin:/bin"}
        proc = self.run_wrapper(env=env)
        self.assertEqual(proc.returncode, 12, proc.stderr)
        self.assertEqual((self.status()["state"], self.status()["exit"]), ("missing", 12))

    def test_argument_errors_are_2_without_status(self):
        for extra in (("--timeout", "5", "--heartbeat", "5"), ("--timeout", "x"), ("--bogus",), ("--image",),
                      ("--image", str(self.root / "nope.png"))):
            with self.subTest(extra=extra):
                proc = self.run_wrapper(*extra, run_dir=f"bad-{len(extra)}-{extra[0]}")
                self.assertEqual(proc.returncode, 2, proc.stderr)
                self.assertFalse((self.root / f"bad-{len(extra)}-{extra[0]}" / "status.json").exists())
        args = ["bash", str(WRAPPER), "--profile", "run", "--prompt-file", str(self.prompt), "--run-dir", str(self.root / "r")]
        self.assertEqual(subprocess.run(args, capture_output=True, env=self.env).returncode, 2)

    def interrupt(self, name, env):
        proc = subprocess.Popen(self.args(), env={**self.env, **env}, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        info = self.recorded(self.root, name)  # 가짜 codex 가 자식까지 띄운 뒤에 보낸다
        proc.send_signal(signal.SIGTERM)
        proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, 130)
        self.assertEqual(self.status()["exit"], 130)
        self.assert_group_gone(info)

    def test_interrupt_is_130(self):
        self.interrupt("pids.json", {"FAKE_MODE": "silent"})

    def test_interrupt_during_version_is_130(self):
        self.interrupt("vpids.json", {"FAKE_MODE": "ok", "FAKE_VERSION_HANG": "1", "HTEAM_CODEX_VERSION_WAIT": "600"})


def png_raw(fields: tuple, raw: bytes | None = None, idat: bytes | None = None) -> bytes:
    """IHDR 필드(너비, 높이, 깊이, 색 형식, 인터레이스)와 풀린 데이터(raw) 또는 IDAT 원문(idat)으로 CRC 가 맞는 PNG."""
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    width, height, depth, ctype, interlace = fields
    body = zlib.compress(raw) if idat is None else idat
    return (image.PNG_SIG + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, ctype, 0, 0, interlace))
            + chunk(b"IDAT", body) + chunk(b"IEND", b""))


def png_chunks(fields: tuple, chunks: list[tuple[bytes, bytes]]) -> bytes:
    """IHDR 뒤에 (종류, 본문) 청크를 차례로 두고 IEND 로 끝낸 PNG(CRC 는 맞다)."""
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    width, height, depth, ctype, interlace = fields
    return (image.PNG_SIG + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, ctype, 0, 0, interlace))
            + b"".join(chunk(k, b) for k, b in chunks) + chunk(b"IEND", b""))


class PngTest(unittest.TestCase):
    def test_png_info_checks_palette_and_filters(self):
        # Codex 계획 r3: 색 형식 3 은 IDAT 앞 PLTE(3바이트 × 1–256)가 있어야 하고, 0·4 에는 PLTE 가 없어야 한다.
        # 풀린 데이터의 줄마다 필터 바이트가 0–4 다
        pix = zlib.compress(b"\x00\x00")  # 1×1, 8비트 팔레트: 필터 0 + 색인 0
        self.assertIsNone(image.png_info(png_chunks((1, 1, 8, 3, 0), [(b"IDAT", pix)])))  # PLTE 없음
        self.assertEqual(image.png_info(png_chunks((1, 1, 8, 3, 0), [(b"PLTE", b"\x00\x00\x00"), (b"IDAT", pix)])),
                         (1, 1, 8, 3))
        self.assertIsNone(image.png_info(png_chunks((1, 1, 8, 3, 0), [(b"IDAT", pix), (b"PLTE", b"\x00" * 3)])))  # 뒤
        self.assertIsNone(image.png_info(png_chunks((1, 1, 8, 3, 0), [(b"PLTE", b"\x00" * 4), (b"IDAT", pix)])))
        self.assertIsNone(image.png_info(png_chunks((1, 1, 8, 3, 0), [(b"PLTE", b"\x00" * 771), (b"IDAT", pix)])))
        self.assertIsNone(image.png_info(png_chunks((1, 1, 8, 0, 0), [(b"PLTE", b"\x00" * 3), (b"IDAT", pix)])))  # 회색
        self.assertEqual(image.png_info(png_chunks((1, 1, 8, 2, 0), [(b"PLTE", b"\x00" * 3),
                                                                     (b"IDAT", zlib.compress(bytes(4)))]))[3], 2)
        self.assertIsNone(image.png_info(png_raw((2, 1, 8, 2, 0), b"\x05" + bytes(6))))  # 필터 5
        self.assertIsNone(image.png_info(png_raw((1, 2, 8, 2, 0), bytes(4) + b"\x07" + bytes(3))))  # 둘째 줄

    def test_png_info_decodes_the_pixel_data(self):
        # Codex 계획 r2: CRC 가 맞아도 IDAT 가 풀리지 않거나 풀린 길이가 IHDR 과 다르면 PNG 로 보지 않는다
        self.assertIsNone(image.png_info(png_raw((1, 1, 8, 2, 0), idat=b"not zlib")))
        self.assertEqual(image.png_info(png_raw((2, 2, 8, 2, 0), bytes(2 * (1 + 6)))), (2, 2, 8, 2))
        self.assertIsNone(image.png_info(png_raw((2, 2, 8, 2, 0), bytes(2 * (1 + 6) - 1))))  # 짧다
        self.assertIsNone(image.png_info(png_raw((2, 2, 8, 2, 0), bytes(2 * (1 + 6) + 1))))  # 길다
        self.assertEqual(image.png_info(png_raw((3, 1, 16, 6, 0), bytes(1 + 3 * 8)))[:3], (3, 1, 16))
        self.assertEqual(image.png_info(png_raw((5, 1, 1, 0, 0), bytes(1 + 1)))[:3], (5, 1, 1))  # 1비트: 5픽셀 = 1바이트
        self.assertIsNone(image.png_info(png_raw((1, 1, 16, 3, 0), bytes(1 + 2))))  # 팔레트에 16비트는 없다
        # 인터레이스(Adam7) 3×3 RGB 8비트: 1·4·5·6·7 패스만 픽셀이 있다(패스의 행마다 필터 바이트 하나)
        sizes = [(1, 1), (0, 0), (0, 0), (1, 1), (2, 1), (1, 2), (3, 1)]
        raw = b"".join(bytes(h * (1 + w * 3)) for w, h in sizes)
        self.assertEqual(image.png_info(png_raw((3, 3, 8, 2, 1), raw)), (3, 3, 8, 2))
        self.assertIsNone(image.png_info(png_raw((3, 3, 8, 2, 1), raw + b"\x00")))

    def test_reads_every_filter(self):
        def pixel(x, y):
            return ((x * 37 + y * 11) % 256, (x * 5 + y * 90) % 256, (x * y * 13) % 256)
        data = png_rgb(5, 5, pixel, filters=[0, 1, 2, 3, 4])
        width, height, rgba = image.read_rgba(data)
        self.assertEqual((width, height), (5, 5))
        self.assertEqual([tuple(rgba[i:i + 3]) for i in range(0, len(rgba), 4)],
                         [pixel(x, y) for y in range(5) for x in range(5)])
        self.assertTrue(all(rgba[i] == 255 for i in range(3, len(rgba), 4)))

    def test_chroma_key_clears_the_corner_color(self):
        data = png_rgb(6, 6, lambda x, y: (200, 30, 30) if 2 <= x <= 3 and 2 <= y <= 3 else (0, 255, 0))
        mode, keyed = image.transparency(data)
        self.assertEqual(mode, "chroma")
        width, height, rgba = image.read_rgba(keyed)
        self.assertEqual((rgba[3], rgba[(2 * 6 + 2) * 4 + 3]), (0, 255))
        self.assertEqual(image.png_info(keyed)[3], 6)
        self.assertEqual(image.transparency(keyed), ("native", keyed))  # 다시 하면 이미 투명하다
        other = png_rgb(4, 4, lambda x, y: (x * 60, y * 60, 0))
        self.assertEqual(image.transparency(other), ("no_key", other))

    def test_png_info_walks_every_chunk(self):
        # 머리(IHDR)만 맞는 33바이트, IDAT 가 없는 것, CRC 가 틀린 것, IEND 가 없는 것은 PNG 로 보지 않는다
        good = png_rgb(3, 2, lambda x, y: (1, 2, 3))
        self.assertEqual(image.png_info(good), (3, 2, 8, 2))
        idat = good.index(b"IDAT") - 4
        iend = good.index(b"IEND") - 4
        bad_crc = bytearray(good)
        bad_crc[idat + 9] ^= 0xFF
        for data in (good[:33], good[:idat] + good[iend:], bytes(bad_crc), good[:iend], b"GIF89a" + good[6:]):
            with self.subTest(size=len(data)):
                self.assertIsNone(image.png_info(data))


    def test_png_size_limit(self):
        # 태스크 리뷰 7: IHDR 의 크기가 상한을 넘으면 풀기 전에 PNG 로 보지 않는다(메모리·시간)
        pix = zlib.compress(b"\x00" * 4)
        for width, height in ((image.MAX_SIDE + 1, 1), (1, image.MAX_SIDE + 1), (image.MAX_SIDE, image.MAX_SIDE)):
            with self.subTest(size=(width, height)):
                data = png_chunks((width, height, 8, 2, 0), [(b"IDAT", pix)])
                self.assertIsNone(image.png_info(data))
                self.assertIsNone(image.read_rgba(data))
        self.assertEqual(image.png_info(png_rgb(2, 1, lambda x, y: (1, 2, 3)))[:2], (2, 1))

    def test_rgba_reader_stops_at_iend_and_uses_the_first_ihdr(self):
        # 태스크 리뷰 10: IEND 뒤의 덧붙은 청크(IDAT·IHDR)는 png_info 처럼 보지 않는다
        good = png_rgb(3, 2, lambda x, y: (x * 9, y * 9, 7))
        def chunk(kind, body):
            return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
        tail = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", b"junk")
        dup = good.replace(b"IDAT", b"IHDR", 0)  # 같은 PNG
        self.assertEqual(image.read_rgba(good + tail), image.read_rgba(dup))
        self.assertEqual(image.png_info(good + tail), (3, 2, 8, 2))
        mid = good[:33] + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + good[33:]  # 둘째 IHDR 는 쓰지 않는다
        self.assertEqual(image.read_rgba(mid)[:2], (3, 2))


class PreflightTest(FakeCodexMixin, unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="hteam-pre-")).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        env = {**self.fake_codex(self.root), "FAKE_NO_IMAGE": "1"}
        patch = mock.patch.dict(os.environ, env)
        patch.start()
        self.addCleanup(patch.stop)

    def test_run_args_reach_the_feature_query(self):
        # Codex 78e7b59 P2: 사용자 설정에서 꺼져 있어도 실행 인자가 켜면 사전 점검이 통과하고, 끄면 막힌다
        with self.assertRaises(HteamError) as ctx:
            image.preflight([])
        self.assertEqual(ctx.exception.code, "no_image_generation")
        for args in (["--enable=image_generation"], ["--enable", "image_generation"],
                     ["-c", "features.image_generation=true"], ["-cfeatures.image_generation=true"],
                     ["-c", "features={image_generation=true}"], ["--config= features ={image_generation=true}"]):
            with self.subTest(args=args):
                image.preflight(args)
        os.environ.pop("FAKE_NO_IMAGE")
        with self.assertRaises(HteamError):
            image.preflight(["--disable=image_generation"])

    def test_features_table_key_is_forwarded(self):
        # Codex b0a717b P2: 키가 정확히 `features`(테이블 값)인 -c 도 기능 인자다. 앞뒤 공백은 뗀다
        self.assertEqual(image.feature_args(["-c", "features={image_generation=true}", "-c", "featuresx=1", "-c", "feature.a=1"]),
                         ["-c", "features={image_generation=true}"])
        self.assertEqual(image.feature_args(["--config= features ={a=true}"]), ["-c", " features ={a=true}"])

    def test_profile_skips_the_check_with_a_warning(self):
        # Codex 3300643 P2: `codex features list` 는 프로필을 받지 않는다(--help). 프로필에만 있는 설정(provider 등)에 기대는
        # 정상 설정을 막지 않고 건너뛰며 경고만 남긴다. 일반 -c 는 조회에 넘어가지 않는다
        for args in (["--profile", "images", "-c", 'model_provider="image_backend"'], ["-pimages"], ["--profile=images"]):
            with self.subTest(args=args):
                warning = image.preflight(args)
                self.assertIn("프로필이 있어 image_generation 사전 확인을 건너뛰었다", warning)
        self.assertIsNone(image.preflight(["--enable=image_generation"]))

    def test_general_config_is_not_sent_to_the_query(self):
        # provider 를 모르는 조회는 실패한다(가짜 codex 가 그렇게 흉내 낸다). features.* 만 넘기면 통과한다
        os.environ["FAKE_BAD_PROVIDER"] = "1"
        self.addCleanup(os.environ.pop, "FAKE_BAD_PROVIDER", None)
        image.preflight(["-c", 'model_provider="image_backend"', "-c", "features.image_generation=true"])


class CodexArgsTest(unittest.TestCase):
    def test_image_drops_mcp_servers_and_bypass(self):
        # 이미지 실행에 브라우저가 필요 없고(서버 시작을 이미지마다 치르지 않는다), 래퍼가 우회 플래그를 늘 붙인다
        # (같은 플래그를 두 번 주면 codex exec 가 exit 2 로 끝난다)
        args = ["--disable=hooks", "-c", 'mcp_servers.chrome-devtools.command="npx"', "--config", "mcp_servers.a.args=[]",
                "--config=mcp_servers.a.x=1", "-cmcp_servers.a.y=2", "-c=mcp_servers.a.z=3", "-c", "model_verbosity=low",
                "--dangerously-bypass-approvals-and-sandbox", "--yolo", "--full-auto", "--approve-for-me"]
        self.assertEqual(image.codex_args(args), ["--disable=hooks", "-c", "model_verbosity=low"])

    def test_key_whitespace_is_ignored(self):
        # 태스크 리뷰·Codex 78e7b59 P2: codex 는 `=` 앞의 키의 앞뒤 공백을 떼고 읽는다(browser.key_of 하나를 같이 쓴다)
        args = ["-c", ' mcp_servers.hteam-browser={command="npx"}', "-c", "mcp_servers.a.x =1", "--config= mcp_servers.b.y=1",
                "-c", "mcp_servers .c=1", "-c", "model_verbosity=low"]
        self.assertEqual(image.codex_args(args), ["-c", "mcp_servers .c=1", "-c", "model_verbosity=low"])
        self.assertEqual(browser.key_of("  a.b  = 1"), "a.b")

    def test_interactive_only_and_model_args_are_dropped_and_shown(self):
        # 읽기 전용 `codex exec --help`(0.166): -a/--ask-for-approval·--search·--no-alt-screen 은 exec 에 없고, -m/--model 은
        # 이미지가 --model 을 직접 준다. 뺀 인자는 보임 글로 돌려준다
        args = ["--disable=hooks", "-a", "never", "--ask-for-approval=never", "-anever", "--search", "--no-alt-screen",
                "-m", "x", "--model", "y", "--model=z", "-mw", "-c", "model_verbosity=low", "--profile", "p"]
        kept, shown = image.split_args(args)
        self.assertEqual(kept, ["--disable=hooks", "-c", "model_verbosity=low", "--profile", "p"])
        self.assertEqual(shown, ["-a never", "--ask-for-approval=never", "-anever", "--search", "--no-alt-screen", "-m x",
                                 "--model y", "--model=z", "-mw"])
        self.assertEqual(image.split_args(["--disable=hooks"]), (["--disable=hooks"], []))

    def test_feature_args_follow_the_run_args(self):
        # 사전 조회(codex features list)에도 실행에 쓰는 기능·설정 인자만 넘긴다
        args = ["--disable=hooks", "--enable", "image_generation", "-c", "features.x=true", "-cmodel_verbosity=low",
                "--search", "--profile", "p", "--model", "m"]
        # 기능 관련만: features.* 의 -c(키 앞뒤 공백은 뗀다)와 --enable·--disable. 그 밖의 -c 는 조회가 모르는 프로필 설정에
        # 기대는 것일 수 있어(예: 프로필 전용 model_provider) 넘기지 않는다(Codex 3300643 P2)
        self.assertEqual(image.feature_args(args + ["-c", " features.y = false", "-c", "model_provider=\"b\""]),
                         ["-c", "features.x=true", "-c", " features.y = false", "--disable=hooks", "--enable",
                          "image_generation"])


class ImageCommandTest(FakeCodexMixin, TeamCase):
    def setUp(self):
        super().setUp()
        self.init_project()
        self.fake = self.fake_codex(self.tmp)
        self.png = self.tmp / "made.png"
        self.png.write_bytes(png_rgb(8, 4, lambda x, y: (0, 255, 0) if x in (0, 7) or y in (0, 3) else (10, 20, 200)))

    def image(self, *args, mode="image", **env):
        return self.hteam("image", *args, as_=None, env={**self.fake, "FAKE_MODE": mode, "FAKE_PNG": str(self.png), **env},
                          timeout=120)

    def test_two_images_are_copied_without_overwriting(self):
        code, out = self.image("--n", "2", "--out", "assets/home", "Login hero illustration, flat")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["count"], 2)
        paths = [Path(x["path"]) for x in out["images"]]
        self.assertEqual([p.relative_to(self.proj).as_posix() for p in paths],
                         ["assets/home/login-hero-illustration-flat-1.png", "assets/home/login-hero-illustration-flat-2.png"])
        self.assertEqual((out["images"][0]["width"], out["images"][0]["height"], out["images"][0]["alpha"]), (8, 4, False))
        self.assertEqual(paths[0].read_bytes(), self.png.read_bytes())
        run_dir = Path(out["images"][0]["run_dir"])
        self.assertEqual(run_dir.parent, self.tmp / "cache/herdr-team/images/proj")
        prompt = (run_dir / "prompt.txt").read_text()
        for needle in ("image_gen", "Login hero illustration, flat", "절대 경로 하나만 마지막 줄에"):
            self.assertIn(needle, prompt)
        argv = self.argvs(self.tmp)[0]
        self.assertIn("--disable=hooks", argv)  # [agents.codex].args
        self.assertFalse([a for a in argv if "mcp_servers." in a])  # 기본 설정의 chrome-devtools 정의는 넘기지 않는다
        self.assertEqual(argv[argv.index("--model") + 1], "gpt-6.1-sol")  # [image] 가 없으면 [defaults] 의 codex_*
        self.assertEqual(argv[argv.index("-c") + 1], "model_reasoning_effort=high")
        code, out = self.image("--out", "assets/home", "Login hero illustration, flat")
        self.assertEqual(Path(out["images"][0]["path"]).name, "login-hero-illustration-flat-1-v2.png")
        self.assertEqual(sorted(p.name for p in (self.proj / "assets/home").iterdir()),  # 임시 파일이 남지 않는다
                         ["login-hero-illustration-flat-1-v2.png", "login-hero-illustration-flat-1.png",
                          "login-hero-illustration-flat-2.png"])

    def test_transparent_uses_chroma_key(self):
        code, out = self.image("--transparent", "--ar", "2:1", "--out", "assets/x", "icon")
        self.assertEqual(code, 0, out)
        item = out["images"][0]
        self.assertEqual((item["transparent"], item["alpha"]), ("chroma", True))
        self.assertEqual(image.png_info(Path(item["path"]).read_bytes())[3], 6)
        prompt = (Path(item["run_dir"]) / "prompt.txt").read_text()
        self.assertIn("가로세로 비율은 2:1 다.", prompt)
        self.assertIn("#00FF00", prompt)

    def test_existing_links_are_taken_names(self):
        # 끊어진 링크도 쓰인 이름이다. 링크를 따라 출력 폴더 밖에 쓰지 않고 다음 이름(-v2)에 둔다
        out = self.proj / "assets/x"
        out.mkdir(parents=True)
        outside = self.tmp / "outside.png"
        (out / "picture-1.png").symlink_to(outside)
        code, res = self.image("--out", "assets/x", "picture")
        self.assertEqual(code, 0, res)
        self.assertEqual(Path(res["images"][0]["path"]).name, "picture-1-v2.png")
        self.assertFalse(outside.exists())
        self.assertTrue((out / "picture-1.png").is_symlink())
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["picture-1-v2.png", "picture-1.png"])

    def test_out_folder_link_is_refused(self):
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        (self.proj / "assets").mkdir()
        (self.proj / "assets/y").symlink_to(elsewhere)
        code, out = self.image("--out", "assets/y", "picture")
        self.assertEqual((code, out["error"]["code"]), (2, "usage"), out)
        self.assertEqual(list(elsewhere.iterdir()), [])
        self.assertEqual(self.argvs(self.tmp), [])  # codex 를 부르기 전에 막는다

    def test_symlink_result_is_refused(self):
        code, out = self.image("picture", mode="link")
        self.assertEqual((code, out["images"][0]["status"]), (1, "failed"), out)
        self.assertIn("심볼릭 링크", out["images"][0]["reason"])
        self.assertEqual(sorted(self.proj.glob("generated/*")), [])

    def test_undecodable_png_is_a_failure(self):
        # CRC 가 맞는 머리·꼬리에 풀리지 않는 IDAT: 게시하지 않고(sips 로 다시 쓰지 못하면) 그 이미지의 실패다
        self.png.write_bytes(png_raw((1, 1, 8, 2, 0), idat=b"not zlib"))
        code, out = self.image("picture")
        self.assertEqual((code, out["images"][0]["status"]), (1, "failed"), out)
        self.assertIn("PNG 로 바꾸지 못했다", out["images"][0]["reason"])
        self.assertEqual(sorted(self.proj.glob("generated/*")), [])

    def test_user_browser_server_is_off_for_images(self):
        # 사용자(설정·플러그인)에 같은 이름 chrome-devtools 가 켜져 있으면 이미지 실행에서만 끈다(Codex 계획 r2). 정의를
        # 통째로(같은 transport 키 + enabled=false) 준다: 일부 키만 주면 플러그인 정의에 "invalid transport", url 정의에
        # command 를 주면 "url is not supported for stdio" 로 codex 가 시작하지 못한다(codex-cli 0.166 에서 확인)
        for kind, want in (("stdio", 'mcp_servers.chrome-devtools={command="npx",enabled=false}'),
                           ("url", 'mcp_servers.chrome-devtools={url="http://127.0.0.1:9/mcp",enabled=false}')):
            with self.subTest(kind=kind):
                (self.tmp / "argv.jsonl").unlink(missing_ok=True)
                code, out = self.image("--out", f"assets/{kind}", "picture", FAKE_USER_MCP=kind)
                self.assertEqual(code, 0, out)
                [argv] = self.argvs(self.tmp)
                self.assertEqual(argv[argv.index(want) - 1], "-c")
        (self.tmp / "argv.jsonl").unlink()
        self.assertEqual(self.image("--out", "assets/none", "picture")[0], 0)
        self.assertFalse([a for a in self.argvs(self.tmp)[0] if "chrome-devtools" in a])  # 없으면 아무것도 더하지 않는다

    def test_non_image_result_is_a_failure(self):
        self.png.write_text("not an image\n")
        code, out = self.image("picture")
        self.assertEqual((code, out["images"][0]["status"]), (1, "failed"), out)
        self.assertIn("PNG 로 바꾸지 못했다", out["images"][0]["reason"])
        self.assertEqual(sorted(self.proj.glob("generated/*")), [])

    @unittest.skipUnless(shutil.which("sips"), "sips 필요(macOS)")
    def test_non_png_is_converted_with_sips(self):
        jpeg = self.tmp / "made.jpg"
        subprocess.run(["sips", "-s", "format", "jpeg", str(self.png), "--out", str(jpeg)], capture_output=True, check=True)
        self.png = jpeg
        code, out = self.image("--out", "assets/j", "picture")
        self.assertEqual(code, 0, out)
        item = out["images"][0]
        self.assertEqual((Path(item["path"]).name, item["width"], item["height"]), ("picture-1.png", 8, 4))
        self.assertTrue(any("sips" in w for w in item["warnings"]))
        self.assertEqual(sorted(p.name for p in (self.proj / "assets/j").iterdir()), ["picture-1.png"])

    def test_missing_terminal_event_warns_without_none(self):
        code, out = self.image("picture", mode="noevent")
        self.assertEqual(code, 0, out)
        [warning] = out["images"][0]["warnings"]
        self.assertIn("종단 이벤트가 없음 인데", warning)
        self.assertNotIn("None", warning)

    def test_refusal_is_not_retried(self):
        code, out = self.image("--n", "2", "picture", mode="refuse")
        self.assertEqual((code, out["error"]["code"]), (1, "image_failed"), out)
        self.assertEqual([x["status"] for x in out["images"]], ["refused", "refused"])
        self.assertIn("정책상 만들 수 없다", out["images"][0]["result"])
        self.assertEqual(len(self.argvs(self.tmp)), 2)  # 이미지마다 한 번, 다시 하지 않는다

    def test_missing_path_is_a_failure(self):
        code, out = self.image("picture", mode="nopath")
        self.assertEqual((code, out["images"][0]["status"]), (1, "failed"), out)
        self.assertIn("경로가 없다", out["images"][0]["reason"])

    def test_hung_wrapper_is_stopped(self):
        # 래퍼가 멈춰도(여기서는 codex --version 이 끝나지 않고 버전 대기가 길다) hteam image 는 timeout + 여유
        # (HTEAM_IMAGE_GRACE) 뒤 래퍼를 끝내고 그 이미지를 실패로 낸다. 래퍼의 trap 이 버전 조회 그룹을 끝낸다
        start = time.monotonic()
        # 래퍼의 버전 조회 대기 칸이 준비 신호(vpids)를 기다리고(FAKE_SLEEP_GATE), 상한(4 + 1초)은 셸 대역이 준비를 쓰기에
        # 넉넉하다(느린 기계에서 준비 전에 끝내지 않는다)
        code, out = self.image("--timeout", "4", "picture", FAKE_VERSION_HANG="1", HTEAM_CODEX_VERSION_WAIT="600",
                               HTEAM_IMAGE_GRACE="1", FAKE_SLEEP_GATE=str(self.tmp / "vpids.json"))
        self.assertEqual((code, out["error"]["code"]), (1, "image_failed"), out)
        self.assertEqual(out["images"][0]["status"], "failed")
        self.assertIn("끝나지 않아", out["images"][0]["reason"])
        self.assertLess(time.monotonic() - start, 60)
        self.assert_group_gone(self.recorded(self.tmp, "vpids.json"))

    def test_preflight_and_usage(self):
        code, out = self.image("picture", FAKE_NO_IMAGE="1")
        self.assertEqual((code, out["error"]["code"]), (12, "no_image_generation"), out)
        self.assertEqual(self.argvs(self.tmp), [])
        for args in (("--n", "9", "x"), ("--ar", "wide", "x"), ("--ref", "nope.png", "x"), ("--timeout", "1", "x")):
            with self.subTest(args=args):
                self.assertEqual(self.image(*args)[0], 2)


class PublishTest(unittest.TestCase):
    """게시는 검사한 폴더의 fd 기준이다(Codex 계획 r2 P1: 검사 뒤 폴더 이름이 링크로 바뀌어도 원래 폴더에 쓴다)."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="hteam-pub-")).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_publish_uses_the_folder_fd(self):
        out, elsewhere = self.root / "out", self.root / "elsewhere"
        out.mkdir()
        elsewhere.mkdir()
        dfd = os.open(out, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.addCleanup(os.close, dfd)
        out.rename(self.root / "out.old")
        out.symlink_to(elsewhere)  # 검사 뒤 같은 이름이 밖을 가리키는 링크가 됐다
        (self.root / "out.old" / "s.png").symlink_to(self.root / "nowhere.png")  # 끊어진 링크도 쓰인 이름이다
        self.assertEqual(image._publish(b"png", dfd, "s"), "s-v2.png")
        self.assertEqual((self.root / "out.old" / "s-v2.png").read_bytes(), b"png")
        self.assertEqual(list(elsewhere.iterdir()), [])
        self.assertFalse((self.root / "nowhere.png").exists())
        self.assertEqual(sorted(p.name for p in (self.root / "out.old").iterdir()), ["s-v2.png", "s.png"])

    def test_read_does_not_wait_on_a_fifo(self):
        # 결과 경로가 검사 뒤 FIFO 로 바뀌어도 열기에서 기다리지 않고(O_NONBLOCK) 일반 파일이 아니라고 실패한다
        fifo = self.root / "result.png"
        os.mkfifo(fifo)
        done = []

        def read():
            try:
                image._read(fifo)
            except OSError as exc:
                done.append(exc)
        th = threading.Thread(target=read, daemon=True)
        th.start()
        th.join(10)
        self.assertFalse(th.is_alive(), "FIFO 를 열며 멈췄다")
        self.assertTrue(done and "일반 파일" in str(done[0]), done)


class ImageLoopTest(TeamCase):
    """이미지 하나의 예상 가능한 오류는 그 이미지의 실패다. 앞의 결과를 지키고 나머지를 계속한다(설계 12장)."""

    warn = None

    def setUp(self):
        super().setUp()
        self.init_project()
        self.p = Project(self.proj)

    def run_image(self, effects):
        ok = {"status": "ok", "path": str(self.proj / "assets/a.png"), "warnings": []}
        side = [dict(ok, i=n + 1) if e == "ok" else e for n, e in enumerate(effects)]
        with mock.patch.object(image, "preflight", return_value=None), mock.patch.object(image.browser, "user_off", return_value=([], self.warn)), \
                mock.patch.object(image, "one", side_effect=side) as one:
            try:
                return image.image(self.p, "x", n=len(effects), out=str(self.proj / "assets"), ar=None,
                                   transparent=False, refs=[], timeout=60), one
            except HteamError as exc:
                return exc, one
            except KeyboardInterrupt:  # 그대로 나오면 테스트 실행 전체가 멈춘다
                self.fail("KeyboardInterrupt 가 그대로 나왔다")

    def test_one_error_does_not_hide_the_others(self):
        exc, one = self.run_image(["ok", OSError("디스크가 찼다"), "ok"])
        self.assertEqual((exc.code, one.call_count), ("image_failed", 3))
        items = exc.data["images"]
        self.assertEqual([x["status"] for x in items], ["ok", "failed", "ok"])
        self.assertIn("디스크가 찼다", items[1]["reason"])
        self.assertEqual(exc.data["count"], 2)

    def test_codex_missing_keeps_what_was_made(self):
        # Codex 계획 r2: 실행 중 래퍼가 exit 12(codex 없음)면 그 오류 그대로 멈추되 앞서 만든 이미지 목록을 붙인다
        from hteam.errors import MISSING
        exc, one = self.run_image(["ok", HteamError("codex_missing", "codex 가 PATH 에 없다", MISSING), "ok"])
        self.assertEqual((exc.code, exc.exit_code, one.call_count), ("codex_missing", 12, 2))
        self.assertEqual(([x["status"] for x in exc.data["images"]], exc.data["count"]), (["ok"], 1))
        self.assertEqual(exc.data["out"], str(self.proj / "assets"))

    def test_browser_query_warning_is_kept(self):
        # 사용자 chrome-devtools 를 확인하지 못하면 끄지 않고 결과 warnings 에 남긴다(이미지는 계속 만든다)
        self.warn = "사용자 Codex 의 chrome-devtools 서버를 확인하지 못해 끄지 않았다(시간 초과)"
        result, one = self.run_image(["ok"])
        self.assertEqual((result["count"], result["warnings"]), (1, [self.warn]))

    def image_with(self, args, **kw):
        ok = {"status": "ok", "path": str(self.proj / "assets/a.png"), "warnings": [], "i": 1}
        with mock.patch.object(image, "preflight", return_value=None) as pre, mock.patch.object(image, "one", return_value=ok), \
                mock.patch.object(image.config.Config, "args", return_value=args):
            return image.image(self.p, "x", n=1, out=str(self.proj / "assets"), ar=None, transparent=False, refs=[],
                               timeout=60), pre

    def test_run_args_reach_preflight_and_user_off(self):
        # Codex 78e7b59 P2: 거른 실행 인자(MCP 정의·우회·exec 가 받지 않는 인자를 뺀 것)를 사전 점검과 사용자 서버 조회에 넘긴다
        args = ["--enable=image_generation", "--search", "-c", 'mcp_servers.hteam-browser={command="npx"}', "-c", "a=1"]
        with mock.patch.object(image.browser, "user_off", return_value=([], None)) as off:
            result, pre = self.image_with(args)
        kept = ["--enable=image_generation", "-c", "a=1"]
        pre.assert_called_once_with(kept)
        off.assert_called_once_with(self.p.root, kept)
        self.assertEqual(result["warnings"], ["이미지 실행(codex exec)이 받지 않거나 이미지가 직접 정하는 인자를 뺐다: --search"])

    def test_preflight_skip_warning_is_kept(self):
        warn = "프로필이 있어 image_generation 사전 확인을 건너뛰었다"
        with mock.patch.object(image.browser, "user_off", return_value=([], None)), \
                mock.patch.object(image, "preflight", return_value=warn), \
                mock.patch.object(image, "one", return_value={"status": "ok", "path": "p", "warnings": [], "i": 1}):
            result = image.image(self.p, "x", n=1, out=str(self.proj / "assets"), ar=None, transparent=False, refs=[], timeout=60)
        self.assertEqual(result["warnings"], [warn])

    def test_profile_warning_is_kept(self):
        # 프로필(-p)이 있으면 user_off 는 조회를 믿지 않고 끄지 않는다. 그 경고가 결과 warnings 에 남는다(Codex 78e7b59 P2)
        result, _ = self.image_with(["--profile", "p"])
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("프로필이 있어", result["warnings"][0])

    def test_memory_error_is_an_image_failure(self):
        exc, one = self.run_image(["ok", MemoryError(), OverflowError("too big")])
        self.assertEqual((exc.code, one.call_count), ("image_failed", 3))
        self.assertEqual([x["status"] for x in exc.data["images"]], ["ok", "failed", "failed"])

    def test_interrupt_returns_what_was_made(self):
        exc, one = self.run_image(["ok", KeyboardInterrupt(), "ok"])
        self.assertEqual((exc.code, one.call_count), ("image_interrupted", 2))
        self.assertEqual([x["status"] for x in exc.data["images"]], ["ok"])


class ImageSkillTest(unittest.TestCase):
    def test_skill_runs_hteam_image_within_the_bash_limit(self):
        text = (ROOT / "skills/image/SKILL.md").read_text(encoding="utf-8")
        # 포그라운드 최악 시간이 Bash 600초 안에 든다: 기능 조회 30 + codex mcp get 15 + timeout 450 + GRACE 30 +
        # max(래퍼를 끝내는 STOP_WAIT 15, PNG 변환 sips 60: 둘은 함께 일어나지 않는다) = 585
        self.assertEqual(30 + browser.QUERY_TIMEOUT + 450 + image.GRACE + max(image.STOP_WAIT, 60), 585)
        for needle in ("name: image", ".herdr-team/bin/hteam image", "--timeout 450", "30 + 15 + 450 + 30 + 60 = 585",
                       "`--n` 이 1 이고", "run_in_background: true",
                       "`refused`", "Read 로 하나씩 직접 연다", "### 이미지", "`--background` 는 hteam 에 넘기지 않는다"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
