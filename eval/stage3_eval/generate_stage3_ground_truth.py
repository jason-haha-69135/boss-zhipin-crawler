#!/usr/bin/env python3
"""
Stage 3 Ground Truth 生成器（Human-in-the-Loop 人工审核前置脚本）
复用 Stage 1 & Stage 2 评测集（QUAL-01 ~ QUAL-09）及 latest_stage2_eval_report.json，
调用 gemini-4-argon (temperature=0.0) 生成 Stage 3 结构化意图 Ground Truth 草案，
输出至 eval/dataset/stage3/stage3_intent_manifest.json 供人工 Manual Review。
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.gemini_client import create_interaction_with_fallback, load_backend_api_key
from core.intent_parser import (
    CITY_CODE_MAP,
    DEGREE_CODE_LABELS,
    EXPERIENCE_CODE_LABELS,
    ParsedSearchIntent,
    SALARY_CODE_LABELS,
    SCALE_CODE_LABELS,
    STAGE_CODE_LABELS,
    resolve_intent_city,
)

DEFAULT_STAGE2_REPORT = BASE_DIR / "eval" / "runs" / "latest_stage2_eval_report.json"
DEFAULT_OUTPUT_MANIFEST = BASE_DIR / "eval" / "dataset" / "stage3" / "stage3_intent_manifest.json"
DEFAULT_ARGON_MODEL = "gemini-4-argon"
TARGET_STRATEGIES = ("精准对口", "高薪突破")


class Stage3GroundTruthSchema(BaseModel):
    """Argon 模型生成的 Stage 3 单条样本 Ground Truth 草案结构"""

    expected_query: str = Field(
        description="纯净的核心岗位名称（仅岗位角色本身，绝不含城市、'行业'、'岗位'、'月薪'、'双休'或'/'）"
    )
    expected_city_name: str = Field(description="BOSS直聘官方标准城市名")
    expected_city_code: str = Field(description="BOSS直聘官方城市编码（1:1映射）")
    expected_salary_code: str = Field(
        description="BOSS直聘官方薪资编码：''/'402'/'403'/'404'/'405'/'406'/'407'"
    )
    expected_min_salary_k: int = Field(description="最低月薪整数（单位K，如 0.7w->7, 1.2w->12, 2.5w->25）")
    expected_experience_code: str = Field(default="", description="经验编码，未显式提及则填''")
    expected_degree_code: str = Field(default="", description="学历编码，未显式提及则填''")
    expected_scale_code: str = Field(default="", description="公司规模编码，未显式提及则填''")
    expected_stage_code: str = Field(default="", description="融资阶段编码，未显式提及则填''")
    expected_industry_keywords: List[str] = Field(
        description="3-8个高相关行业及近义词关键词，用于 Stage 4 语义过滤"
    )
    expected_require_double_weekend: bool = Field(
        default=False, description="是否显式要求双休"
    )
    expected_soft_requirements: List[str] = Field(
        default_factory=list, description="软性偏好要求列表（如行业偏好、最低月薪等）"
    )
    rationale: str = Field(description="简明标注依据（1句话，供人工 Review 核验）")


def _select_stage2_queries(sample_eval: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从单份简历的 10 条 Stage 2 Query 中精选代表性策略（默认：精准对口 + 高薪突破）。"""
    queries = sample_eval.get("generated_queries") or []
    selected: List[Dict[str, Any]] = []
    used_indices = set()

    for tag in TARGET_STRATEGIES:
        for idx, q in enumerate(queries):
            if idx not in used_indices and (q.get("strategy_tag") or "").strip() == tag:
                selected.append(q)
                used_indices.add(idx)
                break

    # 若不足 2 条则按顺序补齐
    for idx, q in enumerate(queries):
        if len(selected) >= 2:
            break
        if idx not in used_indices:
            selected.append(q)
            used_indices.add(idx)

    return selected


