from __future__ import annotations
import collections
import datetime
import enum
import json
import time

import requests

from roboToald import config


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

    def __init__(self, start, end, extrapolationCount):
        self.start = int(start)
        self.end = int(end)
        self.extrapolation_count = extrapolationCount

    @property
    def duration(self) -> datetime.timedelta:
        return datetime.timedelta(seconds=self.end - self.start)

    def get_time_until(self, now: int = None) -> datetime.timedelta:
        if not now:
            now = time.time()
        return datetime.timedelta(seconds=self.start - now)

    def get_percent_elapsed(self, now: int = None) -> float:
        if not now:
            now = time.time()
        passed_time = datetime.timedelta(seconds=now - self.start)
        return passed_time.total_seconds() / self.duration.total_seconds()

    def get_status(self, now: int = None) -> RaidWindowStatus:
        if not now:
            now = time.time()
        if now > self.end:
            return RaidWindowStatus.PAST
        elif self.start < now < self.end:
            return RaidWindowStatus.NOW
        elif self.start < now + config.SOON_THRESHOLD:
            return RaidWindowStatus.SOON
        return RaidWindowStatus.LATER

    @classmethod
    def from_json(cls, **kwargs) -> RaidWindow:
        return cls(**kwargs)


class RaidTargets:
    _time: int = 0
    _targets: list[RaidTarget] = []
    _names: list[str] = []

    def __init__(self, raidTargets: list):
        RaidTargets._time = time.time()
        RaidTargets._targets = raidTargets

    @classmethod
    def get_targets(cls):
        cls.load()
        return cls._targets

    @classmethod
    def get_all_names(cls) -> list[str]:
        cls.load()
        return cls._names

    @classmethod
    def get_by_name(cls, name: str) -> RaidTarget:
        cls.load()
        for target in cls._targets:
            if target.name_matches(name):
                return target

    @classmethod
    def from_json(cls, **kwargs) -> RaidTargets:
        return cls(**kwargs)

    @classmethod
    def load(cls) -> None:
        if cls._time < (time.time() - 60):
            r = requests.get(config.RT_ENDPOINT)
            r.json(cls=JSONDecoder)  # implicitly loads the class data
            cls._names = [t.name for t in cls._targets]
        else:
            # print(f'Using cached rt_data from: {cls._time}')
            pass


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
        self.aliases = aliases.split(',')
        self.era = era
        self.zone = zone
        self.windows = windows

    def name_matches(self, name: str) -> bool:
        if self.name.lower() == name.lower():
            return True
        if name.lower() in map(str.lower, self.aliases):
            return True
        return False

    def get_time_until(self, now: int = None) -> datetime.timedelta:
        return self.get_active_window(now).get_time_until(now)

    def get_active_window(self, now: int = None) -> RaidWindow:
        if not now:
            now = time.time()
        sorted_windows = collections.OrderedDict()
        for window in self.windows:
            sorted_windows[window.get_time_until(now)] = window

        for window in sorted_windows.values():
            if window.get_status() < RaidWindowStatus.PAST:
                return window

    def get_active_window_status(self, now: int = None) -> RaidWindowStatus:
        if not now:
            now = time.time()
        return self.get_active_window(now).get_status()

    @classmethod
    def from_json(cls, **kwargs) -> RaidTarget:
        return cls(**kwargs)


# Mutated from https://github.com/AlexisGomes/JsonEncoder/
class JSONDecoder(json.JSONDecoder):
    def __init__(self, *args, **kwargs):
        json.JSONDecoder.__init__(
            self, object_hook=self.object_hook, *args, **kwargs)

    def object_hook(self, obj):  # pylint: disable=method-hidden
        if isinstance(obj, dict):
            if 'raidTargets' in obj:
                return RaidTargets.from_json(**obj)
            try:
                return RaidTarget.from_json(**obj)
            except TypeError:
                return RaidWindow.from_json(**obj)

        # handling the resolution of nested objects
        if isinstance(obj, dict):
            for key in list(obj):
                obj[key] = self.object_hook(obj[key])

        return obj


if __name__ == '__main__':
    scout = RaidTargets.get_by_name("scout")
    print(scout.get_active_window().get_time_until())
