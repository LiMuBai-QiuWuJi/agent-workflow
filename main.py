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

from core.team import Team
from core.dispatcher import dispatch

def decompose(requirement: str) -> list[tuple[str, str]]:
    return [
        ("coder",
         f"任务：{requirement}\n"
         f"请实现该需求对应的代码，并在产出末尾按【交付清单】格式声明生成的文件。"),
        ("tester",
         f"任务：针对以下需求，编写一份验收要点清单（供后续评审编码产出时使用）：{requirement}\n"
         f"要求：逐条列出功能正确性、边界情况两类检查点。"),
    ]


def main() -> None:
    requirement = input("需求：")
    team = Team.seed_builtin()

    print(f"编制：{[(r.key, r.name) for r in team.roles.values()]}")
    for role_key, task in decompose(requirement):
        role = team.get(role_key)
        print(f"\n===== 派单 → {role.name}（engine={role.engine}, model={role.model}, T={role.temperature}）=====")
        reply = dispatch(team, role_key, task)
        print(f"\n----- {role.name} 产出 -----\n{reply}")


if __name__ == "__main__":
    main()
