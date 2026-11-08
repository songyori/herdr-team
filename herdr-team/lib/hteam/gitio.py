"""git 호출. 커밋은 늘 경로를 지정한다(설계 5.5): `git add -- <경로>` 와 `git commit -- <경로>`."""
from __future__ import annotations

import os
import subprocess
import time

from .errors import FAIL, MISSING, HteamError
from .util import env_float


# 작업 트리를 직접 stat 하게 한다. core.fsmonitor 훅이 "바뀐 것 없음" 이라고 답하면 git diff·status·ls-files 가 stat 을
# 건너뛰어 변경을 놓친다(리뷰어도 .git/config 를 쓸 수 있다). 변조 기준점·검사가 기대는 조회에 붙인다.
NO_FSMONITOR = ("-c", "core.fsmonitor=false")

# 경로를 최상위 기준으로 받는 diff·status 조회에 붙인다. 사용자·리뷰어가 diff.relative=true 를 두면 `git diff` 가
# 프로젝트 기준 경로만 내고 밖을 숨긴다(.git/config 는 리뷰어도 쓸 수 있다). `--no-relative` 는 git 2.28 부터라 -c 로 끈다.
# 같은 조회가 fsmonitor 에 속지 않게 NO_FSMONITOR 도 붙인다.
ABSOLUTE = ("-c", "diff.relative=false", *NO_FSMONITOR)

# 읽기만 하는 `git status` 조회의 환경(설계 5.7): status 가 index 를 새로 쓰며 index.lock 을 쥐지 않게 한다. hteam test 는
# 워커가 자주 부르므로 같은 폴더에서 일하는 다른 워커의 커밋을 실패시키지 않게 한다. `git diff` 에는 효과가 없다
# (diff 는 상태 정보가 바뀌면 이 변수와 관계없이 index 를 새로 쓴다). 그래서 테스트 관문은 status 기반 modified_tracked 를 쓴다
READ_ONLY = {"GIT_OPTIONAL_LOCKS": "0"}


def _name(args: tuple[str, ...]) -> str:
    """오류 메시지의 git 하위 명령(앞의 `-c 이름=값` 은 건너뛴다)."""
    i = 0
    while i + 1 < len(args) and args[i] == "-c":
        i += 2
    return args[i] if i < len(args) else ""


def run(root, *args: str, check: bool = True, input: str | bytes | None = None,
        raw: bool = False, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """raw 면 입출력을 바이트로 둔다(파일명이 UTF-8 이 아닐 수 있는 출력은 부르는 쪽이 os.fsdecode 로 푼다. input 도
    바이트로 준다). env 는 지금 환경에 더할 변수다(READ_ONLY 등)."""
    try:
        proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=not raw, input=input,
                              timeout=120, env={**os.environ, **env} if env else None)
    except FileNotFoundError:
        raise HteamError("git_missing", "git 이 없다", MISSING) from None
    except subprocess.TimeoutExpired:
        raise HteamError("git_timeout", f"git {_name(args)} 이 120초 안에 끝나지 않았다", FAIL) from None
    if check and proc.returncode != 0:
        err = proc.stderr or proc.stdout
        if raw:
            err = err.decode("utf-8", "replace")
        # index.lock 은 git 의 긴 안내문 앞에 나와 300자로 자르면 사라질 수 있다. 자르기 전에 표시한다(_wait_index).
        # 다른 git 이 쥐고 있을 때(`Unable to create '…/index.lock': File exists.` 이거나 실패 직후 잠금 파일이 있을 때)만
        # 표시한다. 권한 오류 등은 기다려도 풀리지 않는다. gettext 를 켠 git 은 로캘에 따라 그 문구를 번역하므로 잠금
        # 파일을 직접 본다(LC_ALL=C 로 부르지 않는다: git commit 이 돌리는 사용자 훅이 그 로캘을 물려받는다)
        held = "index.lock" in err and ("File exists" in err or _index_locked(root))
        raise HteamError("git_failed", f"git {_name(args)} 실패: {err.strip()[-300:]}", FAIL,
                         data={"index_lock": True} if held else None)
    return proc


