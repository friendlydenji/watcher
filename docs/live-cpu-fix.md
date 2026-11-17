# Sửa lỗi live báo không có CPU — 2026-11-17

## Yêu cầu và cách giữ bản cũ

Người dùng chạy app cùng trace nhưng UI thường xuyên báo không có CPU.
Mục tiêu là hiển thị đúng CPU/thread của app trong khi chạy, không mất dữ liệu
khi app ngủ hoặc khi các tiến trình khác phát sinh nhiều scheduler events.

Giữ nguyên thư mục `watcher`, các file trace gốc và các gói bàn giao trước.
Bản sửa lần này nằm riêng ở `watcher-live-fixed`; gói `watcher-live-fixed.zip`
chứa nguồn mới và các file jobs JSON đã khôi phục để mở xem ngay.

## Nguyên nhân đã kiểm chứng từ dữ liệu thực

Hai capture người dùng vừa chạy:

| Scheduler report gốc | Dung lượng | SDK TIDs |
| --- | ---: | --- |
| live-mixed_demo-20261117-094118-65851.txt | 559.476.809 byte | 65890, 65891 |
| live-mixed_demo-20261117-094151-66853.txt | 491.174.753 byte | 66905, 66906 |

Code cũ thu scheduler toàn hệ thống. `/api/live` lấy 524.288 byte cuối report,
sau đó mới lọc TID theo phần cuối SDK log. Trong cả hai file thực, đoạn cuối
vẫn có hàng nghìn scheduler records parse được, nhưng **không có record của
app**. Vì vậy mảng scheduler trả về rỗng; đây không phải máy không có CPU.
Ngoài ra, tab CPU chỉ tạo hàng từ các khoảng running trong cửa sổ hiện tại,
nên một cửa sổ không có running làm các hàng CPU biến mất.

## Những thay đổi

- `live-app.sh`: tạo app ở cổng chờ, giữ đúng PID khi exec. Bật private trace
  instance với `-P <pid> -c` trước khi cho app chạy. Kernel lọc tiến trình và
  theo các thread con, không ghi toàn bộ hệ thống.
- `run_gated.py`: cổng khởi chạy bằng FIFO; app chưa thực thi trước khi tracer
  và reader sẵn sàng. Nếu tracing thất bại, cleanup dừng tiến trình đang chờ.
- `read_trace.py`: đọc trace_pipe không chặn với deadline và flush ngay.
  Lần kiểm tra kernel đầu tiên phát hiện timeout/sudo/cat bị kill (status 137),
  nên thay bằng reader này; bản cuối kết thúc và phân tích thành công.
- `live_session.py`: ghi trạng thái capture nguyên tử. Dashboard phân biệt
  app đang chạy, đã kết thúc, capture hoàn tất/lỗi, thay vì chỉ dựa vào mtime.
- `live_data.py`: đọc tăng dần ở nền; **lọc TID trước khi giữ lịch sử**.
  Các poll không có event mới không xóa lịch sử cũ. Giữ danh sách TID/CPU đã
  quan sát; SDK log bị cuộn khỏi response không làm quên thread. Nếu mới biết
  thêm TID thì đọc lại một đoạn giao có giới hạn và loại trùng event.
- CPU rows lấy từ dữ liệu đã quan sát của capture, không chỉ các running
  slices trong cửa sổ. Khi app không chạy trong một khoảng, giữ hàng CPU và
  giải thích rõ khoảng đó; không bịa running/idle của toàn CPU.
- Report cũ lớn được backfill ở nền; UI báo đang nạp lịch sử. Giới hạn bộ nhớ:
  10.000 SDK events, 20.000 app scheduler events và tối đa 3 nguồn đang đọc.

Các tùy chọn PID/children và instance đã được đối chiếu với man page cài đặt
và tài liệu chính thức:
https://www.trace-cmd.org/Documentation/trace-cmd/trace-cmd-record.1.html

## Kết quả kiểm chứng

- `make`: pass.
- `make test`: bộ C, **22 test Python** và **6 test JavaScript** pass.
- Browser regression (fixture): chọn job, CPU/thread, chi tiết, zoom/pan,
  tìm kiếm, export, đổi nguồn, mobile và API guards: pass.
- **Kernel thật + browser thật**: chạy `mixed_demo 4` qua capture riêng.
  CPU rows xuất hiện trong 10 lần quan sát khi app đang chạy, giữ lại sau khi
  app kết thúc và tự chuyển sang replay. Replay khớp 40 job app đã gửi; cả 40
  job có scheduler đầy đủ. Không có JavaScript exception.
- Capture kernel thật 2 giây: 20 job, 20/20 đủ scheduler; report khoảng 48 KB.
  Đây là lần chạy khác các report 491/559 MB, không phải benchmark so sánh
  cùng thời lượng/tải; chỉ chứng minh lọc PID hoạt động và giữ được cả worker.
- Đọc lại report 491.174.753 byte của người dùng bằng bộ live mới: có 2.314
  SDK events, 1.306 scheduler events của app, TID 66905/66906 và 11 CPU đã quan
  sát. Bản cũ trả scheduler rỗng với chính file này.

## Khôi phục hai capture cũ

Giữ nguyên file gốc. Bản sao report mới chỉ chứa dòng liên quan tới TID của app,
kèm SDK log gốc, được phân tích trong thư mục traces của bản sửa:

| Prefix mới | Dòng scheduler đã lọc | Job đã ghép | Scheduler đầy đủ |
| --- | ---: | ---: | ---: |
| recovered-live-mixed_demo-20261117-094118-65851 | 1.262 | 100 | 100/100 |
| recovered-live-mixed_demo-20261117-094151-66853 | 1.724 | 136 | 136/136 |

Hai file `.jobs.json` tương ứng tự xuất hiện trong dropdown của dashboard.
Không có job incomplete trong kết quả flow của hai capture này. Điều đó không
chứng minh mọi event kernel đều không bị mất; chỉ mô tả tính đầy đủ của các
khoảng đã phân tích cho các job quan sát được.

## Chạy đúng bản sửa

Dùng thư mục mới, không chạy lại script trong thư mục watcher cũ:

```bash
cd /home/ubuntu/Documents/ChatGPT/pet/watcher-live-fixed
python3 scripts/dashboard.py --port 8766
```

Mở http://127.0.0.1:8766, chọn Theo dõi capture trực tiếp. Ở terminal khác:

```bash
cd /home/ubuntu/Documents/ChatGPT/pet/watcher-live-fixed
./scripts/live-app.sh 15 ./demo/mixed_demo 10
```

Lịch sử live có giới hạn bộ nhớ; file trace vẫn là đầu vào phân tích đầy đủ.
Máy chạy phải hỗ trợ private instances và PID/children filtering của trace-cmd.
Bản sửa được kiểm chứng trên kernel máy hiện tại, không khẳng định mọi kernel
hoặc mọi BSP đều hỗ trợ như nhau. Chưa push bản sửa lên GitHub.
