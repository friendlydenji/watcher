# Xử lý review Watcher — 2026-11-17

Báo cáo này ghi nhận đợt sửa đầu. Bản bổ sung đã kiểm chứng capture kernel
thật và sửa lỗi live: xem [live-cpu-fix.md](live-cpu-fix.md).

## Yêu cầu và quyết định của người dùng

- Đọc PDF “Review of the watcher GitHub repository - Claude”, đối chiếu với
  https://github.com/friendlydenji/watcher, sửa các phần cần thiết và UI.
- Người dùng yêu cầu giữ khả năng khôi phục bản gốc và trả lại file đã sửa.
- Khi được hỏi về giấy phép, người dùng chọn: “cho phép phát triển tiếp nhưng
  không đc thương mại hóa”. Vì vậy chọn **PolyForm Noncommercial 1.0.0**,
  không dùng MIT/Apache-2.0. Văn bản LICENSE lấy nguyên bản từ dự án PolyForm:
  https://github.com/polyformproject/polyform-licenses/blob/1.0.0/PolyForm-Noncommercial-1.0.0.md
- Review được dùng như nguồn đề xuất. Các lời mời hỏi lại trong PDF không
  được coi là chỉ thị từ người dùng.

## Mốc mã nguồn và khôi phục

- Repo gốc: `friendlydenji/watcher`.
- Commit gốc: `62de9c65097a70b76c13cd89c30e3d3418fd25a3`.
- Nhánh làm việc cục bộ: `fix/review-and-dashboard`.
- Lưu nguyên bản dưới tên `watcher-original-62de9c6.tar.gz` bên cạnh repo.
- Trả lại `watcher-reviewed.zip` chứa toàn bộ nguồn đã sửa và
  `watcher-review.patch` chứa thay đổi so với commit gốc.
- Không sửa bản PDF nguồn, không tạo lịch sử commit giả và chưa push hay
  thay đổi cài đặt repo trên GitHub.

## Những đề xuất đã thực hiện

| Vấn đề trong review | Thay đổi và lý do |
| --- | --- |
| Release ghi sau unlock | Ghi ngay trước `pthread_mutex_unlock`, khi chưa thể có holder kế tiếp. Test C kiểm tra tại đúng ranh giới gọi unlock. |
| Syscall gettid mỗi event | Cache bằng C11 `_Thread_local`; reset ở child bằng `pthread_atfork`. Nếu đăng ký hook thất bại thì dùng syscall thay vì cache không an toàn. |
| Không có test C | Test C cho ranh giới release, schema, TID riêng theo thread, fork, errno, init/shutdown và backend thất bại. |
| live reset tracing toàn cục | Tạo instance duy nhất; `start/stop/reset -B <instance>`, chỉ delete instance đó. Dừng nếu không dùng được instance. |
| comm bị cắt 15 ký tự | Phân tích chọn TID lấy từ SDK event log, kể cả worker đổi tên. Live cũng lọc scheduler bằng TID. |
| README có đường dẫn cá nhân/tên thư mục sai | Viết lại theo `git clone …; cd watcher`, thêm hướng dẫn UI/replay/live/export và giới hạn. |
| Không có LICENSE | Thêm PolyForm Noncommercial theo quyết định của người dùng. |
| Không có CI | Thêm Actions chạy build, C/Python/JavaScript và build SDK với CFLAGS do người dùng đặt. |
| CFLAGS thay thế làm mất chuẩn/warning | Tách cờ bắt buộc của SDK khỏi CFLAGS; giữ C11, warning và pthread. |
| .gitignore có file cũ | Bỏ trace_marker.o, bỏ nó khỏi demo clean; thêm ignore cho test binaries/npm. |
| UI không nêu điều cần chú ý | Banner job chậm nhất và diễn giải thành phần lớn nhất từ dữ liệu đo. |
| 6 cột số khó so sánh | Danh sách job có thanh phân rã, sort, search, >p95 khi đủ ít nhất 20 job. |
| Trục CPU khó theo dõi thread | Mặc định mỗi hàng một thread; tab CPU phụ vẫn được giữ. |
| Màu vừa là trạng thái vừa là danh tính | Thread view dùng màu trạng thái cố định; CPU view dùng màu xanh dương/tím theo TID, không lặp vòng bảng 8 màu. |
| Replay thiếu scheduler | Timeline đọc từ JSON đã phân tích; correlate nhúng cả SDK/scheduler events từ `.txt` hoặc `trace-cmd report` của `.dat`. |
| Điều hướng thô/tooltip | Nút zoom, W/S, A/D, Ctrl+wheel, Shift+drag, vùng chọn tổng hợp; click mở chi tiết ở panel ngay dưới timeline, dùng được bằng touch. |
| Mũi tên chồng nhau | Chỉ vẽ chuyển job đang chọn, wakeup mặc định tắt; giới hạn số mũi tên mỗi cửa sổ. |
| Hai bảng log chiếm chỗ | Gộp vào phần sự kiện gốc, mặc định đóng. |
| lang=vi nhưng chữ tiếng Anh | Dashboard tiếng Việt; giữ tên event/API khi giúp đối chiếu dữ liệu. |
| Export Perfetto | Script và nút tải Chrome trace JSON; scheduler, job và resource có hàng riêng để tránh slice chồng không lồng nhau. |

## Điều chỉnh đề xuất để giữ đúng ý nghĩa dữ liệu

1. **Không xếp mutex vào thanh 100% cùng scheduler.** Mutex/condition có thể
   trùng với ngủ/chờ CPU. Thanh chính chỉ gồm queue + các trạng thái worker;
   mutex/condition hiển thị riêng. Bản review cũng đề cập hiện tượng trùng
   trong phần đánh giá code, nên đề xuất cộng bốn nhóm trên UI được điều chỉnh.
