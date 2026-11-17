# Quản lý ConTrack Environments

## Kiến trúc và phạm vi

Menu **ConTrack Environments**, URL `/contrack-environments`, là chức năng độc lập với **Versions**, Build Source, Fix EOL và các tích hợp hiện có. Vue gọi module FastAPI `app/modules/contrack_environments`. Module dùng catalog YAML, PostgreSQL CLI và một Tomcat `CATALINA_BASE` riêng trên Linux. Không thay đổi framework, schema DB của tool hay Node local server.

Người dùng chỉ gửi bundle ID, database profile ID và repository profile ID. Module ánh xạ chúng thành WAR + database baseline + repository + application configuration. Mỗi lần chuẩn bị luôn tạo working DB mới; chuyển từ 5.2.0 về 5.1.0 cũng restore baseline 5.1.0 vào DB mới, không downgrade DB hiện tại. Baseline và WAR trong catalog chỉ được đọc.

MVP repository là mapping tới Git/SVN server Docker **đã có**, kiểm tra kết nối TCP và đưa URL vào application config. Module không tạo repository, sửa dữ liệu repository, thay container hay mount Docker socket. Dữ liệu trong baseline phải phù hợp với repository profile do quản trị viên chuẩn bị.

## Điều kiện trước khi dùng

Tính năng mặc định **disabled**. UI vẫn hiện cho người có quyền và giải thích cấu hình còn thiếu. Không tạo DB hay dừng server chỉ vì mở trang.

Máy/container chạy backend cần:

- Linux, Python dependencies trong `backend/requirements.txt`.
- Java và Tomcat tương thích WAR thực tế; Tomcat chưa có trong source này.
- `createdb`, `pg_restore`, `psql` có version tương thích PostgreSQL baseline/server.
- Tài khoản PostgreSQL riêng có quyền tạo DB và restore; không dùng database metadata `contrack` của tool làm working DB.
- Catalog có WAR và dump thật, endpoint Git/SVN có thể truy cập.
- Thư mục cấu hình Tomcat hoàn chỉnh, đúng ứng dụng và schema-version SELECT thật.

Đặt biến môi trường `CONTRACK_ENV_CONFIG=/etc/contrack/environment.yaml` khi chạy backend. Copy `deploy/contrack-environments/config.example.yaml` ra vị trí này, chỉnh cấu hình rồi đặt `enabled: true`. Restart backend sau khi thay cấu hình môi trường. File YAML được đọc lại mỗi request, vì vậy không thay root/cấu hình giữa một lần prepare.

`CONTRACK_ENV_ROOT` ghi đè root trong YAML; `CONTRACK_ENV_PG_PASSWORD` ghi đè password. Có thể dùng `.pgpass` qua `pg_passfile` (chmod 0600). Không đưa password/token/private key vào catalog hay URL repository. Config lỗi được báo bằng thông báo chung, không trả nội dung bí mật từ validation.

Các đường dẫn catalog/runtime/runs/lock có thể đổi bằng YAML; đều phải là đường dẫn tương đối trong root và không chồng lấn. `tomcat_home`, `config_templates`, `pg_bin`, `pg_passfile` là cấu hình riêng do quản trị viên cung cấp, không nhận qua UI/API. Root phải là filesystem Linux local dùng chung giữa các process backend; không dùng NFS hoặc root khác nhau cho từng replica.

## Cấu trúc thư mục

```text
/srv/contrack-env/
├── catalog/
│   ├── wars/<version>/<build-id>/{contrack.war,manifest.yaml}
│   ├── databases/schema-<version>/<profile>/{baseline.dump,manifest.yaml}
│   ├── repositories/{git,svn}/<profile>/manifest.yaml
│   └── bundles/<bundle>.yaml
├── runtime/
│   ├── server/{webapps,conf,logs,temp,work,state.yaml,tomcat.pid}
│   ├── databases/current.yaml
│   ├── repositories/current.yaml
│   ├── current/{version.yaml,run-id}
│   └── environment.lock
└── runs/<UTC timestamp>-<random ID>/
    ├── request.yaml
    ├── recipe.yaml
    ├── state.yaml
    ├── run.log
    ├── staged-conf/
    ├── contrack.war
    └── repository.yaml
```

Các file run và runtime state được ghi atomic bằng temporary file + replace. `version.yaml` là trạng thái môi trường chính; các file con hỗ trợ tra cứu. Thời gian lưu UTC, giao diện hiển thị theo timezone trình duyệt. Không tự xóa run thất bại hay working DB để giữ dữ liệu chẩn đoán. Quản trị viên chịu trách nhiệm retention và dọn DB/run cũ sau khi xác định không sử dụng.

## Thêm WAR

Copy cấu trúc mẫu trong `deploy/contrack-environments/catalog/` vào root đã cấu hình, rồi cung cấp artifact thật. Thư mục mẫu trong repository **không chứa** WAR/dump và không dùng được để chạy ngay.

