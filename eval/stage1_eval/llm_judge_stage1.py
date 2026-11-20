"""
Stage 1 简历画像提取 LLM-as-a-Judge 原子级评测器 (Atomic 9-Field Evaluator)
核心职责：
1. 针对 Stage 1 (`extract_resume_profile_with_gemini`) 输出的 9 字段 JSON (`CandidateProfileSchema`)，
   与 Ground Truth 进行逐字段原子核对（Atomic Classification & Verification）。
2. 对每个字段进行 0~10 分区间打分并给出具体原因 (`reason`)，输出整份 Profile 的 9 字段平均分。
3. 严格执行“数字与硬实体完全一致铁律”（年限、门店数、百分比、学历等级、学校/专业、城市名）
   与“幻觉编造惩罚铁律”，在原子核对过程中同步捕获 Hallucination 与 Entity Mismatch。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

STAGE1_EVAL_DIR = Path(__file__).resolve().parent
EVAL_DIR = STAGE1_EVAL_DIR.parent
PROJECT_ROOT = EVAL_DIR.parent
for _p in (PROJECT_ROOT, EVAL_DIR, STAGE1_EVAL_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from core.gemini_client import create_interaction_with_fallback
from core.resume_parser import mask_sensitive_pii
from stage1_schema_validator import validate_parsed_profile

# CandidateProfileSchema 固定的 9 个标准字段名
PROFILE_FIELD_NAMES: List[str] = [
    "candidate_title",
    "years_of_experience",
    "education_summary",
    "target_cities",
    "industry_background",
    "core_skills",
    "experience_highlights",
    "inferred_salary_floor",
    "inferred_welfare_prefs",
]

ProfileFieldNameLiteral = Literal[
    "candidate_title",
    "years_of_experience",
    "education_summary",
    "target_cities",
    "industry_background",
    "core_skills",
    "experience_highlights",
    "inferred_salary_floor",
    "inferred_welfare_prefs",
]


class FieldAtomicEvaluation(BaseModel):
    """单个字段的原子级核对与 0~10 分评估结果"""

    field_name: ProfileFieldNameLiteral = Field(
        description="被评估的 profile 字段名（取自 CandidateProfileSchema 的 9 个标准字段）"
    )
    ground_truth_value: str = Field(
        description="Ground Truth 中该字段的基准值摘要"
    )
    extracted_value: str = Field(
        description="待测模型实际提取出的该字段值摘要"
    )
    entity_number_match: bool = Field(
        description=(
            "该字段涉及的关键数字或硬实体（工作年限、门店数、金额、增长百分比、学校名、学历等级、标准城市名）"
            "是否与 Ground Truth 完全一致；若不涉及数字/硬实体且无事实冲突则为 True"
        )
    )
    has_hallucination: bool = Field(
        description="该字段是否包含 Ground Truth 与简历原文中完全没有依据的无中生有（幻觉编造）或事实张冠李戴/夸大"
    )
    score: float = Field(
        ge=0.0,
        le=10.0,
        description="该字段的语义完整度与准确度得分（0~10分，支持整数或0.5步长）",
    )
    reason: str = Field(
        description="打分原因（30~80字）：明确说明语义覆盖完整度、数字/硬实体是否一致、以及是否存在漏提或幻觉"
    )


class Stage1JudgeOutput(BaseModel):
    """LLM-as-a-Judge 对单份简历 Stage 1 Profile 的完整 9 字段原子评测输出"""

    field_evaluations: List[FieldAtomicEvaluation] = Field(
        description="严格按照 CandidateProfileSchema 全部 9 个字段顺序输出的逐字段原子核对结果列表（必须包含全部 9 个字段）"
    )
    overall_comment: str = Field(
        description="对整份简历画像提取质量的综合诊断总结（40~100字，指出优势与主要扣分项）"
    )


STAGE1_JUDGE_PROMPT_TEMPLATE = """你是一位极其严苛的 AI 简历解析质量评测专家（LLM-as-a-Judge）。
你的任务是评估【待测模型提取的候选人画像 (`extracted_profile`)】与【真实基准标注 (`ground_truth`)】之间的 **语义完整度与准确度（Semantic Completeness & Similarity）**。

请对 `CandidateProfileSchema` 中的 **全部 9 个字段** 逐一进行 **原子级比对（Atomic Classification & Verification）**，为每个字段打出 **0 ~ 10 分** 并给出具体扣分或得分原因。

---

### 一、 核心评判铁律（必须严格执行）

