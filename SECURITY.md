# Security

IntentBench is intended for a trusted local operator. It has no user authentication, role-based authorization, or tenant isolation security boundary. Workspace identifiers organize data; they do not restrict who can read or change it. Keep the API and frontend on loopback. An internet-facing deployment requires an authenticated gateway, TLS, access control, resource limits, and a separate deployment security review.

Host and Origin checks protect against unrelated websites; they are not authentication, and local processes or users that can reach the API can read or change its data.

## Data and credentials

- Keep `.env`, imported datasets, SQLite files, model credentials, indexes, experiment exports, and backups outside published source. Default runtime data lives in ignored `data/private/`; outputs live in ignored `artifacts/`.
- Protect local secrets and databases with operating-system permissions. The owner should be the only reader; protect backups and any custom `INTENT_DATA_DIR` too. Git ignore rules do not encrypt or redact data.
- Configure only endpoints you trust. API keys are sent to configured model services, and provider requests can include input text, catalog definitions, and conversation context. Local model downloads and dependency installation can also use the network.
- Use synthetic cases in issues, tests, screenshots, and logs. Review exported JSON before sharing: case-level results and metadata can contain private information.
- If a secret was committed or otherwise exposed, revoke or rotate it. Deleting it from the latest revision does not remove it from prior commits, forks, releases, caches, or existing clones.

## Reporting a vulnerability

Do not put credentials, private datasets, or exploit details affecting a live private service in a public issue. Until a private reporting channel is listed here or enabled on the repository, open only a non-sensitive request for a private contact method. Maintainers should verify that channel before making the repository public.

A useful private report identifies the affected revision, minimal synthetic reproduction, expected and observed behavior, and likely impact. There is no published response-time commitment or supported-version policy yet.

## Release checks

Follow [release preparation](docs/public-release.md). Scan both release files and the history that will actually be pushed. Automated scans are heuristics and cannot prove ownership, confidentiality clearance, or absence of secrets. Repository visibility and hosting a running application are separate decisions.
