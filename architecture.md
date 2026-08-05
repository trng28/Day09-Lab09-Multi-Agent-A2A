# Multi-Agent E-commerce Dispute Resolution Architecture

## 1. Tổng quan

Hệ thống xử lý 50 khiếu nại thương mại điện tử bằng một workflow LangGraph gồm
năm domain agent. Dữ liệu và phép tính tài chính được xử lý deterministic từ CSV;
`gpt-4o-mini` được dùng trong Policy Agent với Structured Outputs. Mọi quyết định
của model phải đồng thuận với policy engine trước khi được ghi vào output.

```text
input/EC_xxx.json
        |
        v
+-----------------------+
| LangGraph Coordinator |
+-----------+-----------+
            |
            v
      Order Agent
            |
            v
     Payment Agent
            |
            v
     Delivery Agent
            |
            v
 Policy Agent (gpt-4o-mini)
            |
            v
      Assemble Output
            |
            v
     Verifier Agent
            |
            +----------> trace.jsonl
            |
            v
   output/EC_xxx.json
```

Coordinator chỉ điều phối state và handoff. Logic đọc dữ liệu nằm trong các data
agent; logic quyết định nằm trong Policy Agent; kiểm tra giới hạn nằm trong
Verifier Agent.

## 2. Cấu trúc source code

```text
Day09-Lab09-Multi-Agent-A2A/
├── src/
│   ├── agents/
│   │   ├── __init__.py
│   │   └── services.py        # A2A models và 5 agent
│   ├── coordinator/
│   │   ├── __init__.py
│   │   └── workflow.py        # LangGraph state, nodes và handoff
│   ├── repository/
│   │   ├── __init__.py
│   │   └── olist.py           # CSV repository
│   ├── api.py                 # FastAPI
│   └── main.py                # Batch runner
├── data/                      # 9 Olist CSV
├── input/                     # EC_001.json ... EC_050.json
├── output/                    # 50 assessment JSON
├── run.py                     # CLI entrypoint
├── evaluate.py                # Independent local evaluator
├── zip_output.py              # Tạo output.zip
├── trace.jsonl                # Trace của lần chạy gần nhất
├── metadata.json
└── requirements.txt
```

## 3. LangGraph workflow

State dùng chung có các trường:

```text
case
order_result
payment_result
delivery_result
policy_result
output
trace
```

Đồ thị chạy tuần tự để mỗi agent nhận artifact đã được kiểm chứng từ bước trước:

```text
START
  -> order
  -> payment
  -> delivery
  -> policy
  -> assemble
  -> verify
  -> END
```

Việc chạy tuần tự giúp trace dễ audit và bảo đảm Policy Agent không chạy khi dữ
liệu order/payment/delivery chưa hoàn tất.

## 4. A2A handoff contract

Mỗi node giao việc qua `A2ATask`:

```json
{
  "task_id": "EC_001-order-a1b2c3d4",
  "case_id": "EC_001",
  "agent": "order",
  "payload": {
    "order_id": "<olist_order_id>"
  },
  "context": {}
}
```

Agent trả về `A2AResult`:

```json
{
  "task_id": "EC_001-order-a1b2c3d4",
  "status": "completed",
  "artifact": {}
}
```

`payload` chứa yêu cầu trực tiếp. `context` chứa artifact từ agent trước. Agent
không truy cập toàn bộ LangGraph state nếu không cần thiết.

## 5. Trách nhiệm và quyền truy cập

| Component | Quyền đọc | Trách nhiệm |
|---|---|---|
| Coordinator | Input và artifacts | Tạo task, handoff, assemble, trace |
| Order Agent | Orders, order items | Status, item, seller, item/freight totals |
| Payment Agent | Payments | Payment rows, IDs và tổng payment |
| Delivery Agent | Order artifact | So sánh delivery/carrier/shipping limits |
| Policy Agent | Verified artifacts | Áp `EC_POLICY_V1`, gọi `gpt-4o-mini` |
| Verifier Agent | Output JSON | Schema limits, confidence, refund/status consistency |
| Olist Repository | Required CSV files | Load, index và sắp xếp rows ổn định |

Policy Agent không tự đọc CSV. Model không nhận customer message làm nguồn sự
thật; model chỉ nhận facts đã được các data agent truy xuất.

## 6. Domain agents

### 6.1 Order Agent

Order Agent nhận `order_id`, truy xuất order và item rows, sau đó trả:

- order status và timestamps;
- item rows;
- `item_total_brl`;
- `freight_total_brl`;
- item IDs và seller IDs, tối đa năm ID mỗi nhóm.

Item rows được sắp xếp theo `order_item_id` để output reproducible.

### 6.2 Payment Agent

Payment Agent chỉ truy xuất payment rows và trả:

- số payment rows;
- `payment_total_brl`;
- payment IDs.

Payment rows được sắp xếp theo `payment_sequential`. Tổng tiền dùng `Decimal` và
làm tròn hai chữ số theo `ROUND_HALF_UP`.

### 6.3 Delivery Agent

Delivery Agent phân tích:

```text
order_delivered_customer_date > order_estimated_delivery_date
order_delivered_carrier_date > shipping_limit_date
```

Artifact gồm:

```text
late
seller_late
late_seller_ids
logistics_late
delivery_within_estimate
```

Seller chỉ bị quy trách nhiệm khi order giao trễ và carrier nhận hàng sau
`shipping_limit_date` của item thuộc seller đó.

