# Chuyển WAR + baseline DB trên Tomcat Linux hiện có

Luồng `switch_version` dành cho mô hình hiện tại: tool chạy bằng Docker, PostgreSQL chạy bằng Docker trên cùng host, Tomcat có sẵn trong `/home/vsvndev/Contrack-Recreate/contrack-env/runtime/server`.

User chọn **ConTrack WAR** và **Database Profile** trên giao diện, nhấn **Validate selection**, sau đó **Switch Version**. Tool tạo DB làm việc mới, restore baseline, kiểm tra schema thật, stop Tomcat, đổi URL JDBC, thay WAR, start Tomcat và kiểm tra HTTP cùng kết nối đến DB mới. Không cần bundle/repository manifest cho luồng này. Repository và các DB cũ được giữ lại.

Đây là chức năng riêng. `deploy_war` vẫn copy WAR như trước. Không đổi sang `prepare_environment` để dùng luồng này.

## 1. Catalog của 5.2.0 và 5.2.1

```text
/home/vsvndev/Contrack-Recreate/contrack-env/
  catalog/
    wars/
      5.2.0/{app.war,manifest.yaml}
      5.2.1/{app.war,manifest.yaml}
    databases/
      5.2.0/standard-v1/{baseline.dump,manifest.yaml}
      5.2.1/standard-v1/{baseline.dump,manifest.yaml}
  runtime/server/
    bin/start.sh
    bin/shutdown.sh
    conf/
    webapps/
```

Ví dụ manifest DB 5.2.1:

```yaml
database_id: "DB-521-STANDARD-V1"
schema_version: "5.2.1"
profile_type: "standard"
artifact:
  file: "baseline.dump"
status: "available"
```

Ví dụ manifest WAR 5.2.1:

```yaml
war_id: "WAR-521-RELEASE-001"
display_version: "5.2.1"
build_type: "release"
build_id: "001"
artifact:
  file: "app.war"
compatibility:
  database_schema: "5.2.1"
status: "available"
```

Các ID phải duy nhất; 5.2.0 dùng ID khác. `schema_version` là schema thực tế của ConTrack, không phải major PostgreSQL và không nhất thiết trùng tên release. WAR/baseline chỉ ghép được khi hai trường schema khớp. Có thể bổ sung SHA256 thật vào `artifact.sha256`; khi chạy tool luôn ghi checksum vào recipe và kiểm tra lại trước khi switch.

Baseline cần custom archive (`pg_dump -Fc`), cả schema và data. Bộ `pg_restore` trong PostgreSQL container phải đọc được version archive. Không dùng DB metadata `contrack` của tool làm baseline ứng dụng.

## 2. Xác định cấu hình thật trên host

Chạy trên Linux bằng user quản lý Tomcat, ví dụ `vsvndev`. User này cần Python 3.9+, SSH server, quyền dùng Docker và quyền đọc/ghi Tomcat hiện có.

```bash
cd /home/vsvndev/contrack_tool
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}'
ls -l /home/vsvndev/Contrack-Recreate/contrack-env/runtime/server/bin/start.sh
ls -l /home/vsvndev/Contrack-Recreate/contrack-env/runtime/server/bin/shutdown.sh

# Chỉ liệt kê tên file có nhắc PostgreSQL, không in URL/password.
grep -RIl --include='*.xml' --include='*.properties' 'postgresql' \
  /home/vsvndev/Contrack-Recreate/contrack-env/runtime/server/conf
```

Ghi lại **tên container PostgreSQL chứa các DB ứng dụng**, role restore, cổng Tomcat và URL health. Tên container khác với tên service Compose; điền đúng tên từ `docker ps`.

JDBC phải nằm trong file cấu hình bên ngoài WAR mà ứng dụng thật sự đọc. Không dùng file trong thư mục exploded `webapps/app`, vì thư mục đó được thay khi deploy. Hai dạng được hỗ trợ:

* XML: một `<Resource name="jdbc/ConTrack" url="jdbc:postgresql://.../old_db?..." .../>` duy nhất, chọn theo tên Resource.
* Properties UTF-8: một dòng URL duy nhất, chọn theo key, ví dụ `jdbc.url=jdbc:postgresql://127.0.0.1:5439/old_db`.

Runner giữ nguyên host/port/options JDBC, username/password và các cấu hình khác; chỉ đổi tên DB trong URL. Không hỗ trợ URL JDBC nhiều host, URL rút gọn hoặc properties nhiều dòng. File JDBC phải nằm dưới root `contrack-env`, không trùng WAR, catalog hoặc file state.

