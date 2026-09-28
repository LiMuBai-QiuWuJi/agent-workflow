import os
import json
from call_llm import CallParameters,ChatSession,call_llm

from skill.calculator.schemas import CALCULATOR_SCHEMA
from skill.calculator.tool import calculator
from skill.read_file.schemas import READFILE_SCHEMAS
from skill.read_file.tool import read_file
from skill.write_file.schemas import WRITEFILE_SCHEMAS
from skill.write_file.tool import write_file


# def answer(question: str, session: ChatSession,
#            stream: bool = True,
#            context_mode: str = "unlimited",
#            context_window: int = 10) -> str:
#     """RAG 问答：LLM 自行决定是否需要调用 query_knowledge 工具检索资料"""
#     tools = [CALCULATOR_SCHEMA, READFILE_SCHEMAS, WRITEFILE_SCHEMAS]

#     from core.ApiKeyPool import ApiKeyPool
#     from prompts.get_prompt import get_prompt,PromptFileName
#     params = CallParameters(
#         api_key=ApiKeyPool.get_key("DEEPSEEK_OPENAI_API_KEY"),
#         base_url= "https://api.deepseek.com",
#         model="deepseek-flash",
#         max_tokens = 4096,
#         temperature = 0.4,
#         system_prompt=get_prompt(PromptFileName.SCHEDULER), # 若session为空，内部会用此内容自动创建一个session
#         user_input=question,
#         stream=stream,
#         tools=tools,
#         tool_map={
#             "calculator": calculator,
#             "read_file": read_file,
#             "write_file": write_file,
#         },
#         context_mode=context_mode,
#         context_window=context_window,
#     )

#     return call_llm(params, session=session)

# def main():
#     from prompts.get_prompt import get_prompt,PromptFileName
#     system_prompt = get_prompt(PromptFileName.SCHEDULER)
#     session = ChatSession(system_prompt)
#     while True:
#         user_input = input("你：")
#         while not user_input:
#             user_input = input("你：")
#         if user_input.lower() in ("exit", "quit"):
#             break
#         elif user_input.lower() in ("showall",):
#             print(f"\n\n{session.messages}")
#             continue

#         answer(user_input, session=session)
#         print(f"\n{'=' * 40}\n")

# if __name__ == "__main__":
#     main()


#####################################
#        以下是测试派发功能用         #
#####################################

# from core.team import Team
# from core.dispatcher import dispatch

# def decompose(requirement: str) -> list[tuple[str, str]]:
#     return [
#         ("coder",
#          f"任务：{requirement}\n"
#          f"请实现该需求对应的代码，并在产出末尾按【交付清单】格式声明生成的文件。"),
#         ("tester",
#          f"任务：针对以下需求，编写一份验收要点清单（供后续评审编码产出时使用）：{requirement}\n"
#          f"要求：逐条列出功能正确性、边界情况两类检查点。"),
#     ]


# def main() -> None:
#     requirement = input("需求：")
#     team = Team.seed_builtin()

#     print(f"编制：{[(r.key, r.name) for r in team.roles.values()]}")
#     for role_key, task in decompose(requirement):
#         role = team.get(role_key)
#         print(f"\n===== 派单 → {role.name}（engine={role.engine}, model={role.model}, T={role.temperature}）=====")
#         reply = dispatch(team, role_key, task)
#         print(f"\n----- {role.name} 产出 -----\n{reply}")


# if __name__ == "__main__":
#     main()


######################################
# 以下是测试岗位独立记忆与新版派发功能用 #
######################################

import os
import sys
import time

from call_llm import USAGE_LOG
from core.dispatcher import plan_tasks, run_pipeline
from core.memory import Memory
from core.task_table import DirectReply, TaskTableError
from core.team import Team


class Tee:
    """write 进来的每个字符同时给屏幕和文件"""

    def __init__(self, console, file):
        self.console = console
        self.file = file

    def write(self, s):
        self.console.write(s)
        self.file.write(s)
        return len(s)

    def flush(self):
        self.console.flush()
        self.file.flush()


PROJECT_ID = "demo_3"
CONFIG_PATH = "run_config.txt"


def load_run_config(path: str = CONFIG_PATH) -> dict:
    """运行配置：工程启动时读取一次，不实时重读（改配置需重启）。
    格式 key=value，# 开头为注释；缺文件返回空 dict，不报错。"""
    config = {}
    if not os.path.exists(path):
        return config
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            config[key.strip()] = value.strip()
    return config


