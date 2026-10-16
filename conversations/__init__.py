"""돌아보기 비서와 나눈 대화 기록. 출입구에서는 이렇게 연결한다:

    import conversations
    app.include_router(conversations.router)
"""
from .routes import router  # noqa: F401
