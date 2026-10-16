# Release preparation

IntentBench benchmarks decision models for intent routing using text and conversation context, with English synthetic starter data across four sectors. Its own code, documentation, and bundled examples are licensed under [Apache-2.0](../LICENSE). Third-party libraries, model weights, datasets, and services retain their own terms.

## Release checklist

1. Review the provenance and publication rights of new code, documentation, examples, and test fixtures. Retain applicable third-party notices. Include the canonical `LICENSE` in source, package, and container distributions.
2. Keep credentials, private datasets, runtime databases, indexes, benchmark outputs, and backups out of source and release artifacts. Check endpoints, screenshots, comments, and examples for private information; use reserved example domains and synthetic credentials in fixtures.
3. Run backend behavior tests, frontend tests and the production build sequentially. Run dependency checks and secret scans against both release files and all Git history included in the release. Inspect CI permissions, generated bundles, package contents, and container build context.
4. Review the exact files, branches, tags, and artifacts being published. Check hosted issue attachments, CI logs, and release assets as well as repository source. Verify a private vulnerability reporting channel and update [SECURITY.md](../SECURITY.md) before making the repository public.
5. Reproduce the offline lexical benchmark with isolated temporary storage. Publish benchmark comparisons only with fixed dataset/catalog identities, model and protocol settings, split methodology, sample counts, error counts, and timing conditions.

Repository visibility and hosting a running application are separate decisions. The default application assumes a trusted local operator. Follow the [security guidance](../SECURITY.md) before deploying beyond loopback.

## Verification record

Record the release revision or source-export digest, scanner versions and scope, test commands and outcomes, dependency-audit results, and unresolved findings. Keep sensitive scan reports and raw private benchmark runs local. Publish a reviewed summary of the checks and their limits. Automated scans reduce risk but do not prove ownership, confidentiality clearance, or the absence of secrets.

If a credential is exposed, revoke or rotate it promptly and review all affected publication surfaces. Deleting a file from the latest commit does not remove copies from earlier commits, forks, releases, caches, or existing clones.

## Pitfalls

- A working-tree scan does not cover earlier commits, author metadata, other refs, or ignored files copied into an archive. Build release archives from a reviewed file list and inspect the resulting contents.
- Benchmark counts, operational observations, internal process names, and deployment notes can reveal private information without containing raw data. Use reproducible synthetic examples in public documentation.
- Check frontend defaults, backend routing, tests, fixtures, generated assets, and documentation together when changing or removing a provider. Existing local databases may retain provider registrations, so unsupported records must be handled consistently across list, detail, resolution, and inference paths.
- Use isolated temporary storage and disabled or mocked external model boundaries for verification. Test isolation must begin before collection imports application modules; an autouse fixture can run too late if an import creates storage.
- Import application modules through the canonical `app.*` package in tests, using the configured pytest `pythonpath`. The repository-root `apps.api.app.*` path can work with `python -m pytest` while failing with the `pytest` command used in CI.
- Keep cross-document links and setup instructions current. Verify the documented workflow against a fresh demo installation.
- CORS response headers alone do not prevent cross-site requests from changing local data. Validate Host and Origin before processing requests, and use Fetch Metadata for cross-site requests without Origin. Scope test-only host exceptions to tests.
- Set owner-only permissions on local data directories and files. Reject symbolic-link targets before changing permissions or opening private storage.
- Container CLI commands need a writable artifact path for the non-root application user. The image maps `/app/artifacts` to `/app/data/private` for this purpose. Validate build-context exclusions with synthetic private-file markers; an absence from the final image does not prove a file was excluded from the build context.
- Apply security patches to build tools and locked transitive dependencies together. Inspect the resolved lockfile and rerun the build after an update.
- Review a secret-scanner false positive against its exact match. Full-history scans retain findings from earlier commits even after current files change. For verified historical metric names or catalog checksums, record only the exact commit, path, rule, and line fingerprint in `.gitleaksignore`; preserve historical migration data and avoid broad keyword or path exclusions. Describe the finding in comments without copying the triggering assignment, since the ignore file is scanned too. Verify that new synthetic credentials still fail the scan after adding an exception.
- Run expensive test suites and frontend builds sequentially. Confirm completed job status and reproduce transient timeouts in isolation before classifying them as application defects.
- License metadata alone is insufficient for distribution. Inspect the built package's license expression and included license file, and verify that the runtime container contains the same license text.

- Verify an English release through the full request flow, including catalog text, retrieval instructions, model prompts, response text, and supported workflow replies. Preserving multilingual user content and historical fixtures is intentional.
- Use exact known content fingerprints for language migrations. Preserve edited/reviewed records and historical snapshots; never identify a legacy catalog solely by whether its workspace already exists.
- Verify each sector with its own seed/test/calibration cohort and workspace-scoped model registrations. Do not reuse banking OOS labels or silently copy credentials across sectors.
