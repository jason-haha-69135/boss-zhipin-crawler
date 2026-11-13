"""
智能简历解析与求职 Query 预生成引擎 (Resume Multimodal Parser & Query Generator)
架构设计（双阶段解耦微服务模式）：
1. 安全网关层：严格遵循安全规范校验上传的简历文件（10MB 大小上限 + 扩展名白名单 + 文件头 Magic Bytes 校验 + 防 Zip Bomb / XXE + 本地正则 PII 脱敏）。
2. 阶段一（独立服务 `extract_resume_profile_with_gemini`）：
   - 利用 Gemini Interactions API (`client.interactions.create`) 原生多模态能力（`temperature=0.1` 收敛型事实抽取）：
     * PDF 简历 (`.pdf`)：直接以 `DocumentContent` (`application/pdf`) 送入 Gemini 视觉+文档理解；
     * 图片简历 (`.png` / `.jpg` / `.jpeg` / `.webp`)：直接以 `ImageContent` 送入 Gemini 视觉理解；
     * Word / 文本简历 (`.docx` / `.txt` / `.md`)：在内存中安全提取纯文本并脱敏后送入 Gemini。
   - 输出经 Python 确定性校准与二次脱敏的结构化求职画像 (`CandidateProfileSchema`)。
3. 阶段二（独立服务 `generate_queries_from_profile_with_gemini`）：
   - 接收阶段一产出的结构化 `profile`（以及用户在前端或上游服务传入的自定义城市、薪资底线、求职偏好覆盖项）；
   - 由 Python 中间层注入 BOSS直聘 高频标准岗位词锚点，通过纯文本轻量级调用（`temperature=0.35` 策略规划）生成 5 条高区分度求职策略 Query（精准对口 / 晋升冲刺 / 作息福利优选 / 跨界拓展 / 高薪突破）。
"""

import base64
import io
import json
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from core.gemini_client import create_interaction_with_fallback
from core.intent_parser import CITY_CODE_MAP

# BOSS直聘 高频标准岗位词同义扩展映射字典（用于阶段二词库桥接）
BOSS_ROLE_SYNONYMS: Dict[str, List[str]] = {
    "督导": ["店面督导", "零售督导", "区域运营经理", "陈列督导", "连锁营运督导"],
    "运营": ["区域运营经理", "门店运营主管", "连锁营运经理", "品牌运营经理"],
    "店长": ["连锁店长", "店面督导", "区域店长", "零售营运主管"],
    "买手": ["时尚买手", "服装买手", "商品企划主管", "服饰买手"],
    "商品": ["商品企划主管", "商品运营经理", "OTB商品管理", "零售商品督导"],
    "陈列": ["商品陈列督导", "视觉陈列师", "VM陈列主管", "品牌陈列经理"],
    "餐饮": ["餐饮区域经理", "连锁餐饮督导", "餐饮营运经理", "门店督导"],
    "医疗": ["医疗运营经理", "连锁门诊运营", "口腔运营主管", "区域运营督导"],
}

# 最大允许上传的简历文件大小：10 MB
MAX_RESUME_BYTES = 10 * 1024 * 1024
# DOCX 解压后 XML 最大允许体积：20 MB（防止 Zip Bomb 炸弹）
MAX_DOCX_UNCOMPRESSED_BYTES = 20 * 1024 * 1024

ALLOWED_EXTENSIONS = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
}


class CandidateProfileSchema(BaseModel):
    """阶段一：Gemini 从简历中深度提炼的结构化候选人画像"""

    candidate_title: str = Field(
        description="候选人当前或核心目标岗位头衔，如 '资深零售区域运营 / 店面督导' 或 '连锁餐饮营运店长'"
    )
    years_of_experience: str = Field(
        description="工作年限与核心资历概括，如 '5年连锁零售门店督导与团队管理经验'"
    )
    education_summary: str = Field(
        description="最高学历及专业概括，如 '本科 · 市场营销' 或 '大专 · 工商企业管理'（未提及则填 '未注明学历'；严禁包含学校详细街道门牌地址或宿舍楼号）"
    )
    target_cities: List[str] = Field(
        description="从简历现居地、求职意向或最近工作地推断的目标城市列表（仅保留1~3个市级标准城市名，如 ['深圳', '广州']；严禁包含家庭住址或学校详细地址）"
    )
    industry_background: List[str] = Field(
        description="过往从业行业背景标签（2~4个），如 ['服装/鞋帽零售', '时尚连锁品牌', '百货/购物中心']"
    )
    core_skills: List[str] = Field(
        description="核心专业技能与管理能力标签（4~8个），如 ['多店巡店督导', 'SOP标准化落地', '商品陈列管理', '店长赋能培训', '门店损益与连带率提升']"
    )
    experience_highlights: List[str] = Field(
        description="简历中最具竞争力的 2~4 条量化业绩或核心资历亮点（严禁包含手机号、邮箱、身份证号、家庭住址、学校地址等个人敏感隐私信息）"
    )
    inferred_salary_floor: str = Field(
        description="结合候选人资历、目标城市与职级推断的合理月薪底线描述，如 '1.2w'、'1w'、'1.5w'"
    )
    inferred_welfare_prefs: List[str] = Field(
        description="建议争取的作息与福利条件（2~4个），如 ['周末双休', '五险一金', '年终奖']"
    )


