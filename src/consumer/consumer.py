from kafka import KafkaConsumer
from kafka.errors import NoBrokersAvailable
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError
from datetime import datetime
import json, os, time, sys

# --- CONFIGURAZIONE ---
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP")
SASL_USERNAME = os.getenv("SASL_USERNAME")
SASL_PASSWORD = os.getenv("SASL_PASSWORD")
KAFKA_CA = "/etc/ssl/certs/kafka/ca.crt"
TOPIC = "student-events"
MONGO_URI = os.environ["MONGO_URI"]

# --- RETRY LOGIC PER MONGODB ---
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

# --- RETRY LOGIC PER KAFKA ---
def get_kafka_consumer():
    retries = 0
    while True:
        try:
            print(f"[CONSUMER] Tentativo connessione Kafka... ({retries+1})", flush=True)
            consumer = KafkaConsumer(
                TOPIC,
                bootstrap_servers=KAFKA_BOOTSTRAP,
                security_protocol="SASL_SSL",
                sasl_mechanism="SCRAM-SHA-512",
                sasl_plain_username=SASL_USERNAME,
                sasl_plain_password=SASL_PASSWORD,
                ssl_cafile=KAFKA_CA,
                auto_offset_reset='earliest',
                group_id='db-consumer-group',
                enable_auto_commit=False,  # <--- FONDAMENTALE PER AT-LEAST-ONCE
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

collection = get_mongo_collection()
consumer = get_kafka_consumer()

def log_event(event):
    t = event.get("type")
    u = event.get("user_id")
    print(f"[PROCESSED] Type: {t}, User: {u}", flush=True)

def persist_event(event):
    """Tenta la scrittura su DB. Se fallisce, solleva eccezione."""
    event["_ingest_ts"] = datetime.utcnow()
    # Se insert_one fallisce, lancia eccezione che verrà catturata nel main loop
    collection.insert_one(event)

# --- CICLO PRINCIPALE ---
print(f"[CONSUMER] Iniziato loop di consumo messaggi...", flush=True)

for message in consumer:
    try:
        event = message.value
        
        # 1. Scrittura su DB
        persist_event(event)
        log_event(event)
        
        # 2. Commit Manuale SOLO se la scrittura è andata a buon fine
        consumer.commit()
        
    except Exception as e:
        print(f"[FATAL ERROR] Impossibile salvare evento: {e}", flush=True)
        print("Il pod verrà terminato per forzare il riavvio e il retry del messaggio.", flush=True)
        # Esce con codice errore. K8s riavvierà il pod. 
        # Kafka  ridarà lo stesso messaggio perché non è stato fatto commit.
        sys.exit(1)