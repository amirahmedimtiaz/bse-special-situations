"""Copy supplied credentials into GitHub Secrets without logging their contents."""
from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import dotenv_values


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--email-env", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    local = root / ".env"
    current = dotenv_values(local) if local.exists() else {}
    email = dotenv_values(args.email_env)
    values = {"OPENROUTER_API_KEY": os.getenv("OPENROUTER_API_KEY") or current.get("OPENROUTER_API_KEY")}
    for key in ("EMAIL_SENDER", "EMAIL_PASSWORD", "EMAIL_RECEIVER"):
        values[key] = current.get(key) or email.get(key)
    values["STATE_ENCRYPTION_KEY"] = current.get("STATE_ENCRYPTION_KEY") or Fernet.generate_key().decode()
    if not all(values.values()):
        raise ValueError("Required credentials are missing; no secrets were printed or uploaded")
    # Generated local credential backup: private permissions, ignored by Git.
    # Never rotate an existing state key implicitly: it is needed to decrypt history.
    saved = {**current, **values}
    with os.fdopen(os.open(local, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as stream:
        os.chmod(local, 0o600)
        for key, value in saved.items():
            if value is not None:
                escaped = value.replace("\\", "\\\\").replace("'", "\\'")
                stream.write(f"{key}='{escaped}'\n")
    for key, value in values.items():
        subprocess.run(["gh", "secret", "set", key, "--repo", args.repo], input=value,
                       text=True, capture_output=True, check=True)
        print(f"Configured secret: {key}")
    print("Local encrypted-state recovery key backed up in ignored .env (mode 0600).")


if __name__ == "__main__":
    main()
