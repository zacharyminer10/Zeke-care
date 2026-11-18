# Style checker

Proves a change to the styles (or a refactor) leaves the look unchanged. It records the final computed
style and position of every element on 23 screens and pop-ups x 3 sizes (iPad landscape, iPad portrait,
phone) x 2 themes (138 combinations) and compares two versions.

Run from the repo root (needs the same Playwright setup as `tests/regression.py`; takes a few minutes):

    git show origin/main:index.html > /tmp/before.html
    python3 tests/stylecheck/snap.py /tmp/before.html /tmp/before.json            # baseline
    python3 tests/stylecheck/snap.py index.html /tmp/after.json /tmp/before.json  # compare -> IDENTICAL or the screens that changed

Both files must be in a folder the script can serve (it serves the file's own folder).

Other helpers (used for the 1.19.2 CSS cleanup):
- `cssx.py`: parse/serialize the `<style>` block.
- `xform.py`: remove overridden declarations, merge repeated selectors, drop `!important`.
- `verify.py` / `pverify.py`: swap candidate CSS into the same live page and compare (pverify runs the 3 sizes in parallel).
- `impcheck.py`: test removing each `!important` on only the elements it can affect.
