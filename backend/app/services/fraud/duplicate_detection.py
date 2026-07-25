"""
HireLens — Cross-Candidate Duplicate / Template Detection

Single-resume analysis can never catch this: if 5 "different" candidates in
the same batch all submit near-identical resumes (same "resume writing
service" template, or the same person applying under multiple names), no
amount of per-resume credibility scoring will notice — each one individually
can look perfectly fine. This only becomes visible when you compare
candidates AGAINST EACH OTHER within a batch.

Approach: k-word shingling + Jaccard similarity — a well-established,
computationally cheap plagiarism-detection technique that needs no external
API, no embeddings model, no cost. It operates on the resume's ALREADY-
EXTRACTED verbatim bullets/summary (the same text the credibility analysis
already stored), not on raw file contents — so this adds zero extra parsing
or storage.

Honesty note: two candidates in the same field legitimately describe similar
work in similar words sometimes (e.g. "Implemented REST APIs using FastAPI"
is a completely normal, common sentence). A high similarity score is a
signal to LOOK CLOSER, not automatic proof of fraud — always shown with the
overlapping candidates named so a recruiter can judge in context.
"""

import re

DEFAULT_SHINGLE_SIZE = 6          # words per shingle — smaller catches more, noisier
DEFAULT_SIMILARITY_THRESHOLD = 0.35
MIN_FINGERPRINT_WORDS = 25        # skip near-empty fingerprints — comparing them is meaningless


def _normalize(text: str) -> list[str]:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return [w for w in text.split() if w]


def compute_shingles(text: str, k: int = DEFAULT_SHINGLE_SIZE) -> set[str]:
    words = _normalize(text)
    if len(words) < k:
        return set()
    return {" ".join(words[i:i + k]) for i in range(len(words) - k + 1)}


def jaccard_similarity(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


def extract_fingerprint_text(report_data: dict) -> str:
    """Pulls the prose most likely to reveal template reuse: verbatim
    experience bullets, project descriptions, and the AI-written summary
    (excluded — that's OUR text, not the candidate's) is NOT included."""
    parts: list[str] = []

    for exp in (report_data.get("experience") or []):
        parts.extend(exp.get("responsibilities") or [])

    for proj in (report_data.get("projects") or []):
        if proj.get("description"):
            parts.append(proj["description"])

    return " ".join(parts)


def find_duplicate_clusters(
    items: list[dict],
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    shingle_size: int = DEFAULT_SHINGLE_SIZE,
) -> list[dict]:
    """
    items: [{"id": report_id, "name": candidate_name, "text": fingerprint_text}, ...]

    Returns clusters: [{"similarity": float, "members": [{"id","name"}, ...]}, ...]
    Uses union-find style grouping so A~B and B~C become one 3-way cluster
    even if A~C alone is below threshold.
    """
    fingerprints = []
    for item in items:
        shingles = compute_shingles(item["text"], k=shingle_size)
        word_count = len(_normalize(item["text"]))
        if word_count < MIN_FINGERPRINT_WORDS:
            continue  # too little content to compare meaningfully
        fingerprints.append({**item, "shingles": shingles})

    n = len(fingerprints)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    pair_scores: dict[tuple[int, int], float] = {}
    for i in range(n):
        for j in range(i + 1, n):
            sim = jaccard_similarity(fingerprints[i]["shingles"], fingerprints[j]["shingles"])
            if sim >= threshold:
                pair_scores[(i, j)] = sim
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        root = find(i)
        groups.setdefault(root, []).append(i)

    clusters = []
    for indices in groups.values():
        if len(indices) < 2:
            continue
        relevant_scores = [s for (i, j), s in pair_scores.items() if i in indices and j in indices]
        clusters.append({
            "similarity": round(max(relevant_scores), 3) if relevant_scores else 0.0,
            "members": [
                {"id": fingerprints[i]["id"], "name": fingerprints[i].get("name") or "Unknown"}
                for i in indices
            ],
        })

    clusters.sort(key=lambda c: c["similarity"], reverse=True)
    return clusters
