"""子进程沙箱测试：执行 LLM 产的 Python 源码（设计 v0.5 §4.3.3）。

M6 主沙箱路径是 M3 DSL；本子进程沙箱仅当 3b 需要 LLM 产 Python 源码时启用，为可选路径占位。

覆盖点：
- 正常代码：print('hello') → stdout 含 hello，returncode=0，timed_out=False
- 表达式求值：print(1+1) → stdout 含 2
- 超时 kill：无限循环 + timeout=0.5 → timed_out=True，returncode!=0
- 异常捕获：raise ValueError('x') → stderr 含 ValueError，returncode!=0，timed_out=False
- 空代码安全：run('') 不崩
- 模块说明：sandbox_subprocess 模块注释/docstring 说明 M6 主路径是 DSL，子进程为可选

TDD：本文件先于 sandbox_subprocess.py 编写，import 失败为预期红线。
"""
from __future__ import annotations

import quant.mining.sandbox_subprocess as mod
from quant.mining.sandbox_subprocess import SandboxResult, SubprocessSandbox


def test_run_simple_code() -> None:
    """正常代码执行：stdout 含预期输出，退出码 0。"""
    sb = SubprocessSandbox(timeout=5.0)
    r = sb.run("print('hello')")
    assert isinstance(r, SandboxResult)
    assert "hello" in r.stdout
    assert r.returncode == 0
    assert r.timed_out is False


def test_run_returns_value() -> None:
    """表达式求值：print(1+1) 输出 2。"""
    sb = SubprocessSandbox()
    r = sb.run("print(1+1)")
    assert "2" in r.stdout


def test_timeout_killed() -> None:
    """超时：无限循环 + 短 timeout → timed_out=True，returncode!=0。"""
    sb = SubprocessSandbox(timeout=0.5)
    r = sb.run("while True:\n    pass")
    assert r.timed_out is True
    assert r.returncode != 0


def test_exception_captured() -> None:
    """异常：raise ValueError → stderr 含异常名，returncode!=0，timed_out=False。"""
    sb = SubprocessSandbox()
    r = sb.run("raise ValueError('x')")
    assert "ValueError" in r.stderr
    assert r.returncode != 0
    assert r.timed_out is False


def test_empty_code_safe() -> None:
    """空代码：run('') 不抛异常，正常返回。"""
    sb = SubprocessSandbox()
    r = sb.run("")
    assert isinstance(r, SandboxResult)
    assert r.timed_out is False


def test_note_main_path_is_dsl() -> None:
    """模块说明：docstring 或注释声明 M6 主沙箱是 M3 DSL，子进程为可选路径占位。"""
    text = (mod.__doc__ or "") + "\n" + _module_source()
    assert "DSL" in text
    assert "可选" in text


def _module_source() -> str:
    """读取模块源码用于注释断言。"""
    import inspect

    return inspect.getsource(mod)
