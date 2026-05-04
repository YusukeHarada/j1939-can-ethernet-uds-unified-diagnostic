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

---

# A-SPICE プロセス準拠 設計・仕様書

本ドキュメントは Automotive SPICE（A-SPICE）の SWE.1〜SWE.6 に対応した設計・仕様の記録です。

各 SWR（ソフトウェア要件）と SWE.2〜SWE.6 成果物の対応は [docs/TRACEABILITY.md](docs/TRACEABILITY.md) を参照。

---

## SWE.1：ソフトウェア要件定義

### 目的

ECU との UDS 診断通信をテスター側から実行し、送受信データを CSV で一元管理する。

### 利害関係者と要求

| 利害関係者 | 要求概要 |
|-----------|---------|
| ソフトウェアエンジニア | CLI で UDS リクエストを送受信し、結果を CSV に保存したい |
| テスト担当者 | 実機なしでシミュレーション実行したい |
| CI 担当者 | 静的解析・テスト・カバレッジを自動実行したい |

### ソフトウェア要件一覧

| ID | 要件 | 優先度 |
|----|------|--------|
| SWR-01 | CSV ファイルを入力として UDS リクエストを一括送信できること | 必須 |
| SWR-02 | J1939（SocketCAN）と Ethernet（DoIP）の両トランスポートをサポートすること | 必須 |
| SWR-03 | 受信した UDS レスポンスを CSV ファイルに出力できること | 必須 |
| SWR-04 | 8バイトを超える UDS ペイロードをマルチフレームで送受信できること | 必須 |
| SWR-05 | ISO 14229-1 に規定される 26 種の UDS サービス ID をサポートすること | 必須 |
| SWR-06 | 実機なしでシミュレーション実行できること | 必須 |
| SWR-07 | SID・sub-function・DID・payload の入力バリデーションを行うこと | 必須 |
| SWR-08 | 不正な入力に対して適切なエラーメッセージを出力し、終了コード 1 で終了すること | 必須 |
| SWR-09 | DoIP（ISO 13400-2）の Routing Activation ハンドシェイクを実装すること | 必須 |
| SWR-10 | Python 3.11 以上、Ubuntu / WSL 環境で動作すること | 必須 |

### 外部インターフェース要件

| ID | 対象 | 仕様 |
|----|------|------|
| EIF-01 | J1939 / CAN | SocketCAN（AF_CAN / CAN_RAW）、ISO 15765-2、29bit CAN ID |
| EIF-02 | Ethernet / DoIP | TCP、ポート 13400、ISO 13400-2:2019（version 0x02） |
| EIF-03 | 入力 CSV | `service_id` / `did` / `payload_hex` 列を持つ UTF-8 CSV |
| EIF-04 | 出力 CSV（J1939） | `protocol` / `can_id` / `pgn` / `source_address` / `destination_address` / `payload_hex` |
| EIF-05 | 出力 CSV（Ethernet） | `protocol` / `host` / `port` / `payload_hex` |

---

## SWE.2：ソフトウェアアーキテクチャ設計

### アーキテクチャ方針

責務を明確に分離した4層構成とし、各層は隣接する層にのみ依存する。

```
┌─────────────────────────────────────────────┐
│  CLI 層  cli.py                              │  ← ユーザーインターフェース
├─────────────────────────────────────────────┤
│  UDS 層  uds.py                              │  ← メッセージ構築・バリデーション
├─────────────────────────────────────────────┤
│  トランスポート層  transport.py               │  ← フレーム変換・CSV エンコード
├─────────────────────────────────────────────┤
│  通信層  live.py                             │  ← SocketCAN / DoIP 実通信
└─────────────────────────────────────────────┘
         csvio.py（横断的 CSV I/O ユーティリティ）
```

### モジュール責務

| モジュール | 責務 | 依存先 |
|-----------|------|--------|
| `cli.py` | CLI 引数解析、コマンドディスパッチ、エラーハンドリング | uds, transport, live, csvio |
| `uds.py` | UDS メッセージの構築・解析・SID バリデーション（ISO 14229-1） | なし |
| `transport.py` | J1939 / Ethernet フレーム構造の定義と CSV エンコード/デコード | uds |
| `live.py` | ISO 15765-2 マルチフレーム処理、DoIP TCP 通信 | transport, uds |
| `csvio.py` | CSV ファイルの読み書きユーティリティ | なし |

### コンポーネント間インターフェース

