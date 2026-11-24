# Contributing to Pin2Brand

Thank you for helping make AI-generated interfaces and brand systems less generic!

## Local Development Setup

```bash
git clone https://github.com/jonaduran13-creator/pin2brand.git
cd pin2brand
uv sync --extra dev
```

## Running Tests

```bash
uv run pytest -v
```

## Pull Request Guidelines

1. Keep the deterministic CIELAB + Laplacian fallback working with zero API keys required.
2. Ensure all exported schemas (`visual-identity.json`, `tokens.w3c.json`, `tailwind.theme.json`) validate cleanly in `tests/test_pin2brand.py`.
3. Maintain WCAG AA (>= 4.5:1) contrast guarantees on all generated foreground/background color tokens.
