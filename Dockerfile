FROM python:3.12-slim@sha256:dd29372629eeba2dd003fd9e9d35a5b8236c44727875a0364254b5127af88e65 AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 BROODBENCH_DATA=/data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home bench && mkdir /data && chown bench:bench /data
COPY *.py ./
COPY static ./static
USER 10001:10001
EXPOSE 8798
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8798/api/health',timeout=3)"
CMD ["uvicorn","app:app","--host","0.0.0.0","--port","8798","--no-access-log"]

FROM runtime AS test
USER root
RUN pip install --no-cache-dir pytest==8.3.5
COPY tests ./tests
USER 10001:10001
CMD ["python","-m","pytest","tests","--ignore=tests/test_browser.py","-q","-p","no:cacheprovider"]

FROM runtime AS final