```
cli.py
  │── uds_from_row()         CSVの1行 → UdsMessage
  │── validate_client_request()  SIDバリデーション
  │── encode_j1939() / encode_ethernet()  UdsMessage → フレーム
  │── _isotp_segments()      フレーム → ISO 15765-2 セグメント列（J1939）
  │── exchange_socketcan()   J1939 送受信（SocketCAN）
  └── exchange_doip()        Ethernet 送受信（DoIP TCP）
```

### データフロー

```
【送信フロー】
入力CSV → uds_from_row() → validate_client_request()
       → encode_j1939/ethernet() → _isotp_segments() or DoIPフレーム
       → SocketCAN送信 / TCP送信
       → レスポンス受信 → 再組み立て → UdsMessage → 出力CSV

【受信フロー（シミュレーション）】
フレームCSV → j1939_from_row / ethernet_from_row()
           → decode_j1939 / decode_ethernet()
           → build_server_response()
           → j1939_to_row / ethernet_to_row() → 出力CSV
```

### 設計上の制約・前提

- ECU 側のサービスロジック（セッション管理、セキュリティシード計算等）はスコープ外。本ツールはテスター側として動作する
- DoIP のシミュレーションモードは UDP を使用し、TCP（Routing Activation）は実機 live モードのみ
- CAN FD（64バイトデータ）は対象外。Classic CAN（8バイト）のみ

---

## SWE.3：ソフトウェア詳細設計・実装

### uds.py：UDS メッセージ層

#### UdsMessage クラス

```
UdsMessage（frozen dataclass）
  ├── service_id: int        UDS サービス ID（0x00〜0xFF）
  ├── did: int | None        データ識別子（0x0000〜0xFFFF）
  ├── payload: bytes         追加データ（sub-function 含む）
  ├── to_payload() → bytes   [SID][DID high][DID low][payload] に直列化
  ├── from_payload() → UdsMessage  バイト列から復元
  ├── status() → str         "request" / "positive_response" / "negative_response"
  └── validate_client_request()  SID バリデーション実行
```

#### SID バリデーションロジック

```
validate_client_request()
  ├── CLIENT_SERVICE_IDS に含まれるか確認
  ├── _SUBFUNC_REQUIRED に含まれる → payload[0] が存在するか確認
  │     └── _SUBFUNC_RANGES で有効範囲チェック
  ├── _DID_REQUIRED に含まれる → did が None でないか確認
  └── _PAYLOAD_REQUIRED に含まれる → payload が空でないか確認
```

#### バリデーションルール一覧

| SID | sub-function 必須 | 有効範囲 | DID 必須 | payload 必須 |
|-----|:-----------------:|----------|:--------:|:------------:|
| 0x10 | ○ | 0x01〜0x7F | — | — |
| 0x11 | ○ | 0x01〜0x03 | — | — |
| 0x19 | ○ | 0x01〜0x19 | — | — |
| 0x22 | — | — | ○ | — |
| 0x27 | ○ | 0x01〜0x7E | — | — |
| 0x2E | — | — | ○ | ○ |
| 0x31 | ○ | 0x01〜0x03 | — | — |
| 0x34 | — | — | — | ○ |
| 0x36 | — | — | — | ○ |
| 0x3E | ○ | 0x00〜0x01 | — | — |

### live.py：通信層

#### ISO 15765-2 セグメンテーション（J1939 送信）

```
_isotp_segments(payload: bytes) → list[bytes]
  ├── len(payload) ≤ 7  →  Single Frame（SF）: [0x0N, data...]  1フレーム
  └── len(payload) > 7  →  First Frame（FF）: [0x1H, 0xLL, data[0:6]]
                            Consecutive Frame（CF）: [0x2N, data...]  N=SN(0〜F)
                            ※ SN は 0x1〜0xF で循環
```

#### ISO 15765-2 再組み立て（J1939 受信）

```
_isotp_receive(sock, peer_can_id, own_can_id) → bytes
  ├── SF 受信  →  payload 直接返却
  ├── FF 受信  →  expected_length 記録 → FC（ContinueToSend）送信
  └── CF 受信  →  SN チェック → バッファ追記 → expected_length 到達で返却
                  SN 不一致 → DiagnosticError
```

#### DoIP 通信シーケンス（Ethernet 送信）

