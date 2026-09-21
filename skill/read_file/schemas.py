READFILE_SCHEMAS = {
    "type" : "function",
    "function" : {
        "name" : "read_file",
        "description" : "阅读指定文件内容",
        "parameters":{
            "type" : "object",
            "properties" : {
                "file_abs_path" : {"type":"string","description":"待读取文件的完整绝对路径，支持pdf、docx、txt、md和其他utf-8编码存储的文本文件"},
            },
            "required" : ["file_abs_path"]
        }
    }
}