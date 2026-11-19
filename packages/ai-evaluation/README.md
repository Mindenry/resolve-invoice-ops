# RESOLVE AI Evaluation tools

- `validate` checks dataset structure before it is imported.
- `run` queues a real evaluation through the API, waits for the worker, and prints the measured
  metrics. It does not compute scores locally, so it cannot fabricate results.

```bash
pip install -e packages/ai-evaluation
resolve-eval validate datasets/evaluation/investigation_samples.json
resolve-eval run --email admin@example.com --password "$RESOLVE_DEMO_PASSWORD" --organization northwind
```

When the API is configured with the deterministic stub provider, run metrics are labelled
`deterministic_stub: true`; they measure the harness, not a real model.