class RecommendedQueryItem(BaseModel):
    """阶段二：基于简历画像生成的单条求职查询建议"""

    strategy_tag: str = Field(
        description="推荐策略维度标签，取自：'精准对口'、'晋升冲刺'、'作息福利优选'、'跨界拓展'、'高薪突破'"
    )
    query_text: str = Field(
        description=(
            "预生成的自然语言求职查询句，必须包含【城市 + 核心岗位名称 + 月薪底线 + 作息/福利要求】，"
            "例如：'深圳的区域运营经理岗位，月薪至少1.2w，周末双休，要交五险一金，最好有年终奖'"
        )
    )
    match_reason: str = Field(
        description="结合候选人画像中的具体工作资历、核心技能或量化业绩，说明为什么推荐该查询方向及薪资标准（40~80字）"
    )


class ResumeQueryGenerationLLMOutput(BaseModel):
    """阶段二：Gemini 基于候选人画像生成多策略求职 Query 的结构化输出"""

    recommended_queries: List[RecommendedQueryItem] = Field(
        description="基于候选人结构化画像量身生成的 5 条不同策略维度的自然语言求职 Query"
    )


class ResumeParseLLMOutput(BaseModel):
    """完整简历解析与预生成 Query 的组合结构（向后兼容）"""

    profile: CandidateProfileSchema = Field(description="候选人简历结构化画像")
    recommended_queries: List[RecommendedQueryItem] = Field(
        description="基于简历资历量身生成的 4~5 条不同策略维度的自然语言求职 Query"
    )


def sanitize_filename(filename: str) -> str:
    """清理上传的文件名，去除路径分隔符与控制字符"""
    base = os.path.basename((filename or "resume").strip())
    base = re.sub(r"[\x00-\x1f\x7f/\\]+", "_", base)
    return base[:120] or "resume"


def mask_sensitive_pii(text: str) -> str:
    """
    对文本中的敏感个人隐私信息进行脱敏掩码处理，涵盖：
    1. 中国大陆 11 位手机号；
    2. 18 位二代身份证号；
    3. 电子邮箱地址；
    4. 家庭住址 / 现居详细地址 / 户籍地址 / 学校或宿舍详细地址（街道、路名、门牌号、小区、楼栋、单元室、校区宿舍等）。
    防止个人敏感隐私暴露在 profile、前端 UI 或日志中。
    """
    if not text:
        return ""
    # 1. 脱敏中国大陆 11 位手机号
    masked = re.sub(
        r"(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)",
        r"\1****\2",
        text,
    )
    # 2. 脱敏 18 位身份证号
    masked = re.sub(
        r"(?<!\d)(\d{6})\d{8}(\d{3}[\dXx])(?!\d)",
        r"\1********\2",
        masked,
    )
    # 3. 脱敏电子邮箱
    masked = re.sub(
        r"([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*(@[A-Za-z0-9.-]+\.[A-Za-z]{2,})",
        r"\1***\2",
        masked,
    )
    # 4a. 脱敏带显式标签的家庭/学校/现居/户籍/宿舍/通讯地址
    masked = re.sub(
        r"((?:家庭|现居|居住|联系|通讯|户籍|学校|院校|校区|宿舍|详细)(?:住址|地址)\s*[:：]\s*)([^\n，,；;。｜|）\)】\]]+)",
        r"\1[地址已脱敏]",
        masked,
    )
    # 4b. 脱敏具体街道/路/巷 + 门牌号 + 小区/楼栋/校区/宿舍详细地址
    masked = re.sub(
        r"(?:[\u4e00-\u9fa5]{2,6}(?:区|县|镇|街道|乡))?[\u4e00-\u9fa5]{2,12}(?:路|街|道|大道|巷|弄|胡同)\s*(?:特?\d{1,5}\s*号(?:院|附\d+号)?)(?:[\u4e00-\u9fa5A-Za-z0-9\-—#幢栋座单元室层号楼苑园庭院村小区大厦广场公寓中心花园公馆校区宿舍]{0,25})?",
        "[地址已脱敏]",
        masked,
    )
    # 4c. 脱敏住宅小区/花园/公寓/学校校区/学生宿舍 + 楼栋/单元/室号
    masked = re.sub(
        r"[\u4e00-\u9fa5]{2,14}(?:小区|花园|新村|公寓|家园|名苑|豪庭|雅苑|公馆|山庄|学生公寓|研究生公寓|宿舍(?:楼|区)?|校区)\s*(?:[A-Za-z0-9一二三四五六七八九十]{1,4}\s*(?:栋|幢|座|号楼|单元|期|区))+(?:\s*\d{1,5}\s*(?:室|房|号|层))?",
        "[地址已脱敏]",
        masked,
    )
    # 4d. 脱敏独立楼栋 + 单元 + 门牌室号（如“3栋2单元502室”）
    masked = re.sub(
        r"(?<![A-Za-z0-9])\d{1,3}\s*(?:栋|幢|座|号楼)\s*(?:\d{1,2}\s*单元\s*)?\d{2,5}\s*(?:室|房|号)",
        "[地址已脱敏]",
        masked,
    )
    return masked


