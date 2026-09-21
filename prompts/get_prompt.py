import os
from enum import Enum

class PromptFileName(Enum):
    CODER       = "coder.md"
    TESTER      = "tester.md"
    SCHEDULER   = "scheduler.md"

script_dir = os.path.dirname(os.path.abspath(__file__))
prompt_dir = os.path.join(script_dir,"prompt_file")

def get_prompt(name:PromptFileName) -> str:
    prompt_path = os.path.join(prompt_dir,name.value)
    # print(prompt_path)
    with open(prompt_path,"r",encoding="utf-8") as file:
        return file.read()

def get_prompt_path(name:PromptFileName) -> str:
    return os.path.join("prompts", "prompt_file", name.value)

def get_prompt_abs_path(name:PromptFileName) -> str:
    return os.path.join( script_dir, "prompts", "prompt_file", name.value )



