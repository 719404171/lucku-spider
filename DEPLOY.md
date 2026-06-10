# 部署指南

将 SNKRDUNK 交易卡爬虫部署到服务器，支持不同操作系统和场景。

---

## CentOS 一键部署

```bash
# 1. 上传项目到服务器（在本地 Windows 执行）
scp -r D:\AiProject\SpiderCard root@your-server:/www/Python/

# 2. SSH 登录服务器
ssh root@your-server

# 3. 运行部署脚本
cd /www/Python/SpiderCard
chmod +x deploy_centos.sh
sudo bash deploy_centos.sh
```

部署脚本自动完成：
- 安装 Python 3、Nginx、Git 等依赖
- 创建虚拟环境并安装 Python 包
- 配置 systemd 服务（开机自启 + 掉线重启）
- 配置 Nginx 反向代理（80 端口）
- 配置防火墙（开放 80/443 端口）
- 设置目录权限

### 可选：配置域名 + HTTPS

```bash
# 先确保域名解析到服务器 IP，然后运行
sudo bash deploy_centos.sh your-domain.com

# 或者部署完成后手动配置 SSL
sudo certbot --nginx -d your-domain.com
```

### 管理命令

```bash
# 查看服务状态
sudo systemctl status snkrdunk

# 查看实时日志
sudo journalctl -u snkrdunk -f

# 重启服务（更新代码后）
sudo systemctl restart snkrdunk

# 重启 Nginx
sudo systemctl restart nginx
```

### 更新代码

```bash
cd /www/Python/snkrdunk
# 上传新代码覆盖（或用 git pull）
sudo cp -r /path/to/new/files/* .
sudo chown -R nginx:nginx .
sudo systemctl restart snkrdunk
```

---

## 通用 Linux 部署（Ubuntu/Debian）

```bash
# 上传或 clone
git clone https://github.com/your/repo.git
cd SpiderCard
```

### 2. 安装依赖

```bash
# 安装 Python 3.10+
sudo apt update
sudo apt install python3 python3-pip python3-venv nginx -y

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
pip install gunicorn  # 生产级 WSGI 服务器
```

### 3. 配置 Gunicorn + 后台运行

创建服务文件 `/etc/systemd/system/snkrdunk.service`：

```ini
[Unit]
Description=SNKRDUNK Trading Card Scraper
After=network.target

[Service]
User=www-data
WorkingDirectory=/home/user/SpiderCard
Environment="PATH=/home/user/SpiderCard/venv/bin"
ExecStart=/home/user/SpiderCard/venv/bin/gunicorn -w 2 -b 127.0.0.1:5000 app:app
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable snkrdunk
sudo systemctl start snkrdunk
# 查看状态
sudo systemctl status snkrdunk
```

### 4. 配置 Nginx 反向代理

