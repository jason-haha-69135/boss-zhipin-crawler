#!/usr/bin/env python3
"""
Stage 3 意图解析与 BOSS直聘 URL 生成 — LLM-as-a-Judge 裁判模块
默认使用 gemini-4-argon (temperature=0.0) 对照人工审核通过的 Ground Truth，
从 4 个核心维度（URL 与硬性筛选编码、核心岗位提纯、行业近义词扩展、软性偏好提取）进行 0~10 分评分与诊断。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.gemini_client import create_interaction_with_fallback

DEFAULT_STAGE3_JUDGE_MODEL = "gemini-4-argon"

STAGE3_DIMENSION_KEYS = [
    "url_and_hard_filter_score",
    "role_purification_score",
    "industry_expansion_score",
    "soft_requirements_score",
]

STAGE3_DIMENSION_LABELS: Dict[str, str] = {
    "url_and_hard_filter_score": "URL 与硬性筛选编码",
    "role_purification_score": "核心岗位词提纯",
    "industry_expansion_score": "行业近义词扩展",
    "soft_requirements_score": "软性偏好与底薪提取",
}


class Stage3JudgeSchema(BaseModel):
    """Argon LLM-as-a-Judge 评分结构"""

    url_and_hard_filter_score: float = Field(
        ge=0.0,
        le=10.0,
        description="BOSS直聘拼接 URL 及硬性筛选编码（city/salary/experience/degree/scale/stage）与 Ground Truth 的一致度与合法性（0~10分）",
    )
    role_purification_score: float = Field(
        ge=0.0,
        le=10.0,
        description="核心岗位词 query 的提纯质量（是否纯净单一岗位、无城市/行业/岗位字样/月薪/斜杠污染、兼顾召回与精准，0~10分）",
    )
    industry_expansion_score: float = Field(
        ge=0.0,
        le=10.0,
        description="industry_keywords 行业及近义词扩展的准确度与覆盖率（供 Stage 4 语义过滤使用，0~10分）",
    )
    soft_requirements_score: float = Field(
        ge=0.0,
        le=10.0,
        description="min_salary_k、require_double_weekend 及 soft_requirements 的提取准确性（0~10分）",
    )
    overall_score_10: float = Field(
        ge=0.0,
        le=10.0,
        description="综合得分（0~10分），参考权重：URL硬筛35% + 岗位提纯30% + 行业扩展25% + 软条件10%",
    )
    diagnosis_comment: str = Field(
        description="1~2句简明中文裁判评语，指出 BOSS直聘 URL 是否完全一致或具体差异点"
    )


def evaluate_stage3_intent_with_llm_judge(
    *,
    input_query: str,
    input_target_city: str,
    ground_truth: Dict[str, Any],
    actual_intent: Dict[str, Any],
    actual_boss_url: str,
    deterministic_checks: Dict[str, Any],
    judge_model: str = DEFAULT_STAGE3_JUDGE_MODEL,
    api_key: Optional[str] = None,
    proxy_url: Optional[str] = None,
) -> Dict[str, Any]:
    """调用 gemini-4-argon (temperature=0.0) 对单条 Stage 3 意图解析与 URL 拼接结果打分。"""
    prompt = (
        "你是 BOSS直聘 智能求职系统的 Stage 3 评测裁判官（LLM-as-a-Judge）。\n"
        "请严格对照【人工审核通过的 Ground Truth】，评估待测模型（Stage 3）的实际解析结果与拼接出的 BOSS直聘 URL。\n\n"
        f"【用户输入 Query】：{input_query}\n"
        f"【传入意向城市 target_city】：{input_target_city}\n\n"
        "【Ground Truth（黄金真值）】：\n"
        f"- expected_boss_url: {ground_truth.get('expected_boss_url', '')}\n"
        f"- expected_query: {ground_truth.get('expected_query', '')}\n"
        f"- expected_city: {ground_truth.get('expected_city_name', '')} ({ground_truth.get('expected_city_code', '')})\n"
        f"- expected_salary: {ground_truth.get('expected_min_salary_k', 0)}K / code='{ground_truth.get('expected_salary_code', '')}'\n"
        f"- expected_industry_keywords: {json.dumps(ground_truth.get('expected_industry_keywords', []), ensure_ascii=False)}\n"
        f"- expected_extra_codes: exp='{ground_truth.get('expected_experience_code', '')}', "
        f"deg='{ground_truth.get('expected_degree_code', '')}', "
        f"scale='{ground_truth.get('expected_scale_code', '')}', "
        f"stage='{ground_truth.get('expected_stage_code', '')}'\n\n"
        "【待测 Stage 3 实际输出（gemini-3.8-flash）】：\n"
        f"- actual_boss_url: {actual_boss_url}\n"
        f"- actual_query: {actual_intent.get('query', '')}\n"
        f"- actual_city: {actual_intent.get('city_name', '')} ({actual_intent.get('city_code', '')})\n"
        f"- actual_salary: {actual_intent.get('min_salary_k', 0)}K / code='{actual_intent.get('salary_code', '')}'\n"
        f"- actual_industry_keywords: {json.dumps(actual_intent.get('industry_keywords', []), ensure_ascii=False)}\n"
        f"- actual_extra_codes: exp='{actual_intent.get('experience_code', '')}', "
        f"deg='{actual_intent.get('degree_code', '')}', "
        f"scale='{actual_intent.get('scale_code', '')}', "
        f"stage='{actual_intent.get('stage_code', '')}'\n"
        f"- actual_soft_requirements: {json.dumps(actual_intent.get('soft_requirements', []), ensure_ascii=False)}\n\n"
        f"【程序硬校验结果】：{json.dumps(deterministic_checks, ensure_ascii=False)}\n\n"
        "【严格评分标准（0~10分，精确到小数点后1位）】：\n"
        "1. `url_and_hard_filter_score`：若 `actual_boss_url` 与 `expected_boss_url` 参数完全一致且无幻觉编码，给 9.5~10.0 分；"
        "若仅 `query` 有合理近义微调但 city/salary/extra 完全正确，给 8.5~9.4 分；若 city 或 salary 编码错误或出现幻觉过滤码，必须 <= 5.0 分。\n"
        "2. `role_purification_score`：`query` 与 Ground Truth 完全一致且纯净给 9.5~10.0 分；若仅保留如 'BD' 这类行业常用缩写给 8.5~9.4 分；"
        "若残留城市/行业/'岗位'/薪资/斜杠，必须 <= 5.0 分。\n"
        "3. `industry_expansion_score`：评估 `actual_industry_keywords` 对目标行业及其近义词的语义覆盖与精准度，无无关漂移词。\n"
        "4. `soft_requirements_score`：评估 `min_salary_k`、`require_double_weekend` 与 `soft_requirements` 是否完整准确。\n"
        "5. `overall_score_10` 严格按 `0.35*url_and_hard_filter + 0.30*role_purification + 0.25*industry_expansion + 0.10*soft_requirements` 计算并保留 2 位小数。\n"
    )

    raw_json = create_interaction_with_fallback(
        model=judge_model,
        prompt=prompt,
        schema_cls=Stage3JudgeSchema,
        temperature=0.0,
        api_key=api_key,
        proxy_url=proxy_url,
    )
    judged = Stage3JudgeSchema.model_validate_json(raw_json)
    computed_overall = round(
        0.35 * judged.url_and_hard_filter_score
        + 0.30 * judged.role_purification_score
        + 0.25 * judged.industry_expansion_score
        + 0.10 * judged.soft_requirements_score,
        2,
    )
    data = judged.model_dump()
    data["overall_score_10"] = computed_overall
    return data