1. **数字与硬实体“零容忍”铁律（Entity & Number Exact Match）**：
   - 凡是涉及 **关键数字**（如：工作年限 `6年`、`9年`，管辖门店数 `18家`、`30家`，业绩金额 `8600万元`，增长百分比 `24%`，连带率 `1.65至2.18`，团队人数 `32人`）和 **核心硬实体**（如：最高学历等级 `本科`/`大专`/`硕士`、专业名称、毕业院校名称、标准城市名 `深圳`/`上海`），**必须与 `ground_truth`（及简历原文事实）完全一致**！
   - **一票否决扣分**：即便两段话的句式和近义词再相似（例如把 `"管辖 3 家门店"` 提取成 `"管辖 30 家门店"`，或把 `"8年经验"` 算成 `"5年经验"`，或把 `"大专"` 写成 `"本科"`），只要核心数字或硬实体错误，该字段 **`entity_number_match` 必须标为 `false`，且该字段得分最高不得超过 3.0 分**！

2. **幻觉惩罚铁律（Hallucination Penalty）**：
   - 在进行逐字段比对时，必须同时检验 `extracted_profile` 是否包含 **完全没有依据的编造信息（无中生有）** 或 **张冠李戴的事实（如双栏简历排版串行导致把 A 公司的业绩安到 B 公司头上）**。
   - 一旦发现某字段存在幻觉编造，**`has_hallucination` 必须标为 `true`**，并根据幻觉严重程度直接扣除 **4 ~ 10 分**，同时在 `reason` 中明确点出哪一个词或哪一句话属于幻觉。

3. **语义等价宽容原则（Semantic Equivalence）**：
   - 在核心数字与硬实体完全一致、且无幻觉的前提下，允许合理的专业同义词或归纳表达（例如 `ground_truth` 写 `"多店巡店督导"`，`extracted_profile` 写 `"多门店日常巡检与营运督导"`，语义完全等价，应给予满分 10 分）。
   - 若 `extracted_profile` 在 `education_summary` 等字段中额外补充了简历原文中真实存在的毕业院校名称（如 GT 写 `"本科 · 市场营销"`，模型提取为 `"本科 · 深圳大学 · 市场营销"`），属于忠于原文的有效信息补充，不视为幻觉，应给予满分 10 分。

4. **隐私脱敏合规性检查**：
   - `extracted_profile` 的任何字段中严禁出现未脱敏的真实手机号、身份证号、邮箱以及详细的家庭住址/学校街道宿舍地址（`target_cities` 只能保留市级城市名，若原文含详细地址而模型已将其替换为 `[地址已脱敏]` 或已剥离详细地址，则完全合规）。若泄露了未脱敏的真实敏感隐私，对应字段直接得 **0 分**。

---

### 二、 0 ~ 10 分通用量表（Scoring Rubric）

- **10 分（完美匹配）**：完整覆盖 `ground_truth` 该字段全部核心要点，语义高度等价，所有数字/硬实体 100% 准确，零幻觉。
- **8 ~ 9 分（轻微瑕疵）**：核心语义及所有关键数字/硬实体 100% 准确，无任何幻觉；仅遗漏了极次要的修饰词或标签数量比 GT 少 1 个次要项。
- **5 ~ 7 分（部分遗漏或轻微偏差）**：提取出了正确的核心方向，但遗漏了 `ground_truth` 中约 30%~50% 的重要要点（如 3 条关键业绩只提到了 1~2 条，或漏掉重要技能）；或者在推断类字段（`inferred_salary_floor` / `inferred_welfare_prefs`）上与 GT 存在小幅偏差。
- **1 ~ 3 分（严重错误 / 数字实体失真 / 含明显幻觉）**：
  - 关键数字或硬实体与 `ground_truth` 不符（如年限算错、学历等级错、门店数/百分比错、城市错）；
  - 或者存在明显的无中生有幻觉编造；
  - 或者遗漏了该字段 60% 以上的核心事实。
- **0 分（完全错误 / 空白 / 严重幻觉 / 隐私泄露）**：与 `ground_truth` 完全无关、字段为空、整段编造，或泄露了未脱敏的手机号/身份证/邮箱/家庭或学校详细地址。

---

### 三、 9 个字段的专项核对细则（必须按顺序输出全部 9 项）

