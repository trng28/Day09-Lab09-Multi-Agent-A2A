# Member Role Report — Day 9: Multi Agent A2A

## 1. Thông tin cá nhân

| Thông tin       | Nội dung     |
| --------------- | ------------ |
| Họ và tên       | Nguyễn Thị Tuyết Mai  |
| MSSV            | 2A202601693     |
| Khóa/Lớp        | K3         |
| Vai trò chính   | Test Developer / QA (Phát triển Bộ Testcase)    |
| Ngày hoàn thành | 2026-08-05 |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao   | Trạng thái                            |
| ------------------ | ------------------ | -------------- | ----------------- | ------------------------------------- |
| Phát triển Bộ Testcase tự động (Unit/Integration Tests) | `tests/test_agents.py`, `tests/test_policy.py`, `tests/test_workflow.py`, `tests/test_repository.py` | API specs, logic nghiệp vụ, cấu trúc dữ liệu Olist CSV | Bộ test suite chạy 18 testcase độc lập | Hoàn thành |
| Cài đặt Test Runner | `run_tests.py` | Toàn bộ các testcase trong `tests/` | Kịch bản chạy test tích hợp CI/CD | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động                 | Thành viên/module được hỗ trợ | Kết quả                 |
| ------------------------- | ----------------------------- | ----------------------- |
| Viết tài liệu hướng dẫn chạy test | Nhóm phát triển / QA | File `walkthrough.md` mô tả chi tiết cách kiểm thử hệ thống |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao          | Cách xác minh   |
| --------------------- | --------------------------- | ------------------------- | --------------- |
| Viết bộ testcase kiểm thử 5 Agents & OlistRepository | `tests/test_agents.py`, `tests/test_policy.py`, `tests/test_repository.py` | 17 unit testcases kiểm tra các ca biên | `python run_tests.py` |
| Kiểm thử tích hợp State Graph LangGraph | `tests/test_workflow.py` | 1 integration testcase chạy toàn luồng | `python run_tests.py` |

Nêu một output cụ thể mà phần việc của bạn tạo ra hoặc giúp xác minh:

Bàn giao kịch bản kiểm thử tự động toàn diện giúp xác minh độ chính xác của 5 Agent độc lập và luồng LangGraph tích hợp. Output cụ thể là 18/18 testcases chạy thành công trong 0.039 giây, cho phép kiểm thử toàn bộ logic nghiệp vụ mà không cần kết nối API OpenAI, tiết kiệm tài nguyên và bảo đảm độ ổn định.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Phần việc của tôi giải quyết vấn đề kiểm thử chất lượng, độ chính xác và tính toàn vẹn của dữ liệu trong pipeline của hệ thống Dispute Resolution. Điều này đảm bảo rằng các thay đổi trong source code của các agent hoặc quy tắc chính sách (policy) không làm hỏng logic nghiệp vụ hiện tại, đồng thời xác thực cấu trúc đầu ra khớp với schema quy định của Olist.

### Cách triển khai

Sử dụng thư viện `unittest` của Python và cơ chế Mock (`unittest.mock.patch`) để cô lập các tác vụ:
1. Giả lập dữ liệu CSV của `OlistRepository` để tăng tốc độ chạy test và chạy độc lập với tệp dữ liệu thực tế.
2. Giả lập (Mock) lớp `ChatOpenAI` của LangChain để chặn các cuộc gọi mạng đến OpenAI API, mô phỏng các kết quả biểu quyết (majority voting) khác nhau từ mô hình `gpt-4o-mini` để kiểm thử logic của `PolicyAgent`.
3. Kiểm thử các trường hợp biên và đặc biệt tại `VerifierAgent` như confidence nằm ngoài `[0, 1]` hay các sai lệch về tài chính.

### Input, output và contract

| Thành phần              | Mô tả                                  |
| ----------------------- | -------------------------------------- |
| Input                   | Mã nguồn của các Agent, Repository, Workflow và cấu hình Mock |
| Output                  | Trạng thái kết quả chạy 18 testcases (Passed / Failed) |
| Module phụ thuộc        | `src/agents/services.py`, `src/coordinator/workflow.py`, `src/repository/olist.py` |
| Module sử dụng output   | Quy trình CI/CD và báo cáo kiểm thử chất lượng trước khi release |
| Điều kiện lỗi cần xử lý | Mất kết nối API (được giải quyết bằng Mocking), sai dữ liệu đầu vào |

### Cách xác minh

```bash
python run_tests.py
```

- **Kết quả mong đợi:** Toàn bộ 18 testcases được phát hiện và chạy thành công mà không gặp lỗi nào, đưa ra thông báo `All tests passed successfully!`.
- **Kết quả thực tế:** 18 bài test đã chạy thành công trong 0.039 giây.
- **Artifact/log:** Các file kiểm thử nằm trong thư mục `tests/` và script `run_tests.py`.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Lựa chọn phương án kiểm thử cho PolicyAgent phụ thuộc vào OpenAI LLM.
- **Các phương án đã cân nhắc:**
  1. Chạy test thực tế kết nối trực tiếp đến API OpenAI (sử dụng API key).
  2. Mock hoàn toàn module `ChatOpenAI` để giả định các câu trả lời có cấu trúc của mô hình.
