REGISTRY   ?= ghcr.io
IMAGE_REPO ?= $(shell whoami)/adaptive-discovery
IMAGE_TAG  ?= latest
FULL_IMAGE  = $(REGISTRY)/$(IMAGE_REPO):$(IMAGE_TAG)

COMPOSE_DIR = adaptive-network-analyzer
COMPOSE     = docker compose \
                -f $(COMPOSE_DIR)/docker-compose.yml \
                --env-file .env \
                --project-directory $(COMPOSE_DIR)

.PHONY: help setup build push up down restart logs dashboard clean

help:
	@echo "Targets:"
	@echo "  setup      Bootstrap environment (copy .env, create dirs)"
	@echo "  build      Build the discovery daemon image"
	@echo "  push       Tag and push image to $(REGISTRY)"
	@echo "  up         Start the full stack"
	@echo "  down       Stop and remove containers"
	@echo "  restart    Restart the discovery daemon only"
	@echo "  logs       Follow logs from all containers"
	@echo "  dashboard  Regenerate Grafana dashboard JSON"
	@echo "  dashboard-push  Regenerate and push to live Grafana"
	@echo "  clean      Remove containers, volumes, and built images"

setup:
	@bash scripts/setup.sh

build:
	docker build \
		--pull \
		--no-cache \
		-t $(FULL_IMAGE) \
		-f $(COMPOSE_DIR)/discovery/Dockerfile \
		$(COMPOSE_DIR)/discovery/

push: build
	docker push $(FULL_IMAGE)

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) restart adaptive-discovery

logs:
	$(COMPOSE) logs -f

dashboard:
	python3 $(COMPOSE_DIR)/grafana/create_dashboard.py

dashboard-push:
	python3 $(COMPOSE_DIR)/grafana/create_dashboard.py --push

clean:
	$(COMPOSE) down -v --rmi local
	docker image prune -f
