#!/bin/bash
# CCGovern 啟動器 — 雙擊即可開啟
cd "$(dirname "$0")" || exit 1
if [ ! -d ".venv" ]; then
    echo "首次啟動，建立環境中…"
    uv venv .venv && source .venv/bin/activate && uv pip install -e .
else
    source .venv/bin/activate
fi
clear
exec ccgovern
