# Release Checklist

Use this before publishing from `dev` to `main`.

## 1. Local safety check

```bash
python -m py_compile nubli.py
python tests/smoke.py
```

## 2. Packaging check

```bash
python -m pip install --upgrade build twine
python -m build
python -m twine check dist/*
```

## 3. Secret/data check

Confirm the release does not include:

- `.env` or `.env.*`
- real PDFs or client documents
- generated anonymized outputs
- `.venv`
- caches
- private logs
- credentials or tokens

## 4. Branch flow

Recommended:

```text
feature/* -> dev -> main
fix/*     -> dev -> main
```

Only publish from `main` after `dev` has passed CI.

## 5. Tagging

After merge to `main`, create a signed or regular tag according to maintainer policy:

```bash
git tag v0.1.0
git push origin v0.1.0
```

Do not tag private local experiments.
