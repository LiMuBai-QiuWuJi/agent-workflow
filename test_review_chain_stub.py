# -*- coding: utf-8 -*-
"""test_review_chain_stub.py —— 评审链受控循环确定性回放：不发 LLM，零 API 消耗。
用法：在项目根目录运行 python test_review_chain_stub.py"""
import contextlib
import io
import os

import core.dispatcher as dispatcher
from core.verifier import extract_declared_files, resolve_under

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


def make_stub(coder_replies, tester_replies, create_files=True):
    iters = {"coder": iter(coder_replies), "tester": iter(tester_replies)}
    calls = {"coder": [], "tester": []}

    def stub(team, role_key, task_content, memory=None, project_id="demo"):
        calls[role_key].append(task_content)   # 记下任务文本，供断言"被通知第 N 次退回"
        reply = next(iters[role_key])
        if create_files and role_key == "coder":
            # 模拟编码岗 write_file：声明了什么就真写什么（核验的前提）
            for f in extract_declared_files(reply):
                p = resolve_under(f"demo_out/{project_id}", f)
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "w", encoding="utf-8") as fp:
                    fp.write("# stub 写盘\n")
        return reply

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
    out = buf.getvalue()
    assert "闭环成功" in out
    assert "退回 2 次" in out
    assert "核验通过 1 个文件" in out
    print("场景 1 通过：退回 2 次后复审通过，交付核验放行，闭环成功")


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


def scenario_fake_done_caught():
    # 编码岗声称写了 report.md，实际没写（create_files=False）
    coder = "实现完成，报告已生成\n【交付清单】\nreport.md\n[请求协作:tester] 请审查"
    stub, calls = make_stub([coder], [VERDICT_OK], create_files=False)
    dispatcher.dispatch = stub
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        dispatcher.run_review_chain(FakeTeam(), None, "stub_test", "桩需求")
    out = buf.getvalue()
    assert "交付核验失败" in out
    assert "report.md" in out              # 缺失文件名进了失败现场
    assert "闭环成功" not in out           # 关键：假完成绝不算完成
    print("场景 3 通过：声明 report.md 实际未生成，核验判失败而非完成")


def scenario_no_manifest():
    coder = "该需求无需落盘文件，口头交付即可\n[请求协作:tester] 请审查"
    stub, calls = make_stub([coder], [VERDICT_OK])
    dispatcher.dispatch = stub
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        dispatcher.run_review_chain(FakeTeam(), None, "stub_test", "桩需求")
    out = buf.getvalue()
    assert "契约违约" in out
    assert "闭环成功" not in out
    print("场景 4 通过：未声明交付清单按契约违约判失败（空清单不留后门）")


TRUNCATED_NO_SIGNAL = "实现写了一半（输出被 max_tokens 截断）"


def scenario_truncated_recovered():
    # 截断导致协作信号丢失 → 调度层回灌补发任务 → 编码岗补发信号 → 评审闭环
    coder_recovered = "补发契约信号\n【交付清单】\nfib.py\n[请求协作:tester] 请审查"
    stub, calls = make_stub([TRUNCATED_NO_SIGNAL, coder_recovered], [VERDICT_OK])
    dispatcher.dispatch = stub
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        dispatcher.run_review_chain(FakeTeam(), None, "stub_test", "桩需求")
    out = buf.getvalue()
    assert len(calls["coder"]) == 2                      # 初始 1 次 + 补发 1 次
    assert "截断" in calls["coder"][1] and "补发" in calls["coder"][1]
    assert "闭环成功" in out
    print("场景 5 通过：截断致信号丢失，回灌补发任务后编码岗补发契约，闭环成功")


def scenario_truncated_recovery_fails():
    # 截断 → 补发机会给了 → 补发仍无信号 → 按契约终止（恢复不是无底洞）
    stub, calls = make_stub([TRUNCATED_NO_SIGNAL, TRUNCATED_NO_SIGNAL], [VERDICT_OK])
    dispatcher.dispatch = stub
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        dispatcher.run_review_chain(FakeTeam(), None, "stub_test", "桩需求")
    out = buf.getvalue()
    assert "未发协作信号" in out
    assert "闭环成功" not in out
    assert len(calls["coder"]) == 2                      # 只补发一次，不无限重试
    print("场景 6 通过：补发后仍无信号，按契约终止（恢复只给一次）")


if __name__ == "__main__":
    scenario_pass_after_2_rejects()
    scenario_exceed_max_rejects()
    scenario_fake_done_caught()
    scenario_no_manifest()
    scenario_truncated_recovered()
    scenario_truncated_recovery_fails()
    print("六场景全过——受控循环、交付核验与截断补发")
