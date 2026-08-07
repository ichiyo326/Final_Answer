# 課題1: ぐるなびWebスクレイピング

## ファイル対応表

| ファイル | 内容 |
|---|---|
| `1-1.py` | 課題1-1のソースコード（requests + BeautifulSoup） |
| `1-1.csv` | 課題1-1の成果物（50件） |
| `1-2.py` | 課題1-2のソースコード（Selenium） |
| `1-2.csv` | 課題1-2の成果物（50件） |
| `chromedriver` | 課題1-2で使用したchromedriver |

## 実行方法

```bash
pip install requests beautifulsoup4 pandas
python3 1-1.py
```

```bash
pip install selenium pandas
python3 1-2.py
```

出力カラム: 店舗名, 電話番号, メールアドレス, 都道府県, 市区町村, 番地, 建物名, URL, SSL
