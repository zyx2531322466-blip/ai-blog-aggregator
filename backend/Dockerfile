# 后端镜像：Python 3.10 + FastAPI（uvicorn）
FROM python:3.10-slim

# 允许在受限网络下通过镜像源安装依赖（CI/本地可通过 --build-arg 覆盖）
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -i "${PIP_INDEX_URL}" -r requirements.txt

COPY . .

# SQLite 开发数据的挂载目录
RUN mkdir -p /app/data

EXPOSE 8000

# 启动前执行数据库迁移，再启动 API 服务
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
