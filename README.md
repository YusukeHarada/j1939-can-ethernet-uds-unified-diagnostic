# J1939 / Ethernet UDS Diagnostic CLI

J1939（CAN）または Ethernet 上で UDS（Unified Diagnostic Services, ISO 14229-1）の診断通信を行う Python 製 CLI ツールです。

テスター（診断器）側として動作し、UDS リクエストを CSV で管理・送受信します。

## 特徴

- **J1939 / SocketCAN**：ISO 15765-2 に準拠したマルチフレーム対応（SF / FF / CF / FC）
- **Ethernet / DoIP**：ISO 13400-2（DoIP over TCP）に対応。Routing Activation から Diagnostic Message 送受信まで実装
- **CSV 入出力**：UDS リクエストを CSV で一括管理。受信レスポンスも CSV に保存
- **シミュレーションモード**：実機なしで CSV 変換・動作確認が可能
- **SID バリデーション**：sub-function 値・DID 必須・payload 必須など ISO 14229-1 準拠の入力チェック

## 対応 UDS サービス

| SID | サービス名 |
|-----|-----------|
| 0x10 | DiagnosticSessionControl |
| 0x11 | ECUReset |
| 0x14 | ClearDiagnosticInformation |
| 0x19 | ReadDTCInformation |
| 0x22 | ReadDataByIdentifier |
| 0x23 | ReadMemoryByAddress |
| 0x24 | ReadScalingDataByIdentifier |
| 0x27 | SecurityAccess |
| 0x28 | CommunicationControl |
| 0x2A | ReadDataByPeriodicIdentifier |
| 0x2C | DynamicallyDefineDataIdentifier |
| 0x2E | WriteDataByIdentifier |
| 0x2F | InputOutputControlByIdentifier |
| 0x31 | RoutineControl |
| 0x34 | RequestDownload |
| 0x35 | RequestUpload |
| 0x36 | TransferData |
| 0x37 | RequestTransferExit |
| 0x38 | RequestFileTransfer |
| 0x3D | WriteMemoryByAddress |
| 0x3E | TesterPresent |
| 0x83 | AccessTimingParameter |
| 0x84 | SecuredDataTransmission |
| 0x85 | ControlDTCSetting |
| 0x86 | ResponseOnEvent |
| 0x87 | LinkControl |

---

## セットアップ

### 動作要件

- Python 3.11 以上
- Ubuntu / WSL（J1939 実機モードは SocketCAN が必要）

### インストール

```bash
git clone https://github.com/YusukeHarada/j1939-can-ethernet-uds-unified-diagnostic.git
cd j1939-can-ethernet-uds-unified-diagnostic

# 通常インストール
pip install -e .

# 開発環境（テスト・静的解析含む）
pip install -e ".[dev]"
```

インストール後、`udsdiag` コマンドが使用可能になります。
インストールせずに実行する場合は `python run_udsdiag.py` を使います。

---

## CSV 仕様

### 入力 CSV（UDS リクエスト）

```csv
service_id,did,payload_hex
0x22,0xF190,
0x2E,0xF187,12 34
0x10,,01
0x11,,01
0x14,,
0x19,,02 FF
0x27,,01
0x3E,,00
```

| 列 | 必須 | 説明 |
|----|------|------|
| `service_id` | ○ | UDS サービス ID（16 進数、例：`0x22`） |
| `did` | 一部 | データ識別子（0x22 / 0x2E で必須） |
| `payload_hex` | 一部 | 追加 payload（スペース区切り 16 進数、例：`12 34`）。sub-function を要するサービスはここに記載 |

### 出力 CSV（J1939 フレーム）

```csv
protocol,can_id,pgn,source_address,destination_address,payload_hex
j1939,0x18DADAF9,0xDADA,0xF9,0xDA,22 F1 90
j1939,0x18DADAF9,0xDADA,0xF9,0xDA,2E F1 87 12 34
```

### 出力 CSV（Ethernet フレーム）

```csv
protocol,host,port,payload_hex
ethernet,127.0.0.1,13400,22 F1 90
ethernet,127.0.0.1,13400,2E F1 87 12 34
```

---

## 使い方

### コマンド一覧

| コマンド | 役割 |
|---------|------|
| `client` | UDS クライアントリクエストをフレームに変換して送信 |
| `server` | フレーム CSV からレスポンスフレームを生成（バッチ） |
| `serve` | UDP サーバーとして待ち受け、リクエストに応答 |
| `send` | UDS CSV → フレーム CSV に変換（`client` の別名） |
| `receive` | フレーム CSV → UDS CSV にデコード |

---

### 1. シミュレーションモード（実機不要）

CSV を変換して動作を確認できます。

#### J1939

```bash
# UDS リクエスト CSV → J1939 フレーム CSV
udsdiag client --transport j1939 \
  --input data/normal_uds.csv --output out_j1939.csv

# J1939 フレーム CSV → レスポンスフレーム CSV
udsdiag server --transport j1939 \
  --input out_j1939.csv --output response_j1939.csv \
  --response-payload "AB CD EF"

# レスポンスフレーム CSV → UDS CSV にデコード
udsdiag receive --transport j1939 \
  --input response_j1939.csv --output decoded.csv
```

#### Ethernet

