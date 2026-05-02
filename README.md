# J1939 / Ethernet UDS Diagnostic CLI

J1939(CAN) または Ethernet 上で UDS(Unified Diagnostic Services) Client の request を扱う Python CLI です。
検証・CI では CSV 入出力のシミュレーションとして request をフレーム化し、実機では生成済みフレームを UDP または SocketCAN raw CAN に送信できます。

## 使い方

```bash
python -m udsdiag client --transport j1939 --input data/normal_uds.csv --output out_j1939.csv

python -m udsdiag client --transport ethernet --input data/normal_uds.csv --output out_eth.csv
```

Client 実機送信例:

```bash
python -m udsdiag client --transport ethernet --input data/normal_uds.csv --output out_eth.csv \
  --mode live --host 192.0.2.10 --port 13400

python -m udsdiag client --transport j1939 --input data/normal_uds.csv --output out_j1939.csv \
  --mode live --interface can0
```

互換性のため `send` / `receive` コマンドも残していますが、UDS の役割としては `client` を使用します。
`client` は UDS Client request として定義されている Service ID のみを受け付け、negative response などの Server 側データは入力エラーにします。

## CSV

UDS Client request 入力:

```csv
service_id,did,payload_hex
0x22,0xF190,
0x2E,0xF187,12 34
```

J1939 フレーム出力:

```csv
protocol,can_id,pgn,source_address,destination_address,payload_hex
j1939,0x18DADAF9,0xDADA,0xF9,0xDA,22 F1 90
```

Ethernet フレーム出力:

```csv
protocol,host,port,payload_hex
ethernet,127.0.0.1,13400,22 F1 90
```

## 品質ゲート

```bash
python -m pytest
python -m coverage run -m pytest
python -m coverage report
python -m ruff check .
python -m mypy src tests
```

CI では実行エラー、単体テスト、C0/C1 カバレッジ 100%、静的解析を確認します。
