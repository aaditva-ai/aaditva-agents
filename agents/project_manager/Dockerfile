# Use the official Python base image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies + Node.js (required for notion-mcp-server)
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g @notionhq/notion-mcp-server@1.9.1

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy pyproject.toml and uv.lock first for better layer caching
COPY pyproject.toml uv.lock ./

# Install Python dependencies, pinned exactly to the committed lock
RUN uv sync --frozen --no-install-project --no-dev

# Copy application code
COPY . .

# Install the project itself against the same frozen lock (build time, not runtime)
RUN uv sync --frozen --no-dev

# Create a non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
ENV HOST=0.0.0.0

# Expose the port Cloud Run will use
EXPOSE 8080

# Run the A2A server without re-checking/syncing the venv - it's already fully materialized
CMD ["uv", "run", "--no-sync", "python", "agent.py"]
