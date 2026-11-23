# MeloForge Studio

MeloForge Studio е основа за създаване на песни и музикални видеоклипове с адаптивна Local-First / Smart-Hybrid / Cloud-Quality архитектура.

> Това е desktop alpha. Основните потоци за цяла песен и AI video са свързани, но за реална генерация са нужни стартиран ACE-Step engine и активен provider акаунт с актуални тарифи.

## Стек

- Frontend: React + TypeScript + Vite
- Backend: FastAPI + Pydantic + HTTPX
- Local LLM: Ollama / OpenAI-compatible local endpoint
- Cloud LLM: OpenRouter, Novita, NVIDIA NIM, Hugging Face Inference Providers
- Music: ACE-Step 1.5 asynchronous API (локално или собствен частен endpoint)
- Video: Novita Wan 2.2 async API
- Локален FFmpeg Composer: цяла песен с повтаряща се AI сцена, 16:9/9:16 експорти и отделен файл с текста
- Следващи модули: VoxCPM и InvokeAI

## Стартиране

Изисквания: Python 3.11+, Node.js 20+. За локално генериране стартирай ACE-Step 1.5 API.

1. За локална разработка копирай `.env.example` като `.env`. Инсталираното Desktop приложение създава `config.env` и локални данни в `%LOCALAPPDATA%\MeloForge Studio`.
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

## Windows приложение и инсталатор

За portable Windows build (без инсталатор) изпълни от корена на проекта:

```powershell
.\scripts\build-windows.ps1 -SkipInstaller
```

Резултатът е в `dist\MeloForge Studio\MeloForge Studio.exe`. Скриптът първо изгражда React интерфейса, след това пакетира локалния FastAPI сървър и UI в едно Windows приложение. То слуша само на `127.0.0.1` и отваря приложението в стандартния браузър.

За `Setup.exe` инсталирай Inno Setup 6 и изпълни:

```powershell
.\scripts\build-windows.ps1
```

Инсталаторът ще бъде в `release\MeloForge-Studio-Setup.exe`. Не включва модели, API ключове или потребителски файлове.

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

## Music generation

MeloForge използва официалния асинхронен ACE-Step 1.5 API: `GET /v1/models`, `POST /release_task`, `POST /query_result`. Стартирай услугата и зареди модел; после отвори Music Studio → „Настрой музикалния engine“. За private/hosted endpoint въведи адреса и актуална цена за секунда. API ключовете се пазят локално, защитени от Windows DPAPI за текущия Windows профил. Локалният `127.0.0.1` endpoint се оценява с $0 API разход. Генерирането не започва преди изрично потвърждение на офертата в UI.

Ако полето за текст е празно, ACE-Step може да генерира текст/структура заедно с песента. Избраният език е български или английски; реалната езикова поддръжка зависи от заредения модел. След готовност на песента и Novita видеото, Video Studio сглобява пълната дължина с повтаряне на кратката сцена, записва 16:9 и 9:16 версии и предлага текста като TXT. Монтажът се изпълнява локално с FFmpeg и не изпраща нова платена заявка.

## Състояние на разработката

- Включени са хардуерен детектор, provider registry, LLM router, budget guard, ACE-Step song flow, provider setup UI и Novita Wan 2.2 adapter.
- Цените все още се въвеждат ръчно; динамично обновяване на каталози/тарифи е следващ етап.
- Работите и настройките се пазят локално като JSON; следващи етапи са база данни/job queue, storyboard и синхронизирани субтитри.
- Не са включени API ключове, не се изпращат платени заявки при първо стартиране.

## Безопасност

В Desktop режим API ключовете се шифроват чрез Windows DPAPI и се пазят в профила на потребителя; provider settings не връщат ключове към UI. В разработка може да се използва `.env`, който не трябва да се commit-ва. Преди public deployment са нужни login, rate limiting, per-user secrets, audit logs и cloud spend caps.
