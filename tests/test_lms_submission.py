"""Critical submission paths, with no real credentials or network."""
import asyncio
import copy
import os
import tempfile
import unittest
from datetime import datetime,timedelta
from pathlib import Path
from unittest.mock import AsyncMock,patch

from campuspulse.config import load_config
from campuspulse.domain import TZ
from campuspulse.firestore_repository import FirestoreRepository,compound_id
from campuspulse.lms_store import LmsError,Principal
from campuspulse.lms_tools import LmsTools
from campuspulse.schedule_changes import update_schedule
from campuspulse.study_plan import prepare_plan,confirm_plan
from tests.test_lms_firestore import CONFIG,ADMIN,STUDENT,OTHER,seeded_storage


class SubmissionTests(unittest.TestCase):
    def setUp(self):
        self.storage=seeded_storage()
        self.repo=FirestoreRepository(self.storage,CONFIG)

    def test_config_does_not_override_environment_or_execute_values(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'.env';path.write_text('EXISTING=file\nNEW_VALUE="$(untrusted)"\nEMPTY=\n',encoding='utf-8')
            with patch.dict(os.environ,{'EXISTING':'environment'},clear=True):
                load_config(path)
                self.assertEqual(os.environ['EXISTING'],'environment')
                self.assertEqual(os.environ['NEW_VALUE'],'$(untrusted)')
                self.assertNotIn('EMPTY',os.environ)

    def test_120_lessons_do_not_break_schedule_or_plan_and_hide_other_courses(self):
        now=datetime.now(TZ).replace(hour=10,minute=0,second=0,microsecond=0)+timedelta(days=1)
        # 6 enrolled courses * 20 lessons. Each per-course result stays bounded.
        for c in range(6):
            cid=f'course{c}'
            self.storage.data[f'courses/{cid}']={'code':cid,'name':cid,'owner_id':'admin'}
            self.storage.data[f'enrollments/{compound_id(cid,"student1")}']={'course_id':cid,'student_id':'student1','archived':False}
            for i in range(20):
                start=now+timedelta(days=i,hours=c)
                self.storage.data[f'lessons/{cid}-{i}']={'course_id':cid,'title':'Lecture','starts_at':start,'ends_at':start+timedelta(minutes=40)}
        result=LmsTools(self.repo,STUDENT).call('get_schedule')
        self.assertNotIn('error',result)
        self.assertEqual(len(result['lessons']),42)
        self.assertNotIn('other',{row['course_id'] for row in result['lessons']})
        self.assertIn('plan',LmsTools(self.repo,STUDENT).call('plan_study'))

    def lesson(self,key,start):
        row={'course_id':'course','title':'Assignment 1','starts_at':start,'ends_at':start+timedelta(minutes=80)}
        self.storage.data['lessons/'+key]=row
        return row

    def change(self,key,row,start):
        return {'id':key,'expected_start':row['starts_at'].isoformat(),'expected_end':row['ends_at'].isoformat(),
                'starts_at':start.isoformat(),'ends_at':(start+timedelta(minutes=80)).isoformat()}

    def test_schedule_atomic_conflicts_stale_writes_and_linked_deadline(self):
        start=datetime(2030,1,1,10,tzinfo=TZ)
        row=self.lesson('one',start);self.lesson('two',start+timedelta(hours=2))
        self.storage.data['assignments/a'].update(lesson_id='one',due=row['ends_at'])
        before=copy.deepcopy(self.storage.data)
        with self.assertRaises(LmsError):
            update_schedule(self.repo,ADMIN,{'changes':[self.change('one',row,start+timedelta(hours=2))]})
        self.assertEqual(self.storage.data,before)
        change=self.change('one',row,start+timedelta(days=1))
        with self.assertRaises(LmsError):update_schedule(self.repo,STUDENT,{'changes':[change]})
        self.assertEqual(update_schedule(self.repo,ADMIN,{'changes':[change]})['updated_deadlines'],1)
        self.assertEqual(self.storage.data['assignments/a']['due'],start+timedelta(days=1,minutes=80))
        with self.assertRaises(LmsError):update_schedule(self.repo,ADMIN,{'changes':[change]})

    def test_plan_proposal_writes_only_on_confirmation_and_is_idempotent(self):
        start=datetime(2030,1,1,14,tzinfo=TZ)
        plan={'blocks':[{'task_id':'a','title':'Work','course':'CS','start':start.isoformat(),
                         'end':(start+timedelta(minutes=50)).isoformat(),'minutes':50}]}
        before=copy.deepcopy(self.storage.data)
        proposal=prepare_plan(self.repo,STUDENT,plan)
        self.assertEqual(self.storage.data,before)
        with self.assertRaises(LmsError):confirm_plan(self.repo,OTHER,proposal['proposal'])
        self.assertEqual(confirm_plan(self.repo,STUDENT,proposal['proposal'])['created'],1)
        self.assertTrue(confirm_plan(self.repo,STUDENT,proposal['proposal'])['already_applied'])
        with self.assertRaises(LmsError):confirm_plan(self.repo,STUDENT,proposal['proposal']+'x')

    def test_logout_is_respected_by_a_second_repository_process(self):
        token,_=self.repo.login('student1','student1')
        other=FirestoreRepository(self.storage,CONFIG)
        other.secret=self.repo.secret
        self.assertEqual(other.principal(token).user_id,'student1')
        self.repo.logout(token)
        with self.assertRaises(LmsError):other.principal(token)

    def test_cloud_agent_does_not_serialize_credentials(self):
        from campuspulse.cloud_agent import CampusPulseCloudAgent
        agent=CampusPulseCloudAgent()
        self.assertEqual(vars(agent),{})
        with patch.dict(os.environ,{'CAMPUSPULSE_LMS_SESSION_SECRET':'x'*40,'CAMPUSPULSE_LLM_PROVIDER':'vertex'}),patch('campuspulse.lms_repository.open_repository',return_value=self.repo),patch('campuspulse.lms_agent.run_lms_query',new=AsyncMock(return_value={'answer':'ok'})) as run:
            answer=agent.query('signed-token','Plan')
        self.assertEqual(answer['answer'],'ok')
        self.assertEqual(run.call_args.args[2]['engine'],'gemini')

    def test_academic_migration_links_existing_assessment_and_is_idempotent(self):
        from scripts.prepare_academic_data import migrate
        self.repo.save('grade_items',ADMIN,{'course_id':'course','title':'Assignment 1','component':'regmid'})
        self.lesson('assessment',datetime(2030,1,1,10,tzinfo=TZ))
        before_grades=copy.deepcopy({key:row for key,row in self.storage.data.items() if key.startswith('grades/')})
        preview=migrate(self.repo,ADMIN)
        self.assertTrue(any(row['collection']=='assignments' for row in preview['changes']))
        migrate(self.repo,ADMIN,True)
        self.assertEqual(migrate(self.repo,ADMIN)['changes'],[])
        assignments=self.repo.list('assignments',ADMIN,'course')
        linked=next(row for row in assignments if row.get('lesson_id')=='assessment')
        self.assertEqual(linked['due'],'2030-01-01T11:20:00+05:00')
        self.assertEqual(before_grades,{key:row for key,row in self.storage.data.items() if key.startswith('grades/')})


if __name__=='__main__':unittest.main()
