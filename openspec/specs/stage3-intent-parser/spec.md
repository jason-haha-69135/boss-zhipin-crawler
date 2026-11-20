# Stage 3 Intent Parser Specification

## Purpose
Parse natural-language job search queries and Stage 2 three-element queries (`[行业]的[岗位]岗位，月薪至少[X.Xw]`) into BOSS直聘 official URL parameters and downstream soft semantic requirements using `gemini-3.8-flash` (with deterministic offline fallback), verified against a human-reviewed `gemini-4-argon` Ground Truth benchmark.

## Requirements

### Requirement: Stage 3 Intent Parsing with Gemini 3.8 Flash and Explicit City Priority
The `core/intent_parser.py` module SHALL parse natural-language job search queries into structured `ParsedSearchIntent` objects using `gemini-3.8-flash` (`DEFAULT_STAGE3_INTENT_MODEL`) at `temperature=0.1` (without `gemini-3.5-flash-lite`), and MUST resolve the target city according to deterministic priority rules mapped 1:1 to BOSS直聘 `CITY_CODE_MAP`.

#### Scenario: Resolve city from Stage 2 target_city when query text contains no city
- **WHEN** `parse_user_intent` receives a city-free Stage 2 `query_text` (such as `"互联网新媒体行业的新媒体运营专员岗位，月薪至少0.7w"`) alongside `target_city="武汉"`
- **THEN** the parser SHALL resolve `city_name="武汉"` and `city_code="101200100"` rather than defaulting to `"深圳"`
- **AND** `build_boss_url()` SHALL contain `city=101200100`

#### Scenario: Prioritize explicit city in user query over target_city and resume profile
- **WHEN** `user_query` explicitly mentions `"上海"` while `target_city="杭州"` or `resume_profile` has `target_city="深圳"`
- **THEN** the parser SHALL prioritize `"上海"` (`"101020100"`)

#### Scenario: Fallback to resume profile city when query and target_city are unspecified
- **WHEN** `user_query` contains no city name and `target_city` is omitted, while `resume_profile` specifies `target_city="成都"`
- **THEN** the parser SHALL resolve `city_name="成都"` and `city_code="101270100"`

### Requirement: Core Role Purification and Full BOSS直聘 Code Whitelist Validation
The `core/intent_parser.py` module SHALL strip industry modifiers, city prefixes, salary clauses, and `"岗位"`/`"职位"` suffixes from the URL `query` parameter while expanding `industry_keywords`, and MUST validate all hard filter codes (`city_code`, `salary_code`, `experience_code`, `degree_code`, `scale_code`, `stage_code`) against official whitelist dictionaries.

#### Scenario: Purify Stage 2 three-element query into clean BOSS search keyword and industry synonyms
- **WHEN** `parse_user_intent` processes `"企业级软件与信息技术服务行业的大客户销售经理岗位，月薪至少1.0w"`
- **THEN** `intent.query` SHALL be purified to a clean single role keyword (such as `"大客户销售经理"`) without `"行业"`, `"岗位"`, city names, or `/` slashes
- **AND** `intent.industry_keywords` SHALL contain relevant domain synonyms (such as `"软件"`, `"企业服务"`, `"IT"`, `"SaaS"`)
- **AND** `intent.min_salary_k` SHALL equal `10` and `intent.salary_code` SHALL equal `"405"`

#### Scenario: Reject and sanitize invalid LLM filter codes before building BOSS URL
- **WHEN** the LLM returns a `scale_code` not in `SCALE_CODE_LABELS` or a `stage_code` not in `STAGE_CODE_LABELS`
- **THEN** `parse_user_intent` SHALL sanitize the invalid code to `""` so `build_boss_url()` never emits invalid BOSS直聘 query parameters

#### Scenario: Offline deterministic fallback parses Stage 2 industry-role-salary structure
- **WHEN** the Gemini API is unavailable and `fallback_parse_intent` processes `"连锁餐饮与新茶饮行业的餐饮区域经理岗位，月薪至少1.5w"` with `target_city="广州"`
- **THEN** `fallback_parse_intent` SHALL cleanly separate `query="餐饮区域经理"`, `city_name="广州"`, `city_code="101280100"`, `min_salary_k=15`, `salary_code="405"`, and non-empty `industry_keywords`

### Requirement: Standalone Stage 3 Parse API and Analyze Handoff
The backend (`app.py`) SHALL expose a standalone `POST /api/intent/parse` endpoint for Stage 3 and MUST forward `target_city` and `resume_profile` into `parse_user_intent` during `POST /api/analyze`.

#### Scenario: Invoke standalone Stage 3 intent parse endpoint
- **WHEN** a client sends `POST /api/intent/parse` with `{"query": "互联网新媒体行业的新媒体运营岗位，月薪至少0.8w", "target_city": "杭州"}`
- **THEN** the endpoint SHALL return HTTP `200` with `model_used="gemini-3.8-flash"`, structured `intent`, and valid `boss_url` containing `city=101210100` and `salary=404`

### Requirement: Stage 3 Human-Reviewed Ground Truth Benchmark and Dashboard Visualization
The Stage 3 evaluation suite (`eval/stage3_eval/` and `eval/dataset/stage3/`) SHALL reuse the Stage 1 & Stage 2 qualified dataset (`QUAL-01` ~ `QUAL-09`), generate a draft Ground Truth using `gemini-4-argon` for manual review prior to benchmark execution, evaluate Stage 3 using `gemini-4-argon` as LLM-as-a-Judge, and render results in the `#eval` frontend dashboard.

#### Scenario: Generate Argon draft Ground Truth for manual review before running Stage 3 eval
- **WHEN** `eval/stage3_eval/generate_stage3_ground_truth.py` executes on Stage 2 outputs derived from `QUAL-01` through `QUAL-09`
- **THEN** it SHALL call `gemini-4-argon` (`temperature=0.0`) to produce `eval/dataset/stage3/stage3_intent_manifest.json` containing expected `query`, `city_name`, `city_code`, `salary_code`, `min_salary_k`, `industry_keywords`, and `boss_url`
- **AND** benchmark execution SHALL wait until the user completes manual review of the Ground Truth

#### Scenario: Evaluate Stage 3 against reviewed Ground Truth and display in frontend eval dashboard
- **WHEN** `eval/stage3_eval/evaluate_stage3_intent.py` runs after Ground Truth approval
- **THEN** it SHALL verify deterministic URL validity, city 1:1 accuracy, salary accuracy, and core query purity alongside `gemini-4-argon` semantic scoring
- **AND** it SHALL archive the report to `eval/runs/latest_stage3_eval_report.json` and render Stage 3 KPI cards, ECharts charts, and sample comparison tables under the `#eval` Stage 3 tab
