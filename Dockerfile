FROM python:3.11-slim@sha256:6f31d6e9ba2b0a787a3f81c37b004155b87b9efa1b771182bd550c1615745be5
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TF_NUM_INTRAOP_THREADS=1 TF_NUM_INTEROP_THREADS=1 OMP_NUM_THREADS=1
WORKDIR /app
COPY pyproject.toml ./
RUN python -c "import tomllib, subprocess; deps=tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']; subprocess.check_call(['pip','install','--no-cache-dir',*deps])" && useradd --uid 10001 --create-home app
COPY src ./src
RUN pip install --no-cache-dir --no-deps .
ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=$GIT_COMMIT
USER 10001:10001
ENTRYPOINT ["air-quality"]
CMD ["--help"]
