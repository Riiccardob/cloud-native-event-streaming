from flask import Flask, jsonify, request
from pymongo import MongoClient
from datetime import datetime, timedelta
import os, time, threading

app = Flask(__name__)

POD_NAME = os.getenv("POD_NAME", "unknown-pod")
MONGO_URI = os.environ["MONGO_URI"]

# Configurazione Mongo con Timeout breve
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
db = client.student_events
collection = db.events

_cache = {}
_cache_lock = threading.Lock()
CACHE_TTL = int(os.getenv("METRICS_CACHE_TTL", 10))

def cache_get(key):
    with _cache_lock:
        entry = _cache.get(key)
        if not entry: return None
        value, ts = entry
        if time.time() - ts > CACHE_TTL:
            del _cache[key]
            return None
        return value

def cache_set(key, value):
    with _cache_lock:
        _cache[key] = (value, time.time())

@app.route("/healthz")
def healthz():
    mongo_ok = False
    try:
        client.admin.command('ping')
        mongo_ok = True
    except Exception as e:
        print(f"[HEALTH FAIL] Mongo unreachable: {e}", flush=True)

    status = {
        "status": "ok" if mongo_ok else "degraded", 
        "mongo_connected": mongo_ok, 
        "processed_by": POD_NAME
    }
    return jsonify(status), 200 if mongo_ok else 503


# 1. Totale logins (Cached)
@app.route("/metrics/logins", methods=["GET"])
def total_logins():
    key = "total_logins"
    cached = cache_get(key)
    if cached: return jsonify({**cached, "source": "cache", "processed_by": POD_NAME})

    count = collection.count_documents({"type": "login"})
    resp = {"total_logins": count}
    cache_set(key, resp)
    return jsonify({**resp, "source": "db", "processed_by": POD_NAME})

# 2. Avg logins per user (Cached)
@app.route("/metrics/logins/average", methods=["GET"])
def avg_logins_per_user():
    key = "avg_logins"
    cached = cache_get(key)
    if cached: return jsonify({**cached, "source": "cache", "processed_by": POD_NAME})

    pipeline = [
        {"$match": {"type": "login"}},
        {"$group": {"_id": "$user_id", "count": {"$sum": 1}}},
        {"$group": {"_id": None, "average_logins": {"$avg": "$count"}}}
    ]
    result = list(collection.aggregate(pipeline))
    resp = result[0] if result else {"average_logins": 0}
    if "_id" in resp: del resp["_id"]
    
    cache_set(key, resp)
    return jsonify({**resp, "source": "db", "processed_by": POD_NAME})

# 3. Downloads (OTTIMIZZATO con $facet)
@app.route("/metrics/downloads", methods=["GET"])
def downloads():
    page = int(request.args.get("page", "1"))
    per_page = int(request.args.get("per_page", "50"))
    skip = (page - 1) * per_page
    key = f"downloads_p{page}_pp{per_page}"
    
    cached = cache_get(key)
    if cached: return jsonify({**cached, "source": "cache", "processed_by": POD_NAME})

    pipeline = [
        {"$match": {"type": "download_materiale"}},
        {"$group": {"_id": "$materiale_id", "downloads": {"$sum": 1}}},
        {"$sort": {"downloads": -1}},
        {"$facet": {
            "metadata": [{"$count": "total"}],
            "data": [{"$skip": skip}, {"$limit": per_page}]
        }}
    ]
    
    result = list(collection.aggregate(pipeline))[0]
    total = result["metadata"][0]["total"] if result["metadata"] else 0
    items = [{"materiale_id": r["_id"], "downloads": r["downloads"]} for r in result["data"]]
    
    resp = {"data": items, "page": page, "per_page": per_page, "total": total}
    cache_set(key, resp)
    return jsonify({**resp, "source": "db", "processed_by": POD_NAME})

