# from flask import Flask, request, jsonify
# from kafka import KafkaProducer
# import json, os, uuid
# from datetime import datetime

# app = Flask(__name__)

# KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP")
# SASL_USERNAME = os.getenv("SASL_USERNAME")
# SASL_PASSWORD = os.getenv("SASL_PASSWORD")
# KAFKA_CA = os.getenv("KAFKA_CA", "/etc/ssl/certs/kafka/ca.crt")
# #Legge il nome del pod dalla variabile d'ambiente
# POD_NAME = os.getenv("POD_NAME", "unknown-pod") # "unknown-pod" è un default

# TOPIC = "student-events"

# # Kafka secure producer
# producer = KafkaProducer(
#     bootstrap_servers=KAFKA_BOOTSTRAP,
#     security_protocol="SASL_SSL",
#     sasl_mechanism="SCRAM-SHA-512",
#     sasl_plain_username=SASL_USERNAME,
#     sasl_plain_password=SASL_PASSWORD,
#     ssl_cafile=KAFKA_CA,
#     value_serializer=lambda v: json.dumps(v).encode("utf-8")
# )

# #Contatori per monitoraggio locale
# event_count = {
#     "login": 0,
#     "quiz_submission": 0,
#     "download_materiale": 0,
#     "prenotazione_esame": 0
# }

# def produce_event(event_type: str, payload: dict):
#     """Crea un evento completo e lo invia a Kafka"""
#     event = {
#         "event_id": str(uuid.uuid4()),
#         "type": event_type,
#         "timestamp": datetime.utcnow().isoformat(),
#         **payload
#     }
#     producer.send(TOPIC, value=event)
#     producer.flush()
#     event_count[event_type] += 1
#     print(f"[PRODUCER] Evento inviato: {event_type} -> {event}", flush=True)
#     return event

# @app.route("/healthz")
# def healthz():
#     return jsonify({"status": "ok"}), 200

# #LOGIN EVENT
# @app.route("/event/login", methods=["POST"])
# def produce_login():
#     data = request.json or {}
#     required = ["user_id"]
#     if not all(k in data for k in required):
#         return jsonify({"error": "Missing required field: user_id", "processed_by": POD_NAME}), 400

#     event = produce_event("login", {"user_id": data["user_id"]})
#     return jsonify({"status": "ok", "event": event, "processed_by": POD_NAME}), 200

# #QUIZ SUBMISSION
# @app.route("/event/quiz", methods=["POST"])
# def produce_quiz():
#     data = request.json or {}
#     required = ["user_id", "quiz_id", "course_id", "score"]
#     if not all(k in data for k in required):
#         return jsonify({"error": f"Missing required fields: {required}", "processed_by": POD_NAME}), 400

#     event = produce_event("quiz_submission", {
#         "user_id": data["user_id"],
#         "quiz_id": data["quiz_id"],
#         "course_id": data["course_id"],
#         "score": data["score"]
#     })
#     return jsonify({"status": "ok", "event": event, "processed_by": POD_NAME}), 200

# #DOWNLOAD MATERIALE
# @app.route("/event/download", methods=["POST"])
# def produce_download():
#     data = request.json or {}
#     required = ["user_id", "materiale_id", "course_id"]
#     if not all(k in data for k in required):
#         return jsonify({"error": f"Missing required fields: {required}", "processed_by": POD_NAME}), 400

#     event = produce_event("download_materiale", {
#         "user_id": data["user_id"],
#         "materiale_id": data["materiale_id"],
#         "course_id": data["course_id"]
#     })
#     return jsonify({"status": "ok", "event": event, "processed_by": POD_NAME}), 200

# #PRENOTAZIONE ESAME
# @app.route("/event/exam", methods=["POST"])
# def produce_exam():
#     data = request.json or {}
#     required = ["user_id", "esame_id", "course_id"]
#     if not all(k in data for k in required):
#         return jsonify({"error": f"Missing required fields: {required}", "processed_by": POD_NAME}), 400

#     event = produce_event("prenotazione_esame", {
#         "user_id": data["user_id"],
#         "esame_id": data["esame_id"],
#         "course_id": data["course_id"]
#     })
#     return jsonify({"status": "ok", "event": event, "processed_by": POD_NAME}), 200

# #METRICHE LOCALI
# @app.route("/metrics", methods=["GET"])
# def metrics():
#     total = sum(event_count.values())
#     return jsonify({"events_sent": total, "breakdown": event_count, "processed_by": POD_NAME}), 200

# if __name__ == "__main__":
#     app.run(host="0.0.0.0", port=5000)


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
    """
    Tenta la connessione a Kafka in un loop infinito finché non ha successo.
    Evita che il pod vada in CrashLoopBackOff se Kafka è lento ad avviarsi.
    """
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
                value_serializer=lambda v: json.dumps(v).encode("utf-8")
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

# Inizializzazione globale (blocca l'avvio di Flask finché Kafka non c'è)
producer = get_kafka_producer()

# Contatori per monitoraggio locale
event_count = {
    "login": 0,
    "quiz_submission": 0,
    "download_materiale": 0,
    "prenotazione_esame": 0
}

def produce_event(event_type: str, payload: dict):
    """Crea un evento completo e lo invia a Kafka"""
    event = {
        "event_id": str(uuid.uuid4()),
        "type": event_type,
        "timestamp": datetime.utcnow().isoformat(),
        **payload
    }
    try:
        producer.send(TOPIC, value=event)
        producer.flush()
        event_count[event_type] += 1
        print(f"[PRODUCER {POD_NAME}] Evento inviato: {event_type} -> {event}", flush=True)
        return event
    except Exception as e:
        print(f"[PRODUCER {POD_NAME}] ERRORE invio Kafka: {e}", flush=True)
        raise e

@app.route("/healthz")
def healthz():
    # Se siamo qui, Flask sta girando e Kafka è connesso (teoricamente)
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
    # Avvia il server Flask
    app.run(host="0.0.0.0", port=5000)