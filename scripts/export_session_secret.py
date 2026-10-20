"""Export the existing private signing secret to an ignored upload file, never stdout."""
import os
from pathlib import Path


def main():
    from campuspulse.config import load_config
    load_config()
    value=os.getenv('CAMPUSPULSE_LMS_SESSION_SECRET','')
    if len(value)<32:
        raise SystemExit('Set a shared random session secret of at least 32 characters first')
    folder=Path(__file__).resolve().parents[1]/'.local'
    folder.mkdir(exist_ok=True)
    (folder/'session-secret.txt').write_text(value,encoding='utf-8')
    print('Private secret export ready in .local/session-secret.txt; value not displayed')


if __name__=='__main__':main()
