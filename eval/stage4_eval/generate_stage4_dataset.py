#!/usr/bin/env python3
"""
Stage 4 离线候选岗位池与相关性 Ground Truth 生成器（Human-in-the-Loop 人工审核前置脚本）
基于 Stage 3 批准的 6 个跨行业/跨城市 Intent，调用 gemini-4-argon (temperature=0.0)
合成 6 组真实 BOSS直聘结构的候选岗位池（每组 16 条 = 96 条岗位，含 0~3 相关性分级与异地/低薪/作息文字陷阱）
+ 12 条薪资/作息边界用例，输出至 eval/dataset/stage4/stage4_ranking_manifest.json 供人工 Manual Review。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.boss_crawler import parse_salary_bounds
from core.gemini_client import create_interaction_with_fallback, load_backend_api_key

DEFAULT_STAGE3_MANIFEST = BASE_DIR / "eval" / "dataset" / "stage3" / "stage3_intent_manifest.json"
DEFAULT_OUTPUT_MANIFEST = BASE_DIR / "eval" / "dataset" / "stage4" / "stage4_ranking_manifest.json"
DEFAULT_ARGON_MODEL = "gemini-4-argon"

# 从 Stage 3 批准集中精选 6 个跨行业、跨城市、跨薪资档位的代表性场景
SELECTED_STAGE3_CASES = [
    ("S3-QUAL-01-A", False),  # 上海 · 新媒体运营 · >=7K
    ("S3-QUAL-02-B", True),   # 北京 · 大客户销售经理 · >=12K · 要求双休
    ("S3-QUAL-03-B", True),   # 上海 · 交互设计师 · >=8K · 要求双休
    ("S3-QUAL-04-A", True),   # 广州 · Java开发工程师 · >=10K · 要求双休
    ("S3-QUAL-05-B", False),  # 武汉 · 海外商务经理 · >=11K
    ("S3-QUAL-08-B", True),   # 北京 · 研发项目经理 · >=20K · 要求双休
]

BOUNDARY_EDGE_CASES: Dict[str, List[Dict[str, Any]]] = {
    "salary_parse_cases": [
        {"id": "SAL-01", "input": "12-18K·13薪", "expected": [12, 18, 13]},
        {"id": "SAL-02", "input": "1.5-2.5W·14薪", "expected": [15, 25, 14]},
        {"id": "SAL-03", "input": "200-300元/天", "expected": [4, 7, 12]},
        {"id": "SAL-04", "input": "15K", "expected": [15, 15, 12]},
        {"id": "SAL-05", "input": "1.2万", "expected": [12, 12, 12]},
        {"id": "SAL-06", "input": "面议", "expected": [0, 0, 12]},
    ],
    "weekend_policy_cases": [
        {"id": "WKD-01", "input": "提供单双休、五险一金", "expected": "大小周/单双休"},
        {"id": "WKD-02", "input": "隔周双休，弹性打卡", "expected": "大小周/单双休"},
        {"id": "WKD-03", "input": "非双休，介意勿投", "expected": "排班轮休/单休"},
        {"id": "WKD-04", "input": "不双休，做六休一", "expected": "排班轮休/单休"},
        {"id": "WKD-05", "input": "周末双休，五险一金，带薪年假", "expected": "周末双休"},
        {"id": "WKD-06", "input": "五天八小时，法休齐全", "expected": "周末双休"},
    ],
}


class SyntheticBossJob(BaseModel):
    """单条合成 BOSS直聘候选岗位（ASCII Schema 字段，写入时映射为 BOSS 中文标准键）"""

    job_id: str = Field(description="岗位唯一编号，如 J01~J16")
    job_name: str = Field(description="BOSS直聘真实风格职位名称")
    salary_desc: str = Field(description="如 '12-18K·13薪'、'1.5-2.2W'、'6-8K'")
    location: str = Field(description="格式：'城市·区·商圈'，如 '广州·天河区·珠江新城'")
    experience: str = Field(default="3-5年")
    degree: str = Field(default="本科")
    company_name: str = Field(description="逼真的企业简称")
    industry: str = Field(description="BOSS直聘行业分类")
    stage: str = Field(default="已上市")
    scale: str = Field(description="如 '1000-9999人'、'100-499人'、'20-99人'")
    boss_online: bool = Field(default=True)
    skills: str = Field(description="逗号分隔的 2~4 个技能标签")
    welfare: str = Field(description="逗号分隔的福利标签，如 '周末双休, 五险一金, 年终奖' 或 '单双休, 绩效奖金'")
    full_jd: str = Field(default="", description="1~2句简短职责/作息描述")
    ground_truth_grade: int = Field(
        ge=0,
        le=3,
        description="黄金相关性等级：3=极高匹配(必进Top8), 2=良好匹配(应进Top8), 1=一般匹配(合规但弱相关), 0=噪音或降权陷阱(异地/低薪/无关)",
    )
    trap_type: str = Field(
        default="none",
        description="样本类型标签：'none' | 'synonym_title' | 'off_city' | 'low_salary' | 'weekend_trap' | 'irrelevant_domain'",
    )
    annotation_reason: str = Field(description="1句话标注理由（供人工 Manual Review）")


class Stage4ScenarioDatasetSchema(BaseModel):
    """单个评测场景的 16 条候选岗位池"""

    jobs: List[SyntheticBossJob]


def _generate_single_scenario(
    scenario_idx: int,
    stage3_sample: Dict[str, Any],
    require_double_weekend: bool,
    model_name: str,
    api_key: Optional[str],
) -> Dict[str, Any]:
    """调用 gemini-4-argon 为单个 Stage 3 Intent 合成 16 条含陷阱的 BOSS直聘候选岗位池。"""
    t0 = time.perf_counter()
    gt = stage3_sample["ground_truth"]
    inp = stage3_sample["input"]
    profile = inp.get("resume_profile") or {}

    intent_dict = {
        "raw_query": inp["query_text"] + ("，要求周末双休" if require_double_weekend else ""),
        "query": gt["expected_query"],
        "city_name": gt["expected_city_name"],
        "city_code": gt["expected_city_code"],
        "salary_code": gt["expected_salary_code"],
        "salary_label": gt.get("expected_salary_label", ""),
        "min_salary_k": gt["expected_min_salary_k"],
        "industry_keywords": gt["expected_industry_keywords"],
        "require_double_weekend": require_double_weekend,
        "soft_requirements": gt.get("expected_soft_requirements", [])
        + (["周末双休"] if require_double_weekend else []),
    }

    prompt = (
        "你是 BOSS直聘 智能求职系统的 Stage 4 离线排序评测数据集构建专家。\n"
        "请针对以下候选人求职意图，生成 **精确 16 条** 高度逼真的 BOSS直聘候选岗位数据（job_id 为 J01~J16），"
        "用于评测 Stage 4 粗排打分器与异地/低薪垫底降权逻辑。\n\n"
        f"【目标核心岗位 query】：{intent_dict['query']}\n"
        f"【目标城市 city_name】：{intent_dict['city_name']}\n"
        f"【最低月薪要求 min_salary_k】：{intent_dict['min_salary_k']}K\n"
        f"【目标行业关键词】：{json.dumps(intent_dict['industry_keywords'], ensure_ascii=False)}\n"
        f"【是否要求周末双休】：{require_double_weekend}\n"
        f"【候选人核心技能】：{json.dumps(profile.get('core_skills', [])[:6], ensure_ascii=False)}\n\n"
        "【严格配比要求（共 16 条，请打乱顺序输出，禁止按 grade 排序！）】：\n"
        "1. **4 条 Grade=3（极高匹配正例）**：目标城市内、最低月薪 >= min_salary_k、岗位标题精准匹配目标岗位、行业高度匹配、命中候选人核心技能"
        + ("、且明确周末双休" if require_double_weekend else "")
        + "（trap_type='none'）。\n"
        "2. **4 条 Grade=2（良好匹配 / 同义标题正例）**：目标城市内、最高月薪 >= min_salary_k、至少 2 条使用**同义/变体职位名**（不包含完整 query 字面串但属同一岗位，trap_type='synonym_title'），行业相关。\n"
        "3. **3 条 Grade=1（合规但弱相关）**：目标城市内、薪资达标，但行业偏离或作息为“单双休/隔周双休/非双休”（至少 1 条放 trap_type='weekend_trap' 测试作息误判防线）。\n"
        "4. **5 条 Grade=0（降权陷阱与噪音）**：\n"
        "   - 精确 **2 条异地陷阱**（trap_type='off_city'）：工作地点为**非目标城市**（如周边城市或其他一线城市），即使岗位名称和薪资都很高也要标注 grade=0；\n"
        "   - 精确 **2 条低薪陷阱**（trap_type='low_salary'）：在目标城市内，但**最高月薪严格低于 min_salary_k**（如 min_salary_k=10 则给 '5-8K'），标注 grade=0；\n"
        "   - 精确 **1 条跨行业无关噪音**（trap_type='irrelevant_domain'）：在目标城市内且薪资达标，但岗位与行业完全不相关，标注 grade=0。\n\n"
        "注意：所有薪资范围必须是可解析的标准格式（如 '12-18K·13薪'、'6-8K'、'1.5-2.2W'），禁止写'面议'。"
    )

    raw_json = create_interaction_with_fallback(
        model=model_name,
        prompt=prompt,
        schema_cls=Stage4ScenarioDatasetSchema,
        temperature=0.0,
        api_key=api_key,
    )
    parsed = Stage4ScenarioDatasetSchema.model_validate_json(raw_json)

    # 确定性校验与补齐 expected_demoted 标签
    jobs_out: List[Dict[str, Any]] = []
    target_city = intent_dict["city_name"]
    min_sal = int(intent_dict["min_salary_k"])
    for j in parsed.jobs:
        low_k, high_k, months = parse_salary_bounds(j.salary_desc)
        loc = j.location
        exp_city_mis = bool(target_city and target_city != "全国" and loc and target_city not in loc)
        exp_low_sal = bool(min_sal > 0 and high_k > 0 and high_k < min_sal)
        jd = {
            "job_id": j.job_id,
            "岗位名称": j.job_name,
            "薪资范围": j.salary_desc,
            "最低月薪K": low_k,
            "最高月薪K": high_k,
            "计薪月数": months,
            "工作地点": loc,
            "经验要求": j.experience,
            "学历要求": j.degree,
            "公司名称": j.company_name,
            "所属行业": j.industry,
            "融资阶段": j.stage,
            "公司规模": j.scale,
            "BOSS在线": j.boss_online,
            "技能标签": j.skills,
            "福利待遇": j.welfare,
            "完整JD": j.full_jd,
            "ground_truth_grade": j.ground_truth_grade,
            "trap_type": j.trap_type,
            "annotation_reason": j.annotation_reason,
            "expected_city_mismatch": exp_city_mis,
            "expected_below_salary_floor": exp_low_sal,
            "expected_demoted": exp_city_mis or exp_low_sal,
        }
        jobs_out.append(jd)

    return {
        "scenario_id": f"S4-SCEN-0{scenario_idx + 1}",
        "source_stage3_case_id": stage3_sample["case_id"],
        "source_sample_id": stage3_sample["source_sample_id"],
        "industry_category": stage3_sample.get("industry_category", ""),
        "intent": intent_dict,
        "resume_profile": {
            "candidate_title": profile.get("candidate_title", ""),
            "core_skills": profile.get("core_skills", []),
            "industry_background": profile.get("industry_background", []),
        },
        "total_jobs": len(jobs_out),
        "expected_demoted_count": sum(1 for x in jobs_out if x["expected_demoted"]),
        "grade_counts": {
            "grade_3": sum(1 for x in jobs_out if x["ground_truth_grade"] == 3),
            "grade_2": sum(1 for x in jobs_out if x["ground_truth_grade"] == 2),
            "grade_1": sum(1 for x in jobs_out if x["ground_truth_grade"] == 1),
            "grade_0": sum(1 for x in jobs_out if x["ground_truth_grade"] == 0),
        },
        "jobs": jobs_out,
        "generation_latency_s": round(time.perf_counter() - t0, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="使用 gemini-4-argon 生成 Stage 4 离线岗位池与 Ground Truth 草案")
    parser.add_argument("--stage3-manifest", type=Path, default=DEFAULT_STAGE3_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_MANIFEST)
    parser.add_argument("--model", type=str, default=DEFAULT_ARGON_MODEL)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()

    if not args.stage3_manifest.is_file():
        raise FileNotFoundError(f"找不到 Stage 3 Ground Truth 文件: {args.stage3_manifest}")

    s3_data = json.loads(args.stage3_manifest.read_text(encoding="utf-8"))
    s3_by_id = {s["case_id"]: s for s in s3_data.get("samples", [])}

    tasks = []
    for idx, (cid, req_wkd) in enumerate(SELECTED_STAGE3_CASES):
        if cid not in s3_by_id:
            raise KeyError(f"Stage 3 清单中缺少用例: {cid}")
        tasks.append((idx, s3_by_id[cid], req_wkd))

    api_key = load_backend_api_key()
    print(f"[Stage4-GT] 正在调用 {args.model} (temperature=0.0) 生成 {len(tasks)} 组离线候选岗位池 (96 条岗位)...")

    results_by_idx: Dict[int, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        fmap = {
            pool.submit(_generate_single_scenario, idx, sample, req_wkd, args.model, api_key): idx
            for idx, sample, req_wkd in tasks
        }
        for fut in as_completed(fmap):
            idx = fmap[fut]
            res = fut.result()
            results_by_idx[idx] = res
            gc = res["grade_counts"]
            print(
                f"  ✓ {res['scenario_id']} ({res['intent']['city_name']} · {res['intent']['query']} · >={res['intent']['min_salary_k']}K) | "
                f"jobs={res['total_jobs']} | grades(3/2/1/0)={gc['grade_3']}/{gc['grade_2']}/{gc['grade_1']}/{gc['grade_0']} | "
                f"demoted={res['expected_demoted_count']} ({res['generation_latency_s']}s)"
            )

    scenarios = [results_by_idx[i] for i in range(len(tasks))]
    manifest = {
        "schema_version": "stage4_ranking_ground_truth_v1",
        "review_status": "PENDING_MANUAL_REVIEW",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "generator_model": args.model,
        "temperature": 0.0,
        "total_scenarios": len(scenarios),
        "total_jobs": sum(s["total_jobs"] for s in scenarios),
        "boundary_edge_cases": BOUNDARY_EDGE_CASES,
        "scenarios": scenarios,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[Stage4-GT] 已保存 Stage 4 离线数据集与 Ground Truth 草案至: {args.output}")
    print("[Stage4-GT] 请完成人工 Manual Review 后，再运行 Stage 4 Eval！")


if __name__ == "__main__":
    main()
