FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Docker CLI only (talks to the host daemon through the mounted socket).
COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker

WORKDIR /srv
COPY apps/agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY apps/agent/app ./app

ENV WORKSPACE_ROOT=/workspace DB_PATH=/data/agent.db PYTHONUNBUFFERED=1
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request as u; u.urlopen('http://localhost:8000/api/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
