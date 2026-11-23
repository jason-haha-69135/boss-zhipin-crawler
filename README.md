<div align="center">

# BOSS Zhipin Job Intelligence Agent & Eval Suite
### BOSS直聘 智能求职分析 Agent 与全链路评测工作台

🌐 **[English](./README_EN.md)** &nbsp;|&nbsp; **[简体中文](./README_ZH.md)**
*(In-Page Jump / 页内快速定位: [English](#english) · [简体中文](#简体中文))*

</div>

---

> [!IMPORTANT]
> **⚠️ Disclaimer & Security Notice / 免责声明与安全提示**
> - **Educational & Research Use Only / 仅供学习与技术研究**：This project is intended solely for personal learning, AI Agent architecture research, and LLM evaluation benchmarking. Please strictly comply with the target platform's Terms of Service, `robots.txt`, and applicable laws. Do **NOT** use this tool for commercial scraping, high-frequency automated harvesting, or unauthorized data redistribution. Users assume full responsibility for their usage.
> - **本项目仅限个人学习、AI Agent 架构与评测体系研究使用**：请严格遵守目标平台服务条款、`robots.txt` 及相关法律法规，**严禁用于商业化高频抓取、批量数据倒卖或任何侵犯隐私的用途**，由此产生的一切风险与责任由使用者自行承担。
> - **Localhost Only / 严禁公网裸奔部署**：The FastAPI server binds to `127.0.0.1:8000` by default without authentication. **Never** expose it directly to `0.0.0.0` or the public internet without adding authentication, rate limiting, and CORS restrictions.

---

<a id="english"></a>

## 🌐 English Version

> **Language Switcher**: **[English](#english)** | **[简体中文 (Chinese)](#简体中文)**

An end-to-end **Conversational Job Intelligence Agent & 6-Dimension Visual Analytics Platform** built with **Playwright (CDP)**, **FastAPI (SSE Streaming)**, **Google Gemini Interactions API**, and **Apache ECharts**, paired with an in-house **LLM-as-a-Judge Multi-Stage Evaluation Suite & Interactive Dashboard**.

### ✨ Key Features

1. **Decoupled Dual-Stage Multimodal Resume Intelligence (`Stage 1` & `Stage 2`)**
   - **Stage 1 (`POST /api/resume/parse-profile`)**: Extracts a structured 9-field candidate profile (`CandidateProfileSchema`) from `.pdf`, `.docx`, `.png`, `.jpg`, `.jpeg`, `.webp`, `.txt`, and `.md` resumes (`<= 10MB`), enforcing strict file magic-byte validation, prompt-injection defense, and deterministic PII redaction (masking candidate names, phone numbers, emails, IDs, and detailed home/school street addresses).
   - **Stage 2 (`POST /api/resume/generate-queries`)**: Generates 5 differentiated natural-language job search queries across strategic angles (*Stretch / High-Salary*, *Core Match*, *Adjacent Exploration*, *Work-Life Balance*, *Steady Fallback*) with real-time user override controls (target city, salary floor, custom focus) without re-uploading the resume.
2. **Natural Language Intent Parsing & Two-Stage Live Job Collection (`Stage 3` & `Stage 4`)**
   - Translates conversational job requests into BOSS Zhipin (`zhipin.com`) city codes, salary brackets, and soft requirements.
   - **Stage 1 Crawl**: Collects batch job listings via Playwright CDP over a persistent logged-in Chrome session.
   - **Stage 2 Deep Crawl**: Ranks candidates and visits the top `N` (`3–20`) job detail pages to extract full job descriptions (`Post Description`) and HR activity metrics.
3. **6-Dimension Market Analytics & Deep Resume-to-JD Matching (`Stage 5`)**
   - Renders interactive **Apache ECharts** dashboards across 6 dimensions: *Industry Distribution*, *Salary & Bonus Structure*, *Top 15 Core Skills*, *Experience & Degree Thresholds*, *Company Scale & Brand Tier*, and *Weekend/Work-Life Schedule & Welfare*.
   - Produces an overall match gauge (`0–100`), executive summary, strengths/risks/actionable advice, and per-job deep match cards, plus one-click `.xlsx` export.
4. **Unified 3-Layer Evaluation Pipeline & Visual Dashboard (`Option A`)**
   - Built-in **LLM-as-a-Judge Atomic 9-Field Evaluator** (`0–10` scale per field) verifying semantic completeness, strict entity/number exact match (years, store counts, percentages, school names, revenue figures), zero-hallucination rate, and PII redline safety across 25 multimodal positive samples and 20 adversarial/corrupted negative samples.
   - Interactive frontend **Eval Dashboard (`/#eval`)** with **Aggregated View** (KPI cards, 9-field atomic score bar chart, file-format breakdown, cross-run trend comparison, and sample matrix) and **Single-Use View** (side-by-side 9-field Ground Truth vs. Extracted diff table and live single-sample sandbox runner).

---

### 📂 Project Structure

```text
boss-zhipin-crawler/
├── .github/workflows/ci.yml             # CI gate: Stage 3/4/5 unit tests, OpenSpec AST & secret hygiene
├── core/
│   ├── gemini_client.py                 # Adaptive Gemini Interactions API client (Vertex AI & AI Studio)
│   ├── resume_parser.py                 # Stage 1: Multimodal resume profile extraction + deterministic PII masking
│   ├── query_generator.py               # Stage 2: 10-strategy 3-element job query generator (with BOSS city 1:1)
│   ├── intent_parser.py                 # Stage 3: NL/Stage 2 intent parser, 48-city priority & official whitelists
│   ├── boss_crawler.py                  # Stage 4: Two-stage Playwright CDP crawler + offline rank_and_filter_jobs
│   └── gemini_analyzer.py               # Stage 5: Compliant-pool 6D statistics & grounded Gemini deep JD matching
├── eval/
│   ├── eval_store.py                    # Unified multi-stage eval store & protocol adapter (Stage 1 ~ Stage 5)
│   ├── stage1_eval/                     # Stage 1: 9-field atomic judge, schema validator & dataset generator
│   ├── stage2_eval/                     # Stage 2: 10-strategy query evaluator & Argon LLM-as-a-Judge
│   ├── stage3_eval/                     # Stage 3: Argon URL Ground Truth generator, evaluator & judge
│   ├── stage4_eval/                     # Stage 4: Offline candidate-pool generator, NDCG@8 evaluator & judge
│   ├── stage5_eval/                     # Stage 5: Automated Ground Truth anchors, 6D report evaluator & judge
│   ├── dataset/                         # Stage-isolated evaluation datasets & manifests (stage1/ ~ stage5/)
│   └── runs/                            # Archived evaluation run JSON reports & latest_stage1..5_eval_report.json
├── openspec/
│   ├── project.md                       # OpenSpec project conventions & architecture overview
│   ├── AGENTS.md                        # OpenSpec Explore -> Propose -> Apply -> Archive workflow rules
│   ├── specs/                           # Canonical AST-validated master specs (stage1 ~ stage5)
│   └── changes/archive/                 # Archived OpenSpec change proposals, designs & task logs
├── static/
│   ├── index.html                       # Dual-workspace SPA (Job Search Analytics + 5-Stage Eval Dashboard)
│   ├── styles.css                       # Responsive UI & evaluation dashboard styles
│   └── app.js                           # Frontend controller & Apache ECharts rendering (XSS-safe DOM APIs)
├── design/                              # Synced architecture design doc & BOSS Zhipin API reference
├── system_design.md                     # 6-page end-to-end system design & architecture documentation
├── app.py                               # FastAPI server entry point (SSE streaming, REST & Stage 1~5 APIs)
├── start_chrome.sh                      # Helper script to launch Chrome with remote debugging port 9222
├── .env.example                         # Environment variable template (gemini-3.8-flash / gemini-4-argon)
├── requirements.txt                     # Python dependencies
├── LICENSE                              # MIT License
└── SECURITY.md                          # Security policy & localhost-only deployment guidelines
```

---

### 🚀 Quick Start

#### 1. Install Dependencies
```bash
git clone git@github.com:jason-haha-69135/boss-zhipin-crawler.git
cd boss-zhipin-crawler
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

#### 2. Launch Debug Chrome & Log In to BOSS Zhipin (For Live Crawling)
```bash
./start_chrome.sh
```
> Log in to `zhipin.com` once in the opened Chrome window (session cookies persist locally in `chrome-profile/`).

#### 3. Configure Gemini Credentials & Start the Web Server
```bash
# Option A: Use Google AI Studio API Key
export GEMINI_API_KEY="YOUR_GEMINI_API_KEY"

# Option B: Or use GCP Vertex AI Application Default Credentials
# gcloud auth application-default login
# export GOOGLE_CLOUD_PROJECT="your-gcp-project-id"

python app.py
```

#### 4. Open in Browser
- **Job Search & 6D Analytics Workspace**: `http://127.0.0.1:8000/`
- **Multi-Stage Evaluation Dashboard**: `http://127.0.0.1:8000/#eval`

#### 5. Run Multi-Stage CLI Evaluation Benchmarks (`eval/`)
```bash
# Stage 1 ~ Stage 5 independent evaluation scripts (Analyzer: gemini-3.8-flash | Judge: gemini-4-argon)
python eval/stage1_eval/evaluate_stage1_parser.py --live-gemini --llm-judge
python eval/stage2_eval/evaluate_stage2_queries.py
python eval/stage3_eval/evaluate_stage3_intent.py
python eval/stage4_eval/evaluate_stage4_ranking.py
python eval/stage5_eval/evaluate_stage5_analysis.py
```

---
---

<a id="简体中文"></a>

## 🇨🇳 简体中文版

> **语言切换**: **[English](#english)** | **[简体中文](#简体中文)**

基于 **Playwright (CDP 协议接管本地 Chrome)** + **FastAPI (SSE 实时流式推送)** + **Google Gemini Interactions API** + **Apache ECharts** 构建的对话式求职采集、多模态简历解析与六维可视化分析系统，内置基于**统一三层评测协议 (Unified 3-Layer Protocol)** 的 **LLM-as-a-Judge 全链路评测工作台**。

### ✨ 核心功能亮点

1. **前后端解耦的两阶段多模态简历智能服务 (`Stage 1` & `Stage 2`)**
   - **Stage 1（`POST /api/resume/parse-profile` · 简历深度理解与画像提取）**：支持 `.pdf` / `.docx` / `.png` / `.jpg` / `.jpeg` / `.webp` / `.txt` / `.md` 八种格式（`<= 10MB`），内置 Magic Bytes 真实文件签名校验、Prompt 注入防御与确定性 PII 隐私二次脱敏（强制抹除姓名、手机号、邮箱、微信号、身份证号以及**家庭住址或学校详细门牌地址**），输出标准 9 字段结构化求职画像 (`CandidateProfileSchema`)。
   - **Stage 2（`POST /api/resume/generate-queries` · 多策略求职 Query 生成）**：基于结构化画像生成 5 条差异化自然语言求职 Query（冲刺高薪、精准对口、跨界探索、作息优先、稳健保底），支持在前端直接修改意向城市、月薪底线或附加方向并秒级重生成 Query（无需重复上传简历）。
2. **自然语言求职意图解析与两阶段爬虫采集 (`Stage 3` & `Stage 4`)**
   - 自动将自然语言诉求解析为 BOSS直聘 标准城市编码、薪资区间与软性福利要求。
   - **阶段一列表采集**：通过 CDP 协议复用本地已登录的 Chrome 会话批量采集岗位列表。
   - **阶段二详情深挖**：智能粗排筛选 Top `N`（支持 `3~20` 自定义）高潜岗位，自动进入详情页拉取完整职位描述（Post Description）与 HR 活跃度。
3. **六维市场全景可视化与人岗契合度深度诊断 (`Stage 5`)**
   - 基于 **Apache ECharts** 实时渲染六维图表：**所属行业分布**、**薪资水平与多薪占比**、**核心技能 Top 15**、**经验与学历门槛**、**公司规模与品牌知名度**、**双休/排班作息与高频福利**。
   - 结合候选人真实简历画像输出 `0~100` 综合匹配度仪表盘、优势/风险/沟通建议以及 Top 候选岗位逐一点评卡片，并支持一键导出 `.xlsx` 岗位明细表。
4. **内生全链路评测流水线与双视图可视化大盘 (`Option A`)**
   - **LLM-as-a-Judge 9 字段原子核对引擎**：针对 Stage 1 输出的 9 个字段逐一与 Ground Truth 进行 `0~10` 分原子核对（Atomic Classification），严苛核验关键数字与硬实体（年限、门店数、百分比、学校名、金额）是否完全一致，同步检测模型幻觉（Hallucination）与 PII 隐私泄露红线。
   - **前端双视图评测大盘 (`/#eval`)**：
     - **Aggregated View（全局聚合大盘）**：提供 5 大核心 KPI 卡片、9 字段原子均分横向柱状图、多模态文件格式得分对比图、跨批次历史趋势图、样本热力矩阵表及 20 个反例异常文件安全拦截明细。
     - **Single-Use View（单样本原子核对与实时评测沙盒）**：支持在浏览器中任选 `QUAL-001 ~ QUAL-025` 样本在线触发实时提取与 Judge 打分，并排对比 9 个字段的 `Ground Truth` vs `实际提取值`、实体核对状态、幻觉标记、得分进度条与扣分原因。

---

### 📂 目录结构

```text
boss-zhipin-crawler/
├── .github/workflows/ci.yml             # GitHub Actions CI 门禁（Stage 3/4/5 单测 + OpenSpec AST + 密钥扫描）
├── core/
│   ├── gemini_client.py                 # Gemini Interactions API 自适应双通道客户端 (Vertex AI & AI Studio)
│   ├── resume_parser.py                 # Stage 1：多模态简历画像提取 + 确定性 PII 脱敏
│   ├── query_generator.py               # Stage 2：10 策略三要素 Query 生成器（含 BOSS 城市 1:1 映射）
│   ├── intent_parser.py                 # Stage 3：自然语言/Stage 2 意图解析、48 城优先级与全量官方白名单
│   ├── boss_crawler.py                  # Stage 4：两阶段 Playwright CDP 爬虫 + 离线粗排降权引擎 (rank_and_filter_jobs)
│   └── gemini_analyzer.py               # Stage 5：合规池六维统计计算与 Gemini 人岗匹配深度分析
├── eval/
│   ├── eval_store.py                    # 全链路 5 阶段统一评测存储与协议适配器 (Stage 1 ~ Stage 5)
│   ├── stage1_eval/                     # Stage 1：9 字段原子裁判、Schema/文件签名校验与数据集生成器
│   ├── stage2_eval/                     # Stage 2：10 策略 Query 评测器与 Argon LLM-as-a-Judge
│   ├── stage3_eval/                     # Stage 3：Argon URL Ground Truth 生成器、评测器与裁判
│   ├── stage4_eval/                     # Stage 4：离线候选岗位池生成器、NDCG@8 评测器与裁判
│   ├── stage5_eval/                     # Stage 5：自动事实锚点生成、六维报告评测器与裁判
│   ├── dataset/                         # 分阶段隔离的评测数据集与基准清单 (stage1/ ~ stage5/)
│   └── runs/                            # 历史评测报告快照与最新汇总 (latest_stage1..5_eval_report.json)
├── openspec/
│   ├── project.md                       # OpenSpec 项目规范与架构约定
│   ├── AGENTS.md                        # OpenSpec Explore -> Propose -> Apply -> Archive 流程规则
│   ├── specs/                           # 5 份 100% 符合 OpenSpec AST 规范的主规范 (stage1 ~ stage5)
│   └── changes/archive/                 # 已归档的 OpenSpec 变更提案、设计文档与任务清单
├── static/
│   ├── index.html                       # 双工作台单页应用 (求职六维分析工作台 + 5 阶段全链路评测看板)
│   ├── styles.css                       # 响应式样式表与评测矩阵样式
│   └── app.js                           # 前端交互与 Apache ECharts 渲染逻辑 (全量采用安全 DOM API)
├── design/                              # 同步后的系统架构设计文档与 BOSS直聘接口字典
├── system_design.md                     # 6 页端到端系统设计与架构总览文档
├── app.py                               # FastAPI 后端服务主入口 (SSE 流式分析 + 独立 Stage 1~5 REST API)
├── start_chrome.sh                      # 启动带 9222 调试端口的独立 Chrome 脚本
├── .env.example                         # 环境变量配置模板 (gemini-3.8-flash / gemini-4-argon)
├── requirements.txt                     # Python 依赖列表
├── LICENSE                              # MIT 开源协议
└── SECURITY.md                          # 安全漏洞披露政策与本地安全部署边界说明
```

---

### 🚀 快速启动指南

#### 第一步：克隆仓库并安装依赖
```bash
git clone git@github.com:jason-haha-69135/boss-zhipin-crawler.git
cd boss-zhipin-crawler
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

#### 第二步：启动调试模式 Chrome 并登录 BOSS直聘（用于实时岗位采集）
```bash
./start_chrome.sh
```
> 在弹出的独立 Chrome 窗口中登录 BOSS直聘（登录态自动保存在本地 `chrome-profile/` 目录中，后续无需重复扫码）。

#### 第三步：配置 Gemini 凭证并启动 Web 服务
```bash
# 方式 A：使用 Google AI Studio API Key
export GEMINI_API_KEY="您的_GEMINI_API_KEY"

# 方式 B：或使用 GCP Vertex AI ADC 凭证
# gcloud auth application-default login
# export GOOGLE_CLOUD_PROJECT="您的_GCP_PROJECT_ID"

python app.py
```

#### 第四步：打开浏览器访问双工作台
- **智能求职采集与六维分析工作台**：`http://127.0.0.1:8000/`
- **全链路评测可视化工作台 (Eval Dashboard)**：`http://127.0.0.1:8000/#eval`（或点击页面顶部导航栏按钮一键切换）

#### 第五步：命令行运行 Stage 1 ~ Stage 5 分阶段评测（自动同步至前端 `#eval` 看板）
```bash
# 主链路默认 gemini-3.8-flash | LLM-as-a-Judge 默认 gemini-4-argon
python eval/stage1_eval/evaluate_stage1_parser.py --live-gemini --llm-judge
python eval/stage2_eval/evaluate_stage2_queries.py
python eval/stage3_eval/evaluate_stage3_intent.py
python eval/stage4_eval/evaluate_stage4_ranking.py
python eval/stage5_eval/evaluate_stage5_analysis.py
```
