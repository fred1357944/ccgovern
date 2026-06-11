# CCGovern — 團隊 AI 編碼工具成本治理

> **Team cost governance for AI coding tools.** Aggregate every developer's Claude Code
> usage into a team dashboard with budget alerts, policy enforcement, and manager reports.
> **Fully self-hosted** — usage data never leaves your network. Zero cloud dependency,
> zero extra runtime deps beyond Textual. MIT licensed.

彙總團隊中每位開發者的 Claude Code 用量，算出成本，提供**團隊成本 dashboard、預算告警、政策檢查、經理月報**。
為「多開發者匯總 + 多廠商擴充」而設計；目前支援 Claude Code，架構預留 Cursor/Copilot 擴充。

繁體中文介面 · vim 風格導航 · 深色主題 · cache-first 啟動 · **全部跑在你自己的內網**。

## 為什麼是這個

個人版 token 工具已被 Anthropic 原生 Tool Search（2026-01）與免費競品（McPick）覆蓋。
唯一可商業化且 Anthropic 結構上不會做的，是**「多廠商 × 組織層」**的成本治理：
跨開發者彙總、預算上限、政策強制、經理/CFO dashboard。CCGovern 切的是這一塊。

## 安裝

```bash
cd ~/Projects/ccgovern
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

## 快速開始（看 demo）

```bash
ccgovern-demo     # 產生 4 位假開發者的用量（含 1 個預算告警 + 1 個政策違規）並匯入
ccgovern          # 開啟團隊 dashboard，4 個分頁應全有資料
```

## 真實使用（v0.2：HTTP 多機上傳）

管理者機器起中央伺服器：

```bash
ccgovern-server --token <共享密鑰>      # 預設埠 8377，純 stdlib 零依賴
```

每位開發者在自己機器跑（可排 cron）：

```bash
ccgovern-collect --upload http://<server>:8377 --token <共享密鑰>
# 或離線模式：ccgovern-collect --out <共享匯入目錄>
```

管理者檢視與匯出：

```bash
ccgovern                                # TUI dashboard（自動匯入 ingest 目錄）
ccgovern-report --month 2026-06         # 產經理月報（Markdown + CSV，給經理/財務）
```

## 分頁

| 分頁 | 內容 |
|------|------|
| **團隊總覽** | 每位開發者本月花費 vs 預算、狀態燈、主要模型；團隊合計 |
| **開發者明細** | 單一開發者的每日趨勢（估算）、模型花費分佈 |
| **預算/告警** | 設定團隊/個人月預算上限，預估月底超支告警 |
| **政策** | 允許的 model/MCP/plugin 清單，違規列表 |

vim 導航：`j/k` 移動 · `g/G` 頂/底 · `/` 搜尋 · `1/2/3/4` 切分頁 · `R` 重新匯入。

## 資料與成本

- 用量來源：每位開發者本機 `~/.claude/projects/**/*.jsonl`（token tier）+ `~/.claude/stats-cache.json`（模型維度）。
- **成本未儲存於資料中**，由 token × 模型定價自算（2026：Opus $5/$25、Sonnet $3/$15、Haiku $1/$5 每 1M；cache_read 0.1×、cache_write 1.25×）。
- 每日每模型成本為**估算**（用 all-time tier 比例拆分），總額以 stats-cache 的 modelUsage 為準。

## 部署模式（自架，買斷友善）

CCGovern **沒有任何雲端元件**，全部跑在客戶端：

```
開發者 A 機器 ─ ccgovern-collect ─┐
開發者 B 機器 ─ ccgovern-collect ─┼─ HTTP →  管理者機器（內網）
開發者 C 機器 ─ ccgovern-collect ─┘          ├ ccgovern-server  （收報告，純 stdlib）
                                             ├ ccgovern         （TUI dashboard）
                                             ├ ccgovern-report  （經理月報 md/csv）
                                             └ ccgovern-alert   （Slack 告警，可排 cron）
```

- `--token` 的密鑰是**管理者自訂的共享密碼**（如 `openssl rand -hex 16`），只是擋雜訊，不涉及任何外部服務
- 不想架 server 也行：`ccgovern-collect --out <共享資料夾>`（Dropbox/NAS）即可
- 用量資料**永遠不出客戶內網** —— 對在意隱私/合規的團隊，這比 SaaS 更好賣

## 告警（可排 cron）

```bash
ccgovern-alert --dry-run                                    # 先看會發什麼
ccgovern-alert --slack-webhook https://hooks.slack.com/...  # 發到 Slack
```

通知內容：已超支 / 預估月底超支的預算 + error 級政策違規。無事不發。

## 架構

```
src/ccgovern/
├── util/atomic_io.py     # atomic 寫檔 + 備份
├── models/               # usage / report / governance
├── collector/            # 每開發者本機：解析 → 算成本 → 產 DeveloperReport
├── server/               # 匯總：ingest → SQLite → aggregate/budget/policy
├── demo/seed.py          # 假團隊資料產生器
└── tui/                  # 4 分頁 dashboard
```

設定與資料：`~/.config/ccgovern/`（settings.json / ccgovern.db / ingest/）。
