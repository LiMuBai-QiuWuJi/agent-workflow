import os
import re
import shutil

from call_llm import CallParameters, ChatSession, call_llm, ApiKeyPool, TRUNCATION_MARK
from core.memory import Memory
from core.team import Team
from core.task_table import Task, TaskTableError, parse_task_table
from core.verifier import verify_delivery

COLLAB_RE = re.compile(r"[\[【]请求协作[:：]\s*([A-Za-z_\-]+)\s*[\]】]")
"""输出契约信号：[请求协作:岗位key] 协作说明。
全半角括号（[]/【】）与全半角冒号（:/：）均容忍——模型标点风格漂移不该卡死评审链。
与 VERDICT_RE 的宽容度保持一致。"""

VERDICT_RE = re.compile(r"【评审结论[:：](通过|不通过)】")
"""输出契约信号："""

MAX_REJECT = 2
"""同一任务最多退回 2 次：编码岗最多改 2 轮、最多经历 3 轮评审；
第 3 次评审仍不通过 = 判失败终止。该上限归属于调度器管理。
可在 run_config.txt 用 dispatch.max_reject 覆盖（启动时读一次）。"""

MAX_TOOL_ROUNDS = 15
"""工具调用轮数上限：超限回灌收尾提示逼模型给结论。
可在 run_config.txt 用 dispatch.max_tool_rounds 覆盖。"""

API_BASE_URL = "https://api.deepseek.com"
"""LLM API 地址。可在 run_config.txt 用 api.base_url 覆盖。"""

