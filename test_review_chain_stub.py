# -*- coding: utf-8 -*-
"""test_review_chain_stub.py —— 评审链受控循环确定性回放：不发 LLM，零 API 消耗。
用法：在项目根目录运行 python test_review_chain_stub.py"""
import contextlib
import io

import core.dispatcher as dispatcher

CODER_V1 = "初始实现（有缺陷）\n【交付清单】\nfib.py\n[请求协作:tester] 请审查"
CODER_V2 = "第 1 次修正\n【交付清单】\nfib.py\n[请求协作:tester] 请复审"
CODER_V3 = "第 2 次修正\n【交付清单】\nfib.py\n[请求协作:tester] 请复审"
VERDICT_NO = "1. 边界未处理（n=-1 未抛异常）\n【评审结论:不通过】"
VERDICT_OK = "逐项复核通过\n【评审结论:通过】"


class FakeRole:
    name = "测试岗"


class FakeTeam:
    def get(self, key):
        return FakeRole()


def make_stub(coder_replies, tester_replies):
    iters = {"coder": iter(coder_replies), "tester": iter(tester_replies)}
    calls = {"coder": [], "tester": []}

    def stub(team, role_key, task_content, memory=None, project_id="demo"):
        calls[role_key].append(task_content)   # 记下任务文本，供断言"被通知第 N 次退回"
        return next(iters[role_key])

    return stub, calls


def scenario_pass_after_2_rejects():
    stub, calls = make_stub([CODER_V1, CODER_V2, CODER_V3],
                            [VERDICT_NO, VERDICT_NO, VERDICT_OK])
    dispatcher.dispatch = stub
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        dispatcher.run_review_chain(FakeTeam(), None, "stub_test", "桩需求")
    assert len(calls["coder"]) == 3 and len(calls["tester"]) == 3
    assert "第 1 次退回修改" in calls["coder"][1]   # 模型只在任务描述里被通知次数
    assert "第 2 次退回修改" in calls["coder"][2]
    assert "闭环成功（任务#1，退回 2 次）" in buf.getvalue()
    print("场景 1 通过：退回 2 次后复审通过，闭环成功")


def scenario_exceed_max_rejects():
    stub, calls = make_stub([CODER_V1, CODER_V2, CODER_V3],
                            [VERDICT_NO, VERDICT_NO, VERDICT_NO])
    dispatcher.dispatch = stub
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        dispatcher.run_review_chain(FakeTeam(), None, "stub_test", "桩需求")
    assert "退回超上限" in buf.getvalue()
    assert len(calls["coder"]) == 3                  # 初始 1 次 + 退回 2 次
    assert len(calls["tester"]) == 3                 # 第 3 次评审仍发生，但…
    # …第 3 次"退回"被拦死：不存在第 4 次编码岗派发，也无"第 3 次退回修改"任务
    assert all("第 3 次退回" not in t for t in calls["coder"])
    print("场景 2 通过：第 3 次不通过触发刹车，退回派发被拦死（连派发都不做）")


if __name__ == "__main__":
    scenario_pass_after_2_rejects()
    scenario_exceed_max_rejects()
    print("两场景全过——受控循环的每一格都不依赖模型心情")
