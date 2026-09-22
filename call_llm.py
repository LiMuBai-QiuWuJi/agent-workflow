import json
import os
import time
from dataclasses import dataclass, field
from typing import Callable
from openai import OpenAI, Stream
from openai.types.chat import ChatCompletionChunk
from openai.types.chat import ChatCompletion

script_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(script_dir, ".env")

USAGE_LOG: list[dict] = []
"""token 账单：每次成功调用的 {model, prompt, completion}，供对比实验汇总。"""

class ApiKeyPool:
    """API Key 池：首次调用 get_key 时扫描 .env 与环境变量中所有含 API_KEY 的条目，
    键名统一大写建索引；之后一律走内存，不再读文件。"""

    _pool: dict[str, str] | None = None   # {大写键名: 值}

    @classmethod
    def _ensure_loaded(cls) -> None:
        if cls._pool is not None:
            return
        from dotenv import dotenv_values
        entries: dict[str, str] = {}
        if os.path.exists(env_path):
            entries.update(dotenv_values(env_path))   # .env 打底
        for name, value in os.environ.items():         # 环境变量覆盖同名项
            if value:
                entries[name] = value
        cls._pool = {
            name.upper(): value
            for name, value in entries.items()
            if "API_KEY" in name.upper() and value
        }

    @classmethod
    def get_key(cls, key_name: str = "") -> str:
        cls._ensure_loaded()
        query = key_name.strip().upper()
        if query:
            if query in cls._pool:                     # ① 全名命中（大小写不敏感）
                return cls._pool[query]
            matches = [(k, v) for k, v in cls._pool.items() if query in k]  # ② 模糊包含
            if len(matches) == 1:
                return matches[0][1]
            if not matches:
                raise KeyError(f"未找到含 {key_name!r} 的 API_KEY（池中现有：{list(cls._pool)}）")
            raise KeyError(f"{key_name!r} 匹配到多个 {[k for k, _ in matches]}，请写更完整的 key_name")
        if len(cls._pool) == 1:                        # ③ 空参且池中只有一个
            return next(iter(cls._pool.values()))
        raise ValueError(f"池中有 {len(cls._pool)} 个 key，请指定 key_name：{list(cls._pool)}")


@dataclass
class CallParameters:
    api_key: str = ""
    base_url: str = ""
    model: str = ""

    system_prompt: str = ""
    user_input: str = ""

    max_tokens: int = 4096
    temperature: float = 0.7
    timeout: float = 30.0
    stream: bool = True

    tools: list[dict] = field(default_factory=list)
    tool_choice: str = "auto"
    tool_map: dict[str, Callable] = field(default_factory=dict)

    context_mode: str = "none"
    """none | recent | unlimited  —— 无历史 | 最近 N 轮 | 无限上下文"""
    context_window: int = 10
    """recent 模式时保留最近 N 轮对话（一轮 = user + assistant[+tools]）"""

    retries: int = 3
    retries_delay_s: int = 2


class ChatSession:
    def __init__(self, content: str = ""):
        self.messages = []
        self._round_start_idx = 0
        if content:
            self.add_system(content)

    def add_system(self, content: str = ""):
        self.messages.append({"role": "system", "content": content})

    def add_user(self, content: str = ""):
        self.messages.append({"role": "user", "content": content})
        self._round_start_idx = len(self.messages) - 1

    def add_assistant(self, content: str = "", msg_dict: dict = None):
        if msg_dict is None:
            self.messages.append({"role": "assistant", "content": content})
        else:
            self.messages.append(msg_dict)

    def add_tools(self, tool_call_id: str = "", content: str = ""):
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content,
        })

    def get_messages_for_request(self, parameters: CallParameters):
        """
        根据 context_mode 返回待发送的消息列表。
        system 消息始终保留；当前轮次（从最后一次 add_user 开始）始终保留，
        以保证同一次 call_llm 内部的工具调用链完整。
        """
        system_msgs = [m for m in self.messages if m["role"] == "system"]
        current_round = self.messages[self._round_start_idx:]

        if parameters.context_mode == "none":
            return system_msgs + current_round

        if parameters.context_mode == "unlimited":
            return self.messages

        if parameters.context_mode == "recent":
            historical = self.messages[:self._round_start_idx]
            historical_non_system = [m for m in historical if m["role"] != "system"]
            user_indices = [
                i for i, m in enumerate(historical_non_system) if m["role"] == "user"
            ]
            n_hist = parameters.context_window - 1
            if len(user_indices) <= n_hist or n_hist < 0:
                kept = historical_non_system
            else:
                cutoff = user_indices[-n_hist]
                kept = historical_non_system[cutoff:]
            return system_msgs + kept + current_round

        return self.messages


