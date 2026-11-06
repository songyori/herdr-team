"""git 호출. 커밋은 늘 경로를 지정한다(설계 5.5): `git add -- <경로>` 와 `git commit -- <경로>`."""
from __future__ import annotations

import os
import subprocess

from .errors import FAIL, MISSING, HteamError


# 경로를 최상위 기준으로 받는 diff·status 조회에 붙인다. 사용자·리뷰어가 diff.relative=true 를 두면 `git diff` 가
# 프로젝트 기준 경로만 내고 밖을 숨긴다(.git/config 는 리뷰어도 쓸 수 있다). `--no-relative` 는 git 2.28 부터라 -c 로 끈다.
ABSOLUTE = ("-c", "diff.relative=false")


def _name(args: tuple[str, ...]) -> str:
    """오류 메시지의 git 하위 명령(앞의 `-c 이름=값` 은 건너뛴다)."""
    i = 0
    while i + 1 < len(args) and args[i] == "-c":
        i += 2
    return args[i] if i < len(args) else ""


def run(root, *args: str, check: bool = True, input: str | None = None, raw: bool = False) -> subprocess.CompletedProcess:
    """raw 면 출력을 바이트로 둔다(파일명이 UTF-8 이 아닐 수 있는 출력을 부르는 쪽이 os.fsdecode 로 푼다)."""
    try:
        proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=not raw, input=input,
                              timeout=120)
    except FileNotFoundError:
        raise HteamError("git_missing", "git 이 없다", MISSING) from None
    except subprocess.TimeoutExpired:
        raise HteamError("git_timeout", f"git {_name(args)} 이 120초 안에 끝나지 않았다", FAIL) from None
    if check and proc.returncode != 0:
        err = proc.stderr or proc.stdout
        if raw:
            err = err.decode("utf-8", "replace")
        raise HteamError("git_failed", f"git {_name(args)} 실패: {err.strip()[-300:]}", FAIL)
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
    """커밋이 바꾼 경로(최상위 기준). 병합 커밋은 첫 부모와 견준다(기본 diff-tree 는 병합에 빈 목록을 낸다).
    이름 바꾸기는 옛 경로와 새 경로를 다 낸다."""
    parents = run(root, "rev-list", "--parents", "-n", "1", sha).stdout.split()[1:]
    if len(parents) > 1:
        args = ("diff-tree", "-r", "--name-only", "-z", "--no-renames", parents[0], sha)
    else:
        args = ("diff-tree", "--no-commit-id", "--name-only", "-r", "-z", "--root", "--no-renames", sha)
    return _z(run(root, *ABSOLUTE, *args).stdout)


def diff_names(root, a: str, b: str) -> list[str]:
    """a 와 b 사이에 바뀐 경로(최상위 기준, 저장소 전체). 이름 바꾸기는 양쪽 경로를 다 낸다."""
    return _z(run(root, *ABSOLUTE, "diff", "--name-only", "-z", "--no-renames", a, b).stdout)


def _yes_no(proc: subprocess.CompletedProcess, args: tuple[str, ...]) -> bool:
    """exit 0 은 예, 1 은 아니오다. 그 밖(잘못된 리비전 128 등)은 답이 아니라 오류다."""
    if proc.returncode not in (0, 1):
        raise HteamError("git_failed", f"git {_name(args)} 실패: {(proc.stderr or proc.stdout).strip()[-300:]}", FAIL)
    return proc.returncode == 0


def differs(root, a: str, b: str, path: str) -> bool:
    """커밋 a 와 b 사이에 path 의 내용이 다른가. path 는 root 기준(`../` 가능)이다. diff.relative=true 면 root 밖
    경로를 "같다"고 답하므로 끈다."""
    args = (*ABSOLUTE, "diff", "--quiet", a, b, "--", literal(path))
    return not _yes_no(run(root, *args, check=False), args)


def dirty(root, pathspecs: list[str]) -> list[str]:
    """pathspecs 안의 커밋하지 않은 변경(추적하지 않는 새 파일 포함) 경로(최상위 기준). 스테이징한 이름 바꾸기는 옛
    경로를 숨기므로 --no-renames 로 양쪽을 다 낸다(git 2.18 이상)."""
    if not pathspecs:
        return []
    out = run(root, *ABSOLUTE, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames", "--",
              *pathspecs).stdout
    entries, found = _z(out), []
    i = 0
    while i < len(entries):
        entry = entries[i]
        found.append(entry[3:])
        i += 2 if entry[:1] in ("R", "C") else 1  # 이름 바꾸기는 다음 칸이 옛 이름이다
    return found


