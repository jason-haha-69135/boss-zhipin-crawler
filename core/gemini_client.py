"""
基于 Interactions API 的智能自适应 Gemini 客户端 (Gemini Interactions API Client)
核心特性：
1. 全面采用 Google GenAI Interactions API (`client.interactions.create(...)`) 进行模型交互。
2. 原生支持用户指定的四大模型：
   - Gemini 3.8 Flash (`gemini-3.8-flash`)
   - Gemini 3.5 Flash Light (`gemini-3.5-flash-lite`)
   - Gemini 3.1 Pro (`gemini-3.1-pro-preview` / `gemini-3.1-pro`)
   - Gemini 4 Argon (`gemini-4-argon`)
3. 针对本地与云端环境提供双通道自适应路由：
   - 通道 A【GCP Vertex AI Global Endpoint (`aiplatform.googleapis.com`, `location="global"`)】：
     自动加载本机 `gcloud` 激活账号或本地运行时配置的 OAuth ADC 凭证。
     Vertex AI 企业级端点支持全球统一调用，无需第三方代理即可直连。
   - 通道 B【Google AI Studio (`generativelanguage.googleapis.com`)】：
     使用 API Key 调用，支持显式传入或自动探测本机代理端口 (7890/7897/6152/1087 等)。
4. 彻底解决 macOS Python 3.14 SSL 证书链缺失 (`CERTIFICATE_VERIFY_FAILED`) 及客户端证书冲突：
   - 自动注入 `certifi` 与 macOS `/etc/ssl/cert.pem` 根证书链；
   - 自动设置 `GOOGLE_API_USE_CLIENT_CERTIFICATE="false"` 避免客户端证书冲突；
   - 若遇代理/网关自签名证书导致 `CERTIFICATE_VERIFY_FAILED`，自动降级 `verify_ssl=False` 重试。
"""

import base64
import configparser
import copy
import json
import os
import re
import socket
import ssl
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Type, Union

import certifi

# 强制为 macOS Python 3.14 注入根证书路径，并禁用 Corp Mac mTLS 客户端证书避免 Vertex AI 报错
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
os.environ.setdefault("CURL_CA_BUNDLE", certifi.where())
os.environ["GOOGLE_API_USE_CLIENT_CERTIFICATE"] = "false"

import google.auth
from google import genai
from google.genai import types
from pydantic import BaseModel

DEFAULT_GCP_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
DEFAULT_GCLOUD_ACCOUNT = os.environ.get("GCLOUD_ACCOUNT", "")

# 全局默认模型配置常量（支持环境变量覆盖）
DEFAULT_STAGE1_EXTRACT_MODEL: str = os.environ.get("STAGE1_EXTRACT_MODEL", "gemini-3.8-flash")
DEFAULT_LLM_JUDGE_MODEL: str = os.environ.get("LLM_JUDGE_MODEL", "gemini-4-argon")

# 支持的四大核心模型定义与候选回退链
MODEL_CANDIDATES_MAP: Dict[str, List[str]] = {
    "gemini-3.8-flash": [
        "gemini-3.8-flash",
        "gemini-2.5-flash",
        "gemini-flash-latest",
        "gemini-2.0-flash",
    ],
    "gemini-3.5-flash-lite": [
        "gemini-3.5-flash-lite",
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash",
        "gemini-3.8-flash",
    ],
    "gemini-3.1-pro": [
        "gemini-3.1-pro-preview",
        "gemini-3.1-pro",
        "gemini-2.5-pro",
        "gemini-3.8-flash",
    ],
    "gemini-4-argon": [
        "gemini-4-argon",
        "gemini-2.5-pro",
        "gemini-3.8-flash",
    ],
}

# 运行时已验证成功的 (backend, requested_model) -> actual_model 缓存
_RESOLVED_MODEL_CACHE: Dict[Tuple[str, str], str] = {}
# 运行时已验证成功的优先通道 ("vertex" 或 "aistudio")
_PREFERRED_CHANNEL: Optional[str] = None

