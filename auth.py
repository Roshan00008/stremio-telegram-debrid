import secrets

from fastapi import HTTPException, Request

from config import Config


def _secure_compare(provided: str, expected: str) -> bool:
    if len(provided) != len(expected):
        return False
    return secrets.compare_digest(provided, expected)


def verify_api_key(request: Request) -> None:
    if Config.API_KEY:
        api_key = (
            request.query_params.get("api_key", "")
            or request.path_params.get("api_key", "")
        )
        if not _secure_compare(api_key, Config.API_KEY):
            raise HTTPException(status_code=403, detail="Unauthorized: Invalid API Key")


def check_api_key(api_key: str = "", query_api_key: str = "") -> None:
    if not Config.API_KEY:
        return
    actual_key = api_key or query_api_key
    if not _secure_compare(actual_key, Config.API_KEY):
        raise HTTPException(status_code=403, detail="Unauthorized")


def get_manifest(api_key: str = "") -> dict:
    return {
        "id": "community.telegram.stremio.addon",
        "version": "1.0.0",
        "name": "Telegram Addon by SunilRoy-dev",
        "description": (
            "Personal Telegram streaming proxy. For educational & personal testing only. "
            "Do not use for unauthorized hosting of copyrighted media."
        ),
        "logo": "https://upload.wikimedia.org/wikipedia/commons/8/82/Telegram_logo.svg",
        "resources": ["meta", "stream", "subtitles"],
        "types": ["movie", "series"],
        "idPrefixes": ["tgfile_", "tt"],
        "catalogs": [],
        "behaviorHints": {
            "configurable": False,
            "configurationRequired": False,
        },
    }
