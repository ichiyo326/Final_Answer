#!/bin/bash
set -e

# systemdの無いコンテナ内なので、mysqldを手動で起動する。
service mysql start

# 初回起動時のみ ex2 データベースと、パスワード認証可能な作業用ユーザーを作成する。
# (Ubuntu標準のmysql-serverはデフォルトでrootがauth_socket認証のため、
#  Python(sqlalchemy)からパスワード接続する用にユーザーを作る)
mysql -u root <<'SQL'
CREATE DATABASE IF NOT EXISTS ex2 CHARACTER SET utf8mb4;
CREATE USER IF NOT EXISTS 'scraper'@'localhost' IDENTIFIED WITH mysql_native_password BY 'scraper_pw';
GRANT ALL PRIVILEGES ON ex2.* TO 'scraper'@'localhost';
FLUSH PRIVILEGES;
SQL

exec "$@"
