# Hiệu năng SDK — phép đo ngày 2026-11-17

## Phương pháp

Mỗi ô là trung vị 5 lượt, `-O2`, cùng harness `tests/benchmark_events.c`.
Các lượt cũ/mới xen kẽ. Mỗi lượt 1.000 event warmup ở main trước khi đo;
các worker đo được tạo mới, nên thời gian của chúng vẫn gồm first-touch TLS.
Đo phase thay đổi và resource 64-bit lớn; không chỉ benchmark một chuỗi hằng.
Linux dùng CLOCK_MONOTONIC; QNX dùng ClockCycles cho stopwatch độ phân giải cao.
Baseline QNX chỉ thay tối thiểu cách lấy TID/feature macro để code cũ build được;
không coi thư viện Linux gốc là đã từng chạy nguyên bản trên QNX.
Bản baseline đó được giữ trong reports/baseline-lti-qnx.c.

Một thread: wall time / event. Bốn thread: wall time / tổng số event là
**nghịch đảo throughput tổng**, không phải latency riêng một lời gọi.
Mean-thread time riêng từng worker được lưu trong JSON. Không suy ra CPU%
hay WCET từ những số wall-time này. File thường được ghi vào thư mục tạm;
không fsync mỗi event và không phải phép đo độ bền/tốc độ flash.

## Linux x86_64 trên máy phát triển

| Backend | Thread | Bản cũ (µs/event) | Bản mới (µs/event) | Giảm trung vị |
| --- | ---: | ---: | ---: | ---: |
| devnull | 1 | 1.178 | 0.681 | 42.2% |
| devnull | 4 | 0.306 | 0.180 | 41.3% |
| regular-file | 1 | 1.842 | 1.245 | 32.4% |
| regular-file | 4 | 0.929 | 0.912 | 1.9% |

Số no-op ở thang vài ns; khác biệt nhỏ/dao động không được dùng để quảng cáo
cải thiện có ý nghĩa. Đường file 4 thread chỉ cải thiện rất ít trong phép đo;
chưa có profile đủ chi tiết để quy nguyên nhân cho một thành phần cụ thể; không áp số cải thiện devnull cho mọi workload.
Kết quả thô: [linux-performance-final.json](../reports/linux-performance-final.json).

## QNX 7.1 trên R-Car V4M thực tế

Máy đích báo Cortex-A76 1 GHz, 4 CPU. Không pin affinity, không thay chính sách
scheduling, không thay xung nhịp. Đây là phép đo trên hệ thống đang chạy bình thường.
Tần số ClockCycles lấy từ system page, không dùng tần số CPU đoán thay thế.

| Backend | Thread | Bản cũ (µs/event) | Bản mới (µs/event) | Giảm trung vị |
| --- | ---: | ---: | ---: | ---: |
| devnull | 1 | 6.496 | 2.516 | 61.3% |
| devnull | 4 | 6.662 | 6.595 | 1.0% |
| regular-file | 1 | 14.287 | 10.013 | 29.9% |
| kernel (collector active) | 1 | — | 3.077 | backend mới |
| kernel (collector active) | 4 | — | 3.197 | backend mới |

Kernel/native 4 thread đạt khoảng **313.000 event/s tổng** trong burst ngắn đã đo.
Thời gian trung bình mỗi thread/event khoảng **12,5 µs**; không được gọi số
3,197 µs/event tổng throughput là latency từng thread.
Collector có cảnh báo backlog; sau khi tăng buffer và kiểm tra file kết quả,
lượt cuối của cả native 1 thread và 4 thread giữ **đủ 11.000 SDK markers**
(1.000 warmup + 10.000 measured), cùng marker clock. Không có cảnh báo dropping
buffers ở các lượt cuối. Điều này không phải chứng nhận throughput lossless
dài hạn hoặc cam kết deadline realtime.

Cải thiện được giữ: khoảng **61%** ở file-backend/devnull một thread và
**30%** ở file thường một thread. Shared-file 4 thread chỉ gần ngang baseline.
Một biến thể thử chỉ định dạng nhanh, ghi đồng thời cùng fd đã gây hồi quy
4 thread; không bàn giao biến thể đó. Bản cuối tuần tự hóa toàn record trên
QNX file backend để tránh hồi quy này. Native TraceEvent không dùng mutex file.

Kết quả thô: [qnx71-performance.json](../reports/qnx71-performance.json),
[paired runs](../reports/qnx71-performance-final.txt),
[native runs](../reports/qnx71-native-final.txt).

## Thay đổi trong hot path

- Thay snprintf mỗi event bằng serializer số nguyên/chuỗi có giới hạn.
- Cache TID/PID prefix theo thread; reset đúng ở child sau fork.
- Mã lti_event không gọi malloc/free tường minh. Tuy nhiên object QNX 7.1
  dùng `__emutls_get_address`; không được suy ra first-touch TLS không cấp
  phát ở runtime. Metadata/clock được chuẩn bị ở init; đây không phải thư
  viện zero-allocation/WCET đã được chứng nhận.
- QNX dùng ClockCycles; tránh timestamp CLOCK_MONOTONIC bị lượng tử theo tick
  trên máy đã kiểm tra. Cả SDK và scheduler import dùng cùng epoch/frequency.
- QNX native backend ghi TraceEvent thay vì message write tới file manager.
- File records vẫn ghi đồng bộ; không thêm hàng đợi async có thể lặng lẽ rơi event.
- Retry write nếu EINTR; đếm short/failed writes và TraceEvent errors.

## Giới hạn và cách tự đo

Các số trên phụ thuộc OS, CPU, filesystem, collector, scheduler và tải máy.
Không áp kết quả QNX 7.1 này cho QNX 8.0 hoặc CPU khác. Build thành công không
phải bằng chứng hiệu năng hoặc tính đúng realtime trên mọi target.

```sh
./benchmark_events 100000 1 /dev/null
./benchmark_events 20000 4 /dev/null
```

Native QNX cần chạy qua collector; ví dụ:

```sh
./watcher-qnx-capture 10 /tmp/new-bench ./benchmark_events 10000 1 kernel
```

Luôn kiểm tra `.collector.log`, mã trả về và event counts; API insertion thành
công không chứng minh collector đã lưu mọi event. Dùng prefix mới mỗi lần chạy.


## Footprint tĩnh và trade-off bộ nhớ

GCC Linux `-O2`, số từ size/readelf (object, không phải RSS của cả chương trình):

| Object Linux | text | data | bss gồm TLS | Tổng |
| --- | ---: | ---: | ---: | ---: |
| Bản cũ | 1.826 B | 100 B | 20 B | 1.946 B |
| Bản mới | 2.722 B | 196 B | 84 B | 3.002 B |

Prefix cache mới chiếm 68 byte TLS payload mỗi thread, chưa gồm overhead runtime.
Object QNX 7.1 AArch64 khoảng 4.942 B theo size; QNX 8.0 AArch64 khoảng 4.522 B.
Đây là SDK code/data, không gồm libc/libgcc, kernel buffers và logger process.
QNX 7.1 object có tham chiếu emulated TLS; QNX 8.0 object dùng TLS section.

`-fstack-usage` Linux báo frame riêng lti_event cũ 352 B, mới 416 B.
Không cộng/trừ stack libc snprintf từ các số này vì chưa đo stack toàn call
chain. Bản mới đổi thêm khoảng 1 KB object và 64 B frame riêng để giảm chi phí
định dạng; không khẳng định footprint nhỏ hơn. Buffer collector QNX dùng bộ
nhớ riêng của kernel/tracelogger, không được gộp vào kích thước liblti.a.
