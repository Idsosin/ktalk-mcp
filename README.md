# KTalk MCP Server

MCP-сервер для работы с записями и транскрипциями [KTalk](https://ktalk.ru) — системой для проведения встреч.

## Возможности

| Инструмент | Описание |
|---|---|
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
| `KTALK_API_TOKEN` | Да* | API-токен для авторизации (Bearer) |
| `KTALK_SESSION_TOKEN` | Да* | Токен сессии (альтернатива API-токену) |
| `KTALK_BASE_URL` | Нет | Базовый URL KTalk (по умолчанию `https://ktstech.ktalk.ru`) |
| `KTALK_DOWNLOAD_DIR` | Нет | Папка для скачанных записей (по умолчанию `./downloads`) |

\* Необходимо задать хотя бы один из токенов: `KTALK_API_TOKEN` или `KTALK_SESSION_TOKEN`.

### Как получить Session Token

1. Откройте KTalk в браузере (например `https://ktstech.ktalk.ru`)
2. Войдите в систему
3. Откройте DevTools (F12) → Application → Cookies
4. Скопируйте значение cookie `sessionToken`

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
      "command": "python",
      "args": ["/полный/путь/к/ktalk-mcp/server.py"],
      "env": {
        "KTALK_SESSION_TOKEN": "ваш-токен",
        "KTALK_BASE_URL": "https://ktstech.ktalk.ru",
        "KTALK_DOWNLOAD_DIR": "/полный/путь/к/папке/downloads"
      }
    }
  }
}
```

Или с использованием виртуального окружения:

```json
{
  "mcpServers": {
    "ktalk": {
      "command": "/полный/путь/к/ktalk-mcp/.venv/bin/python",
      "args": ["/полный/путь/к/ktalk-mcp/server.py"],
      "env": {
        "KTALK_SESSION_TOKEN": "ваш-токен"
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
      "command": "python",
      "args": ["/полный/путь/к/ktalk-mcp/server.py"],
      "env": {
        "KTALK_SESSION_TOKEN": "ваш-токен"
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

- `GET /api/recordings/{recordingKey}/transcript` — транскрипция записи
- `GET /api/Recordings/{recordingKey}/file/{qualityName}` — файл записи
