"""디자인 diff 자동 검사(설계 11.6): 지운 줄의 신호 감소, 옮긴 줄 상쇄, 추가한 줄의 확대 막기·포커스 제거, 대상 파일."""
import unittest
from unittest import mock

from tests.helpers import TeamCase
from hteam import designdiff
from hteam.designdiff import design_diff_lint, has_focus_alternative


class DesignDiffTest(TeamCase):
    def change(self, files: dict, message: str = "[T-001] 작업", delete=()) -> str:
        """files 를 쓰고 delete 를 지운 뒤 한 커밋으로 남긴다. 그 sha."""
        paths = []
        for rel, text in files.items():
            path = self.proj / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
            paths.append(rel)
        for rel in delete:
            self.git("rm", "-q", "--", rel)
        if paths:
            self.git("add", "--", *paths)
        self.git("commit", "-q", "-m", message, "--", *paths, *delete)
        return self.head()

    def lint(self, files, shas):
        return design_diff_lint(self.proj, list(files), list(shas))

    def test_removed_aria_label_is_reported(self):
        self.change({"src/Btn.tsx": '<button aria-label="닫기"><X/></button>\n<a aria-labelledby="t">x</a>\n'},
                    "기존")
        sha = self.change({"src/Btn.tsx": "<button><X/></button>\n<a>x</a>\n"})
        self.assertEqual(self.lint(["src/Btn.tsx"], [sha]),
                         ["src/Btn.tsx: 지운 줄에서 aria-label 1개가 줄었다(대체가 있는지 확인)",
                          "src/Btn.tsx: 지운 줄에서 aria-labelledby 1개가 줄었다(대체가 있는지 확인)"])

    def test_moved_or_rewrapped_signals_are_not_reported(self):
        self.change({"src/A.tsx": '<button aria-label="닫기" className="x">\n'}, "기존")
        sha = self.change({"src/A.tsx": '<button\n  aria-label="닫기"\n  className="x">\n'})
        self.assertEqual(self.lint(["src/A.tsx"], [sha]), [])

    def test_motion_wrap_and_app_signals(self):
        old = ("@media (prefers-reduced-motion: reduce) { .a { animation: none } }\n.t { word-break: keep-all }\n"
               '<p class="break-keep">x</p>\n')
        self.change({"src/a.css": old, "lib/a.dart": "Semantics(label: 'x', child: Text(semanticsLabel: 'y'))\n",
                     "android/a.kt": 'Image(contentDescription = "x")\nIcon(semanticLabel: "y")\n'}, "기존")
        sha = self.change({"src/a.css": ".a {}\n.t {}\n<p>x</p>\n", "lib/a.dart": "Text('y')\n",
                           "android/a.kt": "Image()\nIcon()\n"})
        found = self.lint(["android/a.kt", "lib/a.dart", "src/a.css"], [sha])
        for name, rel in (("prefers-reduced-motion", "src/a.css"), ("keep-all", "src/a.css"), ("break-keep", "src/a.css"),
                          ("Semantics(", "lib/a.dart"), ("semanticsLabel", "lib/a.dart"),
                          ("contentDescription", "android/a.kt"), ("semanticLabel", "android/a.kt")):
            self.assertIn(f"{rel}: 지운 줄에서 {name} 1개가 줄었다(대체가 있는지 확인)", found)

    def test_zoom_block_in_added_lines(self):
        sha = self.change({"index.html": '<meta name="viewport" content="width=device-width, maximum-scale=1.0, '
                                         'user-scalable=no">\n<meta name="viewport" content="maximum-scale=5">\n',
                           "src/layout.ts": "export const viewport = { maximumScale: 1, userScalable: false }\n"})
        self.assertEqual(self.lint(["index.html", "src/layout.ts"], [sha]),
                         ["index.html:1: 확대 막기(maximum-scale=1.0, user-scalable=no\">)",
                          "src/layout.ts:1: 확대 막기(maximumScale: 1, userScalable: false })"])

    def test_focus_removal_without_focus_visible(self):
        caught = {"a.css": ".btn:focus { outline: none }\n", "b.tsx": '<i className="focus:outline-none"/>\n',
                  "c.tsx": '<i className="dark:focus:outline-none"/>\n', "d.tsx": '<i className="outline-hidden"/>\n',
                  "e.css": ".a:focus { outline-style: none }\n",
                  "f.tsx": '<i className="outline-none focus:ring-0 focus:shadow-none focus:ring-transparent '
                           'focus:outline-hidden"/>\n'}
        kept = {"g.css": ".a:focus-visible { box-shadow: 0 0 0 2px #000 }\n.b { outline: none }\n",
                "h.tsx": '<i className="outline-none focus:ring-2"/>\n', "i.tsx": '<i className="outline-none dark:focus:ring-2"/>\n',
                "j.tsx": '<i className="outline-none md:focus:ring-2"/>\n', "k.tsx": '<i className="outline-none focus:!ring-2"/>\n',
                "l.css": ".a { outline-offset: 0 }\n"}
        files = {f"src/{k}": v for k, v in {**caught, **kept}.items()}
        sha = self.change(files)
        found = self.lint(sorted(files), [sha])
        self.assertEqual([x.split(":", 1)[0] for x in found], [f"src/{k}" for k in sorted(caught)])
        self.assertEqual(found[0], "src/a.css:1: 포커스 표시 제거(.btn:focus { outline: none }, 파일에 focus-visible 없음)")
        self.assertFalse(has_focus_alternative(".a:focus { outline: none }"))

    def test_removed_focus_visible_is_not_called_focus(self):
        self.change({"src/a.css": ".a:focus-visible { outline: 2px solid }\n"}, "기존")
        sha = self.change({"src/a.css": ".a { color: red }\n"})
        self.assertEqual(self.lint(["src/a.css"], [sha]),
                         ["src/a.css: 지운 줄에서 :focus-visible 1개가 줄었다(대체가 있는지 확인)"])

    def test_crlf_file(self):
        self.change({"src/a.html": '<button aria-label="x">\r\n<p>y</p>\r\n'}, "기존")
        sha = self.change({"src/a.html": "<button>\r\n<p>y</p>\r\n.b { outline: none }\r\n"})
        self.assertEqual(self.lint(["src/a.html"], [sha]),
                         ["src/a.html: 지운 줄에서 aria-label 1개가 줄었다(대체가 있는지 확인)",
                          "src/a.html:3: 포커스 표시 제거(.b { outline: none }, 파일에 focus-visible 없음)"])

    def test_only_lines_added_by_the_given_commits(self):
        mine = self.change({"src/a.css": ".a { outline: none }\n"})
        self.change({"src/a.css": ".a { outline: none }\n.b { outline: 0 }\n"}, "[T-002] 다른 태스크")
        self.assertEqual(self.lint(["src/a.css"], [mine]),
                         ["src/a.css:1: 포커스 표시 제거(.a { outline: none }, 파일에 focus-visible 없음)"])

    def test_skips_non_targets_excluded_and_git_errors(self):
        self.change({"docs/design/system/README.md": 'aria-label="x"\n', "docs/planning/a.json": '{"aria-label": 1}\n',
                     "docs/design/references.md": "keep-all\n", "src/a.py": "keep-all\n", "src/b.css": ".b { keep-all }\n"},
                    "기존")
        sha = self.change({"docs/design/system/README.md": "x\n", "docs/planning/a.json": "{}\n",
                           "docs/design/references.md": "x\n", "src/a.py": "x\n", "src/b.css": ".b {}\n"})
        files = ["docs/design/references.md", "docs/design/system/README.md", "docs/planning/a.json", "src/a.py",
                 "src/b.css", "../outside.css"]
        self.assertEqual(self.lint(files, [sha]), ["src/b.css: 지운 줄에서 keep-all 1개가 줄었다(대체가 있는지 확인)"])
        with mock.patch.object(designdiff.gitio, "diff_lines", return_value=None):
            self.assertEqual(self.lint(files, [sha]), [])

    def test_deleted_file_has_only_removed_line_findings(self):
        self.change({"src/Old.tsx": '<button aria-label="x" />\n'}, "기존")
        sha = self.change({}, delete=["src/Old.tsx"])
        self.assertEqual(self.lint(["src/Old.tsx"], [sha]),
                         ["src/Old.tsx: 지운 줄에서 aria-label 1개가 줄었다(대체가 있는지 확인)"])

    def test_moved_file_extracted_component_and_restored_lines_are_not_reported(self):
        self.change({"src/Item.tsx": '<li><button aria-label="삭제"><X/></button></li>\n',
                     "src/Card.tsx": '<div><button aria-label="닫기">x</button></div>\n'}, "기존")
        self.git("mv", "src/Item.tsx", "src/TodoItem.tsx")  # 내용 그대로 옮긴다
        moved = self.change({"src/Card.tsx": "<div><CloseButton /></div>\n",  # 컴포넌트 추출: 모양이 다른 줄
                             "src/CloseButton.tsx": '<button\n  aria-label="닫기">x</button>\n'},
                            delete=[])
        self.git("commit", "-q", "--amend", "--no-edit")  # mv 를 같은 커밋에 담는다
        moved = self.head()
        files = ["src/Card.tsx", "src/CloseButton.tsx", "src/Item.tsx", "src/TodoItem.tsx"]
        self.assertEqual(self.lint(files, [moved]), [])
        gone = self.change({"src/Card.tsx": "<div>x</div>\n"})
        back = self.change({"src/Card.tsx": '<div><button aria-label="닫기">x</button></div>\n'})
        self.assertEqual(self.lint(["src/Card.tsx"], [gone, back]), [])

    def test_net_decrease_is_reported_per_file_and_moved_file_stays_quiet(self):
        self.change({"src/components/TodoItem.tsx": '<button aria-label="삭제">x</button>\n<p>할 일</p>\n',
                     "src/Other.tsx": '<button aria-label="열기">o</button>\n'}, "기존")
        (self.proj / "src/ui").mkdir()
        self.git("mv", "src/Other.tsx", "src/ui/Other.tsx")  # 내용 그대로 옮긴 파일
        self.change({"src/components/TodoItem.tsx": "<button>x</button>\n<p>할 일</p>\n"}, delete=[])
        self.git("commit", "-q", "--amend", "--no-edit")
        sha = self.head()
        files = ["src/Other.tsx", "src/components/TodoItem.tsx", "src/ui/Other.tsx"]
        self.assertEqual(self.lint(files, [sha]),
                         ["src/components/TodoItem.tsx: 지운 줄에서 aria-label 1개가 줄었다(대체가 있는지 확인)"])

    def test_identifiers_are_not_signals_but_attributes_are(self):
        self.change({"src/a.ts": "const role = user.role\nconst l = navigator.language\nconst s = { focus: { a: 1 } }\n",
                     "src/b.tsx": ('<div role="dialog" lang="ko"><img alt="" />'
                                   '<i className="focus:ring-2 motion-safe:animate-spin" /></div>\n')}, "기존")
        sha = self.change({"src/a.ts": "x\n", "src/b.tsx": "<div><img /><i /></div>\n"})
        found = self.lint(["src/a.ts", "src/b.tsx"], [sha])
        self.assertEqual(found, [f"src/b.tsx: 지운 줄에서 {name} 1개가 줄었다(대체가 있는지 확인)"
                                 for name in ("role", "alt", "lang", "focus:", "motion-safe:")])

    def test_markdown_is_not_a_target(self):
        self.change({"docs/user/a.md": "aria-label keep-all\n"}, "기존")
        sha = self.change({"docs/user/a.md": "x\n"})
        self.assertEqual(self.lint(["docs/user/a.md"], [sha]), [])


if __name__ == "__main__":
    unittest.main()
