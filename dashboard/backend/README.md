# Dashboard Backend (first slice)

Local, authenticated HTTP API for the dashboard. It stores dashboard settings
and reports bot state. Weather and image generation run through keyless public
APIs; **the Discord adapter is offline**, so emoji copy and server clone are
validated but report `bot_offline` instead of applying a Discord action.

A successful save therefore returns:

```json
{"saved": true, "applied": false, "reason": "bot_offline", "data": {}}
```

The `data` field contains the saved object. The dashboard must not show a
mutation as applied when `applied` is `false`.

## Setup

Requires Python 3.11+.

1. Copy the example config (do not commit the real one):

   ```powershell
   Copy-Item dashboard/backend/config.example.json dashboard/backend/config.json
   ```

2. Open `dashboard/backend/config.json` and fill in `bot_token`,
   `application_id`, and `guild_id` manually. Leave them empty if you only
   want to exercise the offline dashboard.

3. Install the Python dependencies:

   ```powershell
   python -m pip install -r dashboard/backend/requirements.txt
   ```

4. Run the API from the repository root:

   ```powershell
   python dashboard/backend/main.py
   ```

5. The console prints the pairing code:

   ```text
   [dashboard] Pairing code: 123456
   ```

   Enter that code in the dashboard. The bot token is never sent to the
   browser; the browser only receives the session cookie and CSRF token.

The API listens on `127.0.0.1:8765` by default. The Vite frontend on port
`4000` calls it directly; the backend allows only the configured local
dashboard origins and sends credentials only to those origins.

## Security notes

- The bot token stays in `dashboard/backend/config.json` and is never returned
  by an endpoint or written to logs.
- `config.json` and `runtime_state.json` must not be committed. The real
  config contains credentials; the runtime state is local user data. Add both
  to your local/global gitignore if they are not already ignored.
- Pairing codes are six digits, generated with `secrets`, and rate-limited to
  five attempts per 60 seconds per remote IP.
- Sessions are in memory, expire after 8 hours, and use an `HttpOnly`,
  `SameSite=Strict` cookie.
- Mutations require the `X-CSRF-Token` header returned by pairing or
  `GET /api/v1/session`.
- `Host` and `Origin` headers are checked against explicit local allowlists.
- Adding/removing voice tokens updates the repository-root `config.json`
  atomically (temporary file + `os.replace`) while preserving every other key.
  Tokens are validated against Discord before being stored and are never
  returned by the API or written to logs.

## API

| Method | Path | Notes |
| --- | --- | --- |
| `POST` | `/api/v1/pair` | Body `{"code":"123456"}`; sets session cookie |
| `GET` | `/api/v1/session` | Returns `authenticated` and, when valid, `csrf_token` |
| `POST` | `/api/v1/logout` | Requires session + `X-CSRF-Token`; returns `204` |
| `GET` | `/api/v1/status` | Bot/API status and warnings |
| `GET` | `/api/v1/capabilities` | Feature capability list |
| `GET`/`PUT` | `/api/v1/automation` | Auto-Mess settings |
| `GET`/`PUT` | `/api/v1/afk` | AFK settings |
| `GET`/`PUT` | `/api/v1/reactions` | Auto-Reaction settings |
| `POST` | `/api/v1/utility/weather` | Body `{"location":"Hanoi"}`; keyless Open-Meteo |
| `POST` | `/api/v1/utility/image` | Body `{"prompt":"cat in space"}`; returns a Pollinations URL |
| `POST` | `/api/v1/utility/emoji-copy` | Body `{"source_id":"…","target_id":"…","emoji_ids":["…"]}`; queues to the bot |
| `GET` | `/api/v1/utility/emoji-copy/status` | Query `request_id`; returns queued/running/success/error |
| `POST` | `/api/v1/utility/clone` | Body `{"source_id":"…","target_id":"…","confirm":true,"options":{"info":true,"structure":true,"emojis":false}}` |
| `GET` | `/api/v1/utility/clone/status` | Query `request_id`; returns queued/running/success/error |
| `GET` | `/api/v1/voice/tokens` | Voice token liveness + bot voice state |
| `POST` | `/api/v1/voice/tokens` | Body `{"token":"…"}`; validates with Discord, appends to root `config.json` |
| `DELETE` | `/api/v1/voice/tokens` | Body `{"token_index":0}`; removes that entry from root `config.json` |
| `GET` | `/api/v1/voice/soundboard` | Query `guild_id`, `token_index`; lists server sounds |
| `GET` | `/api/v1/voice/soundboard/defaults` | Query `token_index`; lists Discord default sounds |
| `POST` | `/api/v1/voice/soundboard/play` | Body `{"token_index":0,"channel_id":"…","sound_id":"…"}` |
| `POST` | `/api/v1/voice/join` | Body `{"token_index":0,"channels":["…"]}`; queues a bot command |
| `POST` | `/api/v1/voice/leave` | Body `{"token_index":0,"channel_id":"…"}`; queues a bot command |

All endpoints except pairing and session checks require a valid session.
Mutating requests and logout require the CSRF header.

Voice join/leave commands are written to `voice_commands.json` and consumed by
the running bot's Voice cog. The bot writes live gateway/channel state to
`voice_state.json`; the dashboard merges that state into `/voice/tokens`.
Tokens that return 401 are removed from the root `config.json` automatically
and a voice reload is queued.

Dashboard clone requests are written to `clone_commands.json` and consumed by
the running bot's Utility cog. The bot writes progress/results to
`clone_results.json`.

Dashboard emoji-copy requests are written to `emoji_commands.json` and consumed
by the same Utility cog. Results are written to `emoji_results.json`.

## State

State is stored in `dashboard/backend/runtime_state.json` using an atomic
temporary-file + `os.replace` write. Missing files and missing keys fall back
to defaults. Corrupt JSON is logged as a warning and treated as defaults
instead of crashing the API.

## Tests

From the repository root:

```powershell
python -m pytest dashboard/backend/tests -q
```

The tests use `aiohttp.test_utils.TestClient`/`TestServer`, a temporary state
file, and the injected pairing code `123456`.

## Extending to a live bot

`bot_adapter.py` defines the `BotAdapter` interface and the current
`OfflineBotAdapter`. A future official Discord bot adapter should implement
`get_status`, `apply_automation`, `apply_afk`, `apply_reactions`, and
`run_utility(action, data)`, then be passed to `create_app(adapter=...)`.
The HTTP handlers do not import `discord` and do not need to change.
