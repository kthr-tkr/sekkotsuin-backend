"""簡易のレート制限（プロセス内メモリ）。ログインや本人確認の総当たりを防ぐ。

複数プロセスで動かす場合は Redis などの共有ストアに置き換える。
"""

import time
from collections import defaultdict, deque

from fastapi import HTTPException, status


class RateLimiter:
    def __init__(self, max_attempts: int, window_sec: int) -> None:
        self.max_attempts = max_attempts
        self.window_sec = window_sec
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def hit(self, key: str) -> None:
        """1回分を記録し、上限を超えていれば 429 を返す。"""
        now = time.monotonic()
        q = self._hits[key]
        while q and q[0] <= now - self.window_sec:
            q.popleft()
        if len(q) >= self.max_attempts:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "試行回数が多すぎます。しばらくしてからもう一度お試しください。",
            )
        q.append(now)

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)

    def clear(self) -> None:
        self._hits.clear()


# ログイン: 同じ ID に 15 分で 10 回まで。本人確認: 同じ接続元から 15 分で 10 回まで
login_limiter = RateLimiter(max_attempts=10, window_sec=15 * 60)
verify_limiter = RateLimiter(max_attempts=10, window_sec=15 * 60)
# パスワード再設定のメール: 同じアドレスに 1 時間で 3 回まで
reset_limiter = RateLimiter(max_attempts=3, window_sec=60 * 60)
