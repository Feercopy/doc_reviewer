.PHONY: test

PYTEST ?= .venv-backend/bin/pytest

test:
	@test -x "$(PYTEST)" || { echo "Missing pytest runner at $(PYTEST). Create the backend test venv first."; exit 2; }
	$(PYTEST) apps/api/tests apps/worker/tests -q
	npm --prefix apps/web run test
	npm --prefix apps/web run build
	docker compose -f infra/docker-compose.yml config >/dev/null
	npm --prefix apps/web run e2e
