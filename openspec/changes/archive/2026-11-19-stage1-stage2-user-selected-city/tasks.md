# Implementation Tasks: User-Selected BOSS直聘 City (UI -> Stage 1 -> Stage 2)

## 1. Canonical BOSS直聘 City Map (`core/intent_parser.py` & `app.py`)
- [x] 1.1 Add `resolve_boss_city(city_name: str) -> Tuple[str, str]` helper in `core/intent_parser.py` validating 1:1 mapping against `CITY_CODE_MAP`, and expand `CITY_CODE_MAP` to cover major Chinese provincial capitals & popular cities.
- [x] 1.2 Expose `boss_cities` (`[{"name": ..., "code": ...}]`) in `GET /api/status` & `GET /api/cities` in `app.py` as the single source of truth for the frontend city selector.

## 2. Stage 1 Resume Parser & API (`core/resume_parser.py` & `app.py`)
- [x] 2.1 Update `extract_resume_profile_with_gemini` and `sanitize_and_normalize_profile` to accept optional `target_city: Optional[str] = None`, validate 1:1 against `CITY_CODE_MAP`, and attach `target_city`, `target_city_code`, and `target_cities` into the returned Stage 1 JSON (`profile` + top-level keys).
- [x] 2.2 Update `POST /api/resume/parse-profile` in `app.py` to accept `target_city` (both multipart form and JSON payload), validate it via `resolve_boss_city`, and return HTTP 400 if an invalid city is submitted.

## 3. Stage 2 Query Generator & API (`core/query_generator.py` & `app.py`)
- [x] 3.1 Add `target_city: str` and `target_city_code: str` fields to `RecommendedQueryItem` in `core/query_generator.py`.
- [x] 3.2 Update `_sanitize_queries_list`, `build_queries_from_profile_fallback`, and `generate_queries_from_profile_with_gemini` to read `target_city` / `target_city_code` from Stage 1 `profile` JSON (or explicit override), bind them deterministically to every item and top-level JSON, while keeping `query_text` 100% free of city names and welfare terms.

## 4. Frontend UI Pre-Upload Gate & Dynamic City Switching (`static/index.html`, `static/app.js`, `static/styles.css`)
- [x] 4.1 Add a BOSS直聘 1:1 city selector dropdown (`#resume-target-city-select`) in the resume upload card populated dynamically from `GET /api/status` (`boss_cities`).
- [x] 4.2 Enforce pre-upload city selection gate: block file picker/drag-and-drop upload and highlight the city selector with a clear hint if no city is selected yet.
- [x] 4.3 Pass the selected `target_city` to `POST /api/resume/parse-profile`, then pass the resulting Stage 1 JSON (with `target_city` & `target_city_code`) to `POST /api/resume/generate-queries`.
- [x] 4.4 Enable dynamic city switching after parsing: whenever the user changes the target city dropdown, immediately update `currentResumeProfile` JSON (`target_city`, `target_city_code`, `target_cities`) and automatically re-call `POST /api/resume/generate-queries` without re-uploading the resume, updating the rendered query cards with a `target_city` badge.

## 5. Stage 1 & Stage 2 Evaluation Alignment (`eval/stage1_eval/` & `eval/stage2_eval/`)
- [x] 5.1 Update `eval/stage2_eval/evaluate_stage2_queries.py` and `eval/stage2_eval/llm_judge_stage2.py` to verify `target_city` & `target_city_code` 1:1 BOSS直聘 mapping (`target_city_pass_rate == 100%`) while preserving `no_city_or_welfare_pass_rate == 100%` inside `query_text`.
- [x] 5.2 Re-run Stage 2 evaluation (`gemini-3.8-flash` + `gemini-4-argon`) and verify all gates pass (`run_stage2_queries_20261119_174942`: 9.46/10, 100% city 1:1 map); verify Stage 1 unit/validation tests with explicit `target_city` and invalid city rejection.

## 6. OpenSpec Archive (After User Approval)
- [x] 6.1 Merge delta specs into `openspec/specs/stage1-resume-parser/spec.md` and `openspec/specs/stage2-query-generator/spec.md`, archive the change to `openspec/changes/archive/2026-11-19-stage1-stage2-user-selected-city/`, and update `system_design.md`.