def _index_locked(root) -> bool:
    """root 의 index 잠금 파일(`git rev-parse --git-path index` + `.lock`: 일반 저장소·worktree·GIT_INDEX_FILE 을 git 이
    푼다)이 지금 있나. 실패한 git 뒤에만 부른다. 조회가 실패하면 False(부르는 쪽은 영어 문구로만 가른다). 번역된
    로캘에서 실패와 이 확인 사이에 다른 git 이 잠금을 풀면 기다리지 않고 git_failed 다(드물고 안전한 쪽이다)."""
    try:
        proc = run(root, "rev-parse", "--git-path", "index", check=False, raw=True)
    except HteamError:
        return False
    if proc.returncode != 0 or not proc.stdout.strip():
        return False
    return os.path.lexists(os.path.join(os.fsdecode(root), _out_line(proc.stdout) + ".lock"))  # 상대 경로는 root 기준


def _zb(data: bytes) -> list[str]:
    """NUL 로 나눈 git 출력(바이트) → 경로. os.fsdecode(surrogateescape)로 푼다: UTF-8 이 아닌 이름도 손실 없이 남고
    text 모드처럼 \\r 을 줄바꿈으로 바꾸지 않는다. 그대로 argv 로 넘기면 같은 바이트가 된다."""
    return [os.fsdecode(x) for x in data.split(b"\0") if x]


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
    out = run(root, "log", "--reverse", "--format=%H%x1f%s%x1e", f"{base}..HEAD", raw=True).stdout
    pairs = []
    for rec in out.split(b"\x1e"):
        rec = rec.strip(b"\n")
        if rec:
            sha, _, subject = rec.partition(b"\x1f")
            # 제목은 `[T-xxx]` 접두사만 본다. UTF-8 이 아닌 제목도 실패하지 않게 바꿔 읽는다
            pairs.append((sha.decode("ascii"), subject.decode("utf-8", "replace")))
    return pairs


def _against(root, sha: str) -> tuple[str, ...]:
    """diff-tree 가 견줄 대상: 병합 커밋은 첫 부모와(기본 diff-tree 는 병합에 빈 목록·합친 diff 를 낸다), 그 밖은 부모와
    (뿌리 커밋은 --root 로 빈 트리와)."""
    parents = run(root, "rev-list", "--parents", "-n", "1", sha).stdout.split()[1:]
    return (parents[0], sha) if len(parents) > 1 else ("--no-commit-id", "--root", sha)


def commit_files(root, sha: str) -> list[str]:
    """커밋이 바꾼 경로(최상위 기준). 병합 커밋은 첫 부모와 견준다. 이름 바꾸기는 옛 경로와 새 경로를 다 낸다."""
    args = ("diff-tree", "--name-only", "-r", "-z", "--no-renames", *_against(root, sha))
    return _zb(run(root, *ABSOLUTE, *args, raw=True).stdout)


def diff_lines(root, shas: list[str], rel: str) -> tuple[list[str], list[str]] | None:
    """커밋들(shas)이 파일 rel(root 기준, `../` 가능)에서 (추가한 줄, 지운 줄) 내용. 커밋을 걸쳐 합친 멀티셋이다(설계 11.7).

    부모는 commit_files 와 같다. `-U0` diff 의 hunk(`@@`) 안 `+`·`-` 줄만 모은다: `diff --git` 에서 hunk 상태를 끄므로
    `+++`·`---` 머리는 빠지고 내용이 `++` 로 시작하는 줄은 남는다. CRLF 파일의 줄 끝 \\r 은 뗀다(지금 파일은 read_text 가
    줄바꿈을 바꿔 읽는다). 경로는 `:(top,literal)` 로 넘긴다(`[id]` 같은 이름이 glob 으로 풀리지 않게). git 이 실패하거나
    출력이 UTF-8 이 아니면 None(그 파일 검사만 건너뛴다)."""
    spec = f":(top,literal){to_top(top_prefix(root), rel)}"
    added: list[str] = []
    removed: list[str] = []
    for sha in shas:
        try:
            out = run(root, *ABSOLUTE, "diff-tree", "-r", "-p", "-U0", "--no-color", "--no-ext-diff", "--no-textconv",
                      "--no-renames", *_against(root, sha), "--", spec, raw=True).stdout.decode("utf-8")
        except (HteamError, UnicodeDecodeError):
            return None
        hunk = False
        for line in out.split("\n"):
            if line.startswith("diff --git "):
                hunk = False
            elif line.startswith("@@"):
                hunk = True
            elif hunk and line[:1] in ("+", "-"):
                (added if line[0] == "+" else removed).append(line[1:].removesuffix("\r"))
    return added, removed


