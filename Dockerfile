FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.lock pyproject.toml README.md ./
RUN python -m pip install -r requirements.lock
COPY src ./src
RUN python -m pip install --no-build-isolation --no-deps . \
    && python -m compileall -q /app/src \
    && useradd --uid 10001 --create-home repolens \
    && mkdir -p /var/lib/repolens /workspace /run/repolens-render \
    && chown -R repolens:repolens /var/lib/repolens /run/repolens-render \
    && chmod 700 /run/repolens-render
USER repolens
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "repolens.main:application", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
