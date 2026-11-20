#!/usr/bin/env python3
"""
Stage 5 六维分析与人岗匹配评估 — 自动化独立评测脚本
- 待测分析模型: gemini-3.8-flash (temperature=0.2)
- 基准锚点与裁判模型 (LLM-as-a-Judge): gemini-4-argon (temperature=0.0)
- 复用数据: Stage 4 已批准的 6 组跨行业场景 (eval/dataset/stage4/stage4_ranking_manifest.json)
- 输出归档:
  - eval/dataset/stage5/stage5_analysis_manifest.json (Argon 自动生成事实锚点)
  - eval/runs/<run_id>.json & eval/runs/latest_stage5_eval_report.json
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.boss_crawler import rank_and_filter_jobs
from core.gemini_analyzer import (
    DEFAULT_STAGE5_ANALYSIS_MODEL,
    DEFAULT_STAGE5_TEMPERATURE,
    analyze_jobs_with_gemini,
    compute_six_dimension_stats,
)
from core.gemini_client import load_backend_api_key
from core.intent_parser import ParsedSearchIntent
from eval.stage5_eval.llm_judge_stage5 import (
    DEFAULT_STAGE5_JUDGE_MODEL,
    STAGE5_DIMENSION_KEYS,
    STAGE5_DIMENSION_LABELS,
    evaluate_stage5_analysis_with_llm_judge,
    generate_stage5_ground_truth_anchor,
)

DEFAULT_STAGE4_MANIFEST = BASE_DIR / "eval" / "dataset" / "stage4" / "stage4_ranking_manifest.json"
DEFAULT_STAGE5_MANIFEST = BASE_DIR / "eval" / "dataset" / "stage5" / "stage5_analysis_manifest.json"
RUNS_DIR = BASE_DIR / "eval" / "runs"
LATEST_STAGE5_REPORT_PATH = RUNS_DIR / "latest_stage5_eval_report.json"

_LEGACY_RETAIL_BIAS_TOKENS = (
    "门店巡检",
    "商品陈列",
    "巡店出差",
    "连锁门店督导",
    "管辖门店数",
    "知名女装",
    "服装终端督导",
)


def _run_deterministic_checks(
    report: Dict[str, Any],
    top_candidates: List[Dict[str, Any]],
    intent: ParsedSearchIntent,
) -> Dict[str, Any]:
    """执行 Stage 5 确定性硬门禁校验。"""
    dims = report.get("dimensions") or {}
    me = report.get("match_evaluation") or {}
    recs = report.get("recommended_jobs") or []

    required_dims = ("industry", "salary", "skills", "experience", "brand", "welfare")
    schema_complete_ok = bool(
        (report.get("executive_summary") or "").strip()
        and all((dims.get(d) or {}).get("insight", "").strip() for d in required_dims)
        and (me.get("verdict") or "").strip()
        and len(me.get("strengths") or []) >= 2
        and len(me.get("risks") or []) >= 1
        and len(me.get("advice") or []) >= 2
    )

    overall_sc = me.get("overall_score", -1)
    top_k_coverage_ok = bool(
        len(recs) == len(top_candidates)
        and isinstance(overall_sc, (int, float))
        and 0 <= overall_sc <= 100
        and all(
            isinstance(r.get("match_score"), (int, float))
            and 0 <= r["match_score"] <= 100
            and bool((r.get("match_reason") or "").strip())
            for r in recs
        )
    )

    serialized = json.dumps(report, ensure_ascii=False)
    is_retail_query = any(k in intent.raw_query for k in ("服装", "零售", "督导", "门店"))
    leaked_tokens = [tok for tok in _LEGACY_RETAIL_BIAS_TOKENS if tok in serialized]
    zero_domain_bias_ok = True if is_retail_query else (len(leaked_tokens) == 0)

    stat_grounding_ok = bool(
        intent.city_name in serialized and (intent.query in serialized or intent.query[:2] in serialized)
    )

    return {
        "schema_complete_ok": schema_complete_ok,
        "top_k_coverage_ok": top_k_coverage_ok,
        "zero_domain_bias_ok": zero_domain_bias_ok,
        "leaked_bias_tokens": leaked_tokens,
        "stat_grounding_ok": stat_grounding_ok,
    }


def _evaluate_single_scenario(
    scenario: Dict[str, Any],
    *,
    extract_model: str,
    judge_model: str,
    temperature: float,
    api_key: Optional[str],
    proxy_url: Optional[str],
) -> Dict[str, Any]:
    """对单个场景执行 Stage 4 排序 -> Argon 锚点 -> gemini-3.8-flash Stage 5 分析 -> Argon 裁判。"""
    sid = scenario["scenario_id"].replace("S4-", "S5-")
    intent = ParsedSearchIntent.model_validate(scenario["intent"])
    resume_profile = scenario.get("resume_profile") or {}
    jobs_copy = [dict(j) for j in scenario.get("jobs", [])]

    ranked_jobs, top_candidates = rank_and_filter_jobs(
        jobs=jobs_copy,
        intent=intent,
        top_k=8,
        resume_profile=resume_profile,
    )
    stats = compute_six_dimension_stats(ranked_jobs, top_candidates, intent)

    # 1. Argon 自动生成事实锚点
    t_gt = time.perf_counter()
    gt_anchor = generate_stage5_ground_truth_anchor(
        scenario_id=sid,
        intent=scenario["intent"],
        stats=stats,
        top_candidates=top_candidates,
        resume_profile=resume_profile,
        model_name=judge_model,
        api_key=api_key,
        proxy_url=proxy_url,
    )
    gt_latency_s = round(time.perf_counter() - t_gt, 2)

    # 2. gemini-3.8-flash 执行 Stage 5 六维分析
    t0 = time.perf_counter()
    report = analyze_jobs_with_gemini(
        intent=intent,
        jobs=ranked_jobs,
        top_candidates=top_candidates,
        model_name=extract_model,
        temperature=temperature,
        api_key=api_key,
        proxy_url=proxy_url,
        resume_profile=resume_profile,
    )
    analysis_latency_s = round(time.perf_counter() - t0, 2)

    # 3. 确定性硬门禁
    det_checks = _run_deterministic_checks(report, top_candidates, intent)

    # 4. Argon LLM-as-a-Judge 评分
    t1 = time.perf_counter()
    judge_res = evaluate_stage5_analysis_with_llm_judge(
        scenario_id=sid,
        intent=scenario["intent"],
        stats=stats,
        top_candidates=top_candidates,
        resume_profile=resume_profile,
        ground_truth_anchor=gt_anchor,
        actual_report=report,
        deterministic_checks=det_checks,
        judge_model=judge_model,
        api_key=api_key,
        proxy_url=proxy_url,
    )
    judge_latency_s = round(time.perf_counter() - t1, 2)

    me = report.get("match_evaluation") or {}
    recs = report.get("recommended_jobs") or []
    return {
        "scenario_id": sid,
        "source_stage4_scenario_id": scenario["scenario_id"],
        "source_sample_id": scenario.get("source_sample_id", ""),
        "industry_category": scenario.get("industry_category", ""),
        "intent": scenario["intent"],
        "stats_summary": {
            "total_jobs": stats["total_jobs"],
            "compliant_jobs_count": stats["compliant_jobs_count"],
            "demoted_jobs_count": stats["demoted_jobs_count"],
            "avg_min_k": stats["salary"]["avg_min_k"],
            "avg_max_k": stats["salary"]["avg_max_k"],
            "median_mid_k": stats["salary"]["median_mid_k"],
        },
        "ground_truth_anchor": gt_anchor,
        "deterministic_checks": det_checks,
        "judge_scores": {k: judge_res[k] for k in STAGE5_DIMENSION_KEYS},
        "overall_score_10": judge_res["overall_score_10"],
        "diagnosis_comment": judge_res["diagnosis_comment"],
        "report_overall_match_score": me.get("overall_score", 0),
        "report_verdict": me.get("verdict", ""),
        "report_executive_summary": report.get("executive_summary", ""),
        "top_3_recommended": [
            {
                "rank": r.get("rank"),
                "job_name": r.get("job_name"),
                "company_name": r.get("company_name"),
                "salary_desc": r.get("salary_desc"),
                "weekend_policy": r.get("weekend_policy"),
                "match_score": r.get("match_score"),
            }
            for r in recs[:3]
        ],
        "gt_latency_s": gt_latency_s,
        "analysis_latency_s": analysis_latency_s,
        "judge_latency_s": judge_latency_s,
    }


def run_stage5_dataset_evaluation(
    *,
    stage4_manifest_path: Path = DEFAULT_STAGE4_MANIFEST,
    stage5_manifest_path: Path = DEFAULT_STAGE5_MANIFEST,
    extract_model: str = DEFAULT_STAGE5_ANALYSIS_MODEL,
    judge_model: str = DEFAULT_STAGE5_JUDGE_MODEL,
    temperature: float = DEFAULT_STAGE5_TEMPERATURE,
    workers: int = 3,
    api_key: Optional[str] = None,
    proxy_url: Optional[str] = None,
    save_report: bool = True,
) -> Dict[str, Any]:
    """执行 Stage 5 自动化端到端评测（gemini-3.8-flash 分析 + gemini-4-argon 锚点与裁判）。"""
    if not stage4_manifest_path.is_file():
        raise FileNotFoundError(f"找不到 Stage 4 数据集文件: {stage4_manifest_path}")

    s4_manifest = json.loads(stage4_manifest_path.read_text(encoding="utf-8"))
    scenarios = s4_manifest.get("scenarios") or []
    eff_api_key = api_key or load_backend_api_key()

    print(
        f"[Stage5-Eval] 启动评测: scenarios={len(scenarios)}, analyzer={extract_model} (temp={temperature}), "
        f"judge={judge_model} (temp=0.0)..."
    )

    results_by_idx: Dict[int, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        fmap = {
            pool.submit(
                _evaluate_single_scenario,
                sc,
                extract_model=extract_model,
                judge_model=judge_model,
                temperature=temperature,
                api_key=eff_api_key,
                proxy_url=proxy_url,
            ): idx
            for idx, sc in enumerate(scenarios)
        }
        for fut in as_completed(fmap):
            idx = fmap[fut]
            res = fut.result()
            results_by_idx[idx] = res
            dc = res["deterministic_checks"]
            print(
                f"  ✓ {res['scenario_id']} ({res['intent']['city_name']}·{res['intent']['query']}) | "
                f"Argon={res['overall_score_10']}/10 | MatchScore={res['report_overall_match_score']}/100 | "
                f"Schema={dc['schema_complete_ok']} Cov={dc['top_k_coverage_ok']} ZeroBias={dc['zero_domain_bias_ok']} "
                f"({res['analysis_latency_s']}s + judge {res['judge_latency_s']}s)"
            )

    scenario_results = [results_by_idx[i] for i in range(len(scenarios))]
    n = len(scenario_results)
    now = datetime.datetime.now()

    # 保存 Stage 5 自动生成的 Argon Ground Truth 锚点清单
    stage5_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    stage5_manifest_payload = {
        "schema_version": "stage5_analysis_ground_truth_v1",
        "review_status": "AUTO_APPROVED",
        "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "generator_model": judge_model,
        "source_stage4_manifest": str(stage4_manifest_path.relative_to(BASE_DIR)),
        "total_scenarios": n,
        "anchors": [
            {
                "scenario_id": r["scenario_id"],
                "intent": r["intent"],
                "stats_summary": r["stats_summary"],
                "ground_truth_anchor": r["ground_truth_anchor"],
            }
            for r in scenario_results
        ],
    }
    stage5_manifest_path.write_text(
        json.dumps(stage5_manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    mean_score = round(sum(r["overall_score_10"] for r in scenario_results) / n, 2)
    schema_rate = round(
        sum(1 for r in scenario_results if r["deterministic_checks"]["schema_complete_ok"]) / n, 4
    )
    coverage_rate = round(
        sum(1 for r in scenario_results if r["deterministic_checks"]["top_k_coverage_ok"]) / n, 4
    )
    zero_bias_rate = round(
        sum(1 for r in scenario_results if r["deterministic_checks"]["zero_domain_bias_ok"]) / n, 4
    )
    grounding_rate = round(
        sum(1 for r in scenario_results if r["deterministic_checks"]["stat_grounding_ok"]) / n, 4
    )
    mean_analysis_s = round(sum(r["analysis_latency_s"] for r in scenario_results) / n, 2)
    mean_judge_s = round(sum(r["judge_latency_s"] for r in scenario_results) / n, 2)

    per_dim_means = {
        dk: round(sum(r["judge_scores"][dk] for r in scenario_results) / n, 2)
        for dk in STAGE5_DIMENSION_KEYS
    }

    run_id = f"run_stage5_analysis_{now.strftime('%Y%m%d_%H%M%S')}"
    report_payload: Dict[str, Any] = {
        "run_id": run_id,
        "stage_id": "stage5_analysis",
        "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "evaluation_mode": "llm_as_a_judge_stage5_grounded_analysis",
        "extract_model": extract_model,
        "judge_model": judge_model,
        "temperature_used": temperature,
        "source_manifest": str(stage5_manifest_path.relative_to(BASE_DIR)),
        "total_scenarios": n,
        "mean_score_10": mean_score,
        "schema_complete_rate": schema_rate,
        "top_k_coverage_rate": coverage_rate,
        "zero_domain_bias_rate": zero_bias_rate,
        "stat_grounding_rate": grounding_rate,
        "mean_analysis_latency_s": mean_analysis_s,
        "mean_judge_latency_s": mean_judge_s,
        "dimension_labels": STAGE5_DIMENSION_LABELS,
        "per_dimension_mean_scores_10": per_dim_means,
        "scenario_evaluations": scenario_results,
    }

    if save_report:
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        run_file = RUNS_DIR / f"{run_id}.json"
        run_file.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        LATEST_STAGE5_REPORT_PATH.write_text(
            json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            f"\n[Stage5-Eval] 评测完成！Argon 均分: {mean_score}/10 | "
            f"Schema={schema_rate*100:.0f}% | TopK覆盖={coverage_rate*100:.0f}% | 零领域污染={zero_bias_rate*100:.0f}%"
        )
        print(f"[Stage5-Eval] 报告已归档: {run_file}")

    return report_payload


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 Stage 5 六维分析与人岗匹配评估")
    parser.add_argument("--extract-model", type=str, default=DEFAULT_STAGE5_ANALYSIS_MODEL)
    parser.add_argument("--judge-model", type=str, default=DEFAULT_STAGE5_JUDGE_MODEL)
    parser.add_argument("--temperature", type=float, default=DEFAULT_STAGE5_TEMPERATURE)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()

    run_stage5_dataset_evaluation(
        extract_model=args.extract_model,
        judge_model=args.judge_model,
        temperature=args.temperature,
        workers=args.workers,
    )


if __name__ == "__main__":
    main()
