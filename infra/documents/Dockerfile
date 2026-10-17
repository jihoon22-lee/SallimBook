# Dedicated linux/amd64 inspection integration image; no production service is replaced.
FROM python:3.14.7-slim-trixie@sha256:7bf6c3111fe094f8ee1a1cbcdc63c4cfb345b0e3df42d5aa9a90b3b4b022ab6d

# A dated, signed Debian snapshot fixes transitive apt inputs as well as tool versions.
RUN printf '%s\n' \
      'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/20261017T000000Z trixie main' \
      'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian-security/20261017T000000Z trixie-security main' \
      > /etc/apt/sources.list \
    && rm /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      poppler-utils=25.03.0-5+deb13u4 \
      tesseract-ocr=5.5.0-1+b1 \
      tesseract-ocr-eng=1:4.1.0-2 \
      tesseract-ocr-kor=1:4.1.0-2 \
      fonts-noto-cjk=1:20240730+repack1-1 \
    && rm -rf /var/lib/apt/lists/*

# Cisco's maintained 1.4.6 LTS patch, integrity-pinned to the official release digest.
ADD --checksum=sha256:d3ee9e401974855a1edc1761b1425417d126de618d5f0c91cd51209f69f6fcc2 https://github.com/Cisco-Talos/clamav/releases/download/clamav-1.4.6/clamav-1.4.6.linux.x86_64.deb /opt/clamav.deb
RUN dpkg -i /opt/clamav.deb && rm /opt/clamav.deb \
    && install -d -o 65534 -g 65534 /var/lib/clamav \
    && /usr/local/bin/clamscan --version

COPY infra/documents/requirements.txt /opt/sallimbook/requirements.txt
RUN python -m pip install --no-cache-dir --require-hashes -r /opt/sallimbook/requirements.txt
COPY infra/documents/freshclam.conf /etc/sallimbook/freshclam.conf
# Only official, signed ClamAV databases. The harness changes this cache key daily.
ARG SALLIMBOOK_CVD_REFRESH=2026-10-17
RUN test -n "$SALLIMBOOK_CVD_REFRESH" \
    && /usr/local/bin/freshclam --config-file=/etc/sallimbook/freshclam.conf --stdout \
    && chmod -R a+rX /var/lib/clamav
COPY infra/documents/clamd.conf /etc/sallimbook/clamd.conf
COPY services/api/src/sallimbook/core/errors.py /opt/sallimbook/sallimbook/core/errors.py
COPY services/api/src/sallimbook/documents/validation.py services/api/src/sallimbook/documents/_validation_worker.py /opt/sallimbook/sallimbook/documents/
COPY infra/documents/run_checks.py /opt/sallimbook/run_checks.py
ENV PYTHONPATH=/opt/sallimbook PYTHONDONTWRITEBYTECODE=1 TZ=Etc/UTC
WORKDIR /opt/sallimbook
USER 10001:10001
CMD ["python", "-B", "/opt/sallimbook/run_checks.py"]
