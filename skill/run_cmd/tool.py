import os
import subprocess

script_dir = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(script_dir))   # skill/run_cmd → 项目根

OUTPUT_LIMIT = 2000   # 输出截断上限：工具结果要进模型上下文，太长会吃掉滑动窗口


def run_cmd(cmd: str, cwd: str = "", timeout_s: int = 30) -> dict:
    """在工作区内执行一条命令，返回 {status, returncode, output}。
    三道保险：cwd 沙箱（只允许项目根内的相对路径）、超时强杀、输出截断。"""
    # print(f"项目根目录: {PROJECT_ROOT}")
    if not cmd or not cmd.strip():
        return {"status": "error", "message": "命令为空"}

    timeout_s = max(1, min(int(timeout_s or 30), 120))   # 上下 clamps，防呆

    # 沙箱：cwd 拼到项目根下解析，越界（含 ../../）直接拒绝
    root = os.path.realpath(PROJECT_ROOT)
    workdir = root
    if cwd:
        candidate = os.path.realpath(os.path.join(root, cwd))
        if candidate != root and not candidate.startswith(root + os.sep):
            return {"status": "error", "message": f"cwd 越界：{cwd}（只允许项目根内的相对路径）"}
        workdir = candidate
    if not os.path.isdir(workdir):
        return {"status": "error", "message": f"目录不存在：{cwd or '.'}"}

    try:
        proc = subprocess.run(
            cmd, cwd=workdir, shell=True,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": f"执行超时（>{timeout_s}s），进程已终止"}
    except Exception as e:
        return {"status": "error", "message": f"执行失败：{type(e).__name__}: {e}"}

    output = (proc.stdout or "") + (proc.stderr or "")
    if len(output) > OUTPUT_LIMIT:
        output = output[:OUTPUT_LIMIT] + "\n……（输出过长已截断）"
    return {
        "status": "ok" if proc.returncode == 0 else "error",
        "returncode": proc.returncode,
        "output": output,
    }
