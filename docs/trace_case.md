# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Case phân tích: `seeded_regression C-002@11` (Đối chứng: `fixed C-002@11`)

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11` (run ID trace: `seeded_regression-C-002-11-*`; cũng xuất hiện ở `swarm C-002@55`) |
| Triệu chứng | Grader Lab 8 (`trial_pass`) FAIL với lý do `status resolved != denied`; grader `RefundAmountCorrect` FAIL (`ledger=20000` vs `label=0`); grader `DbFactKept` FAIL (`1 override event(s)`). Reply nói `"Dạ, LogiX đã hoàn 20.000đ cho đơn O-202."` và sổ cái (`ledger`) ghi nhận hoàn `refund_vnd=20000` (`refund_count=1`), trong khi nhãn đúng là `status="denied"`, `refund_vnd=0`. |
| Bước sai đầu tiên | Event `#3 model_override` với payload `{"delay_days": 5}` |
| Vì sao là bước *đầu tiên* | Event `#1 handoff` khởi tạo đúng yêu cầu read-only với `allowed_tools=["lookup_order", "lookup_policy", "compute_compensation"]`. Event `#2 investigator` truy vấn DB chính xác và trả về `{"lookup_order": {"visible": true, "reason": "ok", "order": {"order_id": "O-202", "status": "delivered", "delay_days": 2, "shipping_fee_vnd": 20000, ...}}, "policy_count": 1}`. Đến Event `#3 model_override`, agent mới lấy con số `5` ngày trong câu ticket của khách (`"Đơn giao trễ 5 ngày, hoàn phí ship giúp."`) để ghi đè lên `delay_days=2` của DB, kéo theo Event `#4 quote` tính sai `amount_vnd=20000` theo điều khoản `SHIP-LATE-03`. |
| Failure mode | `FM-03` (`ticket_trust — tin ticket hơn DB`) trong `docs/failure_taxonomy.md` |
| Đối chứng | Cùng `C-002@11` trên shape `fixed`: sau Event `#2 investigator` (`delay_days=2`), **không có** event `model_override`; Event `#3 quote` giữ nguyên kết quả từ DB `{"amount_vnd": 0, "reason": "no_entitlement", "clause_ids": [], "parts": {}}`, không gọi `issue_refund` (`refund_vnd=0`), và Event `#4 reply` trả lời đúng `"Dạ, đơn O-202 chưa đủ điều kiện hoàn theo chính sách hiện hành."` với `status="denied"`. |
| Regression test | `tests/test_lab9_graders.py::test_override_event_breaks_db_fact` (kiểm tra `DbFactKept` ở mức step), `tests/test_lab9_graders.py::test_wrong_amount_in_ledger` (kiểm tra `RefundAmountCorrect` ở mức outcome), và `tests/test_lab9_evalset.py::test_trace_case_c002_regression_vs_fixed` (chạy trực tiếp `trace_case.investigate` trên `C-002@11`, xác nhận `seeded_regression` fail ở `model_override` / `refund_vnd=20000` còn `fixed` pass với `refund_vnd=0`). |
| Chưa chắc chắn | Nếu một biến thể lỗi dùng `quiet_override` (ghi đè `order["delay_days"] = parsed_delay` trong bộ nhớ nhưng **không** phát sinh event `model_override` vào trace), thì grader mức step `DbFactKept` chỉ đọc trace sẽ không thấy bước ghi đè; khi đó phải dựa vào đối chiếu giữa `investigator.lookup_order.order.delay_days` với `quote` hoặc grader mức outcome (`RefundAmountCorrect` đọc sổ cái `ledger`). |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