```
exchange_doip(frame, source_address, target_address)
  1. TCP 接続（host:port）
  2. Routing Activation Request 送信（payload_type=0x0005）
  3. Routing Activation Response 受信（payload_type=0x0006）
     └── response_code ∉ {0x10, 0x11} → DiagnosticError
  4. Diagnostic Message 送信（payload_type=0x8001）
     └── [src_addr(2)][tgt_addr(2)][UDS payload]
  5. レスポンス受信ループ
     ├── 0x8002（Positive ACK）→ スキップして継続
     ├── 0x8003（Negative ACK）→ DiagnosticError
     └── 0x8001（Diagnostic Message）→ payload[4:] を返却
```

#### DoIP ヘッダ構造（8バイト）

```
Byte 0   : Protocol Version（0x02）
Byte 1   : Inverse Version（~0x02 & 0xFF = 0xFD）
Byte 2-3 : Payload Type（big-endian）
Byte 4-7 : Payload Length（big-endian）
```

---

## SWE.4：ソフトウェア単体テスト

### テスト方針

- pytest によるユニットテスト
- SocketCAN・TCP ソケットは `monkeypatch` でスタブ化し、実機不要で実行
- C0/C1 カバレッジ 100% を CI で強制

### テストファイル構成

| ファイル | テスト対象 | テスト件数 |
|---------|-----------|----------:|
| `tests/test_uds.py` | `uds.py` — メッセージ構築・SID バリデーション | 35件 |
| `tests/test_transport.py` | `transport.py` — フレームエンコード/デコード | 15件 |
| `tests/test_csvio.py` | `csvio.py` — CSV 読み書き | 8件 |
| `tests/test_live.py` | `live.py` — ISO 15765-2・DoIP | 32件 |
| `tests/test_cli.py` | `cli.py` — コマンド統合・エラーハンドリング | 15件 |
| **合計** | | **105件** |

### 主要テストケース

#### SID バリデーション（test_uds.py）

| テストID | 観点 | 入力 | 期待結果 |
|---------|------|------|---------|
| test_0x10_requires_sub_function | sub-function 必須チェック | 0x10, payload=b"" | DiagnosticError |
| test_0x10_invalid_sub_function_range | 範囲外 sub-function | 0x10, payload=b"\x00" | DiagnosticError |
| test_0x22_requires_did | DID 必須チェック | 0x22, did=None | DiagnosticError |
| test_0x2e_requires_payload | payload 必須チェック | 0x2E, did=0xF187, payload=b"" | DiagnosticError |
| test_0x11_valid_reset_types | 正常系 | 0x11, payload=b"\x01" | 正常終了 |

#### ISO 15765-2（test_live.py）

| テストID | 観点 | 入力 | 期待結果 |
|---------|------|------|---------|
| test_single_frame_exact_7 | SF 境界値（7バイト） | payload=7bytes | セグメント数 1 |
| test_multi_frame_8_bytes | FF/CF 分割（8バイト） | payload=8bytes | セグメント数 2 |
| test_multi_frame_large_payload | 大ペイロード | payload=100bytes | FF+14CF |
| test_multi_frame_sn_wraps | SN 0xF→0x0 折り返し | payload=118bytes | SN 正常循環 |
| test_sequence_number_error | SN 不正 | 不正 SN の CF | DiagnosticError |
| test_multi_frame_response | 受信再組み立て | FF+CF受信 | payload 復元 |

#### DoIP（test_live.py）

| テストID | 観点 | 入力 | 期待結果 |
|---------|------|------|---------|
| test_successful_exchange | 正常系 | Routing OK → Diag Resp | UDS payload 返却 |
| test_skips_positive_ack | ACK スキップ | Pos ACK → Diag Resp | UDS payload 返却 |
| test_negative_ack_raises | Neg ACK | Neg ACK 受信 | DiagnosticError |
| test_routing_denied | Routing 拒否 | code=0x00 | DiagnosticError |
| test_connection_refused_raises | 接続失敗 | OSError | DiagnosticError |

### カバレッジ結果

```
Name    Stmts   Miss Branch BrPart  Cover
-----------------------------------------
TOTAL     507      0    144      0   100%
```

---

## SWE.5：ソフトウェア結合テスト

### 結合テスト方針

CLI 層 → UDS 層 → トランスポート層 → 通信層の各境界をまたいだ統合動作を確認する。`test_cli.py` が結合テストを兼ねる。

### 結合テストケース

#### 正常系：シミュレーションモード（実機不要）

