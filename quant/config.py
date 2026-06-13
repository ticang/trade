from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class AccountConfig:
    account_id: str
    broker: str
    env: str
    name: str = ""


@dataclass
class Config:
    sqlite_path: str = "data/trade.db"
    duckdb_path: str = "data/trade.duckdb"
    log_level: str = "INFO"
    accounts: list[AccountConfig] = field(default_factory=list)


def load_config(path: Path | str) -> Config:
    """从 YAML 文件加载配置，缺失字段走 dataclass 默认值。"""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    accounts = [
        AccountConfig(
            account_id=a["account_id"],
            broker=a.get("broker", ""),
            env=a.get("env", ""),
            name=a.get("name", ""),
        )
        for a in data.get("accounts", [])
    ]
    return Config(
        sqlite_path=data.get("sqlite_path", "data/trade.db"),
        duckdb_path=data.get("duckdb_path", "data/trade.duckdb"),
        log_level=data.get("log_level", "INFO"),
        accounts=accounts,
    )
