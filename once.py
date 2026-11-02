"""같은 요청은 한 번만: 화면이 연결이 끊긴 줄 알고 같은 요청(같은 요청 번호)을 다시 보내면,
AI를 다시 부르거나 다시 저장하지 않고 처음 답을 그대로 돌려준다.

  처음 요청이 아직 답을 만드는 중이면, 다시 온 요청은 그 답을 기다렸다가 같은 답을 받는다.
  잘 끝난 답만 기억한다(10분, 최근 500개). 실패한 답은 기억하지 않아 다시 시도할 수 있다.
  요청 번호가 없으면(예전 화면) 그냥 한 번 실행한다.

서버 한 곳(한 프로세스)의 기억이다. 서버가 다시 켜지면 비워진다.
"""
import threading
import time
from collections import OrderedDict

from fastapi.responses import Response

KEEP_SECONDS, KEEP_COUNT, WAIT_SECONDS = 600, 500, 180


class Once:
    def __init__(self):
        self._items = OrderedDict()
        self._lock = threading.Lock()

    def _forget_old(self, now):
        while self._items:
            key, item = next(iter(self._items.items()))
            if len(self._items) <= KEEP_COUNT and now - item["at"] < KEEP_SECONDS:
                break
            self._items.pop(key)

    def run(self, key, work):
        if not key:
            return work()
        now = time.monotonic()
        with self._lock:
            self._forget_old(now)
            item = self._items.get(key)
            mine = item is None
            if mine:
                item = {"at": now, "done": threading.Event(), "result": None, "failed": False}
                self._items[key] = item
        if not mine:
            item["done"].wait(WAIT_SECONDS)
            if item["done"].is_set() and not item["failed"]:
                return item["result"]
            return work()                     # 처음 요청이 실패했거나 너무 오래 걸렸다: 이번 요청이 직접 한다
        try:
            result = work()
        except Exception:
            item["failed"] = True
            with self._lock:
                self._items.pop(key, None)
            item["done"].set()
            raise
        if isinstance(result, Response) and result.status_code >= 400:   # 실패한 답은 기억하지 않는다
            item["failed"] = True
            with self._lock:
                self._items.pop(key, None)
        item["result"] = result
        item["done"].set()
        return result