def added_lines(root, shas: list[str], rel: str) -> set[str] | None:
    """diff_lines 의 추가한 줄 집합. None 이면 None."""
    lines = diff_lines(root, shas, rel)
    return None if lines is None else set(lines[0])


def diff_names(root, a: str, b: str) -> list[str]:
    """a 와 b 사이에 바뀐 경로(최상위 기준, 저장소 전체). 이름 바꾸기는 양쪽 경로를 다 낸다."""
    return _zb(run(root, *ABSOLUTE, "diff", "--name-only", "-z", "--no-renames", a, b, raw=True).stdout)


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
              *pathspecs, raw=True, env=READ_ONLY).stdout
    entries, found = _zb(out), []
    i = 0
    while i < len(entries):
        entry = entries[i]
        found.append(entry[3:])
        i += 2 if entry[:1] in ("R", "C") else 1  # 이름 바꾸기는 다음 칸이 옛 이름이다
    return found


def status_codes(root, path: str) -> list[str]:
    """root 기준 경로 path(글자 그대로)의 `git status --porcelain=v1` 항목의 XY 두 글자. 비면 깨끗하다(추적하지 않는 새 파일은
    `??`). upgrade 가 커밋하지 않은 변경·삭제를 덮어쓰지 않게 본다(설계 9.6)."""
    out = run(root, *ABSOLUTE, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames", "--",
              literal(path), raw=True, env=READ_ONLY).stdout
    return [entry[:2] for entry in _zb(out)]


def tracked(root, path: str) -> bool:
    """path(root 기준, 글자 그대로)가 인덱스에 있나(`git ls-files --error-unmatch`)."""
    return run(root, "ls-files", "--error-unmatch", "--", literal(path), check=False).returncode == 0


def diff_stat(root, paths: list[str]) -> str:
    """paths 의 `git diff --stat`(앞뒤 공백을 뗀 것). 경로가 없거나 git 이 실패하면 빈 문자열."""
    if not paths:
        return ""
    proc = run(root, "diff", "--stat", "--", *[literal(x) for x in paths], check=False)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def file_mode(root) -> bool:
    """git 이 실행 비트를 보는가(core.fileMode, 없으면 true). false 면 git 처럼 변조 검사도 실행 비트를 보지 않는다."""
    return run(root, "config", "--bool", "core.fileMode", check=False).stdout.strip() != "false"


def modified_tracked(root) -> list[str]:
    """HEAD 와 다른 추적 파일(작업 트리나 인덱스 어느 한쪽이라도, 추적하지 않는 파일 제외), 최상위 기준, 저장소 전체.
    status 기반이라 GIT_OPTIONAL_LOCKS=0 으로 index 를 쓰지 않는다(tracked_changes 의 git diff 는 쓴다). 변조 검사처럼
    fileMode·ignoreStat 을 고정해 견주지 않는다: 보여 주는 용도다."""
    out = run(root, *ABSOLUTE, "status", "--porcelain=v1", "-z", "--untracked-files=no", "--no-renames",
              raw=True, env=READ_ONLY).stdout
    return sorted({entry[3:] for entry in _zb(out)})


