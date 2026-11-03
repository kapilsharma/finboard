# ADR-0009: Parser discovery via entry points, including built-ins

**Status:** Accepted (refines HANDOVER §6)

**Decision.** All parsers, built-in and third-party, are discovered through `importlib.metadata.entry_points(group="finboard.parsers")`. Built-ins are declared in finboard's own `pyproject.toml`. Each entry point resolves to a parser instance or a zero-arg factory. The public SDK is `finboard.parsers.sdk`, and compatibility is governed by an integer `PARSER_API_VERSION`.

**Why.** There is one code path to test. A contributor's out-of-tree parser behaves exactly like a built-in. Entry points are the standard Python plugin mechanism (pytest, flake8).

**Rules.** Load failures, duplicate ids and API-version mismatches are isolated and listed in Settings › Parsers with the reason. They never prevent startup. Parser `version` (semver) is recorded on every import.

**Alternatives rejected.** Scanning a `plugins/` folder (executes arbitrary files dropped into a folder, no packaging metadata). pluggy (more than we need).
