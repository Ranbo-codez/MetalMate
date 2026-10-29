# Contributing to MetalMate

Thanks for helping. Bug reports, board themes that don't get recognised, engine suggestions and code are all
welcome.

## Ground rules

- MetalMate is for practice, analysis and games against bots. Features whose main purpose is hiding engine use from
  opponents or chess sites won't be accepted.
- Keep it private: nothing should leave the user's Mac except engine downloads they asked for.
- Never commit screenshots of other people's games or third-party sites. Put private test images in
  `tests/fixtures/private/` (ignored by git); tests that need them must skip when they're missing.

## Setting up

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m metalmate          # run from source
```

Running from source, macOS asks for Screen Recording permission for your terminal (or IDE) rather than for
MetalMate.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -t .
```

The suite runs offscreen and uses a throwaway data folder, so it never touches your games or settings. It covers
recognition on rendered boards, game tracking (including missed moves and tab switches), engines and profiles
(with a fake UCI engine), the game library and the UI pages.

Please add a test with every fix. For recognition problems, a rendered board that reproduces the issue
(`metalmate.render.BoardRenderer`) is ideal.

## Style

- Python 3.11+, type hints where they help, no unnecessary abstractions.
- Comments explain *why*, not what.
- User-facing text: plain, friendly and short. Explain settings in words a non-programmer understands.
- UI: use the components in `metalmate/ui/controls.py` and the colours in `metalmate/ui/theme.py`.

## Reporting bugs

Use the [bug report form](https://github.com/Ranbo-codez/MetalMate/issues/new/choose). Security problems go
through [private reporting](https://github.com/Ranbo-codez/MetalMate/security/advisories/new) instead (see
SECURITY.md).

## Pull requests

Changes reach `main` only through pull requests that Ranbir Dhall reviews and approves, after the tests pass.

1. Fork and branch from `main`.
2. Make your change with tests; run the suite.
3. Describe what changed and why. Screenshots help for UI changes (use `scripts/make_screenshots.py` for demo data).

MetalMate is created by Ranbir Dhall and licensed under the PolyForm Noncommercial License 1.0.0 (see LICENSE).
By contributing you agree that your contribution may be distributed under that licence, and that Ranbir Dhall
may also license it to others on other terms (for example a commercial licence).
