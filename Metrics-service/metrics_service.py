from flask import Flask, jsonify
from pymongo import MongoClient
from datetime import datetime, timedelta
import os

app = Flask(__name__)

MONGO_URI = os.environ["MONGO_URI"]
client = MongoClient(MONGO_URI)
db = client.student_events
collection = db.events

try:
    client.admin.command('ping')
    print("✅ Connected to MongoDB")
except Exception as e:
    print(f"❌ MongoDB connection error: {e}")

@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"}), 200

@app.route("/metrics/logins", methods=["GET"])
def total_logins():
    count = collection.count_documents({"type": "login"})
    return jsonify({"total_logins": count})

@app.route("/metrics/logins/average", methods=["GET"])
def avg_logins_per_user():
    pipeline = [
        {"$match": {"type": "login"}},
        {"$group": {"_id": "$user_id", "count": {"$sum": 1}}},
        {"$group": {"_id": None, "average_logins": {"$avg": "$count"}}}
    ]
    result = list(collection.aggregate(pipeline))
    if result:
        return jsonify({"average_logins": result[0]["average_logins"]})
    else:
        return jsonify({"average_logins": 0})
    # return jsonify(result[0] if result else {"average_logins": 0})

@app.route("/metrics/quiz/success-rate", methods=["GET"])
def quiz_success_rate():
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
    return jsonify(result[0] if result else {"success_rate": 0})

@app.route("/metrics/activity/last7days", methods=["GET"])
def activity_trend():
    since = datetime.utcnow() - timedelta(days=7)
    pipeline = [
        {"$match": {"_ingest_ts": {"$gte": since}}},
        {"$group": {"_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$_ingest_ts"}}, "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}}
    ]
    result = list(collection.aggregate(pipeline))
    return jsonify(result)

@app.route("/metrics/quiz/average-score", methods=["GET"])
def avg_score_per_course():
    pipeline = [
        {"$match": {"type": "quiz_submission"}},
        {"$group": {"_id": "$course_id", "average_score": {"$avg": "$score"}}}
    ]
    result = list(collection.aggregate(pipeline))
    return jsonify(result)

@app.route("/metrics/downloads", methods=["GET"])
def downloads():
    pipeline = [
        {"$match": {"type": "download_materiale"}},
        {"$group": {"_id": "$materiale_id", "downloads": {"$sum": 1}}}
    ]
    result = list(collection.aggregate(pipeline))
    return jsonify(result)

@app.route("/metrics/exams", methods=["GET"])
def exams():
    pipeline = [
        {"$match": {"type": "prenotazione_esame"}},
        {"$group": {"_id": "$course_id", "prenotazioni": {"$sum": 1}}}
    ]
    result = list(collection.aggregate(pipeline))
    return jsonify(result)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
