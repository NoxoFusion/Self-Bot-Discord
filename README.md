<div align="center">

# NoxoFusion Selfbot

**A fully asynchronous Discord self-bot — 31 owner-only commands, a multi-token voice pool, and a live local web dashboard, bridged by an atomic file-based command spool.**

![Version](https://img.shields.io/badge/version-0.1.0-blue)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![discord.py-self](https://img.shields.io/badge/discord.py--self-2.1.0-5865F2)
![Tests](https://img.shields.io/badge/tests-523%20pytest%20%2F%20297%20vitest-brightgreen)
![License](https://img.shields.io/badge/license-MIT-green)

[Discord](https://discord.gg/rxw8Hwk3qA) · [TikTok](https://www.tiktok.com/@noxofusion) · [YouTube](https://www.youtube.com/@noxofusion2010)

</div>

---

## 🎬 Demo

<!-- Replace assets/demo.gif with a real screen recording before publishing. -->
![Demo](assets/demo.gif)

*Illustrative terminal preview — the message formats match the real command output; IDs, latencies and counts are examples.*

```text
$ python main.py
[INFO] Token length: 72 characters
[INFO] Loaded 31 commands
[INFO] Cogs loaded: 8 | Failed: 0
[dashboard] Pairing code: 483921

🤖 SELFBOT MENU | Prefix: .
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 COGS:
😴 afk           ⚔️ moderation
💬 automess      🎭 presence
ℹ️ general       ⚡ reactions
🎨 utility       🎧 voice
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚡ COMMANDS:
  📖 .help <cog>     Detailed help for a cog
  🔄 .reload <name>  Reload config/cog by file name
  🏓 .ping           Check latency
  ✏️ .prefix <new>   Change prefix
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

.ping
🏓 Pong! 42ms
.play 0 lofi hip hop radio
✅ Queued "Lofi Hip Hop Radio" (position 1)
.soundboard 42 0
✅ Sound sent!
.auto_mess on 123456789 time 60
✅ **Auto Mess:** ON | <#123456789> | mode `time` | value `60`
```

`.help <cog>` answers with a rendered "moondark" card (Pillow), not a wall of text.

---

## ⚠️ Disclaimer & Security Warning

> **Using a self-bot violates Discord's Terms of Service.** Accounts running this software can be
> **permanently banned**. This project is for educational purposes only. The author
> (**noxofusion**) is **not responsible** for any account termination, data loss, or damage
> caused by using this tool. Use it at your own risk.

- **Never share your token, cookies, or password** — with anyone, in any form.
- `config.json` holds your account token and is **ignored by git** (`.gitignore` covers
  `config.json`, `accounts.json`, `data/`, `*.bak`). **Check `.gitignore` before your first push** —
  a leaked token means a stolen account.
- All dashboard endpoints are localhost-only, session-paired, and CSRF-protected. Keep it that way.

---

## ✨ Purpose & Features

A single-owner automation suite: the bot process owns the Discord gateway; the dashboard
(aiohttp backend + React web app) never touches your token — it enqueues commands through an
**atomic file-based spool** and mirrors live state back over WebSocket.

**31 commands across 8 cogs — every single one owner-only** (global check, no exceptions):

| Area | What it does |
| --- | --- |
| 🎧 **Voice & Music** | Multi-token voice pool — the main account plus secondary tokens, each joinable to **2 channels simultaneously**. YouTube playback with queue, loop, replay, bass/effects, volume; server soundboard via REST. |
| 🎭 **Rich Presence** | Custom / Spotify / streaming presence for the main account, per-platform identity spoofing (iOS, Android, Xbox, VR…), YouTube art resolve, image upload to catbox (≤700 KB, sha256-cached), service presets. |
| 💬 **Automation** | Smart Auto Mess (time or message-count mode), keyword auto-responses, auto-reactions, AFK with reply mentions/DMs. |
| ⚔️ **Moderation** | ID ban/unban, channel nuke with confirm, bulk friend/DM/group cleanup — all rate-limit paced, aborting on 429 escalation to protect the token. |
| 🎨 **Utility** | Server clone (info + structure), emoji copy between servers, AI image generation, weather. |

**Built for stability, not just speed** — every claim below is enforced in code:

- **Fully asynchronous** — one event loop drives the gateway, voice bridges, broadcasters, and the spool consumer; bulk REST calls are paced with sleeps and abort thresholds.
- **Single-instance OS lock** (`msvcrt`/`fcntl`) — a second `python main.py` can never open a duplicate gateway session on the same token (Discord invalidates those).
- **Cross-process-safe config** — atomic `os.replace` writes, optimistic compare-and-retry on the shared `config.json`, crash-recovery `.bak` snapshots.
- **Identity probe before boot** — every secondary token is checked against `/users/@me` so a rotated main-account token can never be booted twice.
- **Tested** — 523 backend pytest + 297 vitest tests, green.

---

## 🚀 Quick Start

**Requirements:** Windows or Linux · Python 3.11+ · Node.js 18+ (dashboard) · FFmpeg (voice playback)

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Create config.json in the repo root
#    (placeholders — NEVER commit your real token)
```

```json
{
    "prefix": ".",
    "token": "YOUR_MAIN_ACCOUNT_TOKEN",
    "voice_token": ["YOUR_SECONDARY_VOICE_TOKEN"]
}
```

```bash
# 3. Dashboard web app (first run only)
cd dashboard/apps/web
npm install
cd ../..

# 4. Launch
python main.py              # interactive prompt launches the dashboard
python main.py --dashboard   # always launch dashboard
python main.py --no-dashboard # bot only
```

The console prints a **pairing code** (e.g. `[dashboard] Pairing code: 483921`) — enter it once in
the web UI at `http://127.0.0.1:4000`. The API backend listens on `http://127.0.0.1:8765`.

**Verify your setup:**

```bash
python -m pytest dashboard/backend/tests -q   # 523 passed
cd dashboard/apps/web && npx vitest run       # 297 passed
```

---

## 📂 Project Structure & Workflow

```text
Self-bot-discord/
├── main.py                  # entry point, global owner check, help renderer, reload
├── config.json              # prefix + tokens (gitignored)
├── cogs/                    # 8 cogs — afk, auto_mess, general, moderation,
│                            #   presence, reactions, utility, voice
├── src/                     # voice_connector, voice_audio (music engine),
│                            #   main_voice bridge, command_spool, data_store,
│                            #   dashboard_sync, single_instance, http_client
├── dashboard/
│   ├── backend/             # aiohttp API — 55 endpoints, pairing auth, CSRF
│   │   ├── voice_api/       # presence, media player, voice state, WebSocket hub
│   │   └── tests/           # 523 pytest tests
│   ├── apps/web/            # React 18 + react-router 7 dashboard (8 panels)
│   └── shared/              # design-mode test suites
```

**Workflow — Input → Processing → Output:**

```text
Input                       Processing                          Output
─────────                   ───────────                         ───────
Chat commands (.prefix…)  → cogs (owner-only check)          → Discord REST / gateway
Dashboard clicks          → aiohttp API → atomic spool files → bot consumer → Discord
Bot events                → state writers (locked, atomic)   → voice_state.json / WS → dashboard
```

---

## 🔧 Troubleshooting / FAQ

**`AttributeError: module 'discord' has no attribute 'ActivityPlatform'`**
Vanilla `discord.py` is installed instead of the self-bot fork. Fix:
`pip uninstall discord.py -y && pip install -r requirements.txt` (pins `discord.py-self==2.1.0`).

**`⚠️ Pillow not installed. Image help will be disabled.`**
Rendered help cards need Pillow: `pip install Pillow`.

**Bot prints `Stopped old bot instance(s)` on startup**
The single-instance lock found another `main.py` still holding the token's gateway session, killed
it, and waits 15 s for Discord to close the old session before logging in — this is protection,
not an error. Never run two instances on one token.

**Bulk commands stop with `⚠️ Stopped to protect the token`**
Discord's rate limit escalated mid-operation. The command aborted on purpose — wait a few minutes
and run it again. This is the pacing engine doing its job.

**Dashboard shows `401` / `Pair the dashboard first.`**
Your session expired or the pairing code rotated. Restart the backend and pair with the fresh code
printed in the console.

---

## 🌐 Connect & Support

[![Discord](https://img.shields.io/badge/Discord-join%20the%20server-5865F2?logo=discord&logoColor=white)](https://discord.gg/rxw8Hwk3qA)
[![TikTok](https://img.shields.io/badge/TikTok-@noxofusion-black?logo=tiktok&logoColor=white)](https://www.tiktok.com/@noxofusion)
[![YouTube](https://img.shields.io/badge/YouTube-@noxofusion2010-red?logo=youtube&logoColor=white)](https://www.youtube.com/@noxofusion2010)

---

## 📄 License

Released under the **MIT License** — see below.

```text
MIT License

Copyright (c) 2026 noxofusion

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
