"""子进程沙箱：执行 LLM 产的 Python 源码（设计 v0.5 §4.3.3）。

M6 主沙箱路径是 M3 DSL 解释器（受控算子集合，无任意代码执行）；本模块仅当 3b 需要 LLM
直产 Python 源码时作为可选路径占位。安全部署注释：生产环境应叠加 seccomp/nsjail +
CPU/内存配额 + 只读根文件系统 + 网络禁用；M6 阶段保留占位，待后续接入强隔离方案。
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass


@dataclass
class SandboxResult:
    """子进程执行结果。"""

    stdout: str
    stderr: str
    returncode: int
    timed_out: bool


class SubprocessSandbox:
    """子进程沙箱：执行 LLM 产的 Python 源码，超时 kill。

    M6 主路径用 M3 DSL（受控算子），本子进程沙箱为可选路径占位。
    安全部署注释：生产应加 seccomp/nsjail + 资源限制（M6 占位，留后续）。
    """

    def __init__(self, timeout: float = 5.0, python: str = "") -> None:
        self.timeout = timeout
        # 空串 → sys.executable，保证与当前解释器一致
        self.python = python or sys.executable

    def run(self, code: str) -> SandboxResult:
        """子进程执行 code（python -c code）。

        超时 → kill 子进程，timed_out=True。
        子进程内异常 → 捕获 stderr，returncode!=0。
        安全部署注释：M6 占位，生产应加 seccomp/nsjail + 资源限制。
        """
        try:
            proc = subprocess.run(
                [self.python, "-c", code],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as e:
            # 超时：subprocess.run 内部已 kill 子进程
            out = e.stdout or ""
            err = e.stderr or ""
            if isinstance(out, bytes):
                out = out.decode("utf-8", "replace")
            if isinstance(err, bytes):
                err = err.decode("utf-8", "replace")
            return SandboxResult(
                stdout=out,
                stderr=err,
                returncode=-1,
                timed_out=True,
            )
        return SandboxResult(
            stdout=proc.stdout,
            stderr=proc.stderr,
            returncode=proc.returncode,
            timed_out=False,
        )
