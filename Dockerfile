FROM python:3.14-slim-bookworm

ENV DISPLAY=:99
ENV PYTHONUNBUFFERED=1

RUN sed -i 's|http://deb.debian.org/debian-security|https://security.debian.org/debian-security|g' /etc/apt/sources.list.d/debian.sources \
    && sed -i 's|http://deb.debian.org/debian|https://ftp.debian.org/debian|g' /etc/apt/sources.list.d/debian.sources \
    && printf 'Acquire::http::No-Cache "true";\nAcquire::https::No-Cache "true";\nAcquire::http::Pipeline-Depth "0";\n' > /etc/apt/apt.conf.d/99nocache \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        xvfb \
        ca-certificates \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt \
    && patchright install chrome

COPY . .

RUN chmod +x docker_entrypoint.sh

EXPOSE 8080

CMD ["./docker_entrypoint.sh"]