1. **`candidate_title`**：核对求职头衔：若简历原文明确提到求职岗位/应聘岗位，核对是否准确提取了该岗位；若未明确提到，核对是否结合最近 1~2 份工作的核心岗位提炼出精准专业头衔，有无虚构或夸大职级。
2. **`years_of_experience`**：**重点核对工作年限数字**（如 `1年`、`4年以上`、`5年以上`；若简历时间线写有“2012-04至今”等未注明截止年份的模板表述，只要模型按简历内工作时间跨度合理折算均视为数字匹配 `entity_number_match=True`）以及资历概括的核心行业范围。
3. **`education_summary`**：**重点核对简历中提及的所有高等教育学历阶段（如同时提到本科和硕士研究生，或最高的博士，应全部抓取）**，核对各阶段的学历等级、专业名称与毕业院校是否与 GT 一致（若仅提取了最高学历而漏掉本科学段，则酌情扣 1.5~2.5 分，但不标为 `entity_number_match=False`）。
4. **`target_cities`**：核对市级标准城市集合是否与 GT 一致（若简历未直接写城市但提取了最高学历院校所在城市亦视为合规；严禁包含区县街道门牌详细地址）。
5. **`industry_background`**：按集合比对过往细分行业标签的语义覆盖率，检查是否漏掉核心行业或编造未从业过的行业。
6. **`core_skills`**：按集合比对核心专业技能与管理能力标签的语义覆盖率，检查是否漏掉核心硬技能或编造简历未提及的技能。
7. **`experience_highlights`**：**最核心核对项**！逐条核对 GT 中的关键业绩亮点，**重点比对所有量化数字（参与人数、转发数、延时毫秒数、GitHub Star数、团队人数、获奖等级与次数等）及核心职务名称（如“项目经理”）**是否 100% 吻合，严查张冠李戴与篡改数字/职务。
8. **`inferred_salary_floor`**：**区分“简历明示金额”与“经验推断金额”两种情况核对**：
   - **情况 A（简历原文明确指出了期望薪资具体金额，如 `期望薪资：6K-7K`）**：**必须严格遵守“数字与硬实体零容忍”铁律**！提取的月薪底线必须与简历明示金额完全一致（如 `0.6w`），若不一致则 `entity_number_match` 标为 `false`，得分上限锁死为 3.0 分；
   - **情况 B（简历原文未写明期望薪资，属于结合工作经验和年限推断出来的月薪底线）**：**允许与 `ground_truth` 存在上下 ±40% 以内（即 `|extracted - gt| / gt <= 40%`）的差异**！只要在 ±40% 容差区间内，**`entity_number_match` 必须标为 `true`**（完全一致得 10 分；偏差在 ±20% 以内得 8.5~9.5 分；偏差在 20%~40% 之间得 7.0~8.0 分；仅当偏差超过 ±40% 时才将 `entity_number_match` 标为 `false` 并扣至 3.0 分以下）。
9. **`inferred_welfare_prefs`**：核对建议福利标签（如 `五险一金`、`周末双休`、`年终奖`）与 GT 的语义重合度。

---

### 四、 待评测数据输入
{raw_context_section}
#### 1. 真实基准标注 (`ground_truth`)：
```json
{ground_truth_json}
```

#### 2. 待测模型提取结果 (`extracted_profile`)：
```json
{extracted_profile_json}
```

