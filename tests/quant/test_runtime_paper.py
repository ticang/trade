from quant.runtime.paper import run_paper_session


def test_run_paper_session_produces_auditable_summary() -> None:
    summary = run_paper_session(n_days=20, n_symbols=5, accounts=["acct-a", "acct-b"])

    assert summary.mode == "paper"
    assert summary.days_run == 20
    assert summary.account_count == 2
    assert summary.total_fills > 0
    assert summary.max_reconcile_diff < 0.001
    assert all(account.positions for account in summary.accounts)
    assert all(account.fills > 0 for account in summary.accounts)


def test_run_paper_session_is_deterministic() -> None:
    first = run_paper_session(n_days=5, n_symbols=3, accounts=["acct-a"])
    second = run_paper_session(n_days=5, n_symbols=3, accounts=["acct-a"])

    assert first.to_dict() == second.to_dict()
