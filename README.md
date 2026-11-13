<div align="center">

# BOSS Zhipin Job Intelligence Agent & Eval Suite
### BOSS直聘 智能求职分析 Agent 与全链路评测工作台

🌐 **[English](./README_EN.md)** &nbsp;|&nbsp; **[简体中文](./README_ZH.md)**
*(In-Page Jump / 页内快速定位: [English](#english) · [简体中文](#简体中文))*

</div>

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
├── core/
│   ├── gemini_client.py                 # Adaptive Gemini Interactions API client (Vertex AI & AI Studio)
│   ├── resume_parser.py                 # Stage 1 (Profile Extraction + PII Masking) & Stage 2 (Query Generation)
│   ├── intent_parser.py                 # Stage 3 Natural language job intent & filter parser
│   ├── boss_crawler.py                  # Stage 4 Two-stage Playwright CDP job crawler & Excel exporter
│   └── gemini_analyzer.py               # Stage 5 6-dimension statistics & Gemini deep JD matching
├── resume_eval_benchmark/
│   ├── schema_and_validator.py          # 9-field schema validator, file signature & PII redline guardrails
│   ├── llm_judge_evaluator.py           # LLM-as-a-Judge 9-field atomic classification scorer (0~10 scale)
│   ├── evaluate_parser.py               # CLI evaluation runner (supports --live-gemini & --llm-judge)
│   ├── eval_store.py                    # Unified 3-layer evaluation protocol adapter & run archive store
│   ├── dataset/                         # 25 multimodal qualified samples + 20 disqualified security samples
│   └── runs/                            # Archived evaluation run JSON reports for the web dashboard
├── static/
│   ├── index.html                       # Dual-workspace SPA (Job Search Analytics + Eval Dashboard)
│   ├── styles.css                       # Responsive UI & evaluation table styles
│   └── app.js                           # Frontend controller & ECharts rendering (XSS-safe DOM APIs)
├── design/                              # System architecture & BOSS Zhipin API reference docs
├── app.py                               # FastAPI server entry point (SSE streaming + REST + Eval APIs)
├── start_chrome.sh                      # Helper script to launch Chrome with remote debugging port 9222
└── requirements.txt                     # Python dependencies
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

#### 5. Run Stage 1 CLI Evaluation Benchmark
```bash
# Run live Gemini extraction + LLM-as-a-Judge 9-field atomic evaluation on selected samples
python resume_eval_benchmark/evaluate_parser.py \
  --live-gemini --llm-judge --sample-ids QUAL-001,QUAL-002
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
├── core/
│   ├── gemini_client.py                 # Gemini Interactions API 自适应双通道客户端 (Vertex AI & AI Studio)
│   ├── resume_parser.py                 # Stage 1 (简历画像提取 + PII脱敏) & Stage 2 (多策略 Query 生成)
│   ├── intent_parser.py                 # Stage 3 自然语言求职意图解析器
│   ├── boss_crawler.py                  # Stage 4 两阶段 BOSS直聘爬虫引擎与 Excel 导出
│   └── gemini_analyzer.py               # Stage 5 六维统计计算与 Gemini 人岗匹配深度分析
├── resume_eval_benchmark/
│   ├── schema_and_validator.py          # 9字段 Schema 校验器、文件签名检测与 PII 脱敏红线门禁
│   ├── llm_judge_evaluator.py           # LLM-as-a-Judge 9字段原子核对评分引擎 (0~10分制)
│   ├── evaluate_parser.py               # 命令行评测运行器 (支持 --live-gemini 与 --llm-judge)
│   ├── eval_store.py                    # 统一三层评测协议转换器与历史评测批次归档存储
│   ├── dataset/                         # 25份多格式正例简历样本 + 20份反例攻击/损坏安全测试样本
│   └── runs/                            # 自动归档的历史评测报告 JSON (供前端评测大盘读取与对比)
├── static/
│   ├── index.html                       # 双工作台单页应用 (求职六维分析工作台 + 全链路评测工作台)
│   ├── styles.css                       # 响应式样式表与评测矩阵样式
│   └── app.js                           # 前端交互与 ECharts 渲染逻辑 (全量采用安全 DOM API)
├── design/                              # 系统架构设计文档与 BOSS直聘 接口字典
├── app.py                               # FastAPI 后端服务主入口
├── start_chrome.sh                      # 启动带 9222 调试端口的独立 Chrome 脚本
└── requirements.txt                     # Python 依赖列表
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

#### 第五步：命令行运行 Stage 1 批量评测（自动同步至前端历史库）
```bash
# 对指定样本执行真实 Gemini 提取 + LLM-as-a-Judge 9字段原子核对
python resume_eval_benchmark/evaluate_parser.py \
  --live-gemini --llm-judge --sample-ids QUAL-001,QUAL-002
```
