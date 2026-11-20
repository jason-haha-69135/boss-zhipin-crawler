# Change: User-Selected BOSS直聘 Target City Across UI, Stage 1, and Stage 2

## Why
Previously, Stage 1 inferred `target_cities` purely from resume text or university location, while Stage 2 stripped city names from `query_text` without outputting a structured city field. In real BOSS直聘 usage, job seekers explicitly pick their target city (mapped 1:1 to BOSS直聘 `city_code`) before searching, and may dynamically switch cities after uploading their resume. Decoupling city selection to an explicit UI selector before Stage 1 upload—and carrying that exact BOSS直聘 city (`target_city` + `target_city_code`) through Stage 1 JSON into Stage 2 JSON—eliminates city guesswork, guarantees 1:1 BOSS直聘 city code fidelity, and allows instant Stage 2 regeneration whenever the user switches cities.

## What Changes
- **Single Source of Truth for BOSS直聘 Cities**:
  - Expose the canonical BOSS直聘 `CITY_CODE_MAP` (1:1 `city_name <-> city_code` mapping) from backend (`GET /api/config` / `core/intent_parser.py`) to the frontend UI so users only select valid BOSS直聘 cities.
- **Frontend UI Pre-Upload City Gate & Dynamic Switching (`static/index.html`, `static/app.js`)**:
  - Require the user to select a BOSS直聘 target city in the UI **before** uploading a resume file (block/prompt upload if unselected).
  - Allow the user to dynamically change the target city in the UI after Stage 1 parsing completes; changing the city immediately updates the in-memory Stage 1 profile JSON (`target_city`, `target_city_code`, `target_cities`) and automatically re-invokes Stage 2 (`POST /api/resume/generate-queries`) with the updated JSON without re-uploading the resume.
- **Stage 1 (`core/resume_parser.py`, `POST /api/resume/parse-profile`)**:
  - Accept user-selected `target_city` (validated 1:1 against BOSS直聘 `CITY_CODE_MAP`) as input alongside the uploaded resume.
  - After resume parsing completes, write the validated `target_city`, `target_city_code`, and `target_cities` into the Stage 1 output JSON passed downstream to Stage 2.
- **Stage 2 (`core/query_generator.py`, `POST /api/resume/generate-queries`)**:
  - Consume `target_city` and `target_city_code` from the Stage 1 JSON (or updated JSON when the user switches city dynamically).
  - Keep `query_text` 100% free of city names and welfare words (`"[目标行业/细分赛道]的[单一标准核心岗位名]岗位，月薪至少[X.Xw]"`).
  - Output explicit structured city fields (`target_city` and `target_city_code`) at both top-level Stage 2 JSON and on every `RecommendedQueryItem`.
- **Evaluation Alignment (`eval/stage1_eval/`, `eval/stage2_eval/`)**:
  - Validate 1:1 `CITY_CODE_MAP` mapping and city JSON propagation in Stage 1 and Stage 2 benchmarks.

## Impact
- **Affected specs**:
  - `openspec/specs/stage1-resume-parser/spec.md`
  - `openspec/specs/stage2-query-generator/spec.md`
- **Affected code**:
  - `core/intent_parser.py` (canonical `CITY_CODE_MAP` lookup helper)
  - `core/resume_parser.py` (`extract_resume_profile_with_gemini`, `sanitize_and_normalize_profile`)
  - `core/query_generator.py` (`RecommendedQueryItem`, `_sanitize_queries_list`, `build_queries_from_profile_fallback`, `generate_queries_from_profile_with_gemini`)
  - `app.py` (`GET /api/config`, `POST /api/resume/parse-profile`, `POST /api/resume/generate-queries`)
  - `static/index.html`, `static/app.js`, `static/styles.css`
  - `eval/stage1_eval/` & `eval/stage2_eval/`
