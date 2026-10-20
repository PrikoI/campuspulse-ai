# Совместимая версия CampusPulse AI

Дата: 20 октября 2026. Объединяются `feature/firestore-integration` (`72319fc`)
и `origin/master` (`4bfbf92`), общий предок `5ab0500`.
Рабочая ветка — `feature/firestore-integration`. Удалённые ветки не изменяются.

## Что сохранено

Из feature: Firebase Admin singleton, Firestore Repository и personal storage,
разделение студентов, транзакции, проекции, фильтры и пагинация, JSON-совместимые
результаты MCP, штатный structuredContent, подтверждение личных изменений,
индексы, документация и безопасная проверка тестового namespace.

Из команды: LMS API 0.5.0, same-origin HTML и allowlist ассетов, описание
Vertex в status/OpenAPI, отдельная статическая проверка конфигурации,
Vertex AI/ADC для LMS вместо Developer API. Прежнее самостоятельное приложение
не переписано. Настроенный выбор Firestore сохраняется launcher-ом.

Конфликты README, lms_agent, LMS_API, LMS_VERIFICATION и start-lms разрешены
с сохранением обеих функциональных частей. Синхронные операции базы и модели
в асинхронном агенте выполняются через asyncio.to_thread.

## Найденные проблемы и исправления

Коммит `origin/master` импортировал `campuspulse.vertex_gemini` и объявлял
раздачу `web/lms/`, но самих файлов в коммите и локальных исходниках не было.
Также отсутствовали документация, Vertex/JS-тесты и UI smoke-скрипт,
упоминавшиеся в HANDOFF. Без этих файлов объединённый сервер не запускался бы.

Восстановлены минимальный Vertex-провайдер и интерфейс по серверным контрактам,
добавлены собственные тесты. Это восстановление совместимости; точное
оформление отсутствующего оригинала команды не воспроизведено. Исторические
заявления о Chrome в HANDOFF отделены от проверок текущей версии.

`--check` ранее открывал repository, что могло инициировать Firestore/ADC
вопреки заявленной проверке без сети. Теперь проверяются зависимости и файлы,
repository не открывается. `--check-vertex` не обнаруживает ADC.
Восстановленный UI также отбрасывает запоздалые результаты агента и личных
предложений после выхода/смены сессии, чтобы они не возвращались на экран.

## Путь данных и контракты

Firestore → существующий Repository → разрешённая JSON-совместимая структура
→ MCP structuredContent → function response → Gemini в Vertex AI.
JSON-файл на диске не создаётся. Старые формы ответов сохранены: courses,
assignments, items и другие именованные поля; единая дополнительная оболочка
success/data не вводится. Даты — ISO 8601, ошибки содержат безопасные
error/status/error_code. Личные действия сначала возвращают change/proposal
для пользователя; подписанное подтверждение исключено из модельного контекста.

Доступны восемь прежних MCP-инструментов и два personal-инструмента Firestore.
Модель не получает произвольный доступ к базе. Личный кэш не добавлен:
проекции и ограниченные запросы уже реализованы, доказанной пользы от
дополнительного кэша нет; ответы читаются из repository.

## Изменённые файлы относительно feature до merge

- `.env.example`, `README.md`, `HANDOFF.md`, `start-lms.cmd`.
- `campuspulse/lms_agent.py`, `lms_server.py`, `lms_openapi.py`.
- Новый `campuspulse/vertex_gemini.py`.
- `docs/LMS_API.md`, `LMS_VERIFICATION.md`; новые `FRONTEND.md`, `VERTEX_AI.md`, `MERGE_REPORT.md`.
- `tests/test_lms.py`, `test_lms_firestore_json.py`; новые `test_lms_vertex.py`, `lms_frontend.test.mjs`.
- Новый `web/lms/`: index.html, style.css, app.mjs, api.mjs, ui.mjs, forms.mjs, agent.mjs.

## Фактически выполненные проверки

- Первый LMS-прогон: **88 тестов — OK** (до добавления Vertex-тестов).
- Полный `unittest discover('tests')`: **125 тестов — OK**, 38.099 секунды.
  Внешняя сеть заблокирована audit hook; все облачные SDK-вызовы подменены.
  Покрыты также старое приложение, HTTP и настоящий локальный stdio MCP.
- `node --test tests/lms_frontend.test.mjs`: **5 тестов — OK**, включая
  отсутствие запоздалых данных прежней сессии после выхода.
- `node --check` всех пяти активных ES modules: **OK**.
- `lms_server --check` с выбором firestore: **OK**, repository/ADC не открывались.
- `lms_server --check-vertex` с тестовыми project/model: **OK**, configured=true,
  calls_enabled=false, adc_verified=false, live_verified=false.
- `git diff --check`: без ошибок пробелов. Ключ firebase-key.json игнорируется
  Git и не отслеживается; его содержимое не читалось.

## Что ещё требуется

Реальная Firestore и реальный Vertex не проверялись при merge. Безопасный
облачный backend harness уже существует: scripts/check_firestore_backend.py
с явным --live и отдельным system_tests/backend-* namespace; инструкции
в FIRESTORE_JSON_REPORT.md. Пользовательские документы не изменялись.

Нужна браузерная проверка восстановленного интерфейса, в том числе с реальными
данными. Интерфейс минимальный: расписание — таблица, admin-формы — JSON.
Исходные файлы оформления команды можно подключить позднее, если они найдутся.

Перед Vertex AI Agent Engine остаются проверка ADC/IAM и выбранной модели,
производственная identity вместо временной локальной авторизации,
управление секретом сессий, проверка транспорта MCP в целевой среде и
проверка облачных квот/расходов. Биллинг, IAM, Security Rules, ключи и облачный
деплой в рамках объединения не изменялись. Существующий stash сохранён.
