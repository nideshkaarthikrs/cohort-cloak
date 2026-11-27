FROM python:3.11-slim-bookworm AS runtime
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py ./
COPY config/ ./config/
COPY cloak/ ./cloak/
COPY data/ ./data/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1
ENTRYPOINT ["python", "main.py"]

FROM runtime AS audit
COPY requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY tests/ ./tests/
COPY tools/ ./tools/
COPY docs/ ./docs/
COPY pytest.ini raksha.toml README.md ./
