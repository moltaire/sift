"""Leave-one-out cross-validation for the spam classifier.

Compares centroid and kNN classifiers across title and listing inputs.

Usage:
    python eval_embeddings.py                      # both inputs, centroid + kNN
    python eval_embeddings.py --input title
    python eval_embeddings.py --classifier centroid
    python eval_embeddings.py --k 3 --k 5 --k 11  # specific k values
"""

import argparse

import numpy as np
from numpy.linalg import norm

from fumble.embeddings import EMBED_MODEL, classify_spam
from fumble.store import init_db, load_labelled_embeddings


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (norm(a) * norm(b)))


def _knn_classify(vec: np.ndarray, labelled: list[tuple[np.ndarray, str]], k: int) -> str:
    sims = [(_cosine_sim(vec, v), label) for v, label in labelled]
    sims.sort(key=lambda x: x[0], reverse=True)
    neighbours = [label for _, label in sims[:k]]
    return "spam" if neighbours.count("spam") > neighbours.count("good") else "good"


def _metrics(y_true: list[str], y_pred: list[str], n_spam: int, n_good: int) -> dict:
    spam_tp = sum(t == "spam" and p == "spam" for t, p in zip(y_true, y_pred))
    spam_fp = sum(t == "good" and p == "spam" for t, p in zip(y_true, y_pred))
    spam_fn = sum(t == "spam" and p == "good" for t, p in zip(y_true, y_pred))
    spam_tn = sum(t == "good" and p == "good" for t, p in zip(y_true, y_pred))
    precision = spam_tp / (spam_tp + spam_fp) if (spam_tp + spam_fp) else 0.0
    recall    = spam_tp / (spam_tp + spam_fn) if (spam_tp + spam_fn) else 0.0
    f1        = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "n": len(y_true), "n_spam": n_spam, "n_good": n_good,
        "tp": spam_tp, "fp": spam_fp, "fn": spam_fn, "tn": spam_tn,
        "precision": precision, "recall": recall, "f1": f1,
        "accuracy": (spam_tp + spam_tn) / len(y_true),
    }


def loo_centroid(labelled: list[tuple[np.ndarray, str]]) -> dict:
    y_true, y_pred = [], []
    for i, (vec, label) in enumerate(labelled):
        rest = [item for j, item in enumerate(labelled) if j != i]
        y_pred.append(classify_spam(vec, rest))
        y_true.append(label)
    n_spam = sum(l == "spam" for _, l in labelled)
    return _metrics(y_true, y_pred, n_spam, len(labelled) - n_spam)


def loo_knn(labelled: list[tuple[np.ndarray, str]], k: int) -> dict:
    y_true, y_pred = [], []
    for i, (vec, label) in enumerate(labelled):
        rest = [item for j, item in enumerate(labelled) if j != i]
        y_pred.append(_knn_classify(vec, rest, k))
        y_true.append(label)
    n_spam = sum(l == "spam" for _, l in labelled)
    return _metrics(y_true, y_pred, n_spam, len(labelled) - n_spam)


def print_report(label: str, m: dict) -> None:
    print(f"  {label:<20} P={m['precision']:.0%}  R={m['recall']:.0%}  F1={m['f1']:.0%}  "
          f"acc={m['accuracy']:.0%}  TP={m['tp']} FP={m['fp']} FN={m['fn']} TN={m['tn']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", choices=["title", "listing", "both"], default="both")
    parser.add_argument("--classifier", choices=["centroid", "knn", "both"], default="both")
    parser.add_argument("--k", type=int, action="append", dest="ks",
                        help="k for kNN (repeatable, default: 3 5 7 11)")
    parser.add_argument("--model", default=EMBED_MODEL)
    args = parser.parse_args()

    ks = args.ks or [3, 5, 7, 11]
    input_types = ["title", "listing"] if args.input == "both" else [args.input]

    init_db()

    for input_type in input_types:
        labelled = load_labelled_embeddings(model=args.model, input_type=input_type)
        if not labelled:
            print(f"\n{input_type}: no embeddings found — run backfill first.")
            continue

        n_spam = sum(l == "spam" for _, l in labelled)
        n_good = len(labelled) - n_spam
        print(f"\n── {input_type.upper()} (n={len(labelled)}: {n_spam} spam, {n_good} good) ──")
        print(f"  {'classifier':<20} {'P':>4}  {'R':>4}  {'F1':>4}  {'acc':>4}  confusion")

        if args.classifier in ("centroid", "both"):
            m = loo_centroid(labelled)
            print_report("centroid", m)

        if args.classifier in ("knn", "both"):
            for k in ks:
                m = loo_knn(labelled, k)
                print_report(f"kNN k={k}", m)


if __name__ == "__main__":
    main()
