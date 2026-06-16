# 前后端只读 API bridge 浏览器烟雾记录

日期：2026-06-16

## 环境

- 后端：`uvicorn quant.api.app:app --port 8000`
- 前端：`NEXT_PUBLIC_TRADE_API_BASE_URL=http://localhost:8000 npm run dev`
- 浏览器：Codex in-app browser，localhost 页面

## 结果

| 页面 | URL | 结果 | 截图 |
|---|---|---|---|
| 监控 | `http://localhost:3000/monitor` | PASS：无“加载中/加载失败”，展示账户、持仓、策略、风控、告警 API 数据 | `api-bridge-screenshots-2026-06-16/monitor.png` |
| 交易 | `http://localhost:3000/trade` | PASS：无“加载中/加载失败”，展示账户、持仓、委托、成交 API 数据；下单仍为本地模拟 | `api-bridge-screenshots-2026-06-16/trade.png` |
| 研究 | `http://localhost:3000/research` | PASS：无“加载中/加载失败”，展示因子评价、回测、策略生命周期 API 数据 | `api-bridge-screenshots-2026-06-16/research.png` |
| 复盘 | `http://localhost:3000/replay` | PASS：无“加载中/加载失败”，K 线与情绪曲线正常渲染 | `api-bridge-screenshots-2026-06-16/replay.png` |

## 控制台观察

- 无 API 失败导致的页面错误。
- 开发模式下 `/research` 与 `/replay` 触发 Recharts 依赖的 React `defaultProps` 未来兼容性 warning（`XAxis`/`YAxis`/`ReferenceLine`）。这是第三方库 warning，不影响当前只读 API bridge 验收；后续可在升级 Recharts 或切换图表组件时处理。
