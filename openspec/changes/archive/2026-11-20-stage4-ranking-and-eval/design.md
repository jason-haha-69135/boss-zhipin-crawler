# Technical Design: Stage 4 Ranking, Filtering & Evaluation (`stage4-ranking-and-eval`)

## 1. Pure Offline Filtering & Ranking Engine (`core/boss_crawler.py`)

### 1.1 Fixed `detect_weekend_policy(text: str) -> str`
Evaluate negative and non-double-weekend patterns **strictly before** double-weekend patterns:
1. Negated / Single / Shift-rest patterns first:
   - `"非双休"`, `"不双休"`, `"不是双休"`, `"无双休"`, `"单休"`, `"做六休一"`, `"月休4天"`, `"月休6天"`, `"排班"`, `"轮休"`, `"调休"` -> `"排班轮休/单休"`
2. Alternating-weekend patterns second:
   - `"大小周"`, `"大小休"`, `"隔周双休"`, `"单双休"`, `"双单休"` -> `"大小周/单双休"`
3. True double-weekend patterns third:
   - `"周末双休"`, `"双休"`, `"做五休二"`, `"五天八小时"`, `"5天8小时"`, `"周六日休"` -> `"周末双休"`
4. Otherwise -> `"未明确注明"` (or `"未注明"` if empty).

### 1.2 Enhanced `parse_salary_bounds(salary_desc: str) -> Tuple[int, int, int]`
- Supports:
  - Standard K range: `12-18K·13薪` -> `(12, 18, 13)`
  - Single K: `15K` -> `(15, 15, 12)`
  - W / 万 range or single: `1.5-2.5W` / `1.2万` -> `(15, 25, 12)` / `(12, 12, 12)`
  - Daily wage: `200-300元/天` -> converted via `round(val * 21.75 / 1000)` -> `(4, 7, 12)`
  - Negotiable / empty (`面议`, `""`) -> `(0, 0, 12)`.

### 1.3 Keep-in-Full-Pool + Mandatory Bottom Demotion (`rank_and_filter_jobs`)
```python
def rank_and_filter_jobs(
    jobs: List[Dict[str, Any]],
    intent: ParsedSearchIntent,
    top_k: int = 8,
    resume_profile: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
```
- **Demotion Flags (Non-Destructive)**:
  - `is_city_mismatch`: `True` when `intent.city_name` is specified (and not `"全国"`), `job["工作地点"]` is non-empty, and `intent.city_name` does not appear in `job["工作地点"]`.
  - `is_below_salary_floor`: `True` when `intent.min_salary_k > 0`, `job["最高月薪K"] > 0`, and `job["最高月薪K"] < intent.min_salary_k`.
  - `is_demoted = is_city_mismatch or is_below_salary_floor`.
- **Scoring Breakdown (`score_breakdown`)**:
  - `base`: `50.0`
  - `title_score`: Exact substring match `+20.0`; otherwise tokenized overlap (Chinese bi-grams + ASCII tech tokens like `Java`/`UI`/`BD`/`IT`/`SaaS`) up to `+16.0`.
  - `industry_score`: `+12.0 + 4.0 * matched` (cap `+24.0`) or `-10.0` if industry keywords specified and none match.
  - `salary_score`: `min_k >= floor` `+12.0`; `max_k >= floor` `+5.0`; `max_k < floor` `-25.0`.
  - `weekend_score`: If `require_double_weekend`: `"周末双休"` `+15.0`, `"大小周/单双休"` `-6.0`, `"排班轮休/单休"` `-12.0`.
  - `skill_score`: Overlap between `resume_profile["core_skills"]` and job metadata (`岗位名称 + 技能标签 + 完整JD`), up to `+10.0`.
  - `company_bonus`: Scale + welfare completeness + `BOSS在线` (up to `+13.0`).
  - `demotion_penalty`: `-40.0` if `is_city_mismatch`, `-30.0` if `is_below_salary_floor`.
- **Two-Tier Deterministic Sorting**:
  - Sort full pool by `(0 if not is_demoted else 1, -score)` so **every compliant job strictly outranks every demoted job**, while demoted jobs remain preserved at the bottom of `ranked_jobs` (and exported Excel).
  - `top_candidates = ranked_jobs[:top_k]`.
- **Phase 2 Post-Enrichment Re-Sort**:
  - After fetching full JDs in `crawl_boss_two_stage`, recompute `score_candidate_for_detail` (with `resume_profile`) and re-sort `top_candidates` by `(0 if not is_demoted else 1, -score)`.

## 2. Standalone Ranking API (`app.py`)
- `POST /api/jobs/rank`:
  - Request: `{ "intent": dict, "jobs": List[dict], "top_k": int = 8, "resume_profile": Optional[dict] }`
  - Response: `{ "total_jobs": int, "demoted_count": int, "top_k": int, "top_candidates": List[dict], "ranked_jobs": List[dict] }`
- `POST /api/analyze`: forward `resume_profile=req.resume_profile` into `crawl_boss_two_stage`.

## 3. Stage 4 Offline Benchmark & Human-in-the-Loop Ground Truth (`eval/stage4_eval/`)
- **`eval/stage4_eval/generate_stage4_dataset.py`**:
  - Selects 6 diverse Stage 3 intents (spanning Internet/Tech, Retail/Ops, Sales/BD, Design, Education/Cross-border, Management across Beijing/Shanghai/Guangzhou/Wuhan).
  - Calls `gemini-4-argon` (`temperature=0.0`) to synthesize 16 realistic BOSS直聘 `joblist.json`-format candidates per scenario (96 total jobs), explicitly mixing:
    - Grade `3` (Highly Relevant: exact/close role + matching industry + meets salary + target city + double weekend if requested)
    - Grade `2` (Relevant: synonymous title or slightly broader industry, meets city & salary)
    - Grade `1` (Marginal: weak industry/role match, meets city & salary)
    - Grade `0` (Irrelevant / Traps: off-city injection, below-salary-floor trap, `"单双休"`/`"隔周双休"`/`"非双休"` text traps, unrelated domain noise)
  - Plus 12 deterministic unit-edge cases for `parse_salary_bounds` & `detect_weekend_policy`.
  - Saves draft to `eval/dataset/stage4/stage4_ranking_manifest.json` (`review_status: "PENDING_MANUAL_REVIEW"`) and **pauses for user Manual Review**.
- **`eval/stage4_eval/evaluate_stage4_ranking.py` & `llm_judge_stage4.py`**:
  - Deterministic metrics: `mean_ndcg_at_8`, `mean_recall_at_8`, `demotion_accuracy_rate` (off-city & low-salary demoted below all compliant jobs), `weekend_policy_accuracy`, `salary_parse_accuracy`.
  - `gemini-4-argon` (`temperature=0.0`) LLM-as-a-Judge scores each scenario's Top-8 ranking on 4 dimensions (`top_k_relevance_score`, `ranking_order_score`, `demotion_cleanliness_score`, `explainability_score`).
  - Archives to `eval/runs/latest_stage4_eval_report.json` and renders in `#eval` **STAGE 4** tab (5 KPI cards, 3 ECharts charts, scenario Top-K vs Ground Truth comparison table).
