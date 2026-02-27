#!/usr/bin/env python3
"""
KTalk MCP Server

MCP server for working with KTalk meeting recordings and transcripts
via kts-ktalk-api-proxy with JWT (Keycloak) authentication.

Provides the following tools:
  0. login              - authenticate via Keycloak (username/password)
  1. list_recordings    - list recordings with optional filters
  2. get_recording_info - get recording metadata (participants, qualities, duration)
  3. get_transcript     - fetch transcript and save as .txt file
  4. download_recording - download recording video/audio file

Configuration via environment variables:
  KTALK_PROXY_URL    - proxy base URL (e.g. https://your-proxy.example.com)
  KTALK_JWT_TOKEN    - (optional) JWT override; if omitted, uses saved token from login
  KTALK_DOWNLOAD_DIR - directory for saved files (default: ./downloads)
"""

import json
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_DOWNLOAD_DIR = "./downloads"
TOKEN_DIR = Path.home() / ".ktalk-mcp"
TOKEN_FILE = TOKEN_DIR / "token.json"

# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "ktalk",
    instructions=(
        "MCP server for KTalk: list, download and transcribe meeting recordings "
        "via proxy. Call the 'login' tool first if you get a 401 error."
    ),
)

# ---------------------------------------------------------------------------
# Token persistence
# ---------------------------------------------------------------------------


def _save_tokens(data: dict) -> None:
    """Persist JWT tokens to a local file."""
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _load_tokens() -> dict | None:
    """Load JWT tokens from the local file, or return None."""
    if not TOKEN_FILE.exists():
        return None
    try:
        return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------


def _get_proxy_url() -> str:
    """Return the proxy base URL from the environment."""
    url = os.environ.get("KTALK_PROXY_URL", "").rstrip("/")
    if not url:
        raise ValueError(
            "KTALK_PROXY_URL environment variable is not set. "
            "Provide the kts-ktalk-api-proxy URL."
        )
    return url


async def _refresh_access_token(tokens: dict) -> str | None:
    """Try to refresh the access token using the stored refresh_token."""
    refresh_token = tokens.get("refresh_token", "")
    keycloak_url = tokens.get("keycloak_token_url", "")
    if not refresh_token or not keycloak_url:
        return None
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(keycloak_url, data={
                "client_id": "admin-cli",
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            })
            if resp.status_code != 200:
                return None
            data = resp.json()
        new_access = data.get("access_token", "")
        if not new_access:
            return None
        _save_tokens({
            "access_token": new_access,
            "refresh_token": data.get("refresh_token", refresh_token),
            "expires_at": time.time() + data.get("expires_in", 300),
            "keycloak_token_url": keycloak_url,
        })
        return new_access
    except Exception:
        return None


def _get_jwt_token() -> str:
    """Return a valid JWT token (env var > saved file)."""
    env_token = os.environ.get("KTALK_JWT_TOKEN", "")
    if env_token:
        return env_token

    tokens = _load_tokens()
    if tokens and tokens.get("access_token"):
        expires_at = tokens.get("expires_at", 0)
        if time.time() < expires_at - 30:
            return tokens["access_token"]

    raise ValueError(
        "No valid JWT token. "
        "Call the 'login' tool to authenticate via Keycloak, "
        "or set KTALK_JWT_TOKEN environment variable."
    )


def _get_api_base() -> str:
    """Return the KTalk API base routed through the proxy."""
    return f"{_get_proxy_url()}/api/talk"


def _get_download_dir() -> Path:
    """Return the directory where downloaded files are saved."""
    return Path(os.environ.get("KTALK_DOWNLOAD_DIR", DEFAULT_DOWNLOAD_DIR))


async def _get_valid_token() -> str:
    """Return a valid JWT, attempting a refresh if the saved token is expired."""
    env_token = os.environ.get("KTALK_JWT_TOKEN", "")
    if env_token:
        return env_token

    tokens = _load_tokens()
    if not tokens or not tokens.get("access_token"):
        raise ValueError(
            "No valid JWT token. "
            "Call the 'login' tool to authenticate via Keycloak."
        )

    expires_at = tokens.get("expires_at", 0)
    if time.time() < expires_at - 30:
        return tokens["access_token"]

    refreshed = await _refresh_access_token(tokens)
    if refreshed:
        return refreshed

    raise ValueError(
        "JWT token expired and refresh failed. "
        "Call the 'login' tool to re-authenticate."
    )


async def _build_headers() -> dict[str, str]:
    """Build headers for JSON API requests (Bearer JWT via proxy)."""
    return {
        "Accept": "application/json",
        "Accept-Encoding": "identity",
        "User-Agent": "ktalk-mcp/1.0",
        "Authorization": f"Bearer {await _get_valid_token()}",
    }


