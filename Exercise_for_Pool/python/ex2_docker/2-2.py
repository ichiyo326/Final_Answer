"""
課題2-2: ぐるなびスクレイピング結果をMySQL (database: ex2, table: ex2_2) へ格納する

requests + BeautifulSoup でスクレイピングし（課題1-1と同じロジック）、
sqlalchemy + pandas で MySQL に書き込む。
Dockerコンテナ内のPython3.8環境で実行することを想定。

■ 実行前の準備
  1. pip install sqlalchemy pandas requests beautifulsoup4 pymysql
  2. MySQLに database `ex2` を作成しておく:
       mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS ex2 CHARACTER SET utf8mb4;"
  3. 下記 CONFIG の DB接続情報を環境に合わせて修正する
     （パスワード等は環境変数から読む形にしてあるので、実行前に
      export MYSQL_PASSWORD=xxxx のように設定すること）

■ 注意
  ネットワーク非接続環境で作成したため、ぐるなびの実HTML構造は
  未検証。1-1.py と同様にセレクタ調整が必要な場合がある。
"""

from __future__ import annotations

import os
import re
import json
import time
import socket
import ssl
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
import pandas as pd
from sqlalchemy import create_engine

# ============================== CONFIG ==============================
SEARCH_URLS = [
    "https://r.gnavi.co.jp/area/tokyo/rs/",
]
PAGE_PARAM = "p"
MAX_PAGES_PER_AREA = 20
TARGET_RECORD_COUNT = 50

REQUEST_INTERVAL_SEC = 3
TIMEOUT_SEC = 10

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

DETAIL_URL_PATTERN = re.compile(r"https?://r\.gnavi\.co\.jp/([a-zA-Z0-9]{5,14})/?$")

# --- MySQL接続情報 ---
MYSQL_HOST = os.environ.get("MYSQL_HOST", "localhost")
MYSQL_PORT = os.environ.get("MYSQL_PORT", "3306")
MYSQL_USER = os.environ.get("MYSQL_USER", "root")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "")  # 環境変数で渡すこと
MYSQL_DB = "ex2"
MYSQL_TABLE = "ex2_2"
# ======================================================================


def get_engine():
    url = (
        f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}"
        f"@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}?charset=utf8mb4"
    )
    return create_engine(url)


def polite_get(session: requests.Session, url: str):
    try:
        res = session.get(url, headers=HEADERS, timeout=TIMEOUT_SEC)
        res.encoding = res.apparent_encoding
        res.raise_for_status()
        time.sleep(REQUEST_INTERVAL_SEC)
        return res
    except requests.RequestException as e:
        print(f"  [WARN] リクエスト失敗: {url} ({e})")
        time.sleep(REQUEST_INTERVAL_SEC)
        return None


def build_page_url(base_url: str, page: int) -> str:
    sep = "&" if "?" in base_url else "?"
    return base_url if page <= 1 else f"{base_url}{sep}{PAGE_PARAM}={page}"


def extract_detail_urls(html: str, base_url: str):
    soup = BeautifulSoup(html, "html.parser")
    urls = []
    for a in soup.find_all("a", href=True):
        full_url = urljoin(base_url, a["href"])
        m = DETAIL_URL_PATTERN.match(full_url)
        if m and re.search(r"\d", m.group(1)):
            urls.append(full_url.rstrip("/") + "/")
    seen = set()
    result = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            result.append(u)
    return result


def find_value_by_label(soup: BeautifulSoup, keywords):
    for label_tag_name, value_tag_name in (("th", "td"), ("dt", "dd")):
        for label in soup.find_all(label_tag_name):
            label_text = label.get_text(strip=True)
            if any(kw in label_text for kw in keywords):
                value = label.find_next_sibling(value_tag_name)
                if value is not None:
                    return value
                parent = label.find_parent()
                if parent is not None:
                    value = parent.find(value_tag_name)
                    if value is not None:
                        return value
    return None


def extract_email(text: str) -> str:
    m = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", text)
    return m.group(0) if m else ""


def extract_phone(text: str) -> str:
    m = re.search(r"0\d{1,4}-\d{1,4}-\d{3,4}", text)
    return m.group(0) if m else ""


# --- 住所分割（課題1と同じロジック） ---
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


def resolve_final_url(session: requests.Session, raw_href: str) -> str:
    try:
        res = session.get(
            raw_href, headers=HEADERS, timeout=TIMEOUT_SEC, allow_redirects=True
        )
        time.sleep(REQUEST_INTERVAL_SEC)
        return res.url
    except requests.RequestException:
        time.sleep(REQUEST_INTERVAL_SEC)
        return raw_href


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
        with socket.create_connection((host, port), timeout=TIMEOUT_SEC) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                ssock.getpeercert()
        return True
    except Exception:
        return False