创建 `/etc/nginx/sites-available/snkrdunk`：

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;
    }

    # 静态文件缓存
    location /static/ {
        alias /home/user/SpiderCard/static/;
        expires 7d;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/snkrdunk /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### 5. 配置 HTTPS（推荐）

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

---

## 宝塔面板部署

### 前置条件

- 服务器已安装宝塔面板（CentOS/Ubuntu 均可）
- 已安装 **Nginx**（宝塔软件商店安装）
- 已安装 **Python 项目管理器**（宝塔软件商店搜索安装）

### 步骤

#### 1. 上传项目

宝塔面板 → **文件** → 进入 `/www/wwwroot/` → 新建目录 `snkrdunk` → 上传项目文件

或使用 Git：

```bash
cd /www/wwwroot/
git clone https://github.com/your/repo.git snkrdunk
```

#### 2. 安装 Python 依赖

宝塔面板 → **终端** → 执行：

```bash
cd /www/Python/snkrdunk

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# ⚠️ CentOS 7 OpenSSL 兼容说明
# 本项目已全面使用内置 urllib，无需安装 requests 即可运行 Web UI
# 如仍需使用 CLI 工具的 requests 特性，可安装兼容版本：
#   pip install "urllib3<2" "requests<2.29"

# 安装其他依赖
pip install flask gunicorn beautifulsoup4 lxml
```

#### 3. 方法一：使用宝塔 Python 项目管理器（推荐）

> ⚠️ **常见错误**: `Error: '' is not a valid port number` → 原因是**先选框架后端口被清空**。必须先填端口再选框架。

1. 宝塔面板 → **软件商店** → **Python 项目管理器** → **设置**
2. 点击 **添加 Python 项目**
3. 按以下顺序填写：
   - **项目名称**: `snkrdunk`
   - **监听端口**: **先填** `5000`
   - **框架**: 选 `Flask`
   - **启动方式**: 选 `gunicorn`
   - **项目目录**: `/www/Python/snkrdunk`
   - **启动文件**: `/www/Python/snkrdunk/app.py`
   - **Python 版本**: 选 3.9+
   - **命令行**: 留空
4. 点击确定，等待启动

> **备用 - 命令行模式**（端口报错时用）：
> 1. 添加项目 → 启动方式选 **命令行**
> 2. **命令行**填入：
>    ```
>    /www/Python/snkrdunk/venv/bin/gunicorn -w 2 -b 0.0.0.0:5000 --timeout 300 app:app
>    ```

#### 4. 方法二：手动配置 systemd 服务

如果不想用 Python 项目管理器，在终端执行：

```bash
cat > /etc/systemd/system/snkrdunk.service << 'EOF'
[Unit]
Description=SNKRDUNK Trading Card Scraper
After=network.target

[Service]
Type=simple
User=www
Group=www
WorkingDirectory=/www/Python/snkrdunk
Environment="PATH=/www/Python/snkrdunk/venv/bin"
ExecStart=/www/Python/snkrdunk/venv/bin/gunicorn -w 2 -b 127.0.0.1:5000 --timeout 300 app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable snkrdunk
systemctl start snkrdunk
```

#### 5. 配置 Nginx 反向代理

宝塔面板 → 网站 → 添加站点：

- **域名**: 输入你的域名或服务器 IP（如 `192.168.1.100`）
- **根目录**: `/www/Python/snkrdunk`
- **PHP 版本**: 纯静态

添加完成后，点击 **设置** → **反向代理** → **添加反向代理**：

- **代理名称**: `snkrdunk`
- **目标 URL**: `http://127.0.0.1:5000`
- **发送域名**: `$host`

或者直接修改 Nginx 配置文件：

宝塔面板 → 网站 → 设置 → 配置文件，在 `server` 块中添加：

```nginx
location / {
    proxy_pass http://127.0.0.1:5000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_read_timeout 300s;
}
```

然后点击 **重载配置**。

#### 6. 配置 HTTPS（可选）

宝塔面板 → 网站 → 设置 → SSL → 申请 Let's Encrypt 免费证书

#### 7. 防火墙设置

宝塔面板 → 安全 → 添加端口规则 → 放行 `5000` 端口（如果需要直接访问）

> 如果通过 Nginx 代理（推荐），只需放行 `80` 和 `443` 端口即可，`5000` 端口不用对外开放。

### 验证

1. 浏览器访问 `http://你的服务器IP`（或绑定的域名）
2. 如果看到 SNKRDUNK 交易卡爬虫页面，说明部署成功

### 常用操作

| 操作 | 方法 |
|---|---|
| 启动 / 停止 / 重启 | Python 项目管理器 → 对应按钮 |
| 查看日志 | Python 项目管理器 → 日志 |
| 更新代码 | 文件管理器上传覆盖 → Python 项目管理器 → 重启 |
| 修改端口 | Python 项目管理器 → 设置 → 修改端口 |
| 设置开机自启 | Python 项目管理器 → 开机自启开关 |

### 注意事项

1. **权限问题**: 确保 `/www/Python/snkrdunk/data` 目录有写入权限：
   ```bash
   chmod 755 /www/Python/snkrdunk/data
   chown -R www:www /www/Python/snkrdunk
   ```

2. **Python 版本**: 宝塔 Python 项目管理器默认可能使用 Python 3.6，建议在软件商店安装 Python 3.10+ 再创建项目

3. **内存**: 爬虫任务可能占用较多内存，建议服务器至少 2GB 内存

4. **超时设置**: 如果爬取大量卡片，Nginx 反向代理的超时时间要改大：
   ```nginx
   proxy_read_timeout 600s;
   proxy_connect_timeout 30s;
   ```

---

## 方案二：Docker 部署

适合任何支持 Docker 的环境，无需手动配置依赖。

### 1. 创建 Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# 复制项目文件
COPY . .

# 创建数据目录
RUN mkdir -p data

# 暴露端口
EXPOSE 5000

# 启动命令
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "app:app"]
```

### 2. 创建 docker-compose.yml

```yaml
version: '3.8'

services:
  web:
    build: .
    container_name: snkrdunk
    ports:
      - "5000:5000"
    volumes:
      # 持久化数据
      - ./data:/app/data
    environment:
      - TZ=Asia/Shanghai
    restart: unless-stopped
```

### 3. 部署

```bash
# 构建并启动
docker-compose up -d

# 查看日志
docker logs -f snkrdunk
```

### 4. 带 Nginx 的完整版 docker-compose.yml

```yaml
version: '3.8'

