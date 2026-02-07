#!/usr/bin/env python3
"""
KTalk MCP Server

MCP server for working with KTalk meeting recordings and transcripts.
Provides the following tools:
  1. get_transcript      - fetch transcript and save as .txt file
  2. download_recording  - download recording video/audio file
  3. get_recording_info  - get recording metadata (participants, qualities, duration)

Configuration via environment variables:
  KTALK_BASE_URL     - base URL (e.g. https://ktstech.ktalk.ru)
  KTALK_API_TOKEN    - API key for authorization (sent as X-Api-Key header)
  KTALK_DOWNLOAD_DIR - directory for saved files (default: ./downloads)
"""

import os
import re
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "https://ktstech.ktalk.ru"
DEFAULT_DOWNLOAD_DIR = "./downloads"

# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "ktalk",
    instructions="MCP server for KTalk: download meeting recordings and transcripts",
)


def _get_base_url() -> str:
    """Return the KTalk base URL from the environment."""
    return os.environ.get("KTALK_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _get_download_dir() -> Path:
    """Return the directory where downloaded files are saved."""
    return Path(os.environ.get("KTALK_DOWNLOAD_DIR", DEFAULT_DOWNLOAD_DIR))


def _get_api_token() -> str:
    """Return the API key from the environment."""
    token = os.environ.get("KTALK_API_TOKEN", "")
    if not token:
        raise ValueError(
            "KTALK_API_TOKEN environment variable is not set. "
            "Please provide a valid KTalk API key."
        )
    return token


def _build_headers() -> dict[str, str]:
    """Build headers for JSON API requests."""
    return {
        "Accept": "application/json",
        "User-Agent": "ktalk-mcp/1.0",
        "X-Api-Key": _get_api_token(),
    }


def _build_download_headers() -> dict[str, str]:
    """Build headers for file download requests."""
    return {
        "Accept": "*/*",
        "User-Agent": "ktalk-mcp/1.0",
        "X-Api-Key": _get_api_token(),
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
            "Make sure KTALK_API_TOKEN contains a valid API key."
        )
    if response.status_code == 403:
        return (
            "Error 403: Forbidden. "
            "Check the API key and access permissions for this recording."
        )
    if response.status_code == 404:
        return f"Error 404: {context}"
    return None


# ---------------------------------------------------------------------------
# Tool 1: Get transcript
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_transcript(
    recording_key: str,
    base_url: str | None = None,
    output_dir: str | None = None,
) -> str:
    """Download the transcript of a KTalk recording and save it as a .txt file.

    Calls GET /api/recordings/{recordingKey}/transcript, formats the result
    with timestamps and speaker names, and saves it to the download directory.

    Args:
        recording_key: Recording key (e.g. "Y3ljMA8KGS72A68L0jp0").
        base_url: KTalk base URL. Falls back to KTALK_BASE_URL env var.
        output_dir: Directory to save the file. Falls back to KTALK_DOWNLOAD_DIR env var.

    Returns:
        Summary with the saved file path and basic stats.
    """
    url_base = (base_url or _get_base_url()).rstrip("/")
    url = f"{url_base}/api/recordings/{recording_key}/transcript"
    headers = _build_headers()
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
# Tool 2: Download recording file
# ---------------------------------------------------------------------------

@mcp.tool()
async def download_recording(
    recording_key: str,
    quality_name: str = "240p",
    base_url: str | None = None,
    output_dir: str | None = None,
) -> str:
    """Download a KTalk meeting recording file.

    Calls GET /api/Recordings/{recordingKey}/file/{qualityName} and saves
    the file to disk. Use get_recording_info first to see available qualities.

    Args:
        recording_key: Recording key (e.g. "Y3ljMA8KGS72A68L0jp0").
        quality_name: Video quality. Typical values: "240p", "480p", "720p", "900p", "1080p".
                      Defaults to "240p".
        base_url: KTalk base URL. Falls back to KTALK_BASE_URL env var.
        output_dir: Directory to save the file. Falls back to KTALK_DOWNLOAD_DIR env var.

    Returns:
        Summary with the saved file path and size, or an error message.
    """
    url_base = (base_url or _get_base_url()).rstrip("/")
    url = f"{url_base}/api/Recordings/{recording_key}/file/{quality_name}"
    headers = _build_download_headers()
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
# Tool 3: Get recording info
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_recording_info(
    recording_key: str,
    base_url: str | None = None,
) -> str:
    """Get metadata about a KTalk recording.

    Returns title, duration, participants, available download qualities,
    and transcript status.

    Args:
        recording_key: Recording key (e.g. "Y3ljMA8KGS72A68L0jp0").
        base_url: KTalk base URL. Falls back to KTALK_BASE_URL env var.

    Returns:
        Recording information in a human-readable text format.
    """
    url_base = (base_url or _get_base_url()).rstrip("/")
    url = f"{url_base}/api/Recordings/{recording_key}"
    headers = _build_headers()

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
