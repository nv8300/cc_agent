import asyncio
import os
import time
import uuid
import json
import hashlib
from datetime import datetime
from typing import List, Dict, Any, Optional, AsyncGenerator
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pydantic import BaseModel, ValidationError

# 缓存配置
CACHE_DIR = os.path.join(os.path.expanduser("~"), ".url_fetcher_cache")
CACHE_TTL = 900  # 15分钟缓存有效期

# 确保缓存目录存在
os.makedirs(CACHE_DIR, exist_ok=True)

# API配置
API_CONFIG = {
    "max_retries": 5,
    "initial_retry_delay": 5.0,
    "max_retry_delay": 10.0,
    "rpm_limit": 3,
    "request_timestamps": []
}

@dataclass
class TextBlock:
    type: str  # 'text' 或 'tool_use'
    text: Optional[str] = None
    id: Optional[str] = None
    name: Optional[str] = None
    input: Optional[Dict[str, Any]] = None
    output: Optional[str] = None


class ValidationResult(BaseModel):
    result: bool
    message: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None


class Tool(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    async def description(self) -> str:
        pass

    @abstractmethod
    def is_read_only(self) -> bool:
        pass

    @abstractmethod
    async def validate_input(self, input_data: Dict[str, Any]) -> ValidationResult:
        pass

    @abstractmethod
    async def execute(self, input_data: Dict[str, Any]) -> str:
        pass


# 通用工具函数
def last(arr: List[Any]) -> Any:
    return arr[-1] if arr and len(arr) > 0 else None


def format_duration(ms: int) -> str:
    seconds = ms // 1000
    remaining_ms = ms % 1000
    if remaining_ms > 0:
        return f"{seconds}s {remaining_ms}ms"
    return f"{seconds}s"


def format_number(num: int) -> str:
    return f"{num:,}"


# 速率限制管理
def clean_old_timestamps() -> None:
    now = time.time()
    API_CONFIG["request_timestamps"] = [
        ts for ts in API_CONFIG["request_timestamps"]
        if now - ts < 60
    ]


async def wait_for_rate_limit() -> None:
    clean_old_timestamps()
    now = time.time()
    
    while len(API_CONFIG["request_timestamps"]) >= API_CONFIG["rpm_limit"]:
        oldest_request = API_CONFIG["request_timestamps"][0]
        wait_time = 60 - (now - oldest_request) + 0.1
        
        if wait_time > 0:
            print(f"已达API速率限制，等待 {wait_time:.1f} 秒...")
            await asyncio.sleep(wait_time)
            now = time.time()
            clean_old_timestamps()
        else:
            clean_old_timestamps()


def record_request_timestamp() -> None:
    API_CONFIG["request_timestamps"].append(time.time())
    clean_old_timestamps()


# 日志工具
def get_messages_path(log_name: str, fork_num: int, sidechain_num: int) -> str:
    log_dir = os.path.join("logs", log_name)
    os.makedirs(log_dir, exist_ok=True)
    return os.path.join(log_dir, f"fork{fork_num}_side{sidechain_num}.log")


def overwrite_log(file_path: str, messages: List[Dict[str, Any]]) -> None:
    with open(file_path, "w", encoding="utf-8") as f:
        for msg in messages:
            msg_type = msg.get("type", "unknown")
            content = str(msg.get("content", "No content"))
            timestamp = time.ctime(msg.get("timestamp", time.time()))
            f.write(f"[{timestamp}] [{msg_type}] {content[:200]}...\n")


# 消息处理工具
def create_user_message(content: str) -> Dict[str, Any]:
    return {
        "type": "user",
        "id": f"user_{uuid.uuid4().hex[:8]}",
        "content": content,
        "timestamp": time.time()
    }


def create_assistant_message(content: List[TextBlock]) -> Dict[str, Any]:
    input_tokens = sum(len(block.text) // 4 for block in content if block.text)
    output_tokens = sum(len(str(block.input)) // 4 for block in content if block.type == "tool_use")
    
    return {
        "type": "assistant",
        "id": f"assistant_{uuid.uuid4().hex[:8]}",
        "message": {
            "content": content,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0
            }
        },
        "timestamp": time.time()
    }


def normalize_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized = []
    
    system_msgs = [msg for msg in messages if msg.get("type") == "system"]
    if system_msgs:
        normalized.append({
            "role": "system",
            "content": system_msgs[0]["content"]
        })
    
    for msg in messages:
        if msg["type"] == "user":
            normalized.append({
                "role": "user",
                "content": msg["content"]
            })
        elif msg["type"] == "assistant":
            if "message" in msg and "content" in msg["message"]:
                content = msg["message"]["content"]
                if any(block.type == "tool_use" for block in content):
                    tool_blocks = [b for b in content if b.type == "tool_use"]
                    tool_content = []
                    for block in tool_blocks:
                        tool_content.append({
                            "name": block.name,
                            "parameters": block.input
                        })
                    normalized.append({
                        "role": "assistant",
                        "content": f"<FunctionCallBegin>{json.dumps(tool_content[0])}<FunctionCallEnd>"
                    })
                else:
                    text_content = "\n".join([block.text for block in content if block.text])
                    normalized.append({
                        "role": "assistant",
                        "content": text_content
                    })
    
    return normalized
