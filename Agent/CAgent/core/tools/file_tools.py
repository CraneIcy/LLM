"""
文件系统操作工具：获取工作目录、列出目录、读写文件、增删改等。
"""

import os
import shutil

from .base import BaseTool


class GetCwdTool(BaseTool):
    name = "getCwd"
    description = "获取当前工作目录"
    parameters = {"type": "object", "properties": {}}

    def execute(self, **kwargs) -> str:
        return os.getcwd()


class ListDirTool(BaseTool):
    name = "listDir"
    description = "列出指定目录下所有文件和子目录"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "目录路径，默认当前目录"},
        },
    }

    def execute(self, path: str = ".", **kwargs) -> str:
        items = []
        for name in os.listdir(path):
            full = os.path.join(path, name)
            if os.path.isdir(full):
                items.append(f"[文件夹] {name}")
            else:
                size = os.path.getsize(full)
                items.append(f"[文件] {name} ({size}字节)")
        return "\n".join(items) if items else "(空目录)"


class GetFileTypeTool(BaseTool):
    name = "getFileType"
    description = "获取指定路径的类型：是文件还是文件夹，以及文件扩展名"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件或目录路径"},
        },
        "required": ["path"],
    }

    def execute(self, path: str, **kwargs) -> str:
        if os.path.isdir(path):
            return f"{path} 是一个目录"
        elif os.path.isfile(path):
            ext = os.path.splitext(path)[1]
            return f"{path} 是一个文件，扩展名: {ext or '无'}"
        else:
            return f"{path} 不存在"


class ReadFileTool(BaseTool):
    name = "readFile"
    description = "读取指定文件的文本内容"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
        },
        "required": ["path"],
    }

    def execute(self, path: str, **kwargs) -> str:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()


class CreateFileTool(BaseTool):
    name = "createFile"
    description = "在指定目录下创建新文件，可附带初始内容"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件完整路径，例如 D:/LLM/test.txt"},
            "content": {"type": "string", "description": "初始内容，可选"},
        },
        "required": ["path"],
    }

    def execute(self, path: str, content: str = "", **kwargs) -> str:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"文件已创建: {path}"


class WriteFileTool(BaseTool):
    name = "writeFile"
    description = "覆盖写入指定文件的内容"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "content": {"type": "string", "description": "要写入的新内容"},
        },
        "required": ["path", "content"],
    }

    def execute(self, path: str, content: str, **kwargs) -> str:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"文件已写入: {path}"


class MakeDirTool(BaseTool):
    name = "makeDir"
    description = "创建新目录"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "要创建的目录路径"},
        },
        "required": ["path"],
    }

    def execute(self, path: str, **kwargs) -> str:
        os.makedirs(path, exist_ok=True)
        return f"目录已创建: {path}"


class RemoveDirTool(BaseTool):
    name = "removeDir"
    description = "删除目录及其所有内容（非空目录也会被删除）"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "要删除的目录路径"},
        },
        "required": ["path"],
    }

    def execute(self, path: str, **kwargs) -> str:
        shutil.rmtree(path)
        return f"目录已删除: {path}"


class RemoveFileTool(BaseTool):
    name = "removeFile"
    description = "删除指定文件"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "要删除的文件路径"},
        },
        "required": ["path"],
    }

    def execute(self, path: str, **kwargs) -> str:
        os.remove(path)
        return f"文件已删除: {path}"


class RenameTool(BaseTool):
    name = "rename"
    description = "重命名文件或目录"
    parameters = {
        "type": "object",
        "properties": {
            "oldPath": {"type": "string", "description": "原路径"},
            "newPath": {"type": "string", "description": "新路径"},
        },
        "required": ["oldPath", "newPath"],
    }

    def execute(self, oldPath: str, newPath: str, **kwargs) -> str:
        os.rename(oldPath, newPath)
        return f"已重命名: {oldPath} -> {newPath}"
