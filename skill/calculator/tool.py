def calculator(a: float, b: float, operator: str) -> str:
    if operator == "+":
        return str(a + b)
    elif operator == "-":
        return str(a - b)
    elif operator == "*":
        return str(a * b)
    elif operator == "/":
        return str(a / b) if b != 0 else "Error: 除零"
    return "Error: 未知运算符"
