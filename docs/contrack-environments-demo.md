# Demo ConTrack Environments với thư mục Contrack-Recreate

Tài liệu này dùng chức năng đã implement, giữ nguyên code và Compose gốc. Các lệnh chạy **trên Linux server**, từ thư mục `contrack_tool`, bằng Bash. Đây là demo dựng môi trường thật: cần WAR chạy được, baseline PostgreSQL đúng schema và cấu hình ứng dụng thật.

## Trường hợp Tomcat đã có cấu hình tại runtime/server

Theo thông tin server bổ sung, thư mục `/home/vsvndev/Contrack-Recreate/contrack-env/runtime/server` đã có cấu hình Tomcat và đích WAR là `webapps/` bên trong thư mục này. Dùng [hướng dẫn Deploy WAR vào Tomcat có sẵn](contrack-war-deploy-existing-tomcat.md) với `operation_mode: deploy_war` cho trường hợp của bạn.

Các bước bên dưới chỉ dành cho `operation_mode: prepare_environment`: luồng này tạo working DB mới và thay `runtime/server/conf` bằng template đã render. Không trỏ `config_templates` vào chính `runtime/server/conf` để chạy thử. Chế độ Deploy WAR có override riêng, không cần template, PostgreSQL CLI hay image Tomcat mới.

## 1. Xác định đường dẫn host và container

Giả định cấu trúc bạn mô tả là:

```text
<thu-muc-cha>/
├── contrack_tool/
│   ├── docker-compose.yml
│   └── deploy/contrack-environments/
└── Contrack-Recreate/
    ├── contrack-env/
    │   ├── catalog/{wars,databases,repositories,bundles}/
    │   ├── runtime/{server,databases,repositories,current}/
    │   └── runs/
    ├── config/environment.yaml
    ├── secrets/runtime.pgpass
    └── tomcat-conf/
```

`config`, `secrets`, `tomcat-conf` là các thư mục bổ sung cần chuẩn bị, nằm ngoài runtime để không bị thay khi switch. Nếu `catalog`, `runtime`, `runs` thực tế nằm **ngay trong `Contrack-Recreate`**, chỉ đổi `CT_ENV_ROOT` ở bước sau thành `"$CT_RECREATE_ROOT"`. Nếu root thực tế là `/contrack-env`, đặt `CT_ENV_ROOT=/contrack-env`.

| Nội dung | Trên Linux host | Backend container nhìn thấy |
|---|---|---|
| Root môi trường | `$CT_ENV_ROOT` | `/srv/contrack-env` |
| YAML cấu hình | `$CT_ENV_CONFIG` | `/etc/contrack/environment.yaml` |
| Tomcat binaries | `$CT_TOMCAT_HOME` | `/opt/tomcat` |
| Template conf | `$CT_TOMCAT_CONF` | `/etc/contrack/tomcat-conf` |
| PG password file | `$CT_PGPASS_FILE` | `/run/secrets/contrack-runtime.pgpass` |

Vì vậy **`root` trong YAML dùng đường dẫn container `/srv/contrack-env`**, không dùng đường dẫn host `../Contrack-Recreate/...`.

Kiến trúc demo: browser → frontend → FastAPI; FastAPI chạy PostgreSQL CLI và Tomcat con trong cùng container backend. Git/SVN và target PostgreSQL có thể là các server/container sẵn có. Adapter hiện tại không SSH tới Linux khác và không start/stop một Tomcat container riêng. Nếu Tomcat hiện tại chạy container riêng, cần chuẩn bị một Tomcat home riêng cho runtime này.

## 2. Chuẩn bị thư mục và biến môi trường

Vào đúng thư mục source trên server, sau đó chạy:

