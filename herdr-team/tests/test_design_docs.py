"""디자인 직무 문서(설계 11.1–11.3): director 의 세 단계·질문 형식·산출물, scaffold, 설정."""
import json
import re
import shutil
import tempfile
import tomllib
import unittest
from pathlib import Path

from tests.helpers import ROOT
from hteam import config, outbox, textlint
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
        for needle in ("`### 디자인 점검`", "`### 확인한 화면`(글로만 적는다", "확인용 스크린숏을 커밋하지 않는다",
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
                       "`### 시스템 추가 제안`", "`### 디자인 점검`", "`### 확인한 화면`", "`### 이미지`"):
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
                       "토큰 갱신 태스크", "`### 디자인 점검`", "시스템이 없을 때", "`## 확정 값`",
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


RULES = ROOT / "templates" / "design-rules.md"
REVIEW_DESIGN = ROOT / "templates" / "review-design.md"


def blocks(text: str) -> list[str]:
    """즉시 차단 항목 목록(`- ` 또는 들여 쓴 `- ` 글머리)."""
    return [line.strip()[2:] for line in text.split("\n") if line.strip().startswith("- ")]


class DesignRulesTest(unittest.TestCase):
    """디자인 규칙 §0–§7·즉시 차단 항목과 리뷰 디자인 절 기준 1–9(설계 11.5)."""

    def setUp(self):
        self.rules = RULES.read_text(encoding="utf-8")
        self.review = REVIEW_DESIGN.read_text(encoding="utf-8")

    def test_sections_in_order(self):
        heads = [line for line in self.rules.split("\n") if line.startswith("#")]
        self.assertEqual(heads, ["# 디자인 규칙", "## §0 범위", "## §1 금지 목록 (AI 티)", "## §2 접근성 (WCAG 2.2 AA)",
                                 "## §3 색", "## §4 글자", "## §5 레이아웃", "## §6 표면·동작", "## §7 상태",
                                 "## 즉시 차단 항목", "## 자동 검사", "## 출처"])
        counts = {"§1 금지 목록 (AI 티)": 10, "§2 접근성 (WCAG 2.2 AA)": 14, "§3 색": 7, "§4 글자": 10, "§5 레이아웃": 10,
                  "§6 표면·동작": 11, "§7 상태": 5}
        for title, n in counts.items():
            found = re.findall(r"(?m)^(\d+)\. ", section(self.rules, title))
            self.assertEqual([int(x) for x in found], list(range(1, n + 1)), title)

    def test_head_and_substitutions(self):
        head = self.rules[:self.rules.index("## §0 범위")]
        for needle in ("`### 디자인 점검`", "`## rN`", "§1 항목마다 지켰는지", "§2–§6 에서 어긴 곳과 예외·근거",
                       "§7 에서 확인한 상태와 확인 방법", "`hteam review`", "판정은 리뷰어가 한다"):
            self.assertIn(needle, head)
        self.assertIn("디렉터가 없는 프로젝트는 화면 `notes.md` 의 `## 확정 값`", section(self.rules, "§0 범위"))
        self.assertIn("developer 는 프리앰블의 ask 명령으로 메인에게 묻는다", section(self.rules, "§0 범위"))
        self.assertIn("Tailwind 조합은 한 줄 또는 한 클래스 목록 안에서 본다", section(self.rules, "자동 검사"))
        self.assertIn("herdr-team 은 orca-team 0.5.2 에서 옮겼다", section(self.rules, "출처"))
        self.assertIn("jakubkrehel/skills", section(self.rules, "출처"))
        for old in (".orchestration", "orch review", "리포트", "r{round}", "Codex", "ask 로 묻는다"):
            self.assertNotIn(old, self.rules)
        state = section(self.rules, "§7 상태")
        for needle in ("되돌리기", "다시 시도", "임시 확인 페이지", "확인 뒤 되돌린다", "`.herdr-team/text-rules.md` §3 의 4번"):
            self.assertIn(needle, state)

    def test_immediate_blocks_match_the_review_list(self):
        rules = blocks(section(self.rules, "즉시 차단 항목"))
        grade = self.review[self.review.index("6. 디자인 지적의 심각도"):self.review.index("   - P2:")]
        review = [b for b in blocks(grade) if not b.startswith("P1:")]
        self.assertEqual(len(rules), 10)
        self.assertEqual(set(rules), set(review))
        self.assertIn("보고서에 예외를 적었어도 리뷰어는 P1(REQUEST_CHANGES)로 판정한다", section(self.rules, "즉시 차단 항목"))

    def test_review_design_criteria(self):
        self.assertEqual([int(x) for x in re.findall(r"(?m)^(\d+)\. ", self.review)], list(range(1, 10)))
        self.assertEqual(re.findall(r"\{\{(\w+)\}\}", self.review), ["browser", "lint"])
        for needle in ("(이전 버전 프로젝트는 `### 금지 목록 점검`)", "`(새로 생김)`·`(회귀)`·`(기존)`",
                       "`(기존)` 은 P3 로 3개까지만 적는다", "즉시 차단 항목은 보고서에 예외를 적었어도 P1 이다",
                       "§ 제목이 없는 이전 버전 규칙 파일이면 P2 는 적지 않고 §1 과 즉시 차단 항목만 본다",
                       "디자인 지적은 15개까지 적고", "\"확인 못 함\"", "design-rules §3 의 7번",
                       "기본·hover·focus·눌림·disabled·로딩·error 중 해당하는 것",
                       "\"지운 줄에서 … 줄었다\" 는 4번, \"확대 막기\"·\"포커스 표시 제거\" 는 6번의 즉시 차단 항목 후보다"):
            self.assertIn(needle, self.review)
        self.assertLess(self.review.index("9. 밀도"), self.review.index("렌더링:"))
        self.assertLess(self.review.index("렌더링:"), self.review.index("{{lint}}"))

    def test_role_docs(self):
        for role in ("director", "designer", "developer"):
            text = (ROOT / "templates" / "roles" / f"{role}.md").read_text(encoding="utf-8")
            for needle in ("§1 AI 티 금지 목록, §2–§7", "즉시 차단 항목(design-rules)은 예외가 인정되지 않는다",
                           "§7 의 4번", "§7 의 5번", "`### 디자인 점검`"):
                self.assertIn(needle, text, role)
        for path in (ROOT / "templates").rglob("*.md"):  # 옛 소절 이름은 리뷰 디자인 절의 호환 문장에만 있다
            if path != REVIEW_DESIGN:
                self.assertNotIn("금지 목록 점검", path.read_text(encoding="utf-8"), path)
        director = (ROOT / "templates" / "roles" / "director.md").read_text(encoding="utf-8")
        system = section(director, "단계 ③ 디자인 시스템")
        for needle in ("design-rules §3 을 따른다", "design-rules §4 를 따른다", "`word-break: keep-all`",
                       "`font-display: swap`", "눌림·disabled·로딩"):
            self.assertIn(needle, system)
        designer = (ROOT / "templates" / "roles" / "designer.md").read_text(encoding="utf-8")
        self.assertIn("§7 의 상태(기본, hover, focus, 눌림, 비활성, 로딩, 빈 상태, 오류, 좁은 폭, 긴 글 중 해당하는 것)를 시안에 넣는다",
                      designer)
        self.assertIn("design-rules §7 의 상태(빈 상태, 로딩, 오류 포함)와 반응형(모바일·데스크톱 기준폭)", designer)
        developer = (ROOT / "templates" / "roles" / "developer.md").read_text(encoding="utf-8")
        rules = section(developer, "화면 규칙")
        for needle in ("임시 확인 페이지", "커밋하지 않는다", "확인 뒤 되돌린다", "Storybook", "§7 줄에는 상태와 방법만 적는다"):
            self.assertIn(needle, rules)


