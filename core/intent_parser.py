"""
自然语言求职意图解析器 (Intent Parser)
将用户的自然语言查询（如：“深圳的服装店面督导，月薪至少1w，周末要双休”）
拆解为：
1. BOSS直聘 URL 硬性过滤参数 (query, city, salary, experience, degree, scale, stage)
2. 软性偏好条件 (industry_keywords, min_salary_k, require_double_weekend, soft_requirements)
"""

import os
import re
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from core.gemini_client import create_interaction_with_fallback

# Stage 3 默认模型与温度配置（彻底移除 gemini-3.5-flash-lite）
DEFAULT_STAGE3_INTENT_MODEL = os.environ.get("STAGE3_INTENT_MODEL", "gemini-3.8-flash")
DEFAULT_STAGE3_TEMPERATURE = float(os.environ.get("STAGE3_TEMPERATURE", "0.1"))

# BOSS直聘 官方城市编码字典 (1:1 映射 /wapi/zpCommon/data/cityGroup.json)
CITY_CODE_MAP: Dict[str, str] = {
    "全国": "100010000",
    "北京": "101010100",
    "上海": "101020100",
    "广州": "101280100",
    "深圳": "101280600",
    "杭州": "101210100",
    "成都": "101270100",
    "武汉": "101200100",
    "南京": "101190100",
    "苏州": "101190400",
    "西安": "101110100",
    "重庆": "101040100",
    "长沙": "101250100",
    "天津": "101030100",
    "郑州": "101180100",
    "东莞": "101281600",
    "佛山": "101280800",
    "宁波": "101210400",
    "青岛": "101120200",
    "合肥": "101220100",
    "厦门": "101230200",
    "无锡": "101190200",
    "常州": "101191100",
    "珠海": "101280700",
    "惠州": "101280300",
    "中山": "101281700",
    "福州": "101230100",
    "泉州": "101230500",
    "济南": "101120100",
    "大连": "101070200",
    "沈阳": "101070100",
    "哈尔滨": "101050100",
    "长春": "101060100",
    "石家庄": "101090100",
    "太原": "101100100",
    "南昌": "101240100",
    "昆明": "101290100",
    "南宁": "101300100",
    "贵阳": "101260100",
    "海口": "101310100",
    "兰州": "101160100",
    "乌鲁木齐": "101130100",
    "温州": "101210700",
    "嘉兴": "101210300",
    "绍兴": "101210500",
    "南通": "101190500",
    "徐州": "101190800",
    "烟台": "101120500",
}


def resolve_boss_city(city_name: str, strict: bool = True) -> Tuple[str, str]:
    """将城市名标准化并与 BOSS直聘 CITY_CODE_MAP 执行 1:1 映射。

    当 strict=True 且城市不在 CITY_CODE_MAP 中时抛出 ValueError。
    """
    cleaned = (city_name or "").strip().replace("市", "").strip()
    if cleaned in CITY_CODE_MAP:
        return cleaned, CITY_CODE_MAP[cleaned]
    if strict:
        raise ValueError(
            f"无效的 BOSS直聘 意向城市: '{city_name}'。请从 BOSS直聘 官方支持城市列表中选择。"
        )
    return "深圳", CITY_CODE_MAP["深圳"]


def get_boss_city_options() -> List[Dict[str, str]]:
    """返回供前端下拉选择器渲染的 BOSS直聘 1:1 城市列表。"""
    return [{"name": name, "code": code} for name, code in CITY_CODE_MAP.items()]

# 薪资编码字典
SALARY_CODE_LABELS: Dict[str, str] = {
    "": "不限",
    "402": "3K以下",
    "403": "3-5K",
    "404": "5-10K",
    "405": "10-20K",
    "406": "20-50K",
    "407": "50K以上",
}

# 经验编码字典
EXPERIENCE_CODE_LABELS: Dict[str, str] = {
    "": "不限",
    "108": "在校生",
    "102": "应届生",
    "101": "经验不限",
    "103": "1年以内",
    "104": "1-3年",
    "105": "3-5年",
    "106": "5-10年",
    "107": "10年以上",
}

