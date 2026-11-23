# Demo switch WAR và PostgreSQL với môi trường hiện tại

Giữ PostgreSQL Docker hiện có, tạo working DB riêng cho từng version. DB preparation và thay JDBC/start-stop bên dưới là thao tác quản trị **thủ công**. UI Deploy WAR hiện chỉ copy WAR và ghi lịch sử copy; chưa tự chạy các bước DB này.

## 1. Giá trị demo và điều kiện

| Thành phần | Giá trị demo |
|---|---|
| Source tool | `/home/vsvndev/contrack_tool` |
| Root tài nguyên | `/home/vsvndev/Contrack-Recreate/contrack-env` |
| Tomcat base | `<root>/runtime/server` |
| PostgreSQL service của Compose tool | `postgres` |
| Role demo | `contrack` |
| PostgreSQL host port | `5439` (container port `5432`) |
| Working DB 5.2.0 | `ct_520_standard` |
| Working DB 5.3.0 | `ct_530_standard` |
| JDBC file minh họa | `<Tomcat base>/conf/Catalina/localhost/app.xml` |

Service/role/port trên lấy từ Compose trong source. Chúng không chứng minh DB ConTrack của server thực tế nằm trong container này. Nếu DB ứng dụng ở PostgreSQL container khác, chọn đúng container đó và role tương ứng trước khi chạy các lệnh DB. Không dùng DB metadata tên `contrack` của tool làm baseline ứng dụng.

File JDBC minh họa chỉ dùng nếu WAR thực sự sử dụng datasource đó. Không tạo `app.xml` rồi giả định ứng dụng sẽ tự đọc. Nếu cấu hình DB đang nằm ở file properties ngoài WAR hoặc biến môi trường/service, sửa đúng nguồn cấu hình hiện có đó. Cấu hình nằm trong thư mục exploded `webapps/app` có thể bị thay khi redeploy WAR; cần đưa cấu hình ra ngoài bằng cơ chế ứng dụng hỗ trợ trước khi làm luồng này.

Hai baseline phải là dump thật có schema/data phù hợp 5.2.0 và 5.3.0. Thêm WAR 5.3.0 không tự sinh được baseline 5.3.0. Nếu chưa có baseline 5.3.0, cần chuẩn bị bằng quy trình tạo DB/migration chính thức của ConTrack trước khi chạy phần 5.3.0 dưới đây.

## 2. Xác định PostgreSQL container

Chạy trên Linux host, trong cùng shell:

```bash
cd /home/vsvndev/contrack_tool
export CT_ENV_ROOT=/home/vsvndev/Contrack-Recreate/contrack-env
export CT_TOMCAT="$CT_ENV_ROOT/runtime/server"
export CT_PG_CONTAINER="$(docker compose ps -q postgres)"
export CT_PG_ROLE=contrack

test -n "$CT_PG_CONTAINER"
docker ps --format 'table {{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Ports}}'
docker exec "$CT_PG_CONTAINER" psql -U "$CT_PG_ROLE" -d postgres -c '\l'
docker port "$CT_PG_CONTAINER" 5432
```

Mong đợi: container PostgreSQL chạy, danh sách database đọc được và port mapping đúng. Nếu source DB ConTrack không nằm ở đây, đặt lại `CT_PG_CONTAINER` thành ID/tên container đúng và `CT_PG_ROLE` thành role có quyền cần thiết.

Các lệnh `docker exec ... -U` giả định kết nối nội bộ container đã được xác thực theo cấu hình hiện tại. Nếu yêu cầu mật khẩu, cấu hình xác thực/pgpass phù hợp; không truyền mật khẩu vào câu lệnh hoặc gửi mật khẩu khi chia sẻ log.

## 3. Chuẩn bị baseline

```text
catalog/databases/
├── schema-5.2.0/standard-v1/baseline.dump
└── schema-5.3.0/standard-v1/baseline.dump
```

Tạo thư mục:

