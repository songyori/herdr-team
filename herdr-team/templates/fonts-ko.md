# 한글 글꼴

디자인 디렉터(director)가 톤 시안과 디자인 시스템의 글꼴을 정할 때, 디자인 시스템이 없는 프로젝트의 화면 디자이너(designer)가 글꼴을 고를 때 읽는다. 팔레트 배정(`hteam palette deal`)의 `body_font` 는 아래 표에서 배정이 "예" 인 글꼴에서 나온다. 같은 목록이 플러그인 카탈로그 `fonts-ko.json` 에 있다(조사 2026-11-18).

## 1. 후보
| 이름 | 계열 | 성격 | 라이선스 | 예약 이름 | 받는 곳 | 배정 |
|---|---|---|---|---|---|---|
| SUIT | 돋움 | 단정한 네오 그로테스크, 9굵기·가변 | OFL-1.1 | SUIT | https://github.com/sun-typeface/SUIT | 예 |
| SUITE | 돋움 | 단정한 네오 그로테스크, 정적 7굵기 | OFL-1.1 | SUITE | https://github.com/sun-typeface/SUITE | 예 |
| Wanted Sans | 돋움 | 라틴 짝이 좋은 돋움, 7굵기·가변 | OFL-1.1 | 없음 | https://github.com/wanteddev/wanted-sans | 예 |
| Spoqa Han Sans Neo | 돋움 | 담백하고 작은 글자에서 잘 읽힌다, 5굵기 | OFL-1.1 | Spoqa Han Sans, Spoqa Han Sans JP, Spoqa Han Sans Neo | https://github.com/spoqa/spoqa-han-sans | 예 |
| IBM Plex Sans KR | 돋움 | 기술적·휴머니스트, 7굵기 | OFL-1.1 | Plex | https://fonts.google.com/specimen/IBM+Plex+Sans+KR | 예 |
| Gothic A1 | 돋움 | 고딕, 9굵기 | OFL-1.1 | 없음 | https://fonts.google.com/specimen/Gothic+A1 | 예 |
| Asta Sans | 돋움 | 가변(300–800) 돋움 | OFL-1.1 | 없음 | https://fonts.google.com/specimen/Asta+Sans | 예 |
| Hahmlet | 부리 | 가변 부리, 제목에도 맞다 | OFL-1.1 | 없음 | https://fonts.google.com/specimen/Hahmlet | 예 |
| Gowun Batang | 부리 | 손맛 있는 바탕, 2굵기 | OFL-1.1 | 없음 | https://fonts.google.com/specimen/Gowun+Batang | 예 |
| Gowun Dodum | 돋움 | 손맛 있는 돋움, 1굵기 | OFL-1.1 | 없음 | https://fonts.google.com/specimen/Gowun+Dodum | 예 |
| Noto Serif KR | 부리 | 본문 부리, 가변(200–900) | OFL-1.1 | 없음 | https://fonts.google.com/specimen/Noto+Serif+KR | 예 |
| Nanum Myeongjo | 부리 | 본문 부리, 3굵기 | OFL-1.1 | Nanum, Naver Nanum, NanumGothic, Naver NanumGothic, NanumMyeongjo, Naver NanumMyeongjo, NanumBrush, Naver NanumBrush, NanumPen, Naver NanumPen | https://fonts.google.com/specimen/Nanum+Myeongjo | 예 |
| Song Myung | 부리 | 부리, 1굵기 | OFL-1.1 | 없음 | https://fonts.google.com/specimen/Song+Myung | 예 |
| Orbit | 돋움 | 표시용에 가까운 둥근 돋움 | OFL-1.1 | 없음 | https://fonts.google.com/specimen/Orbit | 아니오 |
| Do Hyeon | 표시 | 제목·로고용 | OFL-1.1 | 없음 | https://fonts.google.com/specimen/Do+Hyeon | 아니오 |
| Black Han Sans | 표시 | 굵은 제목·로고용 | OFL-1.1 | 없음 | https://fonts.google.com/specimen/Black+Han+Sans | 아니오 |
| Jua | 손글씨 | 둥근 손글씨 느낌, 제목용 | OFL-1.1 | 없음 | https://fonts.google.com/specimen/Jua | 아니오 |
| Galmuri | 표시 | 픽셀 글꼴 | OFL-1.1 | 없음 | https://github.com/quiple/galmuri | 아니오 |
| MaruBuri | 부리 | 본문 부리 | 확인 못 함 | 확인 못 함 | https://hangeul.naver.com/font | 아니오 |
| NanumSquare Neo | 돋움 | 네모꼴, 가변 | 확인 못 함 | 확인 못 함 | https://hangeul.naver.com/font | 아니오 |
| LINE Seed Sans KR | 돋움 | 둥근 기하 | 확인 못 함 | 확인 못 함 | https://seed.line.me | 아니오 |
| Gmarket Sans | 돋움 | 굵은 기하, 제목용 | 확인 못 함 | 확인 못 함 | https://corp.gmarket.com/fonts | 아니오 |
| Paperlogy | 돋움 | 제목·본문 | 확인 못 함 | 확인 못 함 | https://github.com/fonts-archive/Paperlogy | 아니오 |