# 学历编码字典
DEGREE_CODE_LABELS: Dict[str, str] = {
    "": "不限",
    "209": "初中及以下",
    "208": "中专/中技",
    "206": "高中",
    "202": "大专",
    "203": "本科",
    "204": "硕士",
    "205": "博士",
}

# 公司规模编码字典（官方白名单）
SCALE_CODE_LABELS: Dict[str, str] = {
    "": "不限",
    "301": "0-20人",
    "302": "20-99人",
    "303": "100-499人",
    "304": "500-999人",
    "305": "1000-9999人",
    "306": "10000人以上",
}

# 融资阶段编码字典（官方白名单）
STAGE_CODE_LABELS: Dict[str, str] = {
    "": "不限",
    "801": "未融资",
    "802": "天使轮",
    "803": "A轮",
    "804": "B轮",
    "805": "C轮",
    "806": "D轮及以上",
    "807": "已上市",
    "808": "不需要融资",
}

# 行业近义词词典（供 Fallback 兜底扩展与 Stage 4 行业匹配）
DOMAIN_SYNONYMS: Dict[str, List[str]] = {
    "服装": ["服装", "服饰", "女装", "男装", "童装", "鞋服", "纺织", "时尚", "零售"],
    "服饰": ["服饰", "服装", "女装", "男装", "鞋服", "时尚", "零售"],
    "鞋服": ["鞋服", "服装", "服饰", "运动服饰", "时尚", "零售"],
    "餐饮": ["餐饮", "连锁餐饮", "食品", "茶饮", "咖啡", "快餐", "酒旅餐饮"],
    "美妆": ["美妆", "化妆品", "护肤", "美容", "日化", "个护"],
    "互联网": ["互联网", "软件", "科技", "信息科技", "SaaS", "电商"],
    "人工智能": ["人工智能", "AI", "大模型", "算法", "机器学习", "深度学习", "科技"],
    "AI": ["AI", "人工智能", "大模型", "算法", "AIGC", "智能硬件"],
    "大数据": ["大数据", "数据智能", "云计算", "互联网", "软件"],
    "软件": ["软件", "软件开发", "互联网", "信息科技", "企业服务", "SaaS"],
    "新媒体": ["新媒体", "传媒", "内容运营", "MCN", "短视频", "自媒体", "文化传媒"],
    "传媒": ["传媒", "文化传媒", "新媒体", "广告", "公关", "营销"],
    "外贸": ["外贸", "进出口", "国际贸易", "跨境电商", "B2B外贸"],
    "跨境电商": ["跨境电商", "跨境", "出海", "电商", "外贸", "亚马逊"],
    "电商": ["电商", "电子商务", "直播电商", "社交电商", "新零售", "互联网"],
    "SaaS": ["SaaS", "企业服务", "软件", "云计算", "B2B", "ToB"],
    "大客户销售": ["大客户销售", "B2B", "企业服务", "SaaS", "商业化"],
    "行政": ["行政", "综合管理", "后勤", "职能管理", "企业服务"],
    "人事": ["人事", "人力资源", "HR", "招聘", "组织发展"],
    "医疗": ["医疗", "医疗健康", "生物医药", "大健康", "医药", "医疗器械"],
    "金融": ["金融", "银行", "证券", "基金", "保险", "金融科技", "投资"],
    "教育": ["教育", "培训", "职业教育", "在线教育", "教培", "院校"],
    "零售": ["零售", "新零售", "连锁零售", "快消", "商超", "消费品"],
    "制造": ["制造", "智能制造", "工业", "生产制造", "供应链", "硬件"],
}

_SORTED_CITY_NAMES: List[str] = sorted(CITY_CODE_MAP.keys(), key=len, reverse=True)


