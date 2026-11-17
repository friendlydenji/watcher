# Watcher

Watcher là SDK C/C++ và dashboard để theo dõi công việc đi qua các thread.
Bạn đánh dấu lúc gửi, nhận và hoàn tất một công việc (`job`); Watcher ghép
các dấu mốc đó với scheduler trace để hiển thị thời gian trong hàng đợi,
thực sự chạy trên CPU, chờ CPU và ngủ/bị chặn.

**Bắt đầu bằng ba marker SEND → RECEIVE → DONE.** Bạn có thể giữ nguyên
mutex và condition hiện có. Chỉ dùng wrapper khi cần đo thêm thời gian chờ
một khóa cụ thể.

## 1. Build và liên kết SDK

### Linux

Cần compiler C11/C++17 và pthread. Chạy từ thư mục gốc repository:

```sh
make -C sdk
cc -std=c11 -O2 -Isdk/include my_app.c sdk/liblti.a -pthread -o my_app
# Với C++:
c++ -std=c++17 -O2 -Isdk/include my_app.cpp sdk/liblti.a -pthread -o my_app
```

Để tích hợp vào hệ thống build khác, thêm `sdk/include` vào đường dẫn header,
liên kết `sdk/liblti.a` sau object của ứng dụng, và bật pthread. Header C là
`lti/lti.h`; header C++ là `lti/lti.hpp`.

### QNX 7.1 / 8.0

Cần SDP tương ứng và license compiler. Chọn variant phù hợp với máy đích;
cùng mã nguồn SDK được build thành binary cho từng ABI:

```sh
./scripts/build-qnx.sh /path/to/qnx710 gcc_ntoaarch64le build/qnx71
./scripts/build-qnx.sh /path/to/qnx800 gcc_ntoaarch64le build/qnx80
```

Script tạo `liblti.a`, các ứng dụng mẫu và `watcher-qnx-capture`. Sau khi nạp
môi trường SDP, liên kết ứng dụng C, ví dụ cho QNX 7.1 AArch64:

```sh
qcc -Vgcc_ntoaarch64le -std=c11 -O2 -D_QNX_SOURCE \
  -Isdk/include my_app.c build/qnx71/liblti.a -o my_app
```

C++ dùng `q++`, `-std=c++17` và cùng thư viện. Các variant đã build được liệt
kê trong [hướng dẫn QNX](docs/qnx.md). Runtime đã kiểm tra trên QNX 7.1;
QNX 8.0 hiện đã kiểm tra build, chưa kiểm tra chạy trên máy đích.

## 2. Tích hợp tối thiểu

Ví dụ C hoàn chỉnh dưới đây gửi một job cho một thread xử lý:

```c
#include "lti/lti.h"
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>

static void *worker(void *argument)
{
    uint64_t job_id = *(const uint64_t *)argument;
    lti_event(LTI_RECEIVE, job_id, 0);
    /* Xử lý công việc tại đây. */
    lti_event(LTI_DONE, job_id, 0);
    return NULL;
}

int main(void)
{
    uint64_t job_id = 1;
    pthread_t thread;
    if (lti_init() != 0) {
        perror("lti_init");
        return 1;
    }
    lti_event(LTI_SEND, job_id, 0);
    int status = pthread_create(&thread, NULL, worker, &job_id);
    if (status == 0)
        status = pthread_join(thread, NULL);
    lti_shutdown();
    return status != 0 || lti_write_errors() != 0;
}
```

Lưu thành `my_app.c`, build theo bước 1 rồi thử ghi marker ra file:

```sh
LTI_EVENT_FILE=/tmp/my-app.events.log ./my_app
```

Đây là file marker của SDK. Để biết thread chạy trên CPU nào và chờ CPU bao
lâu, cần thu thêm scheduler theo bước 4 hoặc 5.

Trong ứng dụng có hàng đợi, đặt marker như sau:

| Marker | Đặt ở đâu? |
| --- | --- |
| `LTI_SEND` | Sau khi đưa job vào queue, trước khi consumer có thể lấy nó; thường là trước khi nhả mutex hoặc publish vào queue. |
| `LTI_RECEIVE` | Khi worker đã lấy được job và bắt đầu xử lý. |
| `LTI_DONE` | Khi worker hoàn tất công việc cần đo. |

Mang cùng `job_id` trong phần tử queue từ producer đến worker. Mỗi job dùng
một ID khác `0`, duy nhất trong process và lần capture. Không tái sử dụng ID
cho job khác trong cùng lần đo. `LTI_NO_JOB` (`0`) dành cho thao tác chưa gắn
với job nào. Việc ghép job hiện giới hạn trong một process.

Gọi `lti_init()` một lần trước khi tạo các thread được đo. Gọi
`lti_shutdown()` sau khi các thread đó đã kết thúc. Nếu muốn ứng dụng vẫn
chạy khi không mở được backend, bạn có thể xử lý lỗi init theo chính sách
của ứng dụng; các lần ghi marker sau đó không tạo dữ liệu.

