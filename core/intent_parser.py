"""
自然语言求职意图解析器 (Intent Parser)
将用户的自然语言查询（如：“深圳的服装店面督导，月薪至少1w，周末要双休”）
拆解为：
1. BOSS直聘 URL 硬性过滤参数 (query, city, salary, experience, degree, scale, stage)
2. 软性偏好条件 (industry_keywords, min_salary_k, require_double_weekend, soft_requirements)
"""

import re
import urllib.parse
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from core.gemini_client import create_interaction_with_fallback

# 城市编码字典
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
}

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
    stage_code: str = ""
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


def fallback_parse_intent(user_query: str) -> ParsedSearchIntent:
    """本地确定性规则兜底解析（当未配置 API Key 或 LLM 调用异常时启用）"""
    text = user_query.strip()

    # 1. 识别城市
    detected_city = "深圳"
    for city_name in CITY_CODE_MAP:
        if city_name in text:
            detected_city = city_name
            break
    city_code = CITY_CODE_MAP.get(detected_city, "101280600")

    # 2. 识别薪资要求
    min_salary_k = 0
    salary_code = ""
    match_w = re.search(r"(\d+(?:\.\d+)?)\s*[wW万]", text)
    match_k = re.search(r"(\d+)\s*[kK千]", text)
    if match_w:
        min_salary_k = int(float(match_w.group(1)) * 10)
    elif match_k:
        min_salary_k = int(match_k.group(1))

    if min_salary_k >= 50:
        salary_code = "407"
    elif min_salary_k >= 20:
        salary_code = "406"
    elif min_salary_k >= 10:
        salary_code = "405"
    elif min_salary_k >= 5:
        salary_code = "404"
    elif min_salary_k >= 3:
        salary_code = "403"

    # 3. 识别双休要求
    require_double_weekend = "双休" in text

    # 4. 识别常见行业词
    industry_keywords: List[str] = []
    industry_map = {
        "服装": ["服装", "服饰", "女装", "男装", "童装", "鞋服", "纺织", "时尚"],
        "餐饮": ["餐饮", "食品", "茶饮", "咖啡", "连锁餐饮"],
        "美妆": ["美妆", "化妆品", "护肤", "美容"],
        "互联网": ["互联网", "软件", "电商", "科技"],
        "金融": ["金融", "银行", "证券", "基金", "保险"],
        "教育": ["教育", "培训", "院校"],
    }
    for ind_key, synonyms in industry_map.items():
        if ind_key in text:
            industry_keywords.extend(synonyms)

    # 5. 提取核心岗位词
    cleaned = text
    # 去除逗号后面的薪资/福利要求子句
    clauses = [c.strip() for c in re.split(r"[，,。；;！!]", cleaned) if c.strip()]
    first_clause = clauses[0] if clauses else cleaned
    for city_name in CITY_CODE_MAP:
        first_clause = first_clause.replace(f"{city_name}的", "").replace(city_name, "")
    for ind_key in industry_map:
        if first_clause.startswith(ind_key) and len(first_clause) > len(ind_key) + 1:
            first_clause = first_clause[len(ind_key) :]
    first_clause = re.sub(r"^(找|想找|搜索|查询|招聘|的)+", "", first_clause).strip()
    first_clause = re.sub(r"(岗位|职位|工作)+$", "", first_clause).strip()
    core_query = first_clause or "店面督导"

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
    api_key: Optional[str] = None,
    proxy_url: Optional[str] = None,
) -> ParsedSearchIntent:
    """使用 Gemini 3.5 Flash Light (Interactions API) 快速将用户自然语言解析为 BOSS直聘 URL 参数与软性条件"""
    fallback = fallback_parse_intent(user_query)

    try:
        prompt = (
            "你是一个专业的招聘搜索意图解析器。请将用户的求职需求解析为结构化参数。\n"
            "注意：\n"
            "1. `query` 字段只保留核心岗位名称（如用户说“深圳的服装店面督导”，`query` 应为“店面督导”，把“服装”及其近义词放入 `industry_keywords`，这样既能搜索到所有叫“店面督导”的服装品牌岗位，又不会因为标题没写“服装”二字而漏掉大牌服装企业）。\n"
            "2. 如果用户说“月薪至少1w”或“1w-2w”，`salary_code` 设为 `'405'` (10-20K)，`min_salary_k` 设为 `10`。\n"
            f"用户输入：{user_query}"
        )
        raw_json = create_interaction_with_fallback(
            model="gemini-3.5-flash-lite",
            prompt=prompt,
            schema_cls=LLMIntentSchema,
            temperature=0.1,
            api_key=api_key,
            proxy_url=proxy_url,
        )
        parsed_llm = LLMIntentSchema.model_validate_json(raw_json)

        city_name = parsed_llm.city_name.replace("市", "").strip() or fallback.city_name
        city_code = CITY_CODE_MAP.get(city_name, fallback.city_code)
        salary_code = parsed_llm.salary_code if parsed_llm.salary_code in SALARY_CODE_LABELS else fallback.salary_code
        exp_code = (
            parsed_llm.experience_code
            if parsed_llm.experience_code in EXPERIENCE_CODE_LABELS
            else ""
        )
        deg_code = (
            parsed_llm.degree_code if parsed_llm.degree_code in DEGREE_CODE_LABELS else ""
        )

        return ParsedSearchIntent(
            raw_query=user_query,
            query=parsed_llm.query.strip() or fallback.query,
            city_name=city_name,
            city_code=city_code,
            salary_code=salary_code,
            salary_label=SALARY_CODE_LABELS.get(salary_code, "不限"),
            experience_code=exp_code,
            experience_label=EXPERIENCE_CODE_LABELS.get(exp_code, "不限"),
            degree_code=deg_code,
            degree_label=DEGREE_CODE_LABELS.get(deg_code, "不限"),
            scale_code=parsed_llm.scale_code,
            stage_code=parsed_llm.stage_code,
            min_salary_k=parsed_llm.min_salary_k or fallback.min_salary_k,
            industry_keywords=parsed_llm.industry_keywords or fallback.industry_keywords,
            require_double_weekend=parsed_llm.require_double_weekend or fallback.require_double_weekend,
            soft_requirements=parsed_llm.soft_requirements or fallback.soft_requirements,
        )
    except Exception as exc:
        print(f"[IntentParser] LLM 解析降级至本地规则解析: {exc}")
        return fallback
