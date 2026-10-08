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


def log_usage(model: str, usage) -> None:
    """记录一次调用的 token 消耗（流式/非流式共用出口）。"""
    if usage is None:
        return
    USAGE_LOG.append({
        "model": model,
        "prompt": usage.prompt_tokens,
        "completion": usage.completion_tokens,
    })


def usage_summary(since: int = 0) -> dict:
    """累计账单：USAGE_LOG[since:] 的调用次数与 prompt/completion 合计。

    since 用于 Web 长驻进程按"本轮运行"统计（服务器启动以来日志不清空）。"""
    items = USAGE_LOG[since:]
    return {
        "calls": len(items),
        "prompt": sum(u["prompt"] for u in items),
        "completion": sum(u["completion"] for u in items),
    }

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
    max_tool_rounds: int = 15
    """工具调用轮数上限：超限后回灌"轮数用尽"提示并强制模型收尾，假完成交给交付核验兜"""

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
    finish_reason = None
    usage = None
    model = ""

    for chunk in response:
        if chunk.usage is not None:
            # stream_options=include_usage 的汇总块（最后一个 chunk）
            usage = chunk.usage
        if chunk.model:
            model = chunk.model
        if not chunk.choices:
            continue            # usage-only 块：正文与工具已收完
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
            finish_reason = chunk.choices[0].finish_reason
            # 不 break：usage 汇总块还在流后面，提前退出会丢账单

    log_usage(model, usage)

    if finish_reason == "length":
        # 截断感知：finish_reason=="length" = 被 max_tokens 掐断，不是"模型没话说"
        assistant_content += TRUNCATION_MARK
        print(TRUNCATION_MARK)

    msg_dict = {"role": "assistant", "content": assistant_content}
    has_tools = len(accumulated_tool_calls) > 0
    if has_tools:
        msg_dict["tool_calls"] = [
            accumulated_tool_calls[i] for i in sorted(accumulated_tool_calls.keys())
        ]
    return msg_dict, has_tools


def _extract_nonstream(response: ChatCompletion) -> tuple[dict, bool]:
    log_usage(response.model, response.usage)
    msg = response.choices[0].message
    msg_dict = msg.model_dump(exclude_none=True)
    if response.choices[0].finish_reason == "length":
        # 截断感知：被 max_tokens 掐断时打标记，让调度层区分"没话说"与"被掐断"
        msg_dict["content"] = (msg_dict.get("content") or "") + TRUNCATION_MARK
    has_tools = msg.tool_calls is not None and len(msg.tool_calls) > 0
    if has_tools:
        print(f"DeepSeek: [调用工具 {len(msg.tool_calls)} 个]")
    else:
        print(f"DeepSeek: {msg_dict.get('content', '')}")
    return msg_dict, has_tools


TRUNCATION_MARK = "（输出被 max_tokens 截断）"
"""截断标记：finish_reason=="length" 时追加到产出末尾，供调度层识别"被掐断"并触发补发。"""


def call_llm(parameters: CallParameters, session: ChatSession = None) -> str:
    client = OpenAI(api_key=parameters.api_key, base_url=parameters.base_url)

    if session is None:
        session = ChatSession(parameters.system_prompt)

    session.add_user(parameters.user_input)
    final_reply = ""

    def _request_once() -> tuple[dict, bool]:
        """发一次聊天请求并统一抽取结果（流式/非流式共用出口）。"""
        msgs = session.get_messages_for_request(parameters)
        create_kwargs = dict(
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
            # 让最后一个 chunk 携带 usage 汇总（token 账单流式路径也要记）
            create_kwargs["stream_options"] = {"include_usage": True}
        response = client.chat.completions.create(**create_kwargs)
        if parameters.stream:
            print("DeepSeek: ", end="", flush=True)
            msg_dict, has_tools = _extract_stream(response)
            print()
        else:
            msg_dict, has_tools = _extract_nonstream(response)
        return msg_dict, has_tools

    for attempt in range(parameters.retries):
        try:
            tool_rounds = 0
            while True:
                msg_dict, has_tools = _request_once()

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
                        # 参数 JSON 不完整多半是输出撞 max_tokens 被掐断在参数中间：
                        # 不能静默按空参执行（会假成功/误调用），把截断作为错误回灌让模型缩小输出重来
                        result = {"status": "error",
                                  "message": f"工具 {func_name} 参数 JSON 解析失败：参数可能被 max_tokens 截断。"
                                             "请缩小单次输出（分段写入/精简参数）后重试"}
                        print(f"工具调用：{func_name}(参数 JSON 解析失败，按截断错误回灌)")
                        session.add_tools(
                            tool_call_id=tc["id"],
                            content=json.dumps(result, ensure_ascii=False),
                        )
                        continue

                    print(f"工具调用：{func_name}({args})")
                    if func_name in parameters.tool_map:
                        try:
                            result = parameters.tool_map[func_name](**args)
                        except Exception as e:
                            result = {"status":"error","message":f"工具执行失败：{type(e).__name__}: {e}"}
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

                tool_rounds += 1
                if tool_rounds >= parameters.max_tool_rounds:
                    # 工具轮数上限：回灌收尾提示，逼模型用剩余预算给结论；
                    # 若仍假装调工具/不给结论，交付核验会判假完成
                    session.add_user(
                        f"系统提示：工具调用已达 {parameters.max_tool_rounds} 轮上限。"
                        "请停止调用工具，基于已获得的结果立即给出最终结论。"
                    )
                    final_dict, _ = _request_once()
                    session.add_assistant(msg_dict=final_dict)
                    final_reply = final_dict.get("content", "") or "（工具轮数用尽，模型未给出文字结论）"
                    break

            if TRUNCATION_MARK in final_reply:
                # 截断补发（同轮内部闭环）：最终输出被 max_tokens 掐断时，
                # 立刻要一次短回复把结论与契约信号补回来.限一次。
                # 返回值 = 前半全文 + 补发段拼接（不丢中段）：
                # 回执、评审任务文本都依赖这个返回值，只回补发段会把主分析撕掉。
                truncated_part = final_reply.replace(TRUNCATION_MARK, "")
                session.add_user(
                    "系统提示：你的上一段输出被 max_tokens 截断。不要重复前文，"
                    "只补发最终结论与契约信号（【交付清单】/[请求协作:岗位key]），尽量精简。"
                )
                final_dict, _ = _request_once()
                session.add_assistant(msg_dict=final_dict)
                recovery = final_dict.get("content", "")
                if recovery.strip():
                    final_reply = (truncated_part + "\n" + recovery).strip()
                # recovery 也为空时保留带截断标记的原返回值，交由上层判失败

            return final_reply

        except Exception as e:
            print(f"第 {attempt + 1} 次调用失败：{e}")
            if attempt < parameters.retries - 1:
                # 指数退避：2s → 4s → 8s……API 抖动期固定 2s 连撞三次全超时（2026-09-28 实测）
                time.sleep(parameters.retries_delay_s * (2 ** attempt))

    raise RuntimeError(f"{parameters.retries} 次重试失败")
