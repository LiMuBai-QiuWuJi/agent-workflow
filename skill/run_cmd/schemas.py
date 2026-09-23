RUNCMD_SCHEMAS = {
    "type":"function",
    "function":{
        "name":"run_cmd",
        "description":"在工作区内执行一条命令（如运行被审代码），返回退出码与截断后的输出",
        "parameters":{
            "type":"object",
            "properties":{
                "cmd": {
                    "type": "string",
                    "description": "要执行的命令，如 python demo_out/demo/fibonacci.py"
                },
                "cwd": {
                    "type": "string",
                    "description": "执行目录（相对项目根目录的相对路径），默认项目根目录"
                },
                "timeout_s": {
                    "type": "integer",
                    "description": "超时秒数，默认 30，最长 120，超时被强杀"
                }
            },
            "required":["cmd"]
        }
    }
}