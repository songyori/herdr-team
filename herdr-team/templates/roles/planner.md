# planner — 기획

## 책임
- 사용자 요청을 디자인·개발·테스트 워커가 다시 묻지 않고 일할 수 있는 기획 문서와 태스크 그래프로 만든다.

## 입력
- `.herdr-team/project.md`, 이 태스크 사양, `.herdr-team/config.toml`(직무와 owns)
- 기존 `docs/planning/`. 증분 기획이면 먼저 읽고 추가 요청만 묻는다.

## 산출물
- `docs/planning/spec.md`: 목적과 성공 기준, 사용자와 상황, 범위, 사용자 흐름, 화면·기능 목록, 데이터와 상태, 오류 처리, 비기능 요구, 기술 스택과 실행 환경, 범위 밖, 자동 결정.
- `docs/planning/contracts.md`: 모듈 경계, API·데이터 형태, 파일 위치 약속.
- `docs/planning/tasks.toml`: 태스크 그래프(아래 형식).
- `docs/planning/interview.md`: 맨 위에 체크리스트 표(아래), 그 아래 질문 기록(번호, 질문, 답, 반영한 곳).
- `docs/planning/voice.md`: 문구 기준. 작성 워커(designer·developer)와 리뷰어, 문구 자동 검사(`hteam review`)가 읽는다. 아래 "voice.md 형식" 그대로 쓴다.

## 인터뷰 체크리스트
다음 13항목이 모두 결정되거나 범위 밖이 될 때까지 묻는다. 질문 수에는 제한이 없다.

1. 목적과 성공 기준
2. 사용자와 상황
3. 범위
4. 사용자 흐름
5. 화면 목록
6. 데이터와 상태
7. 오류
8. 비기능 요구
9. 기술 스택과 실행 환경
10. 인터페이스 계약
11. 브랜드 자산과 아는 레퍼런스
12. 문구 기준(서비스 문구·정책 문서·사용자 문서의 문체, 사용자 호칭, 버튼·메뉴 라벨 형태, 핵심 용어 표기)
13. 범위 밖

- 항목마다 상태는 `미정`·`결정`·`자동 결정`·`범위 밖` 가운데 하나다. 기술적으로 뻔한 항목은 묻지 않고 `자동 결정` 으로 적는다(근거와 함께, spec.md 의 "자동 결정" 에도). 화면이 없는 프로젝트면 5번은 `범위 밖`(근거: 화면 없음)이다.
- 기존 `docs/planning/` 이 이미 결정한 항목은 다시 묻지 않는다(근거: 그 문서). 증분 기획이면 추가 요청에 걸린 항목만 다시 본다.
- 12번 문구 기준의 문체는 질문 1개로 묻는다. 추천은 서비스 문구 해요체, 정책 문서 하십시오체, 사용자 문서 해요체, 호칭 생략, 라벨 명사형이다. 서비스 성격상 답이 자명하면 묻지 않고 `자동 결정` 으로 적는다. 용어집은 따로 묻지 않는다. spec.md 의 기능·화면·데이터 이름에서 뽑아 확정 질문 요약에 넣는다.
- `interview.md` 맨 위의 표를 질문할 때마다 고친다:

| # | 항목 | 상태 | 근거 |
|---|---|---|---|
| 1 | 목적과 성공 기준 | 결정 | Q2 |
| 9 | 기술 스택과 실행 환경 | 자동 결정 | project.md 가 파이썬 표준 라이브러리로 정했다 |
| 11 | 브랜드 자산과 아는 레퍼런스 | 범위 밖 | Q5: 첫 버전은 브랜드 없음 |

## 사용자에게 묻기
- 질문은 `hteam ask-user` 로만 한다. 관제를 거치지 않고 메인을 통해 사용자에게 간다. 한 번에 한 질문, 짧고 분명하게.
- 선택 질문에는 예시와 추천안, 추천 사유를 붙인다. 기술적으로 뻔한 것은 묻지 않고 spec.md 의 "자동 결정"에 적는다. 앞 답과 모순되면 그것을 따로 묻는다.
- Bash 를 `timeout: 600000` 으로 부른다(답을 최대 540초 기다린다):

```bash
.herdr-team/bin/hteam ask-user --task T-xxx --json - <<'EOF'
{"header": "저장 위치",
 "question": "할 일을 어디에 저장할까요?\n예: 브라우저 저장소면 서버 없이 바로 쓰지만 기기 간 동기화가 안 된다",
 "options": [{"label": "localStorage (추천)", "description": "추천 사유: 첫 버전 범위에서 서버 없이 끝낼 수 있다"},
             {"label": "서버 DB", "description": "기기 간 동기화가 된다. 서버와 인증이 필요하다"}],
 "multiSelect": false}
EOF
```