```bash
# Thay dòng này bằng đường dẫn thực tế của contrack_tool.
cd /duong-dan-thuc-te/contrack_tool

# Cấu hình lại khi mở shell mới, hoặc source file exports riêng của quản trị viên.
export CT_RECREATE_ROOT="$(realpath ../Contrack-Recreate)"
export CT_ENV_ROOT="$CT_RECREATE_ROOT/contrack-env"
export CT_ENV_CONFIG="$CT_RECREATE_ROOT/config/environment.yaml"
export CT_TOMCAT_CONF="$CT_RECREATE_ROOT/tomcat-conf"
export CT_PGPASS_FILE="$CT_RECREATE_ROOT/secrets/runtime.pgpass"

# Thay bằng Tomcat standalone đã giải nén, tương thích WAR thực tế.
# Folder phải chứa bin/startup.sh, bin/shutdown.sh, bin/catalina.sh và lib/.
export CT_TOMCAT_HOME=/duong-dan-thuc-te/apache-tomcat

# App ConTrack demo mở ở host:18080; nội bộ container vẫn dùng 8080.
export CT_APPLICATION_PORT=18080

mkdir -p "$CT_ENV_ROOT/catalog/wars" \
  "$CT_ENV_ROOT/catalog/databases" \
  "$CT_ENV_ROOT/catalog/repositories" \
  "$CT_ENV_ROOT/catalog/bundles" \
  "$CT_ENV_ROOT/runtime/server" \
  "$CT_ENV_ROOT/runtime/databases" \
  "$CT_ENV_ROOT/runtime/repositories" \
  "$CT_ENV_ROOT/runtime/current" \
  "$CT_ENV_ROOT/runs" \
  "$CT_RECREATE_ROOT/config" \
  "$CT_RECREATE_ROOT/secrets" \
  "$CT_TOMCAT_CONF"

test -f "$CT_TOMCAT_HOME/bin/startup.sh"
test -f "$CT_TOMCAT_HOME/bin/shutdown.sh"
test -d "$CT_TOMCAT_HOME/lib"
```

Không dùng biến `$HOME` làm thư mục dự án. Mọi lệnh Compose bên dưới cần chạy trong cùng shell đang có các biến đã export. Các biến `CT_*` phục vụ Compose nội suy **host paths**; biến `CONTRACK_ENV_CONFIG` bên trong backend được override Compose cung cấp tự động.

## 3. Chọn target PostgreSQL và repository

Chuẩn bị các giá trị thực tế sau trước khi bật module:

| Giá trị cần biết | Ví dụ cách xác định |
|---|---|
| DB host/port mà backend container truy cập được | IP/DNS nội bộ hoặc service name trên cùng Docker network |
| Role cho working DB | `contrack_runtime`, có LOGIN và CREATEDB; đủ quyền restore baseline |
| Source DB để tạo baseline | DB demo đã có schema ConTrack tương thích WAR |
| Schema-version SELECT thật | SELECT đọc metadata schema, trả một dòng/một cột như `5.2.0` |
| Repository URL | SVN/Git đang có và tương thích dữ liệu baseline |
| Cấu hình datasource/repository của WAR | File/context/property mà ứng dụng ConTrack thật đọc |

Target PostgreSQL có thể dùng chung PostgreSQL **server** hiện có nếu admin đồng ý, nhưng module luôn tạo các database mới `ct_*`; không restore đè DB metadata của tool hay DB đang dùng. Nếu cần role mới, DBA có thể chạy trên máy có PostgreSQL client:

```bash
# Thay host và DBA_ROLE; -P hỏi mật khẩu role mới tương tác.
createuser -h DB_HOST_THUC_TE -p 5432 -U DBA_ROLE -P --createdb contrack_runtime
```

DB server cần cho phép kết nối từ backend container theo cấu hình network/authentication hiện có. `127.0.0.1` trong backend container là chính backend, không phải Linux host hay container PostgreSQL khác. Repository URL cũng phải truy cập được từ backend và ứng dụng ConTrack.

Nếu target DB/repository là Docker container ở network khác: admin kết nối chúng và backend vào network chung hoặc dùng địa chỉ/port đã publish có thể truy cập được. Nếu dùng network chung, khai báo network đó trong một Compose override riêng để cấu hình tồn tại sau recreate. Không thay Git/SVN architecture để chạy demo.

## 4. Tạo cấu hình module

Tạo file mới từ mẫu, tránh ghi đè cấu hình đang có:

