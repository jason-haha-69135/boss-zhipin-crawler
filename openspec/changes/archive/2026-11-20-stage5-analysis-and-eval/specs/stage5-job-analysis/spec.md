## ADDED Requirements

### Requirement: Domain-Agnostic 6-Dimension Statistics and Compliant-Pool Isolation
The `core/gemini_analyzer.py` module SHALL compute 6-dimension market statistics primarily on Stage 4 compliant jobs (`not is_demoted`) while exposing `compliant_jobs_count` and `demoted_jobs_count`, and MUST contain zero hardcoded apparel or store-supervisor domain copy in its schemas or fallback analysis.

#### Scenario: Exclude Stage 4 demoted jobs from market salary and industry statistics
- **WHEN** `compute_six_dimension_stats` receives a job list containing both compliant jobs and Stage 4 demoted (`is_demoted=True`) off-city or low-salary jobs
- **THEN** average salary, median salary, and industry distributions SHALL be computed exclusively from the compliant jobs
- **AND** the returned stats SHALL record `compliant_jobs_count` and `demoted_jobs_count` accurately

#### Scenario: Generate domain-agnostic fallback analysis for non-retail technical roles
- **WHEN** `build_fallback_analysis` runs for a `"Java开发工程师"` search in `"广州"`
- **THEN** the generated insights, risks, and advice SHALL reference `"Java开发工程师"` and `"广州"` without any legacy `"门店巡检"`, `"商品陈列"`, or `"连锁门店督导"` phrases

### Requirement: Grounded Gemini 3.8 Flash Analysis with Score Bounds and Standalone API
The `core/gemini_analyzer.py` module SHALL default to `gemini-3.8-flash` (`DEFAULT_STAGE5_ANALYSIS_MODEL`, `temperature=0.2`), enforce `0 <= score <= 100` bounds and full Top-K evaluation coverage, and `app.py` MUST expose a standalone `POST /api/analysis/evaluate` endpoint.

#### Scenario: Produce bounded, 1:1 Top-K job evaluations grounded in stats and resume profile
- **WHEN** `analyze_jobs_with_gemini` executes with `intent`, `jobs`, `top_candidates` (length `N`), and `resume_profile`
- **THEN** `overall_score` and every item's `match_score` SHALL satisfy `0 <= score <= 100`
- **AND** `recommended_jobs` SHALL contain all `N` candidates sorted descending by `match_score` with non-empty `match_reason`, `highlights`, and `risks`

#### Scenario: Invoke standalone Stage 5 analysis endpoint without browser crawling
- **WHEN** a client sends `POST /api/analysis/evaluate` with `intent`, `jobs`, `top_candidates`, and optional `resume_profile`
- **THEN** the endpoint SHALL return HTTP `200` with `model_used="gemini-3.8-flash"`, computed `stats`, and full 6-dimension `report`

### Requirement: Automated Stage 5 Benchmark and `#eval` STAGE 5 Dashboard
The Stage 5 evaluation suite (`eval/stage5_eval/` and `eval/dataset/stage5/`) SHALL reuse the 6 approved Stage 4 scenarios, generate Ground Truth anchors and judge `gemini-3.8-flash` reports using `gemini-4-argon` (`temperature=0.0`), archive results to `eval/runs/latest_stage5_eval_report.json`, and activate `stage5_analysis` in `#eval`.

#### Scenario: Execute end-to-end Stage 5 evaluation and render STAGE 5 dashboard
- **WHEN** `eval/stage5_eval/evaluate_stage5_analysis.py` executes on the 6 cross-industry scenarios
- **THEN** it SHALL verify deterministic schema completeness, Top-K coverage, score bounds, and zero domain-bias leakage alongside `gemini-4-argon` 4-dimension scores (`jd_groundedness_score`, `profile_alignment_score`, `risk_identification_score`, `advice_actionability_score`)
- **AND** it SHALL archive the report to `eval/runs/latest_stage5_eval_report.json` and activate the `stage5_analysis` tab in `#eval` with KPI cards, ECharts charts, and scenario evaluation details
