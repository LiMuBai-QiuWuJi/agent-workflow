# -*- coding: utf-8 -*-
"""web_server.py —— FastAPI + SSE 服务化入口：浏览器与终端共用同一底层。

启动：python -m uvicorn web_server:app --port 8000
- GET  /          运行视图（web/index.html）
- GET  /config    运行配置（run_config.txt 内容）
- POST /config    body: 配置全文（text/plain）写回 run_config.txt；需重启生效
- POST /run       body: {"requirement": "..."} → SSE 事件流（与终端同一调度入口）

事件流与 main.py 落盘的 events_*.jsonl 同源同 schema：两张图先对录播开发，
本文件落地后同源切直播，页面只换数据源。
"""
import json
import os
import queue
import threading

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from core.dispatcher import plan_tasks, run_pipeline
from core.memory import Memory
from core.task_table import DirectReply, TaskTableError
from core.team import Team
from main import apply_run_config, load_run_config

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "run_config.txt")
WEB_PROJECT_ID = "web"
"""服务化运行的默认工程 id（工作区 demo_out/web/）。
可在 run_config.txt 用 project.id 覆盖（每次运行读取一次，无需重启），
与终端模式 main.py 的 PROJECT_ID 对齐时记忆即共享。"""

app = FastAPI(title="agent-workflow", docs_url=None, redoc_url=None)


class SSESink:
    """事件汇：列表收集 + 队列推流，喂给 SSE。dispatcher 只调 append()。"""

    def __init__(self):
        self.items: list[dict] = []
        self.q: queue.Queue = queue.Queue()

    def append(self, event: dict) -> None:
        # 结局类事件带项目根绝对路径，前端产出说明可直接展示完整路径
        if event.get("event") in ("done", "verified", "fail"):
            event["root"] = PROJECT_ROOT
        self.items.append(event)
        self.q.put(event)


class RunRequest(BaseModel):
    requirement: str


def _run_pipeline(sink: SSESink, requirement: str) -> None:
    """与 main.py 同款接线：配置 → 调度拆解 → 任务表执行。异常也走事件流。"""
    try:
        team = Team.seed_builtin()
        memory = Memory()
        config = load_run_config()
        apply_run_config(team, config)
        collab = config.get("dispatch.collab", "True").strip().lower() != "false"
        core_only = config.get("verify.core_only", "True").strip().lower() != "false"
        project_id = (config.get("project.id", "") or "").strip() or WEB_PROJECT_ID

        try:
            tasks = plan_tasks(team, requirement, sink)
        except DirectReply as e:
            sink.items[0].clear()          # 原地改：队列持有同一 dict 引用
            sink.items[0].update({"event": "direct_reply", "answer": e.answer})
            return
        except TaskTableError as e:
            sink.items[0].clear()
            sink.items[0].update({"event": "fail", "stage": "调度",
                                  "reason": "任务拆解契约违约", "raw": e.raw})
            return
        # plan 事件换成结构化任务表（与 main.py 同处理）。
        # 注意：队列里持有同一 dict 引用，必须原地改，不能换对象。
        sink.items[0].clear()
        sink.items[0].update({
            "event": "plan",
            "tasks": [{"id": t.id, "role": t.role_key,
                       "desc": t.description[:80],
                       "review_of": t.review_of,
                       "deliverable": t.deliverable,
                       "depends_on": t.depends_on}
                      for t in tasks],
        })
        run_pipeline(team, memory, project_id, tasks, core_only, collab, sink)
    except Exception as e:      # 最后一道闸：任何逃逸异常都变成 fail 事件
        sink.append({"event": "fail", "stage": "系统",
                     "reason": f"{type(e).__name__}: {e}"})
    finally:
        sink.q.put(None)        # 流结束标记


@app.get("/")
def index() -> FileResponse:
    return FileResponse(os.path.join(PROJECT_ROOT, "web", "index.html"))


@app.get("/config")
def config() -> PlainTextResponse:
    text = ""
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            text = f.read()
    return PlainTextResponse(text)


@app.post("/config")
async def save_config(request: Request) -> PlainTextResponse:
    """配置全文写回 run_config.txt（UTF-8）。简单校验：至少一行 key=value。"""
    try:
        text = (await request.body()).decode("utf-8")
    except UnicodeDecodeError:
        return PlainTextResponse("保存失败：不是 UTF-8 文本", status_code=400)
    if not any("=" in ln and not ln.strip().startswith("#")
               for ln in text.splitlines()):
        return PlainTextResponse("保存失败：没有可识别的 key=value 配置行", status_code=400)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(text)
    return PlainTextResponse("已保存；配置在进程启动时读取一次，重启服务后生效")


@app.get("/replay.jsonl")
def replay() -> FileResponse:
    return FileResponse(os.path.join(PROJECT_ROOT, "web", "replay.jsonl"))


@app.get("/replay_reject.jsonl")
def replay_reject() -> FileResponse:
    return FileResponse(os.path.join(PROJECT_ROOT, "web", "replay_reject.jsonl"))


@app.post("/run")
def run(req: RunRequest) -> StreamingResponse:
    sink = SSESink()
    threading.Thread(target=_run_pipeline, args=(sink, req.requirement),
                     daemon=True).start()

    def gen():
        while True:
            event = sink.q.get()
            if event is None:
                break
            yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
