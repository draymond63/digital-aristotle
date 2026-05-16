# C:\Users\dan\AppData\Local\Programs\Ollama\ollama.exe pull qwen3.5:9b

import json
from typing import Generator
from ollama import ChatResponse
from ollama import Client, AsyncClient
# from transformers import AutoTokenizer
from datetime import datetime

from brains.prompts_system import TOPIC_ID_PROMPT


class Agent:
    def __init__(self, max_tokens=4096):
        self.model = 'qwen2.5:3b-instruct-q4_K_M'
        # self.model = 'phi4-mini:3.8b-q4_K_M'
        self.client = Client()
        # self.tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-3B-Instruct", trust_remote_code=True)
        # self.max_tokens = max_tokens


    def ask(self, system: str="", user: str="", **kwargs) -> str:
        return self.generate([{'role': 'system', 'content': system}, {'role': 'user', 'content': user}], **kwargs)
    
    def _generate(self, messages: list[dict[str, str]], temperature=0.7, **kwargs):
        # print("Generating response for messages:\n", messages, end="\n\n")
        # discussion = "\n".join([msg['content'] for msg in messages])
        # tokens = self.tokenizer.encode(discussion)
        # if len(tokens) > self.max_tokens:
        #     print(f"Warning: input tokens ({len(tokens)}) exceed max_tokens ({self.max_tokens}). Consider truncating the input.")

        response = self.client.chat(
            model=self.model,
            messages=messages,
            options={'temperature': temperature},
            **kwargs
        )
        return response

    def generate(self, *args, **kwargs) -> str:
        response = self._generate(*args, **kwargs)
        return response.message.content

    def generate_chunks(self,*args, **kwargs):
        responses = self._generate(*args, stream=True, **kwargs)
        yield from self._chunk_responses(responses)

    @staticmethod
    def _chunk_responses(response: Generator[ChatResponse, None, None], chunk_on="\n\n") -> Generator[str, None, None]:
        buffer = ""
        for chunk in response:
            content = chunk.message.content
            buffer += content
            while chunk_on in buffer:
                split_index = buffer.index(chunk_on)
                piece = buffer[:split_index].strip()
                buffer = buffer[split_index + 2:]
                if piece:
                    yield piece
        if buffer.strip():
            yield buffer.strip()


    def identify_topics(self, msg: str, threshold=0.5) -> list[str]:
        response = self.ask(system=TOPIC_ID_PROMPT, user=msg, format="json", temperature=0.0)
        try:
            json_response = json.loads(response)
            if not len(json_response):
                print("Warning: no topics identified")
                return []
            if isinstance(json_response, list):
                topics = [item["name"] for item in json_response if item["confidence"] > threshold]
            elif isinstance(json_response, dict):
                topics = [json_response["name"]]
        except Exception as e:
            raise RuntimeError(f"Failed to decode: {response}") from e
        return topics



if __name__ == "__main__":
    from brains.prompts_system import TOPIC_ID_PROMPT
    agent = Agent()
    startTime = datetime.now()
    response = agent.generate_chunks([{"role": "user", "content": "How is macroscopic inductance derived from the B field?"}], temperature=0.0)
    for chunk in response:
        print(chunk)
    endTime = datetime.now()
    print(f"Time taken: {endTime - startTime}")