Tạo thư mục build mới, ví dụ `catalog/wars/5.2.0/hf-8383-002/`; thêm `contrack.war` và `manifest.yaml`:

```yaml
war_id: WAR-5.2.0-HF8383-002
display_version: 5.2.0
build_type: hotfix
build_id: hf-8383-002
artifact:
  file: contrack.war
  # sha256: giá trị sha256sum của artifact, khuyến nghị khai báo
compatibility:
  database_schema: 5.2.0
status: available
```

Không ghi đè build cũ. Không suy đoán version từ tên WAR. Khuyến nghị catalog chỉ quản trị viên có quyền ghi; process backend chỉ cần đọc. Artifact path phải nằm trong thư mục manifest; từ chối traversal, absolute path và symlink trỏ ra ngoài. Nếu khai báo SHA-256, checksum phải khớp. Recipe luôn lưu checksum WAR/baseline tại thời điểm nhận prepare và kiểm tra lại trước khi chạy.

## Thêm database baseline

Tạo baseline bằng `pg_dump -Fc` (custom format), không copy physical data directory và không dùng plain SQL dump với adapter này. Database mẫu phải chứa schema-version metadata thật mà ứng dụng sử dụng.

```yaml
database_id: DB-520-LARGE-V1
schema_version: 5.2.0
profile_type: large
artifact:
  file: baseline.dump
status: available
```

Lưu trong `catalog/databases/schema-5.2.0/large-v1/`. Schema trong WAR, bundle và baseline phải bằng nhau. UI chỉ hiển thị DB profile có schema tương ứng; API kiểm tra lại độc lập. Các profile cùng schema có thể dùng chung giữa release/hotfix.

Module gọi `createdb --template=template0` rồi `pg_restore --single-transaction --exit-on-error --no-owner --no-privileges`. Tên DB dạng `ct_520_<UTC timestamp>_<random suffix>`, dưới 63 ký tự. Không tái sử dụng DB cũ, không drop DB tự động, không sửa baseline. Dump phải restore được với role đã cấu hình; extensions/ownership đặc biệt cần chuẩn bị trước.

`schema_version_query` là SELECT chỉ quản trị viên cấu hình, trả **đúng một giá trị** như `5.2.0`, không phải hằng số giả định theo manifest. Repository này không chứa schema của ConTrack Java nên không thể cung cấp tên bảng đúng. Query chạy qua `psql --no-psqlrc` với read-only transaction và statement timeout; kiểm tra ngay sau restore và sau khi server lên.

## Thêm repository profile

```yaml
repository_id: SVN-STANDARD-V1
display_name: SVN Standard
repository_type: svn
url: svn://svn.example.internal/contrack
status: available
```

Lưu trong `catalog/repositories/svn/standard-v1/manifest.yaml`. Git dùng `repository_type: git` và URL tương ứng. Các scheme hỗ trợ: `http`, `https`, `svn`, `svn+ssh`, `git`, `ssh`; không nhúng credentials trong URL. Authentication của ConTrack tới repository được cấu hình trong template bằng cơ chế ứng dụng hiện có. TCP check xác nhận server reachable, không xác nhận quyền đọc repository hoặc tính tương thích dữ liệu.

## Tạo version bundle

```yaml
bundle_id: CT-5.2.0-HF8383
display_name: "ConTrack 5.2.0 HotFix #8383"
application:
  war_id: WAR-5.2.0-HF8383-002
database:
  schema_version: 5.2.0
  default_database_id: DB-520-LARGE-V1
repository:
  default_repository_id: SVN-STANDARD-V1
status: available
```

Lưu `catalog/bundles/5.2.0-hf8383.yaml`. IDs phải duy nhất, chỉ dùng chữ, số, `.`, `_`, `-`, không có `..`. Manifest có field không hỗ trợ hoặc ID trùng bị từ chối. Không có command/script trong manifest. Bundle thiếu tài nguyên hoặc schema mismatch được hiển thị unavailable; không thể prepare.

## Cấu hình application/Tomcat

`config_templates` trỏ tới bản sao đầy đủ thư mục `conf` của Tomcat dành riêng cho môi trường này, gồm `server.xml`, cấu hình datasource/application thực tế và các file Tomcat cần dùng. Module render sang run trước khi chạm server hiện tại, rồi copy vào `runtime/server/conf` sau khi stop thành công. Tomcat chạy bằng `startup.sh`/`shutdown.sh` từ `tomcat_home`, với `CATALINA_BASE` riêng và `CATALINA_PID` riêng. Không điều khiển Tomcat dùng chung hay service systemd bên ngoài.

Placeholder hỗ trợ:

