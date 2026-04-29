FROM python:3.11-slim

WORKDIR /app

# Install uv
RUN pip install uv

# Copy project metadata and lock file
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen

# Copy source code
COPY src/ ./src/

# Expose port
EXPOSE 8001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health', timeout=5)" || exit 1

# Run application
CMD ["uv", "run", "python", "-m", "uvicorn", "mock_abha.main:app", "--host", "0.0.0.0", "--port", "8001"]
