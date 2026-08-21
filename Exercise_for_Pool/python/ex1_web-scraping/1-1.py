"""
課題1-1: requests + BeautifulSoup によるぐるなびクローリング・スクレイピング

出力:
  1-1.csv          : 店舗名, 電話番号, メールアドレス, 都道府県, 市区町村, 番地, 建物名, URL, SSL（50件）
  1-1_url_log.csv  : ホームページURLの取得元・アクセス後URL・採用URL・採用理由・
                      接続失敗理由・SSL判定理由のログ（本間さんへの提出物ではないが、
                      再提出時確認事項の裏付けとして残す）

取得ロジック（一覧巡回・詳細ページ解析・URL確定・住所分割・SSL判定）は
gnavi_common.py / gnavi_requests_scraper.py に切り出し、課題2-2（2-2.py）と共有している。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

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


def main():
    records, log_rows = scraper.scrape(SEARCH_URLS, target_count=gc.TARGET_RECORD_COUNT)

    df = pd.DataFrame(records, columns=CSV_COLUMNS)
    # Excelで開いた際に文字化けしないよう BOM 付き UTF-8 で出力
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n{OUTPUT_CSV} を出力しました。({len(df)}件)")

    pd.DataFrame(log_rows).to_csv(URL_LOG_CSV, index=False, encoding="utf-8-sig")
    print(f"{URL_LOG_CSV} を出力しました。")


if __name__ == "__main__":
    main()
