FROM python:3.11-slim
ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=$GIT_COMMIT PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TF_NUM_INTRAOP_THREADS=1 TF_NUM_INTEROP_THREADS=1 OMP_NUM_THREADS=1
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --uid 10001 --create-home app
USER 10001:10001
ENTRYPOINT ["air-quality"]
CMD ["--help"]

