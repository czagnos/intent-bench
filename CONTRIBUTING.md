# Contributing

This project uses the [Apache License 2.0](LICENSE). Unless explicitly stated otherwise, contributions intentionally submitted for inclusion are provided under the same license. Submit only material you have the right to contribute, and preserve any applicable third-party notices. Dependencies and model presets do not change upstream licensing terms.

Use synthetic data that you have permission to publish. Do not include employer/client documents, internal addresses, API credentials, real conversations, private benchmark results, or machine-specific deployment instructions. Put local inputs and outputs in the ignored directories described in [data handling](data/README.md).

Before changing code, look for existing helpers and types. Keep reusable components independent of a feature's data source. For behavioral changes, write a failing test through the public interface, implement the smallest change, and refactor. Mock external boundaries rather than internal collaborators. Add lessons from corrections to the relevant technical guide's pitfalls section.

Run verification from the repository root:

```bash
.venv/bin/pytest -q
npm --prefix apps/web test
npm --prefix apps/web run build
```

Run these sequentially. Include the actual results and remaining limitations with your change. Review non-trivial changes before merging. For benchmark claims, include the fixed dataset/catalog identity, model and protocol settings, split methodology, sample counts, technical errors, and timing conditions. Keep raw private runs local and share only independently reviewed, publishable results.

See [security reporting](SECURITY.md) for sensitive issues and [release preparation](docs/public-release.md) for release checks.
