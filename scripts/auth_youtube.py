#!/usr/bin/env python3
"""
YouTube OAuth authentication helper.

This script authenticates with YouTube Data API and saves the token
for later use by the upload scripts.

Usage:
    python3 scripts/auth_youtube.py

Prerequisites:
    1. Create a project in Google Cloud Console
    2. Enable YouTube Data API v3
    3. Create OAuth 2.0 credentials (Desktop app)
    4. Download client_secret.json to config/oauth/
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
CONFIG_DIR = REPO_ROOT / "config" / "oauth"

CLIENT_SECRET_PATH = CONFIG_DIR / "client_secret.json"
TOKEN_PATH = CONFIG_DIR / "token.json"


def main() -> None:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Error: Required packages not installed.")
        print("Run: pip install google-auth-oauthlib google-api-python-client")
        sys.exit(1)

    if not CLIENT_SECRET_PATH.exists():
        print(f"Error: Client secret not found at {CLIENT_SECRET_PATH}")
        print()
        print("To set up OAuth:")
        print("1. Go to https://console.cloud.google.com/")
        print("2. Create or select a project")
        print("3. Enable YouTube Data API v3")
        print("4. Go to APIs & Services > Credentials")
        print("5. Create OAuth 2.0 Client ID (Desktop app)")
        print("6. Download JSON and save to:")
        print(f"   {CLIENT_SECRET_PATH}")
        sys.exit(1)

    SCOPES = [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube.readonly",
    ]

    print("Starting OAuth flow...")
    print("A browser window will open for authentication.")
    print()

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), SCOPES)
    credentials = flow.run_local_server(port=0)

    # Save the credentials
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(credentials.to_json(), encoding="utf-8")

    print()
    print("Authentication successful!")
    print(f"Token saved to: {TOKEN_PATH}")
    print()
    print("You can now use the upload features.")


if __name__ == "__main__":
    main()
