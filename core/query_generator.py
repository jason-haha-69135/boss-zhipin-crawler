"""
阶段二独立服务：多策略求职 Query 生成引擎 (Stage 2: Multi-Strategy Job Query Generator)
架构设计（与 Stage 1 `core/resume_parser.py` 完全解耦）：
1. 输入：接收阶段一产出的 9 字段脱敏结构化候选人画像 `profile` (`CandidateProfileSchema`)，
   以及用户在前端或上游服务传入的自定义覆盖项（月薪底线 `salary_floor`、目标行业/附加方向 `custom_focus` 等）。
2. 词库锚点桥接：由 Python 中间层 (`_infer_boss_role_anchors`) 结合 `BOSS_ROLE_SYNONYMS` 注入
   BOSS直聘 高频标准岗位词锚点，防止生成生僻或拼凑的岗位名。
3. 模型与生成参数默认配置：
   - 默认生成模型 (`DEFAULT_STAGE2_QUERY_MODEL`)：`gemini-3.8-flash`
   - 默认采样温度 (`DEFAULT_STAGE2_TEMPERATURE`)：`0.4`（兼顾策略发散度与三要素指令遵循）
   - 默认输出 Query 数量 (`DEFAULT_QUERY_COUNT`)：`10` 条
4. 输出：包含 10 条不同求职策略维度的自然语言求职 Query，
   **不包含城市名**（因为 BOSS直聘 上是先定位城市再进行搜索），并将原有的作息/福利要求替换为**行业要求**，
   每条严格包含【① 目标行业/赛道 + ② 单一标准核心岗位名称 + ③ 明确最低月薪底线】三要素及个性化 `match_reason`。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from core.gemini_client import create_interaction_with_fallback
from core.intent_parser import CITY_CODE_MAP
from core.resume_parser import (
    CandidateProfileSchema,
    _normalize_city_list,
    _normalize_salary_floor,
    mask_sensitive_pii,
    sanitize_and_normalize_profile,
)

# Stage 2 全局默认配置常量（支持环境变量覆盖）
DEFAULT_STAGE2_QUERY_MODEL: str = os.environ.get("STAGE2_QUERY_MODEL", "gemini-3.8-flash")
DEFAULT_STAGE2_TEMPERATURE: float = float(os.environ.get("STAGE2_TEMPERATURE", "0.4"))
DEFAULT_QUERY_COUNT: int = int(os.environ.get("STAGE2_QUERY_COUNT", "10"))

# BOSS直聘 高频标准岗位词同义扩展映射字典（用于阶段二词库桥接，覆盖多行业）
BOSS_ROLE_SYNONYMS: Dict[str, List[str]] = {
    "督导": ["店面督导", "零售督导", "区域运营经理", "陈列督导", "连锁营运督导", "终端门店督导"],
    "运营": ["区域运营经理", "门店运营主管", "新媒体运营", "内容运营专员", "用户运营主管", "电商运营经理", "品牌运营专员", "社群运营"],
    "市场": ["市场营销专员", "品牌策划主管", "市场推广专员", "活动策划执行", "渠道营销主管", "整合营销专员", "商务拓展BD"],
    "新媒体": ["新媒体运营", "短视频运营", "公众号内容运营", "小红书运营", "社交媒体运营", "内容策划专员"],
    "软件": ["软件开发工程师", "Java开发工程师", "后端开发工程师", "全栈开发工程师", "C++开发工程师", "Web前端开发工程师", "系统研发工程师"],
    "开发": ["后端开发工程师", "Java开发工程师", "Python开发工程师", "前端开发工程师", "全栈工程师", "软件研发工程师"],
    "算法": ["算法工程师", "人工智能工程师", "机器学习工程师", "计算机视觉工程师", "大模型算法工程师", "AI研发工程师"],
    "人工智能": ["人工智能工程师", "算法工程师", "机器学习研发", "AIGC应用工程师", "深度学习工程师"],
    "项目": ["IT项目经理", "软件项目经理", "研发项目经理", "交付项目经理", "PMO项目主管", "敏捷项目经理", "技术项目经理"],
    "外贸": ["外贸业务员", "国际贸易专员", "海外销售经理", "跨境电商运营", "外贸跟单专员", "海外客户经理", "进出口业务主管"],
    "贸易": ["国际贸易专员", "外贸业务主管", "海外商务拓展", "跨境贸易专员", "外贸客户经理"],
    "英语": ["外贸业务专员", "海外市场专员", "国际商务代表", "英语翻译专员", "海外客户支持"],
    "行政": ["行政专员", "行政主管", "人事行政专员", "总务行政助理", "总裁办秘书", "综合行政专员", "前台行政"],
    "秘书": ["总经理秘书", "行政秘书", "总裁办助理", "商务助理", "文秘专员", "高管助理"],
    "新闻": ["新媒体采编", "内容编辑", "新闻记者", "宣传策划专员", "品牌公关专员", "媒介专员", "文案策划"],
    "编辑": ["内容编辑", "新媒体编辑", "文案策划专员", "图书编辑", "采编记者", "品牌文案"],
    "店长": ["连锁店长", "店面督导", "区域店长", "零售营运主管", "旗舰店店长"],
    "买手": ["时尚买手", "服装买手", "商品企划主管", "服饰买手"],
    "商品": ["商品企划主管", "商品运营经理", "OTB商品管理", "零售商品督导"],
    "陈列": ["商品陈列督导", "视觉陈列师", "VM陈列主管", "品牌陈列经理"],
    "餐饮": ["餐饮区域经理", "连锁餐饮督导", "餐饮营运经理", "门店督导"],
    "医疗": ["医疗运营经理", "连锁门诊运营", "口腔运营主管", "区域运营督导"],
}

# 10 大标准求职策略维度定义
STRATEGY_DIMENSIONS: List[str] = [
    "精准对口",
    "晋升冲刺",
    "核心行业优选",
    "跨界拓展",
    "高薪突破",
    "细分垂直深耕",
    "头部名企/大厂",
    "复合技能溢价",
    "高成长潜力岗",
    "稳健保底优选",
]


class RecommendedQueryItem(BaseModel):
    """阶段二：基于简历画像生成的单条求职查询建议"""

    strategy_tag: str = Field(
        description=(
            "推荐策略维度标签，优先取自 10 大标准策略：'精准对口'、'晋升冲刺'、'核心行业优选'、"
            "'跨界拓展'、'高薪突破'、'细分垂直深耕'、'头部名企/大厂'、'复合技能溢价'、'高成长潜力岗'、'稳健保底优选'"
        )
    )
    query_text: str = Field(
        description=(
            "预生成的自然语言求职查询句，必须写成流畅的一句话自然语言，严格包含【目标行业 + 单一标准核心岗位名称 + 月薪底线】三要素，"
            "严禁包含具体城市名称（BOSS直聘先定位城市再搜索），也不要包含双休/五险一金等福利词；"
            "例如：'连锁服装零售行业的区域运营经理岗位，月薪至少1.2w' 或 '互联网新媒体行业的新媒体运营岗位，月薪至少0.8w'"
        )
    )
    match_reason: str = Field(
        description="结合候选人画像中的具体工作资历、行业背景、学历专业、核心技能或量化业绩，说明为什么推荐该行业与岗位方向及薪资标准（40~80字）"
    )


class ResumeQueryGenerationLLMOutput(BaseModel):
    """阶段二：Gemini 基于候选人画像生成多策略求职 Query 的结构化输出"""

    recommended_queries: List[RecommendedQueryItem] = Field(
        description="基于候选人结构化画像量身生成的 10 条不同策略维度的自然语言求职 Query"
    )


def _strip_city_and_welfare_from_query(raw_query: str) -> str:
    """
    确定性后置清洗：
    1. 移除句首或句中不小心带入的城市前缀（如 '深圳的'、'在广州地区'）；
    2. 移除句尾不小心带入的作息/福利子句（如 '，周末双休，要交五险一金，最好有年终奖'），
       确保输出的 Query 纯净保留【行业 + 岗位 + 月薪底线】三要素。
    """
    q = (raw_query or "").strip()
    if not q:
        return ""
    for city in CITY_CODE_MAP:
        if city == "全国":
            continue
        q = re.sub(rf"^(?:在)?{re.escape(city)}(?:市|地区)?(?:的|找)?\s*", "", q)
    # 剥离末尾的作息/福利附加子句
    q = re.sub(
        r"[，,；;]\s*(?:要求|需要|希望|最好)?(?:周末双休|双休|大小周|五险一金|六险一金|年终奖|带薪年假|不加班|朝九晚六).*$",
        "",
        q,
    )
    return q.strip(" ，,。；;")


def _sanitize_queries_list(
    queries: List[RecommendedQueryItem],
    max_count: int = DEFAULT_QUERY_COUNT,
) -> List[Dict[str, str]]:
    """对阶段二生成的推荐 Query 列表进行脱敏、去城市与福利词、去重与数量规整"""
    cleaned_queries: List[Dict[str, str]] = []
    seen_texts = set()
    for item in queries or []:
        q_text = _strip_city_and_welfare_from_query(mask_sensitive_pii((item.query_text or "").strip()))
        if not q_text or q_text in seen_texts:
            continue
        seen_texts.add(q_text)
        cleaned_queries.append(
            {
                "strategy_tag": mask_sensitive_pii((item.strategy_tag or "智能推荐").strip()),
                "query_text": q_text,
                "match_reason": mask_sensitive_pii((item.match_reason or "").strip()),
            }
        )
    return cleaned_queries[:max_count]


def _infer_boss_role_anchors(profile_dict: Dict[str, Any]) -> List[str]:
    """
    Python 中间层词库桥接：
    根据阶段一抽出的 candidate_title、education_summary、industry_background 与 core_skills，
    匹配并推荐 BOSS直聘 上真实高频存在的标准岗位词锚点，供阶段二模型参考。
    """
    combined = " ".join(
        [
            str(profile_dict.get("candidate_title") or ""),
            str(profile_dict.get("education_summary") or ""),
            " ".join(profile_dict.get("industry_background") or []),
            " ".join(profile_dict.get("core_skills") or []),
        ]
    )
    anchors: List[str] = []
    # 从候选人头衔中拆分简洁单一岗位词
    raw_title_parts = re.split(r"[/｜|、·,，（）()\s]+", str(profile_dict.get("candidate_title") or ""))
    for part in raw_title_parts:
        clean_p = re.sub(r"^(资深|高级|初级|见习|驻店|品牌|实习|全职|兼职)", "", part.strip())
        if 2 <= len(clean_p) <= 9 and clean_p not in ("求职意向", "应聘岗位", "相关岗位") and clean_p not in anchors:
            anchors.append(clean_p)

    # 结合 BOSS_ROLE_SYNONYMS 扩展标准高频热搜岗位名
    for key, syns in BOSS_ROLE_SYNONYMS.items():
        if key in combined:
            for s in syns:
                if s not in anchors:
                    anchors.append(s)

    if not anchors:
        anchors = [
            "区域运营经理",
            "店面督导",
            "市场营销专员",
            "新媒体运营",
            "项目经理",
            "行政主管",
            "客户经理",
            "运营专员",
            "品牌策划专员",
            "商务拓展主管",
        ]
    return anchors[:12]


def build_queries_from_profile_fallback(
    profile_dict: Dict[str, Any],
    query_count: int = DEFAULT_QUERY_COUNT,
) -> List[Dict[str, str]]:
    """
    当阶段二遇到网络波动时，直接利用阶段一已成功解析的真实 `profile_dict`
    动态构建 `query_count`（默认 10）条不同策略维度的求职 Query（零画像损耗兜底）。
    每条 Query 严格包含【行业 + 单一标准岗位名 + 月薪底线】，不含城市与作息福利。
    """
    salary_floor = str(profile_dict.get("inferred_salary_floor") or "1.2w").strip()
    industries = [
        str(ind).strip().replace("/", "")
        for ind in (profile_dict.get("industry_background") or [])
        if ind and str(ind).strip()
    ]
    primary_ind = industries[0] if len(industries) >= 1 else "互联网科技"
    secondary_ind = industries[1] if len(industries) >= 2 else f"{primary_ind}及相关"
    cross_ind = industries[2] if len(industries) >= 3 else "数字化商业与新消费"

    anchors = _infer_boss_role_anchors(profile_dict)
    while len(anchors) < 10:
        for backup_role in [
            "运营主管",
            "项目专员",
            "市场策划专员",
            "客户成功经理",
            "业务运营专员",
            "品牌推广专员",
            "管理培训生",
            "商务运营主管",
        ]:
            if backup_role not in anchors:
                anchors.append(backup_role)
            if len(anchors) >= 10:
                break

    years_desc = str(profile_dict.get("years_of_experience") or "丰富实战经验")
    edu_desc = str(profile_dict.get("education_summary") or "良好教育背景")
    skills_list = profile_dict.get("core_skills") or ["标准化运营", "团队协作"]
    skills_desc = "、".join(skills_list[:3])

    # 计算不同策略档位的月薪底线（单位：w）
    base_val = 1.0
    m_w = re.search(r"(\d+(?:\.\d+)?)", salary_floor)
    if m_w:
        base_val = float(m_w.group(1))
    up_salary_20 = f"{round(base_val * 1.2, 1)}w"
    up_salary_35 = f"{round(base_val * 1.35, 1)}w"
    up_salary_15 = f"{round(base_val * 1.15, 1)}w"
    steady_salary = f"{max(0.4, round(base_val * 0.9, 1))}w"
    safe_salary = f"{max(0.4, round(base_val * 0.85, 1))}w"

    fallback_templates = [
        {
            "strategy_tag": "精准对口",
            "query_text": f"{primary_ind}行业的{anchors[0]}岗位，月薪至少{salary_floor}",
            "match_reason": f"高度契合您【{years_desc}】的履历背景与【{skills_desc}】核心能力，行业与岗位对口度最高。",
        },
        {
            "strategy_tag": "晋升冲刺",
            "query_text": f"{primary_ind}行业的{anchors[1]}岗位，月薪至少{up_salary_20}",
            "match_reason": f"依托您在过往经历中的项目统筹与量化业绩亮点，在【{primary_ind}】赛道向上冲刺高一职级的【{anchors[1]}】，争取 {up_salary_20}+ 薪酬包。",
        },
        {
            "strategy_tag": "核心行业优选",
            "query_text": f"{secondary_ind}行业的{anchors[2]}岗位，月薪至少{steady_salary}",
            "match_reason": f"聚焦您熟悉的【{secondary_ind}】成熟赛道标准岗位，兼顾业务契合度与稳健薪酬回报。",
        },
        {
            "strategy_tag": "跨界拓展",
            "query_text": f"{cross_ind}行业的{anchors[3]}岗位，月薪至少{salary_floor}",
            "match_reason": f"发挥您在【{skills_desc}】上的跨行业可迁移能力，切入高景气度的【{cross_ind}】相邻赛道。",
        },
        {
            "strategy_tag": "高薪突破",
            "query_text": f"{primary_ind}行业的{anchors[4]}岗位，月薪至少{up_salary_35}",
            "match_reason": "面向高绩效回报的核心业务骨干岗位，充分释放您的核心技术与业务增长经验。",
        },
        {
            "strategy_tag": "细分垂直深耕",
            "query_text": f"{primary_ind}细分领域的{anchors[5]}岗位，月薪至少{salary_floor}",
            "match_reason": f"紧密围绕您熟悉的【{primary_ind}】垂直场景与【{skills_desc}】专项技能深耕，凸显专业壁垒。",
        },
        {
            "strategy_tag": "头部名企/大厂",
            "query_text": f"大型{primary_ind}企业的{anchors[6]}岗位，月薪至少{up_salary_15}",
            "match_reason": f"结合您的【{edu_desc}】背景与规范化项目经历，重点锁定行业头部知名企业的标准编制岗位。",
        },
        {
            "strategy_tag": "复合技能溢价",
            "query_text": f"{secondary_ind}行业的{anchors[7]}岗位，月薪至少{up_salary_15}",
            "match_reason": f"融合【{skills_desc}】等多维复合能力，在交叉型岗位上获取更高的薪酬溢价空间。",
        },
        {
            "strategy_tag": "高成长潜力岗",
            "query_text": f"新兴{cross_ind}行业的{anchors[8]}岗位，月薪至少{salary_floor}",
            "match_reason": "瞄准处于快速扩张期的新兴业务板块，兼具合理的起薪保障与清晰的职业晋升通道。",
        },
        {
            "strategy_tag": "稳健保底优选",
            "query_text": f"{primary_ind}行业的{anchors[9]}岗位，月薪至少{safe_salary}",
            "match_reason": "在最对口的主流行业适当放宽起薪门槛，换取极高的简历初筛通过率与面试邀约率。",
        },
    ]
    return fallback_templates[: max(1, query_count)]


def generate_queries_from_profile_with_gemini(
    profile: Dict[str, Any],
    target_city: Optional[str] = None,
    salary_floor: Optional[str] = None,
    welfare_prefs: Optional[List[str]] = None,
    custom_focus: Optional[str] = None,
    query_count: int = DEFAULT_QUERY_COUNT,
    model_name: str = DEFAULT_STAGE2_QUERY_MODEL,
    temperature: float = DEFAULT_STAGE2_TEMPERATURE,
    api_key: Optional[str] = None,
    proxy_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    【阶段二独立服务核心函数】
    接收阶段一提炼的结构化候选人画像 `profile`（支持前端或外部调用方覆盖目标城市、薪资底线、福利要求或附加方向），
    注入 Python 词库锚点，通过纯文本轻量级 Model Call（默认模型 `gemini-3.8-flash`，默认 `temperature=0.4`）
    生成 `query_count`（默认 `10` 条）高区分度求职策略 Query。
    无需重复上传简历原文件！
    """
    if not isinstance(profile, dict) or not profile:
        raise ValueError("候选人简历画像 (profile) 不能为空。")

    effective_query_count = max(1, min(int(query_count or DEFAULT_QUERY_COUNT), 20))

    # 将传入的 dict 转换为 CandidateProfileSchema 进行规整与校验
    prof_obj = CandidateProfileSchema(
        candidate_title=str(profile.get("candidate_title") or "资深运营管理"),
        years_of_experience=str(profile.get("years_of_experience") or "具备相关实战经验"),
        education_summary=str(profile.get("education_summary") or "未注明学历"),
        target_cities=list(profile.get("target_cities") or ["深圳"]),
        industry_background=list(profile.get("industry_background") or []),
        core_skills=list(profile.get("core_skills") or []),
        experience_highlights=list(profile.get("experience_highlights") or []),
        inferred_salary_floor=str(profile.get("inferred_salary_floor") or "1.2w"),
        inferred_welfare_prefs=list(profile.get("inferred_welfare_prefs") or ["周末双休", "五险一金", "年终奖"]),
    )
    effective_profile = sanitize_and_normalize_profile(prof_obj)

    # 应用用户在 UI 或接口层传入的实时微调覆盖项
    if target_city and target_city.strip():
        overridden_cities = _normalize_city_list(re.split(r"[/,，、\s]+", target_city.strip()))
        effective_profile["target_cities"] = overridden_cities

    if salary_floor and salary_floor.strip():
        effective_profile["inferred_salary_floor"] = _normalize_salary_floor(salary_floor.strip())

    if welfare_prefs:
        cleaned_w = [mask_sensitive_pii(w.strip()) for w in welfare_prefs if w and w.strip()]
        if cleaned_w:
            effective_profile["inferred_welfare_prefs"] = cleaned_w[:4]

    clean_focus = mask_sensitive_pii((custom_focus or "").strip())
    role_anchors = _infer_boss_role_anchors(effective_profile)
    base_salary = effective_profile["inferred_salary_floor"]
    industry_list = effective_profile.get("industry_background") or ["互联网/科技"]
    industry_str = "、".join(industry_list)

    focus_instruction = (
        f"\n- **用户额外指定的求职偏好/行业方向微调**：`{clean_focus}`（请在生成 Query 时重点响应该诉求！）"
        if clean_focus
        else ""
    )

    query_gen_prompt = f"""你是一位精通 BOSS直聘 搜索推荐机制的资深猎头顾问。现在我们已经完成了候选人简历的深度解析，得到了如下结构化求职画像。请基于该画像，为候选人量身生成 **{effective_query_count} 条** 不同策略维度的自然语言求职查询语句 (`recommended_queries`)。

### 一、 候选人结构化求职画像：
```json
{json.dumps(effective_profile, ensure_ascii=False, indent=2)}
```

### 二、 Python 词库匹配的 BOSS直聘 高频标准岗位词参考锚点：
`{", ".join(role_anchors)}`
- **候选人过往与目标行业背景**：`{industry_str}`
- **当前基准期望月薪底线**：`{base_salary}`{focus_instruction}

### 三、 预生成 {effective_query_count} 条自然语言求职 Query 的严格规范：
1. **必须包含【行业 + 岗位 + 月薪底线】三要素，且严禁包含城市名与作息/福利词**：
   - 因为 BOSS直聘 上是先定位城市再进行搜索，**每条 `query_text` 中绝对不要出现任何城市名称（如深圳、上海、广州、北京、武汉等）**！
   - 同时**不要包含“周末双休、五险一金、年终奖”等作息福利要求**，将其替换为明确的**目标行业/赛道限定**。
   - 每条 `query_text` **必须写成流畅的一句话自然语言**，且严格包含以下 **3 个核心要素**：
     ① **明确的目标行业/细分赛道名称**（结合候选人 `industry_background` `{industry_str}` 或可跨界迁移的相邻高景气行业，如 `互联网新媒体行业`、`连锁服装零售行业`、`企业级软件研发行业`、`跨境电商与外贸行业`、`人工智能与大数据行业` 等）
     ② **在 BOSS直聘 上真实高频存在的简洁单一岗位名称**（2~8个字，如 `区域运营经理`、`新媒体运营`、`Java开发工程师`、`IT项目经理`、`外贸业务员`、`人工智能工程师`、`行政专员`、`内容编辑` 等；**严禁在一句话里用斜杠 `/` 或顿号拼接多个岗位名**！）
     ③ **明确的最低月薪底线**（以 `{base_salary}` 为基准，根据不同策略合理上下浮动，如 `月薪至少{base_salary}`）
2. **标准句式参考范例（严格遵循此三要素句式）**：
   - `"连锁服装零售行业的区域运营经理岗位，月薪至少1.2w"`
   - `"互联网新媒体行业的新媒体运营岗位，月薪至少0.8w"`
   - `"企业服务软件行业的Java后端开发工程师岗位，月薪至少1.2w"`
   - `"跨境电商与外贸行业的外贸业务员岗位，月薪至少0.6w"`
3. **{effective_query_count} 大差异化求职策略维度（必须生成满 {effective_query_count} 条，且每条的“行业+岗位”组合或薪资梯度有明显区分度，严禁重复）**：
   - **策略 1 (`精准对口`)**：最贴合候选人核心过往行业（`{industry_list[0]}`）与核心头衔的同级高频岗位 + 基准月薪 `{base_salary}`。
   - **策略 2 (`晋升冲刺`)**：在对口核心行业中，结合候选人的管理经验、高学历或项目亮点向上跃迁一级（如主管/经理/高级工程师/负责人），月薪底线在 `{base_salary}` 基础上合理上浮 15%~30%。
   - **策略 3 (`核心行业优选`)**：聚焦候选人履历中最具竞争力的主航道行业，匹配岗位供给量充足的主流标准岗位 + 稳健月薪底线。
   - **策略 4 (`跨界拓展`)**：利用候选人的可迁移技能（`{", ".join(effective_profile.get("core_skills", [])[:4])}`），拓展到相邻高景气度新行业赛道的对应岗位 + 基准月薪 `{base_salary}`。
   - **策略 5 (`高薪突破`)**：面向高薪酬溢价行业或高技术/业务壁垒岗位，设定更具进取心的月薪底线（上浮 25%~40%）。
   - **策略 6 (`细分垂直深耕`)**：紧密围绕候选人最擅长的一项垂直专业技能或细分垂直行业场景，匹配专精型岗位。
   - **策略 7 (`头部名企/大厂`)**：结合候选人学历背景（`{effective_profile.get("education_summary", "")}`）与代表性项目经历，匹配成熟大型企业主导的行业赛道与标准编制岗位（月薪上浮 10%~20%）。
   - **策略 8 (`复合技能溢价`)**：结合候选人 2 项以上交叉技能（如“技术+项目管理”、“外语+跨境贸易”、“文案+新媒体策划”），匹配交叉学科/复合型行业岗位（月薪上浮 15%~25%）。
   - **策略 9 (`高成长潜力岗`)**：面向新兴数字化、AI 应用、智能制造、跨境出海等高增长潜力行业的对应岗位 + 基准月薪 `{base_salary}`。
   - **策略 10 (`稳健保底优选`)**：在对口主流行业中，将月薪底线在 `{base_salary}` 基础上适当下调 10%~15%，换取更高的简历初筛通过率与面试邀约密度。
4. **`match_reason` 撰写要求**：
   - 必须引用画像中的具体年限、行业经历、学历专业、技能或业绩亮点（40~80字），向候选人解释为什么推荐这个【行业 + 岗位】方向与薪资标准，严禁出现任何个人隐私信息（如姓名、手机号、邮箱、详细门牌地址）。
"""

    try:
        raw_json = create_interaction_with_fallback(
            model=model_name,
            prompt=query_gen_prompt,
            schema_cls=ResumeQueryGenerationLLMOutput,
            temperature=temperature,
            api_key=api_key,
            proxy_url=proxy_url,
        )
        parsed_out = ResumeQueryGenerationLLMOutput.model_validate_json(raw_json)
        cleaned_queries = _sanitize_queries_list(
            parsed_out.recommended_queries,
            max_count=effective_query_count,
        )
        # 若模型返回的条数不足 effective_query_count，则用 fallback 补齐至 effective_query_count 条
        if len(cleaned_queries) < effective_query_count:
            fallback_pool = build_queries_from_profile_fallback(
                effective_profile,
                query_count=effective_query_count,
            )
            existing_texts = {q["query_text"] for q in cleaned_queries}
            for fq in fallback_pool:
                if len(cleaned_queries) >= effective_query_count:
                    break
                if fq["query_text"] not in existing_texts:
                    cleaned_queries.append(fq)
                    existing_texts.add(fq["query_text"])

        return {
            "model_used": model_name,
            "temperature_used": temperature,
            "query_count": len(cleaned_queries),
            "profile": effective_profile,
            "recommended_queries": cleaned_queries,
        }
    except Exception as exc:
        print(f"[QueryGenerator-Stage2] Gemini 生成推荐 Query 异常，使用基于真实画像的策略兜底: {exc}")
        fallback_queries = build_queries_from_profile_fallback(
            effective_profile,
            query_count=effective_query_count,
        )
        return {
            "model_used": f"{model_name} (Query-Fallback)",
            "temperature_used": temperature,
            "query_count": len(fallback_queries),
            "profile": effective_profile,
            "recommended_queries": fallback_queries,
        }
