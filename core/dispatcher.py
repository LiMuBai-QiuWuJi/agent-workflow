from call_llm import CallParameters, ChatSession, call_llm, ApiKeyPool
from core.team import Team


def dispatch(team: Team, role_key: str, task_content: str) -> str:
    """把任务派给指定岗位：
    岗位的 system prompt = prompts/ 下的文件内容；
    岗位的调用参数       = Role 里的 model/temperature/max_tokens；
    岗位的 key           = ApiKeyPool 找 API key 的关键词。
    调度器不关心具体引擎是谁——它只认岗位。"""
    role = team.get(role_key)
    params = CallParameters(
        api_key=ApiKeyPool.get_key(role.engine),   # "deepseek" → 池中模糊命中 DEEPSEEK_OPENAI_API_KEY
        base_url="https://api.deepseek.com",
        model=role.model,
        system_prompt=team.load_prompt(role),
        user_input=task_content,
        temperature=role.temperature,
        max_tokens=role.max_tokens,
        stream=False,    # 演示阶段非流式，输出干净便于核对
    )
    session = ChatSession()   # 每次派发独立会话；Day 2 由 memory.py 换成按(工程,岗位)隔离
    return call_llm(params, session=session)


