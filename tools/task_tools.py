import os
import re
import json
import time
import uuid
import asyncio
from datetime import datetime
from typing import List, Dict, Any, AsyncGenerator, Optional
from pydantic import BaseModel, Field
from .base import Tool, ValidationResult, TextBlock, create_assistant_message, create_user_message, normalize_messages, wait_for_rate_limit, record_request_timestamp
from .base import API_CONFIG, get_messages_path, overwrite_log, format_duration, last

class ThinkTool(Tool):
    @property
    def name(self) -> str:
        return "ThinkTool"

    async def description(self) -> str:
        return """Use the tool to think about something. It will not obtain new information or make any changes to the repository, but just log the thought. Use it when complex reasoning or brainstorming is needed. 

Common use cases:
1. When exploring a repository and discovering the source of a bug, call this tool to brainstorm several unique ways of fixing the bug
2. After receiving test results, use this tool to brainstorm ways to fix failing tests
3. When planning a complex refactoring, use this tool to outline different approaches"""

    def is_read_only(self) -> bool:
        return True

    async def validate_input(self, input_data: Dict[str, Any]) -> ValidationResult:
        # 检查是否提供了思考内容
        if "thought" not in input_data:
            return ValidationResult(result=False, message="Missing required parameter: 'thought' (the thinking content to log)")
            
        # 检查思考内容是否为空
        thought = input_data["thought"].strip()
        if not thought:
            return ValidationResult(result=False, message="Parameter 'thought' cannot be empty or only whitespace")
            
        return ValidationResult(result=True)

    async def execute(self, input_data: Dict[str, Any]) -> str:
        thought = input_data["thought"]
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        
        try:
            # 记录思考内容
            log_entry = f"[{timestamp}] Thought recorded: {thought[:50]}..."
            return f"Thought logged successfully at {timestamp}:\n\n{thought}\n\nThis thought has been recorded for transparency."
                
        except Exception as e:
            return f"Error logging thought: {str(e)}"


