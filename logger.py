import asyncio
import collections
from datetime import datetime

# Ring buffer for recent logs (stores last 500 lines)
log_buffer = collections.deque(maxlen=500)
subscribers = set()

def emit_log(msg: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] {msg}"
    print(formatted, flush=True)
    log_buffer.append(formatted)
    
    # Notify active SSE subscribers
    dead_subscribers = set()
    for q in subscribers:
        try:
            q.put_nowait(formatted)
        except asyncio.QueueFull:
            pass
        except Exception:
            dead_subscribers.add(q)
    for d in dead_subscribers:
        subscribers.discard(d)

def get_recent_logs():
    return list(log_buffer)

def subscribe():
    q = asyncio.Queue(maxsize=100)
    subscribers.add(q)
    return q

def unsubscribe(q):
    subscribers.discard(q)
