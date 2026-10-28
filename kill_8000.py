import os
import signal
import psutil

for conn in psutil.net_connections():
    if conn.laddr.port == 8000:
        print(f"Found connection on 8000: PID={conn.pid}, status={conn.status}")
        if conn.pid:
            p = psutil.Process(conn.pid)
            print(f"Process Name: {p.name()}, exe: {p.exe()}")
            p.kill()
            print("Killed process successfully!")