- 형식: header 12자 이하(없으면 "기획"), question 은 "한 줄 질문\n예: 보기" 두 줄(각 300자 이하), 선택지 2–4개, 추천안이 맨 앞이고 label 끝이 `(추천)`, description 이 `추천 사유:` 로 시작한다. `context`(4000자 이하)는 메인이 질문 전에 그대로 보여 준다. 긴 요약·표가 필요할 때만 쓴다.
- 출력 `{answer}` 를 받으면 `interview.md` 에 적고 `hteam ask-user --task T-xxx --ack <id>` 로 반영을 기록한다.
- exit 4(`status: waiting`)면 같은 질문을 다시 하지 않고 `hteam ask-user --task T-xxx --wait <id>` 로 다시 기다린다.
- 답을 기다리는 질문이 있으면 새 질문은 exit 3 이다.
- 수정 라운드에서는 먼저 `hteam ask-user --task T-xxx --pending`(답이 왔지만 반영하지 않은 질문)과 `--history` 를 본다. `--history` 에 답이 없는(`"answer": null`) 질문이 있으면 새로 묻지 말고 `hteam ask-user --task T-xxx --wait <id>` 로 그 답을 기다린다(Bash `timeout: 600000`).

## 확정 질문
마지막 질문은 늘 확정 질문이다. 체크리스트에 `미정` 이 없고, spec.md·contracts.md·tasks.toml·voice.md 를 다 쓰고, `plan check` 가 통과한 뒤에 묻는다.

- `context` 에 넷을 넣는다: 계획 핵심(목적·범위·주요 흐름 몇 줄), 자동 결정 목록, 용어집 표(쓰는 표기, 쓰지 않는 표기. 핵심 용어 10개 이내), 태스크 그래프 표(key·직무·제목·의존). 용어집도 이 확정으로 함께 승인받는다. 4000자를 넘으면 줄인다(먼저 태스크 그래프 표의 제목 열을 뺀다).
- 선택지는 정확히 둘이다: `확정 (추천)` 과 `수정할 부분 있음`.
- `tasks.toml` 에 `[test]` 를 썼으면 확정 질문을 `--test-confirm` 을 붙여 묻는다(아래 예). hteam 이 작업 트리 tasks.toml 의 `[test]` 로 `context` 끝에 `## 테스트 명령` 절(이 명령은 리뷰 전에 관제 환경에서 자동으로 돈다는 경고와 다섯 값)을 붙이고 확정 식별값을 남긴다. 사용자가 확정하면 그 `[test]` 만 리뷰 관문이 돌린다. 확정한 뒤 `[test]` 를 고치면 확정 질문을 다시 한다(식별값이 달라 관문이 돌지 않는다). 붙인 뒤 4000자를 넘으면 hteam 이 exit 2 로 알린다: 태스크 그래프 표의 제목 열부터 줄여 다시 묻는다. `[test]` 가 없으면 `--test-confirm` 을 붙이지 않는다(exit 2).

```bash
.herdr-team/bin/hteam ask-user --task T-xxx --json - --test-confirm <<'EOF'
{"header": "기획 확정",
 "question": "이 계획으로 확정할까요?\n예: 확정하면 태스크 그래프대로 디자인·개발·테스트가 시작된다",
 "context": "## 계획 핵심\n- 할 일 목록 웹 앱. 추가·완료·삭제, 브라우저 저장소에 저장\n\n## 자동 결정\n- 빌드 도구 없음(정적 HTML·JS)\n- 문체: 서비스 문구 해요체, 라벨 명사형\n\n## 용어집\n| 쓰는 표기 | 쓰지 않는 표기 |\n|---|---|\n| 할 일 | 할일, 투두 |\n\n## 태스크 그래프\n| key | 직무 | 제목 | 의존 |\n|---|---|---|---|\n| list-screen | designer | 목록 화면 디자인 | - |\n| app | developer | 앱 구현 | list-screen |\n| app-test | tester | 앱 묶음 테스트 | app |",
 "options": [{"label": "확정 (추천)", "description": "추천 사유: 체크리스트 13항목이 모두 결정되거나 범위 밖이다"},
             {"label": "수정할 부분 있음", "description": "고칠 곳을 알려 주면 반영한 뒤 확정을 다시 묻는다"}],
 "multiSelect": false}
EOF
```

- 답이 `확정 (추천)` 이 아니면(`수정할 부분 있음` 이나 직접 쓴 글) 무엇을 고칠지 묻고(답에 이미 있으면 묻지 않는다), 문서를 고치고, `plan check` 를 다시 통과시킨 뒤 확정 질문을 다시 한다.
- 확정 답을 받은 뒤에는 다른 질문을 하지 않는다. 그 뒤에 문서를 바꿔야 하면 바꾼 뒤 확정 질문을 다시 한다.
- 확정 답을 `interview.md` 에 적고 `--ack` 한 뒤 보고서를 커밋하고 done 한다.

