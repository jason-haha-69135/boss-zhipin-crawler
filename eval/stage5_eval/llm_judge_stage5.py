#!/usr/bin/env python3
"""
Stage 5 六维分析与人岗匹配评估 — LLM-as-a-Judge 裁判与锚点生成模块
默认使用 gemini-4-argon (temperature=0.0)：
1. 为 6 组跨行业场景自动生成 Stage 5 事实锚点 (Ground Truth Anchors)；
2. 对 gemini-3.8-flash 生成的六维洞察与 Top-8 人岗匹配报告进行四维评审 (0~10分)。
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

DEFAULT_STAGE5_JUDGE_MODEL = "gemini-4-argon"

STAGE5_DIMENSION_KEYS = [
    "jd_groundedness_score",
    "profile_alignment_score",
    "risk_identification_score",
    "advice_actionability_score",
]

STAGE5_DIMENSION_LABELS: Dict[str, str] = {
    "jd_groundedness_score": "JD与统计事实忠实度",
    "profile_alignment_score": "人岗简历契合诊断",
    "risk_identification_score": "风险与作息陷阱识别",
    "advice_actionability_score": "求职建议可执行性",
}


class Stage5GroundTruthAnchorSchema(BaseModel):
    """Argon 为单个场景自动生成的 Stage 5 事实与分析基准锚点"""

    expected_score_min: int = Field(ge=0, le=100, description="合理的整体匹配分下限 (0~100)")
    expected_score_max: int = Field(ge=0, le=100, description="合理的整体匹配分上限 (0~100)")
    must_cite_facts: List[str] = Field(
        description="3-5 条必须忠实于 Python 统计数据的关键事实锚点（如平均薪资、中位数、头部公司、双休占比）"
    )
    key_profile_matches: List[str] = Field(
        description="2-4 条候选人简历技能/行业与 Top-8 岗位的核心契合点"
    )
    must_flag_risks: List[str] = Field(
        description="2-3 条必须识别出的真实风险点（如单双休/隔周双休岗、临界薪资、跨行业门槛等）"
    )


class Stage5JudgeSchema(BaseModel):
    """Argon Stage 5 LLM-as-a-Judge 评分结构"""

    jd_groundedness_score: float = Field(
        ge=0.0,
        le=10.0,
        description="统计数字、企业名称、薪资与作息描述是否严格忠实于输入 stats 与 Top-8 JD，无捏造幻觉（0~10分）",
    )
    profile_alignment_score: float = Field(
        ge=0.0,
        le=10.0,
        description="整体匹配评估与 Top-8 逐岗点评是否深度结合了候选人真实简历技能与背景，而非泛泛而谈（0~10分）",
    )
    risk_identification_score: float = Field(
        ge=0.0,
        le=10.0,
        description="是否准确识别出真实风险（如单双休/隔周双休、薪资下限落差、技能缺口）并在风险岗扣分（0~10分）",
    )
    advice_actionability_score: float = Field(
        ge=0.0,
        le=10.0,
        description="求职与面试沟通建议是否紧扣目标岗位与真实数据、具备直接可落地价值，无模板废话（0~10分）",
    )
    overall_score_10: float = Field(
        ge=0.0,
        le=10.0,
        description="综合得分（0~10分），权重：事实忠实度35% + 人岗契合25% + 风险识别20% + 建议可执行性20%",
    )
    diagnosis_comment: str = Field(
        description="1~2句简明中文裁判评语，概括报告事实准确度、人岗诊断深度与潜在改进点"
    )


def generate_stage5_ground_truth_anchor(
    *,
    scenario_id: str,
    intent: Dict[str, Any],
    stats: Dict[str, Any],
    top_candidates: List[Dict[str, Any]],
    resume_profile: Dict[str, Any],
    model_name: str = DEFAULT_STAGE5_JUDGE_MODEL,
    api_key: Optional[str] = None,
    proxy_url: Optional[str] = None,
) -> Dict[str, Any]:
    """调用 gemini-4-argon (temperature=0.0) 为单个场景生成 Stage 5 评测基准锚点。"""
    top_brief = [
        {
            "job_name": j.get("岗位名称"),
            "company": j.get("公司名称"),
            "salary": j.get("薪资范围"),
            "industry": j.get("所属行业"),
            "weekend": j.get("作息制度"),
            "skills": j.get("技能标签"),
        }
        for j in top_candidates
    ]
    prompt = (
        "你是 BOSS直聘 智能求职系统的 Stage 5 评测基准标注专家。\n"
        "请基于以下真实的合规池六维统计、Top-8 候选岗位和候选人简历画像，提炼出 Stage 5 深度分析报告的黄金事实锚点。\n\n"
        f"【场景 ID】：{scenario_id}\n"
        f"【求职意图】：{json.dumps(intent, ensure_ascii=False)}\n"
        f"【候选人简历画像】：{json.dumps(resume_profile, ensure_ascii=False)}\n"
        f"【合规池六维统计 stats】：{json.dumps(stats, ensure_ascii=False)}\n"
        f"【Top-8 候选岗位摘要】：{json.dumps(top_brief, ensure_ascii=False)}\n"
    )
    raw_json = create_interaction_with_fallback(
        model=model_name,
        prompt=prompt,
        schema_cls=Stage5GroundTruthAnchorSchema,
        temperature=0.0,
        api_key=api_key,
        proxy_url=proxy_url,
    )
    return Stage5GroundTruthAnchorSchema.model_validate_json(raw_json).model_dump()


def evaluate_stage5_analysis_with_llm_judge(
    *,
    scenario_id: str,
    intent: Dict[str, Any],
    stats: Dict[str, Any],
    top_candidates: List[Dict[str, Any]],
    resume_profile: Dict[str, Any],
    ground_truth_anchor: Dict[str, Any],
    actual_report: Dict[str, Any],
    deterministic_checks: Dict[str, Any],
    judge_model: str = DEFAULT_STAGE5_JUDGE_MODEL,
    api_key: Optional[str] = None,
    proxy_url: Optional[str] = None,
) -> Dict[str, Any]:
    """调用 gemini-4-argon (temperature=0.0) 评审 gemini-3.8-flash 生成的 Stage 5 报告。"""
    dims = actual_report.get("dimensions") or {}
    report_summary = {
        "executive_summary": actual_report.get("executive_summary", ""),
        "dimension_insights": {
            k: (dims.get(k) or {}).get("insight", "")
            for k in ("industry", "salary", "skills", "experience", "brand", "welfare")
        },
        "match_evaluation": actual_report.get("match_evaluation", {}),
        "recommended_jobs": [
            {
                "rank": j.get("rank"),
                "job_name": j.get("job_name"),
                "company_name": j.get("company_name"),
                "salary_desc": j.get("salary_desc"),
                "weekend_policy": j.get("weekend_policy"),
                "match_score": j.get("match_score"),
                "match_reason": j.get("match_reason"),
                "highlights": j.get("highlights"),
                "risks": j.get("risks"),
            }
            for j in (actual_report.get("recommended_jobs") or [])
        ],
    }

    prompt = (
        "你是 BOSS直聘 智能求职系统的 Stage 5 深度分析评测裁判官（LLM-as-a-Judge）。\n"
        "请严格核对待测模型（gemini-3.8-flash）生成的六维洞察与 Top-8 人岗匹配报告，是否忠实于真实统计数据与 JD、是否深度结合简历画像且零幻觉。\n\n"
        f"【场景 ID】：{scenario_id}\n"
        f"【求职意图】：{json.dumps(intent, ensure_ascii=False)}\n"
        f"【候选人简历画像】：{json.dumps(resume_profile, ensure_ascii=False)}\n"
        f"【合规池真实统计 stats】：{json.dumps(stats, ensure_ascii=False)}\n"
        f"【Argon 基准事实锚点 Ground Truth】：{json.dumps(ground_truth_anchor, ensure_ascii=False)}\n"
        f"【程序硬门禁校验结果】：{json.dumps(deterministic_checks, ensure_ascii=False)}\n\n"
        f"【待测 Stage 5 报告 (gemini-3.8-flash)】：\n{json.dumps(report_summary, ensure_ascii=False, indent=2)}\n\n"
        "【严格评分标准（0~10分，精确到小数点后1位）】：\n"
        "1. `jd_groundedness_score`：引用的薪资/比例/企业名/作息是否完全来自真实 stats 和 Top-8 JD，无编造数字或无关行业套话。\n"
        "2. `profile_alignment_score`：整体诊断和 Top-8 逐岗 `match_reason` 是否具体关联候选人真实技能/背景。\n"
        "3. `risk_identification_score`：是否准确抓出基准锚点中的真实风险（如非双休、薪资下限、行业偏差）并在风险岗合理降分。\n"
        "4. `advice_actionability_score`：建议是否具体可执行、针对当前目标岗位量身定制。\n"
    )

    raw_json = create_interaction_with_fallback(
        model=judge_model,
        prompt=prompt,
        schema_cls=Stage5JudgeSchema,
        temperature=0.0,
        api_key=api_key,
        proxy_url=proxy_url,
    )
    judged = Stage5JudgeSchema.model_validate_json(raw_json)
    computed_overall = round(
        0.35 * judged.jd_groundedness_score
        + 0.25 * judged.profile_alignment_score
        + 0.20 * judged.risk_identification_score
        + 0.20 * judged.advice_actionability_score,
        2,
    )
    data = judged.model_dump()
    data["overall_score_10"] = computed_overall
    return data
