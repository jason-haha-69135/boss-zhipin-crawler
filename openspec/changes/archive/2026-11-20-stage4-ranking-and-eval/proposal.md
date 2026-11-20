# Change Proposal: Stage 4 Ranking & Filtering Upgrades, Offline Benchmark & `#eval` Dashboard (`stage4-ranking-and-eval`)

## Why
1. **Weekend Policy Misclassification Bug**: `detect_weekend_policy` in `core/boss_crawler.py` checks `"双休" in text` before checking `"单双休"`, `"隔周双休"`, or negated phrases (`"非双休"`, `"不双休"`), causing non-double-weekend jobs to be falsely classified as `"周末双休"` and awarded `+15` points.
2. **Missing City/Salary Demotion Enforcement**: `score_candidate_for_detail` neither validates `工作地点` against `intent.city_name` nor reliably demotes jobs whose `最高月薪K < intent.min_salary_k` to the bottom of the candidate pool, allowing off-city or under-budget jobs to consume scarce Phase 2 detail-fetch slots.
3. **Rigid Exact-Substring Title Matching & Missing Profile Signals**: Checking only `intent.query in job_name` assigns `0` title points to close variants (e.g., `"Java后端开发"` vs `"Java开发工程师"`), ignores `resume_profile["core_skills"]`, and omits explainable `score_breakdown` metadata.
4. **Incomplete Salary Parsing & Unsorted Phase 2 Results**: `parse_salary_bounds` fails on daily wages (`200-300元/天`) and `W`-unit ranges (`1.5-2.5W`), and Phase 2 does not re-sort `top_candidates` after updating scores with full JD text.
5. **Coupled Crawler I/O Prevents Reproducible Stage 4 Evaluation**: Ranking and filtering logic is embedded inside Playwright CDP crawling (`crawl_boss_two_stage`), blocking deterministic offline evaluation (`NDCG@K`, demotion accuracy, edge-case parsing) and `#eval` STAGE 4 visualization.

## What Changes
1. **Core Stage 4 Engine (`core/boss_crawler.py` & `app.py`)**:
   - Fix `detect_weekend_policy` precedence (negation & alternating-weekend patterns evaluated strictly before `"双休"`).
   - Expand `parse_salary_bounds` to support `K`, `W`/`万`, and daily wage (`元/天`, converted via 21.75 workdays/month) formats.
   - Decouple pure offline `rank_and_filter_jobs(jobs, intent, top_k=8, resume_profile=None)` with tokenized title matching, `resume_profile` skill overlap scoring, explainable `score_breakdown`, and **keep-in-full-pool + mandatory bottom demotion** for off-city and below-salary-floor jobs.
   - Re-sort `top_candidates` after Phase 2 JD enrichment and forward `resume_profile` from `POST /api/analyze`.
   - Expose standalone `POST /api/jobs/rank` endpoint in `app.py`.
2. **Human-in-the-Loop Offline Dataset & Ground Truth (`eval/stage4_eval/generate_stage4_dataset.py`)**:
   - Generate realistic BOSS直聘 `joblist.json`-format offline candidate pools and relevance Ground Truth (`0~3` grades + expected demotion flags) using `gemini-4-argon` (`temperature=0.0`) grounded on Stage 3 scenarios, pausing for **user Manual Review** before running Stage 4 Eval.
3. **Stage 4 Eval Engine & `#eval` STAGE 4 Dashboard (`eval/stage4_eval/`, `eval/eval_store.py`, `static/app.js`)**:
   - Compute deterministic IR & boundary metrics (`NDCG@8`, `Recall@8`, wrong-city & low-salary demotion rate, salary/weekend edge-case accuracy) alongside `gemini-4-argon` LLM-as-a-Judge scoring.
   - Activate `stage4_ranking` in `eval/eval_store.py`, `app.py`, and `#eval` with 5 KPI cards, 3 ECharts charts, and an interactive scenario Top-K vs Ground Truth table.

## Impact
- **Modified**: `core/boss_crawler.py`, `app.py`, `eval/eval_store.py`, `static/app.js`, `system_design.md`.
- **Added**: `eval/stage4_eval/generate_stage4_dataset.py`, `eval/stage4_eval/llm_judge_stage4.py`, `eval/stage4_eval/evaluate_stage4_ranking.py`, `eval/dataset/stage4/stage4_ranking_manifest.json`.
- **Backward Compatibility**: `crawl_boss_two_stage` keeps its existing return signature `(collected_jobs, top_candidates, excel_filename)` with optional `resume_profile=None`; off-city and low-salary jobs remain preserved in `collected_jobs` and the exported Excel file.