```bash
mkdir -p "$CT_ENV_ROOT/catalog/databases/schema-5.2.0/standard-v1"
mkdir -p "$CT_ENV_ROOT/catalog/databases/schema-5.3.0/standard-v1"
```

Nếu đã có custom-format dumps tương ứng, copy vào đúng thư mục. Giữ baseline cũ, tạo profile/build mới khi thay dữ liệu chuẩn.

Nếu tạo baseline 5.2.0 từ DB ứng dụng đang có, xác nhận DB nguồn thực sự có schema 5.2.0 rồi chạy:

```bash
read -r -p 'Tên DB nguồn ConTrack schema 5.2.0: ' CT_SOURCE_DB
export CT_BASELINE_520="$CT_ENV_ROOT/catalog/databases/schema-5.2.0/standard-v1/baseline.dump"

# Bỏ qua khối dump nếu baseline chuẩn này đã tồn tại; không ghi đè.
test -n "$CT_SOURCE_DB" &&
test "$CT_SOURCE_DB" != contrack &&
test ! -e "$CT_BASELINE_520" &&
docker exec "$CT_PG_CONTAINER" pg_dump \
  -U "$CT_PG_ROLE" -Fc --no-owner --no-privileges -- "$CT_SOURCE_DB" \
  > "${CT_BASELINE_520}.tmp" &&
docker exec -i "$CT_PG_CONTAINER" pg_restore --list \
  < "${CT_BASELINE_520}.tmp" > /dev/null &&
mv -n -- "${CT_BASELINE_520}.tmp" "$CT_BASELINE_520"
```

