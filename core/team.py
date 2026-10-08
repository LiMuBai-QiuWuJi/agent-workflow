from prompts.get_prompt import PromptFileName,get_prompt_path
from dataclasses import dataclass, field
from typing import Callable
import os

script_dir = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(script_dir)   # team.py 在 core/ 下，项目根目录是上一层


@dataclass
class Role:
    """岗位 = 组织编制的一条记录。注意：本类不创建任何 LLM 客户端，
    engine 只是配置字符串——这就是"岗位-模型解耦"的落点。"""
    key: str            # 岗位唯一标识，调度/任务引用它："coder" / "tester"
    name: str           # 显示名："编码岗" / "测试岗"（日志、名片用）
    duty: str           # 一句话职责（调度器日志用；完整 prompt 在 prompt_name 文件里）
    prompt_name: PromptFileName    # system prompt 文件路径（相对项目根目录）
    engine: str         # 引擎标识："deepseek" —— ApiKeyPool.get_key() 靠它找 key
    model: str          # 具体模型名："deepseek-flash"
    temperature: float = 0.4
    max_tokens: int = 4096
    tools: list[dict] = field(default_factory=list)
    tool_choice: str = "auto"
    tool_map: dict[str, Callable] = field(default_factory=dict)


class Team:
    """编制 = 若干岗位的登记表。所有"岗位长什么样"的知识只存在这里。"""

    def __init__(self):
        self.roles: dict[str, Role] = {}

    def add_role(self, role: Role) -> None:
        if role.key in self.roles:
            raise ValueError(f"岗位 key 重复：{role.key}")
        self.roles[role.key] = role

    def get(self, key: str) -> Role:
        if key not in self.roles:
            raise KeyError(f"岗位不存在：{key}（现有岗位：{list(self.roles)}）")
        return self.roles[key]

    def load_prompt(self, role: Role) -> str:
        """读岗位的 system prompt 文件。资产在文件里，不在代码里。"""
        path = os.path.join(PROJECT_ROOT, get_prompt_path(role.prompt_name))
        # print(f"{path}")
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def roster_text(self) -> str:
        """编制表文本：调度岗看到的"团队有哪些岗位、各岗干什么"的唯一出处。
        调度岗自己不进表——它不能被派活。"""
        return "\n".join(
            f"- {r.key}（{r.name}）：{r.duty}"
            for r in self.roles.values() if r.key != "scheduler"
        )

    @classmethod
    def seed_builtin(cls) -> "Team":
        """播种内置编制：编码岗 + 测试岗。"""
        from skill.calculator.schemas import CALCULATOR_SCHEMA
        from skill.calculator.tool import calculator
        from skill.read_file.schemas import READFILE_SCHEMAS
        from skill.read_file.tool import read_file
        from skill.write_file.schemas import WRITEFILE_SCHEMAS
        from skill.write_file.tool import write_file
        from skill.run_cmd.schemas import RUNCMD_SCHEMAS
        from skill.run_cmd.tool import run_cmd

        team = cls()
        team.add_role(Role(
            key="coder", name="编码岗",
            duty="按任务描述实现代码，产出末尾声明交付文件",
            prompt_name=PromptFileName.CODER,
            engine="deepseek", model="deepseek-flash",
            temperature=0.4,
            max_tokens=8192,   # 重写大文件时 4096 会撞截断：参数 JSON 被掐断 + 信号发不出（2026-09-28 实测）
            tools=[CALCULATOR_SCHEMA, WRITEFILE_SCHEMAS],
            tool_choice="auto",
            tool_map={
                "calculator": calculator,
                "write_file": write_file,
            }
        ))
        team.add_role(Role(
            key="tester", name="测试岗",
            duty="审查编码岗产出，输出【评审结论:通过/不通过】",
            prompt_name=PromptFileName.TESTER,
            engine="deepseek", model="deepseek-flash",
            temperature=0.2,   # 评审要稳，温度调低
            max_tokens=8192,   # 评审跑实测+写编号问题清单，4096 撞截断丢结论（2026-09-28 运行_20260928_144543 实测）
            tools=[CALCULATOR_SCHEMA, READFILE_SCHEMAS,RUNCMD_SCHEMAS],
            tool_choice="auto",
            tool_map={
                "calculator": calculator,
                "read_file": read_file,
                "run_cmd":run_cmd
            }
        ))
        team.add_role(Role(
            key="assistant", name="助理岗",
            duty="读取并分析指定资料/文件并直接输出结论（只读，无交付物）",
            prompt_name=PromptFileName.ASSISTANT,
            engine="deepseek", model="deepseek-flash",
            temperature=0.3,
            max_tokens=8192,   # 全文分析类产出常超 4096（2026-10-08 实测 4098 撞截断）；截断补发兜底仍在
            tools=[CALCULATOR_SCHEMA, READFILE_SCHEMAS],   # 只读权限：不给 write_file / run_cmd
            tool_choice="auto",
            tool_map={
                "calculator": calculator,
                "read_file": read_file,
            }
        ))
        team.add_role(Role(
            key="scheduler", name="调度岗",
            duty="拆解需求为子任务并定岗位（管理岗，不执行具体工作）",
            prompt_name=PromptFileName.SCHEDULER,
            engine="deepseek", model="deepseek-flash",
            temperature=0.2,   # 拆解决策要稳
            max_tokens=4096,
            tools=[],          # 调度岗不碰工具：它只产出任务表
            tool_choice="auto",
            tool_map={}
        ))
        return team
