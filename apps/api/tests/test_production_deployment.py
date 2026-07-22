import os
from pathlib import Path


REPO_ROOT = Path(
    os.environ.get(
        "PRODUCTION_DEPLOY_REPO_ROOT",
        str(Path(__file__).resolve().parents[3]),
    )
)


def test_production_compose_uses_release_tagged_application_images() -> None:
    compose = (REPO_ROOT / "infra/docker-compose.prod.yml").read_text()

    assert "image: ${GATE_API_IMAGE:-infra-api}" in compose
    assert "image: ${GATE_WORKER_IMAGE:-infra-worker}" in compose
    assert "image: ${GATE_WEB_IMAGE:-infra-web}" in compose


def test_production_workflow_deploys_only_verified_main_sha() -> None:
    workflow = (REPO_ROOT / ".github/workflows/deploy-production.yml").read_text()

    assert "push:\n    branches:\n      - main" in workflow
    assert "pull_request:\n    branches:\n      - main" in workflow
    assert "needs:\n      - resolve-release\n      - verify" in workflow
    assert "if: github.ref == 'refs/heads/main'" in workflow
    assert "format('gate-challenger-pr-{0}', github.event.pull_request.number)" in workflow
    assert "|| 'gate-challenger-production'" in workflow
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in workflow
    assert "release_sha:" in workflow
    assert "pull_request_number:" in workflow
    assert "reviewed_head_sha:" in workflow
    assert "resolve-release:" in workflow
    assert "The pull request did not merge within the reconciliation window." in workflow
    assert "ref: ${{ needs.resolve-release.outputs.release_sha }}" in workflow
    assert "RELEASE_SHA: ${{ needs.resolve-release.outputs.release_sha }}" in workflow
    assert '"deploy $RELEASE_SHA"' in workflow
    assert "environment:\n      name: production" in workflow


def test_codex_review_workflow_merges_only_clean_verified_head() -> None:
    workflow = (
        REPO_ROOT / ".github/workflows/codex-auto-merge.yml"
    ).read_text()

    assert "pull_request_target:" in workflow
    assert "issue_comment:\n    types:\n      - created" in workflow
    assert "pull_request_review:\n    types:\n      - submitted" in workflow
    assert "workflow_run:" in workflow
    assert "github.event.pull_request.head.sha" in workflow
    assert "<!-- codex-review-head:$REVIEW_HEAD_SHA -->" in workflow
    assert "github.event.issue.pull_request != null" in workflow
    assert "github.event.comment.user.login == 'chatgpt-codex-connector[bot]'" in workflow
    assert "github.event.comment.user.id == 199175422" in workflow
    assert "github.event.comment.user.type == 'Bot'" in workflow
    assert "Codex Review: Didn't find any major issues." in workflow
    assert "reviewed_head_prefix" in workflow
    assert '"$reviewed_head_prefix"*) matching_heads+=' in workflow
    assert '"${#matching_heads[@]}" -ne 1' in workflow
    assert "<!-- codex-clean-head:$reviewed_head_sha -->" in workflow
    assert "invalidate-non-clean-review:" in workflow
    assert "github.event.review.commit_id" in workflow
    assert "needs.capture-clean-review.outputs.clean == 'true'" in workflow
    assert "for _ in $(seq 1 12)" in workflow
    assert "permissions: {}" in workflow
    assert "checks: read" in workflow
    assert "--json name,bucket" in workflow
    assert "workflow_run will retry" in workflow
    assert "revalidate_latest_codex_result" in workflow
    assert 'repos/$GH_REPO/pulls/$PR_NUMBER/reviews' in workflow
    assert 'repos/$GH_REPO/issues/$PR_NUMBER/events' in workflow
    assert 'A newer Codex review contains findings.' in workflow
    assert 'blocked_head_prefix' in workflow
    assert 'stale_marker="<!-- codex-clean-head:$blocked_head_sha -->"' in workflow
    assert 'trusted_clean_marker_count' in workflow
    assert 'latest_non_clean_comment_at' in workflow
    assert 'The clean Codex authorization marker was invalidated.' in workflow
    assert 'The pull request was reopened after its clean Codex review.' in workflow
    assert "Revalidate, schedule deployment, and merge" in workflow
    assert 'if [ "$current_head_sha" != "$REVIEWED_HEAD_SHA" ]' in workflow
    assert '--match-head-commit "$REVIEWED_HEAD_SHA"' in workflow
    assert "--squash" in workflow
    assert "actions: write" in workflow
    assert "gh workflow run deploy-production.yml" in workflow
    assert '-f pull_request_number="$PR_NUMBER"' in workflow
    assert '-f reviewed_head_sha="$REVIEWED_HEAD_SHA"' in workflow


def test_server_deployer_enforces_traceable_release_safety() -> None:
    deployer = (REPO_ROOT / "deploy/server/gate-challenger-deploy").read_text()

    required_safety_controls = (
        "flock -n",
        "requested SHA is not the current origin/main",
        "pg_dump",
        "alembic upgrade head",
        "python -m app.seeds.skills",
        "health_check",
        "rollback_release",
        "restored the previous active release pointer",
    )

    for control in required_safety_controls:
        assert control in deployer


def test_restricted_ssh_entrypoint_accepts_only_a_commit_sha() -> None:
    entrypoint = (
        REPO_ROOT / "deploy/server/gate-challenger-deploy-entrypoint"
    ).read_text()

    assert "SSH_ORIGINAL_COMMAND" in entrypoint
    assert "^deploy\\ ([0-9a-f]{40})$" in entrypoint
    assert "exec sudo -n /usr/local/sbin/gate-challenger-deploy" in entrypoint
