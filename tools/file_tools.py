import os
import json
import glob
from typing import Dict, Any, List
from .base import Tool, ValidationResult, TextBlock


class FileReadTool(Tool):
    @property
    def name(self) -> str:
        return "FileReadTool"

    async def description(self) -> str:
        return "Read content from local files. Required parameter: 'path' (full file path). Optional: 'lines' (e.g., '1-50')."

    def is_read_only(self) -> bool:
        return True

    async def validate_input(self, input_data: Dict[str, Any]) -> ValidationResult:
        if "path" not in input_data:
            return ValidationResult(result=False, message="Missing required parameter: 'path'")
            
        path = input_data["path"]
        if not os.path.exists(path):
            return ValidationResult(result=False, message=f"File not found: {path}")
            
        if not os.path.isfile(path):
            return ValidationResult(result=False, message=f"Not a file: {path}")
            
        return ValidationResult(result=True)

    async def execute(self, input_data: Dict[str, Any]) -> str:
        path = input_data["path"]
        lines = input_data.get("lines")
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.readlines()
                
                if lines:
                    try:
                        start, end = map(int, lines.split('-'))
                        content = content[start-1:end]
                    except:
                        return "Warning: Invalid line range format, returning all lines."
                        
                full_content = ''.join(content)
                if len(full_content) > 3000:
                    return f"Content of {path} (truncated):\n{full_content[:3000]}\n...[content truncated]"
                return f"Content of {path}:\n{full_content}"
                
        except Exception as e:
            return f"Error reading file: {str(e)}"


class FileWriteTool(Tool):
    @property
    def name(self) -> str:
        return "FileWriteTool"

    async def description(self) -> str:
        return """Write a file to the local filesystem. Overwrites the existing file if there is one.

Before using this tool:

1. Use the ReadFile tool to understand the file's contents and context

2. Directory Verification (only applicable when creating new files):
   - Use the LS tool to verify the parent directory exists and is the correct location"""

    def is_read_only(self) -> bool:
        return False

    async def validate_input(self, input_data: Dict[str, Any]) -> ValidationResult:
        # 检查必填参数
        if "file_path" not in input_data:
            return ValidationResult(result=False, message="Missing required parameter: 'file_path' (must be an absolute path)")
            
        file_path = input_data["file_path"]
        # 验证文件路径是否为绝对路径
        if not os.path.isabs(file_path):
            return ValidationResult(result=False, message=f"file_path must be an absolute path, got: {file_path}")
            
        # 检查是否提供了内容
        if "content" not in input_data:
            return ValidationResult(result=False, message="Missing required parameter: 'content' (the content to write to the file)")
            
        # 检查文件是否为Jupyter笔记本（.ipynb）
        if file_path.endswith(".ipynb"):
            from .code_tools import NotebookEditTool
            return ValidationResult(
                result=False, 
                message=f"For Jupyter notebooks, use {NotebookEditTool.name} instead of FileWriteTool"
            )
            
        # 验证父目录存在
        parent_dir = os.path.dirname(file_path)
        if not os.path.exists(parent_dir):
            return ValidationResult(result=False, message=f"Parent directory does not exist: {parent_dir}. Use LS tool to verify correct path.")
        if not os.path.isdir(parent_dir):
            return ValidationResult(result=False, message=f"Parent path is not a directory: {parent_dir}")
            
        return ValidationResult(result=True)

    async def execute(self, input_data: Dict[str, Any]) -> str:
        file_path = input_data["file_path"]
        content = input_data["content"]
        
        try:
            # 检查是否是覆盖现有文件
            overwrite = os.path.exists(file_path)
            
            # 写入文件内容
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            # 返回操作结果
            if overwrite:
                return f"Successfully overwrote existing file: {file_path}\nWrote {len(content)} characters."
            else:
                return f"Successfully created new file: {file_path}\nWrote {len(content)} characters."
                
        except Exception as e:
            return f"Error writing to file: {str(e)}"


