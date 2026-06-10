#!/bin/bash
set -e

# ============================================================
#  SNKRDUNK 交易卡爬虫 - CentOS 一键部署脚本
#  适用: CentOS 7/8/9, Rocky Linux, AlmaLinux
#  用法: sudo bash deploy_centos.sh
# ============================================================

APP_DIR="/www/Python/snkrdunk"
DOMAIN="${1:-}"  # 可选参数: 域名

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[$(date +'%H:%M:%S')]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# ============================================================
#  检查 root 权限
# ============================================================
if [ "$EUID" -ne 0 ]; then
  err "请使用 sudo 或 root 用户运行此脚本"
fi

log "=== SNKRDUNK 交易卡爬虫 - CentOS 部署 ==="
echo ""

# ============================================================
#  1. 安装系统依赖
# ============================================================
log "[1/7] 安装系统依赖..."

# 启用 EPEL + PowerTools（某些包需要）
yum install -y epel-release
if command -v dnf &> /dev/null; then
  dnf config-manager --set-enabled crb 2>/dev/null || true
fi

yum install -y python3 python3-pip python3-devel nginx git wget curl

# 检查 Python 版本
PY_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
log "  Python 版本: $PY_VERSION"

# ============================================================
#  2. 创建项目目录
# ============================================================
log "[2/7] 创建项目目录..."
mkdir -p $APP_DIR
mkdir -p $APP_DIR/data

# ============================================================
#  3. 复制项目文件
# ============================================================
log "[3/7] 复制项目文件..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$SCRIPT_DIR" = "$APP_DIR" ]; then
  log "  已在目标目录中"
else
  # 尝试从当前目录复制
  if [ -f "app.py" ]; then
    cp -r . $APP_DIR/
    log "  从当前目录复制文件"
  else
    warn "  app.py 未找到，尝试从 Git 克隆..."
    if [ -n "$DOMAIN" ]; then
      warn "  请先上传项目文件到 $APP_DIR，或配置 Git 仓库"
      warn "  手动操作:"
      echo "    cd $APP_DIR"
      echo "    git clone <your-repo-url> ."
      exit 0
    fi
  fi
fi

cd $APP_DIR

# ============================================================
#  4. 创建虚拟环境 + 安装依赖
# ============================================================
log "[4/7] 创建 Python 虚拟环境..."

python3 -m venv venv
source venv/bin/activate

log "  安装 Python 依赖..."

# ⚠️ CentOS 7 OpenSSL 兼容说明
# 本项目已全面使用内置 urllib，无需安装 requests 即可运行 Web UI
# 如仍需使用 CLI 工具的 requests 特性，可安装兼容版本：
pip install flask gunicorn beautifulsoup4 lxml -q

# ============================================================
#  5. 创建 systemd 服务
# ============================================================
log "[5/7] 创建 systemd 服务..."

cat > /etc/systemd/system/snkrdunk.service << 'SERVICE'
[Unit]
Description=SNKRDUNK Trading Card Scraper
After=network.target

[Service]
Type=simple
User=nginx
Group=nginx
WorkingDirectory=/www/Python/snkrdunk
Environment="PATH=/www/Python/snkrdunk/venv/bin"
ExecStart=/www/Python/snkrdunk/venv/bin/gunicorn -w 2 -b 127.0.0.1:5000 --timeout 300 app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE

# 设置目录权限
chown -R nginx:nginx $APP_DIR
chmod 755 $APP_DIR
chmod 755 $APP_DIR/data

systemctl daemon-reload
systemctl enable snkrdunk
systemctl start snkrdunk

log "  服务状态: $(systemctl is-active snkrdunk)"

# ============================================================
#  6. 配置 Nginx
# ============================================================
log "[6/7] 配置 Nginx..."

if [ -n "$DOMAIN" ]; then
  # 带域名的配置
  cat > /etc/nginx/conf.d/snkrdunk.conf << 'NGINX'
server {
    listen 80;
    server_name DOMAIN_PLACEHOLDER;

    access_log /var/log/nginx/snkrdunk_access.log;
    error_log /var/log/nginx/snkrdunk_error.log;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_connect_timeout 10s;
        proxy_send_timeout 300s;

        # WebSocket 支持（如果需要）
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # 静态文件缓存
    location /static/ {
        alias /www/Python/snkrdunk/static/;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }

    # 限制敏感文件访问
    location ~* \.(py|pyc|md|txt|log)$ {
        deny all;
    }
}

server {
    listen 443 ssl http2;
    server_name DOMAIN_PLACEHOLDER;

    ssl_certificate /etc/letsencrypt/live/DOMAIN_PLACEHOLDER/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/DOMAIN_PLACEHOLDER/privkey.pem;

    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }
}
NGINX

  sed -i "s/DOMAIN_PLACEHOLDER/$DOMAIN/g" /etc/nginx/conf.d/snkrdunk.conf
else
  # 无域名，使用 IP
  cat > /etc/nginx/conf.d/snkrdunk.conf << 'NGINX'
server {
    listen 80 default_server;
    server_name _;

    access_log /var/log/nginx/snkrdunk_access.log;
    error_log /var/log/nginx/snkrdunk_error.log;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;
    }
}
NGINX
fi

# 备份默认配置并启动
if [ -f /etc/nginx/nginx.conf ]; then
  cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.backup
fi

# 确保 nginx 用户可访问
chown -R nginx:nginx /var/log/nginx

# 测试配置
nginx -t && systemctl enable nginx && systemctl restart nginx

# ============================================================
#  7. 配置防火墙
# ============================================================
log "[7/7] 配置防火墙..."

if command -v firewall-cmd &> /dev/null; then
  firewall-cmd --permanent --add-service=http 2>/dev/null || true
  firewall-cmd --permanent --add-service=https 2>/dev/null || true
  firewall-cmd --reload 2>/dev/null || true
  log "  防火墙已配置"
elif command -v iptables &> /dev/null; then
  iptables -A INPUT -p tcp --dport 80 -j ACCEPT
  iptables -A INPUT -p tcp --dport 443 -j ACCEPT
  log "  iptables 规则已添加"
fi

# ============================================================
#  完成
# ============================================================
SERVER_IP=$(curl -s ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  部署完成!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "  访问地址: http://$SERVER_IP"
if [ -n "$DOMAIN" ]; then
  echo "  域名:     https://$DOMAIN"
  echo ""
  echo "  配置 HTTPS:"
  echo "    sudo certbot --nginx -d $DOMAIN"
fi
echo ""
echo "  项目目录: $APP_DIR"
echo "  数据目录: $APP_DIR/data"
echo ""
echo "  常用命令:"
echo "    sudo systemctl status snkrdunk   # 查看服务状态"
echo "    sudo systemctl restart snkrdunk  # 重启服务"
echo "    sudo journalctl -u snkrdunk -f   # 查看实时日志"
echo "    sudo systemctl restart nginx      # 重启 Nginx"
echo ""
echo "  查看爬取数据:"
echo "    ls -la $APP_DIR/data/"
echo ""
