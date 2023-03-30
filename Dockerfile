FROM python:3.10-bullseye

#   sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list #服务器在海外请添加这行到一下RUN开头
RUN apt-get update && \
    apt-get install -y \
        libnss3 \
        libnspr4 \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libcups2 \
        libdrm2 \
        libdbus-1-3 \
        libatspi2.0-0 \
        libxcomposite1 \
        libxdamage1 \
        libxfixes3 \
        libxrandr2 \
        libgbm1 \
        libxkbcommon0 \
        libasound2 \
        curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /xiaomai-bot

COPY . .

RUN mkdir /usr/share/fonts/zh

ADD ./statics/fonts/simhei.ttf /usr/share/fonts/zh
RUN chmod 644 /usr/share/fonts/zh/simhei.ttf && \
    fc-cache -fv && \
    fc-list

RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip install --upgrade pip \
    pip install poetry && \
    cd /xiaomai-bot && \
    poetry config installer.max-workers 10 && \
    poetry install --no-root --only main

RUN apt-get clean && \
    rm -rf /var/cache/apt/archives/* /var/lib/apt/lists/* /tmp/* /var/tmp/*

#   声明这个镜像服务的守护端口,以方便配置映射
EXPOSE 4000

ENTRYPOINT ["/root/.local/bin/poetry", "run", "python", "main.py"]

