## MODIFIED Requirements

### Requirement: Decoupled Profile-to-Query Service Contract
The `core/query_generator.py` module SHALL operate as an independent Stage 2 service (`generate_queries_from_profile_with_gemini`) that accepts an in-memory Stage 1 `profile` JSON (carrying the user-selected BOSS直聘 `target_city` and `target_city_code`) without re-uploading or re-parsing the original resume file, and MUST include `target_city` and `target_city_code` in its JSON output.

#### Scenario: Generate 10 queries carrying BOSS直聘 target city from Stage 1 JSON
- **WHEN** `generate_queries_from_profile_with_gemini` receives a Stage 1 `profile` JSON with `target_city="武汉"` and `target_city_code="101200100"`
- **THEN** the module SHALL invoke `gemini-3.8-flash` (`DEFAULT_STAGE2_QUERY_MODEL`) at `temperature=0.4` (`DEFAULT_STAGE2_TEMPERATURE`) to return `query_count=10` (`DEFAULT_QUERY_COUNT`) `RecommendedQueryItem` objects
- **AND** the top-level JSON output SHALL include `"target_city": "武汉"`, `"target_city_code": "101200100"`, and `"target_cities": ["武汉"]`
- **AND** every item in `recommended_queries` SHALL include `"target_city": "武汉"` and `"target_city_code": "101200100"`

#### Scenario: Dynamically switch target city in UI and re-dispatch updated JSON to Stage 2
- **WHEN** a user dynamically changes the selected BOSS直聘 target city in the UI after Stage 1 parsing has already completed (for example switching from `"武汉"` to `"上海"`)
- **THEN** the UI SHALL update `currentResumeProfile` JSON with `"target_city": "上海"`, `"target_city_code": "101020100"`, and `"target_cities": ["上海"]`
- **AND** the UI SHALL automatically re-invoke `POST /api/resume/generate-queries` with the updated JSON without requiring the user to re-upload the resume
- **AND** Stage 2 SHALL return 10 newly generated queries whose JSON output reflects `"target_city": "上海"` and `"target_city_code": "101020100"`

### Requirement: Stage 2 Automated Benchmark and LLM-as-a-Judge Gate
The Stage 2 evaluation suite (`eval/stage2_eval/evaluate_stage2_queries.py` and `eval/stage2_eval/llm_judge_stage2.py`) SHALL evaluate all 90 generated queries (9 qualified profiles $\times$ 10 queries) from `eval/dataset/stage2/stage2_qualified_manifest.json` using deterministic three-element and BOSS直聘 city-mapping checks plus `gemini-4-argon` (`DEFAULT_STAGE2_JUDGE_MODEL`) at `temperature=0.0`.

#### Scenario: Verify 100 percent syntax purity BOSS city code mapping and gemini-4-argon quality score
- **WHEN** `evaluate_stage2_queries.py` runs across `QUAL-01` through `QUAL-09`
- **THEN** `decompose_query_three_elements` and `evaluate_single_query_item` SHALL verify `three_elements_pass_rate == 1.0`, `no_city_or_welfare_pass_rate == 1.0`, `single_role_pass_rate == 1.0`, `target_city_pass_rate == 1.0`, and `pii_safety_pass_rate == 1.0`
- **AND** `evaluate_queries_with_llm_judge` using `gemini-4-argon` SHALL score each query on strategy alignment and resume grounding, archiving the full report to `eval/runs/latest_stage2_eval_report.json` with a mean score $\ge 9.0 / 10.0$

## ADDED Requirements

### Requirement: Structured BOSS直聘 City Field Separation from Query Text
The `core/query_generator.py` module SHALL output `target_city` and `target_city_code` as independent structured JSON fields on each `RecommendedQueryItem` while keeping `query_text` completely free of city names and welfare terms.

#### Scenario: Keep query text free of city names while preserving structured city code
- **WHEN** Stage 2 generates queries for a candidate whose selected BOSS直聘 city is `"北京"` (`"101010100"`)
- **THEN** each `RecommendedQueryItem` SHALL contain `"target_city": "北京"` and `"target_city_code": "101010100"`
- **AND** `RecommendedQueryItem.query_text` SHALL NOT contain `"北京"` or any other city name
- **AND** if the LLM omits or hallucinates `target_city`, `_sanitize_queries_list` SHALL deterministically bind `target_city` and `target_city_code` to the validated BOSS直聘 city from `effective_profile`
