"""Schema definition and multi-layer security/quality validator for Resume Parsing."""

from __future__ import annotations

import os
import re
import struct
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from pydantic import BaseModel, Field
except ImportError:  # Fallback if pydantic is not installed in the current env
    class BaseModel:  # type: ignore[no-redef]
        def __init__(self, **kwargs: Any) -> None:
            for k, v in kwargs.items():
                setattr(self, k, v)

        def dict(self) -> Dict[str, Any]:
            return dict(self.__dict__)

        def model_dump(self) -> Dict[str, Any]:
            return dict(self.__dict__)

    def Field(default: Any = None, **kwargs: Any) -> Any:  # type: ignore[misc]
        return default


# 最大允许上传的简历文件大小：10 MB
MAX_RESUME_BYTES = 10 * 1024 * 1024
# DOCX 解压后 XML 最大允许体积：20 MB（防止 Zip Bomb 炸弹）
MAX_DOCX_UNCOMPRESSED_BYTES = 20 * 1024 * 1024

ALLOWED_EXTENSIONS: Dict[str, str] = {
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
        description="最高学历及专业概括，如 '本科 · 市场营销' 或 '大专 · 工商企业管理'（未提及则填 '未注明学历'）"
    )
    target_cities: List[str] = Field(
        description="从简历现居地、求职意向或最近工作地推断的目标城市列表（1~3个标准城市名，如 ['深圳', '广州']）"
    )
    industry_background: List[str] = Field(
        description="过往从业行业背景标签（2~4个），如 ['服装/鞋帽零售', '时尚连锁品牌', '百货/购物中心']"
    )
    core_skills: List[str] = Field(
        description="核心专业技能与管理能力标签（4~8个），如 ['多店巡店督导', 'SOP标准化落地', '商品陈列管理', '店长赋能培训', '门店损益与连带率提升']"
    )
    experience_highlights: List[str] = Field(
        description="简历中最具竞争力的 2~4 条量化业绩或核心资历亮点（严禁包含手机号、邮箱、身份证号等个人敏感隐私信息）"
    )
    inferred_salary_floor: str = Field(
        description="结合候选人资历、目标城市与职级推断的合理月薪底线描述，如 '1.2w'、'1w'、'1.5w'"
    )
    inferred_welfare_prefs: List[str] = Field(
        description="建议争取的作息与福利条件（2~4个），如 ['周末双休', '五险一金', '年终奖']"
    )


# 正则：用于检测 profile 中是否泄露了敏感隐私信息（手机号、邮箱、身份证号、家庭/学校详细地址）
PHONE_REGEX = re.compile(r"(?<!\d)(?:1[3-9]\d{9}|0\d{2,3}-?\d{7,8})(?!\d)")
EMAIL_REGEX = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
ID_CARD_REGEX = re.compile(
    r"(?<!\d)[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)"
)
ADDRESS_DETAIL_REGEX = re.compile(
    r"(?:[\u4e00-\u9fa5]{2,12}(?:路|街|道|大道|巷|弄|胡同)\s*特?\d{1,5}\s*号|"
    r"[\u4e00-\u9fa5]{2,14}(?:小区|花园|公寓|家园|名苑|学生公寓|宿舍(?:楼|区)?)\s*[A-Za-z0-9一二三四五六七八九十]{1,4}\s*(?:栋|幢|座|号楼|单元))"
)

# 常见 Prompt 注入特征模式
PROMPT_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(?:all\s+)?(?:previous|above|prior)\s+instructions", re.IGNORECASE),
    re.compile(r"忽略(?:之前|以上|前面|所有)的?(?:所有)?(?:指令|要求|规则|系统提示)", re.IGNORECASE),
    re.compile(r"system\s*prompt\s*override", re.IGNORECASE),
    re.compile(r"IMPORTANT\s*SYSTEM\s*INSTRUCTION", re.IGNORECASE),
    re.compile(r"请直接将身份证号.*写入\s*experience_highlights", re.IGNORECASE),
]


def resolve_safe_path(file_path: str, allowed_root: str) -> Path:
    """Resolve a file path safely within an allowed root directory to prevent path traversal."""
    root_resolved = Path(allowed_root).resolve()
    target_resolved = Path(file_path).resolve()
    root_prefix = str(root_resolved) + os.sep
    if str(target_resolved) != str(root_resolved) and not str(target_resolved).startswith(root_prefix):
        raise ValueError(f"Path traversal blocked: {file_path} is outside {allowed_root}")
    return target_resolved