**Cần một SELECT thật trả về đúng một giá trị schema**, ví dụ từ bảng metadata mà ConTrack đang dùng. Source tool không chứa schema ConTrack nên không có sẵn tên bảng/cột này. Không dùng `SELECT '5.2.1'` để giả lập kiểm tra.

## 3. Tạo cấu hình host runner

Chạy một lần, không ghi đè file đã được chỉnh:

```bash
mkdir -p /home/vsvndev/Contrack-Recreate/config
cp -n deploy/contrack-environments/host-switch.example.json \
  /home/vsvndev/Contrack-Recreate/config/host-switch.json
chmod 600 /home/vsvndev/Contrack-Recreate/config/host-switch.json
nano /home/vsvndev/Contrack-Recreate/config/host-switch.json
```

Điền các trường:

| Trường | Giá trị cần xác nhận |
|---|---|
| `root` | `/home/vsvndev/Contrack-Recreate/contrack-env` |
| `war_filename` | `app.war`, phải giống basename `artifact.file` của WAR |
| `postgres.container` | Tên PostgreSQL container thật |
| `postgres.user` | Role có quyền tạo DB/restore các đối tượng trong baseline |
| `jdbc.file` | Đường dẫn tương đối của JDBC file thật dưới root |
| `jdbc.resource_name` | Tên Resource thật trong XML |
| `schema_version_query` | SELECT schema thật, một giá trị, không có mật khẩu |
| `start_command` | Mặc định `['/bin/bash', './start.sh']` trong JSON phải dùng dấu nháy kép |
| `stop_command` | Mặc định `['/bin/bash', './shutdown.sh']` |
| `server_port` | Cổng HTTP Tomcat thật |
| `health_url` | URL trả 2xx khi ứng dụng hoạt động, ưu tiên endpoint có truy cập DB |

Runner chạy lệnh trong `runtime/server/bin`. Nếu script của bạn tên `shutdown` hoặc `startup.sh`, sửa đúng tên trong JSON. Script start phải chạy nền Tomcat và trả về.

Nếu dùng properties, thay cả object `jdbc` bằng:

```json
{
  "file": "runtime/server/conf/application.properties",
  "format": "properties",
  "property": "jdbc.url"
}
```

Đây chỉ là ví dụ; không tạo file/key mới rồi giả định WAR tự đọc. Với Tomcat chạy trên host và PG demo publish `5439:5432`, URL hiện có thường dùng `127.0.0.1:5439`. Runner không tự sửa host/port JDBC.

Mặc định runner xác định Tomcat qua `/proc` với đúng tham số `-Dcatalina.base=<root>/runtime/server` và lớp `org.apache.catalina.startup.Bootstrap`. Nếu Tomcat dùng cơ chế khác, cấu hình thêm `status_command`, ví dụ `["systemctl", "is-active", "--quiet", "TEN_SERVICE_THAT"]` cùng `inactive_status_codes: [3]`. Chỉ dùng lệnh status xác định đúng Tomcat này. Runner đợi cả process và cổng dừng trước khi đổi file.

PostgreSQL CLI chạy bên trong container bằng `docker exec`, không mount Docker socket vào backend. Auth nội bộ container cần hoạt động sẵn; nếu cần password, cấu hình `.pgpass` ở trong PostgreSQL container theo cách quản trị hiện tại. Không đưa password vào argv, manifest hay recipe. User/role JDBC hiện có cần quyền kết nối và sử dụng các DB mới; dễ demo nhất là dùng cùng role ứng dụng/restore, sau đó tách quyền khi triển khai chính thức.

Kiểm tra trên host; lệnh này không tạo DB hay deploy WAR:

```bash
python3 backend/app/modules/contrack_environments/host_runner.py \
  --config /home/vsvndev/Contrack-Recreate/config/host-switch.json check
```

Kết quả phải có `"ok": true`. Nếu báo `TOMCAT_STATUS_MISMATCH`, cổng đang mở nhưng runner chưa nhận diện đúng process; sửa cấu hình status trước. `JDBC_*` là lỗi file/selector/URL JDBC. `HOST_CONFIGURATION_INVALID` thường do còn placeholder, thiếu file hoặc query schema chưa điền.

## 4. Cấu hình SSH key chỉ được gọi runner

Backend cần SSH đến host bằng một key riêng. Các lệnh sau chạy trên host, không in private key:

