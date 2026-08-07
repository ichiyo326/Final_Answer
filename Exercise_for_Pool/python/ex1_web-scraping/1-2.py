"""
課題1-2: Selenium によるぐるなびクローリング・スクレイピング

出力: 1-2.csv （店舗名, 電話番号, メールアドレス, 都道府県, 市区町村, 番地, 建物名, URL, SSL）
使用: 課題要件の通り、ページ下部の「>」（次へ）ボタンをクリックしてページ遷移する。

■ 実行前の準備
  1. お使いのChromeのバージョンに合ったchromedriverをダウンロードし、
     このスクリプトと同じディレクトリに配置する。
  2. pip install selenium pandas

■ 実行前に必ず確認してください
  このコードは AI アシスタントがネットワークに接続できない環境で作成したため、
  ぐるなびの実際のHTML構造（クラス名等）を見て動作確認できていません。
  下記 CONFIG / セレクタ定義部分は、キーワードによるラベル検索や
  URLパターンなど、なるべく構造変化に強い書き方にしてありますが、
  実行してうまく要素が見つからない場合は、ブラウザの開発者ツール(F12)で
  実際の要素を確認し、NEXT_BUTTON_XPATH 等を調整してください。
"""

from __future__ import annotations

import re
import json
import time
import socket
import ssl
from urllib.parse import urlparse

import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, WebDriverException,
)

# ============================== CONFIG ==============================
CHROMEDRIVER_PATH = "./chromedriver"  # 提出物として同ディレクトリに同梱すること

SEARCH_URL = "https://r.gnavi.co.jp/area/tokyo/rs/"  # 検索条件は問わない。適宜変更する

TARGET_RECORD_COUNT = 50
MAX_PAGE_TRANSITIONS = 20  # 安全装置

REQUEST_INTERVAL_SEC = 3  # 課題要件: 各リクエスト（ページ遷移）前に3秒アイドリング
WAIT_TIMEOUT_SEC = 10

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# 店舗詳細ページURLの形式（例: https://r.gnavi.co.jp/g725448/ ）。
# 実際のURL形式に合わせて修正すること。
DETAIL_URL_PATTERN = re.compile(r"https?://r\.gnavi\.co\.jp/([a-zA-Z0-9]{5,14})/?$")

# 「次へ」（>）ボタンを探すXPath。テキストや aria-label 等、複数の候補を用意している。
NEXT_BUTTON_XPATH = (
    "//a[contains(@href,'p=')][.//img[contains(@class,'nextIcon')]]"
)

OUTPUT_CSV = "1-2.csv"
# ======================================================================


def build_driver() -> webdriver.Chrome:
    import os
    options = webdriver.ChromeOptions()
    options.add_argument(f"user-agent={USER_AGENT}")
    # ヘッドレスで動かしたい場合は以下2行のコメントを外す
    # options.add_argument("--headless=new")
    # options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    if os.path.exists(CHROMEDRIVER_PATH):
        service = Service(executable_path=CHROMEDRIVER_PATH)
        return webdriver.Chrome(service=service, options=options)
    # ローカルにchromedriverが無い場合、Selenium Managerに自動解決させる
    return webdriver.Chrome(options=options)


def wait_for_page_load(driver):
    WebDriverWait(driver, WAIT_TIMEOUT_SEC).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )


def extract_detail_urls_from_current_page(driver) -> list[str]:
    urls = []
    for a in driver.find_elements(By.TAG_NAME, "a"):
        try:
            href = a.get_attribute("href")
        except WebDriverException:
            href = None
        m = DETAIL_URL_PATTERN.match(href) if href else None
        if m and re.search(r"\d", m.group(1)):
            urls.append(href.rstrip("/") + "/")
    seen = set()
    result = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            result.append(u)
    return result


