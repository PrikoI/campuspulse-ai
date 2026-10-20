# CampusPulse LMS API v1

Версия локальной реализации: 0.5.0. Базовый URL `http://127.0.0.1:8766/api/v1`.
Машиночитаемая схема: `GET /api/v1/openapi.json` (OpenAPI 3.1).
Примеры отказов без базы относятся к repository=pending. Доступен постоянный
repository=firestore; его конфигурация, схема, личные задачи и endpoints
`/personal`, `/actions/prepare`, `/actions/confirm` описаны в [FIRESTORE.md](FIRESTORE.md).
Локальный интерфейс подключён
на том же origin: `GET /`, `/lms`, `/lms/`; статические модули — `/lms-assets/` по
фиксированному списку файлов. Произвольные файлы проекта и прежнее демо не раздаются.
`status.frontend_connected` отражает наличие активных файлов интерфейса, а не
готовность базы или внешних сервисов. Промышленное размещение и корпоративная
авторизация пока не подключены. См. [интерфейс](FRONTEND.md).

## Авторизация и общий формат

`GET /status` и `/openapi.json` публичны. `POST /auth/login` принимает только
`username` и `password`. Временные пары: `admin/admin`, `student1/student1`,
`student2/student2`. Это сессии для разработки, а не записи студентов в базе.

```powershell
$base = 'http://127.0.0.1:8766/api/v1'
Invoke-RestMethod "$base/auth/login" -Method Post -ContentType 'application/json' `
  -Body '{"username":"student1","password":"student1"}' -SessionVariable lmsSession
Invoke-RestMethod "$base/me" -WebSession $lmsSession
Invoke-RestMethod "$base/agent/query" -Method Post -ContentType 'application/json' `
  -Body '{"message":"Покажи мои предметы","engine":"local"}' -WebSession $lmsSession
Invoke-RestMethod "$base/auth/logout" -Method Post -ContentType 'application/json' `
  -Body '{}' -WebSession $lmsSession
```

Ответ входа и `/me`: `{"user":{"id":string,"role":"student"|"admin","name":string}}`.
Cookie `campuspulse_lms`: HttpOnly, SameSite=Strict, Path=/, срок 8 часов.
После выхода токен отзывается в родительском API-процессе; после обычного
перезапуска с новым ключом подписи нужно войти повторно. Если задан постоянный
`CAMPUSPULSE_LMS_SESSION_SECRET`, подпись переживает перезапуск, а список отозванных
токенов в памяти — нет. В production этот механизм необходимо заменить.
На loopback HTTP cookie не имеет Secure; это локальная среда разработки.

`POST` и `PATCH` требуют `Content-Type: application/json` и единственный
`Content-Length` от 1 до 8 000 000 байт. Transfer-Encoding не поддерживается.
Корневое тело — объект. Дубли ключей, NaN/Infinity, неизвестные поля и
повторяющиеся query-параметры отклоняются. Идентификаторы: непустая строка до
120 символов без `/`, `\`, `?`, `#` и управляющих символов.

Ошибка API: `{"error":string,"data_access":[]}`; Host/Origin и перегрузка могут
возвращать только `error`. Коды: 400 формат, 401 нет сессии, 403 роль/доступ,
404 неизвестный endpoint, 405 метод, 409 конфликт данных (будущий адаптер), 413 размер, 415 Content-Type, 429 лимит,
500 внутренняя ошибка, 503 нет зависимости/базы/провайдера, 504 тайм-аут.
Одновременно выполняются максимум два запроса; тайм-аут агента — 100 секунд.
Пять неудачных входов за минуту для пары IP/логин приводят к 429.

## Маршруты

В таблице пути указаны относительно `/api/v1`.

| Метод и путь | Доступ | Текущий результат |
|---|---|---|
| `GET /status` | публичный | источник, наличие MCP, транспорт, ограничения интеграций |
| `GET /openapi.json` | публичный | OpenAPI 3.1 |
| `POST /auth/login` | публичный | user + cookie |
| `GET /me` | любой вошедший | user |
| `POST /auth/logout`, `{}` | любой вошедший | `logged_out=true`, удаление cookie |
| `GET /{collection}` | студент | 503, журнал попытки чтения |
| `GET /grade-summary?course_id=…&target=…` | студент | 503; после интеграции — расчёт из LMS |
| `GET /attendance-summary?course_id=…` | студент | 503; после интеграции — сводка посещений |
| `GET /admin/users` | преподаватель | 503, попытка чтения users |
| `POST /admin/students` | преподаватель | 503 после проверки username/password/name |
| `GET /admin/{collection}` | преподаватель | 503, попытка чтения |
| `POST /admin/{collection}` | преподаватель | 503 после проверки create-полей |
| `PATCH /admin/{collection}/{id}` | преподаватель | 503 после проверки непустого частичного обновления |
| `POST /grading/calculate` | любой вошедший | независимый расчёт по числам из запроса |
| `POST /agent/query` | студент | JSON с ответом и журналом реальных MCP-вызовов |
| `POST /agent/stream` | студент | те же действия через POST SSE |
| `GET /data/resources` | любой вошедший | каталог доступных ресурсов всей базы; пока 503 |
| `POST /data/query` | любой вошедший | универсальное чтение по имени ресурса; пока 503 |

