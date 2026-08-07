# 課題2: Docker & DB

## ファイル対応表

| ファイル | 内容 |
|---|---|
| `Dockerfile` | 課題2-1の環境構築用（Ubuntu20.04 + Python3.8 + MySQL8.0） |
| `docker-compose.yml` | 上記の起動設定 |
| `docker-entrypoint.sh` | コンテナ起動時にMySQLを起動しDB/ユーザーを作成 |
| `requirements.txt` | コンテナ内にインストールするpythonライブラリ |
| `ex2-1.png` | 課題2-1の成果物（Ubuntu/Python/MySQLのバージョン確認） |
| `2-2.py` | 課題2-2のソースコード（スクレイピング結果をMySQLへ格納） |
| `ex2-2_count.png` | `select count(URL) from ex2_2;` の実行結果 |
| `ex2-2_columns.png` | `show columns from ex2_2;` の実行結果 |
| `ex2-2_table.png` | `select * from ex2_2 limit 5;` の実行結果 |

## 実行方法

```bash
docker compose build
docker compose up -d
docker compose exec ex2env bash
```

コンテナ内で:

```bash
cd /workspace
export MYSQL_HOST=localhost MYSQL_USER=scraper MYSQL_PASSWORD=scraper_pw
python3 2-2.py
```

DB名: `ex2` / テーブル名: `ex2_2`
