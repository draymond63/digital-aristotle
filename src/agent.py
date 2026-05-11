# C:\Users\dan\AppData\Local\Programs\Ollama\ollama.exe pull qwen3.5:9b

from ollama import chat, ChatResponse
from datetime import datetime



def ask(msg):
    response: ChatResponse = chat(
        model='qwen3.5:9b',
        messages=[{'role': 'user', 'content': msg}],
    )
    print(response.message.content)


startTime = datetime.now()
ask("Hello!")
endTime = datetime.now()
print(f"Time taken: {endTime - startTime}")
