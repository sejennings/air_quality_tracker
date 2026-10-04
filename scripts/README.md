# Container verification

Ubuntu deployment remains on hold. The public portfolio repository uses one GHCR image package; public visibility is accepted by the project owner. A private image with public source is also supported by GHCR, but is not required for this setup.

Build and test locally with Docker Desktop in Linux-container mode:

```powershell
./scripts/test-container.ps1
```

CI builds a Linux amd64 image and tests validation, retention, training, model promotion and scoring using synthetic data. It validates Compose, publishes the same tested image under the commit SHA, pulls it back, compares image IDs and reruns all eight tests. Pull requests never publish. Main pushes, the verification branch and manual runs can publish. No host deployment occurs.

After a successful workflow run, use its digest from the run summary:

```powershell
./scripts/test-container.ps1 -Pull -Image 'ghcr.io/sejennings/air_quality_tracker@sha256:DIGEST'
```

Public GHCR images can be pulled anonymously; Docker Hub authentication is not required for the public Python base image. The image excludes `.env`, datasets, notebooks and runtime/model artifacts. The container runs as a non-root user; tests also exercise a read-only filesystem with writable temporary storage.

The first publishing run failed its private-visibility check; that package was deleted. Publishing resumed after the owner accepted public visibility. All eight tests and Compose validation passed in the first run. See the latest Actions run for current publishing and registry verification results.
