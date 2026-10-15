"""일기장. 출입구에서는 이렇게 연결한다:

    import diary
    app.include_router(diary.router)
"""
from .routes import router  # noqa: F401
