"""DuckDB 跨进程单写权交接。

设计 v0.5 §6 写并发策略 + §9 DuckDB 单写进程：
- DuckDB 单写进程（盘中独占，盘后交接）
- 跨进程写权经 lockfile 协调：盘中进程 acquire 创建 lockfile（holder+pid+ts），
  盘后 release 删 lockfile 完成交接；其他进程见 lockfile 存在 → 拒绝/等待。
- 租约过期（>ttl）→ 后续 acquire 强制接管（防前进程崩溃留下僵尸租约）。
- release 仅在 holder 匹配时删 lockfile（防误删他人租约）。

注意：本模块仅协调写权归属，不真起 DuckDB 连接；连接由 DuckdbStore 持有。
"""
from __future__ import annotations

import os
import time
from pathlib import Path


class WriteLease:
    """跨进程写权租约（lockfile 机制）。

    盘中进程 acquire 写权（创建 lockfile，写 holder+pid+ts）；
    盘后 release（删 lockfile）完成交接。其他进程见 lockfile → 拒绝/等待。
    """

    def __init__(self, lockfile: Path, holder: str = "intraday", ttl: float = 86400) -> None:
        self.lockfile = Path(lockfile)
        self.holder = holder
        self.ttl = ttl

    def acquire(self, timeout: float = 0) -> bool:
        """创建 lockfile（写 holder+pid+ts）。

        - 不存在 → 创建并返回 True
        - 已存在且未过期 → 拒绝（timeout>0 则等待至过期或超时）
        - 已存在但过期（>ttl）→ 强制接管（覆盖写）
        """
        deadline = time.monotonic() + timeout
        while True:
            ts = time.time()
            if not self.lockfile.exists():
                self._write(ts)
                return True
            # 存在 → 判断是否过期
            if self._is_expired(ts):
                self._write(ts)
                return True
            # 未过期且无等待预算 → 拒绝
            if timeout <= 0:
                return False
            # 有等待预算 → 轮询到过期或超时
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.05, remaining))

    def release(self) -> None:
        """删 lockfile（仅当 holder 匹配，防误删他人租约）。不存在静默。"""
        if not self.lockfile.exists():
            return
        holder = self.current_holder()
        if holder == self.holder:
            try:
                self.lockfile.unlink()
            except FileNotFoundError:
                # 并发释放竞争：已被删，静默
                pass

    def is_held(self) -> bool:
        """lockfile 存在且未过期 → True。"""
        if not self.lockfile.exists():
            return False
        return not self._is_expired(time.time())

    def current_holder(self) -> str | None:
        """读 lockfile 第一行（holder）。不存在或损坏 → None。"""
        if not self.lockfile.exists():
            return None
        try:
            return self.lockfile.read_text().splitlines()[0].strip()
        except (OSError, IndexError):
            return None

    # ---- 内部 ----
    def _write(self, ts: float) -> None:
        """覆盖写 lockfile（holder\\npid\\nts）。"""
        self.lockfile.write_text(f"{self.holder}\n{os.getpid()}\n{ts}\n")

    def _is_expired(self, now: float) -> bool:
        """读 lockfile 第三行（ts），判断是否超过 ttl。损坏视为过期（可接管）。"""
        try:
            lines = self.lockfile.read_text().splitlines()
            ts = float(lines[2].strip())
        except (OSError, IndexError, ValueError):
            return True
        return (now - ts) > self.ttl


class DuckdbHandoff:
    """盘中→盘后 DuckDB 写权交接协调。"""

    def __init__(self, lease: WriteLease) -> None:
        self.lease = lease

    def intraday_acquire(self) -> bool:
        """盘中进程获取写权。"""
        return self.lease.acquire()

    def post_market_handoff(self) -> bool:
        """盘后释放写权（交接）。成功（lockfile 已不存在）返回 True。"""
        self.lease.release()
        return not self.lease.is_held()

    def can_write(self) -> bool:
        """当前进程是否持有写权。

        简化：lockfile 存在且未过期，且 holder 与本 lease 一致。
        """
        if not self.lease.is_held():
            return False
        return self.lease.current_holder() == self.lease.holder
