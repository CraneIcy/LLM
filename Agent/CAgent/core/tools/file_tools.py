"""
文件系统操作工具：获取工作目录、列出目录、读写文件、增删改等。

安全边界（与 AGENTS.md 第七章、README 安全边界一致）：
- 只接受非空字符串路径，路径统一解析为绝对路径后再操作；
- 拒绝作用于盘符根、POSIX 根、当前项目根与系统关键目录；
- 删除目录 / 删除文件 / 覆盖式重命名属于危险操作，必须显式传 confirm=true，
  否则直接拦截并返回说明，不做任何副作用。
"""

import os
import shutil

from .base import BaseTool

# 系统关键目录（小写、以 / 分隔），不允许这些路径被删除或改名
_PROTECTED_SEGMENTS = (
    "/windows",
    "/program files",
    "/program files (x86)",
    "/programdata",
    "/system",
    "/usr",
    "/bin",
    "/sbin",
    "/etc",
    "/boot",
    "/dev",
    "/proc",
    "/sys",
    "/library",
    "/private",
)


def _normalize_path(path):
    """把用户给的路径解析成绝对路径；非法输入返回 None。"""
    if not isinstance(path, str) or not path.strip():
        return None
    return os.path.abspath(os.path.expanduser(path.strip()))


def _protected_reason(abspath):
    """判断路径是否落在禁止改动的范围内，返回原因字符串（未命中返回 None）。"""
    norm = abspath.replace("\\", "/").rstrip("/")
    lower = norm.lower()
    # 盘符根（C:）或 POSIX 根（/）或空
    if norm == "" or (len(norm) == 2 and norm[1] == ":") or norm == "/":
        return "目标是盘符根或系统根目录"
    tail = lower.split(":/", 1)[1] if ":/" in lower else lower
    tail = "/" + tail.lstrip("/")
    for seg in _PROTECTED_SEGMENTS:
        if tail == seg or tail.startswith(seg + "/"):
            return f"目标是系统关键目录（{seg}）"
    # 当前项目根（进程工作目录）
    cwd = os.path.abspath(os.getcwd()).replace("\\", "/").rstrip("/").lower()
    if lower == cwd:
        return "目标是当前项目根目录"
    return None


def _confirm_hint(action, abspath):
    """危险操作的统一拦截提示。"""
    return (
        f"已拦截：{action} 属于不可逆操作，目标 {abspath}。"
        "确认无误后请带 confirm=true 重新调用；不确定时先用 listDir / getFileType 核对目标。"
    )


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
        full_path = _normalize_path(path)
        if full_path is None:
            return "错误：path 不能为空，请给出要列出的目录路径"
        if not os.path.isdir(full_path):
            return f"错误：目录不存在或不是目录 -> {full_path}"
        items = []
        for name in os.listdir(full_path):
            full = os.path.join(full_path, name)
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
        full_path = _normalize_path(path)
        if full_path is None:
            return "错误：path 不能为空，请给出要读取的文件路径"
        if not os.path.isfile(full_path):
            return f"错误：文件不存在或不是普通文件 -> {full_path}"
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()


class CreateFileTool(BaseTool):
    name = "createFile"
    description = "在指定目录下创建新文件，可附带初始内容；同名文件已存在时会被覆盖（覆盖前会提示原文件大小）"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件完整路径，例如 D:/LLM/test.txt"},
            "content": {"type": "string", "description": "初始内容，可选"},
        },
        "required": ["path"],
    }

    def execute(self, path: str, content: str = "", **kwargs) -> str:
        full_path = _normalize_path(path)
        if full_path is None:
            return "错误：path 不能为空，请给出要创建的文件路径"
        if os.path.isdir(full_path):
            return f"错误：目标是一个目录，不能当文件创建 -> {full_path}"
        parent = os.path.dirname(full_path)
        if parent and not os.path.isdir(parent):
            return f"错误：上级目录不存在 -> {parent}（可先用 makeDir 创建）"
        existed = os.path.isfile(full_path)
        old_size = os.path.getsize(full_path) if existed else 0
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        if existed:
            return f"文件已覆盖: {full_path}（原文件 {old_size} 字节被替换为 {len(content)} 字节）"
        return f"文件已创建: {full_path}"


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
        full_path = _normalize_path(path)
        if full_path is None:
            return "错误：path 不能为空，请给出要写入的文件路径"
        if os.path.isdir(full_path):
            return f"错误：目标是一个目录，不能写入 -> {full_path}"
        parent = os.path.dirname(full_path)
        if parent and not os.path.isdir(parent):
            return f"错误：上级目录不存在 -> {parent}（可先用 makeDir 创建）"
        existed = os.path.isfile(full_path)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        if existed:
            return f"文件已覆盖写入: {full_path}（{len(content)} 字节）"
        return f"文件已写入（新建）: {full_path}（{len(content)} 字节）"


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
        full_path = _normalize_path(path)
        if full_path is None:
            return "错误：path 不能为空，请给出要创建的目录路径"
        if os.path.exists(full_path):
            if os.path.isdir(full_path):
                return f"目录已存在（未做改动）: {full_path}"
            return f"错误：同名文件已存在，无法创建目录 -> {full_path}"
        os.makedirs(full_path, exist_ok=True)
        return f"目录已创建: {full_path}"


