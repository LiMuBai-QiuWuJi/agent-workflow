import os
from pathlib import Path

script_dir = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(script_dir))   # skill/write_file → 项目根

def write_file (txt_file_abs_path:str|Path, w_or_a:str="w", makedirsOrNot:bool=True, write_data:str="") -> str:
    if txt_file_abs_path is None or len(str(txt_file_abs_path))==0:
        return "输入路径为空"

    # 路径锚定：相对路径一律以项目根为锚点（与 run_cmd/read_file 同标准），
    # 绝对路径经 os.path.join 自动透传不变——从任何目录启动程序都能写对。
    file_path = os.path.join(PROJECT_ROOT, str(txt_file_abs_path))

    if makedirsOrNot:
        parent = os.path.dirname(file_path)
        if parent:  # 过滤掉空字符串
            os.makedirs(parent, exist_ok=True)

    try:
        with open(file_path, w_or_a, encoding='utf-8') as file:
            file.write(write_data)
    except FileNotFoundError as e:
        return "父目录不存在，"
    except PermissionError:
        return "权限不足，无法写入"
    # except IsADirectoryError:
    #     return "路径是目录，不是文件"
    except Exception as e:
         return f"文件写入异常 {e}"

    return "文件写入成功"