def tracked_changes(root) -> list[str]:
    """HEAD 와 다른 추적 파일(작업 트리나 인덱스 어느 한쪽이라도), 최상위 기준, 저장소 전체. 이름 바꾸기는 양쪽 경로를
    다 낸다(`git mv 제품 제외경로` 가 옛 경로를 숨기지 못하게). `git diff HEAD` 는 작업 트리만 HEAD 와 견주므로
    스테이징한 뒤 작업 트리만 되돌린 변경은 `diff --cached` 로 더한다."""
    work = _z(run(root, *ABSOLUTE, "diff", "--name-only", "-z", "--no-renames", "HEAD").stdout)
    staged = _z(run(root, *ABSOLUTE, "diff", "--cached", "--name-only", "-z", "--no-renames", "HEAD").stdout)
    return sorted(set(work) | set(staged))


def index_blobs(root, paths: list[str]) -> dict[str, str | None]:
    """최상위 기준 경로(글자 그대로)의 인덱스 객체 ID(blob 과 견줄 수 있다). 인덱스에 없으면 None. 충돌 중이라 단계가
    여럿이면 `단계:ID` 를 이어 붙인다(어느 blob 과도 같지 않다). 경로를 argv 로 넘기면 대량 변경에서 ARG_MAX 를
    넘으므로 인덱스 전체(`:(top)`, root 가 하위 폴더여도 저장소 전체)를 한 번 읽어 거른다. 저장소 어딘가의 UTF-8
    이 아닌 파일명이 디코딩 오류를 내지 않게 바이트로 읽고 os.fsdecode(surrogateescape, 손실 없음)로 푼다. UTF-8
    이름은 다른 git 출력(text)과 같은 글자로 풀린다."""
    result: dict[str, str | None] = dict.fromkeys(paths)
    if not paths:
        return result
    out = run(root, "ls-files", "-s", "-z", "--full-name", "--", ":(top)", raw=True).stdout
    found: dict[str, list[str]] = {}
    for entry in (x for x in out.split(b"\0") if x):
        meta, _, name = entry.partition(b"\t")
        _, sha, stage = meta.decode("ascii").split()
        found.setdefault(os.fsdecode(name), []).append(sha if stage == "0" else f"{stage}:{sha}")
    result.update({name: ",".join(shas) for name, shas in found.items() if name in result})
    return result


def untracked(root) -> list[str]:
    """root 아래의 추적하지 않는 파일(무시 규칙 적용), root 기준."""
    return sorted(_z(run(root, "ls-files", "--others", "--exclude-standard", "-z").stdout))


def blob(root, commit: str, path: str) -> str | None:
    """commit 의 path(git 최상위 기준, 글자 그대로) 객체 ID. 없다고 확인되면 None. git 이 읽지 못하면(잘못된 리비전,
    손상·권한) git_failed 다. `rev-parse commit:path` 는 둘을 같은 exit 1 로 내서 ls-tree 를 쓴다."""
    out = run(root, "ls-tree", "-z", "--full-tree", commit, "--", literal(path)).stdout
    for entry in _z(out):
        meta, _, name = entry.partition("\t")
        if name == path:
            return meta.split()[2]
    return None


def _ref_present(root, ref: str) -> bool:
    """ref 가 느슨한 파일이나 packed-refs 로 존재하는가(깨졌어도). 버전에 기대지 않는다."""
    from pathlib import Path
    loose = run(root, "rev-parse", "--git-path", ref).stdout.strip()
    if (Path(root) / loose).exists():  # git -C 기준 상대 경로이므로 root 에 붙인다(절대 경로면 그대로)
        return True
    listed = run(root, "for-each-ref", "--format=%(refname)", ref).stdout.split()
    return ref in listed


def has_head(root) -> bool:
    """커밋이 하나라도 있는가(HEAD 가 태어났는가). 객체는 읽지 않는다.

    HEAD 가 가리키는 브랜치 ref 가 아예 없을 때(unborn)만 False 다. 비거나 깨진 ref 파일(커밋 직후 전원 끊김)도
    `rev-parse --verify` 는 unborn 과 같은 exit 1 이라, `symbolic-ref` 와 `show-ref --exists`(없음 2, 오류 1)로
    가른다. 그 밖에 HEAD 를 풀지 못하면 git_failed 다."""
    args = ("rev-parse", "--verify", "-q", "HEAD")
    if _yes_no(run(root, *args, check=False), args):
        return True
    target = run(root, "symbolic-ref", "-q", "HEAD", check=False)
    if target.returncode == 0:
        ref = target.stdout.strip()
        exists = run(root, "show-ref", "--exists", ref, check=False)
        if exists.returncode == 2:
            return False
        if exists.returncode == 129:
            # git 2.43 미만은 --exists 를 모른다(exit 129). ref 가 있는지(느슨한 파일·packed-refs)로 직접 가른다.
            if not _ref_present(root, ref):
                return False
            detail = "ref 는 있으나 풀리지 않는다"
        else:
            detail = (exists.stderr or exists.stdout).strip()
    else:
        detail = (target.stderr or target.stdout).strip()
    raise HteamError("git_failed", f"HEAD 를 풀지 못했다(비거나 깨진 ref?): {detail[-300:]}", FAIL)