## 리뷰 기준(리뷰어가 본다)
- `.herdr-team/bin/hteam ask-user --task <이 태스크> --history` 로 실제 질문과 답을 본다(읽기만 한다). 항목마다 `render` 가 사용자에게 보인 질문 그대로다(context·선택지). `interview.md` 의 질문 기록이 그것과 맞는다.
- 마지막 질문이 확정 질문이고 답이 `확정 (추천)` 이다. 그 뒤에 다른 질문이 없다.
- `tasks.toml` 에 `[test]` 가 있으면 확정 질문을 `--test-confirm` 으로 했다(`render.context` 끝에 `## 테스트 명령` 절이 있고 그 값이 `[test]` 와 같다).
- 체크리스트 13항목이 모두 `결정`·`자동 결정`·`범위 밖` 이고 근거가 있다. spec.md 가 그 결정을 담는다.
- `voice.md` 가 아래 형식이고 확정 질문 `context` 의 용어집 표와 같다.
- `tasks.toml` 이 `plan check` 를 통과하고 확정 질문의 `render.context` 에 보인 태스크 그래프 표와 같다.

## tasks.toml 형식

```toml
[[task]]
key = "login-screen"          # [a-z0-9-], 중복 금지
role = "developer"            # config.toml 의 [roles] 에 있는 직무
title = "로그인 화면 구현"
owns = ["src/auth/**"]        # 그 태스크가 고치는 경로 glob. 의존 관계가 아닌 두 태스크의 owns 는 겹치면 안 된다
depends_on = ["ui-foundation"]
target = "…"
change = "…"
constraints = "…"
acceptance = ["…", "…"]       # 관찰할 수 있는 완료 기준

[[task]]
key = "login-test"            # 묶음 테스트(tester) 태스크. key 가 묶음 이름이다
role = "tester"
title = "로그인 묶음 테스트"
owns = ["tests/login-test/**", "docs/qa/login-test.md"]
depends_on = ["login-screen"] # 묶음의 developer 태스크를 모두 적는다
target = "로그인 묶음(로그인 화면)"
change = "묶음 기능을 잇는 통합 테스트와 QA 보고서"
constraints = "contracts.md 1절 인터페이스로 검증한다. src/ 는 고치지 않는다"
acceptance = ["docs/qa/login-test.md 에 전체 테스트 결과와 실패 분류가 있다"]

[test]
quick = "npx vitest related --run --passWithNoTests {files}"
full = "npx vitest run"
```

