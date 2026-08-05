# Database課題

「一週間で身につくMySQL」の基本編（0〜7日目）をやって、Dockerで立てたMySQLで実際にSQLを動かしてみました。

## 環境構築

```
docker run -it --name kadai_mysql_only -e MYSQL_ROOT_PASSWORD=mysql -d mysql:latest
```

MySQLは8.0系。データベース名はSCHOOLにしました。

## このフォルダに置いてあるもの

- 図4-1.png：resourceテーブルを全件表示したところ
- 図6-5.png：resourceとclass_nameを内部結合してWHEREで絞ったところ
- Sample607.png：交差結合にWHEREをつけたSample607.sqlの結果
- 図7-2.png：LEFT OUTER JOINの結果
- 図7-3.png：RIGHT OUTER JOINの結果
- 図7-6.png：USINGを使ったLEFT OUTER JOINの結果
- show_tables.png：show tables;を打った結果

作ったテーブルはstudent、resource、score、class_name、purchase_historyの5つです。
使ったSQL全部はschool_kadai.sqlにまとめてあります。
