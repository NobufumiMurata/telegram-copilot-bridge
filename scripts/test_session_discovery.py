"""Verify whether a fresh Copilot ACP process can discover sessions
created by other (external) Copilot CLI instances.

Usage:
    python scripts/test_session_discovery.py

Steps:
  1. Start copilot --acp process
  2. Call initialize
  3. Call session/list BEFORE creating any session  (external discovery test)
  4. Create one session via session/new
  5. Call session/list again (should include at least the new session)
  6. Print results and stop
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import time

# ── helpers ─────────────────────────────────────────────────────────

def find_copilot() -> str:
    cmd = shutil.which("copilot")
    if not cmd:
        raise FileNotFoundError("copilot CLI not found in PATH")
    return cmd


class ACPClient:
    """Minimal ACP JSON-RPC client for testing."""

    def __init__(self, cmd: str):
        env = os.environ.copy()
        env["NO_COLOR"] = "1"
        self._proc = subprocess.Popen(
            [cmd, "--acp", "--no-ask-user", "--allow-tool", "read"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            env=env,
        )
        self._msg_id = 0
        self._lock = threading.Lock()
        self._pending: dict[int, tuple[threading.Event, list]] = {}
        self._running = True
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self._stderr_reader = threading.Thread(target=self._stderr_loop, daemon=True)
        self._stderr_reader.start()

    def _next_id(self) -> int:
        with self._lock:
            self._msg_id += 1
            return self._msg_id

    def _read_loop(self):
        while self._running:
            try:
                raw = self._proc.stdout.readline()
            except Exception:
                break
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                print(f"  [non-JSON] {line[:200]}")
                continue
            msg_id = msg.get("id")
            if msg_id is not None and msg_id in self._pending:
                event, slot = self._pending[msg_id]
                slot.append(msg)
                event.set()

    def _stderr_loop(self):
        while self._running:
            try:
                raw = self._proc.stderr.readline()
            except Exception:
                break
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").strip()
            if line:
                print(f"  [stderr] {line[:300]}")

    def request(self, method: str, params: dict, timeout: float = 15.0) -> dict:
        msg_id = self._next_id()
        event = threading.Event()
        slot: list = []
        self._pending[msg_id] = (event, slot)

        payload = json.dumps({
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": msg_id,
        })
        self._proc.stdin.write((payload + "\n").encode("utf-8"))
        self._proc.stdin.flush()

        if not event.wait(timeout=timeout):
            self._pending.pop(msg_id, None)
            raise TimeoutError(f"{method} timed out after {timeout}s")
        self._pending.pop(msg_id, None)
        return slot[0]

    def stop(self):
        self._running = False
        try:
            self._proc.stdin.close()
            self._proc.terminate()
            self._proc.wait(timeout=5)
        except Exception:
            self._proc.kill()


# ── main ────────────────────────────────────────────────────────────

def main():
    copilot_cmd = find_copilot()
    print(f"Copilot CLI: {copilot_cmd}")

    client = ACPClient(copilot_cmd)
    try:
        # Step 1: initialize
        print("\n=== Step 1: initialize ===")
        resp = client.request("initialize", {
            "protocolVersion": 1,
            "clientCapabilities": {},
        })
        caps = resp.get("result", {})
        print(f"  agentInfo: {json.dumps(caps.get('agentInfo', {}), indent=2)}")

        # Step 2: session/list BEFORE creating any session
        print("\n=== Step 2: session/list (BEFORE session/new) ===")
        resp = client.request("session/list", {})
        if resp.get("error"):
            print(f"  ERROR: {resp['error']}")
        else:
            sessions = resp.get("result", {}).get("sessions", [])
            print(f"  Found {len(sessions)} session(s)")
            for s in sessions:
                print(f"    - {json.dumps(s, indent=6)}")

        # Step 3: create a session
        cwd = os.getcwd()
        print(f"\n=== Step 3: session/new (cwd={cwd}) ===")
        resp = client.request("session/new", {"cwd": cwd, "mcpServers": []}, timeout=30.0)
        if resp.get("error"):
            print(f"  ERROR: {resp['error']}")
            return
        session_id = resp["result"]["sessionId"]
        print(f"  Created session: {session_id}")
        print(f"  Models: {json.dumps(resp['result'].get('models', {}), indent=4)}")

        # Step 4: session/list AFTER creating a session
        print("\n=== Step 4: session/list (AFTER session/new) ===")
        resp = client.request("session/list", {})
        if resp.get("error"):
            print(f"  ERROR: {resp['error']}")
        else:
            sessions = resp.get("result", {}).get("sessions", [])
            print(f"  Found {len(sessions)} session(s)")
            for s in sessions:
                print(f"    - {json.dumps(s, indent=6)}")

        # Step 5: try session/load with a session from list (the most recent external one)
        print("\n=== Step 5: session/load (external session) ===")
        external_sessions = resp.get("result", {}).get("sessions", [])
        # Pick the first one that isn't the one we just created
        target = None
        for s in external_sessions:
            if s.get("sessionId") != session_id:
                target = s
                break
        if target:
            t_id = target["sessionId"]
            t_cwd = target.get("cwd", os.getcwd())
            t_title = target.get("title", "?")
            print(f"  Attempting: {t_id[:8]} | {t_title} | cwd={t_cwd}")
            resp = client.request(
                "session/load",
                {"sessionId": t_id, "cwd": t_cwd, "mcpServers": []},
                timeout=15.0,
            )
            if resp.get("error"):
                print(f"  ERROR: {resp['error']}")
            else:
                print(f"  Result: {json.dumps(resp.get('result', {}), indent=4)}")

            # Step 6: try sending a prompt to the loaded session
            print(f"\n=== Step 6: prompt to loaded session ===")
            resp = client.request(
                "session/prompt",
                {
                    "sessionId": t_id,
                    "prompt": [{"type": "text", "text": "What was my last message in this session? Reply in one sentence."}],
                },
                timeout=30.0,
            )
            if resp.get("error"):
                print(f"  ERROR: {resp['error']}")
            else:
                print(f"  stopReason: {resp.get('result', {}).get('stopReason', '?')}")
        else:
            print("  No external session to test.")

    finally:
        print("\n=== Cleanup: stopping ACP process ===")
        client.stop()
        print("Done.")


if __name__ == "__main__":
    main()
