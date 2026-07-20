#!/usr/bin/env python3
"""One-time OAuth consent for the YouTube Data API upload backend.

Opens a browser consent screen, then caches a refresh token at
``youtube_api_token_path`` so all later uploads (webui, cron) are silent.

Run from the project root after setting ``youtube_api_client_secrets_path``
in config.json:
    python scripts/youtube_api_auth.py

IMPORTANT: on the Google consent screen, pick the *channel* (brand account)
you want uploads to land on — the token is bound to that channel.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)

from config import get_youtube_api_client_secrets_path, get_youtube_api_token_path
from youtube_api_upload import load_or_refresh_credentials


def main() -> int:
    secrets = get_youtube_api_client_secrets_path()
    token = get_youtube_api_token_path()
    if not secrets:
        print("ERROR: youtube_api_client_secrets_path is not set in config.json")
        return 1
    print(f"Client secrets: {secrets}")
    print(f"Token cache:    {token}")
    creds = load_or_refresh_credentials(secrets, token)
    print(f"OK — token valid: {creds.valid}. Cached refresh token at {token}")
    print('Uploads via upload_backend: "api" will now run without a browser.')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
