"""규칙 참조 시험(설계 11.9, 13단계): 템플릿·코드 글의 §N 인용이 규칙 파일의 절·항목을 가리킨다.

대상 규칙 파일은 인용 앞(같은 줄)에 나온 마지막 규칙 파일 이름(design-rules·text-rules·web-rules)이다. 없으면 파일마다
기본 대상이다: text-rules.md·review-text.md·textlint.py 는 text-rules, web-rules.md 는 web-rules, 그 밖은 design-rules.
앞에 이름이 없고 인용 바로 뒤 괄호에 규칙 파일 이름이 있으면(`§1 의 8번(text-rules.md)`) 그 파일이다. 바로 앞에 `orca` 가 붙은
인용(`orca §17`, orca-team 설계의 절)은 다른 문서라 보지 않는다. 범위(`§2–§6`)는 그 사이 절을
모두 본다. 규칙 파일의 `## §N` 제목 줄은 인용이 아니다.
"""
from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tests.helpers import ROOT

RULES = {"design-rules": "design-rules.md", "text-rules": "text-rules.md", "web-rules": "web-rules.md"}
CITE = re.compile(r"§(\d+)(?:\.(\d+))?(?:\s*[–-]\s*§?(\d+))?(?:\s*의\s*(\d+)번?)?")
NAME = re.compile(r"(design-rules|text-rules|web-rules)")
OTHER_DOC = re.compile(r"orca\s*$")  # 다른 문서의 절 번호(orca-team 설계)
LATER = re.compile(r"\s*\(\s*`?\.?(?:herdr-team/)?(design-rules|text-rules|web-rules)")  # 인용 바로 뒤 괄호의 파일 이름
FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")


def default_target(rel: str) -> str:
    name = rel.rsplit("/", 1)[-1]
    if name in ("text-rules.md", "review-text.md", "textlint.py"):
        return "text-rules"
    if name == "web-rules.md":
        return "web-rules"
    return "design-rules"


def parse_rules(path: Path) -> dict[int, set[int]]:
    """`## §N` 절마다 그 안의 번호 항목(줄 머리 `M. `). 펜스 코드 블록 안은 보지 않는다."""
    out: dict[int, set[int]] = {}
    cur, fence = None, None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = FENCE.match(line)
        if m:
            mark = m.group(1)
            if fence is None:
                fence = mark
            elif re.fullmatch(re.escape(fence[0]) + "{" + str(len(fence)) + ",}", line.strip()):
                fence = None
            continue
        if fence:
            continue
        h = re.match(r"## §(\d+)\b", line)
        if h:
            cur = int(h.group(1))
            out[cur] = set()
            continue
        if line.startswith("## "):
            cur = None
            continue
        item = re.match(r"(\d+)\. ", line)
        if item and cur is not None:
            out[cur].add(int(item.group(1)))
    return out


def problems(root: Path, stats: dict | None = None) -> list[str]:
    """인용 문제 목록. stats 를 주면 본 파일 수(files)와 인용 수(cites)를 담는다(시험이 아무것도 안 본 채 통과하지 않게)."""
    tpl = root / "templates"
    rules = {k: parse_rules(tpl / v) for k, v in RULES.items() if (tpl / v).is_file()}
    files = sorted(tpl.rglob("*.md")) + sorted((root / "lib" / "hteam").glob("*.py")) + sorted((root / "hooks").glob("*.py"))
    found = []
    cites = 0
    for f in files:
        rel = f.relative_to(root).as_posix()
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if line.startswith("## §"):
                continue
            for m in CITE.finditer(line):
                before = line[:m.start()]
                if OTHER_DOC.search(before):
                    continue
                cites += 1
                names = NAME.findall(before)
                later = LATER.match(line[m.end():])
                target = names[-1] if names else (later.group(1) if later else default_target(rel))
                sec = rules.get(target)
                if sec is None:
                    found.append(f"{rel}:{n}: {RULES[target]} 가 없다: {m.group(0)}")
                    continue
                a, dot, b, item = (int(x) if x else None for x in m.groups())
                item = item if item is not None else dot
                for s in range(a, (b if b is not None else a) + 1):
                    if s not in sec:
                        found.append(f"{rel}:{n}: {RULES[target]} 에 §{s} 가 없다: {m.group(0)}")
                if item is not None and a in sec and item not in sec[a]:
                    found.append(f"{rel}:{n}: {RULES[target]} §{a} 에 {item}번이 없다: {m.group(0)}")
    if stats is not None:
        stats.update(files=len(files), cites=cites)
    return found


METHOD = re.compile(r"(?: \[(?:기계|렌더|판단)\])+$")


