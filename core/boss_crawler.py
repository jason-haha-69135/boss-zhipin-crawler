"""
BOSS直聘两阶段采集引擎 (Two-Stage Crawler Engine)
Stage 1: 列表页滚动批量采集 (/wapi/zpgeek/search/joblist.json)
Stage 2: Top 8 候选岗位详情页定向补全 (/wapi/zpgeek/job/detail.json) 获取完整 JD、双休/单休说明、详细地址与 HR 活跃度
"""

import os
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from playwright.sync_api import Response, Route, sync_playwright

from core.intent_parser import ParsedSearchIntent

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
ProgressCallback = Callable[[int, str], None]


def parse_salary_bounds(salary_desc: str) -> Tuple[int, int, int]:
    """
    从薪资字符串（如 '12-18K·13薪', '10-15K', '200-300元/天'）解析出:
    (最低月薪K, 最高月薪K, 计薪月数)
    """
    if not salary_desc:
        return (0, 0, 12)

    months = 12
    m_match = re.search(r"(\d+)\s*薪", salary_desc)
    if m_match:
        months = int(m_match.group(1))

    k_match = re.search(r"(\d+)\s*-\s*(\d+)\s*[kK]", salary_desc)
    if k_match:
        return (int(k_match.group(1)), int(k_match.group(2)), months)

    single_k = re.search(r"(\d+)\s*[kK]", salary_desc)
    if single_k:
        val = int(single_k.group(1))
        return (val, val, months)

    return (0, 0, months)


def detect_weekend_policy(text: str) -> str:
    """从福利标签或完整 JD 文本中识别作息/周末制度"""
    if not text:
        return "未注明"
    if any(k in text for k in ["双休", "做五休二", "周末双休", "五天八小时", "5天8小时", "周六日休"]):
        return "周末双休"
    if any(k in text for k in ["大小周", "大小休", "隔周双休", "单双休"]):
        return "大小周/单双休"
    if any(k in text for k in ["月休6天", "月休8天", "月休4天", "排班", "轮休", "调休", "做六休一", "单休"]):
        return "排班轮休/单休"
    return "未明确注明"


def parse_api_job_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """解析 /wapi/zpgeek/search/joblist.json 中的单条岗位 JSON"""
    area_parts = [
        item.get("cityName", ""),
        item.get("areaDistrict", ""),
        item.get("businessDistrict", ""),
    ]
    location = "·".join([p for p in area_parts if p])

    skills = item.get("skills") or []
    welfare = item.get("welfareList") or []
    encrypt_job_id = str(item.get("encryptJobId", ""))
    job_url = f"https://www.zhipin.com/job_detail/{encrypt_job_id}.html" if encrypt_job_id else ""

    salary_desc = str(item.get("salaryDesc", ""))
    min_k, max_k, months = parse_salary_bounds(salary_desc)

    combined_tags = " ".join(skills + welfare + [str(item.get("jobName", ""))])

    return {
        "encryptJobId": encrypt_job_id,
        "securityId": str(item.get("securityId", "")),
        "lid": str(item.get("lid", "")),
        "岗位名称": str(item.get("jobName", "")),
        "薪资范围": salary_desc,
        "最低月薪K": min_k,
        "最高月薪K": max_k,
        "计薪月数": months,
        "工作地点": location,
        "经验要求": str(item.get("jobExperience", "")),
        "学历要求": str(item.get("jobDegree", "")),
        "公司名称": str(item.get("brandName", "")),
        "所属行业": str(item.get("brandIndustry", "")),
        "融资阶段": str(item.get("brandStageName", "")),
        "公司规模": str(item.get("brandScaleName", "")),
        "招聘人": f"{item.get('bossName', '')} ({item.get('bossTitle', '')})".strip(" ()"),
        "BOSS在线": bool(item.get("bossOnline", False)),
        "技能标签": ", ".join(skills) if isinstance(skills, list) else str(skills),
        "福利待遇": ", ".join(welfare) if isinstance(welfare, list) else str(welfare),
        "作息制度": detect_weekend_policy(combined_tags),
        "详细地址": "",
        "HR活跃度": "在线" if item.get("bossOnline") else "",
        "完整JD": "",
        "岗位链接": job_url,
    }


