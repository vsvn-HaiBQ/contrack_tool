# Deploy WAR vào Tomcat có sẵn trên server

Muốn test nhiều version với DB riêng trên PostgreSQL Docker đang có: xem [Các bước demo switch WAR và DB](contrack-db-switch-demo.md). Phần DB/JDBC/start-stop trong hướng dẫn đó hiện là thao tác quản trị thủ công; UI này vẫn chỉ Deploy WAR.

Áp dụng cho server của bạn: Tomcat đã có cấu hình tại `/home/vsvndev/Contrack-Recreate/contrack-env/runtime/server`; yêu cầu là chọn WAR từ catalog rồi copy vào `webapps`, dùng DB/repository đang cấu hình.

Chế độ `deploy_war` copy đúng `artifact.file` trong WAR manifest và giữ tên file khi đưa vào `webapps` (ví dụ `app.war` → `webapps/app.war`). Giữ `conf`, `bin`, `lib`, DB/repository và các ứng dụng khác. Không tạo working DB, không cần schema query, PostgreSQL CLI, Tomcat template hoặc bản Tomcat mới. Hoạt động được khi Tomcat chạy sẵn trên host, vì backend container chỉ ghi WAR qua bind mount. Tool không tự restart Tomcat và không xóa exploded application; cơ chế reload hiện có của Tomcat quyết định khi nào WAR được nạp.

## Cách khởi động đề nghị khi UI vẫn disabled

Cập nhật source trên Linux server, sau đó chạy một lần:

```bash
cd /home/vsvndev/contrack_tool
CT_ENV_ROOT=/home/vsvndev/Contrack-Recreate/contrack-env \
  bash deploy/contrack-environments/start-war-deploy.sh
```

Launcher kiểm tra Tomcat có sẵn, tạo file **riêng** `Contrack-Recreate/config/war-deploy.generated.yaml` với `enabled: true` và `operation_mode: deploy_war`, build/recreate backend/frontend bằng override đúng, rồi đọc lại cấu hình **trong container vừa tạo**. File `config/environment.yaml` hiện tại và cấu hình Tomcat được giữ nguyên. Launcher chỉ ghi đè file generated nếu có header xác nhận do chính launcher tạo.

Root được truyền qua `CT_ENV_ROOT` cho cả bind mount source, target và biến `CONTRACK_ENV_ROOT` của backend. Vì vậy host và container dùng cùng đường dẫn `/home/vsvndev/Contrack-Recreate/contrack-env`; root trong YAML được biến này ghi đè.

Chỉ xem setup thành công khi cuối lệnh có:

```text
enabled: True
mode: deploy_war
root: /home/vsvndev/Contrack-Recreate/contrack-env
VERIFIED: enabled=True, mode=deploy_war, root and Tomcat mount are correct.
```

Sau đó Ctrl+F5. Form phải là **ConTrack WAR / Deploy WAR**. Launcher không copy WAR; user thực hiện deploy qua UI. Nếu launcher đã VERIFIED nhưng UI còn cảnh báo cũ, kiểm tra URL frontend có trỏ đúng server/project vừa recreate hay không. Dùng lại launcher khi cần cập nhật/recreate deployment này để không mất override.

Các bước dưới đây dành cho cấu hình thủ công, tương đương launcher nhưng dùng `environment.yaml` do admin quản lý.

## 1. Thư mục cần có

```text
/home/vsvndev/
├── contrack_tool/
└── Contrack-Recreate/
    ├── config/environment.yaml
    └── contrack-env/
        ├── catalog/wars/5.2.0/hf-8383-001/
        │   ├── manifest.yaml
        │   └── app.war
        ├── runtime/server/
        │   ├── conf/server.xml            # cấu hình đang có, tool giữ nguyên
        │   ├── webapps/app.war            # giữ tên file khai báo trong manifest
        │   └── ...                       # các file Tomcat hiện có
        └── runs/                         # lịch sử do tool tạo
```

