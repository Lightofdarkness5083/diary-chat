"""7단계 묵상 인도 (묵상 부분). main.py에서는 이렇게 연결한다:

    import meditation
    app.include_router(meditation.router)
"""
from .routes import router  # noqa: F401