class FileEditTool(Tool):
    @property
    def name(self) -> str:
        return "FileEditTool"

    async def description(self) -> str:
        return f"""This is a tool for editing files. For moving or renaming files, you should generally use the Bash tool with the 'mv' command instead. For larger edits, use the Write tool to overwrite files. For Jupyter notebooks (.ipynb files), use the NotebookEditTool instead.

Before using this tool:

1. Use the View tool to understand the file's contents and context

2. Verify the directory path is correct (only applicable when creating new files):
   - Use the LS tool to verify the parent directory exists and is the correct location

To make a file edit, provide the following:
1. file_path: The absolute path to the file to modify (must be absolute, not relative)
2. old_string: The text to replace (must be unique within the file, and must match the file contents exactly, including all whitespace and indentation)
3. new_string: The edited text to replace the old_string

The tool will replace ONE occurrence of old_string with new_string in the specified file."""

    def is_read_only(self) -> bool:
        return False

    async def validate_input(self, input_data: Dict[str, Any]) -> ValidationResult:
        # 检查必填参数
        if "file_path" not in input_data:
            return ValidationResult(result=False, message="Missing required parameter: 'file_path' (must be an absolute path)")
            
        file_path = input_data["file_path"]
        # 验证文件路径是否为绝对路径
        if not os.path.isabs(file_path):
            return ValidationResult(result=False, message=f"file_path must be an absolute path, got: {file_path}")
            
        # 检查文件是否存在（除非是创建新文件，即old_string为空）
        old_string = input_data.get("old_string", "")
        if old_string != "" and not os.path.exists(file_path):
            return ValidationResult(result=False, message=f"File not found: {file_path}")
            
        # 检查文件是否为Jupyter笔记本（.ipynb）
        if file_path.endswith(".ipynb"):
            from .code_tools import NotebookEditTool
            return ValidationResult(
                result=False, 
                message=f"For Jupyter notebooks, use {NotebookEditTool.name} instead of FileEditTool"
            )
            
        # 检查是否提供了new_string
        if "new_string" not in input_data:
            return ValidationResult(result=False, message="Missing required parameter: 'new_string'")
            
        # 对于新文件，验证父目录存在
        if old_string == "" and not os.path.exists(file_path):
            parent_dir = os.path.dirname(file_path)
            if not os.path.exists(parent_dir):
                return ValidationResult(result=False, message=f"Parent directory does not exist: {parent_dir}. Use LS tool to verify correct path.")
            if not os.path.isdir(parent_dir):
                return ValidationResult(result=False, message=f"Parent path is not a directory: {parent_dir}")
                
        return ValidationResult(result=True)

    async def execute(self, input_data: Dict[str, Any]) -> str:
        file_path = input_data["file_path"]
        old_string = input_data.get("old_string", "")
        new_string = input_data["new_string"]
        
        try:
            # 处理创建新文件的情况
            if old_string == "" and not os.path.exists(file_path):
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(new_string)
                return f"Successfully created new file: {file_path}"
            
            # 读取现有文件内容
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 检查old_string出现的次数
            occurrences = content.count(old_string)
            
            # 验证唯一性
            if occurrences == 0:
                return f"Error: old_string not found in file. Ensure exact match including whitespace and indentation."
            if occurrences > 1:
                return f"Error: old_string appears {occurrences} times in file. Must uniquely identify a single instance with sufficient context."
            
            # 执行替换
            new_content = content.replace(old_string, new_string, 1)
            
            # 写入修改后的内容
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            
            # 计算变更的字符数
            change_count = abs(len(new_string) - len(old_string))
            return f"Successfully modified file: {file_path}\nChanged {change_count} characters. One occurrence of the specified text was replaced."
            
        except Exception as e:
            return f"Error editing file: {str(e)}"


class GlobTool(Tool):
    @property
    def name(self) -> str:
        return "GlobTool"

    async def description(self) -> str:
        return "Find files using glob patterns. Required parameter: 'pattern' (e.g., 'src/**/*.py'). Optional: 'ignore' (list of paths to exclude). Returns absolute paths."

    def is_read_only(self) -> bool:
        return True

    async def validate_input(self, input_data: Dict[str, Any]) -> ValidationResult:
        if "pattern" not in input_data:
            return ValidationResult(result=False, message="Missing required parameter: 'pattern'")
        return ValidationResult(result=True)

    async def execute(self, input_data: Dict[str, Any]) -> str:
        pattern = input_data["pattern"]
        ignore = input_data.get("ignore", [])
        
        try:
            # 获取绝对路径
            files = [os.path.abspath(f) for f in glob.glob(pattern, recursive=True)]
            
            if ignore:
                filtered_files = []
                for file in files:
                    if not any(ignored in file for ignored in ignore):
                        filtered_files.append(file)
                files = filtered_files
                
            if not files:
                return f"No files found matching pattern: {pattern}"
                
            result = [f"Found {len(files)} files matching {pattern}:"]
            for file in files[:10]:
                result.append(f"- {file}")
                
            if len(files) > 10:
                result.append(f"... and {len(files) - 10} more files")
                
            return "\n".join(result)
        except Exception as e:
            return f"Error finding files: {str(e)}"