def validate_and_detect_resume_format(
    filename: str,
    raw_bytes: bytes,
) -> Tuple[str, str]:
    """
    严格校验上传简历文件的体积、扩展名白名单与文件头魔数 (Magic Bytes)。
    返回 (ext, mime_type)。若不合法则抛出 ValueError。
    """
    if not raw_bytes:
        raise ValueError("上传的简历文件内容为空，请选择有效的简历文件。")

    if len(raw_bytes) > MAX_RESUME_BYTES:
        size_mb = round(len(raw_bytes) / (1024 * 1024), 2)
        raise ValueError(f"简历文件体积 ({size_mb} MB) 超过 10 MB 安全上限，请上传小于 10 MB 的文件。")

    safe_name = sanitize_filename(filename)
    _, ext = os.path.splitext(safe_name.lower())
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"不支持的文件格式 ({ext or '无扩展名'})。请上传 PDF (.pdf)、Word (.docx)、图片 (.png/.jpg/.webp) 或纯文本 (.txt/.md) 格式的简历。"
        )

    # 校验 Magic Bytes 文件头签名，防止伪造扩展名上传恶意文件
    if ext == ".pdf":
        if not raw_bytes.startswith(b"%PDF-"):
            raise ValueError("文件内容校验失败：该文件不是有效的 PDF 文档（缺少 %PDF- 文件头签名）。")
        return ext, "application/pdf"

    if ext == ".png":
        if not raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("文件内容校验失败：该文件不是有效的 PNG 图片。")
        return ext, "image/png"

    if ext in (".jpg", ".jpeg"):
        if not raw_bytes.startswith(b"\xff\xd8\xff"):
            raise ValueError("文件内容校验失败：该文件不是有效的 JPEG 图片。")
        return ext, "image/jpeg"

    if ext == ".webp":
        if not (len(raw_bytes) >= 12 and raw_bytes.startswith(b"RIFF") and raw_bytes[8:12] == b"WEBP"):
            raise ValueError("文件内容校验失败：该文件不是有效的 WebP 图片。")
        return ext, "image/webp"

    if ext == ".docx":
        if not raw_bytes.startswith(b"PK\x03\x04"):
            raise ValueError("文件内容校验失败：该文件不是有效的 .docx 文档（若为旧版 .doc 格式，请另存为 .docx 或 .pdf 后上传）。")
        return ext, ALLOWED_EXTENSIONS[".docx"]

    if ext in (".txt", ".md"):
        if b"\x00" in raw_bytes[:4096]:
            raise ValueError("文件内容校验失败：文本简历中包含非法二进制字节。")
        return ext, ALLOWED_EXTENSIONS[ext]

    raise ValueError("不支持的简历文件格式。")


def extract_text_from_docx(raw_bytes: bytes) -> str:
    """
    在内存中安全提取 .docx 文件中的段落与表格文本：
    - 校验 ZIP 条目与解压总大小上限（防 Zip Bomb）；
    - 拒绝包含 <!DOCTYPE 或 <!ENTITY 的 XML（防 XXE 实体注入）。
    """
    try:
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
            names = zf.namelist()
            if "word/document.xml" not in names:
                raise ValueError("无效的 .docx 文件结构：未找到 word/document.xml。")

            total_uncompressed = sum(info.file_size for info in zf.infolist())
            if total_uncompressed > MAX_DOCX_UNCOMPRESSED_BYTES:
                raise ValueError("文档解压后体积超出安全限制。")

            xml_bytes = zf.read("word/document.xml")
    except zipfile.BadZipFile as exc:
        raise ValueError("无法读取 .docx 压缩结构，请确认文件未损坏。") from exc

    xml_head = xml_bytes[:2048].upper()
    if b"<!DOCTYPE" in xml_head or b"<!ENTITY" in xml_head:
        raise ValueError("检测到不安全的 XML 实体声明，拒绝解析该文档。")

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ValueError("解析 .docx 文档 XML 内容失败。") from exc

    paragraphs: List[str] = []
    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag in ("p", "tr"):
            texts: List[str] = []
            for child in elem.iter():
                c_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if c_tag == "t" and child.text:
                    texts.append(child.text)
                elif c_tag == "tab":
                    texts.append("  ")
            line = "".join(texts).strip()
            if line and (not paragraphs or paragraphs[-1] != line):
                paragraphs.append(line)

    extracted = "\n".join(paragraphs).strip()
    if not extracted:
        raise ValueError("未能从该 .docx 文档中提取到有效文字，若简历为纯图片排版，请导出为 PDF 或图片上传。")
    return extracted[:15000]


