"""묵상 일기 비서. 출입구에서는 이렇게 연결한다:

    import chat
    app.include_router(chat.router)
"""
from .routes import router  # noqa: F401
