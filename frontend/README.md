# crypto-quant frontend

React + Vite 前端（前台市場分析介面＋ `/admin` 後台）。正式環境由 FastAPI 直接服務 `frontend/dist/`。

本目錄**不另維護說明文件**，避免與主文件不同步（維護規則見開發指南）：

- 開發與啟動指令：根目錄 [`README.md`](../README.md) §2「快速啟動」
- 開發鐵律、測試、換行規則：[`docs/archive/部署與運維.md`](../docs/archive/部署與運維.md)（第二部：開發指南）；**改前端要 build 兩次**（本站 `:8000`＋區網入口 `:8080`）見同檔第一部 §10 與根 README §2
- 元件掛載狀態（哪些面板暫停顯示）：以 `src/App.jsx` 內註解為準
