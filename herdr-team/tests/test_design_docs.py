"""디자인 직무 문서(설계 11.1–11.3): director 의 세 단계·질문 형식·산출물, scaffold, 설정."""
import json
import re
import unittest

from tests.helpers import ROOT
from hteam import outbox
from hteam.globs import within

DIRECTOR = ROOT / "templates" / "roles" / "director.md"
HEREDOC = re.compile(r"ask-user --task T-xxx --json - <<'EOF'\n(.*?)\nEOF", re.S)
# 설계 11.1: tasks.toml 의 디렉터 태스크 owns
DIRECTOR_OWNS = ["docs/design/direction.md", "docs/design/references.md", "docs/design/board/**",
                 "docs/design/pilots/**", "docs/design/system/**"]


def section(text: str, title: str) -> str:
    start = text.index(f"## {title}\n")
    end = text.find("\n## ", start + 1)
    return text[start:] if end == -1 else text[start:end]


class DirectorDocTest(unittest.TestCase):
    def setUp(self):
        self.text = DIRECTOR.read_text(encoding="utf-8")

    def test_three_stages_in_order(self):
        heads = re.findall(r"(?m)^## 단계 (.) (.+)$", self.text)
        self.assertEqual(heads, [("①", "레퍼런스"), ("②", "톤 시안"), ("③", "디자인 시스템")])

    def test_examples_are_valid_questions(self):
        found = [json.loads(x) for x in HEREDOC.findall(self.text)]
        self.assertEqual([o["header"] for o in found], ["레퍼런스", "톤 시안", "디자인 시스템"])
        for obj in found:
            outbox.validate_render(obj, "디자인")  # ask-user 가 받는 형식 그대로다(어기면 exit 2)
        self.assertEqual([o["label"] for o in found[-1]["options"]], ["확정 (추천)", "수정 요청"])
        self.assertEqual(len(found[1]["options"]), 3)  # 톤 3안

    def test_reference_capture_and_design_system(self):
        ref = section(self.text, "단계 ① 레퍼런스")
        for needle in ("WebSearch", "6–9개", "`new_page`", "`take_screenshot`", "`close_page`",
                       "${XDG_CACHE_HOME:-$HOME/.cache}/herdr-team/refs/<프로젝트 폴더 이름>/", "커밋하지 않는다",
                       "스타일 묶음 3–4개", "`docs/design/board/`", "`docs/design/references.md`", "캡처 불가"):
            self.assertIn(needle, ref)
        # MCP 는 filePath 를 자체 허용 목록(시스템 임시 경로) 안에만 저장한다: 임시 폴더에 찍고 캐시로 옮긴다
        for needle in ("tempfile.gettempdir()", "herdr-team-refs-<프로젝트 폴더 이름>", "`mv`", "`filePath` 없이"):
            self.assertIn(needle, ref)
        self.assertIn("임시 폴더의 파일로(뒤에 캐시로 옮긴다)", section(self.text, "도구"))
        system = section(self.text, "단계 ③ 디자인 시스템")
        for needle in ("Design System 타입", "`docs/design/system/`", "`tokens.json`", "`README.md`", "`components/`",
                       "4.5:1", "Lucide·Phosphor·Tabler", "`design_system_url: <URL>`", "밝은 테마 필수"):
            self.assertIn(needle, system)
        self.assertIn('`intent: "other"`', self.text)

    def test_answers_owns_and_rounds(self):
        ask = section(self.text, "사용자에게 묻기")
        for needle in ("`## 결정 기록`", "--ack <id>", "timeout: 600000", "--wait <id>", "AskUserQuestion 은 쓰지 않는다"):
            self.assertIn(needle, ask)
        out = section(self.text, "산출물")
        for rel in DIRECTOR_OWNS:
            self.assertIn(rel.removesuffix("**").rstrip("/") if rel.endswith("**") else rel, out)
            self.assertTrue(within(rel, "docs/design/**"), rel)
        for needle in ("`### 금지 목록 점검`", "`### 확인한 화면`(글로만 적는다", "확인용 스크린숏을 커밋하지 않는다",
                       "`## Network requests`"):
            self.assertIn(needle, out)
        self.assertNotIn("shots/", self.text)
        resume = section(self.text, "수정 라운드에서 이어 가기")
        for needle in ("--pending", "--history", '`"answer": null`'):
            self.assertIn(needle, resume)
        self.assertIn("`design_system_url` 은 바꾸지 않는다", section(self.text, "보강 태스크"))
        self.assertIn("래스터 에셋을 만들지 않는다", section(self.text, "도구"))
        self.assertIn("승인 직무가 아니다", section(self.text, "승인"))

    def test_planner_names_the_director_task(self):
        planner = (ROOT / "templates" / "roles" / "planner.md").read_text(encoding="utf-8")
        tasks = section(planner, "tasks.toml 형식")
        self.assertIn("key `design-direction`", tasks)
        self.assertIn("owns `" + json.dumps(DIRECTOR_OWNS, ensure_ascii=False) + "`", tasks)
        self.assertNotIn("기본 설정에는 director 가 없다", planner)


