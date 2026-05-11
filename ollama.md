ollama ps

ollama pull qwen3.5:4b
ollama pull qwen2.5:3b-instruct-q4_K_M

ollama list
ollama ps
ollama show qwen2.5:3b

curl http://127.0.0.1:11434/api/tags


curl http://localhost:11434/api/generate -d '{
  "model": "qwen3.5:9b",
  "prompt": "Say hello in one sentence"
}'
