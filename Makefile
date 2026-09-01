.PHONY: help start stop restart build rebuild logs shell clean status

# Default target
help:
	@echo "Available commands:"
	@echo "  make start    - Start the bot in detached mode"
	@echo "  make stop     - Stop the bot"
	@echo "  make restart  - Restart the bot"
	@echo "  make build    - Build the Docker image"
	@echo "  make rebuild  - Rebuild the Docker image (no cache)"
	@echo "  make logs     - Show bot logs (follow mode)"
	@echo "  make shell    - Open shell in the bot container"
	@echo "  make clean    - Stop and remove containers, networks, volumes"
	@echo "  make status   - Show container status"

# Start the bot
start:
	docker-compose up -d

# Stop the bot
stop:
	docker-compose down

# Restart the bot
restart: stop start

# Build the Docker image
build:
	docker-compose build

# Rebuild the Docker image without cache
rebuild:
	docker-compose build --no-cache

# Show logs in follow mode
logs:
	docker-compose logs -f bot

# Open shell in the bot container
shell:
	docker-compose exec bot /bin/bash

# Clean up everything
clean:
	docker-compose down -v --remove-orphans
	docker system prune -f

# Show container status
status:
	docker-compose ps
