FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LOG_DIR=/app/logs

WORKDIR /app

# Docker CLI only (no daemon) so the dashboard can run `docker inspect` against the
# host through the mounted /var/run/docker.sock.
COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py data_loader.py analytics.py app.py generate_sample_data.py ./
COPY .streamlit .streamlit

RUN mkdir -p /app/logs

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request as u; u.urlopen('http://localhost:8501/_stcore/health', timeout=3)"

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
