import re
from datetime import datetime, timedelta, timezone

import discord

from services.embedding_service import EmbeddingService
from services.llm_service import LLMService
from storage.repositories import ChunkRepository, MessageRepository
from utils.logger import get_logger

logger = get_logger(__name__)

BATCH_SIZE = 500
CHUNK_GAP = timedelta(minutes=10)  # 이 간격 넘으면 새 대화 덩어리 (버스트 91%가 10분 내)
CHUNK_MAX_MESSAGES = 20  # 한 덩어리 최대 메시지 수 (버스트 p90=26, 대형만 분할)
MAX_MSG_CHARS = 1000  # 메시지 1개 임베딩 텍스트 상한 (긴 붙여넣기/봇 출력 대비)
MAX_CHUNK_CHARS = 4000  # 청크 합본 상한 (임베딩 8192토큰 한도 안전선)
SEARCH_STOPWORDS = {
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


def extract_search_terms(query: str, limit: int = 8) -> list[str]:
    raw = re.findall(r"[0-9A-Za-z가-힣]{2,}", query)
    return [term for term in raw if term not in SEARCH_STOPWORDS][:limit]


def _rrf(rank: int, k: int = 60) -> float:
    return 1.0 / (k + rank)


class MessageArchiveService:
    def __init__(
        self,
        client: discord.Client,
        embedding_service: EmbeddingService,
        llm_service: LLMService | None = None,
    ) -> None:
        self._client = client
        self._repo = MessageRepository()
        self._chunks = ChunkRepository()
        self._embedding = embedding_service
        self._llm = llm_service

    @staticmethod
    def _progress_embed(
        saved: int,
        *,
        done: bool,
        total: int | None = None,
        incremental: bool = False,
    ) -> discord.Embed:
        if done:
            embed = discord.Embed(color=discord.Color.green())
            embed.set_author(name="✅ 채널 기록 저장 완료")
            mode = "추가분" if incremental else "전체"
            embed.description = (
                f"이번에 **{saved:,}개** 저장 ({mode})\n"
                f"채널 누적 **{total:,}개**"
            )
        else:
            embed = discord.Embed(color=discord.Color.blurple())
            embed.set_author(name="📥 채널 기록 저장 중...")
            embed.description = f"**{saved:,}개** 저장됨"
        return embed

    @staticmethod
    def _clip_embed_text(text: str, max_chars: int = 240, max_lines: int = 4) -> str:
        text = re.sub(r"\n{3,}", "\n\n", (text or "").strip())
        lines = [line for line in text.splitlines() if line.strip()]
        if len(lines) > max_lines:
            text = "\n".join(lines[:max_lines]).rstrip() + "\n…"
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 1].rstrip() + "…"

    @staticmethod
    def _evidence_preview(item: dict, terms: list[str]) -> str:
        text = (item.get("content") or item.get("context_content") or "").strip()
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines or not terms:
            return text

        picked: list[str] = []
        lowered_terms = [term.lower() for term in terms]
        for line in lines:
            lowered = line.lower()
            if any(term in lowered for term in lowered_terms):
                picked.append(line)
            if len(picked) >= 4:
                break
        return "\n".join(picked) if picked else text

    @staticmethod
    def _search_evidence_payload(
        item: dict, index: int, terms: list[str] | None = None
    ) -> dict:
        source_url = item.get("source_url")
        title = f"검색 근거 {index}"
        if item.get("start_at"):
            title += f" · {item['start_at'][:10]}"
        elif item.get("created_at"):
            title += f" · {item['created_at'][:10]}"

        raw_text = MessageArchiveService._evidence_preview(item, terms or [])
        payload = {
            "title": title,
            "url": source_url,
            "description": MessageArchiveService._clip_embed_text(raw_text),
            "fields": [],
        }
        authors = item.get("authors") or item.get("author")
        if authors:
            payload["fields"].append(
                {"name": "작성자", "value": str(authors)[:1024], "inline": False}
            )
        if source_url:
            payload["fields"].append(
                {"name": "원문", "value": f"[메시지로 이동]({source_url})", "inline": False}
            )
        if item.get("retrieval_sources"):
            payload["footer"] = f"검색 방식: {', '.join(item['retrieval_sources'])}"
        return payload

    def build_search_evidence_embeds(
        self,
        keyword_matches: list[dict],
        hybrid_matches: list[dict],
        query: str = "",
        limit: int = 3,
    ) -> list[dict]:
        """검색 상위 근거를 최종 응답에 붙일 embed payload로 만든다."""
        selected: list[dict] = []
        seen_urls: set[str] = set()
        for item in hybrid_matches + keyword_matches:
            url = item.get("source_url")
            if not url or url in seen_urls:
                continue
            selected.append(item)
            seen_urls.add(url)
            if len(selected) >= limit:
                break

        terms = extract_search_terms(query)
        return [
            self._search_evidence_payload(item, index, terms)
            for index, item in enumerate(selected, start=1)
        ]

    async def ingest_channel(self, channel_id: int, notify: bool = True) -> dict:
        """현재 채널의 전체 기록을 DB에 적재한다. 이미 저장분이 있으면 그 이후만(증분).

        notify=True면 시작부터 진행률 embed를 띄운다.
        notify=False(검색용 조용한 갱신)면 평소엔 무음이고,
        대규모 백필(첫 배치 초과)일 때만 embed를 lazy하게 띄운다.
        """
        channel = self._client.get_channel(channel_id)
        if not channel or not hasattr(channel, "history"):
            return {"ok": False, "error": "CHANNEL_NOT_ACCESSIBLE"}

        guild_id = channel.guild.id
        last_id = await self._repo.latest_message_id(channel_id)
        after = discord.Object(id=last_id) if last_id else None
        incremental = last_id is not None

        logger.info(
            f"Ingest start | channel={channel_id} "
            f"mode={'incremental' if incremental else 'full'} notify={notify}"
        )

        progress_msg = None
        if notify:
            progress_msg = await channel.send(embed=self._progress_embed(0, done=False))

        batch: list[tuple] = []
        saved = 0
        async for msg in channel.history(limit=None, after=after, oldest_first=True):
            batch.append((
                msg.id,
                channel_id,
                guild_id,
                msg.author.id,
                msg.author.display_name,
                msg.content,
                msg.author.bot,
                msg.created_at,
            ))
            if len(batch) >= BATCH_SIZE:
                await self._repo.bulk_upsert(batch)
                saved += len(batch)
                logger.info(f"Ingest progress | channel={channel_id} saved={saved}")
                if progress_msg is None:
                    # 조용한 갱신인데 백필이 커지면 그때부터 진행률 표시
                    progress_msg = await channel.send(
                        embed=self._progress_embed(saved, done=False)
                    )
                else:
                    await progress_msg.edit(
                        embed=self._progress_embed(saved, done=False)
                    )
                batch = []

        if batch:
            await self._repo.bulk_upsert(batch)
            saved += len(batch)

        # 적재된 새 메시지를 대화 덩어리로 묶어 임베딩 (a안: 적재 시 같이)
        chunked = await self._build_chunks(channel_id, guild_id)

        total = await self._repo.count_by_channel(channel_id)
        logger.info(
            f"Ingest done | channel={channel_id} +{saved} "
            f"(total={total}, chunks+{chunked})"
        )
        if progress_msg is not None:
            await progress_msg.edit(
                embed=self._progress_embed(
                    saved, done=True, total=total, incremental=incremental
                )
            )
        return {
            "ok": True,
            "saved": saved,
            "total": total,
            "incremental": incremental,
        }

    async def search(
        self,
        guild_id: int,
        query: str = "",
        author: str | None = None,
        limit: int = 20,
        before_message_id: int | None = None,
        exclude_mention_user_id: int | None = None,
    ) -> list[dict]:
        terms = extract_search_terms(query)
        if not terms and not author:
            return []
        return await self._repo.search(
            guild_id,
            terms,
            author,
            limit,
            before_message_id=before_message_id,
            exclude_mention_user_id=exclude_mention_user_id,
        )

    async def keyword_chunk_search(
        self,
        guild_id: int,
        query: str = "",
        author: str | None = None,
        limit: int = 20,
        channel_id: int | None = None,
        before_message_id: int | None = None,
        exclude_mention_user_id: int | None = None,
    ) -> list[dict]:
        terms = extract_search_terms(query)
        if not terms and not author:
            return []
        return await self._chunks.keyword_search(
            guild_id,
            terms,
            limit=limit,
            author=author,
            channel_id=channel_id,
            before_message_id=before_message_id,
            exclude_mention_user_id=exclude_mention_user_id,
        )

    @staticmethod
    def _merge_hybrid(
        semantic_matches: list[dict],
        keyword_matches: list[dict],
    ) -> list[dict]:
        merged: dict[int, dict] = {}

        def add(item: dict, source: str, rank: int) -> None:
            item_id = item["id"]
            if item_id not in merged:
                merged[item_id] = {
                    **item,
                    "hybrid_score": 0.0,
                    "retrieval_sources": [],
                }
            existing = merged[item_id]
            existing["hybrid_score"] += _rrf(rank)
            existing["retrieval_sources"].append(source)
            if "distance" in item:
                existing["distance"] = item["distance"]
            if "keyword_score" in item:
                existing["keyword_score"] = item["keyword_score"]

        for rank, item in enumerate(semantic_matches, start=1):
            add(item, "semantic", rank)
        for rank, item in enumerate(keyword_matches, start=1):
            add(item, "keyword", rank)

        return sorted(
            merged.values(),
            key=lambda item: (
                item["hybrid_score"],
                item.get("keyword_score", 0),
                -item.get("distance", 9_999),
            ),
            reverse=True,
        )

    async def hybrid_search(
        self,
        guild_id: int,
        query: str,
        limit: int = 10,
        *,
        candidate_limit: int = 50,
        rerank_limit: int = 10,
        expand_context: bool = True,
        context_before: int = 1,
        context_after: int = 1,
        author: str | None = None,
        channel_id: int | None = None,
        before_message_id: int | None = None,
        exclude_mention_user_id: int | None = None,
    ) -> list[dict]:
        semantic_matches = await self.semantic_search(
            guild_id,
            query,
            limit=candidate_limit,
            candidate_limit=candidate_limit,
            author=author,
            channel_id=channel_id,
            before_message_id=before_message_id,
            exclude_mention_user_id=exclude_mention_user_id,
        )
        keyword_matches = await self.keyword_chunk_search(
            guild_id,
            query,
            author=author,
            limit=candidate_limit,
            channel_id=channel_id,
            before_message_id=before_message_id,
            exclude_mention_user_id=exclude_mention_user_id,
        )
        ranked = self._merge_hybrid(semantic_matches, keyword_matches)
        if self._llm and query.strip() and len(ranked) > 1 and rerank_limit > 1:
            reranked = await self._rerank_with_llm(query, ranked[:rerank_limit])
            ranked = reranked + ranked[rerank_limit:]
        ranked = ranked[:limit]
        if expand_context:
            ranked = await self._chunks.expand_context(
                guild_id,
                ranked,
                before=context_before,
                after=context_after,
            )
        return ranked

    async def _rerank_with_llm(self, query: str, candidates: list[dict]) -> list[dict]:
        blocks = []
        for idx, item in enumerate(candidates, start=1):
            blocks.append(f"[{idx}]\n{item['content'][:700]}")
        prompt = (
            "검색 질문과 후보 대화 조각들이 있어. "
            "질문에 답하는 데 가장 관련 높은 후보 번호를 최대 5개 골라 "
            "관련도 높은 순서대로 숫자만 쉼표로 답해.\n\n"
            f"질문: {query}\n\n"
            + "\n\n".join(blocks)
        )
        try:
            answer = await self._llm.judge(prompt)
        except Exception as e:
            logger.warning(f"hybrid rerank failed: {e}")
            return candidates

        ordered: list[dict] = []
        used: set[int] = set()
        for raw in re.findall(r"\d+", answer):
            idx = int(raw) - 1
            if 0 <= idx < len(candidates) and idx not in used:
                ordered.append(candidates[idx])
                used.add(idx)
        for idx, item in enumerate(candidates):
            if idx not in used:
                ordered.append(item)
        return ordered

    async def sample_user_messages(
        self, guild_id: int, author: str, recent: int = 50, even: int = 250
    ) -> list[dict]:
        return await self._repo.sample_by_author(guild_id, author, recent, even)

    async def _build_chunks(self, channel_id: int, guild_id: int) -> int:
        """아직 청크로 안 묶인 메시지들을 시간간격·개수 기준으로 묶어 임베딩·저장."""
        last = await self._chunks.latest_chunked_msg_id(channel_id)
        msgs = await self._repo.messages_after(channel_id, last)
        if not msgs:
            return 0

        # 시간 간격 / 최대 개수로 그룹핑
        groups: list[list] = []
        cur: list = []
        for m in msgs:
            if not cur:
                cur = [m]
                continue
            gap = m["created_at"] - cur[-1]["created_at"]
            if gap > CHUNK_GAP or len(cur) >= CHUNK_MAX_MESSAGES:
                groups.append(cur)
                cur = [m]
            else:
                cur.append(m)
        if cur:
            groups.append(cur)

        # 각 그룹을 합본 텍스트로 만들고 빈 청크는 스킵
        texts: list[str] = []
        metas: list[dict] = []
        for g in groups:
            lines: list[str] = []
            authors: list[str] = []
            for m in g:
                content = (m["content"] or "").strip()
                if not content:
                    continue
                content = content[:MAX_MSG_CHARS]  # 메시지 단위 상한
                lines.append(f'{m["author_name"]}: {content}')
                if m["author_name"] not in authors:
                    authors.append(m["author_name"])
            text = "\n".join(lines)[:MAX_CHUNK_CHARS]  # 청크 합본 상한
            if not text:
                continue
            texts.append(text)
            metas.append({
                "start_msg_id": g[0]["message_id"],
                "end_msg_id": g[-1]["message_id"],
                "start_at": g[0]["created_at"],
                "end_at": g[-1]["created_at"],
                "authors": ", ".join(authors),
            })

        if not texts:
            return 0

        embeddings = await self._embedding.embed(texts)
        rows = [
            (
                channel_id,
                guild_id,
                meta["start_msg_id"],
                meta["end_msg_id"],
                meta["start_at"],
                meta["end_at"],
                meta["authors"],
                text,
                EmbeddingService.to_pgvector(emb),
            )
            for meta, text, emb in zip(metas, texts, embeddings)
        ]
        await self._chunks.insert_chunks(rows)
        logger.info(f"Chunks built | channel={channel_id} +{len(rows)}")
        return len(rows)

    async def _pick_funniest(self, candidates: list[dict]) -> dict:
        """웃음 점수 상위 후보들 중 LLM이 가장 재밌는 하나를 고른다.
        LLM 미주입·실패 시 점수 1위(목록 첫 번째)로 폴백."""
        if len(candidates) == 1 or not self._llm:
            return candidates[0]

        blocks = []
        for i, c in enumerate(candidates, 1):
            blocks.append(f"[{i}]\n{c['content'][:700]}")
        prompt = (
            "아래는 친구들 디스코드의 과거 같은 날짜 대화 후보들이야. "
            "이 중 지금 다시 보면 가장 웃기고 재밌을 대화 하나를 골라줘. "
            "맥락 없는 ㅋㅋ 도배보다, 읽으면 상황이 그려지고 빵 터지는 걸 우선해. "
            "다른 말 없이 번호 숫자 하나만 답해.\n\n" + "\n\n".join(blocks)
        )
        try:
            answer = await self._llm.judge(prompt)
            m = re.search(r"\d+", answer)
            if m:
                idx = int(m.group()) - 1
                if 0 <= idx < len(candidates):
                    logger.info(f"recall_this_day | LLM picked #{idx + 1}")
                    return candidates[idx]
        except Exception as e:
            logger.warning(f"recall_this_day pick failed: {e}")
        return candidates[0]

    async def recall_this_day(self, guild_id: int, channel_id: int) -> dict:
        """오늘 날짜의 과거 대화를 서버 전체에서 꺼내 'N년 전 오늘' embed로 채널에 전송."""
        candidates = await self._chunks.recall_this_day(guild_id)
        if not candidates:
            return {"found": False}
        chunk = await self._pick_funniest(candidates)

        kst = timezone(timedelta(hours=9))
        start = chunk["start_at"].astimezone(kst)
        now_kst = datetime.now(kst)
        years_ago = now_kst.year - start.year
        date_label = start.strftime("%Y년 %m월 %d일")

        channel = self._client.get_channel(channel_id)
        if channel and hasattr(channel, "send"):
            embed = discord.Embed(
                title=f"📅 {years_ago}년 전 오늘 ({date_label})",
                description=chunk["content"][:4000],
                color=discord.Color.gold(),
            )
            embed.set_footer(text=f"참여: {chunk['authors']}")
            await channel.send(embed=embed)

        return {
            "found": True,
            "years_ago": years_ago,
            "date": date_label,
            "authors": chunk["authors"],
        }

    async def semantic_search(
        self,
        guild_id: int,
        query: str,
        limit: int = 5,
        *,
        candidate_limit: int = 50,
        author: str | None = None,
        channel_id: int | None = None,
        before_message_id: int | None = None,
        exclude_mention_user_id: int | None = None,
    ) -> list[dict]:
        """쿼리를 임베딩해 의미적으로 가까운 대화 청크를 반환 (서버 전체)."""
        if not query.strip():
            return []
        embeddings = await self._embedding.embed([query])
        if not embeddings:
            return []
        literal = EmbeddingService.to_pgvector(embeddings[0])
        candidates = await self._chunks.vector_search(
            guild_id,
            literal,
            limit=max(limit, candidate_limit),
            author=author,
            channel_id=channel_id,
            before_message_id=before_message_id,
            exclude_mention_user_id=exclude_mention_user_id,
        )
        return candidates[:limit]