- 배정 대상은 라이선스 원문을 확인한 OFL 글꼴 가운데 본문에 쓰는 돋움·부리이고 과용 목록에 없는 것이다.
- 라이선스가 "확인 못 함" 인 글꼴은 참고로만 적었다. 쓰려면 받는 곳에서 라이선스 원문을 직접 확인하고 시스템 README 에 근거를 적는다.
- 표시·손글씨 계열은 제목·로고에만 쓴다. 본문에 쓰지 않는다.
- 굵기가 하나뿐인 글꼴은 강조를 굵기 대신 크기·색으로 한다(브라우저가 굵기를 합성하지 않게, design-rules §4 의 2).
- 고른 글꼴은 이름·라이선스·받는 곳 URL 을 시스템 README 에 적는다.

## 2. 과용 글꼴
근거(브랜드 자산, 사용자 선택) 없이 본문·제목 글꼴로 쓰지 않는다(design-rules §1 의 7). 쓰면 근거를 `direction.md` 와 시스템 README 에 적는다. 리뷰 자동 검사가 같은 목록으로 찾는다.
- 한글: Pretendard, Noto Sans KR(본고딕), Nanum Gothic, 시스템 글꼴(Apple SD Gothic Neo, Malgun Gothic·맑은 고딕, `system-ui`, `-apple-system`, `BlinkMacSystemFont`, `ui-sans-serif`·`sans-serif`·`ui-serif`·`serif` 처럼 이름 대신 쓰는 일반 글꼴)
- 라틴: Inter, Roboto, Open Sans, Poppins, Montserrat, DM Sans, Plus Jakarta Sans, Space Grotesk, Geist, Fraunces
- 판정: 글꼴 스택(`font-family`)의 첫 글꼴이 라틴 과용 글꼴이면 과용이다. 한글을 그리는 글꼴은 스택에서 라틴 과용 글꼴이 아닌 첫 글꼴이다. 그것이 한글 과용 글꼴이면 과용이다. 이름은 대소문자·공백·따옴표와 끝의 `Variable`·`VF` 를 빼고 견준다.

## 3. 라틴·숫자 짝짓기
- 한글 글꼴도 라틴·숫자 글리프를 품는다. 라틴·숫자에 다른 성격을 주려면 라틴 글꼴을 스택 앞에 둔다(`font-family: "<라틴 글꼴>", "<한글 글꼴>", <일반 글꼴>`). 라틴 글꼴은 한글 글리프가 없어 한글은 다음 글꼴이 그린다.
- 더 정확히 나누려면 `@font-face` 의 `unicode-range` 로 라틴(`U+0000-00FF` 등)만 다른 글꼴에 맡긴다.
- 라틴 짝에도 과용 목록이 적용된다(위 2). 첫 글꼴이 Inter 면 한글 글꼴이 무엇이든 과용으로 본다.
- 계열을 엇갈려 쓰는 것(부리 본문 + 돋움 제목, 돋움 본문 + 표시 제목)도 큰 차이를 만든다.

## 4. 글꼴 파일 넣기와 서브셋
- 화면 시안 `index.html` 은 외부 리소스(웹 글꼴 CDN 포함)를 쓰지 않는다. 글꼴 파일을 `assets/<화면>/`(디자이너) 또는 시스템 사본 `docs/design/system/`(디렉터)에 넣고 상대 경로로 부른다. 쓰는 굵기의 파일을 모두 넣고 `font-display: swap` 을 쓴다(design-rules §4 의 2).
- 기본은 받는 곳에서 받은 원본 글꼴 파일을 고치지 않고 그대로 넣는 것이다. 파일과 함께 라이선스 원문(OFL.txt)과 저작권 표시를 둔다.
- 서브셋(쓰는 글자만 남기기. 한글 글꼴은 커서 design-rules §4 의 2 가 권한다)·형식 바꾸기로 만든 파일은 OFL 의 바꾼 판(Modified Version)이다(OFL FAQ, https://openfontlicense.org/ofl-faq/). 위 표의 "예약 이름"(Reserved Font Name)이 있는 글꼴은 바꾼 판에 그 이름을 쓸 수 없다. 서브셋하려면 글꼴 안의 이름(name 테이블의 패밀리·전체·PostScript 이름)과 파일 이름, CSS `font-family` 이름을 모두 예약 이름이 들어가지 않는 새 이름(예: `<프로젝트>-본문`)으로 바꾼다. 원래 이름에 무언가를 덧붙인 이름도 예약 이름을 담으므로 쓰지 않는다. 파일 이름·`font-family` 만 바꾸면 글꼴 안의 이름이 그대로라 안 된다.
- 이름을 바꾸기 어려우면 서브셋하지 않고 원본을 넣거나, 저작권자·Google Fonts 가 배포하는 서브셋 파일을 받은 그대로 넣는다(고치지 않았으므로 바꾼 판이 아니다).
- 예약 이름이 "없음" 인 글꼴도 바꾼 판에는 OFL 원문과 저작권 표시를 두고 바꾼 사실을 시스템 README 에 적는다. "확인 못 함" 인 글꼴은 라이선스를 직접 확인하기 전에는 바꾸지 않는다.

## 5. 기울임
한글에는 기울임을 쓰지 않는다. 한글 글꼴에는 기울임체가 없어 브라우저가 기울여 합성한다(design-rules §4 의 7). 강조는 굵기나 색으로 한다.
