import httpx

api_key = "sk-ws-H.EDPIXLI.EcGp.MEUCIDTLTBn0KceSa-OtCji-ZdS82RPCwZj9QC5AVs-0_itVAiEAvUhcabxZRRLRzWfJZxV8TvhFrXW6SaMj3bYIbeG4wW8"

url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json",
}

data = {
    "model": "qwen-plus",
    "messages": [
        {
            "role": "user",
            "content": "你好"
        }
    ]
}

response = httpx.post(
    url,
    headers=headers,
    json=data,
    timeout=30
)

print("status:", response.status_code)
print(response.text)