Không cần tạo `tomcat-conf` hoặc `secrets/runtime.pgpass` cho chế độ copy WAR này. Nếu các thư mục đó đã được tạo trước đây, có thể giữ nguyên, override mới không mount/chạm tới chúng. Không chạy các bước Prepare Environment theo template của hướng dẫn cũ với cấu hình Tomcat hiện tại.

## 2. Tạo/sửa YAML cấu hình

Trên Linux host:

```bash
cd /home/vsvndev/contrack_tool
export CT_ENV_ROOT=/home/vsvndev/Contrack-Recreate/contrack-env
export CT_ENV_CONFIG=/home/vsvndev/Contrack-Recreate/config/environment.yaml

mkdir -p /home/vsvndev/Contrack-Recreate/config
nano "$CT_ENV_CONFIG"
```

Điền cấu hình:

```yaml
enabled: true
operation_mode: deploy_war
root: /home/vsvndev/Contrack-Recreate/contrack-env
server: runtime/server
```

Override WAR mount thư mục host vào **cùng đường dẫn** trong backend container và đặt `CONTRACK_ENV_ROOT` bằng `CT_ENV_ROOT`. Biến môi trường này ưu tiên hơn `root` trong YAML, tránh lệch root khi shell/config cũ còn chứa `/srv/contrack-env`. Đích file thực tế là:

```text
/home/vsvndev/Contrack-Recreate/contrack-env/runtime/server/webapps/app.war
```

Nếu YAML cũ chứa `pg_host`, `tomcat_home`, `config_templates` và các giá trị chuẩn bị môi trường khác, có thể bỏ các field đó khi dùng config tối thiểu trên. DB metadata và Redis của chính tool vẫn dùng cấu hình Compose gốc.

Nếu chạy backend trực tiếp trên host thay vì Docker, đặt `root: /home/vsvndev/Contrack-Recreate/contrack-env` và truyền `CONTRACK_ENV_CONFIG` vào process backend.

## 3. Thêm WAR vào catalog

Tạo thư mục cho từng build mới, giữ artifact cũ:

```bash
mkdir -p "$CT_ENV_ROOT/catalog/wars/5.2.0/hf-8383-001"
nano "$CT_ENV_ROOT/catalog/wars/5.2.0/hf-8383-001/manifest.yaml"
```

Nội dung mẫu:

```yaml
war_id: WAR-5.2.0-HF8383-001
display_version: 5.2.0
build_type: hotfix
build_id: hf-8383-001
artifact:
  file: app.war
compatibility:
  database_schema: 5.2.0
status: available
```

Đặt WAR thật tại `catalog/wars/5.2.0/hf-8383-001/app.war`. Với cấu trúc hiện tại `catalog/wars/5.2.0/app.war`, đặt manifest ngay tại `catalog/wars/5.2.0/manifest.yaml` và khai báo `artifact.file: app.war`; cấu trúc phẳng này cũng được hỗ trợ. Nguồn được lấy theo manifest, đích giữ basename: `packages/app.war` cũng copy thành `webapps/app.war`. Preview, recipe, runtime state và log ghi đúng tên/đích này. Các file WAR tên khác đã deploy trước đó được giữ nguyên; quản trị viên quản lý chúng riêng.

Thông tin schema trong manifest mô tả yêu cầu của WAR; chế độ này **không kiểm tra hay chuyển đổi DB đang dùng**. Quản trị viên chọn WAR phù hợp cấu hình DB hiện tại. Không cần baseline, repository manifest hoặc bundle trong chế độ này; reader chỉ đọc `catalog/wars`.

## 4. Build và chạy tool

Trong cùng SSH shell đã export hai biến trên:

