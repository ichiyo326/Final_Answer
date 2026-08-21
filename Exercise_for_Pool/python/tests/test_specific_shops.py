"""
test_specific_shops.py

本間さんのフィードバックで名指しされた2店舗を個別に実行し、期待値と突き合わせるスクリプト。

  - LIGNOSA CAFE (https://r.gnavi.co.jp/n814504/)
      期待値: URL=http://lignosa.com/ 相当, メール=info@lignosa.com
  - クラフトビール×バル Beer Bar Ma Maison チカマチラウンジ店 (https://r.gnavi.co.jp/n000418/)
      期待値: 「お店に直接メールする」からメール=feelat@ma-maison.co.jp

1-1.py / 2-2.py と同じ gnavi_requests_scraper.parse_detail_page() をそのまま使うため、
本番の1-1.py/2-2.pyと全く同じロジックで検証できる。

実行方法:
  cd python/ex1_web-scraping  （または python/ 配下ならどこでもよい）
  python3 ../tests/test_specific_shops.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gnavi_requests_scraper as scraper  # noqa: E402

TARGET_SHOPS = [
    {
        "name": "LIGNOSA CAFE",
        "url": "https://r.gnavi.co.jp/n814504/",
        "expected_email": "info@lignosa.com",
        "expected_url_contains": "lignosa.com",
    },
    {
        "name": "クラフトビール×バル Beer Bar Ma Maison チカマチラウンジ店",
        "url": "https://r.gnavi.co.jp/n000418/",
        "expected_email": "feelat@ma-maison.co.jp",
        "expected_url_contains": None,  # 本間さんのフィードバックにURLの期待値記載なし
    },
]


def main():
    session = requests.Session()
    all_ok = True

    for shop in TARGET_SHOPS:
        print(f"\n===== {shop['name']} =====")
        print(f"URL: {shop['url']}")
        log_rows = []
        record = scraper.parse_detail_page(session, shop["url"], log_rows)

        if record is None:
            print("[NG] 詳細ページの取得自体に失敗しました。")
            all_ok = False
            continue

        print(f"  店舗名       : {record['店舗名']}")
        print(f"  メールアドレス : {record['メールアドレス']!r}")
        print(f"  URL          : {record['URL']!r}")
        print(f"  SSL          : {record['SSL']}")
        if log_rows:
            log = log_rows[0]
            print(f"  homepage_label : {log.get('homepage_label')}")
            print(f"  gnavi_url      : {log.get('gnavi_url')}")
            print(f"  accessed_url   : {log.get('accessed_url')}")
            print(f"  adopted_reason : {log.get('adopted_reason')}")
            print(f"  fail_reason    : {log.get('fail_reason')}")
            print(f"  ssl_reason     : {log.get('ssl_reason')}")

        email_ok = record["メールアドレス"] == shop["expected_email"]
        status = "[OK]" if email_ok else "[NG]"
        print(f"{status} メールアドレス期待値一致: 期待={shop['expected_email']!r} 実際={record['メールアドレス']!r}")
        all_ok = all_ok and email_ok

        if shop["expected_url_contains"]:
            url_ok = shop["expected_url_contains"] in (record["URL"] or "")
            status = "[OK]" if url_ok else "[NG]"
            print(f"{status} URL期待値一致: 「{shop['expected_url_contains']}」を含むか -> {record['URL']!r}")
            all_ok = all_ok and url_ok

    print()
    if all_ok:
        print("全店舗で期待値と一致しました。")
    else:
        print("一致しない項目がありました。上のログ（特にadopted_reason/fail_reason）を確認してください。")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
