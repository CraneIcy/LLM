import configparser
import json
import requests
import subprocess
import os
import shutil

config = configparser.ConfigParser()
config.read(".config.ini", encoding="utf-8")

tools = [
    {
        "type": "function",
        "function": {
            "name": "getDate",
            "description": "获取当前电脑的日期和时间",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "isLeapYear",
            "description": "判断给定的年份是否为闰年",
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {"type": "integer", "description": "要判断的年份，例如 2024"}
                },
                "required": ["year"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getCwd",
            "description": "获取当前工作目录",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listDir",
            "description": "列出指定目录下所有文件和子目录",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "目录路径，默认当前目录"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getFileType",
            "description": "获取指定路径的类型：是文件还是文件夹，以及文件扩展名",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件或目录路径"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "readFile",
            "description": "读取指定文件的文本内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "createFile",
            "description": "在指定目录下创建新文件，可附带初始内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件完整路径，例如 D:/LLM/test.txt"},
                    "content": {"type": "string", "description": "初始内容，可选"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "writeFile",
            "description": "覆盖写入指定文件的内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "content": {"type": "string", "description": "要写入的新内容"}
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "makeDir",
            "description": "创建新目录",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要创建的目录路径"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "removeDir",
            "description": "删除目录及其所有内容（非空目录也会被删除）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要删除的目录路径"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "removeFile",
            "description": "删除指定文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要删除的文件路径"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rename",
            "description": "重命名文件或目录",
            "parameters": {
                "type": "object",
                "properties": {
                    "oldPath": {"type": "string", "description": "原路径"},
                    "newPath": {"type": "string", "description": "新路径"}
                },
                "required": ["oldPath", "newPath"],
            },
        },
    },
]

def getDate():
    r = subprocess.run(["cmd", "/c", "date /t & time /t"], capture_output=True, text=True)
    return r.stdout.strip()

def isLeapYear(year):
    return (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)

def getCwd():
    return os.getcwd()

def listDir(path="."):
    items = []
    for name in os.listdir(path):
        full = os.path.join(path, name)
        if os.path.isdir(full):
            items.append(f"[文件夹] {name}")
        else:
            size = os.path.getsize(full)
            items.append(f"[文件] {name} ({size}字节)")
    return "\n".join(items)

def getFileType(path):
    if os.path.isdir(path):
        return f"{path} 是一个目录"
    elif os.path.isfile(path):
        ext = os.path.splitext(path)[1]
        return f"{path} 是一个文件，扩展名: {ext or '无'}"
    else:
        return f"{path} 不存在"

def readFile(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def createFile(path, content=""):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"文件已创建: {path}"

def writeFile(path, content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"文件已写入: {path}"

def makeDir(path):
    os.makedirs(path, exist_ok=True)
    return f"目录已创建: {path}"

def removeDir(path):
    shutil.rmtree(path)
    return f"目录已删除: {path}"

def removeFile(path):
    os.remove(path)
    return f"文件已删除: {path}"

def rename(oldPath, newPath):
    os.rename(oldPath, newPath)
    return f"已重命名: {oldPath} -> {newPath}"

messages = []

while True:
    messages.append({"role": "user", "content": input("你：")})

    while True:
        resp = requests.post(
            url=f"{config['llm']['base_url']}/chat/completions",
            headers={"Authorization": f"Bearer {config['llm']['api_key']}"},
            json={
                "model": config["llm"]["model"],
                "messages": messages,
                "tools": tools,
                "stream": True,
            },
            stream=True,
        )

        assistant_reply = ""
        tool_calls = {}
        for line in resp.iter_lines():
            if line and line.startswith(b"data: "):
                data = line[6:].decode("utf-8")
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                delta = chunk["choices"][0]["delta"]
                if delta.get("content"):
                    assistant_reply += delta["content"]
                    print(delta["content"], end="", flush=True)
                if delta.get("tool_calls"):
                    for tc in delta["tool_calls"]:
                        i = tc["index"]
                        tool_calls.setdefault(i, {"id": "", "name": "", "args": ""})
                        if tc.get("id"):
                            tool_calls[i]["id"] = tc["id"]
                        if tc.get("function", {}).get("name"):
                            tool_calls[i]["name"] = tc["function"]["name"]
                        if tc.get("function", {}).get("arguments"):
                            tool_calls[i]["args"] += tc["function"]["arguments"]

        print()

        if not tool_calls:
            messages.append({"role": "assistant", "content": assistant_reply})
            break

        messages.append({
            "role": "assistant",
            "content": assistant_reply or None,
            "tool_calls": [
                {"id": tc["id"], "type": "function",
                 "function": {"name": tc["name"], "arguments": tc["args"]}}
                for tc in tool_calls.values()
            ],
        })

        for tc in tool_calls.values():
            name = tc["name"]
            args = json.loads(tc["args"]) if tc["args"] else {}
            result = ""

            if name == "getDate":
                result = getDate()
            elif name == "isLeapYear":
                result = str(isLeapYear(args["year"]))
            elif name == "getCwd":
                result = getCwd()
            elif name == "listDir":
                result = listDir(args.get("path", "."))
            elif name == "getFileType":
                result = getFileType(args["path"])
            elif name == "readFile":
                result = readFile(args["path"])
            elif name == "createFile":
                result = createFile(args["path"], args.get("content", ""))
            elif name == "writeFile":
                result = writeFile(args["path"], args["content"])
            elif name == "makeDir":
                result = makeDir(args["path"])
            elif name == "removeDir":
                result = removeDir(args["path"])
            elif name == "removeFile":
                result = removeFile(args["path"])
            elif name == "rename":
                result = rename(args["oldPath"], args["newPath"])

            print(f"[工具 {name} 返回: {result[:200]}]")
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
