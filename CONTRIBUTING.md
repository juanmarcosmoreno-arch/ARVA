# Contributing to ARVA

ARVA is maintained by one person, in spare time. Questions, problem reports and
contributions are welcome, in English or Spanish. Answers are best effort and may
take some days.

## Getting help

Open an issue at <https://github.com/juanmarcosmoreno-arch/ARVA/issues>. Say what you
were trying to do, on which computer (operating system, memory), and what happened
instead. The guides are in [`docs/`](docs/): installation
([English](docs/installation.md), [Mac, in Spanish](docs/guia-mac.md)), methods
([scientific-methods.md](docs/scientific-methods.md)) and architecture
([architecture.md](docs/architecture.md)).

## Reporting a problem

1. In ARVA, open Settings → Diagnostics → **Copy diagnostic report** (or, when the
   interface does not open, run `scripts/diagnostics.sh`). For one failed job, use
   **Copy error details** on that job.
2. Paste the report into a new issue.

The report lists ARVA's version, the computer, the tools, the databases and the recent
errors. It never contains sequences, reads, file contents, passwords or e-mail
addresses. Do not attach sequencing data to a public issue.

A result you believe is scientifically wrong is a problem report too. Name the tool,
the database and its version (they are shown with the result) and, if you can, a public
genome that reproduces it.

## Contributing code or documentation

1. Open an issue first for anything larger than a small fix, so that the approach can
   be agreed before you write it.
2. Fork the repository and create a branch from `main`.
3. Set up the development environment with `scripts/setup-dev.sh` and read
   [docs/developer-guide.md](docs/developer-guide.md). Its rules are short and they
   are enforced in review: no invented results, provenance is part of the result,
   originals are never modified, tools are called with argument lists and never
   installed or updated at run time.
4. Add or update tests. `scripts/test-all.sh` runs the four suites (scientific core,
   tool adapters, API and web interface). Tests that need a real tool are skipped when
   the tool is not installed.
5. Interface text goes in both English and Spanish (`apps/web/src/i18n`).
6. Open a pull request that says what changed and how you checked it.

## Licence

ARVA is released under the [MIT licence](LICENSE). By contributing you agree that your
contribution is released under the same licence. The tools and databases that ARVA
runs keep their own licences.
