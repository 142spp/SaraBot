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
MAX_TRACK_DURATION = 600  # 10분 초과는 플레이리스트/영상으로 간주해 제외


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
                for entry in entries:
                    if not entry:
                        continue
                    duration = entry.get("duration") or 0
                    if duration > MAX_TRACK_DURATION:
                        continue
                    results.append(Track(
                        title=entry.get("title", "Unknown"),
                        url=entry.get("url", ""),
                        webpage_url=entry.get("webpage_url", ""),
                        duration=duration,
                        thumbnail=entry.get("thumbnail"),
                    ))
                    if len(results) >= limit:
                        break
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

    @staticmethod
    def _fmt_duration(seconds: int) -> str:
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    async def _notify(self, guild_id: int, embed: discord.Embed) -> None:
        state = self.get_state(guild_id)
        if not state.text_channel_id:
            return
        channel = self._client.get_channel(state.text_channel_id)
        if channel and hasattr(channel, "send"):
            await channel.send(embed=embed)

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
            pos = len(state.queue)
            logger.info(f"Queued: {track.title} (queue size={pos})")
            embed = discord.Embed(
                description=f"**{track.title}**",
                color=discord.Color.blurple(),
            )
            embed.set_author(name=f"대기열 {pos}번에 추가됨")
            embed.add_field(name="길이", value=self._fmt_duration(track.duration))
            if track.thumbnail:
                embed.set_thumbnail(url=track.thumbnail)
            await self._notify(guild_id, embed)
            return track, False

    async def _get_stream_url(self, webpage_url: str) -> str | None:
        loop = asyncio.get_event_loop()

        def _extract():
            with yt_dlp.YoutubeDL(YTDLP_OPTIONS) as ydl:
                info = ydl.extract_info(webpage_url, download=False)
                if not info:
                    return None
                entry = info.get("entries", [info])[0] if "entries" in info else info
                return entry.get("url") if entry else None

        return await loop.run_in_executor(None, _extract)

    async def _play(
        self, guild_id: int, track: Track, vc: discord.VoiceClient
    ) -> None:
        state = self.get_state(guild_id)
        state.current_track = track
        state.is_playing = True

        stream_url = await self._get_stream_url(track.webpage_url)
        if not stream_url:
            logger.error(f"Failed to get stream URL for: {track.title}")
            await self._on_track_end(guild_id)
            return

        source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS)
        source = discord.PCMVolumeTransformer(source, volume=state.volume)

        def after(error):
            if error:
                logger.error(f"Player error: {error}")
            asyncio.run_coroutine_threadsafe(
                self._on_track_end(guild_id), self._client.loop
            )

        vc.play(source, after=after)
        logger.info(f"Playing: {track.title} (guild={guild_id})")
        embed = discord.Embed(
            description=f"**{track.title}**",
            color=discord.Color.green(),
        )
        embed.set_author(name="🎵 지금 재생 중")
        embed.add_field(name="길이", value=self._fmt_duration(track.duration))
        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)
        await self._notify(guild_id, embed)

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

    async def send_queue_embed(self, guild_id: int, channel_id: int) -> None:
        state = self.get_state(guild_id)
        channel = self._client.get_channel(channel_id)
        if not channel or not hasattr(channel, "send"):
            return

        embed = discord.Embed(color=discord.Color.og_blurple())
        embed.set_author(name="🎵 재생 목록")

        if state.current_track:
            embed.add_field(
                name="▶ 지금 재생 중",
                value=f"**{state.current_track.title}**  `{self._fmt_duration(state.current_track.duration)}`",
                inline=False,
            )
            if state.current_track.thumbnail:
                embed.set_thumbnail(url=state.current_track.thumbnail)
        else:
            embed.description = "재생 중인 곡이 없어."

        if state.queue:
            lines = []
            for i, t in enumerate(state.queue, 1):
                lines.append(f"`{i}.` **{t.title}**  `{self._fmt_duration(t.duration)}`")
            embed.add_field(name="대기열", value="\n".join(lines), inline=False)

        total = len(state.queue) + (1 if state.current_track else 0)
        embed.set_footer(text=f"총 {total}곡")
        await channel.send(embed=embed)

    def _get_voice_client(self, guild_id: int) -> discord.VoiceClient | None:
        guild = self._client.get_guild(guild_id)
        return guild.voice_client if guild else None  # type: ignore[return-value]
