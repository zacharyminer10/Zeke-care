# EZAide: instructions for Claude

EZAide is a care checklist web app for families and caregivers looking after someone at home (meds, feeds, cleaning, supplies, who did what and when). It is built **iPad first** (landscape ~1080×810, portrait ~810×1080); phones second.

## Who you're working with

- The owner is **Zach**. He is not a developer. Act as his software engineer **and** product owner: be critical, point out problems and trade-offs, and **explain technical things step by step in plain language**.
- Keep replies short. Lead with what changed and what he needs to do. Show screenshots of UI changes (before/after) when you can.
- If a request is ambiguous and expensive to redo, ask one short question first. Otherwise build it and say which reading you took.

## Rule: no secrets or personal details, anywhere (both repos are public)

Both `zeke-care` and `ezaide` are **public**: every file, every old version and every commit message can be read by anyone, including bots that scrape GitHub for keys. So, in files, commit messages, PRs, issues and comments, **never** put:

- Keys, tokens, passwords or session cookies of any kind: Claude/Anthropic (`sk-ant-…`, `sessionKey`), GitHub, Google, Apple, Cloudflare, AWS, Stripe, Slack, OpenAI, private keys, `.env` / credential files.
- Zach's personal details: his own email address (use `Zach <zacharyminer10@users.noreply.github.com>` for commits), phone numbers, home address, family members' details, or anything about his son's health beyond what is already public.
- Real data from the app: backups, logs, screenshots of the real board, real names or codes of the people using it.

The only email allowed in the code is the public support address `ezaide.app@gmail.com`. Test data uses made-up names and 555-01xx numbers.

