"""
gnavi_requests_scraper.py

requests + BeautifulSoup によるぐるなびクローリング・スクレイピングの共通実装。
課題1-1（1-1.py）と課題2-2（2-2.py）は出力先（CSV / MySQL）が異なるだけで
取得ロジックは同一のため、ここに切り出して1-1.pyと2-2.pyで判定基準がずれないようにする。
（1-2.py はSeleniumを使うため別実装だが、住所分割・URL確定・SSL判定は
 gnavi_common モジュールを共通で使い、基準を統一している。）
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

import gnavi_common as gc

CANDIDATE_MULTIPLIER = 2   # 詳細取得の失敗分を見込み、必要件数より多く候補URLを集める
MAX_LIST_PAGES = 40        # 一覧ページ取得の安全上限（無限ループ防止）
MAX_DETAIL_RETRIES = 2     # 詳細ページ取得に失敗した場合の再試行回数


def polite_get(session: requests.Session, url: str):
    """リクエスト"前"に3秒待機してからGETする（修正指摘4）。失敗時はNoneを返す。"""
    gc.wait_before_request()
    try:
        res = session.get(url, headers=gc.HEADERS, timeout=gc.TIMEOUT_SEC)
        res.encoding = res.apparent_encoding
        res.raise_for_status()
        return res
    except requests.RequestException as e:
        print(f"  [WARN] リクエスト失敗: {url} ({e})")
        return None


def extract_detail_urls(html: str, base_url: str) -> list[str]:
    """一覧ページのHTMLから店舗詳細ページのURL一覧を抽出する。"""
    soup = BeautifulSoup(html, "html.parser")
    urls, seen = [], set()
    for a in soup.find_all("a", href=True):
        full_url = urljoin(base_url, a["href"])
        m = gc.DETAIL_URL_PATTERN.match(full_url)
        if m and any(ch.isdigit() for ch in m.group(1)):
            full_url = full_url.rstrip("/") + "/"
            if full_url not in seen:
                seen.add(full_url)
                urls.append(full_url)
    return urls


def collect_candidate_urls(session: requests.Session, search_urls: list[str], target_count: int) -> list[str]:
    """
    必要件数(target_count)より多めの候補URLを収集する（修正指摘3: 50件を確実に取得するため）。
    詳細取得時に失敗した店舗があっても、候補に余裕があれば次の候補で埋め合わせられる。
    """
    target_candidates = target_count * CANDIDATE_MULTIPLIER
    detail_urls: list[str] = []
    seen = set()
    for area_url in search_urls:
        for page in range(1, MAX_LIST_PAGES + 1):
            if len(detail_urls) >= target_candidates:
                break
            page_url = gc.build_page_url(area_url, page)
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
            print(f"  +{new_count}件 (候補累計 {len(detail_urls)}件)")
            if new_count == 0:
                break
        if len(detail_urls) >= target_candidates:
            break
    return detail_urls


def find_value_by_label(soup: BeautifulSoup, keywords: list[str]):
    """th/dt ラベルのテキストにキーワードを含む要素の、対応する td/dd を返す。"""
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


def extract_email_from_mailto(soup: BeautifulSoup) -> str:
    """
    「お店に直接メールする」リンクのhref（mailto:）からのみメールアドレスを取得する
    （修正指摘1: ページ全体からメール形式の文字列を検索しない）。
    掲載されていない店舗は空欄のままとする。
    """
    for a in soup.find_all("a", href=True):
        if a["href"].lower().startswith("mailto:"):
            return gc.extract_mailto(a["href"])
    return ""


def extract_official_url_and_label(soup: BeautifulSoup, base_url: str):
    """
    「お店のホームページ」を優先し、掲載がなければ「オフィシャルページ」を取得する
    （修正指摘2）。href が "#" で実URLが data-o 属性のJSONに入っている場合はそちらを使う。
    """
    for label in gc.HOMEPAGE_LABELS_PRIORITY:
        for a in soup.find_all("a"):
            if label not in a.get_text(strip=True):
                continue
            data_o = a.get("data-o")
            if data_o:
                url = gc.parse_data_o_url(data_o)
                if url:
                    return url, label
            href = a.get("href")
            if href and href != "#":
                return urljoin(base_url, href), label
    return "", ""


def extract_address(soup: BeautifulSoup):
    """
    「住所」欄の adr マイクロフォーマットから region（都道府県〜番地）と
    locality（建物名）を別々に取得し、region 側だけ gnavi_common.split_address で分割する。
    """
    address_value_tag = find_value_by_label(soup, ["住所"])
    raw_address, building_from_dom = "", ""
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

    raw_address = gc.clean_raw_address(raw_address)
    building_from_dom = re.sub(r"\s+", "", building_from_dom)

    pref, city, banchi, building_guess = gc.split_address(raw_address)
    building = building_from_dom if building_from_dom else building_guess
    return pref, city, banchi, building


def parse_detail_page(session: requests.Session, url: str, log_rows: list[dict]):
    """店舗詳細ページを取得し、1レコード分のdictを返す。取得失敗時はNoneを返す。"""
    res = None
    for attempt in range(MAX_DETAIL_RETRIES + 1):
        res = polite_get(session, url)
        if res is not None:
            break
        print(f"  [RETRY {attempt + 1}/{MAX_DETAIL_RETRIES}] {url}")
    if res is None:
        log_rows.append({"detail_url": url, "status": "detail_page_fetch_failed"})
        return None

    soup = BeautifulSoup(res.text, "html.parser")

    name_tag = soup.find("h1")
    shop_name = (
        name_tag.get_text(strip=True)
        if name_tag and name_tag.get_text(strip=True)
        else (soup.title.get_text(strip=True) if soup.title else "")
    )
    shop_name = shop_name.replace("\n", " ").replace("\r", " ").strip()

    phone_value_tag = find_value_by_label(soup, ["電話番号", "電話"])
    phone = gc.extract_phone(phone_value_tag.get_text(" ", strip=True)) if phone_value_tag else ""

    email = extract_email_from_mailto(soup)

    pref, city, banchi, building = extract_address(soup)

    official_url, label = extract_official_url_and_label(soup, url)
    resolve_info = gc.resolve_shop_url(session, official_url, referer=url)
    ssl_flag, ssl_reason = gc.check_ssl(resolve_info["adopted_url"])

    log_rows.append({
        "detail_url": url,
        "homepage_label": label,
        "gnavi_url": resolve_info["gnavi_url"],
        "accessed_url": resolve_info["accessed_url"],
        "adopted_url": resolve_info["adopted_url"],
        "adopted_reason": resolve_info["adopted_reason"],
        "destination_param": resolve_info["destination_param"],
        "destination_match": resolve_info["destination_match"],
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


def scrape(search_urls: list[str], target_count: int = gc.TARGET_RECORD_COUNT):
    """
    一覧ページを巡回して候補URLを集め、詳細ページを取得して target_count 件のレコードを
    確保する（不足時は候補を使い切るまで次の店舗を試す）。

    戻り値: (records, log_rows)
    """
    session = requests.Session()
    candidates = collect_candidate_urls(session, search_urls, target_count)
    print(f"\n候補URL数: {len(candidates)}")

    records: list[dict] = []
    log_rows: list[dict] = []
    for i, url in enumerate(candidates, start=1):
        if len(records) >= target_count:
            break
        print(f"[DETAIL {i}/{len(candidates)}] (取得済み {len(records)}/{target_count}) {url}")
        record = parse_detail_page(session, url, log_rows)
        if record:
            records.append(record)

    if len(records) < target_count:
        print(f"[WARN] 候補URLを使い切りましたが {len(records)}/{target_count} 件しか取得できませんでした。"
              f" SEARCH_URLSの追加や候補倍率(CANDIDATE_MULTIPLIER)の引き上げを検討してください。")

    return records, log_rows
