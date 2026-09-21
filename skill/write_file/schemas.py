WRITEFILE_SCHEMAS={
    "type" : "function",
    "function" : {
        "name" : "write_file",
        "description":"写入内容到指定文件",
        "parameters":{
            "type":"object",
            "properties":{
                "txt_file_abs_path":{"type":"string","description":"待写入文件的完整绝对路径"},
                "w_or_a":{
                    "type":"string",
                    "enum":["w","a"],
                    "description":"覆盖写入(w) 还是累加写入(a)。默认为累加写入(a)。"
                },
                "makedirsOrNot":{"type":"boolean","description":"是否自动创建目录，默认为不创建(False),创建时参数为True"},
                "write_data":{"type":"string","description":"待写入文件内部的数据内容"}
            },
            "required":["txt_file_abs_path","write_data"]
        }
    }
}