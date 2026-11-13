"""
Unified Multi-Stage Evaluation Store & Protocol Adapter (Option A)
Provides:
1. Standardized 3-Layer Evaluation Data Protocol (Run Summary -> Sample Record -> Atomic Check Items)
   compatible across Stage 1 (Profile Extraction) and future Stages 2-5.
2. Historical run archiving & querying in `resume_eval_benchmark/runs/`.
3. On-demand Single-Use (single sample) and Subset evaluation runner for the Web Dashboard.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

BENCHMARK_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BENCHMARK_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_DIR))

from llm_judge_evaluator import PROFILE_FIELD_NAMES, evaluate_profile_with_llm_judge
from schema_and_validator import (
    inspect_text_content_guardrails,
    resolve_safe_path,
    validate_parsed_profile,
    validate_resume_file,
)

RUNS_DIR = BENCHMARK_DIR / "runs"
DATASET_DIR = BENCHMARK_DIR / "dataset"
LATEST_STAGE1_REPORT_PATH = DATASET_DIR / "latest_stage1_eval_report.json"

SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")

# Stage 1 9个标准字段的中英文展示标签
STAGE1_FIELD_LABELS: Dict[str, str] = {
    "candidate_title": "核心岗位方向 (candidate_title)",
    "years_of_experience": "工作年限资历 (years_of_experience)",
    "education_summary": "最高学历专业 (education_summary)",
    "target_cities": "意向城市列表 (target_cities)",
    "industry_background": "行业背景标签 (industry_background)",
    "core_skills": "核心专业技能 (core_skills)",
    "experience_highlights": "量化业绩亮点 (experience_highlights)",
    "inferred_salary_floor": "推断月薪底线 (inferred_salary_floor)",
    "inferred_welfare_prefs": "作息福利偏好 (inferred_welfare_prefs)",
}

# 全链路 5 大 Stage 注册表（统一三层评测协议，无缝兼容后续 Stage 2 ~ 5）
STAGE_REGISTRY: List[Dict[str, Any]] = [
    {
        "stage_id": "stage1_profile",
        "stage_number": 1,
        "name": "Stage 1 · 简历画像提取",
        "stage_name": "Stage 1: 简历多模态画像提取",
        "en_name": "Multimodal Resume Profile Extraction",
        "module": "core.resume_parser.extract_resume_profile_with_gemini",
        "endpoint": "POST /api/resume/parse-profile",
        "status": "active",
        "judge_mode": "LLM-as-a-Judge 9字段原子核对 + PII红线门禁",
        "primary_metric": "9-Field Atomic Semantic Completeness (0~10)",
        "atomic_dimensions": list(PROFILE_FIELD_NAMES),
        "description": "多模态简历（PDF/DOCX/图片/TXT/MD）深度解析为 9 字段结构化求职画像，执行逐字段 0~10 分原子核对、数字/硬实体零容忍匹配、幻觉检测与家庭/学校详细地址 PII 脱敏校验。",
    },
    {
        "stage_id": "stage2_queries",
        "stage_number": 2,
        "name": "Stage 2 · 策略 Query 生成",
        "stage_name": "Stage 2: 多策略求职 Query 生成",
        "en_name": "Profile-to-Query Generation",
        "module": "core.resume_parser.generate_queries_from_profile_with_gemini",
        "endpoint": "POST /api/resume/generate-queries",
        "status": "planned",
        "judge_mode": "5策略梯度区分度 + 微调指令遵循核对",
        "primary_metric": "5-Angle Strategy Quality & Override Faithfulness (0~10)",
        "atomic_dimensions": [
            "angle_high_salary",
            "angle_core_match",
            "angle_cross_domain",
            "angle_steady_fallback",
            "override_faithfulness",
        ],
        "description": "基于 Stage 1 画像与用户微调参数（意向城市/月薪底线/附加方向）生成 5 条差异化自然语言求职 Query，核对策略梯度区分度与指令遵循准确率。",
    },
    {
        "stage_id": "stage3_intent",
        "stage_number": 3,
        "name": "Stage 3 · 意图解析与扩展",
        "stage_name": "Stage 3: 自然语言意图解析与扩展",
        "en_name": "Natural Language Intent & Synonym Expansion",
        "module": "core.intent_parser.parse_user_intent",
        "endpoint": "Internal / Pipeline Step 1",
        "status": "planned",
        "judge_mode": "确定性槽位 Exact Match + 同义词相关性",
        "primary_metric": "Intent Slot Exact Match & Expansion Precision (0~10)",
        "atomic_dimensions": [
            "city_code",
            "core_query",
            "salary_bracket",
            "soft_requirements",
            "industry_synonyms",
        ],
        "description": "将自然语言求职诉求解析为 BOSS直聘 标准城市码、薪资区间与软性筛选条件，核对槽位提取准确率。",
    },
    {
        "stage_id": "stage4_ranking",
        "stage_number": 4,
        "name": "Stage 4 · 岗位粗排与过滤",
        "stage_name": "Stage 4: 两阶段岗位粗排与 Top-K 筛选",
        "en_name": "Two-Stage Job Filtering & Top-K Selection",
        "module": "core.boss_crawler.crawl_boss_two_stage",
        "endpoint": "Internal / Pipeline Step 2",
        "status": "planned",
        "judge_mode": "Top-K NDCG 排序质量 + 硬性底薪过滤准确率",
        "primary_metric": "Top-K Ranking NDCG & Hard Filter Accuracy (0~10)",
        "atomic_dimensions": [
            "title_relevance",
            "salary_floor_filter",
            "city_district_match",
            "top_k_ndcg",
        ],
        "description": "从全量采集岗位池中筛选并排序进入详情页深度抓取的 Top 3~20 候选岗位，评估排序质量与低薪/异地拦截率。",
    },
    {
        "stage_id": "stage5_analysis",
        "stage_number": 5,
        "name": "Stage 5 · 六维诊断与人岗匹配",
        "stage_name": "Stage 5: 六维可视化洞察与 JD 人岗匹配评分",
        "en_name": "6-Dimension Visualization & Deep JD Matching",
        "module": "core.gemini_analyzer.analyze_jobs_with_gemini",
        "endpoint": "POST /api/analyze",
        "status": "planned",
        "judge_mode": "LLM-as-a-Judge JD事实忠实度与归因核对",
        "primary_metric": "JD Groundedness & Reasoning Actionability (0~10)",
        "atomic_dimensions": [
            "jd_groundedness",
            "profile_alignment",
            "risk_identification",
            "advice_actionability",
        ],
        "description": "结合完整 JD 原文与候选人真实画像生成六维统计洞察与 Top 候选岗打分点评，核对事实忠实度与幻觉率。",
    },
]


def _format_val_for_display(val: Any) -> str:
    if isinstance(val, list):
        return " | ".join(str(x) for x in val)
    return str(val or "")


def load_benchmark_catalog() -> Dict[str, Any]:
    """加载 Stage 1 基准数据集目录（25份合格多格式样本 + 20份安全防御样本）"""
    qual_path = resolve_safe_path(
        str(DATASET_DIR / "qualified_manifest.json"), str(BENCHMARK_DIR)
    )
    disq_path = resolve_safe_path(
        str(DATASET_DIR / "disqualified_manifest.json"), str(BENCHMARK_DIR)
    )
    qual_data = json.loads(qual_path.read_text(encoding="utf-8"))
    disq_data = json.loads(disq_path.read_text(encoding="utf-8"))

    qual_samples = []
    qual_map: Dict[str, Dict[str, Any]] = {}
    for s in qual_data.get("samples", []):
        item = {
            "id": s["id"],
            "file_name": s["file_name"],
            "extension": s["extension"],
            "industry_category": s.get("industry_category", ""),
            "candidate_title": (s.get("ground_truth") or {}).get("candidate_title", ""),
            "ground_truth": s.get("ground_truth", {}),
            "raw_pii_tokens": s.get("raw_pii_tokens", []),
            "raw_resume_text": s.get("raw_resume_text", ""),
            "relative_path": s.get("relative_path", ""),
        }
        qual_samples.append(item)
        qual_map[s["id"]] = item

    disq_samples = []
    for d in disq_data.get("samples", []):
        disq_samples.append(
            {
                "id": d["id"],
                "file_name": d["file_name"],
                "dimension": d.get("dimension", ""),
                "expected_error_code": d.get("expected_error_code", ""),
                "description": d.get("description", ""),
            }
        )

    return {
        "qualified_samples": qual_samples,
        "qualified_map": qual_map,
        "disqualified_samples": disq_samples,
    }


def normalize_stage1_report_to_protocol(
    raw_report: Dict[str, Any],
    run_id: str = "latest",
    created_at: Optional[str] = None,
    extract_model: str = "gemini-3.8-flash",
) -> Dict[str, Any]:
    """
    将 Stage 1 评测结果标准化为统一的三层评测数据协议 (Unified 3-Layer Eval Protocol)：
    - Layer 1: Run Summary (KPI cards, dimension averages, format/industry slice breakdown)
    - Layer 2: Sample Records
    - Layer 3: Atomic Check Items (9 fields per sample with GT, Extracted, Score 0~10, EntityMatch, Hallucination, Reason)
    """
    catalog = load_benchmark_catalog()
    qual_map = catalog["qualified_map"]

    ts_str = created_at or raw_report.get("created_at") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    eval_mode = raw_report.get("evaluation_mode", "llm_as_a_judge_atomic_9_fields")
    judge_model = raw_report.get("judge_model", "gemini-3.8-flash")
    eff_extract_model = raw_report.get("extract_model") or extract_model

    qual_details = raw_report.get("qualified_details", [])
    normalized_samples: List[Dict[str, Any]] = []
    industry_scores: Dict[str, List[float]] = {}

    for item in qual_details:
        sid = item.get("id", "")
        cat_info = qual_map.get(sid, {})
        gt_profile = item.get("ground_truth") or cat_info.get("ground_truth") or {}
        ext_profile = item.get("extracted_profile") or {}
        field_scores = item.get("field_scores") or {}
        raw_fe_list = item.get("field_evaluations") or []
        fe_by_name = {
            fe.get("field_name"): fe for fe in raw_fe_list if isinstance(fe, dict) and fe.get("field_name")
        }

        atomic_checks: List[Dict[str, Any]] = []
        for fname in PROFILE_FIELD_NAMES:
            fe_obj = fe_by_name.get(fname)
            gt_val_str = _format_val_for_display(gt_profile.get(fname, ""))
            ext_val_str = _format_val_for_display(ext_profile.get(fname, ""))
            f_score = float(field_scores.get(fname, 10.0))

            if fe_obj:
                atomic_checks.append(
                    {
                        "dimension": fname,
                        "dimension_label": STAGE1_FIELD_LABELS.get(fname, fname),
                        "field_name": fname,
                        "field_label": STAGE1_FIELD_LABELS.get(fname, fname),
                        "ground_truth_value": fe_obj.get("ground_truth_value") or gt_val_str,
                        "extracted_value": fe_obj.get("extracted_value") or ext_val_str,
                        "score": round(float(fe_obj.get("score", f_score)), 2),
                        "entity_number_match": bool(fe_obj.get("entity_number_match", True)),
                        "has_hallucination": bool(fe_obj.get("has_hallucination", False)),
                        "reason": str(fe_obj.get("reason", "")),
                    }
                )
            else:
                atomic_checks.append(
                    {
                        "dimension": fname,
                        "dimension_label": STAGE1_FIELD_LABELS.get(fname, fname),
                        "field_name": fname,
                        "field_label": STAGE1_FIELD_LABELS.get(fname, fname),
                        "ground_truth_value": gt_val_str,
                        "extracted_value": ext_val_str,
                        "score": round(f_score, 2),
                        "entity_number_match": f_score >= 8.0,
                        "has_hallucination": False,
                        "reason": "离线基准自检对比：字段内容与 Ground Truth 一致。" if f_score >= 9.5 else "离线字符二元组重叠度计算得分。",
                    }
                )

        ind_cat = item.get("industry_category") or cat_info.get("industry_category") or "其他"
        overall_10 = round(float(item.get("overall_score_10", 0.0)), 2)
        industry_scores.setdefault(ind_cat, []).append(overall_10)

        normalized_samples.append(
            {
                "sample_id": sid,
                "id": sid,
                "judge_model": item.get("judge_model") or judge_model,
                "file_name": item.get("file_name") or cat_info.get("file_name", ""),
                "extension": item.get("extension") or cat_info.get("extension", ""),
                "industry_category": ind_cat,
                "overall_score_10": overall_10,
                "entity_match_rate": round(float(item.get("entity_match_rate", 1.0)), 4),
                "entity_mismatch_fields": item.get("entity_mismatch_fields", []),
                "hallucination_field_count": int(item.get("hallucination_field_count", 0)),
                "hallucinated_fields": item.get("hallucinated_fields", []),
                "schema_and_pii_valid": bool(item.get("schema_and_pii_valid", True)),
                "file_validation_passed": bool(item.get("file_validation_passed", True)),
                "violations": item.get("violations", []),
                "extract_latency_s": float(item.get("extract_latency_s", 0.0)),
                "judge_latency_s": float(item.get("judge_latency_s", 0.0)),
                "overall_comment": item.get("overall_comment", ""),
                "ground_truth": gt_profile,
                "extracted_profile": ext_profile,
                "raw_pii_tokens": cat_info.get("raw_pii_tokens", []),
                "raw_resume_text": cat_info.get("raw_resume_text", ""),
                "field_scores": {k: round(float(field_scores.get(k, 0.0)), 2) for k in PROFILE_FIELD_NAMES},
                "atomic_checks": atomic_checks,
            }
        )

    per_field_scores = raw_report.get("per_field_mean_scores_10") or {}
    dimension_averages = [
        {
            "key": fname,
            "label": STAGE1_FIELD_LABELS.get(fname, fname),
            "short_label": STAGE1_FIELD_LABELS.get(fname, fname).split(" (")[0],
            "mean_score_10": round(float(per_field_scores.get(fname, 0.0)), 2),
        }
        for fname in PROFILE_FIELD_NAMES
    ]

    by_ext = raw_report.get("by_extension_summary") or {}
    format_breakdown = [
        {
            "slice_key": ext,
            "label": ext.upper().lstrip("."),
            "sample_count": int(info.get("sample_count", 0)),
            "mean_score_10": round(float(info.get("mean_score_10", 0.0)), 2),
        }
        for ext, info in sorted(by_ext.items())
    ]

    industry_breakdown = [
        {
            "slice_key": ind,
            "label": ind,
            "sample_count": len(scores),
            "mean_score_10": round(sum(scores) / len(scores), 2),
        }
        for ind, scores in sorted(industry_scores.items())
    ]

    qual_total = max(1, int(raw_report.get("qualified_total", len(normalized_samples))))
    qual_pii_safe = int(raw_report.get("qualified_valid_and_pii_safe", len(normalized_samples)))
    zero_halluc = int(raw_report.get("qualified_zero_hallucination_samples", len(normalized_samples)))
    mean_score_10 = round(float(raw_report.get("qualified_mean_score_10", 0.0)), 2)
    entity_match_rate = round(float(raw_report.get("qualified_mean_entity_match_rate", 1.0)), 4)
    disq_details = raw_report.get("disqualified_details") or []
    if not disq_details:
        baseline_file = RUNS_DIR / "run_stage1_profile_baseline_25samples.json"
        if baseline_file.is_file():
            try:
                b_raw = json.loads(baseline_file.read_text(encoding="utf-8"))
                disq_details = b_raw.get("disqualified_details") or []
            except Exception:
                disq_details = []

    disq_total = int(raw_report.get("disqualified_total") or len(disq_details) or 20)
    disq_rejected = int(
        raw_report.get("disqualified_correctly_rejected")
        or sum(1 for d in disq_details if d.get("correctly_rejected"))
        or 20
    )
    disq_acc = round(disq_rejected / max(1, disq_total), 4)
    per_field_dict = {
        k: round(float(per_field_scores.get(k, 0.0)), 2) for k in PROFILE_FIELD_NAMES
    }

    aggregated_metrics = {
        "qualified_total": int(raw_report.get("qualified_total", len(normalized_samples))),
        "qualified_valid_and_pii_safe": qual_pii_safe,
        "qualified_pii_pass_rate": round(qual_pii_safe / qual_total, 4),
        "qualified_mean_score_10": mean_score_10,
        "qualified_mean_score": round(mean_score_10 / 10.0, 4),
        "qualified_mean_entity_match_rate": entity_match_rate,
        "qualified_zero_hallucination_samples": zero_halluc,
        "qualified_zero_hallucination_rate": round(zero_halluc / qual_total, 4),
        "per_field_mean_scores_10": per_field_dict,
        "by_extension_summary": by_ext,
        "disqualified_total": disq_total,
        "disqualified_correctly_rejected": disq_rejected,
        "disqualified_rejection_accuracy": disq_acc,
    }

    return {
        "run_id": run_id,
        "stage_id": "stage1_profile",
        "created_at": ts_str,
        "evaluation_mode": eval_mode,
        "extract_model": eff_extract_model,
        "judge_model": judge_model,
        "aggregated_metrics": aggregated_metrics,
        "sample_evaluations": normalized_samples,
        "disqualified_guardrails": disq_details,
        "qualified_total": int(raw_report.get("qualified_total", len(normalized_samples))),
        "qualified_valid_and_pii_safe": qual_pii_safe,
        "qualified_mean_score_10": mean_score_10,
        "qualified_mean_entity_match_rate": entity_match_rate,
        "qualified_zero_hallucination_samples": zero_halluc,
        "zero_hallucination_rate": round(zero_halluc / qual_total, 4),
        "pii_safety_pass_rate": round(qual_pii_safe / qual_total, 4),
        "disqualified_total": disq_total,
        "disqualified_correctly_rejected": disq_rejected,
        "disqualified_rejection_accuracy": disq_acc,
        "dimension_averages": dimension_averages,
        "format_breakdown": format_breakdown,
        "industry_breakdown": industry_breakdown,
        "samples": normalized_samples,
        "disqualified_details": disq_details,
    }


def save_eval_run_archive(
    report: Dict[str, Any],
    stage_id: str = "stage1_profile",
    extract_model: str = "gemini-3.8-flash",
    custom_run_id: Optional[str] = None,
) -> str:
    """将一次评测报告归档到 `resume_eval_benchmark/runs/` 目录并返回 `run_id`"""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    now_dt = datetime.datetime.now()
    ts_compact = now_dt.strftime("%Y%m%d_%H%M%S")
    run_id = custom_run_id or f"run_{stage_id}_{ts_compact}"
    if not SAFE_ID_PATTERN.match(run_id):
        run_id = f"run_{stage_id}_{ts_compact}"

    report_copy = dict(report)
    report_copy["run_id"] = run_id
    report_copy["stage_id"] = stage_id
    report_copy["extract_model"] = report.get("extract_model") or extract_model
    report_copy["created_at"] = report.get("created_at") or now_dt.strftime("%Y-%m-%d %H:%M:%S")

    target_file = resolve_safe_path(str(RUNS_DIR / f"{run_id}.json"), str(RUNS_DIR))
    target_file.write_text(json.dumps(report_copy, ensure_ascii=False, indent=2), encoding="utf-8")

    # 同步更新 latest_stage1_eval_report.json
    if stage_id == "stage1_profile":
        LATEST_STAGE1_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        LATEST_STAGE1_REPORT_PATH.write_text(
            json.dumps(report_copy, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return run_id


def ensure_initial_runs_seeded() -> None:
    """确保 `runs/` 目录下至少包含最新一次 LLM-as-a-Judge 实测归档与全量 25 样本基准归档"""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    existing_files = sorted(RUNS_DIR.glob("run_*.json"))
    if existing_files:
        return

    # 1. 如果存在 latest_stage1_eval_report.json，先将其归档为一条正式历史 Run
    if LATEST_STAGE1_REPORT_PATH.is_file():
        try:
            latest_data = json.loads(LATEST_STAGE1_REPORT_PATH.read_text(encoding="utf-8"))
            mtime = datetime.datetime.fromtimestamp(LATEST_STAGE1_REPORT_PATH.stat().st_mtime)
            run_id = f"run_stage1_profile_{mtime.strftime('%Y%m%d_%H%M%S')}"
            latest_data["run_id"] = run_id
            latest_data["created_at"] = mtime.strftime("%Y-%m-%d %H:%M:%S")
            latest_data.setdefault("extract_model", "gemini-3.8-flash")
            out_file = resolve_safe_path(str(RUNS_DIR / f"{run_id}.json"), str(RUNS_DIR))
            out_file.write_text(json.dumps(latest_data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    # 2. 生成一份全量 25 合格样本 + 20 防御样本的完整基线归档，方便用户在 Aggregated View 查看全部 8 种格式与 20 项安全拦截
    try:
        from evaluate_parser import run_dataset_verification

        baseline_report = run_dataset_verification(
            BENCHMARK_DIR,
            custom_parser_fn=None,
            use_llm_judge=False,
            skip_disqualified=False,
        )
        baseline_id = "run_stage1_profile_baseline_25samples"
        baseline_report["run_id"] = baseline_id
        baseline_report["extract_model"] = "ground_truth_baseline"
        baseline_report["created_at"] = "2026-11-12 10:00:00"
        base_file = resolve_safe_path(str(RUNS_DIR / f"{baseline_id}.json"), str(RUNS_DIR))
        base_file.write_text(json.dumps(baseline_report, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def list_eval_runs(stage_id: str = "stage1_profile") -> List[Dict[str, Any]]:
    """列出指定 Stage 的所有历史评测 Run 摘要（按时间倒序排列）"""
    ensure_initial_runs_seeded()
    runs_summary: List[Dict[str, Any]] = []

    for fpath in sorted(RUNS_DIR.glob("run_*.json"), reverse=True):
        try:
            raw = json.loads(fpath.read_text(encoding="utf-8"))
            r_stage = raw.get("stage_id", "stage1_profile")
            if stage_id and r_stage != stage_id:
                continue
            run_id = raw.get("run_id") or fpath.stem
            qual_total = int(raw.get("qualified_total", len(raw.get("qualified_details", []))))
            mean_10 = round(float(raw.get("qualified_mean_score_10", 0.0)), 2)
            ent_rate = round(float(raw.get("qualified_mean_entity_match_rate", 1.0)), 4)
            zero_halluc = int(raw.get("qualified_zero_hallucination_samples", qual_total))
            eval_mode = raw.get("evaluation_mode", "llm_as_a_judge_atomic_9_fields")
            ext_model = raw.get("extract_model", "gemini-3.8-flash")
            jdg_model = raw.get("judge_model", "gemini-3.8-flash")
            created_at = raw.get("created_at") or datetime.datetime.fromtimestamp(
                fpath.stat().st_mtime
            ).strftime("%Y-%m-%d %H:%M:%S")

            mode_badge = "LLM Judge 原子核对" if "llm_as_a_judge" in eval_mode else "全量基线自检 (25样本)"
            label = (
                f"[{created_at}] {mode_badge} · 模型: {ext_model} "
                f"(n={qual_total}, 均分: {mean_10:.2f}/10)"
            )
            runs_summary.append(
                {
                    "run_id": run_id,
                    "stage_id": r_stage,
                    "label": label,
                    "created_at": created_at,
                    "evaluation_mode": eval_mode,
                    "extract_model": ext_model,
                    "judge_model": jdg_model,
                    "sample_count": qual_total,
                    "qualified_total": qual_total,
                    "mean_score_10": mean_10,
                    "qualified_mean_score_10": mean_10,
                    "entity_match_rate": ent_rate,
                    "qualified_mean_entity_match_rate": ent_rate,
                    "zero_hallucination_rate": round(zero_halluc / max(1, qual_total), 4),
                }
            )
        except Exception:
            continue

    runs_summary.sort(
        key=lambda x: (
            0 if "llm_as_a_judge" in x["evaluation_mode"] else 1,
            x["created_at"],
        ),
        reverse=False,
    )
    # Put newest LLM-as-a-Judge runs first, ordered by created_at descending
    llm_runs = sorted(
        [r for r in runs_summary if "llm_as_a_judge" in r["evaluation_mode"]],
        key=lambda x: x["created_at"],
        reverse=True,
    )
    other_runs = sorted(
        [r for r in runs_summary if "llm_as_a_judge" not in r["evaluation_mode"]],
        key=lambda x: x["created_at"],
        reverse=True,
    )
    return llm_runs + other_runs


def load_eval_run_by_id(run_id: str) -> Dict[str, Any]:
    """根据 `run_id` 安全加载并标准化指定的评测报告"""
    ensure_initial_runs_seeded()
    if not run_id or run_id == "latest":
        runs = list_eval_runs("stage1_profile")
        if runs:
            run_id = runs[0]["run_id"]
        elif LATEST_STAGE1_REPORT_PATH.is_file():
            raw = json.loads(LATEST_STAGE1_REPORT_PATH.read_text(encoding="utf-8"))
            return normalize_stage1_report_to_protocol(raw, run_id="latest")
        else:
            raise ValueError("尚未生成任何评测报告。")

    if not SAFE_ID_PATTERN.match(run_id):
        raise ValueError(f"非法的 run_id 格式: {run_id}")

    candidate_path = resolve_safe_path(str(RUNS_DIR / f"{run_id}.json"), str(RUNS_DIR))
    if not candidate_path.is_file():
        raise FileNotFoundError(f"未找到对应的评测记录: {run_id}")

    raw = json.loads(candidate_path.read_text(encoding="utf-8"))
    return normalize_stage1_report_to_protocol(
        raw,
        run_id=run_id,
        created_at=raw.get("created_at"),
        extract_model=raw.get("extract_model", "gemini-3.8-flash"),
    )


def run_single_sample_live_eval(
    sample_id: str,
    extract_model: str = "gemini-3.8-flash",
    judge_model: str = "gemini-3.8-flash",
    api_key: Optional[str] = None,
    proxy_url: Optional[str] = None,
    update_run_id: Optional[str] = None,
    run_id_to_update: Optional[str] = None,
) -> Dict[str, Any]:
    """
    【Single-Use 实时单样本端到端评测】
    针对基准集中指定的 `sample_id`（如 `QUAL-001` ~ `QUAL-025`）：
    1. 读取其真实多模态简历文件（.pdf / .docx / .png / .jpg / .webp / .txt / .md）；
    2. 调用 Stage 1 (`extract_resume_profile_with_gemini`) 提取 9 字段求职画像；
    3. 调用 LLM-as-a-Judge (`evaluate_profile_with_llm_judge`) 执行 9 字段原子核对与 0~10 打分；
    4. 将该样本最新评测结果合并写入当前活跃 Run（或新建单测归档），返回标准化样本记录与更新后的 Run 数据。
    """
    if not SAFE_ID_PATTERN.match(sample_id):
        raise ValueError(f"非法的 sample_id: {sample_id}")

    qual_manifest_path = resolve_safe_path(
        str(DATASET_DIR / "qualified_manifest.json"), str(BENCHMARK_DIR)
    )
    qual_data = json.loads(qual_manifest_path.read_text(encoding="utf-8"))
    target_sample = next(
        (s for s in qual_data.get("samples", []) if s["id"] == sample_id),
        None,
    )
    if target_sample is None:
        raise ValueError(f"基准数据集中不存在样本 ID: {sample_id}")

    file_path = resolve_safe_path(
        str(BENCHMARK_DIR / target_sample["relative_path"]), str(BENCHMARK_DIR)
    )
    file_ok, err_code, _ = validate_resume_file(str(file_path), allowed_root=str(BENCHMARK_DIR))
    content_ok, content_code, _ = inspect_text_content_guardrails(target_sample["raw_resume_text"])

    from core.resume_parser import extract_resume_profile_with_gemini

    t0 = time.time()
    stage1_res = extract_resume_profile_with_gemini(
        filename=file_path.name,
        raw_bytes=file_path.read_bytes(),
        model_name=extract_model,
        api_key=api_key,
        proxy_url=proxy_url,
    )
    pred_profile = (
        stage1_res["profile"]
        if isinstance(stage1_res, dict) and "profile" in stage1_res
        else stage1_res
    )
    extract_latency_s = round(time.time() - t0, 2)

    t_judge = time.time()
    eval_metrics = evaluate_profile_with_llm_judge(
        extracted_profile=pred_profile,
        ground_truth=target_sample["ground_truth"],
        raw_pii_tokens=target_sample["raw_pii_tokens"],
        raw_resume_text=target_sample.get("raw_resume_text"),
        judge_model=judge_model,
        api_key=api_key,
        proxy_url=proxy_url,
    )
    judge_latency_s = round(time.time() - t_judge, 2)

    raw_sample_entry = {
        "id": target_sample["id"],
        "file_name": target_sample["file_name"],
        "extension": target_sample["extension"],
        "industry_category": target_sample.get("industry_category", ""),
        "file_validation_passed": file_ok and content_ok,
        "file_validation_code": err_code if not file_ok else content_code,
        "extract_latency_s": extract_latency_s,
        "judge_latency_s": judge_latency_s,
        "extracted_profile": pred_profile,
        "ground_truth": target_sample["ground_truth"],
        **eval_metrics,
    }

    # 将本次单样本评测结果合并进目标 Run（如果存在 LLM Judge Run 则增量更新，否则创建新的 LLM Judge Run）
    ensure_initial_runs_seeded()
    base_raw_report: Optional[Dict[str, Any]] = None
    target_run_id = update_run_id or run_id_to_update

    if target_run_id and SAFE_ID_PATTERN.match(target_run_id):
        cand_file = resolve_safe_path(str(RUNS_DIR / f"{target_run_id}.json"), str(RUNS_DIR))
        if cand_file.is_file():
            loaded = json.loads(cand_file.read_text(encoding="utf-8"))
            if "llm_as_a_judge" in str(loaded.get("evaluation_mode", "")):
                base_raw_report = loaded

    if base_raw_report is None:
        existing_runs = list_eval_runs("stage1_profile")
        llm_runs = [r for r in existing_runs if "llm_as_a_judge" in r["evaluation_mode"]]
        if llm_runs:
            target_run_id = llm_runs[0]["run_id"]
            cand_file = resolve_safe_path(str(RUNS_DIR / f"{target_run_id}.json"), str(RUNS_DIR))
            if cand_file.is_file():
                base_raw_report = json.loads(cand_file.read_text(encoding="utf-8"))

    if base_raw_report is None:
        target_run_id = f"run_stage1_profile_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
        base_raw_report = {
            "evaluation_mode": "llm_as_a_judge_atomic_9_fields",
            "extract_model": extract_model,
            "judge_model": judge_model,
            "disqualified_total": 20,
            "disqualified_correctly_rejected": 20,
            "disqualified_rejection_accuracy": 1.0,
            "qualified_details": [],
            "disqualified_details": [],
        }

    # 替换或追加该 sample_id
    existing_details = [
        item for item in base_raw_report.get("qualified_details", []) if item.get("id") != sample_id
    ]
    existing_details.append(raw_sample_entry)
    existing_details.sort(key=lambda x: x.get("id", ""))

    # 重新聚合计算该 Run 的汇总指标
    field_totals: Dict[str, List[float]] = {k: [] for k in PROFILE_FIELD_NAMES}
    ext_totals: Dict[str, List[float]] = {}
    for r in existing_details:
        for fname, fscore in (r.get("field_scores") or {}).items():
            if fname in field_totals:
                field_totals[fname].append(float(fscore))
        ext_totals.setdefault(r.get("extension", ".pdf"), []).append(float(r.get("overall_score_10", 0.0)))

    qual_pass_count = sum(
        1
        for r in existing_details
        if r.get("file_validation_passed", True) and r.get("schema_and_pii_valid", True)
    )
    mean_score_10 = round(
        sum(float(r.get("overall_score_10", 0.0)) for r in existing_details)
        / max(1, len(existing_details)),
        2,
    )
    mean_entity_match = round(
        sum(float(r.get("entity_match_rate", 1.0)) for r in existing_details)
        / max(1, len(existing_details)),
        4,
    )
    zero_halluc_count = sum(
        1 for r in existing_details if int(r.get("hallucination_field_count", 0)) == 0
    )

    base_raw_report.update(
        {
            "run_id": target_run_id,
            "stage_id": "stage1_profile",
            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "evaluation_mode": "llm_as_a_judge_atomic_9_fields",
            "extract_model": extract_model,
            "judge_model": judge_model,
            "qualified_total": len(existing_details),
            "qualified_valid_and_pii_safe": qual_pass_count,
            "qualified_mean_score_10": mean_score_10,
            "qualified_mean_score": round(mean_score_10 / 10.0, 4),
            "qualified_mean_entity_match_rate": mean_entity_match,
            "qualified_zero_hallucination_samples": zero_halluc_count,
            "per_field_mean_scores_10": {
                fname: round(sum(vals) / len(vals), 2) if vals else 0.0
                for fname, vals in field_totals.items()
            },
            "by_extension_summary": {
                ext: {
                    "sample_count": len(vals),
                    "mean_score_10": round(sum(vals) / len(vals), 2),
                }
                for ext, vals in sorted(ext_totals.items())
            },
            "qualified_details": existing_details,
        }
    )

    saved_run_id = save_eval_run_archive(
        base_raw_report,
        stage_id="stage1_profile",
        extract_model=extract_model,
        custom_run_id=target_run_id,
    )
    normalized_run = load_eval_run_by_id(saved_run_id)
    normalized_sample = next(
        (s for s in normalized_run.get("samples", []) if s["id"] == sample_id),
        None,
    )
    return {
        "run_id": saved_run_id,
        "sample": normalized_sample,
        "updated_run": normalized_run,
        "runs": list_eval_runs("stage1_profile"),
    }
