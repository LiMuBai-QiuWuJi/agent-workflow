# -*- coding: utf-8 -*-
"""core/task_table.py —— 调度岗产出 → 任务表：解析、校验、契约违约即失败。

调度岗（scheduler）是唯一做"分工决策"的 LLM：需求 + 编制表 → 任务表。
本模块把它的自然语言产出解析成确定性 Task 列表；任何契约违约
（岗位不存在 / 编号不连续 / 评审对象缺失 / 依赖悬空 / 输出无法拆解）
都抛 TaskTableError，raw 里带完整现场，由调用方判失败终止。
"""
import re
from dataclasses import dataclass, field


class TaskTableError(Exception):
    """任务表契约违约。raw = 调度岗原始产出（失败现场）。"""

    def __init__(self, reason: str, raw: str):
        self.reason = reason
        self.raw = raw
        super().__init__(f"{reason}\n----- 调度岗原始产出 -----\n{raw}")


class DirectReply(Exception):
    """调度岗判断输入无需拆解（问候/自我介绍/纯问答），直接给用户应答。
    不是失败：系统把 answer 原样转告用户，不进任务表。"""

    def __init__(self, answer: str):
        self.answer = answer.strip()
        super().__init__(self.answer)


@dataclass
class Task:
    """任务表中的一行。id 恒为「任务#N」（解析时归一化，不信模型的字面编号）。"""
    id: str                  # "任务#1"
    num: int                 # 1（排序、依赖校验用）
    role_key: str            # 岗位 key，必须来自编制表
    description: str         # 自包含任务描述（评审标记与交付声明已剥离）
    review_of: str | None = None   # "[评审 任务#N]" → 被评审任务的 id
    deliverable: str = ""          # "；交付：xxx" → 核心交付物文件名
    depends_on: list[int] = field(default_factory=list)  # 依赖的前置任务 num 列表


TASK_RE = re.compile(r"^任务#(\d+)\s*\[岗位:([A-Za-z_\-]+)\]\s*(?P<body>.*)$")
REVIEW_RE = re.compile(r"\[评审\s*任务#(\d+)\]")
DELIVER_RE = re.compile(r"；?交付[:：]\s*([^\s；。]+)")
STANDALONE_DELIVER_RE = re.compile(r"^交付[:：]\s*([^\s；。]+)")
"""交付声明独立成行：调度岗把「本任务适用规则」附在任务描述后时，
交付声明常被挤到任务行之外的下一行（2026-10-08 实测：贪吃蛇交付声明漏解析，
产出型任务被误当分析型，触发假回执与假总结）。归属 = 最近一个还没有交付声明的非评审任务。"""
DEP_RE = re.compile(r"^依赖[:：]\s*任务#(\d+)\s*←\s*任务#(\d+)\s*$")
NO_DECOMPOSE_RE = re.compile(r"无法拆解[:：]\s*(?P<why>.+)")
DIRECT_RE = re.compile(r"直接回复[:：]\s*(?P<answer>.+)", re.S)


def parse_task_table(reply: str, team) -> list[Task]:
    """解析调度岗产出为任务表。team 只用于校验岗位 key 存在于编制表。

    三种合法出口：任务表 / DirectReply（无需拆解的直接应答）/ TaskTableError（违约）。"""
    raw = reply or ""
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]

    direct = DIRECT_RE.search(raw)
    if direct:
        raise DirectReply(direct.group("answer"))

    no = NO_DECOMPOSE_RE.search(raw)
    if no:
        raise TaskTableError(f"调度岗判断需求无法拆解：{no.group('why').strip()}", raw)

    tasks: list[Task] = []
    for ln in lines:
        m = TASK_RE.match(ln)
        if not m:
            continue
        num = int(m.group(1))
        role_key = m.group(2).strip()
        body = m.group("body").strip()

        review_of = None
        rv = REVIEW_RE.search(body)
        if rv:
            review_of = f"任务#{rv.group(1)}"
            body = REVIEW_RE.sub("", body).strip()

        deliverable = ""
        dv = DELIVER_RE.search(body)
        if dv:
            deliverable = dv.group(1).strip()
            body = DELIVER_RE.sub("", body).strip("；; ")

        tasks.append(Task(id=f"任务#{num}", num=num, role_key=role_key,
                          description=body, review_of=review_of,
                          deliverable=deliverable))

    if not tasks:
        raise TaskTableError("产出中解析不到任何「任务#N [岗位:xxx]」行", raw)

    # —— 校验：编号连续（1..N，不缺不重）——
    nums = [t.num for t in tasks]
    if sorted(nums) != list(range(1, len(tasks) + 1)):
        raise TaskTableError(f"任务编号必须连续（实际：{sorted(nums)}）", raw)

    # —— 校验：岗位必须来自编制表（这是"分工"的真实边界）——
    for t in tasks:
        try:
            team.get(t.role_key)
        except KeyError as e:
            raise TaskTableError(f"{t.id} 指定了编制表之外的岗位：{e}", raw)

    # —— 校验：评审对象必须存在 ——
    id_set = {t.id for t in tasks}
    for t in tasks:
        if t.review_of and t.review_of not in id_set:
            raise TaskTableError(f"{t.id} 是评审任务，但被评审对象 {t.review_of} 不在任务表中", raw)

    # —— 交付声明独立成行：归并进最近一个没有交付声明的非评审任务 ——
    for ln in lines:
        m = STANDALONE_DELIVER_RE.match(ln)
        if not m:
            continue
        target = next((t for t in reversed(tasks)
                       if not t.deliverable and not t.review_of), None)
        if target is not None:
            target.deliverable = m.group(1).strip()

    # —— 依赖行：解析进对应任务并校验（只允许依赖编号更小的任务）——
    for ln in lines:
        m = DEP_RE.match(ln)
        if not m:
            continue
        dependent, target = int(m.group(1)), int(m.group(2))
        if dependent not in nums or target not in nums:
            raise TaskTableError(f"依赖行指向不存在的任务：{ln}", raw)
        if dependent <= target:
            raise TaskTableError(f"依赖必须指向编号更小的前置任务（{ln}）", raw)
        next(t for t in tasks if t.num == dependent).depends_on.append(target)

    return tasks