class LLMIntentSchema(BaseModel):
    """用于 Gemini Structured Output 的意图解析 Schema"""

    query: str = Field(
        description="核心岗位名称关键词（仅保留岗位角色本身，如'店面督导'、'Java开发'、'产品经理'，去掉城市、薪资、双休和过窄的行业定语以免漏掉同行业公司）"
    )
    city_name: str = Field(
        default="深圳",
        description="目标城市名称，如'深圳'、'北京'、'上海'、'广州'、'杭州'等；若未提及则默认'深圳'",
    )
    salary_code: str = Field(
        default="",
        description="BOSS直聘薪资档位代码：''(不限), '402'(3K以下), '403'(3-5K), '404'(5-10K), '405'(10-20K, 适用于至少1w/1w-2w/10k-20k), '406'(20-50K), '407'(50K以上)",
    )
    experience_code: str = Field(
        default="",
        description="经验要求代码：''(不限), '108'(在校生), '102'(应届生), '101'(经验不限), '103'(1年以内), '104'(1-3年), '105'(3-5年), '106'(5-10年), '107'(10年以上)",
    )
    degree_code: str = Field(
        default="",
        description="学历要求代码：''(不限), '209'(初中及以下), '208'(中专/中技), '206'(高中), '202'(大专), '203'(本科), '204'(硕士), '205'(博士)",
    )
    scale_code: str = Field(
        default="",
        description="公司规模代码：''(不限), '301'(0-20人), '302'(20-99人), '303'(100-499人), '304'(500-999人), '305'(1000-9999人), '306'(10000人以上)",
    )
    stage_code: str = Field(
        default="",
        description="融资阶段代码：''(不限), '801'(未融资), '802'(天使轮), '803'(A轮), '804'(B轮), '805'(C轮), '806'(D轮及以上), '807'(已上市), '808'(不需要融资)",
    )
    min_salary_k: int = Field(
        default=0,
        description="用户期望的最低月薪（单位：K，例如'至少1w'或'10k以上'填10，未提及填0）",
    )
    industry_keywords: List[str] = Field(
        default_factory=list,
        description="用户提及的行业或细分领域关键词及其近义词列表，如用户提到'服装'，可返回['服装', '服饰', '女装', '男装', '鞋服', '时尚', '零售']",
    )
    require_double_weekend: bool = Field(
        default=False,
        description="用户是否要求周末双休/双休",
    )
    soft_requirements: List[str] = Field(
        default_factory=list,
        description="用户提出的所有软性偏好与附加要求列表，如['服装行业', '月薪至少10K', '周末双休']",
    )


class ParsedSearchIntent(BaseModel):
    """最终用于爬虫与分析器的完整结构化意图"""

    raw_query: str
    query: str
    city_name: str
    city_code: str
    salary_code: str = ""
    salary_label: str = "不限"
    experience_code: str = ""
    experience_label: str = "不限"
    degree_code: str = ""
    degree_label: str = "不限"
    scale_code: str = ""
    scale_label: str = "不限"
    stage_code: str = ""
    stage_label: str = "不限"
    min_salary_k: int = 0
    industry_keywords: List[str] = Field(default_factory=list)
    require_double_weekend: bool = False
    soft_requirements: List[str] = Field(default_factory=list)

    def build_boss_url(self) -> str:
        """生成 BOSS直聘 URL"""
        params: Dict[str, str] = {"query": self.query, "city": self.city_code}
        if self.salary_code:
            params["salary"] = self.salary_code
        if self.experience_code:
            params["experience"] = self.experience_code
        if self.degree_code:
            params["degree"] = self.degree_code
        if self.scale_code:
            params["scale"] = self.scale_code
        if self.stage_code:
            params["stage"] = self.stage_code
        return f"https://www.zhipin.com/web/geek/jobs?{urllib.parse.urlencode(params)}"