# 本机常见代理软件默认 HTTP 端口（Clash / Clash Verge / Surge / V2RayU / Shadowsocks / Sing-box）
COMMON_LOCAL_PROXIES: List[str] = [
    "http://127.0.0.1:7890",
    "http://127.0.0.1:7897",
    "http://127.0.0.1:7891",
    "http://127.0.0.1:6152",
    "http://127.0.0.1:1087",
    "http://127.0.0.1:10809",
    "http://127.0.0.1:10808",
    "http://127.0.0.1:1080",
    "http://127.0.0.1:8888",
    "http://127.0.0.1:2080",
]


def clean_json_schema(schema_cls: Type[BaseModel]) -> Dict[str, Any]:
    """
    将 Pydantic BaseModel 的 JSON Schema 展开内联 ($defs / $ref)，
    生成适配 Interactions API `response_format` 的纯平 JSON Schema。
    """
    raw_schema = copy.deepcopy(schema_cls.model_json_schema())
    defs = raw_schema.pop("$defs", {})

    def _resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                ref_path = node["$ref"]
                ref_name = ref_path.split("/")[-1]
                target = copy.deepcopy(defs.get(ref_name, {}))
                return _resolve(target)
            cleaned: Dict[str, Any] = {}
            for k, v in node.items():
                if k in ("title", "$defs"):
                    continue
                cleaned[k] = _resolve(v)
            return cleaned
        if isinstance(node, list):
            return [_resolve(item) for item in node]
        return node

    return _resolve(raw_schema)


