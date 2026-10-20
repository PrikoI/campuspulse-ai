"""Enable Alem in the ignored .env without displaying or replacing credentials."""
from pathlib import Path


def configure(path):
    lines = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
    settings = {"CAMPUSPULSE_LLM_PROVIDER": "alem", "CAMPUSPULSE_ALEM_ENABLED": "1"}
    keys = set()
    output = []
    for line in lines:
        key = line.partition("=")[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
        if key in settings:
            if key in keys:
                continue
            output.append(key + "=" + settings[key])
        else:
            output.append(line)
        keys.add(key)
    for key, value in settings.items():
        if key not in keys:
            output.append(key + "=" + value)
    if not keys.intersection({"CAMPUSPULSE_ALEM_MODEL", "GEMMA_MODEL"}):
        output.append("CAMPUSPULSE_ALEM_MODEL=gemma4")
    if not keys.intersection({"CAMPUSPULSE_ALEM_API_KEY", "OPENAI_API_KEY"}):
        output.extend(["# Private Alem API key; never commit .env.", "CAMPUSPULSE_ALEM_API_KEY="])
    path.write_text("\n".join(output) + "\n", encoding="utf-8")


def main():
    configure(Path(__file__).resolve().parents[1] / ".env")
    print("Alem enabled in private .env. Existing credentials preserved; restart the server.")


if __name__=='__main__':main()
