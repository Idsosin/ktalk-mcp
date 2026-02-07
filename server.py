#!/usr/bin/env python3
"""
KTalk MCP Server

MCP-сервер для работы с записями и транскрипциями KTalk.
Предоставляет инструменты:
  1. get_transcript — получить транскрипцию записи
  2. download_recording — скачать файл записи
  3. get_recording_info — получить информацию о записи (участники, качества, длительность)

Конфигурация через переменные окружения:
  KTALK_BASE_URL    — базовый URL (например https://ktstech.ktalk.ru)
  KTALK_API_TOKEN   — API-ключ для авторизации (передаётся в заголовке X-Api-Key)
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


def _get_api_token() -> str:
    """Получить API-ключ из переменной окружения."""
    token = os.environ.get("KTALK_API_TOKEN", "")
    if not token:
        raise ValueError(
            "Переменная окружения KTALK_API_TOKEN не задана. "
            "Укажите API-ключ для авторизации в KTalk."
        )
    return token


def _build_headers() -> dict[str, str]:
    """Собрать заголовки для HTTP-запросов к KTalk API."""
    return {
        "Accept": "application/json",
        "User-Agent": "ktalk-mcp/1.0",
        "X-Api-Key": _get_api_token(),
    }


def _build_download_headers() -> dict[str, str]:
    """Собрать заголовки для скачивания файлов."""
    return {
        "Accept": "*/*",
        "User-Agent": "ktalk-mcp/1.0",
        "X-Api-Key": _get_api_token(),
    }


def _format_timestamp(ms: int) -> str:
    """Форматировать миллисекунды в HH:MM:SS."""
    total_seconds = ms // 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _format_duration(seconds: int) -> str:
    """Форматировать секунды в читаемую длительность."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}ч {minutes}мин {secs}с"
    if minutes > 0:
        return f"{minutes}мин {secs}с"
    return f"{secs}с"


def _format_transcript(data: Any) -> str:
    """Отформатировать JSON-ответ транскрипции в читаемый текст."""
    if not data:
        return "Транскрипция пуста."

    # Формат 1: Список фраз
    if isinstance(data, list):
        lines = []
        for item in data:
            speaker = item.get("speakerName", item.get("speaker", "Неизвестный"))
            text = item.get("text", "")
            start_ms = item.get("startTimeOffsetInMillis", item.get("startMs", 0))
            ts = _format_timestamp(start_ms)
            lines.append(f"[{ts}] {speaker}: {text}")
        return "\n".join(lines) if lines else "Транскрипция пуста."

    # Формат 2: Объект с полем transcription / transcriptionV2 / tracks
    transcription = data.get("transcriptionV2") or data.get("transcription") or data

    status = transcription.get("status") if isinstance(transcription, dict) else None
    if status and status not in ("success", "complete"):
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

    # Формат 3: Плоский текст
    if not lines and isinstance(data, dict) and "text" in data:
        return data["text"]

    # Формат 4: Поле phrases
    if not lines and isinstance(data, dict):
        phrases = data.get("phrases", [])
        for phrase in phrases:
            speaker = phrase.get("speakerName", phrase.get("speaker", "Неизвестный"))
            text = phrase.get("text", "")
            start_ms = phrase.get("startTimeOffsetInMillis", phrase.get("startMs", 0))
            ts = _format_timestamp(start_ms)
            lines.append(f"[{ts}] {speaker}: {text}")

    return "\n".join(lines) if lines else "Не удалось извлечь текст транскрипции."


def _handle_error(response: httpx.Response, context: str) -> str | None:
    """Обработать HTTP-ошибки. Возвращает сообщение об ошибке или None."""
    if response.status_code == 401:
        return (
            "Ошибка 401: Не авторизован. "
            "Убедитесь, что переменная окружения KTALK_API_TOKEN содержит корректный API-ключ."
        )
    if response.status_code == 403:
        return (
            "Ошибка 403: Доступ запрещён. "
            "Проверьте API-ключ и права доступа к записи."
        )
    if response.status_code == 404:
        return f"Ошибка 404: {context}"
    return None


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

        error = _handle_error(response, f"Запись с ключом '{recording_key}' не найдена.")
        if error:
            return error

        response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            data = response.json()
            return _format_transcript(data)
        else:
            return response.text


# ---------------------------------------------------------------------------
# Инструмент 2: Скачать файл записи
# ---------------------------------------------------------------------------