def decode_plain_text(raw_bytes: bytes) -> str:
    """解码 .txt / .md 简历文本"""
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            text = raw_bytes.decode(encoding).strip()
            if text:
                return text[:15000]
        except UnicodeDecodeError:
            continue
    raise ValueError("无法识别该文本文件的字符编码，请使用 UTF-8 编码保存或导出为 PDF 上传。")


def _normalize_city_list(raw_cities: List[str]) -> List[str]:
    """
    将模型识别出的城市列表标准化为 BOSS直聘 支持的市级标准城市名，
    自动剥离可能夹带的区县、街道、家庭住址或学校地址细节。
    """
    normalized: List[str] = []
    for item in raw_cities or []:
        orig_str = (item or "").strip()
        if not orig_str:
            continue
        # 1. 优先从原始字符串中匹配 CITY_CODE_MAP 中的标准城市名（即使传入了“广州市天河区兴民路222号”也能精准提纯为“广州”）
        matched_std = None
        for std_city in CITY_CODE_MAP:
            if std_city in orig_str:
                matched_std = std_city
                break
        if matched_std:
            final_city = matched_std
        else:
            # 2. 若包含“XX市...”，仅截取到市名，截断后续区县/街道/门牌地址
            m_city = re.search(r"([\u4e00-\u9fa5]{2,5})市", orig_str)
            if m_city:
                final_city = re.sub(r"^.+省", "", m_city.group(1))
            else:
                raw_str = mask_sensitive_pii(orig_str)
                final_city = re.sub(r"[市省区县]$", "", raw_str.replace("[地址已脱敏]", "").strip())
        if final_city and 2 <= len(final_city) <= 6 and final_city not in normalized:
            normalized.append(final_city)
    return normalized[:3] or ["深圳"]


def _normalize_salary_floor(raw_salary: str) -> str:
    """规整月薪底线描述（例如 '12000' -> '1.2w', '15k' -> '1.5w'）"""
    s = (raw_salary or "").strip().lower()
    if not s:
        return "1.2w"
    m_w = re.search(r"(\d+(?:\.\d+)?)\s*[w万]", s)
    if m_w:
        return f"{m_w.group(1)}w"
    m_k = re.search(r"(\d+(?:\.\d+)?)\s*k", s)
    if m_k:
        val_k = float(m_k.group(1))
        val_w = round(val_k / 10.0, 2)
        return f"{int(val_w) if val_w.is_integer() else val_w}w"
    m_num = re.search(r"(\d{4,6})", s)
    if m_num:
        val_num = float(m_num.group(1))
        val_w = round(val_num / 10000.0, 2)
        return f"{int(val_w) if val_w.is_integer() else val_w}w"
    return mask_sensitive_pii(raw_salary.strip())


def sanitize_and_normalize_profile(prof: CandidateProfileSchema) -> Dict[str, Any]:
    """
    Python 中间层确定性校准与脱敏：
    对阶段一 Gemini 抽取的简历画像进行 PII 二次脱敏、城市词库对齐与薪资格式标准化。
    """
    prof.candidate_title = mask_sensitive_pii((prof.candidate_title or "资深运营管理").strip())
    prof.years_of_experience = mask_sensitive_pii((prof.years_of_experience or "具备相关实战经验").strip())
    prof.education_summary = mask_sensitive_pii((prof.education_summary or "未注明学历").strip())
    prof.experience_highlights = [
        mask_sensitive_pii(h.strip()) for h in (prof.experience_highlights or []) if h and h.strip()
    ][:4]
    prof.core_skills = [mask_sensitive_pii(s.strip()) for s in (prof.core_skills or []) if s and s.strip()][:8]
    prof.industry_background = [
        mask_sensitive_pii(i.strip()) for i in (prof.industry_background or []) if i and i.strip()
    ][:4]
    prof.target_cities = _normalize_city_list(prof.target_cities)
    prof.inferred_salary_floor = _normalize_salary_floor(prof.inferred_salary_floor)
    prof.inferred_welfare_prefs = [
        mask_sensitive_pii(w.strip()) for w in (prof.inferred_welfare_prefs or []) if w and w.strip()
    ][:4] or ["周末双休", "五险一金", "年终奖"]
    return prof.model_dump()


def _sanitize_queries_list(queries: List[RecommendedQueryItem]) -> List[Dict[str, str]]:
    """对阶段二生成的推荐 Query 列表进行脱敏与清理"""
    cleaned_queries: List[Dict[str, str]] = []
    for item in queries or []:
        q_text = mask_sensitive_pii((item.query_text or "").strip())
        if not q_text:
            continue
        cleaned_queries.append(
            {
                "strategy_tag": (item.strategy_tag or "智能推荐").strip(),
                "query_text": q_text,
                "match_reason": mask_sensitive_pii((item.match_reason or "").strip()),
            }
        )
    return cleaned_queries[:5]


