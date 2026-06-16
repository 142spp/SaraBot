import asyncio
from dataclasses import dataclass, field

import discord
import yt_dlp

from utils.logger import get_logger

logger = get_logger(__name__)

YTDLP_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

MAX_QUEUE_SIZE = 50


@dataclass
class Track:
    title: str
    url: str
    webpage_url: str
    duration: int  # seconds
    thumbnail: str | None = None


@dataclass
class GuildMusicState:
    guild_id: int
    voice_channel_id: int | None = None
    text_channel_id: int | None = None
    current_track: Track | None = None
    queue: list[Track] = field(default_factory=list)
    is_playing: bool = False
    volume: float = 0.5


class MusicService:
    def __init__(self, client: discord.Client) -> None:
        self._client = client
        self._states: dict[int, GuildMusicState] = {}
        # search_music 결과를 webpage_url 기준으로 캐싱 — play_music 재호출 방지
        self._track_cache: dict[str, Track] = {}

    def get_state(self, guild_id: int) -> GuildMusicState:
        if guild_id not in self._states:
            self._states[guild_id] = GuildMusicState(guild_id=guild_id)
        return self._states[guild_id]

    async def search(self, query: str, limit: int = 5) -> list[Track]:
        options = {**YTDLP_OPTIONS, "noplaylist": True}
        search_query = query if query.startswith("http") else f"ytsearch{limit}:{query}"

        loop = asyncio.get_event_loop()

        def _extract():
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(search_query, download=False)
                if not info:
                    return []
                entries = info.get("entries", [info])
                results = []
                for entry in entries[:limit]:
                    if not entry:
                        continue
                    results.append(Track(
                        title=entry.get("title", "Unknown"),
                        url=entry.get("url", ""),
                        webpage_url=entry.get("webpage_url", ""),
                        duration=entry.get("duration", 0),
                        thumbnail=entry.get("thumbnail"),
                    ))
                return results

        tracks = await loop.run_in_executor(None, _extract)
        for track in tracks:
            if track.webpage_url:
                self._track_cache[track.webpage_url] = track
        logger.debug(f"Search '{query}' → {len(tracks)} results (cached {len(tracks)})")
        return tracks

    async def _fetch_track(self, query: str) -> Track | None:
        if query in self._track_cache:
            logger.debug(f"Track cache hit: {query}")
            return self._track_cache[query]

        loop = asyncio.get_event_loop()

        def _extract():
            with yt_dlp.YoutubeDL(YTDLP_OPTIONS) as ydl:
                search = query if query.startswith("http") else f"ytsearch1:{query}"
                info = ydl.extract_info(search, download=False)
                if not info:
                    return None
                entry = info.get("entries", [info])[0] if "entries" in info else info
                if not entry:
                    return None
                return Track(
                    title=entry.get("title", "Unknown"),
                    url=entry.get("url", ""),
                    webpage_url=entry.get("webpage_url", ""),
                    duration=entry.get("duration", 0),
                    thumbnail=entry.get("thumbnail"),
                )

        return await loop.run_in_executor(None, _extract)

    async def enqueue(
        self, guild_id: int, query: str, text_channel_id: int
    ) -> tuple[Track | None, bool]:
        """트랙을 큐에 추가한다. (track, is_now_playing) 반환"""
        state = self.get_state(guild_id)

        if len(state.queue) >= MAX_QUEUE_SIZE:
            return None, False

        track = await self._fetch_track(query)
        if not track:
            return None, False

        state.text_channel_id = text_channel_id

        vc = self._get_voice_client(guild_id)
        if vc and not state.is_playing:
            await self._play(guild_id, track, vc)
            return track, True
        else:
            state.queue.append(track)
            logger.info(f"Queued: {track.title} (queue size={len(state.queue)})")
            return track, False

    async def _play(
        self, guild_id: int, track: Track, vc: discord.VoiceClient
    ) -> None:
        state = self.get_state(guild_id)
        state.current_track = track
        state.is_playing = True

        source = discord.FFmpegPCMAudio(track.url, **FFMPEG_OPTIONS)
        source = discord.PCMVolumeTransformer(source, volume=state.volume)

        def after(error):
            if error:
                logger.error(f"Player error: {error}")
            asyncio.run_coroutine_threadsafe(
                self._on_track_end(guild_id), self._client.loop
            )

        vc.play(source, after=after)
        logger.info(f"Playing: {track.title} (guild={guild_id})")

    async def _on_track_end(self, guild_id: int) -> None:
        state = self.get_state(guild_id)
        state.current_track = None
        state.is_playing = False

        if state.queue:
            next_track = state.queue.pop(0)
            vc = self._get_voice_client(guild_id)
            if vc:
                await self._play(guild_id, next_track, vc)

    async def skip(self, guild_id: int) -> Track | None:
        vc = self._get_voice_client(guild_id)
        state = self.get_state(guild_id)
        if not vc or not state.is_playing:
            return None
        skipped = state.current_track
        vc.stop()  # after() callback이 다음 곡 재생
        return skipped

    def get_queue_info(self, guild_id: int) -> dict:
        state = self.get_state(guild_id)
        return {
            "is_playing": state.is_playing,
            "current_track": (
                {"title": state.current_track.title, "duration": state.current_track.duration}
                if state.current_track else None
            ),
            "queue": [
                {"title": t.title, "duration": t.duration} for t in state.queue
            ],
            "queue_length": len(state.queue),
        }

    def _get_voice_client(self, guild_id: int) -> discord.VoiceClient | None:
        guild = self._client.get_guild(guild_id)
        return guild.voice_client if guild else None  # type: ignore[return-value]