def score_candidate_for_detail(job: Dict[str, Any], intent: ParsedSearchIntent) -> float:
    """
    在 Stage 1 结束后对所有采集到的岗位进行初筛打分，选出最值得拉取详情页完整 JD 的 Top 8 候选岗位
    """
    score = 50.0
    job_name = job.get("岗位名称", "")
    industry = job.get("所属行业", "")
    company = job.get("公司名称", "")
    skills = job.get("技能标签", "")
    welfare = job.get("福利待遇", "")
    full_meta = f"{job_name} {industry} {company} {skills} {welfare}"

    # 1. 核心岗位词匹配
    if intent.query and intent.query in job_name:
        score += 18.0

    # 2. 行业关键词匹配
    if intent.industry_keywords:
        matched_ind = [kw for kw in intent.industry_keywords if kw in full_meta]
        if matched_ind:
            score += min(25.0, 12.0 + len(matched_ind) * 4.0)
        else:
            score -= 10.0

    # 3. 薪资匹配
    min_k = job.get("最低月薪K", 0)
    max_k = job.get("最高月薪K", 0)
    if intent.min_salary_k > 0 and max_k > 0:
        if min_k >= intent.min_salary_k:
            score += 12.0
        elif max_k >= intent.min_salary_k:
            score += 5.0
        else:
            score -= 15.0

    # 4. 双休偏好
    if intent.require_double_weekend:
        if job.get("作息制度") == "周末双休":
            score += 15.0
        elif job.get("作息制度") in ("大小周/单双休", "排班轮休/单休"):
            score -= 8.0

    # 5. 公司规模与福利完善度加分
    scale = job.get("公司规模", "")
    if any(s in scale for s in ["500-999人", "1000-9999人", "10000人以上"]):
        score += 6.0
    elif "100-499人" in scale:
        score += 3.0

    if welfare:
        score += min(5.0, len(welfare.split(",")) * 0.8)

    if job.get("BOSS在线"):
        score += 2.0

    return round(score, 1)


