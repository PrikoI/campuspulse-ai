"""Agent Engine entry point. Serializes no credentials or live SDK clients."""
import asyncio
import os

from .lms_store import LmsError


class CampusPulseCloudAgent:
    def set_up(self):
        if len(os.getenv('CAMPUSPULSE_LMS_SESSION_SECRET', '')) < 32:
            raise RuntimeError('A shared session signing secret of at least 32 characters is required')
        self._repository = None

    def query(self, session_token: str, message: str, course_id: str = '', page: str = 'overview', history: list | None = None) -> dict:
        """IAM-protected RPC with application identity verified from a signed token."""
        if not hasattr(self, '_repository'):
            self.set_up()
        if self._repository is None:
            from .lms_repository import open_repository
            self._repository = open_repository()
        from .lms_agent import run_lms_query
        payload = {'message':message, 'engine':'llm', 'page':page, 'history':history if history is not None else []}
        if course_id:
            payload['course_id'] = course_id
        return asyncio.run(asyncio.wait_for(run_lms_query(self._repository,session_token,payload,transport='mcp'),timeout=180))


async def remote_query(repository, token, payload, emit=None):
    from .lms_validation import agent_payload
    from .config import google_credentials
    clean = agent_payload(payload)
    actor = await asyncio.to_thread(repository.principal,token)
    if actor.role != 'student':
        raise LmsError('Помощник доступен студенту.',403)
    resource = os.getenv('CAMPUSPULSE_AGENT_ENGINE_RESOURCE','')
    import re
    if not re.fullmatch(r'projects/[^/]+/locations/[^/]+/reasoningEngines/[^/]+',resource):
        raise LmsError('Укажите CAMPUSPULSE_AGENT_ENGINE_RESOURCE.',503)
    parts = resource.split('/')
    def invoke():
        from google.auth.transport.requests import AuthorizedSession
        session = AuthorizedSession(google_credentials())
        try:
            response = session.post(f'https://{parts[3]}-aiplatform.googleapis.com/v1/{resource}:query',
                json={'class_method':'query','input':{'session_token':token,'message':clean['message'],
                      'course_id':clean.get('course_id',''),'page':clean.get('page','overview'),
                      'history':clean.get('history',[])}},timeout=190)
            if not response.ok:
                raise LmsError(f'Agent Engine: HTTP {response.status_code}. Проверьте IAM и развёртывание.',503)
            result = response.json().get('output')
            if not isinstance(result,dict) or 'answer' not in result:
                raise LmsError('Agent Engine вернул неожиданный формат.',502)
            return result
        finally:
            session.close()
    if emit:
        emit({'type':'remote_start','provider':'agent-engine','message':'Запрос передан облачному агенту'})
    result = await asyncio.to_thread(invoke)
    if emit:
        for event in result.get('trace',[]):
            emit({**event,'replayed':True})
    result['deployment'] = 'agent-engine'
    return result
