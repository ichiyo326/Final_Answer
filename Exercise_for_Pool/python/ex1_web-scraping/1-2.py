"""
課題1-2: Selenium によるぐるなびクローリング・スクレイピング

出力:
  1-2.csv          : 店舗名, 電話番号, メールアドレス, 都道府県, 市区町村, 番地, 建物名, URL, SSL（50件）
  1-2_url_log.csv  : ホームページURLの取得元・アクセス後URL・採用URL・採用理由・
                      接続失敗理由・SSL判定理由のログ

ページ下部の「次へ」ボタンをクリックしてページ遷移する。
一覧・詳細のスクレイピングはSeleniumで行い、ホームページURLの最終確認・SSL判定・
メール取得・住所分割は 1-1.py / 2-2.py と共通の gnavi_common モジュールを使って
判定基準を統一している（URL確認だけは requests の別セッションで行う。
CAPTCHA判定・失敗理由の扱いを3スクリプトで完全に揃えるため）。
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pandas as pd
import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    WebDriverException,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gnavi_common as gc  # noqa: E402

# ============================== CONFIG ==============================
CHROMEDRIVER_PATH = "./chromedriver"  # 提出物として同ディレクトリに同梱
SEARCH_URL = "https://r.gnavi.co.jp/area/tokyo/rs/"

CANDIDATE_MULTIPLIER = 2       # 50件確保のため候補を多めに集める（修正指摘3）
MAX_PAGE_TRANSITIONS = 40
MAX_DETAIL_RETRIES = 2
RESTART_DRIVER_EVERY = 20      # 予防的にブラウザを再起動する間隔（修正指摘2-9）
WAIT_TIMEOUT_SEC = 10

# 「次へ」ボタン: alt属性が「次」で始まる画像を持つリンクのみを対象とする。
# 修正前はクラス名で判定していたため、見た目の似た「最後のページへ」ボタンを
# 誤ってクリックし、途中で頭打ちになることがあった（修正指摘2-8）。
NEXT_BUTTON_XPATH = "//a[.//img[starts-with(@alt,'次')]]"

OUTPUT_CSV = "1-2.csv"
URL_LOG_CSV = "1-2_url_log.csv"

CSV_COLUMNS = ["店舗名", "電話番号", "メールアドレス", "都道府県", "市区町村", "番地", "建物名", "URL", "SSL"]
# ======================================================================


def build_driver() -> webdriver.Chrome:
    options = webdriver.ChromeOptions()
    options.add_argument(f"user-agent={gc.USER_AGENT}")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    if os.path.exists(CHROMEDRIVER_PATH):
        service = Service(executable_path=CHROMEDRIVER_PATH)
        return webdriver.Chrome(service=service, options=options)
    # 同梱のchromedriverが無い場合はSelenium Managerに解決させる
    return webdriver.Chrome(options=options)


def is_driver_alive(driver: webdriver.Chrome) -> bool:
    """WebDriverのセッションが有効かどうかを確認する（修正指摘2-9）。"""
    try:
        driver.execute_script("return 1")
        return True
    except WebDriverException:
        return False


def wait_for_page_load(driver: webdriver.Chrome):
    WebDriverWait(driver, WAIT_TIMEOUT_SEC).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )


def click_and_wait_for_navigation(driver: webdriver.Chrome, element):
    """
    クリック直後に document.readyState を見ると、実際の遷移が始まる前の
    "古いページの complete" を読んでしまい待機が素通りすることがある
    （バグ調査で判明：ページ送りが1ページ目のまま進んでいなかった原因）。
    クリック前の <html> 要素を古い参照として保持し、まずその要素が
    stale になる（＝実際にDOMが入れ替わった）ことを待ってから、
    新しいページの読み込み完了を待つことで、この競合を避ける。
    """
    old_html = driver.find_element(By.TAG_NAME, "html")
    try:
        element.click()
    except WebDriverException:
        driver.execute_script("arguments[0].click();", element)
    try:
        WebDriverWait(driver, WAIT_TIMEOUT_SEC).until(EC.staleness_of(old_html))
    except TimeoutException:
        # 稀にDOM差し替えがstaleness判定に引っかからない実装のページもあるため、
        # ここでのタイムアウトは致命的エラーにはせず、後続のreadyState待ちに委ねる。
        pass
    wait_for_page_load(driver)


def extract_detail_urls_from_current_page(driver: webdriver.Chrome) -> list[str]:
    urls, seen = [], set()
    for a in driver.find_elements(By.TAG_NAME, "a"):
        try:
            href = a.get_attribute("href")
        except WebDriverException:
            href = None
        if not href:
            continue
        m = gc.DETAIL_URL_PATTERN.match(href)
        if m and any(ch.isdigit() for ch in m.group(1)):
            href = href.rstrip("/") + "/"
            if href not in seen:
                seen.add(href)
                urls.append(href)
    return urls


def collect_candidate_urls(driver: webdriver.Chrome, target_count: int) -> list[str]:
    """必要件数より多めの候補URLを収集する（修正指摘3）。"""
    target_candidates = target_count * CANDIDATE_MULTIPLIER

    gc.wait_before_request()
    driver.get(SEARCH_URL)
    wait_for_page_load(driver)

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
        print(f"[LIST page {page}] +{new_count}件 (候補累計 {len(detail_urls)}件)")

        if len(detail_urls) >= target_candidates:
            break

        try:
            next_button = WebDriverWait(driver, WAIT_TIMEOUT_SEC).until(
                EC.element_to_be_clickable((By.XPATH, NEXT_BUTTON_XPATH))
            )
        except TimeoutException:
            print("  次へボタンが見つかりません。")
            break

        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", next_button)
        next_href = None
        try:
            next_href = next_button.get_attribute("href")
        except WebDriverException:
            pass
        url_before_click = driver.current_url

        gc.wait_before_request()  # ページ遷移「前」の3秒待機（修正指摘4）
        click_and_wait_for_navigation(driver, next_button)

        if driver.current_url == url_before_click and next_href:
            # クリックしても実際にはページが遷移しなかった場合のフォールバック。
            # （「次へ」ボタンの要素自体は正しく見つかっているにもかかわらず、
            #  クリックイベントが実際のページ遷移に結びついていないケースがあったため、
            #  そのボタンのhref先へ直接遷移することで、確実にページ送りを進める。）
            print("  [INFO] クリックではページが遷移しなかったため、リンク先へ直接遷移します。")
            gc.wait_before_request()
            driver.get(next_href)
            wait_for_page_load(driver)

    return detail_urls


def visible_or_hidden_text(element) -> str:
    """
    Seleniumの`.text`は画面に実際に表示されているテキストしか返さない
    （CSSで隠されている・アイコン化されているテキストは空文字になる）。
    ぐるなびの「オフィシャルページ／お店のホームページ」リンクはアイコン画像で、
    ラベル文字列自体は視覚的に隠して埋め込まれているため、`.text`だけでは
    検出できないことがバグ調査で判明した（BeautifulSoup版は生HTMLを読むため検出できていた）。
    `textContent`は表示状態に関係なくDOM上のテキストを返すため、こちらを使う。
    """
    try:
        text = element.get_attribute("textContent") or ""
    except WebDriverException:
        text = ""
    return text.strip()


def normalize_label_text(text: str) -> str:
    """
    ラベル判定用に、テキスト中の空白文字（改行・タブ・半角/全角スペース）を
    全て除去する。実ページでは「オフィシャル ページ」のように、DOM構造上の
    改行・インデントに由来する空白がラベル文中に混在することがあり、
    Seleniumの`textContent`はその空白をそのまま返すため
    （BeautifulSoupの`get_text(strip=True)`は要素ごとに前後の空白を削ってから
    連結するため、この差が生じない）、比較前に除去して吸収する。
    """
    return re.sub(r"\s+", "", text or "")


def find_value_by_label(driver: webdriver.Chrome, keywords: list[str]):
    for label_tag, value_tag in (("th", "td"), ("dt", "dd")):
        for label in driver.find_elements(By.TAG_NAME, label_tag):
            label_text = visible_or_hidden_text(label)
            if any(kw in label_text for kw in keywords):
                try:
                    return label.find_element(By.XPATH, f"following-sibling::{value_tag}[1]")
                except NoSuchElementException:
                    continue
    return None


def extract_email_from_mailto(driver: webdriver.Chrome) -> str:
    """
    「お店に直接メールする」リンクのhref（mailto:）からのみメールアドレスを取得する
    （修正指摘1）。掲載されていない店舗は空欄のままとする。
    """
    for a in driver.find_elements(By.CSS_SELECTOR, "a[href^='mailto:']"):
        try:
            href = a.get_attribute("href")
        except WebDriverException:
            href = None
        if href:
            return gc.extract_mailto(href)
    return ""


def extract_official_url_and_label(driver: webdriver.Chrome):
    """「お店のホームページ」を優先し、掲載がなければ「オフィシャルページ」を取得する（修正指摘2）。"""
    for label in gc.HOMEPAGE_LABELS_PRIORITY:
        for a in driver.find_elements(By.TAG_NAME, "a"):
            link_text = normalize_label_text(visible_or_hidden_text(a))
            if label not in link_text:
                continue

            data_o = a.get_attribute("data-o")
            if data_o:
                url = gc.parse_data_o_url(data_o)
                if url:
                    return url, label

            try:
                href = a.get_attribute("href")
            except WebDriverException:
                href = None
            if href and not href.rstrip().endswith("#"):
                return href, label
    return "", ""


def extract_address(driver: webdriver.Chrome):
    """
    「住所」欄の adr マイクロフォーマットから region（都道府県〜番地）と
    locality（建物名）を別々に取得し、region 側だけ gnavi_common.split_address で分割する。
    """
    address_el = find_value_by_label(driver, ["住所"])
    raw_address, building_from_dom = "", ""
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

    raw_address = gc.clean_raw_address(raw_address)
    building_from_dom = re.sub(r"\s+", "", building_from_dom)

    pref, city, banchi, building_guess = gc.split_address(raw_address)
    building = building_from_dom if building_from_dom else building_guess
    return pref, city, banchi, building


def parse_detail_page(driver: webdriver.Chrome, url_session: requests.Session, url: str, log_rows: list[dict]):
    gc.wait_before_request()  # 詳細ページ取得「前」の3秒待機（修正指摘4）
    try:
        driver.get(url)
        wait_for_page_load(driver)
    except WebDriverException as e:
        print(f"  [WARN] ページ取得失敗: {url} ({e})")
        log_rows.append({"detail_url": url, "status": "detail_page_fetch_failed"})
        return None

    try:
        shop_name = driver.find_element(By.TAG_NAME, "h1").text.strip()
    except NoSuchElementException:
        shop_name = driver.title.strip()
    shop_name = shop_name.replace("\n", " ").replace("\r", " ").strip()

    phone_el = find_value_by_label(driver, ["電話番号", "電話"])
    phone = gc.extract_phone(phone_el.text) if phone_el else ""

    email = extract_email_from_mailto(driver)

    pref, city, banchi, building = extract_address(driver)

    official_url, label = extract_official_url_and_label(driver)
    resolve_info = gc.resolve_shop_url(url_session, official_url, referer=url)
    ssl_flag, ssl_reason = gc.check_ssl(resolve_info["adopted_url"])

    log_rows.append({
        "detail_url": url,
        "homepage_label": label,
        "gnavi_url": resolve_info["gnavi_url"],
        "accessed_url": resolve_info["accessed_url"],
        "adopted_url": resolve_info["adopted_url"],
        "adopted_reason": resolve_info["adopted_reason"],
        "fail_reason": resolve_info["fail_reason"],
        "ssl": ssl_flag,
        "ssl_reason": ssl_reason,
    })

    return {
        "店舗名": shop_name,
        "電話番号": phone,
        "メールアドレス": email,
        "都道府県": pref,
        "市区町村": city,
        "番地": banchi,
        "建物名": building,
        "URL": resolve_info["adopted_url"],
        "SSL": ssl_flag,
    }


def main():
    driver = build_driver()
    # ホームページURL確認・SSL判定専用のセッション（1-1.py / 2-2.py と共通ロジックを使う）
    url_session = requests.Session()
    records: list[dict] = []
    log_rows: list[dict] = []

    try:
        candidates = collect_candidate_urls(driver, gc.TARGET_RECORD_COUNT)
        print(f"\n候補URL数: {len(candidates)}")

        for i, url in enumerate(candidates, start=1):
            if len(records) >= gc.TARGET_RECORD_COUNT:
                break

            if not is_driver_alive(driver):
                print("  [WARN] WebDriverセッションが切断されました。ブラウザを再生成します。")
                try:
                    driver.quit()
                except WebDriverException:
                    pass
                driver = build_driver()
            elif i > 1 and (i - 1) % RESTART_DRIVER_EVERY == 0:
                print("  ブラウザを予防的に再起動します。")
                driver.quit()
                driver = build_driver()

            print(f"[DETAIL {i}/{len(candidates)}] (取得済み {len(records)}/{gc.TARGET_RECORD_COUNT}) {url}")

            record = None
            for attempt in range(MAX_DETAIL_RETRIES + 1):
                record = parse_detail_page(driver, url_session, url, log_rows)
                if record is not None:
                    break
                print(f"  [RETRY {attempt + 1}/{MAX_DETAIL_RETRIES}] {url}")
                if not is_driver_alive(driver):
                    driver.quit()
                    driver = build_driver()
            if record:
                records.append(record)
    finally:
        try:
            driver.quit()
        except WebDriverException:
            pass

    if len(records) < gc.TARGET_RECORD_COUNT:
        print(f"[WARN] 候補URLを使い切りましたが {len(records)}/{gc.TARGET_RECORD_COUNT} 件しか取得できませんでした。")

    df = pd.DataFrame(records, columns=CSV_COLUMNS)
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n{OUTPUT_CSV} を出力しました。({len(df)}件)")

    pd.DataFrame(log_rows).to_csv(URL_LOG_CSV, index=False, encoding="utf-8-sig")
    print(f"{URL_LOG_CSV} を出力しました。")


if __name__ == "__main__":
    main()