def strip_markdown_json(raw_text: str) -> str:
    """清理模型输出可能附带的 ```json ... ``` 代码块包裹"""
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def extract_interaction_text(interaction: Any) -> str:
    """从 Interactions API 返回的 Interaction 对象中提取输出文本"""
    output_text = getattr(interaction, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return strip_markdown_json(output_text)

    # 兜底：从 interaction.steps 中提取最后一个 model_output 的文本块
    steps = getattr(interaction, "steps", None) or []
    collected: List[str] = []
    for step in steps:
        step_type = getattr(step, "type", None) or (
            step.get("type") if isinstance(step, dict) else None
        )
        if step_type == "model_output":
            content_list = getattr(step, "content", None) or (
                step.get("content") if isinstance(step, dict) else []
            )
            for item in content_list or []:
                item_type = getattr(item, "type", None) or (
                    item.get("type") if isinstance(item, dict) else None
                )
                if item_type == "text":
                    txt = getattr(item, "text", None) or (
                        item.get("text") if isinstance(item, dict) else ""
                    )
                    if txt:
                        collected.append(txt)
    if collected:
        return strip_markdown_json("".join(collected))
    raise ValueError(
        f"Interactions API 未返回有效文本内容 (status={getattr(interaction, 'status', 'unknown')})"
    )


def _get_gcloud_active_config() -> Tuple[str, str]:
    """读取 ~/.config/gcloud/configurations/config_default 中的激活账号与项目"""
    account = os.environ.get("GCLOUD_ACCOUNT", "").strip() or DEFAULT_GCLOUD_ACCOUNT
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip() or DEFAULT_GCP_PROJECT
    cfg_path = os.path.expanduser("~/.config/gcloud/configurations/config_default")
    if os.path.isfile(cfg_path):
        try:
            parser = configparser.ConfigParser()
            parser.read(cfg_path, encoding="utf-8")
            if parser.has_option("core", "account"):
                acc = parser.get("core", "account").strip()
                if acc:
                    account = acc
            if parser.has_option("core", "project"):
                proj = parser.get("core", "project").strip()
                if proj:
                    project = proj
        except Exception:
            pass
    return account, project


def load_vertex_credential_candidates() -> List[Tuple[Any, str]]:
    """
    加载本机候选 GCP 账号的 OAuth ADC 凭证与所属 Project 列表供 Vertex AI (`aiplatform.googleapis.com`) 使用。
    按优先级依次尝试：
    1. `.gemini_runtime.json` 中配置的 `(account, project, adc)` 绑定对
    2. `~/.config/gcloud/application_default_credentials.json`
    """
    candidates: List[Tuple[Any, str]] = []
    from google.oauth2 import credentials as oauth2_credentials

    runtime_file = Path(__file__).resolve().parent.parent / ".gemini_runtime.json"
    if runtime_file.is_file():
        try:
            data = json.loads(runtime_file.read_text(encoding="utf-8"))
            for item in data.get("vertex_adc_candidates", []) or []:
                adc_info = item.get("adc")
                proj = str(item.get("project", "")).strip()
                if isinstance(adc_info, dict) and adc_info.get("refresh_token") and proj:
                    creds = oauth2_credentials.Credentials.from_authorized_user_info(
                        adc_info,
                        scopes=["https://www.googleapis.com/auth/cloud-platform"],
                    )
                    candidates.append((creds, proj))
        except Exception:
            pass

    account, project = _get_gcloud_active_config()
    account_project_pairs = [
        (
            os.path.expanduser("~/.config/gcloud/application_default_credentials.json"),
            project or DEFAULT_GCP_PROJECT,
        ),
        (
            os.path.expanduser("~/.config/gcloud/application_default_credentials.json"),
            DEFAULT_GCP_PROJECT,
        ),
    ]
    for adc_file, target_proj in account_project_pairs:
        if os.path.isfile(adc_file):
            try:
                creds, _ = google.auth.load_credentials_from_file(
                    adc_file,
                    scopes=["https://www.googleapis.com/auth/cloud-platform"],
                    quota_project_id=target_proj,
                )
                candidates.append((creds, target_proj))
            except Exception:
                continue

    return candidates


def load_vertex_credentials() -> Tuple[Optional[Any], str]:
    """返回首选的 Vertex AI (credentials, project) 元组"""
    cands = load_vertex_credential_candidates()
    if cands:
        return cands[0]
    return None, DEFAULT_GCP_PROJECT


def load_backend_api_key(explicit_key: Optional[str] = None) -> Optional[str]:
    """从后端环境变量或后端私有配置文件 (.gemini_runtime.json) 读取 API Key，不在前端 UI 暴露"""
    if explicit_key and explicit_key.strip():
        return explicit_key.strip()
    env_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if env_key:
        return env_key
    runtime_file = Path(__file__).resolve().parent.parent / ".gemini_runtime.json"
    if runtime_file.is_file():
        try:
            data = json.loads(runtime_file.read_text(encoding="utf-8"))
            k = str(data.get("api_key", "")).strip()
            if k:
                return k
        except Exception:
            pass
    return None


def has_vertex_auth_available() -> bool:
    """检查本机是否具备可用的 Vertex AI ADC 凭证或后端 API Key"""
    creds, _ = load_vertex_credentials()
    return creds is not None or bool(load_backend_api_key())


def _detect_macos_scutil_proxy() -> Optional[str]:
    """从 macOS `scutil --proxy` 读取系统当前启用的 HTTPS/HTTP 代理"""
    try:
        proc = subprocess.run(
            ["scutil", "--proxy"],
            capture_output=True,
            text=True,
            timeout=1.0,
            check=False,
        )
        out = proc.stdout or ""
        https_enable = re.search(r"HTTPSEnable\s*:\s*(\d+)", out)
        https_proxy = re.search(r"HTTPSProxy\s*:\s*([^\s]+)", out)
        https_port = re.search(r"HTTPSPort\s*:\s*(\d+)", out)
        if (
            https_enable
            and https_enable.group(1) == "1"
            and https_proxy
            and https_port
        ):
            return f"http://{https_proxy.group(1)}:{https_port.group(1)}"

        http_enable = re.search(r"HTTPEnable\s*:\s*(\d+)", out)
        http_proxy = re.search(r"HTTPProxy\s*:\s*([^\s]+)", out)
        http_port = re.search(r"HTTPPort\s*:\s*(\d+)", out)
        if (
            http_enable
            and http_enable.group(1) == "1"
            and http_proxy
            and http_port
        ):
            return f"http://{http_proxy.group(1)}:{http_port.group(1)}"
    except Exception:
        pass
    return None


def detect_local_proxy() -> Optional[str]:
    """探测环境变量、macOS 系统代理或本机正在监听的常见代理端口"""
    env_proxy = (
        os.environ.get("GEMINI_PROXY", "").strip()
        or os.environ.get("HTTPS_PROXY", "").strip()
        or os.environ.get("https_proxy", "").strip()
        or os.environ.get("HTTP_PROXY", "").strip()
        or os.environ.get("http_proxy", "").strip()
        or os.environ.get("ALL_PROXY", "").strip()
    )
    if env_proxy:
        return env_proxy

    sys_proxy = _detect_macos_scutil_proxy()
    if sys_proxy:
        return sys_proxy

    for proxy_url in COMMON_LOCAL_PROXIES:
        try:
            host_port = proxy_url.split("://", 1)[1]
            host, port_str = host_port.split(":", 1)
            with socket.create_connection((host, int(port_str)), timeout=0.12):
                return proxy_url
        except OSError:
            continue
    return None


def build_ssl_context(verify_ssl: bool = True) -> ssl.SSLContext:
    """
    构建兼容 macOS Python 3.14 与本地代理的 SSLContext：
    - verify_ssl=True 时同时加载 certifi 根证书与 macOS /etc/ssl/cert.pem；
    - verify_ssl=False 时跳过证书校验（用于本地代理开启 MITM 自签名证书的场景）。
    """
    if not verify_ssl:
        return ssl._create_unverified_context()

    ctx = ssl.create_default_context(cafile=certifi.where())
    if os.path.exists("/etc/ssl/cert.pem"):
        try:
            ctx.load_verify_locations(cafile="/etc/ssl/cert.pem")
        except Exception:
            pass
    return ctx


def build_http_options(
    proxy_url: Optional[str] = None,
    verify_ssl: bool = True,
) -> types.HttpOptions:
    """构建 genai.Client 所需的 HttpOptions（显式传入 SSLContext 防止 macOS Python 3.14 证书报错）"""
    client_args: Dict[str, Any] = {
        "verify": build_ssl_context(verify_ssl=verify_ssl),
    }
    effective_proxy = (proxy_url or "").strip()
    if effective_proxy:
        client_args["proxy"] = effective_proxy
    return types.HttpOptions(client_args=client_args)


def get_candidate_models(requested_model: str, backend: str = "vertex") -> List[str]:
    """获取指定模型的尝试队列"""
    candidates: List[str] = []
    cache_key = (backend, requested_model)
    if cache_key in _RESOLVED_MODEL_CACHE:
        candidates.append(_RESOLVED_MODEL_CACHE[cache_key])

    chain = MODEL_CANDIDATES_MAP.get(
        requested_model, [requested_model, "gemini-3.8-flash"]
    )
    for m in chain:
        if m and m not in candidates:
            candidates.append(m)
    return candidates


def _convert_prompt_for_generate_content(prompt: Union[str, List[Dict[str, Any]]]) -> Any:
    """将 Interactions API 的多模态输入列表转换为 generate_content 兼容的 contents 列表"""
    if isinstance(prompt, str):
        return prompt
    parts: List[Any] = []
    for item in prompt:
        if not isinstance(item, dict):
            parts.append(str(item))
            continue
        itype = item.get("type", "")
        if itype in ("document", "image") and item.get("data"):
            raw_bytes = base64.b64decode(item["data"])
            parts.append(
                types.Part.from_bytes(
                    data=raw_bytes,
                    mime_type=item.get("mime_type", "application/pdf"),
                )
            )
        elif itype == "text":
            parts.append(str(item.get("text", "")))
    return parts


def create_interaction_with_fallback(
    model: str,
    prompt: Union[str, List[Dict[str, Any]]],
    schema_cls: Type[BaseModel],
    temperature: float = 0.2,
    api_key: Optional[str] = None,
    proxy_url: Optional[str] = None,
) -> str:
    """
    使用 Google GenAI Interactions API (`client.interactions.create`) 调用 Gemini 模型：
    1. 支持纯文本 `prompt: str` 以及多模态内容块列表 `List[Dict[str, Any]]`
       （如 `{"type": "document", "data": base64, "mime_type": "application/pdf"}` 或 `{"type": "image", ...}`）。
    2. 支持四大模型：`gemini-3.8-flash` / `gemini-3.5-flash-lite` / `gemini-3.1-pro` / `gemini-4-argon`
    3. 在中国大陆 + Google Corp VPN 环境下，优先或自动切换至 GCP Vertex AI (`location="global"`)，
       彻底绕开 AI Studio (`generativelanguage.googleapis.com`) 的地理位置封锁 (`400 User location is not supported`)。
    4. 若遇到 SSL 证书错误 (`CERTIFICATE_VERIFY_FAILED`)，自动降级 `verify_ssl=False` 重试。
    """
    global _PREFERRED_CHANNEL
    json_schema = clean_json_schema(schema_cls)
    effective_api_key = load_backend_api_key(api_key)
    effective_proxy = (proxy_url or "").strip() or detect_local_proxy()
    vertex_cred_candidates = load_vertex_credential_candidates()
    creds = vertex_cred_candidates[0][0] if vertex_cred_candidates else None
    errors: List[str] = []

    def _try_vertex_channel(px: Optional[str] = None) -> Optional[str]:
        global _PREFERRED_CHANNEL
        if not vertex_cred_candidates:
            return None

        vertex_candidates = get_candidate_models(model, backend="vertex")
        for cred_item, proj_item in vertex_cred_candidates:
            cred_expired = False
            for verify_flag in (True, False):
                client = genai.Client(
                    vertexai=True,
                    project=proj_item,
                    location="global",
                    credentials=cred_item,
                    http_options=build_http_options(proxy_url=px, verify_ssl=verify_flag),
                )
                ssl_tag = "" if verify_flag else ", SSL-Unverified"
                px_tag = f", Proxy={px}" if px else ""
                channel_label = f"VertexAI(project={proj_item}, loc=global{px_tag}{ssl_tag})"
                need_ssl_retry = False

                interactions_iam_denied = False
                for cand_model in vertex_candidates:
                    if not interactions_iam_denied:
                        try:
                            print(
                                f"[GeminiInteractions] 正在通过 [{channel_label}] 调用 Interactions API: model={cand_model} ..."
                            )
                            interaction = client.interactions.create(
                                model=cand_model,
                                input=prompt,
                                response_format=json_schema,
                                response_mime_type="application/json",
                                generation_config={"temperature": temperature},
                            )
                            text_out = extract_interaction_text(interaction)
                            _RESOLVED_MODEL_CACHE[("vertex", model)] = cand_model
                            _PREFERRED_CHANNEL = "vertex"
                            print(
                                f"[GeminiInteractions] Vertex AI Interactions 调用成功: model={cand_model} (id={getattr(interaction, 'id', 'N/A')})"
                            )
                            return text_out
                        except Exception as exc:
                            err_str = str(exc)
                            errors.append(f"[{channel_label}:{cand_model}]: {err_str}")
                            if "Reauthentication is needed" in err_str or "invalid_grant" in err_str:
                                cred_expired = True
                                break
                            if "aiplatform.interactions.create" in err_str or "PERMISSION_DENIED" in err_str:
                                interactions_iam_denied = True
                            elif (
                                "CERTIFICATE_VERIFY_FAILED" in err_str
                                or "SSLCertVerificationError" in err_str
                                or "SSL" in err_str
                            ) and verify_flag:
                                need_ssl_retry = True
                                break
                            elif (
                                "NameResolutionError" in err_str
                                or "nodename nor servname" in err_str
                                or "ConnectError" in err_str
                            ):
                                return None
                            else:
                                continue

                    # 当 GCP 项目未授予 aiplatform.interactions.create 权限时，自动在同连接上回退至 Vertex AI generate_content
                    if interactions_iam_denied:
                        try:
                            resp = client.models.generate_content(
                                model=cand_model,
                                contents=_convert_prompt_for_generate_content(prompt),
                                config=types.GenerateContentConfig(
                                    response_mime_type="application/json",
                                    response_json_schema=json_schema,
                                    temperature=temperature,
                                ),
                            )
                            if resp and resp.text:
                                text_out = strip_markdown_json(resp.text)
                                _RESOLVED_MODEL_CACHE[("vertex", model)] = cand_model
                                _PREFERRED_CHANNEL = "vertex"
                                print(
                                    f"[GeminiInteractions] Vertex AI (generate_content 兼容通道) 调用成功: model={cand_model}"
                                )
                                return text_out
                        except Exception as g_exc:
                            g_err = str(g_exc)
                            errors.append(f"[{channel_label}-GenContent:{cand_model}]: {g_err}")
                            if "Reauthentication is needed" in g_err or "invalid_grant" in g_err or "PERMISSION_DENIED" in g_err or "SERVICE_DISABLED" in g_err:
                                cred_expired = True
                                break
                if cred_expired or not need_ssl_retry:
                    break
        return None

    def _try_aistudio_channel(px: Optional[str], label_prefix: str) -> Optional[str]:
        global _PREFERRED_CHANNEL
        if not effective_api_key:
            return None

        aistudio_candidates = get_candidate_models(model, backend="aistudio")
        for verify_flag in (True, False):
            client = genai.Client(
                api_key=effective_api_key,
                vertexai=False,
                http_options=build_http_options(proxy_url=px, verify_ssl=verify_flag),
            )
            ssl_tag = "" if verify_flag else ", SSL-Unverified"
            channel_label = f"AIStudio({label_prefix}{ssl_tag})"
            need_ssl_retry = False

            for cand_model in aistudio_candidates:
                try:
                    print(
                        f"[GeminiInteractions] 正在通过 [{channel_label}] 调用 Interactions API: model={cand_model} ..."
                    )
                    interaction = client.interactions.create(
                        model=cand_model,
                        input=prompt,
                        response_format=json_schema,
                        response_mime_type="application/json",
                        generation_config={"temperature": temperature},
                    )
                    text_out = extract_interaction_text(interaction)
                    _RESOLVED_MODEL_CACHE[("aistudio", model)] = cand_model
                    _PREFERRED_CHANNEL = "aistudio"
                    print(
                        f"[GeminiInteractions] AI Studio 调用成功: model={cand_model} (id={getattr(interaction, 'id', 'N/A')})"
                    )
                    return text_out
                except Exception as exc:
                    err_str = str(exc)
                    errors.append(f"[{channel_label}:{cand_model}]: {err_str}")
                    if (
                        "CERTIFICATE_VERIFY_FAILED" in err_str
                        or "SSLCertVerificationError" in err_str
                        or "SSL" in err_str
                    ) and verify_flag:
                        need_ssl_retry = True
                        break
                    if (
                        "NameResolutionError" in err_str
                        or "nodename nor servname" in err_str
                        or "ConnectError" in err_str
                    ):
                        return None
                    # 地理位置受限、API Key 服务被禁用或网络不可达时，无需在同一通道继续换模型
                    if (
                        "User location is not supported" in err_str
                        or "API_KEY_SERVICE_BLOCKED" in err_str
                        or "NameResolutionError" in err_str
                        or "nodename nor servname" in err_str
                        or "ConnectError" in err_str
                    ):
                        return None

            if not need_ssl_retry:
                break
        return None

    # 智能通道调度：
    # 若本机存在可用的 GCP Vertex AI ADC 凭证且未显式配置外部代理（或上次 Vertex AI 已成功），
    # 优先走 Vertex AI Global Endpoint（在 Google Corp VPN / 中国大陆下直连即通，0 额外延迟）。
    if creds is not None and (_PREFERRED_CHANNEL == "vertex" or not effective_proxy):
        res_v = _try_vertex_channel(effective_proxy)
        if res_v is not None:
            return res_v

    # 尝试 AI Studio 通道
    if effective_api_key:
        primary_label = f"Proxy={effective_proxy}" if effective_proxy else "Direct"
        res_ai = _try_aistudio_channel(effective_proxy, primary_label)
        if res_ai is not None:
            return res_ai

        # 如果遇到地理位置不支持，遍历本机常见代理端口重试
        if any("User location is not supported" in e for e in errors):
            for local_px in COMMON_LOCAL_PROXIES:
                if local_px == effective_proxy:
                    continue
                try:
                    host_port = local_px.split("://", 1)[1]
                    host, port_str = host_port.split(":", 1)
                    with socket.create_connection((host, int(port_str)), timeout=0.12):
                        res_px = _try_aistudio_channel(local_px, f"AutoProxy={local_px}")
                        if res_px is not None:
                            return res_px
                except OSError:
                    continue

    # 如果之前先试了 AI Studio 失败，兜底再试一次 Vertex AI
    if creds is not None and _PREFERRED_CHANNEL != "vertex" and effective_proxy:
        res_v2 = _try_vertex_channel(effective_proxy) or _try_vertex_channel(None)
        if res_v2 is not None:
            return res_v2

    if not effective_api_key and creds is None:
        raise RuntimeError(
            "后端未检测到可用的 GCP Vertex AI 凭证或 Gemini API Key。"
        )

    raise RuntimeError(" | ".join(errors[-4:]) if errors else "Gemini Interactions API 调用未知错误")