| Placeholder | Giá trị |
|---|---|
| `{{DATABASE_NAME}}` | Working database mới |
| `{{DATABASE_HOST}}`, `{{DATABASE_PORT}}`, `{{DATABASE_USER}}` | Cấu hình PostgreSQL target |
| `{{JDBC_URL}}` | JDBC URL tới working database |
| `{{REPOSITORY_URL}}` | URL của profile đã chọn |
| `{{SERVER_PORT}}` | Port Tomcat đã cấu hình |

Template phải có `{{DATABASE_NAME}}` và `{{REPOSITORY_URL}}`. Đặt chúng vào đúng cấu hình mà ConTrack WAR thật sử dụng; không chỉ thêm comment để qua kiểm tra. `server.xml` phải có Connector port tương ứng. Không còn placeholder chưa resolve. XML values được escape. Password datasource/repository dùng cơ chế secret hiện có của ứng dụng trong template do admin quản lý; module không tự suy đoán tên property/file của ConTrack. File render có chmod 0600; không đưa nội dung config vào API hoặc run log.

WAR được copy vào `runtime/server/webapps/contrack.war`, context path `/contrack`. Chỉ xóa WAR/exploded directory `contrack` trong managed base khi switch. `tomcat_home` có thể mount read-only. `server_host`/health URL phải trỏ cùng host và port của managed Tomcat. Chọn endpoint ứng dụng trả 200 trực tiếp, không redirect tới login/site khác.

## Docker tùy chọn

Compose và Dockerfile cũ được giữ nguyên. Để chạy managed Tomcat trong cùng container backend, build một image mở rộng riêng từ repo root:

```bash
docker build -f backend/Dockerfile -t contrack-tool-backend:local .
docker build -f deploy/contrack-environments/Dockerfile -t contrack-tool-backend:environments .
docker compose -f docker-compose.yml -f deploy/contrack-environments/compose.override.yaml up -d --no-build backend
```

Chuẩn bị trước tất cả file/thư mục mount trong override; xem các biến `CT_ENV_ROOT`, `CT_ENV_CONFIG`, `CT_TOMCAT_HOME`, `CT_TOMCAT_CONF`, `CT_PGPASS_FILE`, `CT_APPLICATION_PORT`. Trong container dùng đường dẫn `/srv/contrack-env`, `/opt/tomcat`, `/etc/contrack/tomcat-conf`, `/run/secrets/contrack-runtime.pgpass` tương ứng. Java/PG client được cài trong image opt-in; chọn version PG client khác nếu baseline yêu cầu. Giữ app port nội bộ 8080 hoặc điều chỉnh cả config và port mapping.

Backend cần kết nối được target PostgreSQL/repository qua Docker network hoặc hostname nội bộ thực tế. Không dùng `127.0.0.1` để trỏ tới một container DB khác. Worker hiện có không chạy chức năng mới, không cần các mount này. Khi container backend restart, Tomcat con cũng dừng; UI lưu last successful health check, không giám sát liên tục application. Dùng Prepare Environment để khởi tạo lại. Các service của Compose gốc không bị thay đổi.

## Quyền và cách switch trên UI

Admin có quyền mặc định. Với dev/qa/custom role hiện có, admin vào quản lý roles, bật **ConTrack Environments** (`contrack_environments`) rồi người dùng refresh phiên/UI. Quyền này cho phép đọc catalog/history và switch môi trường dùng chung.

1. Mở **ConTrack Environments**.
2. Chọn version bundle; database/repository mặc định tự điền.
3. Có thể chọn DB profile cùng schema hoặc repository profile khác đã có trong catalog.
4. **Validate selection** kiểm tra mapping, artifact và cấu hình Linux mà không tạo DB/dừng server.
5. Bấm **Prepare Environment**. Module kiểm tra lại dưới khóa độc quyền, tạo run, render config, tạo/restore DB, kiểm tra schema/repository, dừng server managed hiện tại, deploy WAR và start.
6. Xem progress/log và trạng thái **READY**. Current environment chỉ **RUNNING** sau khi toàn bộ health checks thành công.

Không cần Node local hay Redmine API key để mở chức năng này. Không yêu cầu chọn WAR hoặc đường dẫn thủ công trên UI. Không có dữ liệu demo được hiển thị như môi trường thật.

## API

Tất cả endpoint dưới `/api/contrack-environments` yêu cầu cookie đăng nhập và quyền menu mới.

| Method/path | Mục đích |
|---|---|
| `GET /catalog` | Versions, DB/repository profiles và lý do bundle invalid |
| `GET /current` | Runtime state và switch lock |
| `POST /validate` | Kiểm tra selection và Linux configuration |
| `POST /prepare` | Nhận prepare, trả 202 + run ID, chạy background |
| `GET /runs?limit=30&offset=0` | Lịch sử phân trang |
| `GET /runs/{run_id}` | Request, recipe, state và 64 KiB cuối run log |