services:
  web:
    build: .
    container_name: snkrdunk
    expose:
      - "5000"
    volumes:
      - ./data:/app/data
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    container_name: snkrdunk-nginx
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf
      - ./certbot/www:/var/www/certbot
      - ./certbot/conf:/etc/letsencrypt
    depends_on:
      - web
    restart: unless-stopped

  certbot:
    image: certbot/certbot
    container_name: snkrdunk-certbot
    volumes:
      - ./certbot/www:/var/www/certbot
      - ./certbot/conf:/etc/letsencrypt
    entrypoint: "/bin/sh -c 'trap exit TERM; while :; do certbot renew; sleep 12h & wait $${!}; done;'"
```

---

## 方案三：Windows 服务器（IIS）

如果服务器是 Windows Server。

### 1. 安装依赖

```powershell
# 安装 Python 3.10+
# 安装 IIS + CGI
# 使用 waitress（Windows 友好的 WSGI）
.\venv\Scripts\pip install waitress
```

### 2. 创建启动脚本 run_prod.bat

```batch
@echo off
cd /d D:\SpiderCard
.\venv\Scripts\waitress-serve --port=5000 app:app
```

### 3. 配置 IIS

1. 安装 Application Request Routing (ARR) 和 URL Rewrite
2. 创建站点指向静态文件目录
3. 配置反向代理到 `http://localhost:5000`

### 4. 后台运行（使用 NSSM）

```powershell
# 下载 NSSM (Non-Sucking Service Manager)
nssm install SNKRDUNK "D:\SpiderCard\venv\Scripts\python.exe" "app.py"
nssm start SNKRDUNK
```

---

## 快速部署脚本（Linux）

一键部署脚本 `deploy.sh`：

```bash
#!/bin/bash
set -e

# 配置
APP_DIR="/www/Python/snkrdunk"
DOMAIN="your-domain.com"

echo "=== 部署 SNKRDUNK 交易卡爬虫 ==="

# 1. 安装系统依赖
sudo apt update
sudo apt install -y python3 python3-pip python3-venv nginx

# 2. 创建目录
sudo mkdir -p $APP_DIR
sudo chown $USER:$USER $APP_DIR

# 3. 复制项目文件（假设在当前目录）
cp -r . $APP_DIR/
cd $APP_DIR

# 4. 创建虚拟环境并安装依赖
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install gunicorn

# 5. 创建 systemd 服务
cat > /tmp/snkrdunk.service << 'EOF'
[Unit]
Description=SNKRDUNK Trading Card Scraper
After=network.target

[Service]
User=www-data
WorkingDirectory=/www/Python/snkrdunk
Environment="PATH=/www/Python/snkrdunk/venv/bin"
ExecStart=/www/Python/snkrdunk/venv/bin/gunicorn -w 2 -b 127.0.0.1:5000 app:app
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo cp /tmp/snkrdunk.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable snkrdunk
sudo systemctl start snkrdunk

# 6. 配置 Nginx
cat > /tmp/snkrdunk-nginx << 'CONF'
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 300s;
    }
}
CONF

sudo cp /tmp/snkrdunk-nginx /etc/nginx/sites-available/snkrdunk
sudo ln -sf /etc/nginx/sites-available/snkrdunk /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx

echo ""
echo "=== 部署完成 ==="
echo "访问: http://$(curl -s ifconfig.me)"
echo "或:   http://localhost"
echo ""
echo "查看日志: sudo journalctl -u snkrdunk -f"
```

```bash
# 使用
chmod +x deploy.sh
./deploy.sh
```

---

## 安全建议

1. **修改 app.py**，设置 secret_key：
```python
app.secret_key = os.environ.get("SECRET_KEY", "your-random-secret-here")
```

2. **环境变量**，不要在代码中硬编码敏感信息：
```bash
export SECRET_KEY="random-string"
export FLASK_ENV="production"
```

3. **限制访问**，通过 Nginx 添加 IP 白名单：
```nginx
allow your-ip;
deny all;
```

4. **定期更新**：
```bash
cd /www/Python/snkrdunk
git pull
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart snkrdunk
```

---

## 快速对比

| 方案 | 难度 | 适合场景 | 性能 |
|---|---|---|---|
| Gunicorn + Nginx | ⭐⭐ | Linux VPS（推荐） | ⭐⭐⭐⭐⭐ |
| Docker | ⭐ | 运维自动化 | ⭐⭐⭐⭐ |
| IIS + Waitress | ⭐⭐⭐ | Windows 服务器 | ⭐⭐⭐ |