```bash
if [ ! -e "$CT_ENV_CONFIG" ]; then
  cp deploy/contrack-environments/config.example.yaml "$CT_ENV_CONFIG"
fi
chmod 600 "$CT_ENV_CONFIG"
nano "$CT_ENV_CONFIG"
```

Nội dung tối thiểu cho phương án Docker này:

```yaml
# Bật sau khi hoàn tất các giá trị thật và các bước chuẩn bị bên dưới.
enabled: true
root: /srv/contrack-env

pg_host: DB_HOST_THUC_TE
pg_port: 5432
pg_user: contrack_runtime
pg_passfile: /run/secrets/contrack-runtime.pgpass

# Thay chuỗi bên dưới bằng SELECT thật đọc metadata schema của ConTrack.
# Kết quả bắt buộc đúng một dòng/một cột, ví dụ 5.2.0.
schema_version_query: "THAY_BANG_SELECT_SCHEMA_THAT"

tomcat_home: /opt/tomcat
config_templates: /etc/contrack/tomcat-conf
server_host: 127.0.0.1
server_port: 8080
health_url: http://127.0.0.1:8080/contrack/

command_timeout: 1800
health_timeout: 180
```

Đây là mẫu cần điền, **chưa phải cấu hình chạy ngay**: `DB_HOST_THUC_TE` và `THAY_BANG_SELECT_SCHEMA_THAT` phải được thay. Giữ các subpath catalog/runtime/runs mặc định nếu đang dùng đúng cấu trúc đã nêu. Nếu dùng endpoint health khác, thay path nhưng giữ cùng host/port nội bộ và chọn URL trả HTTP 200 trực tiếp, không redirect.

Không dùng `SELECT '5.2.0'` để giả lập schema check. Cần biết bảng/property schema-version thật trong baseline. Repository mã nguồn tool này không có schema ứng dụng Java để tự suy ra SELECT đó.

## 5. Cấu hình mật khẩu PostgreSQL

Tạo file bằng editor, không đưa mật khẩu vào command line:

```bash
if [ ! -e "$CT_PGPASS_FILE" ]; then
  (umask 077; touch "$CT_PGPASS_FILE")
fi
chmod 600 "$CT_PGPASS_FILE"
nano "$CT_PGPASS_FILE"
```

Nội dung một dòng, thay host và mật khẩu bằng giá trị thật:

```text
DB_HOST_THUC_TE:5432:*:contrack_runtime:MAT_KHAU_THAT
```

Wildcard `*` ở vị trí database là cần thiết vì mỗi run tạo một working DB tên khác nhau. Host/port/user phải khớp YAML. Escape `:` và `\` trong mật khẩu theo định dạng `.pgpass`.

File này cấp mật khẩu cho **PostgreSQL CLI**. JDBC của ConTrack cần datasource credentials trong cấu hình ứng dụng riêng ở bước sau; Java không tự sử dụng `.pgpass`.

## 6. Chuẩn bị Tomcat conf template thật

Với thư mục `tomcat-conf` mới, copy đủ conf của Tomcat standalone:

```bash
# Chỉ copy lần đầu vào folder mới; không ghi đè template đã tùy chỉnh.
if [ ! -e "$CT_TOMCAT_CONF/server.xml" ]; then
  cp -RL "$CT_TOMCAT_HOME/conf/." "$CT_TOMCAT_CONF/"