2. **Ngủ/bị chặn không tự động nghĩa là mutex.** UI chỉ diễn giải quan sát và
   chỉ ra nơi đọc thêm. Nó không tự khẳng định nguyên nhân gốc.
3. Khoảng không có scheduler giữ trạng thái chưa xác định. Nếu phát hiện
   scheduler overlap, thanh tổng dùng phần processing chưa xác định, tránh
   tạo tổng lớn hơn 100% hoặc kết luận dựa trên số liệu mâu thuẫn.
4. Chi tiết hiện ở panel dưới timeline, giữ ngữ cảnh của job, thay vì drawer
   che biểu đồ. Trên màn hình hẹp các phần xếp dọc và timeline cuộn ngang.
5. `lock_release` nay là marker ngay trước một **lần thử unlock**. Nếu pthread
   trả lỗi, marker không chứng minh khóa đã nhả. Trả nguyên mã lỗi pthread;
   giới hạn này được ghi trong README/schema.

## Kiểm chứng đã thực hiện

Môi trường cục bộ: Linux, GCC 11.4.0, Python 3.10.12, Node.js 20.20.2,
Chrome headless qua Playwright 1.62.1.

- `make`: build SDK, demo C++/C và C ping-pong; không warning.
- `make test`: một bộ C, **17 test Python**, **5 test JavaScript** đều qua.
- C regression mới chạy trên SDK gốc: fail đúng assertion thiếu release ở
  đầu `pthread_mutex_unlock`; chạy trên SDK đã sửa: pass.
- Build SDK với `CFLAGS='-O0 -g -Werror'`: pass, vẫn có C11/warnings/pthread.
- Kiểm tra cú pháp từng script shell, JavaScript và `git diff --check`: pass.
- Chạy C ping-pong thật với 5 job và event-file backend: 133 event đúng schema,
  5 luồng send/receive/done hoàn tất, không có job incomplete trong lần chạy đó.
- Test replay chạy cả `.txt` và nhánh `.dat`. Nhánh `.dat` dùng fake trace-cmd
  report để kiểm tra pipeline không cần root; đây không phải chứng nhận đọc
  một capture kernel thật trên máy hiện tại.
- Test shell mock kiểm tra instance-scoped start/stop/reset/delete ở cả đường
  thành công và start thất bại; kiểm tra worker khác comm vẫn được phân tích.
  Không chạy trace-cmd thật hoặc sửa tracefs trong bộ test này.
- Browser E2E: chọn job chậm nhất, tìm kiếm, đổi thread/CPU, click chi tiết,
  keyboard zoom, Ctrl+wheel, Shift-pan, kéo chọn vùng, xuất JSON, đổi nguồn
  replay/live, API traversal/404; không có JavaScript exception.
- Xem ảnh desktop 1440px và mobile 390px; sửa phần kết luận bị ép hẹp trên
  mobile, xác nhận không có tràn ngang toàn trang. Timeline trên mobile có
  vùng cuộn ngang riêng. Dữ liệu ảnh là **minh họa nhân tạo**, có nhãn trong UI.

## Benchmark SDK

Cùng compiler `-O2`, cùng chương trình benchmark, mỗi lần 500.000 event sau
1.000 event warmup, xen kẽ 5 lượt gốc và 5 lượt mới, ghi `/dev/null` một thread.

| Bản | Các lượt (ns/event) | Trung vị |
| --- | --- | --- |
| Commit gốc | 1450.2, 1436.5, 1439.0, 1475.9, 1440.8 | 1440.8 ns |
| Bản sửa | 1106.9, 1113.4, 1092.9, 1090.8, 1114.9 | 1106.9 ns |

Trong phép đo này trung vị giảm khoảng **23,2%** (tính từ hai trung vị).
Không dùng kết quả này để khẳng định cải thiện chung trên ứng dụng, ổ đĩa,
tracefs, nhiều thread hoặc máy khác. SDK vẫn format và write đồng bộ mỗi event.

## Phần chưa xác nhận hoặc chưa thay đổi trên dịch vụ

- Máy hiện tại không cho phiên làm việc đọc tracefs, nên chưa chạy capture
  scheduler thực có quyền root. Cần thử `capture-app.sh` và `live-app.sh`
  trên Linux đích có tracefs và quyền phù hợp; kiểm tra không ảnh hưởng phiên
  tracing khác và mức mất event khi tải cao.
- Đã kiểm tra cấu trúc/chuyển đổi Chrome trace JSON và tải xuống trên browser;
  chưa kiểm chứng nhập file trong Perfetto UI thực tế.
- GitHub Actions mới là cấu hình cục bộ; chưa có workflow run trên GitHub.
- Chưa cập nhật description/topics trên GitHub. Gợi ý description:
  `Linux C/C++ thread interaction profiler with job latency diagnostics and scheduler timelines.`
  Topics: `linux`, `profiling`, `tracing`, `scheduler`, `pthreads`, `performance`,
  `perfetto`, `c`, `cpp`.
- Không đổi hoặc bịa số commit để đáp ứng nhận xét “chỉ một commit”.
- Job IDs là số JSON như schema cũ; UI JavaScript vẫn có giới hạn số nguyên
  chính xác ở 2^53-1. PID/TID reuse và cross-process flow cũng giữ giới hạn v1.
- Live đọc phần cuối hữu hạn và suy ra trạng thái LIVE theo thời điểm ghi
  file; không bảo đảm giữ toàn bộ lịch sử của một capture bận dài.
