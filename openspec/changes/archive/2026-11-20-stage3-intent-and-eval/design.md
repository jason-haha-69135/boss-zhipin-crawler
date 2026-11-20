# Technical Design: Stage 3 Intent Parser & Evaluation (`stage3-intent-and-eval`)

## 1. Stage 3 Core Architecture (`core/intent_parser.py`)

### 1.1 Function Signature & Defaults
```python
DEFAULT_STAGE3_INTENT_MODEL = os.environ.get("STAGE3_INTENT_MODEL", "gemini-3.8-flash")
DEFAULT_STAGE3_TEMPERATURE = float(os.environ.get("STAGE3_TEMPERATURE", "0.1"))

def parse_user_intent(
    user_query: str,
    target_city: Optional[str] = None,
    resume_profile: Optional[Dict[str, Any]] = None,
    model_name: str = DEFAULT_STAGE3_INTENT_MODEL,
    temperature: float = DEFAULT_STAGE3_TEMPERATURE,
    api_key: Optional[str] = None,
    proxy_url: Optional[str] = None,
) -> ParsedSearchIntent:
```
- Completely removes all references to `gemini-3.5-flash-lite`.

### 1.2 City Resolution Priority
1. Explicit city mentioned directly inside `user_query` (matched against `CITY_CODE_MAP` or extracted by LLM when actually present in `user_query`);
2. Explicit `target_city` parameter passed from Stage 2 JSON or UI selector (mapped 1:1 via `resolve_boss_city`);
3. `resume_profile["target_city"]` or `resume_profile["target_cities"][0]`;
4. Default fallback `"深圳"` (`"101280600"`).

### 1.3 Whitelist Code Dictionaries
- `CITY_CODE_MAP` (48 official BOSS直聘 cities)
- `SALARY_CODE_LABELS` (`""`, `"402"`~`"407"`)
- `EXPERIENCE_CODE_LABELS` (`""`, `"101"`~`"108"`)
- `DEGREE_CODE_LABELS` (`""`, `"202"`~`"209"`)
- `SCALE_CODE_LABELS` (`""`, `"301"`~`"306"`) — **NEW**
- `STAGE_CODE_LABELS` (`""`, `"801"`~`"808"`) — **NEW**

### 1.4 Stage 2-Aware Fallback (`fallback_parse_intent`)
- Regex split for Stage 2's three-element pattern: `^(.+?(?:行业|领域|赛道|企业))的(.+?)(?:岗位|职位)?$` extracts `raw_industry` and pure `core_query`.
- Decimal salary conversion: `min_salary_k = int(round(float(match_w.group(1)) * 10))`.
- Expanded `DOMAIN_SYNONYMS` covering 12+ industries (互联网/软件、人工智能/AI、服装零售、连锁餐饮、新媒体/传媒、外贸/跨境电商、大客户销售/SaaS、行政人事、医疗健康、金融、教育、美妆).

## 2. Standalone Endpoint (`app.py`)
- `POST /api/intent/parse`:
  - Request: `{ "query": str, "target_city": Optional[str], "resume_profile": Optional[dict], "model": str = "gemini-3.8-flash" }`
  - Response: `{ "model_used": str, "intent": ParsedSearchIntent, "boss_url": str }`
- `POST /api/analyze`:
  - Add `target_city: Optional[str] = None` to `AnalyzeRequest` and forward `target_city` + `resume_profile` into `parse_user_intent`.

## 3. Stage 3 Evaluation Dataset & Human-in-the-Loop Ground Truth (`eval/dataset/stage3/` & `eval/stage3_eval/`)

### 3.1 Reusing Stage 1 & Stage 2 Eval Dataset (`QUAL-01` ~ `QUAL-09`)
- Source samples directly from `eval/runs/latest_stage2_eval_report.json` (which itself is built on `QUAL-01` ~ `QUAL-09` from Stage 1):
  - Select representative Stage 2 queries per qualified resume (e.g., 2~3 distinct strategy queries per resume across all 9 resumes = 18~27 samples, each paired with the candidate's Stage 1 `target_city` / `target_city_code` and `profile`).
- `eval/stage3_eval/generate_stage3_ground_truth.py`:
  - Calls **`gemini-4-argon`** (`temperature=0.0`) with strict BOSS直聘 dictionary constraints to generate draft `ground_truth` (`expected_query`, `expected_city_name`, `expected_city_code`, `expected_salary_code`, `expected_min_salary_k`, `expected_industry_keywords`, `expected_boss_url`) into `eval/dataset/stage3/stage3_intent_manifest.json`.
  - Prints a clear review table for **user Manual Review** BEFORE running `evaluate_stage3_intent.py`.

### 3.2 Stage 3 Evaluation Gates (`evaluate_stage3_intent.py` & `llm_judge_stage3.py`)
- **Deterministic Gates (Target: 100%)**:
  - `url_valid_ok`: Valid `https://www.zhipin.com/web/geek/jobs?...` URL with all codes in official whitelists.
  - `city_match_ok`: Exact 1:1 match of `city_name` and `city_code` against Ground Truth.
  - `salary_match_ok`: Exact match of `min_salary_k` and `salary_code` against Ground Truth.
  - `query_pure_ok`: `query` contains no city name, no `"行业"` / `"岗位"` / `"月薪"` / `"双休"`, and no `/` slash.
- **LLM-as-a-Judge (`llm_judge_stage3.py`, Default: `gemini-4-argon`, `temperature=0.0`)**:
  - Scores 4 semantic dimensions (0~10): `role_purification_score` (recall vs precision balance), `industry_expansion_score` (`industry_keywords` relevance for Stage 4), `hard_filter_accuracy_score` (city/salary/exp/degree/scale/stage codes), and `soft_requirements_score`.

## 4. Frontend `#eval` Dashboard Stage 3 Visualization
- Add Stage 3 pill tab (`stage3_intent`) in `#eval-workspace-section` (`static/index.html`, `static/app.js`, `eval/eval_store.py`).
- Render:
  - 5 KPI cards (Mean Score `/10`, URL & Whitelist Rate, City 1:1 Accuracy, Salary Accuracy, Core Query Purity);
  - 3 ECharts charts (5-Dimension Capability Radar, Per-Resume Sample Score Bar, Salary/City Code Distribution);
  - Interactive detail table comparing Input (`query_text` + `target_city`), Ground Truth vs Parsed Output (`query`, `city_code`, `salary_code`, `industry_keywords`, clickable `boss_url`), and `gemini-4-argon` judge diagnosis.
