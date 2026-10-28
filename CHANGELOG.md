# Change Log

## v1.3.0
    * Retries are now driven by named errors. The Lambda raises throttling, AWS-side failures (5xx) and connection problems as `AWSTransientError`, keeping the original error as its cause, through the `aws_errors` module (distributed by the Installer, packaged in the new `AwsErrorsLayer`). The state machine retries `AWSTransientError` and the Lambda service errors: 5 seconds, doubling, at most 300 seconds apart, full jitter, 20 attempts. It no longer retries on `States.TaskFailed`, which matched every error, permanent ones included.
    * Fix: throttling during VPC removal was swallowed. Every EC2 call caught its own errors, printed them and continued; a throttled describe left its result unset, so the next line failed with an `UnboundLocalError`. Throttling is now retried, and a retry re-describes whatever is left of the default VPC. A delete refused for another reason (e.g. a dependency) is still logged and the removal continues; a describe refused for another reason now fails with its own error.
    * New offline unit tests for the retry rules and the error handling.

## v1.2.6
    * Security: bump `urllib3` floor to `>=2.8.0` in `boto3.in` (distributed from canonical `Installer/templates/boto3.in`) to remediate CVE-2026-97687 (HTTPS-proxy TLS configuration ignored or overridden), CVE-2026-97688 (infinite loop on chunked Deflate responses) and CVE-2026-97689 (unbounded chunk-size-line buffering). All three are fixed in urllib3 2.8.0; the previous `>=2.7.0` floor resolved to 2.7.0, which is affected by all three. Locks recompiled with `--upgrade`; other transitive deps refreshed to their latest in-range versions as a side effect (no code or behaviour change).

## v1.2.5
    * `README.md` gains the OpenSSF Best Practices Passing-level badge (project entry [bestpractices.dev/projects/12827](https://www.bestpractices.dev/projects/12827)).

## v1.2.4
    * Carries Installer v3.0.11 customer-side release verification. `scripts/deploy.py` now verifies the Sigstore signature of every released artefact (SBOM, evidence, SLSA provenance) against the maintainer identity (`peter@peterbengtson.com` via `https://github.com/login/oauth`) before any `sam build` / `cfn deploy` / script execution; the shared verifier lives in `scripts/_verify_release.py` (distributed by `refresh`). Tampered artefacts, wrong signer, or missing bundles fail the deploy. New `--unsafe-untagged` flag on `./deploy` for emergency overrides (loud red audit banner). No code changes in this component; the verifier rides along with `refresh`-distributed scripts.

## v1.2.3
    * Security: bump `urllib3` floor to `>=2.7.0` in `boto3.in` to remediate CVE-2026-44431 and CVE-2026-44432 (both affect urllib3 ≤ 2.6.3, fixed in 2.7.0). The pinned `boto3==1.42.94` previously resolved urllib3 transitively to 2.6.3; the new floor forces resolution to 2.7.0 across every Lambda lockfile. No code changes; recompiled locks only.

## v1.2.2
    * Enable auto-close workflow for external pull requests, enforcing the cathedral governance policy uniformly across all OpenSecOps repositories. Pull requests from non-team authors are closed automatically with a redirect comment pointing to the bug-report template, the GitHub Security Advisory flow, and the fork-under-MPL-2.0 path.
    * `SECURITY.md` §14 now carries a Trust-page cross-link ([opensecops.org/trust.html](https://www.opensecops.org/trust.html)) alongside the existing canonical supply-chain document link, positioning the Trust page as the lighter customer-facing synthesis.

## v1.2.1

- `SECURITY.md` and `README` updated re: OpenSSF Scorecard publication status. See [supply-chain documentation](https://github.com/OpenSecOps-Org/Documentation/blob/main/docs/security/supply-chain.md) §5.5.

## v1.2.0
    * Converted to OpenSecOps supply-chain framework: hash-pinned dependencies, signed releases, daily CVE scan, Scorecard. See `SECURITY.md`.
    * `boto3` pinned to `1.42.94` (was `1.28.33`) per project-wide pin policy.

## v1.1.5
    * Updated GitHub remote references in publish.zsh script to use only OpenSecOps-Org, removed Delegat-AB

## v1.1.4
    * Updated GitHub organization name from CloudSecOps-Org to OpenSecOps-Org.
    * Updated references to CloudSecOps-Installer to Installer.

## v1.1.3
    * File paths corrected for the new name of the installer.

## v1.1.2
    * Updated LICENSE file to MPL 2.0.


## v1.1.1
    * Updated publish.zsh to support dual-remote publishing to CloudSecOps-Org repositories.

## v1.1.0
    * Upgraded to Python 3.12.

## v1.0.3
    * Refreshed deployment scripts.

## v1.0.2
    * Open-source credits and URLs
    * Fixed installer initial stackset creation.

## v1.0.1
    * `--dry-run` and `--verbose` added to `deploy`.

## v1.0.0
    * Initial release.
