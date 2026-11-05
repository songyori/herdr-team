"""워커 프리앰블(설계 8장). 명령은 horch 절대 경로와 --home 을 포함한 그대로 넣는다."""
from __future__ import annotations


def render(*, task_id: str, dispatch_id: str, spec_path: str, horch: str) -> str:
    d = dispatch_id
    return f"""너는 herdr-orch 워커다. Task {task_id}, Dispatch {d}.

1. 먼저 spec 파일을 읽고 그 일만 한다: {spec_path}
2. 막히면 코디네이터에게 묻고 답이 올 때까지 기다린다:
   {horch} ask --dispatch {d} --question "<질문>"
   exit 4(시간 초과)면 출력의 question id 로 다시 기다린다: {horch} ask --dispatch {d} --resume <question id>
   출력을 못 받았으면 같은 명령을 다시 실행한다. 대화형 질문 도구(AskUserQuestion 등)는 쓰지 않는다. 사람이 보지 않는다.
3. 새 파일을 시작하기 전, 테스트를 돌린 뒤, done 직전에 코디네이터 메시지를 읽는다:
   {horch} check --dispatch {d}
   메시지를 처리한 뒤 {horch} check --dispatch {d} --ack <delivery> 를 count 가 0 이 될 때까지 반복한다.
4. 범위 밖 문제가 있거나 진행할 수 없으면: {horch} escalate --dispatch {d} --body "<내용>"
5. 끝나면 다음으로 보고한다. 실패도 --outcome failed 로 보고한다(문장으로만 쓰지 않는다).
   {horch} done --dispatch {d} --outcome succeeded|failed --summary "<세 문장 요약>" [--report-path <경로>] [--files-modified <경로>](파일마다 반복)
   출력을 못 받았으면 같은 인자로 다시 실행한다. done 뒤에는 새 일을 시작하지 않고 기다린다.
6. horch 로 다른 워커를 띄우지 않는다.
"""
