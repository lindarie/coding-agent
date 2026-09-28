# Image in which the agent's run_command executes. Add whatever toolchains your projects need.
FROM python:3.12-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends nodejs npm git make \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir pytest ruff
WORKDIR /work
