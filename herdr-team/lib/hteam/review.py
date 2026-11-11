"""교차 리뷰(설계 6.1–6.3): review(사전 검사, 기준점, 시도 기록, 리뷰어 실행·복구), review-finish(정리, 변조 검사, 판정).

경로: owns·보고서·리뷰 파일·시도 기록의 경로는 프로젝트 루트 기준이다. 프로젝트가 git 최상위의 하위 폴더일 수 있어
git 출력(최상위 기준)은 gitio.from_top 으로 바꾸고, 프로젝트 밖 경로는 `../` 로 남긴다. 프로젝트 밖 경로는 어느 owns·
제외 경로에도 들지 않는다: 사전 검사는 그것을 owns 밖으로 지적하고, 변조 검사는 경고로만 남긴다(설계 6.3 3).
blob 에는 gitio.to_top 으로 최상위 기준 경로를 넘긴다.

작업 루트(설계 5.10.2·5.10.4): git 조회·작업 트리 파일(리뷰 결과·반려 파일)·리뷰 커밋·변조 기준점은 그 태스크의 작업 루트
(p.work_root)에서 한다. 들어가는 함수(review·review-finish·새 시도·리뷰어 띄우기)가 태스크 상태로 p 를 다시 묶는다
(workspace.view). 상태·로그·프롬프트는 상태 루트(p.root)다. 작업 공간 태스크가 아니면 두 루트가 같다.

잠금 순서: finish 잠금(state.finish_lock, state/tasks/T-xxx.finish.lock) → 태스크 잠금. 프로젝트 잠금은 쓰지 않는다.
review·review-finish 는 호출 내내, fix·drop 은 취소·정리하는 동안 finish 잠금을 잡는다(설계 6.4).
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import os
import re
from typing import Iterator

from . import compose, config, crew, dispatch, gitio, plan, procs, queue, roles, specs, state, tasks, testgate, workspace
from .errors import CONFLICT, FAIL, USAGE, HteamError
from .globs import covers_tree, matches_any
from .horch import Horch
from .paths import SHIM, find_project, review_rel
from .util import die_at, now, show, write_atomic

AUTO_ATTEMPTS = 2  # 라운드당 자동 시도(설계 6.3 6)
GATE_PROBLEM = "hteam 테스트 관문: quick 이 통과하지 못했다."
# 판정 맞추기(설계 6.3, orca-team align_verdict). 절은 다음 `## `·`VERDICT:`·끝까지다
FINDINGS_RE = re.compile(r"^## 지적 사항[ \t]*\n(.*?)(?=^## |^VERDICT:|\Z)", re.M | re.S)
PRIOR_RE = re.compile(r"^## 이전 지적 확인[ \t]*\n(.*?)(?=^## |^VERDICT:|\Z)", re.M | re.S)
BROAD_P1_RE = re.compile(r"(?<![A-Za-z0-9])P1(?![A-Za-z0-9])", re.I)
NONE_LINE_RE = re.compile(r"^\s*(?:[-+*#]+|\d+[.)])?[\s*#]*(?:해당\s*)?없음")
STRICT_ID_RE = re.compile(r"r\d+-F\d+")
STRICT_GRADE_RE = re.compile(r"\[(P[123])\]", re.I)
STRICT_PRIOR_RE = re.compile(r"^\s*(?:[-+]|\d+[.)])?\s*r\d+-F\d+\s*(?:\[P1\]\s*)?[:：]\s*미해결", re.I)
ADJUST_BASIS = "`## 지적 사항` 의 P1 줄과 `## 이전 지적 확인` 의 미해결 줄 수 기준"
VERDICTS = ("APPROVE", "REQUEST_CHANGES")
# 리뷰 시도를 띄우거나 복구할 수 있는 상태: 첫 시도·복구는 working, 자동 재시도·--retry·그 복구는 reviewing
REVIEW_STATES = frozenset({"working", "reviewing"})


def attempt_slot(k: int):
    def pick(st: dict) -> dict:
        found = next((a for a in st["rounds"][-1]["reviews"] if a["attempt"] == k), None)
        if found is None:  # 그 사이 새 라운드가 생겼다(fix)
            raise HteamError("attempt_missing", f"{st['id']} 현재 라운드에 리뷰 시도 a{k} 가 없다", CONFLICT,
                             "hteam status 로 태스크 상태를 확인한다")
        return found
    return pick


def _check_round(tid: str, rd: dict | None) -> None:
    """fix·drop 이 이 라운드를 닫는 중이다(취소를 저장한 뒤 멈췄거나 진행 중). 리뷰어를 띄우거나 상태를 옮기지 않는다."""
    if rd and (rd["work"].get("canceled") or any(a.get("canceled") for a in rd["reviews"])):
        raise HteamError("round_canceled", f"{tid} r{rd['round']} 의 실행 키가 취소됐다", CONFLICT,
                         "앞선 fix·drop 이 끝나지 않았다. 같은 명령을 다시 한다")


def _rel(prefix: str, paths: list[str]) -> list[str]:
    return [gitio.from_top(prefix, x) for x in paths]


def _outside(path: str) -> bool:
    """프로젝트 폴더 밖 경로(`../`)."""
    return path.startswith("../")


def _covered(path: str, patterns) -> bool:
    """path 가 patterns(프로젝트 기준 owns·제외 경로) 안인가. 프로젝트 밖(`../`) 경로는 늘 밖이다: `**` 로 시작하는
    glob(`**/*.md`)은 `../README.md` 에도 맞으므로 matches_any 에 맡기지 않는다."""
    return not _outside(path) and matches_any(path, patterns)


def target_commits(p, st: dict) -> list[dict]:
    """base 이후 `[T-xxx]` 로 시작하는 커밋. `[T-xxx] review rN:` 은 뺀다(`spec: T-xxx` 는 접두사가 달라 빠진다).
    건드린 경로로 거르지 않는다: 프로젝트 밖만 고친 태스크 커밋도 사전 검사가 owns 밖으로 지적해야 한다. 그래서 같은
    저장소의 여러 herdr-team 프로젝트가 태스크 ID 를 겹쳐 쓰면 사전 검사가 거짓으로 실패한다(지원하지 않음, 설계 6.3 3)."""
    tid = st["id"]
    return [{"sha": sha, "subject": subject} for sha, subject in gitio.log_since(p.work_root, st["base"])
            if subject.startswith(f"[{tid}]") and not subject.startswith(f"[{tid}] review r")]


def changed_files(p, commits: list[dict]) -> list[str]:
    """대상 커밋이 건드린 경로, 프로젝트 기준(프로젝트 밖은 `../`). 병합 커밋은 첫 부모와 견준 경로다."""
    prefix = gitio.top_prefix(p.work_root)
    files: set[str] = set()
    for c in commits:
        files.update(_rel(prefix, gitio.commit_files(p.work_root, c["sha"])))
    return sorted(files)


def prechecks(p, cfg, st: dict, spec, commits: list[dict], files: list[str]) -> list[str]:
    """설계 6.1 4. 하나라도 걸리면 리뷰어를 띄우지 않고 REQUEST_CHANGES."""
    tid = st["id"]
    own = list(st["owns"]) + [f"docs/tasks/{tid}/**"]
    found = []
    if not commits:
        found.append(f"리뷰 대상 커밋이 없다(base 이후 `[{tid}]` 로 시작하는 커밋)")
    outside = [f for f in files if not _covered(f, own) and gitio.differs(p.work_root, st["base"], "HEAD", f)]
    if outside:
        found.append("owns 밖 경로의 내용이 base 와 다르다: " + ", ".join(outside))
    if spec.role == "planner":
        try:
            plan.check(p, cfg, p.work_root / plan.PLAN_FILE)
        except HteamError as exc:
            if exc.code == "plan_incomplete":  # 앞선 plan apply(관제)가 남긴 일이다. 기획자가 고칠 수 없다
                raise HteamError("plan_incomplete", f"{tid} 를 리뷰하기 전에 앞선 plan apply 를 정리해야 한다: {exc.message}",
                                 CONFLICT, f"{exc.hint}. 순서: 메인에 알려 사용자가 사양을 정리한다 → 앞선 것과 같은 "
                                 f"`{SHIM} plan apply`(앞선 것이 --append 였으면 --append)로 plan 을 끝낸다 → 그 뒤 같은 "
                                 f"review 를 다시 한다(`{SHIM} review {tid}`)",
                                 data=exc.data) from None
            detail = "; ".join(exc.data.get("errors") or []) or exc.message
            found.append(f"`{plan.PLAN_FILE}` 가 plan check 를 통과하지 못한다: {detail}")
    # status --porcelain 은 최상위 기준 경로를 낸다(pathspec 은 프로젝트 기준). 이 태스크의 리뷰 폴더는 hteam 이 쓴다:
    # 사전 검사가 rN.md 를 쓴 뒤 커밋 전에 죽었으면 owns(`**/*.md` 등)가 그것을 덮어 다시 셀 때 결과가 바뀐다
    mine = [f"docs/reviews/{tid}/**"]
    dirty = [d for d in _rel(gitio.top_prefix(p.work_root), gitio.dirty(p.work_root, [gitio.glob_spec(o) for o in own]))
             if not matches_any(d, mine)]
    if dirty:
        found.append("owns 안에 커밋하지 않은 변경이 있다: " + ", ".join(dirty))
    return found


def _gate_text(tid: str, n: int, tests: dict, p=None) -> str:
    """테스트 관문 반려 파일(설계 6.1 4a). 명령은 JSON 문자열, 출력 끝은 가변 길이 펜스로 넣는다. 로그 경로는 다음 라운드
    워커가 작업 루트에서 여는 경로다(p, testgate.describe)."""
    quick = tests["quick"]
    tail = f"\n출력 끝:\n{testgate.fenced(quick['tail'])}\n" if quick.get("tail") else ""
    return (f"# {tid} r{n} 리뷰 (출처: hteam 테스트 관문)\n\n리뷰어를 띄우지 않았다. 수정 라운드에서 다음을 고친다.\n\n"
            f"## 지적 사항\n- [P1] {GATE_PROBLEM}\n\n## 테스트 관문\n"
            + "".join(f"- {x}\n" for x in testgate.describe(quick, "quick", p)) + tail
            + f"\n고친 뒤 `{SHIM} test {tid}` 로 다시 확인한다.\n실패가 이 태스크 탓이 아니면(소유 경로 밖 코드, 위의 커밋 안 된 "
            "다른 파일) 코드를 고치지 말고 근거를 보고서에 적은 뒤 프리앰블의 ask 명령으로 묻는다(메인이 답한다).\n\n"
            "VERDICT: REQUEST_CHANGES\n")


def _precheck_fail(p, tid: str, n: int, problems: list[str], tests: dict | None = None,
                   expect: frozenset = frozenset({"working"}), request: str | None = None) -> dict:
    """리뷰어 없이 hteam 이 REQUEST_CHANGES 를 쓴다: 사전 검사(설계 6.1 4)와 테스트 관문(4a, tests 가 있다. --retry 가 다시
    돌린 관문이면 expect 는 reviewing). 라운드를 하나 쓴다."""
    rel = review_rel(tid, n)
    if tests is not None:
        text = _gate_text(tid, n, tests, p)
    else:
        text = (f"# {tid} r{n} 리뷰 (출처: hteam 사전 검사)\n\n리뷰어를 띄우지 않았다. 수정 라운드에서 다음을 고친다.\n\n"
                "## 지적 사항\n" + "".join(f"- [P1] {show(x)}\n" for x in problems) + "\nVERDICT: REQUEST_CHANGES\n")
    write_atomic(p.work_root / rel, text)
    die_at("after_precheck_write")
    if gitio.dirty(p.work_root, [gitio.literal(rel)]):
        sha = gitio.commit_paths(p.work_root, [rel], f"[{tid}] review r{n}: REQUEST_CHANGES")
    else:  # 앞 호출이 같은 내용을 커밋한 뒤 상태를 쓰기 전에 죽었다. 빈 커밋을 만들지 않는다
        sha = gitio.last_commit(p.work_root, rel)
    die_at("after_precheck_commit")
    info = testgate.summary(tests)
    with state.edit(p, tid, expect=expect) as st:
        rd = st["rounds"][-1]
        _check_round(tid, rd)
        rd.update(verdict="REQUEST_CHANGES", review_source="hteam", prechecks=problems)
        if tests is not None:
            rd["tests"] = tests
        state.move(st, "changes", "precheck", **info, **({"request": request} if request else {}))
    return {"task": tid, "round": n, "status": "changes", "verdict": "REQUEST_CHANGES", "source": "hteam",
            "problems": problems, "commit": sha, **info}


def _changes(p, prefix: str, exec_bit: bool) -> tuple[dict[str, str | None], dict[str, str | None]]:
    """프로젝트 기준 경로의 (작업 트리 항목, 인덱스 항목)(gitio.changed_entries 는 최상위 기준이다). 숨김 플래그가 붙은
    파일과 서브모듈은 프로젝트 안만 본다(밖은 경고뿐이고 sparse checkout 의 skip-worktree 파일이 아주 많을 수 있다)."""
    work, index = gitio.changed_entries(p.work_root, exec_bit, inside=lambda top: top.startswith(prefix))
    return ({gitio.from_top(prefix, t): v for t, v in work.items()},
            {gitio.from_top(prefix, t): v for t, v in index.items()})


def baseline(p, tid: str) -> dict:
    """변조 기준점(설계 6.1 5): HEAD, 커밋하지 않은 변경(HEAD 와 다른 추적 파일, 프로젝트 안의 숨김 플래그 파일·서브모듈
    가운데 바뀐 것)의 작업 트리 항목과 인덱스 항목(`모드:객체 ID`), 추적 안 된 파일, 진행 중인 다른 태스크, git 이 작업
    트리의 실행 비트를 보는지(exec_bit, core.fileMode. 거짓이면 작업 트리 파일의 모드는 인덱스의 모드다).
    경로는 프로젝트 기준이다. 추적 파일은 저장소 전체를 본다(프로젝트 밖은 `../`, 리뷰 동안 바뀌면 경고를 내려고).
    추적 안 된 파일은 프로젝트 안만 본다."""
    others = [s["id"] for s in state.all_states(p) if s["id"] != tid and s["status"] in ("working", "launch_failed")]
    prefix = gitio.top_prefix(p.work_root)
    exec_bit = gitio.file_mode(p.work_root)
    dirty, index = _changes(p, prefix, exec_bit)
    return {"at": now(), "head": gitio.head(p.work_root), "exec_bit": exec_bit, "dirty": dirty, "index": index,
            "untracked": gitio.untracked(p.work_root), "in_progress": others}


def tamper_check(p, tid: str, base: dict) -> tuple[dict | None, list[str]]:
    """설계 6.3 3. (변조 기록 또는 None, 경고).

    변조: fast-forward 가 아닌 HEAD 이동, 프로젝트 안 제외 경로 밖의 추적 파일 변경과 커밋. 경고: 프로젝트 안의 추적 안 된
    새 파일, 프로젝트 밖(`../`)에서 바뀐 추적 파일과 커밋(hteam 작업은 owns 밖을 건드리지 않으므로 모노레포의 다른 일이다).
    견주는 값은 git 항목 `모드:객체 ID` 다: 내용이 같아도 심볼릭 링크로 바꾸거나 실행 비트를 바꾸면 변조다. 트리·인덱스의
    모드는 그대로 견주고, 작업 트리의 실행 비트는 기준점 때의 core.fileMode 로 본다(false 면 인덱스의 모드). 프로젝트 안의
    숨김 플래그(assume-unchanged·skip-worktree, core.ignoreStat) 파일과 서브모듈은 git diff 가 보지 않아도 작업 트리를
    직접 해시해 견준다(서브모듈은 HEAD 와 안의 커밋하지 않은 변경). 서브모듈 안의 변경은 항목 하나로 요약된다. 제외
    경로가 서브모듈 경로 자체를 덮으면(그 경로·윗 폴더의 고정 경로나 glob·`**`, _covered) 일반 파일처럼 뺀다(삭제·교체도:
    그 태스크의 일일 수 있다). 그 아래만 덮을 때(`vendor/**`, globs.covers_tree)는 서브모듈로 남은 변경(커밋 이동·안의
    변경, _gitlink_move)만 빼고 삭제·심볼릭 링크나 파일로 바꾸기·모드 변경은 변조다. 일부만 덮으면(`vendor/docs/**`)
    빼지 않는다(거짓 양성은 review --retry 로 푼다). 값이 객체 ID 뿐인 옛 기준점(이 형식 전)에 기록된
    경로는 지금 값과 늘 달라 보인다: 기준점 때 커밋하지 않은 추적 파일 변경이 있었으면 그 경로가 프로젝트 안·제외 경로
    밖일 때 변조로 멈추고(프로젝트 밖이면 경고), 깨끗한 트리에서 만든 옛 기준점은 그대로 끝난다."""
    states = {s["id"]: s for s in state.all_states(p)}
    during = [s["id"] for s in states.values() if s["id"] != tid and any(
        h.get("event") in ("start", "fix") and h.get("at", "") >= base["at"] for h in s.get("history", []))]
    # 같은 작업 루트에서 도는 태스크만 뺀다: 다른 슬롯(또는 메인 폴더와 슬롯 사이)의 워커는 이 작업 트리를 바꾸지 않는다(설계
    # 5.10.4, Codex 커밋 리뷰 b916c8c P1). shared 모드는 모두 메인 폴더다
    excluded_tasks = sorted(t for t in set(base["in_progress"]) | set(during)
                            if workspace.task_root(p, states.get(t, {})) == p.work_root)
    patterns = [".herdr-team/**", "docs/reviews/**", "docs/handoff/**"]  # 인수인계(5.9.7)는 어느 태스크의 일도 아니다
    for t in excluded_tasks:
        patterns += list(states.get(t, {}).get("owns") or []) + [f"docs/tasks/{t}/**"]

    def excluded(path: str) -> bool:
        return _covered(path, patterns)

    prefix = gitio.top_prefix(p.work_root)
    head = gitio.head(p.work_root)
    exec_bit = base.get("exec_bit", True)  # 기준점 때의 core.fileMode 로 고정한다(리뷰어가 설정을 바꿔도)
    record = {"head_before": base["head"], "head_after": head, "excluded_tasks": excluded_tasks}
    if head != base["head"] and not gitio.is_ancestor(p.work_root, base["head"], head):
        return {**record, "reason": "HEAD 가 fast-forward 가 아니게 움직였다", "paths": []}, []
    bad: set[str] = set()
    outside: set[str] = set()
    allowed: set[str] = set()
    if head != base["head"]:
        for sha, subject in gitio.log_since(p.work_root, base["head"]):
            files = _rel(prefix, gitio.commit_files(p.work_root, sha))
            if any(subject.startswith(f"[{t}]") for t in excluded_tasks):
                allowed.update(files)
                continue
            outside.update(f for f in files if _outside(f))
            bad.update(f for f in files if not _outside(f) and not excluded(f))
    now_dirty, now_index = _changes(p, prefix, exec_bit)
    candidates = set(base["dirty"]) | set(now_dirty)
    if head != base["head"]:
        candidates |= set(_rel(prefix, gitio.diff_names(p.work_root, base["head"], head)))
    trees: dict[tuple[str, str], str | None] = {}  # 이 검사 안에서 (커밋, 경로)마다 ls-tree 를 한 번만 부른다
    for path in candidates - allowed:
        if excluded(path):
            continue
        top = gitio.to_top(prefix, path)  # ls-tree --full-tree 는 최상위 기준 경로를 받는다

        def tree(commit: str, top: str = top) -> str | None:
            if (commit, top) not in trees:
                trees[(commit, top)] = gitio.tree_entry(p.work_root, commit, top)
            return trees[(commit, top)]
        before = base["dirty"][path] if path in base["dirty"] else tree(base["head"])
        after = now_dirty[path] if path in now_dirty else tree(head)
        moved = before != after
        if not moved and "index" in base:  # 스테이징한 뒤 작업 트리만 되돌린 변경은 인덱스에만 남는다
            before = base["index"][path] if path in base["index"] else tree(base["head"])
            after = now_index[path] if path in now_index else tree(head)
            moved = before != after
        recorded = [d[path] for d in (base["dirty"], base.get("index", {}), now_dirty, now_index) if path in d]
        if moved and _gitlink_move(before, after, *recorded) and covers_tree(path, patterns):
            continue  # 서브모듈 안의 변경은 항목 하나로 요약된다. 그 아래 전체를 가진 다른 태스크의 일일 수 있다
        if moved:
            (outside if _outside(path) else bad).add(path)
    fresh = {u for u in set(gitio.untracked(p.work_root)) - set(base["untracked"]) if not excluded(u)}
    warnings = sorted(fresh | outside)
    if bad:
        return {**record, "reason": "리뷰 동안 제외 경로 밖 추적 파일이 바뀌었다", "paths": sorted(bad)}, warnings
    return None, warnings


def _gitlink_move(*entries) -> bool:
    """서브모듈이 서브모듈로 남은 채 바뀌었나(커밋 이동·안의 변경): 견준 전·후와 기록된 항목이 모두 gitlink(모드
    160000)다. 하나라도 없거나(삭제) 다른 모드(심볼릭 링크·파일)면 아니다."""
    return bool(entries) and all(isinstance(e, str) and e.startswith("160000:") for e in entries)


def _launch_attempt(p, cfg, h, tid: str, k: int, request: str | None = None) -> dict:
    """프롬프트를 (없으면) 만들고 시작 장벽으로 리뷰어를 띄운 뒤 reviewing 으로 간다(설계 6.1 6–8).

    기록을 쓸 때마다 dispatch.owned 로 이전 상태(REVIEW_STATES)·취소·실행자를 다시 확인한다. 라운드를 고정 에이전트가 맡았으면
    리뷰어를 숨겨 띄운다(--hidden, 6.1 7·6.5 의 1. 보기는 관제의 view_step 이 에이전트 탭 pane 에 연다)."""
    pick = attempt_slot(k)
    st = state.require(p, tid)
    p = workspace.view(p, st)
    rd = st["rounds"][-1]
    att = pick(st)
    if not att.get("reset"):
        # 결과 경로 초기화(설계 6.1 6). 시도 기록 뒤 죽었으면 복구가 여기서 다시 지운다. 초기화는 리뷰어를
        # 띄우기 전에만 하므로(reset 표시) 이미 실행된 시도의 결과 파일은 지우지 않는다
        with dispatch.owned(p, tid, pick, REVIEW_STATES) as cur:
            (p.work_root / att["file"]).unlink(missing_ok=True)
            pick(cur)["reset"] = True
    spec = specs.load(p, tid)
    info = testgate.summary(att["inputs"].get("tests"))  # 출력·history 의 관문 요약(설계 6.1 4a)
    prompt = p.task_dir(tid) / f"r{rd['round']}-review-a{k}.md"
    if not prompt.is_file():
        write_atomic(prompt, compose.review_prompt(p, cfg, spec, rd, att, st["rounds"]))
    # 작업 공간 태스크의 리뷰어는 슬롯의 작업 루트와 슬롯 env 로 뜬다(설계 5.10.4)
    env = workspace.slot_env(cfg, st["workspace"]["slot"]) if st.get("workspace") else None
    res = dispatch.launch(p, h, tid, pick, agent=att["agent"], model=att["model"], effort=att["effort"],
                          args=cfg.args(att["agent"]), spec_file=prompt, expect=REVIEW_STATES,
                          hidden=crew.round_crew(rd) is not None, cwd=p.work_root, env=env)
    try:
        # fix·drop 의 취소·전이가 그 사이 끼었으면 reviewing 으로 두지 않는다(정리는 그쪽이 horch 상태로 한다)
        with dispatch.owned(p, tid, pick, REVIEW_STATES) as cur:
            if res["mode"] == "adopt":  # 실제로 도는 리뷰어에 맞춘다
                pick(cur).update(agent=res["agent"], model=res["model"], effort=res["effort"])
            state.move(cur, "reviewing", "review", attempt=k, dispatch=res["dispatch"], **info,
                       **({"request": request} if request else {}))
    except HteamError as exc:
        dispatch.left_running(exc, res, h)
        raise
    out = {"task": tid, "round": rd["round"], "attempt": k, "status": "reviewing", "reviewer": att["agent"], **res,
           **info}
    if res["mode"] == "adopt" and res.get("state") in ("settled", "retained", "released", "abandoned"):
        out["next"] = [SHIM, "review-finish", tid]
    return out


def _require_open(st: dict, tid: str, k: int) -> dict:
    """review-finish 가 시도 k 로 결정을 쓰기 전에: reviewing 이고, 라운드에 취소가 없고(Task 8 fix·drop 을 되돌리지
    않게), 시도 k 가 아직 결과 없이 열려 있다. 그 시도 기록을 돌려준다."""
    if st["status"] in state.CLOSED:
        raise state.closed_error(st)
    if st["status"] != "reviewing":
        raise HteamError("bad_state", f"{tid} 는 {st['status']} 다(review-finish 는 reviewing 에서)", CONFLICT,
                         data={"status": st["status"]})
    _check_round(tid, st["rounds"][-1])
    att = attempt_slot(k)(st)
    if att.get("result") is not None:
        raise HteamError("attempt_closed", f"{tid} 리뷰 시도 a{k} 가 그 사이 {att['result']} 로 끝났다", CONFLICT,
                         "hteam status 로 태스크 상태를 확인한다")
    return att


@contextlib.contextmanager
def _finish_write(p, tid: str, k: int) -> Iterator[tuple[dict, dict]]:
    """태스크 잠금 아래에서 _require_open 을 다시 본 뒤 (상태, 시도 k) 를 내준다. 블록이 끝나면 저장한다."""
    with state.edit(p, tid, expect={"reviewing"}) as st:
        yield st, _require_open(st, tid, k)


def _new_attempt(p, cfg, h, tid: str, *, commits: list[dict], files: list[str], extra: bool,
                 failed: tuple[int, str, list[str]] | None = None, tests: dict | None = None,
                 request: str | None = None) -> dict:
    """새 시도: 기준점·결과 경로·실행 키·입력(대상 커밋, 바뀐 파일, 관문 결과 tests)을 시도 기록에 먼저 쓴다. 남은 결과 파일은
    지운다(설계 6.1 6). 프롬프트·복구·자동 재시도는 이 입력을 다시 쓴다(관문을 다시 돌리지 않는다).

    failed=(k, 사유, 경고)면 실패한 시도 k 의 결과도 같은 쓰기에 남긴다. 그래서 자동 재시도 사이에 죽어도 열린 시도가
    남고 review 가 그것을 이어 띄운다(설계 6.3 6). 기준점은 git 을 부르므로 잠금 밖에서 만들고, 잠금 안에서 상태를 다시 본다."""
    spec = specs.load(p, tid)
    p = workspace.view(p, state.require(p, tid))
    base = baseline(p, tid)
    with state.edit(p, tid, expect=REVIEW_STATES) as st:
        rd = st["rounds"][-1]
        _check_round(tid, rd)
        if failed is not None:
            fk, reason, warnings = failed
            _require_open(st, tid, fk).update(result="failed", reason=reason, warnings=warnings)
        if state.open_attempt(rd):  # 한 라운드에 끝나지 않은 시도는 하나다
            raise HteamError("review_in_progress", f"{tid} 에 끝나지 않은 리뷰 시도가 있다", CONFLICT,
                             "hteam review T 로 그 시도를 이어 한다")
        choice = config.resolve(cfg, spec.role, spec.front, {"worker": rd["agent"]})
        k = max((a["attempt"] for a in rd["reviews"]), default=0) + 1
        title = roles.review_title(tid, rd["round"], k)
        att = {**dispatch.new_slot(title), "attempt": k, "agent": choice.reviewer, "model": choice.review_model,
               "effort": choice.review_effort, "file": review_rel(tid, rd["round"], k), "baseline": base,
               "inputs": {"commits": commits, "files": files, "tests": tests}, "result": None, "reason": None, "tamper": None,
               "extra": extra, "dispatch_end": None, "verdict_read": None, "verdict_sha": None, "reset": False,
               "warnings": []}
        rd["reviews"].append(att)
        st["launcher"] = {"key": title, **procs.me()}
    if failed is not None:
        die_at("after_fail")
    die_at("after_attempt")
    return _launch_attempt(p, cfg, h, tid, k, request)


def _recover(p, cfg, h, st: dict, att: dict) -> dict:
    """앞 호출이 시도 기록 뒤 죽었다(설계 6.1 0): 사전 검사·새 기준점 없이 저장된 시도로 이어 한다."""
    tid, k = st["id"], att["attempt"]
    if dispatch.busy(st, att):
        raise HteamError("launching", f"{att['title']} 를 띄우는 실행자가 아직 살아 있다", CONFLICT, "나중에 다시 한다")
    if att.get("dispatch"):
        if st["status"] == "working":
            die_at("recover_recorded")
            with state.edit(p, tid, expect={"working"}) as cur:
                _check_round(tid, cur["rounds"][-1])
                slot = attempt_slot(k)(cur)  # 잠긴 상태에서 다시 고른다(그 사이 fix 가 새 라운드를 썼을 수 있다)
                if slot.get("result") is not None or slot.get("dispatch") != att["dispatch"]:
                    raise HteamError("attempt_changed", f"{tid} 리뷰 시도 a{k} 가 그 사이 바뀌었다", CONFLICT,
                                     "hteam status 로 태스크 상태를 확인한다")
                state.move(cur, "reviewing", "review", attempt=k, dispatch=att["dispatch"],
                           **testgate.summary(att["inputs"].get("tests")))
            out = {"task": tid, "attempt": k, "status": "reviewing", "dispatch": att["dispatch"], "mode": "recorded",
                   **testgate.summary(att["inputs"].get("tests"))}
            # 리뷰어가 먼저 끝났으면 그 worker_done(next 가 review 였다)은 다시 오지 않는다. 태스크 잠금 밖에서 본다
            try:
                row, why = dispatch.slot_row(h.workers(), att), "worker-list 에 그 행이 없다"
            except HteamError as exc:
                row, why = None, exc.code
            if row is None:  # 리뷰어가 끝났는지 모른다
                out["warnings"] = [f"리뷰 Dispatch {att['dispatch']} 의 상태를 읽지 못했다({why}). 끝났으면 "
                                   f"review-finish {tid}, 아니면 리뷰어 worker_done 을 기다린다(status 의 next)"]
                return out
            if dispatch.review_ended(row):
                out["next"] = [SHIM, "review-finish", tid]
            return out
        raise HteamError("review_in_progress", f"{tid} 의 리뷰 시도 a{k} 가 진행 중이다", CONFLICT,
                         "리뷰어 worker_done 뒤 hteam review-finish")
    with state.edit(p, tid, expect=REVIEW_STATES) as cur:
        _check_round(tid, cur["rounds"][-1])
        slot = attempt_slot(k)(cur)
        if dispatch.busy(cur, slot):  # 잠금 안에서 다시 본다
            raise HteamError("launching", f"{slot['title']} 를 띄우는 실행자가 아직 살아 있다", CONFLICT,
                             "나중에 다시 한다")
        cur["launcher"] = {"key": slot["title"], **procs.me()}
    return _launch_attempt(p, cfg, h, tid, k)


def review(p, tid: str, retry: bool = False, expect_round: int | None = None, request: str | None = None) -> dict:
    """처음 읽은 라운드로 판정·시도·상태를 쓰므로 호출 내내 finish 잠금을 쥔다(설계 6.4). 라운드를 닫는 fix·drop 의
    취소·정리도 같은 잠금 안에서 하므로, 이 호출이 도는 동안 새 라운드가 생기지 않는다(옛 review 가 새 라운드에
    판정을 쓰지 않는다). 잠금 순서는 finish → 태스크다. review-finish 의 자동 재시도는 이 함수를 거치지 않는다.
    테스트 관문(설계 6.1 4a)도 이 잠금 안에서 돈다(그동안 같은 태스크의 fix·drop·review-finish 는 기다린다. 관제 안의
    fix·drop·review-finish 는 기다리지 않고 review_busy 다, 설계 8.5).

    expect_round·request 는 큐 `review --retry`(설계 7.1): 라운드가 바뀌었으면 round_changed, 새 시도의 history 사건에
    요청 id 를 남긴다."""
    with state.finish_lock(p, tid):
        return _review(p, tid, retry, expect_round, request)


def _review(p, tid: str, retry: bool, expect_round: int | None = None, request: str | None = None) -> dict:
    cfg = config.load(p)
    st = state.require(p, tid)
    tasks._expect_round(tid, st, expect_round)  # 상태보다 먼저: 다른 라운드로 옮겨 갔으면 그 요청은 이미 처리된 것이다
    if st["status"] in state.CLOSED:
        raise state.closed_error(st)  # 무엇보다 먼저, 복구도 하지 않는다
    workspace.require_worktree(p, st)  # 슬롯이 worktree 가 아니면 그 폴더에 쓰거나 커밋하지 않는다
    p = workspace.view(p, st)
    spec = specs.load(p, tid)
    cfg.role(spec.role)
    h = Horch(p.horch_home)
    rd = state.current_round(st)
    _check_round(tid, rd)
    att = state.open_attempt(rd)
    if att and not retry:
        return _recover(p, cfg, h, st, att)
    if retry:
        last = state.latest_attempt(rd)
        if st["status"] != "reviewing" or att or not last or last.get("result") not in ("failed", "tampered"):
            raise HteamError("no_failed_review", f"{tid} 에 실패·무효로 멈춘 리뷰가 없다", CONFLICT,
                             "--retry 는 review_failed·review_tampered 뒤 사용자가 다시 하라고 했을 때만 쓴다")
        commits = target_commits(p, st)
        # 사전 검사는 하지 않는다. 관문은 입력(code_head·식별값·확정 여부)이 바뀌었을 때만 다시 돌린다(설계 6.1)
        tests = testgate.retry_results(p, st, spec.role, commits, (last.get("inputs") or {}).get("tests"))
        if testgate.failed_quick(tests):
            return _precheck_fail(p, tid, rd["round"], [GATE_PROBLEM], tests, expect=frozenset({"reviewing"}),
                                  request=request)
        return _new_attempt(p, cfg, h, tid, commits=commits, files=changed_files(p, commits), extra=True, tests=tests,
                            request=request)
    if st["status"] != "working":
        raise HteamError("bad_state", f"{tid} 는 {st['status']} 다(review 는 working 에서)", CONFLICT,
                         data={"status": st["status"]})
    warnings = []
    did = rd["work"].get("dispatch")
    if did:
        code, data = h.call("worker-retain", "--dispatch", did)  # 리뷰 동안 pane 을 남긴다. 실패해도 계속
        if code:
            warnings.append(f"작업 Dispatch {did} 를 retain 하지 못했다: {(data.get('error') or {}).get('code')}")
    commits = target_commits(p, st)
    files = changed_files(p, commits)
    problems = prechecks(p, cfg, st, spec, commits, files)
    if problems:
        return {**_precheck_fail(p, tid, rd["round"], problems), "warnings": warnings}
    # 테스트 관문(설계 6.1 4a): 사전 검사를 통과한 뒤에만, 상태 전이 전에 돈다. 실행 불가·잠금 대기 초과·중단은 예외로
    # 올라가고 아무것도 쓰지 않는다(working 그대로, 다시 부르면 retain 은 그대로 된다)
    tests = testgate.gate_results(p, st, spec.role, commits)
    if testgate.failed_quick(tests):
        return {**_precheck_fail(p, tid, rd["round"], [GATE_PROBLEM], tests), "warnings": warnings}
    res = _new_attempt(p, cfg, h, tid, commits=commits, files=files, extra=False, tests=tests)
    res["warnings"] = warnings + res.get("warnings", [])
    return res


def _clean(line: str) -> str:
    return line.replace("*", "").replace("`", "")


def broad_count(findings: str, prior: str | None) -> int:
    """넓은 셈(REQUEST_CHANGES → APPROVE 로 내리는 것을 막는 데만): `## 지적 사항` 에서 낱말 P1 이 든 줄과 `## 이전 지적 확인`
    에서 미해결이 든 줄."""
    return (sum(1 for line in findings.splitlines() if BROAD_P1_RE.search(line))
            + sum(1 for line in (prior or "").splitlines() if "미해결" in line))


def strict_count(findings: str, prior: str | None) -> int:
    """엄격한 셈(APPROVE → REQUEST_CHANGES 로 올리는 데만): `*`·백틱을 지운 줄에서 `없음` 줄을 빼고 id(rN-Fk)가 있고 첫
    등급 표시가 [P1] 인 지적 줄, `rN-Fk[ [P1]]: 미해결` 모양의 이전 지적 줄."""
    count = 0
    for line in findings.splitlines():
        line = _clean(line)
        grade = STRICT_GRADE_RE.search(line)
        if not NONE_LINE_RE.match(line) and STRICT_ID_RE.search(line) and grade and grade.group(1).upper() == "P1":
            count += 1
    return count + sum(1 for line in (prior or "").splitlines() if STRICT_PRIOR_RE.match(_clean(line)))


def align_verdict(text: str, verdict: str) -> tuple[str, str, int | None]:
    """(맞춘 내용, 맞춘 판정, 바꿨으면 셈 아니면 None). `## 지적 사항` 이 없으면(형식을 따르지 않은 파일) 그대로다. 같은 내용에
    늘 같은 결과다(복구가 다시 맞춰도 같다). 바꿀 때는 판정 읽기와 같은 마지막 VERDICT 줄 앞에 맞추기 문장과 빈 줄을 끼운다."""
    found = FINDINGS_RE.search(text)
    if not found:
        return text, verdict, None
    prior = PRIOR_RE.search(text)
    prior_text = prior.group(1) if prior else None
    if verdict == "REQUEST_CHANGES" and broad_count(found.group(1), prior_text) == 0:
        want, count = "APPROVE", 0
    elif verdict == "APPROVE" and (count := strict_count(found.group(1), prior_text)) > 0:
        want = "REQUEST_CHANGES"
    else:
        return text, verdict, None
    lines = text.splitlines(keepends=True)
    i = max(n for n, line in enumerate(lines) if line.strip().startswith("VERDICT:"))
    end = lines[i][len(lines[i].rstrip("\r\n")):]
    lines[i] = (f"> hteam 판정 맞추기: 막는 지적(`## 지적 사항` 의 P1 줄, `## 이전 지적 확인` 의 미해결 줄) {count}개라 {want} 로 "
                f"바꿨다(원래 {verdict}).\n\nVERDICT: {want}{end}")
    return "".join(lines), want, count


def _verdict_in(data: bytes) -> tuple[str | None, str | None]:
    """리뷰 파일 바이트의 마지막 `VERDICT:` 줄. UTF-8 이 아니면 시도 실패다(예외로 태스크를 막지 않는다)."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None, "리뷰 파일이 UTF-8 이 아니다"
    lines = [line.strip() for line in text.splitlines() if line.strip().startswith("VERDICT:")]
    if not lines:
        return None, "VERDICT 줄이 없다"
    value = lines[-1].split(":", 1)[1].strip()
    if value not in VERDICTS:
        return None, f"VERDICT 값을 모른다: {value}"
    return value, None


