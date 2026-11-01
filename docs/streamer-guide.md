# THOUGHTQUAKE streamer guide

M3–M4 connect real Twitch chat to the local thought injection engine. The **LIVE**
badge describes chat input. **TINY MODEL / CI** separately identifies fixture model
output; it is not a claim about real-model quality.

## Set up your Public app

1. Open the [Twitch developer console](https://dev.twitch.tv/console/apps) and register
   an application. Choose **Public** as the client type. If registration asks for a
   redirect URI, use `http://localhost`; the Device Code flow does not run a callback server.
2. Copy the Client ID. No client secret is used. In the terminal where you will run
   THOUGHTQUAKE, set it:

   ```sh
   export THOUGHTQUAKE_TWITCH_CLIENT_ID='your-public-client-id'
   ```

   In PowerShell: `$env:THOUGHTQUAKE_TWITCH_CLIENT_ID = 'your-public-client-id'`.
3. Install and log in:

   ```sh
   pip install -e '.[dev]'
   thoughtquake auth
   ```

   Open the displayed verification URI, enter the displayed code if requested,
   and sign in with the account that will read chat and post bot announcements.
   Approve `user:read:chat user:write:chat`. A separate bot account is useful because
   messages from the authenticated account are ignored to prevent feedback loops.
4. Credentials are saved in `~/.config/thoughtquake/token.json` with mode 0600.
   Refresh updates replace the file atomically. Do not share this file or commit it.
   If authorization is revoked or expires, run `thoughtquake auth` again.

## Start the local server and OBS

```sh
thoughtquake run --channel YOUR_CHANNEL --record work/live.jsonl
```

The server binds to `127.0.0.1:8080`. Add an OBS **Browser Source** with URL
`http://127.0.0.1:8080/`, width **1920**, height **1080**. For a transparent
background, use `http://127.0.0.1:8080/?bg=transparent`. Keep OBS and THOUGHTQUAKE
on the same computer. `--port`, `--no-browser`, and local broadcaster mode controls
work as in demo mode. Open `/control`, paste the fresh per-run token printed in
the console, and choose a mode or toggle immune. Press **I** there for the immune
hotkey; keep the token and control page out of the OBS browser source.

Without a real-model library, live mode uses the mock and displays **TINY MODEL / CI**.
This is suitable for testing the chat connection and presentation. For a real run,
install `.[model]`, build the calibrated library, and pass its path:

```sh
thoughtquake build-library
thoughtquake run --channel YOUR_CHANNEL --library library/qwen2.5-0.5b-instruct.npz
```

Real model weights are loaded locally; they are not available in CI. Neither the
mock nor Tiny output supplies evidence for quality or speed claims.

Simulation is **off** in live mode. `--sim` explicitly adds the seeded crowd;
its users are named `sim_*`, and a separate **SIMULATED ×40** chip accompanies
**LIVE**. Keep the chip visible. Recording stores chat-derived pushes and output
frames, not OAuth credentials. It includes Twitch display names and user IDs;
review a recording before sharing it.

## Test with a friend's account

Have a friend type `sea`, `STAR`, and `!push jazz` in your channel. Check that their
name appears in the ticker and Mind Share changes. Matching is case-insensitive
and uses whole words. If a message matches multiple concepts, its earliest match
wins. Ordinary messages that match no concept have no effect. Messages from the
bot account and duplicate Twitch message IDs have no effect.

Disconnect the network briefly: the Subject should keep generating and the
**RECONNECTING** chip should appear. A normal reconnect creates a new subscription;
Twitch's directed socket transfer preserves the existing subscription. A revoked
subscription displays **AUTH REQUIRED** and stops chat IO until you restart after
a new login. Lost messages during an unplanned disconnect cannot be recovered.

Try a short recording with both `thoughtquake replay work/live.jsonl --frames`
and `--engine`. Frame replay needs no model and changes the source badge to
**REPLAY**. Engine replay requires the original library and model configuration.

## What the bot may post

The authenticated account may post round-start, round-end, and Telepathy reveal
notices. It posts at round boundaries only, with no per-token or periodic leader
announcements. All messages are trimmed to **200 characters**, and the sender allows
at most **one announcement per five seconds**. Extra announcements are dropped
rather than queued indefinitely. Send failures are logged and do not stop play.
Broadcasters or moderators may use `!immune on|off`. Twitch user IDs and
`badges[].set_id` (broadcaster/moderator) authorize this command; this badge
interpretation also needs the live check below. There are no chat mode-switching
commands and no command that relays arbitrary viewer text as the bot. Telepathy guesses use `!guess <word>` during its 30-second guessing window.
The first correct alias earns a point; the reveal shows the winner and scoreboard.

## Public-docs contract and required live check

The following endpoints and field names were implemented from Twitch's public
docs, checked on 1 November 2026. Fixtures use synthetic IDs, not recorded live
responses. Every row still needs the friend's-account live check above.

| Public docs | Implemented wire contract to check live |
| --- | --- |
| [Device Code flow](https://dev.twitch.tv/docs/authentication/getting-tokens-oauth/#device-code-grant-flow) | `POST /oauth2/device`: `client_id`, `scopes`; response `device_code`, `user_code`, `verification_uri`, `interval`, `expires_in`. `POST /oauth2/token`: device grant or `refresh_token`, no client secret. Check pending/denial and rotated-token behavior. |
| [Validation](https://dev.twitch.tv/docs/authentication/validate-tokens/) | `GET /oauth2/validate` with `Authorization: OAuth …`; check `client_id`, `user_id`, `login`, `scopes`, `expires_in`. Startup and hourly validation, proactive refresh at five minutes remaining, and one retry after a Helix 401. |
| [EventSub sockets](https://dev.twitch.tv/docs/eventsub/handling-websocket-events/) | `wss://eventsub.wss.twitch.tv/ws?keepalive_timeout_seconds=30`; `metadata.message_type/message_id`, `payload.session.id/keepalive_timeout_seconds/reconnect_url`, revocation subscription status. Check welcome deadline, heartbeat loss, and directed handoff. |
| [Chat subscription](https://dev.twitch.tv/docs/eventsub/eventsub-subscription-types/#channelchatmessage) | `POST /helix/eventsub/subscriptions`: `type=channel.chat.message`, `version=1`, condition `broadcaster_user_id/user_id`, transport `method/session_id`. Chat payload uses `chatter_user_id/chatter_user_name/message_id/message.text`. |
| [Send Chat Message](https://dev.twitch.tv/docs/api/reference/#send-chat-message) and [Get Users](https://dev.twitch.tv/docs/api/reference/#get-users) | `POST /helix/chat/messages`: `broadcaster_id`, `sender_id`, `message`; inspect `data[].is_sent/drop_reason`. `GET /helix/users?login=…` resolves the channel ID. Check channel access and actual delivery. |

The endpoints use `https://id.twitch.tv` for OAuth and `https://api.twitch.tv`
for Helix. Helix requests use `Client-Id` and `Authorization: Bearer …`.
Public-client Device Code refresh is described on the Device Code page; the
separate generic refresh guide describes other client types too. The 200-character
limit is THOUGHTQUAKE's stricter limit. No live Twitch, OBS, or real-model end-to-end
test was performed during implementation; local HTTP/WebSocket fakes test the
protocol and retry paths without external network access.
