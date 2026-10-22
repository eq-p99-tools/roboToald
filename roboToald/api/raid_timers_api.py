"""Public raid-target JSON feed (PHP ``targets-v2.json`` replacement)."""

from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from roboToald import config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/raidtargets", tags=["raidtargets"])


@router.get("/{guild_id}/targets-v2.json")
def get_feed(guild_id: int, request: Request) -> JSONResponse:
    expected = config.get_raidtargets_feed_key(guild_id)
    provided = request.headers.get("AuthorizationKey", "") or ""
    if (
        not expected
        or config.get_raidtargets_source(guild_id) != "local"
        or not hmac.compare_digest(provided, expected)
    ):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    from roboToald.raidtargets import rt_service

    feed = rt_service.build_feed_for_guild(guild_id)
    return JSONResponse(
        feed,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "max-age=30",
        },
    )
