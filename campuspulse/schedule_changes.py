"""Atomic teacher timetable edits with stale-data and overlap checks."""
from .domain import parse_time
from .lms_store import LmsError
from .lms_validation import identifier


def update_schedule(repo, actor, payload):
    repo.require_admin(actor)
    if not isinstance(payload,dict) or set(payload)!={'changes'} or not isinstance(payload['changes'],list) or not 1<=len(payload['changes'])<=100:
        raise LmsError('Нужны от 1 до 100 изменений расписания.')
    changes={}
    for change in payload['changes']:
        if not isinstance(change,dict) or set(change)!={'id','starts_at','ends_at','expected_start','expected_end'}:
            raise LmsError('Изменение: id, starts_at, ends_at, expected_start, expected_end.')
        key=identifier(change['id'],'id')
        if key in changes:
            raise LmsError('Повторяющееся занятие.')
        clean={field:parse_time(change[field]) for field in ['starts_at','ends_at','expected_start','expected_end']}
        if clean['ends_at']<=clean['starts_at'] or clean['ends_at']-clean['starts_at'] != clean['expected_end']-clean['expected_start']:
            raise LmsError('Перенос должен сохранять длительность занятия.')
        if clean['starts_at'].minute%20 or clean['starts_at'].second or clean['starts_at'].microsecond:
            raise LmsError('Переносите занятия с шагом 20 минут.')
        changes[key]=clean
    def apply(tx):
        courses=repo._courses(actor,tx)
        rows={}
        for cid,course in courses.items():
            if not course.get('archived'):
                rows.update(repo._scan('lessons',[('course_id','==',cid)],tx))
        assignments=[]
        for key,change in changes.items():
            row=rows.get(key)
            if row is None:
                raise LmsError('Занятие недоступно преподавателю.',403)
            if parse_time(row['starts_at'])!=change['expected_start'] or parse_time(row['ends_at'])!=change['expected_end']:
                raise LmsError('Расписание уже изменилось. Обновите страницу.',409)
            assignments.extend((aid,assignment,change) for aid,assignment in repo._scan('assignments',[('lesson_id','==',key)],tx)
                               if assignment.get('due') is not None and parse_time(assignment['due'])==change['expected_end'])
        final=[(key,changes.get(key,{}).get('starts_at',parse_time(row['starts_at'])),changes.get(key,{}).get('ends_at',parse_time(row['ends_at']))) for key,row in rows.items()]
        for key,start,end in final:
            if key in changes and any(other!=key and a<end and b>start for other,a,b in final):
                raise LmsError('Занятия пересекаются. Выберите свободное время.',409)
        for key,change in changes.items():
            repo.storage.put(tx,f'lessons/{key}',{**rows[key],'starts_at':change['starts_at'],'ends_at':change['ends_at']})
        for aid,assignment,change in assignments:
            repo.storage.put(tx,f'assignments/{aid}',{**assignment,'due':change['ends_at']})
        return {'updated':len(changes),'updated_deadlines':len(assignments)}
    return repo._run(actor,'lessons','update',apply)
