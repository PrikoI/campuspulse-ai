"""Live, read-only student scenario. Does not call Gemini unless --gemini is explicit."""
import argparse
import json
import requests


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:8771');parser.add_argument('--gemini',action='store_true');args=parser.parse_args()
    base=args.url.rstrip('/')+'/api/v1/'
    session=requests.Session()
    response=session.post(base+'auth/login',json={'username':'student1','password':'student1'},timeout=30);response.raise_for_status()
    print('Login verified')
    for path in ['courses','assignments']:
        response=session.get(base+path,timeout=30);response.raise_for_status();print(path,len(response.json()['items']))
    for message in ['Покажи расписание на неделю','Составь и сохрани план подготовки на неделю']:
        response=session.post(base+'agent/query',json={'message':message,'engine':'gemini' if args.gemini else 'local'},timeout=210)
        response.raise_for_status();data=response.json()
        tools=[event['tool'] for event in data.get('trace',[]) if event['type']=='tool_start']
        errors=[event for event in data.get('trace',[]) if event['type']=='tool_result' and event.get('status')=='error']
        if errors:raise RuntimeError(json.dumps(errors,ensure_ascii=False))
        print(json.dumps({'request':message,'answer':data['answer'],'tools':tools,
          'mcp_ready':any(event['type']=='mcp_ready' for event in data['trace']),
          'proposal_prepared':bool(data['results'].get('prepare_study_plan',{}).get('proposal')),
          'provider':data.get('provider'),'model':data.get('model'),'model_called':data.get('model_called'),
          'deployment':data.get('deployment','local-backend')},ensure_ascii=False))
        if args.gemini and (not data.get('model_called') or not tools):
            raise RuntimeError('Gemini smoke requires actual model invocation and at least one tool call')
    print('PASS: no plan confirmation sent; no personal task writes')


if __name__=='__main__':main()
