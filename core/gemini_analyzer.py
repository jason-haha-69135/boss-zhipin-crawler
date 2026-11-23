"""
Gemini 六维分析与匹配度评估器 (Gemini 6-Dimension Analyzer & Match Evaluator)
结合 Python 精确统计分布 + Gemini (Pro / Flash / Flash-Lite) 深度语义推理，
从【所属行业、薪资水平、技能要求、经验与学历、公司品牌知名度、福利待遇与作息】六个维度生成可视化图表数据与专家洞察，
并输出整体市场匹配度评分 (0-100) 及 Top 8 候选岗位逐一评分与原因分析。
"""

from collections import Counter
import os
from statistics import median
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from core.gemini_client import create_interaction_with_fallback
from core.intent_parser import ParsedSearchIntent

DEFAULT_STAGE5_ANALYSIS_MODEL = os.environ.get("STAGE5_ANALYSIS_MODEL", "gemini-3.8-flash")
DEFAULT_STAGE5_TEMPERATURE = float(os.environ.get("STAGE5_TEMPERATURE", "0.2"))

ALLOWED_MODELS = {
    "gemini-3.8-flash": "Gemini 3.8 Flash",
    "gemini-4-argon": "Gemini 4 Argon",
}


class JobMatchEvaluationLLM(BaseModel):
    """Gemini 对单个 Top 候选岗位的匹配度评估"""

    job_index: int = Field(description="候选岗位编号 (0 ~ N-1)")
    match_score: int = Field(ge=0, le=100, description="该岗位与用户诉求及简历画像的综合匹配度评分 (0-100)")
    match_reason: str = Field(
        description="结合该岗位的所属行业、薪资区间、完整JD职责要求、作息制度与候选人履历给出的具体匹配原因分析 (60-120字)"
    )
    highlights: List[str] = Field(
        default_factory=list,
        description="该岗位的 2-4 个核心亮点标签（如'头部上市企业'、'底薪稳超期望'、'明确周末双休'、'技术栈高度契合'）",
    )
    risks: List[str] = Field(
        default_factory=list,
        description="需要注意的潜在风险或待向HR确认项（如'标注单双休/隔周双休非纯双休'、'薪资下限略低于预期'、'部分技能待补齐'）",
    )


class GeminiAnalysisLLMOutput(BaseModel):
    """Gemini 结构化输出的六维洞察与匹配度评估报告"""

    executive_summary: str = Field(
        description="针对用户查询的整体招聘市场核心结论摘要 (100-180字)，必须引用真实统计数据"
    )
    industry_insight: str = Field(
        description="【维度1：所属行业】深度总结：分析主流招聘行业构成、目标行业占比及跨行业机会"
    )
    salary_insight: str = Field(
        description="【维度2：薪资水平】深度总结：分析薪资区间分布、平均起薪与上限、中位数、多薪情况及与用户期望薪资的契合度"
    )
    skills_insight: str = Field(
        description="【维度3：技能要求】深度总结：提炼高频核心技能要求及完整JD中的关键能力与项目经验要求"
    )
    experience_insight: str = Field(
        description="【维度4：经验与学历要求】深度总结：分析主流工作年限与学历门槛，评估准入难度"
    )
    brand_insight: str = Field(
        description="【维度5：招聘公司品牌知名度】深度总结：分析招聘企业的规模结构、融资/上市阶段以及头部代表性企业特点"
    )
    welfare_insight: str = Field(
        description="【维度6：福利待遇与作息】深度总结：分析五险一金、补贴福利及最关键的周末作息制度（周末双休 vs 大小周/单双休 vs 排班单休）真实占比"
    )
    overall_match_score: int = Field(
        ge=0,
        le=100,
        description="当前市场岗位与用户全部诉求（岗位+城市+行业+薪资+双休+个人履历等）的综合匹配度评分 (0-100)",
    )
    match_verdict: str = Field(
        description="一句话匹配度定性结论，客观概括市场供给、薪资达标度与核心风险"
    )
    match_strengths: List[str] = Field(
        description="市场匹配度高的 3-4 条有利因素及真实数据支撑"
    )
    match_risks: List[str] = Field(
        description="市场与用户诉求存在落差的 2-4 条风险点/难点及原因解释"
    )
    actionable_advice: List[str] = Field(
        description="给用户的 3-4 条具体求职策略、简历优化与面试沟通建议"
    )
    job_evaluations: List[JobMatchEvaluationLLM] = Field(
        description="对全部 Top 候选岗位（0 ~ N-1）的逐一匹配度评分与点评"
    )


