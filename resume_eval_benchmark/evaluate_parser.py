"""Evaluation harness and LLM-as-a-Judge verification suite for boss-zhipin-crawler Stage 1 resume parser."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

# Ensure boss-zhipin-crawler root is importable
BENCHMARK_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BENCHMARK_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_DIR))

from llm_judge_evaluator import PROFILE_FIELD_NAMES, evaluate_profile_with_llm_judge
from schema_and_validator import (
    inspect_text_content_guardrails,
    resolve_safe_path,
    validate_parsed_profile,
    validate_resume_file,
)


def _parse_salary_to_float_w(salary_str: str) -> Optional[float]:
    """Parse salary strings like '1.2w', '1.5w', '15k', '0.6w' into float units of 'w' (10,000 RMB)."""
    s = salary_str.strip().lower()
    m_w = re.search(r"(\d+(?:\.\d+)?)\s*w", s)
    if m_w:
        return float(m_w.group(1))
    m_k = re.search(r"(\d+(?:\.\d+)?)\s*k", s)
    if m_k:
        return float(m_k.group(1)) / 10.0
    return None


def _char_bigram_jaccard(a: str, b: str) -> float:
    """Compute character/token overlap similarity between two Chinese/English strings."""
    a_clean = re.sub(r"\s+", "", a.lower())
    b_clean = re.sub(r"\s+", "", b.lower())
    if not a_clean and not b_clean:
        return 1.0
    if not a_clean or not b_clean:
        return 0.0
    set_a: Set[str] = {a_clean[i : i + 2] for i in range(max(1, len(a_clean) - 1))}
    set_b: Set[str] = {b_clean[i : i + 2] for i in range(max(1, len(b_clean) - 1))}
    return len(set_a & set_b) / float(len(set_a | set_b))


def score_single_prediction_heuristic(
    pred: Dict[str, Any],
    gt: Dict[str, Any],
    raw_pii_tokens: List[str],
) -> Dict[str, Any]:
    """
    Offline deterministic self-check scorer (used when --llm-judge is not enabled).
    Returns field-level scores (0~10 scale) and PII compliance status.
    """
    schema_ok, violations = validate_parsed_profile(pred, forbidden_pii_tokens=raw_pii_tokens)

    title_sim = _char_bigram_jaccard(str(pred.get("candidate_title", "")), gt["candidate_title"]) * 10.0
    years_sim = _char_bigram_jaccard(str(pred.get("years_of_experience", "")), gt["years_of_experience"]) * 10.0

    pred_edu = str(pred.get("education_summary", "")).strip()
    gt_edu = gt["education_summary"].strip()
    if gt_edu == "未注明学历":
        edu_score = 10.0 if ("未注明" in pred_edu or "未提及" in pred_edu or pred_edu == "未注明学历") else 0.0
    else:
        edu_score = 10.0 if pred_edu == gt_edu else _char_bigram_jaccard(pred_edu, gt_edu) * 10.0

    pred_cities = {c.replace("市", "").strip() for c in pred.get("target_cities", []) if isinstance(c, str)}
    gt_cities = {c.replace("市", "").strip() for c in gt["target_cities"]}
    if pred_cities and gt_cities:
        inter = len(pred_cities & gt_cities)
        prec = inter / len(pred_cities)
        rec = inter / len(gt_cities)
        city_f1 = (2 * prec * rec / (prec + rec)) * 10.0 if (prec + rec) > 0 else 0.0
    else:
        city_f1 = 0.0

    ind_sim = _char_bigram_jaccard(
        " ".join(pred.get("industry_background", [])), " ".join(gt["industry_background"])
    ) * 10.0
    skills_sim = _char_bigram_jaccard(
        " ".join(pred.get("core_skills", [])), " ".join(gt["core_skills"])
    ) * 10.0
    highlights_sim = _char_bigram_jaccard(
        " ".join(pred.get("experience_highlights", [])), " ".join(gt["experience_highlights"])
    ) * 10.0

    pred_sal = _parse_salary_to_float_w(str(pred.get("inferred_salary_floor", "")))
    gt_sal = _parse_salary_to_float_w(gt["inferred_salary_floor"])
    if pred_sal is not None and gt_sal is not None and gt_sal > 0:
        rel_err = abs(pred_sal - gt_sal) / gt_sal
        salary_score = max(0.0, 1.0 - max(0.0, rel_err - 0.15) * 2.0) * 10.0
    else:
        salary_score = 0.0

    welfare_sim = _char_bigram_jaccard(
        " ".join(pred.get("inferred_welfare_prefs", [])), " ".join(gt["inferred_welfare_prefs"])
    ) * 10.0

    field_scores = {
        "candidate_title": round(title_sim, 2),
        "years_of_experience": round(years_sim, 2),
        "education_summary": round(edu_score, 2),
        "target_cities": round(city_f1, 2),
        "industry_background": round(ind_sim, 2),
        "core_skills": round(skills_sim, 2),
        "experience_highlights": round(highlights_sim, 2),
        "inferred_salary_floor": round(salary_score, 2),
        "inferred_welfare_prefs": round(welfare_sim, 2),
    }
    overall_score_10 = round(sum(field_scores.values()) / 9.0, 2)

    return {
        "judge_model": "offline_heuristic",
        "schema_and_pii_valid": schema_ok,
        "violations": violations,
        "overall_score_10": overall_score_10,
        "overall_score": round(overall_score_10 / 10.0, 4),
        "entity_match_rate": 1.0 if overall_score_10 >= 8.0 else 0.5,
        "entity_mismatch_fields": [],
        "hallucination_field_count": 0,
        "hallucinated_fields": [],
        "overall_comment": "离线启发式字符二元组基线对比完成。",
        "field_scores": field_scores,
        "field_evaluations": [],
    }


def run_dataset_verification(
    base_dir: Path,
    custom_parser_fn: Optional[Callable[[Path], Dict[str, Any]]] = None,
    use_llm_judge: bool = False,
    judge_model: str = "gemini-3.8-flash",
    extract_model: str = "gemini-3.8-flash",
    sample_ids_filter: Optional[Set[str]] = None,
    extensions_filter: Optional[Set[str]] = None,
    limit: Optional[int] = None,
    skip_disqualified: bool = False,
) -> Dict[str, Any]:
    """
    Evaluate Stage 1 Resume Profile Extraction on Qualified & Disqualified datasets.
    Supports LLM-as-a-Judge 9-field atomic scoring (0~10 scale per field).
    """
    qual_manifest_path = resolve_safe_path(
        str(base_dir / "dataset" / "qualified_manifest.json"), str(base_dir)
    )
    disq_manifest_path = resolve_safe_path(
        str(base_dir / "dataset" / "disqualified_manifest.json"), str(base_dir)
    )

    qual_data = json.loads(qual_manifest_path.read_text(encoding="utf-8"))
    disq_data = json.loads(disq_manifest_path.read_text(encoding="utf-8"))

    samples_to_run = qual_data["samples"]
    if sample_ids_filter:
        samples_to_run = [s for s in samples_to_run if s["id"] in sample_ids_filter]
    if extensions_filter:
        samples_to_run = [s for s in samples_to_run if s["extension"].lower() in extensions_filter]
    if limit is not None and limit > 0:
        samples_to_run = samples_to_run[:limit]

    qual_results: List[Dict[str, Any]] = []
    field_totals: Dict[str, List[float]] = defaultdict(list)
    ext_totals: Dict[str, List[float]] = defaultdict(list)

    for idx, sample in enumerate(samples_to_run, start=1):
        file_path = resolve_safe_path(str(base_dir / sample["relative_path"]), str(base_dir))
        file_ok, err_code, msg = validate_resume_file(str(file_path), allowed_root=str(base_dir))
        content_ok, content_code, content_msg = inspect_text_content_guardrails(sample["raw_resume_text"])

        t0 = time.time()
        if custom_parser_fn is not None:
            print(
                f"[{idx}/{len(samples_to_run)}] Stage 1 Extracting: {sample['id']} ({sample['file_name']})...",
                flush=True,
            )
            pred_profile = custom_parser_fn(file_path)
        else:
            pred_profile = sample["ground_truth"]
        extract_latency_s = round(time.time() - t0, 2)

        t_judge = time.time()
        if use_llm_judge:
            print(
                f"    -> LLM-as-a-Judge Atomic 9-Field Grading ({judge_model})...",
                flush=True,
            )
            eval_metrics = evaluate_profile_with_llm_judge(
                extracted_profile=pred_profile,
                ground_truth=sample["ground_truth"],
                raw_pii_tokens=sample["raw_pii_tokens"],
                raw_resume_text=sample.get("raw_resume_text"),
                judge_model=judge_model,
            )
        else:
            eval_metrics = score_single_prediction_heuristic(
                pred_profile, sample["ground_truth"], sample["raw_pii_tokens"]
            )
        judge_latency_s = round(time.time() - t_judge, 2)

        for fname, fscore in eval_metrics["field_scores"].items():
            field_totals[fname].append(float(fscore))
        ext_totals[sample["extension"]].append(float(eval_metrics["overall_score_10"]))

        if use_llm_judge or custom_parser_fn is not None:
            print(
                f"    => Score: {eval_metrics['overall_score_10']:.2f}/10.0 | "
                f"EntityMatch: {eval_metrics['entity_match_rate'] * 100:.0f}% | "
                f"Hallucinations: {eval_metrics['hallucination_field_count']} | "
                f"PII Safe: {eval_metrics['schema_and_pii_valid']} "
                f"(Extract: {extract_latency_s}s, Judge: {judge_latency_s}s)",
                flush=True,
            )

        qual_results.append(
            {
                "id": sample["id"],
                "file_name": sample["file_name"],
                "extension": sample["extension"],
                "industry_category": sample.get("industry_category", ""),
                "file_validation_passed": file_ok and content_ok,
                "file_validation_code": err_code if not file_ok else content_code,
                "extract_latency_s": extract_latency_s,
                "judge_latency_s": judge_latency_s,
                "ground_truth": sample["ground_truth"],
                "extracted_profile": pred_profile,
                **eval_metrics,
            }
        )

    disq_results: List[Dict[str, Any]] = []
    if not skip_disqualified:
        for sample in disq_data["samples"]:
            file_path = resolve_safe_path(str(base_dir / sample["relative_path"]), str(base_dir))
            file_ok, err_code, msg = validate_resume_file(str(file_path), allowed_root=str(base_dir))
            actual_stage = "pre_parse_file_validation"
            actual_code = err_code

            if file_ok and "raw_text" in sample:
                content_ok, content_code, content_msg = inspect_text_content_guardrails(sample["raw_text"])
                if not content_ok:
                    file_ok = False
                    actual_stage = "content_guardrail_or_parser_rejection"
                    actual_code = content_code
                    msg = content_msg

            correctly_rejected = (not file_ok) and (actual_code == sample["expected_error_code"])
            disq_results.append(
                {
                    "id": sample["id"],
                    "file_name": sample["file_name"],
                    "dimension": sample["dimension"],
                    "expected_error_code": sample["expected_error_code"],
                    "actual_error_code": actual_code,
                    "rejection_stage": actual_stage,
                    "correctly_rejected": correctly_rejected,
                    "message": msg,
                }
            )

    qual_pass_count = sum(
        1 for r in qual_results if r["file_validation_passed"] and r["schema_and_pii_valid"]
    )
    disq_reject_count = sum(1 for r in disq_results if r["correctly_rejected"])

    per_field_mean_scores_10 = {
        fname: round(sum(scores) / len(scores), 2) if scores else 0.0
        for fname in PROFILE_FIELD_NAMES
        for scores in [field_totals.get(fname, [])]
    }
    by_extension_mean_scores_10 = {
        ext: {
            "sample_count": len(scores),
            "mean_score_10": round(sum(scores) / len(scores), 2),
        }
        for ext, scores in sorted(ext_totals.items())
    }

    mean_score_10 = round(
        sum(r["overall_score_10"] for r in qual_results) / max(1, len(qual_results)), 2
    )
    mean_entity_match = round(
        sum(r["entity_match_rate"] for r in qual_results) / max(1, len(qual_results)), 4
    )
    zero_hallucination_count = sum(
        1 for r in qual_results if r["hallucination_field_count"] == 0
    )

    summary = {
        "evaluation_mode": "llm_as_a_judge_atomic_9_fields" if use_llm_judge else "offline_heuristic",
        "extract_model": extract_model if custom_parser_fn is not None else "ground_truth_baseline",
        "judge_model": judge_model if use_llm_judge else "offline_heuristic",
        "qualified_total": len(qual_results),
        "qualified_valid_and_pii_safe": qual_pass_count,
        "qualified_mean_score_10": mean_score_10,
        "qualified_mean_score": round(mean_score_10 / 10.0, 4),
        "qualified_mean_entity_match_rate": mean_entity_match,
        "qualified_zero_hallucination_samples": zero_hallucination_count,
        "per_field_mean_scores_10": per_field_mean_scores_10,
        "by_extension_summary": by_extension_mean_scores_10,
        "disqualified_total": len(disq_results),
        "disqualified_correctly_rejected": disq_reject_count,
        "disqualified_rejection_accuracy": round(
            disq_reject_count / max(1, len(disq_results)), 4
        ) if disq_results else 1.0,
        "qualified_details": qual_results,
        "disqualified_details": disq_results,
    }
    return summary


def print_evaluation_report(report: Dict[str, Any]) -> None:
    """Print structured human-readable summary of Stage 1 evaluation results."""
    print("\n================ STAGE 1 EVALUATION SUMMARY ================")
    print(f"Evaluation Mode     : {report['evaluation_mode']} (Judge: {report['judge_model']})")
    print(
        f"Qualified Samples   : {report['qualified_valid_and_pii_safe']}/{report['qualified_total']} "
        f"passed Schema & PII gates"
    )
    print(
        f"Overall Mean Score  : {report['qualified_mean_score_10']:.2f} / 10.00 "
        f"({report['qualified_mean_score'] * 100:.1f}%)"
    )
    print(f"Entity/Number Match : {report['qualified_mean_entity_match_rate'] * 100:.1f}% of fields")
    print(
        f"Zero-Hallucination  : {report['qualified_zero_hallucination_samples']}/{report['qualified_total']} samples"
    )

    if report.get("per_field_mean_scores_10"):
        print("\n--- Per-Field Mean Scores (0 ~ 10 Scale) ---")
        for fname, score in report["per_field_mean_scores_10"].items():
            print(f"  • {fname:<24}: {score:.2f} / 10.0")

    if report.get("by_extension_summary"):
        print("\n--- Breakdown by File Format ---")
        for ext, info in report["by_extension_summary"].items():
            print(
                f"  • {ext:<8} (n={info['sample_count']:>2}) : {info['mean_score_10']:.2f} / 10.0"
            )

    if report.get("qualified_details") and report["evaluation_mode"].startswith("llm_as_a_judge"):
        print("\n--- Per-Sample Atomic Judge Details ---")
        for item in report["qualified_details"]:
            print(
                f"\n[{item['id']}] {item['file_name']} -> "
                f"Avg Score: {item['overall_score_10']:.2f}/10.0 | "
                f"PII Safe: {item['schema_and_pii_valid']}"
            )
            print(f"  Summary: {item.get('overall_comment', '')}")
            for fe in item.get("field_evaluations", []):
                flags = []
                if not fe["entity_number_match"]:
                    flags.append("ENTITY_MISMATCH")
                if fe["has_hallucination"]:
                    flags.append("HALLUCINATION")
                flag_str = f" [{' | '.join(flags)}]" if flags else ""
                print(
                    f"    - {fe['field_name']:<24}: {fe['score']:>4.1f}/10{flag_str} | {fe['reason']}"
                )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate boss-zhipin-crawler Stage 1 resume profile extractor on benchmark dataset."
    )
    parser.add_argument(
        "--live-gemini",
        action="store_true",
        help="Call core.resume_parser.extract_resume_profile_with_gemini on Qualified samples.",
    )
    parser.add_argument(
        "--llm-judge",
        action="store_true",
        help="Use LLM-as-a-Judge 9-field atomic evaluation (0~10 score per field + reason).",
    )
    parser.add_argument(
        "--extract-model",
        type=str,
        default="gemini-3.8-flash",
        help="Gemini model name for Stage 1 profile extraction.",
    )
    parser.add_argument(
        "--judge-model",
        type=str,
        default="gemini-3.8-flash",
        help="Gemini model name for LLM-as-a-Judge grading.",
    )
    parser.add_argument(
        "--sample-ids",
        type=str,
        default="",
        help="Optional comma-separated sample IDs to run (e.g. 'QUAL-001,QUAL-002').",
    )
    parser.add_argument(
        "--extensions",
        type=str,
        default="",
        help="Optional comma-separated file extensions to filter (e.g. '.pdf,.png,.docx').",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional max number of qualified samples to evaluate.",
    )
    parser.add_argument(
        "--skip-disqualified",
        action="store_true",
        help="Skip running the 20 disqualified file-security checks.",
    )
    parser.add_argument(
        "--output-report",
        type=str,
        default=str(BENCHMARK_DIR / "dataset" / "latest_stage1_eval_report.json"),
        help="Path to save the detailed evaluation JSON report.",
    )
    args = parser.parse_args()

    custom_fn: Optional[Callable[[Path], Dict[str, Any]]] = None
    if args.live_gemini:
        from core.resume_parser import extract_resume_profile_with_gemini

        def _gemini_parse_wrapper(file_path: Path) -> Dict[str, Any]:
            res = extract_resume_profile_with_gemini(
                filename=file_path.name,
                raw_bytes=file_path.read_bytes(),
                model_name=args.extract_model,
            )
            return res["profile"] if isinstance(res, dict) and "profile" in res else res

        custom_fn = _gemini_parse_wrapper

    # When running --live-gemini, default to using --llm-judge unless user explicitly only wants heuristic
    use_judge = args.llm_judge or args.live_gemini

    sample_ids_set = (
        {s.strip() for s in args.sample_ids.split(",") if s.strip()} if args.sample_ids else None
    )
    ext_set = (
        {
            (e.strip().lower() if e.strip().startswith(".") else f".{e.strip().lower()}")
            for e in args.extensions.split(",")
            if e.strip()
        }
        if args.extensions
        else None
    )

    report = run_dataset_verification(
        BENCHMARK_DIR,
        custom_parser_fn=custom_fn,
        use_llm_judge=use_judge,
        judge_model=args.judge_model,
        extract_model=args.extract_model,
        sample_ids_filter=sample_ids_set,
        extensions_filter=ext_set,
        limit=args.limit if args.limit > 0 else None,
        skip_disqualified=args.skip_disqualified,
    )

    print_evaluation_report(report)

    if args.output_report:
        out_path = Path(args.output_report)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[Saved] Detailed evaluation report written to: {out_path}")

    try:
        from eval_store import save_eval_run_archive

        archived_run_id = save_eval_run_archive(
            report,
            stage_id="stage1_profile",
            extract_model=args.extract_model if args.live_gemini else "ground_truth_baseline",
        )
        print(f"[Archived] Evaluation run stored in dashboard history: {archived_run_id}")
    except Exception as exc:
        print(f"[Warn] Failed to archive eval run to store: {exc}")


if __name__ == "__main__":
    main()
