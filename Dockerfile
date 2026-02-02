FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Copy project files
COPY pyproject.toml uv.lock ./
COPY src/ ./src/

# Install dependencies
RUN uv sync --frozen --no-dev

# Create downloads directory
RUN mkdir -p /app/downloads

EXPOSE 8000

CMD ["uv", "run", "dicom-mcp", "/app/configuration.yaml", "--transport", "sse"]