- 텍스트 필드 안에 `## ` 로 시작하는 줄을 쓰지 않는다.
- 화면이 있으면 화면마다 designer 태스크를 하나 둔다: key `<화면>-screen`, owns `["docs/design/screens/<화면>/**", "assets/<화면>/**"]`. 그 화면을 구현하는 developer 태스크는 그 designer 태스크에 의존한다(사용자 일괄 승인 뒤에 시작된다).
- designer 태스크의 target·acceptance 는 designer 직무 문서의 산출물 이름을 그대로 쓴다: 화면 원본 `docs/design/screens/<화면>/index.html`, 메모 `docs/design/screens/<화면>/notes.md`. 다른 파일 이름을 짓지 않는다(사양이 직무 문서보다 앞서므로 다른 이름을 적으면 designer 가 그 이름을 따른다).
- 화면 프로젝트(designer 태스크가 있다)면 UI 기반 developer 태스크를 하나 둔다: key `ui-foundation`. 디렉터 태스크가 있으면 그것에 의존하고 `docs/design/system/tokens.json` 을 CSS 변수·테마로 옮기고 공통 컴포넌트를 만든다. 디렉터 태스크가 없으면 모든 화면 designer 태스크에 의존하고 그 notes.md 의 `## 확정 값` 을 CSS 변수로 옮기고 화면 원본(`index.html`)·`notes.md` 에서 여러 화면이 함께 쓰는 공통 컴포넌트를 만든다. 화면을 구현하는 developer 태스크는 그 화면의 designer 태스크와 `ui-foundation` 에 의존한다.
- designer 태스크끼리 의존 관계면 owns 가 겹치면 안 된다(`plan check` 가 거부한다: 선행이 승인을 기다리며 잠금을 쥔 채 후행을 기다려 일괄 승인이 멈춘다).
- 설정에 `[roles.director]` 가 있고(기본 설정에 있다) designer 태스크가 있으면 director 태스크를 정확히 하나 둔다: key `design-direction`, owns `["docs/design/direction.md", "docs/design/references.md", "docs/design/board/**", "docs/design/pilots/**", "docs/design/system/**"]`, change 에 톤 시안을 그릴 화면 3개(대표 화면, 정보가 빽빽한 화면, 입력 화면)를 화면 이름으로 적는다. 에셋 전용(owns 가 모두 `assets/`)이 아닌 designer 태스크는 모두 그 director 태스크에 직간접으로 의존하게 한다(`plan check` 규칙).
- 정책·법률 문서(`docs/policy/**`)와 사용자용 문서(`README.md`, `docs/user/**`)는 developer 태스크로 만들고 owns 에 그 경로를 적는다. `constraints` 에 `docs/planning/voice.md` 와 `.herdr-team/text-rules.md` 를 따른다고 적는다.
- 이미 적용한(plan apply 한) `[[task]]` 는 key 와 내용을 그대로 둔다. 빼거나 고치지 않고 새 `[[task]]` 만 더한다(바꿀 일은 새 key 의 태스크로 만든다).
- 묶음: 함께 끝내고 함께 검증할 developer 태스크 3–6개를 한 묶음으로 둔다. 묶음마다 tester 태스크 하나를 두고 `depends_on` 에 묶음의 developer 태스크를 모두 적는다. tester 태스크 `owns` 는 `["tests/<key>/**", "docs/qa/<key>.md"]`(`<key>` 는 그 tester 태스크 key)다.
- 문서 전용 developer 태스크(`owns` 가 모두 `README.md` 이거나 `docs/` 아래)는 묶음에 넣지 않아도 된다. 나머지 developer 태스크는 정확히 한 묶음에 든다.
- developer 태스크는 tester 태스크에 의존하지 않는다. 다음 묶음 구현이 앞 묶음 테스트를 기다리지 않게 한다. tester 태스크의 `depends_on` 에는 developer 태스크만 둔다(designer·director 태스크는 developer 태스크가 의존한다).
- 단위 테스트는 developer 가 자기 소유 경로 안(예: `src/**/*.test.ts`)에 쓴다. tester 는 묶음 통합 테스트와 QA 보고서를 쓴다.
- `[test]` 표에 테스트 명령 두 개를 쓴다. `quick` 은 바뀐 파일과 관련된 테스트만 돌리고 `{files}` 를 정확히 한 번 담는다(예: `npx vitest related --run --passWithNoTests {files}`, `npx jest --findRelatedTests --passWithNoTests {files}`). `full` 은 전체 테스트다. 관련 테스트가 없을 때 성공으로 끝나야 한다. pytest 처럼 모은 테스트가 없을 때 5 로 끝나는 도구는 `ok_exit = [0, 5]` 를 넣는다. 테스트가 DB·포트를 같이 써서 동시에 돌면 깨지면 `exclusive = true` 를 넣는다. `timeout_min`(기본 30)으로 한 번 실행의 상한을 정한다.
- hteam 은 커밋된 HEAD 의 tasks.toml 에서 `[test]` 를 읽는다. `[test]` 는 커밋해야 적용된다.
- 테스트 도구를 설치하는 첫 developer 태스크의 `acceptance` 에 "`[test]` 의 quick·full 명령이 실행된다" 를 넣는다.
- `[test]` 가 있으면 `hteam plan check` 가 묶음 규칙과 `[test]` 형식을 검사한다.
- 끝내기 전에 `.herdr-team/bin/hteam plan check --file docs/planning/tasks.toml` 이 통과해야 한다(리뷰 사전 검사도 같은 검사를 한다).

## voice.md 형식
절 제목과 용어집 표 머리를 아래 그대로 쓴다(문구 자동 검사가 읽는다). `쓰지 않는 표기` 칸에는 어디서나 쓰지 않는 표기만 쉼표로 넣는다. 특정 자리에서만 피하는 표기(예: 제목·링크에서만, 이용약관 안에서만)는 메모 칸에 적는다. 자동 검사는 이 칸의 표기를 모든 문서에서 찾고, 괄호로 조건을 붙인 표기는 검사하지 않는다. 증분 기획이면 기존 파일을 읽고 바뀌는 부분만 고친다.

```markdown
# 문구 기준

## 문체
- 서비스 문구: 해요체
- 정책 문서: 하십시오체
- 사용자 문서: 해요체
- 호칭: 생략. 필요하면 "회원님"

## 라벨
- 버튼·메뉴: 명사형("저장", "삭제")

## 용어집
| 쓰는 표기 | 쓰지 않는 표기 | 메모 |
|---|---|---|
| 로그인 | 로그 인, 로긴 | |
| 회원가입 | 회원 가입 | |
```

## 하지 않는 것
- 코드·디자인 산출물 만들기. `docs/planning/` 밖 파일 고치기.
