<!-- herdr-team -->
# Codex 규칙 (herdr-team)

이 저장소에서 Codex 는 직무 워커이거나 리뷰어다. 프롬프트가 "너는 herdr-orch 워커다" 로 시작하면 프리앰블과 spec 을 따른다.

## 공통
- horch 명령은 셸 명령으로 실행한다(다른 도구에는 `HC_TERMINAL_ID` 가 없어 거부된다). 끝나면 프리앰블의 done 명령을 부른다.
- 대화형으로 사용자에게 묻지 않는다. 막히면 프리앰블의 ask 명령으로 메인에게 묻는다(관제가 메인에 올리고, 메인이 답한다).

## 작업 워커
- spec 의 owns 와 `docs/tasks/<태스크>/report.md` 만 고치고 커밋한다. 커밋은 경로를 지정한다: `git add -- <경로> && git commit -m "[T-xxx] …" -- <경로>`.
- `git stash`·`git reset`·`git checkout -- <파일>`·`git add -A`·`git add .` 를 쓰지 않는다. 같은 작업 폴더에서 다른 워커가 동시에 일한다.

## 리뷰어
- 리뷰 프롬프트의 `REVIEW_FILE` 하나만 쓴다. 다른 파일을 만들거나 고치거나 지우지 않는다.
- git 쓰기(add·commit·stash·reset·checkout 등)를 하지 않는다. 테스트·빌드 같은 확인 명령은 실행해도 된다. 네가 추적 파일 내용을 바꾸거나 HEAD 를 움직이면 판정이 무효가 된다.
- 리뷰 동안 다른 워커·관제·메인의 커밋으로 HEAD 가 움직이는 것은 정상이다. 그 때문에 멈추거나 묻지 않는다.
- 지적은 리뷰 프롬프트의 `REVIEW_FILE 형식` 대로 쓴다: 번호 `r<라운드>-F<n>`, 등급 `[P1|P2|P3]`, `파일:줄 — 문제. 고칠 방향.`. P1 은 `## 지적 사항`, P2·P3 는 `## 후속` 에 둔다. 칭찬과 범위 밖 제안은 쓰지 않는다.
- 리뷰 파일 마지막 줄은 정확히 `VERDICT: APPROVE` 또는 `VERDICT: REQUEST_CHANGES` 다. P1 이 있으면 REQUEST_CHANGES, 없으면 APPROVE 다.
