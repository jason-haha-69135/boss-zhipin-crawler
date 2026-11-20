# Implementation Tasks: Stage 5 6-Dimension Analysis Upgrades, Eval & `#eval` Dashboard

## 1. Core Stage 5 Analyzer Upgrades (`core/gemini_analyzer.py` & `app.py`)
- [x] 1.1 Purge all hardcoded apparel/store-supervisor domain copy from `JobMatchEvaluationLLM`, `GeminiAnalysisLLMOutput`, and `build_fallback_analysis`, and enforce `ge=0, le=100` score bounds.
- [x] 1.2 Update `compute_six_dimension_stats` to isolate Stage 4 demoted jobs (`is_demoted=True`) from market distributions and expose `compliant_jobs_count` and `demoted_jobs_count`.
- [x] 1.3 Add `DEFAULT_STAGE5_ANALYSIS_MODEL = "gemini-3.8-flash"` & `DEFAULT_STAGE5_TEMPERATURE = 0.2`, strengthen anti-hallucination and resume-alignment prompt constraints, and expose standalone `POST /api/analysis/evaluate` in `app.py`.

## 2. Stage 5 Automated Eval Engine & Frontend `#eval` STAGE 5 Visualization
- [x] 2.1 Implement `eval/stage5_eval/llm_judge_stage5.py` (`gemini-4-argon`, `temperature=0.0`) and `eval/stage5_eval/evaluate_stage5_analysis.py` reusing the 6 Stage 4 scenarios, auto-generating Argon Ground Truth anchors (`eval/dataset/stage5/stage5_analysis_manifest.json`), evaluating `gemini-3.8-flash` reports, and archiving to `eval/runs/latest_stage5_eval_report.json`.
- [x] 2.2 Activate `stage5_analysis` in `eval/eval_store.py`, `app.py`, and `static/app.js` with Stage 5 KPI cards, 3 ECharts charts, and 6-scenario diagnosis table in `#eval`.
- [x] 2.3 Run `eval/stage5_eval/evaluate_stage5_analysis.py` live and verify all 5 stages (`STAGE 1` ~ `STAGE 5`) are active in `eval_store` and `#eval`.

## 3. OpenSpec Archive (After User Approval)
- [x] 3.1 Merge `specs/stage5-job-analysis/spec.md` into `openspec/specs/stage5-job-analysis/spec.md`, move this change to `openspec/changes/archive/`, and update `system_design.md` Page 6.