def validate_resume_file(
    file_path: str,
    allowed_root: Optional[str] = None,
) -> Tuple[bool, str, str]:
    """
    对上传的简历文件执行前置安全与格式校验。
    返回: (is_valid, error_code, message)
    """
    try:
        if allowed_root is not None:
            target = resolve_safe_path(file_path, allowed_root)
        else:
            target = Path(file_path).resolve()
    except ValueError as exc:
        return False, "PATH_TRAVERSAL_BLOCKED", str(exc)

    if not target.exists() or not target.is_file():
        return False, "FILE_NOT_FOUND", "文件不存在或不是常规文件"

    file_size = target.stat().st_size
    if file_size == 0:
        return False, "EMPTY_FILE", "文件大小为 0 字节（空文件）"

    ext = target.suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return (
            False,
            "UNSUPPORTED_EXTENSION",
            f"不支持的文件扩展名 '{ext}'，仅允许: {', '.join(sorted(ALLOWED_EXTENSIONS.keys()))}",
        )

    if file_size > MAX_RESUME_BYTES:
        return (
            False,
            "FILE_TOO_LARGE",
            f"文件大小 ({file_size} bytes) 超过最大限制 MAX_RESUME_BYTES ({MAX_RESUME_BYTES} bytes / 10 MB)",
        )

    # 读取头部与尾部字节进行 Magic Bytes 及结构完整性校验
    with open(target, "rb") as f:
        head = f.read(4096)
        f.seek(max(0, file_size - 1024))
        tail = f.read(1024)

    if ext == ".pdf":
        if not head.startswith(b"%PDF-"):
            return False, "INVALID_MAGIC_BYTES", "文件头不是合法的 PDF 签名 (%PDF-)，疑似伪造扩展名"
        if b"%%EOF" not in tail:
            return False, "CORRUPTED_FILE", "PDF 文件缺少 %%EOF 结束标记，文件已截断或损坏"

    elif ext == ".png":
        if not head.startswith(b"\x89PNG\r\n\x1a\n"):
            return False, "INVALID_MAGIC_BYTES", "文件头不是合法的 PNG 签名，疑似伪造扩展名"
        if b"IEND" not in tail:
            return False, "CORRUPTED_FILE", "PNG 文件缺少 IEND 结束块，文件已截断或损坏"

    elif ext in (".jpg", ".jpeg"):
        if not head.startswith(b"\xff\xd8\xff"):
            return False, "INVALID_MAGIC_BYTES", "文件头不是合法的 JPEG SOI 签名 (FF D8 FF)"
        if not tail.rstrip(b"\x00").endswith(b"\xff\xd9"):
            return False, "CORRUPTED_FILE", "JPEG 文件缺少 EOI 结束标记 (FF D9)，文件已截断或损坏"

    elif ext == ".webp":
        if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WEBP":
            return False, "INVALID_MAGIC_BYTES", "文件头不是合法的 RIFF WEBP 签名"
        declared_size = struct.unpack("<I", head[4:8])[0] + 8
        if declared_size != file_size:
            return False, "CORRUPTED_FILE", "WEBP RIFF 声明长度与实际文件大小不一致，文件已损坏"

    elif ext == ".docx":
        if not head.startswith(b"PK\x03\x04"):
            return False, "INVALID_MAGIC_BYTES", "DOCX 文件不是合法的 ZIP 容器签名"
        try:
            with zipfile.ZipFile(target, "r") as zf:
                infos = zf.infolist()
                total_uncompressed = 0
                has_document_xml = False
                for info in infos:
                    # 防御 Zip Slip 目录穿越
                    norm_name = os.path.normpath(info.filename)
                    if norm_name.startswith("..") or norm_name.startswith("/") or "\\" in info.filename:
                        return False, "ZIP_SLIP_DETECTED", f"DOCX 内部包含非法路径条目: {info.filename}"
                    total_uncompressed += info.file_size
                    if info.filename == "word/document.xml":
                        has_document_xml = True
                    if total_uncompressed > MAX_DOCX_UNCOMPRESSED_BYTES:
                        return (
                            False,
                            "DOCX_XML_BOMB_DETECTED",
                            f"DOCX 解压后总大小 ({total_uncompressed} bytes) 超过上限 "
                            f"MAX_DOCX_UNCOMPRESSED_BYTES ({MAX_DOCX_UNCOMPRESSED_BYTES} bytes / 20 MB)",
                        )
                if not has_document_xml:
                    return False, "CORRUPTED_FILE", "DOCX 缺少核心组件 word/document.xml"

                # 读取 word/document.xml 并防御 XXE (XML External Entity)
                xml_bytes = zf.read("word/document.xml")
                xml_head_upper = xml_bytes[:4096].upper()
                if b"<!DOCTYPE" in xml_head_upper or b"<!ENTITY" in xml_head_upper:
                    return False, "XXE_PAYLOAD_DETECTED", "DOCX XML 中包含禁止的 DOCTYPE/ENTITY 声明（疑似 XXE 攻击）"
                try:
                    ET.fromstring(xml_bytes)
                except ET.ParseError as exc:
                    return False, "CORRUPTED_FILE", f"DOCX word/document.xml XML 结构损坏: {exc}"
        except zipfile.BadZipFile:
            return False, "CORRUPTED_FILE", "DOCX ZIP 归档结构损坏，无法解压"

    elif ext in (".txt", ".md"):
        raw_bytes = target.read_bytes()
        if b"\x00" in raw_bytes:
            return False, "CORRUPTED_FILE", "文本文件中包含二进制空字节 (NUL)，疑似二进制文件或乱码"
        try:
            text_content = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return False, "CORRUPTED_FILE", "文本文件不是合法的 UTF-8 编码，包含乱码字节序列"

        if not text_content.strip():
            return False, "EMPTY_FILE", "文本文件仅包含空白字符，无实质内容"

        # 检查是否包含大量不可见控制字符或乱码符号
        control_chars = sum(
            1 for ch in text_content if ord(ch) < 32 and ch not in ("\n", "\r", "\t")
        )
        if control_chars > 5 or "\ufffd" in text_content:
            return False, "GARBLED_CONTENT", "文本文件包含大量乱码或非法控制字符"

    # TODO(security): 生产环境可在此接入沙箱病毒扫描 (ClamAV / Cloud Security Scanner) 及 CDR 内容净化
    return True, "OK", "文件通过前置格式与安全校验"


