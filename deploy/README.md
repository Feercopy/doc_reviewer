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
/opt/gate-challenger/external                 # independently versioned skills
/opt/gate-challenger/backups                  # source backups and DB dumps
```

The external Gate Challenger, Devil's Advocate, and IC Agentic Review sources
are deliberately not updated by the application workflow. Their revisions are
managed separately so analysis runs continue to snapshot explicit skill source
versions.

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
