<div align="center">

# BOSS Zhipin Job Intelligence Agent & Eval Suite
### BOSS直聘 智能求职分析 Agent 与全链路评测工作台

🌐 **Language / 语言切换**: **English** &nbsp;|&nbsp; **[简体中文](./README_ZH.md)** &nbsp;·&nbsp; *([Bilingual Single-Page](./README.md))* &nbsp;|&nbsp; 📚 **[Step-by-Step Tutorial](./tutorials/README.md)**

</div>

---

> [!IMPORTANT]
> **⚠️ Disclaimer & Security Notice**
> - **Educational & Research Use Only**: This project is intended solely for personal learning, AI Agent architecture research, and LLM evaluation benchmarking. Please strictly comply with the target platform's Terms of Service, `robots.txt`, and applicable laws. Do **NOT** use this tool for commercial scraping, high-frequency harvesting, or unauthorized data redistribution.
> - **Localhost Only**: The FastAPI server binds to `127.0.0.1:8000` by default without authentication. **Never** expose it directly to `0.0.0.0` or the public internet without adding authentication, rate limiting, and CORS restrictions.

---

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
├── tutorials/                           # Step-by-step bilingual Spec-Driven Agent tutorials (zh/ & en/, 00~06)
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
