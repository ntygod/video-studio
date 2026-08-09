import os, subprocess, sys
root = os.path.dirname(os.path.abspath(__file__))
DETACHED = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
out = open(os.path.join(root, "server.log"), "ab")
err = open(os.path.join(root, "server.err"), "ab")
p = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8765"],
    cwd=root, stdout=out, stderr=err,
    creationflags=DETACHED | CREATE_NEW_PROCESS_GROUP,
)
print(p.pid)
