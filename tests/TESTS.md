# Running Tests

## Full default suite (CI-equivalent)

```bash
python -m pytest -m "not e2e"
```

## End-to-end mocked suite

```bash
python -m pytest -m e2e
```

## Quality checks

```bash
python -m ruff check .
python -m black --check .
python -m pytest -m "not e2e"
python -m pytest -m e2e
```