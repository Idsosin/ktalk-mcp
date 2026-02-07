# KTalk MCP Server

MCP server for working with [KTalk](https://ktalk.ru) meeting recordings and transcripts.

## Tools

| Tool | Description |
|---|---|
| `get_recording_info` | Get recording metadata (title, participants, available qualities) |
| `get_transcript` | Download transcript as a `.txt` file with timestamps and speaker names |
| `download_recording` | Download meeting recording video file |

## Installation

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Configuration

The server is configured via environment variables:

| Variable | Required | Description |
|---|---|---|
| `KTALK_API_TOKEN` | Yes | API key for authorization (sent as `X-Api-Key` header) |
| `KTALK_BASE_URL` | No | KTalk base URL (default: `https://ktstech.ktalk.ru`) |
| `KTALK_DOWNLOAD_DIR` | No | Directory for downloaded files (default: `./downloads`) |

### How to get an API key

The API key is issued by the KTalk domain administrator.

## Running

### Standalone (for debugging)

```bash
export KTALK_API_TOKEN="your-api-key"
python server.py
```

### Cursor integration

Add to `.cursor/mcp.json` (in project root or home directory):

```json
{
  "mcpServers": {
    "ktalk": {
      "command": "/full/path/to/ktalk-mcp/.venv/bin/python",
      "args": ["/full/path/to/ktalk-mcp/server.py"],
      "env": {
        "KTALK_API_TOKEN": "your-api-key",
        "KTALK_BASE_URL": "https://ktstech.ktalk.ru",
        "KTALK_DOWNLOAD_DIR": "/full/path/to/downloads"
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
        "KTALK_API_TOKEN": "your-api-key"
      }
    }
  }
}
```

## Usage

After connecting the server to Cursor or Claude Desktop, the tools are available in chat:

**Get transcript:**
> Get the transcript for recording Y3ljMA8KGS72A68L0jp0

**Download recording:**
> Download recording Y3ljMA8KGS72A68L0jp0 in 900p quality

**Get recording info:**
> Show info for recording Y3ljMA8KGS72A68L0jp0

## API endpoints

The server uses the following KTalk Public API endpoints:

- `GET /api/Recordings/{recordingKey}` — recording metadata
- `GET /api/recordings/{recordingKey}/transcript` — recording transcript
- `GET /api/Recordings/{recordingKey}/file/{qualityName}` — recording file

Authorization: `X-Api-Key` header.
