#!/usr/bin/env python3
"""
Stage 3 意图解析与 BOSS直聘 URL 生成 — 独立评测脚本
- 待测模型 (Stage 3 Parser): gemini-3.8-flash (temperature=0.1)
- 裁判模型 (LLM-as-a-Judge): gemini-4-argon (temperature=0.0)
- 评测基准: 经人工 Manual Review 批准的 eval/dataset/stage3/stage3_intent_manifest.json (18 条抽样集)
- 输出归档: eval/runs/<run_id>.json & eval/runs/latest_stage3_eval_report.json
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.gemini_client import load_backend_api_key
from core.intent_parser import (
    CITY_CODE_MAP,
    DEFAULT_STAGE3_INTENT_MODEL,
    DEFAULT_STAGE3_TEMPERATURE,
    DEGREE_CODE_LABELS,
    EXPERIENCE_CODE_LABELS,
    SALARY_CODE_LABELS,
    SCALE_CODE_LABELS,
    STAGE_CODE_LABELS,
    parse_user_intent,
)
from eval.stage3_eval.llm_judge_stage3 import (
    DEFAULT_STAGE3_JUDGE_MODEL,
    STAGE3_DIMENSION_KEYS,
    STAGE3_DIMENSION_LABELS,
    evaluate_stage3_intent_with_llm_judge,
)

DEFAULT_MANIFEST_PATH = BASE_DIR / "eval" / "dataset" / "stage3" / "stage3_intent_manifest.json"
RUNS_DIR = BASE_DIR / "eval" / "runs"
LATEST_STAGE3_REPORT_PATH = RUNS_DIR / "latest_stage3_eval_report.json"

_FORBIDDEN_QUERY_TOKENS = ("行业", "领域", "赛道", "岗位", "职位", "月薪", "双休", "/")


def _check_query_purity(query: str) -> bool:
    """检查核心岗位词 query 是否纯净（不含城市、行业/岗位/月薪/双休后缀、斜杠）。"""
    q = (query or "").strip()
    if not q or len(q) > 24:
        return False
    for tok in _FORBIDDEN_QUERY_TOKENS:
        if tok in q:
            return False
    for city in CITY_CODE_MAP:
        if city != "全国" and city in q:
            return False
    return True


def _check_url_and_whitelist(boss_url: str, intent_dict: Dict[str, Any]) -> bool:
    """检查生成的 BOSS直聘 URL 格式与全部官方编码白名单合法性。"""
    if not boss_url.startswith("https://www.zhipin.com/web/geek/jobs?"):
        return False
    parsed = urllib.parse.urlparse(boss_url)
    qs = urllib.parse.parse_qs(parsed.query)
    if not qs.get("query") or not qs.get("city"):
        return False
    city_code = qs["city"][0]
    if city_code not in CITY_CODE_MAP.values():
        return False
    if intent_dict.get("salary_code", "") not in SALARY_CODE_LABELS:
        return False
    if intent_dict.get("experience_code", "") not in EXPERIENCE_CODE_LABELS:
        return False
    if intent_dict.get("degree_code", "") not in DEGREE_CODE_LABELS:
        return False
    if intent_dict.get("scale_code", "") not in SCALE_CODE_LABELS:
        return False
    if intent_dict.get("stage_code", "") not in STAGE_CODE_LABELS:
        return False
    return True


def _urls_equivalent(url_a: str, url_b: str) -> bool:
    """比较两条 BOSS直聘 URL 是否在规范化参数上完全等价。"""
    pa = urllib.parse.urlparse(url_a)
    pb = urllib.parse.urlparse(url_b)
    if (pa.scheme, pa.netloc, pa.path) != (pb.scheme, pb.netloc, pb.path):
        return False
    return urllib.parse.parse_qs(pa.query) == urllib.parse.parse_qs(pb.query)


def _evaluate_single_case(
    sample: Dict[str, Any],
    *,
    extract_model: str,
    judge_model: str,
    temperature: float,
    api_key: Optional[str],
    proxy_url: Optional[str],
) -> Dict[str, Any]:
    """对单条样本执行 Stage 3 解析 (gemini-3.8-flash) + 确定性门禁 + Argon LLM-as-a-Judge 评测。"""
    inp = sample["input"]
    gt = sample["ground_truth"]
    query_text = inp["query_text"]
    target_city = inp.get("target_city")
    resume_profile = inp.get("resume_profile")

    t0 = time.perf_counter()
    parsed_intent = parse_user_intent(
        query_text,
        target_city=target_city,
        resume_profile=resume_profile,
        model_name=extract_model,
        temperature=temperature,
        api_key=api_key,
        proxy_url=proxy_url,
    )
    parse_latency_s = round(time.perf_counter() - t0, 2)
    actual_dict = parsed_intent.model_dump()
    actual_boss_url = parsed_intent.build_boss_url()

    # 确定性门禁校验
    url_valid_ok = _check_url_and_whitelist(actual_boss_url, actual_dict)
    url_exact_match_ok = _urls_equivalent(actual_boss_url, gt.get("expected_boss_url", ""))
    city_match_ok = (
        actual_dict.get("city_name") == gt.get("expected_city_name")
        and actual_dict.get("city_code") == gt.get("expected_city_code")
    )
    salary_match_ok = (
        actual_dict.get("salary_code") == gt.get("expected_salary_code")
        and int(actual_dict.get("min_salary_k", 0)) == int(gt.get("expected_min_salary_k", 0))
    )
    query_pure_ok = _check_query_purity(actual_dict.get("query", ""))
    extra_codes_match_ok = (
        actual_dict.get("experience_code", "") == gt.get("expected_experience_code", "")
        and actual_dict.get("degree_code", "") == gt.get("expected_degree_code", "")
        and actual_dict.get("scale_code", "") == gt.get("expected_scale_code", "")
        and actual_dict.get("stage_code", "") == gt.get("expected_stage_code", "")
    )

    det_checks = {
        "url_exact_match_ok": url_exact_match_ok,
        "url_valid_ok": url_valid_ok,
        "city_match_ok": city_match_ok,
        "salary_match_ok": salary_match_ok,
        "query_pure_ok": query_pure_ok,
        "extra_codes_match_ok": extra_codes_match_ok,
    }

    t1 = time.perf_counter()
    judge_res = evaluate_stage3_intent_with_llm_judge(
        input_query=query_text,
        input_target_city=str(target_city or ""),
        ground_truth=gt,
        actual_intent=actual_dict,
        actual_boss_url=actual_boss_url,
        deterministic_checks=det_checks,
        judge_model=judge_model,
        api_key=api_key,
        proxy_url=proxy_url,
    )
    judge_latency_s = round(time.perf_counter() - t1, 2)

    return {
        "case_id": sample["case_id"],
        "source_sample_id": sample["source_sample_id"],
        "industry_category": sample.get("industry_category", ""),
        "strategy_tag": sample.get("strategy_tag", ""),
        "input_query": query_text,
        "input_target_city": target_city,
        "ground_truth": gt,
        "actual_intent": actual_dict,
        "actual_boss_url": actual_boss_url,
        "actual_boss_url_decoded": urllib.parse.unquote(actual_boss_url),
        "expected_boss_url_decoded": urllib.parse.unquote(gt.get("expected_boss_url", "")),
        "deterministic_checks": det_checks,
        "judge_scores": {
            "url_and_hard_filter_score": judge_res["url_and_hard_filter_score"],
            "role_purification_score": judge_res["role_purification_score"],
            "industry_expansion_score": judge_res["industry_expansion_score"],
            "soft_requirements_score": judge_res["soft_requirements_score"],
        },
        "overall_score_10": judge_res["overall_score_10"],
        "diagnosis_comment": judge_res["diagnosis_comment"],
        "parse_latency_s": parse_latency_s,
        "judge_latency_s": judge_latency_s,
    }


def run_stage3_dataset_evaluation(
    *,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    extract_model: str = DEFAULT_STAGE3_INTENT_MODEL,
    judge_model: str = DEFAULT_STAGE3_JUDGE_MODEL,
    temperature: float = DEFAULT_STAGE3_TEMPERATURE,
    workers: int = 4,
    case_ids: Optional[List[str]] = None,
    api_key: Optional[str] = None,
    proxy_url: Optional[str] = None,
    save_report: bool = True,
) -> Dict[str, Any]:
    """执行 Stage 3 评测（gemini-3.8-flash 生成 URL，gemini-4-argon LLM-as-a-Judge 评分）。"""
    if not manifest_path.is_file():
        raise FileNotFoundError(f"找不到 Stage 3 Ground Truth 文件: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("review_status") != "APPROVED":
        raise ValueError(
            f"Stage 3 Ground Truth 尚未通过人工 Review（当前状态: {manifest.get('review_status')}），禁止运行评测。"
        )

    samples = manifest.get("samples") or []
    if case_ids:
        id_set = set(case_ids)
        samples = [s for s in samples if s.get("case_id") in id_set or s.get("source_sample_id") in id_set]
    if not samples:
        raise ValueError("未匹配到任何 Stage 3 评测样本")

    eff_api_key = api_key or load_backend_api_key()
    print(
        f"[Stage3-Eval] 启动评测: samples={len(samples)}, parser_model={extract_model} (temp={temperature}), "
        f"judge_model={judge_model} (temp=0.0)..."
    )

    results_by_idx: Dict[int, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        future_map = {
            pool.submit(
                _evaluate_single_case,
                s,
                extract_model=extract_model,
                judge_model=judge_model,
                temperature=temperature,
                api_key=eff_api_key,
                proxy_url=proxy_url,
            ): idx
            for idx, s in enumerate(samples)
        }
        for fut in as_completed(future_map):
            idx = future_map[fut]
            res = fut.result()
            results_by_idx[idx] = res
            dc = res["deterministic_checks"]
            status_mark = "✓ EXACT" if dc["url_exact_match_ok"] else "~ DIFF"
            print(
                f"  [{status_mark}] {res['case_id']} | score={res['overall_score_10']}/10 | "
                f"URL={res['actual_boss_url_decoded']} ({res['parse_latency_s']}s + judge {res['judge_latency_s']}s)"
            )

    case_results = [results_by_idx[i] for i in range(len(samples))]
    n = len(case_results)

    mean_score = round(sum(r["overall_score_10"] for r in case_results) / n, 2)
    url_exact_rate = round(sum(1 for r in case_results if r["deterministic_checks"]["url_exact_match_ok"]) / n, 4)
    url_valid_rate = round(sum(1 for r in case_results if r["deterministic_checks"]["url_valid_ok"]) / n, 4)
    city_match_rate = round(sum(1 for r in case_results if r["deterministic_checks"]["city_match_ok"]) / n, 4)
    salary_match_rate = round(sum(1 for r in case_results if r["deterministic_checks"]["salary_match_ok"]) / n, 4)
    query_pure_rate = round(sum(1 for r in case_results if r["deterministic_checks"]["query_pure_ok"]) / n, 4)
    extra_codes_rate = round(sum(1 for r in case_results if r["deterministic_checks"]["extra_codes_match_ok"]) / n, 4)
    mean_parse_latency = round(sum(r["parse_latency_s"] for r in case_results) / n, 2)
    mean_judge_latency = round(sum(r["judge_latency_s"] for r in case_results) / n, 2)

    per_dim_means: Dict[str, float] = {}
    for dk in STAGE3_DIMENSION_KEYS:
        per_dim_means[dk] = round(
            sum(r["judge_scores"][dk] for r in case_results) / n, 2
        )

    # 按简历聚合均值（供前端柱状图）
    resume_buckets: Dict[str, List[Dict[str, Any]]] = {}
    city_counts: Dict[str, int] = {}
    salary_counts: Dict[str, int] = {}
    for r in case_results:
        sid = r["source_sample_id"]
        resume_buckets.setdefault(sid, []).append(r)
        cname = r["actual_intent"].get("city_name") or "未知"
        city_counts[cname] = city_counts.get(cname, 0) + 1
        slabel = r["actual_intent"].get("salary_label") or "不限"
        salary_counts[slabel] = salary_counts.get(slabel, 0) + 1

    per_resume_summary = []
    for sid, items in sorted(resume_buckets.items()):
        per_resume_summary.append(
            {
                "sample_id": sid,
                "industry_category": items[0].get("industry_category", ""),
                "case_count": len(items),
                "mean_score_10": round(sum(x["overall_score_10"] for x in items) / len(items), 2),
                "url_exact_count": sum(1 for x in items if x["deterministic_checks"]["url_exact_match_ok"]),
            }
        )

    now = datetime.datetime.now()
    run_id = f"run_stage3_intent_{now.strftime('%Y%m%d_%H%M%S')}"
    report: Dict[str, Any] = {
        "run_id": run_id,
        "stage_id": "stage3_intent",
        "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "evaluation_mode": "llm_as_a_judge_stage3_url_and_intent",
        "extract_model": extract_model,
        "judge_model": judge_model,
        "temperature_used": temperature,
        "source_manifest": str(manifest_path.relative_to(BASE_DIR)),
        "source_stage2_run_id": manifest.get("source_stage2_run_id", ""),
        "total_cases": n,
        "mean_score_10": mean_score,
        "url_exact_match_rate": url_exact_rate,
        "url_valid_rate": url_valid_rate,
        "city_match_rate": city_match_rate,
        "salary_match_rate": salary_match_rate,
        "query_pure_rate": query_pure_rate,
        "extra_codes_match_rate": extra_codes_rate,
        "mean_parse_latency_s": mean_parse_latency,
        "mean_judge_latency_s": mean_judge_latency,
        "dimension_labels": STAGE3_DIMENSION_LABELS,
        "per_dimension_mean_scores_10": per_dim_means,
        "per_resume_summary": per_resume_summary,
        "city_distribution": city_counts,
        "salary_distribution": salary_counts,
        "case_evaluations": case_results,
    }

    if save_report:
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        run_file = RUNS_DIR / f"{run_id}.json"
        run_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        LATEST_STAGE3_REPORT_PATH.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n[Stage3-Eval] 评测完成！综合得分: {mean_score}/10 | URL 精准一致率: {url_exact_rate*100:.1f}%")
        print(f"[Stage3-Eval] 报告已归档: {run_file}")

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 Stage 3 意图解析与 BOSS直聘 URL 生成评测")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--extract-model", type=str, default=DEFAULT_STAGE3_INTENT_MODEL)
    parser.add_argument("--judge-model", type=str, default=DEFAULT_STAGE3_JUDGE_MODEL)
    parser.add_argument("--temperature", type=float, default=DEFAULT_STAGE3_TEMPERATURE)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    run_stage3_dataset_evaluation(
        manifest_path=args.manifest,
        extract_model=args.extract_model,
        judge_model=args.judge_model,
        temperature=args.temperature,
        workers=args.workers,
    )


if __name__ == "__main__":
    main()
