# Switch Version bằng user/password Linux

Chức năng vẫn dùng SSH từ backend Docker đến host Linux, nhưng dùng mật khẩu thay cho SSH key. `deploy_war` và xác thực key hiện có được giữ nguyên. Cần cập nhật source và build lại image bằng launcher; image cũ chưa nhận các trường cấu hình password.

Host hiện tại: `10.166.136.7`, user: `vsvndev`. Mật khẩu là mật khẩu đăng nhập Linux của user này, không phải mật khẩu PostgreSQL và không phải tài khoản đăng nhập web tool.

## 1. File YAML thực tế

Chỉnh `/home/vsvndev/Contrack-Recreate/config/environment.yaml`:

```yaml
enabled: true
operation_mode: switch_version
root: /home/vsvndev/Contrack-Recreate/contrack-env
server: runtime/server

switch_version:
  auth_method: password
  ssh_host: '10.166.136.7'
  ssh_port: 22
  ssh_user: 'vsvndev'
  ssh_password: 'REPLACE_WITH_LINUX_PASSWORD'
  known_hosts: /run/contrack-switch/known_hosts
  runner_path: /home/vsvndev/contrack_tool/backend/app/modules/contrack_environments/host_runner.py
  host_config: /home/vsvndev/Contrack-Recreate/config/host-switch.json
  timeout: 7200
```

Thay đúng password tại chỗ trên server. YAML không mã hóa mật khẩu: ai có quyền đọc file hoặc backup đều có thể đọc giá trị đó. Giữ file ngoài Git và hạn chế quyền:

```bash
chmod 600 /home/vsvndev/Contrack-Recreate/config/environment.yaml
```

Đặt password trong dấu nháy đơn để giữ nguyên `#`, `:`, `$`, `!`, dấu backslash và khoảng trắng. Nếu mật khẩu có dấu `'`, viết hai dấu `''` trong YAML. Ví dụ minh họa:

```yaml
ssh_password: 'pa''ss#123:abc'
```

Giá trị thực của ví dụ là `pa'ss#123:abc`. Không dùng YAML multiline (`|`, `>`) cho password. Không dùng `${PASSWORD}` trong file này: loader chỉ đọc YAML, không tự nội suy biến shell.

Password được giữ dưới dạng `SecretStr`, không trả trong API catalog, không đưa vào request/recipe/run log, và bị loại khỏi model dump. Khi chạy, backend truyền password cho `sshpass` qua anonymous pipe/FD, không đưa password vào argv hoặc file tạm. Các biến credential `CONTRACK_ENV_SSH_PASSWORD`/`SSHPASS` không được chuyển tiếp cho child process.

## 2. Tùy chọn dùng file secret

Nếu muốn tách password khỏi YAML, bỏ trường `ssh_password` và thêm:

```yaml
  ssh_password_file: /run/contrack-switch/ssh_password
```

Tạo file trên host bằng Bash, nhập ẩn, không ghi password vào lịch sử shell:

```bash
mkdir -p /home/vsvndev/Contrack-Recreate/secrets/switch-ssh
chmod 700 /home/vsvndev/Contrack-Recreate/secrets/switch-ssh

read -r -s -p 'Linux SSH password: ' CT_SWITCH_PASSWORD
printf '\n'
(umask 077; printf '%s\n' "$CT_SWITCH_PASSWORD" > /home/vsvndev/Contrack-Recreate/secrets/switch-ssh/ssh_password)
unset CT_SWITCH_PASSWORD
chmod 600 /home/vsvndev/Contrack-Recreate/secrets/switch-ssh/ssh_password
```

File chứa một dòng UTF-8, quyền 600. Không sử dụng `runtime.pgpass` làm SSH password file vì định dạng khác. Thứ tự ưu tiên: biến môi trường backend `CONTRACK_ENV_SSH_PASSWORD` > `switch_version.ssh_password` > `ssh_password_file`. Chỉ chọn một cách lưu để dễ quản lý. Nếu dùng biến môi trường, phải truyền nó vào backend container; export trên host không tự truyền vào container.

## 3. Known hosts và host runner

Password mode không cần `id_ed25519` hoặc đăng ký key vào `authorized_keys`. Vẫn cần xác minh host key và cấu hình runner thật:

```text
/home/vsvndev/Contrack-Recreate/
  config/
    environment.yaml
    host-switch.json
  secrets/
    runtime.pgpass
    switch-ssh/
      known_hosts
      ssh_password       # chỉ cần nếu dùng file secret
```

