from call_llm import CallParameters, ChatSession, call_llm, ApiKeyPool
from core.memory import Memory
from core.team import Team


def dispatch(team: Team, role_key: str, task_content: str,
             memory: Memory = None, project_id: str = "demo") -> str:
    """把任务派给指定岗位：
    岗位的 system prompt = prompts/prompt_file/ 下的文件内容；
    岗位的调用参数 = Role 里的 model/temperature/max_tokens;
    岗位的 key = ApiKeyPool 找 API key 的关键词。
    新增: memory 不为 None 时，会话按 (project_id, role_key) 持久并收尾沉淀；
    memory 为 None 时保持 Day 1 行为——单任务会话（兼容旧调用）。"""
    role = team.get(role_key)
    params = CallParameters(
        api_key=ApiKeyPool.get_key(role.engine),
        base_url="https://api.deepseek.com",
        model=role.model,
        system_prompt=team.load_prompt(role),
        user_input=task_content,
        temperature=role.temperature,
        max_tokens=role.max_tokens,
        stream=False,          # 演示阶段非流式，输出干净便于核对
        context_mode="recent", # Day 2 打开滑动窗口：发送前只保留最近 context_window 轮历史
        context_window=10,     # 默认 10 轮（一轮 = user + assistant）
    )
    if memory is None:
        session = ChatSession(params.system_prompt)
        return call_llm(params, session=session)
    session = memory.get_session(project_id, role_key, params.system_prompt)
    reply = call_llm(params, session=session)
    memory.settle(session)      # 任务收尾：中间消息丢弃，只沉淀「任务+产出」
    return reply
