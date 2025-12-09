from flask import Flask, request, jsonify
from kafka import KafkaProducer
from kafka.errors import NoBrokersAvailable, KafkaError
import json, os, uuid, time, threading, queue

app = Flask(__name__)

# --- Configurazione (Variabili d'ambiente e default) ---
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP")
SASL_USERNAME = os.getenv("SASL_USERNAME")
SASL_PASSWORD = os.getenv("SASL_PASSWORD")
# Percorso del certificato CA per la connessione sicura a Kafka
KAFKA_CA = os.getenv("KAFKA_CA", "/etc/ssl/certs/kafka/ca.crt")
# Nome del pod corrente, utile per il debug e per vedere il load balancing
POD_NAME = os.getenv("POD_NAME", "unknown-pod")
TOPIC = os.getenv("KAFKA_TOPIC", "student-events")

# Configurazione della coda locale (Fallback)
# Se Kafka è giù, accumula fino a 500 messaggi in RAM prima di rifiutare (Backpressure)
MAX_LOCAL_QUEUE = int(os.getenv("MAX_LOCAL_QUEUE", 500))   # max events to hold locally
# Intervallo in secondi per il thread che prova a svuotare la coda locale verso Kafka
QUEUE_FLUSH_INTERVAL = float(os.getenv("QUEUE_FLUSH_INTERVAL", 3.0))  # 3 secondi

# Coda thread-safe per il buffering locale
local_queue = queue.Queue(maxsize=MAX_LOCAL_QUEUE)
producer = None
# Lock per garantire l'accesso thread-safe all'oggetto producer
producer_lock = threading.Lock()
shutdown_flag = threading.Event()

# Contatori per le metriche interne (monitoraggio stato)
sent_counter = 0
queued_counter = 0
failed_sends = 0
counters_lock = threading.Lock()

# --- Inizializzazione Producer (Tentativo non bloccante) ---
def init_producer():
    global producer
    try:
        # Configurazione del client Kafka con SASL/SCRAM e SSL
        p = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            security_protocol="SASL_SSL" if SASL_USERNAME else "PLAINTEXT",
            sasl_mechanism="SCRAM-SHA-512" if SASL_USERNAME else None,
            sasl_plain_username=SASL_USERNAME if SASL_USERNAME else None,
            sasl_plain_password=SASL_PASSWORD if SASL_USERNAME else None,
            ssl_cafile=KAFKA_CA if SASL_USERNAME else None,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            acks='all',          # Richiede conferma da tutte le repliche (Durabilità)
            retries=5,           # Riprova in caso di errori di rete temporanei
            linger_ms=10,        # Attende 10ms per raggruppare i messaggi (Batching)
            batch_size=16384,
            max_block_ms=1000    # Blocca al massimo 1s se il buffer locale di Kafka è pieno
        )
        with producer_lock:
            producer = p
        print(f"[PRODUCER {POD_NAME}] KafkaProducer initialized.", flush=True)
    except Exception as e:
        with producer_lock:
            producer = None
        print(f"[PRODUCER {POD_NAME}] Kafka init failed: {e}", flush=True)

# Tentativo di connessione all'avvio dell'applicazione
init_producer()

# --- Callback Asincrone ---
def on_send_success(record_metadata):
    global sent_counter
    with counters_lock:
        sent_counter += 1

def on_send_error(ex):
    global failed_sends
    with counters_lock:
        failed_sends += 1
    print(f"[PRODUCER {POD_NAME}] Kafka send error: {ex}", flush=True)

# # --- Thread di Background (Gestione Coda Locale) ---
# def flush_loop():
#     """
#     Thread che gira in background per svuotare la 'local_queue'.
#     Gestisce il reinvio dei messaggi accumulati quando Kafka era irraggiungibile.
#     """
#     global producer, queued_counter
#     while not shutdown_flag.is_set():
#         # Assicura che il producer sia inizializzato
#         with producer_lock:
#             if producer is None:
#                 init_producer()
        
#         # Prova a svuotare la coda messaggio per messaggio
#         while local_queue:
#             event = local_queue[0]  # Legge il primo elemento senza rimuoverlo (Peek)
#             try:
#                 with producer_lock:
#                     if producer is None:
#                         raise NoBrokersAvailable("producer non pronto")
#                     # Invio asincrono
#                     future = producer.send(TOPIC, value=event)
#                     future.add_callback(on_send_success)
#                     future.add_errback(on_send_error)
                
