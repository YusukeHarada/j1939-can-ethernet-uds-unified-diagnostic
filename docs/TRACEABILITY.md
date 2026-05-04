# トレーサビリティマトリクス

SWE.1（要件）→ SWE.2（アーキテクチャ）→ SWE.3（詳細設計）→ SWE.4（単体テスト）→ SWE.5（結合テスト）→ SWE.6（検証）の対応を一覧で示す。

---

## トレーサビリティマトリクス

| SWR | 要件概要 | SWE.2 アーキテクチャ | SWE.3 実装（モジュール / 関数） | SWE.4 単体テスト | SWE.5 結合テスト | SWE.6 |
|-----|---------|---------------------|-------------------------------|-----------------|-----------------|:-----:|
| SWR-01 | CSV入力でUDS一括送信 | CLI層 `cli.py` → UDS層 → トランスポート層 | `cli.py`: `client_command()`<br>`csvio.py`: `read_rows()`<br>`uds.py`: `uds_from_row()` | `test_csvio.py`:<br>`test_read_rows_normal` | `test_cli.py`:<br>`test_cli_client_j1939_simulate` | ✅ |
| SWR-02 | J1939 / Ethernet両対応 | 通信層 `live.py` が両プロトコルを実装<br>`--transport` で切り替え | `live.py`: `send_socketcan_raw()`<br>`exchange_socketcan()`<br>`exchange_doip()`<br>`exchange_ethernet_udp()` | `test_live.py`:<br>`TestSendSocketcanRaw`<br>`TestExchangeSocketcan`<br>`TestExchangeDoip`<br>`TestUdpHelpers` | `test_cli.py`:<br>`test_cli_client_j1939_simulate`<br>`test_cli_client_ethernet_simulate` | ✅ |
| SWR-03 | レスポンスをCSV出力 | トランスポート層 `transport.py` がフレームをCSV列に変換 | `transport.py`: `j1939_to_row()`<br>`ethernet_to_row()`<br>`csvio.py`: `write_rows()` | `test_transport.py`:<br>`test_j1939_to_row`<br>`test_ethernet_to_row`<br>`test_csvio.py`: `test_write_rows` | `test_cli.py`:<br>`test_cli_server_j1939`<br>`test_cli_client_ethernet_simulate` | ✅ |
| SWR-04 | マルチフレーム送受信（8バイト超） | 通信層 `live.py` がISO 15765-2を実装<br>SF / FF / CF / FCを管理 | `live.py`: `_isotp_segments()`<br>`_isotp_receive()`<br>Flow Control送信 | `test_live.py`:<br>`test_single_frame_exact_7`<br>`test_multi_frame_8_bytes`<br>`test_multi_frame_large_payload`<br>`test_multi_frame_sn_wraps`<br>`test_sequence_number_error`<br>`test_multi_frame_response` | `test_cli.py`:<br>`test_cli_live_mode_calls_senders` | ✅ |
| SWR-05 | 26種UDS SIDサポート | UDS層 `uds.py` が`CLIENT_SERVICE_IDS`で管理 | `uds.py`: `CLIENT_SERVICE_IDS`（26件）<br>`validate_client_request()` | `test_uds.py`:<br>`test_client_service_ids_count`<br>`test_positive_response_sid` | `test_cli.py`:<br>`test_cli_server_negative_response` | ✅ |
| SWR-06 | シミュレーション実行（実機不要） | CLI層 `--mode simulate`（デフォルト）でネットワーク通信をスキップ | `cli.py`: `simulate`分岐<br>`transport.py`: `encode_j1939()`<br>`encode_ethernet()`<br>`build_server_response()` | `test_transport.py`:<br>`test_encode_j1939`<br>`test_encode_ethernet`<br>`test_build_server_response` | `test_cli.py`:<br>`test_cli_client_j1939_simulate`<br>`test_cli_client_ethernet_simulate`<br>`test_cli_server_j1939` | ✅ |
| SWR-07 | 入力バリデーション | UDS層 `uds.py` がバリデーション責務を担う<br>CLI層はエラーを捕捉して出力 | `uds.py`: `_validate_sid_fields()`<br>`_SUBFUNC_REQUIRED`<br>`_SUBFUNC_RANGES`<br>`_DID_REQUIRED`<br>`_PAYLOAD_REQUIRED` | `test_uds.py`:<br>`TestSidValidation`クラス全件（20件） | `test_cli.py`:<br>`test_cli_invalid_service_id` | ✅ |
| SWR-08 | エラー時 exit code 1 | CLI層 `cli.py` が例外を捕捉しstderr出力 + exit code 1を返す | `cli.py`: `except DiagnosticError`<br>`sys.exit(1)` | `test_cli.py`:<br>`test_cli_invalid_service_id`<br>`test_cli_client_j1939_live_requires_response_can_id` | `test_cli.py`:<br>`test_cli_invalid_service_id`<br>（stderr + exit code確認） | ✅ |
| SWR-09 | DoIP Routing Activation | 通信層 `live.py` がTCP接続後にRouting Activation → Diagnostic Messageの順で通信 | `live.py`: `_doip_routing_activation()`<br>`_doip_send_diagnostic()`<br>`_doip_recv_diagnostic()`<br>`_doip_header()` | `test_live.py`:<br>`test_successful_exchange`<br>`test_routing_denied`<br>`test_routing_wrong_payload_type`<br>`test_routing_too_short`<br>`test_negative_ack_raises`<br>`test_connection_refused_raises` | `test_cli.py`:<br>`test_cli_client_live_doip_calls_exchange_doip` | ✅ |
| SWR-10 | Python 3.11+ / Ubuntu動作 | `pyproject.toml` で`requires-python = ">=3.11"`を指定 | `pyproject.toml`: `python_requires`<br>type hints（`X \| Y`構文は3.10+） | 全105件がPython 3.12 /<br>ubuntu-latestで実行 | GitHub Actions CI<br>（ubuntu-latest, Python 3.12）で全テスト通過 | ✅ |

---

## 外部インターフェース要件トレース

| EIF | 外部IF概要 | 関連SWR | SWE.3 実装 | SWE.4 単体テスト |
|-----|-----------|---------|-----------|----------------|
| EIF-01 | J1939 / SocketCAN（AF_CAN / CAN_RAW、ISO 15765-2、29bit CAN ID） | SWR-02, SWR-04 | `live.py`: `_can_socket()` / `_pack_can_frame()` / `_isotp_segments()` | `test_live.py`: `TestSendSocketcanRaw` / `TestExchangeSocketcan` |
| EIF-02 | Ethernet / DoIP（TCP、port 13400、ISO 13400-2:2019） | SWR-02, SWR-09 | `live.py`: `exchange_doip()` / `_doip_routing_activation()` | `test_live.py`: `TestExchangeDoip` |
| EIF-03 | 入力CSV（service_id / did / payload_hex、UTF-8） | SWR-01, SWR-07 | `csvio.py`: `read_rows()` / `uds.py`: `uds_from_row()` | `test_csvio.py`: `test_read_rows_normal` / `test_read_rows_missing_column` |
| EIF-04 | J1939出力CSV（protocol / can_id / pgn / source_address / destination_address / payload_hex） | SWR-03 | `transport.py`: `j1939_to_row()` | `test_transport.py`: `test_j1939_to_row` |
| EIF-05 | Ethernet出力CSV（protocol / host / port / payload_hex） | SWR-03 | `transport.py`: `ethernet_to_row()` | `test_transport.py`: `test_ethernet_to_row` |