@mcp.tool()
async def download_recording(
    recording_key: str,
    quality_name: str = "240p",
    base_url: str | None = None,
    output_dir: str | None = None,
) -> str:
    """Скачать файл записи встречи KTalk.

    Вызывает GET /api/Recordings/{recordingKey}/file/{qualityName} и сохраняет
    файл на диск. Перед скачиванием рекомендуется вызвать get_recording_info,
    чтобы узнать доступные качества записи.

    Args:
        recording_key: Ключ записи (например "Y3ljMA8KGS72A68L0jp0").
        quality_name: Качество записи. Типичные значения: "240p", "480p", "720p", "900p", "1080p".
                      По умолчанию "240p".
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

        error = _handle_error(
            response,
            f"Файл записи '{recording_key}' с качеством '{quality_name}' не найден. "
            f"Используйте get_recording_info, чтобы узнать доступные качества.",
        )
        if error:
            return error

        response.raise_for_status()

        filename = _extract_filename(response, recording_key, quality_name)
        file_path = download_dir / filename

        file_path.write_bytes(response.content)

        size_mb = len(response.content) / (1024 * 1024)
        return (
            f"Файл записи сохранён:\n"
            f"  Путь: {file_path.resolve()}\n"
            f"  Размер: {size_mb:.1f} МБ\n"
            f"  Ключ записи: {recording_key}\n"
            f"  Качество: {quality_name}"
        )


# ---------------------------------------------------------------------------
# Инструмент 3: Информация о записи
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_recording_info(
    recording_key: str,
    base_url: str | None = None,
) -> str:
    """Получить информацию о записи KTalk.

    Возвращает название, длительность, участников, доступные качества для скачивания
    и статус транскрипции.

    Args:
        recording_key: Ключ записи (например "Y3ljMA8KGS72A68L0jp0").
        base_url: Базовый URL KTalk (если не указан, берётся из KTALK_BASE_URL).

    Returns:
        Информация о записи в текстовом формате.
    """
    url_base = (base_url or _get_base_url()).rstrip("/")
    url = f"{url_base}/api/Recordings/{recording_key}"
    headers = _build_headers()

    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        response = await client.get(url, headers=headers)

        error = _handle_error(response, f"Запись с ключом '{recording_key}' не найдена.")
        if error:
            return error

        response.raise_for_status()
        data = response.json()

    title = data.get("title", "Без названия")
    description = data.get("description") or ""
    created = data.get("createdDate", "")
    duration = data.get("duration", 0)
    status = data.get("status", "unknown")
    participants_count = data.get("participantsCount", 0)

    # Автор записи
    created_by = data.get("createdBy", {})
    author = f"{created_by.get('firstname', '')} {created_by.get('surname', '')}".strip()
    author_email = created_by.get("email", "")

    # Участники
    participants = data.get("participants", [])
    participant_names = []
    for p in participants:
        user = p.get("userInfo") or {}
        name = (
            p.get("anonymousName")
            or f"{user.get('firstname', '')} {user.get('surname', '')}".strip()
            or "Неизвестный"
        )
        participant_names.append(name)

    # Доступные качества
    qualities = data.get("qualities", [])
    quality_lines = []
    for q in qualities:
        q_name = q.get("name", "?")
        q_status = q.get("status", "unknown")
        size = q.get("size", {})
        resolution = f"{size.get('width', '?')}x{size.get('height', '?')}"
        quality_lines.append(f"  - {q_name} ({resolution}, статус: {q_status})")

    # Транскрипция
    transcription = data.get("transcription", {})
    tr_status = transcription.get("status", "нет") if transcription else "нет"

    has_audio = data.get("hasAudioRecord", False)

    # Формируем вывод
    lines = [
        f"Запись: {title}",
        f"Ключ: {recording_key}",
    ]
    if description:
        lines.append(f"Описание: {description}")
    lines.extend([
        f"Дата создания: {created}",
        f"Автор: {author} ({author_email})" if author_email else f"Автор: {author}",
        f"Длительность: {_format_duration(duration)}",
        f"Статус: {status}",
        f"Участников: {participants_count}",
    ])
    if participant_names:
        lines.append(f"Участники: {', '.join(participant_names)}")
    lines.append(f"Аудиозапись: {'да' if has_audio else 'нет'}")
    lines.append(f"Транскрипция: {tr_status}")
    if quality_lines:
        lines.append("Доступные качества для скачивания:")
        lines.extend(quality_lines)
    else:
        lines.append("Качества для скачивания: нет данных")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _extract_filename(response: httpx.Response, recording_key: str, quality_name: str) -> str:
    """Извлечь имя файла из заголовка Content-Disposition или сгенерировать."""
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
# Точка входа
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