#                 # Se send() non ha dato errori immediati, rimuovo dalla coda locale
#                 local_queue.popleft()
#                 queued_counter = max(0, queued_counter - 1)
#             except NoBrokersAvailable:
#                 # Kafka ancora giù, interrompo il ciclo e riprovo dopo lo sleep
#                 break
#             except KafkaError as e:
#                 # Errore specifico di Kafka, loggho e riprovo
#                 print(f"[PRODUCER {POD_NAME}] Errore Kafka durante flush coda: {e}", flush=True)
#                 time.sleep(0.1)
        
#         # Forza l'invio dei messaggi nel buffer del client Kafka
#         try:
#             with producer_lock:
#                 if producer:
#                     producer.flush(timeout=0.1)
#         except Exception:
#             pass

#         # Attesa prima del prossimo ciclo di controllo
#         time.sleep(QUEUE_FLUSH_INTERVAL)

# --- Thread di Background (Gestione Coda Locale) ---
def flush_loop():
    global producer, queued_counter, failed_sends
    while not shutdown_flag.is_set():
        # Assicura che il producer sia inizializzato
        with producer_lock:
            p = producer
        if p is None:
            init_producer()
            with producer_lock:
                p = producer

        # Prova a svuotare la coda messaggio per messaggio
        while True:
            try:
                event = local_queue.get_nowait()
            except queue.Empty:
                break

            try:
                with producer_lock:
                    if producer is None:
                        raise NoBrokersAvailable("producer not ready")
                    # Invio asincrono
                    future = producer.send(TOPIC, value=event)
                    future.add_callback(on_send_success)
                    future.add_errback(on_send_error)
                
                with counters_lock:
                    queued_counter = max(0, queued_counter - 1)
                
                local_queue.task_done()
            except NoBrokersAvailable:
                # Kafka ancora giù, interrompo il ciclo e riprovo dopo lo sleep
                try:
                    local_queue.put_nowait(event)
                except queue.Full:
                    # Impossibile rimettere in coda, perdo l'evento
                    with counters_lock:
                        failed_sends += 1
                    print(f"[PRODUCER {POD_NAME}] CRITICAL: Lost event during flush, queue full while requeueing", flush=True)
                break
            except KafkaError as e:
                print(f"[PRODUCER {POD_NAME}] KafkaError while flushing queue: {e}", flush=True)
                time.sleep(0.1)

        # Forza l'invio dei messaggi nel buffer del client Kafka
        try:
            with producer_lock:
                if producer:
                    producer.flush(timeout=0.1)
        except Exception:
            pass

        time.sleep(QUEUE_FLUSH_INTERVAL)

# Avvio del thread di flush
flush_thread = threading.Thread(target=flush_loop, daemon=True)
flush_thread.start()

# --- Funzione Core di Invio (Logica Ibrida) ---
def try_send_event(event):
    """
    Try to send via KafkaProducer asynchronously.
    If Kafka is not available, enqueue locally (bounded queue).
    Returns tuple (status, message).
    """
    global producer, queued_counter, failed_sends

    with producer_lock:
        p = producer

    # 1. Prova invio diretto a Kafka
    if p:
        try:
            future = p.send(TOPIC, value=event)
            future.add_callback(on_send_success)
            future.add_errback(on_send_error)
            return ("sent", "event queued to kafka client buffer")
        except (NoBrokersAvailable, KafkaError) as e:
            print(f"[PRODUCER {POD_NAME}] Send error, will enqueue locally: {e}", flush=True)

    # 2. FALLBACK: Coda Locale in RAM
    try:
        local_queue.put_nowait(event)
        with counters_lock:
            global queued_counter
            queued_counter += 1
        return ("queued", f"event enqueued locally ({local_queue.qsize()}/{MAX_LOCAL_QUEUE})")
    except queue.Full:
        with counters_lock:
            global failed_sends
            failed_sends += 1
        # 3. BACKPRESSURE: Coda piena, rifiuto la richiesta
        return ("rejected", "Backpressure active: local queue full, event rejected")

# --- Endpoints ---
#healthcheck completo --> invaliderebbe fallback producer
# @app.route("/healthz")
# def healthz():
#     """
#     Endpoint per le Probes di Kubernetes.
#     Ritorna 503 se Kafka non è connesso, così il pod viene rimosso dal Load Balancer.
#     """
#     with producer_lock:
#         p = producer
#     with counters_lock:
#         sc = sent_counter
#         qc = queued_counter
#         fs = failed_sends

