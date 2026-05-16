# C:\Users\dan\AppData\Local\Programs\Ollama\ollama.exe pull qwen3.5:9b

import json
from ollama import chat, ChatResponse
from ollama import AsyncClient
# from transformers import AutoTokenizer
from datetime import datetime

from brains.prompts import TOPIC_ID_PROMPT


class Agent:
    def __init__(self, max_tokens=4096):
        self.model = 'qwen2.5:3b-instruct-q4_K_M'
        # self.model = 'phi4-mini:3.8b-q4_K_M'
        self.client = AsyncClient()
        # self.tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-3B-Instruct", trust_remote_code=True)
        # self.max_tokens = max_tokens


    def ask(self, system: str="", user: str="", **kwargs) -> str:
        return self.generate([{'role': 'system', 'content': system}, {'role': 'user', 'content': user}], **kwargs)

    def generate(self, messages: list[dict[str, str]], temperature=0.7, **kwargs) -> ChatResponse:
        # print("Generating response for messages:\n", messages, end="\n\n")
        # discussion = "\n".join([msg['content'] for msg in messages])
        # tokens = self.tokenizer.encode(discussion)
        # if len(tokens) > self.max_tokens:
        #     print(f"Warning: input tokens ({len(tokens)}) exceed max_tokens ({self.max_tokens}). Consider truncating the input.")

        return chat(
            model=self.model,
            messages=messages,
            options={'temperature': temperature},
            **kwargs
        )

    async def generate_async(self, messages: list[dict[str, str]], temperature=0.7):
        return await self.client.chat(
            model=self.model,
            messages=messages,
            options={'temperature': temperature}
        )

    def identify_topics(self, msg: str, threshold=0.5) -> list[str]:
        response = self.ask(system=TOPIC_ID_PROMPT, user=msg, format="json", temperature=0.0)
        json_response = json.loads(response.message.content)
        if isinstance(json_response, list):
            topics = [item["name"] for item in json_response if item["confidence"] > threshold]
        elif isinstance(json_response, dict):
            topics = [json_response["name"]]
        return topics



if __name__ == "__main__":
    from brains.prompts import TOPIC_ID_PROMPT
    agent = Agent()
    startTime = datetime.now()
    response = agent.ask(system=TOPIC_ID_PROMPT,user="How is macroscopic inductance derived from the B field?", temperature=0.0)
    print(response)
    endTime = datetime.now()
    print(f"Time taken: {endTime - startTime} ({response.eval_duration})")
