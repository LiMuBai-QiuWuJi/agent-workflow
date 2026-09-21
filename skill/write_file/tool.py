import os
from pathlib import Path

def write_file (txt_file_abs_path:str|Path, w_or_a:str="a", makedirsOrNot:bool=False, write_data:str="") -> str:
    file_path = txt_file_abs_path

    if makedirsOrNot:
        parent = os.path.dirname(file_path)
        if parent:  # 过滤掉空字符串
            os.makedirs(parent, exist_ok=True)


    if file_path is None or len(file_path)==0:
        return "输入路径为空"

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