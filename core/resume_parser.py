"""
阶段一独立服务：智能简历多模态解析与结构化求职画像提取引擎 (Stage 1: Resume Multimodal Parser)
架构设计（与 Stage 2 `core/query_generator.py` 完全解耦）：
1. 安全网关层：严格遵循安全规范校验上传的简历文件（10MB 大小上限 + 扩展名白名单 + 文件头 Magic Bytes 校验 + 防 Zip Bomb / XXE + 本地正则 PII 脱敏）。
2. 阶段一（独立服务 `extract_resume_profile_with_gemini`）：
   - 利用 Gemini Interactions API (`client.interactions.create`) 原生多模态能力（默认 `gemini-3.8-flash`，`temperature=0.1` 收敛型事实抽取）：
     * PDF 简历 (`.pdf`)：直接以 `DocumentContent` (`application/pdf`) 送入 Gemini 视觉+文档理解；
     * 图片简历 (`.png` / `.jpg` / `.jpeg` / `.webp`)：直接以 `ImageContent` 送入 Gemini 视觉理解；
     * Word / 文本简历 (`.docx` / `.txt` / `.md`)：在内存中安全提取纯文本并脱敏后送入 Gemini。
   - 输出经 Python 确定性校准与二次脱敏的结构化求职画像 (`CandidateProfileSchema`)。
   - 阶段二（多策略求职 Query 生成）已完全解耦至独立模块 `core/query_generator.py`。
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
        description="若简历中明确提到求职岗位/应聘岗位/求职意向，则优先提取该岗位；若未明确提及，则结合候选人最近 1~2 份工作的核心岗位提炼出精准的专业头衔"
    )
    years_of_experience: str = Field(
        description="工作年限与核心资历概括，如 '5年连锁零售门店督导与团队管理经验'"
    )
    education_summary: str = Field(
        description="完整提取简历中提及的所有高等教育学历阶段（如同时提到本科、硕士研究生或最高的博士，必须全部抓取并包含学历等级、专业与毕业院校，例如 '硕士 · 国际经济与贸易（华中师范大学）｜学士 · 对外汉语（广州科技大学）'；严禁包含学校详细街道门牌地址或宿舍楼号）"
    )
    target_cities: List[str] = Field(
        description="从简历现居地、求职意向或过往工作地提取的目标城市列表（仅保留1~3个市级标准城市名，如 ['深圳', '广州']；若完全未提及具体城市，请以最高学历的毕业院校所在城市填写；严禁包含家庭住址或学校详细地址）"
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
    seen_lines = set()
    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag == "p":
            # Skip outer <w:p> containers that wrap drawing textboxes with nested <w:p> elements
            nested_p_count = sum(
                1 for sub in elem.iter()
                if sub is not elem and (sub.tag.split("}")[-1] if "}" in sub.tag else sub.tag) == "p"
            )
            if nested_p_count > 0:
                continue
            texts: List[str] = []
            for child in elem.iter():
                c_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if c_tag == "t" and child.text:
                    texts.append(child.text)
                elif c_tag == "tab":
                    texts.append("  ")
            line = "".join(texts).strip()
            if line and line not in seen_lines:
                seen_lines.add(line)
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
   - **若简历中明确提到求职岗位（如“求职意向”、“应聘岗位”、“求职岗位”），则直接提取该岗位**（可结合核心经历并列补充细分方向）；
   - **若简历中没有明确提到求职岗位，则结合候选人最近 1~2 份工作的核心岗位与求职意向，提炼出精准的专业头衔**（切勿随意虚构或拔高职级）。
2. **工作年限与资历概括 (`years_of_experience`)**：
   - 根据简历中的工作时间线准确核算总工作年限与核心资历（若仅有在校实习经历则明确标注为 `"应届毕业生 / 具备...实习经验"`）。
3. **完整高等教育背景 (`education_summary`)**：
   - **不光要提取最高学历，如果简历中有提到本科和硕士研究生，或者最高的博士，必须全部抓取到**！
   - 请完整保留每个高等教育阶段的 **学历等级、专业名称与毕业院校名称**（例如：`"硕士 · 国际经济与贸易（华中师范大学）｜学士 · 对外汉语（广州科技大学）"` 或 `"本科 · 市场营销（中国社会大学）"`；若未提及则填 `"未注明学历"`；**切勿包含学校所在的详细街道地址、校区门牌号或宿舍楼号**）。
4. **意向城市 (`target_cities`)**：
   - 从简历中的求职意向城市、现居地或过往工作地点提取 1~3 个**市级标准城市名**（如 `["上海"]` 或 `["武汉", "广州"]`）；
   - **若简历中完全未提及具体现居城市、求职城市或工作城市，请务必以候选人最高学历的毕业院校所在城市填写**（例如院校为华中师范大学则填 `["武汉"]`，四川大学则填 `["成都"]`）；
   - **若简历写有详细的家庭住址或学校地址，仅允许提取市级城市名，严禁保留区县街道、小区楼栋或门牌号**。
5. **过往行业背景 (`industry_background`)**：
   - 提炼 2~4 个精准的细分行业标签（如 `["互联网/新媒体", "市场营销/品牌传播"]`）。
6. **核心专业技能与管理能力 (`core_skills`)**：
   - 全面提炼 4~8 个最具代表性的硬技能、技术工具、语言/专业证书与业务管理能力标签（切勿遗漏简历中明确列出的编程语言、数据库、设计软件或英语/计算机等级证书）。
7. **量化业绩与核心资历亮点 (`experience_highlights`)**：
   - 提取简历中最有说服力的 2~4 条量化业务成果、管理半径、代表性项目亮点或重要竞赛奖学金荣誉（**所有关键数字、职务名称如“项目经理”必须 100% 忠于简历原文，严禁篡改、降级或夸大**）。
   - **隐私红线：严禁在 `profile` 的任何输出字段中包含候选人的真实姓名、手机号码、电子邮箱、身份证号，以及家庭详细住址（街道/路名/小区/楼栋/室号）或学校详细地址（校区街道门牌/宿舍号）！**
8. **合理月薪底线 (`inferred_salary_floor`) 与福利偏好 (`inferred_welfare_prefs`)**：
   - **若简历中明确写出了期望薪资具体金额（如 `6K-7K`），必须严格采用简历中的薪资下限（如 `"0.6w"`）**；若未写明，请结合候选人工作年限、职级与所在城市水平推断合理的期望月薪底线（统一格式如 `"0.8w"`、`"1w"`、`"1.2w"`、`"1.5w"`）。
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
# 组合式便捷入口（向后兼容：内部串联 Stage 1 + 独立解耦的 Stage 2 `core.query_generator`）
# ==============================================================================
def parse_resume_with_gemini(
    filename: str,
    raw_bytes: bytes,
    model_name: str = "gemini-3.8-flash",
    api_key: Optional[str] = None,
    proxy_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    串联执行【阶段一：多模态简历画像提取 (`core.resume_parser`)】与
    【阶段二：基于画像生成 10 条定制化求职 Query (`core.query_generator`)】，
    保持对旧版单接口调用方的完全向后兼容。
    """
    from core.query_generator import generate_queries_from_profile_with_gemini

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
        "temperature_used": stage2_res.get("temperature_used", 0.4),
        "query_count": stage2_res.get("query_count", len(stage2_res["recommended_queries"])),
        "profile": stage2_res["profile"],
        "recommended_queries": stage2_res["recommended_queries"],
    }
