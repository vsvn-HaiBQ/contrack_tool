# Deploy WAR vào Tomcat có sẵn trên server

Áp dụng cho server của bạn: Tomcat đã có cấu hình tại `/home/vsvndev/Contrack-Recreate/contrack-env/runtime/server`; yêu cầu là chọn WAR từ catalog rồi copy vào `webapps`, dùng DB/repository đang cấu hình.

Chế độ `deploy_war` chỉ thay file `webapps/contrack.war`, giữ `conf`, `bin`, `lib`, DB/repository và các ứng dụng khác. Không tạo working DB, không cần schema query, PostgreSQL CLI, Tomcat template hoặc bản Tomcat mới. Hoạt động được khi Tomcat chạy sẵn trên host, vì backend container chỉ ghi WAR qua bind mount. Tool không tự restart Tomcat và không xóa exploded application; cơ chế reload hiện có của Tomcat quyết định khi nào WAR được nạp.

## 1. Thư mục cần có

```text
/home/vsvndev/
├── contrack_tool/
└── Contrack-Recreate/
    ├── config/environment.yaml
    └── contrack-env/
        ├── catalog/wars/5.2.0/hf-8383-001/
        │   ├── manifest.yaml
        │   └── contrack.war
        ├── runtime/server/
        │   ├── conf/server.xml            # cấu hình đang có, tool giữ nguyên
        │   ├── webapps/contrack.war       # file đích
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
root: /srv/contrack-env
server: runtime/server
```

Đường dẫn `/srv/contrack-env` là root bên trong **backend container**. Nó được mount tới `/home/vsvndev/Contrack-Recreate/contrack-env` trên host. Do đó đích file thực tế đúng là:

```text
/home/vsvndev/Contrack-Recreate/contrack-env/runtime/server/webapps/contrack.war
```

Nếu YAML cũ chứa `pg_host`, `tomcat_home`, `config_templates` và các giá trị chuẩn bị môi trường khác, có thể bỏ các field đó khi dùng config tối thiểu trên. DB metadata và Redis của chính tool vẫn dùng cấu hình Compose gốc.

Nếu chạy backend trực tiếp trên host thay vì Docker, đặt `root: /home/vsvndev/Contrack-Recreate/contrack-env` và truyền `CONTRACK_ENV_CONFIG` vào process backend; không dùng `/srv/contrack-env` khi không có mount tương ứng.

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
  file: contrack.war
compatibility:
  database_schema: 5.2.0
status: available
```

Đặt WAR thật tại `catalog/wars/5.2.0/hf-8383-001/contrack.war`. File có thể có tên khác nếu `artifact.file` khớp, nhưng đích deploy hiện là `webapps/contrack.war`. Nếu ứng dụng thực tế dùng context/tên WAR khác, cần cấu hình/điều chỉnh đích trước khi sử dụng.

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

1. Refresh frontend và vào **ConTrack Environments** bằng tài khoản có quyền menu này.
2. Màn hình hiển thị **Deploy WAR to existing Tomcat**, dropdown **ConTrack WAR**; không có bước chọn database/repository.
3. Chọn WAR, bấm **Validate selection** để kiểm tra artifact và thư mục Tomcat đích.
4. Bấm **Deploy WAR**. Tool giữ lock dùng chung để không có hai lần deploy/switch đồng thời.
5. Run thành **DEPLOYED** khi file WAR đã copy thành công; log ghi rõ đích và operation mode.
6. Truy cập ứng dụng bằng URL/port Tomcat đang dùng. Nếu Tomcat không tự reload WAR, dùng quy trình restart Tomcat hiện có của server.

**DEPLOYED** xác nhận copy file; không khẳng định application đã chạy, schema tương thích hoặc toàn bộ environment READY. Run history giữ thông tin `application_status: NOT_CHECKED`. Nếu copy lỗi trước atomic rename, WAR cũ vẫn giữ nguyên; failed run và log được lưu lại.

## 6. Kiểm tra trên host

```bash
ls -l "$CT_ENV_ROOT/runtime/server/webapps/contrack.war"
sha256sum "$CT_ENV_ROOT/catalog/wars/5.2.0/hf-8383-001/contrack.war"
sha256sum "$CT_ENV_ROOT/runtime/server/webapps/contrack.war"
ls -1 "$CT_ENV_ROOT/runs"
```

Hai checksum phải bằng nhau sau deploy thành công. Nếu không thấy dropdown WAR, kiểm tra đủ manifest/artifact, cấu hình `operation_mode`, frontend/backend code mới và quyền role. Nếu thấy Prepare Environment thay vì Deploy WAR, backend đang đọc YAML cũ hoặc chưa được recreate với override WAR mới.
