"""
課題1-1: requests + BeautifulSoup によるぐるなびクローリング・スクレイピング

出力: 1-1.csv （店舗名, 電話番号, メールアドレス, 都道府県, 市区町村, 番地, 建物名, URL, SSL）

■ 実行前に必ず確認してください
  このコードは AI アシスタントがネットワークに接続できない環境で作成したため、
  ぐるなび (https://www.gnavi.co.jp/) の実際の HTML を見て動作確認できていません。
  下記 CONFIG セクションの XPath 的な考え方（キーワードによるラベル検索）は
  サイト構造が大きく変わらない限り機能する設計にしてありますが、
  実行してエラーになった場合は下記を確認してください。
    1. ブラウザの開発者ツール(F12)で実際の店舗一覧ページ・店舗詳細ページの HTML を見る
    2. SEARCH_URLS を自分が使いたい検索条件の URL に差し替える
    3. extract_detail_urls() の DETAIL_URL_PATTERN が一覧ページ内の店舗リンクにマッチしているか確認する
    4. parse_detail_page() の LABEL_KEYWORDS が実際のラベル文言と一致しているか確認する
"""

from __future__ import annotations

import re
import json
import time
import socket
import ssl
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
import pandas as pd

# ============================== CONFIG ==============================
# 検索条件は問わないので、ここに調べたいエリア等の一覧ページURLを入れる。
# 例: 東京エリアの一覧ページ。実際のURLはブラウザで検索してアドレスバーからコピーすること。
SEARCH_URLS = [
    "https://r.gnavi.co.jp/area/tokyo/rs/",
]
PAGE_PARAM = "p"          # ページ番号を指定するクエリパラメータ名
MAX_PAGES_PER_AREA = 20   # 無限ループ防止の安全装置
TARGET_RECORD_COUNT = 50  # 収集したいレコード数

REQUEST_INTERVAL_SEC = 3  # 課題要件: リクエスト毎に3秒アイドリング
TIMEOUT_SEC = 10

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

# 店舗詳細ページのURLパターン（例: https://r.gnavi.co.jp/g725448/ ）
# サイト構造が違う場合はここを実際のURL形式に合わせて修正すること。
DETAIL_URL_PATTERN = re.compile(r"https?://r\.gnavi\.co\.jp/([a-zA-Z0-9]{5,14})/?$")

OUTPUT_CSV = "1-1.csv"
# ======================================================================


def polite_get(session: requests.Session, url: str) -> requests.Response | None:
    """3秒のアイドリングタイムを挟みつつGETする。失敗時はNoneを返す。"""
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


def extract_detail_urls(html: str, base_url: str) -> list[str]:
    """一覧ページのHTMLから店舗詳細ページのURL一覧を抽出する。"""
    soup = BeautifulSoup(html, "html.parser")
    urls = []
    for a in soup.find_all("a", href=True):
        full_url = urljoin(base_url, a["href"])
        m = DETAIL_URL_PATTERN.match(full_url)
        if m and re.search(r"\d", m.group(1)):
            urls.append(full_url.rstrip("/") + "/")
    # 重複を除きつつ順序維持
    seen = set()
    result = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            result.append(u)
    return result


def find_value_by_label(soup: BeautifulSoup, keywords: list[str]):
    """
    th/dt 等のラベル要素のテキストにキーワードが含まれる場合、
    対応する td/dd の要素を返す。ラベル-値がテーブル/定義リスト
    どちらの構造でも拾えるようにしている。
    """
    for label_tag_name, value_tag_name in (("th", "td"), ("dt", "dd")):
        for label in soup.find_all(label_tag_name):
            label_text = label.get_text(strip=True)
            if any(kw in label_text for kw in keywords):
                value = label.find_next_sibling(value_tag_name)
                if value is not None:
                    return value
                # 兄弟要素で見つからない場合、親の中から探す
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


# ---------------------------------------------------------------------
# 住所分割（正規表現使用・課題要件8）
# ---------------------------------------------------------------------
PREF_PATTERN = re.compile(r"^(北海道|東京都|(?:大阪|京都)府|.{2,3}?県)")
NUM_CHARS = "0-90-9"
CITY_PATTERN = re.compile(rf"^([^{NUM_CHARS}]+)")
BANCHI_PATTERN = re.compile(rf"^([{NUM_CHARS}\-‐－ー―–—.．,、〜~]+)")


def split_address(address: str):
    """
    住所文字列を 都道府県 / 市区町村 / 番地 / 建物名 に分割する。
    ロジック: 都道府県を先頭から特定 → 残りのうち最初の数字が出るまでを
    市区町村 → そこから数字・ハイフン類が続く間を番地 → 残りを建物名とする。
    ※ 北海道の「条・丁目」表記など特殊な住所は完全には対応していない
      （課題要件8で許容されている範囲）。
    """
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
    """
    ぐるなび店舗ページ内の「オフィシャルページ」等のリンクは、
    アクセス解析用のリダイレクトURLになっていることが多い。
    実際にリクエストしてリダイレクトを辿った先の最終URLを返す
    （課題要件5: ブラウザのアドレスバーに表示されるURLに合わせる）。
    """
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
    """URLのSSL証明書の有無（有効性）をTrue/Falseで返す。"""
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


def parse_detail_page(session: requests.Session, url: str) -> dict | None:
    res = polite_get(session, url)
    if res is None:
        return None
    soup = BeautifulSoup(res.text, "html.parser")

    # 店舗名: h1優先、なければtitleタグ
    name_tag = soup.find("h1")
    if name_tag and name_tag.get_text(strip=True):
        shop_name = name_tag.get_text(strip=True)
    else:
        shop_name = soup.title.get_text(strip=True) if soup.title else ""
    shop_name = shop_name.replace("\n", " ").replace("\r", " ").strip()

    page_text = soup.get_text(" ", strip=True)

    # 電話番号
    phone_value_tag = find_value_by_label(soup, ["電話番号", "電話"])
    phone = (
        extract_phone(phone_value_tag.get_text(" ", strip=True))
        if phone_value_tag
        else extract_phone(page_text)
    )

    # メールアドレス
    mail_value_tag = find_value_by_label(soup, ["メールアドレス", "メール"])
    email = (
        extract_email(mail_value_tag.get_text(" ", strip=True))
        if mail_value_tag
        else extract_email(page_text)
    )

    # 住所
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

    # オフィシャルページ / お店のホームページ URL
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


def collect_detail_urls(session: requests.Session) -> list[str]:
    detail_urls: list[str] = []
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
                print("  店舗リンクが見つかりませんでした。ページ構造 or URLを確認してください。")
                break
            new_count = 0
            for u in page_urls:
                if u not in seen:
                    seen.add(u)
                    detail_urls.append(u)
                    new_count += 1
            print(f"  +{new_count}件 (累計 {len(detail_urls)}件)")
            if new_count == 0:
                # ページを繰り返している可能性があるため終了
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
    # Excelで開いた際に文字化けしないよう BOM 付き UTF-8 で出力（課題要件5）
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n{OUTPUT_CSV} を出力しました。({len(df)}件)")


if __name__ == "__main__":
    main()