Коллекции: `courses`, `enrollments`, `assignments`, `grade_items`, `grades`,
`lessons`, `attendance`, `materials`. Списки принимают необязательный `course_id`.
В `/grade-summary` и `/attendance-summary` он обязателен. Только `/grade-summary`
принимает query `target` (0–100, по умолчанию 50). Остальные query-параметры запрещены.
`student_id` студент не передаёт: он берётся из проверенной сессии.
Преподаватель использует `/admin/*`, а не студенческие списки и агента.
Схемы записей и их обязательные поля описаны в [контракте базы](LMS_DATABASE_CONTRACT.md).

После подключения адаптера формы ответов списков: `{items,data_access,source}`,
создания/обновления: `{item,source}`, создания студента: `{user}`. Чтение users:
`{items}`. Успешное создание предполагает HTTP 201, обновление — 200.
Сейчас эти успешные операции с данными не выполняются.

## Честный журнал отсутствующей базы

Пример формы события (это метаданные попытки, без учебных записей):

```json
{
  "type": "database_request",
  "operation": "read",
  "collection": "courses",
  "filters": {"course_id": null, "student_id": "student1"},
  "source": "not-connected",
  "status": "not_connected",
  "executed": false,
  "rows": null,
  "at": "ISO-8601 timestamp with timezone"
}
```

Запись добавляется в `data_access` ошибки. Для `POST` операция — `create`, для
`PATCH` — `update` с `record_id`. Пароли, текст материалов и токен сессии в событие
не попадают. `rows=null` означает, что чтение не выполнялось; это не ноль записей.
При неверном запросе или отказе в правах не показывается несуществующее чтение.

Локальный агент может вернуть HTTP 200 при ошибке инструмента: смотрите
`results[tool].status=503`, `tool_result.status="error"` и `database_request`.
Успешная доставка журнала не означает успешное получение учебных данных.
Для составного инструмента журнал содержит только операции, до которых реально
дошло выполнение: первая ошибка прекращает дальнейшие чтения.

## Агент, MCP и контекст страницы

Поля запроса: обязательный `message` (1–5000 символов); необязательные `course_id`,
`page`, `engine`, `target`, `hours_per_day`, `extra_busy`, `data_query`.
`page`: `overview`, `courses`, `assignments`, `grades`, `attendance`, `materials`,
`schedule`, `plan`. Если в сообщении нет явного намерения, локальный маршрутизатор
использует открытую страницу. Явный запрос имеет приоритет.
`engine=local` по умолчанию; это не LLM. `engine=gemini` теперь выбирает
**Vertex AI через Google Gen AI SDK и ADC**, см. [VERTEX_AI.md](VERTEX_AI.md).
При отключённой базе
возвращает 503 до создания клиента модели и изменения счётчиков квоты.
Старое подключение Developer API через `/api/gemini/connect` здесь недоступно.

Настоящий путь вызова: API → отдельный stdio MCP-процесс → initialize → внутренний
load_session → tools/list → tools/call. Нет автоматического перехода на direct.
Внутренний `load_session` не входит в доступные модели инструменты. Перед каждым
вызовом родительский процесс повторно проверяет сессию, включая выход пользователя.
MCP-инструменты доступны только для чтения:

| Инструмент | Аргументы |
|---|---|
| `list_data_resources` | нет; каталог ресурсов всей доступной базы |
| `query_data` | resource из каталога; необязательные filters, fields, limit, cursor |
| `get_courses` | нет |
| `get_assignments` | необязательный course_id |
| `get_grades` | course_id, необязательный target 0–100 |
| `get_attendance` | course_id |
| `read_materials` | course_id, query 1–500 символов |
| `plan_study` | необязательные course_id, hours_per_day 1–8, extra_busy |

`extra_busy`: до 100 объектов `{start,end}` с ISO-датами и часовым поясом;
конец позже начала. Входы проверяются до чтения базы. При отсутствии course_id
агент сначала вызывает `get_courses`. При отсутствии базы на этом возможна
остановка: это корректный отказ, а не пустой список предметов.

