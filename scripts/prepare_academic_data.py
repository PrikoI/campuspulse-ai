"""Idempotent migration of existing real schedule into linked coursework.

No fake grades, attendance or lecture notes. Deadlines are the existing assessment
lesson end times. Effort is an explicit editable planning estimate, not a fact.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def migrate(repo,actor,execute=False):
    from campuspulse.firestore_repository import compound_id
    courses=[row for row in repo.list('courses',actor) if not row.get('archived')]
    users=repo.users(actor)
    enrollments=repo.list('enrollments',actor)
    planned=[]
    for course in courses:
        cid=course['id']
        lessons=repo.list('lessons',actor,cid)
        items=repo.list('grade_items',actor,cid)
        assignments=repo.list('assignments',actor,cid)
        by_title={row['title']:row for row in items}
        for lesson in lessons:
            item=by_title.get(lesson['title'])
            if not item:
                continue
            week=5 if item['title']=='Midterm' else 10 if item['title']=='Endterm' else int(item['title'].split()[-1]) if item['title'].startswith('Assignment ') else None
            existing=next((row for row in assignments if row.get('item_id')==item['id'] or row['title']==item['title']),None)
            fields={'course_id':cid,'title':item['title'],'due':lesson['ends_at'],'week':week,
                    'item_id':item['id'],'lesson_id':lesson['id'],
                    'minutes':120 if item['title'] in {'Midterm','Endterm'} else 90,
                    'description':'Дедлайн: конец соответствующего занятия. Время подготовки — редактируемая оценка преподавателя.'}
            if existing:
                fields={key:value for key,value in fields.items() if key not in existing or existing[key] is None or existing[key]==''}
            if fields:
                planned.append({'collection':'assignments','course':course['name'],'id':existing['id'] if existing else None,'payload':fields})
        for user in users:
            existing=next((row for row in enrollments if row['course_id']==cid and row['student_id']==user['id']),None)
            # Do not silently restore a deliberately archived enrollment.
            if existing is None:
                planned.append({'collection':'enrollments','course':course['name'],'id':None,
                                'payload':{'course_id':cid,'student_id':user['id']}})
    if execute:
        for change in planned:
            repo.save(change['collection'],actor,change['payload'],change['id'])
    return {'execute':execute,'active_courses':len(courses),'students':len(users),'changes':planned}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    from campuspulse.config import load_config
    from campuspulse.firestore_repository import FirestoreRepository
    from campuspulse.lms_store import Principal
    load_config();repo=FirestoreRepository();actor=Principal('admin','admin','Teacher')
    # Preserve a private snapshot of affected collections before any writes.
    if args.execute:
        from datetime import datetime,timezone
        backup={'created_at':datetime.now(timezone.utc).isoformat(),'collections':{}}
        for kind in ['courses','users','enrollments','assignments','grade_items','lessons']:
            backup['collections'][kind]=[{ 'id':d.id,**d.to_dict()} for d in repo.storage.client.collection(kind).stream(timeout=20)]
        folder=ROOT/'.local';folder.mkdir(exist_ok=True)
        (folder/f"academic-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json").write_text(json.dumps(backup,ensure_ascii=False,default=str),encoding='utf-8')
    result=migrate(repo,actor,args.execute)
    print(json.dumps({'execute':args.execute,'courses':result['active_courses'],'students':result['students'],
        'assignments':sum(row['collection']=='assignments' for row in result['changes']),
        'enrollments':sum(row['collection']=='enrollments' for row in result['changes'])},ensure_ascii=False))


if __name__=='__main__':main()
