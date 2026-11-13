#!/usr/bin/env python3
"""
BOSS直聘岗位数据采集 PoC
默认验证条件：
- 岗位关键词 (query): 店面督导
- 城市 (city): 深圳 (101280600)
- 薪资范围 (salary): 10-20K / 1w-2w (405)
- 导出格式: Excel (.xlsx)
"""

import argparse
import os
import random
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from playwright.sync_api import Page, Response, Route, sync_playwright

# 常用城市编码映射
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
}

# BOSS直聘薪资筛选编码映射
SALARY_CODE_MAP: Dict[str, str] = {
    "3k以下": "402",
    "3-5k": "403",
    "5-10k": "404",
    "10-20k": "405",
    "1w-2w": "405",
    "20-50k": "406",
    "50k以上": "407",
}

OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def build_search_url(query: str, city_code: str, salary_code: str) -> str:
    """构造新版 BOSS直聘 搜索页 URL (/web/geek/jobs)"""
    params = {
        "query": query,
        "city": city_code,
        "salary": salary_code,
    }
    return f"https://www.zhipin.com/web/geek/jobs?{urllib.parse.urlencode(params)}"


def parse_api_job_item(item: Dict[str, Any]) -> Dict[str, str]:
    """解析 /wapi/zpgeek/search/joblist.json 中的单条岗位 JSON"""
    area_parts = [
        item.get("cityName", ""),
        item.get("areaDistrict", ""),
        item.get("businessDistrict", ""),
    ]
    location = "·".join([p for p in area_parts if p])

    skills = item.get("skills") or []
    welfare = item.get("welfareList") or []
    encrypt_job_id = item.get("encryptJobId", "")
    job_url = f"https://www.zhipin.com/job_detail/{encrypt_job_id}.html" if encrypt_job_id else ""

    return {
        "岗位名称": str(item.get("jobName", "")),
        "薪资范围": str(item.get("salaryDesc", "")),
        "工作地点": location,
        "经验要求": str(item.get("jobExperience", "")),
        "学历要求": str(item.get("jobDegree", "")),
        "公司名称": str(item.get("brandName", "")),
        "所属行业": str(item.get("brandIndustry", "")),
        "融资阶段": str(item.get("brandStageName", "")),
        "公司规模": str(item.get("brandScaleName", "")),
        "招聘人": f"{item.get('bossName', '')} ({item.get('bossTitle', '')})".strip(" ()"),
        "技能标签": ", ".join(skills) if isinstance(skills, list) else str(skills),
        "福利待遇": ", ".join(welfare) if isinstance(welfare, list) else str(welfare),
        "岗位链接": job_url,
    }


def extract_jobs_from_dom(page: Page) -> List[Dict[str, str]]:
    """当接口未被拦截时的 DOM 兜底提取方案（兼容新旧版卡片选择器）"""
    cards = page.locator(".job-card-box, .job-card-wrapper").all()
    results: List[Dict[str, str]] = []

    for card in cards:
        try:
            job_name = card.locator(".job-name").first.inner_text().strip()
            salary = card.locator(".job-salary, .salary").first.inner_text().strip()
            area = (
                card.locator(".company-location, .job-area").first.inner_text().strip()
                if card.locator(".company-location, .job-area").count() > 0
                else ""
            )
            tag_items = card.locator(".tag-list li").all_inner_texts()
            exp = tag_items[0].strip() if len(tag_items) > 0 else ""
            degree = tag_items[1].strip() if len(tag_items) > 1 else ""

            company_name = (
                card.locator(".boss-name, .company-name").first.inner_text().strip()
                if card.locator(".boss-name, .company-name").count() > 0
                else ""
            )
            href = card.locator("a.job-name, a.job-card-left").first.get_attribute("href") or ""
            job_url = urllib.parse.urljoin("https://www.zhipin.com", href) if href else ""

            results.append(
                {
                    "岗位名称": job_name,
                    "薪资范围": salary,
                    "工作地点": area,
                    "经验要求": exp,
                    "学历要求": degree,
                    "公司名称": company_name,
                    "所属行业": "",
                    "融资阶段": "",
                    "公司规模": "",
                    "招聘人": "",
                    "技能标签": ", ".join([t.strip() for t in tag_items[2:] if t.strip()]),
                    "福利待遇": "",
                    "岗位链接": job_url,
                }
            )
        except Exception:
            continue

    return results


def export_to_excel(jobs: List[Dict[str, str]], output_filename: str) -> Path:
    """将岗位列表导出为格式化的 Excel (.xlsx) 文件"""
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
        "技能标签",
        "福利待遇",
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
        ws.append([job.get(h, "") for h in headers])

    col_widths = [26, 15, 22, 12, 12, 24, 16, 14, 14, 22, 32, 36, 48]
    for idx, width in enumerate(col_widths, start=1):
        col_letter = ws.cell(row=1, column=idx).column_letter
        ws.column_dimensions[col_letter].width = width

    wb.save(output_path)
    return output_path


