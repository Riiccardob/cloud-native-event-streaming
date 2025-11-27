````markdown
# Architettura Cloud-Native Event-Driven con Kafka e Kong su Kubernetes

Questo repository ospita l'implementazione di un'architettura a microservizi distribuita per la gestione e l'analisi di eventi accademici. Il sistema è progettato per garantire scalabilità, resilienza e sicurezza in ambienti ad alto traffico, integrando un API Gateway (Kong) per la governance e un Message Broker (Kafka) per il disaccoppiamento asincrono.

## Architettura del Sistema

Il sistema adotta il pattern Producer-Consumer con buffer persistente per separare l'ingestione dei dati dalla loro elaborazione.

![Architecture Diagram](docs/img/architecture.svg)

### Componenti Principali

* **Ingress Layer (Kong Gateway):** Unico punto di accesso al cluster. Gestisce l'autenticazione (JWT), la limitazione del traffico (Rate Limiting) e il routing L7 verso i servizi interni.
* **Application Layer:**
    * **Producer Service:** API stateless ottimizzata per l'ingestione ad alto throughput. Utilizza un invio asincrono verso Kafka e una coda locale di fallback per garantire la disponibilità anche in caso di disservizi del broker.
    * **Consumer Service:** Worker che processa i messaggi dalla coda. Implementa logiche di idempotenza (deduplicazione basata su ID evento) e scrittura batch su MongoDB per garantire l'integrità dei dati.
    * **Metrics Service:** API di lettura che espone aggregazioni statistiche in tempo reale.
* **Data Layer:**
    * **Kafka Cluster (Strimzi):** Broker configurato in High Availability per la persistenza temporanea e l'ordinamento degli eventi.
    * **MongoDB:** Database documentale per la persistenza a lungo termine.

---

## Proprietà Non Funzionali

Il progetto soddisfa i seguenti requisiti architetturali critici:

### Performance e Scalabilità
* **Throughput Ottimizzato:** Il Producer disaccoppia la latenza di rete di Kafka dalla risposta HTTP tramite buffering locale, permettendo di gestire picchi di carico elevati senza bloccare i client.
* **Autoscaling:** I microservizi scalano orizzontalmente (HPA) in base all'utilizzo della CPU.
* **Load Balancing:** Kong distribuisce il traffico in ingresso tra le repliche disponibili utilizzando l'algoritmo Round Robin.

### Affidabilità e Fault Tolerance
* **Zero Data Loss:** Il Consumer disabilita l'auto-commit di Kafka ed effettua il commit manuale dell'offset solo dopo aver ricevuto conferma di scrittura dal database.
* **Resilienza:** L'indisponibilità temporanea del database o del consumer non impatta l'accettazione dei nuovi eventi, che vengono bufferizzati su Kafka (Backpressure).

### Sicurezza (Defense in Depth)
* **Sicurezza Perimetrale:** Autenticazione obbligatoria tramite JWT firmati e protezione da abusi tramite Rate Limiting.
* **Sicurezza del Canale:** Comunicazione interna criptata (TLS 1.3) e autenticata (SASL/SCRAM) tra microservizi e Kafka.
* **Isolamento di Rete:** Utilizzo di Network Policies per impedire accessi non autorizzati al Database (solo Consumer e Metrics possono accedere a MongoDB).

---

## Guida all'Installazione

Prerequisiti: Minikube, Kubectl, Helm, Docker.

### 1. Setup Infrastruttura Base

Avviare il cluster e installare gli operatori necessari.

```bash
minikube start --cpus=4 --memory=6144 --driver=docker
eval $(minikube docker-env)

# Installazione Operatori e DB
helm repo add strimzi [https://strimzi.io/charts/](https://strimzi.io/charts/)
helm install strimzi-cluster-operator strimzi/strimzi-kafka-operator -n kafka --create-namespace

helm repo add bitnami [https://charts.bitnami.com/bitnami](https://charts.bitnami.com/bitnami)
helm install mongo-mongodb bitnami/mongodb -n kafka

helm repo add kong [https://charts.konghq.com](https://charts.konghq.com)
helm install kong kong/kong -n kong --create-namespace --set ingressController.installCRDs=false --set ingressController.watchNamespaces="{kong,kafka,metrics}"
````

### 2\. Configurazione dei Secret (Passaggio Critico)

Questa fase è necessaria per generare e iniettare le credenziali di sicurezza nel cluster. Senza questi comandi, i pod non potranno avviarsi.

**A. Certificato CA di Kafka**
Necessario ai client Python per validare il certificato TLS del broker.

```bash
# Attendere che il cluster Kafka sia pronto prima di eseguire
kubectl create secret generic kafka-ca-cert -n kafka \
  --from-literal=ca.crt="$(kubectl get secret uni-it-cluster-cluster-ca-cert -n kafka -o jsonpath='{.data.ca\.crt}' | base64 -d)"