fi
nano "$CT_TOMCAT_CONF/server.xml"
```

`-L` copy nội dung thật của symlink, vì template có symlink bị từ chối. Không copy file binary/keystore vào template: reader hiện tại đọc các file template theo UTF-8; đặt file binary ở vị trí khác rồi cấu hình Tomcat tham chiếu tới đường dẫn mount thích hợp.

Trong `server.xml`, dùng Connector HTTP port 8080, hoặc `port="{{SERVER_PORT}}"`; các Connector khác cũng cần port số hợp lệ. Giữ các cấu hình Tomcat bắt buộc còn lại. Trong file datasource/application thực tế mà WAR đọc, thay:

```text
Tên database hiện tại  → {{DATABASE_NAME}}
JDBC URL hiện tại      → {{JDBC_URL}}       (nếu cấu hình có JDBC URL)
Repository URL        → {{REPOSITORY_URL}}
```

Các placeholder được hỗ trợ khác: `{{DATABASE_HOST}}`, `{{DATABASE_PORT}}`, `{{DATABASE_USER}}`. Không có placeholder password. Dùng cấu hình secret/password mà ứng dụng hiện hỗ trợ; không đưa secret vào manifest/run log.

Ví dụ **hình dạng giá trị** JDBC, không phải tên property chuẩn của ConTrack:

```text
jdbc:postgresql://{{DATABASE_HOST}}:{{DATABASE_PORT}}/{{DATABASE_NAME}}
```

Phải có cả `{{DATABASE_NAME}}` và `{{REPOSITORY_URL}}` trong template và chúng phải được đặt ở cấu hình thực sự có tác dụng. Nếu dùng riêng `{{JDBC_URL}}`, vẫn cần binding `{{DATABASE_NAME}}` thật ở cấu hình ứng dụng phù hợp; không thêm comment giả để qua validation. Không tự đặt tên property như `database.url` nếu WAR không đọc property đó. Xác định rõ datasource file/context trước buổi demo.

Template được render tới run rồi copy vào `runtime/server/conf`. WAR vẫn nằm trong catalog và được copy vào `runtime/server/webapps/contrack.war`. App context là `/contrack`; cần Java/Tomcat tương thích WAR đang có. Image opt-in cài `default-jre-headless`; kiểm tra version trước buổi demo và chọn runtime tương thích nếu WAR yêu cầu Java khác.

## 7. Chuẩn bị catalog cho một version chạy được

Ví dụ demo `ConTrack 5.2.0 HotFix #8383`, dùng các ID của catalog mẫu có sẵn. Nếu version thật khác, sửa đồng bộ WAR/baseline/bundle schema và IDs.

Tạo thư mục:

```bash
mkdir -p "$CT_ENV_ROOT/catalog/wars/5.2.0/hf-8383-001" \
  "$CT_ENV_ROOT/catalog/databases/schema-5.2.0/standard-v1" \
  "$CT_ENV_ROOT/catalog/repositories/svn/standard-v1"
```

Tạo bốn file manifest sau bằng editor. Có thể lấy nội dung từ `deploy/contrack-environments/catalog/`. Chỉ tạo file chưa có; giữ artifact/catalog cũ để bảo toàn lịch sử.

**`catalog/wars/5.2.0/hf-8383-001/manifest.yaml`:**

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

Copy WAR thật tới `catalog/wars/5.2.0/hf-8383-001/contrack.war`. Nếu file build đó đã có, tạo build ID mới thay vì overwrite.

**`catalog/databases/schema-5.2.0/standard-v1/manifest.yaml`:**

```yaml
database_id: DB-520-STANDARD-V1
schema_version: 5.2.0
profile_type: standard
artifact:
  file: baseline.dump
status: available
```

Đặt dump **custom format** của DB demo schema 5.2.0 tại `catalog/databases/schema-5.2.0/standard-v1/baseline.dump`. Dump phải có dữ liệu demo/repository mapping phù hợp. Nếu cần tạo dump bằng PostgreSQL client trên Linux host:

```bash
# Hỏi mật khẩu tương tác; thay host, user và DB nguồn.
# Chọn file output mới, không ghi đè baseline đã dùng.
pg_dump -h DB_HOST_THUC_TE -p 5432 -U SOURCE_DB_USER -W \
  -Fc --no-owner --no-privileges \
  --file="$CT_ENV_ROOT/catalog/databases/schema-5.2.0/standard-v1/baseline.dump" \
  SOURCE_DB_NAME
```

Nếu dump từ container DB, có thể dùng `docker exec ... pg_dump -Fc ... > baseline.dump` ở host; không dùng `-t` khi xuất binary dump. Baseline cần restore được bằng role cấu hình, với extensions/prerequisite được DBA chuẩn bị.

**`catalog/repositories/svn/standard-v1/manifest.yaml`:**

```yaml
repository_id: SVN-STANDARD-V1
display_name: SVN Standard
repository_type: svn
url: svn://SVN_HOST_THUC_TE/REPOSITORY_THUC_TE
status: available
```

