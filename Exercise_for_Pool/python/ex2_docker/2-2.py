"""
課題2-2: ぐるなびスクレイピング結果を MySQL (database: ex2, table: ex2_2) へ格納する

requests + BeautifulSoup でスクレイピングし、sqlalchemy + pandas で MySQL に書き込む。
Dockerコンテナ内のPython3.8環境で実行することを想定。

取得ロジック（一覧巡回・詳細ページ解析・URL確定・住所分割・SSL判定）は課題1-1（1-1.py）と
同じ gnavi_common.py / gnavi_requests_scraper.py を使用し、判定基準がずれないようにしている。
requests / BeautifulSoup はその共有モジュール側で使用しているが、課題2-2の
「使用するpythonのライブラリ」として requests(またはselenium) が明示指定されているため、
本ファイルでも明示的にimportしている。re は、MySQLのテーブル名・DB名をSQL文へ
文字列展開する箇所（下記 get_engine / main 内）で、意図しない文字列が紛れ込んでいないかを
検証する用途で実際に使用している。

出力:
  MySQL ex2.ex2_2         : 店舗名, 電話番号, メールアドレス, 都道府県, 市区町村, 番地, 建物名, URL, SSL（50件）
  2-2_scrape_backup.csv   : 上記と同内容のバックアップCSV
  2-2_url_log.csv         : ホームページURLの取得元・アクセス後URL・採用URL・採用理由・
                             接続失敗理由・SSL判定理由のログ

事前準備:
  - MySQLに database `ex2` を作成しておく
  - 接続情報は環境変数 (MYSQL_HOST / MYSQL_USER / MYSQL_PASSWORD) から読む

実行方法（Dockerコンテナ内、リポジトリでは /workspace/ex2_docker が本ファイルの場所）:
  cd /workspace/ex2_docker
  python3 2-2.py
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pandas as pd
import requests  # noqa: F401  # gnavi_requests_scraper内で使用。課題要件のライブラリとして明示import。
from bs4 import BeautifulSoup  # noqa: F401  # 同上
from sqlalchemy import create_engine, text

# python/ ディレクトリ（本ファイルの一つ上の階層。Docker上では /workspace）を
# sys.path に追加し、1-1.py / 1-2.py と共通の gnavi_common / gnavi_requests_scraper を読み込む。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gnavi_common as gc  # noqa: E402
import gnavi_requests_scraper as scraper  # noqa: E402

# ============================== CONFIG ==============================
SEARCH_URLS = [
    "https://r.gnavi.co.jp/area/tokyo/rs/",
]

MYSQL_HOST = os.environ.get("MYSQL_HOST", "localhost")
MYSQL_PORT = os.environ.get("MYSQL_PORT", "3306")
MYSQL_USER = os.environ.get("MYSQL_USER", "root")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "")
MYSQL_DB = "ex2"
MYSQL_TABLE = "ex2_2"

BACKUP_CSV = "2-2_scrape_backup.csv"
URL_LOG_CSV = "2-2_url_log.csv"

CSV_COLUMNS = ["店舗名", "電話番号", "メールアドレス", "都道府県", "市区町村", "番地", "建物名", "URL", "SSL"]

# DB名・テーブル名としてSQL文へ直接埋め込んでよい文字列かどうかの検証パターン
# （英数字とアンダースコアのみ許可。SQLインジェクション対策の簡易チェック）
SAFE_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")
# ======================================================================


def validate_sql_identifier(name: str, label: str) -> None:
    """DB名・テーブル名をSQL文字列へ直接埋め込む前に、安全な識別子かを正規表現で確認する。"""
    if not SAFE_IDENTIFIER_PATTERN.match(name):
        raise ValueError(f"{label}に使用できない文字が含まれています: {name!r}")


def get_engine():
    validate_sql_identifier(MYSQL_DB, "MYSQL_DB")
    url = (
        f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}"
        f"@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}?charset=utf8mb4"
    )
    return create_engine(url)


def main():
    validate_sql_identifier(MYSQL_TABLE, "MYSQL_TABLE")

    records, log_rows = scraper.scrape(SEARCH_URLS, target_count=gc.TARGET_RECORD_COUNT)

    df = pd.DataFrame(records, columns=CSV_COLUMNS)

    # バックアップCSV（MySQL格納に失敗した場合の切り分け・提出前確認用）
    df.to_csv(BACKUP_CSV, index=False, encoding="utf-8-sig")
    print(f"\n{BACKUP_CSV} を出力しました。({len(df)}件)")
    pd.DataFrame(log_rows).to_csv(URL_LOG_CSV, index=False, encoding="utf-8-sig")
    print(f"{URL_LOG_CSV} を出力しました。")

    engine = get_engine()
    df.to_sql(MYSQL_TABLE, con=engine, if_exists="replace", index=False)
    print(f"\nMySQL {MYSQL_DB}.{MYSQL_TABLE} へ {len(df)} 件を格納しました。")

    with engine.connect() as conn:
        count = conn.execute(text(f"SELECT COUNT(URL) FROM {MYSQL_TABLE};")).scalar()
        print(f"SELECT COUNT(URL) FROM {MYSQL_TABLE}; -> {count}")


if __name__ == "__main__":
    main()
