#!/usr/bin/env python3
"""
KTalk MCP Server

MCP-сервер для работы с записями и транскрипциями KTalk.
Предоставляет два инструмента:
  1. get_transcript — получить транскрипцию записи
  2. download_recording — скачать файл записи

Конфигурация через переменные окружения:
  KTALK_BASE_URL    — базовый URL (например https://ktstech.ktalk.ru)
  KTALK_API_TOKEN   — API-токен для авторизации (Authorization: Bearer)
  KTALK_SESSION_TOKEN — токен сессии (Cookie: sessionToken=...), альтернатива API-токену
  KTALK_DOWNLOAD_DIR — папка для сохранения скачанных записей (по умолчанию ./downloads)
"""

import os
import re
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "https://ktstech.ktalk.ru"
DEFAULT_DOWNLOAD_DIR = "./downloads"

# ---------------------------------------------------------------------------
# MCP-сервер
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "ktalk",
    instructions="MCP-сервер для KTalk: скачивание записей и получение транскрипций встреч",
)


def _get_base_url() -> str:
    """Получить базовый URL KTalk из переменной окружения."""
    return os.environ.get("KTALK_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _get_download_dir() -> Path:
    """Получить папку для скачанных файлов."""
    return Path(os.environ.get("KTALK_DOWNLOAD_DIR", DEFAULT_DOWNLOAD_DIR))


def _build_headers() -> dict[str, str]:
    """Собрать заголовки для HTTP-запросов к KTalk API."""
    headers: dict[str, str] = {
        "Accept": "application/json",
        "User-Agent": "ktalk-mcp/1.0",
    }

    api_token = os.environ.get("KTALK_API_TOKEN")
    session_token = os.environ.get("KTALK_SESSION_TOKEN")

    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"
    elif session_token:
        headers["Cookie"] = f"sessionToken={session_token}"

    return headers


def _build_download_headers() -> dict[str, str]:
    """Собрать заголовки для скачивания файлов."""
    headers: dict[str, str] = {
        "Accept": "*/*",
        "User-Agent": "ktalk-mcp/1.0",
    }

    api_token = os.environ.get("KTALK_API_TOKEN")
    session_token = os.environ.get("KTALK_SESSION_TOKEN")

    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"
    elif session_token:
        headers["Cookie"] = f"sessionToken={session_token}"

    return headers


def _format_timestamp(ms: int) -> str:
    """Форматировать миллисекунды в HH:MM:SS."""
    total_seconds = ms // 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _format_transcript(data: Any) -> str:
    """
    Отформатировать JSON-ответ транскрипции в читаемый текст.

    Поддерживаемые форматы ответа API:
      - Публичный API: GET /api/recordings/{recordingKey}/transcript
      - Внутренний API: GET /api/recordings/v2/{recordingKey}/summary
    """
    if not data:
        return "Транскрипция пуста."

    # ------------------------------------------------------------------
    # Формат 1: Публичный API — список фраз (phrases / segments)
    # ------------------------------------------------------------------
    if isinstance(data, list):
        lines = []
        for item in data:
            speaker = item.get("speakerName", item.get("speaker", "Неизвестный"))
            text = item.get("text", "")
            start_ms = item.get("startTimeOffsetInMillis", item.get("startMs", 0))
            ts = _format_timestamp(start_ms)
            lines.append(f"[{ts}] {speaker}: {text}")
        return "\n".join(lines) if lines else "Транскрипция пуста."

    # ------------------------------------------------------------------
    # Формат 2: Объект с полем transcription / transcriptionV2
    # ------------------------------------------------------------------
    transcription = data.get("transcriptionV2") or data.get("transcription") or data

    # Если транскрипция обёрнута в status
    status = transcription.get("status") if isinstance(transcription, dict) else None
    if status and status != "success":
        return f"Транскрипция недоступна (статус: {status})."

    tracks = transcription.get("tracks", []) if isinstance(transcription, dict) else []

    lines: list[str] = []
    for track in tracks:
        speaker_info = track.get("speaker", {})
        speaker_name = (
            speaker_info.get("anonymousName")
            or f"{speaker_info.get('firstname', '')} {speaker_info.get('surname', '')}".strip()
            or "Неизвестный"
        )
        for chunk in track.get("chunks", []):
            text = chunk.get("text", "")
            start_ms = chunk.get("startTimeOffsetInMillis", 0)
            ts = _format_timestamp(start_ms)
            lines.append(f"[{ts}] {speaker_name}: {text}")

    # ------------------------------------------------------------------
    # Формат 3: Плоский текст (поле "text" на верхнем уровне)
    # ------------------------------------------------------------------
    if not lines and isinstance(data, dict) and "text" in data:
        return data["text"]

    # ------------------------------------------------------------------
    # Формат 4: Поле phrases
    # ------------------------------------------------------------------
    if not lines and isinstance(data, dict):
        phrases = data.get("phrases", [])
        for phrase in phrases:
            speaker = phrase.get("speakerName", phrase.get("speaker", "Неизвестный"))
            text = phrase.get("text", "")
            start_ms = phrase.get("startTimeOffsetInMillis", phrase.get("startMs", 0))
            ts = _format_timestamp(start_ms)
            lines.append(f"[{ts}] {speaker}: {text}")

    return "\n".join(lines) if lines else "Не удалось извлечь текст транскрипции."


# ---------------------------------------------------------------------------
# Инструмент 1: Получить транскрипцию записи
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_transcript(
    recording_key: str,
    base_url: str | None = None,
) -> str:
    """Получить транскрипцию записи KTalk.

    Вызывает GET /api/recordings/{recordingKey}/transcript и возвращает
    отформатированный текст транскрипции с таймкодами и именами спикеров.

    Args:
        recording_key: Ключ записи (например "Y3ljMA8KGS72A68L0jp0").
        base_url: Базовый URL KTalk (если не указан, берётся из KTALK_BASE_URL).

    Returns:
        Текст транскрипции с таймкодами.
    """
    url_base = (base_url or _get_base_url()).rstrip("/")
    url = f"{url_base}/api/recordings/{recording_key}/transcript"
    headers = _build_headers()

    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        response = await client.get(url, headers=headers)

        if response.status_code == 401:
            return (
                "Ошибка 401: Не авторизован. "
                "Убедитесь, что задана переменная окружения KTALK_API_TOKEN или KTALK_SESSION_TOKEN."
            )
        if response.status_code == 403:
            return (
                "Ошибка 403: Доступ запрещён. "
                "Проверьте токен и права доступа к записи."
            )
        if response.status_code == 404:
            return f"Ошибка 404: Запись с ключом '{recording_key}' не найдена."

        response.raise_for_status()

        content_type = response.headers.get("content-type", "")

        if "application/json" in content_type:
            data = response.json()
            return _format_transcript(data)
        else:
            # Если API вернул plain text
            return response.text


# ---------------------------------------------------------------------------
# Инструмент 2: Скачать файл записи
# ---------------------------------------------------------------------------

@mcp.tool()
async def download_recording(
    recording_key: str,
    quality_name: str = "original",
    base_url: str | None = None,
    output_dir: str | None = None,
) -> str:
    """Скачать файл записи встречи KTalk.

    Вызывает GET /api/Recordings/{recordingKey}/file/{qualityName} и сохраняет
    файл на диск.

    Args:
        recording_key: Ключ записи (например "Y3ljMA8KGS72A68L0jp0").
        quality_name: Качество записи. Обычно "original", "low", "medium", "high".
        base_url: Базовый URL KTalk (если не указан, берётся из KTALK_BASE_URL).
        output_dir: Папка для сохранения (если не указана, берётся из KTALK_DOWNLOAD_DIR).

    Returns:
        Путь к сохранённому файлу или сообщение об ошибке.
    """
    url_base = (base_url or _get_base_url()).rstrip("/")
    url = f"{url_base}/api/Recordings/{recording_key}/file/{quality_name}"
    headers = _build_download_headers()
    download_dir = Path(output_dir) if output_dir else _get_download_dir()
    download_dir.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
        response = await client.get(url, headers=headers)

        if response.status_code == 401:
            return (
                "Ошибка 401: Не авторизован. "
                "Убедитесь, что задана переменная окружения KTALK_API_TOKEN или KTALK_SESSION_TOKEN."
            )
        if response.status_code == 403:
            return (
                "Ошибка 403: Доступ запрещён. "
                "Проверьте токен и права доступа к записи."
            )
        if response.status_code == 404:
            return (
                f"Ошибка 404: Файл записи '{recording_key}' с качеством '{quality_name}' не найден."
            )

        response.raise_for_status()

        # Определяем имя файла
        filename = _extract_filename(response, recording_key, quality_name)
        file_path = download_dir / filename

        # Сохраняем файл
        file_path.write_bytes(response.content)

        size_mb = len(response.content) / (1024 * 1024)
        return (
            f"Файл записи сохранён:\n"
            f"  Путь: {file_path.resolve()}\n"
            f"  Размер: {size_mb:.1f} МБ\n"
            f"  Ключ записи: {recording_key}\n"
            f"  Качество: {quality_name}"
        )


def _extract_filename(response: httpx.Response, recording_key: str, quality_name: str) -> str:
    """Извлечь имя файла из заголовка Content-Disposition или сгенерировать."""
    cd = response.headers.get("content-disposition", "")
    if cd:
        match = re.search(r'filename[*]?=["\']?([^"\';\r\n]+)', cd)
        if match:
            return match.group(1).strip()

    # Определяем расширение по Content-Type
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
# Точка входа
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
