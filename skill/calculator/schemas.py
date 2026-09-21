CALCULATOR_SCHEMA = {
    "type": "function",
    "function": {
        "name": "calculator",
        "description": "进行基础数学运算，支持加减乘除",
        "parameters": {
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "第一个数字"},
                "b": {"type": "number", "description": "第二个数字"},
                "operator": {
                    "type": "string",
                    "enum": ["+", "-", "*", "/"],
                    "description": "运算符"
                }
            },
            "required": ["a", "b", "operator"]
        }
    }
}
