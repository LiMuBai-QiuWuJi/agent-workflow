# ============================================================
# agent-workflow · 多 Agent 团队编排系统 · 一体化镜像
# 浏览器运行视图 + FastAPI + SSE + 调度/评审链全栈
#
# 构建：docker build -t agent-workflow .
# 运行：docker run -p 8000:8000 agent-workflow
#        （页面 http://localhost:8000 ，与终端同一调度入口）
#
# API Key 不进镜像：.env 已被 .dockerignore 排除。
# 二选一在运行时注入（ApiKeyPool 环境变量优先于 .env）：
#   挂载本机 .env：docker run -p 8000:8000 -v %cd%\.env:/app/.env agent-workflow
#   环境变量注入：docker run -p 8000:8000 -e DEEPSEEK_API_KEY=sk-xxx agent-workflow
# 运行配置 run_config.txt 已打进镜像；浏览器内配置抽屉可在线改（每次运行读一次）。
# ============================================================
FROM python:3.14-slim

WORKDIR /app

# 运行时真实依赖的精简清单（7 个包）。
# 注意：requirements.txt 是整个 career-pivot 环境的冻结清单（含 faster-whisper/
# playwright/onnxruntime 等与本子工程无关的包），不可用于本镜像——直接装会把
# 镜像撑到数 GB。改依赖时以「运行时 import 实际用到的第三方包」为准。
# PIP_INDEX_URL 仅供网络受限环境构建时换源（如清华镜像），默认值是官方 PyPI。
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip install --no-cache-dir -i "$PIP_INDEX_URL" \
    fastapi==0.141.1 \
    uvicorn==0.52.4 \
    pydantic==2.13.4 \
    openai==3.3.1 \
    python-dotenv==1.2.3 \
    python-docx==1.2.0 \
    pypdf==6.18.0

COPY . .

EXPOSE 8000

# 容器内必须 --host 0.0.0.0，否则宿主浏览器访问不到
CMD ["python", "-m", "uvicorn", "web_server:app", "--host", "0.0.0.0", "--port", "8000"]