def apply_run_config(team, config: dict) -> None:
    """把配置真正应用到编制与调度参数（启动时一次；留空的项不覆盖代码默认值）。"""
    import core.dispatcher as dispatcher
    if config.get("api.base_url", "").strip():
        dispatcher.API_BASE_URL = config["api.base_url"].strip()
    if config.get("api.timeout", "").strip():
        dispatcher.TIMEOUT = float(config["api.timeout"])
    if config.get("dispatch.max_reject", "").strip():
        dispatcher.MAX_REJECT = int(config["dispatch.max_reject"])
    if config.get("dispatch.max_tool_rounds", "").strip():
        dispatcher.MAX_TOOL_ROUNDS = int(config["dispatch.max_tool_rounds"])
    for role_key in ("coder", "tester"):
        role = team.roles.get(role_key)
        if role is None:
            continue
        for attr in ("model", "temperature", "max_tokens"):
            value = config.get(f"{role_key}.{attr}", "").strip()
            if value:
                setattr(role, attr, type(getattr(role, attr))(value))


def main() -> None:
    os.makedirs("运行记录", exist_ok=True)
    log_path = os.path.join("运行记录", f"运行_{time.strftime('%Y%m%d_%H%M%S')}.txt")
    log_file = open(log_path, "w", encoding="utf-8")
    old_stdout, old_stderr = sys.stdout, sys.stderr
    tee = Tee(old_stdout, log_file)
    sys.stdout, sys.stderr = tee, tee
    print(f"（本次运行同时记录到 {log_path}）")

    try:
        team = Team.seed_builtin()
        memory = Memory()
        config = load_run_config()          # 启动读一次：只含通用公用配置
        apply_run_config(team, config)      # 配置真正生效：岗位参数/循环刹车/API 地址/协作开关
        collab = config.get("dispatch.collab", "True").strip().lower() != "false"
        core_only = config.get("verify.core_only", "True").strip().lower() != "false"

        requirement = input("需求：")

        # 智能分工：调度岗（唯一做分工决策的 LLM）拿编制表+需求产出任务表 ——
        events: list[dict] = []      # 事件流：Web 总览图/轨迹图与 SSE 的统一数据源
        try:
            tasks = plan_tasks(team, requirement, events)
        except DirectReply as e:
            # 问候/自我介绍/纯问答：调度岗直接应答，不拆解也不判失败。
            # 队列/列表持有 plan dict 引用，原地改成 direct_reply（SSE 与 JSONL 同步）。
            events[0].clear()
            events[0].update({"event": "direct_reply", "answer": e.answer})
            print(f"\n调度岗：{e.answer}")
            tasks = None
        except TaskTableError as e:
            events[0].clear()
            events[0].update({"event": "fail", "stage": "调度",
                              "reason": "任务拆解契约违约", "raw": e.raw})
            print(f"\n===== 任务拆解失败（调度契约违约），判失败 =====\n{e}")
            tasks = None

        if tasks:
            # 用结构化任务表替换 plan 事件的 raw 正文（两张图的"调度拆解"节点数据源）
            events[0] = {"event": "plan",
                         "tasks": [{"id": t.id, "role": t.role_key,
                                    "desc": t.description[:80],
                                    "review_of": t.review_of,
                                    "deliverable": t.deliverable,
                                    "depends_on": t.depends_on}
                                   for t in tasks]}
            print("\n----- 调度岗任务表 -----")
            for t in tasks:
                tag = f"[评审 {t.review_of}] " if t.review_of else ""
                dep = f"（依赖：{t.depends_on}）" if t.depends_on else ""
                print(f"{t.id} [{t.role_key}] {tag}{t.description[:60]}…{dep}")
            run_pipeline(team, memory, PROJECT_ID, tasks, core_only, collab, events)

        # 事件流落盘：两张图先对录播开发，SSE 落地后同源切直播
        events_path = os.path.join("运行记录", f"events_{time.strftime('%Y%m%d_%H%M%S')}.jsonl")
        with open(events_path, "w", encoding="utf-8") as f:
            for i, e in enumerate(events, 1):
                f.write(json.dumps({"seq": i, **e}, ensure_ascii=False) + "\n")
        print(f"（事件流已记录到 {events_path}）")

        print("\n===== 本次运行账单 =====")
        for i, u in enumerate(USAGE_LOG, 1):
            print(f"第{i}次调用 prompt={u['prompt']} completion={u['completion']}")
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr
        log_file.close()


if __name__ == "__main__":
    main()


