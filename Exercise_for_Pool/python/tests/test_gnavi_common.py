"""
test_gnavi_common.py

gnavi_common.py の resolve_shop_url() / check_ssl() を、実際のネットワークアクセス無しで
検証するユニットテスト。

【なぜこのテストが必要か】
本番の50件実行では、たまたま全件が「正常にアクセスできて最終URLを保存できたケース
（adopted_reason = final_url）」だったため、以下の分岐が一度も通っていない：
  - CAPTCHAへ転送された場合のフォールバック（adopted_reason = fallback_captcha）
  - 接続エラー時のフォールバック（adopted_reason = fallback_connection_error）
  - SSL判定の失敗理由の区別（証明書エラー／名前解決不能／タイムアウト／接続拒否）

これらは「本物のCAPTCHAに遭遇するまで待つ」のではなく、擬似的なSession/socketを使って
意図的に発生させることで、実際のネットワークに依存せず検証できる。

実行方法:
  python3 test_gnavi_common.py
  （全項目 [OK] であれば成功。1つでも [NG] があれば内容を貼って相談する）
"""

from __future__ import annotations

import socket
import ssl
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gnavi_common as gc  # noqa: E402

# テスト中は3秒待機を省略する（ロジック検証が目的のため）
gc.REQUEST_INTERVAL_SEC = 0

FAILED = []


def check(name: str, condition: bool, detail: str = ""):
    status = "[OK]" if condition else "[NG]"
    print(f"{status} {name}" + (f" - {detail}" if detail and not condition else ""))
    if not condition:
        FAILED.append(name)


# ---------------------------------------------------------------------
# 1. resolve_shop_url(): CAPTCHAへ転送された場合のフォールバック
# ---------------------------------------------------------------------
class FakeResponse:
    def __init__(self, url):
        self.url = url


class FakeSessionCaptcha:
    """アクセスすると captcha.gnavi.co.jp へリダイレクトされる想定のフェイクセッション。"""

    def get(self, url, headers=None, timeout=None, allow_redirects=None):
        return FakeResponse(f"https://captcha.gnavi.co.jp/verify?dest={url}")


result = gc.resolve_shop_url(FakeSessionCaptcha(), "https://shop-example.gorp.jp/")
check(
    "CAPTCHA検出時: captcha.gnavi.co.jpのURLではなく元の外部サイトURLを採用する",
    result["adopted_url"] == "https://shop-example.gorp.jp/",
    f"adopted_url={result['adopted_url']}",
)
check(
    "CAPTCHA検出時: adopted_reasonがfallback_captchaになる",
    result["adopted_reason"] == "fallback_captcha",
    f"adopted_reason={result['adopted_reason']}",
)
check(
    "CAPTCHA検出時: accessed_urlにcaptcha.gnavi.co.jpの実際のURLが記録される（ログ用）",
    "captcha.gnavi.co.jp" in result["accessed_url"],
)


# ---------------------------------------------------------------------
# 1b. resolve_shop_url(): CAPTCHA URLのdestinationパラメータとの照合
#     （本間さんの指摘: 「CAPTCHA URLのdestinationパラメータなどから遷移対象を
#      確認できる場合は、ぐるなび店舗ページから取得した外部サイトURLと
#      一致することを確認したうえで、その外部サイトURLを使用してください」）
# ---------------------------------------------------------------------
class FakeSessionCaptchaWithDestination:
    def get(self, url, headers=None, timeout=None, allow_redirects=None):
        import urllib.parse as up
        encoded = up.quote(url, safe="")
        return FakeResponse(f"https://captcha.gnavi.co.jp/verify?destination={encoded}")


result = gc.resolve_shop_url(FakeSessionCaptchaWithDestination(), "https://shop-example.gorp.jp/")
check(
    "CAPTCHA検出時: destinationパラメータが正しく抽出される",
    result["destination_param"] == "https://shop-example.gorp.jp/",
    f"destination_param={result['destination_param']}",
)
check(
    "CAPTCHA検出時: destinationが元の外部サイトURLと一致すればdestination_match=True",
    result["destination_match"] is True,
    f"destination_match={result['destination_match']}",
)
check(
    "CAPTCHA検出時: 一致確認後も採用URLは元の外部サイトURLのまま",
    result["adopted_url"] == "https://shop-example.gorp.jp/",
)


