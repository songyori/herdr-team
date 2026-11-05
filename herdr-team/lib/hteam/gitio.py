"""git 호출. 커밋은 늘 경로를 지정한다(설계 5.5): `git add -- <경로>` 와 `git commit -- <경로>`."""
from __future__ import annotations

import subprocess

from .errors import FAIL, MISSING, HteamError


def run(root, *args: str, check: bool = True, input: str | None = None) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, input=input,
                              timeout=120)
    except FileNotFoundError:
        raise HteamError("git_missing", "git 이 없다", MISSING) from None
    if check and proc.returncode != 0:
        raise HteamError("git_failed", f"git {args[0]} 실패: {(proc.stderr or proc.stdout).strip()[-300:]}", FAIL)
    return proc


def _z(text: str) -> list[str]:
    return [x for x in text.split("\0") if x]


def head(root) -> str:
    return run(root, "rev-parse", "HEAD").stdout.strip()


def is_repo(root) -> bool:
    return run(root, "rev-parse", "--is-inside-work-tree", check=False).stdout.strip() == "true"


def literal(path: str) -> str:
    return f":(literal){path}"


def glob_spec(pattern: str) -> str:
    """owns glob → git pathspec. git 의 glob magic 도 `**` 는 디렉터리를 넘고 `*` 는 한 마디 안이다."""
    return f":(glob){pattern}"


def log_since(root, base: str) -> list[tuple[str, str]]:
    """base 이후(base 제외) 커밋을 오래된 것부터 (sha, 제목)."""
    out = run(root, "log", "--reverse", "--format=%H%x1f%s%x1e", f"{base}..HEAD").stdout
    pairs = []
    for rec in out.split("\x1e"):
        rec = rec.strip("\n")
        if rec:
            sha, _, subject = rec.partition("\x1f")
            pairs.append((sha, subject))
    return pairs


def commit_files(root, sha: str) -> list[str]:
    return _z(run(root, "diff-tree", "--no-commit-id", "--name-only", "-r", "-z", "--root", sha).stdout)


def diff_names(root, a: str, b: str) -> list[str]:
    return _z(run(root, "diff", "--name-only", "-z", a, b).stdout)


def differs(root, a: str, b: str, path: str) -> bool:
    """커밋 a 와 b 사이에 path 의 내용이 다른가."""
    return run(root, "diff", "--quiet", a, b, "--", literal(path), check=False).returncode == 1


def dirty(root, pathspecs: list[str]) -> list[str]:
    """pathspecs 안의 커밋하지 않은 변경(추적하지 않는 새 파일 포함) 경로."""
    if not pathspecs:
        return []
    out = run(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *pathspecs).stdout
    entries, found = _z(out), []
    i = 0
    while i < len(entries):
        entry = entries[i]
        found.append(entry[3:])
        i += 2 if entry[:1] in ("R", "C") else 1  # 이름 바꾸기는 다음 칸이 옛 이름이다
    return found


def tracked_changes(root) -> list[str]:
    """HEAD 와 다른 추적 파일(스테이징·작업 트리 모두)."""
    return _z(run(root, "diff", "--name-only", "-z", "HEAD").stdout)


def untracked(root) -> list[str]:
    return sorted(_z(run(root, "ls-files", "--others", "--exclude-standard", "-z").stdout))


def hash_paths(root, paths: list[str]) -> dict[str, str | None]:
    """작업 트리 파일 내용 해시. 없는 파일은 None."""
    from pathlib import Path
    result: dict[str, str | None] = {}
    present = [p for p in paths if (Path(root) / p).is_file()]
    for p in paths:
        result[p] = None
    if present:
        hashes = run(root, "hash-object", "--stdin-paths", input="\n".join(present) + "\n").stdout.split()
        result.update(dict(zip(present, hashes)))
    return result


def blob(root, commit: str, path: str) -> str | None:
    proc = run(root, "rev-parse", "--verify", "-q", f"{commit}:{path}", check=False)
    return proc.stdout.strip() if proc.returncode == 0 else None


def is_ancestor(root, a: str, b: str) -> bool:
    return run(root, "merge-base", "--is-ancestor", a, b, check=False).returncode == 0


def commit_paths(root, paths: list[str], subject: str, body: str | None = None) -> str:
    """경로 지정 커밋. 다른 워커가 스테이징한 파일을 담지 않는다."""
    run(root, "add", "--", *paths)
    args = ["commit", "-q", "-m", subject]
    if body:
        args += ["-m", body]
    run(root, *args, "--", *paths)
    return head(root)
