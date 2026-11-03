FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.5.14 /uv /usr/local/bin/uv

WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY safe_ftp.py safe_ftp_format.py safe_ftp_install.py safe_ftp_mcp.py ./
RUN uv pip install --system --no-cache . && rm -rf /src

# Credentials live in $HOME/.safe_ftp_deploy. Mount a volume there to keep them.
RUN useradd --create-home --uid 1000 app
USER app
WORKDIR /work

ENTRYPOINT ["safe-ftp-deploy"]
CMD ["--help"]
