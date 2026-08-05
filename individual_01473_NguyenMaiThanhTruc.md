# Báo cáo cá nhân — Multi-Agent A2A

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
|---|---|
| Họ và tên | Nguyễn Mai Thanh Trúc |
| MSSV | 2A202601473 |
| Khóa/Lớp | K3 |
| Vai trò chính | Thiết kế A2A architecture và workflow orchestration |
| Ngày hoàn thành | 05-08-2026 |

## 2. Phạm vi công việc

| Phần việc | File liên quan | Kết quả |
|---|---|---|
| Thiết kế luồng A2A | `architecture.md` | Xác định vai trò agent, quyền truy cập và handoff |
| LangGraph orchestration | `src/coordinator/workflow.py` | Workflow Order → Payment → Delivery → Policy → Verifier |
| A2A contract và agents | `src/agents/services.py` | `A2ATask`, `A2AResult` và năm domain agent |
| Tích hợp hệ thống | `src/main.py`, `src/api.py` | Batch CLI và FastAPI assessment endpoint |
| Evaluation và submission | `evaluate.py`, `zip_output.py` | Báo cáo local và file `output.zip` |

## 3. Kết quả bàn giao

- Workflow xử lý đủ 50 input và tạo 50 output JSON.
- Mỗi case có năm trace events; toàn bộ batch có 250 events.
- Policy Agent dùng `gpt-4o-mini` với Structured Outputs và majority voting ba lượt.
- Deterministic policy guard kiểm tra issue, cause, action, party và refund.
- Verifier kiểm tra schema, entity, evidence, tài chính và giới hạn output.
- Local evaluator: 50/50 case qua hard gate, trace completion 100%.

## 4. Phần kỹ thuật thực hiện

Coordinator lưu artifacts trong `WorkflowState` và chỉ làm nhiệm vụ điều phối.
Mỗi node nhận `A2ATask`, xử lý đúng domain rồi trả `A2AResult`. Order và Payment
Agent đọc CSV; Delivery Agent phân tích timestamp; Policy Agent áp
`EC_POLICY_V1`; Verifier chạy trước khi output được ghi.

Policy Agent gọi `gpt-4o-mini` ba lần song song, chuẩn hóa các structured decision
và chọn majority vote. Kết quả thắng vẫn phải qua deterministic guard. Giá trị
tiền và ID luôn lấy từ CSV, không lấy từ dữ kiện model tự sinh.

| Contract | Nội dung |
|---|---|
| Input | Case JSON có `case_id`, `claimed_order_id`, `policy_version` |
| Handoff | `A2ATask`/`A2AResult` với task ID và artifact |
| Output | Assessment JSON đúng schema trong README |
| Lỗi được chặn | Order không tồn tại, policy không hỗ trợ, evidence hoặc tiền sai |

## 5. Quyết định kỹ thuật chính

Thay vì để một prompt xử lý toàn bộ case, hệ thống tách data agents và Policy
Agent. Model hỗ trợ suy luận nhưng không phải nguồn sự thật. Cách này giữ được
đặc trưng multi-agent/A2A, đồng thời giảm hallucination nhờ policy guard và
Verifier. Majority voting được dùng để giảm ảnh hưởng của một lần model trả sai.

## 6. Lỗi đã xử lý

Trong thử nghiệm, model đôi lúc chọn đúng issue nhưng trả refund sai cho order
`unavailable` không có item. Nguyên nhân là model nhầm `item_total_brl = 0` với
khoản hoàn. Prompt được làm rõ rằng refund phải bằng `payment_total_brl`; ngoài
ra deterministic guard luôn ghi giá trị tiền tính từ CSV. Sau sửa, decision vote
được kiểm tra lại trước khi tạo output.

## 7. Hiểu luồng end-to-end

1. Batch runner đọc case và lấy `claimed_order_id`.
2. Order, Payment và Delivery Agent tạo các facts có thể kiểm chứng từ CSV.
3. Policy Agent áp rule theo thứ tự ưu tiên và dùng model voting để phân tích.
4. Deterministic guard đối chiếu quyết định, responsible party và refund.
5. Coordinator assemble output với evidence tối thiểu theo từng issue.
6. Verifier kiểm tra output; case hợp lệ mới được ghi vào `output/` và trace.
7. `evaluate.py` chấm local; `zip_output.py` đóng gói 50 JSON để nộp.

Lệnh xác minh:

```powershell
python run.py
python evaluate.py
python zip_output.py
```

## 8. Cam kết

- [x] Báo cáo phản ánh đúng source code và phần việc đã thực hiện.
- [x] Có thể giải thích luồng end-to-end và contract giữa các agent.
- [x] Các kết quả nêu trên đã được kiểm chứng bằng output và trace.
- [x] Báo cáo không chứa API key, token hoặc nội dung `.env`.

**Họ và tên:** Nguyễn Mai Thanh Trúc  
**Ngày xác nhận:** 05-08-2026