TIMEOUT = 30.0
"""单次 LLM 请求超时秒数。可在 run_config.txt 用 api.timeout 覆盖（启动时读一次）。"""


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
        base_url=API_BASE_URL,
        model=role.model,
        system_prompt=team.load_prompt(role),
        user_input=task_content,
        temperature=role.temperature,
        max_tokens=role.max_tokens,
        timeout=TIMEOUT,
        stream=False,
        tools=role.tools,
        tool_choice=role.tool_choice,
        tool_map=role.tool_map,
        max_tool_rounds=MAX_TOOL_ROUNDS,
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
                     task: Task, review: Task | None = None,
                     core_only: bool = True, collab: bool = True,
                     reset_workspace: bool = True,
                     events: list | None = None) -> str | None:
    """评审链：编码 → 评审 → 通过则交付核验闭环；不通过则退回修改 → 再评审，
    全程无人工干预（防链式扩散下的受控循环）。

    任务表驱动：task = 调度岗拆解出的产出型任务（id/description/交付物来自任务表，
    不再是代码里写死的模板与「任务#1」）；review = 与 task 配对的评审任务
    （缺省时合成一个默认评审任务给 tester，兼容旧调用）。

    星型调度：退回/终止的决定权全在这份确定性代码里，岗位只发信号。
    防扩散：测试岗产出即使再有 [请求协作:...]
    也不再解析——循环只在编码↔评审这一条边上往返，不产生新边。

    core_only：声明了核心交付物且为 True 时评审只认它；
    False 时验收以交付清单为准，不设硬指标。
    collab：多 Agent 协作总开关；False = 只跑编码岗单干，跳过评审链。
    返回：闭环成功时的最终编码产出；任何失败路径返回 None。"""
    workspace = os.path.join("demo_out", project_id)
    if reset_workspace:
        shutil.rmtree(workspace, ignore_errors=True)   # 工作区清零：
    os.makedirs(workspace, exist_ok=True)          # 环境事实由系统创建

    task_id = task.id           # 任务 id：来自调度岗任务表，调度代码不再自造
    if review is None:
        review = Task(id=f"{task_id}·评审", num=task.num, role_key="tester",
                      description="审查上述实现与交付文件，按输出契约给出"
                                  "【评审结论:通过/不通过】，不通过必须附编号问题清单。")
    review_id = review.id
    reviewer_key = review.role_key
    core_deliverable = task.deliverable
    reject_counts: dict[str, int] = {}   # 受控循环的计数字典

    # 交付约束：写进岗位任务文本（自包含原则）；
    # 依赖外部文件怎么评审由 tester.md 的铁律管，不放任务文本
    coder_constraint = (
        f"核心交付物：{core_deliverable}（必须交付，评审只认它）；"
        f"附属产出不限，需要就生成，一并写入交付清单。\n" if core_deliverable else ""
    )
    tester_constraint = (
        f"核心交付物：{core_deliverable}；只按核心交付物验收，"
        f"附属产出不计入也不扣分，文件数量与拆分方式不构成「与需求不符」。\n"
        if (core_deliverable and core_only) else ""
    )

    coder_task = (
        f"{task_id} 任务：{task.description}\n"
        f"{coder_constraint}"
        f"请实现该任务对应的代码，并用 write_file 写入 {workspace}/ 下的相对路径文件，\n"
        f"产出末尾按【交付清单】格式声明生成的文件。\n"
        f"完成后按输出契约请求评审：[请求协作:{reviewer_key}] 请审查上述实现与交付文件。"
    )
    if events is not None:
        events.append({"event": "dispatch", "task_id": task_id, "role": "coder"})
    coder_reply = dispatch(team, "coder", coder_task, memory=memory, project_id=project_id)
    print(f"\n----- 编码岗产出（初始，{task_id}） -----\n{coder_reply}")

    if not collab:
        print("\n（多 Agent 协作模式已关闭：只跑编码岗，跳过评审链）")
        return coder_reply

    while True:
        collab_req = extract_collaboration(coder_reply)
        if collab_req is None and TRUNCATION_MARK in coder_reply:
            # 截断导致的信号缺失,让编码岗把契约信号补发出来
            recover_task = (
                f"{task_id} 收尾补发：你的上一版产出被 max_tokens 截断，"
                f"输出契约信号（【交付清单】与 [请求协作:{reviewer_key}]）已丢失。\n"
                f"不要重写代码。请直接基于已写入 {workspace}/ 的文件，仅补发两样：\n"
                f"1)【交付清单】声明实际生成的文件相对路径；\n"
                f"2)[请求协作:{reviewer_key}] 请审查上述实现与交付文件。"
            )
            if events is not None:
                events.append({"event": "truncation_recover", "task_id": task_id})
            coder_reply = dispatch(team, "coder", recover_task, memory=memory, project_id=project_id)
            print(f"\n----- 编码岗产出（截断补发，{task_id}） -----\n{coder_reply}")
            collab_req = extract_collaboration(coder_reply)
        if collab_req is None:
            print("（编码岗未发协作信号——无法进入评审，终止；完整现场见上方产出）")
            if events is not None:
                events.append({"event": "fail", "task_id": task_id,
                               "stage": "编码", "reason": "未发协作信号",
                               "raw": coder_reply[-2000:]})
            return None
        role_key, note = collab_req
        role = team.get(role_key)   # 岗位不存在会显式报错并列出现有岗位（Team.get 自带）

        # 【自包含原则】评审任务 = 调度岗的评审任务描述 + 协作说明 + 被审产出 + 环境事实。
        collab_task = (
            f"{review_id} 任务：{review.description}\n"
            f"{tester_constraint}"
            f"协作背景：编码岗（{task_id}）完成「{task.description}」后"
            f"请求你（{role.name}）配合：{note}\n"
            f"相关产出（含交付清单）：\n{coder_reply}\n"
            f"工作目录：{workspace}/"
        )
        if events is not None:
            events.append({"event": "review", "task_id": review_id,
                           "for_task": task_id, "role": role_key})
        tester_reply = dispatch(team, role_key, collab_task, memory=memory, project_id=project_id)
        # 防链式扩散落点：这里刻意不再对 tester_reply 调 extract_collaboration。
        print(f"\n----- {role.name} 评审产出（{review_id}） -----\n{tester_reply}")

        verdict = extract_verdict(tester_reply)
        if verdict is None and TRUNCATION_MARK in tester_reply:
            # 截断冤杀防护（对称编码岗恢复，2026-09-28 运行_20260928_144543 实测暴露）：
            # 评审实测做完了但总结被掐断、结论丢失——给一次补发机会，
            # 只补结论与问题清单，不重跑测试；限一次，不无限重试。
            recover_task = (
                f"{review_id} 收尾补发：你的上一版评审产出被 max_tokens 截断，"
                f"【评审结论】信号已丢失。\n"
                f"不要重跑任何测试。请直接基于已完成的检查，仅补发两样：\n"
                f"1)【评审结论:通过/不通过】独占一行（不通过必须附编号问题清单）；\n"
                f"2) 一句话总评。"
            )
            if events is not None:
                events.append({"event": "truncation_recover", "task_id": review_id})
            tester_reply = dispatch(team, role_key, recover_task, memory=memory, project_id=project_id)
            print(f"\n----- {role.name} 评审产出（截断补发，{review_id}） -----\n{tester_reply}")
            verdict = extract_verdict(tester_reply)
        if verdict is None:
            # 契约即合同：交不出评审结论 = 产出不合契约，按不通过退回一次。
            # 问题清单由调度系统代拟——这本身就是要编码岗面对的"问题"。
            verdict = "不通过"
            tester_reply += "\n（调度系统注：评审岗未按输出契约给出结论，视为不通过）"

        if events is not None:
            events.append({"event": "verdict", "task_id": task_id, "verdict": verdict})

        if verdict == "通过":
            # 输入工作目相对目录和产出清单。获取规范后的绝对地址声明文件列表和缺失文件列表
            declared, missing = verify_delivery(workspace, coder_reply)
            if not declared:
                print(f"\n===== {task_id} 交付核验失败：产出未声明【交付清单】"
                      f"（契约违约），判失败 =====")
                print("----- 终止现场：编码岗最后产出 -----\n" + coder_reply)
                print("（将来增强：将缺失清单退回编码岗补齐——本版只终止并留现场）")
                if events is not None:
                    events.append({"event": "fail", "task_id": task_id,
                                   "stage": "交付核验",
                                   "reason": "未声明交付清单（契约违约）"})
                return None
            if missing:
                print(f"\n===== {task_id} 交付核验失败：声明 {len(declared)} 个文件，"
                      f"缺失 {missing}，判失败 =====")
                print("----- 终止现场：编码岗最后产出 -----\n" + coder_reply)
                if events is not None:
                    events.append({"event": "fail", "task_id": task_id,
                                   "stage": "交付核验",
                                   "reason": f"声明 {len(declared)} 个文件，缺失 {missing}"})
                return None
            print(f"\n===== 评审链闭环成功（{task_id}，退回 "
                  f"{reject_counts.get(task_id, 0)} 次，"
                  f"核验通过 {len(declared)} 个文件：{declared}）=====")
            if events is not None:
                events.append({"event": "verified", "task_id": task_id,
                               "declared": declared})
                events.append({"event": "done", "task_id": task_id,
                               "rejects": reject_counts.get(task_id, 0),
                               "declared": declared})
            return coder_reply

        # —— 不通过：决定是否退回 ——
        n = next_reject(reject_counts, task_id)
        if n is None:
            print(f"\n===== {task_id} 评审失败：退回超上限（>{MAX_REJECT} 次），终止 =====")
            print("----- 终止现场：编码岗最后产出 -----\n" + coder_reply)
            print("----- 终止现场：评审岗最后结论 -----\n" + tester_reply)
            print("（将来增强：LLM 重新拆解任务 / 人工介入通道——本版只终止并留现场）")
            if events is not None:
                events.append({"event": "fail", "task_id": task_id,
                               "stage": "评审",
                               "reason": f"退回超上限（>{MAX_REJECT} 次）"})
            return None
        if events is not None:
            events.append({"event": "reject", "task_id": task_id, "round": n})

        # 【自包含原则】退回任务 = 任务描述原文 + 原产出 + 问题清单（评审产出全文）+
        # 第 N 次退回（模型被通知，不自报）+ 环境事实。
        coder_task = (
            f"{task_id} 任务（第 {n} 次退回修改）：{task.description}\n"
            f"{coder_constraint}"
            f"你的上一版产出被评审不通过。上一版产出：\n{coder_reply}\n"
            f"评审结论与编号问题清单（逐条修正，不要重写全部）：\n{tester_reply}\n"
            f"请修正后用 write_file 覆盖写入 {workspace}/ 下的原相对路径文件，\n"
            f"产出末尾按【交付清单】格式重新声明。\n"
            f"完成后按输出契约再次请求评审：[请求协作:{role_key}] 请复审修正后的实现与交付文件。"
        )
        coder_reply = dispatch(team, "coder", coder_task, memory=memory, project_id=project_id)
        print(f"\n----- 编码岗产出（第 {n} 次退回后，{task_id}） -----\n{coder_reply}")


