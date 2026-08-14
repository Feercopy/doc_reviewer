# Production deployment

Production deploys automatically after a successful verification run for a
commit pushed to `main`. GitHub Actions connects with a dedicated SSH key whose
server-side `authorized_keys` entry forces
`gate-challenger-deploy-entrypoint`. The entrypoint accepts only
`deploy <40-character commit SHA>`.

The root-owned deploy program then:

1. serializes releases with `flock`;
2. fetches the read-only GitHub repository mirror;
3. requires the requested commit to equal the current `origin/main`;
4. materializes an immutable release directory;
5. builds release-tagged API, worker, and web images;
6. creates a PostgreSQL custom-format dump;
7. applies Alembic migrations and refreshes baseline skills;
8. recreates API, worker, web, and edge containers;
9. checks internal API health, public API health, and the public login page;
10. rolls application containers back when the new release is unhealthy.

Database migrations are not automatically downgraded. Production migrations
must follow an expand/contract approach so the previous application release
can continue to run against the migrated schema during an application rollback.

## Server layout

```text
/etc/gate-challenger/github-deploy-key       # server -> GitHub, read-only
/etc/gate-challenger/github-known-hosts
/usr/local/sbin/gate-challenger-deploy
/usr/local/sbin/gate-challenger-deploy-entrypoint
/opt/gate-challenger/repository.git          # mirror cache
/opt/gate-challenger/releases/<commit>
/opt/gate-challenger/shared/infra.env         # root-readable production config
/opt/gate-challenger/current                  # active release symlink
/opt/gate-challenger/external                 # legacy read-only skill mounts
/var/lib/gate-challenger/storage/external     # managed production skill checkouts
/opt/gate-challenger/backups                  # source backups and DB dumps
```

The production Gate Challenger source is managed during the baseline skill
refresh. By default the API container checks out
`https://github.com/Ilya-eremenko/Gate2-challenger-skill.git` at commit
`3447f867987d8727cbbd16e8874c60f2b1ed07d0` into a ref-specific directory in
the shared storage volume and seeds that checkout as the active
`gate-challenger` source. Override `GATE_CHALLENGER_MANAGED_REPO_URL` or
`GATE_CHALLENGER_MANAGED_REF` only when intentionally switching source. The
default checkout path is derived from the effective managed ref. Production
intentionally ignores the legacy `GATE_CHALLENGER_SOURCE_PATH` value that may
remain in `infra.env`; use `GATE_CHALLENGER_MANAGED_PATH` for an intentional
ref-specific managed checkout override.
`GATE2_BENCHMARK_DIR` defaults to that checkout's `benchmark` directory so
benchmark imports and analysis snapshots use the same pinned source revision.

The Progress Review feature follows a compatibility release that can deserialize
the new document type and restore either baseline skill version. The feature
deployer stops the public application services before activating the pinned v2
skill, then recreates them from the new release. If startup fails, rollback runs
the previous release's seeder before bringing its containers back, which
reactivates v1 and archives v2. A failed skill restore makes rollback fail
explicitly instead of reporting a healthy but incompatible release. Rollback
also stops the failed release before restoring v1, so it cannot accept traffic
against the baseline being changed underneath it.

Devil's Advocate and IC Agentic Review sources remain externally mounted and
independently versioned so analysis runs continue to snapshot explicit skill
source versions.

## GitHub environment

Create an environment named `production`, limit it to `main`, and configure:

- `PROD_HOST`: production hostname or IP;
- `PROD_SSH_KEY`: private half of the restricted GitHub Actions deploy key;
- `PROD_KNOWN_HOSTS`: pinned SSH host key line for production.

Also add the public half of the server's GitHub identity as a read-only deploy
key on `Ilya-eremenko/doc_reviewer`.

Protect `main` so changes arrive through pull requests, unresolved review
conversations block merging, administrators cannot bypass the rule, and direct
or force pushes are not allowed. After the workflow has completed on its first
pull request, add the `Verify release` job as a required status check.

## Manual verification and rollback

The root-only preflight command fetches and validates `main` without building,
migrating, or recreating containers:

```bash
sudo /usr/local/sbin/gate-challenger-deploy --preflight <commit-sha>
```

Application rollback is performed by redeploying a known good commit that is
again present at `origin/main`. For emergency recovery, point `current` to a
previous directory under `releases/`, export that release's image tags, and run
its production Compose file. Restore a PostgreSQL dump only as a separately
approved recovery operation.