Xem [ví dụ queue C hoàn chỉnh](examples/job_only/main.c), giữ nguyên toàn bộ
API mutex/condition của pthread.

### C++

`lti::Session` quản lý init/shutdown; `lti::Flow` giữ `job_id` và cung cấp các
hàm đánh dấu tương ứng. Đảm bảo thread kết thúc trước khi `Session` bị hủy:

```cpp
#include "lti/lti.hpp"
#include <thread>

int main()
{
    lti::Session session;
    if (!session.available()) return 1;
    lti::Flow job(1);
    job.send();
    std::thread worker([job] {
        job.receive();
        // Xử lý công việc.
        job.done();
    });
    worker.join();
    return lti_write_errors() != 0;
}
```

## 3. Đo thêm khi cần

### Mutex và condition

Wrapper nhận trực tiếp `pthread_mutex_t` / `pthread_cond_t` đang có, thực
hiện thao tác pthread và ghi marker quanh thao tác đó. Không cần thay kiểu
mutex hay chuyển toàn bộ chương trình sang một API khác.

Thay từng lời gọi cần quan sát bằng lời gọi tương ứng:

| pthread hiện có | Wrapper SDK |
| --- | --- |
| `pthread_mutex_lock(&queue_mutex)` | `lti_mutex_lock(&queue_mutex, 1, job_id)` |
| `pthread_mutex_unlock(&queue_mutex)` | `lti_mutex_unlock(&queue_mutex, 1, job_id)` |
| `pthread_cond_wait(&queue_ready, &queue_mutex)` | `lti_cond_wait(&queue_ready, &queue_mutex, 2, 1, job_id)` |

Giữ nguyên thứ tự lock/unlock và vòng lặp kiểm tra điều kiện. Chỉ gọi
`lti_cond_wait` khi đang giữ mutex, giống như `pthread_cond_wait`.

Mỗi tài nguyên dùng một `resource_id` khác `0`, ổn định trong process;
ví dụ mutex là `1`, condition là `2`. Wrapper trả mã lỗi của hàm pthread,
ứng dụng vẫn cần kiểm tra chúng. Thời gian condition wait bao gồm cả việc
lấy lại mutex sau khi được đánh thức. C++ dùng pthread có thể gọi các
wrapper này; SDK chưa có wrapper cho `std::mutex`.

### Các vùng xử lý và ngủ do ứng dụng đánh dấu

```c
lti_event(LTI_COMPUTE_BEGIN, job_id, 0);
/* Vùng xử lý cần quan sát. */
lti_event(LTI_COMPUTE_END, job_id, 0);

lti_event(LTI_SLEEP_BEGIN, job_id, 0);
/* Thao tác ngủ/chờ do ứng dụng chủ động đánh dấu. */
lti_event(LTI_SLEEP_END, job_id, 0);
```

Các marker này mô tả ý định của ứng dụng; số đo thực sự chạy/chờ CPU đến từ
scheduler. Nếu không gắn wrapper mutex/condition, dashboard hiển thị phần
đó là **Chưa đo**. Thời gian chờ mutex có thể nằm trong thời gian ngủ/chờ
scheduler, nên không cộng hai số đó thành tổng latency.

### Chọn nơi ghi và kiểm tra lỗi

| Cấu hình | Nơi SDK ghi marker |
| --- | --- |
| Có `LTI_EVENT_FILE=/path/to/file` | File append; ứng dụng cần quyền ghi. Trên QNX có thêm sidecar `.clock.json`. |
| Linux, không đặt biến trên | `trace_marker`; cần quyền truy cập tracefs. |
| QNX, không đặt biến trên | User event bằng `TraceEvent`; cần kernel hỗ trợ tracing và collector bên ngoài. |

Các script capture bên dưới cấu hình backend cho ứng dụng. Không cần chạy
ứng dụng Linux bằng root chỉ để ghi marker vào file; collector scheduler
có thể yêu cầu quyền cao hơn.

`lti_write_errors()` trả số lỗi ghi/clock/backend được SDK phát hiện;
`lti_thread_id()` trả TID gốc (trên QNX cần dùng cùng PID để nhận diện thread).
Không có lỗi SDK không bảo đảm collector giữ được tất cả event. Việc ghi
marker có overhead; xem [số đo và cách benchmark](docs/performance.md).

## 4. Chạy và xem live trên Linux

Máy thu cần Python 3.10+, `trace-cmd`, tracefs hỗ trợ private instances và
quyền thu scheduler (`sudo` nếu cần). Dashboard chỉ dùng thư viện chuẩn
Python, không cần npm. Để build các ứng dụng mẫu:

```sh
make
```

Mở dashboard ở một terminal:

```sh
python3 scripts/dashboard.py
```

