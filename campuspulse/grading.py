"""Deterministic AITU-style grading; no model arithmetic or invented syllabus.

University-wide rules: official 2025 student reference guide, p.14.
Within-attestation coursework/exam weights must come from each course syllabus.
"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_CEILING

GUIDE = "https://moodle.astanait.edu.kz/pluginfile.php/24480/block_html/content/%D0%A1%D0%BF%D1%80%D0%B0%D0%B2%D0%BE%D1%87%D0%BD%D0%B8%D0%BA-%D0%BF%D1%83%D1%82%D0%B5%D0%B2%D0%BE%D0%B4%D0%B8%D1%82%D0%B5%D0%BB%D1%8C_eng_AITU.pdf?time=1757054179862"
DEFAULT_POLICY = {
    "name": "AITU reference guide 2025", "version": 1,
    "attestation1_weight": 0.3, "attestation2_weight": 0.3, "final_weight": 0.4,
    "minimum_attestation": 25, "minimum_register": 50, "minimum_final": 50,
    "minimum_total": 50, "coursework_weight": None, "exam_weight": None,
    "attendance_minimum_percent": None, "source_url": GUIDE,
}
COMPONENTS = {"regmid", "midterm", "regend", "endterm", "attestation1", "attestation2", "final"}
SCALE = [(95, "A", 4.0), (90, "A-", 3.67), (85, "B+", 3.33),
         (80, "B", 3.0), (75, "B-", 2.67), (70, "C+", 2.33),
         (65, "C", 2.0), (60, "C-", 1.67), (55, "D+", 1.33),
         (50, "D", 1.0), (25, "FX", 0.0), (0, "F", 0.0)]


def number(value, name="Балл", low=0, high=100):
    if isinstance(value, bool):
        raise ValueError(f"{name}: нужно число от {low} до {high}.")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{name}: нужно число от {low} до {high}.") from None
    if not result.is_finite() or not Decimal(str(low)) <= result <= Decimal(str(high)):
        raise ValueError(f"{name}: нужно число от {low} до {high}.")
    return result


def policy_config(raw=None):
    if raw is not None and not isinstance(raw, dict):
        raise ValueError("Политика оценивания должна быть объектом.")
    raw = raw or {}
    unknown = set(raw) - set(DEFAULT_POLICY)
    if unknown:
        raise ValueError("Неизвестные поля политики: " + ", ".join(sorted(unknown)))
    policy = {**deepcopy(DEFAULT_POLICY), **raw}
    if isinstance(policy["version"], bool) or not isinstance(policy["version"], int) or policy["version"] < 1:
        raise ValueError("Версия политики: положительное целое число.")
    weights = [number(policy[key], key, 0, 1) for key in ("attestation1_weight", "attestation2_weight", "final_weight")]
    if sum(weights) != 1 or weights[2] == 0:
        raise ValueError("Веса двух аттестаций и финала должны давать 1; вес финала больше 0.")
    for key in ("minimum_attestation", "minimum_register", "minimum_final", "minimum_total"):
        policy[key] = float(number(policy[key], key))
    c, e = policy["coursework_weight"], policy["exam_weight"]
    if (c is None) != (e is None):
        raise ValueError("Нужно указать оба веса: coursework_weight и exam_weight.")
    if c is not None:
        if number(c, "Вес заданий", 0, 1) + number(e, "Вес экзамена", 0, 1) != 1:
            raise ValueError("Веса заданий и экзамена должны давать 1.")
    if policy["attendance_minimum_percent"] is not None:
        policy["attendance_minimum_percent"] = float(number(policy["attendance_minimum_percent"], "Порог посещаемости"))
    if not isinstance(policy["name"], str) or len(policy["name"]) > 200:
        raise ValueError("Некорректное имя политики.")
    if not isinstance(policy["source_url"], str) or len(policy["source_url"]) > 2000:
        raise ValueError("Некорректный источник политики.")
    return policy


def letter_grade(score):
    score = number(score)
    for threshold, letter, gpa in SCALE:
        if score >= threshold:
            return {"letter": letter, "gpa": gpa}


def evaluate_grades(items, policy=None, target=50):
    """Missing grades stay unknown; never normalize away ungraded components."""
    policy = policy_config(policy)
    target = number(target, "Целевой итог")
    buckets = {name: [] for name in COMPONENTS}
    for item in items:
        component = item.get("component")
        if not isinstance(component, str) or component not in COMPONENTS:
            raise ValueError("Неизвестный компонент оценки.")
        if item.get("score") is None:
            buckets[component].append((None, number(item.get("weight", 1), "Вес работы", 0.001, 1000)))
        else:
            normalized = number(item["score"], "Балл", 0, item.get("max_score", 100)) / number(item.get("max_score", 100), "Максимум", 0.001, 100000) * 100
            buckets[component].append((normalized, number(item.get("weight", 1), "Вес работы", 0.001, 1000)))
    values, missing = {}, []
    for key, rows in buckets.items():
        if rows and all(score is not None for score, _ in rows):
            values[key] = sum(score * weight for score, weight in rows) / sum(weight for _, weight in rows)
        else:
            values[key] = None
    warnings = []
    attestations = []
    for total, coursework, exam in [("attestation1", "regmid", "midterm"), ("attestation2", "regend", "endterm")]:
        value = values[total]
        if value is None and values[coursework] is not None and values[exam] is not None:
            if policy["coursework_weight"] is None:
                warnings.append("Веса RegMid/Midterm и RegEnd/Endterm не заданы силлабусом; аттестация не рассчитана.")
            else:
                value = values[coursework] * Decimal(str(policy["coursework_weight"])) + values[exam] * Decimal(str(policy["exam_weight"]))
        if value is None:
            missing.append(total)
        attestations.append(value)
    a1, a2 = attestations
    register = (a1 + a2) / 2 if a1 is not None and a2 is not None else None
    admission = None
    reasons = []
    if register is not None:
        admission = a1 >= policy["minimum_attestation"] and a2 >= policy["minimum_attestation"] and register >= policy["minimum_register"]
        if a1 < policy["minimum_attestation"] or a2 < policy["minimum_attestation"]:
            reasons.append("Одна из аттестаций ниже минимального порога.")
        if register < policy["minimum_register"]:
            reasons.append("Рейтинг допуска ниже минимального порога.")
    final = values["final"]
    total = None
    if register is not None and final is not None:
        total = a1 * Decimal(str(policy["attestation1_weight"])) + a2 * Decimal(str(policy["attestation2_weight"])) + final * Decimal(str(policy["final_weight"]))
    required = None
    if a1 is not None and a2 is not None:
        raw_required = (target - a1 * Decimal(str(policy["attestation1_weight"])) - a2 * Decimal(str(policy["attestation2_weight"]))) / Decimal(str(policy["final_weight"]))
        required = max(Decimal(str(policy["minimum_final"])), raw_required, Decimal(0)).quantize(Decimal("0.01"), rounding=ROUND_CEILING)
    if final is None:
        missing.append("final")
    return {
        "policy": policy, "components": {key: float(value) if value is not None else None for key, value in values.items()},
        "attestation1": float(a1) if a1 is not None else None,
        "attestation2": float(a2) if a2 is not None else None,
        "register": float(register) if register is not None else None,
        "final": float(final) if final is not None else None,
        "total": float(total) if total is not None else None,
        "grade": letter_grade(total) if total is not None else None,
        "academic_admission": admission, "admission_reasons": reasons,
        "passed": (admission and final >= policy["minimum_final"] and total >= policy["minimum_total"]) if total is not None else None,
        "target_total": float(target), "required_final": float(required) if required is not None else None,
        "target_reachable": (admission and required <= 100) if required is not None else None,
        "missing": missing, "warnings": list(dict.fromkeys(warnings)),
        "note": "Арифметический расчёт; отсутствующие оценки не заменяются нулями. Статус допуска здесь учитывает оценки; посещаемость проверяется отдельно. Правила стипендии не заданы.",
    }