def _read_verdict(p, att: dict) -> tuple[str | None, str | None, dict | None]:
    """(맞춘 판정, 실패 사유, 기록할 값). 파일을 한 번만 읽어 파싱·해시·판정 맞추기(설계 6.3)가 같은 바이트를 본다. 기록할
    값은 원래 바이트의 SHA-1(verdict_sha), 원래 판정(verdict_raw), 맞춘 판정(verdict_read), 맞춘 내용의 SHA-1(final_sha,
    바꾸지 않았으면 verdict_sha), verdict_adjusted("APPROVE→REQUEST_CHANGES" 등, 바꾸지 않았으면 None)다."""
    end = att.get("dispatch_end") or {}
    if end.get("abandoned") or not end.get("outcome"):
        return None, "리뷰어가 done 없이 끝났다", None
    if end["outcome"] == "failed":
        return None, f"리뷰어가 실패로 보고했다: {end.get('summary') or ''}".strip(), None
    path = p.work_root / att["file"]
    if not path.is_file():
        return None, f"리뷰 파일이 없다: {att['file']}", None
    try:
        data = path.read_bytes()
    except OSError as exc:
        return None, f"리뷰 파일을 읽지 못했다: {att['file']}: {exc.strerror or exc}", None
    verdict, reason = _verdict_in(data)
    if verdict is None:
        return None, reason, None
    text, aligned, _ = align_verdict(data.decode("utf-8"), verdict)
    sha = hashlib.sha1(data).hexdigest()
    return aligned, None, {"verdict_read": aligned, "verdict_sha": sha, "verdict_raw": verdict,
                           "final_sha": hashlib.sha1(text.encode("utf-8")).hexdigest() if aligned != verdict else sha,
                           "verdict_adjusted": f"{verdict}→{aligned}" if aligned != verdict else None}


