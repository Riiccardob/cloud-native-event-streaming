# Architettura Cloud-Native Event-Driven: Kong, Kafka e Kubernetes

Questo progetto implementa un'architettura a microservizi distribuita per la gestione di eventi accademici, progettata per soddisfare requisiti stringenti di **Scalabilità**, **Resilienza** e **Sicurezza**. L'infrastruttura combina un API Gateway (Kong) per la governance del traffico e un Message Broker (Kafka) per il disaccoppiamento asincrono, orchestrati interamente su Kubernetes.

## 1\. Architettura del Sistema

Il sistema adotta il pattern **Producer-Consumer** con buffer persistente.

  * **Ingress Layer (Kong Gateway):** Unico punto di accesso che gestisce autenticazione (JWT), limitazione del traffico (Rate Limiting) e routing L7.
  * **Application Layer:**
      * **Producer Service:** API stateless che riceve richieste HTTP e pubblica messaggi su Kafka in modo asincrono per massimizzare il throughput.
      * **Consumer Service:** Worker che processa i messaggi dalla coda garantendo la semantica *At-Least-Once*.
      * **Metrics Service:** API di lettura per l'analisi statistica dei dati.
  * **Data Layer:**
      * **Kafka Cluster (Strimzi):** Broker in High Availability per la persistenza temporanea e l'ordinamento degli eventi.
      * **MongoDB:** Database NoSQL per la persistenza a lungo termine.

-----

## 2\. Proprietà Non Funzionali (NFR) Implementate

Il progetto dimostra il soddisfacimento delle seguenti proprietà critiche:

### A. Performance e Scalabilità

  * **Ottimizzazione Throughput:** Il *Producer* utilizza un meccanismo di invio asincrono con batching (linger 10ms) per disaccoppiare la latenza di rete di Kafka dalla risposta HTTP al client.
  * **Autoscaling Orizzontale (HPA):** I microservizi scalano automaticamente il numero di repliche quando l'utilizzo della CPU supera il 50%.
  * **Load Balancing:** Kong distribuisce il traffico in ingresso tra le repliche disponibili utilizzando l'algoritmo Round Robin.

### B. Affidabilità e Fault Tolerance

  * **Zero Data Loss:** Il *Consumer* disabilita l'auto-commit di Kafka ed effettua il commit manuale dell'offset solo dopo aver ricevuto conferma di scrittura dal database.
  * **Self-Healing:** Kubernetes monitora lo stato dei pod tramite *Liveness Probes* e riavvia automaticamente le istanze non responsive.
  * **Resilienza Asincrona:** L'indisponibilità temporanea del database o del consumer non impatta l'accettazione dei nuovi eventi, che vengono bufferizzati su Kafka.

### C. Sicurezza (Defense in Depth)

  * **Sicurezza Perimetrale:** Autenticazione obbligatoria tramite JWT firmati e protezione da abusi tramite Rate Limiting.
  * **Sicurezza del Canale:** Comunicazione interna criptata (TLS 1.3) e autenticata (SASL/SCRAM) tra microservizi e Kafka.
  * **Isolamento di Rete:** Utilizzo di **Network Policies** (Layer 4) per segregare l'accesso al database, consentendo il traffico solo dai pod autorizzati (`consumer` e `metrics`), mitigando il rischio di movimenti laterali in caso di compromissione.
  * **Gestione Segreti:** Credenziali e certificati sono iniettati a runtime tramite *Kubernetes Secrets*, mai salvati nel codice sorgente.

-----

## 3\. Installazione e Configurazione

Prerequisiti: Minikube (driver Docker), Kubectl, Helm.

### Fase 1: Setup Infrastruttura Base

Avvio del cluster e installazione degli operatori (Strimzi, MongoDB, Kong).

```bash
minikube start --cpus=4 --memory=6144 --driver=docker
eval $(minikube docker-env)

# Namespace
kubectl create namespace kong
kubectl create namespace kafka
kubectl create namespace metrics

# Installazione Chart Helm
helm repo add strimzi https://strimzi.io/charts/
helm install strimzi-cluster-operator strimzi/strimzi-kafka-operator -n kafka

helm repo add bitnami https://charts.bitnami.com/bitnami
helm install mongo-mongodb bitnami/mongodb --namespace kafka --version 18.1.1

helm repo add kong https://charts.konghq.com
helm install kong kong/kong -n kong --set ingressController.installCRDs=false --set ingressController.watchNamespaces="{kong,kafka,metrics}"
```

### Fase 2: Configurazione dei Secrets (Critico)

Questa fase è necessaria per permettere ai microservizi di autenticarsi con Kafka e MongoDB.

**1. Secret CA di Kafka**
Necessario ai client Python per validare il certificato TLS del broker.

```bash
# Attendere che Strimzi completi il deploy del cluster (vedi Fase 3), poi eseguire:
kubectl create secret generic kafka-ca-cert -n kafka \
  --from-literal=ca.crt="$(kubectl get secret uni-it-cluster-cluster-ca-cert -n kafka -o jsonpath='{.data.ca\.crt}' | base64 -d)"
```

**2. Credenziali MongoDB**
Creazione dell'utente applicativo e del relativo Secret.

