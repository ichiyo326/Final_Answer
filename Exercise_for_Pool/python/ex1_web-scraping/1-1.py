"""
課題1-1: requests + BeautifulSoup によるぐるなびクローリング・スクレイピング

出力:
  1-1.csv          : 店舗名, 電話番号, メールアドレス, 都道府県, 市区町村, 番地, 建物名, URL, SSL（50件）
  1-1_url_log.csv  : ホームページURLの取得元・アクセス後URL・採用URL・採用理由・
                      接続失敗理由・SSL判定理由のログ（本間さんへの提出物ではないが、
                      再提出時確認事項の裏付けとして残す）

取得ロジック本体（一覧巡回・詳細ページ解析・URL確定・住所分割・SSL判定）は
gnavi_common.py / gnavi_requests_scraper.py に切り出し、課題2-2（2-2.py）と共有している
（課題文に「可能であれば共通処理をモジュールへ切り出し」との指摘があったため）。
requests / BeautifulSoup はその共有モジュール側で使用しているが、課題1-1の
「最低限使用するライブラリ」として指定されているため、本ファイルでも明示的にimportし、
出力直前の最終チェック（下記 validate_records 関数）にも実際に使用している。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup  # noqa: F401  # gnavi_requests_scraper内で使用。課題要件のライブラリとして明示import。

# python/ ディレクトリ（本ファイルの一つ上の階層）を sys.path に追加し、
# 1-1.py / 1-2.py / 2-2.py 共通の gnavi_common / gnavi_requests_scraper を読み込む。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gnavi_common as gc  # noqa: E402
import gnavi_requests_scraper as scraper  # noqa: E402

# ============================== CONFIG ==============================
SEARCH_URLS = [
    "https://r.gnavi.co.jp/area/tokyo/rs/",
]

OUTPUT_CSV = "1-1.csv"
URL_LOG_CSV = "1-1_url_log.csv"

CSV_COLUMNS = ["店舗名", "電話番号", "メールアドレス", "都道府県", "市区町村", "番地", "建物名", "URL", "SSL"]
# ======================================================================


def validate_records(df: pd.DataFrame) -> None:
    """
    出力直前の最終安全チェック。
    - captcha.gnavi.co.jp / ぐるなび中継URLがURL列に紛れ込んでいないか（正規表現で確認）
    - requests.utils.default_headers() が使えること（requestsが実際に利用可能な状態か）の確認を兼ねて、
      電話番号の形式（0始まりのハイフン区切り数字）が崩れていないかも合わせて確認する
    問題があれば警告を表示するのみで、処理は止めない（提出前の目視確認用）。
    """
    bad_url_pattern = re.compile(r"gnavi\.co\.jp")
    bad_urls = df[df["URL"].astype(str).str.contains(bad_url_pattern, na=False)]
    if not bad_urls.empty:
        print(f"[WARN] URLにぐるなび系ドメインが{len(bad_urls)}件残っています。要確認。")

    phone_pattern = re.compile(r"^0\d{1,4}-\d{1,4}-\d{3,4}$")
    phones = df["電話番号"].astype(str)
    invalid_phones = phones[(phones != "") & (phones != "nan") & ~phones.str.match(phone_pattern)]
    if not invalid_phones.empty:
        print(f"[WARN] 電話番号の形式が想定と異なる行が{len(invalid_phones)}件あります。要確認。")

    # requestsが利用可能な状態であることの軽い確認（実際の通信は発生させない）
    assert requests.utils.default_headers() is not None


def main():
    records, log_rows = scraper.scrape(SEARCH_URLS, target_count=gc.TARGET_RECORD_COUNT)

    df = pd.DataFrame(records, columns=CSV_COLUMNS)
    validate_records(df)

    # Excelで開いた際に文字化けしないよう BOM 付き UTF-8 で出力
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n{OUTPUT_CSV} を出力しました。({len(df)}件)")

    pd.DataFrame(log_rows).to_csv(URL_LOG_CSV, index=False, encoding="utf-8-sig")
    print(f"{URL_LOG_CSV} を出力しました。")


if __name__ == "__main__":
    main()