def _normalize_city_if_valid(city_name: Optional[str]) -> Optional[Tuple[str, str]]:
    """若输入城市名在 BOSS直聘 CITY_CODE_MAP 中有效，则返回 (标准名, 编码)，否则返回 None。"""
    if not city_name:
        return None
    cleaned = str(city_name).strip().replace("市", "").strip()
    if cleaned in CITY_CODE_MAP:
        return cleaned, CITY_CODE_MAP[cleaned]
    return None


def _detect_city_in_text(text: str) -> Optional[Tuple[str, str]]:
    """按城市名长度降序匹配 user_query 中显式出现的 BOSS直聘 城市。"""
    if not text:
        return None
    for city_name in _SORTED_CITY_NAMES:
        if city_name in text:
            return city_name, CITY_CODE_MAP[city_name]
    return None


def _extract_profile_city(
    resume_profile: Optional[Dict[str, Any]],
) -> Optional[Tuple[str, str]]:
    """从 Stage 1/2 简历画像中提取有效的 BOSS直聘 意向城市。"""
    if not isinstance(resume_profile, dict):
        return None
    direct = _normalize_city_if_valid(resume_profile.get("target_city"))
    if direct:
        return direct
    cities = resume_profile.get("target_cities")
    if isinstance(cities, list):
        for item in cities:
            resolved = _normalize_city_if_valid(item)
            if resolved:
                return resolved
    return None


def resolve_intent_city(
    user_query: str,
    target_city: Optional[str] = None,
    resume_profile: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str]:
    """按确定性优先级解析 BOSS直聘 目标城市与编码：
    1. user_query 中显式提及的 BOSS 城市；
    2. 外部显式传入的 target_city（来自 Stage 2 JSON 或 UI 选择器）；
    3. resume_profile 中的 target_city / target_cities[0]；
    4. 默认兜底 '深圳' ('101280600')。
    """
    in_query = _detect_city_in_text(user_query)
    if in_query:
        return in_query

    explicit = _normalize_city_if_valid(target_city)
    if explicit:
        return explicit

    from_profile = _extract_profile_city(resume_profile)
    if from_profile:
        return from_profile

    return "深圳", CITY_CODE_MAP["深圳"]


def _salary_k_to_code(min_salary_k: int) -> str:
    """将最低月薪（单位 K）映射为 BOSS直聘官方 salary_code。"""
    if min_salary_k >= 50:
        return "407"
    if min_salary_k >= 20:
        return "406"
    if min_salary_k >= 10:
        return "405"
    if min_salary_k >= 5:
        return "404"
    if min_salary_k >= 3:
        return "403"
    if min_salary_k > 0:
        return "402"
    return ""


def _dedupe_keep_order(items: List[str]) -> List[str]:
    """保持顺序去重并过滤空白项。"""
    seen = set()
    result: List[str] = []
    for item in items:
        val = str(item).strip()
        if val and val not in seen:
            seen.add(val)
            result.append(val)
    return result


def _expand_industry_keywords(raw_text: str, raw_industry: str = "") -> List[str]:
    """基于原始行业短语和 DOMAIN_SYNONYMS 生成行业近义词列表。"""
    keywords: List[str] = []
    if raw_industry:
        base_ind = re.sub(r"(行业|领域|赛道|企业)$", "", raw_industry).strip()
        if base_ind:
            keywords.append(base_ind)
    search_pool = f"{raw_industry} {raw_text}"
    for ind_key, synonyms in DOMAIN_SYNONYMS.items():
        if ind_key in search_pool:
            keywords.extend(synonyms)
    return _dedupe_keep_order(keywords)


def _sanitize_core_query(raw_query: str) -> str:
    """清理核心岗位词中的残留后缀（如'岗位'/'职位'）与多余空白。"""
    cleaned = (raw_query or "").strip()
    cleaned = re.sub(r"(岗位|职位|工作)+$", "", cleaned).strip()
    return cleaned