- **Phương án đã chọn:** Phương án 2 (Mock hoàn toàn).
- **Lý do:** Giúp bộ test chạy nhanh vượt trội (0.04 giây thay vì hàng chục giây), không phát sinh chi phí token API, không bị gián đoạn khi gặp sự cố mạng hoặc hết hạn API key, dễ dàng mô phỏng các kịch bản bất đồng ý kiến giữa LLM và Policy Engine để kiểm tra cơ chế fallback tin cậy.
- **Bằng chứng quyết định phù hợp:** Chạy test thành công offline với thời gian 0.044s.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** Lỗi khởi tạo `PolicyAgent` do thiếu biến môi trường `OPENAI_API_KEY` trong quá trình chạy test trên môi trường CI/CD không cấu hình key.
- **Lệnh hoặc bước tái hiện:** `python -m unittest discover -s tests` khi chưa thiết lập file `.env`.
- **Nguyên nhân gốc:** Khởi tạo `PolicyAgent` gọi trực tiếp constructor `ChatOpenAI()` bên trong `__init__`, constructor này sẽ kiểm tra biến môi trường và ném lỗi nếu không tìm thấy key.
- **Cách xử lý:** Sử dụng `patch("src.agents.services.ChatOpenAI")` để giả lập lớp `ChatOpenAI` trước khi import hoặc khởi tạo `PolicyAgent`, đảm bảo đối tượng mock được trả về thay thế cho đối tượng thực tế.
- **Cách xác minh sau khi sửa:** Chạy thành công `python run_tests.py` khi xóa bỏ cấu hình `OPENAI_API_KEY` trong `.env`.
- **Điều học được:** Khi thiết kế các Agent có sử dụng LLM, cần đảm bảo dependencies có thể dễ dàng thay thế hoặc mock được để phục vụ cho các môi trường kiểm thử cô lập.

## 7. Hiểu biết về luồng end-to-end

Giải thích ngắn gọn bằng lời của bạn:

1. Dữ liệu đi từ Crossref đến vector index như thế nào?
2. Evaluation set và ground-truth document IDs dùng để đo retrieval/answer quality ra sao?
3. Quality checks khác freshness monitoring ở điểm nào trong bài lab?
4. Vì sao phải dùng cùng test set cho baseline, corrupted và repaired?
5. Repair được xem là thành công dựa trên artifact và metric nào?

**Câu trả lời:**

1. **Dữ liệu đi từ Crossref đến vector index:** Trong bài Lab 8, dữ liệu được tải từ Crossref API dưới dạng JSON, sau đó được chia nhỏ thành các đoạn text (chunking), chuyển thành vector embedding thông qua mô hình OpenAI embedding, và cuối cùng được nạp vào Vector Database (như FAISS hoặc Chroma) để đánh chỉ mục. Đối với Lab 9 này, dữ liệu Olist được lưu trữ dưới dạng CSV, được nạp bởi OlistRepository và đánh chỉ mục theo `order_id` để các Agent truy vấn nhanh chóng.
2. **Đo retrieval/answer quality:** Evaluation set chứa các câu hỏi kiểm thử và danh sách các Ground-truth Document IDs chứa câu trả lời đúng. Retrieval quality được đo bằng F1-score/Recall để đánh giá xem hệ thống có truy xuất đúng tài liệu không. Answer quality được đo bằng cách so sánh câu trả lời sinh ra bởi mô hình LLM với Ground-truth bằng mô hình LLM trọng tài (evaluator) hoặc logic đối khớp. Trong Lab 9, các metric như `primary_issue`, `financial_resolution` được đối chiếu trực tiếp với bộ quy tắc logic xác định để cho điểm 100/100.
3. **Quality checks vs Freshness monitoring:** Quality checks tập trung vào tính đúng đắn, tính toàn vẹn và độ khớp của dữ liệu (như schema đầu ra, đối soát tài chính). Freshness monitoring tập trung vào tính thời gian thực, độ trễ và tần suất cập nhật dữ liệu để đảm bảo thông tin không bị lỗi thời.
4. **Dùng chung test set cho baseline, corrupted và repaired:** Việc dùng chung một test set đảm bảo tính công bằng (fair comparison), loại bỏ các biến số ngẫu nhiên từ dữ liệu đầu vào và giúp đánh giá chính xác hiệu quả cải tiến hay sửa lỗi của hệ thống qua các phiên bản.
5. **Đánh giá Repair thành công:** Repair thành công khi điểm số cuối cùng (final score) trong `evaluation_report.md` đạt mức mong đợi (100/100), không còn lỗi hard-gate, và trace completion đạt 100%.

## 8. Cam kết của thành viên

Đánh dấu sau khi tự kiểm tra:

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Tôi không ghi “đã chạy thành công” cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Nguyễn Thị Tuyết Mai
**Ngày xác nhận:** 2026-08-05
