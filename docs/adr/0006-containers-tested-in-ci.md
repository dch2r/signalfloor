# ADR 0006: Containers built and tested in CI first

- Status: Accepted
- Date: 2026-10-28

## Context

The project now has an API, a worker, migrations and a dashboard. They need to be packaged as
container images and shown to run together, and later on Kubernetes.

Development happens on an Intel Mac with 8 GB of memory, which also runs Postgres and a local
model with Ollama. Docker Desktop keeps a Linux virtual machine running at 2 GB or more, and a
local Kubernetes cluster needs more on top. That leaves little room for the model.

## Decision

1. Build and run the containers in GitHub Actions on every pull request, not on the laptop. The
   runners have Docker, enough memory, and cost nothing for a public repository.
2. One image for the Python side. The API, the worker and the migrations are the same code, so
   they share an image and differ only in the command it runs.
3. Multi-stage builds. Dependencies are installed with uv in a build stage, and only the
   finished virtual environment is copied into a slim runtime image that runs as a non-root
   user. The dashboard uses Next.js standalone output for the same reason.
4. Pin base images by digest, like the GitHub Actions are pinned by commit. Dependabot keeps
   the digests current.
5. A docker-compose file for the whole stack, and one smoke test script that checks it end to
   end: upload, compare, a background job, a trace and the dashboard pages. The same script
   will run against Kubernetes.

## Consequences

- Every pull request proves the images build and the stack works together.
- Running the stack locally needs Docker, which the main developer doesn't install for now.
  Anyone with Docker can run `docker compose up --build`.
- The images are built in CI but not published yet. Publishing them comes with the Kubernetes
  work.
