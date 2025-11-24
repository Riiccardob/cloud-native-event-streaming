from flask import Flask, request, jsonify
from kafka import KafkaProducer
from kafka.errors import NoBrokersAvailable
import json, os, uuid, time
from datetime import datetime

app = Flask(__name__)

# Configurazione Variabili d'Ambiente
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP")
SASL_USERNAME = os.getenv("SASL_USERNAME")
SASL_PASSWORD = os.getenv("SASL_PASSWORD")
KAFKA_CA = os.getenv("KAFKA_CA", "/etc/ssl/certs/kafka/ca.crt")
POD_NAME = os.getenv("POD_NAME", "unknown-pod")
TOPIC = "student-events"

# --- RETRY LOGIC PER KAFKA ---
def get_kafka_producer():
    retries = 0
    while True:
        try:
            print(f"[PRODUCER {POD_NAME}] Tentativo connessione Kafka... ({retries+1})", flush=True)
            producer = KafkaProducer(
                bootstrap_servers=KAFKA_BOOTSTRAP,
                security_protocol="SASL_SSL",
                sasl_mechanism="SCRAM-SHA-512",
                sasl_plain_username=SASL_USERNAME,
                sasl_plain_password=SASL_PASSWORD,
                ssl_cafile=KAFKA_CA,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                # Ottimizzazione: batching per aumentare il throughput
                linger_ms=10,        # Aspetta fino a 10ms per raggruppare messaggi
                batch_size=16384     # Dimensione massima del batch
            )
            print(f"[PRODUCER {POD_NAME}] Connessione Kafka stabilita con successo!", flush=True)
            return producer
        except NoBrokersAvailable:
            retries += 1
            print(f"[PRODUCER {POD_NAME}] Kafka non pronto. Attendo 5 secondi... (Tentativo {retries})", flush=True)
            time.sleep(5)
        except Exception as e:
            print(f"[PRODUCER {POD_NAME}] Errore generico connessione Kafka: {e}. Riprovo tra 5s...", flush=True)
            time.sleep(5)

producer = get_kafka_producer()

# Contatori per monitoraggio locale
event_count = {
    "login": 0,
    "quiz_submission": 0,
    "download_materiale": 0,
    "prenotazione_esame": 0
}

# Callback per loggare errori asincroni (opzionale ma utile)
def on_send_error(ex):
    print(f"[PRODUCER {POD_NAME}] ERRORE asincrono Kafka: {ex}", flush=True)

def produce_event(event_type: str, payload: dict):
    """Crea un evento completo e lo accoda per l'invio"""
    event = {
        "event_id": str(uuid.uuid4()),
        "type": event_type,
        "timestamp": datetime.utcnow().isoformat(),
        **payload
    }
    try:
        producer.send(TOPIC, value=event).add_errback(on_send_error)
        
        event_count[event_type] += 1
        return event
    except Exception as e:
        print(f"[PRODUCER {POD_NAME}] ERRORE immediato invio Kafka: {e}", flush=True)
        raise e

@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"}), 200

# --- ENDPOINTS ---

@app.route("/event/login", methods=["POST"])
def produce_login():
    data = request.json or {}
    required = ["user_id"]
    if not all(k in data for k in required):
        return jsonify({"error": "Missing required field: user_id", "processed_by": POD_NAME}), 400

    event = produce_event("login", {"user_id": data["user_id"]})
    return jsonify({"status": "ok", "event": event, "processed_by": POD_NAME}), 200

@app.route("/event/quiz", methods=["POST"])
def produce_quiz():
    data = request.json or {}
    required = ["user_id", "quiz_id", "course_id", "score"]
    if not all(k in data for k in required):
        return jsonify({"error": f"Missing required fields: {required}", "processed_by": POD_NAME}), 400

    event = produce_event("quiz_submission", {
        "user_id": data["user_id"],
        "quiz_id": data["quiz_id"],
        "course_id": data["course_id"],
        "score": data["score"]
    })
    return jsonify({"status": "ok", "event": event, "processed_by": POD_NAME}), 200

@app.route("/event/download", methods=["POST"])
def produce_download():
    data = request.json or {}
    required = ["user_id", "materiale_id", "course_id"]
    if not all(k in data for k in required):
        return jsonify({"error": f"Missing required fields: {required}", "processed_by": POD_NAME}), 400

    event = produce_event("download_materiale", {
        "user_id": data["user_id"],
        "materiale_id": data["materiale_id"],
        "course_id": data["course_id"]
    })
    return jsonify({"status": "ok", "event": event, "processed_by": POD_NAME}), 200

@app.route("/event/exam", methods=["POST"])
def produce_exam():
    data = request.json or {}
    required = ["user_id", "esame_id", "course_id"]
    if not all(k in data for k in required):
        return jsonify({"error": f"Missing required fields: {required}", "processed_by": POD_NAME}), 400

    event = produce_event("prenotazione_esame", {
        "user_id": data["user_id"],
        "esame_id": data["esame_id"],
        "course_id": data["course_id"]
    })
    return jsonify({"status": "ok", "event": event, "processed_by": POD_NAME}), 200

@app.route("/metrics", methods=["GET"])
def metrics():
    total = sum(event_count.values())
    return jsonify({"events_sent": total, "breakdown": event_count, "processed_by": POD_NAME}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)