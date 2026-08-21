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
| `2-2_scrape_backup.csv` | 課題2-2の実行結果バックアップCSV |
| `2-2_url_log.csv` | 課題2-2のホームページURL確定ログ |
| `ex2-2_count.png` | `select count(URL) from ex2_2;` の実行結果 |
| `ex2-2_columns.png` | `show columns from ex2_2;` の実行結果 |
| `ex2-2_table.png` | `select * from ex2_2 limit 5;` の実行結果 |
| `../gnavi_common.py` | 住所分割・メール取得・ホームページURL確定・SSL判定など、1-1/1-2/2-2共通のロジック（`docker-compose.yml`のvolumeで`/workspace`直下にマウントされる） |
| `../gnavi_requests_scraper.py` | requestsベースの一覧巡回・詳細ページ解析処理（1-1.pyと共有） |

## 実行方法

```bash
docker compose build
docker compose up -d
docker compose exec ex2env bash
```

コンテナ内で（`docker-compose.yml`のvolumeにより、リポジトリの `python/` ディレクトリが
`/workspace` に、本ファイルのある `ex2_docker/` は `/workspace/ex2_docker` にマウントされる）:

```bash
cd /workspace/ex2_docker
export MYSQL_HOST=localhost MYSQL_USER=scraper MYSQL_PASSWORD=scraper_pw
python3 2-2.py
```

DB名: `ex2` / テーブル名: `ex2_2`

※以前のREADMEでは `cd /workspace` からの実行手順になっていましたが、
`2-2.py` は `/workspace/ex2_docker/2-2.py` にあるため、上記の通り修正しています。
