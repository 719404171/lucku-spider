FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖（BeautifulSoup 需要 lxml）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# 复制项目文件
COPY . .

# 创建数据目录
RUN mkdir -p /app/data

# 暴露端口
EXPOSE 5000

# 使用 gunicorn 生产模式启动
# -w 2: 2 个工作进程
# -b 0.0.0.0:5000: 监听所有网卡
# --timeout 300: 爬取任务可能较慢，超时设为 5 分钟
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "--timeout", "300", "app:app"]