def _infer_boss_role_anchors(profile_dict: Dict[str, Any]) -> List[str]:
    """
    Python 中间层词库桥接：
    根据阶段一抽出的 candidate_title、industry_background 与 core_skills，
    匹配并推荐 BOSS直聘 上真实高频存在的标准岗位词锚点，供阶段二模型参考。
    """
    combined = " ".join(
        [
            str(profile_dict.get("candidate_title") or ""),
            " ".join(profile_dict.get("industry_background") or []),
            " ".join(profile_dict.get("core_skills") or []),
        ]
    )
    anchors: List[str] = []
    # 从候选人头衔中拆分简洁词
    raw_title_parts = re.split(r"[/｜|、·,\s]+", str(profile_dict.get("candidate_title") or ""))
    for part in raw_title_parts:
        clean_p = re.sub(r"^(资深|高级|初级|见习|驻店|品牌)", "", part.strip())
        if 2 <= len(clean_p) <= 8 and clean_p not in anchors:
            anchors.append(clean_p)

    # 结合 BOSS_ROLE_SYNONYMS 扩展标准高频热搜岗位名
    for key, syns in BOSS_ROLE_SYNONYMS.items():
        if key in combined:
            for s in syns:
                if s not in anchors:
                    anchors.append(s)

    if not anchors:
        anchors = ["区域运营经理", "店面督导", "连锁营运经理", "门店运营主管"]
    return anchors[:8]


def build_heuristic_profile_from_text(raw_text: str) -> Dict[str, Any]:
    """当阶段一遇到极端网络异常时，基于提取文本构建本地启发式候选人画像"""
    safe_text = mask_sensitive_pii(raw_text)
    detected_cities = [city for city in CITY_CODE_MAP if city in safe_text][:2] or ["深圳"]

    exp_match = re.search(r"(\d{1,2})\s*年(?:以上)?(?:工作|从业|管理|零售|运营|督导)?经验", safe_text)
    years_str = f"{exp_match.group(1)}年相关工作经验" if exp_match else "具备相关岗位实战经验"

    deg_str = "未注明学历"
    for deg in ("硕士", "研究生", "本科", "大专", "专科"):
        if deg in safe_text:
            deg_str = deg
            break

    role_candidates = [
        "区域运营经理",
        "店面督导",
        "零售督导",
        "陈列督导",
        "连锁店长",
        "营运经理",
        "门店运营",
        "大区经理",
        "产品经理",
        "运营经理",
    ]
    matched_roles = [r for r in role_candidates if r in safe_text]
    primary_role = matched_roles[0] if matched_roles else "区域运营经理"

    return {
        "candidate_title": f"{primary_role} / 资深运营管理",
        "years_of_experience": years_str,
        "education_summary": deg_str,
        "target_cities": detected_cities,
        "industry_background": ["连锁零售/商业运营", "终端门店管理"],
        "core_skills": ["门店运营管理", "SOP标准化督导", "团队带教培训", "数据分析与业绩提升"],
        "experience_highlights": [f"{years_str}，熟悉目标岗位核心业务流程与团队协作"],
        "inferred_salary_floor": "1.2w",
        "inferred_welfare_prefs": ["周末双休", "五险一金", "年终奖"],
    }


