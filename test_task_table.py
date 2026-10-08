# -*- coding: utf-8 -*-
"""test_task_table.py —— 任务表解析器确定性测试：不发 LLM，零 API 消耗。
用法：在项目根目录运行 python test_task_table.py"""
from core.task_table import DirectReply, TaskTableError, parse_task_table


class FakeRole:
    def __init__(self, key):
        self.key = key
        self.name = key
        self.duty = ""


class FakeTeam:
    """只校验岗位 key 是否存在于编制表。"""
    def get(self, key):
        if key not in ("coder", "tester"):
            raise KeyError(f"岗位不存在：{key}（现有岗位：['coder', 'tester']）")
        return FakeRole(key)


VALID = """【任务拆解】
任务#1 [岗位:coder] 实现斐波那契数列函数并自测；交付：fib.py
任务#2 [岗位:tester] [评审 任务#1] 重点审查边界 n<=0 的处理
依赖：任务#2 ← 任务#1
"""


def scenario_valid():
    tasks = parse_task_table(VALID, FakeTeam())
    assert len(tasks) == 2
    t1, t2 = tasks
    assert t1.id == "任务#1" and t1.role_key == "coder"
    assert t1.deliverable == "fib.py"
    assert "[评审" not in t1.description and "交付：" not in t1.description
    assert t2.review_of == "任务#1"
    assert t1.depends_on == [] and t2.depends_on == [1]
    print("场景 1 通过：合法任务表解析正确（交付声明与评审标记从描述剥离）")


def scenario_unknown_role():
    bad = VALID.replace("[岗位:tester]", "[岗位:designer]")
    try:
        parse_task_table(bad, FakeTeam())
    except TaskTableError as e:
        assert "编制表之外" in e.reason
        print("场景 2 通过：编制表之外的岗位被契约违约拦下")
    else:
        raise AssertionError("未知岗位竟然解析通过")


def scenario_non_sequential_ids():
    bad = VALID.replace("任务#2", "任务#3")
    try:
        parse_task_table(bad, FakeTeam())
    except TaskTableError as e:
        assert "连续" in e.reason
        print("场景 3 通过：编号不连续被拦下")
    else:
        raise AssertionError("断号任务表竟然解析通过")


def scenario_review_target_missing():
    bad = VALID.replace("[评审 任务#1]", "[评审 任务#9]")
    try:
        parse_task_table(bad, FakeTeam())
    except TaskTableError as e:
        assert "被评审对象" in e.reason
        print("场景 4 通过：悬空评审对象被拦下")
    else:
        raise AssertionError("悬空评审竟然解析通过")


def scenario_no_decompose():
    bad = "无法拆解：纯问答需求，无代码交付物"
    try:
        parse_task_table(bad, FakeTeam())
    except TaskTableError as e:
        assert "无法拆解" in e.reason
        print("场景 5 通过：调度岗拒拆按违约处理（带原因与现场）")
    else:
        raise AssertionError("无法拆解竟然解析通过")


def scenario_garbage():
    try:
        parse_task_table("我觉得这个需求挺好的，可以开干", FakeTeam())
    except TaskTableError as e:
        assert "解析不到" in e.reason
        print("场景 6 通过：无契约格式产出被拦下，raw 保留现场")
    else:
        raise AssertionError("乱聊竟然解析通过")


def scenario_direct_reply():
    # 问候/自我介绍：调度岗走直接回复通道——不是失败，不应答出任务表
    try:
        parse_task_table("直接回复：你好！我是团队的项目经理，请描述需要实现的代码需求。", FakeTeam())
    except DirectReply as e:
        assert "你好" in e.answer and "项目经理" in e.answer
        print("场景 7 通过：问候走直接回复通道（原样转告，不拆解不判失败）")
    else:
        raise AssertionError("直接回复竟然当任务表解析")
    # 含任务行但同时给了直接回复 → 也以直接回复为准（防模型两样都输出）
    mixed = "直接回复：你好！\n任务#1 [岗位:coder] 不该出现的任务"
    try:
        parse_task_table(mixed, FakeTeam())
    except DirectReply:
        print("场景 8 通过：直接回复优先于任务行（防混合输出穿透）")
    else:
        raise AssertionError("混合输出竟然解析成任务表")


def scenario_standalone_deliver_line():
    # 「本任务适用规则」把交付声明挤到任务行之外的下一行（2026-10-08 贪吃蛇实测格式）
    raw = """【任务拆解】
任务#1 [岗位:coder] 实现贪吃蛇游戏。
本任务适用规则：
1. 文件名一律中文。
以上条目如与你原有工作方式冲突或重复，以本段为准；未提及的原有规则照常执行。
交付：贪吃蛇.html
任务#2 [岗位:tester] [评审 任务#1] 实测验收
依赖：任务#2 ← 任务#1
"""
    tasks = parse_task_table(raw, FakeTeam())
    assert tasks[0].deliverable == "贪吃蛇.html", tasks[0].deliverable
    assert "交付" not in tasks[0].description
    assert tasks[1].deliverable == "" and tasks[1].review_of == "任务#1"
    print("场景 9 通过：交付声明独立成行也能归并进正确任务（不误挂评审任务）")


if __name__ == "__main__":
    scenario_valid()
    scenario_unknown_role()
    scenario_non_sequential_ids()
    scenario_review_target_missing()
    scenario_no_decompose()
    scenario_garbage()
    scenario_direct_reply()
    scenario_standalone_deliver_line()
    print("九场景全过——任务表契约：解析、剥离、校验、直接回复、违约即失败")
