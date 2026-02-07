# KTalk MCP Server

MCP-сервер для работы с записями и транскрипциями [KTalk](https://ktalk.ru) — системой для проведения встреч.

## Возможности

| Инструмент | Описание |
|---|---|
| `get_recording_info` | Получить информацию о записи (название, участники, доступные качества) |
| `get_transcript` | Получить транскрипцию записи (с таймкодами и именами спикеров) |
| `download_recording` | Скачать файл записи встречи |

## Установка

```bash
# Создать виртуальное окружение
python3 -m venv .venv
source .venv/bin/activate

# Установить зависимости
pip install -r requirements.txt
```

## Конфигурация

Сервер настраивается через переменные окружения:

| Переменная | Обязательная | Описание |
|---|---|---|
| `KTALK_API_TOKEN` | Да | API-ключ для авторизации (передаётся как `X-Api-Key`) |
| `KTALK_BASE_URL` | Нет | Базовый URL KTalk (по умолчанию `https://ktstech.ktalk.ru`) |
| `KTALK_DOWNLOAD_DIR` | Нет | Папка для скачанных записей (по умолчанию `./downloads`) |

### Как получить API-ключ

API-ключ выдаётся администратором домена KTalk.

## Запуск

### Автономный запуск (для отладки)

```bash
export KTALK_SESSION_TOKEN="ваш-токен"
python server.py
```

### Подключение к Cursor

Добавьте в файл `.cursor/mcp.json` (в корне проекта или в домашней директории):

```json
{
  "mcpServers": {
    "ktalk": {
      "command": "/полный/путь/к/ktalk-mcp/.venv/bin/python",
      "args": ["/полный/путь/к/ktalk-mcp/server.py"],
      "env": {
        "KTALK_API_TOKEN": "ваш-api-ключ",
        "KTALK_BASE_URL": "https://ktstech.ktalk.ru",
        "KTALK_DOWNLOAD_DIR": "/полный/путь/к/папке/downloads"
      }
    }
  }
}
```

### Подключение к Claude Desktop

Добавьте в `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ktalk": {
      "command": "/полный/путь/к/ktalk-mcp/.venv/bin/python",
      "args": ["/полный/путь/к/ktalk-mcp/server.py"],
      "env": {
        "KTALK_API_TOKEN": "ваш-api-ключ"
      }
    }
  }
}
```

## Использование

После подключения сервера к Cursor или Claude Desktop, инструменты будут доступны в чате:

**Получить транскрипцию:**
> Получи транскрипцию записи Y3ljMA8KGS72A68L0jp0

**Скачать запись:**
> Скачай запись Y3ljMA8KGS72A68L0jp0 в качестве original

**С указанием другого домена:**
> Получи транскрипцию записи r9R9Un2Q3nWNtJ4t6124 с базового URL https://stranadev.ktalk.ru

## API-эндпоинты

Сервер использует следующие эндпоинты KTalk Public API:

- `GET /api/Recordings/{recordingKey}` — информация о записи
- `GET /api/recordings/{recordingKey}/transcript` — транскрипция записи
- `GET /api/Recordings/{recordingKey}/file/{qualityName}` — файл записи

Авторизация: заголовок `X-Api-Key`.
