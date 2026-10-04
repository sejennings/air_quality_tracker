# Private container verification

The source repository stays public for portfolio viewing. Runtime images use the separate GHCR package `ghcr.io/sejennings/air-quality-tracker-runtime` in the same account; no second source repository is needed. CI refuses to push unless the package already exists and is verified private, and checks again after publishing. A package administrator must grant this repository Actions access to the private package. Package bootstrapping is performed using the owner's authenticated CLI, without embedding credentials in files or the image.

```powershell
./scripts/test-container.ps1
./scripts/test-container.ps1 -Pull -Image 'ghcr.io/sejennings/air-quality-tracker-runtime@sha256:DIGEST'
```

Local pulls require read:packages credentials stored by Docker Desktop's credential helper. Authentication is sent through standard input, not command arguments. CI uses its short-lived GITHUB_TOKEN. The image excludes `.env`, historical data, notebooks and runtime/model artifacts. Privacy is an access control; secrets must still stay outside image layers and public source.

All eight tests passed in both GitHub Actions and the locally pulled image before the private-package migration. The previously public test package must be deleted; the private replacement and registry access must be verified before migration is complete. Ubuntu deployment remains on hold.