Thay URL thật, không nhúng password/token. Nếu dùng SVN qua HTTPS, dùng URL HTTPS thực tế. Git dùng `repository_type: git` và URL tương ứng. MVP kiểm tra TCP reachability và render URL; không tạo/copy repository hay sửa Docker Git/SVN.

**`catalog/bundles/5.2.0-hf8383.yaml`:**

```yaml
bundle_id: CT-5.2.0-HF8383
display_name: "ConTrack 5.2.0 HotFix #8383"
application:
  war_id: WAR-5.2.0-HF8383-001
database:
  schema_version: 5.2.0
  default_database_id: DB-520-STANDARD-V1
repository:
  default_repository_id: SVN-STANDARD-V1
status: available
```

Đủ các file này thì dropdown mới có bundle available. Chỉ tạo các thư mục trống chưa đủ. Có thể bổ sung checksum `artifact.sha256` bằng kết quả `sha256sum` của WAR/baseline.

## 8. Build và khởi động backend hỗ trợ demo

Chạy từ `contrack_tool` trong shell đã export các biến ở bước 2:

```bash
# Các file bind-mount phải tồn tại trước khi recreate container.
test -f "$CT_ENV_CONFIG"
test -f "$CT_PGPASS_FILE"
test -f "$CT_TOMCAT_CONF/server.xml"
test -f "$CT_ENV_ROOT/catalog/wars/5.2.0/hf-8383-001/contrack.war"
test -f "$CT_ENV_ROOT/catalog/databases/schema-5.2.0/standard-v1/baseline.dump"

# Kiểm tra Compose resolve được biến/path; --quiet không in secrets của Compose gốc.
docker compose -f docker-compose.yml \
  -f deploy/contrack-environments/compose.override.yaml config --quiet

# Image backend gốc có code mới và web/local-server assets.
docker build -f backend/Dockerfile -t contrack-tool-backend:local .

# Image mở rộng bổ sung Java và PostgreSQL client.
docker build -f deploy/contrack-environments/Dockerfile \
  -t contrack-tool-backend:environments .

# Chạy dependency nội bộ của tool nếu chưa chạy. Các Git/SVN/DB target dùng cấu hình riêng đã chuẩn bị.
docker compose up -d postgres redis

# Chỉ recreate backend; không rebuild nhầm thành image backend gốc thiếu Java/PG CLI.
docker compose -f docker-compose.yml \
  -f deploy/contrack-environments/compose.override.yaml \
  up -d --no-build --no-deps --force-recreate backend

# Build/khởi động frontend đã có menu mới.
docker compose up -d --build --no-deps frontend
```

Mỗi lần khởi động/recreate backend cho môi trường này, dùng **cả hai `-f`**; khi chỉ chạy Compose gốc, mount/config/image opt-in có thể không còn trong cấu hình mong muốn. Build lại hai image trên khi cập nhật backend code; không dùng lệnh build của Compose gộp để vô tình thay image opt-in bằng Dockerfile gốc.

Trong phương án này backend mount root RW nên có thể tạo runtime/runs. Image hiện tại chạy root; nếu đã tùy chỉnh UID thì cấp quyền đọc catalog/config và ghi runtime/runs cho UID đó. Không dùng `chmod -R 777`.

## 9. Kiểm tra trước khi mời user demo

```bash
# Java và PostgreSQL CLI phải hiện version.
docker compose -f docker-compose.yml \
  -f deploy/contrack-environments/compose.override.yaml \
  exec backend sh -c 'java -version; createdb --version; pg_restore --version; psql --version'

# Chỉ in trạng thái bật và đường dẫn, không in password/config đầy đủ.
docker compose -f docker-compose.yml \
  -f deploy/contrack-environments/compose.override.yaml \
  exec backend python -c 'from app.modules.contrack_environments.config import load_settings; s=load_settings(); print("enabled:", s.enabled); print("root:", s.root); print("tomcat:", s.tomcat_home)'

# Kiểm tra catalog thực tế từ bên trong container.
docker compose -f docker-compose.yml \
  -f deploy/contrack-environments/compose.override.yaml \
  exec backend python -c 'from app.modules.contrack_environments.config import load_settings; from app.modules.contrack_environments.catalog import VersionCatalogService; c=VersionCatalogService(load_settings()).list_available_contrack_versions(); print([(v["displayName"],v["status"],v["error"]) for v in c["versions"]])'

# Kết nối PG bằng cấu hình module, không in mật khẩu.
docker compose -f docker-compose.yml \
  -f deploy/contrack-environments/compose.override.yaml \
  exec backend python -c 'from app.modules.contrack_environments.config import load_settings; from app.modules.contrack_environments.adapters import LinuxEnvironmentAdapter; a=LinuxEnvironmentAdapter(load_settings()); print(a._command([a._tool("psql"), "--no-password", "--no-psqlrc", "--tuples-only", "--no-align", "--dbname=postgres", "--command=SELECT 1"],env=a._pg_env()))'
```