def tracked_changes(root, exec_bit: bool | None = None) -> list[str]:
    """HEAD 와 다른 추적 파일(작업 트리나 인덱스 어느 한쪽이라도), 최상위 기준, 저장소 전체. 이름 바꾸기는 양쪽 경로를
    다 낸다(`git mv 제품 제외경로` 가 옛 경로를 숨기지 못하게). `git diff HEAD` 는 작업 트리만 HEAD 와 견주므로
    스테이징한 뒤 작업 트리만 되돌린 변경은 `diff --cached` 로 더한다. exec_bit 를 주면 core.fileMode 를 그 값으로
    고정해 견준다(리뷰 동안 바뀐 설정이 실행 비트 변경을 숨기지 못하게). core.ignoreStat 은 끈다(이 조회가 항목에
    assume-unchanged 를 새로 붙이지 않게). 이미 붙은 숨김 플래그는 git diff 가 보지 않으므로 changed_entries 가 따로 본다."""
    flags = (*ABSOLUTE, "-c", "core.ignoreStat=false",
             *(() if exec_bit is None else ("-c", f"core.fileMode={'true' if exec_bit else 'false'}")))
    work = _zb(run(root, *flags, "diff", "--name-only", "-z", "--no-renames", "HEAD", raw=True, env=READ_ONLY).stdout)
    staged = _zb(run(root, *flags, "diff", "--cached", "--name-only", "-z", "--no-renames", "HEAD", raw=True,
                     env=READ_ONLY).stdout)
    return sorted(set(work) | set(staged))


def _entry(mode: str, oid: str) -> str:
    """git 항목 `모드:객체 ID`. 트리·인덱스의 모드는 core.fileMode 와 상관없이 그대로다(설정은 작업 트리만 본다)."""
    return f"{mode}:{oid}"


def index_read(root) -> tuple[dict[str, str], set[str]]:
    """인덱스 전체를 한 번 읽는다(`:(top)`, root 가 하위 폴더여도 저장소 전체): (최상위 기준 경로 → 항목 `모드:객체 ID`,
    숨김 플래그가 붙은 경로). 충돌 중이라 단계가 여럿이면 `단계:모드:ID` 를 쉼표로 잇는다(어느 항목과도 같지 않다).
    숨김 플래그는 `ls-files -v` 의 소문자 태그(assume-unchanged, core.ignoreStat 이 붙인 것도)와 `S`(skip-worktree)다:
    git diff·status 는 그런 파일의 작업 트리 변경을 보지 않는다. 바이트로 읽고 os.fsdecode 로 푼다(UTF-8 이 아닌 이름도
    손실 없이, 다른 git 출력과 같은 글자로)."""
    out = run(root, *NO_FSMONITOR, "ls-files", "-s", "-v", "-z", "--full-name", "--", ":(top)", raw=True).stdout
    found: dict[str, list[str]] = {}
    hidden: set[str] = set()
    for entry in (x for x in out.split(b"\0") if x):
        meta, _, raw_name = entry.partition(b"\t")
        tag, mode, sha, stage = meta.decode("ascii").split()
        name, item = os.fsdecode(raw_name), _entry(mode, sha)
        found.setdefault(name, []).append(item if stage == "0" else f"{stage}:{item}")
        if tag.islower() or tag == "S":
            hidden.add(name)
    return {name: ",".join(items) for name, items in found.items()}, hidden


def index_entries(root, paths: list[str]) -> dict[str, str | None]:
    """최상위 기준 경로(글자 그대로)의 인덱스 항목 `모드:객체 ID`(tree_entry·worktree_entries 와 견줄 수 있다). 인덱스에
    없으면 None. 경로를 argv 로 넘기면 대량 변경에서 ARG_MAX 를 넘으므로 인덱스 전체를 한 번 읽어 거른다(index_read)."""
    if not paths:
        return {}
    entries, _ = index_read(root)
    return {x: entries.get(x) for x in paths}