def plan_tasks(team: Team, requirement: str, events: list | None = None,
               memory: Memory = None, project_id: str = "demo") -> list[Task]:
    """调度决策入口：编制表 + 需求 → 调度岗 LLM → 任务表。

    这是"智能分工"的落点：调度岗是唯一能决定"拆几件、给谁做、谁审谁"的 LLM，
    它随需求收到团队编制表（Team.roster_text），只能用表里的岗位。
    契约违约抛 TaskTableError（raw=调度岗原始产出），调用方判失败终止。
    memory 不为 None 时调度岗会话同样按 (project_id, "scheduler") 持久并收尾沉淀，
    跨轮对话记忆对调度岗生效（问候/追问类需求依赖这一点）。"""
    role = team.get("scheduler")
    user_input = (
        f"当前团队编制：\n{team.roster_text()}\n\n"
        f"需求：{requirement}\n\n"
        f"请按输出契约拆解。"
    )
    params = CallParameters(
        api_key=ApiKeyPool.get_key(role.engine),
        base_url=API_BASE_URL,
        model=role.model,
        system_prompt=team.load_prompt(role),
        user_input=user_input,
        temperature=role.temperature,
        max_tokens=role.max_tokens,
        timeout=TIMEOUT,
        stream=False,
        context_mode="recent",
        context_window=10,     # 与 dispatch 同口径：跨轮保留最近 10 轮精炼记忆
    )
    if memory is None:
        session = ChatSession(params.system_prompt)
        reply = call_llm(params, session=session)
    else:
        session = memory.get_session(project_id, "scheduler", params.system_prompt)
        reply = call_llm(params, session=session)
        memory.settle(session)      # 任务收尾：中间消息丢弃，只沉淀「任务+产出」

    if not (reply or "").strip():
        # 空产出防护（2026-10-08 实测：账单 completion=639 但正文为空的 provider 行为）：
        # 不解析、不判违约，先给一次补发机会；仍空才走契约违约。
        params.user_input = (
            "系统提示：你上一轮的输出为空。请重新回应本需求："
            "问候/纯问答直接回答；工程需求按输出契约拆解成任务表。"
        )
        reply = call_llm(params, session=session)
        if memory is not None:
            memory.settle(session)

    if events is not None:
        events.append({"event": "plan", "raw": reply})
    return parse_task_table(reply, team)


