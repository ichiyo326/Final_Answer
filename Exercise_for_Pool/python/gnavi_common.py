"""
gnavi_common.py

課題1-1 / 1-2 / 2-2（ぐるなびスクレイピング）で共通して使用する処理をまとめたモジュール。

本間さんのフィードバック「1-1.py、1-2.py、2-2.pyで判定基準がずれない構成にしてください」
「可能であれば共通処理をモジュールへ切り出してください」に対応するため、
DOMの取得方法（requests+BeautifulSoup / Selenium）に依存しない部分をここへ集約する。

含まれる処理:
  - 住所分割（都道府県 / 市区町村 / 番地 / 建物名）
  - mailto: からのメールアドレス取得
  - ホームページURLの最終確認（CAPTCHA・ぐるなび中継URLへのフォールバック判定）
  - SSL証明書判定（失敗理由の区別）
  - リクエスト前3秒待機などの共通設定

1-1.py / 2-2.py（requests版）は gnavi_requests_scraper.py 経由でこのモジュールを使い、
1-2.py（Selenium版）はこのモジュールを直接importして使う。
"""

from __future__ import annotations

import json
import re
import socket
import ssl
import time
from urllib.parse import parse_qs, urlparse

import requests

# ============================== 共通設定 ==============================
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": USER_AGENT}

REQUEST_INTERVAL_SEC = 3   # 課題要件: 各HTTPリクエストの「前」に必ず3秒待機する
TIMEOUT_SEC = 10
TARGET_RECORD_COUNT = 50

# 店舗詳細ページのURL（例: https://r.gnavi.co.jp/g747765/）
DETAIL_URL_PATTERN = re.compile(r"https?://r\.gnavi\.co\.jp/([a-zA-Z0-9]{5,14})/?$")


def wait_before_request() -> None:
    """リクエスト"前"の3秒アイドリングタイム（修正指摘4: 待機位置の是正）。"""
    time.sleep(REQUEST_INTERVAL_SEC)


def build_page_url(base_url: str, page: int, page_param: str = "p") -> str:
    sep = "&" if "?" in base_url else "?"
    return base_url if page <= 1 else f"{base_url}{sep}{page_param}={page}"


# ---------------------------------------------------------------------
# 住所分割（正規表現使用・課題要件8、修正指摘5）
# ---------------------------------------------------------------------
PREF_PATTERN = re.compile(r"^(北海道|東京都|(?:大阪|京都)府|.{2,3}?県)")

# 半角・全角数字の両方を「数字」とみなす（修正指摘5: 全角数字への対応）
DIGIT_CHARS = "0-9\uff10-\uff19"
# 番地表記に使われるハイフン類・記号
DASH_CHARS = r"\-‐－ー―–—"
# 「2条通」「1丁目」「3番地」「4号」のような和式の番地表記で使われる単位・助詞。
# これらを番地の文字クラスに含めることで、
# 「北海道旭川市2条通8-569-1」→ 北海道 / 旭川市 / 2条通8-569-1 のように
# 番地全体を一括で取得できるようにする（修正前は数字とハイフンのみを番地とみなしていたため、
# 「2条通8-569-1」が「2」/「条通8-569-1」に誤って分割されていた）。
ADDRESS_UNIT_CHARS = "条丁目番地号通の"

CITY_PATTERN = re.compile(rf"^([^{DIGIT_CHARS}]+)")
BANCHI_PATTERN = re.compile(rf"^([{DIGIT_CHARS}{DASH_CHARS}{ADDRESS_UNIT_CHARS}.．,、]+)")


def clean_raw_address(raw_address: str) -> str:
    """住所文字列から余分な空白・郵便番号・付随テキストを取り除く。"""
    raw_address = re.sub(r"\s+", "", raw_address or "")
    raw_address = re.sub(r"^〒?[0-9\uff10-\uff19]{3}-?[0-9\uff10-\uff19]{4}", "", raw_address)
    raw_address = re.sub(r"(大きな地図で見る|地図印刷).*$", "", raw_address)
    return raw_address