请严格按照上述评分铁律，对全部 9 个字段逐一输出原子核对结果（`field_evaluations`）及综合诊断总结（`overall_comment`）。
"""


def build_stage1_judge_prompt(
    ground_truth: Dict[str, Any],
    extracted_profile: Dict[str, Any],
    raw_resume_text: Optional[str] = None,
) -> str:
    """构建 Stage 1 LLM-as-a-Judge 评测 Prompt"""
    raw_context_section = ""
    if raw_resume_text and raw_resume_text.strip():
        masked_raw = mask_sensitive_pii(raw_resume_text.strip())[:4000]
        raw_context_section = (
            "\n#### 0. 简历脱敏原文参考（用于辅助核对学校名或细节是否忠于原文）：\n"
            f"```text\n{masked_raw}\n```\n"
        )

    return STAGE1_JUDGE_PROMPT_TEMPLATE.format(
        raw_context_section=raw_context_section,
        ground_truth_json=json.dumps(ground_truth, ensure_ascii=False, indent=2),
        extracted_profile_json=json.dumps(extracted_profile, ensure_ascii=False, indent=2),
    )


def evaluate_profile_with_llm_judge(
    extracted_profile: Dict[str, Any],
    ground_truth: Dict[str, Any],
    raw_pii_tokens: Optional[List[str]] = None,
    raw_resume_text: Optional[str] = None,
    judge_model: str = "gemini-4-argon",
    api_key: Optional[str] = None,
    proxy_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    使用 LLM-as-a-Judge 对单个样本的 Stage 1 `extracted_profile` 执行 9 字段原子核对与 0~10 分打分，
    并结合确定性规则校验 Schema 合法性与 PII 零泄露门禁。
    """
    schema_ok, violations = validate_parsed_profile(
        extracted_profile,
        forbidden_pii_tokens=raw_pii_tokens,
    )

    prompt = build_stage1_judge_prompt(
        ground_truth=ground_truth,
        extracted_profile=extracted_profile,
        raw_resume_text=raw_resume_text,
    )

    raw_json = create_interaction_with_fallback(
        model=judge_model,
        prompt=prompt,
        schema_cls=Stage1JudgeOutput,
        temperature=0.0,
        api_key=api_key,
        proxy_url=proxy_url,
    )
    judge_out = Stage1JudgeOutput.model_validate_json(raw_json)

    # 将模型输出的字段按标准 9 字段顺序对齐，并执行硬规则后置兜底校准
    eval_map: Dict[str, FieldAtomicEvaluation] = {
        item.field_name: item for item in judge_out.field_evaluations
    }

    ordered_evals: List[Dict[str, Any]] = []
    field_scores_map: Dict[str, float] = {}
    hallucinated_fields: List[str] = []
    entity_mismatch_fields: List[str] = []

    for fname in PROFILE_FIELD_NAMES:
        gt_val_str = json.dumps(ground_truth.get(fname, ""), ensure_ascii=False)
        pred_val_str = json.dumps(extracted_profile.get(fname, ""), ensure_ascii=False)

        if fname in eval_map:
            f_item = eval_map[fname]
            score_val = float(f_item.score)
            ent_match = bool(f_item.entity_number_match)
            has_hal = bool(f_item.has_hallucination)
            reason_str = f_item.reason.strip()
        else:
            score_val = 0.0
            ent_match = False
            has_hal = False
            reason_str = "Judge 未返回该字段评估结果，默认计 0 分。"

        # 专项校准 inferred_salary_floor：
        # 若简历原文明确指出期望薪资，则严格执行零容忍；若为推断得出，则允许上下 ±40% 的差异
        if fname == "inferred_salary_floor":
            has_explicit_salary = bool(
                raw_resume_text
                and re.search(r"(期望薪资|期望月薪|薪资要求|目标薪资)\s*[:：]?\s*\d", raw_resume_text)
            )
            m_gt = re.search(r"(\d+(?:\.\d+)?)\s*w", str(ground_truth.get(fname, "")).lower())
            m_pred = re.search(r"(\d+(?:\.\d+)?)\s*w", str(extracted_profile.get(fname, "")).lower())
            if m_gt and m_pred:
                gt_w = float(m_gt.group(1))
                pred_w = float(m_pred.group(1))
                rel_diff = abs(pred_w - gt_w) / gt_w if gt_w > 0 else 0.0
                if has_explicit_salary:
                    if rel_diff > 1e-6:
                        ent_match = False
                else:
                    if rel_diff <= 0.40 + 1e-6:
                        ent_match = True
                        if score_val < 7.5:
                            score_val = 9.0 if rel_diff <= 0.20 + 1e-6 else 8.0
                    else:
                        ent_match = False

        # 铁律 1 强制执行：若关键数字或硬实体不匹配，最高得分不超过 3.0 分
        if not ent_match and score_val > 3.0:
            score_val = 3.0
            reason_str += "（触发数字/硬实体不一致铁律，得分上限锁死为 3.0 分）"

        # 铁律 4 强制执行：若该字段触发了 PII 敏感词泄露，直接锁死为 0.0 分
        if raw_pii_tokens:
            leaked_in_field = [tok for tok in raw_pii_tokens if tok and tok in pred_val_str]
            if leaked_in_field:
                score_val = 0.0
                reason_str += f"（严重违规：该字段泄露了未脱敏 PII {leaked_in_field}，得 0 分）"

        score_val = round(max(0.0, min(10.0, score_val)), 2)
        field_scores_map[fname] = score_val

        if has_hal:
            hallucinated_fields.append(fname)
        if not ent_match:
            entity_mismatch_fields.append(fname)

        ordered_evals.append(
            {
                "field_name": fname,
                "ground_truth_value": gt_val_str,
                "extracted_value": pred_val_str,
                "entity_number_match": ent_match,
                "has_hallucination": has_hal,
                "score": score_val,
                "reason": reason_str,
            }
        )

    # 计算整份 Profile 的 9 字段平均分（0~10 分制与 0~1 归一化分制）
    overall_score_10 = round(sum(field_scores_map.values()) / float(len(PROFILE_FIELD_NAMES)), 2)
    overall_score_norm = round(overall_score_10 / 10.0, 4)

    return {
        "judge_model": judge_model,
        "schema_and_pii_valid": schema_ok,
        "violations": violations,
        "overall_score_10": overall_score_10,
        "overall_score": overall_score_norm,
        "entity_match_rate": round(
            (len(PROFILE_FIELD_NAMES) - len(entity_mismatch_fields)) / float(len(PROFILE_FIELD_NAMES)),
            4,
        ),
        "entity_mismatch_fields": entity_mismatch_fields,
        "hallucination_field_count": len(hallucinated_fields),
        "hallucinated_fields": hallucinated_fields,
        "overall_comment": judge_out.overall_comment,
        "field_scores": field_scores_map,
        "field_evaluations": ordered_evals,
    }
