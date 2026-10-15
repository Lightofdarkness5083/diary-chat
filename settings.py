"""설정 읽기: .env 파일의 '이름=값' 줄을 환경변수로 읽는다."""
import os
from pathlib import Path

ROOT = Path(__file__).parent


def load_env():
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                name, value = line.split("=", 1)
                os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


# AI 지시문(프롬프트)은 저장소에 두지 않는다. 아래 순서로 찾는다.
#   1. PROMPTS_DIR 환경변수가 가리키는 폴더 (시험할 때)
#   2. /etc/secrets  : Render의 Secret Files (인터넷에 올린 서버)
#   3. prompts/      : 내 컴퓨터에서 쓸 때. .gitignore로 막혀 있어 Git에 올라가지 않는다
PROMPT_NAMES = ["meditation_system.md", "meditation_record.md", "meditation_finish.md",
                "meditation_suggest.md", "chat_system.md"]


class PromptMissing(RuntimeError):
    """서버에 AI 지시문이 없다."""


def read_prompt(name):
    places = [os.environ.get("PROMPTS_DIR", ""), "/etc/secrets", str(ROOT / "prompts")]
    for place in places:
        if place and (Path(place) / name).is_file():
            return (Path(place) / name).read_text(encoding="utf-8")
    raise PromptMissing(f"AI 지시문이 서버에 없습니다: {name}")
