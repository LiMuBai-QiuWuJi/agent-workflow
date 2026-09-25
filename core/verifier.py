import os

script_dir = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(script_dir)


def extract_declared_files(reply: str) -> list[str]:
    """从岗位产出解析【交付清单】→ 声明的文件名列表。"""
    idx = (reply or "").find("【交付清单】")
    if idx < 0:
        return []
    files = []
    for line in reply[idx:].splitlines()[1:]:
        s = line.strip().strip("`")          # 兼容 ``` 围栏和行内反引号
        if not s or s.startswith(("【", "[")):
            break
        files.append(s)
    return files


def resolve_under(workspace: str, name: str) -> str:
    """声明的文件名 → 磁盘绝对路径"""
    ws = os.path.normpath(workspace)
    norm = os.path.normpath(str(name))
    if norm == ws or norm.startswith(ws + os.sep):
        rel = norm
    else:
        rel = os.path.join(ws, norm)
    return os.path.join(PROJECT_ROOT, rel)


def verify_delivery(workspace: str, reply: str) -> tuple[list[str], list[str]]:
    """核验产出声明的交付文件 → (声明列表, 缺失列表)。"""
    declared = extract_declared_files(reply)
    missing = [f for f in declared
               if not os.path.isfile(resolve_under(workspace, f))]
    return declared, missing