def changed_entries(root, exec_bit: bool, inside=None, top: str | None = None) -> tuple[dict[str, str | None],
                                                                                      dict[str, str | None]]:
    """커밋하지 않은 변경의 (작업 트리 항목, 인덱스 항목), 둘 다 최상위 기준 경로 → 항목. 대상은 HEAD 와 다른 추적 파일
    (tracked_changes, 저장소 전체)과, git diff 가 보지 않는 것: 숨김 플래그가 붙은 파일과 서브모듈(gitlink) 가운데 작업
    트리 항목이 인덱스 항목과 다른 것이다(작업 트리를 직접 해시한다. 리뷰어가 플래그나 diff.ignoreSubmodules 로 변경을
    숨기지 못하게). inside(최상위 기준 경로 → 참·거짓)를 주면 숨김 파일·서브모듈은 그것이 참인 경로만 본다(sparse
    checkout 의 skip-worktree 파일은 아주 많을 수 있다). 인덱스는 한 번만 읽는다. top 은 이미 아는 git 최상위다."""
    entries, hidden = index_read(root)
    top = toplevel(root) if top is None else top
    changed = set(tracked_changes(root, exec_bit))
    extra = sorted(x for x in hidden | {x for x, e in entries.items() if e.startswith("160000:")}
                   if x not in changed and (inside is None or inside(x)))
    paths = sorted(changed) + extra
    index = {x: entries.get(x) for x in paths}
    work = worktree_entries(top, paths, exec_bit, index, top=top, prefix="")
    for x in extra:
        if work[x] == index[x]:  # 그대로다
            del work[x], index[x]
    return work, index


def untracked(root) -> list[str]:
    """root 아래의 추적하지 않는 파일(무시 규칙 적용), root 기준."""
    return sorted(_zb(run(root, *NO_FSMONITOR, "ls-files", "--others", "--exclude-standard", "-z", raw=True).stdout))


def tree_entry(root, commit: str, path: str) -> str | None:
    """commit 의 path(git 최상위 기준, 글자 그대로) 항목 `모드:객체 ID`. 없다고 확인되면 None. git 이 읽지 못하면(잘못된
    리비전, 손상·권한) git_failed 다. `rev-parse commit:path` 는 둘을 같은 exit 1 로 내서 ls-tree 를 쓴다."""
    out = run(root, "ls-tree", "-z", "--full-tree", commit, "--", literal(path), raw=True).stdout
    for entry in _zb(out):
        meta, _, name = entry.partition("\t")
        if name == path:
            mode, _, oid = meta.split()
            return _entry(mode, oid)
    return None


def blob(root, commit: str, path: str) -> str | None:
    """commit 의 path 객체 ID(없으면 None). tree_entry 의 ID 부분이다."""
    found = tree_entry(root, commit, path)
    return found.split(":", 1)[1] if found else None


def _ref_present(root, ref: str) -> bool:
    """ref 가 느슨한 파일이나 packed-refs 로 존재하는가(깨졌어도). 버전에 기대지 않는다."""
    from pathlib import Path
    loose = _out_line(run(root, "rev-parse", "--git-path", ref, raw=True).stdout)
    if (Path(root) / loose).exists():  # git -C 기준 상대 경로이므로 root 에 붙인다(절대 경로면 그대로)
        return True
    listed = run(root, "for-each-ref", "--format=%(refname)", ref).stdout.split()
    return ref in listed


def head_file(root, top_path: str) -> str | None:
    """HEAD 에 커밋된 파일(git 최상위 기준 경로)의 내용. `git cat-file -e` 가 실패하면(파일 없음, 커밋 없음) None.
    있으면 `git show` 로 읽는다(index 를 잠그지 않는다). git 오류는 git_failed, UTF-8 이 아니면 UnicodeDecodeError."""
    if run(root, "cat-file", "-e", f"HEAD:{top_path}", check=False).returncode != 0:
        return None
    return run(root, "show", f"HEAD:{top_path}", raw=True).stdout.decode("utf-8")


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


def _out_line(data: bytes) -> str:
    """git 이 한 줄로 내는 경로(바이트) → 글자. 출력 구분자인 마지막 LF 하나만 지우고 os.fsdecode 로 푼다(이름의 \\r·끝
    공백·UTF-8 이 아닌 바이트는 그대로)."""
    return os.fsdecode(data[:-1] if data.endswith(b"\n") else data)


def top_prefix(root) -> str:
    """root 의 git 최상위 기준 경로(`sub/` 꼴, 최상위면 빈 문자열). root 기준 경로를 blob 에 넘길 때 앞에 붙인다.
    바이트로 읽는다(text 모드는 폴더 이름의 \\r 을 \\n 으로 바꿔 프로젝트 안 경로를 밖으로 잘못 나눈다)."""
    return _out_line(run(root, "rev-parse", "--show-prefix", raw=True).stdout)


