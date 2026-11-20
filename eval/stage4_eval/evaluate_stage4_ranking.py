#!/usr/bin/env python3
"""
Stage 4 离线岗位过滤与 Top-K 粗排 — 独立评测脚本
- 待测引擎: core.boss_crawler.rank_and_filter_jobs / parse_salary_bounds / detect_weekend_policy
- 裁判模型 (LLM-as-a-Judge): gemini-4-argon (temperature=0.0)
- 评测基准: 经人工 Manual Review 批准的 eval/dataset/stage4/stage4_ranking_manifest.json (6 场景 96 岗位 + 12 边界用例)
- 输出归档: eval/runs/<run_id>.json & eval/runs/latest_stage4_eval_report.json
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.boss_crawler import (
    detect_weekend_policy,
    parse_salary_bounds,
    rank_and_filter_jobs,
)
from core.gemini_client import load_backend_api_key
from core.intent_parser import ParsedSearchIntent
from eval.stage4_eval.llm_judge_stage4 import (
    DEFAULT_STAGE4_JUDGE_MODEL,
    STAGE4_DIMENSION_KEYS,
    STAGE4_DIMENSION_LABELS,
    evaluate_stage4_ranking_with_llm_judge,
)

DEFAULT_MANIFEST_PATH = BASE_DIR / "eval" / "dataset" / "stage4" / "stage4_ranking_manifest.json"
RUNS_DIR = BASE_DIR / "eval" / "runs"
LATEST_STAGE4_REPORT_PATH = RUNS_DIR / "latest_stage4_eval_report.json"


def _compute_ndcg_at_k(ranked_grades: List[int], all_grades: List[int], k: int = 8) -> float:
    """计算标准 NDCG@K（使用 2^rel - 1 增益与 log2(rank + 1) 折损）。"""
    def dcg(grades: List[int]) -> float:
        return sum((2 ** g - 1) / math.log2(idx + 2) for idx, g in enumerate(grades[:k]))

    actual_dcg = dcg(ranked_grades)
    ideal_dcg = dcg(sorted(all_grades, reverse=True))
    if ideal_dcg <= 0:
        return 1.0
    return round(actual_dcg / ideal_dcg, 4)


def _run_boundary_edge_cases(boundary: Dict[str, Any]) -> Dict[str, Any]:
    """执行薪资解析与作息识别 12 条确定性边界用例校验。"""
    salary_results = []
    for c in boundary.get("salary_parse_cases") or []:
        actual = list(parse_salary_bounds(c["input"]))
        passed = actual == list(c["expected"])
        salary_results.append(
            {
                "id": c["id"],
                "input": c["input"],
                "expected": c["expected"],
                "actual": actual,
                "passed": passed,
            }
        )

    weekend_results = []
    for c in boundary.get("weekend_policy_cases") or []:
        actual = detect_weekend_policy(c["input"])
        passed = actual == c["expected"]
        weekend_results.append(
            {
                "id": c["id"],
                "input": c["input"],
                "expected": c["expected"],
                "actual": actual,
                "passed": passed,
            }
        )

    sal_acc = round(
        sum(1 for x in salary_results if x["passed"]) / max(1, len(salary_results)), 4
    )
    wkd_acc = round(
        sum(1 for x in weekend_results if x["passed"]) / max(1, len(weekend_results)), 4
    )
    return {
        "salary_parse_accuracy": sal_acc,
        "weekend_policy_accuracy": wkd_acc,
        "salary_cases": salary_results,
        "weekend_cases": weekend_results,
    }


def _evaluate_single_scenario(
    scenario: Dict[str, Any],
    *,
    top_k: int,
    judge_model: str,
    api_key: Optional[str],
    proxy_url: Optional[str],
) -> Dict[str, Any]:
    """评测单个离线场景的粗排质量、降权纯净度与 Argon 评分。"""
    t0 = time.perf_counter()
    intent = ParsedSearchIntent.model_validate(scenario["intent"])
    resume_profile = scenario.get("resume_profile") or {}
    jobs_copy = [dict(j) for j in scenario.get("jobs", [])]

    ranked_jobs, top_candidates = rank_and_filter_jobs(
        jobs=jobs_copy,
        intent=intent,
        top_k=top_k,
        resume_profile=resume_profile,
    )
    rank_latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)

    all_grades = [int(j.get("ground_truth_grade", 0)) for j in jobs_copy]
    ranked_grades = [int(j.get("ground_truth_grade", 0)) for j in ranked_jobs]
    ndcg_at_k = _compute_ndcg_at_k(ranked_grades, all_grades, k=top_k)

    relevant_total = sum(1 for g in all_grades if g >= 2)
    relevant_in_top_k = sum(1 for j in top_candidates if int(j.get("ground_truth_grade", 0)) >= 2)
    recall_at_k = round(relevant_in_top_k / max(1, relevant_total), 4)

    # 异地/低薪降权垫底核验（保留在全量池，但严格排在所有合规岗位之后且零混入 Top-K）
    expected_demoted_jobs = [j for j in ranked_jobs if j.get("expected_demoted")]
    actual_demoted_jobs = [j for j in ranked_jobs if j.get("is_demoted")]
    first_demoted_idx = next(
        (i for i, j in enumerate(ranked_jobs) if j.get("is_demoted")), len(ranked_jobs)
    )
    all_compliant_before_demoted = all(
        not j.get("is_demoted") for j in ranked_jobs[:first_demoted_idx]
    ) and all(j.get("is_demoted") for j in ranked_jobs[first_demoted_idx:])
    demoted_flags_match = all(
        bool(j.get("is_demoted")) == bool(j.get("expected_demoted")) for j in ranked_jobs
    )
    top_k_zero_demoted = all(not j.get("is_demoted") for j in top_candidates)
    full_pool_preserved = len(ranked_jobs) == len(jobs_copy)
    demotion_clean_ok = bool(
        demoted_flags_match
        and all_compliant_before_demoted
        and top_k_zero_demoted
        and full_pool_preserved
    )

    # 作息陷阱核验（场景内单双休/隔周双休/非双休未被误判为“周末双休”）
    weekend_traps = [j for j in ranked_jobs if j.get("trap_type") == "weekend_trap"]
    weekend_trap_clean_ok = all(j.get("作息制度") != "周末双休" for j in weekend_traps)

    det_metrics = {
        "ndcg_at_8": ndcg_at_k,
        "recall_at_8": recall_at_k,
        "relevant_in_top_8": relevant_in_top_k,
        "relevant_total": relevant_total,
        "expected_demoted_count": len(expected_demoted_jobs),
        "actual_demoted_count": len(actual_demoted_jobs),
        "demotion_clean_ok": demotion_clean_ok,
        "top_k_zero_demoted": top_k_zero_demoted,
        "full_pool_preserved": full_pool_preserved,
        "weekend_trap_clean_ok": weekend_trap_clean_ok,
    }

    t1 = time.perf_counter()
    judge_res = evaluate_stage4_ranking_with_llm_judge(
        scenario_id=scenario["scenario_id"],
        intent=scenario["intent"],
        top_candidates=top_candidates,
        demoted_jobs=actual_demoted_jobs,
        deterministic_metrics=det_metrics,
        judge_model=judge_model,
        api_key=api_key,
        proxy_url=proxy_url,
    )
    judge_latency_s = round(time.perf_counter() - t1, 2)

    return {
        "scenario_id": scenario["scenario_id"],
        "source_stage3_case_id": scenario.get("source_stage3_case_id", ""),
        "source_sample_id": scenario.get("source_sample_id", ""),
        "industry_category": scenario.get("industry_category", ""),
        "intent": scenario["intent"],
        "total_jobs": len(ranked_jobs),
        "deterministic_metrics": det_metrics,
        "judge_scores": {k: judge_res[k] for k in STAGE4_DIMENSION_KEYS},
        "overall_score_10": judge_res["overall_score_10"],
        "diagnosis_comment": judge_res["diagnosis_comment"],
        "rank_latency_ms": rank_latency_ms,
        "judge_latency_s": judge_latency_s,
        "top_candidates": [
            {
                "rank": idx + 1,
                "job_id": j.get("job_id"),
                "岗位名称": j.get("岗位名称"),
                "薪资范围": j.get("薪资范围"),
                "工作地点": j.get("工作地点"),
                "所属行业": j.get("所属行业"),
                "作息制度": j.get("作息制度"),
                "初筛得分": j.get("初筛得分"),
                "ground_truth_grade": j.get("ground_truth_grade"),
                "trap_type": j.get("trap_type"),
                "is_demoted": j.get("is_demoted"),
                "score_breakdown": j.get("score_breakdown"),
            }
            for idx, j in enumerate(top_candidates)
        ],
        "demoted_jobs": [
            {
                "job_id": j.get("job_id"),
                "岗位名称": j.get("岗位名称"),
                "薪资范围": j.get("薪资范围"),
                "工作地点": j.get("工作地点"),
                "trap_type": j.get("trap_type"),
                "demotion_reasons": j.get("demotion_reasons"),
                "初筛得分": j.get("初筛得分"),
            }
            for j in actual_demoted_jobs
        ],
    }


def run_stage4_dataset_evaluation(
    *,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    top_k: int = 8,
    judge_model: str = DEFAULT_STAGE4_JUDGE_MODEL,
    workers: int = 3,
    api_key: Optional[str] = None,
    proxy_url: Optional[str] = None,
    save_report: bool = True,
) -> Dict[str, Any]:
    """执行 Stage 4 离线粗排与过滤评测，并归档至 latest_stage4_eval_report.json。"""
    if not manifest_path.is_file():
        raise FileNotFoundError(f"找不到 Stage 4 Ground Truth 文件: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("review_status") != "APPROVED":
        raise ValueError(
            f"Stage 4 Ground Truth 尚未通过人工 Review（当前状态: {manifest.get('review_status')}），禁止运行评测。"
        )

    boundary_eval = _run_boundary_edge_cases(manifest.get("boundary_edge_cases") or {})
    scenarios = manifest.get("scenarios") or []
    eff_api_key = api_key or load_backend_api_key()

    print(
        f"[Stage4-Eval] 启动评测: scenarios={len(scenarios)} (total_jobs={manifest.get('total_jobs')}), "
        f"judge_model={judge_model} (temp=0.0)..."
    )
    print(
        f"  [Boundary] 薪资解析边界准确率: {boundary_eval['salary_parse_accuracy']*100:.1f}% | "
        f"作息识别边界准确率: {boundary_eval['weekend_policy_accuracy']*100:.1f}%"
    )

    results_by_idx: Dict[int, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        fmap = {
            pool.submit(
                _evaluate_single_scenario,
                sc,
                top_k=top_k,
                judge_model=judge_model,
                api_key=eff_api_key,
                proxy_url=proxy_url,
            ): idx
            for idx, sc in enumerate(scenarios)
        }
        for fut in as_completed(fmap):
            idx = fmap[fut]
            res = fut.result()
            results_by_idx[idx] = res
            dm = res["deterministic_metrics"]
            print(
                f"  ✓ {res['scenario_id']} ({res['intent']['city_name']}·{res['intent']['query']}) | "
                f"Argon={res['overall_score_10']}/10 | NDCG@8={dm['ndcg_at_8']:.4f} | "
                f"Recall@8={dm['recall_at_8']*100:.1f}% | DemotionClean={dm['demotion_clean_ok']} "
                f"({res['rank_latency_ms']}ms + judge {res['judge_latency_s']}s)"
            )

    scenario_results = [results_by_idx[i] for i in range(len(scenarios))]
    n = len(scenario_results)

    mean_score = round(sum(r["overall_score_10"] for r in scenario_results) / n, 2)
    mean_ndcg = round(sum(r["deterministic_metrics"]["ndcg_at_8"] for r in scenario_results) / n, 4)
    mean_recall = round(sum(r["deterministic_metrics"]["recall_at_8"] for r in scenario_results) / n, 4)
    demotion_rate = round(
        sum(1 for r in scenario_results if r["deterministic_metrics"]["demotion_clean_ok"]) / n, 4
    )
    weekend_trap_rate = round(
        sum(1 for r in scenario_results if r["deterministic_metrics"]["weekend_trap_clean_ok"]) / n, 4
    )
    mean_rank_ms = round(sum(r["rank_latency_ms"] for r in scenario_results) / n, 2)
    mean_judge_s = round(sum(r["judge_latency_s"] for r in scenario_results) / n, 2)

    per_dim_means = {
        dk: round(sum(r["judge_scores"][dk] for r in scenario_results) / n, 2)
        for dk in STAGE4_DIMENSION_KEYS
    }

    now = datetime.datetime.now()
    run_id = f"run_stage4_ranking_{now.strftime('%Y%m%d_%H%M%S')}"
    report: Dict[str, Any] = {
        "run_id": run_id,
        "stage_id": "stage4_ranking",
        "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "evaluation_mode": "llm_as_a_judge_stage4_ndcg_and_demotion",
        "extract_model": "deterministic_ranker_v2",
        "judge_model": judge_model,
        "source_manifest": str(manifest_path.relative_to(BASE_DIR)),
        "total_scenarios": n,
        "total_jobs": sum(r["total_jobs"] for r in scenario_results),
        "top_k": top_k,
        "mean_score_10": mean_score,
        "mean_ndcg_at_8": mean_ndcg,
        "mean_recall_at_8": mean_recall,
        "demotion_accuracy_rate": demotion_rate,
        "weekend_trap_clean_rate": weekend_trap_rate,
        "salary_parse_accuracy": boundary_eval["salary_parse_accuracy"],
        "weekend_policy_accuracy": boundary_eval["weekend_policy_accuracy"],
        "mean_rank_latency_ms": mean_rank_ms,
        "mean_judge_latency_s": mean_judge_s,
        "dimension_labels": STAGE4_DIMENSION_LABELS,
        "per_dimension_mean_scores_10": per_dim_means,
        "boundary_evaluation": boundary_eval,
        "scenario_evaluations": scenario_results,
    }

    if save_report:
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        run_file = RUNS_DIR / f"{run_id}.json"
        run_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        LATEST_STAGE4_REPORT_PATH.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            f"\n[Stage4-Eval] 评测完成！Argon 均分: {mean_score}/10 | NDCG@8: {mean_ndcg:.4f} | "
            f"Recall@8: {mean_recall*100:.1f}% | 降权垫底准确率: {demotion_rate*100:.1f}%"
        )
        print(f"[Stage4-Eval] 报告已归档: {run_file}")

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 Stage 4 离线岗位过滤与 Top-K 粗排评测")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--judge-model", type=str, default=DEFAULT_STAGE4_JUDGE_MODEL)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()

    run_stage4_dataset_evaluation(
        manifest_path=args.manifest,
        top_k=args.top_k,
        judge_model=args.judge_model,
        workers=args.workers,
    )


if __name__ == "__main__":
    main()