def export_jobs_to_excel(jobs: List[Dict[str, Any]], output_filename: str) -> Path:
    """将岗位数据导出为格式化的 Excel (.xlsx) 文件（含完整 JD 与作息识别列）"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = os.path.basename(output_filename)
    if not safe_name.endswith(".xlsx"):
        safe_name += ".xlsx"

    output_path = (OUTPUT_DIR / safe_name).resolve()
    if not str(output_path).startswith(str(OUTPUT_DIR.resolve()) + os.sep):
        raise ValueError("非法的输出文件路径")

    wb = Workbook()
    ws = wb.active
    ws.title = "BOSS直聘岗位数据"

    headers = [
        "岗位名称",
        "薪资范围",
        "工作地点",
        "经验要求",
        "学历要求",
        "公司名称",
        "所属行业",
        "融资阶段",
        "公司规模",
        "招聘人",
        "作息制度",
        "技能标签",
        "福利待遇",
        "详细地址",
        "HR活跃度",
        "完整JD",
        "岗位链接",
    ]
    ws.append(headers)

    header_fill = PatternFill(start_color="00A6A7", end_color="00A6A7", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for job in jobs:
        ws.append([str(job.get(h, "")) for h in headers])

    col_widths = [24, 15, 20, 12, 12, 22, 16, 14, 14, 20, 14, 28, 32, 28, 14, 50, 44]
    for idx, width in enumerate(col_widths, start=1):
        col_letter = ws.cell(row=1, column=idx).column_letter
        ws.column_dimensions[col_letter].width = width

    wb.save(output_path)
    return output_path


def crawl_boss_two_stage(
    intent: ParsedSearchIntent,
    max_batches: int = 10,
    top_detail_count: int = 8,
    cdp_url: str = "http://127.0.0.1:9222",
    progress_cb: Optional[ProgressCallback] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], str]:
    """
    执行两阶段 BOSS直聘采集任务：
    - 返回: (全部岗位列表, 已补全完整JD的Top候选岗位列表, 导出的Excel文件名)
    """
    def notify(pct: int, msg: str) -> None:
        print(f"[{pct}%] {msg}")
        if progress_cb:
            progress_cb(pct, msg)

    collected_jobs: List[Dict[str, Any]] = []
    seen_keys = set()
    batch_queue: List[List[Dict[str, Any]]] = []
    has_more_flag = True

    def handle_js_route(route: Route) -> None:
        """拦截并移除 BOSS直聘前端脚本中的 disable-devtool 反调试跳转逻辑"""
        try:
            resp = route.fetch()
            body = resp.text()
            if "this.seact()," in body:
                body = body.replace("this.seact(),", "return;this.seact(),")
            route.fulfill(response=resp, body=body)
        except Exception:
            try:
                route.continue_()
            except Exception:
                pass

    def handle_response(response: Response) -> None:
        nonlocal has_more_flag
        if "/wapi/zpgeek/search/joblist.json" in response.url and response.status == 200:
            try:
                data = response.json()
                if data.get("code") == 0:
                    zp_data = data.get("zpData", {})
                    raw_list = zp_data.get("jobList", [])
                    has_more_flag = bool(zp_data.get("hasMore", True))
                    parsed = [parse_api_job_item(item) for item in raw_list]
                    if parsed:
                        batch_queue.append(parsed)
            except Exception as exc:
                print(f"[Crawler] 解析列表 JSON 警告: {exc}")

    notify(10, f"正在连接本地 Chrome 浏览器 ({cdp_url})...")
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(cdp_url)
        except Exception as exc:
            raise RuntimeError(
                f"无法连接到本地 Chrome 调试端口 ({cdp_url})。请先运行 ./start_chrome.sh 启动 Chrome 并确认已登录 BOSS直聘。"
            ) from exc

        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()
        page.route("**/static.zhipin.com/**/*.js*", handle_js_route)
        page.on("response", handle_response)

        try:
            target_url = intent.build_boss_url()
            notify(
                14,
                f"正在打开 BOSS直聘 搜索：{intent.city_name} · {intent.query} (薪资:{intent.salary_label})...",
            )
            page.goto(target_url, wait_until="domcontentloaded", timeout=30000)

            # ==================== Stage 1: 批量滚动采集列表 ====================
            for batch_num in range(1, max_batches + 1):
                wait_rounds = 0
                while len(batch_queue) < batch_num and wait_rounds < 18:
                    page.wait_for_timeout(500)
                    if wait_rounds in (5, 10, 14) and batch_num > 1:
                        try:
                            page.evaluate(
                                """() => {
                                    window.scrollBy(0, -400);
                                    setTimeout(() => window.scrollTo(0, document.body.scrollHeight), 150);
                                    const cards = document.querySelectorAll('.job-card-box, .job-card-wrapper');
                                    if (cards.length > 0) cards[cards.length - 1].scrollIntoView({ behavior: 'smooth', block: 'end' });
                                }"""
                            )
                            page.mouse.wheel(0, 4000)
                        except Exception:
                            pass
                    wait_rounds += 1

                if len(batch_queue) >= batch_num:
                    batch_jobs = batch_queue[batch_num - 1]
                else:
                    if "security-check" in page.url or "verify" in page.url:
                        notify(
                            25,
                            "检测到 BOSS直聘安全验证，请在打开的 Chrome 窗口手动完成滑块验证...",
                        )
                    break

                added_count = 0
                for job in batch_jobs:
                    unique_key = job.get("岗位链接") or f"{job.get('岗位名称')}_{job.get('公司名称')}"
                    if unique_key not in seen_keys:
                        seen_keys.add(unique_key)
                        collected_jobs.append(job)
                        added_count += 1

                stage1_pct = 15 + int((batch_num / max_batches) * 40)
                notify(
                    min(55, stage1_pct),
                    f"阶段 1/2：已抓取第 {batch_num}/{max_batches} 批（新增 {added_count} 条，累计 {len(collected_jobs)} 条岗位）...",
                )

                if not has_more_flag:
                    notify(55, f"阶段 1/2 完成：已加载全部匹配岗位（共 {len(collected_jobs)} 条）。")
                    break

                if batch_num < max_batches:
                    delay = random.uniform(1.8, 2.8)
                    time.sleep(delay)
                    try:
                        page.evaluate(
                            """() => {
                                const cards = document.querySelectorAll('.job-card-box, .job-card-wrapper');
                                if (cards.length > 0) cards[cards.length - 1].scrollIntoView({ block: 'end' });
                                window.scrollTo(0, document.body.scrollHeight);
                            }"""
                        )
                        page.mouse.wheel(0, 4500)
                    except Exception:
                        break

            # ==================== Stage 2: Top 8 候选岗位详情页定向补全 ====================
            for job in collected_jobs:
                job["初筛得分"] = score_candidate_for_detail(job, intent)

            ranked_jobs = sorted(
                collected_jobs,
                key=lambda x: x.get("初筛得分", 0.0),
                reverse=True,
            )
            top_candidates = ranked_jobs[:top_detail_count]

            if top_candidates:
                notify(
                    58,
                    f"阶段 2/2：从 {len(collected_jobs)} 条岗位中优选出 Top {len(top_candidates)} 候选岗位，正在深度获取完整 JD 与双休/单休详情...",
                )

            for idx, cand in enumerate(top_candidates, start=1):
                sec_id = cand.get("securityId", "")
                lid = cand.get("lid", "")
                if not sec_id:
                    continue

                pct = 58 + int((idx / max(1, len(top_candidates))) * 16)
                notify(
                    pct,
                    f"阶段 2/2：正在读取详情 ({idx}/{len(top_candidates)}) -> {cand.get('公司名称')} · {cand.get('岗位名称')}...",
                )
                try:
                    detail_data = page.evaluate(
                        """async ({ securityId, lid }) => {
                            const url = `/wapi/zpgeek/job/detail.json?securityId=${encodeURIComponent(securityId)}&lid=${encodeURIComponent(lid || '')}`;
                            const resp = await fetch(url, { credentials: 'include' });
                            return await resp.json();
                        }""",
                        {"securityId": sec_id, "lid": lid},
                    )
                    if isinstance(detail_data, dict) and detail_data.get("code") == 0:
                        zp_detail = detail_data.get("zpData", {})
                        job_info = zp_detail.get("jobInfo", {}) or {}
                        boss_info = zp_detail.get("bossInfo", {}) or {}

                        post_desc = str(job_info.get("postDescription", "")).strip()
                        address = str(job_info.get("address", "")).strip()
                        active_desc = str(boss_info.get("activeTimeDesc", "")).strip()

                        cand["完整JD"] = post_desc
                        if address:
                            cand["详细地址"] = address
                        if active_desc:
                            cand["HR活跃度"] = active_desc

                        # 用完整 JD 再次更新作息制度识别
                        combined_text = f"{cand.get('福利待遇', '')} {post_desc}"
                        cand["作息制度"] = detect_weekend_policy(combined_text)
                        # 重新计算初筛得分（因为完整 JD 可能包含“周末双休”或行业关键词）
                        cand["初筛得分"] = score_candidate_for_detail(cand, intent)
                except Exception as exc:
                    print(f"[Crawler] 获取岗位详情异常 ({cand.get('岗位名称')}): {exc}")

                time.sleep(random.uniform(0.9, 1.4))

        finally:
            try:
                page.close()
            except Exception:
                pass

    # 导出 Excel
    excel_filename = ""
    if collected_jobs:
        notify(76, "正在生成并导出 Excel 岗位数据表...")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_query = re.sub(r"[^\w\u4e00-\u9fa5-]+", "_", intent.query)
        raw_filename = f"boss_{intent.city_name}_{safe_query}_{timestamp}.xlsx"
        excel_path = export_jobs_to_excel(collected_jobs, raw_filename)
        excel_filename = excel_path.name

    return collected_jobs, top_candidates, excel_filename
