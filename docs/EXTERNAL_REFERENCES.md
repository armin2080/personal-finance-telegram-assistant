# External technical references

These are implementation references, not endorsements of any external service for processing financial data. Re-check compatibility and terms before adding dependencies or data flows.

- [Telegram Bot API](https://core.telegram.org/bots/api) — Bot API, `getUpdates` long polling, webhook mutual exclusion, file handling, HTTPS.
- [Telegram Bots FAQ](https://core.telegram.org/bots/faq) — update delivery and webhook details.
- [Telegram Serverless](https://blogfork.telegram.org/bots/serverless) — Telegram-hosted backend uses JavaScript ES modules in a V8 isolate; useful if a future ADR proposes a JS port.
- [python-telegram-bot documentation](https://docs.python-telegram-bot.org/en/stable/) — selected Python Bot API wrapper. The scaffold currently requests the 22.8 release line.
- [Raspberry Pi Zero documentation](https://www.raspberrypi.com/documentation/computers/zero.html) — board specifications; Zero 2 W has 512 MB RAM, so the app must remain lightweight.
- [Python version status](https://devguide.python.org/versions/) — check supported Python release branches before selecting a production interpreter.

## Why not Telegram Serverless for this implementation?

Telegram Serverless is a viable platform, but its bot backend is JavaScript and its managed SQLite-like database is hosted by Telegram. The owner asked to retain Python and has a local Raspberry Pi. The project therefore chooses Python on the Pi. Do not treat the platform comparison as permanent; revisit only through an ADR if the owner changes the hosting or language preference.
