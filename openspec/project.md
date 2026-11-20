# Project Context

## Purpose
BOSS直聘智能求职分析 Agent 与六维可视化工作台 (`boss-zhipin-crawler`)。系统通过五阶段流水线（Stage 1 简历安全读取与多模态画像解析、Stage 2 基于画像的多策略求职 Query 生成、Stage 3 自然语言意图解析与 URL 映射、Stage 4 CDP 两阶段反爬采集与初筛打分、Stage 5 Python 六维统计与 Gemini 人岗双向评估），帮助求职者从个人简历出发，自动完成高质量求职搜索词定制、目标岗位采集与深度的市场及人岗匹配度诊断。

## Tech Stack
- **Language & Runtime**: Python 3.10+ (`.venv`)
- **Backend Framework**: FastAPI + Uvicorn (`app.py`)
- **LLM Integration**: Google GenAI SDK (`google-genai`) via unified Interactions API client (`core/gemini_client.py`) supporting Vertex AI Global Endpoint (`location="global"`) and AI Studio fallback
- **Default Models**:
  - Primary Generation / Extraction Model (`DEFAULT_INTERACTION_MODEL`): `gemini-3.8-flash` (Stage 1 `temperature=0.1`, Stage 2 `temperature=0.4`)
  - Evaluation Judge Model (`DEFAULT_LLM_JUDGE_MODEL`): `gemini-4-argon` (`temperature=0.0`)
- **Browser Automation**: Playwright Python (`connect_over_cdp` on `http://127.0.0.1:9222`)
- **Frontend**: Vanilla ES6 JavaScript (`static/app.js`), HTML5/CSS3 (`static/index.html`, `static/styles.css`), Apache ECharts 5
- **Evaluation Suite**: In-house multi-stage benchmark framework (`eval/`) with isolated datasets (`eval/dataset/stage1..stage5/`), stage-explicit scripts (`eval/stage1_eval..stage5_eval/`), and run archive (`eval/runs/`)

## Project Conventions

### Code Style & Architecture
- **Five-Stage Physical Decoupling**:
  - Stage 1: `core/resume_parser.py` (`extract_resume_profile_with_gemini`)
  - Stage 2: `core/query_generator.py` (`generate_queries_from_profile_with_gemini`)
  - Stage 3: `core/intent_parser.py` (`parse_user_intent`)
  - Stage 4: `core/boss_crawler.py` (`crawl_boss_two_stage`)
  - Stage 5: `core/gemini_analyzer.py` (`compute_six_dimension_stats`, `analyze_jobs_with_gemini`)
- **Unified LLM Client**: All Gemini calls MUST go through `create_interaction_with_fallback` in `core/gemini_client.py` with structured Pydantic `schema_cls`.
- **Evaluation Directory Naming**:
  - Datasets MUST reside under `eval/dataset/stage<N>/`.
  - Evaluation scripts MUST reside under `eval/stage<N>_eval/` and include `stage<N>` in their filenames (e.g., `evaluate_stage1_parser.py`, `llm_judge_stage1.py`, `evaluate_stage2_queries.py`, `llm_judge_stage2.py`).
  - Evaluation outputs MUST be written to `eval/runs/`.

### Testing & Evaluation Strategy
- Every stage MUST pass both **Deterministic Gate Checks** (schema completeness, format purity, zero PII leakage) and **LLM-as-a-Judge Evaluation** (`gemini-4-argon`) before a change is archived into `openspec/specs/`.

## Domain Context
- **BOSS直聘 (`zhipin.com`) Search Mechanics**:
  - Users select a target city (`city_code`) in the top bar before searching keywords; therefore, Stage 2 `query_text` MUST NOT include city names.
  - Job list cards do not expose full weekend/welfare policies; therefore, Stage 2 `query_text` MUST replace welfare requirements with explicit target industry prefixes (`[目标行业赛道]的[单一标准核心岗位名]岗位，月薪至少X.Xw`).
  - Searching compound titles with slashes (`/`) or overly narrow prefixes reduces recall on BOSS直聘; Stage 2 MUST output a single clean job role title, and Stage 3 MUST strip industry modifiers from the URL `query` parameter while expanding `industry_keywords` for Stage 4 scoring.

## Important Constraints
- **Zero Disk Persistence for Resumes**: Uploaded resume bytes MUST be validated and parsed purely in memory (`io.BytesIO`).
- **Dual-End PII Zero Leakage**: All candidate profiles and generated queries MUST strip names, 11-digit phone numbers, 18-digit ID numbers, email addresses, and street/building/dormitory addresses.
- **Path Traversal Prevention**: All file reads/writes in `eval/` and `output/` MUST validate paths via `resolve_safe_path()`.
- **Frontend XSS Prevention**: Frontend code MUST NOT use unescaped `innerHTML` when rendering LLM or crawler outputs.
- **Documentation Formatting**: Architecture and specification files (`system_design.md`, `openspec/`) MUST reference files using plain inline code spans (e.g., `` `core/resume_parser.py` ``) without local `file://` hyperlinks.
