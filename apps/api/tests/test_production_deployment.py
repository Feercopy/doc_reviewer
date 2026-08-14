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
    assert 'command: ["python", "supervisor.py"]' in compose
    assert "document-worker:" not in compose
    assert "replicas: ${ANALYSIS_WORKER_REPLICAS:-2}" in compose


def test_production_compose_uses_pinned_managed_gate_challenger_source() -> None:
    compose = (REPO_ROOT / "infra/docker-compose.prod.yml").read_text()
    revision = "3447f867987d8727cbbd16e8874c60f2b1ed07d0"
    managed_checkout = (
        "/var/lib/gate-challenger/storage/external/gate-challenger-"
        + "${GATE_CHALLENGER_MANAGED_REF:-"
        + revision
        + "}"
    )

    assert "GATE_CHALLENGER_SOURCE_PATH: ${GATE_CHALLENGER_SOURCE_PATH:-" not in compose
    assert compose.count("GATE_CHALLENGER_SOURCE_PATH: ${GATE_CHALLENGER_MANAGED_PATH:-") == 2
    assert compose.count(
        "GATE_CHALLENGER_MANAGED_REPO_URL: "
        "${GATE_CHALLENGER_MANAGED_REPO_URL:-https://github.com/"
        "Ilya-eremenko/Gate2-challenger-skill.git}"
    ) == 2
    assert compose.count(
        f"GATE_CHALLENGER_MANAGED_REF: ${{GATE_CHALLENGER_MANAGED_REF:-{revision}}}"
    ) == 2
    assert compose.count(f"gate-challenger-${{GATE_CHALLENGER_MANAGED_REF:-{revision}}}") == 4
    benchmark_setting = (
        "GATE2_BENCHMARK_DIR: ${GATE2_BENCHMARK_DIR:-${GATE_CHALLENGER_MANAGED_PATH:-"
        + managed_checkout
        + "}/benchmark}"
    )
    assert compose.count(benchmark_setting) == 2


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


def test_server_deployer_seeds_new_skills_before_exposing_new_release() -> None:
    deployer = (REPO_ROOT / "deploy/server/gate-challenger-deploy").read_text()

    point_current = 'point_current_at "$release_dir"'
    quiesce_services = 'quiesce_application_services "$previous_dir"'
    activation_attempted = 'skills_seeded="true"'
    seed_command = 'seed_baseline_skills_for "$release_dir"'
    recreate_services = 'recreate_application_services "$release_dir"'

    assert deployer.index(point_current) < deployer.index(quiesce_services)
    assert deployer.index(quiesce_services) < deployer.index(activation_attempted)
    assert deployer.index(activation_attempted) < deployer.index(seed_command)
    assert deployer.index(seed_command) < deployer.index(recreate_services)


def test_server_deployer_restores_previous_skill_version_during_rollback() -> None:
    deployer = (REPO_ROOT / "deploy/server/gate-challenger-deploy").read_text()

    rollback_start = deployer.index("rollback_release()")
    quiesce_failed_release = 'quiesce_application_services "$release_dir"'
    restore_skill = 'seed_baseline_skills_for "$previous_dir"'
    restore_failure = "previous baseline skill restore failed"
    recreate_services = 'recreate_application_services "$previous_dir"'

    assert deployer.index(quiesce_failed_release, rollback_start) < deployer.index(
        restore_skill,
        rollback_start,
    )
    assert deployer.index(restore_skill, rollback_start) < deployer.index(recreate_services, rollback_start)
    failure_index = deployer.index(restore_failure, rollback_start)
    assert failure_index < deployer.index("exit 1", failure_index) < deployer.index(
        recreate_services,
        rollback_start,
    )


def test_restricted_ssh_entrypoint_accepts_only_a_commit_sha() -> None:
    entrypoint = (
        REPO_ROOT / "deploy/server/gate-challenger-deploy-entrypoint"
    ).read_text()

    assert "SSH_ORIGINAL_COMMAND" in entrypoint
    assert "^deploy\\ ([0-9a-f]{40})$" in entrypoint
    assert "exec sudo -n /usr/local/sbin/gate-challenger-deploy" in entrypoint
