# Repository guidance

## Project overview

This repository contains Python scripts for inspecting and summarizing a Sleeper NFL fantasy league. The main implementation is `sleeper_v3_2.py`; older versioned scripts and backups are retained for reference. Generated JSON and Markdown snapshots are stored in `snapshots/`.

## Working conventions

- Keep changes focused and preserve the existing script style unless a task calls for a broader refactor.
- Treat versioned backups as historical copies; update the active script unless asked to change a specific version.
- Do not commit credentials or private league data. Keep the league identifier and roster settings consistent with the user's intent.
- Keep API requests bounded with timeouts and call `raise_for_status()` before consuming responses.
- Preserve existing snapshot formats and file naming conventions when changing snapshot generation.

## Validation

- The repository includes `sleeper_test.py` and `sleeper_transactions_test.py`. Inspect these before changing related behavior.
- Some scripts make live requests to the Sleeper API when run. Review their top-level behavior before executing them; prefer syntax checks or isolated/local checks when possible.
- Do not treat generated files under `snapshots/` as source code.
