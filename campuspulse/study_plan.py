"""Signed, idempotent review of a computed study plan; the model cannot confirm."""
import base64
import hashlib
import hmac
import json
import time

from .firestore_personal import task_record
from .lms_store import LmsError


def prepare_plan(repository, actor, plan):
    if actor.role != 'student':
        raise LmsError('План доступен только студенту.', 403)
    tasks = []
    grouped = {}
    for block in plan.get('blocks', []):
        if block['task_id'] not in grouped:
            grouped[block['task_id']] = {**block}
        else:
            grouped[block['task_id']]['end'] = block['end']
            grouped[block['task_id']]['minutes'] += block['minutes']
    for block in grouped.values():
        start, end = block['start'], block['end']
        from .domain import parse_time
        minutes = block['minutes']
        if minutes < 10:
            continue
        key = hashlib.sha256(f"{actor.user_id}:{block['task_id']}:{start}".encode()).hexdigest()[:32]
        tasks.append({'id': key, **task_record(key, {'title': block['title'], 'course': block.get('course',''),
                       'due': end, 'minutes': minutes, 'done': False})})
    if not tasks or len(tasks) > 100:
        raise LmsError('Нет блоков для сохранения или план превышает 100 задач.')
    body = base64.urlsafe_b64encode(json.dumps({'actor': actor.user_id, 'target':'study_plan', 'expires':int(time.time())+600,
                                               'tasks':tasks}, ensure_ascii=False).encode()).decode().rstrip('=')
    return {'proposal': body+'.'+repository._signature(body), 'change':{'target':'study_plan','tasks':tasks},
            'written':False,'confirmation_required':True,'source':repository.source}


def confirm_plan(repository, actor, token):
    try:
        if not isinstance(token,str) or len(token)>200000:
            raise ValueError()
        body, signature = token.rsplit('.',1)
        if not hmac.compare_digest(signature, repository._signature(body)):
            raise ValueError()
        proposal = json.loads(base64.urlsafe_b64decode(body+'='*(-len(body)%4)))
        if proposal['actor'] != actor.user_id or actor.role != 'student' or proposal['target'] != 'study_plan' or proposal['expires'] <= time.time():
            raise ValueError()
        tasks = proposal['tasks']
        if not isinstance(tasks,list) or not 1 <= len(tasks) <= 100:
            raise ValueError()
    except Exception:
        raise LmsError('Предложение плана недействительно или истекло.', 409) from None
    def apply(tx):
        paths = [(repository._personal_path(actor,'task',task['id']),task) for task in tasks]
        existing = repository.storage.get_many([path for path,_ in paths],tx)
        from .firestore_repository import stored_record
        missing = [(path, task) for path,task in paths if existing.get(path) is None]
        for path,task in missing:
            repository.storage.put(tx,path,stored_record('assignments',{k:v for k,v in task.items() if k!='id'}))
        return {'applied':bool(missing),'created':len(missing),'already_applied':not missing}
    return repository._run(actor,'personal_data','create',apply)
