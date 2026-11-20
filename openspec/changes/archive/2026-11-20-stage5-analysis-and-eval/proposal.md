# Change Proposal: Stage 5 6-Dimension Analysis Upgrades, Automated Eval & `#eval` STAGE 5 Dashboard (`stage5-analysis-and-eval`)

## Why
1. **Hardcoded Apparel/Retail Domain Bias**: `build_fallback_analysis`, `JobMatchEvaluationLLM`, and `GeminiAnalysisLLMOutput` in `core/gemini_analyzer.py` hardcode retail store-supervisor phrases (`"门店巡检"`, `"商品陈列"`, `"知名女装品牌"`, `"连锁门店督导"`), polluting non-retail analyses (Java, AI, Media, Overseas BD, R&D PM) during fallback or LLM generation.
2. **Demoted Jobs Pollute 6-Dimension Market Statistics**: `compute_six_dimension_stats` aggregates all raw jobs including Stage 4 demoted off-city and below-salary-floor jobs (`is_demoted=True`), distorting average/median salary and target-industry ratios.
3. **Missing Score Bounds, Anti-Hallucination Guardrails & Standalone Endpoint**: `match_score` and `overall_match_score` lack `0..100` bounds; prompts lack strict grounding constraints against fabricating numbers/companies outside `stats` and JD text; Stage 5 cannot be invoked independently without running Playwright CDP crawling (`POST /api/analyze`).
4. **Incomplete `#eval` Full-Pipeline Coverage**: `stage5_analysis` is the last remaining `planned` stage in `eval/eval_store.py` and `#eval`.

## What Changes
1. **Core Stage 5 Analyzer Upgrades (`core/gemini_analyzer.py` & `app.py`)**:
   - Purge all hardcoded apparel/store-supervisor copy from Schema field descriptions and `build_fallback_analysis` so insights dynamically adapt to any `intent.query` and industry.
   - Update `compute_six_dimension_stats` to compute 6-dimension stats on compliant jobs (`not is_demoted`) when available (falling back to full pool only if 0 compliant jobs exist) and expose `compliant_jobs_count` and `demoted_jobs_count`.
   - Add `DEFAULT_STAGE5_ANALYSIS_MODEL = "gemini-3.8-flash"` and `DEFAULT_STAGE5_TEMPERATURE = 0.2`, enforce Pydantic `ge=0, le=100` score bounds, and strengthen anti-hallucination & 1:1 `job_evaluations` coverage instructions.
   - Expose standalone `POST /api/analysis/evaluate` in `app.py`.
2. **Automated Stage 5 Benchmark (`eval/stage5_eval/` & `eval/dataset/stage5/`)**:
   - Reuse the 6 approved Stage 4 scenarios (`eval/dataset/stage4/stage4_ranking_manifest.json`) ranked by `rank_and_filter_jobs`.
   - Generate Stage 5 Ground Truth anchors using `gemini-4-argon` (`temperature=0.0`) into `eval/dataset/stage5/stage5_analysis_manifest.json` (auto-approved, no manual review pause requested).
   - Run `evaluate_stage5_analysis.py` with `gemini-3.8-flash` as analyzer and `gemini-4-argon` (`temperature=0.0`) as 4-dimension LLM-as-a-Judge (`jd_groundedness_score`, `profile_alignment_score`, `risk_identification_score`, `advice_actionability_score`) alongside deterministic hard gates (schema completeness, 100% Top-8 evaluation coverage, score range validity, zero domain-bias leakage).
3. **Frontend `#eval` STAGE 5 Dashboard (`eval/eval_store.py`, `app.py`, `static/app.js`)**:
   - Activate `stage5_analysis` (`status: "active"`) so all 5 pipeline stages (`STAGE 1` ~ `STAGE 5`) are live in `#eval`, with 5 KPI cards, 3 ECharts charts, and a 6-scenario analysis quality & Argon diagnosis table.

## Impact
- **Modified**: `core/gemini_analyzer.py`, `app.py`, `eval/eval_store.py`, `static/app.js`, `system_design.md`.
- **Added**: `eval/stage5_eval/llm_judge_stage5.py`, `eval/stage5_eval/evaluate_stage5_analysis.py`, `eval/dataset/stage5/stage5_analysis_manifest.json`.
- **Backward Compatibility**: `analyze_jobs_with_gemini` retains its existing return dictionary schema (`executive_summary`, `dimensions`, `match_evaluation`, `recommended_jobs`) for zero-breakage compatibility with the main dashboard UI.