### 6.4 Policy Agent

Policy Agent áp rule theo đúng priority:

```text
1. canceled_order_paid
2. unavailable_order_paid
3. late_delivery_seller
4. late_delivery_logistics
5. valid_split_payment
6. unsupported_late_claim
```

Policy Agent dùng model cố định:

```text
gpt-4o-mini
temperature = 0.2
structured output = PolicyDecision
vote runs = 3
parallel workers = 3
```

`PolicyDecision` giới hạn issue, root cause và action bằng enum/Literal. Prompt
cấm model tạo evidence, ID, timestamp hoặc giá trị tiền không có trong facts.

Mỗi case được model phân tích độc lập 10 lần. Các structured decision được chuẩn
hóa thành signature gồm issue, cause, action, party và refund, sau đó chọn majority
vote. Nếu nhiều phương án bằng phiếu, signature đồng thuận với deterministic
policy engine được dùng làm tie-breaker. Policy guard tiếp tục kiểm tra phương án
thắng trước khi assemble output.

### 6.5 Deterministic policy guard

Trước khi gọi model, policy engine tự tính expected issue, cause, responsible
party, refund và action từ facts. Output luôn lấy issue/cause/party/refund/action
từ policy engine deterministic này, không bao giờ từ model — model chỉ đóng vai
trò cross-check độc lập để ghi lại vào trace (`model_agreed_with_policy_engine`,
`vote_share`, ...) phục vụ audit.

Vì output không phụ thuộc vào model, một lần model bất đồng (do sampling noise
của LLM) không làm giảm độ tin cậy thực tế của giá trị đã được xác minh từ CSV.
`confidence` vì vậy luôn cố định ở 0.99, phản ánh đúng mức độ được kiểm chứng của
output, thay vì nhiễu từ redundant LLM cross-check.

Tiền và entity ID luôn lấy từ deterministic engine. Model không có quyền thay đổi
các giá trị có thể kiểm chứng từ CSV.

### 6.6 Verifier Agent

Verifier chạy sau khi output được assemble và kiểm tra:

- `confidence` thuộc `[0, 1]`;
- tối đa 5 ID cho mỗi entity set;
- tối đa 10 evidence IDs;
- tối đa 3 causes và responsible parties;
- tối đa 5 actions;
- `case_status` đồng nhất với `recommended_refund_brl`.

Output không được ghi nếu verifier phát hiện lỗi.

## 7. Evidence strategy

Hệ thống dùng evidence tối thiểu theo từng primary issue để giảm false positive:

| Issue | Evidence |
|---|---|
| Canceled/unavailable paid | order, payments, policy |
| Late delivery seller | order, relevant items, payments, responsible seller, policy |
| Late delivery logistics | order, items, payments, policy |
| Valid split payment | order, items, all payments, policy |
| Unsupported late claim | order, items, payments, policy |

Evidence được giới hạn 10 ID và luôn giữ policy evidence. Seller evidence không
được thêm khi seller không phải bên chịu trách nhiệm.

## 8. Trace và audit

Mỗi agent tạo một event trong `trace.jsonl`:

```json
{
  "case_id": "EC_001",
  "step": "PolicyAgent",
  "task_id": "EC_001-policy-a1b2c3d4",
  "status": "completed",
  "duration_ms": 842.35,
  "model": "gpt-4o-mini",
  "model_agreed_with_policy_engine": true,
  "model_fully_agreed_with_policy_engine": true,
  "vote_runs": 10,
  "winning_votes": 9,
  "vote_share": 0.9,
  "vote_distribution": []
}
```

`model_agreed_with_policy_engine` kiểm tra issue/cause/action. Trường `full`
kiểm tra thêm party và refund. Dù full agreement là false, các giá trị tiền và ID
vẫn lấy từ deterministic engine và phải qua Verifier Agent.

Một batch hợp lệ có 250 events: năm agent events cho mỗi một trong 50 case.
`trace.jsonl` luôn bị ghi đè ở lượt chạy mới, không append trace cũ.

## 9. Runtime interfaces

### Batch CLI

```powershell
.\.venv\Scripts\python.exe run.py
```

Batch runner đọc `input/EC_*.json`, tạo output cùng tên và ghi trace mới.

### FastAPI

```powershell
.\.venv\Scripts\uvicorn.exe src.api:app --reload
```

Endpoints:

```text
GET  /health
POST /cases/assess
```

## 10. Evaluation và submission

Local evaluator độc lập đọc CSV và tự dựng ground truth:

```powershell
.\.venv\Scripts\python.exe evaluate.py
```

Nó kiểm tra hard gate, weighted score và trace, sau đó tạo:

```text
evaluation_report.json
evaluation_report.md
```

Tạo file submission:

```powershell
.\.venv\Scripts\python.exe zip_output.py
```

Archive hiện có cấu trúc:

```text
output.zip
└── output/
    ├── EC_001.json
    ├── ...
    └── EC_050.json
```

## 11. Security và reproducibility

- `OPENAI_API_KEY` chỉ nằm trong `.env` và `.env` được ignore.
- Model name nằm trong source code và `metadata.json`.
- Không ghi API key, prompt secrets hoặc raw credentials vào trace.
- CSV là nguồn sự thật duy nhất cho facts, entity IDs và tiền.
- `temperature=0`, sorted IDs và deterministic policy guard giúp kết quả ổn định.
- Mọi phép tính tiền dùng `Decimal`, không dùng phép cộng float trực tiếp.
