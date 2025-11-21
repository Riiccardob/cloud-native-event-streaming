# from kafka import KafkaConsumer
# from pymongo import MongoClient
# from datetime import datetime
# import json, os

# # Configurazione Kafka recuperata dalle variabili d'ambiente
# KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP")
# SASL_USERNAME = os.getenv("SASL_USERNAME")
# SASL_PASSWORD = os.getenv("SASL_PASSWORD")
# # Percorso file CA usato per le connessioni SSL al cluster Kafka
# KAFKA_CA = "/etc/ssl/certs/kafka/ca.crt"
# # Topic Kafka da cui il consumer legge gli eventi
# TOPIC = "student-events"

# # URI di connessione a MongoDB (variabile d'ambiente richiesta)
# MONGO_URI = os.environ["MONGO_URI"]
# # Oggetto client MongoDB e riferimento al database/collection usati
# client = MongoClient(MONGO_URI)
# db = client.student_events
# collection = db.events


# def log_event(event):
#     """Stampa un log leggibile in base al tipo di evento.

#     Parametri:
#     - event: dict che rappresenta l'evento consumato da Kafka

#     Si esamina il campo 'type' e si stampa una riga descrittiva.
#     Non modifica lo stato dell'evento.
#     """
#     t = event.get("type")
#     u = event.get("user_id")
#     match t:
#         case "login":
#             # Evento di login
#             print(f"[LOGIN] Utente {u} ha effettuato l'accesso.", flush=True)
#         case "quiz_submission":
#             # Invio di un quiz con punteggio
#             print(f"[QUIZ] Utente {u} ha inviato quiz {event.get('quiz_id')} con punteggio {event.get('score')}.", flush=True)
#         case "download_materiale":
#             # Download di materiale didattico
#             print(f"[DOWNLOAD] Utente {u} ha scaricato materiale {event.get('materiale_id')}.", flush=True)
#         case "prenotazione_esame":
#             # Prenotazione di un esame
#             print(f"[ESAME] Utente {u} ha prenotato esame {event.get('esame_id')}.", flush=True)
#         case _:
#             # Tipo non riconosciuto
#             print(f"[IGNOTO] Tipo evento non riconosciuto: {t}", flush=True)


# def persist_event(event):
#     """Persistenza dell'evento su MongoDB.

#     Aggiunge un timestamp _ingest_ts con l'orario UTC corrente e inserisce
#     il documento nella collection. Eventuali errori vengono loggati su stdout.
#     """
#     event["_ingest_ts"] = datetime.utcnow()
#     try:
#         collection.insert_one(event)
#     except Exception as e:
#         # In caso di errore con il DB, ne logghiamo l'eccezione
#         print(f"Errore salvataggio DB: {e}", flush=True)


# # Verifica la connessione al server MongoDB prima di partire
# try:
#     client.admin.command('ping')
#     print("Connected to MongoDB")
# except Exception as e:
#     # Se la connessione fallisce, stampiamo l'errore ma non usciamo;
#     # il consumer potrebbe comunque essere avviato in alcune configurazioni.
#     print(f"MongoDB connection error: {e}")


# # Configurazione del consumer Kafka
# consumer = KafkaConsumer(
#     TOPIC,
#     bootstrap_servers=KAFKA_BOOTSTRAP,
#     security_protocol="SASL_SSL",
#     sasl_mechanism="SCRAM-SHA-512",
#     sasl_plain_username=SASL_USERNAME,
#     sasl_plain_password=SASL_PASSWORD,
#     ssl_cafile=KAFKA_CA,
#     # Leggi dal primo offset disponibile se non esiste stato di consumer group
#     auto_offset_reset='earliest',
#     group_id='db-consumer-group',
#     # Deserializza il payload JSON in dict Python
#     value_deserializer=lambda v: json.loads(v.decode('utf-8'))
# )

# print("Consumer avviato, in ascolto su topic:", TOPIC, flush=True)


# # Ciclo principale: per ogni messaggio ricevuto, logghiamo e persistiamo
# for message in consumer:
#     event = message.value
#     log_event(event)
#     persist_event(event)


from kafka import KafkaConsumer
from kafka.errors import NoBrokersAvailable
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError
from datetime import datetime
import json, os, time

# --- CONFIGURAZIONE ---
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP")
SASL_USERNAME = os.getenv("SASL_USERNAME")
SASL_PASSWORD = os.getenv("SASL_PASSWORD")
KAFKA_CA = "/etc/ssl/certs/kafka/ca.crt"
TOPIC = "student-events"
MONGO_URI = os.environ["MONGO_URI"]

# --- RETRY LOGIC PER MONGODB ---
def get_mongo_collection():
    """
    Tenta di connettersi a MongoDB finché non riesce.
    Utile se il pod Mongo si sta riavviando o inizializzando.
    """
    retries = 0
    while True:
        try:
            print(f"[CONSUMER] Tentativo connessione MongoDB... ({retries+1})", flush=True)
            # Imposta un timeout breve per il test di connessione
            client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
            # Comando ping per forzare la verifica della connessione
            client.admin.command('ping')
            print("[CONSUMER] Connesso a MongoDB!", flush=True)
            return client.student_events.events
        except (ServerSelectionTimeoutError, Exception) as e:
            retries += 1
            print(f"[CONSUMER] MongoDB non pronto ({e}). Attendo 5 secondi...", flush=True)
            time.sleep(5)

# --- RETRY LOGIC PER KAFKA ---
def get_kafka_consumer():
    """
    Tenta di connettersi a Kafka finché non riesce.
    """
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
                # Leggi dal primo offset disponibile se non esiste stato di consumer group
                auto_offset_reset='earliest',
                group_id='db-consumer-group',
                # Deserializza il payload JSON in dict Python
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

# --- INIZIALIZZAZIONE RISORSE ---
# Bloccanti: lo script non prosegue finché entrambe le risorse non sono disponibili
collection = get_mongo_collection()
consumer = get_kafka_consumer()


# --- LOGICA DI BUSINESS ---
def log_event(event):
    """Stampa un log leggibile in base al tipo di evento."""
    t = event.get("type")
    u = event.get("user_id")
    match t:
        case "login":
            print(f"[LOGIN] Utente {u} ha effettuato l'accesso.", flush=True)
        case "quiz_submission":
            print(f"[QUIZ] Utente {u} ha inviato quiz {event.get('quiz_id')} con punteggio {event.get('score')}.", flush=True)
        case "download_materiale":
            print(f"[DOWNLOAD] Utente {u} ha scaricato materiale {event.get('materiale_id')}.", flush=True)
        case "prenotazione_esame":
            print(f"[ESAME] Utente {u} ha prenotato esame {event.get('esame_id')}.", flush=True)
        case _:
            print(f"[IGNOTO] Tipo evento non riconosciuto: {t}", flush=True)


def persist_event(event):
    """Persistenza dell'evento su MongoDB."""
    event["_ingest_ts"] = datetime.utcnow()
    try:
        collection.insert_one(event)
    except Exception as e:
        print(f"Errore salvataggio DB: {e}", flush=True)

# --- CICLO PRINCIPALE ---
print(f"[CONSUMER] Iniziato loop di consumo messaggi...", flush=True)
for message in consumer:
    event = message.value
    log_event(event)
    persist_event(event)