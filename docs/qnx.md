# Watcher trên QNX 7.1 và 8.0

## Phạm vi và kết quả thực tế

Cùng mã nguồn SDK C11 dùng cho Linux, QNX 7.1 và QNX 8.0. Không có asm hoặc
nhánh theo CPU trong thư viện; qcc chọn ABI/kiến trúc khi build.
Đã build SDK, C/C++ demos, job-only example, benchmark và capture helper:

| SDK | Variant | Kết quả |
| --- | --- | --- |
| QNX 7.1 | gcc_ntoaarch64le | Build; chạy trên QNX 7.1 R-Car V4M |
| QNX 7.1 | gcc_ntox86_64 | Build |
| QNX 7.1 | gcc_ntoarmv7le | Build |
| QNX 8.0 | gcc_ntoaarch64le | Build |
| QNX 8.0 | gcc_ntox86_64 | Build |

Mỗi target cần binary đúng ABI. Không dùng một binary chung cho mọi CPU hay
khẳng định binary QNX 8.0 chạy trên hệ điều hành QNX 7.1. Chưa có kiểm chứng
runtime QNX 8.0 trong đợt này. Các phép đo ở performance.md là trên máy QNX
7.1 được người dùng cung cấp, không phải giá trị chung cho mọi CPU/BSP.

## Build

```bash
./scripts/build-qnx.sh /path/to/qnx710 gcc_ntoaarch64le build/qnx71-target
./scripts/build-qnx.sh /path/to/qnx800 gcc_ntoaarch64le build/qnx80-target
```

Chọn variant bằng `qcc -V`. Thư mục output chứa `liblti.a`, header vẫn ở
`sdk/include`, và các chương trình kiểm tra. Build dùng `-O2`, C11/C++17,
`-Wall -Wextra -Wpedantic -Werror`; cần license compiler hợp lệ.
Ví dụ liên kết app C sau khi nạp môi trường SDP:

```bash
qcc -Vgcc_ntoaarch64le -O2 -std=c11 -D_QNX_SOURCE \
  -Isdk/include my_app.c build/qnx71-target/liblti.a -o my_app
```

API job và mutex giữ nguyên. Có thể chỉ thêm `lti_init()`, SEND/RECEIVE/DONE
và `lti_shutdown()`; ví dụ `examples/job_only/main.c` giữ nguyên pthread APIs,
không dùng bất kỳ wrapper mutex/condition nào của LTI.

## Hai backend

- Có `LTI_EVENT_FILE`: ghi event file đồng bộ và file `.clock.json` cạnh nó.
- Không có `LTI_EVENT_FILE`: chèn user events bằng TraceEvent. Không ghi file
  trong hot path. Cần instrumented kernel và collector được cấu hình bên ngoài.

Thread IDs lấy từ API QNX, không dùng Linux SYS_gettid. Clock dùng ClockCycles
và tần số trong system page; bộ nhập quy đổi scheduler và SDK cùng clock.
Độ phân giải thực của counter là `ceil(1e9 / cycles_per_sec)` ns, không phải
1 ns chỉ vì trường timestamp dùng đơn vị ns. Bracket mapping bằng 0 là vì
cùng một counter, không phải mọi sai số đo đều bằng 0.
TID 1 của process A khác TID 1 của process B; UI giữ PID/TID thật và dùng
track_id riêng để vẽ. Chưa giải quyết vòng đời PID reuse hay cross-process
handoff như giới hạn schema v1; helper dưới đây lọc một process cùng các thread.

## Chạy và thu trace trên QNX

Chép các binary phù hợp vào máy đích bằng phương thức đang có, chẳng hạn
TFTP. Với máy 192.168.0.125, bản đã kiểm tra nằm sẵn trong:
`/tmp/watcher_portable_20261117_final`.

Dùng tên prefix mới cho mỗi lần chạy. Chế độ native:

```sh
cd /tmp/watcher_portable_20261117_final
WATCHER_QNX_BACKEND=kernel ./watcher-qnx-capture 15 /tmp/my-capture ./mixed_demo 10
traceprinter -n -p 'cycles:0x%016c cpu:%C %Z:%z' \
  -f /tmp/my-capture.kev -o /tmp/my-capture.txt
```

Chế độ event file:

```sh
./watcher-qnx-capture 15 /tmp/my-file-capture ./job_only 20
traceprinter -n -p 'cycles:0x%016c cpu:%C %Z:%z' \
  -f /tmp/my-file-capture.kev -o /tmp/my-file-capture.txt
```

Tham số đầu là giới hạn thời gian của tracelogger; chọn dài hơn thời gian app
chạy. Helper đợi app kết thúc. Nếu app chạy lâu hơn cửa sổ này, scheduler sau
đó không được thu và kết quả có thể partial. Helper không phải attach-by-PID.

QNX tracing là global, không có private instance kiểu Linux trong helper này.
Helper dùng lock riêng, từ chối tracelogger đang chạy, giữ app tại gate, cấu
hình Thread/User classes theo PID, rồi mới cho app chạy. Cần chạy trong môi
trường tracing dành riêng; không khởi động collector khác đồng thời. Helper
chỉ dừng tiến trình tracelogger do nó tạo. SDK bản thân không thay đổi tracing.

Collector dùng 256 kernel buffers và 256 dynamic buffers để giữ được burst
đã kiểm tra. `.collector.log` lưu diagnostics. Mã trả về 3 nghĩa là collector
báo mất buffer; cảnh báo backlog chưa đồng nghĩa đã mất event. Kích thước này
không bảo đảm mọi tải đều không mất dữ liệu; cần kiểm tra trên app thực tế.

## Xem dashboard trên máy phát triển

Lấy `.kev`, `.txt` và `.collector.log` về máy phát triển. Với file backend,
lấy thêm `.events.log` và `.events.log.clock.json`.
Có thể dùng traceprinter của SDK trên host để tạo `.txt` từ `.kev` thay vì
chạy traceprinter trên target. Giữ định dạng full 64-bit cycles đúng lệnh trên.

Native backend:

```bash
python3 scripts/import_qnx.py /path/to/my-capture.txt \
  --collector-log /path/to/my-capture.collector.log \
  --output-prefix traces/my-qnx-capture
```

Event-file backend:

```bash
python3 scripts/import_qnx.py /path/to/my-file-capture.txt \
  --events /path/to/my-file-capture.events.log \
  --collector-log /path/to/my-file-capture.collector.log \
  --output-prefix traces/my-qnx-file-capture
```

```bash
python3 scripts/dashboard.py --port 8767
```

Chọn trace vừa nhập. CPU/thread timelines, job breakdown và Perfetto export
đều dùng chung dashboard. Pipeline QNX hiện là capture/import/replay; script
live-app.sh và live endpoint incremental của Linux không chạy trực tiếp trên
QNX. Chưa triển khai cầu truyền live QNX → host tự động trong bản này.

## Các nguồn đã đối chiếu

- TraceEvent 7.1: https://www.qnx.com/developers/docs/7.1/com.qnx.doc.neutrino.lib_ref/topic/t/traceevent.html
- TraceEvent 8.0: https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.lib_ref/topic/t/traceevent.html
- Traceprinter 7.1: https://qnx.com/developers/docs/7.1/com.qnx.doc.neutrino.utilities/topic/t/traceprinter.html
- Thread states 8.0: https://qnx.com/developers/docs/8.0/com.qnx.doc.sat/topic/events_Thread_class.html
- SDK headers thực tế: sys/trace.h, pthread.h, sys/neutrino.h và sys/syspage.h
  trong các bản SDP đã cài. Không dùng Linux scheduler formats làm QNX input.
