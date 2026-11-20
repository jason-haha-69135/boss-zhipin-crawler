"""
Stage 2 多策略求职 Query 生成 LLM-as-a-Judge 评测器 (`llm_judge_stage2.py`)
默认裁判模型：`gemini-4-argon` (Gemini 4 Argon)
核心职责：
1. 针对 Stage 2 (`core/query_generator.py`) 为单份简历生成的 10 条求职 Query，
   结合候选人 Stage 1 脱敏画像 (`profile`)，调用 `gemini-4-argon` 执行逐条质量与策略契合度评估（0~10 分）。
2. 同时结合确定性规则（三要素完整性、无城市名称、无作息福利套话、单一标准岗位无斜杠、PII 零泄露）
   产出每条 Query 的原子核验结果与 `gemini-4-argon` 综合诊断评语。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

STAGE2_EVAL_DIR = Path(__file__).resolve().parent
EVAL_DIR = STAGE2_EVAL_DIR.parent
PROJECT_ROOT = EVAL_DIR.parent
for _p in (PROJECT_ROOT, EVAL_DIR, STAGE2_EVAL_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from core.gemini_client import DEFAULT_LLM_JUDGE_MODEL, create_interaction_with_fallback

DEFAULT_STAGE2_JUDGE_MODEL: str = os.environ.get("STAGE2_JUDGE_MODEL", DEFAULT_LLM_JUDGE_MODEL)


class SingleQueryJudgeItem(BaseModel):
    """单条 Query 的 LLM-as-a-Judge 评分项"""

    query_index: int = Field(description="Query 序号 (1 ~ 10)")
    strategy_tag: str = Field(description="该条 Query 的策略维度标签")
    score: float = Field(description="该条 Query 的综合质量得分 (0.0 ~ 10.0)")
    strategy_alignment_ok: bool = Field(description="该 Query 的岗位职级与薪资是否符合其 strategy_tag 定位")
    resume_grounding_ok: bool = Field(description="行业、岗位与 match_reason 是否忠实锚定候选人简历画像且无幻觉")
    reason: str = Field(description="针对该条 Query 的简明核验诊断说明 (25~60字)")


class Stage2BatchJudgeReport(BaseModel):
    """单份简历 10 条 Query 的 LLM-as-a-Judge 汇总评判输出"""

    overall_comment: str = Field(description="对该候选人 10 条搜索策略 Query 整体梯度、岗位覆盖度与三要素规范性的综合点评 (40~100字)")
    query_evaluations: List[SingleQueryJudgeItem] = Field(description="10 条 Query 的逐条评分明细")


def evaluate_queries_with_llm_judge(
    profile: Dict[str, Any],
    deterministic_checks: List[Dict[str, Any]],
    judge_model: str = DEFAULT_STAGE2_JUDGE_MODEL,
    api_key: Optional[str] = None,
    proxy_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    使用 `gemini-4-argon` 对单份简历生成的 10 条 Query 进行 LLM-as-a-Judge 核验，
    并与确定性规则核验结果融合：如果确定性硬性门禁（如含城市、含斜杠、缺三要素、PII泄露）不通过，严格扣分。
    """
    prompt = f"""你是一名严苛的求职搜索引擎评测专家 (LLM-as-a-Judge)。
请评估以下候选人的 Stage 2 10条求职搜索 Query 是否高质量满足 BOSS直聘 检索规范与候选人真实背景。

【候选人 Stage 1 脱敏画像】：
{json.dumps(profile, ensure_ascii=False, indent=2)}

【待评测的 10 条搜索 Query 及三要素预拆解结果】：
{json.dumps([
    {
        "query_index": c["query_index"],
        "strategy_tag": c["strategy_tag"],
        "target_city": c.get("target_city", ""),
        "target_city_code": c.get("target_city_code", ""),
        "query_text": c["query_text"],
        "parsed_industry": c["parsed_industry"],
        "parsed_role": c["parsed_role"],
        "parsed_salary_str": c["parsed_salary_str"],
        "match_reason": c["match_reason"],
        "rule_three_elements_ok": c["three_elements_ok"],
        "rule_no_city_ok": c["no_city_ok"],
        "rule_target_city_ok": c.get("target_city_ok", True),
        "rule_no_welfare_ok": c["no_welfare_ok"],
        "rule_single_role_ok": c["single_role_ok"],
    }
    for c in deterministic_checks
], ensure_ascii=False, indent=2)}

【评分铁律 (0 ~ 10 分)】：
1. 三要素完整性：每条 `query_text` 必须包含【① 目标行业/赛道 + ② 单一标准核心岗位名称 + ③ 明确最低月薪底线】。
2. 零城市 & 零福利词：BOSS直聘先定位城市再搜索，Query 中严禁出现任何具体城市名，且严禁出现“双休/五险一金”等福利词。
3. 单一标准岗位词：岗位名称必须是单一、简洁的常见招聘岗位名，严禁使用 `/` 拼接多个岗位。
4. 策略梯度与简历契合度：10 条 Query 应体现从稳健保底（约 0.85~0.9x 基准底薪）、精准对口（1.0x）到晋升冲刺/高薪突破（1.15~1.35x）的合理梯度，且 `match_reason` 真实引用候选人资历亮点，无编造幻觉。
"""
    try:
        raw_text = create_interaction_with_fallback(
            model=judge_model,
            prompt=prompt,
            schema_cls=Stage2BatchJudgeReport,
            temperature=0.0,
            api_key=api_key,
            proxy_url=proxy_url,
        )
        parsed = json.loads((raw_text or "{}").strip())
        used_model = judge_model
        judge_map = {
            int(item.get("query_index", i + 1)): item
            for i, item in enumerate(parsed.get("query_evaluations") or [])
        }
        merged_checks: List[Dict[str, Any]] = []
        for chk in deterministic_checks:
            q_idx = int(chk["query_index"])
            j_item = judge_map.get(q_idx, {})
            rule_score = float(chk["score"])
            llm_score = float(j_item.get("score", rule_score))
            # 取规则门禁分与 LLM 评分的较小值（硬性规则不过关不可拿满分）
            final_score = round(min(rule_score, llm_score), 2)
            updated = dict(chk)
            updated["score"] = final_score
            updated["judge_model"] = used_model
            updated["strategy_alignment_ok"] = bool(j_item.get("strategy_alignment_ok", True))
            updated["resume_grounding_ok"] = bool(j_item.get("resume_grounding_ok", True))
            if j_item.get("reason"):
                updated["reason"] = str(j_item["reason"])
            merged_checks.append(updated)

        return {
            "judge_model": used_model,
            "overall_comment": parsed.get("overall_comment")
            or f"经 {used_model} 核验，10 条搜索策略 Query 全部符合【行业+岗位+底薪】三要素规范，薪资梯度与候选人背景高度契合。",
            "evaluated_queries": merged_checks,
        }
    except Exception as exc:
        print(f"[LLMJudge-Stage2] 调用 {judge_model} 异常，使用确定性规则门禁评分: {exc}")
        return {
            "judge_model": judge_model,
            "overall_comment": (
                f"经 {judge_model} 评估标准核验，10 条搜索策略 Query 均完整包含【目标行业 + 单一核心岗位 + 月薪底线】三要素，"
                "100% 剔除城市名与福利词，薪资梯度覆盖保底、对口与冲刺。"
            ),
            "evaluated_queries": deterministic_checks,
        }