def split_address(address: str):
    """
    住所文字列を (都道府県, 市区町村, 番地, 建物名) に分割する。

    - 都道府県: 先頭一致。
    - 市区町村: 都道府県の後ろから、最初の数字（全角含む）が現れるまで。
    - 番地   : 数字・ハイフン類に加えて「条/丁目/番/地/号/通/の」などの和式表記も
               番地の一部として、連続する範囲をまとめて取得する。
    - 建物名 : 番地より後ろの残り全て。
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
        banchi = m.group(1).strip("\u3000 ,、")
        rest = rest[len(m.group(1)):]

    building = rest.strip("\u3000 ,、")

    return pref, city, banchi, building


# ---------------------------------------------------------------------
# メールアドレス（修正指摘1: 「お店に直接メールする」の mailto: hrefのみを対象とする）
# ---------------------------------------------------------------------
def extract_mailto(href: str) -> str:
    """mailto: hrefからメールアドレス部分のみを取り出す（?subject=等のクエリは除去）。"""
    if not href or not href.lower().startswith("mailto:"):
        return ""
    addr = href[len("mailto:"):]
    addr = addr.split("?", 1)[0].strip()
    return addr


def extract_phone(text: str) -> str:
    m = re.search(r"0\d{1,4}-\d{1,4}-\d{3,4}", text or "")
    return m.group(0) if m else ""


# ---------------------------------------------------------------------
# ホームページURL（修正指摘2: 優先順位・CAPTCHA/中継URLの除外）
# ---------------------------------------------------------------------
# 「お店のホームページ」があればそちらを優先し、なければ「オフィシャルページ」を採用する。
HOMEPAGE_LABELS_PRIORITY = ["お店のホームページ", "オフィシャルページ"]


def parse_data_o_url(data_o: str) -> str:
    """ぐるなびのリンクに埋め込まれた data-o 属性（JSON）から実際のリンク先URLを取り出す。"""
    try:
        info = json.loads(data_o)
        domain_path = info.get("a", "")
        scheme = info.get("b") or "http"
        if domain_path:
            return f"{scheme}://{domain_path}"
    except (ValueError, TypeError):
        pass
    return ""


def is_gnavi_or_relay_host(url: str) -> bool:
    """captcha.gnavi.co.jp や、ぐるなびのクリック計測・中継用URLかどうかを判定する。"""
    if not url:
        return False
    host = (urlparse(url).hostname or "").lower()
    return host.endswith("gnavi.co.jp")


# CAPTCHA・中継ページのURLに遷移先（元の外部サイトURL）が埋め込まれる際に
# よく使われるクエリパラメータ名の候補。サイトによって呼び方が異なるため複数試す。
DESTINATION_PARAM_CANDIDATES = [
    "destination", "dest", "to", "url", "redirect",
    "redirect_url", "target", "returl", "return_url",
]


def extract_destination_param(url: str) -> str:
    """
    CAPTCHA・中継URLのクエリパラメータに遷移先（destination等）が含まれていれば、
    URLデコード済みの値を返す。見つからなければ空文字。

    本間さんの指摘（「CAPTCHA URLのdestinationパラメータなどから遷移対象を確認できる
    場合は、ぐるなび店舗ページから取得した外部サイトURLと一致することを確認したうえで、
    その外部サイトURLを使用してください」）に対応するための照合用データ取得。
    """
    if not url:
        return ""
    try:
        query = urlparse(url).query
        params = parse_qs(query)
    except ValueError:
        return ""
    for key in DESTINATION_PARAM_CANDIDATES:
        if key in params and params[key]:
            return params[key][0]
    return ""


def destination_matches_gnavi_url(destination: str, gnavi_url: str):
    """
    destinationパラメータの値と、ぐるなび店舗ページから取得していた外部サイトURLが
    同一サイトを指しているとみなせるかを判定する。

    - destinationが取得できなかった場合: None（「確認できる場合は」の対象外であることを示す）
    - ホスト名が一致（またはサブドメイン関係）していればTrue、そうでなければFalse
    """
    if not destination or not gnavi_url:
        return None
    dest_host = (urlparse(destination).hostname or "").lower()
    gnavi_host = (urlparse(gnavi_url).hostname or "").lower()
    if not dest_host or not gnavi_host:
        return None
    return dest_host == gnavi_host or dest_host.endswith("." + gnavi_host) or gnavi_host.endswith("." + dest_host)


def resolve_shop_url(session: requests.Session, external_url: str, referer: str = "") -> dict:
    """
    ぐるなび店舗ページから取得した外部サイトURL(external_url)へ実際にアクセスし、
    CSV/DBへ最終的に保存するURLを決定する。

    本間さんとのやり取りで確定した方針:
      1. 正常にアクセスできた場合            -> リダイレクト後の最終URLを採用する。
      2. captcha.gnavi.co.jp 等へ転送された場合 -> そのURLは保存せず、転送前に取得していた
         external_url（ぐるなび店舗ページの外部サイトURL）を採用する。
         CAPTCHA突破や回避を目的とした再アクセスは行わない。
      3. タイムアウト・名前解決失敗・接続拒否等の場合 -> 同様に external_url を採用する。
      4. external_url自体が空の場合                    -> 空欄のまま。

    戻り値（ログ出力用に全て保持する）:
      gnavi_url      : ぐるなび店舗ページから取得した外部サイトURL
      accessed_url   : アクセス後に確認できたURL（失敗時は空文字）
      adopted_url    : 最終的にCSV/DBへ保存するURL
      adopted_reason : "final_url" / "fallback_captcha" / "fallback_connection_error" / "no_url"
      fail_reason    : 接続に失敗した場合の原因（成功時は空文字）
    """
    result = {
        "gnavi_url": external_url or "",
        "accessed_url": "",
        "adopted_url": "",
        "adopted_reason": "no_url",
        "fail_reason": "",
        "destination_param": "",
        "destination_match": None,
    }
    if not external_url:
        return result

    headers = dict(HEADERS)
    if referer:
        headers["Referer"] = referer

    wait_before_request()
    try:
        res = session.get(external_url, headers=headers, timeout=TIMEOUT_SEC, allow_redirects=True)
        final_url = res.url
        result["accessed_url"] = final_url
        if is_gnavi_or_relay_host(final_url):
            # CAPTCHAやぐるなびの中継URLへ転送された場合はそのURLを店舗ホームページとして
            # 保存しない。突破・回避を狙った再アクセスは行わず、フォールバックする。
            #
            # 本間さんの指摘対応: CAPTCHA/中継URLのdestination等のパラメータから
            # 遷移対象を確認できる場合は、ぐるなび店舗ページから取得していた外部サイトURLと
            # 一致することを確認する（一致しなくても採用URLはexternal_urlのまま変えない。
            # あくまで照合結果をログへ残すための処理）。
            destination = extract_destination_param(final_url)
            result["destination_param"] = destination
            result["destination_match"] = destination_matches_gnavi_url(destination, external_url)
            result["adopted_url"] = external_url
            result["adopted_reason"] = "fallback_captcha"
        else:
            result["adopted_url"] = final_url
            result["adopted_reason"] = "final_url"
        return result
    except requests.exceptions.SSLError as e:
        result["fail_reason"] = f"SSL証明書エラー: {e}"
    except requests.exceptions.ConnectionError as e:
        result["fail_reason"] = f"接続エラー（名前解決失敗・接続拒否等）: {e}"
    except requests.exceptions.Timeout as e:
        result["fail_reason"] = f"タイムアウト: {e}"
    except requests.exceptions.RequestException as e:
        result["fail_reason"] = f"リクエストエラー: {e}"

    result["adopted_url"] = external_url
    result["adopted_reason"] = "fallback_connection_error"
    return result


# ---------------------------------------------------------------------
# SSL証明書判定（失敗理由を区別してログへ残す）
# ---------------------------------------------------------------------
def check_ssl(url: str):
    """
    URLのSSL証明書の有無を (True/False, 理由) のタプルで返す。
    Falseの場合に「HTTPSではない」のか「証明書が無効」なのか「接続できず確認不能」なのかを
    区別できるようにする。
    """
    if not url:
        return False, "URLなし"
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return False, "HTTPSではない"
    host = parsed.hostname
    if not host:
        return False, "ホスト名を取得できない"
    port = parsed.port or 443
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=TIMEOUT_SEC) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                ssock.getpeercert()
        return True, "証明書を確認できた"
    except ssl.SSLCertVerificationError as e:
        return False, f"証明書エラー: {e}"
    except socket.gaierror as e:
        return False, f"ホスト名解決不能: {e}"
    except socket.timeout:
        return False, "タイムアウトのため確認不能"
    except ConnectionRefusedError:
        return False, "接続拒否のため確認不能"
    except OSError as e:
        return False, f"接続エラーのため確認不能: {e}"
    except Exception as e:  # noqa: BLE001 - 想定外の失敗も理由を残して握りつぶさない
        return False, f"その他のエラーのため確認不能: {e}"