def is_ancestor(root, a: str, b: str) -> bool:
    args = ("merge-base", "--is-ancestor", a, b)
    return _yes_no(run(root, *args, check=False), args)


def _lock_deadline() -> float:
    return time.monotonic() + env_float("HTEAM_GIT_LOCK_WAIT", 10.0)


def _wait_index(root, *args: str, deadline: float | None = None) -> None:
    """index 를 쓰는 git 명령. 같은 폴더의 다른 git(워커의 커밋)이 index.lock 을 쥔 순간이면 잠깐 기다렸다 다시 한다.
    잠금을 얻지 못해 실패한 add·commit·rm 은 아무것도 바꾸지 않았으므로 다시 해도 된다. HTEAM_GIT_LOCK_WAIT 초(기본 10)
    안에 풀리지 않으면 git_failed 와 할 일을 알린다. deadline 을 주면 그 마감을 쓴다(여러 명령이 한 번의 대기를 나눠 쓴다)."""
    if deadline is None:
        deadline = _lock_deadline()
    while True:
        try:
            run(root, *args)
            return
        except HteamError as exc:
            if not exc.data.get("index_lock"):
                raise
            if time.monotonic() >= deadline:
                exc.hint = ("다른 git 명령(같은 폴더에서 일하는 워커의 커밋 등)이 `.git/index.lock` 을 쥐고 있다. 끝난 뒤 같은 "
                            "명령을 다시 한다. git 이 돌지 않는데도 남아 있으면 메인에 알린다(직접 지우지 않는다)")
                raise
            time.sleep(0.2)


def commit_paths(root, paths: list[str], subject: str, body: str | None = None) -> str:
    """경로 지정 커밋. 다른 워커가 스테이징한 파일을 담지 않는다. 경로의 `*?[` 가 glob 으로 읽히지 않게 literal 로 넘긴다.
    다른 git 이 index.lock 을 쥐고 있으면 잠깐 기다린다(_wait_index)."""
    named = [literal(p) for p in paths]
    deadline = _lock_deadline()  # add 와 commit 이 마감 하나를 나눠 쓴다(합쳐 HTEAM_GIT_LOCK_WAIT 초)
    _wait_index(root, "add", "--", *named, deadline=deadline)
    args = ["commit", "-q", "-m", subject]
    if body:
        args += ["-m", body]
    _wait_index(root, *args, "--", *named, deadline=deadline)
    return head(root)


def unstage(root, paths: list[str]) -> None:
    """HEAD 에 없는 새 파일을 인덱스에서만 뺀다(작업 트리 파일은 그대로). 인덱스에 없으면 넘어간다."""
    _wait_index(root, "rm", "--cached", "-q", "-f", "--ignore-unmatch", "--", *[literal(p) for p in paths])


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


def toplevel(root) -> str:
    """git 최상위 폴더(git 이 낸 실제 경로)."""
    return _out_line(run(root, "rev-parse", "--show-toplevel", raw=True).stdout)


def _through_link(top: str, full: str) -> bool:
    """full 의 상위 폴더(top 아래) 가운데 심볼릭 링크가 있나. 있으면 git 은 그 파일을 없는 것으로 본다."""
    cur = top
    for part in os.path.relpath(full, top).split(os.sep)[:-1]:
        if part == "..":
            return False  # 저장소 밖(git 경로에서는 나오지 않는다)
        cur = os.path.join(cur, part)
        if os.path.islink(cur):
            return True
    return False


def _submodule_changes(top: str, exec_bit: bool) -> str:
    """서브모듈 작업 트리(top) 안의 커밋하지 않은 변경(changed_entries: 작업 트리·인덱스, 숨김 플래그, 안의 서브모듈)의
    요약. 없으면 빈 문자열, 있으면 `+` 와 그 항목들의 해시다(HEAD 가 같아도 안에서 바뀔 때마다 값이 달라진다)."""
    import hashlib
    work, index = changed_entries(top, exec_bit, top=top)
    for x in [x for x, e in work.items() if e is not None and e.startswith("160000:") and e == index.get(x)
              and e == tree_entry(top, "HEAD", x)]:
        # 안의 서브모듈이 작업 트리·인덱스·HEAD 가 모두 같다(diff.ignoreSubmodules=none 이면 미추적 산출물만으로도 git diff 가
        # 그 경로를 낸다). 추적 항목이 바뀐 것이 없으므로 요약에 넣지 않는다
        del work[x]
    if not work:
        return ""
    items = repr(sorted((x, work[x], index[x]) for x in work))
    return "+" + hashlib.sha1(items.encode("utf-8", "backslashreplace")).hexdigest()


