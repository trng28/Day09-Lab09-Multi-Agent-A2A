# Báo cáo cá nhân - Multi-Agent A2A

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
|---|---|
| Họ và tên | Nguyễn Thị Khánh Ly |
| MSSV | 2A202601403 |
| Khóa/Lớp | K3 |
| Vai trò chính | Evaluation metrics, output audit và chuẩn bị submission |
| Ngày hoàn thành | 2026-08-05 |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
|---|---|---|---|---|
| Báo cáo đánh giá local | `evaluate.py`, `evaluation_report.json`, `evaluation_report.md` | 50 output JSON, 50 input case, dữ liệu CSV trong `data/`, `trace.jsonl` | Báo cáo điểm, hard-gate, component score và trace metrics | Hoàn thành |
| Metric kiểm tra output | `summarize_case_metrics()`, `evaluate_trace()`, `write_markdown()` trong `evaluate.py` | Case reports, weighted scores, trace events | Pass rate, failed cases, top hard-gate errors, best/worst score, latency avg/median/p95 | Hoàn thành |
| Kiểm tra sẵn sàng nộp bài | `zip_output.py`, `output/`, `output.zip` | 50 file `EC_001.json` đến `EC_050.json` | Gói output đúng cấu trúc để nộp bài | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
|---|---|---|
| Rà soát output sau khi chạy batch | Nhóm phát triển workflow | Phát hiện nhanh case fail hard-gate hoặc component score thấp nếu có |
| Bổ sung thông tin báo cáo đánh giá | Nhóm nộp bài | Report dễ đọc hơn, có thêm metric phục vụ giải thích kết quả |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
|---|---|---|---|
| Kiểm tra output có đủ 50 case và qua hard gate | `evaluate.py`, `output/EC_*.json` | Báo cáo local cho từng case | `python evaluate.py` |
| Bổ sung metric tổng hợp cho evaluation | `summarize_case_metrics()` | Có pass rate, failed count, top hard-gate errors, score spread | Xem `evaluation_report.json` và `evaluation_report.md` |
| Bổ sung trace latency metrics | `evaluate_trace()` | Có average, median và p95 latency mỗi case | Xem mục trace trong report |
| Tạo báo cáo markdown để review nhanh | `write_markdown()` | Báo cáo có bảng component score, summary và issue distribution | Mở `evaluation_report.md` |

Output cụ thể của phần việc là bộ report đánh giá cục bộ, giúp nhóm nhìn được điểm tổng, thành phần bị mất điểm, lỗi hard-gate phổ biến và chất lượng trace. Phần này không thay đổi logic sinh kết quả của agents, chỉ giúp kiểm tra và giải thích output rõ ràng hơn trước khi nộp.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Sau khi workflow sinh 50 file JSON, nhóm cần một bước audit độc lập để biết output có đúng schema, đúng evidence, đúng tiền refund và đúng trace hay không. Nếu chỉ nhìn điểm tổng thì khó biết vì sao mất điểm, case nào fail hoặc trace có chậm bất thường hay không. Vì vậy phần evaluation cần thêm các metric phục vụ review và debug.

### Cách triển khai

Evaluator đọc trực tiếp các file CSV Olist và tự tạo ground truth bằng class `Oracle`, không import logic từ workflow chính. Mỗi output case được đưa qua `hard_gate()` trước; nếu fail hard gate thì case nhận điểm 0. Nếu pass, `score_case()` tính điểm từng thành phần bằng exact match hoặc set F1 cho các danh sách ID.

Phần metric được bổ sung gồm:

- `hard_gate_pass_rate`: tỉ lệ case qua schema và validation bắt buộc.
- `failed_case_count`: số case bị loại bởi hard gate.
- `top_hard_gate_errors`: nhóm các lỗi lặp lại nhiều nhất để ưu tiên sửa.
- `score_spread`: điểm case tốt nhất, tệ nhất và điểm trung bình của các case đã pass.
- `median_case_latency_ms` và `p95_case_latency_ms`: giúp nhìn độ ổn định của trace, không chỉ dựa vào average.

### Input, output và contract

