# Overall Architecture

```text
                            +----------------+
                            |  Batch Runner  |
                            |  50 JSON Case  |
                            +-------+--------+
                                    |
                                    v
                      +-----------------------------+
                      |      Coordinator Agent      |
                      |-----------------------------|
                      | - Load case                |
                      | - Discover agents          |
                      | - Delegate task            |
                      | - Aggregate result         |
                      | - Trace                    |
                      +-----+------+-------+-------+
                            |      |       |
              A2A Task       |      |       | A2A Task
                            |      |       |
                            v      v       v
                 +-----------+  +-----------+  +------------+
                 | Order     |  | Payment   |  | Delivery   |
                 | Agent     |  | Agent     |  | Agent      |
                 +-----------+  +-----------+  +------------+
                       |              |               |
                       +--------------+---------------+
                                      |
                                      v
                             +----------------+
                             | Policy Agent   |
                             +----------------+
                                      |
                                      v
                             +----------------+
                             | Verifier Agent |
                             +----------------+
                                      |
                                      v
                               output/EC_xxx.json
```

---

# Folder Structure

```text
src/
│
├── coordinator/
│   ├── coordinator.py
│   ├── orchestrator.py
│   ├── agent_registry.py
│   ├── a2a_client.py
│   └── trace.py
│
├── agents/
│
│   ├── order_agent/
│   │      main.py
│   │      service.py
│   │      agent_card.py
│   │
│   ├── payment_agent/
│   │      main.py
│   │      service.py
│   │
│   ├── delivery_agent/
│   │      main.py
│   │      service.py
│   │
│   ├── policy_agent/
│   │      main.py
│   │      service.py
│   │
│   └── verifier_agent/
│          main.py
│          service.py
│
├── repository/
│      order_repository.py
│      payment_repository.py
│      seller_repository.py
│      customer_repository.py
│
├── data/
│      orders.csv
│      order_items.csv
│      ...
│
├── input/
│      EC_001.json
│      ...
│
├── output/
│
├── trace/
│      trace.jsonl
│
├── architecture.md
├── metadata.json
└── main.py
```

---

# Coordinator Workflow

```text
Load Case

↓

Order Agent

↓

Payment Agent

↓

Delivery Agent

↓

Policy Agent

↓

Verifier Agent

↓

Save JSON
```

Coordinator không xử lý nghiệp vụ.

Nó chỉ:

* phân công
* chờ kết quả
* truyền context
* tổng hợp

---

# Order Agent

Input

```json
{
    "order_id":"..."
}
```

Nhiệm vụ

Đọc

```
orders.csv

order_items.csv

products.csv

seller.csv
```

Output

```json
{
   "status":"delivered",
   "seller_ids":[...],
   "items":[...],
   "shipping_limit":[...]
}
```

---

# Payment Agent

Đọc

```
order_payments.csv
```

Output

```json
{
   "payment_total":115.00,
   "payment_rows":2,
   "payment_ids":[
      "...:1",
      "...:2"
   ]
}
```

---

# Delivery Agent

Input

```
Order Info
```

Kiểm tra

```
estimated_delivery_date

actual_delivery_date

carrier_date

shipping_limit_date
```

Output

```json
{
   "late":true,

   "seller_late":true,

   "logistics_late":false,

   "root_cause":"SELLER_HANDOFF_AFTER_LIMIT"
}
```

---

# Policy Agent

Đây là agent quan trọng nhất.

Input

```
Order Result

Payment Result

Delivery Result
```

Áp dụng bảng Rule.

Ví dụ

```
late_delivery

+

seller late

↓

late_delivery_seller

↓

refund freight
```

Output

```json
{
    "primary_issue":"late_delivery_seller",

    "refund":15,

    "action":"refund_freight",

    "responsible":"seller"
}
```

Policy Agent hoàn toàn không đọc CSV.

Nó chỉ áp rule.

---

# Verifier Agent

Nhiệm vụ

### Verify schema

```
confidence

0-1
```

### Verify evidence

```
order:

item:

payment:

seller:

policy:
```

### Verify

```
refund

payment

freight
```

### Verify

```
max evidence =10

max action =5

...
```

Nếu lỗi

```
Coordinator

↓

Policy

↓

Generate again
```

---

# A2A Message

Coordinator

↓

Order Agent

```json
{
  "task_id":"T001",

  "agent":"order",

  "case":"EC_001",

  "payload":{
      "order_id":"abc123"
  }
}
```

Order Agent

↓

Coordinator

```json
{
    "task":"T001",

    "status":"completed",

    "artifact":{
        ...
    }
}
```

Coordinator

↓

Payment Agent

```json
{
   "task":"T002",

   "context":{

      "order_result":{...}
   }
}
```

Đó chính là handoff.

---

# Agent Responsibilities

| Agent          | Quyền đọc dữ liệu                | Kết quả trả về                      |
| -------------- | -------------------------------- | ----------------------------------- |
| Coordinator    | Không đọc CSV                    | Điều phối workflow                  |
| Order Agent    | orders, items, sellers, products | Thông tin đơn hàng, seller, item    |
| Payment Agent  | payments                         | Tổng tiền, payment IDs              |
| Delivery Agent | orders + items                   | Đánh giá giao hàng, nguyên nhân     |
| Policy Agent   | Không đọc CSV                    | Quyết định issue, refund, action    |
| Verifier Agent | Output JSON                      | Kiểm tra schema, evidence, giới hạn |

---

# Sequence Diagram

```text
Client
   │
   ▼
Coordinator
   │
   ├────────► Order Agent
   │◄────────
   │
   ├────────► Payment Agent
   │◄────────
   │
   ├────────► Delivery Agent
   │◄────────
   │
   ├────────► Policy Agent
   │◄────────
   │
   ├────────► Verifier Agent
   │◄────────
   │
   ▼
output/EC_001.json
```

---

# Trace (`trace.jsonl`)

Mỗi lần Coordinator giao việc sẽ ghi một dòng:

```json
{
  "case_id": "EC_001",
  "step": "OrderAgent",
  "task_id": "T001",
  "status": "completed",
  "duration_ms": 45
}
```

```json
{
  "case_id": "EC_001",
  "step": "PaymentAgent",
  "task_id": "T002",
  "status": "completed",
  "duration_ms": 18
}
```

