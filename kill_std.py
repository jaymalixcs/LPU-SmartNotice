import subprocess
import os
import signal

out = subprocess.check_output('netstat -ano | findstr :8000', shell=True).decode()
pids = set()
for line in out.strip().split('\n'):
    parts = line.split()
    if len(parts) >= 5 and '8000' in parts[1] and parts[3] == 'LISTENING':
        pids.add(int(parts[4]))

print("PIDs listening on 8000:", pids)
for pid in pids:
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"Sent SIGTERM to {pid}")
    except Exception as e:
        print(f"Error killing {pid}: {e}")

