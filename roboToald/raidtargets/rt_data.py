from __future__ import annotations

import collections
import datetime
import enum
import json
import logging
import time
from urllib.parse import urlparse

import httpx

from roboToald import config

logger = logging.getLogger(__name__)

DEFAULT_SOON_THRESHOLD = 48 * 60 * 60

RAIDTARGETS_CACHE_SECONDS = 60
SLOW_RAIDTARGETS_WARN_SEC = 3.0
_CONNECT_TIMEOUT = 10.0
_READ_TIMEOUT = 30.0

_httpx_client: httpx.AsyncClient | None = None


def _raidtargets_http_client() -> httpx.AsyncClient:
    global _httpx_client
    if _httpx_client is None:
        _httpx_client = httpx.AsyncClient(
            timeout=httpx.Timeout(_READ_TIMEOUT, connect=_CONNECT_TIMEOUT),
        )
    return _httpx_client


class RaidWindowStatus(enum.Enum):
    NOW = 1
    SOON = 2
    LATER = 3
    PAST = 4

    def __eq__(self, other: RaidWindowStatus) -> bool:
        return self.value == other.value

    def __lt__(self, other: RaidWindowStatus) -> bool:
        return self.value < other.value

    def __le__(self, other) -> bool:
        return self < other or self == other

    def __gt__(self, other: RaidWindowStatus) -> bool:
        return self.value > other.value

    def __ge__(self, other) -> bool:
        return self > other or self == other


class RaidWindow:
    start: int = None
    end: int = None
    extrapolation_count: int = None
    _target: RaidTarget = None

    def __init__(self, start, end, extrapolationCount):
        self.start = int(start)
        self.end = int(end)
        self.extrapolation_count = extrapolationCount

    @property
    def target(self) -> RaidTarget:
        return self._target

    @target.setter
    def target(self, target: RaidTarget):
        self._target = target

    @property
    def duration(self) -> datetime.timedelta:
        return datetime.timedelta(seconds=self.end - self.start)

    def get_time_until(self, now: float = None) -> datetime.timedelta:
        if not now:
            now = time.time()
        return datetime.timedelta(seconds=self.start - now)

    def get_percent_elapsed(self, now: float = None) -> float:
        if not now:
            now = time.time()
        passed_time = datetime.timedelta(seconds=now - self.start)
        return passed_time.total_seconds() / self.duration.total_seconds()

    def get_status(self, now: float = None, soon_threshold: int = None) -> RaidWindowStatus:
        if not now:
            now = time.time()
        if soon_threshold is None:
            soon_threshold = DEFAULT_SOON_THRESHOLD
        if now > self.end:
            return RaidWindowStatus.PAST
        elif self.start < now < self.end:
            return RaidWindowStatus.NOW
        elif self.start < now + soon_threshold:
            return RaidWindowStatus.SOON
        return RaidWindowStatus.LATER

    def get_next(self) -> RaidWindow:
        for window in self._target.windows:
            if window.extrapolation_count == (self.extrapolation_count + 1):
                window.target = self.target
                return window

    @classmethod
    def from_json(cls, **kwargs) -> RaidWindow:
        return cls(**kwargs)