def _methods(path: Path) -> tuple[dict[tuple[int, int], set[str]], dict[str, set[tuple[int, int]]], list[str]]:
    """한 규칙 파일의 (번호 항목 → 표기, 자동 검사 절이 가리키는 항목을 가리키는 규칙 파일별로, 표기가 없는 항목의 문제)."""
    name = path.name
    own = default_target(name)
    items: dict[tuple[int, int], set[str]] = {}
    auto: dict[str, set[tuple[int, int]]] = {}
    found = []
    cur, in_auto, fence = None, False, None
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        m = FENCE.match(line)
        if m:
            if fence is None:
                fence = m.group(1)
            elif re.fullmatch(re.escape(fence[0]) + "{" + str(len(fence)) + ",}", line.strip()):
                fence = None
            continue
        if fence:
            continue
        h = re.match(r"## §(\d+)\b", line)
        if h:
            cur, in_auto = int(h.group(1)), False
            continue
        if line.startswith("## "):
            cur, in_auto = None, line.strip() == "## 자동 검사"
            continue
        if in_auto:
            for c in CITE.finditer(line):
                if c.group(4):
                    names = NAME.findall(line[:c.start()])
                    later = LATER.match(line[c.end():])
                    target = names[-1] if names else (later.group(1) if later else own)
                    auto.setdefault(target, set()).add((int(c.group(1)), int(c.group(4))))
            continue
        item = re.match(r"(\d+)\. ", line)
        if item and cur is not None:
            tag = METHOD.search(line.rstrip())
            if not tag:
                found.append(f"{name}:{n}: 검사 방식 표기가 없다: §{cur} 의 {item.group(1)}")
            items[(cur, int(item.group(1)))] = set(re.findall(r"기계|렌더|판단", tag.group(0))) if tag else set()
    return items, auto, found


def method_problems(*paths: Path) -> list[str]:
    """검사 방식 표기(설계 11.9): 규칙 파일마다 `## §N` 절의 번호 항목 끝에 [기계]·[렌더]·[판단] 이 하나 이상 있다. 주어진
    파일들의 `## 자동 검사` 절이 `§N 의 M` 으로 가리키는 항목은 [기계] 이고, [기계] 항목은 모두 어느 자동 검사 절이 가리킨다.
    인용이 가리키는 파일은 problems 와 같이 고른다(같은 줄 앞의 마지막 규칙 파일 이름, 인용 바로 뒤 괄호의 이름, 없으면 그 파일의
    기본 대상): design-rules 의 자동 검사 절이 `web-rules §5 의 1` 처럼 web-rules 의 항목을 가리킨다(13단계 p13d). 주어지지
    않은 파일을 가리키는 인용은 보지 않는다(그 항목이 있는지는 problems 가 본다). 펜스 코드 블록 안은 보지 않는다."""
    parsed = [(path.name, default_target(path.name), *_methods(path)) for path in paths]
    cited: dict[str, set[tuple[int, int]]] = {}
    for _, _, _, auto, _ in parsed:
        for target, keys in auto.items():
            cited.setdefault(target, set()).update(keys)
    found = []
    for name, own, items, _, missing in parsed:
        found += missing
        mine = cited.get(own, set())
        for key in sorted(mine):
            if key not in items:
                found.append(f"{name}: 자동 검사 절이 가리키는 항목이 없다: §{key[0]} 의 {key[1]}")
            elif "기계" not in items[key]:
                found.append(f"{name}: 자동 검사 절이 가리키는 항목이 [기계] 가 아니다: §{key[0]} 의 {key[1]}")
        for key, tags in sorted(items.items()):
            if "기계" in tags and key not in mine:
                found.append(f"{name}: 자동 검사 절이 가리키지 않는 [기계] 항목: §{key[0]} 의 {key[1]}")
    return found


