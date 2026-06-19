# Slim image for the FastAPI ingest server. Build context is the REPO ROOT
# (`docker build -f cloud/server/Dockerfile .`) because the app imports from
# `cloud.shared.wire` which lives outside cloud/server/.
#
# For Railway:
#   - "Root Directory" in the service settings: leave empty / set to repo root
#   - "Dockerfile path": cloud/server/Dockerfile
#   - "Builder": Dockerfile

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Copy only what the server needs — keep the image small and avoid leaking
# the local CSV / aiobmsble deps that are only relevant on the reader Pi.
COPY cloud/server/requirements.txt /app/cloud/server/requirements.txt
RUN pip install -r /app/cloud/server/requirements.txt

COPY cloud /app/cloud

# Railway sets $PORT at runtime — bind to it.
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn cloud.server.main:app --host 0.0.0.0 --port ${PORT}"]
