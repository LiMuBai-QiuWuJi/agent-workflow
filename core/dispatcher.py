import os
import re

from call_llm import CallParameters, ChatSession, call_llm, ApiKeyPool
from core.memory import Memory
from core.team import Team

COLLAB_RE = re.compile(r"\[请求协作:([A-Za-z_\-]+)\]")
"""输出契约信号：[请求协作:岗位key] 协作说明"""

VERDICT_RE = re.compile(r"【评审结论[:：](通过|不通过)】")
"""输出契约信号："""

MAX_REJECT = 2
"""同一任务最多退回 2 次：编码岗最多改 2 轮、最多经历 3 轮评审；
第 3 次评审仍不通过 = 判失败终止。该上限归属于调度器管理。"""


def extract_collaboration(reply: str) -> tuple[str, str] | None:
    """从岗位产出解析协作请求 → (岗位key, 协作说明)。"""
    m = COLLAB_RE.search(reply or "")
    if not m:
        return None
    role_key = m.group(1).strip()
    note = (reply[m.end():].strip().splitlines() or [""])[0]   # 说明 = 信号同行后半句
    return role_key, note


def extract_verdict(reply: str) -> str | None:
    """从评审岗产出解析评审结论 → "通过" / "不通过"；没有结论返回 None。"""
    m = VERDICT_RE.search(reply or "")
    if not m:
        return None
    return m.group(1)


def next_reject(reject_counts: dict, task_id: str) -> int | None:
    """【受控循环的刹车】退回计数 + 上限判定，纯确定性代码。
    返回本次是第几次退回 (>=1) ;超上限返回 None = 判失败。
    状态机简化为一个计数字典:"""
    n = reject_counts.get(task_id, 0) + 1
    if n > MAX_REJECT:
        return None                     # 超上限：拦死，不计数、不派发
    reject_counts[task_id] = n
    return n


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


def run_review_chain(team: Team, memory: Memory, project_id: str,
                     requirement: str) -> None:
    """调度入口：编码 → 评审 → 通过则闭环；不通过则退回修改 → 再评审，
    全程无人工干预（防链式扩散下的受控循环）。

    星型调度：退回/终止的决定权全在这份确定性代码里，岗位只发信号。
    防扩散：测试岗产出即使再有 [请求协作:...]
    也不再解析——循环只在编码↔测试这一条边上往返，不产生新边。"""
    workspace = os.path.join("demo_out", project_id)
    os.makedirs(workspace, exist_ok=True)          # 环境事实由系统创建

    task_id = "任务#1"          # 编码任务 id：scheduler.md 输出契约的"任务#N"
    review_id = "任务#2"        # 评审任务 id：退回计数挂在编码任务上，评审任务只读
    reject_counts: dict[str, int] = {}   # 受控循环的计数字典

    coder_task = (
        f"{task_id} 任务：{requirement}\n"
        f"请实现该需求对应的代码，并用 write_file 写入 {workspace}/ 下的相对路径文件，\n"
        f"产出末尾按【交付清单】格式声明生成的文件。\n"
        f"完成后按输出契约请求测试岗评审：[请求协作:tester] 请审查上述实现与交付文件。"
    )
    coder_reply = dispatch(team, "coder", coder_task, memory=memory, project_id=project_id)
    print(f"\n----- 编码岗产出（初始） -----\n{coder_reply}")

    while True:
        collab = extract_collaboration(coder_reply)
        if collab is None:
            print("（编码岗未发协作信号——无法进入评审，终止；完整现场见上方产出）")
            return
        role_key, note = collab
        role = team.get(role_key)   # 岗位不存在会显式报错并列出现有岗位（Team.get 自带）

        # 【自包含原则】评审任务 = 需求原文 + 编码产出 + 协作说明 + 环境事实。
        # collab_task = (
        #     f"{review_id} 任务：编码岗完成「{requirement}」后请求你（{role.name}）配合：{note}\n"
        #     f"编码岗产出（含交付清单）：\n{coder_reply}\n"
        #     f"请先用 read_file 逐项核对交付清单声明的文件是否真实存在且内容吻合，\n"
        #     f"再用 run_cmd 实际运行其中的代码（执行目录填 {workspace}，"
        #     f"比如 cmd 填 python {workspace}/xxx.py）（仅举例不一定非要python），\n"
        #     f"最后按输出契约给出【评审结论:通过/不通过】。"
        # )
        collab_task = (
        f"{review_id} 任务：编码岗完成「{requirement}」后请求你（{role.name}）配合：{note}\n"
        f"相关产出（含交付清单）：\n{coder_reply}\n"
        f"工作目录：{workspace}/"
)
        tester_reply = dispatch(team, role_key, collab_task, memory=memory, project_id=project_id)
        # 防链式扩散落点：这里刻意不再对 tester_reply 调 extract_collaboration。
        print(f"\n----- {role.name} 评审产出 -----\n{tester_reply}")

        verdict = extract_verdict(tester_reply)
        if verdict is None:
            # 契约即合同：交不出评审结论 = 产出不合契约，按不通过退回一次。
            # 问题清单由调度系统代拟——这本身就是要编码岗面对的"问题"。
            verdict = "不通过"
            tester_reply += "\n（调度系统注：评审岗未按输出契约给出结论，视为不通过）"

        if verdict == "通过":
            print(f"\n===== 评审链闭环成功（{task_id}，退回 {reject_counts.get(task_id, 0)} 次）=====")
            return

        # —— 不通过：先过刹车，再决定是否退回 ——
        n = next_reject(reject_counts, task_id)
        if n is None:
            print(f"\n===== {task_id} 评审失败：退回超上限（>{MAX_REJECT} 次），终止 =====")
            print("----- 终止现场：编码岗最后产出 -----\n" + coder_reply)
            print("----- 终止现场：评审岗最后结论 -----\n" + tester_reply)
            print("（将来增强：LLM 重新拆解任务 / 人工介入通道——本版只终止并留现场）")
            return

        # 【自包含原则】退回任务 = 需求原文 + 原产出 + 问题清单（评审产出全文）+
        # 第 N 次退回（模型被通知，不自报）+ 环境事实。
        coder_task = (
            f"{task_id} 任务（第 {n} 次退回修改）：{requirement}\n"
            f"你的上一版产出被评审不通过。上一版产出：\n{coder_reply}\n"
            f"评审结论与编号问题清单（逐条修正，不要重写全部）：\n{tester_reply}\n"
            f"请修正后用 write_file 覆盖写入 {workspace}/ 下的原相对路径文件，\n"
            f"产出末尾按【交付清单】格式重新声明。\n"
            f"完成后按输出契约再次请求测试岗评审：[请求协作:tester] 请复审修正后的实现与交付文件。"
        )
        coder_reply = dispatch(team, "coder", coder_task, memory=memory, project_id=project_id)
        print(f"\n----- 编码岗产出（第 {n} 次退回后） -----\n{coder_reply}")