def worktree_entries(root, paths: list[str], exec_bit: bool = True, index: dict[str, str | None] | None = None,
                     top: str | None = None, prefix: str | None = None) -> dict[str, str | None]:
    """root 기준 경로(`../` 포함)의 작업 트리 항목 `모드:객체 ID`(tree_entry·index_entries 와 견줄 수 있다). 없으면 None.

    git 이 보는 대로 본다. 심볼릭 링크는 따라가지 않는다: 120000 과 링크 글자의 blob 이다. 상위 폴더가 링크면 git 처럼
    그 파일은 없다. 일반 파일은 실행 비트로 100755·100644 와 git 필터를 적용한 hash-object 다. exec_bit 가 거짓이면
    (core.fileMode=false) git 처럼 실행 비트를 믿지 않고 index(root 기준 경로 → 인덱스 항목)의 모드를 쓴다(없거나
    충돌 중이면 100644). 폴더는 그 자리가 서브모듈 작업 트리면 160000 과 그 HEAD(안에 커밋하지 않은 변경이 있으면
    `+해시` 를 붙인다, _submodule_changes), 아니면 `dir`. 그 밖(FIFO 등)은 `other`.
    lstat 할 수 없는 경로(권한, 파일 시스템이 거부하는 이름)는 없는 것이다.
    hash-object 는 최상위에서 최상위 기준 경로를 argv 로 넘겨 부른다(`--stdin-paths` 는 줄 끝 \\r 을 지우고 `"` 로
    시작하면 따옴표를 풀며, 절대 경로는 .gitattributes 의 필터가 맞지 않는다). ARG_MAX 를 넘지 않게 나눠 부른다.
    top(git 최상위)·prefix(top_prefix)를 이미 알면 넘긴다(git 을 다시 부르지 않는다)."""
    import stat
    result: dict[str, str | None] = dict.fromkeys(paths)
    if not paths:
        return result
    top = toplevel(root) if top is None else top
    prefix = top_prefix(root) if prefix is None else prefix
    regular: list[tuple[str, str, str]] = []  # (root 기준, 최상위 기준, 모드)
    for rel in paths:
        name = to_top(prefix, rel)
        full = os.path.join(top, name)
        if _through_link(top, full):
            continue
        try:
            info = os.lstat(full)
        except OSError:
            continue
        if stat.S_ISLNK(info.st_mode):
            oid = run(top, "hash-object", "--stdin", input=os.readlink(os.fsencode(full)), raw=True).stdout
            result[rel] = f"120000:{oid.decode('ascii').strip()}"
        elif stat.S_ISREG(info.st_mode):
            if exec_bit:
                mode = "100755" if info.st_mode & stat.S_IXUSR else "100644"
            else:
                mode = "100755" if ((index or {}).get(rel) or "").startswith("100755:") else "100644"
            regular.append((rel, name, mode))
        elif stat.S_ISDIR(info.st_mode):
            sub = run(full, "rev-parse", "--show-toplevel", "HEAD", check=False, raw=True)
            lines = sub.stdout.split(b"\n")
            mine = sub.returncode == 0 and len(lines) > 1 and os.fsdecode(lines[0]) == os.path.realpath(full)
            result[rel] = (f"160000:{lines[1].decode('ascii').strip()}"
                           + _submodule_changes(os.fsdecode(lines[0]), exec_bit)) if mine else "dir"
        else:
            result[rel] = "other"
    for i in range(0, len(regular), 500):
        chunk = regular[i:i + 500]
        oids = run(top, "hash-object", "--", *[name for _, name, _ in chunk]).stdout.split()
        for (rel, _, mode), oid in zip(chunk, oids):
            result[rel] = f"{mode}:{oid}"
    return result