def compute_six_dimension_stats(
    jobs: List[Dict[str, Any]],
    top_candidates: List[Dict[str, Any]],
    intent: ParsedSearchIntent,
) -> Dict[str, Any]:
    """在 Python 中对合规岗位池进行精确统计（隔离 Stage 4 降权的异地/低薪陷阱），生成前端 ECharts 直接可用的数据结构"""
    total = len(jobs)
    compliant_jobs = [j for j in jobs if not j.get("is_demoted", False)]
    demoted_count = total - len(compliant_jobs)
    stat_pool = compliant_jobs if compliant_jobs else jobs
    pool_size = len(stat_pool)

    # 1. 所属行业分布
    ind_counter: Counter[str] = Counter()
    matched_ind_count = 0
    for j in stat_pool:
        ind = j.get("所属行业") or "未注明行业"
        ind_counter[ind] += 1
        meta_text = f"{j.get('岗位名称', '')} {ind} {j.get('公司名称', '')} {j.get('技能标签', '')}".lower()
        if intent.industry_keywords and any(kw.lower() in meta_text for kw in intent.industry_keywords if kw):
            matched_ind_count += 1

    industry_chart = [
        {"name": k, "value": v} for k, v in ind_counter.most_common(10)
    ]

    # 2. 薪资分布
    buckets = {
        "8K以下": 0,
        "8-10K": 0,
        "10-12K": 0,
        "12-15K": 0,
        "15-20K": 0,
        "20-30K": 0,
        "30K以上": 0,
    }
    min_salaries: List[int] = []
    max_salaries: List[int] = []
    mid_salaries: List[float] = []
    bonus_months_count = 0
    meet_salary_count = 0

    for j in stat_pool:
        min_k = j.get("最低月薪K", 0)
        max_k = j.get("最高月薪K", 0)
        months = j.get("计薪月数", 12)
        if months > 12:
            bonus_months_count += 1
        if min_k > 0 and max_k > 0:
            min_salaries.append(min_k)
            max_salaries.append(max_k)
            mid = (min_k + max_k) / 2.0
            mid_salaries.append(mid)
            if intent.min_salary_k > 0 and max_k >= intent.min_salary_k:
                meet_salary_count += 1

            if mid < 8:
                buckets["8K以下"] += 1
            elif mid < 10:
                buckets["8-10K"] += 1
            elif mid < 12:
                buckets["10-12K"] += 1
            elif mid < 15:
                buckets["12-15K"] += 1
            elif mid <= 20:
                buckets["15-20K"] += 1
            elif mid <= 30:
                buckets["20-30K"] += 1
            else:
                buckets["30K以上"] += 1

    avg_min_k = round(sum(min_salaries) / len(min_salaries), 1) if min_salaries else 0.0
    avg_max_k = round(sum(max_salaries) / len(max_salaries), 1) if max_salaries else 0.0
    median_mid_k = round(float(median(mid_salaries)), 1) if mid_salaries else 0.0

    salary_chart = [{"range": k, "count": v} for k, v in buckets.items()]

    # 3. 技能要求 Top 15
    skill_counter: Counter[str] = Counter()
    for j in stat_pool:
        raw_skills = j.get("技能标签", "")
        for s in [x.strip() for x in raw_skills.split(",") if x.strip()]:
            skill_counter[s] += 1
    skills_chart = [{"name": k, "value": v} for k, v in skill_counter.most_common(15)]

    # 4. 经验与学历分布
    exp_counter: Counter[str] = Counter()
    deg_counter: Counter[str] = Counter()
    for j in stat_pool:
        exp_counter[j.get("经验要求") or "经验不限"] += 1
        deg_counter[j.get("学历要求") or "学历不限"] += 1

    experience_chart = [{"name": k, "value": v} for k, v in exp_counter.most_common()]
    degree_chart = [{"name": k, "value": v} for k, v in deg_counter.most_common()]

    # 5. 公司品牌知名度（规模 + 融资阶段 + 头部企业）
    scale_counter: Counter[str] = Counter()
    stage_counter: Counter[str] = Counter()
    large_companies: List[str] = []
    for j in stat_pool:
        sc = j.get("公司规模") or "规模未知"
        st = j.get("融资阶段") or "未注明"
        comp = j.get("公司名称") or ""
        scale_counter[sc] += 1
        stage_counter[st] += 1
        if any(k in sc for k in ["500-999人", "1000-9999人", "10000人以上"]) or "上市" in st:
            if comp and comp not in large_companies:
                large_companies.append(comp)

    scale_chart = [{"name": k, "value": v} for k, v in scale_counter.most_common()]
    stage_chart = [{"name": k, "value": v} for k, v in stage_counter.most_common()]

    # 6. 福利待遇与作息制度
    welfare_counter: Counter[str] = Counter()
    weekend_counter: Counter[str] = Counter()
    for j in stat_pool:
        raw_w = j.get("福利待遇", "")
        for w in [x.strip() for x in raw_w.split(",") if x.strip()]:
            welfare_counter[w] += 1
        weekend_counter[j.get("作息制度") or "未明确注明"] += 1

    welfare_chart = [{"name": k, "value": v} for k, v in welfare_counter.most_common(12)]
    weekend_chart = [{"name": k, "value": v} for k, v in weekend_counter.most_common()]

    return {
        "total_jobs": total,
        "compliant_jobs_count": len(compliant_jobs),
        "demoted_jobs_count": demoted_count,
        "stat_pool_size": pool_size,
        "top_detail_count": len(top_candidates),
        "industry": {
            "distribution": industry_chart,
            "matched_keyword_count": matched_ind_count,
            "matched_keyword_ratio": round(matched_ind_count / max(1, pool_size) * 100, 1),
        },
        "salary": {
            "buckets": salary_chart,
            "avg_min_k": avg_min_k,
            "avg_max_k": avg_max_k,
            "median_mid_k": median_mid_k,
            "bonus_months_count": bonus_months_count,
            "bonus_months_ratio": round(bonus_months_count / max(1, pool_size) * 100, 1),
            "meet_expected_count": meet_salary_count,
            "meet_expected_ratio": round(meet_salary_count / max(1, pool_size) * 100, 1),
        },
        "skills": {
            "top_skills": skills_chart,
        },
        "experience": {
            "experience_dist": experience_chart,
            "degree_dist": degree_chart,
        },
        "brand": {
            "scale_dist": scale_chart,
            "stage_dist": stage_chart,
            "notable_companies": large_companies[:15],
        },
        "welfare": {
            "top_welfare": welfare_chart,
            "weekend_dist": weekend_chart,
        },
    }