class FakeSessionCaptchaWithMismatchedDestination:
    def get(self, url, headers=None, timeout=None, allow_redirects=None):
        return FakeResponse("https://captcha.gnavi.co.jp/verify?destination=https://totally-different-site.com/")


result = gc.resolve_shop_url(FakeSessionCaptchaWithMismatchedDestination(), "https://shop-example.gorp.jp/")
check(
    "CAPTCHA検出時: destinationが一致しなければdestination_match=False",
    result["destination_match"] is False,
    f"destination_match={result['destination_match']}",
)
check(
    "CAPTCHA検出時: 不一致でも採用URLは元の外部サイトURLのまま変わらない（安全側）",
    result["adopted_url"] == "https://shop-example.gorp.jp/",
)


class FakeSessionCaptchaNoDestination:
    def get(self, url, headers=None, timeout=None, allow_redirects=None):
        return FakeResponse("https://captcha.gnavi.co.jp/verify")


result = gc.resolve_shop_url(FakeSessionCaptchaNoDestination(), "https://shop-example.gorp.jp/")
check(
    "CAPTCHA検出時: destinationパラメータが無ければdestination_match=None",
    result["destination_match"] is None,
    f"destination_match={result['destination_match']}",
)


# ---------------------------------------------------------------------
# 2. resolve_shop_url(): ぐるなびのクリック計測・中継URLへ転送された場合も同様に除外
# ---------------------------------------------------------------------
class FakeSessionRelay:
    def get(self, url, headers=None, timeout=None, allow_redirects=None):
        return FakeResponse("https://r.gnavi.co.jp/click/relay?to=" + url)


result = gc.resolve_shop_url(FakeSessionRelay(), "https://shop-example.gorp.jp/")
check(
    "ぐるなび中継URL検出時: 中継URLではなく元の外部サイトURLを採用する",
    result["adopted_url"] == "https://shop-example.gorp.jp/",
    f"adopted_url={result['adopted_url']}",
)
check(
    "ぐるなび中継URL検出時: adopted_reasonがfallback_captchaになる（同じ判定ロジック）",
    result["adopted_reason"] == "fallback_captcha",
)


# ---------------------------------------------------------------------
# 3. resolve_shop_url(): タイムアウト・接続エラー時のフォールバック
# ---------------------------------------------------------------------
class FakeSessionTimeout:
    def get(self, url, headers=None, timeout=None, allow_redirects=None):
        raise requests.exceptions.Timeout("simulated timeout")


class FakeSessionConnectionError:
    def get(self, url, headers=None, timeout=None, allow_redirects=None):
        raise requests.exceptions.ConnectionError("simulated name resolution failure")


class FakeSessionSSLError:
    def get(self, url, headers=None, timeout=None, allow_redirects=None):
        raise requests.exceptions.SSLError("simulated ssl error")


for label, fake_session_cls, expected_keyword in [
    ("タイムアウト", FakeSessionTimeout, "タイムアウト"),
    ("接続エラー(名前解決失敗等)", FakeSessionConnectionError, "接続エラー"),
    ("SSLエラー", FakeSessionSSLError, "SSL証明書エラー"),
]:
    result = gc.resolve_shop_url(fake_session_cls(), "https://shop-example.gorp.jp/")
    check(
        f"{label}時: 元の外部サイトURLへフォールバックする",
        result["adopted_url"] == "https://shop-example.gorp.jp/",
        f"adopted_url={result['adopted_url']}",
    )
    check(
        f"{label}時: adopted_reasonがfallback_connection_errorになる",
        result["adopted_reason"] == "fallback_connection_error",
    )
    check(
        f"{label}時: fail_reasonに理由が記録される",
        expected_keyword in result["fail_reason"],
        f"fail_reason={result['fail_reason']}",
    )


