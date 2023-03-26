FROM python:3.10.10
RUN mkdir /xiaomai-bot
WORKDIR /xiaomai-bot
ADD . /xiaomai-bot
# 修改作图中文字体
ADD ./statics/fonts/ArialEnUnicodeBold.ttf /usr/share/fonts/zh
RUN chmod 777 /usr/share/fonts/zh/ArialEnUnicodeBold.ttf && \
    fc-cache -f && \
    fc-list
RUN apt update -y && \
    apt-get install -y libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libdbus-1-3 libatspi2.0-0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libxkbcommon0 libasound2  && \
    curl -sSL https://install.python-poetry.org | python3 - && \
#   sed 's/pypi.tuna.tsinghua.edu.cn/pypi.org/g' poetry.lock && \ #服务器在海外请取消注释掉这行
    /root/.local/bin/poetry install  --no-root
RUN apt clean && \
    rm -rf /var/lib/apt/lists/*
ENTRYPOINT ["/root/.local/bin/poetry", "run", "python", "main.py"]