async def _build_download_headers() -> dict[str, str]:
    """Build headers for file download requests (Bearer JWT via proxy)."""
    return {
        "Accept": "*/*",
        "Accept-Encoding": "identity",
        "User-Agent": "ktalk-mcp/1.0",
        "Authorization": f"Bearer {await _get_valid_token()}",
    }


def _format_timestamp(ms: int) -> str:
    """Format milliseconds as HH:MM:SS or MM:SS."""
    total_seconds = ms // 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _format_duration(seconds: int) -> str:
    """Format seconds as a human-readable duration string."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _parse_transcript(data: Any) -> list[str]:
    """Parse the API transcript response into a list of formatted lines."""
    if not data:
        return []

    # Format 1: flat list of phrases/segments
    if isinstance(data, list):
        lines = []
        for item in data:
            speaker = item.get("speakerName", item.get("speaker", "Unknown"))
            text = item.get("text", "")
            start_ms = item.get("startTimeOffsetInMillis", item.get("startMs", 0))
            ts = _format_timestamp(start_ms)
            lines.append(f"[{ts}] {speaker}: {text}")
        return lines

    # Format 2: object with transcription / transcriptionV2 / tracks
    transcription = data.get("transcriptionV2") or data.get("transcription") or data

    status = transcription.get("status") if isinstance(transcription, dict) else None
    if status and status not in ("success", "complete"):
        return [f"Transcript unavailable (status: {status})."]

    tracks = transcription.get("tracks", []) if isinstance(transcription, dict) else []

    lines: list[str] = []
    for track in tracks:
        speaker_info = track.get("speaker", {})
        speaker_name = (
            speaker_info.get("anonymousName")
            or f"{speaker_info.get('firstname', '')} {speaker_info.get('surname', '')}".strip()
            or "Unknown"
        )
        for chunk in track.get("chunks", []):
            text = chunk.get("text", "")
            start_ms = chunk.get("startTimeOffsetInMillis", 0)
            ts = _format_timestamp(start_ms)
            lines.append(f"[{ts}] {speaker_name}: {text}")

    # Format 3: plain text field at the top level
    if not lines and isinstance(data, dict) and "text" in data:
        return [data["text"]]

    # Format 4: phrases field
    if not lines and isinstance(data, dict):
        phrases = data.get("phrases", [])
        for phrase in phrases:
            speaker = phrase.get("speakerName", phrase.get("speaker", "Unknown"))
            text = phrase.get("text", "")
            start_ms = phrase.get("startTimeOffsetInMillis", phrase.get("startMs", 0))
            ts = _format_timestamp(start_ms)
            lines.append(f"[{ts}] {speaker}: {text}")

    return lines


def _extract_speakers(data: Any) -> list[str]:
    """Extract unique speaker names from the transcript API response."""
    speakers: set[str] = set()
    if not data or not isinstance(data, dict):
        return []

    transcription = data.get("transcriptionV2") or data.get("transcription") or data
    tracks = transcription.get("tracks", []) if isinstance(transcription, dict) else []

    for track in tracks:
        speaker_info = track.get("speaker", {})
        name = (
            speaker_info.get("anonymousName")
            or f"{speaker_info.get('firstname', '')} {speaker_info.get('surname', '')}".strip()
        )
        if name:
            speakers.add(name)

    return sorted(speakers)


def _handle_error(response: httpx.Response, context: str) -> str | None:
    """Handle HTTP errors. Returns an error message or None if OK."""
    if response.status_code == 401:
        return (
            "Error 401: Unauthorized. "
            "The JWT token is missing or expired. "
            "Call the 'login' tool to re-authenticate."
        )
    if response.status_code == 403:
        return (
            "Error 403: Forbidden. "
            "The JWT token does not have sufficient permissions."
        )
    if response.status_code == 404:
        return f"Error 404: {context}"
    return None


# ---------------------------------------------------------------------------
# Tool 0: Login (Keycloak direct access grant)
# ---------------------------------------------------------------------------


@mcp.tool()
async def login(username: str, password: str) -> str:
    """Authenticate with Keycloak to obtain a JWT token.

    Uses the Keycloak direct access grant (Resource Owner Password).
    The token and refresh token are saved locally so subsequent API
    calls work automatically.  When the access token expires it is
    refreshed transparently.

    Args:
        username: Keycloak username (e.g. "i.sosin").
        password: Keycloak password.

    Returns:
        Confirmation message with token expiry info.
    """
    proxy_url = _get_proxy_url()

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{proxy_url}/api/config")
        resp.raise_for_status()
        config = resp.json()

    keycloak_url = config["keycloak_url"].rstrip("/")
    realm = config["keycloak_realm"]
    token_url = f"{keycloak_url}/realms/{realm}/protocol/openid-connect/token"

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(token_url, data={
            "client_id": "admin-cli",
            "grant_type": "password",
            "username": username,
            "password": password,
            "scope": "openid",
        })
        if resp.status_code != 200:
            detail = resp.json().get("error_description", resp.text)
            return f"Login failed ({resp.status_code}): {detail}"
        token_data = resp.json()

    access_token = token_data.get("access_token", "")
    if not access_token:
        return "Login failed: Keycloak returned no access_token."

    expires_in = token_data.get("expires_in", 300)
    _save_tokens({
        "access_token": access_token,
        "refresh_token": token_data.get("refresh_token", ""),
        "expires_at": time.time() + expires_in,
        "keycloak_token_url": token_url,
    })

    return (
        f"Authenticated as {username}.\n"
        f"Token saved to {TOKEN_FILE}\n"
        f"Expires in {expires_in // 60} min (auto-refreshes)."
    )


# ---------------------------------------------------------------------------
# Tool 1: List recordings
# ---------------------------------------------------------------------------

@mcp.tool()
async def list_recordings(
    room_name: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> str:
    """List KTalk recordings, optionally filtered by room and date range.

    Args:
        room_name: Filter by room name / ID (e.g. "mcptkdy64ohg").
        from_date: Start date filter in YYYY-MM-DD format.
        to_date: End date filter in YYYY-MM-DD format.

    Returns:
        A list of recordings with key, title, date, duration and participant count.
    """
    url = f"{_get_api_base()}/api/Domain/recordings/v2"
    params: dict[str, str] = {}
    if room_name:
        params["roomName"] = room_name
    if from_date:
        params["fromDate"] = from_date
    if to_date:
        params["toDate"] = to_date

    headers = await _build_headers()

    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        response = await client.get(url, headers=headers, params=params)

        error = _handle_error(response, "Recordings endpoint not available.")
        if error:
            return error

        response.raise_for_status()
        data = response.json()

    recordings = data if isinstance(data, list) else data.get("recordings", data.get("items", []))

    if not recordings:
        return "No recordings found."

    lines: list[str] = [f"Found {len(recordings)} recording(s):\n"]
    for rec in recordings:
        key = rec.get("key", rec.get("recordingKey", "?"))
        title = rec.get("title", "Untitled")
        created = rec.get("createdDate", "")
        duration = rec.get("duration", 0)
        participants = rec.get("participantsCount", 0)

        dur_str = _format_duration(duration) if duration else "n/a"
        lines.append(
            f"  [{key}] {title}\n"
            f"    Created: {created} | Duration: {dur_str} | Participants: {participants}"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 2: Get transcript
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_transcript(
    recording_key: str,
    output_dir: str | None = None,
) -> str:
    """Download the transcript of a KTalk recording and save it as a .txt file.

    Fetches the transcript via the proxy, formats the result with timestamps
    and speaker names, and saves it to the download directory.

    Args:
        recording_key: Recording key (e.g. "Y3ljMA8KGS72A68L0jp0").
        output_dir: Directory to save the file. Falls back to KTALK_DOWNLOAD_DIR env var.

    Returns:
        Summary with the saved file path and basic stats.
    """
    url = f"{_get_api_base()}/api/recordings/{recording_key}/transcript"
    headers = await _build_headers()
    download_dir = Path(output_dir) if output_dir else _get_download_dir()
    download_dir.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        response = await client.get(url, headers=headers)

        error = _handle_error(
            response,
            f"Recording '{recording_key}' not found.",
        )
        if error:
            return error

        response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            data = response.json()
            lines = _parse_transcript(data)
            speakers = _extract_speakers(data)
        else:
            lines = [response.text]
            speakers = []

    if not lines:
        return f"Transcript for recording '{recording_key}' is empty."

    transcript_text = "\n".join(lines)

    # Save to file
    filename = f"{recording_key}_transcript.txt"
    file_path = download_dir / filename
    file_path.write_text(transcript_text, encoding="utf-8")

    # Build summary
    summary_parts = [
        "Transcript saved:",
        f"  Path: {file_path.resolve()}",
        f"  Recording key: {recording_key}",
        f"  Lines: {len(lines)}",
    ]
    if speakers:
        summary_parts.append(f"  Speakers: {', '.join(speakers)}")

    return "\n".join(summary_parts)


# ---------------------------------------------------------------------------
# Tool 3: Download recording file
# ---------------------------------------------------------------------------

@mcp.tool()
async def download_recording(
    recording_key: str,
    quality_name: str = "240p",
    output_dir: str | None = None,
) -> str:
    """Download a KTalk meeting recording file.

    Downloads the file via the proxy and saves it to disk.
    Use get_recording_info first to see available qualities.

    Args:
        recording_key: Recording key (e.g. "Y3ljMA8KGS72A68L0jp0").
        quality_name: Video quality. Typical values: "240p", "480p", "720p", "900p", "1080p".
                      Defaults to "240p".
        output_dir: Directory to save the file. Falls back to KTALK_DOWNLOAD_DIR env var.

    Returns:
        Summary with the saved file path and size, or an error message.
    """
    url = f"{_get_api_base()}/api/Recordings/{recording_key}/file/{quality_name}"
    headers = await _build_download_headers()
    download_dir = Path(output_dir) if output_dir else _get_download_dir()
    download_dir.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
        response = await client.get(url, headers=headers)

        error = _handle_error(
            response,
            f"Recording file '{recording_key}' with quality '{quality_name}' not found. "
            f"Use get_recording_info to see available qualities.",
        )
        if error:
            return error

        response.raise_for_status()

        filename = _extract_filename(response, recording_key, quality_name)
        file_path = download_dir / filename

        file_path.write_bytes(response.content)

        size_mb = len(response.content) / (1024 * 1024)
        return (
            f"Recording file saved:\n"
            f"  Path: {file_path.resolve()}\n"
            f"  Size: {size_mb:.1f} MB\n"
            f"  Recording key: {recording_key}\n"
            f"  Quality: {quality_name}"
        )


# ---------------------------------------------------------------------------
# Tool 4: Get recording info
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_recording_info(
    recording_key: str,
) -> str:
    """Get metadata about a KTalk recording.

    Returns title, duration, participants, available download qualities,
    and transcript status.

    Args:
        recording_key: Recording key (e.g. "Y3ljMA8KGS72A68L0jp0").

    Returns:
        Recording information in a human-readable text format.
    """
    url = f"{_get_api_base()}/api/Recordings/{recording_key}"
    headers = await _build_headers()

    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        response = await client.get(url, headers=headers)

        error = _handle_error(
            response,
            f"Recording '{recording_key}' not found.",
        )
        if error:
            return error

        response.raise_for_status()
        data = response.json()

    title = data.get("title", "Untitled")
    description = data.get("description") or ""
    created = data.get("createdDate", "")
    duration = data.get("duration", 0)
    status = data.get("status", "unknown")
    participants_count = data.get("participantsCount", 0)

    # Author
    created_by = data.get("createdBy", {})
    author = f"{created_by.get('firstname', '')} {created_by.get('surname', '')}".strip()
    author_email = created_by.get("email", "")

    # Participants
    participants = data.get("participants", [])
    participant_names = []
    for p in participants:
        user = p.get("userInfo") or {}
        name = (
            p.get("anonymousName")
            or f"{user.get('firstname', '')} {user.get('surname', '')}".strip()
            or "Unknown"
        )
        participant_names.append(name)

    # Available qualities
    qualities = data.get("qualities", [])
    quality_lines = []
    for q in qualities:
        q_name = q.get("name", "?")
        q_status = q.get("status", "unknown")
        size = q.get("size", {})
        resolution = f"{size.get('width', '?')}x{size.get('height', '?')}"
        quality_lines.append(f"  - {q_name} ({resolution}, status: {q_status})")

    # Transcript status
    transcription = data.get("transcription", {})
    tr_status = transcription.get("status", "none") if transcription else "none"

    has_audio = data.get("hasAudioRecord", False)

    # Build output
    lines = [
        f"Recording: {title}",
        f"Key: {recording_key}",
    ]
    if description:
        lines.append(f"Description: {description}")
    lines.extend([
        f"Created: {created}",
        f"Author: {author} ({author_email})" if author_email else f"Author: {author}",
        f"Duration: {_format_duration(duration)}",
        f"Status: {status}",
        f"Participants: {participants_count}",
    ])
    if participant_names:
        lines.append(f"Participant names: {', '.join(participant_names)}")
    lines.append(f"Audio record: {'yes' if has_audio else 'no'}")
    lines.append(f"Transcript: {tr_status}")
    if quality_lines:
        lines.append("Available qualities for download:")
        lines.extend(quality_lines)
    else:
        lines.append("Available qualities: no data")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_filename(response: httpx.Response, recording_key: str, quality_name: str) -> str:
    """Extract filename from Content-Disposition header or generate one."""
    cd = response.headers.get("content-disposition", "")
    if cd:
        match = re.search(r'filename[*]?=["\']?([^"\';\r\n]+)', cd)
        if match:
            return match.group(1).strip()

    content_type = response.headers.get("content-type", "")
    ext_map = {
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "audio/mpeg": ".mp3",
        "audio/wav": ".wav",
        "audio/ogg": ".ogg",
        "application/octet-stream": ".mp4",
    }
    ext = ext_map.get(content_type.split(";")[0].strip(), ".mp4")
    return f"{recording_key}_{quality_name}{ext}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