Kết quả mong đợi: `enabled: True`, root `/srv/contrack-env`, Tomcat `/opt/tomcat`, bundle `available`/error `None`, kiểm tra DB trả `1`. Lệnh cuối chỉ kiểm tra kết nối, chưa chứng minh restore/schema đúng; các bước này được kiểm tra khi Prepare Environment.

Kiểm tra thêm: port host 18080 còn trống; endpoint app thật được chọn trả 200; Tomcat binaries có thể đọc/thực thi trong container. `Validate selection` cũng kiểm tra không có process lạ chiếm app port nội bộ. Không start Tomcat thủ công vào managed base trước buổi demo vì module cần PID do chính nó quản lý.

## 10. Kịch bản user demo lần đầu

1. Mở `http://SERVER_IP:8888`, đăng nhập bằng admin hoặc role đã được bật quyền **ConTrack Environments**.
2. Vào menu **ConTrack Environments**, bấm **Refresh** nếu vừa thêm catalog.
3. Chọn **ConTrack 5.2.0 HotFix #8383**; DB `standard — DB-520-STANDARD-V1` và repository `SVN Standard` tự điền.
4. Bấm **Validate selection**. Mong đợi thông báo `Compatible: ...`; lỗi cấu hình ở đây cần xử lý trước khi trình diễn prepare.
5. Bấm **Prepare Environment** một lần. Quan sát form khóa và run xuất hiện trong **Run history**.
6. Trong run detail, theo dõi các bước: validate → runtime config → database create/restore/schema → repository prepare → server stop → WAR deploy → server start → health check → runtime state.
7. Khi run thành **READY**, phần Current environment hiển thị **RUNNING**, đúng WAR/baseline/repository và working DB mới tên `ct_520_...`.
8. Mở ứng dụng ConTrack tại `http://SERVER_IP:18080/contrack/` (hoặc app path health thực tế). Port 18080 là ConTrack demo; 8888 là tool; 8009 là API tool.
9. Mở **View run**, chỉ ra request/recipe/step/log đã được lưu để truy vết. Current environment hiển thị kết quả health check gần nhất, không phải monitor live.

`Validate selection` kiểm tra catalog và preflight cấu hình, **không tạo DB, không kiểm chứng JDBC credential hay restore thành công**. Chuẩn bị một lần chạy thử hoàn chỉnh trước buổi demo để xác nhận READY với WAR/baseline thật.

## 11. Demo switch hai version

Sau khi version đầu READY, thêm WAR release thứ hai dưới build ID mới và manifest riêng, ví dụ `WAR-5.2.0-RELEASE-001`. Tạo bundle `CT-5.2.0-RELEASE` trỏ WAR đó, dùng lại `DB-520-STANDARD-V1` và `SVN-STANDARD-V1`. Refresh, chọn release rồi Prepare. Mong đợi DB mới tên khác, WAR thay đổi và run mới READY.

Để demo 5.2.0 → 5.1.0, cần thêm **WAR 5.1.0 + baseline có schema thật 5.1.0 + bundle schema 5.1.0**. Dùng cùng schema-version SELECT được cấu hình cho cả hai baseline. Nếu hai version dùng cách đọc schema khác nhau, cấu hình query thống nhất phù hợp hoặc điều chỉnh thiết kế trước khi demo. Module luôn restore baseline 5.1.0 vào DB mới, giữ DB 5.2.0 cũ; không có downgrade.

