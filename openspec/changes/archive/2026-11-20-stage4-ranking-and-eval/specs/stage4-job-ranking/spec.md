## ADDED Requirements

### Requirement: Accurate Weekend Policy and Multi-Format Salary Parsing
The `core/boss_crawler.py` module SHALL accurately parse salary ranges (`K`, `W`/`万`, and daily wage `元/天`) via `parse_salary_bounds` and MUST evaluate negated and alternating-weekend phrases strictly before `"双休"` in `detect_weekend_policy`.

#### Scenario: Prevent false double-weekend classification on alternating or negated rest policies
- **WHEN** `detect_weekend_policy` receives text containing `"单双休"`, `"隔周双休"`, `"大小周"`, `"非双休"`, or `"不双休"`
- **THEN** it SHALL NOT classify the job as `"周末双休"`
- **AND** it SHALL return `"大小周/单双休"` for alternating-weekend text and `"排班轮休/单休"` for negated or single-rest text

#### Scenario: Parse W-unit and daily-wage salary strings into monthly K bounds
- **WHEN** `parse_salary_bounds` processes `"1.5-2.5W·14薪"` or `"200-300元/天"`
- **THEN** `"1.5-2.5W·14薪"` SHALL resolve to `(15, 25, 14)`
- **AND** `"200-300元/天"` SHALL resolve to positive monthly K bounds `(4, 7, 12)` instead of `(0, 0, 12)`

### Requirement: Non-Destructive Bottom Demotion and Tokenized Top-K Ranking
The `core/boss_crawler.py` module SHALL provide a pure offline `rank_and_filter_jobs` function that preserves off-city and below-salary-floor jobs in the full pool while mandatorily demoting them below all compliant jobs, using tokenized title matching, `resume_profile` skill signals, and explainable `score_breakdown`.

#### Scenario: Demote off-city and low-salary jobs to the bottom while keeping them in the full pool
- **WHEN** `rank_and_filter_jobs` ranks a candidate pool containing compliant target-city jobs alongside off-city jobs (city does not match `intent.city_name`) and low-salary jobs (`最高月薪K < intent.min_salary_k`)
- **THEN** every off-city or low-salary job SHALL be marked with `is_demoted=True` (`is_city_mismatch` / `is_below_salary_floor`)
- **AND** every compliant job SHALL rank strictly ahead of all demoted jobs in `ranked_jobs` and `top_candidates`
- **AND** all demoted jobs SHALL remain retained at the bottom of `ranked_jobs` for full Excel export

#### Scenario: Match synonymous job titles and resume skills with explainable breakdown
- **WHEN** `intent.query` is `"Java开发工程师"` and a candidate job is titled `"高级Java后端开发"` with matching `resume_profile["core_skills"]`
- **THEN** `score_candidate_for_detail` SHALL award positive tokenized title relevance and skill overlap points
- **AND** each ranked job SHALL include a `score_breakdown` dictionary detailing per-factor points

#### Scenario: Re-sort Top-K candidates after Phase 2 full JD enrichment
- **WHEN** Phase 2 detail enrichment in `crawl_boss_two_stage` updates `完整JD` and `作息制度` and recomputes `初筛得分`
- **THEN** `top_candidates` SHALL be re-sorted by `(is_demoted, -初筛得分)` before being returned to Stage 5

### Requirement: Standalone Stage 4 Ranking API and Profile Handoff
The backend (`app.py`) SHALL expose a standalone `POST /api/jobs/rank` endpoint for offline Stage 4 ranking and MUST forward `resume_profile` into `crawl_boss_two_stage` during `POST /api/analyze`.

#### Scenario: Invoke standalone Stage 4 ranking endpoint without browser CDP
- **WHEN** a client sends `POST /api/jobs/rank` with a serialized `intent`, a list of structured `jobs`, `top_k`, and optional `resume_profile`
- **THEN** the endpoint SHALL return HTTP `200` with `top_candidates`, `ranked_jobs`, `total_jobs`, and `demoted_count` without launching Playwright

### Requirement: Stage 4 Human-Reviewed Offline Benchmark and Dashboard Visualization
The Stage 4 evaluation suite (`eval/stage4_eval/` and `eval/dataset/stage4/`) SHALL generate an offline candidate-pool and relevance Ground Truth draft using `gemini-4-argon` for manual review prior to benchmark execution, evaluate Stage 4 with deterministic IR metrics (`NDCG@8`, demotion rate, edge-case accuracy) plus `gemini-4-argon` LLM-as-a-Judge, and render results in the `#eval` STAGE 4 dashboard.

#### Scenario: Generate Argon offline Stage 4 dataset and pause for manual review
- **WHEN** `eval/stage4_eval/generate_stage4_dataset.py` executes
- **THEN** it SHALL generate `eval/dataset/stage4/stage4_ranking_manifest.json` with `review_status="PENDING_MANUAL_REVIEW"` containing multi-scenario BOSS直聘 job pools, relevance grades (`0~3`), expected demotion flags, and salary/weekend edge cases
- **AND** Stage 4 evaluation SHALL wait until the user approves the Ground Truth

#### Scenario: Run Stage 4 evaluation and display in frontend eval dashboard
- **WHEN** `eval/stage4_eval/evaluate_stage4_ranking.py` executes on the approved manifest
- **THEN** it SHALL compute `NDCG@8`, `Recall@8`, demotion accuracy, weekend/salary edge-case accuracy, and `gemini-4-argon` 4-dimension scores
- **AND** it SHALL archive the report to `eval/runs/latest_stage4_eval_report.json` and activate the `stage4_ranking` tab in `#eval` with KPI cards, ECharts charts, and Top-K vs Ground Truth tables