Mở [http://127.0.0.1:8765](http://127.0.0.1:8765), chọn **Theo dõi capture
trực tiếp**. Ở terminal khác, chạy ứng dụng đã gắn SDK:

```sh
./scripts/live-app.sh 15 ./my_app
# Hoặc thử demo có sẵn:
./scripts/live-app.sh 15 ./demo/mixed_demo 10
```

Tham số đầu là thời gian thu, từ 1 đến 120 giây; chọn dài hơn thời gian app
chạy. Script tự đặt `LTI_EVENT_FILE`, chạy ứng dụng, thu scheduler và phân
tích kết quả vào `traces/`. Live hiển thị scheduler/marker trong lúc chạy;
thống kê job hoàn chỉnh có sau bước phân tích.

Timeline live mặc định vẽ từ trái sang phải trong cửa sổ 5 giây cố định.
Event mới xuất hiện dần bên phải; khi hết cửa sổ, biểu đồ chuyển sang trang
thời gian tiếp theo. Kéo **Cũ → Mới** để xem lịch sử, bấm **Theo dõi live →**
để quay lại cập nhật. **Tạm dừng** chỉ dừng cập nhật giao diện.

Nếu chỉ cần thu rồi xem lại, kèm file `.dat`:

```sh
./scripts/capture-app.sh ./my_app
python3 scripts/dashboard.py
```

## 5. Thu trên QNX và xem trên máy phát triển

Chép ứng dụng, `watcher-qnx-capture` và các thư viện runtime ứng dụng cần
sang máy đích. Máy đích cần instrumented kernel, `tracelogger`, `pidin` và
quyền tracing. Dùng prefix mới cho mỗi lần thu; chọn thời gian dài hơn app:

```sh
# Chạy trên QNX, tại thư mục chứa binary:
WATCHER_QNX_BACKEND=kernel ./watcher-qnx-capture 15 /tmp/my-capture ./my_app
traceprinter -n -p 'cycles:0x%016c cpu:%C %Z:%z' \
  -f /tmp/my-capture.kev -o /tmp/my-capture.txt
```

Chép `my-capture.txt` và `my-capture.collector.log` về máy phát triển, rồi
chạy từ thư mục repository:

```sh
python3 scripts/import_qnx.py /path/to/my-capture.txt \
  --collector-log /path/to/my-capture.collector.log \
  --output-prefix traces/my-qnx-capture
python3 scripts/dashboard.py
```

Chọn `my-qnx-capture.jobs.json` trên dashboard. Có thể dùng `traceprinter`
của SDP trên host để chuyển `.kev` sang `.txt`. QNX tracing dùng chung toàn
hệ thống: không chạy collector khác đồng thời với helper.

Pipeline QNX hiện hỗ trợ **capture → import → replay**. Chưa có truyền live
tự động từ QNX sang dashboard. Cách dùng event-file backend và cấu hình chi
tiết nằm trong [hướng dẫn QNX](docs/qnx.md).

## 6. Đọc kết quả

- Chọn một job để xem thời gian gửi → nhận → xong và các thành phần latency.
- Chuyển **Thread / CPU** để xem trạng thái thread hoặc thread chạy trên CPU nào.
- **Vừa trace** hiển thị toàn bộ lịch sử; `W/S` zoom, `A/D` di chuyển, `Shift` + kéo để dịch cửa sổ. Kéo trên biểu đồ để tổng hợp một khoảng thời gian.
- Nút **Xuất Perfetto JSON** tải Chrome trace JSON để mở bằng Perfetto.

`traces/*.jobs.json` là dữ liệu dùng cho dashboard; các CSV cùng prefix phục
vụ phân tích bên ngoài. Job phải có đủ SEND/RECEIVE/DONE mới được đưa vào
thống kê latency. Khoảng thiếu scheduler hoặc có báo mất dữ liệu được đánh
dấu chưa xác định; không coi đó là thời gian ngủ hay chờ mutex đã đo được.

Để thử giao diện bằng dữ liệu minh họa:

```sh
mkdir -p traces
cp examples/traces/synthetic.jobs.json traces/example.jobs.json
python3 scripts/dashboard.py
```

## Tham khảo

- [API C](sdk/include/lti/lti.h) và [API C++](sdk/include/lti/lti.hpp).
- [Schema event và giới hạn phép đo](docs/event-schema.md).
- [Build và capture QNX](docs/qnx.md).
- [Hiệu năng SDK](docs/performance.md).
- Kiểm tra mã nguồn: `make test`. Kiểm tra trình duyệt: `npm install`, `npx playwright install chromium`, rồi `npm run test:browser` (Node.js 20+).

## Giấy phép

[PolyForm Noncommercial 1.0.0](LICENSE): cho phép sử dụng, sửa đổi, tiếp tục
phát triển và phân phối cho mục đích phi thương mại theo điều khoản giấy
phép. Quyền sử dụng thương mại không được cấp trong giấy phép này.
