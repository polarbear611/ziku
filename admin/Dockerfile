# 字库后台镜像：web 和 worker 共用，只是启动命令不同
FROM docker.m.daocloud.io/library/python:3.12-slim
RUN sed -i 's@deb.debian.org@mirrors.ustc.edu.cn@g' /etc/apt/sources.list.d/debian.sources \
 && apt-get update && apt-get install -y --no-install-recommends libarchive-tools openssh-client rsync autossh curl fonts-noto-cjk libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*
ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ PIP_TRUSTED_HOST=mirrors.aliyun.com PIP_NO_CACHE_DIR=1
COPY v2/requirements.txt /app/v2/requirements.txt
RUN python -m venv /app/v2/venv && /app/v2/venv/bin/pip install -r /app/v2/requirements.txt \
 && pip install flask==3.0.3 gunicorn==22.0.0 qrcode==7.4.2
COPY v2/*.py v2/run_pages.sh v2/site_tpl.html v2/glyph_tpl.html /app/v2/
COPY admin/*.py admin/deploy.sh /app/admin/
RUN useradd -u 1004 -m zka && mkdir -p /data && chown -R zka /app/v2 /data
# 宋体估字高：Noto Serif CJK 的繁体字面（ttc 第 3 个 = TC）
ENV ZIKU_FONT=/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc ZIKU_FONT_INDEX=3 ZIKU_V2=/app/v2 ZKA_DATA=/data PYTHONUNBUFFERED=1
USER zka
WORKDIR /app/admin
