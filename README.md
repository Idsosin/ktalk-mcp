# KTalk MCP Server

MCP server for working with [KTalk](https://ktalk.ru) meeting recordings and transcripts via [kts-ktalk-api-proxy](https://github.com/kts-studio/kts-ktalk-api-proxy) with JWT (Keycloak) authentication.

The proxy acts as a single entry point to the KTalk API: clients authenticate with a JWT token (Keycloak), while the KTalk API key is stored securely on the proxy server and never exposed to clients.

## Tools

| Tool | Description |
|---|---|
| `login` | Authenticate via Keycloak (username + password), saves token automatically |
| `list_recordings` | List recordings with optional filters (room, date range) |
| `get_recording_info` | Get recording metadata (title, participants, available qualities) |
| `get_transcript` | Download transcript as a `.txt` file with timestamps and speaker names |
| `download_recording` | Download meeting recording video file |

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration

| Variable | Required | Description |
|---|---|---|
| `KTALK_PROXY_URL` | Yes | Proxy base URL (e.g. `https://your-proxy.example.com`) |
| `KTALK_JWT_TOKEN` | No | Manual JWT override (if set, skips saved token) |
| `KTALK_DOWNLOAD_DIR` | No | Directory for downloaded files (default: `./downloads`) |

## Authentication

The server uses **Keycloak Direct Access Grant** (Resource Owner Password Credentials):

1. Call the `login` tool with your Keycloak username and password.
2. The server obtains a JWT access token + refresh token from Keycloak.
3. Tokens are saved to `~/.ktalk-mcp/token.json` and used automatically.
4. When the access token expires, it is refreshed transparently using the refresh token.

> If both tokens expire, call `login` again.

## Running

### Cursor integration

Add to `.cursor/mcp.json` (in project root or home directory):

```json
{
  "mcpServers": {
    "ktalk": {
      "command": "/full/path/to/ktalk-mcp/.venv/bin/python",
      "args": ["/full/path/to/ktalk-mcp/server.py"],
      "env": {
        "KTALK_PROXY_URL": "https://your-proxy.example.com"
      }
    }
  }
}
```

### Claude Desktop integration

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ktalk": {
      "command": "/full/path/to/ktalk-mcp/.venv/bin/python",
      "args": ["/full/path/to/ktalk-mcp/server.py"],
      "env": {
        "KTALK_PROXY_URL": "https://your-proxy.example.com"
      }
    }
  }
}
```

### Standalone (for debugging)

```bash
export KTALK_PROXY_URL="https://your-proxy.example.com"
python server.py
```

## Usage

After connecting the server, start by authenticating:

> Log in to KTalk with username i.sosin

Then use the available tools:

> Show all recordings for room mcptkdy64ohg

> Get the transcript for recording Y3ljMA8KGS72A68L0jp0

> Download recording Y3ljMA8KGS72A68L0jp0 in 900p quality

## API endpoints (via proxy)

All requests are routed through the proxy with the `/api/talk` prefix:

- `GET /api/talk/api/Domain/recordings/v2` -- list recordings
- `GET /api/talk/api/Recordings/{recordingKey}` -- recording metadata
- `GET /api/talk/api/recordings/{recordingKey}/transcript` -- recording transcript
- `GET /api/talk/api/Recordings/{recordingKey}/file/{qualityName}` -- recording file

Authorization: `Authorization: Bearer <JWT>` header. The proxy validates the JWT via Keycloak JWKS and forwards requests to the KTalk API with the server-side API key.