def _generate_single_ground_truth(
    item: Dict[str, Any],
    model_name: str,
    api_key: Optional[str],
) -> Dict[str, Any]:
    """调用 gemini-4-argon 为单条 Stage 3 评测样本生成 Ground Truth 草案。"""
    t0 = time.perf_counter()
    query_text = item["input_query"]
    target_city = item["input_target_city"]
    resume_profile = item["input_resume_profile"]

    det_city_name, det_city_code = resolve_intent_city(
        query_text, target_city=target_city, resume_profile=resume_profile
    )

    prompt = (
        "你是 BOSS直聘 智能求职系统的评测基准标注专家（Ground Truth Annotator）。\n"
        "请为以下 Stage 3 意图解析输入生成最严格、最标准的黄金真值（Ground Truth）。\n\n"
        f"【输入 Query（来自 Stage 2）】：{query_text}\n"
        f"【显式传入 target_city】：{target_city}\n"
        f"【确定性 BOSS 城市映射】：{det_city_name} ({det_city_code})\n"
        f"【候选人简历行业背景】：{json.dumps(resume_profile.get('industry_background', []), ensure_ascii=False)}\n"
        f"【候选人目标岗位锚点】：{resume_profile.get('candidate_title', '')}\n\n"
        "【官方白名单编码规范】：\n"
        f"- 薪资编码 SALARY_CODE_LABELS: {json.dumps(SALARY_CODE_LABELS, ensure_ascii=False)}\n"
        "  （换算规则：3K以下->'402', 3~4K->'403', 5~9K->'404', 10~19K->'405', 20~49K->'406', >=50K->'407'）\n"
        f"- 经验编码 EXPERIENCE_CODE_LABELS: {json.dumps(EXPERIENCE_CODE_LABELS, ensure_ascii=False)}\n"
        f"- 学历编码 DEGREE_CODE_LABELS: {json.dumps(DEGREE_CODE_LABELS, ensure_ascii=False)}\n"
        f"- 规模编码 SCALE_CODE_LABELS: {json.dumps(SCALE_CODE_LABELS, ensure_ascii=False)}\n"
        f"- 融资编码 STAGE_CODE_LABELS: {json.dumps(STAGE_CODE_LABELS, ensure_ascii=False)}\n\n"
        "【硬性标注准则】：\n"
        "1. `expected_query` 必须提取最纯净的单一核心岗位名（去除行业定语、城市名、'岗位'/'职位'、薪资与斜杠`/`），"
        "确保在 BOSS直聘 搜索框中拥有高召回率与精准度。\n"
        "2. `expected_city_name` 和 `expected_city_code` 必须严格等于上述确定性 BOSS 城市映射。\n"
        "3. `expected_min_salary_k` 为整数 K（如 `0.7w` -> `7`, `1.2w` -> `12`），`expected_salary_code` 必须与该档位严格对应。\n"
        "4. 若输入 Query 未显式提及经验/学历/规模/融资要求，则对应 code 必须严格留空 `''`。\n"
        "5. `expected_industry_keywords` 输出 3~6 个核心行业及近义词，供 Stage 4 语义过滤使用。\n"
    )

    raw_json = create_interaction_with_fallback(
        model=model_name,
        prompt=prompt,
        schema_cls=Stage3GroundTruthSchema,
        temperature=0.0,
        api_key=api_key,
    )
    gt = Stage3GroundTruthSchema.model_validate_json(raw_json)

    # 强制白名单与确定性城市校准，防止任何非法编码混入 Ground Truth
    city_name, city_code = det_city_name, det_city_code
    salary_code = gt.expected_salary_code if gt.expected_salary_code in SALARY_CODE_LABELS else ""
    exp_code = gt.expected_experience_code if gt.expected_experience_code in EXPERIENCE_CODE_LABELS else ""
    deg_code = gt.expected_degree_code if gt.expected_degree_code in DEGREE_CODE_LABELS else ""
    scale_code = gt.expected_scale_code if gt.expected_scale_code in SCALE_CODE_LABELS else ""
    stage_code = gt.expected_stage_code if gt.expected_stage_code in STAGE_CODE_LABELS else ""

    intent_preview = ParsedSearchIntent(
        raw_query=query_text,
        query=gt.expected_query.strip(),
        city_name=city_name,
        city_code=city_code,
        salary_code=salary_code,
        salary_label=SALARY_CODE_LABELS.get(salary_code, "不限"),
        experience_code=exp_code,
        experience_label=EXPERIENCE_CODE_LABELS.get(exp_code, "不限"),
        degree_code=deg_code,
        degree_label=DEGREE_CODE_LABELS.get(deg_code, "不限"),
        scale_code=scale_code,
        scale_label=SCALE_CODE_LABELS.get(scale_code, "不限"),
        stage_code=stage_code,
        stage_label=STAGE_CODE_LABELS.get(stage_code, "不限"),
        min_salary_k=gt.expected_min_salary_k,
        industry_keywords=gt.expected_industry_keywords,
        require_double_weekend=gt.expected_require_double_weekend,
        soft_requirements=gt.expected_soft_requirements,
    )

    return {
        "case_id": item["case_id"],
        "source_sample_id": item["source_sample_id"],
        "industry_category": item["industry_category"],
        "strategy_tag": item["strategy_tag"],
        "input": {
            "query_text": query_text,
            "target_city": target_city,
            "target_city_code": CITY_CODE_MAP.get(target_city, city_code),
            "resume_profile": resume_profile,
        },
        "ground_truth": {
            "expected_query": gt.expected_query.strip(),
            "expected_city_name": city_name,
            "expected_city_code": city_code,
            "expected_salary_code": salary_code,
            "expected_salary_label": SALARY_CODE_LABELS.get(salary_code, "不限"),
            "expected_min_salary_k": gt.expected_min_salary_k,
            "expected_experience_code": exp_code,
            "expected_degree_code": deg_code,
            "expected_scale_code": scale_code,
            "expected_stage_code": stage_code,
            "expected_industry_keywords": gt.expected_industry_keywords,
            "expected_require_double_weekend": gt.expected_require_double_weekend,
            "expected_soft_requirements": gt.expected_soft_requirements,
            "expected_boss_url": intent_preview.build_boss_url(),
            "rationale": gt.rationale.strip(),
        },
        "generation_latency_s": round(time.perf_counter() - t0, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="使用 gemini-4-argon 生成 Stage 3 Ground Truth 草案")
    parser.add_argument("--stage2-report", type=Path, default=DEFAULT_STAGE2_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_MANIFEST)
    parser.add_argument("--model", type=str, default=DEFAULT_ARGON_MODEL)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    if not args.stage2_report.is_file():
        raise FileNotFoundError(f"找不到 Stage 2 评测报告: {args.stage2_report}")

    stage2_data = json.loads(args.stage2_report.read_text(encoding="utf-8"))
    sample_evals = stage2_data.get("sample_evaluations") or []
    if not sample_evals:
        raise ValueError("Stage 2 评测报告中未包含 sample_evaluations")

    tasks: List[Dict[str, Any]] = []
    suffixes = ["A", "B", "C", "D"]
    for sample in sample_evals:
        sid = sample.get("sample_id") or sample.get("id") or "UNKNOWN"
        profile = sample.get("input_profile") or {}
        selected_queries = _select_stage2_queries(sample)
        for idx, q in enumerate(selected_queries):
            tasks.append(
                {
                    "order": len(tasks),
                    "case_id": f"S3-{sid}-{suffixes[idx]}",
                    "source_sample_id": sid,
                    "industry_category": sample.get("industry_category", ""),
                    "strategy_tag": q.get("strategy_tag", ""),
                    "input_query": q.get("query_text", ""),
                    "input_target_city": q.get("target_city") or profile.get("target_city") or "深圳",
                    "input_resume_profile": profile,
                }
            )

    api_key = load_backend_api_key()
    print(f"[Stage3-GT] 正在调用 {args.model} (temperature=0.0) 为 {len(tasks)} 条样本生成 Ground Truth 草案...")

    results_by_order: Dict[int, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        future_map = {
            pool.submit(_generate_single_ground_truth, t, args.model, api_key): t
            for t in tasks
        }
        for future in as_completed(future_map):
            t = future_map[future]
            res = future.result()
            results_by_order[t["order"]] = res
            gt = res["ground_truth"]
            print(
                f"  ✓ {res['case_id']} | query='{gt['expected_query']}' | "
                f"city={gt['expected_city_name']}({gt['expected_city_code']}) | "
                f"salary={gt['expected_min_salary_k']}K({gt['expected_salary_code']}) | "
                f"kw={gt['expected_industry_keywords'][:4]} ({res['generation_latency_s']}s)"
            )

    ordered_samples = [results_by_order[i] for i in range(len(tasks))]
    manifest = {
        "schema_version": "stage3_intent_ground_truth_v1",
        "review_status": "PENDING_MANUAL_REVIEW",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "generator_model": args.model,
        "temperature": 0.0,
        "source_stage2_run_id": stage2_data.get("run_id", ""),
        "total_cases": len(ordered_samples),
        "samples": ordered_samples,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[Stage3-GT] 已保存 Ground Truth 草案至: {args.output}")
    print("[Stage3-GT] 请完成人工 Manual Review 后，再运行 Stage 3 Eval！")


if __name__ == "__main__":
    main()