class RaidTargets:
    _cache: dict[int, dict] = {}

    @classmethod
    async def ensure_loaded(cls, guild_id: int) -> None:
        cached = cls._cache.get(guild_id)
        if cached and cached["time"] > (time.time() - RAIDTARGETS_CACHE_SECONDS):
            return

        endpoint = config.get_raidtargets_endpoint(guild_id)
        if not endpoint:
            cls._cache[guild_id] = {"time": time.time(), "targets": [], "names": []}
            return

        headers = {}
        authkey = config.get_raidtargets_authkey(guild_id)
        if authkey:
            headers["AuthorizationKey"] = authkey

        safe_host = urlparse(endpoint).netloc or endpoint
        client = _raidtargets_http_client()
        t0 = time.perf_counter()
        try:
            r = await client.get(endpoint, headers=headers)
            data = json.loads(r.text, cls=JSONDecoder)
        except Exception as e:
            logger.error(
                "Raid targets fetch failed for guild=%s host=%s: %s",
                guild_id,
                safe_host,
                e,
            )
            cls._cache[guild_id] = {"time": time.time(), "targets": [], "names": []}
            return

        elapsed = time.perf_counter() - t0
        if elapsed > SLOW_RAIDTARGETS_WARN_SEC:
            logger.warning(
                "Slow raid targets endpoint guild=%s host=%s elapsed=%.2fs",
                guild_id,
                safe_host,
                elapsed,
            )

        targets = data if isinstance(data, list) else []
        cls._cache[guild_id] = {
            "time": time.time(),
            "targets": targets,
            "names": [t.name for t in targets],
        }

    @classmethod
    async def get_targets(cls, guild_id: int) -> list[RaidTarget]:
        await cls.ensure_loaded(guild_id)
        return cls._cache.get(guild_id, {}).get("targets", [])

    @classmethod
    async def get_all_names(cls, guild_id: int) -> list[str]:
        await cls.ensure_loaded(guild_id)
        return cls._cache.get(guild_id, {}).get("names", [])

    @classmethod
    async def get_by_name(cls, name: str, guild_id: int) -> RaidTarget | None:
        await cls.ensure_loaded(guild_id)
        for target in cls._cache.get(guild_id, {}).get("targets", []):
            if target.name_matches(name):
                return target
        return None


class RaidTarget:
    name: str = None
    short_name: str = None
    aliases: list[str] = None
    era: str = None
    zone: str = None
    windows: list[RaidWindow] = None

    def __init__(self, name, shortName, aliases, era, zone, windows):
        self.name = name
        self.short_name = shortName
        self.aliases = aliases.split(",")
        self.era = era
        self.zone = zone
        self.windows = windows

    def name_matches(self, name: str) -> bool:
        if self.name.lower() == name.lower():
            return True
        if name.lower() in map(str.lower, self.aliases):
            return True
        return False

    def get_time_until(self, now: float = None, soon_threshold: int = None) -> datetime.timedelta:
        return self.get_active_window(now, soon_threshold=soon_threshold).get_time_until(now)

    def get_active_window(self, now: float = None, soon_threshold: int = None) -> RaidWindow:
        if not now:
            now = time.time()
        sorted_windows = collections.OrderedDict()
        for window in self.windows:
            sorted_windows[window.get_time_until(now)] = window

        for window in sorted_windows.values():
            if window.get_status(soon_threshold=soon_threshold) < RaidWindowStatus.PAST:
                window.target = self
                return window

    def get_active_window_status(self, now: float = None, soon_threshold: int = None) -> RaidWindowStatus:
        if not now:
            now = time.time()
        return self.get_active_window(now, soon_threshold=soon_threshold).get_status(soon_threshold=soon_threshold)

    def get_next_window(self, current: RaidWindow) -> RaidWindow:
        for window in self.windows:
            if window.extrapolation_count == (current.extrapolation_count + 1):
                window.target = self
                return window

    @classmethod
    def from_json(cls, **kwargs) -> RaidTarget:
        return cls(**kwargs)


# Mutated from https://github.com/AlexisGomes/JsonEncoder/
class JSONDecoder(json.JSONDecoder):
    def __init__(self, *args, **kwargs):
        json.JSONDecoder.__init__(self, object_hook=self.object_hook, *args, **kwargs)

    def object_hook(self, obj):  # pylint: disable=method-hidden
        if isinstance(obj, dict):
            if "raidTargets" in obj:
                return obj["raidTargets"]
            try:
                return RaidTarget.from_json(**obj)
            except TypeError:
                return RaidWindow.from_json(**obj)

        # handling the resolution of nested objects
        if isinstance(obj, dict):
            for key in list(obj):
                obj[key] = self.object_hook(obj[key])

        return obj