def _extract_stream(response: Stream[ChatCompletionChunk]) -> tuple[dict, bool]:
    assistant_content = ""
    accumulated_tool_calls = {}

    for chunk in response:
        delta = chunk.choices[0].delta

        if delta.content:
            assistant_content += delta.content
            print(delta.content, end="", flush=True)

        if delta.tool_calls:
            for tc in delta.tool_calls:
                idx = tc.index
                if idx not in accumulated_tool_calls:
                    accumulated_tool_calls[idx] = {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": "", "arguments": ""}
                    }
                if tc.function:
                    if tc.function.name:
                        accumulated_tool_calls[idx]["function"]["name"] = tc.function.name
                    if tc.function.arguments:
                        accumulated_tool_calls[idx]["function"]["arguments"] += tc.function.arguments

        if chunk.choices[0].finish_reason is not None:
            break

    msg_dict = {"role": "assistant", "content": assistant_content}
    has_tools = len(accumulated_tool_calls) > 0
    if has_tools:
        msg_dict["tool_calls"] = [
            accumulated_tool_calls[i] for i in sorted(accumulated_tool_calls.keys())
        ]
    return msg_dict, has_tools


def _extract_nonstream(response: ChatCompletion) -> tuple[dict, bool]:
    if response.usage is not None:
            USAGE_LOG.append({
                "model": response.model,
                "prompt": response.usage.prompt_tokens,
                "completion": response.usage.completion_tokens,
            })
    msg = response.choices[0].message
    msg_dict = msg.model_dump(exclude_none=True)
    has_tools = msg.tool_calls is not None and len(msg.tool_calls) > 0
    if has_tools:
        print(f"DeepSeek: [调用工具 {len(msg.tool_calls)} 个]")
    else:
        print(f"DeepSeek: {msg_dict.get('content', '')}")
    return msg_dict, has_tools


def call_llm(parameters: CallParameters, session: ChatSession = None) -> str:
    client = OpenAI(api_key=parameters.api_key, base_url=parameters.base_url)

    if session is None:
        session = ChatSession(parameters.system_prompt)

    session.add_user(parameters.user_input)
    final_reply = ""

    for attempt in range(parameters.retries):
        try:
            while True:
                msgs = session.get_messages_for_request(parameters)

                response = client.chat.completions.create(
                    model=parameters.model,
                    messages=msgs,
                    max_tokens=parameters.max_tokens,
                    temperature=parameters.temperature,
                    timeout=parameters.timeout,
                    stream=parameters.stream,
                    tools=parameters.tools,
                    tool_choice=parameters.tool_choice,
                )

                if parameters.stream:
                    print("DeepSeek: ", end="", flush=True)
                    msg_dict, has_tools = _extract_stream(response)
                    print()
                else:
                    msg_dict, has_tools = _extract_nonstream(response)

                session.add_assistant(msg_dict=msg_dict)

                if not has_tools:
                    final_reply = msg_dict.get("content", "")
                    break

                for tc in msg_dict.get("tool_calls", []):
                    func_name = tc["function"]["name"]
                    args_str = tc["function"]["arguments"]
                    try:
                        args = json.loads(args_str)
                    except json.JSONDecodeError:
                        args = {}

                    print(f"工具调用：{func_name}({args})")
                    if func_name in parameters.tool_map:
                        result = parameters.tool_map[func_name](**args)
                    else:
                        result = {"status": "error", "message": f"未知工具：{func_name}"}

                    if isinstance(result, str):
                        tool_content = result
                    else:
                        tool_content = json.dumps(result, ensure_ascii=False)

                    session.add_tools(
                        tool_call_id=tc["id"],
                        content=tool_content,
                    )

            return final_reply

        except Exception as e:
            print(f"第 {attempt + 1} 次调用失败：{e}")
            if attempt < parameters.retries - 1:
                time.sleep(parameters.retries_delay_s)

    raise RuntimeError(f"{parameters.retries} 次重试失败")