#     status = {
#         "status": "ok" if p else "degraded",
#         "producer_connected": bool(p),
#         "local_queue_len": local_queue.qsize(),
#         "queue_capacity": MAX_LOCAL_QUEUE,
#         "sent_counter": sc,
#         "queued_counter": qc,
#         "failed_sends": fs,
#         "processed_by": POD_NAME
#     }
#     return jsonify(status), 200 if p else 503

@app.route("/healthz")
def healthz():
    """
    Readiness probe: verifica solo che flask sia vivo.
    """
    return jsonify({"status": "ready", "processed_by": POD_NAME}), 200

@app.route("/event/login", methods=["POST"])
def produce_login():
    data = request.json or {}
    required = ["user_id"]
    if not all(k in data for k in required):
        return jsonify({"error": "Missing required field: user_id", "processed_by": POD_NAME}), 400

    eid = data.get("event_id") or str(uuid.uuid4())
    event = {
        "event_id": eid,
        "type": "login",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "user_id": data["user_id"]
    }

    status, msg = try_send_event(event)
    if status == "sent":
        return jsonify({"status": "ok", "event": event, "info": msg, "processed_by": POD_NAME}), 200
    elif status == "queued":
        return jsonify({"status": "accepted", "event": event, "info": msg, "processed_by": POD_NAME}), 202
    else:
        # Qui scatta il Backpressure (503 Service Unavailable)
        return jsonify({"status": "error", "error": msg, "processed_by": POD_NAME}), 503

@app.route("/event/quiz", methods=["POST"])
def produce_quiz():
    data = request.json or {}
    required = ["user_id", "quiz_id", "course_id", "score"]
    if not all(k in data for k in required):
        return jsonify({"error": f"Missing required fields: {required}", "processed_by": POD_NAME}), 400

    event = {
        "event_id": str(uuid.uuid4()),
        "type": "quiz_submission",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "user_id": data["user_id"],
        "quiz_id": data["quiz_id"],
        "course_id": data["course_id"],
        "score": data["score"]
    }

    status, msg = try_send_event(event)
    if status == "sent":
        return jsonify({"status": "ok", "event": event, "info": msg, "processed_by": POD_NAME}), 200
    elif status == "queued":
        return jsonify({"status": "accepted", "event": event, "info": msg, "processed_by": POD_NAME}), 202
    else:
        return jsonify({"status": "error", "error": msg, "processed_by": POD_NAME}), 503
    
@app.route("/event/download", methods=["POST"])
def produce_download():
    data = request.json or {}
    required = ["user_id", "materiale_id", "course_id"]
    if not all(k in data for k in required):
        return jsonify({"error": f"Missing required fields: {required}", "processed_by": POD_NAME}), 400

    event = {
        "event_id": str(uuid.uuid4()),
        "type": "download_materiale",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "user_id": data["user_id"],
        "materiale_id": data["materiale_id"],
        "course_id": data["course_id"]
    }

    status, msg = try_send_event(event)
    if status == "sent":
        return jsonify({"status": "ok", "event": event, "info": msg, "processed_by": POD_NAME}), 200
    elif status == "queued":
        return jsonify({"status": "accepted", "event": event, "info": msg, "processed_by": POD_NAME}), 202
    else:
        return jsonify({"status": "error", "error": msg, "processed_by": POD_NAME}), 503

@app.route("/event/exam", methods=["POST"])
def produce_exam():
    data = request.json or {}
    required = ["user_id", "esame_id", "course_id"]
    if not all(k in data for k in required):
        return jsonify({"error": f"Missing required fields: {required}", "processed_by": POD_NAME}), 400

    event = {
        "event_id": str(uuid.uuid4()),
        "type": "prenotazione_esame",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "user_id": data["user_id"],
        "esame_id": data["esame_id"],
        "course_id": data["course_id"]
    }

    status, msg = try_send_event(event)
    if status == "sent":
        return jsonify({"status": "ok", "event": event, "info": msg, "processed_by": POD_NAME}), 200
    elif status == "queued":
        return jsonify({"status": "accepted", "event": event, "info": msg, "processed_by": POD_NAME}), 202
    else:
        return jsonify({"status": "error", "error": msg, "processed_by": POD_NAME}), 503

@app.route("/metrics", methods=["GET"])
def metrics():
    with counters_lock:
        sc = sent_counter
        qc = queued_counter
        fs = failed_sends
    return jsonify({
        "sent_counter": sc,
        "queued_local": local_queue.qsize(),
        "queue_capacity": MAX_LOCAL_QUEUE,
        "queued_counter": qc,
        "failed_sends": fs,
        "processed_by": POD_NAME
    }), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)