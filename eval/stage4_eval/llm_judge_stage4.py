#!/usr/bin/env python3
"""
Stage 4 离线岗位过滤与 Top-K 粗排 — LLM-as-a-Judge 裁判模块
默认使用 gemini-4-argon (temperature=0.0) 对照人工批准的 Ground Truth，
从 4 个核心维度（Top-K 相关性质量、排序阶梯合理性、异地/低薪降权纯净度、打分可解释性）进行 0~10 分评审。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.gemini_client import create_interaction_with_fallback

DEFAULT_STAGE4_JUDGE_MODEL = "gemini-4-argon"

STAGE4_DIMENSION_KEYS = [
    "top_k_relevance_score",
    "ranking_order_score",
    "demotion_cleanliness_score",
    "explainability_score",
]

STAGE4_DIMENSION_LABELS: Dict[str, str] = {
    "top_k_relevance_score": "Top-8 候选相关性",
    "ranking_order_score": "排序阶梯与 NDCG",
    "demotion_cleanliness_score": "异地/低薪/作息拦截纯净度",
    "explainability_score": "分项打分可解释性",
}


class Stage4JudgeSchema(BaseModel):
    """Argon Stage 4 LLM-as-a-Judge 评分结构"""

    top_k_relevance_score: float = Field(
        ge=0.0,
        le=10.0,
        description="Top-8 候选岗位对目标意图（岗位/行业/薪资/城市/技能）的整体相关性质量（0~10分）",
    )
    ranking_order_score: float = Field(
        ge=0.0,
        le=10.0,
        description="排序先后顺序是否合理（Grade 3 靠前、Grade 2 次之、无高分噪音倒挂，0~10分）",
    )
    demotion_cleanliness_score: float = Field(
        ge=0.0,
        le=10.0,
        description="异地、低薪、单双休/隔周双休文字陷阱是否被准确降权且未污染 Top-8（0~10分）",
    )
    explainability_score: float = Field(
        ge=0.0,
        le=10.0,
        description="score_breakdown 分项得分与 demotion_reasons 是否清晰可解释、无逻辑矛盾（0~10分）",
    )
    overall_score_10: float = Field(
        ge=0.0,
        le=10.0,
        description="综合得分（0~10分），权重：Top-K相关性35% + 排序阶梯30% + 拦截纯净度25% + 可解释性10%",
    )
    diagnosis_comment: str = Field(
        description="1~2句简明中文裁判评语，概括 Top-8 质量、降权表现或潜在改进点"
    )


def evaluate_stage4_ranking_with_llm_judge(
    *,
    scenario_id: str,
    intent: Dict[str, Any],
    top_candidates: List[Dict[str, Any]],
    demoted_jobs: List[Dict[str, Any]],
    deterministic_metrics: Dict[str, Any],
    judge_model: str = DEFAULT_STAGE4_JUDGE_MODEL,
    api_key: Optional[str] = None,
    proxy_url: Optional[str] = None,
) -> Dict[str, Any]:
    """调用 gemini-4-argon (temperature=0.0) 对单个场景的 Stage 4 Top-8 排序与降权结果评分。"""
    top_preview = [
        {
            "rank": idx + 1,
            "job_id": j.get("job_id"),
            "岗位名称": j.get("岗位名称"),
            "薪资范围": j.get("薪资范围"),
            "工作地点": j.get("工作地点"),
            "所属行业": j.get("所属行业"),
            "作息制度": j.get("作息制度"),
            "初筛得分": j.get("初筛得分"),
            "is_demoted": j.get("is_demoted"),
            "ground_truth_grade": j.get("ground_truth_grade"),
            "trap_type": j.get("trap_type"),
            "score_breakdown": j.get("score_breakdown"),
        }
        for idx, j in enumerate(top_candidates)
    ]
    demoted_preview = [
        {
            "job_id": j.get("job_id"),
            "岗位名称": j.get("岗位名称"),
            "薪资范围": j.get("薪资范围"),
            "工作地点": j.get("工作地点"),
            "trap_type": j.get("trap_type"),
            "demotion_reasons": j.get("demotion_reasons"),
            "初筛得分": j.get("初筛得分"),
        }
        for j in demoted_jobs
    ]

    prompt = (
        "你是 BOSS直聘 智能求职系统的 Stage 4 岗位粗排与过滤评测裁判官（LLM-as-a-Judge）。\n"
        "请根据候选人求职意图、确定性 IR 指标（NDCG@8 / Recall@8 / 降权纯净度）与 Top-8 实际排序明细，客观打分。\n\n"
        f"【场景 ID】：{scenario_id}\n"
        f"【求职意图 Intent】：{json.dumps(intent, ensure_ascii=False)}\n"
        f"【确定性 IR 指标】：{json.dumps(deterministic_metrics, ensure_ascii=False)}\n\n"
        f"【Stage 4 输出的 Top-8 候选岗位】：\n{json.dumps(top_preview, ensure_ascii=False, indent=2)}\n\n"
        f"【被保留在底部并降权的岗位】：\n{json.dumps(demoted_preview, ensure_ascii=False, indent=2)}\n\n"
        "【评分准则（0~10分，精确到小数点后1位）】：\n"
        "1. `top_k_relevance_score`：若 Top-8 中全部或绝大多数为 Grade 3/2 岗位、Recall@8 >= 0.85，给 9.0~10.0 分；每混入 1 条无关噪音或 Grade 1 适当扣分。\n"
        "2. `ranking_order_score`：结合 NDCG@8 判断 Grade 3 是否稳居头部、Grade 2 紧随其后。\n"
        "3. `demotion_cleanliness_score`：若异地/低薪岗位 100% 被标记 `is_demoted=True` 且零混入 Top-8，且单双休/隔周双休未被误判为周末双休，给 9.5~10.0 分。\n"
        "4. `explainability_score`：`score_breakdown` 与 `demotion_reasons` 清晰可追溯，无矛盾。\n"
    )

    raw_json = create_interaction_with_fallback(
        model=judge_model,
        prompt=prompt,
        schema_cls=Stage4JudgeSchema,
        temperature=0.0,
        api_key=api_key,
        proxy_url=proxy_url,
    )
    judged = Stage4JudgeSchema.model_validate_json(raw_json)
    computed_overall = round(
        0.35 * judged.top_k_relevance_score
        + 0.30 * judged.ranking_order_score
        + 0.25 * judged.demotion_cleanliness_score
        + 0.10 * judged.explainability_score,
        2,
    )
    data = judged.model_dump()
    data["overall_score_10"] = computed_overall
    return data
