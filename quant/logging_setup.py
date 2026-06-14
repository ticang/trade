import logging
import sys


def setup_logging(level: str = "INFO") -> None:
    """配置根 logger：统一格式 `时间 级别 名称 消息`，输出到 stderr，setLevel。幂等（避免重复 handler）。"""
    root = logging.getLogger()
    # 幂等：已有 handler 不重复加
    if root.handlers:
        root.setLevel(getattr(logging, level.upper(), logging.INFO))
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
