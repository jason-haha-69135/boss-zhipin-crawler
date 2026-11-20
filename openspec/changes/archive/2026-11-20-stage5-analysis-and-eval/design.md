# Technical Design: Stage 5 6-Dimension Analysis & Evaluation (`stage5-analysis-and-eval`)

## 1. Core Analyzer Upgrades (`core/gemini_analyzer.py`)

### 1.1 Defaults & Domain-Agnostic Schema
```python
DEFAULT_STAGE5_ANALYSIS_MODEL = os.environ.get("STAGE5_ANALYSIS_MODEL", "gemini-3.8-flash")
DEFAULT_STAGE5_TEMPERATURE = float(os.environ.get("STAGE5_TEMPERATURE", "0.2"))
```
- Enforce `ge=0, le=100` on `JobMatchEvaluationLLM.match_score` and `GeminiAnalysisLLMOutput.overall_match_score`.
- Replace all apparel/store-supervisor examples in `JobMatchEvaluationLLM`, `GeminiAnalysisLLMOutput`, and `build_fallback_analysis` with domain-agnostic phrasing dynamically grounded in `intent.query`, `intent.city_name`, `stats`, and `top_candidates`.

### 1.2 Compliant-Pool 6-Dimension Statistics (`compute_six_dimension_stats`)
- Partition `jobs` into `compliant_jobs = [j for j in jobs if not j.get("is_demoted", False)]` and `demoted_jobs = [j for j in jobs if j.get("is_demoted", False)]`.
- Use `stat_pool = compliant_jobs if compliant_jobs else jobs` for industry, salary, skills, experience/degree, brand, and welfare distributions so off-city/low-salary traps do not skew market statistics.
- Return `total_jobs` (full pool), `compliant_jobs_count`, `demoted_jobs_count`, and `stat_pool_size` inside `stats`.

### 1.3 Anti-Hallucination & Profile-Grounded Prompting
- Explicitly instruct `gemini-3.8-flash`:
  1. Every cited statistic, salary figure, company name, and weekend policy MUST come strictly from `stats` or `top_candidates` JD text — zero fabricated figures or companies;
  2. Never reference unrelated industries (e.g., store inspection / apparel) unless present in the data;
  3. Explicitly cite `resume_profile` highlights/skills when diagnosing candidate-job fit;
  4. Output exactly `len(top_candidates)` items in `job_evaluations` covering `job_index` `0..N-1`.

## 2. Standalone Stage 5 Endpoint (`app.py`)
- `POST /api/analysis/evaluate`:
  - Request: `{ "intent": dict, "jobs": List[dict], "top_candidates": List[dict], "resume_profile": Optional[dict], "model": str = "gemini-3.8-flash", "temperature": float = 0.2 }`
  - Response: `{ "model_used": str, "stats": dict, "report": dict }`

## 3. Automated Stage 5 Evaluation (`eval/stage5_eval/`)
- **Input Scenarios**: Directly reuse the 6 approved scenarios from `eval/dataset/stage4/stage4_ranking_manifest.json` (`S4-SCEN-01` ~ `S4-SCEN-06`), running `rank_and_filter_jobs` to produce clean `ranked_jobs` + `top_candidates` (Top-8).
- **Automated Ground Truth Anchor Generation** (`eval/dataset/stage5/stage5_analysis_manifest.json`):
  - Inside `evaluate_stage5_analysis.py` (or helper called automatically when manifest is missing), call `gemini-4-argon` (`temperature=0.0`) to extract concise Ground Truth fact anchors per scenario (required stat citations, key candidate strengths/gaps, must-flag weekend/risk traps, expected score band) and save with `review_status: "AUTO_APPROVED"`.
- **Deterministic Hard Gates (Target: 100%)**:
  - `schema_complete_ok`: All 6 dimensions + `executive_summary` + `match_evaluation` non-empty.
  - `top_k_coverage_ok`: `len(recommended_jobs) == len(top_candidates)` with every `match_score` in `[0, 100]`.
  - `zero_domain_bias_ok`: Zero leaked legacy retail/apparel strings (`"门店巡检"`, `"商品陈列"`, `"巡店出差"`, `"连锁门店督导"`, `"管辖门店数"`) in non-retail scenarios.
  - `stat_grounding_ok`: Output references real city/query and non-empty highlights/risks/advice.
- **LLM-as-a-Judge (`eval/stage5_eval/llm_judge_stage5.py`, Default: `gemini-4-argon`, `temperature=0.0`)**:
  - 4 dimensions (0~10):
    1. `jd_groundedness_score` (35%): Strict faithfulness to Python `stats` and Top-8 JD facts, zero hallucinated numbers/companies.
    2. `profile_alignment_score` (25%): Depth of candidate-job fit diagnosis against `resume_profile`.
    3. `risk_identification_score` (20%): Accurate flagging of real risks (e.g., `单双休`/`隔周双休`, salary gaps, skill gaps).
    4. `advice_actionability_score` (20%): Concrete, domain-specific interview/resume advice.
- **Archiving & `#eval` STAGE 5 Dashboard**:
  - Save to `eval/runs/<run_id>.json` and `eval/runs/latest_stage5_eval_report.json`.
  - Activate `stage5_analysis` in `eval/eval_store.py`, `app.py`, and `static/app.js` with 5 KPI cards, 3 ECharts charts, and a 6-scenario analysis & Argon diagnosis table.