```bash
# UDS リクエスト CSV → Ethernet フレーム CSV
udsdiag client --transport ethernet \
  --input data/normal_uds.csv --output out_eth.csv \
  --host 192.168.1.100 --port 13400

# Ethernet フレーム CSV → レスポンスフレーム CSV
udsdiag server --transport ethernet \
  --input out_eth.csv --output response_eth.csv \
  --response-payload "12 34"
```

#### ローカル UDP ループバック（serve + client）

ターミナル 1 でサーバーを起動します。

```bash
udsdiag serve --transport ethernet \
  --host 127.0.0.1 --port 13400 \
  --response-payload "AA BB"
```

ターミナル 2 からクライアントで送信します。

```bash
udsdiag client --transport ethernet \
  --input data/normal_uds.csv --output response_eth.csv \
  --mode live --host 127.0.0.1 --port 13400
```

---

### 2. 実機モード（J1939 / SocketCAN）

WSL または Ubuntu 上で SocketCAN インターフェイスが利用可能な環境で使用します。

#### 仮想 CAN でのテスト（vcan）

```bash
sudo modprobe vcan
sudo ip link add dev vcan0 type vcan
sudo ip link set up vcan0
```

#### リクエスト送信・レスポンス受信

```bash
udsdiag client --transport j1939 \
  --input data/normal_uds.csv --output response_j1939.csv \
  --mode live \
  --interface vcan0 \
  --response-can-id 0x7E8
```

`--response-can-id` には ECU が応答に使用する CAN ID を指定します。  
`--source-address` / `--destination-address` で J1939 論理アドレスを変更できます（デフォルト：送信 `0xF9`、宛先 `0xDA`）。

---

### 3. 実機モード（Ethernet / DoIP）

DoIP（ISO 13400-2 over TCP, port 13400）対応 ECU に接続します。

```bash
udsdiag client --transport ethernet \
  --input data/normal_uds.csv --output response_eth.csv \
  --mode live \
  --doip \
  --host 192.168.1.100 \
  --port 13400 \
  --doip-source-address 0x0E00 \
  --doip-target-address 0x0001
```

`--doip` を付けると UDP ではなく DoIP TCP 接続になります。  
`--doip-source-address` はテスター論理アドレス、`--doip-target-address` は ECU 論理アドレスです。

---

### 主要オプション一覧

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `--transport` | （必須） | `j1939` または `ethernet` |
| `--input` | （必須） | 入力 CSV パス |
| `--output` | （必須） | 出力 CSV パス |
| `--mode` | `simulate` | `simulate`（CSV 変換のみ）または `live`（実通信） |
| `--interface` | `can0` | SocketCAN インターフェイス名（J1939） |
| `--response-can-id` | — | ECU レスポンス CAN ID（J1939 live で必須） |
| `--host` | `127.0.0.1` | ECU IP アドレス（Ethernet） |
| `--port` | `13400` | DoIP ポート番号（Ethernet） |
| `--doip` | `false` | DoIP TCP モードを使用（Ethernet live） |
| `--doip-source-address` | `0x0E00` | テスター論理アドレス |
| `--doip-target-address` | `0x0001` | ECU 論理アドレス |
| `--source-address` | `0xF9` | J1939 送信元アドレス |
| `--destination-address` | `0xDA` | J1939 宛先アドレス |
| `--timeout` | `1.0` | 受信タイムアウト（秒）（live モード） |
| `--response-payload` | — | サーバー応答に付加するデータ（hex） |
| `--negative-response-code` | `0x11` | NRC（server / serve コマンド） |

---

## 開発・CI

### テスト実行

```bash
# 単体テスト
python -m pytest

# カバレッジ計測（C0/C1 100% 必須）
python -m coverage run -m pytest
python -m coverage report
```

### 静的解析

```bash
# ruff（lint + import sort）
python -m ruff check .

# mypy（strict モード）
python -m mypy src tests
```

### CI（GitHub Actions）

`push` / `pull_request` ごとに下記をすべて確認します。

1. ruff 静的解析
2. mypy 型チェック（strict）
3. pytest 単体テスト
4. coverage C0/C1 100%

---

## アーキテクチャ

```
udsdiag/
├── cli.py          # CLI エントリポイント（argparse）
├── uds.py          # UDS メッセージ定義・SID バリデーション（ISO 14229-1）
├── transport.py    # フレーム構造・CSV エンコード/デコード
├── live.py         # 実通信層
│                   #   J1939: ISO 15765-2 セグメンテーション + SocketCAN
│                   #   Ethernet: DoIP (ISO 13400-2) over TCP / UDP
└── csvio.py        # CSV 読み書きユーティリティ
```

### 処理フロー

```
[送信]
入力 CSV
  └─ uds.py          UDS メッセージ構築・SID バリデーション
       └─ transport.py  J1939 / Ethernet フレーム変換
            └─ live.py   ISO 15765-2 セグメント送信 / DoIP TCP 送信
                 └─ 出力 CSV（レスポンスフレーム）

[受信]
受信フレーム
  └─ live.py         ISO 15765-2 再組み立て / DoIP TCP 受信
       └─ transport.py  フレームデコード
            └─ uds.py   UDS レスポンス解析
                 └─ 出力 CSV（デコード済み UDS）
```