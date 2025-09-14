import os
import json
import re
from typing import Dict, Any, List
from .base import Tool, ValidationResult, TextBlock


class GrepTool(Tool):
    @property
    def name(self) -> str:
        return "GrepTool"

    async def description(self) -> str:
        return """Fast content search tool that works with any codebase size

## CRITICAL: Call Format Requirements
✅ CORRECT FORMAT (MANDATORY):
🔧 Use tool: GrepTool
   Parameters: {'pattern': 'your_regex_pattern', 'include': 'file_pattern'}

## Required Parameters
- `pattern`: Regular expression pattern to search for (e.g., "log.*Error", "function\\s+\\w+")
- `include`: **Mandatory file pattern filter** specifying which files to search (e.g., "*.js", "*.{ts,tsx}", "*.sh", "*.py")

## Features
- Searches file contents using regular expressions
- Supports full regex syntax
- Returns matching file paths sorted by modification time
- Shows snippet of matching lines with context"""

    def is_read_only(self) -> bool:
        return True

    async def validate_input(self, input_data: Dict[str, Any]) -> ValidationResult:
        if "pattern" not in input_data:
            return ValidationResult(result=False, message="Missing required parameter: 'pattern' (regex pattern to search)")
            
        if "include" not in input_data:
            return ValidationResult(result=False, message="Missing required parameter: 'include' (file pattern to search, e.g., '*.py')")
            
        try:
            # 验证正则表达式是否有效
            re.compile(input_data["pattern"])
        except re.error as e:
            return ValidationResult(result=False, message=f"Invalid regular expression: {str(e)}")
            
        return ValidationResult(result=True)

    async def execute(self, input_data: Dict[str, Any]) -> str:
        import glob
        
        pattern = input_data["pattern"]
        include = input_data["include"]
        case_sensitive = input_data.get("case_sensitive", True)
        max_matches = input_data.get("max_matches", 20)
        
        try:
            # 编译正则表达式
            flags = 0 if case_sensitive else re.IGNORECASE
            regex = re.compile(pattern, flags=flags)
            
            # 查找匹配的文件
            files = glob.glob(include, recursive=True)
            files = [f for f in files if os.path.isfile(f)]
            
            # 按修改时间排序（最新的在前）
            files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
            
            matches = []
            for file in files:
                try:
                    with open(file, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        if regex.search(content):
                            # 找到匹配，获取几行上下文
                            lines = content.splitlines()
                            line_numbers = []
                            sample_lines = []
                            
                            for i, line in enumerate(lines):
                                if regex.search(line):
                                    line_numbers.append(i + 1)  # 行号从1开始
                                    # 添加匹配行和前后各一行作为上下文
                                    start = max(0, i - 1)
                                    end = min(len(lines), i + 2)
                                    for j in range(start, end):
                                        sample_lines.append(f"Line {j + 1}: {lines[j][:100]}")
                                    
                                    if len(line_numbers) >= 3:  # 每个文件最多显示3个匹配位置
                                        break
                            
                            if line_numbers:
                                matches.append({
                                    "file": file,
                                    "line_numbers": line_numbers,
                                    "samples": sample_lines[:5]  # 最多5行示例
                                })
                                
                                if len(matches) >= max_matches:
                                    break  # 达到最大匹配数
                except Exception as e:
                    continue  # 忽略无法读取的文件
            
            if not matches:
                return f"No files matching pattern '{pattern}' found in files matching '{include}'"
                
            result = [f"Found {len(matches)} files containing pattern '{pattern}':"]
            for match in matches:
                result.append(f"\n- {match['file']}")
                result.append(f"  Lines: {', '.join(map(str, match['line_numbers']))}")
                for sample in match['samples']:
                    result.append(f"  {sample}")
            
            if len(files) > max_matches:
                result.append(f"\n... and {len(files) - max_matches} more files (limited to {max_matches} results)")
                
            return "\n".join(result)
        except Exception as e:
            return f"Error during grep operation: {str(e)}"


class NotebookEditTool(Tool):
    @property
    def name(self) -> str:
        return "NotebookEditTool"

    async def description(self) -> str:
        return """Completely replaces the contents of a specific cell in a Jupyter notebook (.ipynb file) with new source. Jupyter notebooks are interactive documents that combine code, text, and visualizations, commonly used for data analysis and scientific computing. The notebook_path parameter must be an absolute path, not a relative path. The cell_number is 0-indexed. Use edit_mode=insert to add a new cell at the index specified by cell_number. Use edit_mode=delete to delete the cell at the index specified by cell_number."""

    def is_read_only(self) -> bool:
        return False

    async def validate_input(self, input_data: Dict[str, Any]) -> ValidationResult:
        # 检查必填参数
        if "notebook_path" not in input_data:
            return ValidationResult(result=False, message="Missing required parameter: 'notebook_path' (must be an absolute path to a .ipynb file)")
            
        notebook_path = input_data["notebook_path"]
        
        # 验证文件路径是否为绝对路径
        if not os.path.isabs(notebook_path):
            return ValidationResult(result=False, message=f"notebook_path must be an absolute path, got: {notebook_path}")
            
        # 验证文件是否为.ipynb文件
        if not notebook_path.endswith(".ipynb"):
            return ValidationResult(result=False, message=f"notebook_path must point to a Jupyter notebook file (.ipynb), got: {notebook_path}")
            
        # 验证文件是否存在（删除模式除外）
        edit_mode = input_data.get("edit_mode", "replace")
        if edit_mode != "delete" and not os.path.exists(notebook_path):
            return ValidationResult(result=False, message=f"Jupyter notebook not found: {notebook_path}")
            
        # 验证文件是否为有效文件
        if os.path.exists(notebook_path) and not os.path.isfile(notebook_path):
            return ValidationResult(result=False, message=f"notebook_path is not a file: {notebook_path}")
            
        # 验证cell_number参数
        if "cell_number" not in input_data:
            return ValidationResult(result=False, message="Missing required parameter: 'cell_number' (0-indexed cell number)")
            
        try:
            cell_number = int(input_data["cell_number"])
            if cell_number < 0:
                return ValidationResult(result=False, message=f"cell_number must be a non-negative integer, got: {cell_number}")
        except ValueError:
            return ValidationResult(result=False, message=f"cell_number must be an integer, got: {input_data['cell_number']}")
            
        # 验证编辑模式
        valid_modes = ["replace", "insert", "delete"]
        if edit_mode not in valid_modes:
            return ValidationResult(result=False, message=f"edit_mode must be one of {valid_modes}, got: {edit_mode}")
            
        # 验证替换和插入模式下的source参数
        if edit_mode in ["replace", "insert"] and "source" not in input_data:
            return ValidationResult(result=False, message=f"Missing required parameter: 'source' (required for {edit_mode} mode)")
            
        # 验证插入模式下的cell_type参数
        if edit_mode == "insert" and "cell_type" not in input_data:
            return ValidationResult(result=False, message="Missing required parameter: 'cell_type' (required for insert mode, must be 'code' or 'markdown')")
            
        if edit_mode == "insert":
            cell_type = input_data["cell_type"]
            if cell_type not in ["code", "markdown"]:
                return ValidationResult(result=False, message=f"cell_type must be 'code' or 'markdown' for insert mode, got: {cell_type}")
            
        return ValidationResult(result=True)

    async def execute(self, input_data: Dict[str, Any]) -> str:
        notebook_path = input_data["notebook_path"]
        cell_number = int(input_data["cell_number"])
        edit_mode = input_data.get("edit_mode", "replace")
        
        try:
            # 读取现有笔记本内容（删除模式和插入模式可能需要）
            notebook_content = None
            if os.path.exists(notebook_path):
                with open(notebook_path, 'r', encoding='utf-8') as f:
                    notebook_content = json.load(f)
                
                # 验证笔记本结构
                if "cells" not in notebook_content:
                    return "Error: Invalid Jupyter notebook format - no 'cells' section found"
                
                cells = notebook_content["cells"]
                
                # 检查cell_number是否超出范围（替换和删除模式）
                if edit_mode in ["replace", "delete"] and cell_number >= len(cells):
                    return f"Error: cell_number {cell_number} is out of range. Notebook has {len(cells)} cells (0-indexed)"
            
            # 处理不同编辑模式
            if edit_mode == "replace":
                # 替换现有单元格内容
                source = input_data["source"]
                # 确保source是列表格式（Jupyter要求）
                if isinstance(source, str):
                    source = source.split('\n')
                
                cells[cell_number]["source"] = source
                cells[cell_number]["metadata"] = cells[cell_number].get("metadata", {})
                
                with open(notebook_path, 'w', encoding='utf-8') as f:
                    json.dump(notebook_content, f, indent=2, ensure_ascii=False)
                
                return f"Successfully replaced content in cell {cell_number} of notebook: {notebook_path}"
                
            elif edit_mode == "insert":
                # 插入新单元格
                cell_type = input_data["cell_type"]
                source = input_data["source"]
                # 确保source是列表格式
                if isinstance(source, str):
                    source = source.split('\n')
                
                # 如果笔记本不存在，创建新笔记本
                if notebook_content is None:
                    notebook_content = {
                        "cells": [],
                        "metadata": {},
                        "nbformat": 4,
                        "nbformat_minor": 5
                    }
                    cells = notebook_content["cells"]
                
                # 创建新单元格
                new_cell = {
                    "cell_type": cell_type,
                    "metadata": {},
                    "source": source
                }
                
                # 如果是代码单元格，添加输出部分
                if cell_type == "code":
                    new_cell["execution_count"] = None
                    new_cell["outputs"] = []
                
                # 插入单元格
                if cell_number <= len(cells):
                    cells.insert(cell_number, new_cell)
                else:
                    cells.append(new_cell)
                
                with open(notebook_path, 'w', encoding='utf-8') as f:
                    json.dump(notebook_content, f, indent=2, ensure_ascii=False)
                
                return f"Successfully inserted {cell_type} cell at position {cell_number} in notebook: {notebook_path}"
                
            elif edit_mode == "delete":
                # 删除单元格
                if notebook_content is None:
                    return f"Error: Cannot delete cell from non-existent notebook: {notebook_path}"
                
                deleted_cell = cells.pop(cell_number)
                cell_type = deleted_cell.get("cell_type", "unknown")
                
                with open(notebook_path, 'w', encoding='utf-8') as f:
                    json.dump(notebook_content, f, indent=2, ensure_ascii=False)
                
                return f"Successfully deleted {cell_type} cell at position {cell_number} from notebook: {notebook_path}"
                
        except Exception as e:
            return f"Error editing Jupyter notebook: {str(e)}"


class BashTool(Tool):
    @property
    def name(self) -> str:
        return "BashTool"

    async def description(self) -> str:
        return """Execute bash commands in the current working directory.

## CRITICAL: Call Format Requirements
✅ CORRECT FORMAT (MANDATORY):
🔧 Use tool: BashTool
   Parameters: {'command': 'your command here'}

## Required Parameters
- `command`: The bash command to execute (string type, required)
  - Examples: 'git reflog', 'ls -la', 'git stash list'
  - For Python commands, must use 'python3' instead of 'python'

## Optional Parameters
- `timeout`: Command timeout in seconds (integer type, default 10 seconds)"""

    def is_read_only(self) -> bool:
        return False

    async def validate_input(self, input_data: Dict[str, Any]) -> ValidationResult:
        if "command" not in input_data:
            return ValidationResult(result=False, message="Missing required parameter: 'command'")
            
        # 安全检查
        dangerous_cmds = ['sudo', 'rm -rf', 'mv /', 'cp /', 'dd ', 'shutdown', 'rm -r']
        for cmd in dangerous_cmds:
            if cmd in input_data["command"]:
                return ValidationResult(
                    result=False, 
                    message=f"Potentially dangerous command rejected: {cmd}"
                )
        
        # 检查Python命令使用建议
        if 'python ' in input_data["command"] and 'python3 ' not in input_data["command"]:
            return ValidationResult(
                result=True,
                message="Warning: Consider using 'python3' instead of 'python' for compatibility"
            )
                
        return ValidationResult(result=True)

    async def execute(self, input_data: Dict[str, Any]) -> str:
        import asyncio
        
        command = input_data["command"]
        timeout = input_data.get("timeout", 10)
        
        # 自动替换python为python3（如果用户使用了python）
        if 'python ' in command and 'python3 ' not in command:
            command = command.replace('python ', 'python3 ')
            modified_note = "Note: Command modified to use 'python3' for compatibility.\n"
        else:
            modified_note = ""
        
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), 
                timeout=timeout
            )
            
            result = [modified_note] if modified_note else []
            if stdout:
                output = stdout.decode('utf-8')
                result.append(f"Output:\n{output[:2000]}" + ("..." if len(output) > 2000 else ""))
            if stderr:
                error = stderr.decode('utf-8')
                # 检测常见错误并提供解决方案
                if "No module named" in error:
                    module = re.search(r"No module named '?(\w+)'?", error).group(1)
                    result.append(f"Errors:\n{error[:2000]}\n")
                    result.append(f"Suggestion: Install missing module with 'pip3 install {module}'")
                elif "command not found" in error:
                    cmd = re.search(r"(\w+) not found", error).group(1)
                    result.append(f"Errors:\n{error[:2000]}\n")
                    result.append(f"Suggestion: Install missing command or check spelling of '{cmd}'")
                else:
                    result.append(f"Errors:\n{error[:2000]}" + ("..." if len(error) > 2000 else ""))
                
            result.append(f"Exit code: {process.returncode}")
            return "\n".join(result)
        except asyncio.TimeoutError:
            return f"Command timed out after {timeout} seconds: {command}"
        except Exception as e:
            return f"Error executing command: {str(e)}"
