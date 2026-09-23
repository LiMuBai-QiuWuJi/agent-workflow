import os
import re

from call_llm import CallParameters, ChatSession, call_llm, ApiKeyPool
from core.memory import Memory
from core.team import Team

COLLAB_RE = re.compile(r"\[请求协作:([A-Za-z_\-]+)\]")
"""输出契约信号：[请求协作:岗位key] 协作说明"""


def extract_collaboration(reply: str) -> tuple[str, str] | None:
    """从岗位产出解析协作请求 → (岗位key, 协作说明)；没有信号返回 None。
    这是岗位与调度系统之间的唯一协作通道。"""
    m = COLLAB_RE.search(reply or "")
    if not m:
        return None
    role_key = m.group(1).strip()
    note = (reply[m.end():].strip().splitlines() or [""])[0]   # 说明 = 信号同行后半句
    return role_key, note


def dispatch(team: Team, role_key: str, task_content: str,
             memory: Memory = None, project_id: str = "demo") -> str:
    """把任务派给指定岗位：
    岗位的 system prompt = prompts/prompt_file/ 下的文件内容；
    岗位的调用参数 = Role 里的 model/temperature/max_tokens/tools；
    岗位的 key = ApiKeyPool 找 API key 的关键词。
    memory 不为 None 时，会话按 (project_id, role_key) 持久并收尾沉淀；
    memory 为 None 时保持单任务会话（兼容旧调用）。"""
    role = team.get(role_key)
    params = CallParameters(
        api_key=ApiKeyPool.get_key(role.engine),
        base_url="https://api.deepseek.com",
        model=role.model,
        system_prompt=team.load_prompt(role),
        user_input=task_content,
        temperature=role.temperature,
        max_tokens=role.max_tokens,
        stream=False,
        tools=role.tools,
        tool_choice=role.tool_choice,
        tool_map=role.tool_map,
        context_mode="recent",
        context_window=10,     # 默认 10 轮（一轮 = user + assistant）
    )
    if memory is None:
        session = ChatSession(params.system_prompt)
        return call_llm(params, session=session)
    session = memory.get_session(project_id, role_key, params.system_prompt)
    reply = call_llm(params, session=session)
    memory.settle(session)      # 任务收尾：中间消息丢弃，只沉淀「任务+产出」
    return reply


def run_collaboration(team: Team, memory: Memory, project_id: str,
                      requirement: str) -> None:
    """调度入口：编码 → 解析协作信号 → 自动转派一层。
    星型调度,
    岗位只发信号，岗位之间永不直接通信。
    防链式扩散：协作任务（测试岗）的产出即使再有 [请求协作:...] 也不再解析
    只转一层；"""
    workspace = os.path.join("demo_out", project_id)
    os.makedirs(workspace, exist_ok=True)

    coder_task = (
        f"任务：{requirement}\n"
        f"请实现该需求对应的代码，并用 write_file 写入 {workspace}/ 下的相对路径文件，\n"
        f"产出末尾按【交付清单】格式声明生成的文件。\n"
        f"完成后按输出契约请求测试岗评审：[请求协作:tester] 请审查上述实现与交付文件。"
    )
    coder_reply = dispatch(team, "coder", coder_task, memory=memory, project_id=project_id)
    print(f"\n----- 编码岗产出 -----\n{coder_reply}")

    collab = extract_collaboration(coder_reply)
    if collab is None:
        print("（编码岗未发协作信号——今天到此为止；自动评审是 Day 4 的事）")
        return
    role_key, note = collab
    role = team.get(role_key)   # 岗位不存在会显式报错并列出现有岗位（Team.get 自带）

    # 【自包含原则】协作任务 = 需求原文 + 编码产出 + 协作说明 + 环境事实。
    # 测试岗看不到编码岗的历史，一切背景在这里给齐。
    collab_task = (
        f"任务：编码岗完成「{requirement}」后请求你（{role.name}）配合：{note}\n"
        f"编码岗产出（含交付清单）：\n{coder_reply}\n"
        f"请先用 read_file 逐项核对交付清单声明的文件是否真实存在且内容吻合，\n"
        f"再用 run_cmd 实际运行其中的代码（执行目录填 {workspace}，"
        f"如 cmd 填 python {workspace}/xxx.py），\n"
        f"最后按输出契约给出【评审结论:通过/不通过】。"
    )
    tester_reply = dispatch(team, role_key, collab_task, memory=memory, project_id=project_id)
    # 防链式扩散落点：这里刻意不再对 tester_reply 调 extract_collaboration。
    print(f"\n----- {role.name} 协作产出 -----\n{tester_reply}")
