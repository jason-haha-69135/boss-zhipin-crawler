<div align="center">

# Spec-Driven Agent Engineering Tutorial
### 从 0 到 1 手把手构建规范驱动（Spec-Driven）与评测驱动（Eval-Driven）AI Agent 系统

🌐 **[简体中文路径 (Chinese Track)](#简体中文教程目录)** &nbsp;|&nbsp; **[English Track](#english-tutorial-track)** &nbsp;|&nbsp; **[返回仓库主页 / Back to Repo](../README.md)**

</div>

---

<a id="简体中文教程目录"></a>

## 🇨🇳 简体中文版：从空白文件夹到生产级五阶段求职 Agent

### 为什么要写这套教程？
大多数刚开始接触 **Vibe Coding 工具**（如 Antigravity、Codex、Claude Code、Cursor）的开发者都会经历同一个困境：
- **第 1 天**：“太神了！一句话就生成了一个能跑的 Demo！”
- **第 3 天**：“怎么改了 B 功能，A 功能坏了？Prompt 越写越长，幻觉越来越多，根本不敢上线……”

这套教程以本仓库 **BOSS直聘智能求职分析 Agent（`boss-zhipin-crawler`）** 为真实蓝本，手把手带你模拟**从空白文件夹出发**，如何用 **OpenSpec（规范驱动开发）** + **LLM-as-a-Judge（评测驱动开发）** 驾驭 Vibe Coding 工具，一步步完成**需求挖掘 → 架构拆解 → 分阶段实现 → 真值人工审核与评测 → 安全加固与开源上线**的全流程。

### 双轨学习方式（强烈推荐结合使用）
1. **跑通现成仓库（对照验证）**：先按第 0 章把本仓库跑起来，每学完一章直接运行对应 Stage 的独立 API 与评测脚本观察真实效果；
2. **从 0 到 1 亲手复刻（Vibe Coding 实战）**：新建一个空白目录，直接复制每章提供的 **Antigravity / Codex 实战 Prompt 模板**，完整体验 `Explore → Propose → Apply → Manual Review → Eval → Archive` 工程闭环。

```mermaid
flowchart LR
    C0["00 · 环境与离线沙盒\n10分钟跑通全栈"]
    C1["01 · OpenSpec 护栏\n告别抽卡式 Vibe Coding"]
    C2["02 · 需求挖掘与拆解\nStage 1 画像 + Stage 2 策略"]
    C3["03 · 外部对接与I/O解耦\nStage 3 URL + Stage 4 粗排"]
    C4["04 · 算术与推理解耦\nStage 5 零幻觉六维报告"]
    C5["05 · Eval 评测飞轮\nArgon 裁判 + #eval 看板"]
    C6["06 · 安全审计与上线\n历史脱敏 + CI 自动门禁"]

    C0 --> C1 --> C2 --> C3 --> C4 --> C5 --> C6
```

### 📑 中文分章导航

| 章节 | 标题 | 核心工程框架与心法 | 对应本仓库核心源码 |
| :---: | :--- | :--- | :--- |
| **00** | **[快速启动与免爬虫离线沙盒体验](./zh/00-quickstart-and-sandbox.md)** | 双通道凭证自适应、离线 REST 沙盒调试、5 阶段 `#eval` 看板导览 | `app.py`, `.env.example`, `start_chrome.sh` |
| **01** | **[用 OpenSpec 驯服 Vibe Coding 工具](./zh/01-openspec-foundation.md)** | `project.md` + `AGENTS.md` 契约、`Explore → Propose → Apply → Archive` 四步法、AST 语法树硬校验 | `openspec/project.md`, `openspec/AGENTS.md`, `openspec/specs/` |
| **02** | **[需求挖掘与双阶段解耦：从简历到求职策略](./zh/02-stage1-stage2-resume-to-queries.md)** | 单一巨型 Prompt 陷阱、温度分层（`0.1` 收敛 vs `0.4` 发散）、纯内存 PII 双端脱敏、平台规则前置（BOSS 48 城 1:1 映射） | `core/resume_parser.py`, `core/query_generator.py` |
| **03** | **[搜索召回工程与 I/O 解耦：意图 URL 与岗位粗排](./zh/03-stage3-stage4-intent-and-ranking.md)** | 硬筛选白名单 vs 软语义词扩展、将纯计算排序从浏览器反爬 I/O 剥离、非破坏性垫底降权、作息优先级防误判 | `core/intent_parser.py`, `core/boss_crawler.py` |
| **04** | **[确定性统计 + 受控推理：打造零幻觉六维分析](./zh/04-stage5-grounded-6d-analysis.md)** | “绝不让 LLM 做算术”、合规池统计隔离、清除 Prompt/Fallback 领域偏置污染、结构化 Schema 边界护栏 | `core/gemini_analyzer.py`, `static/app.js` |
| **05** | **[Eval-Driven 开发：Human-in-the-Loop 真值与评测大盘](./zh/05-eval-driven-flywheel-and-dashboard.md)** | 确定性门禁 + `NDCG@8` + `gemini-4-argon` 裁判、强模型生成真值草案 + 人工 Manual Review 卡点、`#eval` 看板构建 | `eval/eval_store.py`, `eval/stage1_eval/` ~ `eval/stage5_eval/` |
| **06** | **[从原型到开源/上线：安全审计、CI 门禁与发布清单](./zh/06-security-ci-and-production.md)** | Git 全历史密钥/PII 扫描、`127.0.0.1` 本地安全边界、免责声明与开源三件套、GitHub Actions 自动化守护 | `.github/workflows/ci.yml`, `SECURITY.md`, `LICENSE` |

---
---

<a id="english-tutorial-track"></a>

## 🌐 English Track: Building a Spec-Driven & Eval-Driven AI Agent from Scratch

### Why This Tutorial Series?
Developers new to **Vibe Coding tools** (Antigravity, Codex, Claude Code, Cursor) quickly hit a wall when moving past single-file demos: prompts bloat, regressions multiply, hallucinations creep in, and external I/O (like browser scraping) makes testing feel impossible.

Using this repository (**BOSS Zhipin Job Intelligence Agent**) as a live, runnable reference architecture, this 7-part hands-on guide walks you **from an empty folder to a production-grade 5-stage Agent system** using **OpenSpec (Spec-Driven Development)** and **LLM-as-a-Judge (Eval-Driven Development)**.

### 📑 English Chapter Index

| Chapter | Title | Core Mental Models & Frameworks | Key Repo Files |
| :---: | :--- | :--- | :--- |
| **00** | **[Quickstart & Browser-Free Offline Sandbox](./en/00-quickstart-and-sandbox.md)** | Dual-channel Gemini auth, testing Stage 1–5 REST APIs without Chrome, touring the `#eval` dashboard | `app.py`, `.env.example`, `start_chrome.sh` |
| **01** | **[Taming Vibe Coding Tools with OpenSpec](./en/01-openspec-foundation.md)** | `project.md` + `AGENTS.md` contracts, `Explore → Propose → Apply → Archive` loop, OpenSpec AST validation | `openspec/project.md`, `openspec/AGENTS.md`, `openspec/specs/` |
| **02** | **[Requirement Discovery & Stage Decoupling (Stages 1 & 2)](./en/02-stage1-stage2-resume-to-queries.md)** | Monolithic prompt anti-pattern, temperature stratification (`0.1` vs `0.4`), in-memory PII redaction, upfront domain constraints | `core/resume_parser.py`, `core/query_generator.py` |
| **03** | **[Search Recall & Decoupling Logic from I/O (Stages 3 & 4)](./en/03-stage3-stage4-intent-and-ranking.md)** | Hard URL whitelists vs soft semantic expansion, isolating `rank_and_filter_jobs` from Playwright CDP, non-destructive bottom demotion | `core/intent_parser.py`, `core/boss_crawler.py` |
| **04** | **[Deterministic Math + Grounded LLM Reasoning (Stage 5)](./en/04-stage5-grounded-6d-analysis.md)** | "Never let LLMs do arithmetic", compliant-pool isolation, purging domain-bias leakage, bounded Pydantic schemas | `core/gemini_analyzer.py`, `static/app.js` |
| **05** | **[Eval-Driven Flywheel: Human-in-the-Loop & `#eval` Dashboard](./en/05-eval-driven-flywheel-and-dashboard.md)** | Deterministic gates + `NDCG@8` + `gemini-4-argon` judge, Argon draft Ground Truth + Manual Review gate, 5-stage `#eval` UI | `eval/eval_store.py`, `eval/stage1_eval/` ~ `eval/stage5_eval/` |
| **06** | **[From Prototype to Public Release: Security Audit & CI Gates](./en/06-security-ci-and-production.md)** | Full git-history secret/PII audit, `127.0.0.1` security boundary, OSS legal/security docs, GitHub Actions CI guardrails | `.github/workflows/ci.yml`, `SECURITY.md`, `LICENSE` |
