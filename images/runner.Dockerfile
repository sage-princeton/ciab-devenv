FROM ubuntu:24.04@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv git nodejs npm ca-certificates curl shellcheck openssl unzip jq \
    && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY --from=scaffold requirements.txt /tmp/scaffold-requirements.txt
RUN pip install --no-cache-dir -r /tmp/scaffold-requirements.txt \
    pytest==8.4.2 ruff==0.14.1
RUN case "$(uname -m)" in aarch64) arch=aarch64 ;; x86_64) arch=x86_64 ;; esac \
    && curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-${arch}-2.38.1.zip" -o /tmp/aws.zip \
    && unzip -q /tmp/aws.zip -d /tmp && /tmp/aws/install \
    && rm -rf /tmp/aws /tmp/aws.zip
RUN mkdir /work && chown ubuntu:ubuntu /work
USER ubuntu
WORKDIR /work
ENV PYTHONPATH=/source/src/sdk-scaffold:/devenv
ENTRYPOINT ["python", "/devenv/services/runner.py"]
