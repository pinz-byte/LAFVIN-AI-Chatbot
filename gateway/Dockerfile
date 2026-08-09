FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY symbios_gateway ./symbios_gateway
RUN apt-get update \
    && apt-get install --yes --no-install-recommends libopus0 \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 gateway \
    && mkdir -p /data \
    && chown gateway:gateway /data
USER gateway

EXPOSE 8080
CMD ["uvicorn", "symbios_gateway.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
