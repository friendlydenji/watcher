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

## 5. Mở trình duyệt xem live trực tiếp từ QNX

`watcher-service` chạy trên target QNX 7.1/8.0 và phục vụ cả giao diện lẫn
API dữ liệu. Host chỉ cần trình duyệt; không cần Python trên target, không
cần chạy dashboard trên host và không cần copy trace để xem live.

### Chuẩn bị target

Build theo bước 1. Chép các mục sau trong thư mục output sang cùng một thư
mục trên target, ví dụ `/tmp/watcher`:

```text
watcher-service
watcher-qnx-capture
ui/                     # giữ nguyên toàn bộ thư mục
my_app                  # ứng dụng của bạn, đã gắn SDK
```

Target cần kernel có instrumentation, quyền tracing, `pidin`, `tracelogger`
và các thư viện runtime đúng phiên bản/ABI. Nếu image chưa có `tracelogger`,
thêm công cụ từ SDP tương ứng vào image hoặc thư mục riêng trong `PATH`.
Không chạy collector khác, kể cả kernel tracing của IDE, cùng lúc với service.
Nếu image không hỗ trợ `mkdir` dưới `/dev/shmem`, dùng thư mục có sẵn hoặc
đặt các file UI cạnh binary và truyền `--ui .`.

### Chạy

Trong terminal trên target:

```sh
cd /tmp/watcher
export PATH="$PWD:$PATH"
./watcher-service --listen 0.0.0.0 --port 8765 \
  --ui ./ui --helper ./watcher-qnx-capture --capture-dir /dev/shmem \
  --wait-client -- ./my_app
```

Trên host mở **`http://<IP-target>:8765`**. Với máy đang dùng trong phiên
kiểm tra này, địa chỉ target là `192.168.0.114`.

- `--wait-client`: đợi trình duyệt yêu cầu dữ liệu live rồi mới chạy app,
  giúp quan sát cả ứng dụng có thời gian chạy ngắn. Bỏ tùy chọn này để chạy ngay.
- Sau `--` là chương trình và các tham số của nó. Service khởi chạy một app
  mới cùng các thread của app; chưa hỗ trợ attach vào process đang chạy.
- Mặc định thu liên tục trong thời gian app chạy. Khi app kết thúc, service
  giữ dữ liệu trong RAM để bạn tiếp tục xem. `Ctrl+C` dừng service và phiên
  thu do nó tạo; nếu app đó còn chạy, helper gửi SIGTERM cho app.
- Có thể dùng `--seconds 60` để giới hạn cửa sổ thu; chọn dài hơn thời gian
  app chạy. `--seconds 0` là không giới hạn theo thời gian.

Ví dụ với ứng dụng mẫu trong gói build:

```sh
./watcher-service --ui ./ui --capture-dir /dev/shmem \
  --wait-client -- ./mixed_demo 10
```

Service dùng SDK native `TraceEvent`, thu scheduler thật và cập nhật job trên
trình duyệt khi có đủ SEND/RECEIVE/DONE. Mutex/condition chỉ có số đo khi app
đánh dấu chúng. SDK không gửi HTTP; phần đọc trace và phục vụ web chạy trong
process service riêng.

### Dữ liệu và giới hạn

Service giữ tối đa 20.000 SDK events, 20.000 chuyển trạng thái và 1.024
PID/TID trong RAM; giao diện báo khi lịch sử bị giới hạn. File `.kev`,
`.app.log` và `.collector.log` được lưu dưới `--capture-dir`. Chọn nơi có đủ
chỗ trống; `/dev/shmem` sử dụng RAM. File thu liên tục tiếp tục tăng trong
thời gian app chạy, dù lịch sử phục vụ trên web đã có giới hạn.

Bộ đọc chỉ xử lý phần mới của `.kev`, không gọi `traceprinter` để phân tích
lại toàn bộ file theo mỗi lần cập nhật. Helper yêu cầu flush buffer mỗi
200 ms; trình duyệt yêu cầu dữ liệu mỗi 500 ms. Đây là nhịp cập nhật, không
phải bảo đảm độ trễ thời gian thực. Trình duyệt ghép timeline/job và vẽ biểu đồ.

Nút **Xuất Perfetto JSON** tải dữ liệu đang giữ xuống host. Các file raw trên
target có thể dùng để lưu trữ/phân tích sâu sau đó. Service phục vụ HTTP trong
mạng phát triển tin cậy; chưa có đăng nhập hay TLS.

Để đọc lại một file native có marker SDK ngay trên target:

```sh
./watcher-service --ui ./ui --capture-dir /dev/shmem \
  --replay-kev /path/to/capture.kev
```

Cách thu offline và nhập dữ liệu vào dashboard Python vẫn có trong
[hướng dẫn QNX](docs/qnx.md).

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
- [Kiến trúc, giới hạn và kiểm chứng target service](docs/target-service.md).
- [Hiệu năng SDK](docs/performance.md).
- Kiểm tra mã nguồn: `make test`. Kiểm tra trình duyệt: `npm install`, `npx playwright install chromium`, rồi `npm run test:browser` (Node.js 20+).

## Giấy phép

[PolyForm Noncommercial 1.0.0](LICENSE): cho phép sử dụng, sửa đổi, tiếp tục
phát triển và phân phối cho mục đích phi thương mại theo điều khoản giấy
phép. Quyền sử dụng thương mại không được cấp trong giấy phép này.
