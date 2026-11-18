# EZAide: instructions for Claude

EZAide is a care checklist web app for families and caregivers looking after someone at home (meds, feeds, cleaning, supplies, who did what and when). It is built **iPad first** (landscape ~1080×810, portrait ~810×1080); phones second.

## Who you're working with

- The owner is **Zach**. He is not a developer. Act as his software engineer **and** product owner: be critical, point out problems and trade-offs, and **explain technical things step by step in plain language**.
- Keep replies short. Lead with what changed and what he needs to do. Show screenshots of UI changes (before/after) when you can.
- If a request is ambiguous and expensive to redo, ask one short question first. Otherwise build it and say which reading you took.

## The two branches (never mix them up)

| Branch | What it is | Served at |
| --- | --- | --- |
| `main` | The family version used on Zach's own iPad | GitHub Pages: https://zacharyminer10.github.io/Zeke-care/ |
| `app-store` | EZAide for the App Store (prepared for a future Capacitor wrapper (no native project yet), 7-day trial label, alerts prompt, disclaimer, generic examples) | Not served by Pages; copied to the tester site (below) |

- **Never merge `app-store` into `main`.** Changes flow one way: main → app-store.
- Main must keep `KEY='zeke-care-board.v1'`, `app:'zeke-care-board'` in backups, and `CACHE = 'zeke-care-' + VERSION` in sw.js. Changing them makes the family iPad look empty.
- The App Store version keeps `KEY='ezaide.v1'`, `app:'ezaide'` (still accepting `zeke-care-board` backups in `okSnap`), `CACHE = 'ezaide-' + VERSION`.

## Files

- `index.html`: the whole app (HTML + CSS + ES5 JavaScript) in one large file with long lines.
- `sw.js`: service worker. Bumping `VERSION` is what makes installed iPads see an update.
- `manifest.webmanifest`, `icon-180.png`, `icon-192.png`, `icon-512.png`.
- `tests/regression.py`: Playwright + Chromium regression suite. Keep it **identical on both branches** (it handles the App Store-only pop-ups).

## How Zach likes changes to happen

1. Work on a branch, not straight on `main`.
2. Run the tests (below) and show Zach screenshots of anything visual.
3. **Only release when Zach says "release"** (or clearly says to ship/push it live). Until then nothing goes to `main`, `app-store`, or the tester site.
4. Urgent bug: fix it, then ask whether to release it right away as a point release (e.g. 1.19.1).

## Release checklist

1. In `index.html` set `var VER='x.y'`; in `sw.js` set `const VERSION = 'x.y'`.
2. Run `python3 tests/regression.py` (it also checks upgrading from the last committed version). Everything must PASS.
3. Commit **as Zach**: `git -c user.name="Zach" -c user.email="zacharyminer10@users.noreply.github.com" commit ...`. Push `main`. Check the Pages deploy finished: `gh api repos/zacharyminer10/zeke-care/actions/runs`.
4. Merge into `app-store`:
   - `git fetch origin +refs/heads/app-store:refs/remotes/origin/app-store` (make sure the ref is current), then `git checkout -B app-store origin/app-store && git merge --no-ff --no-commit origin/main`.
   - `sw.js` always conflicts: keep the EZAide header and `CACHE = 'ezaide-' + VERSION` with the new version.
   - `index.html`: keep the App Store pieces (storage key/app id above, trial label `#trl` under the screen title, `storeHooks()` in `render()`, About & disclaimer with its Privacy policy / Help and support / Email us links, disclaimer `dc` and alerts `na` pop-ups in `KEEP`, the "Your shifts · these hours are right" checkbox in the first-task step, generic examples) and apply main's functional change on top. **Ask Zach before resolving anything that changes the App Store version's own design.**
   - Afterwards: no conflict markers; no "Care Board", "Zeke", "He’s" in index.html (the `zeke-care-board` backup check is intentional); run `python3 tests/regression.py --prev <app-store's previous index.html>`; commit "Merge main (x.y) into app-store"; push.
5. Update the tester site: in the `zacharyminer10/ezaide` repo, copy app-store's `index.html` and `sw.js` (and `manifest.webmanifest`/icons if they changed) into `app/`. Keep the `<meta name="robots" content="noindex">` line right after `<head>`. Commit as Zach and push. That repo serves https://ezaide.app (and https://ezaide.app/app/ for testers); its Cloudflare DNS records must stay "DNS only".
6. Tell Zach: on the iPad, ⚙ → **Check for updates** → **Update now**. Testers get it the same way.

A release session needs **both repos** selected: `zacharyminer10/zeke-care` and `zacharyminer10/ezaide`.

## Running the tests

- `python3 tests/regression.py` from the repo root. Optional `--prev OLD.html` checks that data from an older version upgrades cleanly.
- Needs Python Playwright with Chromium (`pip install playwright` then `python3 -m playwright install chromium`). If the browser download is blocked by the environment's network settings, say so plainly and tell Zach what to change, rather than skipping the tests.
- Some tests fake the clock; tests that add a task to one shift only should put it in every shift (or fix the clock), or they fail depending on the time of day.

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
