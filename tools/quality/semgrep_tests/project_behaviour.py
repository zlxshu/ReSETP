"""Semgrep rule fixtures: findings are deliberate historical pathologies."""

from __future__ import annotations

import collections
import re


# ruleid: resetp-no-object-id-cache-key
OBJECT_CACHE[id(object())] = "direct"
# ruleid: resetp-no-object-id-cache-key
_CARBON_PROFILE_SORT_CACHE[(id(object()), "profile")] = "forward"
# ruleid: resetp-no-object-id-cache-key
_CARBON_PROFILE_SORT_CACHE[("profile", id(object()))] = "reverse"


def derived_forward(time_profile: object, city: str) -> object | None:
    cache_key = (id(time_profile), city)
    # ruleid: resetp-no-object-id-cache-key
    value = OBJECT_CACHE.get(cache_key)
    # ruleid: resetp-no-object-id-cache-key
    OBJECT_CACHE[cache_key] = value
    return value


def derived_reverse(time_profile: object, city: str) -> object | None:
    cache_key = (city, id(time_profile))
    # ruleid: resetp-no-object-id-cache-key
    return OBJECT_CACHE.setdefault(cache_key, None)


# ok: resetp-no-object-id-cache-key
STABLE_CACHE[("time-profile-sha256", "city")] = "stable"


def stable_lookup(profile_sha256: str, city: str) -> object | None:
    stable_key = (profile_sha256, city)
    # ok: resetp-no-object-id-cache-key
    return STABLE_CACHE.get(stable_key)


# ruleid: resetp-no-module-mutable-cache
MODULE_CACHE = {}
# ruleid: resetp-no-module-mutable-cache
ORDERED_CACHE = collections.OrderedDict()


class RunContext:
    def __init__(self) -> None:
        # ok: resetp-no-module-mutable-cache
        self.cache = {}


def local_cache() -> dict[str, object]:
    # ok: resetp-no-module-mutable-cache
    request_cache = {}
    return request_cache


def detail_regex(error: object) -> bool:
    # ruleid: resetp-no-detail-message-regex-control-flow
    if re.search("late", error.detail):
        return True
    # ruleid: resetp-no-detail-message-regex-control-flow
    if re.match("failed", error.message):
        return True
    return False


def structured_control(error: object) -> bool:
    # ok: resetp-no-detail-message-regex-control-flow
    if error.code == "LATE_DEPARTURE":
        return True
    # ok: resetp-no-detail-message-regex-control-flow
    return "late" in error.detail


def bare_default() -> object | None:
    # ruleid: resetp-no-broad-except-return-default
    try:
        return work()
    except:
        return None


def exception_default() -> object | None:
    # ruleid: resetp-no-broad-except-return-default
    try:
        return work()
    except Exception:
        return None


def named_exception_default() -> object | None:
    # ruleid: resetp-no-broad-except-return-default
    try:
        return work()
    except Exception as exc:
        remember(exc)
        return None


def narrow_exception() -> object | None:
    try:
        return work()
    # ok: resetp-no-broad-except-return-default
    except ValueError:
        return None


def propagate_exception() -> object:
    try:
        return work()
    # ok: resetp-no-broad-except-return-default
    except Exception:
        raise
