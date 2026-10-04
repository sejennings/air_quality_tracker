# Local container and private registry verification

Ubuntu deployment is on hold. Docker Desktop must use Linux containers.

Build and run all tests locally from PowerShell:

```powershell
./scripts/test-container.ps1
```

The test runner stops on the first failed command. The container runs as a non-root user with a read-only filesystem and writable temporary storage. Tests use synthetic data, train a one-epoch candidate, promote it, and reload it for scoring; no repository models or historical data are modified.

CI builds Linux amd64, runs the full test suite, validates Compose, and keeps the tested image on the same runner. Main pushes, pushes to the CI verification branch, or manual workflow dispatches publish that exact image to GHCR under the commit SHA. Pull requests never publish. Publishing checks existing package visibility before pushing, rejects non-private packages, and verifies private visibility afterward. First-created GHCR packages default to private. CI then pulls the published image, checks its image ID against the tested build, and reruns all tests. No host deployment occurs.

GitHub authentication must be working before pushing changes or dispatching Actions:

```powershell
gh auth login -h github.com
gh workflow run 'CI and image' --ref YOUR_BRANCH
gh run list --workflow 'CI and image'
gh run watch RUN_ID --exit-status
```

Local private GHCR pulls require a classic GitHub personal access token with `read:packages`; use Docker Desktop's credential store. Never paste the token into chat, store it in this repo, or pass it as a command-line argument. In PowerShell, prompt for the token and send it through standard input:

```powershell
$registryCredential = Get-Credential -UserName sejennings -Message 'Use your GitHub read:packages token as the password'
$registryCredential.GetNetworkCredential().Password | docker login ghcr.io -u sejennings --password-stdin
Remove-Variable registryCredential
./scripts/test-container.ps1 -Pull -Image 'ghcr.io/sejennings/air_quality_tracker@sha256:DIGEST_FROM_SUCCESSFUL_RUN'
```

Docker Hub sign-in is not required for normal local builds using the public Python base image. Do not change the GHCR package visibility to public. Source secrets, historical data, and notebooks are excluded from the Docker build context.


Privacy verification finding: the first real CI push created a public package despite the documented default. The package was deleted by cleanup run 37226316105. Publishing now requires an existing, API-verified private package before any push; absent or inaccessible packages fail closed. A private registry destination and read:packages authentication must be provisioned before further publishing. The container build, all eight tests, and Compose checks passed in run 37226077080; its publishing stage failed the post-push privacy check. Ubuntu deployment remains on hold.
