# consumer.py (bulk + idempotency + flush timeout + heartbeat + _ingest_ts)
from kafka import KafkaConsumer
from kafka.errors import NoBrokersAvailable
from pymongo import MongoClient, errors
from pymongo.errors import ServerSelectionTimeoutError
from datetime import datetime, timedelta, timezone
import json, os, time, sys, threading, pathlib

# --- Configurazione Variabili d'Ambiente ---
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP")
SASL_USERNAME = os.getenv("SASL_USERNAME")
SASL_PASSWORD = os.getenv("SASL_PASSWORD")
KAFKA_CA = os.getenv("KAFKA_CA", "/etc/ssl/certs/kafka/ca.crt")
TOPIC = os.getenv("KAFKA_TOPIC", "student-events")
MONGO_URI = os.environ["MONGO_URI"]

# Configurazione del Batching (Bulk Processing)
BUFFER_SIZE = int(os.getenv("CONSUMER_BUFFER_SIZE", "20"))   # flush ogni N eventi
FLUSH_TIMEOUT = int(os.getenv("CONSUMER_FLUSH_TIMEOUT", "5"))  # o flush ogni X secondi

# File di Heartbeat per la Liveness Probe di Kubernetes
HEARTBEAT_FILE = "/tmp/heartbeat"

# --- Connessione Mongo (Retry Loop) ---
def get_mongo_collection():
    retries = 0
    while True:
        try:
            print(f"[CONSUMER] Tentativo connessione MongoDB... ({retries+1})", flush=True)
            client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
            client.admin.command('ping')
            print("[CONSUMER] Connesso a MongoDB!", flush=True)
            return client.student_events.events
        except (ServerSelectionTimeoutError, Exception) as e:
            retries += 1
            print(f"[CONSUMER] MongoDB non pronto ({e}). Attendo 5 secondi...", flush=True)
            time.sleep(5)

# --- Connessione Kafka (Retry Loop) ---
def get_kafka_consumer():
    retries = 0
    while True:
        try:
            print(f"[CONSUMER] Tentativo connessione Kafka... ({retries+1})", flush=True)
            consumer = KafkaConsumer(
                TOPIC,
                bootstrap_servers=KAFKA_BOOTSTRAP,
                security_protocol="SASL_SSL" if SASL_USERNAME else "PLAINTEXT",
                sasl_mechanism="SCRAM-SHA-512" if SASL_USERNAME else None,
                sasl_plain_username=SASL_USERNAME if SASL_USERNAME else None,
                sasl_plain_password=SASL_PASSWORD if SASL_USERNAME else None,
                ssl_cafile=KAFKA_CA if SASL_USERNAME else None,
                auto_offset_reset='earliest',
                group_id='db-consumer-group',
                enable_auto_commit=False,  # relativo a at-least-once
                value_deserializer=lambda v: json.loads(v.decode('utf-8'))
            )
            print("[CONSUMER] Consumer Kafka pronto e sottoscritto!", flush=True)
            return consumer
        except NoBrokersAvailable:
            retries += 1
            print(f"[CONSUMER] Kafka non pronto. Attendo 5 secondi...", flush=True)
            time.sleep(5)
        except Exception as e:
            print(f"[CONSUMER] Errore Kafka generico: {e}. Riprovo tra 5s...", flush=True)
            time.sleep(5)

# --- Setup ---
collection = get_mongo_collection()
consumer = get_kafka_consumer()

# heartbeat loop (per liveness probe)
def heartbeat_loop():
    p = pathlib.Path(HEARTBEAT_FILE)
    while True:
        try:
            # scrivo semplicemente qualcosa per aggiornare il mtime
            p.write_bytes(b"ok")
        except Exception as e:
            print(f"[HEARTBEAT] write failed: {e}", flush=True)
        time.sleep(5)

hb_thread = threading.Thread(target=heartbeat_loop, daemon=True)
hb_thread.start()

# Buffer locale per il Bulk Insert
buffer = []
last_flush = datetime.utcnow()

def log_event(event):
    t = event.get("type")
    u = event.get("user_id")
    eid = event.get("event_id")
    print(f"[PROCESSED] event_id={eid} Type: {t}, User: {u}", flush=True)

def flush_buffer_and_commit():
    """
    Tenta il bulk insert e, se avvenuto con successo, esegue commit.
    """
    global buffer, last_flush
    if not buffer:
        return True

    # Prepara i documenti
    docs = []
    for ev in buffer:
        eid = ev.get("event_id") or ev.get("eventId") or None
        if not eid:
            eid = str(datetime.utcnow().timestamp()) + "-" + (ev.get("user_id","unknown"))
            ev["event_id"] = eid
        # Aggiungi ingest timestamp (utile per metriche)
        ev["_ingest_ts"] = datetime.utcnow().replace(tzinfo=timezone.utc)
        doc = {"_id": eid, **ev}
        docs.append(doc)

    try:
        # Scrittura su DB
        collection.insert_many(docs, ordered=False)

        print(f"[FLUSH] Inseriti {len(docs)} documenti su MongoDB:", flush=True)
        for d in docs:
            print(f"   -> Processed: {d.get('user_id')}", flush=True)

        buffer = []
        last_flush = datetime.utcnow()
        consumer.commit()
        return True
    
    except errors.BulkWriteError as bwe:
        # Gestione Idempotenza: Se ci sono duplicati, Mongo lancia questo errore.
        # i nuovi sono scritti, i doppi scartati
        panic = False
        for err in bwe.details.get('writeErrors', []):
            if err.get('code') != 11000:
                print(f"[FATAL] Errore scrittura non gestito: {err}", flush=True)
                panic = True
        
        if panic:
            print("[CONSUMER] Abort commit a causa di errori gravi DB.", flush=True)
            return False 

        print(f"[WARN] Duplicati gestiti: {bwe.details.get('nInserted')} inseriti", flush=True)
        for d in docs: print(f"   -> Processed (o duplicato): {d.get('user_id')}", flush=True)
        
        buffer = []
        last_flush = datetime.utcnow()
        consumer.commit()
        return True
        
    except Exception as e:
        print(f"[ERROR] Flush fallito: {e}", flush=True)
        return False

# --- Ciclo Principale di Consumo ---
consumer.subscribe([TOPIC])

print(f"[CONSUMER] Iniziato loop di consumo (Polling)...", flush=True)

try:
    while True:
        # 1. POLL: Legge messaggi per 1 secondo (1000ms)
        msg_pack = consumer.poll(timeout_ms=1000)

        for topic_partition, messages in msg_pack.items():
            for message in messages:
                buffer.append(message.value)

        # 2. CONTROLLI DI FLUSH (Eseguiti anche se non arrivano messaggi)
        now = datetime.utcnow()

        buffer_full = len(buffer) >= BUFFER_SIZE
        timeout_reached = (now - last_flush).total_seconds() >= FLUSH_TIMEOUT

        if buffer and (buffer_full or timeout_reached):
            ok = flush_buffer_and_commit()
            if not ok:
                print("[CONSUMER] Flush fallito, riprovo al prossimo giro...", flush=True)
                time.sleep(5)

except KeyboardInterrupt:
    print("Shutdown by user", flush=True)
    # Tenta un ultimo flush prima di chiudere
    flush_buffer_and_commit()
    sys.exit(0)
except Exception as e:
    print(f"[FATAL] {e}", flush=True)
    sys.exit(1)