def top_prefix(root) -> str:
    """root 의 git 최상위 기준 경로(`sub/` 꼴, 최상위면 빈 문자열). root 기준 경로를 blob 에 넘길 때 앞에 붙인다."""
    return run(root, "rev-parse", "--show-prefix").stdout.rstrip("\n")


def is_ancestor(root, a: str, b: str) -> bool:
    args = ("merge-base", "--is-ancestor", a, b)
    return _yes_no(run(root, *args, check=False), args)


def commit_paths(root, paths: list[str], subject: str, body: str | None = None) -> str:
    """경로 지정 커밋. 다른 워커가 스테이징한 파일을 담지 않는다. 경로의 `*?[` 가 glob 으로 읽히지 않게 literal 로 넘긴다."""
    named = [literal(p) for p in paths]
    run(root, "add", "--", *named)
    args = ["commit", "-q", "-m", subject]
    if body:
        args += ["-m", body]
    run(root, *args, "--", *named)
    return head(root)


def unstage(root, paths: list[str]) -> None:
    """HEAD 에 없는 새 파일을 인덱스에서만 뺀다(작업 트리 파일은 그대로). 인덱스에 없으면 넘어간다."""
    run(root, "rm", "--cached", "-q", "-f", "--ignore-unmatch", "--", *[literal(p) for p in paths])


def last_commit(root, path: str) -> str | None:
    """path 를 마지막으로 바꾼 커밋. 없으면 None."""
    return run(root, "log", "-1", "--format=%H", "--", literal(path)).stdout.strip() or None


# --- root 가 git 최상위의 하위 폴더일 때(설계 3.4: 프로젝트 루트 ≠ git 최상위일 수 있다) ---
# git 의 diff·diff-tree·status --porcelain 출력과 ls-tree --full-tree 경로는 최상위 기준이고, owns·보고서·리뷰 경로와
# root 에 붙이는 경로는 root 기준이다. 리뷰(사전 검사·기준점·변조 검사)는 아래로 둘 사이를 바꾼다.


def from_top(prefix: str, path: str) -> str:
    """git 최상위 기준 경로 → root 기준(prefix 는 top_prefix(root)). root 밖 경로는 `../` 로 시작한다. owns 는 `..`
    마디를 쓸 수 없으므로(globs.owns_problem) root 밖 경로는 어느 owns 에도 맞지 않는다."""
    if path.startswith(prefix):
        return path[len(prefix):]
    up, parts = prefix.rstrip("/").split("/"), path.split("/")
    same = 0
    while same < len(up) and same < len(parts) - 1 and up[same] == parts[same]:
        same += 1
    return "/".join([".."] * (len(up) - same) + parts[same:])


def to_top(prefix: str, path: str) -> str:
    """from_top 의 반대: root 기준 경로(`../` 포함) → git 최상위 기준. blob 에 넘길 때 쓴다."""
    import posixpath
    return posixpath.normpath(prefix + path) if prefix else path


def hash_files(root, paths: list[str]) -> dict[str, str | None]:
    """root 기준 경로(`../` 포함)의 작업 트리 내용 해시(필터 적용, blob 과 견줄 수 있다). 없는 파일은 None.

    `hash-object --stdin-paths` 는 상대 경로를 git 최상위 기준으로 읽는다(root 가 하위 폴더면 root 기준 경로로는
    다른 파일을 읽거나 실패한다). 그래서 절대 경로로 넘긴다."""
    import os
    full = {x: os.path.normpath(os.path.join(str(root), x)) for x in paths}
    result: dict[str, str | None] = dict.fromkeys(paths)
    present = [x for x in paths if os.path.isfile(full[x])]
    if present:
        hashes = run(root, "hash-object", "--stdin-paths", input="\n".join(full[x] for x in present) + "\n").stdout.split()
        result.update(zip(present, hashes))
    return result
