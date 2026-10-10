# Response to a second round of audit findings (Issues 6-9, on n_binding_lines_baseline.py)

Only one of these four was actually applied — the other three were
reasonable hardening suggestions, not things that needed fixing, and
were deliberately left as-is at Lucy's direction rather than changed.

- **Issue 9 — FIXED.** The real "binding" definition (loading >= 99.9%,
  not `overload_MW > 0`) was only in the script's docstring, not in the
  CSV itself. `binding_lines.csv` now carries a
  `binding_definition = "loading_ge_99.9pct"` column on every row, so the
  file stays unambiguous even if separated from the docstring or this
  note — the same self-describing-CSV pattern already applied to the
  Step 2 matrix.
- **Issue 6 (sanity-check wording) — not changed.** The report's point
  (a >200% reading doesn't *mathematically prove* a skipped
  `freeze_dispatch`, only indicates it) is technically correct, but the
  check's actual logic was never wrong — only the certainty of its
  wording. Left as originally written.
- **Issue 7 (`n_select` validation) — not changed.** The report itself
  flagged this as "not relevant to your current run, but trivial to
  harden" — a defensive guard against an input nobody is actually
  passing, not a fix for anything broken in this deliverable.
- **Issue 8 (empty-binding check) — not changed.** Same category: only
  matters for a hypothetical future run where nothing binds, not for
  this actual WP2033/all-island result (6 lines do bind).

Re-ran the full pipeline end-to-end after the one applied change:
`binding_lines.csv` regenerated with the same 6 lines, same numbers, now
with the `binding_definition` column; `o_shift_factor_matrix.py` (Step 2)
re-run against the updated file to confirm it still reads cleanly and the
quality gate still passes.
