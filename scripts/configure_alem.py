"""Set Alem defaults and add a private key slot without displaying/replacing keys."""
from pathlib import Path


def main():
    root=Path(__file__).resolve().parents[1]
    settings={'CAMPUSPULSE_LLM_PROVIDER':'alem','OPENAI_BASE_URL':'https://llm.alem.ai/v1',
              'GEMMA_MODEL':'gemma4','CAMPUSPULSE_ALEM_TOOL_MODE':'json','CAMPUSPULSE_ALLOW_CLOUD':'1'}
    for filename in ['.env','.env.example','cloud-config.example.env']:
        path=root/filename
        lines=path.read_text(encoding='utf-8-sig').splitlines() if path.exists() else []
        keys={line.split('=',1)[0].strip() for line in lines if '=' in line and not line.lstrip().startswith('#')}
        output=[]
        for line in lines:
            key=line.split('=',1)[0].strip() if '=' in line and not line.lstrip().startswith('#') else ''
            output.append(key+'='+settings[key] if key in settings else line)
        for key,value in settings.items():
            if key not in keys:output.append(key+'='+value)
        if 'OPENAI_API_KEY' not in keys:
            output.extend(['# Alem API key: insert only in ignored .env, never in example files.','OPENAI_API_KEY='])
        # Example files must never contain a previously entered real API key.
        if filename!='.env':
            output=['OPENAI_API_KEY=' if line.strip().startswith('OPENAI_API_KEY=') else line for line in output]
        path.write_text('\n'.join(output)+'\n',encoding='utf-8')
    print('Alem settings prepared. Existing private key preserved; key contents not displayed.')


if __name__=='__main__':main()