def fallback_parse_intent(
    user_query: str,
    target_city: Optional[str] = None,
    resume_profile: Optional[Dict[str, Any]] = None,
) -> ParsedSearchIntent:
    """本地确定性规则兜底解析（支持 Stage 2 三要素标准句式与自然语言口语，当未配置 API Key 或 LLM 调用异常时启用）"""
    text = user_query.strip()

    # 1. 按确定性优先级解析城市
    detected_city, city_code = resolve_intent_city(
        text, target_city=target_city, resume_profile=resume_profile
    )

    # 2. 识别薪资要求（修复小数四舍五入：1.2w -> 12, 1.5w -> 15, 2.5w -> 25）
    min_salary_k = 0
    match_w = re.search(r"(\d+(?:\.\d+)?)\s*[wW万]", text)
    match_k = re.search(r"(\d+(?:\.\d+)?)\s*[kK千]", text)
    if match_w:
        min_salary_k = int(round(float(match_w.group(1)) * 10))
    elif match_k:
        min_salary_k = int(round(float(match_k.group(1))))
    salary_code = _salary_k_to_code(min_salary_k)

    # 3. 识别双休要求
    require_double_weekend = "双休" in text

    # 4. 提取核心岗位词与行业词（优先识别 Stage 2 标准三要素句式："[行业]的[岗位]岗位，月薪至少[X.Xw]"）
    clauses = [c.strip() for c in re.split(r"[，,。；;！!]", text) if c.strip()]
    first_clause = clauses[0] if clauses else text
    for city_name in _SORTED_CITY_NAMES:
        first_clause = first_clause.replace(f"{city_name}的", "").replace(city_name, "")
    first_clause = re.sub(r"^(找|想找|搜索|查询|招聘|的)+", "", first_clause).strip()

    raw_industry = ""
    stage2_match = re.match(
        r"^(.+?(?:行业|领域|赛道|企业))的(.+?)(?:岗位|职位|工作)?$",
        first_clause,
    )
    if stage2_match:
        raw_industry = stage2_match.group(1).strip()
        core_query = _sanitize_core_query(stage2_match.group(2))
    else:
        for ind_key in sorted(DOMAIN_SYNONYMS.keys(), key=len, reverse=True):
            if first_clause.startswith(ind_key) and len(first_clause) > len(ind_key) + 1:
                raw_industry = ind_key
                first_clause = first_clause[len(ind_key) :].lstrip("的")
                break
        core_query = _sanitize_core_query(first_clause)

    core_query = core_query or "店面督导"
    industry_keywords = _expand_industry_keywords(text, raw_industry=raw_industry)

    soft_reqs: List[str] = []
    if industry_keywords:
        soft_reqs.append(f"行业偏好: {industry_keywords[0]}")
    if min_salary_k > 0:
        soft_reqs.append(f"月薪至少 {min_salary_k}K")
    if require_double_weekend:
        soft_reqs.append("周末双休")
    if "五险一金" in text:
        soft_reqs.append("五险一金")
    if "年终奖" in text or "13薪" in text:
        soft_reqs.append("年终奖")

    return ParsedSearchIntent(
        raw_query=user_query,
        query=core_query,
        city_name=detected_city,
        city_code=city_code,
        salary_code=salary_code,
        salary_label=SALARY_CODE_LABELS.get(salary_code, "不限"),
        min_salary_k=min_salary_k,
        industry_keywords=industry_keywords,
        require_double_weekend=require_double_weekend,
        soft_requirements=soft_reqs,
    )