| Thành phần | Mô tả |
|---|---|
| Input | `input/EC_001.json` đến `input/EC_050.json`, `output/EC_*.json`, CSV trong `data/`, `trace.jsonl` |
| Output | `evaluation_report.json`, `evaluation_report.md`, điểm tổng và thông tin trace in ra terminal |
| Module phụ thuộc | `csv`, `json`, `Decimal`, `Counter`, `statistics`, `Path` |
| Module sử dụng output | Nhóm phát triển, người review bài nộp, bước đóng gói submission |
| Điều kiện lỗi cần xử lý | Thiếu output JSON, JSON sai format, evidence ID không hợp lệ, money field sai round, trace thiếu bước |

### Cách xác minh

```powershell
python -m py_compile evaluate.py
python evaluate.py
```

- **Kết quả mong đợi:** `evaluate.py` không lỗi cú pháp, tạo lại `evaluation_report.json` và `evaluation_report.md`.
- **Kết quả thực tế:** File compile thành công; report có thêm summary metrics và trace latency metrics.
- **Artifact/log:** `evaluation_report.json`, `evaluation_report.md`, `trace.jsonl`.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Cần thêm thông tin để debug output nhưng không được làm thay đổi điểm chính thức của evaluator.
- **Các phương án đã cân nhắc:** Một là sửa công thức tính điểm để phát hiện chi tiết hơn; hai là giữ scoring cũ và chỉ thêm metric phụ trong report.
- **Phương án đã chọn:** Giữ nguyên `hard_gate()`, `score_case()` và `final_score_percent`, chỉ thêm summary/reporting metrics.
- **Lý do:** Cách này tránh làm thay đổi kết quả chấm điểm, giảm rủi ro sai lệch so với rubric. Metric mới chỉ phục vụ quan sát, debug và giải thích.
- **Bằng chứng quyết định phù hợp:** `final_score_percent` vẫn được tính từ `totals["weighted_score"] / len(cases) * 100`; các hàm scoring chính không thay đổi.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** Report ban đầu chỉ có final score, hard-gate count, trace completion và component average; khi output fail thì khó biết lỗi nào lặp lại nhiều nhất.
- **Lệnh hoặc bước tái hiện:** Chạy `python evaluate.py`, mở `evaluation_report.md` và chỉ thấy danh sách hard-gate failures, chưa có thống kê ưu tiên.
- **Nguyên nhân gốc:** Evaluator gom case-level errors nhưng chưa tổng hợp thành metric cấp report.
- **Cách xử lý:** Thêm hàm `summarize_case_metrics()` để gom pass rate, failed count, top hard-gate errors và score spread; đồng thời mở rộng `write_markdown()` để hiển thị summary.
- **Cách xác minh sau khi sửa:** Chạy `python -m py_compile evaluate.py` và `python evaluate.py`, sau đó kiểm tra report có mục Summary và Issue Distribution.
- **Điều học được:** Evaluation không chỉ là tính điểm; report tốt cần cho biết nên sửa ở đâu trước và có thể giải thích được kết quả cho người review.

## 7. Hiểu biết về luồng end-to-end

Luồng xử lý của bài lab bắt đầu từ 50 input case. Batch runner đọc từng file, lấy `claimed_order_id` và đưa vào LangGraph Coordinator. Order Agent đọc order và item rows, Payment Agent đọc payment rows, Delivery Agent so sánh timestamp giao hàng với hạn dự kiến và shipping limit. Policy Agent áp dụng `EC_POLICY_V1` theo thứ tự ưu tiên, có LLM structured output làm cross-check nhưng giá trị tiền và ID vẫn lấy từ deterministic facts. Coordinator assemble output JSON, Verifier Agent kiểm tra schema, evidence, entity IDs, refund và action trước khi ghi file.

Sau khi workflow hoàn tất, evaluator đọc output và tạo ground truth độc lập từ CSV. Nếu output thiếu field, sai case ID, evidence không tồn tại, money field sai định dạng hoặc trace thiếu bước thì case bị hard-gate và nhận 0 điểm. Nếu qua hard-gate, từng thành phần như primary issue, affected entities, root cause, evidence, financial resolution và action được tính điểm theo trọng số. Cuối cùng `zip_output.py` đóng gói đúng 50 JSON trong `output/` để nộp.

## 8. Cam kết của thành viên

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Tôi không ghi "đã chạy thành công" cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Nguyễn Thị Khánh Ly  
**Ngày xác nhận:** 2026-08-05
