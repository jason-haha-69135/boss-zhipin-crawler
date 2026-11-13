#!/usr/bin/env python3
"""
BOSS直聘 智能求职分析 Agent — FastAPI 后端服务
提供：
- GET /                         : 对话式分析与六维可视化前端界面
- GET /api/status               : 检查环境变量 API Key 状态与可用配置
- POST /api/analyze             : SSE 实时流式执行【意图解析 -> 两阶段爬虫 -> Gemini 六维分析与匹配评分】
- GET /api/download/{filename}  : 安全下载导出的 Excel (.xlsx) 岗位明细表
"""

import asyncio
import base64
from email.parser import BytesParser
from email.policy import default as email_default_policy
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from core.boss_crawler import OUTPUT_DIR, crawl_boss_two_stage
from core.gemini_analyzer import ALLOWED_MODELS, analyze_jobs_with_gemini
from core.gemini_client import (
    detect_local_proxy,
    has_vertex_auth_available,
    load_backend_api_key,
)
from core.intent_parser import parse_user_intent
from core.resume_parser import (
    MAX_RESUME_BYTES,
    extract_resume_profile_with_gemini,
    generate_queries_from_profile_with_gemini,
    parse_resume_with_gemini,
)
from resume_eval_benchmark.eval_store import (
    BENCHMARK_DIR,
    STAGE_REGISTRY,
    list_eval_runs,
    load_benchmark_catalog,
    load_eval_run_by_id,
    run_single_sample_live_eval,
    save_eval_run_archive,
)
from resume_eval_benchmark.evaluate_parser import run_dataset_verification

STATIC_DIR = BASE_DIR / "static"

# TODO(security): Local single-user household application; if deployed beyond localhost, add authentication & rate limiting.
app = FastAPI(
    title="BOSS直聘智能岗位分析助手",
    description="自然语言对话式采集 BOSS直聘 岗位并由 Gemini 生成六维可视化图表与匹配度评分",
    version="1.0.0",
)

# 防止同一浏览器实例并发冲突的互斥锁
CRAWL_LOCK = asyncio.Lock()

# 本地运行时配置持久化文件（仅本机 0600 权限，避免刷新页面丢失已输入的 API Key 与代理）
RUNTIME_CFG_FILE = BASE_DIR / ".gemini_runtime.json"
LATEST_SNAPSHOT_FILE = OUTPUT_DIR / "latest_test_snapshot.json"


