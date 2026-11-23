# Provider конфигурация

| Provider | Base URL | Environment |
|---|---|---|
| OpenRouter | https://openrouter.ai/api/v1 | OPENROUTER_API_KEY / OPENROUTER_MODEL |
| Novita LLM | https://api.novita.ai/openai | NOVITA_API_KEY / NOVITA_MODEL |
| NVIDIA NIM | https://integrate.api.nvidia.com/v1 | NVIDIA_API_KEY / NVIDIA_MODEL |
| Hugging Face | https://router.huggingface.co/v1 | HF_TOKEN / HF_MODEL |
| Ollama | http://127.0.0.1:11434/v1 | LOCAL_LLM_ENABLED / LOCAL_LLM_MODEL |

За всеки cloud LLM въведи отделно input и output цена в USD за 1 милион токена. Не копирай тарифи между provider-и и сверявай ги спрямо точния model ID и account route.

OpenRouter е най-подходящ като унифициран LLM router. Novita има OpenAI-compatible LLM endpoint и отделни async image/video endpoints. NVIDIA NIM е hosted API catalog с отделни model IDs. Hugging Face предлага unified Inference Providers, но за задачи като text-to-image/video се използват task-specific clients/API routes, не обикновеният chat endpoint.

## Novita Wan 2.2 T2V

- Create: POST https://api.novita.ai/v3/async/wan-2.2-t2v
- Poll: GET https://api.novita.ai/v3/async/task-result?task_id=...
- Въведи актуалната цена на секунда в NOVITA_VIDEO_COST_PER_SECOND_USD преди генерация.

Официални документи:
- OpenRouter: https://openrouter.ai/docs
- Novita: https://novita.ai/docs/
- Novita Wan 2.2: https://novita.ai/docs/api-reference/model-apis-wan-2.2-t2v
- NVIDIA NIM: https://docs.api.nvidia.com/nim/reference/llm-apis
- Hugging Face: https://huggingface.co/docs/inference-providers
- RunPod Serverless: https://www.runpod.io/product/serverless