class DesignerDocTest(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / "templates" / "roles" / "designer.md").read_text(encoding="utf-8")

    def test_uses_the_project_design_system(self):
        start = section(self.text, "시작")
        for needle in ("`design_system_url:` 줄", "`[roles.director]`", "프리앰블의 ask 명령",
                       "시스템 URL·토큰 파일을 찾지 않는다"):
            self.assertIn(needle, start)
        tools = section(self.text, "도구")
        for needle in ('`intent: "design"`', "`design_systems: false`", "`/herdr-team:image`",
                       "`.herdr-team/bin/hteam image`", "`assets/<화면>/`"):
            self.assertIn(needle, tools)
        rules = section(self.text, "시스템 적용 규칙")
        for needle in ("새로 만들지 않는다", "`### 시스템 추가 제안`", "가장 가까운 토큰", '"없음" 한 줄'):
            self.assertIn(needle, rules)

    def test_without_a_design_system(self):
        # director 가 없는 프로젝트: 시스템 없이 만든 값을 notes.md 의 `## 확정 값` 에 적고, ui-foundation 이 옮긴다
        rules = section(self.text, "시스템이 없을 때")
        for needle in ("`## 확정 값`", "그대로 쓰고", "같은 이름에 다른 값을 주지 않는다", '"없음" 한 줄', "`ui-foundation`"):
            self.assertIn(needle, rules)
    def test_report_items_and_screenshots(self):
        out = section(self.text, "산출물")
        for needle in ("- `- 아티팩트: <claude.ai URL 또는 없음>`", "- `- 디자인 시스템: <design_system_url 또는 없음>`",
                       "`### 시스템 추가 제안`", "`### 금지 목록 점검`", "`### 확인한 화면`", "`### 이미지`"):
            self.assertIn(needle, out)
        shots = section(self.text, "확인한 화면")
        # 실환경(2단계): designer 가 스크린숏 PNG 를 화면 폴더에 커밋하고 DevTools 출력 제목을 보고서에 붙였다.
        # 리뷰어가 직접 렌더하므로(6.2) 확인용 스크린숏은 커밋하지 않고 글로만 적는다
        for needle in ("확인용 스크린숏을 커밋하지 않는다", "글로만 적는다", "`## Network requests`", "320px"):
            self.assertIn(needle, shots)
        self.assertIn("확인용 스크린숏 커밋하기", section(self.text, "하지 않는 것"))
        self.assertNotIn("shots/", self.text)
        self.assertNotIn("래스터 이미지 만들기", self.text)


class DeveloperDocTest(unittest.TestCase):
    def test_screen_rules(self):
        text = (ROOT / "templates" / "roles" / "developer.md").read_text(encoding="utf-8")
        rules = section(text, "화면 규칙")
        for needle in ("key `ui-foundation`", "CSS 변수", "공통 컴포넌트", "직접 쓰지 않는다", "프리앰블의 ask 명령",
                       "토큰 갱신 태스크", "`### 금지 목록 점검`", "시스템이 없을 때", "`## 확정 값`",
                       "확인용 스크린숏을 커밋하지 않는다", "`## Network requests`"):
            self.assertIn(needle, rules)
        self.assertNotIn("shots/", text)
        planner = (ROOT / "templates" / "roles" / "planner.md").read_text(encoding="utf-8")
        tasks = section(planner, "tasks.toml 형식")
        for needle in ("key `ui-foundation`", "디렉터 태스크가 없으면 모든 화면 designer 태스크에 의존하고", "`## 확정 값`"):
            self.assertIn(needle, tasks)
        # Codex 계획 r2: 시스템이 없어도 UI 기반이 공통 컴포넌트를 만든다(화면 태스크는 늘 공통 컴포넌트만 쓰고 없으면 묻는다)
        self.assertIn("화면 원본(`index.html`)·`notes.md` 에서 여러 화면이 함께 쓰는 공통 컴포넌트를 만든다", tasks)
        self.assertIn("화면 원본(`index.html`)·`notes.md` 에서 여러 화면이 함께 쓰는 공통 컴포넌트를 만든다", rules)
        designer = (ROOT / "templates" / "roles" / "designer.md").read_text(encoding="utf-8")
        self.assertIn("CSS 변수와 공통 컴포넌트로 옮긴다", section(designer, "시스템이 없을 때"))


if __name__ == "__main__":
    unittest.main()