def build_queries_from_profile_fallback(profile_dict: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    当阶段二遇到网络波动时，直接利用阶段一已成功解析的真实 `profile_dict`
    动态构建 5 条不同策略维度的求职 Query（零画像损耗兜底）。
    """
    cities = profile_dict.get("target_cities") or ["深圳"]
    primary_city = cities[0] if isinstance(cities, list) and cities else "深圳"
    salary_floor = str(profile_dict.get("inferred_salary_floor") or "1.2w").strip()
    welfares = profile_dict.get("inferred_welfare_prefs") or ["周末双休", "五险一金", "年终奖"]
    welfare_clause = "，".join(welfares[:3]) if welfares else "周末双休，要交五险一金，最好有年终奖"

    anchors = _infer_boss_role_anchors(profile_dict)
    role_match = anchors[0] if len(anchors) >= 1 else "店面督导"
    role_promote = anchors[1] if len(anchors) >= 2 else "区域运营经理"
    role_welfare = anchors[2] if len(anchors) >= 3 else "品牌连锁督导"
    role_cross = anchors[3] if len(anchors) >= 4 else "零售运营主管"

    years_desc = str(profile_dict.get("years_of_experience") or "丰富实战经验")
    skills_list = profile_dict.get("core_skills") or ["标准化运营", "团队管理"]
    skills_desc = "、".join(skills_list[:3])

    # 计算晋升/高薪档位底薪
    base_val = 1.2
    m_w = re.search(r"(\d+(?:\.\d+)?)", salary_floor)
    if m_w:
        base_val = float(m_w.group(1))
    up_salary = f"{round(base_val + 0.3, 1)}w"
    steady_salary = f"{max(0.8, round(base_val - 0.2, 1))}w"

    return [
        {
            "strategy_tag": "精准对口",
            "query_text": f"{primary_city}的{role_match}岗位，月薪至少{salary_floor}，{welfare_clause}",
            "match_reason": f"高度契合您【{years_desc}】的履历背景与【{skills_desc}】核心能力，岗位供给充足，人岗匹配度最高。",
        },
        {
            "strategy_tag": "晋升冲刺",
            "query_text": f"{primary_city}的{role_promote}岗位，月薪至少{up_salary}，周末双休，要交五险一金，最好有年终奖",
            "match_reason": f"依托您在过往工作中的管理经验与量化业绩亮点，向上冲刺高一职级的【{role_promote}】，争取 {up_salary}+ 薪酬包。",
        },
        {
            "strategy_tag": "作息福利优选",
            "query_text": f"{primary_city}的{role_welfare}，月薪至少{steady_salary}，周末双休，要交五险一金，最好有年终奖",
            "match_reason": "聚焦成熟连锁品牌总部或管理规范编制，优先保障周末双休、五险一金及年终多薪福利兑现。",
        },
        {
            "strategy_tag": "跨界拓展",
            "query_text": f"{primary_city}的{role_cross}岗位，月薪至少{salary_floor}，周末双休，要交五险一金",
            "match_reason": f"发挥您在【{skills_desc}】上的跨行业可迁移能力，切入高景气度商业连锁与新零售运营赛道。",
        },
        {
            "strategy_tag": "高薪突破",
            "query_text": f"{primary_city}的大区运营经理，月薪至少{up_salary}，周末双休，五险一金齐全，有年终奖",
            "match_reason": "面向高绩效回报的核心业务负责人岗位，充分释放您的多店统筹与业绩增长经验。",
        },
    ]


# ==============================================================================
# 阶段一独立服务：多模态深度理解简历细节 -> 输出结构化求职画像 (`CandidateProfileSchema`)
# ==============================================================================
def extract_resume_profile_with_gemini(
    filename: str,
    raw_bytes: bytes,
    model_name: str = "gemini-3.8-flash",
    api_key: Optional[str] = None,
    proxy_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    【阶段一独立接口逻辑】
    校验并解析用户上传的简历文件，通过 Gemini Interactions API (`temperature=0.1`)
    专注执行多模态事实抽取（Information Extraction），返回脱敏并标准化后的候选人求职画像 (`profile`)。
    """
    ext, mime_type = validate_and_detect_resume_format(filename, raw_bytes)
    safe_name = sanitize_filename(filename)

    profile_extraction_prompt = """你是一位严谨的资深猎头顾问与人才简历解析专家。请仔细阅读并深度理解这份候选人简历（Understand Resume Details），忠实于简历原文事实，严格按照 JSON Schema 提取候选人的结构化求职画像。

### 简历深度提取规则（零幻觉、高保真）：
1. **核心求职头衔 (`candidate_title`)**：
   - 结合候选人最近 1~2 份工作的核心岗位与求职意向，提炼出精准的专业头衔（如 `"资深零售区域运营 / 店面督导"`、`"时尚女装买手 / 商品企划主管"`）。
2. **工作年限与资历概括 (`years_of_experience`)**：
   - 根据简历中的工作时间线核算总工作年限与核心资历（如 `"7年服装商品企划、买手与终端店铺运营管理经验"`）。
3. **最高学历与专业 (`education_summary`)**：
   - 提取最高学历、毕业院校名称或专业名称（如 `"本科 · 服装设计与工程"`；若未提及则填 `"未注明学历"`；**切勿包含学校所在的详细街道地址、校区门牌号或宿舍楼号**）。
4. **意向城市 (`target_cities`)**：
   - 从简历中的现居地、求职意向城市或最近工作地点提取 1~3 个**市级标准城市名**（如 `["深圳"]` 或 `["深圳", "广州"]`；若完全未提及具体城市，默认填 `["深圳"]`；**若简历写有详细的家庭住址或学校地址，仅允许提取市级城市名，严禁保留区县街道、小区楼栋或门牌号**）。
5. **过往行业背景 (`industry_background`)**：
   - 提炼 2~4 个精准的细分行业标签（如 `["时尚女装/鞋帽零售", "设计师品牌", "买手店/电商视觉"]`）。
6. **核心专业技能与管理能力 (`core_skills`)**：
   - 提炼 4~8 个最具代表性的硬技能与业务管理能力标签（如 `["商品企划与OTB采买", "多店巡店与陈列督导", "SOP标准化落地", "爆款开发与供应链跟单", "销售数据分析"]`）。
7. **量化业绩与核心资历亮点 (`experience_highlights`)**：
   - 提取简历中最有说服力的 2~4 条量化业务成果、管理半径或代表性项目亮点。
   - **隐私红线：严禁在 `profile` 的任何输出字段中包含候选人的真实手机号码、电子邮箱、身份证号，以及家庭详细住址（街道/路名/小区/楼栋/室号）或学校详细地址（校区街道门牌/宿舍号）！**
8. **合理月薪底线 (`inferred_salary_floor`) 与福利偏好 (`inferred_welfare_prefs`)**：
   - 若简历写明了期望薪资，优先采用；若未写明，请结合候选人工作年限、职级与所在城市水平推断合理的期望月薪底线（统一格式如 `"1w"`、`"1.2w"`、`"1.5w"`、`"2w"`）。
   - 给出建议争取的 2~4 项作息与福利条件（如 `["周末双休", "五险一金", "年终奖"]`）。
"""

    extracted_plain_text = ""
    if ext == ".pdf":
        b64_data = base64.b64encode(raw_bytes).decode("ascii")
        multimodal_input: Any = [
            {
                "type": "document",
                "data": b64_data,
                "mime_type": "application/pdf",
            },
            {
                "type": "text",
                "text": profile_extraction_prompt,
            },
        ]
    elif ext in (".png", ".jpg", ".jpeg", ".webp"):
        b64_data = base64.b64encode(raw_bytes).decode("ascii")
        multimodal_input = [
            {
                "type": "image",
                "data": b64_data,
                "mime_type": mime_type,
            },
            {
                "type": "text",
                "text": profile_extraction_prompt,
            },
        ]
    elif ext == ".docx":
        extracted_plain_text = mask_sensitive_pii(extract_text_from_docx(raw_bytes))
        multimodal_input = (
            f"### 候选人上传的简历正文内容（文件名：{safe_name}）：\n"
            f"{extracted_plain_text}\n\n"
            f"{profile_extraction_prompt}"
        )
    else:
        extracted_plain_text = mask_sensitive_pii(decode_plain_text(raw_bytes))
        multimodal_input = (
            f"### 候选人上传的简历正文内容（文件名：{safe_name}）：\n"
            f"{extracted_plain_text}\n\n"
            f"{profile_extraction_prompt}"
        )

    try:
        raw_json = create_interaction_with_fallback(
            model=model_name,
            prompt=multimodal_input,
            schema_cls=CandidateProfileSchema,
            temperature=0.1,
            api_key=api_key,
            proxy_url=proxy_url,
        )
        parsed_prof = CandidateProfileSchema.model_validate_json(raw_json)
        cleaned_profile = sanitize_and_normalize_profile(parsed_prof)
        return {
            "filename": safe_name,
            "model_used": model_name,
            "profile": cleaned_profile,
        }
    except Exception as exc:
        if extracted_plain_text:
            print(f"[ResumeParser-Stage1] Gemini 简历画像解析异常，启用文本启发式兜底: {exc}")
            fallback_prof = build_heuristic_profile_from_text(extracted_plain_text)
            return {
                "filename": safe_name,
                "model_used": f"{model_name} (Profile-Fallback)",
                "profile": fallback_prof,
            }
        raise RuntimeError(f"Gemini 解析简历画像未成功：{exc}") from exc


# ==============================================================================
# 阶段二独立服务：基于结构化求职画像 (+用户微调偏好) -> 生成 5 条定制化求职 Query
# ==============================================================================
def generate_queries_from_profile_with_gemini(
    profile: Dict[str, Any],
    target_city: Optional[str] = None,
    salary_floor: Optional[str] = None,
    welfare_prefs: Optional[List[str]] = None,
    custom_focus: Optional[str] = None,
    model_name: str = "gemini-3.8-flash",
    api_key: Optional[str] = None,
    proxy_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    【阶段二独立接口逻辑】
    接收阶段一提炼的结构化候选人画像 `profile`（支持前端或外部调用方覆盖目标城市、薪资底线、福利要求或附加方向），
    注入 Python 词库锚点，通过纯文本轻量级 Model Call (`temperature=0.35`) 生成 5 条高区分度求职策略 Query。
    无需重复上传简历原文件！
    """
    if not isinstance(profile, dict) or not profile:
        raise ValueError("候选人简历画像 (profile) 不能为空。")

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
    primary_city = effective_profile["target_cities"][0]
    base_salary = effective_profile["inferred_salary_floor"]
    welfare_str = "、".join(effective_profile["inferred_welfare_prefs"])

    focus_instruction = (
        f"\n- **用户额外指定的求职偏好/方向微调**：`{clean_focus}`（请在生成 Query 时重点响应该诉求！）"
        if clean_focus
        else ""
    )

    query_gen_prompt = f"""你是一位精通 BOSS直聘 搜索推荐机制的资深猎头顾问。现在我们已经完成了候选人简历的深度解析，得到了如下结构化求职画像。请基于该画像，为候选人量身生成 **5 条** 不同策略维度的自然语言求职查询语句 (`recommended_queries`)。

### 一、 候选人结构化求职画像：
```json
{json.dumps(effective_profile, ensure_ascii=False, indent=2)}
```

### 二、 Python 词库匹配的 BOSS直聘 高频标准岗位词参考锚点：
`{", ".join(role_anchors)}`
- **当前锁定的首选目标城市**：`{primary_city}`（若候选人有多个意向城市 `{effective_profile["target_cities"]}`，以 `{primary_city}` 为主）
- **当前基准期望月薪底线**：`{base_salary}`
- **当前核心作息与福利诉求**：`{welfare_str}`{focus_instruction}

### 三、 预生成 5 条自然语言求职 Query 的严格规范：
1. **必须可直接用于 BOSS直聘 智能求职搜索框**：
   - 每条 `query_text` **必须写成流畅的一句话自然语言**，且严格包含以下 **4 个核心要素**：
     ① **具体城市名**（优先使用 `{primary_city}`）
     ② **在 BOSS直聘 上真实高频存在的简洁单一岗位名称**（2~7个字，如 `区域运营经理`、`服装店面督导`、`时尚买手`、`商品企划主管`、`品牌陈列督导`、`零售运营经理` 等；**严禁在一句话里用斜杠 `/` 或顿号拼接多个岗位名**！）
     ③ **明确的最低月薪底线**（以 `{base_salary}` 为基准，根据不同策略合理上下浮动，如 `月薪至少1.2w`、`月薪至少1.5w`）
     ④ **明确的作息与福利要求**（如 `周末双休，要交五险一金，最好有年终奖`）
2. **标准句式参考范例**：
   - `"深圳的区域运营经理岗位，月薪至少1.2w，周末双休，要交五险一金，最好有年终奖"`
   - `"深圳的服装店面督导，月薪至少1w，周末双休，要交五险一金"`
   - `"广州的连锁零售营运经理，月薪至少1.5w，周末双休，五险一金齐全，有年终奖"`
3. **5 大差异化求职策略维度（必须生成满 5 条，且每条的岗位名称或薪资梯度有明显区分度）**：
   - **策略 1 (`精准对口`)**：最贴合候选人核心头衔与过往行业的同级高频岗位 + 基准月薪 `{base_salary}` + `{welfare_str}`。
   - **策略 2 (`晋升冲刺`)**：结合候选人的管理经验或业绩亮点向上跃迁一级（如主管/经理/区域负责人），月薪底线在 `{base_salary}` 基础上合理上浮 20%~30%。
   - **策略 3 (`作息福利优选`)**：聚焦成熟连锁品牌总部或管理规范岗，强调稳定双休、五险一金与年终奖保障。
   - **策略 4 (`跨界拓展`)**：利用候选人的可迁移技能（`{", ".join(effective_profile.get("core_skills", [])[:4])}`），拓展到相邻高景气度赛道的对应岗位。
   - **策略 5 (`高薪突破`)**：面向高绩效回报的资深骨干或核心业务统筹岗，设定更具进取心的月薪底线。
4. **`match_reason` 撰写要求**：
   - 必须引用画像中的具体年限、技能或业绩亮点（40~80字），向候选人解释为什么推荐这个岗位方向与薪资标准。
"""

    try:
        raw_json = create_interaction_with_fallback(
            model=model_name,
            prompt=query_gen_prompt,
            schema_cls=ResumeQueryGenerationLLMOutput,
            temperature=0.35,
            api_key=api_key,
            proxy_url=proxy_url,
        )
        parsed_out = ResumeQueryGenerationLLMOutput.model_validate_json(raw_json)
        cleaned_queries = _sanitize_queries_list(parsed_out.recommended_queries)
        if not cleaned_queries:
            cleaned_queries = build_queries_from_profile_fallback(effective_profile)
        return {
            "model_used": model_name,
            "profile": effective_profile,
            "recommended_queries": cleaned_queries,
        }
    except Exception as exc:
        print(f"[ResumeParser-Stage2] Gemini 生成推荐 Query 异常，使用基于真实画像的策略兜底: {exc}")
        fallback_queries = build_queries_from_profile_fallback(effective_profile)
        return {
            "model_used": f"{model_name} (Query-Fallback)",
            "profile": effective_profile,
            "recommended_queries": fallback_queries,
        }


# ==============================================================================
# 组合式便捷入口（向后兼容：内部串联 Stage 1 + Stage 2）
# ==============================================================================
def parse_resume_with_gemini(
    filename: str,
    raw_bytes: bytes,
    model_name: str = "gemini-3.8-flash",
    api_key: Optional[str] = None,
    proxy_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    串联执行【阶段一：多模态简历画像提取】与【阶段二：基于画像生成 5 条定制化求职 Query】，
    保持对旧版单接口调用方的完全向后兼容。
    """
    stage1_res = extract_resume_profile_with_gemini(
        filename=filename,
        raw_bytes=raw_bytes,
        model_name=model_name,
        api_key=api_key,
        proxy_url=proxy_url,
    )
    stage2_res = generate_queries_from_profile_with_gemini(
        profile=stage1_res["profile"],
        model_name=model_name,
        api_key=api_key,
        proxy_url=proxy_url,
    )
    return {
        "filename": stage1_res["filename"],
        "model_used": stage2_res["model_used"],
        "profile": stage2_res["profile"],
        "recommended_queries": stage2_res["recommended_queries"],
    }