def parse_user_intent(
    user_query: str,
    target_city: Optional[str] = None,
    resume_profile: Optional[Dict[str, Any]] = None,
    model_name: str = DEFAULT_STAGE3_INTENT_MODEL,
    temperature: float = DEFAULT_STAGE3_TEMPERATURE,
    api_key: Optional[str] = None,
    proxy_url: Optional[str] = None,
) -> ParsedSearchIntent:
    """使用 Gemini (默认 gemini-3.8-flash, Interactions API) 将自然语言或 Stage 2 推荐 Query 解析为 BOSS直聘 URL 参数与软性条件。"""
    fallback = fallback_parse_intent(
        user_query, target_city=target_city, resume_profile=resume_profile
    )
    resolved_city_name, resolved_city_code = resolve_intent_city(
        user_query, target_city=target_city, resume_profile=resume_profile
    )

    try:
        city_hint = (
            f"上下文已锁定的目标城市：{resolved_city_name}（仅当用户输入文本本身显式提及了另一个城市时才覆盖，否则必须保持为'{resolved_city_name}'）。"
        )
        prompt = (
            "你是一个专业的 BOSS直聘 招聘搜索意图解析器（Stage 3）。请将用户的求职需求或 Stage 2 生成的标准三要素 Query 解析为结构化参数。\n"
            "严格规则：\n"
            "1. `query` 字段只保留单一核心岗位名称本身（如输入“服装零售行业的店面督导岗位，月薪至少1.2w”，`query` 必须是“店面督导”），"
            "绝对不能包含城市名、“行业”、“领域”、“岗位”、“职位”、“月薪”、“双休”或斜杠`/`，把行业词及其近义词放入 `industry_keywords`。\n"
            "2. 薪资换算与官方档位映射：`1.2w` -> `min_salary_k=12, salary_code='405'`；`2.5w` -> `min_salary_k=25, salary_code='406'`；"
            "官方档位：`''`(不限), `'402'`(3K以下), `'403'`(3-5K), `'404'`(5-10K), `'405'`(10-20K), `'406'`(20-50K), `'407'`(50K以上)。\n"
            "3. 仅当用户输入明确提及经验/学历/公司规模/融资阶段要求时，才填写对应的官方代码；未提及一律留空字符串 `''`，避免过度收窄 BOSS直聘 搜索召回。\n"
            f"4. {city_hint}\n"
            f"用户输入：{user_query}"
        )
        raw_json = create_interaction_with_fallback(
            model=model_name,
            prompt=prompt,
            schema_cls=LLMIntentSchema,
            temperature=temperature,
            api_key=api_key,
            proxy_url=proxy_url,
        )
        parsed_llm = LLMIntentSchema.model_validate_json(raw_json)

        # 确定性城市优先级防覆盖：Query 显式城市 > target_city > resume_profile > 默认深圳
        city_name, city_code = resolved_city_name, resolved_city_code
        salary_code = (
            parsed_llm.salary_code
            if parsed_llm.salary_code in SALARY_CODE_LABELS
            else fallback.salary_code
        )
        exp_code = (
            parsed_llm.experience_code
            if parsed_llm.experience_code in EXPERIENCE_CODE_LABELS
            else ""
        )
        deg_code = (
            parsed_llm.degree_code if parsed_llm.degree_code in DEGREE_CODE_LABELS else ""
        )
        scale_code = (
            parsed_llm.scale_code if parsed_llm.scale_code in SCALE_CODE_LABELS else ""
        )
        stage_code = (
            parsed_llm.stage_code if parsed_llm.stage_code in STAGE_CODE_LABELS else ""
        )

        clean_query = _sanitize_core_query(parsed_llm.query) or fallback.query
        min_salary_k = parsed_llm.min_salary_k if parsed_llm.min_salary_k > 0 else fallback.min_salary_k
        if not salary_code and min_salary_k > 0:
            salary_code = _salary_k_to_code(min_salary_k)

        industry_keywords = _dedupe_keep_order(
            parsed_llm.industry_keywords or fallback.industry_keywords
        )

        return ParsedSearchIntent(
            raw_query=user_query,
            query=clean_query,
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
            min_salary_k=min_salary_k,
            industry_keywords=industry_keywords,
            require_double_weekend=(
                parsed_llm.require_double_weekend or fallback.require_double_weekend
            ),
            soft_requirements=parsed_llm.soft_requirements or fallback.soft_requirements,
        )
    except Exception as exc:
        print(f"[IntentParser] LLM 解析降级至本地规则解析: {exc}")
        return fallback
