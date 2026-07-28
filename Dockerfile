FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy project files
COPY pyproject.toml README.md ./
COPY google ./google
COPY main.py sagemath_mcp_server.py model_armor.py mcp_config.json ./
COPY specs ./specs

# Install dependencies using uv
RUN uv sync --frozen || uv pip install --system -e .

EXPOSE 8080

CMD ["python", "main.py"]
