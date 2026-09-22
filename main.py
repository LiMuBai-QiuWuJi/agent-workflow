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

import json

from call_llm import ApiKeyPool, CallParameters, ChatSession, USAGE_LOG, call_llm
from core.dispatcher import dispatch
from core.memory import Memory
from core.team import Team

PROJECT_ID = "demo"


def decompose(requirement: str) -> list[tuple[str, str]]:
    """固定拆成 编码 + 测试 两条。
    【自包含原则】任务描述里嵌入需求原文——执行岗只看得到自己岗的历史。"""
    return [
        ("coder",
         f"任务：{requirement}\n"
         f"请实现该需求对应的代码，并在产出末尾按【交付清单】格式声明生成的文件。"),
        ("tester",
         f"任务：针对以下需求，编写一份验收要点清单（供后续评审编码产出时使用）：{requirement}\n"
         f"要求：逐条列出功能正确性、边界情况两类检查点。"),
    ]


BATCH = [
    "写一个计算斐波那契数列第n项的函数, 并给出使用示例",
    "写一个快速排序函数，要求支持传入自定义比较函数",
    "写一个判断字符串是否为回文的函数，忽略大小写和非字母字符",
]


def demo_isolation(team: Team, memory: Memory) -> None:
    """演示 1,岗位独立记忆——同岗历史逐轮累积,两岗互不可见。"""
    print("===== 演示 1: 岗位独立记忆 =====")
    for round_no in (1, 2):
        for role_key, task in decompose(BATCH[0]):
            reply = dispatch(team, role_key, task, memory=memory, project_id=PROJECT_ID)
            print(f"[第{round_no}轮] {role_key} 产出 {len(reply)} 字")

    coder_msgs = memory.sessions[(PROJECT_ID, "coder")].messages
    tester_msgs = memory.sessions[(PROJECT_ID, "tester")].messages
    print(f"\n编码岗历史 {len(coder_msgs)} 条，测试岗历史 {len(tester_msgs)} 条")

    # 互不可见探针：测试岗的历史里不该出现编码岗的产出特征。
    # 注意：需求原文不能当探针——测试岗自己的任务文本里也嵌了需求原文（自包含原则），
    #      用编码岗产出才有的【交付清单】当探针才不会误报。
    tester_all = "".join(m.get("content", "") for m in tester_msgs)
    assert "【交付清单】" not in tester_all, "Error: 测试岗看到了编码岗的历史!!!!!!!"
    print("互不可见校验通过：测试岗历史中没有编码岗产出的【交付清单】")

    # 换工程id = 全新记忆（多工程隔离的最小验证）
    other = memory.get_session("另一个工程", "coder", "system")
    print(f"换工程id后编码岗历史 {len(other.messages)} 条（应只有 system 这 1 条）")


def run_isolated(team: Team) -> int:
    """每岗一份记忆, 滑动窗口 recent=10, 任务收尾只沉淀「任务+产出」。"""
    memory = Memory()
    USAGE_LOG.clear()
    for requirement in BATCH:
        for role_key, task in decompose(requirement):
            dispatch(team, role_key, task, memory=memory, project_id=PROJECT_ID)
    return sum(u["prompt"] for u in USAGE_LOG)


def run_shared(team: Team) -> int:
    """所有岗位共用一份 messages, 历史只累加不清除、不做任何截断。"""
    shared = ChatSession("你们是共用一份历史的团队成员。")
    USAGE_LOG.clear()
    for requirement in BATCH:
        for role_key, task in decompose(requirement):
            role = team.get(role_key)
            params = CallParameters(
                api_key=ApiKeyPool.get_key(role.engine),
                base_url="https://api.deepseek.com",
                model=role.model,
                system_prompt="",
                user_input=task,
                temperature=role.temperature,
                max_tokens=role.max_tokens,
                stream=False,
                context_mode="unlimited",  # 全量发送
            )
            call_llm(params, session=shared)
    return sum(u["prompt"] for u in USAGE_LOG)


def main() -> None:
    team = Team.seed_builtin()
    memory = Memory()
    demo_isolation(team, memory)

    print("\n===== 演示 2：token 对比（同批任务 × 两种形态）=====")
    isolated_total = run_isolated(team)
    shared_total = run_shared(team)
    print(f"\n独立记忆（新形态）：6 次调用 prompt 合计 {isolated_total} tokens")
    print(f"共享历史（旧形态）：6 次调用 prompt 合计 {shared_total} tokens")
    print(f"共享/独立 = {shared_total / max(isolated_total, 1):.2f} 倍")
    print("明细账单：" + json.dumps(USAGE_LOG, ensure_ascii=False))


if __name__ == "__main__":
    main()