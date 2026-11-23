# MeloForge Studio

MeloForge Studio е основа за създаване на песни и музикални видеоклипове с адаптивна Local-First / Smart-Hybrid / Cloud-Quality архитектура.

> Тази версия е начална инфраструктура за AI Resource Manager, не завършен генератор на музика и видео. Реална генерация изисква инсталирани локални модели или API ключове на съответните доставчици.

## Стек

- Frontend: React + TypeScript + Vite
- Backend: FastAPI + Pydantic + HTTPX
- Local LLM: Ollama / OpenAI-compatible local endpoint
- Cloud LLM: OpenRouter, Novita, NVIDIA NIM, Hugging Face Inference Providers
- Video: Novita Wan 2.2 async API (първи адаптер)
- По-късно: ACE-Step, VoxCPM, InvokeAI, RunPod workers и FFmpeg Composer

## Стартиране

Изисквания: Python 3.11+, Node.js 20+, FFmpeg (за бъдещия монтаж).

1. Копирай `.env.example` като `.env` и добави само своите ключове.
2. Backend:

```bash
cd backend
python -m venv .venv
# Windows PowerShell: .venv\\Scripts\\Activate.ps1
# Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

3. Frontend в нов терминал:

```bash
cd frontend
npm install
npm run dev
```

UI: http://localhost:5173
API: http://localhost:8000/docs

## Локален модел

Инсталирай Ollama, след това:

```bash
ollama pull qwen2.5:3b
```

В `.env` задай `LOCAL_LLM_ENABLED=true`, `LOCAL_LLM_MODEL=qwen2.5:3b` и `LOCAL_LLM_BASE_URL=http://127.0.0.1:11434/v1`. На RTX 2050 4 GB / 16 GB RAM това е ориентировъчен малък модел; възможно е част от изпълнението да се прехвърли към системната RAM/CPU и да е бавно. Реалният капацитет зависи от свободната памет и настройките на Ollama.

## Provider роли

| Доставчик | Роля | Base URL |
|---|---|---|
| OpenRouter | Унифицирано LLM API, избор и fallback между модели | `https://openrouter.ai/api/v1` |
| Novita | OpenAI-compatible LLM API и отделни async генеративни API | `https://api.novita.ai/openai` |
| NVIDIA NIM | Hosted LLM API Catalog | `https://integrate.api.nvidia.com/v1` |
| Hugging Face | Inference Providers; chat и task-specific модели | `https://router.huggingface.co/v1` |
| Ollama | Локален LLM | `http://127.0.0.1:11434/v1` |

Моделните ID-та са специфични за доставчика и трябва да се вземат от неговия текущ каталог.

## Режими

- `local_first`: локално първо; облак само ако е разрешен fallback.
- `hybrid`: локален модел за по-леки текстови задачи, а за останалите — най-евтиният настроен cloud модел с известни тарифи.
- `cloud_quality`: предпочитан cloud доставчик, но без заобикаляне на ценовия лимит.

## Ценова защита

Цените на cloud LLM се въвеждат в `.env` като USD за 1M input/output tokens. Системата добавя 25% резерв към предварителната оценка и блокира платената заявка, ако липсва тарифа или бюджетът се надвишава. Броят входни токени е приблизителен (около 1 токен на 4 знака), не е точен tokenizer. За video се задава цена на секунда според текущата тарифа.

## Състояние на разработката

- Включени са хардуерен детектор, provider registry, LLM router, budget guard и Novita Wan 2.2 adapter.
- Цените все още се въвеждат ръчно; динамично обновяване на каталози/тарифи е следващ етап.
- Няма още database/job queue, user auth, storyboard, ACE-Step/VoxCPM/InvokeAI адаптери и FFmpeg монтаж.
- Не са включени API ключове, не се изпращат платени заявки при първо стартиране.

## Безопасност

API ключовете остават само в backend `.env`. Не въвеждай ключове в React, не ги commit-вай и не публикувай `.env`. Преди public deployment са нужни login, rate limiting, per-user secrets, audit logs и cloud spend caps.
