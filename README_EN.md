<div align="center">

# BOSS Zhipin Job Intelligence Agent & Eval Suite
### BOSS直聘 智能求职分析 Agent 与全链路评测工作台

🌐 **Language / 语言切换**: **English** &nbsp;|&nbsp; **[简体中文](./README_ZH.md)** &nbsp;·&nbsp; *([Bilingual Single-Page](./README.md))*

</div>

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
