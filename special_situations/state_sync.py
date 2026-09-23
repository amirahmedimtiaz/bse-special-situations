"""Encrypted, compressed state partitions in a separate Git branch."""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

from cryptography.fernet import Fernet


class StateSync:
    def __init__(self, folder: Path, remote: str, key: str):
        self.folder = folder
        self.pending_push = False
        self.fernet = Fernet(key.encode())
        self.folder.mkdir(parents=True, exist_ok=True)
        self.git("init", "--initial-branch=state")
        self.git("remote", "add", "origin", remote)
        self.git("config", "user.name", "github-actions[bot]")
        self.git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
        if self.git("ls-remote", "--heads", "origin", "refs/heads/state").strip():
            self.git("fetch", "--depth=1", "origin", "state")
            self.git("checkout", "-B", "state", "FETCH_HEAD")

    def git(self, *args):
        env = os.environ.copy()
        if env.get("GITHUB_TOKEN"):
            auth = base64.b64encode(f"x-access-token:{env['GITHUB_TOKEN']}".encode()).decode()
            env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
                       GIT_CONFIG_VALUE_0=f"AUTHORIZATION: basic {auth}")
        return subprocess.run(["git", *args], cwd=self.folder, env=env, check=True,
                              text=True, capture_output=True, timeout=90).stdout

    def restore(self, store):
        for path in sorted(self.folder.glob("*.enc")):
            if len(path.stem) == 10 and (self.folder / f"{path.stem}.meta.enc").exists():
                continue  # Prefer sharded snapshots if a legacy daily snapshot is present.
            value = gzip.decompress(self.fernet.decrypt(path.read_bytes()))
            store.restore(json.loads(value))

    def save(self, store):
        changed = False
        dirty = set(store.changed_days)
        for day, snapshot in store.partitions(dirty):
            # Stable ID buckets prevent re-encrypting a whole day's history at every checkpoint.
            pieces = {"meta": {**snapshot, "items": []}}
            for item in snapshot["items"]:
                bucket = hashlib.sha256(item["filing"]["id"].encode()).hexdigest()[:2]
                pieces.setdefault(bucket, {"version": 1, "day": day, "items": []})["items"].append(item)
            for bucket, piece in pieces.items():
                path = self.folder / f"{day}.{bucket}.enc"
                data = json.dumps(piece, sort_keys=True, separators=(",", ":")).encode()
                if path.exists() and gzip.decompress(self.fernet.decrypt(path.read_bytes())) == data:
                    continue
                temporary = path.with_suffix(".tmp")
                temporary.write_bytes(self.fernet.encrypt(gzip.compress(data, mtime=0)))
                temporary.replace(path)
                changed = True
        if changed:
            self.git("add", "--", "*.enc")
            self.git("commit", "-m", "Checkpoint encrypted daily filing state")
            self.pending_push = True
        if not self.pending_push:
            store.changed_days.difference_update(dirty)
            return
        for attempt in range(3):
            try:
                self.git("push", "origin", "HEAD:refs/heads/state")
                self.pending_push = False
                store.changed_days.difference_update(dirty)
                return
            except subprocess.SubprocessError:
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