def collect_detail_urls(driver) -> list[str]:
    driver.get(SEARCH_URL)
    wait_for_page_load(driver)
    time.sleep(REQUEST_INTERVAL_SEC)

    detail_urls: list[str] = []
    seen = set()

    for page in range(1, MAX_PAGE_TRANSITIONS + 1):
        page_urls = extract_detail_urls_from_current_page(driver)
        new_count = 0
        for u in page_urls:
            if u not in seen:
                seen.add(u)
                detail_urls.append(u)
                new_count += 1
        print(f"[LIST page {page}] +{new_count}件 (累計 {len(detail_urls)}件) URL={driver.current_url}")

        if len(detail_urls) >= TARGET_RECORD_COUNT:
            break

        # 課題要件: 「>」ボタンをクリックしてページ遷移する
        try:
            next_button = WebDriverWait(driver, WAIT_TIMEOUT_SEC).until(
                EC.element_to_be_clickable((By.XPATH, NEXT_BUTTON_XPATH))
            )
        except TimeoutException:
            print("  次へボタンが見つかりません。ページ遷移を終了します。")
            break

        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", next_button)
        try:
            next_button.click()
        except WebDriverException:
            driver.execute_script("arguments[0].click();", next_button)

        wait_for_page_load(driver)
        time.sleep(REQUEST_INTERVAL_SEC)

    return detail_urls[:TARGET_RECORD_COUNT]


def find_value_by_label(driver, keywords: list[str]):
    """th/dt ラベルのテキストにキーワードを含む要素の次(td/dd)を返す。"""
    for label_tag, value_tag in (("th", "td"), ("dt", "dd")):
        elements = driver.find_elements(By.TAG_NAME, label_tag)
        for label in elements:
            label_text = label.text.strip()
            if any(kw in label_text for kw in keywords):
                try:
                    value = label.find_element(
                        By.XPATH, f"following-sibling::{value_tag}[1]"
                    )
                    return value
                except NoSuchElementException:
                    continue
    return None


def extract_email(text: str) -> str:
    m = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", text)
    return m.group(0) if m else ""


def extract_phone(text: str) -> str:
    m = re.search(r"0\d{1,4}-\d{1,4}-\d{3,4}", text)
    return m.group(0) if m else ""


# ---------------------------------------------------------------------
# 住所分割（正規表現使用・課題要件8）
# ---------------------------------------------------------------------
PREF_PATTERN = re.compile(r"^(北海道|東京都|(?:大阪|京都)府|.{2,3}?県)")
NUM_CHARS = "0-90-9"
CITY_PATTERN = re.compile(rf"^([^{NUM_CHARS}]+)")
BANCHI_PATTERN = re.compile(rf"^([{NUM_CHARS}\-‐－ー―–—.．,、〜~]+)")


def split_address(address: str):
    address = (address or "").strip()
    rest = address

    pref = ""
    m = PREF_PATTERN.match(rest)
    if m:
        pref = m.group(1)
        rest = rest[len(pref):]

    city = ""
    m = CITY_PATTERN.match(rest)
    if m:
        city = m.group(1)
        rest = rest[len(city):]

    banchi = ""
    m = BANCHI_PATTERN.match(rest)
    if m and m.group(1).strip():
        banchi = m.group(1).strip("　 ,、")
        rest = rest[len(m.group(1)):]

    building = rest.strip("　 ,、")

    return pref, city, banchi, building


def check_ssl(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return False
    host = parsed.hostname
    if not host:
        return False
    port = parsed.port or 443
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=WAIT_TIMEOUT_SEC) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                ssock.getpeercert()
        return True
    except Exception:
        return False


def resolve_official_url(driver, href: str) -> str:
    """
    「オフィシャルページ」等のリンクを実際に新しいタブで開き、
    リダイレクト後にアドレスバーに表示される最終URLを取得する
    （課題要件5）。
    """
    original_window = driver.current_window_handle
    driver.switch_to.new_window("tab")
    final_url = href
    try:
        driver.get(href)
        wait_for_page_load(driver)
        time.sleep(REQUEST_INTERVAL_SEC)
        final_url = driver.current_url
    except WebDriverException:
        pass
    finally:
        driver.close()
        driver.switch_to.window(original_window)
    return final_url