| テストID | フロー | 確認内容 |
|---------|--------|---------|
| test_cli_client_j1939_simulate | CSV 入力 → J1939 フレーム CSV 出力 | CAN ID・PGN・payload の正確性 |
| test_cli_server_j1939 | フレーム CSV → レスポンス CSV | positive response（SID+0x40）の生成 |
| test_cli_client_ethernet_simulate | CSV 入力 → Ethernet フレーム CSV 出力 | host・port・payload の正確性 |
| test_cli_receive_j1939 | フレーム CSV → UDS CSV デコード | service_id・did・payload の復元 |

#### 正常系：live モード（スタブ通信）

| テストID | フロー | 確認内容 |
|---------|--------|---------|
| test_cli_live_mode_calls_senders | J1939 live → exchange_socketcan 呼び出し | インターフェース名の受け渡し |
| test_cli_client_live_doip_calls_exchange_doip | Ethernet live + --doip → exchange_doip 呼び出し | 論理アドレスの受け渡し |

#### 異常系

| テストID | 入力条件 | 期待結果 |
|---------|---------|---------|
| test_cli_invalid_service_id | service_id=0x100（範囲外） | exit code 1、エラー出力 |
| test_cli_client_j1939_live_requires_response_can_id | --response-can-id 未指定 | exit code 1、エラー出力 |
| test_cli_server_negative_response | CLIENT_SERVICE_IDS 外の SID | 0x7F negative response 生成 |

#### UDP ループバック統合テスト（実通信）

```bash
# ターミナル 1
udsdiag serve --transport ethernet --host 127.0.0.1 --port 13400 \
  --response-payload "AA BB" --max-messages 3

# ターミナル 2
udsdiag client --transport ethernet \
  --input data/normal_uds.csv --output result.csv \
  --mode live --host 127.0.0.1 --port 13400
```

期待結果：3リクエストすべてのレスポンスが `result.csv` に保存される。

---

## SWE.6：ソフトウェア検証

### 検証方針

A-SPICE SWE.6 では「ソフトウェア要件が実装で満たされていること」を確認する。

### 要件トレーサビリティマトリクス

| 要件 ID | 要件概要 | 対応テスト | 結果 |
|---------|---------|-----------|------|
| SWR-01 | CSV 入力で UDS 送信 | test_cli_client_j1939_simulate | ✅ |
| SWR-02 | J1939 / Ethernet 両対応 | test_cli_client_j1939_simulate, test_cli_client_ethernet_simulate | ✅ |
| SWR-03 | レスポンスを CSV 出力 | test_cli_server_j1939, test_cli_client_ethernet_simulate | ✅ |
| SWR-04 | マルチフレーム送受信 | test_multi_frame_large_payload, test_multi_frame_response | ✅ |
| SWR-05 | 26種 SID サポート | CLIENT_SERVICE_IDS（26件定義） | ✅ |
| SWR-06 | シミュレーション実行 | test_cli_client_j1939_simulate | ✅ |
| SWR-07 | 入力バリデーション | test_uds.py（SID バリデーション群） | ✅ |
| SWR-08 | エラー時 exit code 1 | test_cli_invalid_service_id | ✅ |
| SWR-09 | DoIP Routing Activation | test_successful_exchange, test_routing_denied | ✅ |
| SWR-10 | Python 3.11+ / Ubuntu 動作 | GitHub Actions（ubuntu-latest, Python 3.12） | ✅ |

### 静的解析結果

| ツール | 設定 | 結果 |
|-------|------|------|
| ruff | デフォルト + isort | **エラーなし** |
| mypy | strict モード | **エラーなし（12ファイル）** |

### CI 自動検証

GitHub Actions にて push / pull_request ごとに下記を自動実行し、全項目グリーンであることを継続確認する。

```
✅ ruff check .            静的解析
✅ mypy src tests          型チェック（strict）
✅ coverage run -m pytest  105件 全パス
✅ coverage report         C0/C1 カバレッジ 100%
```

### 既知の制限事項（スコープ外）

| 項目 | 内容 |
|------|------|
| ECU サービスロジック | SecurityAccess シード計算・セッション管理は ECU ファームウェアの責務 |
| CAN FD | 64バイトデータフィールドは非対応（Classic CAN 8バイトのみ） |
| DoIP シミュレーション | simulate モードは UDP。TCP（Routing Activation）は live モードのみ |
| 0x29 Authentication | ISO 14229-1:2020 追加の新 SID は未対応 |

---