# syntax=docker/dockerfile:1

FROM node:24-alpine AS ui-build
WORKDIR /app/ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build

FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=5678
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Optional: Newman for qa.runCollection (no Postman login required).
# Enable with: docker compose build --build-arg INSTALL_NEWMAN=true
ARG INSTALL_NEWMAN=false
RUN if [ "$INSTALL_NEWMAN" = "true" ]; then \
        apt-get update && \
        apt-get install -y --no-install-recommends nodejs npm && \
        npm install -g newman && \
        rm -rf /var/lib/apt/lists/*; \
    fi

COPY backend ./backend
COPY examples ./examples
COPY --from=ui-build /app/ui/dist ./ui/dist

RUN mkdir -p /app/data
VOLUME ["/app/data"]
EXPOSE 5678

CMD ["uvicorn", "app:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "5678"]