def parse_detail_page(driver, url: str) -> dict | None:
    try:
        driver.get(url)
        wait_for_page_load(driver)
    except WebDriverException as e:
        print(f"  [WARN] ページ取得失敗: {url} ({e})")
        time.sleep(REQUEST_INTERVAL_SEC)
        return None
    time.sleep(REQUEST_INTERVAL_SEC)

    try:
        shop_name = driver.find_element(By.TAG_NAME, "h1").text.strip()
    except NoSuchElementException:
        shop_name = driver.title.strip()
    shop_name = shop_name.replace("\n", " ").replace("\r", " ").strip()

    page_text = driver.find_element(By.TAG_NAME, "body").text

    phone_el = find_value_by_label(driver, ["電話番号", "電話"])
    phone = extract_phone(phone_el.text) if phone_el else extract_phone(page_text)

    mail_el = find_value_by_label(driver, ["メールアドレス", "メール"])
    email = extract_email(mail_el.text) if mail_el else extract_email(page_text)

    address_el = find_value_by_label(driver, ["住所"])
    raw_address = ""
    building_from_dom = ""
    if address_el:
        try:
            adr_sub = address_el.find_element(By.CSS_SELECTOR, ".adr")
            try:
                region_el = adr_sub.find_element(By.CSS_SELECTOR, ".region")
                raw_address = region_el.text
                try:
                    locality_el = adr_sub.find_element(By.CSS_SELECTOR, ".locality")
                    building_from_dom = locality_el.text
                except NoSuchElementException:
                    building_from_dom = ""
            except NoSuchElementException:
                raw_address = adr_sub.text
        except NoSuchElementException:
            raw_address = address_el.text
    raw_address = re.sub(r"\s+", "", raw_address)
    raw_address = re.sub(r"^〒?\d{3}-?\d{4}", "", raw_address)
    raw_address = re.sub(r"(大きな地図で見る|地図印刷).*$", "", raw_address)
    building_from_dom = re.sub(r"\s+", "", building_from_dom)
    pref, city, banchi, building_guess = split_address(raw_address)
    building = building_from_dom if building_from_dom else building_guess

    official_href = ""
    for a in driver.find_elements(By.TAG_NAME, "a"):
        link_text = a.text.strip()
        if "オフィシャルページ" in link_text or "お店のホームページ" in link_text or "ホームページ" in link_text:
            data_o = a.get_attribute("data-o")
            if data_o:
                try:
                    info = json.loads(data_o)
                    domain_path = info.get("a", "")
                    scheme = info.get("b") or "http"
                    if domain_path:
                        official_href = f"{scheme}://{domain_path}"
                except (ValueError, TypeError):
                    official_href = ""
            if not official_href:
                href = a.get_attribute("href")
                if href and not href.rstrip().endswith("#"):
                    official_href = href
            if official_href:
                break

    final_url = ""
    ssl_flag = False
    if official_href:
        final_url = resolve_official_url(driver, official_href)
        ssl_flag = check_ssl(final_url)

    return {
        "店舗名": shop_name,
        "電話番号": phone,
        "メールアドレス": email,
        "都道府県": pref,
        "市区町村": city,
        "番地": banchi,
        "建物名": building,
        "URL": final_url,
        "SSL": ssl_flag,
    }


def main():
    driver = build_driver()
    try:
        detail_urls = collect_detail_urls(driver)
        print(f"\n収集した店舗詳細URL数: {len(detail_urls)}")

        records = []
        for i, url in enumerate(detail_urls, start=1):
            print(f"[DETAIL {i}/{len(detail_urls)}] {url}")
            record = parse_detail_page(driver, url)
            if record:
                records.append(record)
    finally:
        driver.quit()

    df = pd.DataFrame(
        records,
        columns=[
            "店舗名", "電話番号", "メールアドレス", "都道府県",
            "市区町村", "番地", "建物名", "URL", "SSL",
        ],
    )
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n{OUTPUT_CSV} を出力しました。({len(df)}件)")


if __name__ == "__main__":
    main()
