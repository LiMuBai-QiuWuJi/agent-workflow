from call_llm import ChatSession


class Memory:
    """岗位独立记忆: key = (工程id, 岗位key) → 该岗位专属的 ChatSession。"""

    def __init__(self):
        self.sessions: dict[tuple[str, str], ChatSession] = {}

    def get_session(self, project_id: str, role_key: str,
                    system_prompt: str = "") -> ChatSession:
        """取某工程下某岗位的会话；第一次调用时连 system prompt 一起建档。"""
        key = (project_id, role_key)
        if key not in self.sessions:
            session = ChatSession(system_prompt)   # 建档时把岗位行为手册放进 system 消息
            self.sessions[key] = session
            return session
        return self.sessions[key]

    @staticmethod
    def settle(session: ChatSession) -> None:
        """任务收尾：丢弃工具循环的中间消息，只留「任务 + 最终产出」。"""
        session.messages = [
            m for m in session.messages
            if m["role"] != "tool" and "tool_calls" not in m
        ]
