# C:\Users\dan\AppData\Local\Programs\Ollama\ollama.exe pull qwen3.5:9b

import json
from ollama import chat, ChatResponse
from datetime import datetime

from prompts import TOPIC_ID_PROMPT


class Agent:
    def __init__(self):
        self.model = 'qwen3.5:9b'

    def ask(self, system: str="", user: str="", **kwargs) -> str:
        return self.generate([{'role': 'system', 'content': system}, {'role': 'user', 'content': user}], **kwargs)

    def generate(self, messages: list[dict[str, str]], temperature=0.7) -> ChatResponse:
        return chat(
            model=self.model,
            messages=messages,
            options={'temperature': temperature}
        )
    
    def identify_topics(self, msg: str, threshold=0.5) -> list[str]:
        print("Asking")
        response = self.generate(system=TOPIC_ID_PROMPT, user=msg, temperature=0.0)
        print(response)
        json_response = json.loads(response.message.content)
        topics = [item["name"] for item in json_response if item["confidence"] > threshold]
        return topics



if __name__ == "__main__":
    agent = Agent()
    startTime = datetime.now()
    agent.ask(system="Be mean to the user", user="Hello!")
    endTime = datetime.now()
    print(f"Time taken: {endTime - startTime}")
