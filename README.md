# trade

## Full Gate

Use the full gate before treating the project as ready:

```powershell
$env:QMT_USERDATA_PATH='D:\迅投极速交易终端 睿智融科版\userdata'
$env:QMT_ACCOUNT='<account-id>'
.\.venv\Scripts\python.exe -m probes.full_gate
```

After installing the package in editable mode, the console entry is also
available from the virtualenv scripts directory:

```powershell
.\.venv\Scripts\trade-full-gate.exe
```

If `.venv\Scripts` is already on `PATH`, `trade-full-gate` also works.

The full gate runs local deterministic regression first, then external/QMT
readiness:

- `tests\probes -m "not network" -q`
- `tests\quant -m "not network" -q`
- `git diff --check`
- `probes.project_gate`

Current known external blockers are reported as `BLOCKED`, not hidden:

- QMT trading readonly handshake can pass while MiniQuote realtime market data
  remains blocked.
- `live_readiness=BLOCKED` means automatic live trading is not allowed.
- AkShare daily snapshot is optional; BaoStock and LLM checks are required.

`status=BLOCKED` is expected until QMT/MiniQMT exposes realtime tick or recent
minute bars to the Python API, or another approved realtime source reports
`PASS/REALTIME`.

## Paper Runtime

The project has a runnable paper-trading runtime that does not touch QMT order
APIs:

```powershell
.\.venv\Scripts\trade-paper-run.exe
```

It executes:

- deterministic market panel
- `MomentumFactor`
- `StrategyRunner`
- `SimBrokerLive`
- `on_fill` dispatch
- end-of-day `reconcile`

The command prints a JSON summary, for example:

```json
{"mode":"paper","days_run":20,"account_count":2,"total_fills":12,"max_reconcile_diff":0.0}
```

Use this mode for production dry runs, scheduler smoke tests, dashboard/API
smoke, and strategy plumbing validation while QMT realtime market data remains
blocked.

## Live Runtime Status

QMT trading-side readonly checks can pass, but automatic live trading still
requires a realtime market data source with `PASS/REALTIME` quality.

Current known live blocker:

- MiniQuote `58610` connects but does not expose valid realtime tick or recent
  minute bars to the Python API.

Until that external permission/startup-mode issue is resolved, live trading must
stay off. Paper runtime and read-only API/runtime checks are safe to run.
