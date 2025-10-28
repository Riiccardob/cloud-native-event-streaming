import requests, random, time, json
from datetime import datetime

BASE_PRODUCER = "http://producer.192.168.49.2.nip.io:30648"
BASE_METRICS = "http://metrics.192.168.49.2.nip.io:30648"

USERS = ["alice", "bob", "charlie", "dave", "eva"]
COURSES = ["math", "physics", "history"]
QUIZZES = ["math101", "phys101", "hist101"]
MATERIALS = ["pdf1", "pdf2", "pdf3"]

def send_event(event_type):
    user = random.choice(USERS)
    course = random.choice(COURSES)

    if event_type == "login":
        data = {"user_id": user}
        endpoint = "/event/login"

    elif event_type == "quiz":
        data = {
            "user_id": user,
            "quiz_id": random.choice(QUIZZES),
            "course_id": course,
            "score": random.randint(10, 30)
        }
        endpoint = "/event/quiz"

    elif event_type == "download":
        data = {
            "user_id": user,
            "materiale_id": random.choice(MATERIALS),
            "course_id": course
        }
        endpoint = "/event/download"

    elif event_type == "exam":
        data = {
            "user_id": user,
            "esame_id": f"{course}_final",
            "course_id": course
        }
        endpoint = "/event/exam"

    else:
        return

    try:
        res = requests.post(BASE_PRODUCER + endpoint, json=data, timeout=5)
        print(f"[{datetime.now().isoformat()}] Sent {event_type.upper()} → {res.status_code}")
    except Exception as e:
        print(f"❌ Error sending {event_type}: {e}")

def get_metrics():
    endpoints = [
        "/metrics/logins",
        "/metrics/quiz/success-rate",
        "/metrics/downloads",
        "/metrics/exams"
    ]
    print("\n📊 METRICS SNAPSHOT")
    for ep in endpoints:
        try:
            res = requests.get(BASE_METRICS + ep, timeout=5)
            print(f"{ep}: {res.text}")
        except Exception as e:
            print(f"{ep}: error ({e})")

if __name__ == "__main__":
    print("🚀 Starting demo loop (Ctrl+C to stop)\n")
    while True:
        send_event(random.choice(["login", "quiz", "download", "exam"]))
        time.sleep(2)
        get_metrics()
        print("-" * 60)
        time.sleep(4)
