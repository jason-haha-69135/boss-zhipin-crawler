#!/usr/bin/env python3
"""
Stage 2 多策略求职 Query 生成评测与批量运行引擎 (`evaluate_stage2_queries.py`)
核心职责：
1. 读取 `qualified_manifest.json` 中的 9 份合格简历样本（优先使用 Stage 1 实测提取画像，无则使用 Ground Truth 画像）；
2. 调用独立解耦的 `core.query_generator.generate_queries_from_profile_with_gemini`
   （默认 `model_name="gemini-3.8-flash"`, `temperature=0.4`, `query_count=10`）生成每个样本的 10 条求职 Query；
3. 对生成的 9 × 10 = 90 条 Query 执行逐条结构化解析与质量核验：
   - 核验【① 目标行业/赛道 + ② 单一标准核心岗位名称 + ③ 明确最低月薪底线】三要素完整性；
   - 核验“零城市名称泄露”与“零作息/福利套话残留”；
   - 核验岗位名称是否为单一简洁岗位（无 `/` 或顿号拼接多岗位）；
   - 核验 `match_reason` 长度与简历画像事实锚定度，以及 PII 隐私零泄露；
4. 汇总全局 KPI、10 大策略维度的平均得分与平均薪资梯度、各样本薪资跨度分布，并归档至 `runs/` 与 `dataset/latest_stage2_eval_report.json`。
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

BENCHMARK_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BENCHMARK_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_DIR))

from core.intent_parser import CITY_CODE_MAP
from core.query_generator import (
    DEFAULT_QUERY_COUNT,
    DEFAULT_STAGE2_QUERY_MODEL,
    DEFAULT_STAGE2_TEMPERATURE,
    STRATEGY_DIMENSIONS,
    _infer_boss_role_anchors,
    generate_queries_from_profile_with_gemini,
)
from schema_and_validator import resolve_safe_path

DATASET_DIR = BENCHMARK_DIR / "dataset"
RUNS_DIR = BENCHMARK_DIR / "runs"
LATEST_STAGE1_REPORT_PATH = DATASET_DIR / "latest_stage1_eval_report.json"
LATEST_STAGE2_REPORT_PATH = DATASET_DIR / "latest_stage2_eval_report.json"

FORBIDDEN_WELFARE_TERMS = (
    "周末双休",
    "双休",
    "五险一金",
    "六险一金",
    "年终奖",
    "大小周",
    "带薪年假",
    "朝九晚六",
)


def parse_salary_w_from_text(text: str) -> Optional[float]:
    """从 Query 或底薪字符串中提取以 'w' (万元/月) 为单位的数值"""
    s = (text or "").strip().lower()
    m_w = re.search(r"(\d+(?:\.\d+)?)\s*[w万]", s)
    if m_w:
        return round(float(m_w.group(1)), 2)
    m_k = re.search(r"(\d+(?:\.\d+)?)\s*k", s)
    if m_k:
        return round(float(m_k.group(1)) / 10.0, 2)
    return None


def decompose_query_three_elements(query_text: str) -> Dict[str, Any]:
    """
    从形如 '互联网新媒体行业的新媒体运营岗位，月薪至少0.8w' 的 Query 中拆解：
    - parsed_industry: 目标行业描述
    - parsed_role: 核心岗位名称
    - parsed_salary_str: 月薪底线字符串
    - parsed_salary_w: 月薪底线数值 (单位 w)
    """
    q = (query_text or "").strip()
    parts = [p.strip() for p in re.split(r"[，,；;]+", q) if p.strip()]
    first_clause = parts[0] if parts else q
    salary_clause = parts[1] if len(parts) > 1 else q

    parsed_industry = ""
    parsed_role = ""

    # 匹配 '<行业>的<岗位>岗位/职位'
    m = re.match(
        r"^(?P<ind>.+?(?:行业|领域|赛道|企业|公司|方向|生态|部门|机构|平台|产业|板块)?)\s*的\s*(?P<role>[^，,]+?)(?:岗位|职位|方向|角色)?$",
        first_clause,
    )
    if m:
        parsed_industry = m.group("ind").strip()
        parsed_role = m.group("role").strip()
    else:
        # 备选：按最后一个 '的' 切分
        if "的" in first_clause:
            idx = first_clause.rfind("的")
            parsed_industry = first_clause[:idx].strip()
            parsed_role = re.sub(r"(?:岗位|职位)$", "", first_clause[idx + 1 :].strip())
        else:
            parsed_role = re.sub(r"(?:岗位|职位)$", "", first_clause)

    sal_w = parse_salary_w_from_text(salary_clause) or parse_salary_w_from_text(q)
    m_sal_str = re.search(r"(?:月薪|薪资|底薪)?(?:至少|不低于|以上|起)?\s*\d+(?:\.\d+)?\s*[wW万kK]", q)
    parsed_salary_str = m_sal_str.group(0).strip() if m_sal_str else (f"月薪至少{sal_w}w" if sal_w else "")

    return {
        "parsed_industry": parsed_industry,
        "parsed_role": parsed_role,
        "parsed_salary_str": parsed_salary_str,
        "parsed_salary_w": sal_w,
    }


def evaluate_single_query_item(
    idx: int,
    item: Dict[str, str],
    profile: Dict[str, Any],
    raw_pii_tokens: List[str],
    base_salary_w: float,
) -> Dict[str, Any]:
    """
    对单条生成的 Query 执行原子级规则与语义锚定度评分 (0 ~ 10 分)：
    1. 三要素完备性 (4.0 分)：包含行业限定 + 单一标准岗位名 + 明确月薪底线；
    2. 零城市 & 零福利套话纯净度 (2.5 分)：不含具体城市名、不含双休/五险一金等福利套话；
    3. 岗位词规范度 (1.5 分)：岗位名长度适中 (2~10字) 且不含 `/` 或 `、` 拼接多个岗位；
    4. 推荐理由 (`match_reason`) 锚定度与 PII 安全 (2.0 分)：理由充实 (25~120字)、关联候选人画像且无 PII 泄露。
    """
    strategy_tag = (item.get("strategy_tag") or f"策略 {idx + 1}").strip()
    query_text = (item.get("query_text") or "").strip()
    match_reason = (item.get("match_reason") or "").strip()

    decomp = decompose_query_three_elements(query_text)
    parsed_ind = decomp["parsed_industry"]
    parsed_role = decomp["parsed_role"]
    sal_w = decomp["parsed_salary_w"]

    has_industry = bool(parsed_ind and len(parsed_ind) >= 2)
    has_role = bool(parsed_role and 2 <= len(parsed_role) <= 12)
    has_salary = sal_w is not None and sal_w > 0
    three_elements_ok = has_industry and has_role and has_salary

    # 检查是否包含城市名
    leaked_cities = [
        c for c in CITY_CODE_MAP if c != "全国" and c in query_text
    ]
    no_city_ok = len(leaked_cities) == 0

    # 检查是否残留作息/福利词
    leaked_welfares = [w for w in FORBIDDEN_WELFARE_TERMS if w in query_text]
    no_welfare_ok = len(leaked_welfares) == 0

    # 检查岗位名是否单一无斜杠/顿号拼接
    single_role_ok = bool(parsed_role) and not any(sep in parsed_role for sep in ("/", "｜", "|", "、"))

    # 检查 PII 零泄露
    combined_out = f"{strategy_tag} {query_text} {match_reason}"
    pii_leaks = [tok for tok in (raw_pii_tokens or []) if tok and len(tok.strip()) >= 2 and tok.strip() in combined_out]
    pii_safe_ok = len(pii_leaks) == 0

    # 检查 match_reason 是否锚定画像关键词
    profile_keywords: List[str] = []
    for sk in profile.get("core_skills") or []:
        if sk and len(sk) >= 2:
            profile_keywords.append(sk)
    for ind in profile.get("industry_background") or []:
        for sub in re.split(r"[/｜|、·,\s]+", str(ind)):
            if len(sub) >= 2:
                profile_keywords.append(sub)
    reason_len_ok = 20 <= len(match_reason) <= 140
    matched_kw = [kw for kw in profile_keywords if kw.lower() in match_reason.lower()]
    reason_grounded_ok = reason_len_ok and (len(matched_kw) >= 1 or len(match_reason) >= 35)

    score = 10.0
    notes: List[str] = []

    if not has_industry:
        score -= 2.0
        notes.append("缺少明确的目标行业前缀")
    if not has_role:
        score -= 2.0
        notes.append("未能拆解出标准岗位名")
    elif not single_role_ok:
        score -= 1.5
        notes.append(f"岗位名含多词拼接 ({parsed_role})")
    if not has_salary:
        score -= 2.0
        notes.append("缺少明确的月薪底线数字")
    if not no_city_ok:
        score -= 1.5
        notes.append(f"包含城市名称 ({','.join(leaked_cities)})")
    if not no_welfare_ok:
        score -= 1.0
        notes.append(f"残留福利词 ({','.join(leaked_welfares)})")
    if not pii_safe_ok:
        score -= 3.0
        notes.append(f"PII 泄露 ({','.join(pii_leaks)})")
    if not reason_grounded_ok:
        score -= 1.0
        notes.append("推荐理由过短或未充分引用画像亮点")

    score = round(max(0.0, min(10.0, score)), 2)

    salary_delta_pct = (
        round(((sal_w - base_salary_w) / base_salary_w) * 100, 1)
        if (sal_w is not None and base_salary_w > 0)
        else 0.0
    )

    if not notes:
        notes.append(
            f"三要素齐备（行业:【{parsed_ind}】· 岗位:【{parsed_role}】· 底薪:【{sal_w}w】），无城市与福利冗余，推荐理由紧扣简历资历。"
        )

    return {
        "query_index": idx + 1,
        "dimension": f"query_{idx + 1:02d}",
        "dimension_label": f"#{idx + 1} {strategy_tag}",
        "strategy_tag": strategy_tag,
        "query_text": query_text,
        "match_reason": match_reason,
        "parsed_industry": parsed_ind,
        "parsed_role": parsed_role,
        "parsed_salary_str": decomp["parsed_salary_str"],
        "parsed_salary_w": sal_w or base_salary_w,
        "salary_delta_pct": salary_delta_pct,
        "three_elements_ok": three_elements_ok,
        "no_city_ok": no_city_ok,
        "no_welfare_ok": no_welfare_ok,
        "single_role_ok": single_role_ok,
        "pii_safe_ok": pii_safe_ok,
        "reason_grounded_ok": reason_grounded_ok,
        "score": score,
        "reason": "；".join(notes),
    }


def run_stage2_dataset_evaluation(
    base_dir: Path = BENCHMARK_DIR,
    model_name: str = DEFAULT_STAGE2_QUERY_MODEL,
    temperature: float = DEFAULT_STAGE2_TEMPERATURE,
    query_count: int = DEFAULT_QUERY_COUNT,
    use_stage1_extracted_profile: bool = True,
    sample_ids_filter: Optional[Set[str]] = None,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """
    对 `qualified_manifest.json` 中的 9 份合格简历样本批量执行 Stage 2 多策略求职 Query 生成与质量评测。
    """
    qual_manifest_path = resolve_safe_path(
        str(base_dir / "dataset" / "qualified_manifest.json"), str(base_dir)
    )
    qual_manifest = json.loads(qual_manifest_path.read_text(encoding="utf-8"))
    qual_samples = qual_manifest.get("samples", [])

    # 加载最新一次 Stage 1 实测提取的 profile（若存在则优先作为 Stage 2 的真实输入）
    stage1_profiles_map: Dict[str, Dict[str, Any]] = {}
    if use_stage1_extracted_profile and LATEST_STAGE1_REPORT_PATH.is_file():
        try:
            s1_data = json.loads(LATEST_STAGE1_REPORT_PATH.read_text(encoding="utf-8"))
            for item in s1_data.get("qualified_details", []):
                sid = item.get("id")
                ext_p = item.get("extracted_profile")
                if sid and isinstance(ext_p, dict) and ext_p:
                    stage1_profiles_map[sid] = ext_p
        except Exception:
            pass

    if sample_ids_filter:
        qual_samples = [s for s in qual_samples if s["id"] in sample_ids_filter]
    if limit is not None and limit > 0:
        qual_samples = qual_samples[:limit]

    sample_results: List[Dict[str, Any]] = []
    strategy_stats: Dict[str, Dict[str, List[float]]] = {
        st: {"scores": [], "salaries_w": [], "deltas_pct": []} for st in STRATEGY_DIMENSIONS
    }
    all_query_scores: List[float] = []
    total_queries_generated = 0
    total_three_elements_passed = 0
    total_no_city_welfare_passed = 0
    total_single_role_passed = 0
    total_pii_safe_passed = 0

    for idx, item in enumerate(qual_samples, 1):
        sid = item["id"]
        fn = item["file_name"]
        ext = item["extension"]
        ind_cat = item.get("industry_category", "")
        raw_pii = item.get("raw_pii_tokens", [])
        gt_profile = item.get("ground_truth", {})
        input_profile = stage1_profiles_map.get(sid) or gt_profile
        profile_source = "stage1_extracted" if sid in stage1_profiles_map else "ground_truth"

        print(f"  [{idx}/{len(qual_samples)}] Running Stage 2 Query Gen on {sid} ({fn}) with {model_name} (temp={temperature})...")
        t0 = time.time()
        gen_out = generate_queries_from_profile_with_gemini(
            profile=input_profile,
            query_count=query_count,
            model_name=model_name,
            temperature=temperature,
        )
        latency_s = round(time.time() - t0, 2)

        effective_profile = gen_out.get("profile") or input_profile
        raw_queries = gen_out.get("recommended_queries") or []
        role_anchors = _infer_boss_role_anchors(effective_profile)
        base_sal_w = parse_salary_w_from_text(str(effective_profile.get("inferred_salary_floor") or "1.0w")) or 1.0

        evaluated_queries: List[Dict[str, Any]] = []
        sample_salaries: List[float] = []
        sample_industries_set: List[str] = []
        sample_roles_set: List[str] = []

        for q_i, q_obj in enumerate(raw_queries):
            q_eval = evaluate_single_query_item(
                idx=q_i,
                item=q_obj,
                profile=effective_profile,
                raw_pii_tokens=raw_pii,
                base_salary_w=base_sal_w,
            )
            evaluated_queries.append(q_eval)
            all_query_scores.append(q_eval["score"])
            total_queries_generated += 1

            if q_eval["three_elements_ok"]:
                total_three_elements_passed += 1
            if q_eval["no_city_ok"] and q_eval["no_welfare_ok"]:
                total_no_city_welfare_passed += 1
            if q_eval["single_role_ok"]:
                total_single_role_passed += 1
            if q_eval["pii_safe_ok"]:
                total_pii_safe_passed += 1

            sal_val = float(q_eval["parsed_salary_w"] or base_sal_w)
            sample_salaries.append(sal_val)
            if q_eval["parsed_industry"] and q_eval["parsed_industry"] not in sample_industries_set:
                sample_industries_set.append(q_eval["parsed_industry"])
            if q_eval["parsed_role"] and q_eval["parsed_role"] not in sample_roles_set:
                sample_roles_set.append(q_eval["parsed_role"])

            st_tag = q_eval["strategy_tag"]
            target_bucket = st_tag if st_tag in strategy_stats else STRATEGY_DIMENSIONS[min(q_i, len(STRATEGY_DIMENSIONS) - 1)]
            strategy_stats[target_bucket]["scores"].append(q_eval["score"])
            strategy_stats[target_bucket]["salaries_w"].append(sal_val)
            strategy_stats[target_bucket]["deltas_pct"].append(q_eval["salary_delta_pct"])

        sample_mean_score = (
            round(sum(q["score"] for q in evaluated_queries) / len(evaluated_queries), 2)
            if evaluated_queries
            else 0.0
        )
        three_elem_rate = (
            round(sum(1 for q in evaluated_queries if q["three_elements_ok"]) / max(1, len(evaluated_queries)), 4)
        )
        pure_format_rate = (
            round(
                sum(1 for q in evaluated_queries if q["no_city_ok"] and q["no_welfare_ok"])
                / max(1, len(evaluated_queries)),
                4,
            )
        )
        pii_ok = all(q["pii_safe_ok"] for q in evaluated_queries)

        min_sal_w = round(min(sample_salaries), 2) if sample_salaries else base_sal_w
        max_sal_w = round(max(sample_salaries), 2) if sample_salaries else base_sal_w
        avg_sal_w = round(sum(sample_salaries) / len(sample_salaries), 2) if sample_salaries else base_sal_w

        print(
            f"      -> Generated {len(evaluated_queries)} queries in {latency_s}s | "
            f"Mean Score: {sample_mean_score}/10 | Salary Range: {min_sal_w}w ~ {max_sal_w}w (Base: {base_sal_w}w)"
        )

        sample_results.append(
            {
                "sample_id": sid,
                "id": sid,
                "file_name": fn,
                "extension": ext,
                "industry_category": ind_cat,
                "profile_source": profile_source,
                "model_used": gen_out.get("model_used", model_name),
                "temperature_used": temperature,
                "latency_s": latency_s,
                "query_count": len(evaluated_queries),
                "overall_score_10": sample_mean_score,
                "three_elements_pass_rate": three_elem_rate,
                "pure_format_pass_rate": pure_format_rate,
                "unique_roles_count": len(sample_roles_set),
                "unique_industries_count": len(sample_industries_set),
                "schema_and_pii_valid": pii_ok,
                "base_salary_w": base_sal_w,
                "min_query_salary_w": min_sal_w,
                "avg_query_salary_w": avg_sal_w,
                "max_query_salary_w": max_sal_w,
                "role_anchors": role_anchors,
                "input_profile": effective_profile,
                "raw_pii_tokens": raw_pii,
                "raw_resume_text": item.get("raw_resume_text", ""),
                "recommended_queries": raw_queries,
                "evaluated_queries": evaluated_queries,
                "atomic_checks": evaluated_queries,
            }
        )

    strategy_breakdown: List[Dict[str, Any]] = []
    per_strategy_scores_map: Dict[str, float] = {}
    for st in STRATEGY_DIMENSIONS:
        sc_list = strategy_stats[st]["scores"]
        sal_list = strategy_stats[st]["salaries_w"]
        dlt_list = strategy_stats[st]["deltas_pct"]
        m_sc = round(sum(sc_list) / len(sc_list), 2) if sc_list else 0.0
        m_sal = round(sum(sal_list) / len(sal_list), 2) if sal_list else 0.0
        m_dlt = round(sum(dlt_list) / len(dlt_list), 1) if dlt_list else 0.0
        per_strategy_scores_map[st] = m_sc
        strategy_breakdown.append(
            {
                "strategy_tag": st,
                "sample_count": len(sc_list),
                "mean_score_10": m_sc,
                "mean_salary_w": m_sal,
                "mean_salary_delta_pct": m_dlt,
            }
        )

    now_dt = datetime.datetime.now()
    ts_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    run_id = f"run_stage2_queries_{now_dt.strftime('%Y%m%d_%H%M%S')}"

    overall_mean_10 = (
        round(sum(all_query_scores) / len(all_query_scores), 2) if all_query_scores else 0.0
    )
    three_elem_overall_rate = round(total_three_elements_passed / max(1, total_queries_generated), 4)
    no_city_welfare_overall_rate = round(total_no_city_welfare_passed / max(1, total_queries_generated), 4)
    single_role_overall_rate = round(total_single_role_passed / max(1, total_queries_generated), 4)
    pii_overall_rate = round(total_pii_safe_passed / max(1, total_queries_generated), 4)
    avg_latency_s = (
        round(sum(s["latency_s"] for s in sample_results) / max(1, len(sample_results)), 2)
        if sample_results
        else 0.0
    )

    report = {
        "run_id": run_id,
        "stage_id": "stage2_queries",
        "created_at": ts_str,
        "evaluation_mode": "stage2_multi_strategy_10_queries",
        "extract_model": model_name,
        "judge_model": "rule_and_profile_grounding_verifier",
        "temperature_used": temperature,
        "target_query_count_per_sample": query_count,
        "qualified_total": len(sample_results),
        "total_queries_generated": total_queries_generated,
        "qualified_mean_score_10": overall_mean_10,
        "three_elements_pass_rate": three_elem_overall_rate,
        "no_city_or_welfare_pass_rate": no_city_welfare_overall_rate,
        "single_role_pass_rate": single_role_overall_rate,
        "pii_safety_pass_rate": pii_overall_rate,
        "mean_latency_s": avg_latency_s,
        "per_strategy_mean_scores_10": per_strategy_scores_map,
        "strategy_breakdown": strategy_breakdown,
        "aggregated_metrics": {
            "qualified_total": len(sample_results),
            "total_queries_generated": total_queries_generated,
            "qualified_mean_score_10": overall_mean_10,
            "three_elements_pass_rate": three_elem_overall_rate,
            "no_city_or_welfare_pass_rate": no_city_welfare_overall_rate,
            "single_role_pass_rate": single_role_overall_rate,
            "pii_safety_pass_rate": pii_overall_rate,
            "mean_latency_s": avg_latency_s,
            "per_strategy_mean_scores_10": per_strategy_scores_map,
            "strategy_breakdown": strategy_breakdown,
        },
        "sample_evaluations": sample_results,
        "qualified_details": sample_results,
    }

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    run_file = resolve_safe_path(str(RUNS_DIR / f"{run_id}.json"), str(RUNS_DIR))
    run_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    LATEST_STAGE2_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    LATEST_STAGE2_REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Stage 2 Query Generation Benchmark on Qualified Dataset")
    parser.add_argument("--model", type=str, default=DEFAULT_STAGE2_QUERY_MODEL)
    parser.add_argument("--temperature", type=float, default=DEFAULT_STAGE2_TEMPERATURE)
    parser.add_argument("--query-count", type=int, default=DEFAULT_QUERY_COUNT)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    report = run_stage2_dataset_evaluation(
        base_dir=BENCHMARK_DIR,
        model_name=args.model,
        temperature=args.temperature,
        query_count=args.query_count,
        limit=args.limit if args.limit > 0 else None,
    )
    print("=" * 78)
    print(f"Stage 2 Evaluation Run ID        : {report['run_id']}")
    print(f"Model / Temperature              : {report['extract_model']} (temp={report['temperature_used']})")
    print(f"Qualified Samples Evaluated      : {report['qualified_total']} samples ({report['total_queries_generated']} total queries)")
    print(f"Overall Mean Quality Score       : {report['qualified_mean_score_10']:.2f} / 10.0")
    print(f"3-Element (Ind+Role+Sal) Rate    : {report['three_elements_pass_rate'] * 100:.1f}%")
    print(f"No-City & No-Welfare Pure Rate   : {report['no_city_or_welfare_pass_rate'] * 100:.1f}%")
    print(f"Single-Role (No Slash) Rate      : {report['single_role_pass_rate'] * 100:.1f}%")
    print(f"PII Zero-Leakage Rate            : {report['pii_safety_pass_rate'] * 100:.1f}%")
    print("=" * 78)


if __name__ == "__main__":
    main()
