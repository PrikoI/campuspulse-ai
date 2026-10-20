# Проверка совместимой версии LMS

Дата: 20 октября 2026. Среда: Windows, Python 3.14.0, проектная `.venv`.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.check_lms
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
node --test tests/lms_frontend.test.mjs
Get-ChildItem web/lms/*.mjs | ForEach-Object { node --check $_.FullName }
```

LMS runner фиксирует pending/local/MCP, выключает облако и блокирует внешние
соединения в процессе тестов. Firestore проверяется с хранилищем в памяти
и подменённым SDK transport; Vertex — с подменёнными ADC и моделью.
HTTP использует loopback, MCP — настоящие локальные stdio-процессы.
Полный Python-набор при объединении также запускался с блокировкой внешней
сети через scripts.check_lms.deny_external_connections и sys.addaudithook.
Итоговые результаты: [MERGE_REPORT.md](MERGE_REPORT.md).

Проверяются серверные роли и сессии, изоляция студентов, CRUD, повторная
запись, ошибки, лимиты чтений и проекции, сериализация дат, личные задачи
и подтверждения, структурированные ответы десяти инструментов Firestore,
HTTP/SSE, статический allowlist и совместимость прежнего API.
Vertex-тесты проверяют ADC, явные project/location/API v1, сохранение
function ID и thought signature, исключение приватных thoughts, авторизацию
перед модельными запросами, лимиты 3/8 и отсутствие повтора при ошибках.
JS-тесты проверяют SSE с фрагментами UTF-8/CRLF, обрыв и ошибку потока,
cookie same-origin, 401 и безопасные ссылки.

--check проверяет зависимости и наличие интерфейса без открытия repository.
--check-vertex проверяет только строки конфигурации; ADC и облачная модель
этим не подтверждаются.

Реальная Firestore, Gemini/Vertex endpoints, браузерный UI smoke и Vertex AI
Agent Engine при объединении не проверялись. Безопасная проверка облачной
базы описана в [FIRESTORE.md](FIRESTORE.md) и
[FIRESTORE_JSON_REPORT.md](FIRESTORE_JSON_REPORT.md).
Данные пользователей, ключи, биллинг и облачные ресурсы не изменялись.

В origin/master отсутствовали заявленные vertex_gemini.py, web/lms/,
документация и тесты этих компонентов. В совместимой версии восстановлены
минимальные реализации по контрактам серверного кода. Исторические заявления
ветки команды о проверках Chrome не являются результатами этого объединения.