```bash
mkdir -p /home/vsvndev/Contrack-Recreate/secrets/switch-ssh
chmod 700 /home/vsvndev/Contrack-Recreate/secrets/switch-ssh

ssh-keygen -t ed25519 -N '' \
  -f /home/vsvndev/Contrack-Recreate/secrets/switch-ssh/id_ed25519 \
  -C contrack-version-switch

mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
touch "$HOME/.ssh/authorized_keys"
chmod 600 "$HOME/.ssh/authorized_keys"
```

Nếu key đã tồn tại, dùng lại key dành riêng cho tính năng này; không chọn overwrite key khác. Thêm **một dòng** vào `~/.ssh/authorized_keys` của user `vsvndev`:

```text
restrict,command="python3 /home/vsvndev/contrack_tool/backend/app/modules/contrack_environments/host_runner.py --config /home/vsvndev/Contrack-Recreate/config/host-switch.json serve" ssh-ed25519 NOI_DUNG_PUBLIC_KEY contrack-version-switch
```

Lấy phần `ssh-ed25519 ...` từ file `id_ed25519.pub`. `restrict` chặn forwarding/PTY; forced command chỉ chấp nhận `check` hoặc `run <run_id>`, không cho chạy shell tùy ý bằng key này. File runner/config cần thuộc user quản trị tin cậy.

Thay `IP_SERVER` bằng IP host mà backend Docker truy cập được:

```bash
ssh-keyscan -t ed25519 IP_SERVER \
  > /home/vsvndev/Contrack-Recreate/secrets/switch-ssh/known_hosts

ssh-keygen -lf /home/vsvndev/Contrack-Recreate/secrets/switch-ssh/known_hosts
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

Đối chiếu hai fingerprint rồi kiểm tra kết nối (không deploy):

```bash
ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes \
  -o UserKnownHostsFile=/home/vsvndev/Contrack-Recreate/secrets/switch-ssh/known_hosts \
  -i /home/vsvndev/Contrack-Recreate/secrets/switch-ssh/id_ed25519 \
  vsvndev@IP_SERVER check
```

Nếu SSH dùng port khác, thêm `-p PORT` vào ssh/ssh-keyscan và cấu hình backend tương ứng. Host cần cho phép SSH từ mạng Docker.

## 5. Bật backend và build Docker

```bash
cd /home/vsvndev/contrack_tool
cp -n deploy/contrack-environments/config.switch-version.example.yaml \
  /home/vsvndev/Contrack-Recreate/config/switch-version.yaml
nano /home/vsvndev/Contrack-Recreate/config/switch-version.yaml
```

Điền `switch_version.ssh_host` cùng IP đã ghi vào `known_hosts`, `ssh_user: vsvndev`, port thật. Không chỉnh file `war-deploy.generated.yaml`; launcher WAR cũ có thể tạo lại file đó.

```bash
CT_ENV_ROOT=/home/vsvndev/Contrack-Recreate/contrack-env \
CT_ENV_CONFIG=/home/vsvndev/Contrack-Recreate/config/switch-version.yaml \
CT_SWITCH_SSH_DIR=/home/vsvndev/Contrack-Recreate/secrets/switch-ssh \
  bash deploy/contrack-environments/start-version-switch.sh
```

Launcher build backend gốc (giữ các assets/local-server hiện có), thêm SSH client bằng image mở rộng và build frontend. Chỉ recreate backend/frontend; không xóa volume. Cuối cùng kiểm tra host runner, root, JDBC selector, kết nối PostgreSQL và số catalog. Không switch WAR/DB trong launcher.

Backend và runner phải dùng cùng root/layout. Backend Docker mặc định chạy root, runner chạy vsvndev; khi bắt đầu run, tool chuyển ownership **các file state/lock và run mới** sang UID/GID của runner để giữ quyền private 0700/0600. Không chmod 777 và không đổi ownership toàn bộ Tomcat/catalog. Nếu backend chạy non-root, cần bố trí cùng UID/GID và quyền state tương thích.

Không chạy lại `start-war-deploy.sh` hoặc `docker compose up` chỉ với base file sau khi đã bật luồng mới; các lệnh đó có thể đưa backend về cấu hình WAR-only hoặc bỏ mount. Khi cập nhật tool, chạy lại launcher `start-version-switch.sh` với cùng biến cấu hình.

## 6. Demo user trên giao diện

1. Truy cập `http://IP_SERVER:8888`, Ctrl+F5, mở **ConTrack Environments**.
2. Phải thấy **Switch version and database**.
   Trước lần chuyển thành công đầu tiên, Current environment hiển thị **NO RECORDED SWITCH**. Copy baseline/build Docker chưa tạo môi trường và không chứng minh Tomcat đang dừng. Nếu vẫn thấy **NOT PREPARED**, kiểm tra form bên dưới: **Prepare environment** là mode cũ hoặc frontend chưa cập nhật; phải kiểm tra `enabled`, `operation_mode` và root bên trong backend đang chạy, rồi dùng đúng launcher và Ctrl+F5. Không tự tạo `runtime/current/version.yaml` để bỏ qua trạng thái ban đầu.
