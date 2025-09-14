import os
import asyncio
import json
from openai import OpenAI
from tools.task_tools import TaskTool

# 配置API密钥
KIMI_API_KEY = os.getenv("KIMI_API_KEY")
if not KIMI_API_KEY:
    raise ValueError("请设置KIMI_API_KEY环境变量")

client = OpenAI(
    api_key=KIMI_API_KEY,
    base_url="https://api.moonshot.cn/v1"
)

MODEL_CONFIG = {
    "default": "kimi-k2-0905-preview",
    "code": "kimi-k2-0905-preview",
    "research": "kimi-k2-0905-preview"
}


def get_user_input():
    # 第一次询问：获取代码路径
    code_path = input("Please give the code path: ").strip()
    while not code_path:
        print("Code path cannot be empty.")
        code_path = input("Please give the code path: ").strip()
    
    # 第二次询问：获取具体指令
    instruction = input("Please give instruction: ").strip()
    while not instruction:
        print("Instruction cannot be empty.")
        instruction = input("Please give instruction: ").strip()
    
    # 构建测试输入字典
    test_input = {
        "description": f"""you should cd to path: {code_path}
        {instruction}"""
    }
    return test_input


async def test_task_tool():
    task_tool = TaskTool()

    # 测试输入 - Git恢复任务
    test_input = get_user_input()

    print(f"输入: {test_input['description']}")

    print("\n开始执行任务...\n")
    tool_context = {
        "options": {
            "verbose": True,
            "messageLogName": "kimi_test_task"
        }
    }
    
    # 生成缺失的参数
    async def generate_missing_parameters(description):
        """让agent基于任务描述生成必要的参数"""
        print("\n📝 正在生成任务所需参数...")
        
        # 使用通用模型生成详细提示和其他参数
        system_prompt = """你是一个参数生成助手。基于简短的任务描述，生成以下参数:
1. prompt: 详细的任务指令（100-200字）
2. subagent_type: 适合的子代理类型（general-purpose, code-reviewer, researcher, data-scientist）
3. safe_mode: 是否启用安全模式（True/False）
4. max_steps: 5-20之间

返回格式: 直接返回包含这些参数的JSON对象，不要添加额外解释。"""
        
        try:
            # 调用模型生成参数
            response = client.chat.completions.create(
                model=MODEL_CONFIG["default"],
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"任务描述: {description}"}
                ],
                temperature=0.7
            )
            
            # 解析生成的参数
            parameters = json.loads(response.choices[0].message.content)
            print("✅ 参数生成完成:")
            for key, value in parameters.items():
                print(f"- {key}: {value}")
            return parameters
            
        except Exception as e:
            print(f"⚠️ 参数生成失败，使用默认值: {str(e)}")
            # 返回默认参数
            return {
                "prompt": f"完成与'{description}'相关的任务，使用适当的工具和步骤",
                "subagent_type": "general-purpose",
                "safe_mode": False,
                "max_steps": 20
            }
    
    # 生成缺失的参数
    generated_params = await generate_missing_parameters(test_input["description"])
    
    # 合并用户输入和生成的参数
    full_input = {**test_input,** generated_params}
    
    # 执行任务
    async for result in task_tool.call(full_input, tool_context):
        if result["type"] == "progress":
            content = result["content"]
            if content.get("type") == "assistant" and "message" in content and "content" in content["message"]:
                for block in content["message"]["content"]:
                    if block.type == "text":
                        print(f"▶️ {block.text}")
                    elif block.type == "tool_use":
                        print(f"\n🔧 使用工具: {block.name}")
                        print(f"   参数: {block.input}")
                        if block.output:
                            print(f"   结果: {block.output[:500]}...")
        
        elif result["type"] == "result":
            print("\n📋 最终结果:")
            print(result["resultForAssistant"])
            print("\n📊 统计信息:")
            stats = result["statistics"]
            print(f"- 耗时: {stats['duration']}")
            print(f"- 工具使用次数: {stats['tool_uses']}")
            print(f"- API调用次数: {stats['api_calls']}")
            print(f"- 执行步骤: {stats['steps_executed']}/{full_input['max_steps']}")
            print(f"- 使用模型: {stats['model_used']}")


if __name__ == "__main__":
    asyncio.run(test_task_tool())
