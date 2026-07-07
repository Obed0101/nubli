# Contributing to Nubli

Thanks for helping improve Nubli.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[all]'
python tests/smoke.py
```

## Branching model

- `main`: stable release branch.
- `dev`: integration branch.
- `feature/<short-name>`: new features.
- `fix/<short-name>`: bug fixes.

Open pull requests into `dev` first. Release PRs go from `dev` to `main`.

## Before opening a PR

Run:

```bash
python -m py_compile nubli.py
python tests/smoke.py
```

If packaging changed, also run:

```bash
python -m build
```

## Code style

- Keep the CLI simple and predictable.
- Prefer standard library for core features.
- Keep heavy dependencies optional.
- Fail closed for privacy-sensitive behavior.
- Use clear comments where behavior is security-sensitive or intentionally conservative.

## Test data policy

Only use synthetic data in examples and tests. Do not add real company documents, private reports, IDs, phone numbers, emails, client names or PDFs.

## Commit guidance

Use short, plain commit messages, for example:

- `feat: add interactive installer`
- `fix: fail closed on zero replacements`
- `docs: document visual redaction regions`

Do not commit generated outputs, `.venv`, `.env`, caches or private files.
