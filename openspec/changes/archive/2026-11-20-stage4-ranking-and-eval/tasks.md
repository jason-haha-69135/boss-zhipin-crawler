# Implementation Tasks: Stage 4 Ranking & Filtering Upgrades, Offline Benchmark & Eval Dashboard

## 1. Core Stage 4 Ranking & Filtering Upgrades (`core/boss_crawler.py` & `app.py`)
- [x] 1.1 Fix `detect_weekend_policy` precedence (negated/single/alternating-weekend rules strictly before `"双休"`) and expand `parse_salary_bounds` to handle `W`/`万` ranges and daily wages (`元/天`).
- [x] 1.2 Upgrade `score_candidate_for_detail` with tokenized title relevance matching, `resume_profile["core_skills"]` overlap scoring, `is_city_mismatch` / `is_below_salary_floor` demotion flags, and explainable `score_breakdown`.
- [x] 1.3 Decouple pure offline `rank_and_filter_jobs(jobs, intent, top_k=8, resume_profile=None)` implementing keep-in-full-pool + mandatory bottom demotion sorting, and re-sort `top_candidates` after Phase 2 JD enrichment in `crawl_boss_two_stage`.
- [x] 1.4 Expose standalone `POST /api/jobs/rank` in `app.py` and forward `resume_profile` into `crawl_boss_two_stage` in `POST /api/analyze`.

## 2. Stage 4 Offline Dataset & Argon Ground Truth Generation (Pre-Review Gate)
- [x] 2.1 Build `eval/stage4_eval/generate_stage4_dataset.py` using `gemini-4-argon` (`temperature=0.0`) to synthesize 6 multi-industry BOSS直聘 candidate pools (16 jobs/scenario = 96 jobs with `0~3` relevance grades & demotion flags) plus 12 salary/weekend edge cases into `eval/dataset/stage4/stage4_ranking_manifest.json`.
- [x] 2.2 Run `generate_stage4_dataset.py` and present the scenario & Ground Truth summary to the user for **Manual Review** (STOP before running Stage 4 Eval until user approves!).

## 3. Stage 4 Eval Engine & Frontend `#eval` STAGE 4 Visualization (After Ground Truth Approval)
- [x] 3.1 Implement `eval/stage4_eval/llm_judge_stage4.py` (`gemini-4-argon`, `temperature=0.0`) and `eval/stage4_eval/evaluate_stage4_ranking.py` computing `NDCG@8`, `Recall@8`, demotion accuracy, edge-case accuracy, and Argon 4-dimension scores, archiving to `eval/runs/latest_stage4_eval_report.json`.
- [x] 3.2 Activate `stage4_ranking` in `eval/eval_store.py`, `app.py`, and `static/app.js` with Stage 4 KPI cards, 3 ECharts charts, and interactive scenario Top-K vs Ground Truth comparison table in `#eval`.
- [x] 3.3 Run `eval/stage4_eval/evaluate_stage4_ranking.py` on the approved Ground Truth dataset and present Stage 4 evaluation results and `#eval` dashboard visualization.

## 4. OpenSpec Archive (After User Approval)
- [x] 4.1 Merge `specs/stage4-job-ranking/spec.md` into `openspec/specs/stage4-job-ranking/spec.md`, move this change to `openspec/changes/archive/`, and update `system_design.md` Page 5.
