import numpy as np
from numpy.linalg import norm

import ollama

EMBED_MODEL = "nomic-embed-text"

# nomic-embed-text has an 8192-token context window (~4 chars/token for DE/EN text).
# 6000 chars ≈ 1500 tokens — safely within limits with room to spare.
_CHUNK_SIZE = 6_000
_CHUNK_OVERLAP = 200


def embed_text(text: str, model: str = EMBED_MODEL) -> np.ndarray:
    """Embed text and return a float32 vector.

    If the text exceeds _CHUNK_SIZE characters it is split into overlapping
    chunks, each chunk is embedded in a single batched Ollama call, and the
    resulting vectors are mean-pooled into one representative vector.
    """
    if len(text) <= _CHUNK_SIZE:
        response = ollama.embed(model=model, input=text)
        return np.array(response.embeddings[0], dtype=np.float32)

    step = _CHUNK_SIZE - _CHUNK_OVERLAP
    chunks = [text[i : i + _CHUNK_SIZE] for i in range(0, len(text), step)]
    response = ollama.embed(model=model, input=chunks)
    vecs = np.array(response.embeddings, dtype=np.float32)
    return vecs.mean(axis=0)


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (norm(a) * norm(b)))


def classify_spam(vec: np.ndarray, labelled: list[tuple[np.ndarray, str]]) -> str:
    """Centroid-based binary classify. Returns 'spam' or 'good'.
    Requires at least one sample from each class; returns 'good' if a class is missing."""
    spam_vecs = [v for v, label in labelled if label == "spam"]
    good_vecs = [v for v, label in labelled if label == "good"]

    if not spam_vecs or not good_vecs:
        return "good"

    spam_centroid = np.mean(spam_vecs, axis=0)
    good_centroid = np.mean(good_vecs, axis=0)

    return "spam" if _cosine_sim(vec, spam_centroid) > _cosine_sim(vec, good_centroid) else "good"


def backfill(model: str = EMBED_MODEL) -> None:
    """Embed all assessments that don't yet have an embedding stored."""
    from fumble import store

    with store._connect() as conn:
        rows = conn.execute(
            "SELECT id, job_title, employer, listing_text FROM assessments"
        ).fetchall()

    total = len(rows)
    print(f"Backfilling embeddings for {total} assessments (model={model})...")

    title_ok = title_skip = listing_ok = listing_skip = 0

    for i, row in enumerate(rows, 1):
        assessment_id = row["id"]
        job_title = row["job_title"] or ""
        employer = row["employer"] or ""
        listing_text = row["listing_text"] or ""

        title_text = f"{job_title} at {employer}"
        if title_text.strip(" at"):
            try:
                vec = embed_text(title_text, model=model)
                store.store_embedding(assessment_id, model, "title", vec)
                title_ok += 1
            except Exception as e:
                print(f"  [{i}/{total}] title failed (id={assessment_id}): {e}")
                title_skip += 1

        if listing_text.strip():
            try:
                vec = embed_text(listing_text, model=model)
                store.store_embedding(assessment_id, model, "listing", vec)
                listing_ok += 1
            except Exception as e:
                print(f"  [{i}/{total}] listing failed (id={assessment_id}): {e}")
                listing_skip += 1

        if i % 10 == 0 or i == total:
            print(f"  {i}/{total} done")

    print(
        f"Backfill complete. "
        f"title: {title_ok} stored, {title_skip} failed. "
        f"listing: {listing_ok} stored, {listing_skip} failed."
    )
