# sf-duoheyi (SF Multi-in-One)

A working all-in-one SF Express points script for the QingLong panel, merged and deduplicated from four community **plaintext** scripts: daily points tasks, dual-platform sign-in, Honey Harvest, Member Day, and festival events — all in a single file.

## Why this one

- **100% plaintext, auditable line by line**: no encrypted payloads, no obfuscated packaging, no binaries downloaded at runtime. Every line of code is laid out for you to read — read the code before you run it; that is the bare minimum for this kind of script.
- **Zero backend servers, credentials never leave your machine**: signatures (MD5) are computed locally; your CK is sent only to SF Express's official APIs. Nothing is relayed through any author's server, and there is no need to use a third-party "scan-to-get-CK" website — that is handing your account to a stranger.
- **Connects to exactly one official domain**: every network request in the file goes to `mcs-mimp-web.sf-express.com`. Don't take our word for it — verify it yourself: `grep -oE 'https?://[^" ]+' sf-duoheyi.py | sort -u` returns exactly one domain.
- **Full event coverage**: the union of all four scripts' APIs (25 endpoints in total); for each category only the newest implementation is kept, so you no longer need three or four SF scripts running at once and fighting each other.
- **Independent module switches + date gating**: Member Day runs automatically only on the 26th–28th of each month, festival events start and stop with their event windows, and expired events are off by default instead of spamming your logs with errors every day.
- **Multi-account + proxy system**: accounts run in parallel with per-account exception isolation; each account can have its own proxy, and a dynamic proxy extraction API is supported with automatic IP rotation and retry on errors.
- **CK expiry is detected**: when your login state expires, the script clearly reports "CK expired" instead of failing silently and leaving you thinking the tasks ran.

## Features

| Module | Contents | Default |
|---|---|---|
| Daily sign-in | App + Mini Program dual-platform sign-in, pending App gift packs | On |
| Daily points tasks | The full set of daily tasks (browsing / interaction / privilege benefits, etc.), each isolated on failure, points claimed together at the end | On |
| Honey Harvest | Honey tasks, honey collection, adventure game, container expansion, coupon claiming (`SF_HONEY`) | On (auto-skipped when the event has not started) |
| Member Day | On the 26th–28th of each month: Member Day tasks, lottery, red-packet merging and withdrawal, hourly red packets (`SF_MEMBER_DAY`) | On (auto-skipped outside the window) |
| Festival event framework | World Cup module (expired in July 2026, `SF_WORLD_CUP`) | Off |

## Usage

1. Create a new script in the QingLong panel and put `sf-duoheyi.py` in it, or subscribe to this repository.
2. Environment variable `sfsyUrl` (required): your account CK string or login URL. Separate multiple accounts with `&`, an English comma, a Chinese comma, or newlines; to route one account through a proxy, append `#proxy` after its CK.
   - How to get your CK: use a packet-capture tool on requests from the SF Express App / Mini Program (e.g. the "My Points" pages) and concatenate `sessionId`, `_login_mobile_`, and `_login_user_id_` from the Cookie. **Capture packets manually — never use any third-party "scan-to-get-CK" website.**
3. Optional variables: `SF_PROXY_API_URL` (dynamic proxy extraction URL), `SF_PROXY_TYPE` (http/socks5, default socks5), `SFSY_PUSH` (push switch), etc. — see the header comment of the script for details.
4. Suggested schedule: `11 6-18/3 * * *`, or twice a day at 00:00 and 12:00.

## Sources & credits

This script is merged from the following open-source plaintext scripts (per-module source comments are kept in the code so everything stays traceable):

- [ShuiLiZe/QingLong](https://github.com/ShuiLiZe/QingLong) "顺丰速运.py" — the core framework (daily tasks, sign-in, Member Day, proxy system)
- [Qcby/QcbyScript](https://github.com/Qcby/QcbyScript) "顺丰速运.py" — multi-separator account parsing, exception fallback
- [smallfawn/QLScriptPublic](https://github.com/smallfawn/QLScriptPublic) "daily/sfsy.py" — same-lineage daily-task implementation, kept as reference
- [agluo/ql-script-hub](https://github.com/agluo/ql-script-hub) "SFSU_checkin.py" — Honey Harvest, hourly red packets

Thanks to the original authors for their open-source work. This repository only merges, organizes, and maintains: it tracks updates from the sources and new SF Express events, and every release passes a syntax check, a domain audit, and a live test on a real account before being published.

## Disclaimer

This project is for study, exchange, and automating daily tasks on your own personal account only, and is not affiliated with SF Express. Using automation scripts may violate platform rules; you bear the account risk yourself. Do not use it for commercial purposes or bulk profit.
