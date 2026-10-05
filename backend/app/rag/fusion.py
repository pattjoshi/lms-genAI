"""Reciprocal Rank Fusion (RRF): merge several ranked lists into one.

The meaning search returns cosine similarities (0..1) and the keyword search returns BM25
scores (0..anything). The two scales can't be compared or added. RRF ignores the scores
and uses only the RANK in each list:

    rrf(chunk) = sum over lists of 1 / (k + rank_in_that_list)

A chunk ranked high in both lists wins; a chunk found by only one list still counts.
k (default 60, from the original RRF paper) dampens the gap between rank 1 and rank 2,
so one list can't dominate just because it was confident.
"""


def rrf(rankings: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    """`rankings` = lists of ids, best first. Returns (id, rrf score), best first."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    # Ties keep first-seen order (Python's sort is stable), i.e. the first list wins.
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