def build_fallback_analysis(
    intent: ParsedSearchIntent,
    stats: Dict[str, Any],
    top_candidates: List[Dict[str, Any]],
    reason_msg: str = "",
) -> Dict[str, Any]:
    """当未提供 API Key 或模型调用异常时的本地统计分析兜底"""
    total = stats["total_jobs"]
    ind_top = ", ".join([f"{x['name']}({x['value']}个)" for x in stats["industry"]["distribution"][:4]])
    sal_info = stats["salary"]
    skill_top = ", ".join([f"{x['name']}({x['value']})" for x in stats["skills"]["top_skills"][:6]])
    exp_top = ", ".join([f"{x['name']}({x['value']})" for x in stats["experience"]["experience_dist"][:3]])
    deg_top = ", ".join([f"{x['name']}({x['value']})" for x in stats["experience"]["degree_dist"][:3]])
    scale_top = ", ".join([f"{x['name']}({x['value']})" for x in stats["brand"]["scale_dist"][:3]])
    notable = "、".join(stats["brand"]["notable_companies"][:6]) or "多家连锁品牌企业"
    welfare_top = ", ".join([f"{x['name']}({x['value']})" for x in stats["welfare"]["top_welfare"][:5]])
    weekend_top = ", ".join([f"{x['name']}({x['value']}个)" for x in stats["welfare"]["weekend_dist"]])

    base_score = 78
    if intent.require_double_weekend:
        double_cnt = next(
            (x["value"] for x in stats["welfare"]["weekend_dist"] if x["name"] == "周末双休"),
            0,
        )
        if double_cnt == 0:
            base_score = 68

    recommended = []
    for idx, cand in enumerate(top_candidates):
        c_score = int(min(96, max(55, cand.get("初筛得分", 75))))
        jd_preview = (cand.get("完整JD") or "")[:160].replace("\n", " ")
        recommended.append(
            {
                "rank": idx + 1,
                "job_name": cand.get("岗位名称", ""),
                "company_name": cand.get("公司名称", ""),
                "salary_desc": cand.get("薪资范围", ""),
                "location": cand.get("详细地址") or cand.get("工作地点", ""),
                "experience": cand.get("经验要求", ""),
                "degree": cand.get("学历要求", ""),
                "industry": cand.get("所属行业", ""),
                "scale": cand.get("公司规模", ""),
                "stage": cand.get("融资阶段", ""),
                "weekend_policy": cand.get("作息制度", "未明确注明"),
                "hr_activity": cand.get("HR活跃度", ""),
                "skills": cand.get("技能标签", ""),
                "welfare": cand.get("福利待遇", ""),
                "jd_snippet": jd_preview + ("..." if len(cand.get("完整JD", "")) > 160 else ""),
                "job_url": cand.get("岗位链接", ""),
                "match_score": c_score,
                "match_reason": (
                    f"该岗位属于【{cand.get('所属行业') or '相关行业'}】，薪资为 {cand.get('薪资范围')}，"
                    f"公司规模 {cand.get('公司规模') or '适中'}，作息制度识别为【{cand.get('作息制度')}】。"
                ),
                "highlights": [
                    cand.get("所属行业") or "行业匹配",
                    cand.get("薪资范围") or "薪资达标",
                    cand.get("作息制度") or "福利齐全",
                ],
                "risks": ["建议面试沟通时进一步核实具体工作作息、绩效考核指标与岗位职责边界"],
            }
        )

    notice_prefix = f"（注：{reason_msg}，以下为基于采集数据的自动统计总结）" if reason_msg else ""
    pool_size = stats.get("stat_pool_size", total)
    demoted_cnt = stats.get("demoted_jobs_count", 0)
    return {
        "executive_summary": (
            f"{notice_prefix}本次在【{intent.city_name}】共采集到 {total} 个与“{intent.query}”相关的岗位"
            f"（其中合规目标池 {pool_size} 条，异地/低薪降权 {demoted_cnt} 条），并对排名 Top {len(top_candidates)} 的岗位进行了深度分析。"
            f"合规样本平均薪资区间为 {sal_info['avg_min_k']}K - {sal_info['avg_max_k']}K（中位数 {sal_info['median_mid_k']}K），"
            f"主流行业集中在 {ind_top}。"
        ),
        "dimensions": {
            "industry": {
                "title": "所属行业分布",
                "insight": f"合规岗位行业主要分布在：{ind_top}。其中命中目标行业关键词的岗位共 {stats['industry']['matched_keyword_count']} 个（占比 {stats['industry']['matched_keyword_ratio']}%）。",
                "chart_data": stats["industry"]["distribution"],
            },
            "salary": {
                "title": "薪资水平分布",
                "insight": f"合规样本平均起薪 {sal_info['avg_min_k']}K，平均上限 {sal_info['avg_max_k']}K，中位数 {sal_info['median_mid_k']}K；共有 {sal_info['bonus_months_count']} 个岗位提供 13薪及以上年终奖（占比 {sal_info['bonus_months_ratio']}%）。",
                "chart_data": stats["salary"]["buckets"],
                "metrics": {
                    "avg_min_k": sal_info["avg_min_k"],
                    "avg_max_k": sal_info["avg_max_k"],
                    "median_mid_k": sal_info["median_mid_k"],
                    "bonus_months_ratio": sal_info["bonus_months_ratio"],
                },
            },
            "skills": {
                "title": "核心技能要求",
                "insight": f"企业对“{intent.query}”最为看重的高频技能标签依次为：{skill_top or '岗位通用能力'}。建议在简历中结合真实项目与量化成果突出上述核心技能。",
                "chart_data": stats["skills"]["top_skills"],
            },
            "experience": {
                "title": "经验与学历门槛",
                "insight": f"工作经验要求集中在：{exp_top}；学历门槛主要分布在：{deg_top}。建议对照自身年限与学历背景精准投递匹配度最高的“{intent.query}”岗位。",
                "experience_data": stats["experience"]["experience_dist"],
                "degree_data": stats["experience"]["degree_dist"],
            },
            "brand": {
                "title": "招聘公司品牌知名度",
                "insight": f"招聘企业规模主要为：{scale_top}。样本中识别到的中大型或上市代表企业包括：{notable}。",
                "scale_data": stats["brand"]["scale_dist"],
                "stage_data": stats["brand"]["stage_dist"],
                "notable_companies": stats["brand"]["notable_companies"],
            },
            "welfare": {
                "title": "福利待遇与作息制度",
                "insight": f"高频福利标签包括：{welfare_top}。作息制度分布为：{weekend_top}。投递前建议重点核实标明“大小周/单双休”或未注明作息的岗位。",
                "welfare_data": stats["welfare"]["top_welfare"],
                "weekend_data": stats["welfare"]["weekend_dist"],
            },
        },
        "match_evaluation": {
            "overall_score": base_score,
            "verdict": f"{intent.city_name}“{intent.query}”核心岗位与薪资分布整体匹配，建议结合具体作息与技能要求择优投递",
            "strengths": [
                f"{intent.city_name}地区“{intent.query}”合规岗位供给充足（合规池 {pool_size} 条）",
                f"市场主流薪资（{sal_info['avg_min_k']}K-{sal_info['avg_max_k']}K）能够较好覆盖期望月薪水平",
                f"包含多家成熟规模代表企业（{notable}），平台背书较强",
            ],
            "risks": [
                "部分岗位存在大小周/单双休或未明确标注作息制度的情况，需面试前二次确认",
                "不同企业在核心技能栈与底薪/绩效结构上差异较大，需逐一核对 JD 细节",
            ],
            "advice": [
                f"优先投递下方 Top {len(top_candidates)} 列表中综合匹配分高且满足核心硬性条件的“{intent.query}”岗位",
                "开聊时可主动核实：薪资固定底薪与绩效比例、真实周末作息制度及团队业务方向",
                f"简历中重点量化与高频技能（{skill_top or intent.query}）相关的项目落地成果",
            ],
        },
        "recommended_jobs": recommended,
    }