**Enforced by `tools/checksecrets.py`** (shows only the first few characters of anything it finds):
- At the start of every session run `git config core.hooksPath .githooks`. The pre-commit and commit-msg hooks then block any commit whose files or message contain one of these.
- `tools/build.py` refuses a build that contains one; `tools/release.py` re-checks this repo, the app-store branch and the tester site before each push.
- Before pushing anything to the ezaide repo by hand: `python3 tools/checksecrets.py --repo ../ezaide`.
- `python3 tools/checksecrets.py --history` checks every version ever committed; `python3 tests/secrets_selftest.py` proves the checker still catches each kind.
- If something does get pushed: tell Zach at once. The key must be **revoked/rotated** (deleting the file isn't enough; it stays in the history and copies).
- Never weaken or bypass the checker (`--no-verify`, editing the allowlist) to get a commit through; remove the secret instead.

## One codebase, two versions

There is **one** `index.html` / `sw.js`. Built from it:

| Version | Storage key / backup id / SW cache | Lives on | Served at |
| --- | --- | --- | --- |
| Family (Zach's own iPad) | `zeke-care-board.v1` / `zeke-care-board` / `zeke-care-` | `main` (the source files themselves) | GitHub Pages: https://zacharyminer10.github.io/Zeke-care/ |
| App Store (EZAide: disclaimer, alerts prompt, 7-day trial label, About & disclaimer, generic examples; prepared for a future Capacitor wrapper, no native project yet) | `ezaide.v1` / `ezaide` (also accepts `zeke-care-board` backups) / `ezaide-` | `app-store` branch, **generated output only** | Tester site https://ezaide.app/app/ (copied into the `zacharyminer10/ezaide` repo) |

- **The edition block** at the top of the `<script>` in `index.html` (`var ED={id:'family',store:false,...}` between `/* ==== EDITION ==== */` and `/* ==== END EDITION ==== */`) holds everything that differs: storage key, backup id and file name, and the wording that differs ("He’s sleeping" vs "Sleeping", the 911 alert, "with his care", tour/guide examples). The App Store values are in `store/edition.js`.
- **App Store-only features** live in `index.html` and are switched on by `ED.store`: pop-ups `dc` (disclaimer) and `na` (alerts prompt), the trial label `#trl`, the About & disclaimer button/sheet (Privacy policy / Help and support / Email us links), the sign-up note under the code box, the "A quick note" tour step, the first-run order (shifts → disclaimer → recovery key → first task, no tour), `dc`/`na` in `KEEP`, the native bridge (`NAT`, `EZStore`, `storeHooks()`). Their markup is added by `storeDom()`; their CSS only matches App Store elements or `[data-ed="store"]`. With `store:false` none of it runs or appears.
- When adding something App Store-only: gate it with `if(ED.store)`; wording that differs goes in **both** edition blocks. Never write a storage key, backup id or cache name anywhere else.
- `tools/build.py` swaps the edition block for `store/edition.js` and renames the SW cache, writing `dist/family/` and `dist/store/` (with `privacy.html` from `store/`). It **refuses** if the family build isn't `zeke-care-board.v1` / `zeke-care-board` / `zeke-care-`, if the App Store build isn't the `ezaide` equivalents, or if the App Store build contains "Zeke", "He’s" or "Care Board"; it checks the text and then reads the real values in a browser.
- **Never edit, merge into or cherry-pick on `app-store`.** `tools/release.py` replaces its files with the build each release. Never merge `app-store` into `main`.
- Changing main's storage key, backup id or cache name makes the family iPad look empty.

## Files

- `index.html`: the whole app (HTML + CSS + ES5 JavaScript) in one large file with long lines. It is the family version as-is.
- `sw.js`: service worker. Bumping `VERSION` is what makes installed iPads see an update.
- `manifest.webmanifest`, `icon-180.png`, `icon-192.png`, `icon-512.png` (shared by both versions).
- `store/edition.js` (App Store edition block), `store/privacy.html` (App Store privacy policy; the live copy is `privacy.html` in the ezaide repo).
- `tools/build.py`, `tools/release.py` (below). `dist/` is build output and is not committed.
- `tests/regression.py`: Playwright + Chromium regression suite; runs on either build (`--html`). The `ED` tests check each version's key, App Store pieces and first-run order.
- `tests/stylecheck/`: proves a change leaves the look unchanged (see its README).
- `tools/checksecrets.py`, `.githooks/`, `tests/secrets_selftest.py`: the no-secrets rule (above).

## How Zach likes changes to happen

1. Work on a branch, not straight on `main`.
2. Run the tests on both builds (below) and show Zach screenshots of anything visual.
3. **Only release when Zach says "release"** (or clearly says to ship/push it live). Until then nothing goes to `main`, `app-store`, or the tester site.
4. Urgent bug: fix it, then ask whether to release it right away as a point release (e.g. 1.19.1).

## Release

Only when Zach says "release". The session needs **both repos**: `zacharyminer10/zeke-care` and `zacharyminer10/ezaide` (checked out next to each other).

```
python3 tools/release.py x.y --notes "short list of changes"
```

It does the whole checklist and stops at the first problem: bump `VER` (index.html) and `VERSION` (sw.js) → build both versions → regression tests on both, with upgrade checks from what is live on `main` and `app-store` → commit as Zach → push `main` → wait for the Pages deploy → build the App Store version from `origin/main` → test it → replace the `app-store` branch's files with the build (one commit on top) → copy it into `app/` of the ezaide repo with `<meta name="robots" content="noindex">` right after `<head>` → push → wait for that deploy.

- `--family-only` / `--store-only` split it (e.g. ship the family version, wait for Zach to confirm his iPad, then ship the App Store version). `--dry-run` does everything except commit/push.
- Commits are made as Zach (`Zach <zacharyminer10@users.noreply.github.com>`). The ezaide repo serves https://ezaide.app; its Cloudflare DNS records must stay "DNS only".
- Afterwards tell Zach: on the iPad, ⚙ → **Check for updates** → **Update now**. Testers get it the same way.
- Urgent bug: fix it, then ask whether to release it right away as a point release (e.g. 1.19.1).

## Running the tests

- `python3 tools/build.py`, then `python3 tests/regression.py --html dist/family/index.html` and `--html dist/store/index.html`. Add `--prev OLD.html` to check that data from an older version upgrades cleanly (family against `git show origin/main:index.html`, App Store against `git show origin/app-store:index.html`). Without `--html` it tests `./index.html` against the last commit.
- Needs Python Playwright with Chromium (`pip install playwright` then `python3 -m playwright install chromium`; a preinstalled `/opt/pw-browsers/chromium` is used if present). If the browser download is blocked by the environment's network settings, say so plainly and tell Zach what to change, rather than skipping the tests.
- Some tests fake the clock; tests that add a task to one shift only should put it in every shift (or fix the clock), or they fail depending on the time of day.
- Look changes: `tests/stylecheck/snap.py` (see its README) on both builds.

## Code gotchas learned the hard way

- When patching `index.html` with scripts, assert each search string occurs **exactly once** before replacing, and never delete a span "from A to B" without checking what's in between (this once deleted the supply-orders code).
- After big edits, run a JS syntax check (e.g. `new Function(scriptText)` in Node on the `<script>` contents) and compare the list of function names before/after.
- The board's "day" starts at the reset time (`S.resetAt`), not midnight: use `bizDay()`, `offMin()`, `slotDiff()`. Exceptions: the Log's dates and Typical day use calendar days.
- Today's shift times can be overridden for the day (`S.shOv`, `curPeriods()`); future days use `S.periods`.
- Use the color tokens and classes (`.tag.up`, `.tag.bad`, `--bad`, `--acc`, …), never hard-coded colors, so light mode works.
- Don't reuse a component's class name as a modifier on something else (the Manage icon once inherited the Emergency button's `.sos` padding).
- The newest pop-up is always on top; pop-ups that must not close on an outside tap are in `KEEP`.
- New tasks being added live in `DRAFT` (not `S.tasks`) until **Add task**; `T(id)` finds both. Use `T(id)` for task lookups, not `S.tasks.filter(...)`.
- Anything in `S` is saved unless its key is in `TRANSIENT` (`snap()`).
- CSS `text-transform:uppercase` text comes back uppercase from Playwright `inner_text`; compare case-insensitively.

## Product notes

- Roles: Owner / Manager (with permissions) / Caregiver. Caregivers can only add one-time tasks.
- The App Store version is not a medical device; keep the disclaimer wording intact.
- Zach's product decisions, roadmap and pricing live in his claude.ai Project ("Zeke App"), not in this repo. If a change touches product direction, ask him.
