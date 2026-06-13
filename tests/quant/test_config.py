from quant.config import Config, load_config


def test_load_config_from_yaml(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "sqlite_path: data/trade.db\nduckdb_path: data/trade.duckdb\n"
        "log_level: INFO\naccounts: [{account_id: acct1, broker: sim, env: paper}]",
        encoding="utf-8",
    )
    cfg = load_config(cfg_file)
    assert cfg.sqlite_path == "data/trade.db"
    assert cfg.log_level == "INFO"
    assert len(cfg.accounts) == 1 and cfg.accounts[0].account_id == "acct1"


def test_config_defaults_when_minimal(tmp_path):
    cfg_file = tmp_path / "c.yaml"
    cfg_file.write_text("accounts: []", encoding="utf-8")
    cfg = load_config(cfg_file)
    assert cfg.log_level == "INFO"
