FROM python:3.11-slim

WORKDIR /app

# 安装依赖(利用层缓存)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# 数据目录(挂 volume 持久化)
RUN mkdir -p /app/data
VOLUME ["/app/data"]

ENV DB_PATH=/app/data/app.db \
    PORT=8000 \
    STAFF_PASSWORD=888888

EXPOSE 8000

CMD ["python", "-m", "backend.app"]
