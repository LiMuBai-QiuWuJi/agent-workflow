# -*- coding: utf-8 -*-
"""test_pipeline_stub.py —— 任务表驱动主线（run_pipeline）确定性回放：不发 LLM，零 API 消耗。
用法：在项目根目录运行 python test_pipeline_stub.py"""
import contextlib
import io
import os

import core.dispatcher as dispatcher
from core.task_table import Task
from core.verifier import extract_declared_files, resolve_under

CODER_OK = "实现完成\n【交付清单】\nfib.py\n[请求协作:tester] 请审查"
VERDICT_OK = "逐项复核通过\n【评审结论:通过】"
STANDALONE = "验收要点清单：1. 边界 2. 异常路径"   # 任务#3 直发任务的产出


class FakeRole:
    name = "桩岗位"


class FakeTeam:
    def get(self, key):
        return FakeRole()


def make_stub(replies: dict[str, list[str]]):
    iters = {k: iter(v) for k, v in replies.items()}
    calls = {"coder": [], "tester": []}

    def stub(team, role_key, task_content, memory=None, project_id="demo"):
        calls[role_key].append(task_content)
        reply = next(iters[role_key])
        if role_key == "coder":
            for f in extract_declared_files(reply):   # 模拟 write_file 真落盘
                p = resolve_under(f"demo_out/{project_id}", f)
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "w", encoding="utf-8") as fp:
                    fp.write("# stub 写盘\n")
        return reply

    return stub, calls


def scenario_pipeline_routes_by_table():
    """任务表：#1 编码（配评审 #2）+ #3 测试岗独立任务（无评审，直发）。"""
    tasks = [
        Task(id="任务#1", num=1, role_key="coder",
             description="实现斐波那契数列函数并自测", deliverable="fib.py"),
        Task(id="任务#2", num=2, role_key="tester",
             description="重点审查边界", review_of="任务#1"),
        Task(id="任务#3", num=3, role_key="tester",
             description="为该需求编写验收要点清单", depends_on=[1]),
    ]
    stub, calls = make_stub({"coder": [CODER_OK],
                             "tester": [VERDICT_OK, STANDALONE]})
    dispatcher.dispatch = stub
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        dispatcher.run_pipeline(FakeTeam(), None, "stub_pipe", tasks)
    out = buf.getvalue()

    assert len(calls["coder"]) == 1            # 编码只派一次（评审链内部无退回）
    assert len(calls["tester"]) == 2           # 评审一次 + 独立任务一次
    assert "实现斐波那契数列函数并自测" in calls["coder"][0]   # 任务文本来自调度岗描述
    assert "【交付清单】" in calls["coder"][0]                # 系统侧契约照常注入
    assert "验收要点清单" in calls["tester"][1]               # 独立任务按表直发
    assert "任务#1 产出摘要" in calls["tester"][1]            # 依赖注入前置产出
    assert "闭环成功" in out and "任务#3" in out
    assert os.path.exists("demo_out/stub_pipe/fib.py")       # 前任务文件未被后任务清掉
    print("场景 1 通过：任务表驱动——配评审走链、独立任务直发、依赖注入、工作区跨任务保留")


def scenario_collab_off_skips_review():
    """collab=False：评审配对也跳过，全部任务直发一次。"""
    tasks = [
        Task(id="任务#1", num=1, role_key="coder", description="写个加法函数"),
        Task(id="任务#2", num=2, role_key="tester", description="审", review_of="任务#1"),
    ]
    stub, calls = make_stub({"coder": ["单干完成\n【交付清单】\nadd.py"],
                             "tester": []})
    dispatcher.dispatch = stub
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        dispatcher.run_pipeline(FakeTeam(), None, "stub_pipe2", tasks, collab=False)
    assert len(calls["coder"]) == 1 and len(calls["tester"]) == 0
    print("场景 2 通过：协作关闭时评审配对不派发，编码单干")


if __name__ == "__main__":
    scenario_pipeline_routes_by_table()
    scenario_collab_off_skips_review()
    print("两场景全过——任务表执行：路由、依赖、协作开关")