# ---------------------------------------------------------------------
# 4. resolve_shop_url(): 正常にアクセスできた場合（比較対象として再確認）
# ---------------------------------------------------------------------
class FakeSessionOK:
    def get(self, url, headers=None, timeout=None, allow_redirects=None):
        return FakeResponse(url.replace("http://", "https://").rstrip("/") + "/final")


result = gc.resolve_shop_url(FakeSessionOK(), "http://shop-example.com/")
check(
    "正常アクセス時: リダイレクト後の最終URLを採用する",
    result["adopted_url"] == "https://shop-example.com/final",
)
check("正常アクセス時: adopted_reasonがfinal_urlになる", result["adopted_reason"] == "final_url")


# ---------------------------------------------------------------------
# 5. resolve_shop_url(): URLが空の場合
# ---------------------------------------------------------------------
result = gc.resolve_shop_url(FakeSessionOK(), "")
check("URL空欄時: adopted_urlが空文字のまま", result["adopted_url"] == "")
check("URL空欄時: adopted_reasonがno_urlになる", result["adopted_reason"] == "no_url")


# ---------------------------------------------------------------------
# 6. check_ssl(): 失敗理由の区別
# ---------------------------------------------------------------------
class _FakeSock:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def wrap_socket(self, sock, server_hostname=None):
        raise NotImplementedError  # 呼ばれない想定（create_connection側で失敗させる）


def _patch_create_connection(monkeypatch_exc):
    def _raise(*args, **kwargs):
        raise monkeypatch_exc
    return _raise


_orig_create_connection = socket.create_connection

test_cases = [
    ("証明書エラー", ssl.SSLCertVerificationError("simulated cert error"), "証明書エラー"),
    ("ホスト名解決不能", socket.gaierror("simulated dns failure"), "ホスト名解決不能"),
    ("タイムアウト", socket.timeout(), "タイムアウトのため確認不能"),
    ("接続拒否", ConnectionRefusedError(), "接続拒否のため確認不能"),
]

for label, exc, expected_reason in test_cases:
    # SSLCertVerificationErrorはwrap_socket側で起きる想定なので、
    # create_connection自体は成功させ、その後の処理で例外を発生させる必要があるケースと、
    # create_connection自体で失敗するケースを分けて扱う。
    if isinstance(exc, ssl.SSLCertVerificationError):
        class _CtxRaisesCert:
            def wrap_socket(self, sock, server_hostname=None):
                raise exc

        def _fake_create_connection(*args, **kwargs):
            return _FakeSock()

        socket.create_connection = _fake_create_connection
        orig_create_default_context = ssl.create_default_context
        ssl.create_default_context = lambda: _CtxRaisesCert()
        try:
            ok, reason = gc.check_ssl("https://example.com/")
        finally:
            socket.create_connection = _orig_create_connection
            ssl.create_default_context = orig_create_default_context
    else:
        socket.create_connection = _patch_create_connection(exc)
        try:
            ok, reason = gc.check_ssl("https://example.com/")
        finally:
            socket.create_connection = _orig_create_connection

    check(f"SSL判定 - {label}: Falseになる", ok is False, f"ok={ok}")
    check(f"SSL判定 - {label}: 理由が正しく区別される", expected_reason in reason, f"reason={reason}")

ok, reason = gc.check_ssl("http://example.com/")
check("SSL判定 - HTTPの場合: Falseになる", ok is False)
check("SSL判定 - HTTPの場合: 理由がHTTPSではないになる", reason == "HTTPSではない")


# ---------------------------------------------------------------------
# 結果まとめ
# ---------------------------------------------------------------------
print()
if FAILED:
    print(f"失敗: {len(FAILED)}件")
    for name in FAILED:
        print(f"  - {name}")
    sys.exit(1)
else:
    print("全項目 [OK]。CAPTCHA/接続エラー/SSL失敗理由のフォールバックロジックは正しく動作しています。")
