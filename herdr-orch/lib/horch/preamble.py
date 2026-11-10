"""워커 프리앰블(설계 8장). 명령은 horch 절대 경로와 --home 을 포함한 그대로 넣는다."""
from __future__ import annotations


CONTINUED = "   이 세션은 앞 태스크를 이어 받았을 수 있다. 앞 대화의 Task·Dispatch ID 는 쓰지 않는다. 이 프리앰블의 ID 만 쓴다.\n"


def render(*, task_id: str, dispatch_id: str, spec_path: str, horch: str, continued: bool = False) -> str:
    """continued 는 고정 터미널에 다시 넣는 Dispatch(--terminal)다. 1항 뒤에 이어 받기 줄을 넣는다(설계 13.4 의 4)."""
    d = dispatch_id
    cont = CONTINUED if continued else ""
    return f"""너는 herdr-orch 워커다. Task {task_id}, Dispatch {d}.

1. 먼저 spec 파일을 읽고 그 일만 한다: {spec_path}
{cont}2. 막히면 코디네이터에게 묻고 답이 올 때까지 기다린다:
   {horch} ask --dispatch {d} --question "<질문>" [--key <key>]
   exit 4(시간 초과)면 출력의 question id 로 다시 기다린다: {horch} ask --dispatch {d} --resume <question id>
   같은 질문을 새로 하려면 다른 `--key` 를 준다(같은 key·같은 본문은 이전 답을 돌려준다).
   대화형 질문 도구(AskUserQuestion 등)는 쓰지 않는다. 사람이 보지 않는다.
3. 새 파일을 시작하기 전, 테스트를 돌린 뒤, done 직전에 소유자 메시지를 읽는다:
   {horch} check --dispatch {d}
   메시지를 처리한 뒤 {horch} check --dispatch {d} --ack <delivery> 를 count 가 0 이 될 때까지 반복한다.
4. 범위 밖 문제가 있거나 진행할 수 없으면: {horch} escalate --dispatch {d} --body "<내용>"
5. 끝나면 다음으로 보고한다. 실패도 --outcome failed 로 보고한다(문장으로만 쓰지 않는다).
   {horch} done --dispatch {d} --outcome succeeded|failed --summary "<세 문장 요약>" [--report-path <경로>] [--files-modified <경로>](파일마다 반복)
   출력을 못 받았으면 같은 인자로 다시 실행한다. done 뒤에는 새 일을 시작하지 않고 기다린다.
6. horch 는 셸 명령으로 실행한다(다른 도구에는 $HC_TERMINAL_ID 가 없어 거부된다). horch 로 다른 워커를 띄우지 않는다.
   도구 시간 초과 등으로 horch 출력을 못 받았으면 같은 명령을 그대로 다시 실행한다(ask·check·done 은 재호출 안전. escalate 는 다시 보내면 같은 보고가 한 번 더 간다).
"""
