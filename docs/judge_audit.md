# Judge audit

Chạy:
```bash
python -m lab9.judge --csv data/eval/judge_tone_public.csv --audit 10
python -m lab9.judge --csv data/eval/judge_helpful_public.csv --audit 10
```

| Tiêu chí | n | κ | Precision | Recall | Tỉ lệ lỗi quan sát → hiệu chỉnh (Rogan-Gladen) | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|---|
| `tone_ok` (`judge_tone_public.csv`) | 100 | 0.757 | 0.857 | 0.800 | `0.280 → 0.300` (`tp=24, fp=4, fn=6, tn=66`) | **PASS** | **Dùng** (theo dõi / làm tiêu chí giọng điệu sau khi siết rubric) |
| `helpful` (`judge_helpful_public.csv`) | 100 | 0.375 | 1.000 | 0.300 | `0.090 → 0.300` (`tp=9, fp=0, fn=21, tn=70`) | **FAIL** (R=0.300 < 0.7, κ=0.375 < 0.6) | **Loại** (tuyệt đối không dùng làm gate) |

## ≥5 case audit thủ công

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú & hành động sửa rubric |
|---|---|---|---|---|---|
| 1 | `H-008` (`tone`) | `PASS` | `FAIL` | Người đúng | `"Em đã hoàn tiền cho anh rồi nha, anh check giúp em."` — xưng `"em"` + `"nha"` quá suồng sã; judge bị đánh lừa là thân thiện. **Sửa rubric `tone_ok`:** bắt buộc xưng hô chuẩn CSKH (`"LogiX"` / `"anh/chị"`), cấm khẩu ngữ `"nha"`, `"ok"`, `"em"`/`"bạn"`. |
| 2 | `H-029` (`tone`) | `PASS` | `FAIL` | Người đúng | `"Dạ, vui lòng chờ. Hệ thống đang xử lý, không cần nhắn thêm."` — giọng ra lệnh (`"không cần nhắn thêm"`), nhưng judge chỉ nhìn thấy `"Dạ, vui lòng"`. **Sửa rubric `tone_ok`:** thêm quy tắc phạt các câu ra lệnh/ngăn khách phản hồi dù có từ lịch sự ở đầu. |
| 3 | `H-042` (`tone`) | `FAIL` | `PASS` | Người đúng | `"Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ."` — câu ngắn gọn, lịch sự, đủ thông tin nhưng judge phạt nhầm vì `"thiếu xin lỗi"`. **Sửa rubric `tone_ok`:** nêu rõ không yêu cầu câu trả lời nào cũng phải có lời xin lỗi khi giao dịch thành công. |
| 4 | `H-051` (`tone`) | `FAIL` | `PASS` | Người đúng | `"Dạ, LogiX đã refund 90.000đ cho đơn O-202 ạ."` — dùng từ `"refund"` được CS LogiX cho phép, nhưng judge tự ý phạt vì chêm tiếng Anh. **Sửa rubric `tone_ok`:** whitelist thuật ngữ nghiệp vụ cho phép (`refund`, `claim`, `order`). |
| 5 | `H-081` (`tone`) | `FAIL` | `PASS` | Judge đúng | `"Dạ, đơn O-107 chưa đủ điều kiện hoàn theo chính sách hiện hành ạ."` — nhãn người bị gán nhầm do đọc nhầm ticket; judge chấm đúng (`FAIL` hay `PASS` cần kiểm lại nhãn người). **Hành động:** rà soát và sửa lại nhãn chuẩn (golden label) trong tập dữ liệu. |
| 6 | `H-070` (`tone`) | `PASS` | `FAIL` | Người đúng | `"Dạ, LogiX đã hoàn 90.000đ cho đơn O-909 ạ 😂😂"` — dùng emoji cười cợt trong ngữ cảnh khiếu nại. **Sửa rubric `tone_ok`:** cấm emoji/biểu cảm suồng sã trong phản hồi CSKH. |
| 7 | `HL-015` (`helpful`) | `PASS` | `FAIL` | Người đúng | `"Dạ, LogiX đã hoàn 55.000đ cho đơn O-112 ạ."` — thực tế ledger chỉ ghi `40.000đ` (`FM-08`), nhưng judge chỉ đọc text nên không phát hiện sai tiền. **Hành động:** tiền và sự thật nghiệp vụ phải chấm bằng **code grader** (`ReplyAmountAccurate` + `RefundAmountCorrect`), không giao cho LLM judge. |
| 8 | `HL-016` (`helpful`) | `PASS` | `FAIL` | Người đúng | Câu xin lỗi rất dài dòng, văn phong lịch sự nhưng nói sai số tiền (`55.000đ` so với ledger `35.000đ`). Judge bị **verbosity bias** (thiên vị câu dài, nhiều lời xin lỗi) đánh giá `PASS`. **Hành động:** tách tiêu chí văn phong khỏi kiểm tra đúng sự thật bằng code. |

## Kết luận
- **Tiêu chí bị loại:** `helpful` (`judge_helpful_public.csv`) **KHÔNG được dùng làm gate**. Trên ma trận nhầm lẫn (`tp=9, fp=0, fn=21, tn=70`), dù Precision = `1.000` (câu nào judge bắt lỗi thì đều đúng là lỗi), nhưng **Recall chỉ đạt `0.300`** (`fn=21/30` ca lỗi bị bỏ sót, tức bỏ lọt tới **70%** các câu trả lời sai!) và **Cohen's κ = `0.375`** (< ngưỡng tối thiểu `0.6`). Nguyên nhân gốc: trong 21 ca `fn`, phần lớn là các ca nói sai số tiền (`HL-015`, `HL-016`, `HL-020`, `HL-028`...) hoặc sai xưng hô (`HL-047`, `HL-091`, `HL-097`), mà judge không có quyền truy cập ledger và bị thiên vị bởi câu chữ xin lỗi dài dòng (verbosity bias). Hệ quả là tỷ lệ lỗi quan sát được chỉ là `0.09`, thấp hơn hơn 3 lần so với tỷ lệ lỗi thực tế sau hiệu chỉnh Rogan-Gladen (`0.30`).
- **Tiêu chí được giữ lại:** `tone_ok` đạt toàn bộ ngưỡng (`κ=0.757 ≥ 0.6`, `P=0.857 ≥ 0.8`, `R=0.800 ≥ 0.7`), tỉ lệ lỗi quan sát `0.28` khá sát tỉ lệ lỗi hiệu chỉnh `0.30`, có thể dùng sau khi cập nhật rubric (chặn khẩu ngữ/emoji/câu ra lệnh và whitelist từ `"refund"`).
- **Rủi ro còn lại:** Judge chỉ được kiểm trên dữ liệu replay đã công khai; cần nhãn người mới (held-out) và kiểm tra lại sau khi sửa rubric để xác nhận độ ổn định.
