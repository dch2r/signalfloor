# signalfloor Helm chart

Deploys the signalfloor API, the background worker, the dashboard, a database migration job and
a daily job that deletes old trace spans. It can also run a single Postgres pod for trying it
out.

## Install

The images aren't published to a registry yet, so build them and make them available to your
cluster first. With [kind](https://kind.sigs.k8s.io):

```bash
docker build -f packages/server/Dockerfile -t signalfloor-server:local .
docker build -t signalfloor-dashboard:local dashboard
kind load docker-image signalfloor-server:local signalfloor-dashboard:local

helm install signalfloor deploy/helm/signalfloor --wait --wait-for-jobs
kubectl port-forward svc/signalfloor-dashboard 3000:3000
```

By default the chart starts its own Postgres pod. For a real database, turn that off and point
the chart at yours, either with a URL or with a Secret you manage:

```bash
helm install signalfloor deploy/helm/signalfloor \
  --set postgresql.enabled=false \
  --set database.existingSecret=signalfloor-database
```

The Secret needs the key `SIGNALFLOOR_DATABASE_URL`. See `values.yaml` for every setting.

Set `auth.apiKeys` to require API keys. Separate several with commas, escaped as `\,` inside
`--set`. Empty leaves the API open to anything in the cluster that can reach it. The dashboard
has no login of its own, so put it behind your own sign in before exposing it.

## How it fits together

- **Migrations run as a plain Job, once per release.** It is not a Helm hook. Helm runs
  post-install hooks only after the pods are ready, and the API isn't ready until the schema is
  migrated, so a hook would deadlock `helm install --wait`.
- **The API is ready only when the schema is.** `/health/ready` checks that the database
  answers and that its schema is at the migration the code expects. On a fresh install and
  after an upgrade with a new migration, API pods take traffic only once the Job has finished.
- **The worker waits for the database instead of crashing.** It retries with backoff while the
  database is down or not yet migrated. On SIGTERM it finishes its current job, with two minutes
  to do so.
- **Containers run locked down:** not as root, with a read only filesystem and no Linux
  capabilities. The dashboard gets a writable folder for the Next.js cache only.
- **Two or more API pods get a disruption budget**, so draining a node never takes them all
  down at once.

CI installs the chart on a kind cluster, upgrades it, and runs `scripts/smoke-test.sh` against it
on every pull request.