```bash
# Recupera password di root
MONGO_ROOT_PASSWORD=$(kubectl get secret -n kafka mongo-mongodb -o jsonpath='{.data.mongodb-root-password}' | base64 -d)
MONGO_POD=$(kubectl get pods -n kafka -l app.kubernetes.io/name=mongodb -o jsonpath='{.items[0].metadata.name}')

# Crea utente su Mongo
kubectl exec -it -n kafka $MONGO_POD -- bash -c "mongosh -u root -p $MONGO_ROOT_PASSWORD --authenticationDatabase admin --eval 'db.getSiblingDB(\"student_events\").createUser({user: \"appuser\", pwd: \"appuserpass\", roles: [{role: \"readWrite\", db: \"student_events\"}]})'"

# Crea Secret per l'applicazione
MONGO_URI="mongodb://appuser:appuserpass@mongo-mongodb.kafka.svc.cluster.local:27017/student_events?authSource=student_events"
kubectl create secret generic mongo-creds -n kafka --from-literal=MONGO_URI="$MONGO_URI"
kubectl create secret generic mongo-creds -n metrics --from-literal=MONGO_URI="$MONGO_URI"
```

### Fase 3: Deploy Applicativo

```bash
# 1. Applicare definizioni Kafka (Cluster, Topic, Utenti) e Network Policies
kubectl apply -f k8s/00-infrastructure/kafka-cluster.yaml
kubectl apply -f k8s/00-infrastructure/kafka-topic.yaml
kubectl apply -f k8s/00-infrastructure/users.yaml
# (Assicurarsi di applicare anche la Network Policy se salvata su file, es: kubectl apply -f k8s/01-security/mongo-network-policy.yaml)

# 2. Build Immagini Docker
docker build -t producer:latest ./src/producer
docker build -t consumer:latest ./src/consumer
docker build -t metrics-service:latest ./src/metrics

# 3. Deploy Microservizi
kubectl apply -f k8s/ -R
```

-----

## 4\. API Reference

Il sistema espone due gruppi di API tramite l'Ingress Controller. Tutte le richieste richiedono autenticazione tramite Bearer Token.

**Generazione Token:**

```bash
python3 JWTtoken/gen_jwt.py
```

### A. Producer API (Ingestione Eventi)

Queste API sono esposte dal servizio `producer` e permettono l'invio asincrono degli eventi verso Kafka.

**Base URL:** `http://producer.<MINIKUBE_IP>.nip.io:<KONG_PORT>`
**Auth:** `Authorization: Bearer <TOKEN>`

| Metodo | Endpoint | Payload Richiesto (JSON) | Descrizione |
| :--- | :--- | :--- | :--- |
| `POST` | `/event/login` | `{"user_id": "string"}` | Registra un evento di login utente. |
| `POST` | `/event/quiz` | `{"user_id": "...", "quiz_id": "...", "course_id": "...", "score": int}` | Invia il risultato di un quiz. |
| `POST` | `/event/download` | `{"user_id": "...", "materiale_id": "...", "course_id": "..."}` | Traccia il download di materiale didattico. |
| `POST` | `/event/exam` | `{"user_id": "...", "esame_id": "...", "course_id": "..."}` | Registra la prenotazione di un esame. |

### B. Metrics API (Analisi & Monitoraggio)

Queste API sono esposte dal servizio `metrics-service` ed effettuano aggregazioni in tempo reale sui dati persistiti in MongoDB.

**Base URL:** `http://metrics.<MINIKUBE_IP>.nip.io:<KONG_PORT>`
**Auth:** `Authorization: Bearer <TOKEN>`

| Metodo | Endpoint | Descrizione |
| :--- | :--- | :--- |
| `GET` | `/healthz` | Health check del servizio (Liveness/Readiness Probe). |
| `GET` | `/metrics/logins` | Restituisce il conteggio totale dei login effettuati. |
| `GET` | `/metrics/logins/average` | Calcola la media dei login per singolo utente. |
| `GET` | `/metrics/quiz/success-rate` | Calcola la % di quiz superati (voto \>= 18). |
| `GET` | `/metrics/quiz/average-score` | Restituisce il voto medio raggruppato per corso. |
| `GET` | `/metrics/downloads` | Elenca il numero di download per ogni materiale. |
| `GET` | `/metrics/exams` | Conta le prenotazioni esami raggruppate per corso. |
| `GET` | `/metrics/activity/last7days` | Fornisce l'andamento temporale (istogramma) degli eventi nell'ultima settimana. |

-----

## 5\. Suite di Validazione (Demo)

Il progetto include script automatizzati nella cartella `demo/` per verificare le proprietà non funzionali:

  * `01_security.sh`: Verifica TLS, Autenticazione JWT e gestione Secrets.
  * `02_resilience.sh`: Test di tolleranza ai guasti (Consumer Crash & Recovery).
  * `03_scalability.sh`: Stress test per verificare throughput e Load Balancing.
  * `04_autoscaling.sh`: Generazione carico CPU per triggerare HPA.
  * `05_governance.sh`: Verifica delle policy di Rate Limiting e protezione DoS.

-----

**Autore:** Riccardo Barone
**Corso:** Cloud Computing Technologies