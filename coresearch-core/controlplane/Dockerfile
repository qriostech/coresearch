FROM python:3.13-slim

ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY coresearch-core/controlplane/ ./controlplane/
COPY coresearch-core/connections/ ./connections/
COPY coresearch-core/shared/ ./shared/

RUN useradd -m -s /bin/bash coresearch && \
    chown -R coresearch:coresearch /app /home/coresearch

USER coresearch

CMD ["uvicorn", "controlplane.api:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