def read_verdict(p, att: dict) -> tuple[str | None, str | None]:
    """이 시도의 파일에서 마지막 `VERDICT:` 줄만 본다(판정 맞추기 뒤). done 없이 끝났거나 failed·읽을 수 없으면 시도 실패."""
    verdict, reason, _ = _read_verdict(p, att)
    return verdict, reason


def _sha(path) -> str | None:
    try:
        return hashlib.sha1(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _evidence(p, att: dict, tid: str, n: int):
    """기록한 판정을 쓸 때: 시도 파일이 있으면 그것이 원래 해시(verdict_sha)와, 없으면(이미 최종화) 최종 rN.md 가 맞춘 내용의
    해시(final_sha, 옛 기록은 verdict_sha)와 같아야 한다.

    (판정, 실패 사유, 검증한 경로). 최종화는 검증한 그 파일만 한다."""
    src = p.work_root / att["file"]
    if src.exists():
        path, want = src, att.get("verdict_sha")
    else:
        path, want = p.work_root / review_rel(tid, n), att.get("final_sha") or att.get("verdict_sha")
    if want and _sha(path) == want:
        return att["verdict_read"], None, path
    return None, "기록한 판정의 리뷰 파일이 없거나 바뀌었다", None


def _cleanup_reviewer(p, h, tid: str, att: dict) -> dict:
    """리뷰 Dispatch 정리(멱등, 설계 6.3 2). 처음 본 종료 증거(상태·outcome·판정)를 먼저 시도 기록에 남기고,
    그 기록을 유지한 채 abandon·release 를 한다. 모두 끝난 뒤에만 cleaned 를 쓴다."""
    k, did = att["attempt"], att["dispatch"]
    row = dispatch.row_by_id(h.workers(), did)
    end = att.get("dispatch_end")
    if end is None:
        end = {"state": None, "outcome": None, "summary": None, "verdict": None, "abandoned": False}
        if row:
            if row["state"] == "launching":
                raise HteamError("launching", f"리뷰 Dispatch {did} 가 아직 launching 이다", CONFLICT)
            if row["state"] == "active" and row.get("verdict") not in ("exited", "lost"):
                raise HteamError("reviewer_running", f"리뷰어 {did} 가 아직 일한다", CONFLICT,
                                 "worker_done 을 기다린다. idle 이면 horch send 로 done 을 요구한다")
            end.update(state=row["state"], outcome=row.get("outcome"), summary=row.get("summary"),
                       verdict=row.get("verdict"), abandoned=row["state"] == "active")
        with _finish_write(p, tid, k) as (_, a):
            a["dispatch_end"] = end
        die_at("after_end")
    s = row["state"] if row else None
    if s == "active":  # 기록된 판정이 exited·lost 다
        h.ok("worker-abandon", "--dispatch", did)
        s = "abandoned"
    if s in ("settled", "retained", "abandoned"):
        h.ok("worker-release", "--dispatch", did)
    with _finish_write(p, tid, k) as (_, a):
        a["cleaned"] = True
        return dict(a)


def _warning_body(warnings: list[str]) -> str | None:
    fresh = [w for w in warnings if not _outside(w)]
    outside = [w for w in warnings if _outside(w)]
    parts = []
    if fresh:
        parts.append("리뷰 동안 생긴 추적하지 않는 새 파일:\n" + "\n".join(f"- {show(w)}" for w in fresh))
    if outside:
        parts.append("리뷰 동안 프로젝트 밖에서 바뀐 추적 파일:\n" + "\n".join(f"- {show(w)}" for w in outside))
    return "\n\n".join(parts) or None


def attempt_error(tid: str, n: int, att: dict) -> HteamError | None:
    """시도 기록의 결과가 실패·변조면 review-finish 가 내는 오류(review_failed·review_tampered), 아니면 None. 관제의
    재확인이 decide 전에 죽은 관제의 시도 결과를 같은 문구로 올린다(설계 8.7)."""
    if att.get("result") == "failed":
        return HteamError("review_failed", f"{tid} r{n} 리뷰 시도가 실패했다: {att.get('reason')}", FAIL,
                          "메인에 묻는다(다시 시도 / 버림). 다시면 hteam review T --retry",
                          data={"attempt": att.get("attempt"), "reason": att.get("reason")})
    if att.get("result") == "tampered":
        tamper = att.get("tamper") or {}
        return HteamError("review_tampered", f"{tid} r{n} 리뷰 중 제품이 바뀌었다: "
                          f"{', '.join(show(x) for x in tamper.get('paths') or []) or tamper.get('reason')}",
                          FAIL, "자동으로 다시 하지 않는다. 메인에 올리고, 사용자가 정리한 뒤 hteam review T --retry",
                          data={"tamper": tamper})
    return None


def review_finish(p, tid: str, nowait: bool = False) -> dict:
    """같은 태스크의 review-finish 는 한 번에 하나만 돈다. 겹치면 옛 시도 정보를 쥔 호출이 이미 옮긴 파일을 못 찾아
    재시도를 띄우는 사이 다른 호출이 승인으로 옮긴다. 잠금은 태스크 잠금보다 먼저 잡는다(fix·drop 의 취소·정리도 같은
    잠금을 잡으므로 이 호출이 끝난 뒤에 취소한다). nowait(관제 안)면 기다리지 않고 review_busy(설계 8.5)."""
    with state.finish_lock(p, tid, nowait=nowait):
        return _finish(p, tid)


def _finish(p, tid: str) -> dict:
    cfg = config.load(p)
    h = Horch(p.horch_home)
    st = state.require(p, tid)
    if st["status"] in state.CLOSED:
        raise state.closed_error(st)
    if st["status"] != "reviewing":
        raise HteamError("bad_state", f"{tid} 는 {st['status']} 다(review-finish 는 reviewing 에서)", CONFLICT,
                         data={"status": st["status"]})
    workspace.require_worktree(p, st)
    p = workspace.view(p, st)
    rd = st["rounds"][-1]
    _check_round(tid, rd)  # 취소된 시도는 열린 시도가 아니다. no_open_review 의 --retry 안내도 여기서 막힌다
    att = state.open_attempt(rd)
    if att is None:
        raise HteamError("no_open_review", f"{tid} 에 끝나지 않은 리뷰 시도가 없다", CONFLICT,
                         "실패·무효로 멈췄으면 메인에 묻고 hteam review T --retry")
    if not att.get("dispatch"):
        raise HteamError("review_not_launched", f"{tid} 리뷰 시도 a{att['attempt']} 가 아직 띄워지지 않았다", CONFLICT,
                         "hteam review T 로 시작을 이어 한다")
    k, n = att["attempt"], rd["round"]
    if not att.get("cleaned"):
        att = _cleanup_reviewer(p, h, tid, att)
    # 변조 검사는 판정을 이미 기록한 복구 호출에서도 최종 전이 전에 늘 다시 한다(설계 6.3 3)
    tamper, warnings = tamper_check(p, tid, att["baseline"])
    if tamper:
        with _finish_write(p, tid, k) as (_, a):
            a.update(tamper=tamper, result="tampered", warnings=warnings)
            err = attempt_error(tid, n, a)
        raise err
    die_at("before_verdict")
    verdict, reason = None, None
    if att.get("verdict_read") is None:
        verdict, reason, record = _read_verdict(p, att)
        if verdict is not None:  # 판정과 그 판정을 읽은 바이트의 해시(맞춘 판정·내용 해시와 함께)를 먼저 남긴다
            with _finish_write(p, tid, k) as (_, a):
                a.update(**record, warnings=warnings)
            die_at("after_verdict")
            att = attempt_slot(k)(state.require(p, tid))
    if att.get("verdict_read") is not None:
        # 처음 호출도 이어 하는 호출도: 시도 파일(이미 옮겼으면 rN.md)이 기록한 해시와 같아야 하고 그 파일만 최종화한다
        verdict, reason, verified = _evidence(p, att, tid, n)
    if verdict is None:
        auto = [a for a in rd["reviews"] if not a.get("extra") and not a.get("canceled")]
        if not att.get("extra") and len(auto) < AUTO_ATTEMPTS:
            res = _new_attempt(p, cfg, h, tid, commits=att["inputs"]["commits"], files=att["inputs"]["files"],
                               extra=False, failed=(k, reason, warnings), tests=att["inputs"].get("tests"))
            return {**res, "retried": True, "failed_attempt": k, "reason": reason}
        with _finish_write(p, tid, k) as (_, a):
            a.update(result="failed", reason=reason, warnings=warnings)
            err = attempt_error(tid, n, a)
        raise err
    final_rel = review_rel(tid, n)
    final = p.work_root / final_rel
    _require_open(state.require(p, tid), tid, k)  # 옮기고 커밋하기 전에 fix·drop 의 취소가 끼었는지 본다
    adjusted = att.get("verdict_adjusted")
    if verified != final:  # 검증한 시도 파일만 최종 파일로 옮긴다(판정을 맞췄으면 같은 바이트로 다시 맞춘 내용을 쓴다)
        if adjusted:
            write_atomic(final, align_verdict(verified.read_bytes().decode("utf-8"), att["verdict_raw"])[0])
        else:
            os.replace(verified, final)
    die_at("after_move")
    for other in (p.work_root / "docs" / "reviews" / tid).glob(f"r{n}-a*.md"):
        other.unlink()
    if gitio.dirty(p.work_root, [gitio.literal(final_rel)]):
        note = f"판정 맞추기: {adjusted}({ADJUST_BASIS})" if adjusted else None
        body = "\n\n".join(x for x in (note, _warning_body(att.get("warnings") or [])) if x) or None
        sha = gitio.commit_paths(p.work_root, [final_rel], f"[{tid}] review r{n}: {verdict}", body)
    else:  # 앞 호출이 커밋한 뒤 상태를 쓰기 전에 죽었다
        sha = gitio.last_commit(p.work_root, final_rel)
    die_at("after_commit")
    to = "approved" if verdict == "APPROVE" else "changes"
    with _finish_write(p, tid, k) as (cur, a):
        a["result"] = verdict
        cur["rounds"][-1]["verdict"] = verdict
        state.move(cur, to, "verdict", attempt=k, verdict=verdict, verdict_adjusted=adjusted)
    return {"task": tid, "round": n, "attempt": k, "verdict": verdict, "status": to, "file": final_rel, "commit": sha,
            "source": att["agent"], "verdict_adjusted": adjusted, "warnings": att.get("warnings") or []}


def _cmd_review(args) -> dict:
    """`review T` 는 관제만, `review T --retry` 는 큐 명령이다(설계 7.1, 8.3). 도움말 없는 --round·--request 는 관제가 띄운
    리뷰 자식만 준다(큐 review --retry 의 라운드 재검사와 재실행 기록, 설계 8.8)."""
    p = find_project(args.root)
    if (args.round is not None or args.request is not None) and not roles.drive_env(p):
        raise HteamError("usage", "--round·--request 는 관제가 띄운 리뷰 자식만 쓴다", USAGE)
    if not args.retry:
        roles.require_drive(p)
        return review(p, args.task, expect_round=args.round, request=args.request)
    return queue.route(p, "review", {"task": args.task, "retry": True},
                       lambda req: review(p, args.task, retry=True, expect_round=args.round, request=args.request),
                       check=lambda: state.require(p, args.task),
                       expect_round=lambda: state.require(p, args.task)["round"])


def _cmd_review_finish(args) -> dict:
    p = find_project(args.root)
    roles.require_drive(p)
    return review_finish(p, args.task, nowait=True)


def register(sub) -> None:
    s = sub.add_parser("review")
    s.add_argument("task")
    s.add_argument("--retry", action="store_true")
    s.add_argument("--round", type=int, help=argparse.SUPPRESS)
    s.add_argument("--request", help=argparse.SUPPRESS)
    s.set_defaults(func=_cmd_review)
    s = sub.add_parser("review-finish")
    s.add_argument("task")
    s.set_defaults(func=_cmd_review_finish)
