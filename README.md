# Keitaro Wrapper

Небольшая обёртка над Admin API трекера Keitaro (тестовое задание «Это Легко»).

* **New campaign** — создаёт кампанию `test_tadjibayev_*` с доменом, группой и источником и двумя потоками:
  1. `country = <GEO>` → редирект на `https://google.com`;
  2. все остальные → выбранный оффер (100 %).
* **Edit campaign** — забирает потоки из Keitaro и даёт править состав офферов и веса как черновик:
  Add / Remove / Bring back / Pin веса, **Push** отправляет поток в Keitaro, **Cancel** откатывает черновик.

> Скриншоты: `docs/screenshots/` (добавить после проверки на стенде).

## Стек

FastAPI · SQLAlchemy 2 (async) · Alembic · Pydantic v2 · httpx · PostgreSQL · Jinja2 + vanilla JS (без сборки) · pytest + respx.

## Настройка `.env`

```bash
cp .env.example .env
```

| Переменная | Что это |
|---|---|
| `KEITARO_URL` | Адрес стенда без `/admin_api/v1`, например `https://keitaro-for-tests.etolegko.com` |
| `KEITARO_API_KEY` | Ключ из админки (кнопка «API ключ»). **Не коммитить.** |
| `DEFAULT_DOMAIN_ID`, `DEFAULT_GROUP_ID`, `DEFAULT_SOURCE_ID` | Что выбрано в форме по умолчанию (на стенде: 1813, 10332, 836) |
| `CAMPAIGN_PREFIX` | Префикс имён кампаний, по умолчанию `test_tadjibayev_` |
| `DATABASE_URL` | `postgresql+asyncpg://…` или `sqlite+aiosqlite:///./keitaro_wrapper.db` |

## Запуск в Docker

```bash
docker compose up --build
```

Приложение: http://localhost:8000 (порт меняется через `APP_PORT=8080 docker compose up`).
Миграции применяются автоматически при старте контейнера (`alembic upgrade head`).

## Запуск локально

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
export DATABASE_URL=sqlite+aiosqlite:///./keitaro_wrapper.db   # или PostgreSQL
alembic upgrade head
uvicorn app.main:app --reload
```

Без доступа к стенду можно поднять офлайн‑заглушку Keitaro:

```bash
uvicorn scripts.mock_keitaro:app --port 9000
KEITARO_URL=http://127.0.0.1:9000 KEITARO_API_KEY=dev uvicorn app.main:app --reload
```

`python -m scripts.explore_api` сохраняет реальные ответы стенда в `docs/api_samples/`.

## Миграции

```bash
alembic revision --autogenerate -m "describe change"   # создать
alembic upgrade head                                   # применить
alembic downgrade -1                                   # откатить одну
```

## Тесты

```bash
pytest -q
```

Keitaro в тестах замокан через `respx` (`tests/fake_keitaro.py` — маленький эмулятор в памяти).
Покрыто: алгоритм весов, синхронизация, сценарии редактора, payload'ы создания кампании, HTTP‑клиент.

## Ключевые решения

### Алгоритм весов (`app/services/weights.py`, чистая функция)
* Удалённые офферы всегда 0 % и не могут быть закреплены (при удалении pin снимается).
* Закреплённые (pinned) веса не меняются; `100 − Σpinned` делится поровну между незакреплёнными активными.
* Остаток от целочисленного деления: +1 первым незакреплённым по позиции — детерминированно, сумма всегда ровно 100.
* `Σpinned > 100` → ошибка 422, изменение не сохраняется.
* Все активные закреплены и сумма ≠ 100, или 0 активных офферов → Push заблокирован с понятным сообщением.
* Пересчёт происходит только при Add / Remove / Bring back / Pin. При Fetch веса из Keitaro принимаются как есть.

### Черновик, dirty и Cancel
У каждой связи поток↔оффер хранится рабочее состояние (`share`, `status`) и опубликованное (`published_share`, `published_status`) + флаг `added_in_draft`.
* **dirty** = хотя бы одна связь отличается от опубликованной (pin сам по себе — локальная настройка и не делает поток dirty).
* **Cancel** удаляет связи, добавленные в черновике (сам оффер остаётся в таблице `offers`), и возвращает опубликованные значения.
* **Push** отправляет `PUT /streams/{id}` только с активными офферами. Перед этим поток перечитывается из Keitaro: если его изменили снаружи после последнего Fetch — ответ 409 и кнопка «Push anyway». После PUT ответ Keitaro сверяется с отправленным; при ошибке поток остаётся жёлтым, БД не меняется.
* Удалённый оффер после Push пропадает из Keitaro, но остаётся у нас серым со статусом `removed` и кнопкой Bring back.

### Синхронизация (Fetch streams)
* Потоки без офферов (`schema != "landings"`) хранятся только как имя / позиция; фильтры и редиректы не читаются.
* Для чистого потока Keitaro — источник правды: известные офферы, которых больше нет в Keitaro, становятся `removed` (не удаляются); новые — добавляются активными.
* **Поток с неопубликованными изменениями не перезаписывается** — UI предупреждает: сначала Push или Cancel, потом Fetch.
* Оффер с `state: disabled` в Keitaro считается у нас `removed`.
* Поток, удалённый в Keitaro, удаляется локально.

### Создание кампании
Префикс `test_tadjibayev_` добавляется на бэкенде, если его нет. GEO проверяется по списку ISO‑3166‑1 alpha‑2. Поток 1 — `type: regular`, `schema: redirect`, `action_type: http`; поток 2 — `type: default` (замыкающий), `schema: landings`. Если создание потока не удалось, кампания удаляется в Keitaro, чтобы не оставлять полусобранную.

## Проверка на стенде
Кампания `test_tadjibayev_campaign1` (#49) создана на стенде; на ней проверены Add → Push, Remove → Push (оффер ушёл из Keitaro, у нас остался `removed`), Pin 25 % + Bring back → 25/38/37 → Push, Cancel, удаление оффера прямо в Keitaro → Fetch → `removed`. После каждого Push веса в Keitaro совпадали с нашими. Реальные ответы API лежат в `docs/api_samples/`; `PUT /streams/{id}` с одним полем `offers` меняет только состав офферов, `schema`/`type`/`filters` сохраняются.

## Ограничения
* Нет авторизации пользователей — обёртка рассчитана на локальный/внутренний запуск.
* Каталог офферов кешируется на 60 с (`OFFERS_CACHE_TTL`).
* Порядок потоков и их фильтры не редактируются (не требуется заданием).