3. Chọn WAR 5.2.0. Danh sách **Database Profile** chỉ hiển thị baseline có schema tương ứng.
4. Chọn `standard — DB-520-STANDARD-V1`, nhấn **Validate selection**. Bước này không tạo DB.
5. Nhấn **Switch Version** một lần. Theo dõi Run history / View run.
6. Chờ các bước `database_create`, `database_restore`, `database_schema`, `stage`, `server_stop`, `war_deploy`, `server_start`, `health_check`, `runtime_state` thành công và run **READY**.
7. Current environment hiển thị tên DB mới dạng `ct_520_...`. Truy cập ứng dụng và kiểm tra chức năng cần dùng.
8. Chọn WAR 5.2.1 + baseline 5.2.1, thao tác tương tự. Tool tạo DB mới; DB lần trước còn nguyên.

Mỗi lần bấm Switch Version đều restore một DB mới. Chưa có lựa chọn reuse DB làm việc hoặc sinh dữ liệu theo chức năng/bug trong tính năng này. Muốn quay lại version cũ, chọn lại WAR/baseline cũ để dựng DB mới; thao tác này không tự kết nối lại DB đã test trước đó.

Health yêu cầu HTTP 2xx, process/cổng Tomcat hoạt động và PostgreSQL có ít nhất một client connection khác đến đúng DB mới. Nếu ứng dụng chỉ mở kết nối DB khi thao tác, chọn endpoint health có truy cập DB hoặc truy cập chức năng trong thời gian health check. URL đăng nhập trả 200 một mình chưa đủ để báo READY.

## 7. Khi lỗi và cách khôi phục

* Restore hoặc schema sai: giữ Tomcat/WAR/JDBC hiện tại, giữ DB ứng viên để điều tra.
* Lỗi sau khi stop/đổi file: runner cố stop ứng viên, khôi phục WAR, JDBC và thư mục exploded cũ; start lại bản cũ nếu trước đó nó đang chạy. Run vẫn FAILED, kèm `rollback_status: SUCCESS` hoặc `FAILED`.
* Backup nằm ở `runs/<run_id>/backup`, có thể chứa JDBC credentials; giữ private và không đưa vào Git. `failed-exploded` giữ file ứng viên nếu rollback.
* Không drop DB cũ hoặc DB lỗi tự động. Cần có chính sách dọn DB/run sau demo để tránh đầy đĩa.
* SSH bị ngắt: host có thể tiếp tục chạy. Host giữ khóa phụ `.host`; thao tác môi trường khác bị chặn đến khi host hoàn tất. Refresh giao diện để đọc state/log trên filesystem chung, không bấm lặp.
* Nếu process bị kill hoặc rollback thất bại, Current environment có thể UNKNOWN. Kiểm tra thực tế Tomcat, JDBC, WAR và DB; lưu backup rồi sửa/reset state theo kết quả kiểm tra trước khi chạy lại. Không đánh dấu READY bằng tay để bỏ qua health.

Rollback chỉ khôi phục các file triển khai và kết nối DB; không hoàn tác thao tác trên repository hoặc dịch vụ bên ngoài. Các DB cũ không bị migration trong luồng này. Candidate DB có thể đã có dữ liệu do app tạo trước khi health lỗi, nên được giữ lại.

## Kiểm chứng trong source

Unit tests chạy orchestration thực trên filesystem tạm, giả lập biên PostgreSQL/Tomcat: chọn schema, restore trước stop, checksum, backup/rollback, khóa sau mất SSH, và chỉnh JDBC XML/properties. Frontend tests kiểm tra chọn baseline tương thích, chặn click trùng và gọi đúng endpoint. Docker build/SSH/Tomcat/PostgreSQL thật phải được kiểm chứng trên server bằng các bước trên; không có truy cập server từ workspace Windows này.
