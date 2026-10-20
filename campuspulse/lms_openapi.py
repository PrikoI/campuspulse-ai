"""OpenAPI contract for the local LMS server; contains no academic examples."""
from copy import deepcopy

from .grading import COMPONENTS, DEFAULT_POLICY
from .lms_store import FIELDS, KINDS
from .lms_validation import PAGES, REQUIRED
from .lms_data import QUERY_PROPERTIES


def obj(properties=None, required=()):
    return {"type": "object", "properties": properties or {}, "required": list(required), "additionalProperties": False}


def ref(name):
    return {"$ref": f"#/components/schemas/{name}"}


def openapi_document():
    string = {"type": "string"}
    identifier = {"type": "string", "minLength": 1, "maxLength": 120, "pattern": r"^[^/\\?#\x00-\x1f]+$"}
    score = {"type": ["number", "null"], "minimum": 0, "maximum": 100000}
    stamp = {"type": "string", "format": "date-time"}
    fields = {
        "course_id": identifier, "student_id": identifier, "item_id": identifier, "lesson_id": identifier,
        "code": {**string, "minLength": 1, "maxLength": 80},
        "name": {**string, "minLength": 1, "maxLength": 200},
        "title": {**string, "minLength": 1, "maxLength": 200},
        "description": {**string, "maxLength": 10000}, "text": {**string, "minLength": 1, "maxLength": 50000},
        "comment": {**string, "maxLength": 2000}, "kind": {**string, "minLength": 1, "maxLength": 200},
        "archived": {"type": "boolean"}, "component": {"type": "string", "enum": sorted(COMPONENTS)},
        "instructor_ids": {"type": "array", "maxItems": 20, "uniqueItems": True, "items": identifier},
        "status": {"type": "string", "enum": ["present", "absent", "late", "excused"]},
        "due": {"type": ["string", "null"], "format": "date-time"}, "starts_at": stamp, "ends_at": stamp,
        "week": {"type": ["integer", "null"], "minimum": 1, "maximum": 100},
        "minutes": {"type": ["integer", "null"], "minimum": 10, "maximum": 2400}, "score": score,
        "max_score": {"type": "number", "minimum": 0.001, "maximum": 100000},
        "weight": {"type": "number", "minimum": 0.001, "maximum": 1000},
        "source_url": {"type": "string", "maxLength": 2000, "description": "Empty or an http/https URL; never fetched automatically."},
        "policy": ref("Policy"),
    }
    policy = {}
    for key, default in DEFAULT_POLICY.items():
        if key in {"name", "source_url"}:
            policy[key] = {"type": "string", "maxLength": 200 if key == "name" else 2000}
        elif key == "version":
            policy[key] = {"type": "integer", "minimum": 1}
        else:
            policy[key] = {"type": ["number", "null"] if default is None else "number", "minimum": 0,
                           "maximum": 1 if key.endswith("weight") else 100}
    busy = {"type": "array", "maxItems": 100, "items": obj({"start": stamp, "end": stamp}, ["start", "end"])}
    schemas = {
        "Policy": {**obj(policy), "description": "Defaults: AITU reference guide 2025. Coursework/exam weights remain null until the course syllabus is supplied; see docs/LMS_DATABASE_CONTRACT.md."},
        "Login": obj({"username": string, "password": {"type": "string", "format": "password", "maxLength": 512}}, ["username", "password"]),
        "StudentCreate": obj({"username": identifier, "password": {"type": "string", "minLength": 1, "maxLength": 512, "format": "password"}, "name": fields["name"]}, ["username", "password", "name"]),
        "AgentRequest": obj({"message": {**string, "minLength": 1, "maxLength": 5000}, "course_id": {"type": ["string", "null"], "maxLength": 120},
                             "history": {"type": "array", "maxItems": 8, "description": "Up to four user/assistant pairs, 20000 text characters total; untrusted context, not proof of actions or academic facts.",
                                         "items": obj({"role": {"type": "string", "enum": ["user", "assistant"]}, "content": {**string, "minLength": 1, "maxLength": 8000}}, ["role", "content"])},
                             "data_query": ref("DataQuery"),
                             "page": {"type": "string", "enum": sorted(PAGES), "default": "overview"},
                             "engine": {"type": "string", "enum": ["local", "gemini", "llm"], "default": "local"},
                             "target": {"type": "number", "minimum": 0, "maximum": 100},
                             "hours_per_day": {"type": "number", "minimum": 1, "maximum": 8, "default": 3}, "extra_busy": busy}, ["message"]),
        "CalculationRequest": obj({"items": {"type": "array", "maxItems": 100, "items": obj({"component": fields["component"], "score": score, "max_score": fields["max_score"], "weight": fields["weight"]}, ["component"])}, "policy": ref("Policy"), "target": {"type": "number", "minimum": 0, "maximum": 100}}, ["items"]),
        "DatabaseAccess": {"type": "object", "required": ["type", "operation", "collection", "filters", "source", "status", "executed", "rows", "at"],
                           "properties": {"type": {"const": "database_request"}, "operation": {"type": "string", "enum": ["read", "describe", "create", "update"]},
                                          "collection": string, "filters": {"type": "object"}, "source": string, "status": string,
                                          "executed": {"type": ["boolean", "null"]}, "rows": {"type": ["integer", "null"]}, "at": stamp}},
        "Error": {"type": "object", "required": ["error"], "properties": {"error": string, "data_access": {"type": "array", "items": ref("DatabaseAccess")}}},
        "Empty": obj(),
        "DataQuery": obj(deepcopy(QUERY_PROPERTIES), ["resource"]),
        "PersonalChange": obj({"target": {"type": "string", "enum": ["task", "preferences"]},
                               "operation": {"type": "string", "enum": ["save", "delete"], "default": "save"},
                               "record_id": {"type": ["string", "null"], "maxLength": 120},
                               "payload": {"type": "object", "description": "Task: title, course, due, minutes, done; preferences: hours_per_day. See docs/FIRESTORE.md."}}, ["target", "payload"]),
        "ActionConfirmation": obj({"proposal": {"type": "string", "maxLength": 10000}, "confirmed": {"const": True}}, ["proposal", "confirmed"]),
        "PlanConfirmation": obj({"proposal": {"type":"string","maxLength":200000},"confirmed":{"const":True}},['proposal','confirmed']),
        "ScheduleChanges": obj({'changes':{'type':'array','minItems':1,'maxItems':100,'items':obj({'id':identifier,'starts_at':stamp,'ends_at':stamp,'expected_start':stamp,'expected_end':stamp},['id','starts_at','ends_at','expected_start','expected_end'])}},['changes']),
    }
    schemas["AgentRequest"]["properties"]["personal_change"] = ref("PersonalChange")
    for kind in sorted(KINDS):
        properties = {key: deepcopy(fields[key]) for key in sorted(FIELDS[kind])}
        if kind=='assignments':
            for key in ['item_id','lesson_id']:
                properties[key]['type']=['string','null']
        schemas[kind + "Create"] = obj(properties, sorted(REQUIRED[kind]))
        schemas[kind + "Update"] = {**obj(properties), "minProperties": 1}
    paths = {}
    def endpoint(path, method, summary, body=None, query=(), public=False, status="200", stream=False, database=False):
        response = {"description": "SSE action events ending with complete or error; an error after headers keeps HTTP 200." if stream else "Operation response; see docs/LMS_API.md for response fields.",
                    "content": {"text/event-stream" if stream else "application/json": {"schema": {"type": "string" if stream else "object"}}}}
        errors = {code: {"description": description, "content": {"application/json": {"schema": ref("Error")}}}
                  for code, description in {"400": "Invalid input", "401": "Login required", "403": "Access denied", "404": "Unknown endpoint or record", "405": "Unsupported method", "409": "Data conflict", "413": "Body too large", "415": "JSON required", "429": "Request limit", "500": "Internal failure", "503": "Database, MCP or provider unavailable", "504": "Timeout"}.items()}
        operation = {"operationId": method + path.replace("/api/v1/", "_").replace("/", "_").replace("{", "").replace("}", "").replace(".", "_"),
                     "summary": summary, "security": [] if public else [{"localSession": []}], "responses": {status: response, **errors}}
        parameters = []
        for name in ("collection", "id"):
            if "{" + name + "}" in path:
                parameters.append({"name": name, "in": "path", "required": True, "schema": {"type": "string", "enum": sorted(KINDS)} if name == "collection" else identifier})
        for name in query:
            parameters.append({"name": name, "in": "query", "required": name == "course_id" and path.endswith("summary"), "schema": identifier if name == "course_id" else {"type": "number", "minimum": 0, "maximum": 100, "default": 50}})
        if parameters:
            operation["parameters"] = parameters
        if body:
            operation["requestBody"] = {"required": True, "content": {"application/json": {"schema": ref(body)}}}
        if database:
            operation["description"] = "Uses the configured repository with server-side permissions. Pending returns HTTP 503; firestore stores persistent data."
        paths.setdefault(path, {})[method] = operation
    endpoint("/api/v1/status", "get", "Local readiness and integration status", public=True)
    endpoint("/api/v1/openapi.json", "get", "This API contract", public=True)
    endpoint("/api/v1/auth/login", "post", "Temporary local login; sets HttpOnly cookie", "Login", public=True)
    endpoint("/api/v1/auth/logout", "post", "Revoke local session", "Empty")
    endpoint("/api/v1/me", "get", "Current authenticated identity")
    endpoint("/api/v1/data/resources", "get", "Discover all permitted database resources and their fields", database=True)
    endpoint("/api/v1/data/query", "post", "Read any catalog resource through the team's gateway", "DataQuery", database=True)
    endpoint("/api/v1/personal", "get", "Student: saved personal tasks and allowed preferences", database=True)
    endpoint("/api/v1/actions/prepare", "post", "Student: prepare a signed change for review; no writes", "PersonalChange", database=True)
    endpoint("/api/v1/actions/confirm", "post", "Student: explicitly confirm the reviewed change; unavailable to LLM tools", "ActionConfirmation", database=True)
    endpoint('/api/v1/actions/confirm-plan','post','Confirm a reviewed study plan; idempotent personal task creation','PlanConfirmation',database=True)
    endpoint('/api/v1/admin/schedule','post','Atomically move lessons; reject overlaps and stale edits; update linked deadlines','ScheduleChanges',database=True)
    for kind in sorted(KINDS):
        endpoint(f"/api/v1/{kind}", "get", "Student: enrollment-scoped " + kind, query=["course_id"], database=True)
        endpoint(f"/api/v1/admin/{kind}", "get", "Teacher: read " + kind, query=["course_id"], database=True)
        endpoint(f"/api/v1/admin/{kind}", "post", "Teacher: create " + kind, kind + "Create", status="201", database=True)
        endpoint(f"/api/v1/admin/{kind}/{{id}}", "patch", "Teacher: update " + kind, kind + "Update", database=True)
    endpoint("/api/v1/admin/grades/{id}", "delete", "Teacher: delete grade in owned course", database=True)
    endpoint("/api/v1/admin/courses/{id}", "delete", "Teacher: delete owned course without related records", database=True)
    endpoint("/api/v1/admin/users", "get", "Teacher: list users", database=True)
    endpoint("/api/v1/admin/students", "post", "Teacher: create student", "StudentCreate", status="201", database=True)
    endpoint("/api/v1/grade-summary", "get", "Student: grade calculation from LMS", query=["course_id", "target"], database=True)
    endpoint("/api/v1/attendance-summary", "get", "Student: marked and unmarked attendance", query=["course_id"], database=True)
    endpoint("/api/v1/grading/calculate", "post", "Arithmetic simulation of explicit input; no database", "CalculationRequest")
    endpoint("/api/v1/agent/query", "post", "Student: local MCP or server-selected Alem/Vertex LLM; model blocked while pending/disabled", "AgentRequest")
    endpoint("/api/v1/agent/stream", "post", "Student: agent action journal over POST SSE", "AgentRequest", stream=True)
    return {"openapi": "3.1.0", "info": {"title": "CampusPulse LMS local API", "version": "0.5.0"},
            "servers": [{"url": "/"}], "paths": paths,
            "components": {"securitySchemes": {"localSession": {"type": "apiKey", "in": "cookie", "name": "campuspulse_lms"}}, "schemas": schemas}}
