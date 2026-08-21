"""
hunt_for_real_edge_cases.py

本番の50件はたまたま全て「正常アクセス」だったため、CAPTCHA/接続失敗/SSL失敗の
本物のケースが1件も含まれていなかった。

このスクリプトは、複数エリア・より多くの店舗をスキャンし、
その中から実際に以下に該当した行だけを抜き出して報告する。

  - adopted_reason が final_url 以外（fallback_captcha / fallback_connection_error）
  - SSL が False

【注意】
- 本番のCAPTCHAは狙って発生させられないため、「見つかれば儲けもの」という位置づけ。
  0件のまま終わっても、それ自体は不具合の証拠にはならない
  （ぐるなびのボット対策に今回は引っかからなかった、というだけ）。
- AREA_URLS の各URLは実際にブラウザで開いて存在することを確認してから使うこと
  （このスクリプトを書いた側ではアクセスして確認できていないURLも含まれる）。
- 通常のスクレイピング課題より多くのリクエストを送るため、実行に時間がかかる
  （3秒待機 × リクエスト数）。TARGET_SCAN_COUNT で調整すること。

実行方法:
  cd python/ex1_web-scraping  （または python/ 配下ならどこでもよい）
  python3 ../tests/hunt_for_real_edge_cases.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gnavi_common as gc  # noqa: E402
import gnavi_requests_scraper as scraper  # noqa: E402

# ============================== CONFIG ==============================
# 複数エリアを混ぜることで、店舗の多様性を増やし、リンク切れ・接続失敗・
# CAPTCHA遭遇の可能性を上げる狙い。URLは実在確認済みのものだけ残すこと。
AREA_URLS = [
    "https://r.gnavi.co.jp/area/tokyo/rs/",
    "https://r.gnavi.co.jp/area/osaka/rs/",
    "https://r.gnavi.co.jp/area/kanagawa/rs/",
    "https://r.gnavi.co.jp/area/aichi/rs/",
    "https://r.gnavi.co.jp/area/fukuoka/rs/",
]

# 50件確保が目的ではなく「幅広くスキャンして例外ケースを探す」ことが目的なので、
# target_countを大きめに指定し、候補をできるだけ多く処理する。
TARGET_SCAN_COUNT = 150

OUTPUT_ALL_LOG_CSV = "edge_case_scan_full_log.csv"
OUTPUT_EDGE_CASES_CSV = "edge_case_scan_findings.csv"
# ======================================================================


def main():
    print(f"スキャン対象エリア数: {len(AREA_URLS)}")
    print(f"目標スキャン件数: {TARGET_SCAN_COUNT}")
    print("（3秒待機×多数のリクエストのため、時間がかかります）\n")

    records, log_rows = scraper.scrape(AREA_URLS, target_count=TARGET_SCAN_COUNT)

    log_df = pd.DataFrame(log_rows)
    log_df.to_csv(OUTPUT_ALL_LOG_CSV, index=False, encoding="utf-8-sig")
    print(f"\n{OUTPUT_ALL_LOG_CSV} に全ログを保存しました。（{len(log_df)}件）")

    if "adopted_reason" not in log_df.columns:
        print("[WARN] ログにadopted_reason列がありません。0件処理だった可能性があります。")
        return

    edge_cases = log_df[
        (log_df["adopted_reason"] != "final_url") | (log_df["ssl"] == False)  # noqa: E712
    ].copy()

    if edge_cases.empty:
        print("\n本物のCAPTCHA/接続失敗/SSL失敗ケースは見つかりませんでした。")
        print("（スキャン件数を増やす、別エリアを試す、時間を置いて再実行する、などで")
        print(" 遭遇確率を上げられる可能性がありますが、0件自体は不具合の証拠ではありません。）")
        return

    edge_cases.to_csv(OUTPUT_EDGE_CASES_CSV, index=False, encoding="utf-8-sig")
    print(f"\n[FOUND] 本物の例外ケースが {len(edge_cases)} 件見つかりました。")
    print(f"{OUTPUT_EDGE_CASES_CSV} に保存しました。\n")

    reason_counts = edge_cases["adopted_reason"].value_counts(dropna=False)
    print("内訳（adopted_reason）:")
    print(reason_counts.to_string())

    ssl_false = edge_cases[edge_cases["ssl"] == False]  # noqa: E712
    if len(ssl_false):
        print("\nSSL=False の内訳（ssl_reason）:")
        print(ssl_false["ssl_reason"].value_counts(dropna=False).to_string())

    print("\n詳細:")
    cols = ["detail_url", "homepage_label", "gnavi_url", "accessed_url",
            "adopted_url", "adopted_reason", "fail_reason", "ssl", "ssl_reason"]
    print(edge_cases[cols].to_string())


if __name__ == "__main__":
    main()
