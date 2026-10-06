# Development Notes

CatalogFlow began as a portfolio proof-of-work around a data-operations problem: receiving inconsistent product files and turning them into cleaner, reviewable, export-ready catalog data.

## Design choices

- **Local-first:** the application runs on localhost so a user can test catalog files without deploying a server.
- **Deterministic baseline:** template enrichment works without an LLM. AI is optional rather than required for the workflow to function.
- **Human-review layer:** before/after previews keep the operator in the loop.
- **Cost control:** live provider enrichment is capped to a sample in the prototype.
- **Simple interoperability:** CSV and Excel remain the primary input/output formats.

## What I would change for production

- Move job state and outputs to a database/object store.
- Add authentication, user isolation, upload retention rules, and audit logs.
- Add explicit schema profiles per client/vendor.
- Add stronger validation rules and row-level exception reporting.
- Add background workers and retries for provider calls.
- Add observability, rate limits, and structured error logging.
- Add benchmark datasets and regression tests for mapping/normalization quality.
