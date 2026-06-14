"""DuckDB 跨进程单写权交接测试。

设计 v0.5 §6 写并发策略 + §9 DuckDB 单写进程：
- 盘中进程独占写 DuckDB（acquire 写权 → lockfile 标记 holder+pid+ts）
- 盘后释放写权（release → 删 lockfile）完成交接
- 其他进程见 lockfile 存在 → 拒绝/等待；过期（>ttl）→ 强制接管
- lockfile holder 不匹配 → 防误删他人租约

本测试只验 lockfile 租约语义，不真起 DuckDB/进程。
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from quant.data.duckdb_handoff import DuckdbHandoff, WriteLease


def _write_lockfile(lockfile: Path, holder: str, ts: float) -> None:
    """直接写一个 lockfile（模拟过期租约/外部进程写入）。"""
    lockfile.write_text(f"{holder}\n{os.getpid()}\n{ts}\n")


def test_acquire_creates_lockfile(tmp_path: Path) -> None:
    """acquire 成功 → lockfile 存在，内容含 holder。"""
    lease = WriteLease(tmp_path / "writer.lock", holder="intraday")
    assert lease.acquire()
    lockfile = tmp_path / "writer.lock"
    assert lockfile.exists()
    content = lockfile.read_text()
    assert "intraday" in content


def test_acquire_when_held_returns_false(tmp_path: Path) -> None:
    """已 acquire 再 acquire → False（租约未过期，拒绝）。"""
    lease = WriteLease(tmp_path / "writer.lock", holder="intraday")
    assert lease.acquire()
    assert lease.acquire() is False


def test_release_removes_lockfile(tmp_path: Path) -> None:
    """acquire + release → lockfile 不存在。"""
    lease = WriteLease(tmp_path / "writer.lock", holder="intraday")
    lease.acquire()
    lease.release()
    assert not (tmp_path / "writer.lock").exists()


def test_release_wrong_holder_keeps(tmp_path: Path) -> None:
    """holder A acquire，holder B release → lockfile 仍在（防误删他人租约）。"""
    lease_a = WriteLease(tmp_path / "writer.lock", holder="intraday")
    lease_a.acquire()
    lease_b = WriteLease(tmp_path / "writer.lock", holder="postmarket")
    lease_b.release()
    assert (tmp_path / "writer.lock").exists()


def test_expired_lock_takeover(tmp_path: Path) -> None:
    """lockfile ts 过期（>ttl）→ 新 acquire 强制接管成功。"""
    lockfile = tmp_path / "writer.lock"
    ttl = 1.0
    # 写一个已过期 5s 的旧租约（holder=intraday，但 ts 远早于 ttl）
    _write_lockfile(lockfile, "intraday", ts=time.time() - ttl - 5)
    lease = WriteLease(lockfile, holder="postmarket", ttl=ttl)
    # 旧租约已过期 → 接管
    assert lease.acquire() is True
    assert lease.current_holder() == "postmarket"


def test_current_holder(tmp_path: Path) -> None:
    """acquire 后 current_holder 返回 holder；未持有 → None。"""
    lease = WriteLease(tmp_path / "writer.lock", holder="intraday")
    assert lease.current_holder() is None
    lease.acquire()
    assert lease.current_holder() == "intraday"


def test_handoff_intraday_to_postmarket(tmp_path: Path) -> None:
    """DuckdbHandoff: intraday_acquire → can_write True；post_market_handoff → False。"""
    lease = WriteLease(tmp_path / "writer.lock", holder="intraday")
    handoff = DuckdbHandoff(lease)
    assert handoff.intraday_acquire() is True
    assert handoff.can_write() is True
    assert handoff.post_market_handoff() is True
    assert handoff.can_write() is False


def test_is_held(tmp_path: Path) -> None:
    """acquire → is_held True；release → False。"""
    lease = WriteLease(tmp_path / "writer.lock", holder="intraday")
    assert lease.is_held() is False
    lease.acquire()
    assert lease.is_held() is True
    lease.release()
    assert lease.is_held() is False