Body validate/prepare:

```json
{
  "bundle_id": "CT-5.2.0-HF8383",
  "database_profile_id": "DB-520-LARGE-V1",
  "repository_profile_id": "SVN-STANDARD-V1"
}
```

Chỉ `bundle_id` bắt buộc; bỏ profile để dùng default. Không nhận shell command, DB command hoặc file path. Đây là web tool nên không thêm framework/CLI mới; API sử dụng lại được từ script với authenticated session.

## Health check, failures và history

Sau start kiểm tra: PID thuộc đúng managed Tomcat, app port reachable, WAR checksum đúng, kết nối DB thành công, schema SELECT khớp, application HTTP 200 trực tiếp. UI ghi **last successful health check**, không khẳng định giám sát live. API không được phép READY chỉ vì chạy xong startup script.

`request.yaml` lưu selection/user request; `recipe.yaml` lưu bundle/WAR/baseline/repository thực tế, working DB và hashes; `state.yaml` lưu user, từng bước, failed step, mã lỗi và thời gian; `run.log` giữ tiến trình. Không lưu stdout/stderr tool ngoài vì có thể chứa secrets. Tomcat diagnostic logs ở `runtime/server/logs`, chỉ quản trị viên truy cập trên host.

Lock OS tại `runtime/environment.lock` được giữ từ trước khi queue đến cuối run; process khác nhận 409. Lock tự giải phóng khi process chết, không unlink lock file để tránh race. Không xóa file lock thủ công khi đang chạy. Run đang QUEUED/PREPARING mà process đã chết được hiển thị INTERRUPTED, lưu lại khi bắt đầu run mới. Trạng thái SWITCHING bị gián đoạn hiển thị UNKNOWN.

Lỗi trước bước stop giữ nguyên môi trường đang chạy. Lỗi sau stop không rollback tự động; candidate đã start được stop để không chạy môi trường chưa health-check thành công. Nếu không xác định được server đã dừng hay chưa, trạng thái UNKNOWN. Giữ DB mới và run failed để điều tra; prepare lại để tạo môi trường mới. Không tiếp tục các bước deployment tiếp theo sau lỗi.

## Troubleshooting

| Triệu chứng | Kiểm tra |
|---|---|
| Menu không hiện | Quyền role `contrack_environments`; refresh session |
| Feature disabled | `CONTRACK_ENV_CONFIG`, file YAML, `enabled` |
| Catalog trống | Root/mount/path của manifest; catalog mẫu không có binary |
| Invalid manifest | IDs trùng, field lạ, path traversal, schema YAML |
| Schema mismatch | WAR/bundle/baseline metadata và query thật sau restore |
| External tool failed | PG binaries/version, `.pgpass` mode, role CREATEDB/restore, baseline custom format |
| Template config | Full Tomcat conf, placeholders, Connector port, app datasource config |
| Repository unreachable | DNS/network/port của Git/SVN Docker server từ backend |
| Unmanaged server | Port đã bị process khác dùng; module sẽ không dừng process đó |
| Server start/health failed | Java/Tomcat/WAR compatibility, Tomcat logs, direct health URL, actual DB schema |
| Storage unavailable | Quyền ghi runtime/runs, disk space, symlink ngoài managed root |
| Interrupted/UNKNOWN | Backend/container restart; kiểm tra PID/log và Prepare Environment lại |

## Kiểm thử

```bash
cd backend
python -m unittest discover -s tests -p 'test_contrack_environments.py' -v
cd ..
npm run build
node --test local-server/tests/*.test.cjs frontend/tests/*.test.cjs
```

Backend tests dùng adapter giả có database model để kiểm tra mapping, failure-stop, lock liên process, API permissions và chuỗi 5.1.0 → 5.2.0 → hotfix → 5.1.0. Chúng không thay thế integration test với WAR, PostgreSQL, Tomcat và repository thật. Chưa được xem READY trên UI là đã được kiểm chứng ngoài môi trường test nếu chưa cấu hình/chạy hạ tầng thật.

Integration test thật được cung cấp trong `backend/tests/test_contrack_environments_live.py`, mặc định skip. Chạy trên Linux bằng cấu hình riêng dành cho test (test này thực sự switch server và tạo bốn database, giữ lại DB/run):

```bash
export CT_ENV_LIVE_ALLOW_PREPARE=1
export CT_ENV_LIVE_CONFIG=/etc/contrack/environment-test.yaml
export CT_ENV_LIVE_510=CT-5.1.0-RELEASE
export CT_ENV_LIVE_520=CT-5.2.0-RELEASE
export CT_ENV_LIVE_HOTFIX=CT-5.2.0-HF8383
cd backend
python -m unittest discover -s tests -p 'test_contrack_environments_live.py' -v
```

Không bật cờ này trong test mặc định/CI có môi trường dùng chung.