JSON-ответ агента: `answer`, `engine`, `reasoning_loop`, `transport`, `model_called`, `provider`, `model`,
`trace`, `results`, `source`, `team_database_connected`, `budget`, `notice`.
В local `model_called=false`, `reasoning_loop=false`, `transport=mcp`.
В Gemini provider=vertex-ai; проект, регион и модель задаются на сервере.
Состояние статической конфигурации возвращается в `/status.vertex`; ADC и живой
ответ этим не проверяются. `--check-vertex` проверяет только строки настроек.
`budget` описывает ограничения будущей ветки модели, а не потраченные деньги.
Пределы: 3 модельных шага, 8 инструментальных вызовов, 1200 выходных токенов,
10 запросов на пользователя и 20 всего в день. Счётчики в памяти не являются
денежным лимитом и сбрасываются при перезапуске.

## SSE для фронтенда команды

Stream — POST. Используйте `fetch`, а не браузерный EventSource.
События идут как `data: <JSON>\n\n`; граница сетевого чанка не является границей события.
Поток заканчивается событием `complete` с `response` или `error` со статусом и
сообщением. Если соединение оборвалось без финального события, операция не считается
доставленной. Автоматический повтор не предусмотрен.

Порядок при нормальном локальном вызове: `started`, `mcp_connect`, `mcp_ready`,
`tool_start`, `database_request`, `tool_result`, `complete`. Может быть несколько
инструментов. `mcp_ready` означает завершённое рукопожатие и обнаружение восьми
инструментов, а не подключение базы. Содержимое `complete.response.trace` повторяет
журнал текущего запроса; фронтенду не нужно добавлять эти события второй раз.
При реальных разрешённых запросах Vertex в поток добавляются model_start/model_result.
Токены ADC и приватные размышления модели в журнал не включаются.
Если ошибка возникла после заголовков SSE, HTTP остаётся 200: читайте событие
`error.status`. Неверный Host/Origin или отсутствие сессии отклоняются до потока.

```javascript
const response = await fetch('/api/v1/agent/stream', {
  method: 'POST', credentials: 'same-origin',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({message: 'Покажи мои предметы', engine: 'local'})
});
if (!response.ok) throw new Error((await response.json()).error);
const reader = response.body.getReader();
const decoder = new TextDecoder();
let buffer = '', terminal = false;
for (;;) {
  const {value, done} = await reader.read();
  buffer += decoder.decode(value, {stream: !done});
  let end;
  while ((end = buffer.indexOf('\n\n')) >= 0) {
    const frame = buffer.slice(0, end); buffer = buffer.slice(end + 2);
    const data = frame.split('\n').filter(line => line.startsWith('data:'))
      .map(line => line.slice(5).trimStart()).join('\n');
    if (!data) continue;
    const event = JSON.parse(data);
    console.log(event); // Replace with the team's journal renderer.
    terminal ||= event.type === 'complete' || event.type === 'error';
  }
  if (done) break;
}
if (!terminal) throw new Error('Поток завершился без финального события');
```

Разрешены только локальные Host/Origin текущего сервера. CORS для другого порта
не настроен. Команде нужен same-origin proxy, сохраняющий cookie, Host/Origin и
стриминг без буферизации. Используйте один hostname последовательно: `localhost`
и `127.0.0.1` имеют разные cookie. Production HTTPS, доверенные прокси и OAuth
подключаются отдельно; не отключайте проверки Origin для интеграции.

## Калькулятор оценок

`POST /grading/calculate`: `{items:[{component,score,max_score?,weight?}],policy?,target?}`.
`items` — до 100 числовых входов, не импорт записей LMS. Разрешённые component:
regmid, midterm, regend, endterm, attestation1, attestation2, final.
Ответ: `{calculation,simulation:true,source:"explicit-request-input",database_accessed:false,notice}`.
Ничего не записывается в ведомость.

Сохранены правила из ранее проверенного текста справочника AITU 2025, стр. 14:
Register=(A1+A2)/2; Total=0.3×A1+0.3×A2+0.4×Final; каждая аттестация минимум 25,
Register/Final/Total минимум 50. Источник указан в `calculation.policy.source_url`.
Прямое повторное получение PDF 20.10.2026 вернуло 502; актуальность силлабуса
конкретного курса 2026 года этим не подтверждена.

Веса coursework/exam по умолчанию null: составные аттестации без силлабуса не
рассчитываются. Пустые баллы неизвестны. Буквенная оценка арифметического total
не отменяет `academic_admission` и `passed`. Правила стипендии не заданы.
Посещаемость не подменяется универсальным порогом допуска.
