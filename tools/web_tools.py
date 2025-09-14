import os
import re
import json
import hashlib
from urllib.parse import urlparse, urlunparse
from typing import Dict, Any, Optional
from bs4 import BeautifulSoup
import aiohttp
from openai import OpenAI
from .base import Tool, ValidationResult, TextBlock, CACHE_DIR, CACHE_TTL


class WebSearchTool(Tool):
    @property
    def name(self) -> str:
        return "WebSearchTool"

    async def description(self) -> str:
        return """- Allows Kode to search the web and use the results to inform responses
- Provides up-to-date information for current events and recent data
- Returns search result information formatted as search result blocks
- Use this tool for accessing information beyond the Kode's knowledge cutoff
- Searches are performed automatically within a single API call using DuckDuckGo"""

    def is_read_only(self) -> bool:
        return True

    async def validate_input(self, input_data: Dict[str, Any]) -> ValidationResult:
        # 验证是否提供了搜索查询
        if "query" not in input_data:
            return ValidationResult(result=False, message="Missing required parameter: 'query' (search term or phrase)")
            
        # 验证查询不为空
        query = input_data["query"].strip()
        if not query:
            return ValidationResult(result=False, message="Search query cannot be empty or only whitespace")
            
        # 验证查询长度
        if len(query) < 3:
            return ValidationResult(result=False, message="Search query is too short (minimum 3 characters)")
            
        # 验证结果数量参数（如果提供）
        if "num_results" in input_data:
            try:
                num = int(input_data["num_results"])
                if num < 1 or num > 20:
                    return ValidationResult(result=False, message="num_results must be between 1 and 20")
            except ValueError:
                return ValidationResult(result=False, message="num_results must be an integer")
                
        return ValidationResult(result=True)

    async def execute(self, input_data: Dict[str, Any]) -> str:
        query = input_data["query"].strip()
        num_results = int(input_data.get("num_results", 5))  # 默认返回5个结果
        
        try:
            # 使用DuckDuckGo的HTML接口进行搜索（模拟浏览器请求）
            url = f"https://html.duckduckgo.com/html/?q={aiohttp.helpers.escape_uri_component(query)}"
            
            # 模拟浏览器请求头
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'DNT': '1',  # 不跟踪请求
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=15) as response:
                    if response.status != 200:
                        return f"Search failed with status code: {response.status}"
                        
                    # 获取HTML内容并解析
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # 提取搜索结果
                    results = []
                    result_elements = soup.select('div.result')  # 定位结果元素
                    
                    for element in result_elements[:num_results]:
                        # 提取标题和链接
                        title_element = element.select_one('a.result__a')
                        if not title_element:
                            continue
                            
                        title = title_element.get_text(strip=True)
                        url = title_element['href']
                        
                        # 提取摘要
                        snippet_element = element.select_one('a.result__snippet')
                        snippet = snippet_element.get_text(strip=True) if snippet_element else ""
                        
                        # 提取来源和时间
                        source_element = element.select_one('span.result__url')
                        source = source_element.get_text(strip=True) if source_element else ""
                        
                        results.append({
                            "title": title,
                            "snippet": snippet,
                            "source": source,
                            "url": url
                        })
                    
                    # 格式化结果
                    if not results:
                        return f"No results found for query: '{query}'"
                        
                    output = [f"Search results for '{query}' ({len(results)}):"]
                    for i, item in enumerate(results, 1):
                        output.append(f"\n{i}. {item['title']}")
                        if item.get('source'):
                            output.append(f"   Source: {item['source']}")
                        if item.get('snippet'):
                            output.append(f"   Snippet: {item['snippet'][:200]}{'...' if len(item['snippet']) > 200 else ''}")
                        if item.get('url'):
                            output.append(f"   URL: {item['url']}")
                    
                    return "\n".join(output)
                    
        except asyncio.TimeoutError:
            return f"Search timed out for query: '{query}'"
        except Exception as e:
            return f"Error performing search: {str(e)}"