Muốn demo chọn Database Profile khác: thêm baseline `large-v1` cùng schema, với ID mới `DB-520-LARGE-V1`, `profile_type: large`; UI tự liệt kê ở bundle schema 5.2.0. Không chỉ nhân bản manifest đổi tên mà bỏ qua dữ liệu baseline thật.

## 12. Lỗi thường gặp theo đúng setup này

| Thông báo/triệu chứng | Kiểm tra và cách xử lý |
|---|---|
| Administrator must configure and enable | Backend có dùng override không; biến `CONTRACK_ENV_CONFIG` trong container; file mount đúng; YAML có `enabled: true` |
| Mount báo file/directory không khớp | File YAML/pgpass phải có trên host trước khi Compose chạy; kiểm tra bằng `test -f` |
| Catalog empty | `CT_ENV_ROOT` đang trỏ đúng cấp `contrack-env` hay thừa/thiếu một cấp |
| Required PostgreSQL tool missing | Backend phải dùng image `contrack-tool-backend:environments`, đã build image mở rộng |
| Schema query required | Điền SELECT thật vào YAML; giá trị rỗng không đủ |
| Template must bind DATABASE_NAME/REPOSITORY_URL | Sửa đúng application configuration được WAR đọc |
| External tool failed ở restore | PG client/version, role permissions, pgpass mode 0600/host/user, dump custom format/extensions |
| Repository unreachable | URL/port/network Git/SVN từ container backend |
| Unmanaged server | Port nội bộ 8080 đang thuộc process khác; xác định process trước khi dùng port cho demo |
| Server start/health failed | Xem Tomcat logs; Java/Tomcat/WAR compatibility; datasource credentials; URL trả 200 không redirect |
| Run FAILED | Xem failed step/log; lỗi trước stop giữ app cũ, lỗi sau stop cần prepare lại sau khi sửa |

Xem log sau lỗi:

```bash
# API log, lệnh này vẫn dùng đúng override.
docker compose -f docker-compose.yml \
  -f deploy/contrack-environments/compose.override.yaml logs --tail=100 backend

# Log ứng dụng trên host; không đưa nội dung có secret lên màn demo.
tail -n 100 "$CT_ENV_ROOT/runtime/server/logs/catalina.out"

# Liệt kê các run đã có, mỗi run giữ request.yaml / recipe.yaml / state.yaml / run.log.
ls -1 "$CT_ENV_ROOT/runs"
```

DB/run được giữ lại sau mỗi lần prepare, kể cả thất bại. Chuẩn bị dung lượng cho số lần demo; quản trị viên dọn các DB/run không còn dùng sau buổi demo. Không xóa `runtime/environment.lock` khi đang chuẩn bị và không sửa trực tiếp baseline.

## 13. Nếu backend chạy trực tiếp trên Linux host

Bỏ phần image/mount Docker. Cài Java, Tomcat và PostgreSQL CLI trên cùng Linux host với backend. Trong YAML, đổi sang các **host paths**:

```yaml
root: /DUONG_DAN_THUC_TE/Contrack-Recreate/contrack-env
tomcat_home: /DUONG_DAN_THUC_TE/apache-tomcat
config_templates: /DUONG_DAN_THUC_TE/Contrack-Recreate/tomcat-conf
pg_passfile: /DUONG_DAN_THUC_TE/Contrack-Recreate/secrets/runtime.pgpass
```

Truyền `CONTRACK_ENV_CONFIG` vào process/service chạy FastAPI. Với cách chạy tay, từ thư mục `backend`:

```bash
export CONTRACK_ENV_CONFIG="$CT_ENV_CONFIG"
uvicorn app.main:app --host 0.0.0.0 --port 8009
```

Nếu backend do systemd quản lý, đặt biến này trong cấu hình service hiện có rồi restart service. Loader của module đọc biến môi trường process; chỉ thêm tên biến vào file mẫu hoặc `.env` mà launcher không load thì chưa đủ. App demo lúc này chạy trực tiếp port `server_port` trên host, không có mapping 18080:8080 của Docker.