class TodoWriteTool(Tool):
    @property
    def name(self) -> str:
        return "TodoWriteTool"

    async def description(self) -> str:
        return """Use this tool to create and manage todo items for tracking tasks and progress. This tool provides comprehensive todo management:

## Required Parameters

- `operation`: **Mandatory field** specifying the action type. Must be one of:
  - 'create': Add a single new todo item
  - 'update': Modify an existing todo (requires 'id' and updated fields)
  - 'delete': Remove a todo by its 'id'
  - 'clear': Remove all todos (no additional parameters needed)
  - 'batch': Process multiple todos at once (requires 'todos' array)

- `todos`: Required for 'create' and 'batch' operations. An array of todo objects with:
  - 'id': Unique identifier (string, required for updates/deletes)
  - 'content': Task description (string, required)
  - 'status': Progress state (string, one of: 'pending', 'in_progress', 'completed')
  - 'priority': Importance level (string, one of: 'low', 'medium', 'high')"""

    def is_read_only(self) -> bool:
        return False
        
    def _get_todo_file_path(self) -> str:
        """获取存储待办事项的文件路径"""
        return os.path.join(os.getcwd(), ".todo.json")
    
    def _load_todos(self) -> List[Dict[str, Any]]:
        """从文件加载待办事项"""
        file_path = self._get_todo_file_path()
        if not os.path.exists(file_path):
            return []
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, Exception) as e:
            # 如果文件损坏，返回空列表
            return []
    
    def _save_todos(self, todos: List[Dict[str, Any]]) -> None:
        """将待办事项保存到文件"""
        file_path = self._get_todo_file_path()
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(todos, f, indent=2, ensure_ascii=False)
        except Exception as e:
            raise Exception(f"Failed to save todos: {str(e)}")

    async def validate_input(self, input_data: Dict[str, Any]) -> ValidationResult:
        # 检查操作类型
        if "operation" not in input_data:
            return ValidationResult(result=False, message="Missing required parameter: 'operation' (create, update, delete, clear, batch)")
            
        operation = input_data["operation"]
        valid_operations = ["create", "update", "delete", "clear", "batch"]
        if operation not in valid_operations:
            return ValidationResult(result=False, message=f"Invalid operation. Must be one of: {', '.join(valid_operations)}")
        
        # 验证创建操作
        if operation == "create":
            if "content" not in input_data:
                return ValidationResult(result=False, message="Missing required parameter: 'content' (todo item description)")
            
            status = input_data.get("status", "pending")
            valid_statuses = ["pending", "in_progress", "completed"]
            if status not in valid_statuses:
                return ValidationResult(result=False, message=f"Invalid status. Must be one of: {', '.join(valid_statuses)}")
                
            priority = input_data.get("priority", "medium")
            valid_priorities = ["low", "medium", "high"]
            if priority not in valid_priorities:
                return ValidationResult(result=False, message=f"Invalid priority. Must be one of: {', '.join(valid_priorities)}")
        
        # 验证更新操作
        elif operation == "update":
            if "id" not in input_data:
                return ValidationResult(result=False, message="Missing required parameter: 'id' (todo item ID to update)")
                
            if "updates" not in input_data or not input_data["updates"]:
                return ValidationResult(result=False, message="Missing or empty parameter: 'updates' (fields to update)")
                
            # 验证更新字段
            updates = input_data["updates"]
            valid_fields = ["content", "status", "priority"]
            for field in updates:
                if field not in valid_fields:
                    return ValidationResult(result=False, message=f"Invalid update field: {field}. Valid fields: {', '.join(valid_fields)}")
        
        # 验证删除操作
        elif operation == "delete":
            if "id" not in input_data:
                return ValidationResult(result=False, message="Missing required parameter: 'id' (todo item ID to delete)")
        
        # 验证批量操作
        elif operation == "batch":
            if "operations" not in input_data or not isinstance(input_data["operations"], list):
                return ValidationResult(result=False, message="Missing or invalid parameter: 'operations' (list of operations)")
                
        return ValidationResult(result=True)

    async def execute(self, input_data: Dict[str, Any]) -> str:
        operation = input_data["operation"]
        todos = self._load_todos()
        result = ""
        
        try:
            if operation == "create":
                # 创建新的待办事项
                new_todo = {
                    "id": str(len(todos) + 1),  # 简单的ID生成
                    "content": input_data["content"],
                    "status": input_data.get("status", "pending"),
                    "priority": input_data.get("priority", "medium"),
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat()
                }
                
                # 检查是否有多个进行中的任务
                if new_todo["status"] == "in_progress":
                    in_progress_count = sum(1 for t in todos if t["status"] == "in_progress")
                    if in_progress_count > 0:
                        return "Error: Cannot have more than one task in 'in_progress' state at a time."
                
                todos.append(new_todo)
                self._save_todos(todos)
                result = f"Successfully created todo item (ID: {new_todo['id']}): {new_todo['content']}"
            
            elif operation == "update":
                # 更新现有待办事项
                todo_id = input_data["id"]
                updates = input_data["updates"]
                
                # 查找待更新的任务
                todo_index = next((i for i, t in enumerate(todos) if t["id"] == todo_id), None)
                if todo_index is None:
                    return f"Error: Todo item with ID {todo_id} not found"
                
                # 应用更新
                todos[todo_index].update(updates)
                todos[todo_index]["updated_at"] = datetime.now().isoformat()
                self._save_todos(todos)
                result = f"Successfully updated todo item (ID: {todo_id}) with: {', '.join(updates.keys())}"
            
            elif operation == "delete":
                # 删除待办事项
                todo_id = input_data["id"]
                initial_count = len(todos)
                todos = [t for t in todos if t["id"] != todo_id]
                
                if len(todos) == initial_count:
                    return f"Error: Todo item with ID {todo_id} not found"
                
                self._save_todos(todos)
                result = f"Successfully deleted todo item (ID: {todo_id})"
            
            elif operation == "clear":
                # 清空所有待办事项
                self._save_todos([])
                result = "Successfully cleared all todo items"
            
            elif operation == "batch":
                # 批量操作
                operations = input_data["operations"]
                success_count = 0
                error_messages = []
                
                for op in operations:
                    try:
                        # 验证单个操作
                        validation = await self.validate_input(op)
                        if not validation.result:
                            error_messages.append(f"Invalid operation: {validation.message}")
                            continue
                            
                        # 执行单个操作
                        if op["operation"] == "create":
                            new_todo = {
                                "id": str(len(todos) + 1),
                                "content": op["content"],
                                "status": op.get("status", "pending"),
                                "priority": op.get("priority", "medium"),
                                "created_at": datetime.now().isoformat(),
                                "updated_at": datetime.now().isoformat()
                            }
                            todos.append(new_todo)
                            success_count += 1
                        elif op["operation"] == "update":
                            todo_index = next((i for i, t in enumerate(todos) if t["id"] == op["id"]), None)
                            if todo_index is not None:
                                todos[todo_index].update(op["updates"])
                                todos[todo_index]["updated_at"] = datetime.now().isoformat()
                                success_count += 1
                            else:
                                error_messages.append(f"Update failed: Todo {op['id']} not found")
                        elif op["operation"] == "delete":
                            initial_count = len(todos)
                            todos = [t for t in todos if t["id"] != op["id"]]
                            if len(todos) < initial_count:
                                success_count += 1
                            else:
                                error_messages.append(f"Delete failed: Todo {op['id']} not found")
                    except Exception as e:
                        error_messages.append(f"Operation failed: {str(e)}")
                
                self._save_todos(todos)
                result = f"Batch operation completed. {success_count} successful, {len(error_messages)} failed."
            
            # 添加当前待办事项列表摘要
            pending = sum(1 for t in todos if t["status"] == "pending")
            in_progress = sum(1 for t in todos if t["status"] == "in_progress")
            completed = sum(1 for t in todos if t["status"] == "completed")
            
            result += f"\n\nCurrent todo status: {pending} pending, {in_progress} in progress, {completed} completed"
            
            return result
            
        except Exception as e:
            return f"Error managing todos: {str(e)}"