def analyze_jobs_with_gemini(
    intent: ParsedSearchIntent,
    jobs: List[Dict[str, Any]],
    top_candidates: List[Dict[str, Any]],
    model_name: str = DEFAULT_STAGE5_ANALYSIS_MODEL,
    temperature: float = DEFAULT_STAGE5_TEMPERATURE,
    api_key: Optional[str] = None,
    proxy_url: Optional[str] = None,
    resume_profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    结合 Python 合规池六维统计分布、Top K 完整 JD 及可选的候选人真实简历画像，
    通过 Gemini Interactions API (默认 gemini-3.8-flash, temp=0.2) 生成领域中立、事实忠实的深度分析报告。
    """
    stats = compute_six_dimension_stats(jobs, top_candidates, intent)
    if not jobs:
        return build_fallback_analysis(intent, stats, top_candidates, "未采集到匹配的岗位数据")

    selected_model = (
        model_name if model_name in ALLOWED_MODELS else DEFAULT_STAGE5_ANALYSIS_MODEL
    )

    # 构造 Top K 候选岗位的完整上下文
    candidate_blocks = []
    for idx, c in enumerate(top_candidates):
        jd_text = (c.get("完整JD") or "未获取到详情正文")[:700]
        candidate_blocks.append(
            f"【候选岗位 #{idx}】\n"
            f"- 岗位名称: {c.get('岗位名称')}\n"
            f"- 公司名称: {c.get('公司名称')} | 行业: {c.get('所属行业')} | 规模: {c.get('公司规模')} | 融资: {c.get('融资阶段')}\n"
            f"- 薪资范围: {c.get('薪资范围')} | 经验: {c.get('经验要求')} | 学历: {c.get('学历要求')}\n"
            f"- 工作地点: {c.get('详细地址') or c.get('工作地点')} | HR活跃度: {c.get('HR活跃度')}\n"
            f"- 技能标签: {c.get('技能标签')}\n"
            f"- 福利待遇: {c.get('福利待遇')} | 自动识别作息: {c.get('作息制度')}\n"
            f"- 完整职位描述(JD): {jd_text}\n"
        )
    candidates_context = "\n".join(candidate_blocks)

    resume_context_block = ""
    if resume_profile and isinstance(resume_profile, dict):
        resume_context_block = f"""
### 候选人个人真实简历画像（已通过 Stage 1 简历解析提取）：
- 核心头衔/方向：{resume_profile.get('candidate_title', '未注明')}
- 工作年限与资历：{resume_profile.get('years_of_experience', '未注明')}
- 学历背景：{resume_profile.get('education_summary', '未注明')}
- 过往行业背景：{resume_profile.get('industry_background', [])}
- 核心专业技能：{resume_profile.get('core_skills', [])}
- 关键业绩与履历亮点：{resume_profile.get('experience_highlights', [])}
（请在评估 `overall_match_score`、`actionable_advice` 以及全部 Top {len(top_candidates)} 候选岗位的 `match_score` 与 `match_reason` 时，深度结合候选人真实简历资历与岗位 JD 进行【人岗履历契合度】诊断！）
"""

    prompt = f"""你是一位资深的招聘市场数据分析专家与职业顾问。
用户提出了如下求职查询需求：
- 原始自然语言查询：「{intent.raw_query}」
- 解析后的核心岗位：「{intent.query}」 | 城市：「{intent.city_name}」 | 期望最低月薪：{intent.min_salary_k}K | 要求周末双休：{intent.require_double_weekend}
- 行业关键词偏好：{intent.industry_keywords}
- 全部软性要求：{intent.soft_requirements}
{resume_context_block}
本次共采集 {stats['total_jobs']} 条岗位，其中经过 Stage 4 过滤后的合规目标岗位池为 {stats['compliant_jobs_count']} 条（已隔离异地/低薪降权岗位 {stats['demoted_jobs_count']} 条），并提取了排名 Top {len(top_candidates)} 的候选岗位详情。

### 合规样本池六维精确统计数据（请严格引用，禁止编造数据）：
1. 【所属行业分布】: {stats['industry']}
2. 【薪资水平分布】: {stats['salary']}
3. 【技能要求 Top 15】: {stats['skills']}
4. 【经验与学历分布】: {stats['experience']}
5. 【公司品牌知名度(规模/融资/头部企业)】: {stats['brand']}
6. 【福利待遇与作息制度】: {stats['welfare']}

### Top {len(top_candidates)} 候选岗位详情（含完整 JD）：
{candidates_context}

【严格事实忠实度与输出红线】：
1. 所有引用的统计数字、百分比、薪资区间、企业名称与作息制度（如“周末双休” vs “大小周/单双休”）必须 100% 来源于上方真实统计数据或候选岗位 JD，严禁编造任何未出现的数据或公司名。
2. 所有分析与建议必须紧扣当前目标岗位「{intent.query}」与真实行业赛道，严禁套用任何无关行业的模板话术。
3. 必须对全部 {len(top_candidates)} 个候选岗位（`job_index` 从 0 到 {len(top_candidates) - 1}，一个都不能少）逐一给出 `match_score` (0-100 整数)、`match_reason`、`highlights` 和 `risks`。
4. 若某候选岗位作息为“大小周/单双休”或“排班轮休/单休”而用户要求双休，必须在 `risks` 中明确指出并合理下调其 `match_score`。
"""

    try:
        raw_json = create_interaction_with_fallback(
            model=selected_model,
            prompt=prompt,
            schema_cls=GeminiAnalysisLLMOutput,
            temperature=temperature,
            api_key=api_key,
            proxy_url=proxy_url,
        )
        llm_out = GeminiAnalysisLLMOutput.model_validate_json(raw_json)

        eval_map = {ev.job_index: ev for ev in llm_out.job_evaluations}
        recommended = []
        for idx, cand in enumerate(top_candidates):
            ev = eval_map.get(idx)
            c_score = ev.match_score if ev else int(min(95, max(55, cand.get("初筛得分", 75))))
            c_reason = (
                ev.match_reason
                if ev
                else f"该岗位属于{cand.get('所属行业')}行业，薪资{cand.get('薪资范围')}，作息制度为{cand.get('作息制度')}。"
            )
            c_highlights = (
                ev.highlights
                if ev and ev.highlights
                else [
                    cand.get("所属行业") or "行业相关",
                    cand.get("薪资范围") or "薪资匹配",
                    cand.get("作息制度") or "福利完善",
                ]
            )
            c_risks = (
                ev.risks
                if ev and ev.risks
                else ["建议面试时进一步核实周末排班与出差要求"]
            )
            jd_preview = (cand.get("完整JD") or "")[:200].replace("\n", " ")

            recommended.append(
                {
                    "rank": idx + 1,
                    "job_name": cand.get("岗位名称", ""),
                    "company_name": cand.get("公司名称", ""),
                    "salary_desc": cand.get("薪资范围", ""),
                    "location": cand.get("详细地址") or cand.get("工作地点", ""),
                    "experience": cand.get("经验要求", ""),
                    "degree": cand.get("学历要求", ""),
                    "industry": cand.get("所属行业", ""),
                    "scale": cand.get("公司规模", ""),
                    "stage": cand.get("融资阶段", ""),
                    "weekend_policy": cand.get("作息制度", "未明确注明"),
                    "hr_activity": cand.get("HR活跃度", ""),
                    "skills": cand.get("技能标签", ""),
                    "welfare": cand.get("福利待遇", ""),
                    "jd_snippet": jd_preview + ("..." if len(cand.get("完整JD", "")) > 200 else ""),
                    "job_url": cand.get("岗位链接", ""),
                    "match_score": c_score,
                    "match_reason": c_reason,
                    "highlights": c_highlights[:4],
                    "risks": c_risks[:3],
                }
            )

        # 按 Gemini 给出的匹配度评分从高到低排序
        recommended.sort(key=lambda x: x["match_score"], reverse=True)
        for idx, item in enumerate(recommended, start=1):
            item["rank"] = idx

        return {
            "executive_summary": llm_out.executive_summary,
            "dimensions": {
                "industry": {
                    "title": "所属行业分布",
                    "insight": llm_out.industry_insight,
                    "chart_data": stats["industry"]["distribution"],
                },
                "salary": {
                    "title": "薪资水平分布",
                    "insight": llm_out.salary_insight,
                    "chart_data": stats["salary"]["buckets"],
                    "metrics": {
                        "avg_min_k": stats["salary"]["avg_min_k"],
                        "avg_max_k": stats["salary"]["avg_max_k"],
                        "median_mid_k": stats["salary"]["median_mid_k"],
                        "bonus_months_ratio": stats["salary"]["bonus_months_ratio"],
                    },
                },
                "skills": {
                    "title": "核心技能要求",
                    "insight": llm_out.skills_insight,
                    "chart_data": stats["skills"]["top_skills"],
                },
                "experience": {
                    "title": "经验与学历门槛",
                    "insight": llm_out.experience_insight,
                    "experience_data": stats["experience"]["experience_dist"],
                    "degree_data": stats["experience"]["degree_dist"],
                },
                "brand": {
                    "title": "招聘公司品牌知名度",
                    "insight": llm_out.brand_insight,
                    "scale_data": stats["brand"]["scale_dist"],
                    "stage_data": stats["brand"]["stage_dist"],
                    "notable_companies": stats["brand"]["notable_companies"],
                },
                "welfare": {
                    "title": "福利待遇与作息制度",
                    "insight": llm_out.welfare_insight,
                    "welfare_data": stats["welfare"]["top_welfare"],
                    "weekend_data": stats["welfare"]["weekend_dist"],
                },
            },
            "match_evaluation": {
                "overall_score": max(0, min(100, llm_out.overall_match_score)),
                "verdict": llm_out.match_verdict,
                "strengths": llm_out.match_strengths,
                "risks": llm_out.match_risks,
                "advice": llm_out.actionable_advice,
            },
            "recommended_jobs": recommended,
        }
    except Exception as exc:
        print(f"[GeminiAnalyzer] Gemini 调用异常，降级为统计分析报告: {exc}")
        return build_fallback_analysis(
            intent,
            stats,
            top_candidates,
            f"Gemini API 调用未成功 ({exc})",
        )
