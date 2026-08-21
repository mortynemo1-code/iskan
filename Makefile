.PHONY: install up down logs test web-build simulate backup restore migrate monitoring

install:
	./install.sh

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

test:
	python3 -m pytest -q backend/tests

web-build:
	cd web && npm run build

simulate:
	@test -n "$(TOKEN)" || (echo "Usage: make simulate TOKEN=<INSTALLATION_TOKEN>" && exit 1)
	python3 scripts/simulate_agents.py --installation-token "$(TOKEN)" --agents 5

backup:
	./scripts/backup.sh

restore:
	@test -n "$(FILE)" || (echo "Usage: make restore FILE=backups/postgres-*.dump" && exit 1)
	WORKFORCE_CONFIRM_RESTORE=YES ./scripts/restore.sh "$(FILE)"

migrate:
	./scripts/apply_migrations.sh

monitoring:
	docker compose --profile monitoring up -d prometheus loki promtail grafana