class TaskToolInput(BaseModel):
    description: str = Field(description="Short task description (3-5 words)")
    prompt: str = Field(description="Detailed task instructions")
    model_name: Optional[str] = Field(None, description="Optional specific model name")
    subagent_type: Optional[str] = Field(None, description="Specialized agent type to use")
    safe_mode: Optional[bool] = Field(False, description="Enable safe mode (read-only tools)")
    max_steps: Optional[int] = Field(20, description="Maximum number of steps to execute (default 20)")


class TaskTool(Tool):
    @property
    def name(self) -> str:
        return "TaskTool"

    async def description(self) -> str:
        return "Launch specialized sub-agents to complete complex tasks"

    @property
    def input_schema(self) -> type[TaskToolInput]:
        return TaskToolInput

    def is_read_only(self) -> bool:
        return False

    async def validate_input(self, input_data: Dict[str, Any]) -> ValidationResult:
        try:
            # 检查是否只提供了description，如果是则通过验证
            if len(input_data) == 1 and "description" in input_data:
                return ValidationResult(result=True, message="仅提供了description，其他参数将动态生成")
                
            # 否则使用完整验证
            parsed_input = self.input_schema(**input_data)

            available_models = ["kimi-k2-0905-preview"]
            if parsed_input.model_name and parsed_input.model_name not in available_models:
                return ValidationResult(
                    result=False,
                    message=f"Model '{parsed_input.model_name}' not found. Available: {', '.join(available_models)}"
                )

            available_agents = await get_available_agent_types()
            if parsed_input.subagent_type and parsed_input.subagent_type not in available_agents:
                return ValidationResult(
                    result=False,
                    message=f"Agent '{parsed_input.subagent_type}' not found. Available: {', '.join(available_agents)}"
                )

            # 限制最大步骤数在合理范围
            if parsed_input.max_steps is not None and (parsed_input.max_steps < 1 or parsed_input.max_steps > 20):
                return ValidationResult(
                    result=False,
                    message=f"max_steps must be between 1 and 20"
                )

            return ValidationResult(result=True)

        except ValidationError as e:
            err_msg = e.errors()[0]["msg"]
            return ValidationResult(result=False, message=f"Invalid input: {err_msg}")

    async def call(
        self,
        input_data: Dict[str, Any],
        tool_context: Dict[str, Any] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        tool_context = tool_context or {}
        parsed_input = self.input_schema(** input_data)
        start_time = time.time_ns() // 1000

        options = tool_context.get("options", {})
        fork_number = options.get("forkNumber", 0)
        message_log_name = options.get("messageLogName", "task_logs")

        subagent_type = parsed_input.subagent_type or "general-purpose"
        progress_msg = create_assistant_message([TextBlock(type="text", text=f"Loading subagent: {subagent_type}")])
        yield {
            "type": "progress",
            "content": progress_msg,
            "normalizedMessages": [],
            "tools": []
        }
        current_messages = [progress_msg]

        agent_config = await get_agent_by_type(subagent_type)
        if not agent_config:
            available_agents = await get_available_agent_types()
            help_msg = f"Agent '{subagent_type}' not found. Available: {', '.join(available_agents)}"
            yield {"type": "result", "data": [TextBlock(type="text", text=help_msg)]}
            return

        from openai import OpenAI
        KIMI_API_KEY = os.getenv("KIMI_API_KEY", "sk-aVI5HrvCBk9FPTl50s31zHMGGVbDTTTJ9AezMQUheWL2fA5U")
        effective_model = parsed_input.model_name or agent_config["model_name"]
        model_msg = create_assistant_message([TextBlock(type="text", text=f"Using model: {effective_model}")])
        yield {
            "type": "progress",
            "content": model_msg,
            "normalizedMessages": normalize_messages(current_messages),
            "tools": []
        }
        current_messages.append(model_msg)

        tools = await get_task_tools(parsed_input.safe_mode)
        
        tool_filter = agent_config.get("tools")
        if tool_filter and tool_filter != "*":
            if isinstance(tool_filter, list):
                tools = [t for t in tools if t.name in tool_filter]

        user_message = create_user_message(parsed_input.prompt)
        current_messages.append(user_message)
        system_prompts = [agent_config["systemPrompt"]]

        context = {
            "cwd": os.getcwd(),
            "timestamp": time.time(),
            "user": os.getenv("USER", "unknown")
        }
        
        async for msg in query(
            current_messages.copy(),
            system_prompts,
            context,
            tools,
            effective_model,
            max_steps=parsed_input.max_steps,
            client=OpenAI(
                api_key=KIMI_API_KEY,
                base_url="https://api.moonshot.cn/v1"
            )
        ):
            current_messages.append(msg)
            
            from .base import get_messages_path, overwrite_log
            log_path = get_messages_path(
                message_log_name,
                fork_number,
                1  # 简化的sidechain_num
            )
            overwrite_log(log_path, current_messages)
            
            yield {
                "type": "progress",
                "content": msg,
                "normalizedMessages": normalize_messages(current_messages),
                "tools": [tool.name for tool in tools]
            }

        # 最终结果统计
        duration_ms = (time.time_ns() // 1000) - start_time
        tool_uses = 0
        for m in current_messages:
            if m.get("type") == "assistant" and "message" in m and "content" in m["message"]:
                for c in m["message"]["content"]:
                    if c.type == "tool_use":
                        tool_uses += 1

        text_results = []
        last_msg = last(current_messages) if current_messages else None
        if last_msg and last_msg.get("type") == "assistant" and "message" in last_msg and "content" in last_msg["message"]:
            text_results = [c for c in last_msg["message"]["content"] if c.type == "text"]
        
        yield {
            "type": "result",
            "data": text_results,
            "resultForAssistant": "\n".join([t.text for t in text_results if t.text]),
            "statistics": {
                "duration": format_duration(duration_ms),
                "tool_uses": tool_uses,
                "api_calls": len(API_CONFIG["request_timestamps"]),
                "model_used": effective_model,
                "steps_executed": min(len(current_messages) // 2, parsed_input.max_steps)
            }
        }

    async def execute(self, input_data: Dict[str, Any]) -> str:
        results = []
        async for result in self.call(input_data):
            if result["type"] == "result":
                results.append(result["resultForAssistant"])
        
        return "\n".join(results) if results else "Task completed with no results"


# 任务执行相关函数
async def get_tools() -> List[Tool]:
    from .file_tools import FileReadTool, FileWriteTool, FileEditTool, GlobTool
    from .code_tools import GrepTool, NotebookEditTool, BashTool
    from .web_tools import WebSearchTool, URLFetcherTool
    from .task_tools import ThinkTool, TodoWriteTool
    
    return [
        GrepTool(), 
        FileReadTool(), 
        GlobTool(), 
        BashTool(), 
        FileEditTool(), 
        FileWriteTool(), 
        ThinkTool(), 
        TodoWriteTool(), 
        URLFetcherTool(), 
        NotebookEditTool(), 
        WebSearchTool()
    ]


async def get_read_only_tools() -> List[Tool]:
    return [tool for tool in await get_tools() if tool.is_read_only()]


async def get_task_tools(safe_mode: bool) -> List[Tool]:
    all_tools = await get_tools() if not safe_mode else await get_read_only_tools()
    return [tool for tool in all_tools if tool.name != "TaskTool"]


async def get_agent_by_type(agent_type: str) -> Optional[Dict[str, Any]]:
    default_agents = {
        "general-purpose": {
            "systemPrompt": "You are a general-purpose AI agent. Use tools to complete tasks step by step. "
                            "First understand the task, then choose appropriate tools. "
                            "When using tools, you must wrap the call in <FunctionCallBegin> and <FunctionCallEnd> tags. "
                            "The format must be: <FunctionCallBegin>{\"name\":\"TOOL_NAME\",\"parameters\":{\"key\":\"value\"}}<FunctionCallEnd>"
                            "Never use other formats like <TOOL_NAME> or XML tags. "
                            "Optimize tool usage to minimize API calls - avoid redundant calls to the same tool with same parameters.",
            "model_name": "kimi-k2-0905-preview",
            "tools": "*"
        },
        "code-reviewer": {
            "systemPrompt": "You are a code reviewer. Follow these steps:\n"
                            "1. Use GlobTool to find relevant Python files (pattern: '*.py')\n"
                            "2. Select the most relevant file and use FileReadTool to read its content\n"
                            "3. Analyze the code directly from the content provided\n"
                            "4. If you need to run linters (like flake8), first check if they're installed. "
                            "   If not, install them with 'pip3 install flake8' before running\n"
                            "5. For Python commands, always use 'python3' instead of 'python'\n"
                            "6. After gathering necessary information, provide a comprehensive code review\n"
                            "\n"
                            "When using tools, wrap calls in <FunctionCallBegin> and <FunctionCallEnd> with valid JSON. "
                            "Avoid redundant tool calls. After completing your analysis, provide your final review.",
            "model_name": "kimi-k2-0905-preview",
            "tools": ["GrepTool", "FileReadTool", "GlobTool", "BashTool", "FileEditTool", "FileWriteTool", "ThinkTool", "TodoWriteTool"]
        },
        "researcher": {
            "systemPrompt": "You are a researcher. Use GlobTool to find relevant files, "
                            "use FileReadTool to extract information. "
                            "When using tools, you must wrap the call in <FunctionCallBegin> and <FunctionCallEnd> tags. "
                            "Optimize tool usage to minimize API calls.",
            "model_name": "kimi-k2-0905-preview",
            "tools": ["GrepTool", "FileReadTool", "GlobTool", "URLFetcherTool", "ThinkTool", "WebSearchTool"]
        },
        "data-scientist": {
            "systemPrompt": "You are a data scientist working with Jupyter notebooks. "
                            "Use NotebookEditTool to modify notebook cells, "
                            "FileReadTool to read notebook contents, "
                            "and BashTool to execute notebooks when needed. ",
            "model_name": "kimi-k2-0905-preview",
            "tools": ["NotebookEditTool", "FileReadTool", "BashTool", "ThinkTool", "TodoWriteTool"]
        }
    }
    return default_agents.get(agent_type)


async def get_available_agent_types() -> List[str]:
    return ["general-purpose", "code-reviewer", "researcher"]


async def query(
    messages: List[Dict[str, Any]],
    system_prompts: List[str],
    context: Dict[str, Any],
    tools: List[Tool],
    model_name: str,
    max_steps: int = 8,
    max_tool_uses_per_step: int = 1,
    client=None
) -> AsyncGenerator[Dict[str, Any], None]:
    step = 0
    current_messages = messages.copy()
    executed_tools = set()
    completed_analysis = False
    
    # 提取用户提到的路径（如果有）
    target_path = None
    for msg in current_messages:
        if msg.get("type") == "user" and "content" in msg:
            path_match = re.search(r'/[\w/\-]+fix-git', msg["content"])
            if path_match:
                target_path = path_match.group(0)
                break
    
    # 如果检测到目标路径，先添加cd命令提示
    if target_path:
        system_prompt = next((m for m in current_messages if m.get("type") == "system"), None)
        if system_prompt:
            system_prompt["content"] += f"\n\nImportant: First navigate to the target directory using: 'cd {target_path}'"
            system_prompt["content"] += "\nThen use 'git reflog' to find lost changes and appropriate git commands to recover them."

    current_messages.insert(0, {
        "type": "system",
        "content": "\n".join(system_prompts),
        "timestamp": time.time()
    })
    
    while step < max_steps and not completed_analysis:
        step += 1
        tool_uses_in_step = 0
        
        normalized_msgs = normalize_messages(current_messages)
        
        model_response = await call_kimi_model(
            normalized_msgs,
            model_name,
            tools,
            client=client
        )
        
        if model_response["type"] == "error":
            yield create_assistant_message([model_response["content"]])
            return
            
        assistant_msg = create_assistant_message([model_response["content"]])
        current_messages.append(assistant_msg)
        yield assistant_msg
        
        # 检查是否是最终分析结果（非工具调用）
        if model_response["type"] == "text":
            # 判断是否包含实质性分析内容
            if len(model_response["content"].text.strip()) > 50:
                completed_analysis = True
            return
            
        if model_response["type"] == "tool_use" and tool_uses_in_step < max_tool_uses_per_step:
            tool_uses_in_step += 1
            tool_use = model_response["content"]
            
            # 特殊处理Git相关任务
            if "git" in tool_use.name.lower() or "git" in str(tool_use.input).lower():
                # 检查是否先执行了cd命令
                has_cd = any(
                    "bash" in str(t.name).lower() and 
                    "cd" in str(t.input.get("command", "")).lower() and
                    target_path in str(t.input.get("command", ""))
                    for t in executed_tools
                )
                
                # 如果还没有cd到目标目录，先添加cd命令
                if target_path and not has_cd:
                    cd_msg = create_assistant_message([
                        TextBlock(
                            type="text", 
                            text=f"First, I need to navigate to the target directory: {target_path}"
                        )
                    ])
                    current_messages.append(cd_msg)
                    yield cd_msg
                    
                    # 自动添加cd命令工具调用
                    cd_tool = next((t for t in tools if t.name == "BashTool"), None)
                    if cd_tool:
                        cd_result = await cd_tool.execute({
                            "command": f"cd {target_path} && pwd"
                        })
                        
                        cd_result_msg = create_assistant_message([
                            TextBlock(
                                type="tool_use",
                                id=f"tool_{uuid.uuid4().hex[:8]}",
                                name="BashTool",
                                input={"command": f"cd {target_path} && pwd"},
                                output=cd_result
                            )
                        ])
                        current_messages.append(cd_result_msg)
                        yield cd_result_msg
                        executed_tools.add(f"BashTool:cd {target_path}")
            
            # 检查重复调用
            tool_key = f"{tool_use.name}:{json.dumps(tool_use.input, sort_keys=True)}"
            if tool_key in executed_tools:
                skip_msg = create_assistant_message([
                    TextBlock(type="text", text=f"Skipping redundant tool call: {tool_use.name} with same parameters")
                ])
                current_messages.append(skip_msg)
                yield skip_msg
                continue
            executed_tools.add(tool_key)
            
            # 查找工具
            tool = next((t for t in tools if t.name == tool_use.name), None)
            if not tool:
                error_msg = create_assistant_message([
                    TextBlock(type="text", text=f"Error: Tool '{tool_use.name}' not found")
                ])
                current_messages.append(error_msg)
                yield error_msg
                return
                
            # 验证输入
            validation = await tool.validate_input(tool_use.input)
            if not validation.result:
                # 特殊处理目录/文件混淆的情况
                if "Not a file" in validation.message and "FileReadTool" in tool_use.name:
                    # 建议使用BashTool替代
                    error_msg = create_assistant_message([
                        TextBlock(
                            type="text", 
                            text=f"{validation.message}\nSince this is a directory, I'll use BashTool to execute commands there instead."
                        )
                    ])
                    current_messages.append(error_msg)
                    yield error_msg
                    
                    # 尝试使用ls命令查看目录内容
                    bash_tool = next((t for t in tools if t.name == "BashTool"), None)
                    if bash_tool:
                        path = tool_use.input.get("path", "")
                        ls_result = await bash_tool.execute({
                            "command": f"ls -la {path}"
                        })
                        
                        ls_result_msg = create_assistant_message([
                            TextBlock(
                                type="tool_use",
                                id=f"tool_{uuid.uuid4().hex[:8]}",
                                name="BashTool",
                                input={"command": f"ls -la {path}"},
                                output=ls_result
                            )
                        ])
                        current_messages.append(ls_result_msg)
                        yield ls_result_msg
                        continue
                else:
                    error_msg = create_assistant_message([
                        TextBlock(type="text", text=f"Tool input validation failed: {validation.message}")
                    ])
                    current_messages.append(error_msg)
                    yield error_msg
                    return
            # 显示验证警告
            elif validation.message:
                warn_msg = create_assistant_message([
                    TextBlock(type="text", text=f"Tool input warning: {validation.message}")
                ])
                current_messages.append(warn_msg)
                yield warn_msg
                
            # 执行工具
            tool_result = await tool.execute(tool_use.input)
            
            # 创建结果消息
            result_msg = create_user_message(f"Tool {tool_use.name} returned: {tool_result}")
            current_messages.append(result_msg)
            yield create_assistant_message([
                TextBlock(
                    type="tool_use",
                    id=tool_use.id,
                    name=tool_use.name,
                    input=tool_use.input,
                    output=tool_result
                )
            ])

async def call_kimi_model(
    messages: List[Dict[str, Any]],
    model_name: str,
    tools: List[Tool],
    client=None
) -> Dict[str, Any]:
    from .base import API_CONFIG, wait_for_rate_limit, record_request_timestamp
    from openai import APIError, RateLimitError, APITimeoutError, APIConnectionError
    
    tool_descriptions = []
    for tool in tools:
        tool_descriptions.append(f"- {tool.name}: {await tool.description()}")
    
    system_message = next((m for m in messages if m["role"] == "system"), None)
    if system_message:
        system_message["content"] += "\n\nAvailable tools:\n" + "\n".join(tool_descriptions)
        system_message["content"] += "\n\nWhen calling a tool, always use the <FunctionCallBegin> and <FunctionCallEnd> tags with valid JSON."
        system_message["content"] += "\nThe format must be: <FunctionCallBegin>{\"name\":\"TOOL_NAME\",\"parameters\":{\"key\":\"value\"}}<FunctionCallEnd>"

    retry_count = 0
    while retry_count < API_CONFIG["max_retries"]:
        try:
            await wait_for_rate_limit()
            
            completion = client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=0.6,
                timeout=30
            )
            
            record_request_timestamp()

            response_message = completion.choices[0].message
            usage = completion.usage
            content = response_message.content or ""
            
            # 改进的工具调用解析逻辑
            func_call_str = None
            
            # 尝试解析标准格式 <FunctionCallBegin>...</FunctionCallEnd>
            if "<FunctionCallBegin>" in content and "<FunctionCallEnd>" in content:
                start_tag = "<FunctionCallBegin>"
                end_tag = "<FunctionCallEnd>"
                start_idx = content.index(start_tag) + len(start_tag)
                end_idx = content.index(end_tag)
                func_call_str = content[start_idx:end_idx].strip()
            
            # 尝试解析带工具标签的格式 <ToolName>...</ToolName>
            if not func_call_str:
                tool_tag_match = re.search(r'<(\w+Tool)>(.*?)</\1>', content, re.DOTALL)
                if tool_tag_match:
                    tool_name = tool_tag_match.group(1)
                    tool_params_str = tool_tag_match.group(2).strip()
                    try:
                        # 尝试直接解析参数
                        tool_params = json.loads(tool_params_str)
                        func_call_str = json.dumps({
                            "name": tool_name,
                            "parameters": tool_params
                        })
                    except json.JSONDecodeError:
                        # 尝试提取键值对
                        params = {}
                        for line in tool_params_str.split('\n'):
                            line = line.strip()
                            if ':' in line:
                                key, value = line.split(':', 1)
                                params[key.strip().strip('"')] = value.strip().strip('", ')
                        func_call_str = json.dumps({
                            "name": tool_name,
                            "parameters": params
                        })
            
            # 如果找到了函数调用
            if func_call_str:
                try:
                    func_call = json.loads(func_call_str)
                    return {
                        "type": "tool_use",
                        "content": TextBlock(
                            type="tool_use",
                            id=f"tool_{uuid.uuid4().hex[:8]}",
                            name=func_call["name"],
                            input=func_call["parameters"]
                        ),
                        "usage": usage
                    }
                except json.JSONDecodeError:
                    return {
                        "type": "error",
                        "content": TextBlock(
                            type="text", 
                            text=f"Failed to parse tool call: {func_call_str}. Please check the format."
                        ),
                        "usage": usage
                    }
                    
            # 如果没有找到工具调用，视为文本响应
            return {
                "type": "text",
                "content": TextBlock(type="text", text=content),
                "usage": usage
            }
            
        except RateLimitError as e:
            retry_count += 1
            wait_time = API_CONFIG["initial_retry_delay"] * (2 **(retry_count - 1))
            wait_time = min(wait_time, API_CONFIG["max_retry_delay"])
            
            if hasattr(e, 'message') and 'try again after' in e.message:
                try:
                    match = re.search(r'after (\d+) seconds', e.message)
                    if match:
                        wait_time = int(match.group(1)) + 0.5
                except:
                    pass
                    
            print(f"速率限制错误 (第 {retry_count}/{API_CONFIG['max_retries']} 次重试)，将在 {wait_time:.1f} 秒后重试...")
            await asyncio.sleep(wait_time)
            
            if retry_count >= API_CONFIG["max_retries"]:
                return {
                    "type": "error",
                    "content": TextBlock(
                        type="text", 
                        text=f"已达到最大重试次数 {API_CONFIG['max_retries']}，仍受速率限制: {str(e)}"
                    ),
                    "usage": None
                }
                
        except (APIError, APITimeoutError, APIConnectionError) as e:
            retry_count += 1
            wait_time = API_CONFIG["initial_retry_delay"] * (2** (retry_count - 1))
            wait_time = min(wait_time, API_CONFIG["max_retry_delay"])
            
            print(f"API错误 (第 {retry_count}/{API_CONFIG['max_retries']} 次重试): {str(e)}，将在 {wait_time:.1f} 秒后重试...")
            await asyncio.sleep(wait_time)
            
            if retry_count >= API_CONFIG["max_retries"]:
                return {
                    "type": "error",
                    "content": TextBlock(
                        type="text", 
                        text=f"已达到最大重试次数 {API_CONFIG['max_retries']}，API错误: {str(e)}"
                    ),
                    "usage": None
                }
                
        except Exception as e:
            return {
                "type": "error",
                "content": TextBlock(type="text", text=f"模型调用失败: {str(e)}"),
                "usage": None
            }
    
    return {
        "type": "error",
        "content": TextBlock(
            type="text", 
            text=f"已达到最大重试次数 {API_CONFIG['max_retries']}，无法完成模型调用"
        ),
        "usage": None
    }


# 辅助函数
def last(arr: List[Any]) -> Any:
    return arr[-1] if arr and len(arr) > 0 else None


def format_duration(ms: int) -> str:
    seconds = ms // 1000
    remaining_ms = ms % 1000
    if remaining_ms > 0:
        return f"{seconds}s {remaining_ms}ms"
    return f"{seconds}s"
