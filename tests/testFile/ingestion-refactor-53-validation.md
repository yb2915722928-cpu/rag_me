# Ingestion refactor #53 validation

## Final layout

The ten new contract modules added for this refactor are under `tests/testFile/` and are discovered as `tests.testFile.test_...`. Existing pre-refactor tests remain in their original locations. New temporary files and generated subprocess inputs were confined to a cleaned temporary directory below `tests/testFile/`; no temporary output remains after the runs.

## Commands and results

Environment: Python 3.11.16, Windows 10.0.26300, FFmpeg/FFprobe 8.1.2. The canonical interpreter was `E:\aaa-project\rag-me\.venv\Scripts\python.exe`. `PYTHONDONTWRITEBYTECODE=1` was set. `TMP`, `TEMP`, and `TMPDIR` were directed to a scoped directory under `tests/testFile/`, which was removed in a finally/cleanup step after each run.

Focused relocated acceptance suite:

```text
python -m unittest discover -s tests/testFile -p test_*.py -q
Ran 38 tests in 36.489s
OK
```

Full repository suite after relocation:

```text
python -m unittest discover -s tests -q
Ran 426 tests in 93.069s
OK (skipped=10)
```

The full run emitted three expected `pypdf` `EOF marker not found` diagnostics from malformed-input coverage. All ten live-service gates remained disabled/skipped; no paid service calls were enabled.

## Historical media CLI note

An earlier one-off #61 merger smoke run reported one success CLI case returning exit code 1 with empty stderr while its stdout was lost by the then-current assertion ordering. The cause was not established and no production timeout or behavior change was made for it. A later focused eight-case CLI run and diagnostic fifteen-test smoke run passed. The final media tests retain complete stdout/stderr diagnostics so a future failure is actionable.

## Scope

This acceptance change adds only the bounded missing projections: complete file/bytes/native-file-to-handoff/native-bytes-to-handoff/JSON coverage for image describe and image understand, plus the corresponding video-only uncertainty case. It does not add a costly 27-key success matrix, retries, live service calls, or new production behavior.