```

**B. Credenziali MongoDB**
Creazione dell'utente applicativo e del relativo Secret.

```bash
# Recupera password di root
MONGO_ROOT_PASSWORD=$(kubectl get secret -n kafka mongo-mongodb -o jsonpath='{.data.mongodb-root-password}' | base64 -d)
MONGO_POD=$(kubectl get pods -n kafka -l app.kubernetes.io/name=mongodb -o jsonpath='{.items[0].metadata.name}')

# Crea utente su Mongo
kubectl exec -it -n kafka $MONGO_POD -- bash -c "mongosh -u root -p $MONGO_ROOT_PASSWORD --authenticationDatabase admin --eval 'db.getSiblingDB(\"student_events\").createUser({user: \"appuser\", pwd: \"appuserpass\", roles: [{role: \"readWrite\", db: \"student_events\"}]})'"

# Crea Secret per l'applicazione nei namespace necessari
MONGO_URI="mongodb://appuser:appuserpass@mongo-mongodb.kafka.svc.cluster.local:27017/student_events?authSource=student_events"

kubectl create secret generic mongo-creds -n kafka --from-literal=MONGO_URI="$MONGO_URI"
kubectl create secret generic mongo-creds -n metrics --from-literal=MONGO_URI="$MONGO_URI"
```

**C. Configurazione JWT**
Creazione del segreto per la validazione dei token.

```bash
# Assicurarsi che il file k8s/01-security/jwt-credential.yaml sia applicato
kubectl apply -f k8s/01-security/jwt-credential.yaml
```

### 3\. Build e Deploy Applicativo

```bash
# Build Immagini Docker
docker build -t producer:latest ./src/producer
docker build -t consumer:latest ./src/consumer
docker build -t metrics-service:latest ./src/metrics

# Deploy Risorse Kubernetes
kubectl create ns metrics
# Assicura la label per la network policy
kubectl label namespace metrics name=metrics --overwrite

kubectl apply -f k8s/00-infrastructure/
kubectl apply -f k8s/01-security/
kubectl apply -f k8s/02-apps/ -R
kubectl apply -f k8s/03-gateway/
```

-----

## API Reference

Il sistema espone le API tramite l'Ingress Controller. Tutte le richieste richiedono un Token JWT valido nell'header.

Specifica Completa: La definizione formale delle interfacce è disponibile nel file docs/openapi.yaml.

**Header Richiesto:**
`Authorization: Bearer <TOKEN>`

Per generare un token valido per i test, utilizzare lo script fornito in `JWTtoken/gen_jwt.py`.

### Ingestion API (Producer)

**Host:** `producer.<MINIKUBE_IP>.nip.io:<KONG_PORT>`

| Metodo | Endpoint | Descrizione |
| :--- | :--- | :--- |
| `POST` | `/event/login` | Registra accesso utente. |
| `POST` | `/event/quiz` | Invia risultato quiz. |
| `POST` | `/event/download` | Traccia download materiale. |
| `POST` | `/event/exam` | Prenotazione esame. |

**Codici di Risposta:**

  * `200 OK`: Evento inviato a Kafka con successo.
  * `202 Accepted`: Evento accodato localmente (Fallback attivo).
  * `503 Service Unavailable`: Coda piena (Backpressure).

### Analytics API (Metrics)

**Host:** `metrics.<MINIKUBE_IP>.nip.io:<KONG_PORT>`

| Metodo | Endpoint | Descrizione |
| :--- | :--- | :--- |
| `GET` | `/metrics/logins` | Totale accessi storici. |
| `GET` | `/metrics/logins/average` | Media login per utente. |
| `GET` | `/metrics/quiz/success-rate` | Tasso successo Quiz (voto \>= 18). |
| `GET` | `/metrics/quiz/average-score` | Voto medio per corso (paginato). |
| `GET` | `/metrics/downloads` | Statistiche download (paginato). |
| `GET` | `/metrics/exams` | Statistiche prenotazioni (paginato). |
| `GET` | `/metrics/activity/last7days` | Trend attività ultima settimana. |
| `GET` | `/healthz` | Health check del servizio. |

-----
```