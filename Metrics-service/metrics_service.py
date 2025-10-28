from flask import Flask, jsonify
from pymongo import MongoClient
from datetime import datetime, timedelta
import os

app = Flask(__name__)

#Leggi il nome del pod
POD_NAME = os.getenv("POD_NAME", "unknown-pod")

MONGO_URI = os.environ["MONGO_URI"]
client = MongoClient(MONGO_URI)
db = client.student_events
collection = db.events

#Test di connessione (solo log)
try:
    client.admin.command('ping')
    print("Connected to MongoDB")
except Exception as e:
    print(f"MongoDB connection error: {e}")

@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"}), 200

#Totale logins
@app.route("/metrics/logins", methods=["GET"])
def total_logins():
    print(f"[METRICS @ {POD_NAME}] Esecuzione /metrics/logins", flush=True)
    count = collection.count_documents({"type": "login"})
    return jsonify({"total_logins": count, "processed_by": POD_NAME})

#Media logins per utente
@app.route("/metrics/logins/average", methods=["GET"])
def avg_logins_per_user():
    print(f"[METRICS @ {POD_NAME}] Esecuzione /metrics/logins/average", flush=True)
    pipeline = [
        {"$match": {"type": "login"}},
        {"$group": {"_id": "$user_id", "count": {"$sum": 1}}},
        {"$group": {"_id": None, "average_logins": {"$avg": "$count"}}}
    ]
    result = list(collection.aggregate(pipeline))
    response_data = result[0] if result else {"average_logins": 0}
    response_data["processed_by"] = POD_NAME
    return jsonify(response_data)
    # if result:
    #     return jsonify({"average_logins": result[0]["average_logins"]})
    # else:
    #     return jsonify({"average_logins": 0})
    # return jsonify(result[0] if result else {"average_logins": 0})

#Tasso di successo dei quiz
@app.route("/metrics/quiz/success-rate", methods=["GET"])
def quiz_success_rate():
    print(f"[METRICS @ {POD_NAME}] Esecuzione /metrics/quiz/success-rate", flush=True)
    pipeline = [
        {"$match": {"type": "quiz_submission"}},
        {"$group": {
            "_id": None,
            "total": {"$sum": 1},
            "success": {"$sum": {"$cond": [{"$gte": ["$score", 18]}, 1, 0]}}
        }},
        {"$project": {"_id": 0, "success_rate": {"$multiply": [{"$divide": ["$success", "$total"]}, 100]}}}
    ]
    result = list(collection.aggregate(pipeline))
    # return jsonify(result[0] if result else {"success_rate": 0})
    response_data = result[0] if result else {"success_rate": 0}
    response_data["processed_by"] = POD_NAME
    return jsonify(response_data)

#Attività ultimi 7 giorni
@app.route("/metrics/activity/last7days", methods=["GET"])
def activity_trend():
    print(f"[METRICS @ {POD_NAME}] Esecuzione /metrics/activity/last7days", flush=True)
    since = datetime.utcnow() - timedelta(days=7)
    pipeline = [
        {"$match": {"_ingest_ts": {"$gte": since}}},
        {"$group": {"_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$_ingest_ts"}}, "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}}
    ]
    result = list(collection.aggregate(pipeline))
    return jsonify({"data": result, "processed_by": POD_NAME})

#Media punteggi per corso
@app.route("/metrics/quiz/average-score", methods=["GET"])
def avg_score_per_course():
    print(f"[METRICS @ {POD_NAME}] Esecuzione /metrics/quiz/average-score", flush=True)
    pipeline = [
        {"$match": {"type": "quiz_submission"}},
        {"$group": {"_id": "$course_id", "average_score": {"$avg": "$score"}}}
    ]
    result = list(collection.aggregate(pipeline))
    return jsonify({"data": result, "processed_by": POD_NAME})

#Download per materiale
@app.route("/metrics/downloads", methods=["GET"])
def downloads():
    print(f"[METRICS @ {POD_NAME}] Esecuzione /metrics/downloads", flush=True)
    pipeline = [
        {"$match": {"type": "download_materiale"}},
        {"$group": {"_id": "$materiale_id", "downloads": {"$sum": 1}}}
    ]
    result = list(collection.aggregate(pipeline))
    return jsonify({"data": result, "processed_by": POD_NAME})

#Prenotazioni esami per corso
@app.route("/metrics/exams", methods=["GET"])
def exams():
    print(f"[METRICS @ {POD_NAME}] Esecuzione /metrics/exams", flush=True)
    pipeline = [
        {"$match": {"type": "prenotazione_esame"}},
        {"$group": {"_id": "$course_id", "prenotazioni": {"$sum": 1}}}
    ]
    result = list(collection.aggregate(pipeline))
    return jsonify({"data": result, "processed_by": POD_NAME})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
