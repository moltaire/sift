"""Evaluate LLM-based spam filters against ground-truth labels in the DB.

Modes:
  title   — title_spam_check: qwen3.5:9b think=False on job title + employer
  listing — llm_spam_check:   qwen3.5:9b think=False on first 2000 chars of listing

Usage:
    python eval_title_spam.py                    # title mode
    python eval_title_spam.py --mode listing
    python eval_title_spam.py --mode both
    python eval_title_spam.py --show-errors
"""

import argparse
import sqlite3
import time
from pathlib import Path

from fumble.extract import (
    _SPAM_PROMPT, _SPAM_SYSTEM, _SpamResult,
    _TITLE_SPAM_PROMPT, _TITLE_SPAM_SYSTEM, _TitleSpamResult,
)
from fumble.llm import MODEL, call_llm
from fumble.store import DB_PATH, init_db

CRITERIA = Path("resources/search-criteria.md").read_text()
_SPAM_CHAR_LIMIT = 2_000

_LABEL_MAP = {
    "spam": "spam",
    "disliked": "good",
    "liked": "good",
    "superliked": "good",
}


def load_labelled() -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT id, job_title, employer, listing_text, rating
        FROM assessments
        WHERE rating IN ('spam', 'liked', 'disliked', 'superliked')
        ORDER BY id
        """
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def check_title(row: dict) -> tuple[bool, str, float]:
    prompt = _TITLE_SPAM_PROMPT.format(job_title=row["job_title"], employer=row["employer"])
    t0 = time.monotonic()
    try:
        content = call_llm(_TITLE_SPAM_SYSTEM, prompt, _TitleSpamResult.model_json_schema(),
                           model=MODEL, think=False)
        result = _TitleSpamResult.model_validate_json(content)
        return result.is_spam, result.reason, time.monotonic() - t0
    except Exception:
        return False, "", time.monotonic() - t0


def check_listing(row: dict) -> tuple[bool, str, float]:
    prompt = _SPAM_PROMPT.format(
        criteria_text=CRITERIA,
        listing_text=(row["listing_text"] or "")[:_SPAM_CHAR_LIMIT],
    )
    t0 = time.monotonic()
    try:
        content = call_llm(_SPAM_SYSTEM, prompt, _SpamResult.model_json_schema(),
                           model=MODEL, think=False)
        result = _SpamResult.model_validate_json(content)
        return result.is_spam, result.reason, time.monotonic() - t0
    except Exception:
        return False, "", time.monotonic() - t0


def run_eval(labelled: list[dict], check_fn, label: str, show_errors: bool) -> dict:
    total = len(labelled)
    print(f"\n── {label} ──")
    results = []
    t_total = 0.0
    for i, row in enumerate(labelled, 1):
        true_label = _LABEL_MAP[row["rating"]]
        predicted, reason, elapsed = check_fn(row)
        t_total += elapsed
        pred_label = "spam" if predicted else "good"
        correct = pred_label == true_label
        results.append({**row, "true_label": true_label, "pred_label": pred_label,
                        "reason": reason, "correct": correct, "elapsed": elapsed})
        mark = "✓" if correct else "✗"
        print(f"[{i:3}/{total}] {mark} {elapsed:4.1f}s  [{row['rating']:>9} → {true_label}]  "
              f"pred={pred_label:<4}  {row['job_title'][:50]}")

    tp = sum(r["true_label"] == "spam" and r["pred_label"] == "spam" for r in results)
    fp = sum(r["true_label"] == "good" and r["pred_label"] == "spam" for r in results)
    fn = sum(r["true_label"] == "spam" and r["pred_label"] == "good" for r in results)
    tn = sum(r["true_label"] == "good" and r["pred_label"] == "good" for r in results)
    n_spam = tp + fn
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall    = tp / (tp + fn) if (tp + fn) else 0.0
    f1        = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    t_avg = t_total / total
    slowest = max(results, key=lambda r: r["elapsed"])
    print(f"""
  Precision  {precision:.1%}   FP={fp} (good jobs wrongly blocked)
  Recall     {recall:.1%}   FN={fn} (spam that got through)
  F1         {f1:.1%}   TP={tp} TN={tn}
  Avg/call   {t_avg:.1f}s   total={t_total:.0f}s
  Slowest    {slowest['elapsed']:.1f}s  ({slowest['job_title'][:50]})
  Saves      ~{tp * 4:.0f} min at 4 min/assessment ({tp}/{n_spam} spam caught)""")

    if show_errors:
        fps = [r for r in results if r["true_label"] == "good" and r["pred_label"] == "spam"]
        fns = [r for r in results if r["true_label"] == "spam" and r["pred_label"] == "good"]
        if fps:
            print(f"\n  False Positives ({len(fps)}) — good jobs wrongly blocked:")
            for r in fps:
                print(f"    [{r['rating']:>9}]  {r['job_title']} @ {r['employer']}"
                      + (f"  → {r['reason']}" if r["reason"] else ""))
        if fns:
            print(f"\n  False Negatives ({len(fns)}) — spam that got through:")
            for r in fns:
                print(f"    [{r['rating']:>9}]  {r['job_title']} @ {r['employer']}")

    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "t_avg": t_avg}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["title", "listing", "both"], default="title")
    parser.add_argument("--show-errors", action="store_true")
    args = parser.parse_args()

    init_db()
    labelled = load_labelled()
    print(f"Evaluating {len(labelled)} labelled assessments with model={MODEL}, think=False")

    if args.mode in ("title", "both"):
        run_eval(labelled, check_title, f"TITLE  (job_title + employer → {MODEL})", args.show_errors)

    if args.mode in ("listing", "both"):
        run_eval(labelled, check_listing, f"LISTING  (first {_SPAM_CHAR_LIMIT} chars → {MODEL})", args.show_errors)


if __name__ == "__main__":
    main()