def run_pipeline(team: Team, memory: Memory, project_id: str,
                 tasks: list[Task],
                 core_only: bool = True, collab: bool = True,
                 events: list | None = None) -> None:
    """任务表驱动的主线执行：按编号顺序执行非评审任务；
    有评审配对的走评审链，无配对的直发一次；
    声明了依赖的任务自动注入前置任务产出摘要（自包含原则的系统侧兜底）。

    工作区由本函数统一清零一次——多任务连续执行时，后任务不清前任务的盘。
    调度状态机仍是确定性代码：任务表取代的是过去写死的「任务#1/#2」两岗流水线。"""
    workspace = os.path.join("demo_out", project_id)
    shutil.rmtree(workspace, ignore_errors=True)   # 整条流水线一次清零
    os.makedirs(workspace, exist_ok=True)

    reviews = {t.review_of: t for t in tasks if t.review_of}
    prev_outputs: dict[int, str] = {}

    for task in sorted((t for t in tasks if not t.review_of), key=lambda t: t.num):
        desc = task.description
        if task.depends_on:
            deps_txt = "\n".join(
                f"任务#{m} 产出摘要：\n{prev_outputs.get(m, '（该前置任务无产出记录）')[:1500]}"
                for m in sorted(task.depends_on)
            )
            desc += f"\n\n前置任务产出（上下文参考）：\n{deps_txt}"
        exec_task = Task(id=task.id, num=task.num, role_key=task.role_key,
                         description=desc, deliverable=task.deliverable)
        review = reviews.get(task.id) if collab else None
        if events is not None:
            events.append({"event": "task_start", "task_id": task.id,
                           "role": task.role_key, "has_review": bool(review)})
        if review:
            out = run_review_chain(team, memory, project_id, exec_task, review,
                                   core_only=core_only, collab=collab,
                                   reset_workspace=False, events=events)
        else:
            reply = dispatch(team, task.role_key, desc, memory=memory, project_id=project_id)
            print(f"\n----- {team.get(task.role_key).name} 产出（{task.id}） -----\n{reply}")
            out = reply
        prev_outputs[task.num] = out or "（该任务未成功产出）"