def load_latest_snapshot() -> Dict[str, Any]:
    if LATEST_SNAPSHOT_FILE.is_file():
        try:
            return json.loads(LATEST_SNAPSHOT_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_latest_snapshot(
    resume_parsed: Optional[Dict[str, Any]] = None,
    dashboard_payload: Optional[Dict[str, Any]] = None,
) -> None:
    snap = load_latest_snapshot()
    if resume_parsed is not None:
        snap["resume_parsed"] = resume_parsed
    if dashboard_payload is not None:
        snap["dashboard_payload"] = dashboard_payload
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        LATEST_SNAPSHOT_FILE.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def load_runtime_config() -> Dict[str, str]:
    if RUNTIME_CFG_FILE.is_file():
        try:
            return json.loads(RUNTIME_CFG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_runtime_config(api_key: Optional[str], proxy_url: Optional[str]) -> None:
    cfg = load_runtime_config()
    changed = False
    if api_key and api_key.strip():
        cfg["api_key"] = api_key.strip()
        changed = True
    if proxy_url is not None and proxy_url.strip():
        cfg["proxy_url"] = proxy_url.strip()
        changed = True
    if changed:
        try:
            RUNTIME_CFG_FILE.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
            os.chmod(RUNTIME_CFG_FILE, 0o600)
        except Exception:
            pass


class AnalyzeRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=300, description="用户的自然语言求职查询")
    model: str = Field(default="gemini-3.8-flash", description="选择的 Gemini 模型")
    max_batches: int = Field(default=10, ge=1, le=50, description="最大抓取批次数（每批约15条）")
    top_detail_count: int = Field(
        default=8,
        ge=3,
        le=20,
        description="用户在 UI 自定义的 Top 候选岗位深度抓取与评估数量（范围 3-20）",
    )
    resume_profile: Optional[Dict[str, Any]] = Field(
        default=None,
        description="可选的候选人已解析简历画像（用于在六维分析中结合真实履历评估人岗契合度）",
    )


def _extract_resume_from_multipart(content_type: str, body: bytes) -> Tuple[str, bytes, str]:
    """使用 Python 标准库解析 multipart/form-data 请求体，无需外部 python-multipart 依赖"""
    raw_Mime = b"Content-Type: " + content_type.encode("utf-8") + b"\r\n\r\n" + body
    msg = BytesParser(policy=email_default_policy).parsebytes(raw_Mime)
    filename = ""
    file_bytes = b""
    model_name = "gemini-3.8-flash"

    if msg.is_multipart():
        for part in msg.iter_parts():
            cd = part.get("Content-Disposition", "")
            part_filename = part.get_filename()
            if part_filename or 'name="file"' in cd:
                filename = part_filename or "resume.pdf"
                payload = part.get_payload(decode=True)
                file_bytes = payload if isinstance(payload, bytes) else b""
            elif 'name="model"' in cd:
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    model_name = payload.decode("utf-8", errors="ignore").strip() or model_name
    return filename, file_bytes, model_name


def format_sse(event: str, data: Dict[str, Any]) -> str:
    """格式化 Server-Sent Events 消息帧"""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


@app.get("/api/status")
async def get_status() -> Dict[str, Any]:
    """返回服务状态及后端凭证就绪状态（绝不向前端暴露任何密钥明文）"""
    return {
        "ai_ready": has_vertex_auth_available(),
        "models": [
            {"id": "gemini-3.8-flash", "label": "Gemini 3.8 Flash"},
            {"id": "gemini-3.5-flash-lite", "label": "Gemini 3.5 Flash Light"},
            {"id": "gemini-3.1-pro", "label": "Gemini 3.1 Pro"},
            {"id": "gemini-4-argon", "label": "Gemini 4 Argon"},
        ],
    }


@app.get("/api/latest-snapshot")
async def get_latest_snapshot() -> Dict[str, Any]:
    """返回最近一次简历解析与六维分析快照（用于页面加载时即刻渲染最新测试成果）"""
    return load_latest_snapshot()


class GenerateQueriesRequest(BaseModel):
    """阶段二独立接口请求模型：基于结构化求职画像（及可选的用户偏好微调）生成定制化求职 Query"""

    profile: Dict[str, Any] = Field(..., description="阶段一提取的候选人结构化求职画像 (CandidateProfileSchema)")
    target_city: Optional[str] = Field(
        default=None,
        max_length=60,
        description="可选：用户微调覆盖的目标城市（如 '广州' 或 '深圳/广州'）",
    )
    salary_floor: Optional[str] = Field(
        default=None,
        max_length=30,
        description="可选：用户微调覆盖的期望月薪底线（如 '1.5w' 或 '12k'）",
    )
    welfare_prefs: Optional[List[str]] = Field(
        default=None,
        description="可选：用户微调覆盖的作息与福利诉求列表（如 ['周末双休', '五险一金']）",
    )
    custom_focus: Optional[str] = Field(
        default=None,
        max_length=150,
        description="可选：用户附加的求职方向或细分赛道偏好（如 '偏向服装买手或商品企划岗'）",
    )
    model: str = Field(default="gemini-3.8-flash", description="选择的 Gemini 模型")
    filename: Optional[str] = Field(default=None, max_length=120, description="关联的简历文件名（用于更新快照）")


async def _parse_resume_upload_request(request: Request) -> Tuple[str, bytes, str]:
    """统一解析 multipart/form-data 或 JSON Base64 简历上传请求并执行体积校验"""
    content_length_hdr = request.headers.get("content-length")
    if content_length_hdr and content_length_hdr.isdigit():
        if int(content_length_hdr) > int(MAX_RESUME_BYTES * 1.5):
            raise HTTPException(status_code=413, detail="上传的简历文件超过 10 MB 限制。")

    body = await request.body()
    if len(body) > int(MAX_RESUME_BYTES * 1.5):
        raise HTTPException(status_code=413, detail="上传的简历文件超过 10 MB 限制。")

    content_type = request.headers.get("content-type", "")
    filename = ""
    raw_bytes = b""
    requested_model = "gemini-3.8-flash"

    if "multipart/form-data" in content_type.lower():
        filename, raw_bytes, requested_model = _extract_resume_from_multipart(content_type, body)
    else:
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception as exc:
            raise HTTPException(status_code=400, detail="非法的请求数据格式。") from exc

        filename = str(payload.get("filename") or "").strip()
        b64_str = str(payload.get("content_base64") or "").strip()
        requested_model = str(payload.get("model") or "gemini-3.8-flash").strip()
        if "," in b64_str and b64_str.startswith("data:"):
            b64_str = b64_str.split(",", 1)[1]
        try:
            raw_bytes = base64.b64decode(b64_str, validate=False) if b64_str else b""
        except Exception as exc:
            raise HTTPException(status_code=400, detail="简历文件 Base64 解码失败。") from exc

    selected_model = requested_model if requested_model in ALLOWED_MODELS else "gemini-3.8-flash"
    return filename, raw_bytes, selected_model


@app.post("/api/resume/parse-profile")
async def parse_resume_profile_endpoint(request: Request) -> Dict[str, Any]:
    """
    【阶段一独立服务接口】仅执行多模态简历深度理解与结构化求职画像提取：
    1. 校验文件大小 (<=10MB)、扩展名白名单与 Magic Bytes 文件头签名；
    2. 调用 Gemini Interactions API (`temperature=0.1`) 提取结构化 `profile`；
    3. 经 Python 确定性校准与 PII 二次脱敏后即刻返回画像（前端可先行渲染画像卡片）。
    """
    filename, raw_bytes, selected_model = await _parse_resume_upload_request(request)
    saved_cfg = load_runtime_config()
    effective_api_key = load_backend_api_key(saved_cfg.get("api_key"))
    effective_proxy = saved_cfg.get("proxy_url", "").strip() or None

    try:
        stage1_result = await asyncio.to_thread(
            extract_resume_profile_with_gemini,
            filename=filename,
            raw_bytes=raw_bytes,
            model_name=selected_model,
            api_key=effective_api_key,
            proxy_url=effective_proxy,
        )
        return stage1_result
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/resume/generate-queries")
async def generate_resume_queries_endpoint(req: GenerateQueriesRequest) -> Dict[str, Any]:
    """
    【阶段二独立服务接口】基于结构化求职画像（及用户微调的目标城市/底薪/附加偏好）生成 5 条多策略求职 Query：
    1. 无需重复上传简历原文件，仅接收轻量级 `profile` JSON 与可选覆盖参数；
    2. 由 Python 注入 BOSS直聘 高频标准岗位词锚点，调用 Gemini (`temperature=0.35`) 生成 5 条差异化自然语言 Query；
    3. 同步更新本地最新快照并返回 `{ filename, model_used, profile, recommended_queries }`。
    """
    selected_model = req.model if req.model in ALLOWED_MODELS else "gemini-3.8-flash"
    saved_cfg = load_runtime_config()
    effective_api_key = load_backend_api_key(saved_cfg.get("api_key"))
    effective_proxy = saved_cfg.get("proxy_url", "").strip() or None

    try:
        stage2_result = await asyncio.to_thread(
            generate_queries_from_profile_with_gemini,
            profile=req.profile,
            target_city=req.target_city,
            salary_floor=req.salary_floor,
            welfare_prefs=req.welfare_prefs,
            custom_focus=req.custom_focus,
            model_name=selected_model,
            api_key=effective_api_key,
            proxy_url=effective_proxy,
        )
        snap = load_latest_snapshot()
        prev_fn = (snap.get("resume_parsed") or {}).get("filename") or "个人简历.pdf"
        combined_record = {
            "filename": (req.filename or "").strip() or prev_fn,
            "model_used": stage2_result["model_used"],
            "profile": stage2_result["profile"],
            "recommended_queries": stage2_result["recommended_queries"],
        }
        save_latest_snapshot(resume_parsed=combined_record)
        return combined_record
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/resume/parse")
async def parse_resume_endpoint(request: Request) -> Dict[str, Any]:
    """
    【向后兼容组合接口】一次性串联执行阶段一（画像提取）与阶段二（推荐 Query 生成）
    """
    filename, raw_bytes, selected_model = await _parse_resume_upload_request(request)
    saved_cfg = load_runtime_config()
    effective_api_key = load_backend_api_key(saved_cfg.get("api_key"))
    effective_proxy = saved_cfg.get("proxy_url", "").strip() or None

    try:
        result = await asyncio.to_thread(
            parse_resume_with_gemini,
            filename=filename,
            raw_bytes=raw_bytes,
            model_name=selected_model,
            api_key=effective_api_key,
            proxy_url=effective_proxy,
        )
        save_latest_snapshot(resume_parsed=result)
        return result
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/analyze")
async def analyze_endpoint(req: AnalyzeRequest) -> StreamingResponse:
    """SSE 实时流式执行：意图解析 -> BOSS直聘两阶段采集 -> Gemini 六维分析"""
    selected_model = req.model if req.model in ALLOWED_MODELS else "gemini-3.8-flash"
    saved_cfg = load_runtime_config()
    effective_api_key = load_backend_api_key(saved_cfg.get("api_key"))
    effective_proxy = saved_cfg.get("proxy_url", "").strip() or None
    max_batches = max(1, min(req.max_batches, 50))
    top_detail_count = max(3, min(req.top_detail_count, 20))

    async def event_generator() -> AsyncGenerator[str, None]:
        if CRAWL_LOCK.locked():
            yield format_sse(
                "error",
                {"message": "当前已有正在执行的采集任务，请等待其完成后再发起新查询。"},
            )
            return

        async with CRAWL_LOCK:
            loop = asyncio.get_running_loop()
            queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

            def push_event(event_type: str, payload: Dict[str, Any]) -> None:
                loop.call_soon_threadsafe(queue.put_nowait, format_sse(event_type, payload))

            def worker() -> None:
                try:
                    # Step 1: 意图解析
                    push_event(
                        "progress",
                        {
                            "percent": 5,
                            "stage": "intent",
                            "message": "正在使用 Gemini 解析您的求职意图与筛选条件...",
                        },
                    )
                    intent = parse_user_intent(
                        req.query,
                        api_key=effective_api_key,
                        proxy_url=effective_proxy,
                    )
                    push_event(
                        "intent",
                        {
                            "percent": 10,
                            "intent": intent.model_dump(),
                            "boss_url": intent.build_boss_url(),
                            "message": (
                                f"意图解析完成：城市【{intent.city_name}】| 核心岗位【{intent.query}】| "
                                f"薪资档位【{intent.salary_label}】| 软性要求：{', '.join(intent.soft_requirements) or '无'}"
                            ),
                        },
                    )

                    # Step 2: 两阶段 BOSS直聘爬虫
                    def on_crawl_progress(pct: int, msg: str) -> None:
                        push_event(
                            "progress",
                            {"percent": pct, "stage": "crawl", "message": msg},
                        )

                    jobs, top_candidates, excel_filename = crawl_boss_two_stage(
                        intent=intent,
                        max_batches=max_batches,
                        top_detail_count=top_detail_count,
                        progress_cb=on_crawl_progress,
                    )

                    if not jobs:
                        push_event(
                            "error",
                            {
                                "message": (
                                    "未能从 BOSS直聘 捕获到岗位数据。请确认：\n"
                                    "1. 已运行 ./start_chrome.sh 启动调试浏览器；\n"
                                    "2. 已在 Chrome 中登录 BOSS直聘 账号且未停留在滑块验证页。"
                                )
                            },
                        )
                        return

                    # Step 3: Gemini 六维总结与匹配度评估
                    model_label = ALLOWED_MODELS.get(selected_model, selected_model)
                    push_event(
                        "progress",
                        {
                            "percent": 82,
                            "stage": "gemini",
                            "message": (
                                f"采集完成（共 {len(jobs)} 条岗位，已深度提取 Top {len(top_candidates)} 完整 JD）。"
                                f"正在调用 {model_label} 生成六维可视化分析与匹配度评分..."
                            ),
                        },
                    )

                    analysis_report = analyze_jobs_with_gemini(
                        intent=intent,
                        jobs=jobs,
                        top_candidates=top_candidates,
                        model_name=selected_model,
                        api_key=effective_api_key,
                        proxy_url=effective_proxy,
                        resume_profile=req.resume_profile,
                    )

                    result_payload = {
                        "percent": 100,
                        "message": "分析完成！已为您生成六维可视化报告与匹配度评估。",
                        "query": req.query,
                        "model": selected_model,
                        "model_label": model_label,
                        "intent": intent.model_dump(),
                        "total_crawled": len(jobs),
                        "top_detail_count": len(top_candidates),
                        "excel_filename": excel_filename,
                        "download_url": f"/api/download/{excel_filename}" if excel_filename else "",
                        "report": analysis_report,
                    }
                    save_latest_snapshot(dashboard_payload=result_payload)
                    push_event("result", result_payload)
                except Exception as exc:
                    push_event("error", {"message": f"处理过程中发生错误：{exc}"})
                finally:
                    loop.call_soon_threadsafe(queue.put_nowait, None)

            thread = threading.Thread(target=worker, daemon=True)
            thread.start()

            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class EvalRunSingleRequest(BaseModel):
    """Single-Use 实时单样本评测请求模型"""

    sample_id: str = Field(..., min_length=4, max_length=20, description="标准集样本 ID，例如 QUAL-001")
    extract_model: str = Field(default="gemini-3.8-flash", description="Stage 1 画像提取模型")
    judge_model: str = Field(default="gemini-3.8-flash", description="LLM-as-a-Judge 裁判模型")
    run_id: Optional[str] = Field(default=None, description="可选：将评测结果合并更新到指定的历史 Run ID")


class EvalRunBatchRequest(BaseModel):
    """批量运行/新增一次评测 Run 请求模型"""

    sample_ids: Optional[List[str]] = Field(default=None, description="可选：指定评测的样本 ID 列表")
    extensions: Optional[List[str]] = Field(default=None, description="可选：按扩展名过滤，如 ['.pdf', '.docx']")
    limit: int = Field(default=3, ge=1, le=25, description="评测样本数量上限 (1-25)")
    live_gemini: bool = Field(default=True, description="是否调用真实 Gemini 进行 Stage 1 提取与 LLM-as-a-Judge 评测")
    extract_model: str = Field(default="gemini-3.8-flash", description="Stage 1 画像提取模型")
    judge_model: str = Field(default="gemini-3.8-flash", description="LLM-as-a-Judge 裁判模型")


@app.get("/api/eval/overview")
async def get_eval_overview() -> Dict[str, Any]:
    """
    获取全链路评测工作台 (Option A) 初始化概览：
    - stages: Stage 1 ~ Stage 5 统一三层评测协议注册表
    - runs: 历史评测运行记录元数据列表
    - active_run: 最新一次评测运行完整报告（含 Aggregated 大盘与 Single-Use 样本原子核对明细）
    - catalog: 25 个正例多模态样本与 20 个反例安全拦截样本目录
    """
    runs = await asyncio.to_thread(list_eval_runs)
    active_run: Dict[str, Any] = {}
    if runs:
        try:
            active_run = await asyncio.to_thread(load_eval_run_by_id, runs[0]["run_id"])
        except Exception:
            active_run = {}
    catalog = await asyncio.to_thread(load_benchmark_catalog)
    return {
        "stages": STAGE_REGISTRY,
        "runs": runs,
        "active_run": active_run,
        "catalog": catalog,
    }


@app.get("/api/eval/runs/{run_id}")
async def get_eval_run_detail(run_id: str) -> Dict[str, Any]:
    """按 run_id 加载单次评测运行的完整三层协议数据"""
    try:
        run_data = await asyncio.to_thread(load_eval_run_by_id, run_id)
        return {"run": run_data}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve
    except FileNotFoundError as fnf:
        raise HTTPException(status_code=404, detail=str(fnf)) from fnf
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/eval/stage1/run-single")
async def run_stage1_single_sample_endpoint(req: EvalRunSingleRequest) -> Dict[str, Any]:
    """
    【Single-Use 实时单样本评测接口】
    在浏览器中选择任意一个数据集样本（如 QUAL-001 ~ QUAL-025），
    实时触发 Stage 1 Gemini 多模态画像提取 + LLM-as-a-Judge 9 字段原子核对打分，
    并将最新原子核对结果写回评测历史档案。
    """
    selected_extract = req.extract_model if req.extract_model in ALLOWED_MODELS else "gemini-3.8-flash"
    selected_judge = req.judge_model if req.judge_model in ALLOWED_MODELS else "gemini-3.8-flash"
    try:
        res = await asyncio.to_thread(
            run_single_sample_live_eval,
            sample_id=req.sample_id.strip().upper(),
            extract_model=selected_extract,
            judge_model=selected_judge,
            run_id_to_update=req.run_id,
        )
        runs = await asyncio.to_thread(list_eval_runs)
        res["runs"] = runs
        return res
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve
    except FileNotFoundError as fnf:
        raise HTTPException(status_code=404, detail=str(fnf)) from fnf
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/eval/stage1/run-batch")
async def run_stage1_batch_eval_endpoint(req: EvalRunBatchRequest) -> Dict[str, Any]:
    """
    【Batch 批量评测接口】
    按筛选条件（指定样本、指定文件格式或前 N 个样本）执行 Stage 1 提取与 LLM-as-a-Judge 评测，
    生成新的历史评测 Run 并返回更新后的 Aggregated View 大盘数据。
    """
    selected_extract = req.extract_model if req.extract_model in ALLOWED_MODELS else "gemini-3.8-flash"
    selected_judge = req.judge_model if req.judge_model in ALLOWED_MODELS else "gemini-3.8-flash"

    sample_ids_set = (
        {s.strip().upper() for s in req.sample_ids if s and s.strip()}
        if req.sample_ids
        else None
    )
    ext_set = (
        {
            (e.strip().lower() if e.strip().startswith(".") else f".{e.strip().lower()}")
            for e in req.extensions
            if e and e.strip()
        }
        if req.extensions
        else None
    )

    def _run_batch_sync() -> Dict[str, Any]:
        custom_fn = None
        if req.live_gemini:
            def _gemini_wrapper(file_path: Path) -> Dict[str, Any]:
                out = extract_resume_profile_with_gemini(
                    filename=file_path.name,
                    raw_bytes=file_path.read_bytes(),
                    model_name=selected_extract,
                )
                return out["profile"] if isinstance(out, dict) and "profile" in out else out

            custom_fn = _gemini_wrapper

        raw_report = run_dataset_verification(
            BENCHMARK_DIR,
            custom_parser_fn=custom_fn,
            use_llm_judge=req.live_gemini,
            judge_model=selected_judge,
            extract_model=selected_extract,
            sample_ids_filter=sample_ids_set,
            extensions_filter=ext_set,
            limit=max(1, min(req.limit, 25)),
            skip_disqualified=False,
        )
        saved_run_id = save_eval_run_archive(
            raw_report,
            stage_id="stage1_profile",
            extract_model=selected_extract if req.live_gemini else "ground_truth_baseline",
        )
        return load_eval_run_by_id(saved_run_id)

    try:
        active_run = await asyncio.to_thread(_run_batch_sync)
        runs = await asyncio.to_thread(list_eval_runs)
        return {
            "run_id": active_run["run_id"],
            "active_run": active_run,
            "runs": runs,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/download/{filename}")
async def download_excel(filename: str) -> FileResponse:
    """安全下载导出的 Excel 文件（严格校验文件名与目录边界，防止路径穿越）"""
    safe_name = os.path.basename(filename)
    if not safe_name or not safe_name.endswith(".xlsx") or safe_name != filename:
        raise HTTPException(status_code=400, detail="非法的 Excel 文件名")

    target_path = (OUTPUT_DIR / safe_name).resolve()
    output_root = OUTPUT_DIR.resolve()
    if not str(target_path).startswith(str(output_root) + os.sep) or not target_path.is_file():
        raise HTTPException(status_code=404, detail="未找到对应的 Excel 导出文件")

    return FileResponse(
        path=target_path,
        filename=safe_name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.get("/")
async def serve_index() -> FileResponse:
    """返回前端单页应用主页"""
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


if __name__ == "__main__":
    print("=" * 65)
    print("BOSS直聘 智能求职分析助手已启动！")
    print("本机访问: http://127.0.0.1:8000")
    print("=" * 65)
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True, log_level="info")