class TextRulesDocTest(unittest.TestCase):
    """문구 규칙을 쓰는 직무 문서·코디네이터·메인 규칙·설정 템플릿(설계 10장·11.7)."""

    @staticmethod
    def read(rel):
        return (ROOT / "templates" / rel).read_text(encoding="utf-8")

    def test_planner_writes_voice_doc(self):
        text = self.read("roles/planner.md")
        self.assertIn("`docs/planning/voice.md`: 문구 기준", section(text, "산출물"))
        checklist = section(text, "인터뷰 체크리스트")
        for needle in ("12. 문구 기준(", "질문 1개", "서비스 문구 해요체, 정책 문서 하십시오체", "용어집은 따로 묻지 않는다"):
            self.assertIn(needle, checklist)
        self.assertIn("용어집 표(쓰는 표기, 쓰지 않는 표기. 핵심 용어 10개 이내)", section(text, "확정 질문"))
        tasks = section(text, "tasks.toml 형식")
        for needle in ("`docs/policy/**`", "`README.md`, `docs/user/**`", "developer 태스크로 만들고",
                       "`docs/planning/voice.md` 와 `.herdr-team/text-rules.md` 를 따른다"):
            self.assertIn(needle, tasks)
        fmt = text[text.index("## voice.md 형식\n"):text.index("## 하지 않는 것\n")]
        for needle in ("메모 칸에 적는다", "괄호로 조건을 붙인 표기는 검사하지 않는다", "바뀌는 부분만 고친다"):
            self.assertIn(needle, fmt)
        example = re.search(r"```markdown\n(.*?)```", fmt, re.S).group(1)
        for line in ("# 문구 기준", "## 문체", "- 서비스 문구: 해요체", "- 정책 문서: 하십시오체", "- 사용자 문서: 해요체",
                     "## 라벨", "## 용어집", "| 쓰는 표기 | 쓰지 않는 표기 | 메모 |"):
            self.assertIn(line + "\n", example)
        root = Path(tempfile.mkdtemp(prefix="hteam-voice-"))
        self.addCleanup(shutil.rmtree, root, True)
        (root / "docs/planning").mkdir(parents=True)
        (root / "docs/planning/voice.md").write_text(example, encoding="utf-8")
        self.assertEqual(textlint.load_glossary(root), [("로그인", ["로그 인", "로긴"]), ("회원가입", ["회원 가입"])])

    def test_writers_follow_text_rules(self):
        for role, own in (("designer", "실제 서비스에 그대로 들어갈 문구로 쓴다"),
                          ("developer", "디자인 시안의 문구가 있으면 그대로 옮기고")):
            text = self.read(f"roles/{role}.md")
            self.assertIn("`.herdr-team/text-rules.md`(문구 규칙)와 `docs/planning/voice.md`(문구 기준", section(text, "입력"))
            rules = section(text, "문구 규칙")
            for needle in ("`### 문구 점검`", "text-rules §1–§4 를 지켰는지", "voice.md 는 고치지 않는다", "`## rN`", own):
                self.assertIn(needle, rules, role)
        self.assertIn("`### 문구 점검`", section(self.read("roles/designer.md"), "산출물"))
        for role in ("director", "tester", "planner"):  # E5: 문구 점검 대상이 아니다
            self.assertNotIn("문구 점검", self.read(f"roles/{role}.md"), role)

    def test_main_rules_name_voice(self):
        main = self.read("CLAUDE.section.md")
        self.assertIn("기획 `docs/planning/`(spec.md, contracts.md, tasks.toml, interview.md, voice.md)", main)
        self.assertIn("- 문구: `.herdr-team/text-rules.md`(작성·리뷰 공통 규칙), `docs/planning/voice.md`(planner 가 정한 "
                      "문체·호칭·라벨·용어집).", main)

    def test_developer_owns_user_and_policy_docs(self):
        raw = tomllib.loads(self.read("config.toml"))
        self.assertEqual(raw["roles"]["developer"]["owns"], ["src/**", "README.md", "docs/user/**", "docs/policy/**"])
        self.assertEqual(config.validate(raw), [])


if __name__ == "__main__":
    unittest.main()
