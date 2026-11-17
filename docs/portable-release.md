# Bàn giao Watcher portable — 2026-11-17

## Người dùng yêu cầu

1. Sửa trường hợp dùng marker job mà không thay mutex, pipeline vẫn hoạt động.
2. Port sang QNX 7.1 và QNX 8.0; source không phụ thuộc CPU cụ thể.
3. Đo hiệu năng lib hiện tại và tối ưu nếu có thể.

Người dùng cung cấp máy QNX qua Telnet để kiểm chứng. Không lưu mật khẩu vào
source hoặc gói bàn giao. Thư mục bản trước giữ nguyên; bản mới ở
`watcher-portable`. Không push GitHub và không sửa thư mục SDK đã cài.

## Đã làm và lý do

- analyze_sync xuất CSV có header nhưng không có row khi không quan sát sync.
- correlate chấp nhận sync CSV rỗng/không có; mutex/condition chưa đo là null.
- UI hiện Chưa đo, không hiểu thiếu instrumentation thành không có contention.
- examples/job_only dùng pthread mutex/cond nguyên bản, chỉ gắn marker job.
- SDK dùng backend Linux hoặc QNX; TID, clock và native insertion theo API OS.
- QNX dùng ClockCycles để tránh lượng tử timestamp theo tick của CLOCK_MONOTONIC
  trên target đã kiểm tra. Converter dùng đầy đủ cycle count 64-bit.
- QNX correlation phân biệt (PID,TID); track_id chỉ dùng để vẽ, giữ TID thật.
- Thêm capture helper từ chối collector đang chạy, gate app trước khi bật trace,
  lọc PID, thu kernel/user events và lưu diagnostics. QNX tracing vẫn là global.
- Native importer trích cả LTI_CLOCK/LTI_EVENT, sinh jobs JSON dùng chung UI.
- Tối ưu serializer và prefix cache; QNX file backend tuần tự hóa toàn record.
- Loại phương án thử gây hồi quy nhiều thread; không thêm buffer async mặc định.
- Chẩn đoán collector: tách backlog khỏi dropping; loss thực làm capture trả mã 3
  và importer đánh dấu dữ liệu không tin cậy nếu có collector log.

## Kiểm chứng

- Linux: hai bộ C, 24 Python tests, 7 JavaScript tests, browser E2E với fixture
  và QNX trace thật; kiểm tra cú pháp shell/JS/Python.
- Linux kernel: job-only 20/20 job đầy đủ scheduler, sync CSV rỗng.
- QNX 7.1 máy đích: portable test 4.002 records, 4 worker threads và fork,
  không hỏng record, write_errors=0.
- QNX job-only file backend: 20/20 jobs, scheduler đầy đủ, không có sync markers.
- QNX job-only native TraceEvent: 20/20 jobs, scheduler đầy đủ, không có sync markers.
- QNX C++ mixed_demo: 10/10 jobs, scheduler đầy đủ; mutex/condition annotations có dữ liệu.
- Native burst validation: file cuối 1-thread và 4-thread đều đủ 11.000 SDK
  markers (warmup + measured), có clock marker; collector có backlog nhưng
  không báo dropping. Không chứng nhận mọi tải hoặc dài hạn không mất event.
- Build full artifacts: QNX 7.1 AArch64/x86_64/ARMv7 và QNX 8.0 AArch64/x86_64.
- QNX 8.0 mới kiểm chứng build, chưa kiểm chứng runtime trên hệ điều hành 8.0.

## Số đo và giới hạn

Xem performance.md và reports/*final*.json/txt: five paired repetitions,
không pin CPU, không thay xung nhịp/scheduling của target. Không suy ra WCET
hoặc CPU% từ throughput. Kết quả nhiều thread ghi cùng file không được quảng
cáo bằng số cải thiện một thread. RAM/stack footprint tăng và được ghi rõ.

Đợt này port SDK và luồng QNX capture/import/replay. Linux live vẫn được giữ.
Chưa triển khai bridge live QNX-to-host tự động. File native .kev được giữ để
mở bằng công cụ QNX; không giả lập sched_switch của Linux từ một trace QNX.
Hướng dẫn build/chạy: qnx.md. Các hạn chế schema v1 như PID reuse và job ID
vượt vùng số nguyên chính xác JavaScript vẫn cần xem xét riêng.


## Gói bàn giao

- watcher-portable.zip: source, tài liệu, số đo và bốn trace JSON cuối đã kiểm chứng.
- watcher-qnx-prebuilt.zip: liblti.a, headers và chương trình kiểm tra cho năm
  SDK/variant đã build. Không kèm SDK hoặc thư viện hệ thống QNX.
- watcher-portable.patch: thay đổi source so với watcher-live-fixed.zip đã giao.
- Dashboard cục bộ bản mới: http://127.0.0.1:8767.

Thư mục bản trước và dữ liệu gốc được giữ nguyên. Các thử nghiệm trung gian
vẫn ở thư mục làm việc, nhưng không được đưa làm trace mẫu mặc định trong gói.