```bash
test -f "$CT_ENV_CONFIG"
test -f "$CT_ENV_ROOT/runtime/server/conf/server.xml"
test -d "$CT_ENV_ROOT/runtime/server/webapps"

docker compose -f docker-compose.yml \
  -f deploy/contrack-environments/compose.war-deploy.override.yaml \
  config --quiet

# Dùng Dockerfile backend gốc; chế độ này không cần image Java/PG CLI mở rộng.
docker compose -f docker-compose.yml \
  -f deploy/contrack-environments/compose.war-deploy.override.yaml \
  up -d --build backend frontend
```

Từ các lần sau, khi restart/recreate backend, tiếp tục dùng đúng hai file `-f` để giữ mount và biến config. Không ghép thêm `compose.override.yaml` dành cho Prepare Environment đầy đủ. Backend cần quyền ghi vào `runtime/server/webapps`, `runtime/current`, `runtime/environment.lock` và `runs`. WAR được ghi qua file tạm, kiểm tra SHA-256 rồi rename atomic; Tomcat không nhận file WAR mới đang copy dở. Không đổi quyền `conf` và không `chmod -R 777`.

## 5. User thao tác

Trước lần deploy đầu tiên qua tool, phần Current WAR deployment hiển thị **NO RECORDED DEPLOYMENT**. Điều này chỉ có nghĩa tool chưa có bản ghi `runtime/current/version.yaml`; không xác định Tomcat đang dừng/chưa được cấu hình. WAR đã copy thủ công trước đó không tự được gán version vì tool không suy đoán version từ tên file. Nếu thấy **Current environment / NOT PREPARED** cùng nút **Prepare Environment**, kiểm tra YAML thực tế được backend load: phải có `operation_mode: deploy_war`, sau đó cập nhật/recreate backend và refresh frontend.

`runtime/current/version.yaml` là file **tool tự sinh**, không cần điền trước bằng manifest/bundle mẫu. YAML lỗi (ví dụ dán lặp thành `repository: "..."bundle: "..."` trên cùng dòng) được báo với đường dẫn và dòng/cột, đồng thời chặn trước khi copy WAR. Với file trạng thái mẫu đã tạo thủ công và chưa có deployment thực tế, giữ bản sao bằng cách đổi tên file thành `version.yaml.invalid.<timestamp>.bak`, rồi deploy qua UI để tool ghi lại trạng thái đúng. Đây là metadata tool; không đổi/xóa `runtime/server/conf` hoặc database để xử lý lỗi YAML này.

1. Refresh frontend và vào **ConTrack Environments** bằng tài khoản có quyền menu này.
2. Màn hình hiển thị **Deploy WAR to existing Tomcat**, dropdown **ConTrack WAR**; không có bước chọn database/repository.
3. Chọn WAR, bấm **Validate selection** để kiểm tra artifact và thư mục Tomcat đích.
4. Bấm **Deploy WAR**. Tool giữ lock dùng chung để không có hai lần deploy/switch đồng thời.
5. Run thành **DEPLOYED** khi file WAR đã copy thành công; log ghi rõ đích và operation mode.
6. Truy cập ứng dụng bằng URL/port Tomcat đang dùng. Nếu Tomcat không tự reload WAR, dùng quy trình restart Tomcat hiện có của server.

**DEPLOYED** xác nhận copy file; không khẳng định application đã chạy, schema tương thích hoặc toàn bộ environment READY. Run history giữ thông tin `application_status: NOT_CHECKED`. Nếu copy lỗi trước atomic rename, WAR cũ vẫn giữ nguyên; failed run và log được lưu lại.

## 6. Kiểm tra trên host

```bash
ls -l "$CT_ENV_ROOT/runtime/server/webapps/app.war"
sha256sum "$CT_ENV_ROOT/catalog/wars/5.2.0/hf-8383-001/app.war"
sha256sum "$CT_ENV_ROOT/runtime/server/webapps/app.war"
ls -1 "$CT_ENV_ROOT/runs"
```

