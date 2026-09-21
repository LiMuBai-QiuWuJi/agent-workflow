from pathlib import Path
from pypdf import PdfReader
from docx import Document

def read_pdf(pdf_abs_path: str | Path) -> str:
    if pdf_abs_path == None or len(str(pdf_abs_path)) == 0:   # Path 无 len()，先转 str
        return "输入路径为空"
    try:
        pdfReader = PdfReader(pdf_abs_path)
        # 遍历所有页拼接，避免多页 PDF 只进第一页
        file_data = ""
        for page in pdfReader.pages:
            file_data += (page.extract_text() or "") + "\n"
    except FileNotFoundError:
        return "文件不存在"
    except PermissionError:
        return "权限不足，无法读取"
    except IsADirectoryError:
        return "路径是目录，不是文件"
    except Exception as e:
        return f"读取PDF异常: {e}"

    # extract_text 对扫描件（图片型PDF）会返回 None，按空处理
    if file_data == None or len(file_data.strip()) == 0:
        # 文本为空但有图片 → 扫描件，pypdf 解不了，需要 OCR
        img_count = sum(len(p.images) for p in pdfReader.pages)
        if img_count > 0:
            return f"疑似扫描件（图片型PDF），共 {img_count} 张图片，pypdf 无法提取文字，需用 OCR"
        return "文本内容为空"
    return file_data


def read_docx(docx_abs_path: str | Path) -> str:
    if docx_abs_path == None or len(str(docx_abs_path)) == 0:
        return "输入路径为空"

    try:
        doc = Document(docx_abs_path)   # 构造时就会抛 FileNotFoundError 等，必须放进 try
        text = ""
        # 读所有段落
        for para in doc.paragraphs:
            text += para.text + "\n"   # 段落之间补换行

        # 读表格
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    text += cell.text + "\n"
    except FileNotFoundError:
        return "文件不存在"
    except PermissionError:
        return "权限不足，无法读取"
    except IsADirectoryError:
        return "路径是目录，不是文件"
    except Exception as e:
        return f"读取docx异常: {e}"

    if len(text) == 0:
        return "文本内容为空"
    return text


def read_text(text_abs_path: str | Path) -> str:
    if text_abs_path == None or len(str(text_abs_path)) == 0:
        return "输入路径为空"
    try:
        with open(text_abs_path, 'r', encoding='utf-8') as file:
            file_data = file.read()
    except FileNotFoundError:
        return "文件不存在"
    except PermissionError:
        return "权限不足，无法读取"
    except IsADirectoryError:
        return "路径是目录，不是文件"
    except UnicodeDecodeError:          # 文本特有：编码不匹配时给明确提示
        return "编码不匹配，非 utf-8 文本"
    except Exception as e:
        return f"读取文本异常: {e}"

    if len(file_data) == 0:
        return "文本内容为空"
    return file_data


def read_file(file_abs_path: str | Path) -> str:
    """输入文件绝对地址，根据文件后缀自动选择读取方法"""
    if file_abs_path == None or len(str(file_abs_path)) == 0:
        return "输入路径为空"

    # 取后缀，结果带点，如 ".pdf"，统一转小写防止 ".PDF" 匹配不上
    suffix = Path(file_abs_path).suffix.lower()

    if suffix == ".pdf":
        return read_pdf(file_abs_path)
    elif suffix == ".docx":
        return read_docx(file_abs_path)
    else:
        return read_text(file_abs_path)
    # elif suffix == ".txt" or suffix == ".md":
    #     return read_text(file_abs_path)
    # else:
    #     return f"Error 不支持的文件类型 : {suffix}"