def run_crawler(
    cdp_url: str,
    query: str,
    city: str,
    salary: str,
    max_pages: int,
) -> List[Dict[str, str]]:
    city_code = CITY_CODE_MAP.get(city, city)
    salary_code = SALARY_CODE_MAP.get(salary.lower(), salary)

    collected_jobs: List[Dict[str, str]] = []
    seen_keys = set()
    batch_queue: List[List[Dict[str, str]]] = []
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
                        print(f"  [API拦截成功] 捕获到 {len(parsed)} 条岗位数据")
                else:
                    print(f"  [API提示] 返回状态码 code={data.get('code')}, message={data.get('message')}")
            except Exception as exc:
                print(f"  [API解析警告] 无法解析响应 JSON: {exc}")

    print(f"正在连接本地 Chrome 调试端口: {cdp_url} ...")
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(cdp_url)
        except Exception as exc:
            raise RuntimeError(
                f"无法连接到 Chrome ({cdp_url})。\n"
                "请先运行 ./start_chrome.sh 启动带远程调试端口的 Chrome 并登录 BOSS直聘！"
            ) from exc

        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()
        page.route("**/static.zhipin.com/**/*.js*", handle_js_route)
        page.on("response", handle_response)

        try:
            target_url = build_search_url(query, city_code, salary_code)
            print(f"\n---> 正在打开搜索页并抓取第 1/{max_pages} 批: {target_url}")
            page.goto(target_url, wait_until="domcontentloaded", timeout=30000)

            for page_num in range(1, max_pages + 1):
                # 等待当前批次的 API 响应到达
                wait_rounds = 0
                while len(batch_queue) < page_num and wait_rounds < 20:
                    page.wait_for_timeout(500)
                    # 如果等待超过 2.5 秒仍未触发下一批请求，做一次小幅回滚再触底以激活懒加载监听
                    if wait_rounds in (5, 10, 15) and page_num > 1:
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

                if len(batch_queue) >= page_num:
                    page_jobs = batch_queue[page_num - 1]
                else:
                    if "security-check" in page.url or "verify" in page.url:
                        input("  [注意] 检测到滑块/安全验证！请在浏览器窗口手动完成验证后，按回车键继续...")
                    print("  [提示] 未从 API 捕获到更多批次数据，停止翻页。")
                    break

                added_count = 0
                for job in page_jobs:
                    unique_key = job.get("岗位链接") or f"{job.get('岗位名称')}_{job.get('公司名称')}"
                    if unique_key not in seen_keys:
                        seen_keys.add(unique_key)
                        collected_jobs.append(job)
                        added_count += 1

                print(
                    f"  [进度] 第 {page_num}/{max_pages} 批新增 {added_count} 条岗位，"
                    f"累计已采集 {len(collected_jobs)} 条 (hasMore={has_more_flag})。"
                )

                if not has_more_flag:
                    print("  [结束] 接口提示已加载全部匹配岗位 (hasMore=False)。")
                    break

                if page_num < max_pages:
                    delay = random.uniform(2.0, 3.5)
                    print(f"  [滚动加载] 等待 {delay:.1f} 秒后向下滚动加载第 {page_num + 1}/{max_pages} 批...")
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
        finally:
            try:
                page.close()
            except Exception:
                pass

    return collected_jobs


def main() -> None:
    parser = argparse.ArgumentParser(description="BOSS直聘岗位数据采集 PoC")
    parser.add_argument("--query", default="店面督导", help="搜索岗位关键词 (默认: 店面督导)")
    parser.add_argument("--city", default="深圳", help="城市名称或城市编码 (默认: 深圳)")
    parser.add_argument("--salary", default="1w-2w", help="薪资范围，如 1w-2w / 10-20k (默认: 1w-2w)")
    parser.add_argument("--pages", type=int, default=30, help="最大抓取批次/页数，每批15条，遇到 hasMore=False 自动停止 (默认: 30)")
    parser.add_argument("--cdp", default="http://127.0.0.1:9222", help="Chrome CDP 调试地址")
    args = parser.parse_args()

    print("=" * 60)
    print("BOSS直聘 PoC 采集任务启动")
    print(f"筛选条件 -> 岗位: [{args.query}] | 地区: [{args.city}] | 薪资: [{args.salary}] | 最大批次: [{args.pages}]")
    print("=" * 60)

    jobs = run_crawler(
        cdp_url=args.cdp,
        query=args.query,
        city=args.city,
        salary=args.salary,
        max_pages=max(1, min(args.pages, 100)),
    )

    if not jobs:
        print("\n未采集到任何岗位数据，请确认已在调试浏览器中登录 BOSS直聘。")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"boss_{args.city}_{args.query}_{args.salary}_{timestamp}.xlsx"
    output_path = export_to_excel(jobs, filename)

    print("\n" + "=" * 60)
    print(f"采集完成！共获取 {len(jobs)} 条岗位数据。")
    print(f"Excel 文件已保存至: {output_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
