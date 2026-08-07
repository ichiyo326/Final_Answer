# 課題2-1・2-2用: Ubuntu20.04 + Python3.8 + MySQL を1コンテナに同梱
# 「1コンテナにまとめなくてもよい」とのことだが、Ubuntu/Python/MySQLの
# バージョンを1枚のスクリーンショットに収める(ex2-1.png)には、
# 同一シェルで cat /etc/issue / python3 --version / mysql --version が
# 実行できるこの構成が一番簡単。

FROM ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Tokyo

# Ubuntu20.04標準リポジトリの python3 は 3.8系、mysql-server は 8.0系。
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        mysql-server \
        curl \
        wget \
        vim \
        ca-certificates \
        gnupg \
        unzip \
    && rm -rf /var/lib/apt/lists/*

# Chrome/chromedriverが必要な場合（課題1-2/2-2でselenium利用時）にホスト側で
# 用意したchromedriverをコンテナへ持ち込めるよう /workspace をそのまま使う。
WORKDIR /workspace

COPY requirements.txt /workspace/requirements.txt
RUN pip3 install --no-cache-dir -r /workspace/requirements.txt

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["/bin/bash"]
