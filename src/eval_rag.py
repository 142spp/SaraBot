"""RAG retrieval evaluation for archived Discord message chunks.

This script builds or reuses a local cache of synthetic search questions.
The cache stores only target chunk ids and generated questions, not chat content.

Usage:
    PYTHONPATH=src .venv/bin/python src/eval_rag.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from statistics import mean, median

from dotenv import load_dotenv
from openai import AsyncOpenAI

import config
from services.embedding_service import EmbeddingService
from storage.db import close_pool, get_pool


DEFAULT_CASES_PATH = Path(".rag_eval_cases.json")
STOPWORDS = {
    "이",
    "그",
    "저",
    "것",
    "거",
    "뭐",
    "무슨",
    "언제",
    "어디",
    "누가",
    "누구",
    "왜",
    "어떻게",
    "대해",
    "관련",
    "예전",
    "옛날",
    "했어",
    "한거",
    "얘기",
    "이야기",
    "대화",
    "말했던",
    "말한",
    "기억",
    "찾아줘",
    "알려줘",
    "궁금해",
}


def _embedding_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in vector) + "]"


def _scrub_for_prompt(text: str) -> str:
    return re.sub(r"https?://\S+", "[URL]", text)[:900]


def _extract_terms(query: str) -> list[str]:
    raw = re.findall(r"[0-9A-Za-z가-힣]{2,}", query)
    return [term for term in raw if term not in STOPWORDS][:8]


async def _make_query(client: AsyncOpenAI, content: str) -> str:
    prompt = (
        "아래 디스코드 대화 조각을 나중에 찾고 싶은 사용자가 할 법한 "
        "한국어 검색 질문을 하나만 만들어. 대화 문장을 그대로 베끼지 말고, "
        "고유명사/핵심 주제는 유지해. 답은 질문 한 줄만.\n\n"
        f"{_scrub_for_prompt(content)}"
    )
    response = await client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        timeout=30,
    )
    return (response.choices[0].message.content or "").strip().splitlines()[0][:200]


async def _load_or_create_cases(
    *,
    path: Path,
    samples: int,
    seed: str,
    min_chars: int,
    max_chars: int,
) -> list[dict]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))

    pool = await get_pool()
    client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
    cases: list[dict] = []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, content
            FROM message_chunks
            WHERE embedding IS NOT NULL
              AND length(content) BETWEEN $1 AND $2
            ORDER BY md5(id::text || $3)
            LIMIT $4
            """,
            min_chars,
            max_chars,
            seed,
            samples,
        )
        for row in rows:
            cases.append({
                "target_id": row["id"],
                "query": await _make_query(client, row["content"]),
            })

    path.write_text(
        json.dumps(cases, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return cases


async def _vector_ids(conn, embedding_literal: str, limit: int) -> list[int]:
    rows = await conn.fetch(
        """
        SELECT id
        FROM message_chunks
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> $1::vector ASC
        LIMIT $2
        """,
        embedding_literal,
        limit,
    )
    return [row["id"] for row in rows]


async def _keyword_chunk_ids(conn, query: str, limit: int) -> list[int]:
    terms = _extract_terms(query)
    if not terms:
        return []

    params: list = []
    clauses: list[str] = []
    score_parts: list[str] = []
    for term in terms:
        params.append(f"%{term}%")
        idx = len(params)
        clauses.append(f"content ILIKE ${idx}")
        score_parts.append(f"CASE WHEN content ILIKE ${idx} THEN 1 ELSE 0 END")

    params.append(limit)
    rows = await conn.fetch(
        f"""
        SELECT id
        FROM message_chunks
        WHERE {" OR ".join(clauses)}
        ORDER BY ({" + ".join(score_parts)}) DESC, end_at DESC
        LIMIT ${len(params)}
        """,
        *params,
    )
    return [row["id"] for row in rows]


def _rrf(rank: int, k: int = 60) -> float:
    return 1.0 / (k + rank)


def _hybrid_rrf_ids(vector_ids: list[int], keyword_ids: list[int]) -> list[int]:
    scores: dict[int, float] = {}
    for rank, item_id in enumerate(vector_ids, start=1):
        scores[item_id] = scores.get(item_id, 0.0) + _rrf(rank)
    for rank, item_id in enumerate(keyword_ids, start=1):
        scores[item_id] = scores.get(item_id, 0.0) + _rrf(rank)
    return [
        item_id
        for item_id, _ in sorted(
            scores.items(),
            key=lambda item: item[1],
            reverse=True,
        )
    ]


def _hit(ids: list[int], target_id: int, k: int) -> bool:
    return target_id in ids[:k]


async def _expanded_context_ids(conn, ids: list[int]) -> set[int]:
    if not ids:
        return set()
    rows = await conn.fetch(
        """
        WITH selected AS (
            SELECT id, channel_id, start_msg_id, end_msg_id
            FROM message_chunks
            WHERE id = ANY($1::bigint[])
        ),
        before_rows AS (
            SELECT s.id AS selected_id, c.id AS context_id
            FROM selected s
            JOIN LATERAL (
                SELECT id
                FROM message_chunks
                WHERE channel_id = s.channel_id
                  AND end_msg_id < s.start_msg_id
                ORDER BY end_msg_id DESC
                LIMIT 1
            ) c ON true
        ),
        after_rows AS (
            SELECT s.id AS selected_id, c.id AS context_id
            FROM selected s
            JOIN LATERAL (
                SELECT id
                FROM message_chunks
                WHERE channel_id = s.channel_id
                  AND start_msg_id > s.end_msg_id
                ORDER BY start_msg_id ASC
                LIMIT 1
            ) c ON true
        )
        SELECT id AS context_id FROM selected
        UNION
        SELECT context_id FROM before_rows
        UNION
        SELECT context_id FROM after_rows
        """,
        ids,
    )
    return {row["context_id"] for row in rows}


async def evaluate(cases: list[dict]) -> dict:
    pool = await get_pool()
    embedder = EmbeddingService()
    vectors = await embedder.embed([case["query"] for case in cases])

    metrics = {
        "vector@5": [],
        "vector@10": [],
        "vector@50": [],
        "keyword_chunk@50": [],
        "union_vector50_keyword50": [],
        "hybrid_rrf@5": [],
        "hybrid_rrf@10": [],
        "expanded_hybrid_rrf@5": [],
        "expanded_hybrid_rrf@10": [],
    }
    ranks = []

    async with pool.acquire() as conn:
        for case, vector in zip(cases, vectors):
            target_id = int(case["target_id"])
            literal = _embedding_literal(vector)
            vector_ids = await _vector_ids(conn, literal, 50)
            keyword_ids = await _keyword_chunk_ids(conn, case["query"], 50)
            union_ids = list(dict.fromkeys(vector_ids + keyword_ids))
            hybrid_ids = _hybrid_rrf_ids(vector_ids, keyword_ids)

            metrics["vector@5"].append(_hit(vector_ids, target_id, 5))
            metrics["vector@10"].append(_hit(vector_ids, target_id, 10))
            metrics["vector@50"].append(_hit(vector_ids, target_id, 50))
            metrics["keyword_chunk@50"].append(_hit(keyword_ids, target_id, 50))
            metrics["union_vector50_keyword50"].append(target_id in union_ids)
            metrics["hybrid_rrf@5"].append(_hit(hybrid_ids, target_id, 5))
            metrics["hybrid_rrf@10"].append(_hit(hybrid_ids, target_id, 10))
            expanded_5 = await _expanded_context_ids(conn, hybrid_ids[:5])
            expanded_10 = await _expanded_context_ids(conn, hybrid_ids[:10])
            metrics["expanded_hybrid_rrf@5"].append(target_id in expanded_5)
            metrics["expanded_hybrid_rrf@10"].append(target_id in expanded_10)
            ranks.append(
                vector_ids.index(target_id) + 1 if target_id in vector_ids else 999
            )

    return {
        "cases": len(cases),
        "median_vector_rank_capped_999": median(ranks),
        **{name: mean(values) for name, values in metrics.items()},
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--samples", type=int, default=100)
    parser.add_argument("--seed", default="sachikobot-rag-v1")
    parser.add_argument("--min-chars", type=int, default=180)
    parser.add_argument("--max-chars", type=int, default=900)
    args = parser.parse_args()

    load_dotenv(".env")
    cases = await _load_or_create_cases(
        path=args.cases,
        samples=args.samples,
        seed=args.seed,
        min_chars=args.min_chars,
        max_chars=args.max_chars,
    )
    result = await evaluate(cases)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
