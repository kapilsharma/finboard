# Changelog

Notable changes to Finboard. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/). The release workflow publishes a
version's section as its release notes, so a tag needs a section here first
([CONTRIBUTING › Releasing](CONTRIBUTING.md#releasing)).

## [Unreleased]

Everything below is new: there has been no release yet.

### Added
- **Run it with Docker.** `deploy/compose.yaml` starts the app, a background worker, the
  housekeeping scheduler, Postgres and Redis. One `init` command writes the secret key and
  database passwords. Only the app is published, on `127.0.0.1:8765`.
- **Statement import.** Upload password-protected PDF statements; the password is never
  stored. Preview, fix rows, commit; re-importing a statement adds nothing; roll an import back.
- **Parsers.** ICICI Bank savings statements, plus a generic table parser for other layouts.
  New banks are added as adapters without touching the core.
- **Categorisation.** Your own rules (contains, starts with, exact, regular expression), a
  starter pack for common Indian merchants, a review queue, transfer pairing between your own
  accounts, and rule packs you can export and import.
- **Dashboard and transactions.** Income, spending, net saving and savings rate by month,
  monthly limits per category, income by source, per-account totals, and a searchable ledger.
- **Your data.** Export everything as one zip, import it into an empty Finboard, export
  transactions as CSV, delete everything. A database backup is taken before every upgrade
  that changes the schema.
- **Several people on one server (optional).** Server mode adds sign-in with a username and
  password, sign-up the operator can open, per-person limits, and S3-compatible storage for
  statements. Local mode, with no sign-in, stays the default. See `docs/HOSTING.md`.
- **Optional AI, off by default.** Category suggestions computed on your machine, and Ask
  Finboard, which answers questions as charts without sending transaction data to the model.
  Both need the `-ai` image.