# 4. Exams (OTTIMIZZATO con $facet)
@app.route("/metrics/exams", methods=["GET"])
def exams():
    page = int(request.args.get("page", "1"))
    per_page = int(request.args.get("per_page", "50"))
    skip = (page - 1) * per_page
    key = f"exams_p{page}_pp{per_page}"
    
    cached = cache_get(key)
    if cached: return jsonify({**cached, "source": "cache", "processed_by": POD_NAME})

    pipeline = [
        {"$match": {"type": "prenotazione_esame"}},
        {"$group": {"_id": "$course_id", "prenotazioni": {"$sum": 1}}},
        {"$sort": {"prenotazioni": -1}},
        {"$facet": {
            "metadata": [{"$count": "total"}],
            "data": [{"$skip": skip}, {"$limit": per_page}]
        }}
    ]
    
    result = list(collection.aggregate(pipeline))[0]
    total = result["metadata"][0]["total"] if result["metadata"] else 0
    items = [{"course_id": r["_id"], "prenotazioni": r["prenotazioni"]} for r in result["data"]]
    
    resp = {"data": items, "page": page, "per_page": per_page, "total": total}
    cache_set(key, resp)
    return jsonify({**resp, "source": "db", "processed_by": POD_NAME})

# 5. Quiz Success Rate
@app.route("/metrics/quiz/success-rate", methods=["GET"])
def quiz_success_rate():
    key = "quiz_success_rate"
    cached = cache_get(key)
    if cached: return jsonify({**cached, "source": "cache", "processed_by": POD_NAME})

    pipeline = [
        {"$match": {"type": "quiz_submission"}},
        {"$group": {
            "_id": None,
            "total": {"$sum": 1},
            "success": {"$sum": {"$cond": [{"$gte": ["$score", 18]}, 1, 0]}}
        }},
        {"$project": {"_id": 0, "success_rate": {"$cond": [{"$eq": ["$total", 0]}, 0, {"$multiply": [{"$divide": ["$success", "$total"]}, 100]}]}}}
    ]
    result = list(collection.aggregate(pipeline))
    resp = result[0] if result else {"success_rate": 0}
    
    cache_set(key, resp)
    return jsonify({**resp, "source": "db", "processed_by": POD_NAME})

# 6. Activity Trend (LIVE - Usa _ingest_ts)
@app.route("/metrics/activity/last7days", methods=["GET"])
def activity_trend():
    # Usa _ingest_ts aggiunto dal Consumer FIXATO
    since = datetime.utcnow() - timedelta(days=7)
    pipeline = [
        {"$match": {"_ingest_ts": {"$gte": since}}},
        {"$group": {"_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$_ingest_ts"}}, "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}}
    ]
    result = list(collection.aggregate(pipeline))
    return jsonify({"data": result, "source": "live", "processed_by": POD_NAME})

# 7. Avg Score Course (OTTIMIZZATO con $facet)
@app.route("/metrics/quiz/average-score", methods=["GET"])
def avg_score_per_course():
    page = int(request.args.get("page", "1"))
    per_page = int(request.args.get("per_page", "50"))
    skip = (page - 1) * per_page
    key = f"avg_score_p{page}_pp{per_page}"
    
    cached = cache_get(key)
    if cached: return jsonify({**cached, "source": "cache", "processed_by": POD_NAME})

    pipeline = [
        {"$match": {"type": "quiz_submission"}},
        {"$group": {"_id": "$course_id", "average_score": {"$avg": "$score"}}},
        {"$sort": {"average_score": -1}},
        {"$facet": {
            "metadata": [{"$count": "total"}],
            "data": [{"$skip": skip}, {"$limit": per_page}]
        }}
    ]
    
    result = list(collection.aggregate(pipeline))[0]
    total = result["metadata"][0]["total"] if result["metadata"] else 0
    items = [{"course_id": r["_id"], "average_score": r["average_score"]} for r in result["data"]]
    
    resp = {"data": items, "page": page, "per_page": per_page, "total": total}
    cache_set(key, resp)
    return jsonify({**resp, "source": "db", "processed_by": POD_NAME})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)