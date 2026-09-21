import os
import json
from dotenv import load_dotenv
from call_llm import CallParameters,ChatSession,call_llm

from skill.calculator.schemas import CALCULATOR_SCHEMA
from skill.calculator.tool import calculator
from skill.read_file.schemas import READFILE_SCHEMAS
from skill.read_file.tool import read_file
from skill.write_file.schemas import WRITEFILE_SCHEMAS
from skill.write_file.tool import write_file

script_dir = os.path.dirname(os.path.abspath(__file__))

env_path = os.path.join(script_dir,".env")
print("加载 '.env' ",end="")
print(f"{load_dotenv(env_path)}")

def answer(question: str, session: ChatSession,
           stream: bool = True,
           context_mode: str = "unlimited",
           context_window: int = 10) -> str:
    """RAG 问答：LLM 自行决定是否需要调用 query_knowledge 工具检索资料"""
    tools = [CALCULATOR_SCHEMA, READFILE_SCHEMAS, WRITEFILE_SCHEMAS]

    api_key = os.getenv("DEEPSEEK_OPENAI_API_KEY")
    if not api_key:
        raise ValueError("获取 DEEPSEEK_API_KEY 失败。请检查.env文件或系统环境变量设置")

    params = CallParameters(
        api_key=api_key,
        base_url= "https://api.deepseek.com",
        model="deepseek-flash",
        max_tokens = 4096,
        temperature = 0.4,
        system_prompt="",
        user_input=question,
        stream=stream,
        tools=tools,
        tool_map={
            "calculator": calculator,
            "read_file": read_file,
            "write_file": write_file,
        },
        context_mode=context_mode,
        context_window=context_window,
    )

    return call_llm(params, session=session)

def main():
    from prompts.get_prompt import get_prompt,PromptFileName
    system_prompt = get_prompt(PromptFileName.SCHEDULER)
    session = ChatSession(system_prompt)
    while True:
        user_input = input("你：")
        while not user_input:
            user_input = input("你：")
        if user_input.lower() in ("exit", "quit"):
            break
        elif user_input.lower() in ("showall",):
            print(f"\n\n{session.messages}")
            continue

        answer(user_input, session=session)
        print(f"\n{'=' * 40}\n")

if __name__ == "__main__":
    main()

