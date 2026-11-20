# Implementation Tasks: Stage 3 Intent Parser, Argon Ground Truth & Eval Dashboard

## 1. Core Stage 3 Intent Parser Upgrades (`core/intent_parser.py` & `app.py`)
- [x] 1.1 Replace hardcoded `gemini-3.5-flash-lite` with `DEFAULT_STAGE3_INTENT_MODEL = "gemini-3.8-flash"` (`temperature=0.1`) and add `model_name`, `target_city`, and `resume_profile` parameters to `parse_user_intent`.
- [x] 1.2 Implement deterministic city priority resolution (`Query explicit city > target_city > resume_profile city > "深圳"`) mapped 1:1 via `CITY_CODE_MAP`.
- [x] 1.3 Add `SCALE_CODE_LABELS` (`301`~`306`) and `STAGE_CODE_LABELS` (`801`~`808`) whitelist validation in `parse_user_intent`.
- [x] 1.4 Upgrade `fallback_parse_intent` to cleanly split Stage 2's `"[行业]的[岗位]岗位，月薪至少[X.Xw]"` format, fix decimal salary rounding, and expand `DOMAIN_SYNONYMS` across all benchmark domains.
- [x] 1.5 Add standalone `POST /api/intent/parse` endpoint in `app.py`, update `AnalyzeRequest` & `POST /api/analyze` to forward `target_city` + `resume_profile`, and update `static/app.js` to send `target_city` in `/api/analyze`.

## 2. Stage 3 Eval Dataset & Argon Ground Truth Generation (Pre-Review Gate)
- [x] 2.1 Build `eval/stage3_eval/generate_stage3_ground_truth.py` reusing `QUAL-01` ~ `QUAL-09` profiles and Stage 2 outputs (`eval/runs/latest_stage2_eval_report.json`) and calling `gemini-4-argon` (`temperature=0.0`) to generate draft Ground Truth in `eval/dataset/stage3/stage3_intent_manifest.json`.
- [x] 2.2 Run `generate_stage3_ground_truth.py` and present the full Ground Truth table to the user for **Manual Review** (STOP before running Stage 3 Eval until user approves!).

## 3. Stage 3 Eval Engine & Frontend `#eval` Visualization (After Ground Truth Approval)
- [x] 3.1 Implement `eval/stage3_eval/llm_judge_stage3.py` (default judge: `gemini-4-argon`, `temperature=0.0`) and `eval/stage3_eval/evaluate_stage3_intent.py` archiving to `eval/runs/latest_stage3_eval_report.json`.
- [x] 3.2 Integrate Stage 3 into `eval/eval_store.py`, `app.py`, `static/index.html`, and `static/app.js` with Stage 3 KPI cards, ECharts charts, and Ground Truth vs Parsed Output detail table in `#eval`.
- [x] 3.3 Run `eval/stage3_eval/evaluate_stage3_intent.py` on the approved Ground Truth dataset and present Stage 3 evaluation results and dashboard visualization.

## 4. OpenSpec Archive (After User Approval)
- [x] 4.1 Merge `specs/stage3-intent-parser/spec.md` into `openspec/specs/stage3-intent-parser/spec.md`, move this change to `openspec/changes/archive/`, and update `system_design.md` Page 4.
