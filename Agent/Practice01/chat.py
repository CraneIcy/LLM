import configparser
import json
import requests

config = configparser.ConfigParser()
config.read(".config.ini", encoding="utf-8")

messages = []

while True:
    messages.append({"role": "user", "content": input("你：")})

    resp = requests.post(
        url=f"{config['llm']['base_url']}/chat/completions",
        headers={"Authorization": f"Bearer {config['llm']['api_key']}"},
        json={
            "model": config["llm"]["model"],
            "messages": messages,
            "stream": True,
        },
        stream=True,
    )

    assistant_reply = ""
    for line in resp.iter_lines():
        if line and line.startswith(b"data: "):
            data = line[6:].decode("utf-8")
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            content = chunk["choices"][0]["delta"].get("content", "")
            if content:
                assistant_reply += content
                print(content, end="", flush=True)

    print()
    messages.append({"role": "assistant", "content": assistant_reply})