def parse_detail_page(session: requests.Session, url: str):
    res = polite_get(session, url)
    if res is None:
        return None
    soup = BeautifulSoup(res.text, "html.parser")

    name_tag = soup.find("h1")
    shop_name = (
        name_tag.get_text(strip=True)
        if name_tag and name_tag.get_text(strip=True)
        else (soup.title.get_text(strip=True) if soup.title else "")
    )
    shop_name = shop_name.replace("\n", " ").replace("\r", " ").strip()

    page_text = soup.get_text(" ", strip=True)

    phone_value_tag = find_value_by_label(soup, ["電話番号", "電話"])
    phone = (
        extract_phone(phone_value_tag.get_text(" ", strip=True))
        if phone_value_tag
        else extract_phone(page_text)
    )

    mail_value_tag = find_value_by_label(soup, ["メールアドレス", "メール"])
    email = (
        extract_email(mail_value_tag.get_text(" ", strip=True))
        if mail_value_tag
        else extract_email(page_text)
    )

    address_value_tag = find_value_by_label(soup, ["住所"])
    raw_address = ""
    building_from_dom = ""
    if address_value_tag:
        adr_el = address_value_tag.find(class_=re.compile(r"\badr\b"))
        if adr_el:
            region_el = adr_el.find(class_=re.compile(r"\bregion\b"))
            locality_el = adr_el.find(class_=re.compile(r"\blocality\b"))
            if region_el:
                raw_address = region_el.get_text(strip=True)
                building_from_dom = locality_el.get_text(strip=True) if locality_el else ""
            else:
                raw_address = adr_el.get_text(" ", strip=True)
        else:
            raw_address = address_value_tag.get_text(" ", strip=True)
    raw_address = re.sub(r"\s+", "", raw_address)
    raw_address = re.sub(r"^〒?\d{3}-?\d{4}", "", raw_address)
    raw_address = re.sub(r"(大きな地図で見る|地図印刷).*$", "", raw_address)
    building_from_dom = re.sub(r"\s+", "", building_from_dom)
    pref, city, banchi, building_guess = split_address(raw_address)
    building = building_from_dom if building_from_dom else building_guess

    official_href = ""
    for a in soup.find_all("a"):
        link_text = a.get_text(strip=True)
        if "オフィシャルページ" in link_text or "お店のホームページ" in link_text or "ホームページ" in link_text:
            data_o = a.get("data-o")
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
                href = a.get("href")
                if href and href != "#":
                    official_href = urljoin(url, href)
            if official_href:
                break

    final_url = ""
    ssl_flag = False
    if official_href:
        final_url = resolve_final_url(session, official_href)
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


def collect_detail_urls(session: requests.Session):
    detail_urls = []
    seen = set()
    for area_url in SEARCH_URLS:
        for page in range(1, MAX_PAGES_PER_AREA + 1):
            if len(detail_urls) >= TARGET_RECORD_COUNT:
                break
            page_url = build_page_url(area_url, page)
            print(f"[LIST] {page_url}")
            res = polite_get(session, page_url)
            if res is None:
                break
            page_urls = extract_detail_urls(res.text, page_url)
            if not page_urls:
                print("  店舗リンクが見つかりませんでした。")
                break
            new_count = 0
            for u in page_urls:
                if u not in seen:
                    seen.add(u)
                    detail_urls.append(u)
                    new_count += 1
            print(f"  +{new_count}件 (累計 {len(detail_urls)}件)")
            if new_count == 0:
                break
        if len(detail_urls) >= TARGET_RECORD_COUNT:
            break
    return detail_urls[:TARGET_RECORD_COUNT]


def main():
    session = requests.Session()
    detail_urls = collect_detail_urls(session)
    print(f"\n収集した店舗詳細URL数: {len(detail_urls)}")

    records = []
    for i, url in enumerate(detail_urls, start=1):
        print(f"[DETAIL {i}/{len(detail_urls)}] {url}")
        record = parse_detail_page(session, url)
        if record:
            records.append(record)

    df = pd.DataFrame(
        records,
        columns=[
            "店舗名", "電話番号", "メールアドレス", "都道府県",
            "市区町村", "番地", "建物名", "URL", "SSL",
        ],
    )

    engine = get_engine()
    df.to_sql(MYSQL_TABLE, con=engine, if_exists="replace", index=False)
    print(f"\nMySQL {MYSQL_DB}.{MYSQL_TABLE} へ {len(df)} 件を格納しました。")

    # 確認用: 提出スクリーンショット取得の参考に、結果を標準出力にも出す
    with engine.connect() as conn:
        from sqlalchemy import text
        count = conn.execute(text(f"SELECT COUNT(URL) FROM {MYSQL_TABLE};")).scalar()
        print(f"SELECT COUNT(URL) FROM {MYSQL_TABLE}; -> {count}")


if __name__ == "__main__":
    main()
