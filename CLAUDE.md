# Commit Message Format

This repo's recent history (see `git log`) follows this convention — use it for every commit unless told otherwise.

## Subject line

```
type(scope): short imperative description
```

- `type` — lowercase: `fix`, `test`, `feature` (this repo uses `feature`, not `feat`), `docs`, `refactor`, etc.
- `scope` — optional, lowercase, names the area touched (e.g. `tests`, `resume-builder`). Omit if the change is repo-wide.
- Description — imperative mood ("add", "correct", "expand"), no trailing period.

Examples from this repo:
- `fix(tests): correct GLib.Variant unwrap in test_get_layout_depth_one`
- `test: expand unit test suite and add GitHub Actions CI pipeline`
- `feature(resume-builder): add direct paste using remote desktop access`

## Body

Optional, separated from the subject by one blank line. Used when the "why" isn't obvious from the subject:
- Explain the root cause of a bug, not just the symptom.
- Explain a non-obvious design/implementation choice.
- For test/feature additions, a short bullet list of what's covered is fine.
- Skip the body entirely for small, self-explanatory changes.

Do not describe *what* the diff does line-by-line — that's what `git diff` is for. Focus on motivation and non-obvious reasoning.

## Trailer

Every commit made by Claude ends with a blank line followed by:

```
Co-Authored-By: Claude <model-name> <noreply@anthropic.com>
```

Use the actual model name in use for that session (e.g. `Claude Sonnet 5`, `Claude Opus 4.8`) — match whatever model generated the commit, don't hardcode an old one.

## Notes

- A few older commits in this repo predate this convention (no `type(scope):` prefix, version numbers in parentheses like `(0.2.2)`) — treat those as legacy, not a pattern to copy.
- Only create commits when the user explicitly asks. Never use `--amend` unless explicitly requested; always create a new commit instead.
- Never use `--no-verify` or otherwise skip hooks.