`pg_dump -Fc` tạo archive dùng với `pg_restore`; `pg_dump` tạo snapshot nhất quán của một database. Việc này không tự xác minh schema là 5.2.0. [PostgreSQL pg_dump](https://www.postgresql.org/docs/16/app-pgdump.html).

Không dùng `docker exec -t` khi xuất/nhập binary dump. Chuẩn bị baseline 5.3.0 từ DB nguồn 5.3.0 tương tự hoặc dùng backup chuẩn có sẵn. Không nhân bản dump 5.2.0 rồi chỉ đổi nhãn thành 5.3.0.

Kiểm tra hai archive:

```bash
docker exec -i "$CT_PG_CONTAINER" pg_restore --list \
  < "$CT_ENV_ROOT/catalog/databases/schema-5.2.0/standard-v1/baseline.dump" > /dev/null

docker exec -i "$CT_PG_CONTAINER" pg_restore --list \
  < "$CT_ENV_ROOT/catalog/databases/schema-5.3.0/standard-v1/baseline.dump" > /dev/null
```

Các lệnh phải kết thúc thành công. Đọc được archive chưa chứng minh restore hoặc schema tương thích; kiểm tra tiếp ở bước sau.

## 4. Tạo working DB lần đầu

Ví dụ demo dùng role `contrack` để tạo và sở hữu các working DB. Khi triển khai thật có thể tách role quản trị/ứng dụng và cấp quyền phù hợp.

Chạy từng lệnh, chỉ tiếp tục khi lệnh trước thành công:

```bash
docker exec "$CT_PG_CONTAINER" createdb \
  -U "$CT_PG_ROLE" --template=template0 -- ct_520_standard &&

docker exec -i "$CT_PG_CONTAINER" pg_restore \
  -U "$CT_PG_ROLE" --exit-on-error --single-transaction \
  --no-owner --no-privileges --dbname=ct_520_standard \
  < "$CT_ENV_ROOT/catalog/databases/schema-5.2.0/standard-v1/baseline.dump"

docker exec "$CT_PG_CONTAINER" createdb \
  -U "$CT_PG_ROLE" --template=template0 -- ct_530_standard &&

docker exec -i "$CT_PG_CONTAINER" pg_restore \
  -U "$CT_PG_ROLE" --exit-on-error --single-transaction \
  --no-owner --no-privileges --dbname=ct_530_standard \
  < "$CT_ENV_ROOT/catalog/databases/schema-5.3.0/standard-v1/baseline.dump"
```

Chỉ tạo/restore một lần cho mỗi working DB. Nếu `createdb` báo DB đã tồn tại, kiểm tra và dùng lại DB đó hoặc chọn một tên mới; không chạy restore tiếp lên DB có dữ liệu chỉ để bỏ qua lỗi. Nếu restore thất bại, dừng thao tác và xử lý theo lỗi, không chuyển JDBC sang DB chưa chuẩn bị xong.

`--single-transaction` cùng `--exit-on-error` dừng và rollback phần restore khi có lỗi; `--no-owner` để role restore sở hữu các đối tượng được tạo. Role đó cần đủ quyền cho các đối tượng/extensions trong baseline. [PostgreSQL pg_restore](https://www.postgresql.org/docs/16/app-pgrestore.html).

Kiểm tra bảng:

```bash
docker exec "$CT_PG_CONTAINER" psql -U "$CT_PG_ROLE" -d ct_520_standard -c '\dt'
docker exec "$CT_PG_CONTAINER" psql -U "$CT_PG_ROLE" -d ct_530_standard -c '\dt'
```

Sau đó chạy SELECT schema-version thật mà ConTrack sử dụng trên từng DB; phải trả đúng schema tương ứng. Tên DB và danh sách bảng không đủ để chứng minh tương thích WAR. Không dùng `SELECT '5.3.0'` thay cho kiểm tra metadata thật.

## 5. Xác định và backup cấu hình JDBC hiện có

Đối với demo, giả định ứng dụng đã sử dụng:

```bash
export CT_JDBC_FILE="$CT_TOMCAT/conf/Catalina/localhost/app.xml"
test -f "$CT_JDBC_FILE"
```

Nếu `test` thất bại, xác định file DB thật rồi đặt lại `CT_JDBC_FILE` trước khi tiếp tục. Có thể tìm tên file, không in nội dung có secret:

```bash
if command -v rg > /dev/null 2>&1; then
  rg -l -i 'jdbc:postgresql:|spring\.datasource|javax\.sql\.DataSource' "$CT_TOMCAT/conf"
else
  grep -RIlE 'jdbc:postgresql:|spring\.datasource|javax\.sql\.DataSource' "$CT_TOMCAT/conf"
fi
```

Tomcat hỗ trợ cấu hình Context riêng bên ngoài WAR; `app.xml` là lựa chọn demo nếu ứng dụng dùng datasource/resource tương ứng. Tên resource và driver phải khớp cấu hình ứng dụng hiện tại. [Tomcat Context](https://tomcat.apache.org/tomcat-9.0-doc/config/context.html), [Tomcat JNDI datasource](https://tomcat.apache.org/tomcat-9.0-doc/jndi-datasource-examples-howto.html).

Giữ bản backup ngoài webapps, trước khi đổi version:

```bash
export CT_SWITCH_BACKUP="$CT_ENV_ROOT/backups/manual-switch-$(date +%Y%m%d-%H%M%S-%N)"
mkdir -p -m 700 "$CT_SWITCH_BACKUP"
cp -p -- "$CT_JDBC_FILE" "$CT_SWITCH_BACKUP/jdbc-config.original"
if test -f "$CT_TOMCAT/webapps/app.war"; then
  cp -p -- "$CT_TOMCAT/webapps/app.war" "$CT_SWITCH_BACKUP/app.war"
fi
```

Backup có thể chứa credential, nên đặt quyền truy cập theo user quản trị hiện có; không chia sẻ nội dung ra log demo. Ghi lại DB và version đang chạy để quay lại chính xác. Không tự điền `runtime/current/version.yaml`: file đó do tool ghi khi deploy.

## 6. Switch sang 5.3.0

Working DB 5.3.0 phải restore/check schema thành công trước bước này. Giữ nguyên PostgreSQL container đang chạy.

**Dừng Tomcat bằng đúng cách đang quản lý server.** Nếu là standalone với scripts ở runtime/server/bin:

```bash
test -f "$CT_TOMCAT/bin/shutdown.sh"
bash "$CT_TOMCAT/bin/shutdown.sh"
```

Nếu Tomcat chạy qua systemd/service khác, dùng stop service hiện tại thay cho shutdown.sh. Xác nhận đúng instance đã dừng hẳn trước khi đổi JDBC/copy WAR; không dừng service của tool hoặc PostgreSQL. Không triển khai WAR khi Tomcat còn có thể auto-reload sang WAR mới với DB cũ.

Mở file JDBC thật:

```bash
nano "$CT_JDBC_FILE"
```

Trong datasource ứng dụng đang dùng, chuyển database trong URL sang:

```text
jdbc:postgresql://127.0.0.1:5439/ct_530_standard
```

Đây là URL cho **Tomcat chạy trên Linux host** với port demo `5439`. Giữ các tham số JDBC hiện có sau tên DB; user/password phải là role được phép truy cập working DB. Nếu port mapping thật khác, dùng port thật. Backend nằm trong Docker network dùng service name và container port `5432` khi cần kết nối; `127.0.0.1` trong backend không phải PostgreSQL container.

Trên UI tool đang chạy độc lập:

1. ConTrack Environments → Refresh.
2. Chọn WAR 5.3.0, có `artifact.file: app.war`.
3. Validate selection → Deploy WAR.
4. Chờ DEPLOYED; đích phải là `runtime/server/webapps/app.war`.

Khởi động lại Tomcat bằng cùng cơ chế đã dùng để stop. Nếu standalone:

```bash
bash "$CT_TOMCAT/bin/startup.sh"
tail -n 100 "$CT_TOMCAT/logs/catalina.out"
```

## 7. Xác nhận ứng dụng và DB

Mở URL ConTrack hiện có (ví dụ port 8080, context `/app/`), kiểm tra version và mở một chức năng có đọc dữ liệu DB. Sau đó xem kết nối trên PostgreSQL:

```bash
docker exec "$CT_PG_CONTAINER" psql -U "$CT_PG_ROLE" -d postgres -c \
"SELECT datname, usename, application_name, count(*) AS connections
 FROM pg_stat_activity
 WHERE datname IN ('ct_520_standard', 'ct_530_standard')
 GROUP BY datname, usename, application_name
 ORDER BY datname, usename;"
```

Đối chiếu kết nối của ứng dụng với `ct_530_standard`, không chỉ dựa vào một HTTP 200 hoặc kết nối psql quản trị. Chạy lại schema-version check nếu ứng dụng có migration lúc startup. UI DEPLOYED vẫn chỉ xác nhận copy WAR; DB switch/startup/health trong quy trình này chưa được tool ghi nhận tự động.

## 8. Quay về 5.2.0

Nếu muốn giữ dữ liệu test đã lưu của 5.2.0, bỏ qua dump/create/restore. Thực hiện:

1. Dừng Tomcat đúng instance.
2. Đổi JDBC sang `jdbc:postgresql://127.0.0.1:5439/ct_520_standard`.
3. Deploy `app.war` 5.2.0 qua UI.
4. Start Tomcat, kiểm tra version và chức năng DB/kết nối.

Không downgrade `ct_530_standard`; DB đó được giữ nguyên để dùng lại. Nếu lần switch mới lỗi, có thể quay về bộ WAR + JDBC + DB trước đó đã xác nhận, với điều kiện DB cũ không bị thay đổi bởi lần switch vừa rồi.

## 9. Khi cần dữ liệu sạch

Tạo working DB tên mới, ví dụ `ct_530_standard_r002`, rồi restore lại baseline 5.3.0 bằng các lệnh ở bước 4 (đổi `--dbname` và tên DB). Sau khi restore/schema check thành công, thực hiện lại bước stop → đổi JDBC → deploy/start → kiểm tra.

Không restore đè DB đang phục vụ Tomcat. Các working DB cũ được dọn riêng sau khi xác nhận không còn sử dụng. Để tự động hóa quy trình này cần bổ sung quản lý DB, mapping version/baseline/working DB và cơ chế điều khiển Tomcat host; chỉ thêm manifest hiện chưa thực hiện được các thao tác đó.
