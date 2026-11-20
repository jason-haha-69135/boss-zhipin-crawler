# Change: Stage 3 Intent Parser Upgrades, Argon Ground Truth Pipeline, and Eval Dashboard

## Why
Stage 1 and Stage 2 now pass structured BOSS直聘 city fields (`target_city` and `target_city_code`) alongside clean city-free three-element `query_text`. However, Stage 3 (`core/intent_parser.py`) still hardcodes `gemini-3.5-flash-lite`, ignores explicit `target_city` / `resume_profile` inputs (silently defaulting to `"深圳"`), lacks whitelist validation for `scale_code` / `stage_code`, cannot cleanly split Stage 2's `"[行业]的[岗位]岗位"` syntax in offline fallback, has no standalone API endpoint, and lacks an independent evaluation suite and `#eval` visualization tab.

## What Changes
- **Five Core Upgrades to Stage 3 (`core/intent_parser.py` & `app.py`)**:
  1. **City Priority Resolution**: Extend `parse_user_intent` to accept `target_city` and `resume_profile`, resolving city via strict priority: `Explicit city in query > Explicit target_city > resume_profile.target_city / target_cities[0] > Default "深圳"`, mapped 1:1 via `CITY_CODE_MAP`.
  2. **Model Upgrade**: Switch Stage 3 default parsing model to `gemini-3.8-flash` (`DEFAULT_STAGE3_INTENT_MODEL`, `temperature=0.1`) and completely remove `gemini-3.5-flash-lite`.
  3. **Stage 2-Aware Fallback**: Upgrade `fallback_parse_intent` to cleanly split Stage 2's `(.+?(?:行业|领域|赛道|企业))的(.+?)(?:岗位|职位)?` syntax, expand `DOMAIN_SYNONYMS` across all benchmark domains, and accurately round decimal salary floors (e.g., `0.85w`).
  4. **Full Code Whitelist Validation**: Add `SCALE_CODE_LABELS` (`301`~`306`) and `STAGE_CODE_LABELS` (`801`~`808`) whitelist checks so no invalid codes can enter `build_boss_url()`.
  5. **Standalone API Endpoint**: Expose `POST /api/intent/parse` for independent Stage 3 invocation and debugging, and update `POST /api/analyze` + frontend `static/app.js` to forward `target_city`.
- **Stage 3 Evaluation Suite & Human-in-the-Loop Ground Truth (`eval/dataset/stage3/`, `eval/stage3_eval/`)**:
  - Reuse the Stage 1 & Stage 2 evaluation dataset (`QUAL-01` ~ `QUAL-09` profiles and their Stage 2 queries) to build `eval/dataset/stage3/stage3_intent_manifest.json`.
  - Generate an initial `ground_truth` draft using **`gemini-4-argon`** (`eval/stage3_eval/generate_stage3_ground_truth.py`) and present it for **Manual Review** before running the Stage 3 benchmark.
  - Build `eval/stage3_eval/evaluate_stage3_intent.py` and `eval/stage3_eval/llm_judge_stage3.py` (default judge model: **`gemini-4-argon`**) archiving results to `eval/runs/latest_stage3_eval_report.json`.
- **Frontend `#eval` Dashboard Stage 3 Visualization (`eval/eval_store.py`, `static/index.html`, `static/app.js`)**:
  - Add a dedicated **Stage 3 · 自然语言意图与 URL 映射评测** tab with KPI cards, ECharts visualizations, and sample-by-sample Ground Truth vs Parsed Output + `gemini-4-argon` judge review table.

## Impact
- **Affected specs**: Creates new living spec `openspec/specs/stage3-intent-parser/spec.md` upon archive.
- **Affected code**:
  - `core/intent_parser.py`
  - `app.py` (`POST /api/intent/parse`, `POST /api/analyze`, `/api/eval/*`)
  - `eval/eval_store.py`, `eval/dataset/stage3/`, `eval/stage3_eval/`
  - `static/index.html`, `static/app.js`