class URLFetcherTool(Tool):
    @property
    def name(self) -> str:
        return "URLFetcherTool"

    async def description(self) -> str:
        return """- Fetches content from a specified URL and processes it using an AI model
- Takes a URL and a prompt as input
- Fetches the URL content, converts HTML to markdown
- Processes the content with the prompt using a small, fast model
- Returns the model's response about the content
- Use this tool when you need to retrieve and analyze web content"""

    def is_read_only(self) -> bool:
        return True
        
    def _get_cache_path(self, url: str) -> str:
        """生成URL对应的缓存文件路径"""
        url_hash = hashlib.md5(url.encode('utf-8')).hexdigest()
        return os.path.join(CACHE_DIR, f"{url_hash}.json")
    
    def _cleanup_cache(self) -> None:
        """清理过期的缓存文件"""
        import time
        now = time.time()
        for filename in os.listdir(CACHE_DIR):
            file_path = os.path.join(CACHE_DIR, filename)
            if os.path.isfile(file_path) and now - os.path.getmtime(file_path) > CACHE_TTL:
                try:
                    os.remove(file_path)
                except Exception:
                    pass
    
    async def _fetch_from_cache(self, url: str) -> Optional[Dict[str, Any]]:
        """从缓存获取URL内容"""
        self._cleanup_cache()  # 先清理过期缓存
        cache_path = self._get_cache_path(url)
        
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                    # 检查缓存是否有效
                    if time.time() - cache_data.get('timestamp', 0) <= CACHE_TTL:
                        return cache_data
            except Exception:
                pass
        return None
    
    async def _save_to_cache(self, url: str, data: Dict[str, Any]) -> None:
        """将URL内容保存到缓存"""
        cache_path = self._get_cache_path(url)
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump({
                    'timestamp': time.time(),
                    'data': data
                }, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
    
    async def _fetch_url_content(self, url: str) -> Dict[str, Any]:
        """获取URL内容并处理重定向"""
        # 确保URL是HTTPS
        parsed = urlparse(url)
        if parsed.scheme == 'http':
            parsed = parsed._replace(scheme='https')
            url = urlunparse(parsed)
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, allow_redirects=False, timeout=10) as response:
                    # 处理重定向
                    if 300 <= response.status < 400 and 'Location' in response.headers:
                        redirect_url = response.headers['Location']
                        # 处理相对路径重定向
                        if not redirect_url.startswith(('http://', 'https://')):
                            redirect_url = urlunparse(parsed._replace(path=redirect_url))
                        return {
                            'status': 'redirect',
                            'redirect_url': redirect_url,
                            'original_url': url
                        }
                    
                    # 处理成功响应
                    if response.status == 200:
                        content_type = response.headers.get('Content-Type', '').lower()
                        content = await response.text()
                        
                        # 简单的HTML到Markdown转换
                        if 'text/html' in content_type:
                            # 移除HTML标签
                            content = re.sub(r'<[^>]*?>', ' ', content)
                            # 合并空白字符
                            content = re.sub(r'\s+', ' ', content).strip()
                        
                        return {
                            'status': 'success',
                            'content': content,
                            'content_type': content_type,
                            'url': url
                        }
                    
                    # 处理错误状态码
                    return {
                        'status': 'error',
                        'message': f"HTTP error {response.status}",
                        'url': url
                    }
                    
            except Exception as e:
                return {
                    'status': 'error',
                    'message': str(e),
                    'url': url
                }
    
    async def _process_content_with_model(self, content: str, prompt: str) -> str:
        """使用AI模型处理内容"""
        # 使用小型快速模型处理内容
        KIMI_API_KEY = os.getenv("KIMI_API_KEY", "sk-aVI5HrvCBk9FPTl50s31zHMGGVbDTTTJ9AezMQUheWL2fA5U")
        client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY", KIMI_API_KEY),  # fallback to KIMI API key
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.moonshot.cn/v1")  # fallback to KIMI API
        )
        
        # 如果内容太长，先进行摘要
        max_content_length = 4000
        if len(content) > max_content_length:
            content = content[:max_content_length] + "\n[Content truncated due to length]"
        
        try:
            response = client.chat.completions.create(
                model="gpt-3.5-turbo" if "openai.com" in client.base_url else "kimi-k2-0905-preview",
                messages=[
                    {"role": "system", "content": "You analyze web content and answer questions about it based on the user's prompt."},
                    {"role": "user", "content": f"Content: {content}\n\nPrompt: {prompt}"}
                ],
                temperature=0.3,
                max_tokens=500
            )
            
            return response.choices[0].message.content or "No response generated."
            
        except Exception as e:
            return f"Error processing content with model: {str(e)}"

    async def validate_input(self, input_data: Dict[str, Any]) -> ValidationResult:
        # 检查必填参数
        if "url" not in input_data:
            return ValidationResult(result=False, message="Missing required parameter: 'url' (the URL to fetch)")
            
        if "prompt" not in input_data:
            return ValidationResult(result=False, message="Missing required parameter: 'prompt' (description of what to extract/analyze)")
            
        # 验证URL格式
        url = input_data["url"]
        parsed = urlparse(url)
        if not all([parsed.scheme, parsed.netloc]):
            return ValidationResult(result=False, message=f"Invalid URL format: {url}. Must be a fully-formed URL (e.g., https://example.com)")
            
        return ValidationResult(result=True)

    async def execute(self, input_data: Dict[str, Any]) -> str:
        import time
        url = input_data["url"]
        prompt = input_data["prompt"]
        
        try:
            # 尝试从缓存获取
            cache_data = await self._fetch_from_cache(url)
            if cache_data:
                fetch_result = cache_data['data']
                result_msg = "Using cached content (less than 15 minutes old). "
            else:
                # 从网络获取
                fetch_result = await self._fetch_url_content(url)
                await self._save_to_cache(url, fetch_result)
                result_msg = ""
            
            # 处理结果
            if fetch_result['status'] == 'redirect':
                return f"{result_msg}URL redirected. Original: {fetch_result['original_url']}\nREDIRECT_URL: {fetch_result['redirect_url']}\nPlease make a new request with the redirect URL."
            
            if fetch_result['status'] == 'error':
                return f"{result_msg}Failed to fetch URL: {fetch_result['message']}\nURL: {fetch_result['url']}"
            
            # 内容处理
            if not fetch_result['content']:
                return f"{result_msg}Fetched URL but found no content.\nURL: {fetch_result['url']}"
            
            # 使用模型处理内容
            model_response = await self._process_content_with_model(
                fetch_result['content'], 
                prompt
            )
            
            # 返回结果
            return f"{result_msg}Successfully processed content from {fetch_result['url']}:\n\n{model_response}\n\nNote: Content may be summarized for brevity."
            
        except Exception as e:
            return f"Error fetching or processing URL: {str(e)}"