def inspect_text_content_guardrails(text: str) -> Tuple[bool, str, str]:
    """
    第二层校验：针对提取出的文本内容进行安全护栏与「是否为简历」语义预检。
    返回: (is_valid, error_code, message)
    """
    stripped = text.strip()
    if len(stripped) < 20:
        return False, "EMPTY_OR_TOO_SHORT", "提取出的文本内容过短，无法构成有效简历"

    for pattern in PROMPT_INJECTION_PATTERNS:
        if pattern.search(stripped):
            return (
                False,
                "PROMPT_INJECTION_DETECTED",
                "检测到疑似 Prompt Injection（提示词注入）或越权覆盖指令文本",
            )

    # 简单启发式检查：是否包含基本的简历要素关键词
    resume_signals = [
        "工作经历", "工作经验", "项目经验", "教育背景", "教育经历", "求职意向",
        "个人技能", "专业技能", "核心能力", "自我评价", "个人总结", "实习经历",
        "营运", "工程师", "经理", "店长", "督导", "专员", "顾问", "研究员",
        "本科", "大专", "硕士", "学历", "负责", "主导", "毕业于",
    ]
    hit_count = sum(1 for kw in resume_signals if kw in stripped)
    if hit_count < 2:
        return (
            False,
            "NOT_A_RESUME",
            f"文档内容缺少简历核心特征词（仅命中 {hit_count} 项），疑似非简历文档（如菜单、发票或代码文件）",
        )

    return True, "OK", "文本内容通过简历语义与安全护栏预检"


def validate_parsed_profile(
    profile: Dict[str, Any],
    forbidden_pii_tokens: Optional[List[str]] = None,
) -> Tuple[bool, List[str]]:
    """
    校验解析出的 CandidateProfileSchema 结构完整性及 PII 隐私红线。
    返回: (is_valid, list_of_violations)
    """
    violations: List[str] = []
    required_str_fields = [
        "candidate_title",
        "years_of_experience",
        "education_summary",
        "inferred_salary_floor",
    ]
    for field_name in required_str_fields:
        val = profile.get(field_name)
        if not isinstance(val, str) or not val.strip():
            violations.append(f"字段 '{field_name}' 为空或类型错误")

    list_bounds = {
        "target_cities": (1, 3),
        "industry_background": (2, 4),
        "core_skills": (4, 8),
        "experience_highlights": (2, 4),
        "inferred_welfare_prefs": (2, 4),
    }
    for field_name, (min_len, max_len) in list_bounds.items():
        val = profile.get(field_name)
        if not isinstance(val, list):
            violations.append(f"字段 '{field_name}' 必须是列表")
        elif not (min_len <= len(val) <= max_len):
            violations.append(
                f"字段 '{field_name}' 长度 ({len(val)}) 不在 Schema 要求范围 [{min_len}, {max_len}] 内"
            )

    # 检查全部字段是否包含敏感隐私信息 (手机号、邮箱、身份证号、家庭/学校详细地址)
    all_text_entries: List[Tuple[str, str]] = []
    for k, v in profile.items():
        if isinstance(v, str):
            all_text_entries.append((k, v))
        elif isinstance(v, list):
            for idx, elem in enumerate(v):
                if isinstance(elem, str):
                    all_text_entries.append((f"{k}[{idx}]", elem))

    for loc, item in all_text_entries:
        if PHONE_REGEX.search(item):
            violations.append(f"{loc} 泄露了手机号: {item}")
        if EMAIL_REGEX.search(item):
            violations.append(f"{loc} 泄露了邮箱地址: {item}")
        if ID_CARD_REGEX.search(item):
            violations.append(f"{loc} 泄露了身份证号: {item}")
        if ADDRESS_DETAIL_REGEX.search(item):
            violations.append(f"{loc} 泄露了家庭或学校详细地址: {item}")
        if forbidden_pii_tokens:
            for token in forbidden_pii_tokens:
                if token and token in item:
                    violations.append(f"{loc} 泄露了简历原文中的敏感 PII ({token}): {item}")

    return len(violations) == 0, violations