class RuleRefTest(unittest.TestCase):
    def test_templates_and_code_cite_existing_rules(self):
        stats: dict = {}
        self.assertEqual(problems(ROOT, stats), [])
        self.assertGreater(stats["files"], 0)  # 경로가 틀려 아무것도 보지 않은 채 통과하지 않는다
        self.assertGreater(stats["cites"], 0)

    def test_rule_items_have_check_methods(self):
        checked = [ROOT / "templates" / name for name in ("design-rules.md", "web-rules.md")]
        for path in checked:
            self.assertTrue(path.is_file(), path.name)  # 13단계 p13d: 웹 규칙도 본다
        self.assertEqual(method_problems(*checked), [])

    def test_method_checker_follows_auto_citations_into_other_rule_files(self):
        # 13단계 p13d(설계 11.9, 13장): design-rules 의 자동 검사 절이 web-rules 항목을 가리킨다. 그 항목도 [기계] 여야 하고
        # web-rules 의 [기계] 항목은 어느 자동 검사 절이 가리켜야 한다. 같은 줄 앞의 마지막 규칙 파일 이름이 대상이다
        with tempfile.TemporaryDirectory() as tmp:
            design, web = Path(tmp) / "design-rules.md", Path(tmp) / "web-rules.md"
            design.write_text("# 규칙\n\n## §1 금지\n1. 하나 [기계]\n2. 둘 [판단]\n\n## 자동 검사\n"
                              "- §1 의 1(하나), web-rules §5 의 1·web-rules §5 의 2, web-rules §6 의 9\n", encoding="utf-8")
            web.write_text("# 웹\n\n## §5 움직임\n1. 하나 [기계]\n2. 둘 [판단]\n3. 셋 [기계] [판단]\n\n## §6 성능\n1. 하나 [판단]\n",
                           encoding="utf-8")
            self.assertEqual(method_problems(design, web), [
                "web-rules.md: 자동 검사 절이 가리키는 항목이 [기계] 가 아니다: §5 의 2",
                "web-rules.md: 자동 검사 절이 가리키는 항목이 없다: §6 의 9",
                "web-rules.md: 자동 검사 절이 가리키지 않는 [기계] 항목: §5 의 3",
            ])
            self.assertEqual(method_problems(design), [])  # 주어지지 않은 파일을 가리키는 인용은 보지 않는다

    def test_method_checker_catches_missing_and_mismatched_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "design-rules.md"
            path.write_text("# 규칙\n\n## §1 금지\n1. 하나 [기계]\n2. 둘 [판단]\n3. 셋\n4. 넷 [렌더] [판단]\n"
                            "5. 다섯 [기계] [판단]\n```\n6. 펜스 안\n```\n\n## 자동 검사\n- §1 의 1(하나), §1 의 2(둘), §1 의 9\n",
                            encoding="utf-8")
            self.assertEqual(method_problems(path), [
                "design-rules.md:6: 검사 방식 표기가 없다: §1 의 3",
                "design-rules.md: 자동 검사 절이 가리키는 항목이 [기계] 가 아니다: §1 의 2",
                "design-rules.md: 자동 검사 절이 가리키는 항목이 없다: §1 의 9",
                "design-rules.md: 자동 검사 절이 가리키지 않는 [기계] 항목: §1 의 5",
            ])

    def test_checker_catches_broken_citations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "templates" / "roles").mkdir(parents=True)
            (root / "lib" / "hteam").mkdir(parents=True)
            (root / "hooks").mkdir()
            (root / "templates" / "design-rules.md").write_text(
                "# 디자인 규칙\n\n## §1 금지\n1. 하나\n2. 둘\n\n```\n3. 펜스 안은 항목이 아니다\n```\n\n## §2 접근성\n1. 하나\n"
                "\n## §4 글자\n1. 하나\n",
                encoding="utf-8")
            (root / "templates" / "text-rules.md").write_text("# 문구\n\n## §1 보존\n1. 하나\n", encoding="utf-8")
            (root / "templates" / "roles" / "designer.md").write_text(
                "- §1 의 2번, §2 의 1번, §1–§2 는 있다\n- §1 의 3번은 없다\n- §9 는 없다\n- text-rules §1 의 4번은 없다\n"
                "- §1.2 는 있다\n- §2–§4 는 가운데 §3 이 빠졌다\n- §1 의 8번(text-rules.md) 은 없다\n",
                encoding="utf-8")
            (root / "lib" / "hteam" / "x.py").write_text(
                '"""orca §17 은 다른 문서다. 이름 없는 §9 도 본다. design-rules §5 는 없다."""\n', encoding="utf-8")
            self.assertEqual(problems(root), [
                "templates/roles/designer.md:2: design-rules.md §1 에 3번이 없다: §1 의 3번",
                "templates/roles/designer.md:3: design-rules.md 에 §9 가 없다: §9",
                "templates/roles/designer.md:4: text-rules.md §1 에 4번이 없다: §1 의 4번",
                "templates/roles/designer.md:6: design-rules.md 에 §3 가 없다: §2–§4",
                "templates/roles/designer.md:6: design-rules.md 에 §3 가 없다: §3",
                "templates/roles/designer.md:7: text-rules.md §1 에 8번이 없다: §1 의 8번",
                "lib/hteam/x.py:1: design-rules.md 에 §9 가 없다: §9",
                "lib/hteam/x.py:1: design-rules.md 에 §5 가 없다: §5",
            ])