Hai checksum phải bằng nhau sau deploy thành công. Nếu không thấy dropdown WAR, kiểm tra đủ manifest/artifact, cấu hình `operation_mode`, frontend/backend code mới và quyền role. Nếu thấy Prepare Environment thay vì Deploy WAR, backend đang đọc YAML cũ hoặc chưa được recreate với override WAR mới.

Nếu catalog lỗi (ví dụ manifest chưa đúng), giao diện hiển thị lỗi catalog riêng và tự tải lại khoảng mỗi 3 giây. Sau khi sửa file, danh sách WAR và nút deploy tự phục hồi; cũng có thể bấm Refresh. Khi catalog chưa tải được, giao diện hiện CONFIGURATION UNAVAILABLE thay vì suy ra NOT PREPARED. Lỗi tải lịch sử không làm mất catalog hợp lệ.

## 7. Chẩn đoán WAR copy thất bại

Thông báo cũ `WAR_DEPLOY_FAILED` không xác định được chính xác nguyên nhân. Code mới ghi `failed_operation` (tạo file tạm, chmod, copy bytes, fsync, rename hoặc lưu state), mã errno và mã lỗi riêng vào run/error log. Không in exception arguments vì có thể chứa dữ liệu bí mật. Nếu storage hết chỗ đến mức không ghi được state, thông báo đã lọc được ghi vào log backend.

Từ thư mục source trên Linux host, sau khi cập nhật file diagnostic, chạy kiểm tra **trong chính backend container**:

```bash
docker compose exec -T backend python - \
  < deploy/contrack-environments/check-war-storage.py
```

Không cần rebuild image chỉ để chạy file kiểm tra qua stdin. Script in UID/GID, owner/mode thư mục và WAR, số byte/inode trống, cờ filesystem read-only; sau đó thử tạo/chmod/ghi/fsync/rename và xóa các file tạm do chính nó tạo. Không đổi WAR, conf hay quyền thư mục có sẵn. Nếu tất cả phép thử PASS, xem lỗi chi tiết của run (đặc biệt bước replace runtime WAR) vì probe không ghi đè WAR hiện có.

Nếu công cụ kiểm tra in root `/srv/contrack-env` trong khi launcher trước đó VERIFIED root `/home/vsvndev/Contrack-Recreate/contrack-env`, hãy so sánh `container`, `config file`, `root override`, `enabled`, `mode` được in ở đầu. Container được kiểm tra có thể đã bị recreate bằng Compose gốc (thiếu override), hoặc lệnh đang nhắm project khác. Chạy lại launcher từ đúng source project, rồi chạy diagnostic trong cùng thư mục. Không tạo thêm cây `/srv/contrack-env` để che lỗi mount; script sẽ dừng rõ ràng khi chưa load Deploy WAR hoặc thiếu webapps.

| Mã lỗi | Hướng kiểm tra |
|---|---|
| `WAR_PERMISSION_DENIED` / EACCES / EPERM | UID/GID của backend, quyền ghi và traverse thư mục, ACL, immutable flag, NFS root squash hoặc cơ chế bảo vệ filesystem trên host |
| `WAR_STORAGE_FULL` / ENOSPC | Byte trống và inode của filesystem chứa runtime, không chỉ dung lượng bên trong image |
| `WAR_QUOTA_EXCEEDED` / EDQUOT | Quota user/filesystem |
| `WAR_READ_ONLY` / EROFS | Bind mount/backend và trạng thái read-only trên host |
| `WAR_DESTINATION_BUSY` / EBUSY | File WAR có bị bind-mount riêng hoặc mount đặc biệt khác không |
| `WAR_PATH_NOT_FOUND` / ENOENT | File nguồn, thư mục đích hoặc file tạm có bị tác vụ khác di chuyển/xóa không |

Chỉ điều chỉnh quyền sau khi xác định user/mount thực tế; không áp dụng `chmod -R 777` cho toàn bộ Tomcat. Run có `war_copied: true` nghĩa file đã thay thành công nhưng bước ghi trạng thái sau đó lỗi; kiểm tra checksum trước khi deploy lại.