Tạo `known_hosts` cho port 22:

```bash
mkdir -p /home/vsvndev/Contrack-Recreate/secrets/switch-ssh
chmod 700 /home/vsvndev/Contrack-Recreate/secrets/switch-ssh
ssh-keyscan -p 22 -t ed25519 10.166.136.7 \
  > /home/vsvndev/Contrack-Recreate/secrets/switch-ssh/known_hosts

ssh-keygen -lf /home/vsvndev/Contrack-Recreate/secrets/switch-ssh/known_hosts
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

Đối chiếu hai fingerprint trước khi kết nối. Nếu SSH port khác, sửa cả YAML và `ssh-keyscan -p`. Known hosts phải khớp địa chỉ mà backend kết nối.

File `host-switch.json` và quyền chạy Docker/start-stop Tomcat vẫn phải được chuẩn bị theo [bước 2–3 của hướng dẫn chính](contrack-version-switch.md). Đường dẫn JDBC/schema query trong mẫu chỉ là placeholder, cần thay bằng giá trị thật. Runner gọi `start.sh`/`shutdown.sh` từ `runtime/server/bin`.

SSH server cần cho phép password authentication cho user `vsvndev`. Chế độ này dùng một mật khẩu, không tự xử lý OTP/MFA hoặc đổi password khi đăng nhập. Password login gọi trực tiếp script Python từ `runner_path` với `host_config`; không dùng forced command trong `authorized_keys`. Quyền của tài khoản Linux vẫn là quyền đăng nhập bình thường của user đó.

Có thể kiểm tra thủ công trên host, nhập password khi được hỏi (không truyền password trong command):

```bash
ssh -T -p 22 \
  -o PreferredAuthentications=password \
  -o PubkeyAuthentication=no \
  -o KbdInteractiveAuthentication=no \
  -o StrictHostKeyChecking=yes \
  -o UserKnownHostsFile=/home/vsvndev/Contrack-Recreate/secrets/switch-ssh/known_hosts \
  vsvndev@10.166.136.7 \
  'python3 /home/vsvndev/contrack_tool/backend/app/modules/contrack_environments/host_runner.py --config /home/vsvndev/Contrack-Recreate/config/host-switch.json check'
```

Kết quả runner phải có `"ok": true`. Bước check không tạo DB, đổi JDBC hoặc deploy WAR. Kết nối từ mạng Docker cũng phải được server cho phép.

## 4. Build và bật trên tool

Cập nhật source server đến bản có password mode, sau đó:

```bash
cd /home/vsvndev/contrack_tool

CT_ENV_ROOT=/home/vsvndev/Contrack-Recreate/contrack-env \
CT_ENV_CONFIG=/home/vsvndev/Contrack-Recreate/config/environment.yaml \
CT_SWITCH_SSH_DIR=/home/vsvndev/Contrack-Recreate/secrets/switch-ssh \
  bash deploy/contrack-environments/start-version-switch.sh
```

Image mở rộng cài `openssh-client` và `sshpass`. Launcher không yêu cầu private key khi dùng password; backend kiểm tra credential tương ứng, gọi host runner và xác nhận layout. Khi thành công, log có `VERIFIED` và `SSH authentication: password`.

Sau đó Ctrl+F5, mở ConTrack Environments, chọn WAR + baseline, Validate selection rồi Switch Version. Thao tác chuyển WAR/DB không chạy trong launcher.

Các lỗi thường gặp:

| Lỗi | Kiểm tra |
|---|---|
| Vẫn yêu cầu private key | `auth_method` chưa là `password`, hoặc backend/launcher cũ |
| `Invalid environment manager configuration` | Image cũ, sai tên trường/indent YAML hoặc giá trị không hợp lệ |
| Thiếu `sshpass` | Chưa build lại bằng Dockerfile/override Switch Version |
| `SSH_AUTHENTICATION_FAILED` | User/password bị từ chối; kiểm tra thông tin đăng nhập và chính sách SSH |
| `HOST_CONNECTION_FAILED` | Host key, network, quyền chạy command hoặc runner không trả JSON hợp lệ |
| `HOST_CONFIGURATION_INVALID` | Sửa `host-switch.json`, JDBC file, schema query và script thật |

Kiểm thử local xác nhận cách truyền password qua FD, đóng FD khi lỗi/timeout, che secret và giữ key mode cũ. Chưa kiểm thử đăng nhập SSH hoặc Docker build thật trên server Linux từ workspace Windows.
