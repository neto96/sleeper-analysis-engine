# Sleeper Analysis Engine

This repository contains the Python engine used to collect Sleeper NFL fantasy league data and produce JSON and Markdown snapshots with roster and waiver analysis. **V3.3 is the finalized configuration-driven roster analysis engine.** Its canonical baseline is commit `a76e2c8f945d8c5f3b7ffd6d30620f1beb31d54d` (`V3.3 final - configuration-driven roster analysis`).

## Current implementation

[`sleeper_v3_2.py`](sleeper_v3_2.py) is the active executable script. Despite its filename and the snapshot's retained `snapshot_version` value of `3.2`, it contains the V3.3 roster-configuration work. `main()` calls the Sleeper API, builds rosters and league data, runs analysis, and writes JSON and Markdown snapshots under `snapshots/`. Running the script is not an offline operation; its production path makes live API requests.

This project is currently a Python implementation. Publishing it to GitHub does **not** make the engine executable inside the separate Grok/Vercel TypeScript app. An integration boundary still needs to be selected, such as running Python separately or porting/adapting the engine behind an agreed interface. The repository is not currently a reusable Python package or an HTTP service.

## Roster configuration and analysis

The league response's `roster_positions` array is normalized by `parse_roster_configuration()`. Direct position counts, FLEX counts and eligibility, bench counts, and unrecognized slot counts are preserved. `expand_roster_slots()` creates deterministic slot instances; shared assignment logic prevents one player from covering multiple slots.

Recognized direct positions are `QB`, `RB`, `WR`, `TE`, `K`, `DEF`, `DL`, `LB`, and `DB`. FLEX eligibility is:

| Slot | Eligible positions |
| --- | --- |
| `FLEX` | RB, WR, TE |
| `WRRB_FLEX` | RB, WR |
| `REC_FLEX` | WR, TE |
| `SUPER_FLEX` | QB, RB, WR, TE |
| `IDP_FLEX` | DL, LB, DB |

The normalized configuration informs optimal lineup selection, lineup coverage, position need, starting depth, lineup strength, roster surplus, replacement cost, and league position analysis. Waiver analysis consumes configuration-aware position need and league scarcity.

### Modeling boundaries

- The offensive optimizer selects only QB/RB/WR/TE. It does not optimize K, DEF, or IDP slots.
- K and DEF are represented in direct-slot configuration and coverage analysis.
- IDP slot codes are preserved and recognized, but IDP player analysis and optimization are not implemented.
- Meaningful players remain those in the `elite`, `strong`, or `useful` tiers. The existing `search_rank` tier boundaries are unchanged: elite ≤50, strong ≤120, useful ≤250, fringe ≤400, otherwise deep waiver; missing or invalid rank is unknown.
- League scarcity thresholds remain High when median depth ≤8 **or** average meaningful players ≤1.5; Moderate when median depth ≤14 **or** average meaningful players ≤2.5; Low otherwise.
- Waiver recommendations remain limited to QB/RB/WR/TE. K/DEF/IDP are not added by roster configuration.

## Tests

The two offline standard-library test modules are `test_sleeper_v3_2_analysis.py` and `test_roster_configuration.py`. The complete suite was previously verified at **105 tests passed, 0 failed**.

With the project's configured Python interpreter, run:

```powershell
python -B -m unittest -v test_sleeper_v3_2_analysis test_roster_configuration
```

See [`V3.3_OUTPUT_CONTRACT.md`](V3.3_OUTPUT_CONTRACT.md) for the actual analysis and snapshot fields, types, compatibility notes, and representative JSON.