class RemoveDirTool(BaseTool):
    name = "removeDir"
    description = (
        "删除目录及其所有内容（非空目录也会被删除）。属于不可逆操作，必须显式传 confirm=true，"
        "否则会被拦截；盘符根、系统关键目录与当前项目根一律拒绝。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "要删除的目录路径"},
            "confirm": {
                "type": "boolean",
                "description": "确认执行不可逆删除；缺省 false 表示先拦截并返回提示",
            },
        },
        "required": ["path"],
    }

    def execute(self, path: str, confirm: bool = False, **kwargs) -> str:
        full_path = _normalize_path(path)
        if full_path is None:
            return "错误：path 不能为空，请给出要删除的目录路径"
        reason = _protected_reason(full_path)
        if reason:
            return f"已拒绝：{reason}，不允许删除 -> {full_path}"
        if not os.path.isdir(full_path):
            return f"错误：目录不存在或不是目录 -> {full_path}"
        if not confirm:
            return _confirm_hint("删除目录（含全部子项）", full_path)
        try:
            shutil.rmtree(full_path)
        except OSError as exc:
            return f"错误：删除目录失败 - {exc}"
        return f"目录已删除: {full_path}"


class RemoveFileTool(BaseTool):
    name = "removeFile"
    description = (
        "删除指定文件。属于不可逆操作，必须显式传 confirm=true，否则会被拦截；删除目录请用 removeDir。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "要删除的文件路径"},
            "confirm": {
                "type": "boolean",
                "description": "确认执行不可逆删除；缺省 false 表示先拦截并返回提示",
            },
        },
        "required": ["path"],
    }

    def execute(self, path: str, confirm: bool = False, **kwargs) -> str:
        full_path = _normalize_path(path)
        if full_path is None:
            return "错误：path 不能为空，请给出要删除的文件路径"
        reason = _protected_reason(full_path)
        if reason:
            return f"已拒绝：{reason}，不允许删除 -> {full_path}"
        if not os.path.isfile(full_path):
            if os.path.isdir(full_path):
                return f"错误：目标是目录，删除目录请用 removeDir -> {full_path}"
            return f"错误：文件不存在 -> {full_path}"
        if not confirm:
            return _confirm_hint("删除文件", full_path)
        try:
            os.remove(full_path)
        except OSError as exc:
            return f"错误：删除文件失败 - {exc}"
        return f"文件已删除: {full_path}"


class RenameTool(BaseTool):
    name = "rename"
    description = (
        "重命名或移动文件/目录。目标已存在时需要 confirm=true 才会覆盖；"
        "盘符根、系统关键目录与当前项目根一律拒绝。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "oldPath": {"type": "string", "description": "原路径"},
            "newPath": {"type": "string", "description": "新路径"},
            "confirm": {
                "type": "boolean",
                "description": "目标已存在时确认覆盖；缺省 false 表示先拦截并返回提示",
            },
        },
        "required": ["oldPath", "newPath"],
    }

    def execute(self, oldPath: str, newPath: str, confirm: bool = False, **kwargs) -> str:
        src = _normalize_path(oldPath)
        dst = _normalize_path(newPath)
        if src is None or dst is None:
            return "错误：oldPath 与 newPath 都不能为空"
        if not os.path.exists(src):
            return f"错误：原路径不存在 -> {src}"
        for p in (src, dst):
            reason = _protected_reason(p)
            if reason:
                return f"已拒绝：{reason}，不允许改名或移动 -> {p}"
        if os.path.exists(dst) and not confirm:
            return _confirm_hint(f"覆盖已存在的目标 {dst}", src)
        try:
            os.rename(src, dst)
        except OSError as exc:
            return f"错误：重命名失败 - {exc}"
        return f"已重命名: {src} -> {dst}"
