

Questo progetto dimostra un'architettura a microservizi cloud-native, event-driven e resiliente, orchestrata su Kubernetes. L'obiettivo è tracciare eventi di studenti (login, quiz, download) in modo asincrono, sicuro e scalabile.

Utilizza **Kong** come API Gateway, **Kafka** (tramite Strimzi) come message broker, **MongoDB** come database di persistenza e tre microservizi (Producer, Consumer, Metrics) scritti in Python.


Il flusso degli eventi è il seguente:

```
[Client Esterno (Frontend/cURL)]
      │
      ▼ (via Kong Ingress - L7 Routing)
[Kong API Gateway]
      │
      ├── POST /event/...  →  [Producer Service] (API Flask)
      │                         │
      │                         ▼ (SASL/SSL)
      │                   [Kafka Broker (Topic: student-events)]
      │                         │
      │                         ▼ (SASL/SSL)
      ├── (altro traffico...) → [Consumer Service] (Worker)
      │                         │
      │                         ▼
      │                   [MongoDB (student_events.events)]
      │                         │
      │                         ▼
      └── GET /metrics/... →  [Metrics Service] (API Flask)
```

-----


Questo progetto non è solo un "Hello World", ma implementa pattern avanzati di Kubernetes per un'architettura robusta:

  * **API Gateway (Kong):** Unico punto di ingresso per tutto il traffico. Gestisce il routing L7, il bilanciamento del carico e le policy centralizzate (es. CORS).
  * **Kafka Sicuro (Strimzi):** Cluster Kafka deployato in modo nativo su K8s. Tutto il traffico tra broker e microservizi è protetto da **SASL/SSL** (autenticazione e crittografia).
  * **Microservizi Python:**
      * **Producer:** API Flask "stateless" che riceve eventi HTTP e li produce su Kafka.
      * **Consumer:** Worker che legge da Kafka e scrive in modo persistente su MongoDB.
      * **Metrics:** API Flask "stateless" che legge da MongoDB ed espone aggregati e statistiche.
  * **Best Practice Kubernetes:**
      * **Sicurezza:** Le credenziali (Kafka SASL, Mongo URI) sono gestite tramite **Kubernetes Secrets** e iniettate nei pod, non hardcoded.
      * **Resilienza:** Tutti i microservizi implementano **Liveness & Readiness Probes** (`/healthz`) per il self-healing automatico.
      * **Osservabilità:** La **Downward API** di K8s viene usata per iniettare il nome del pod (`POD_NAME`) nei container. I log e le risposte API includono questo nome, rendendo il load balancing visibile.
      * **Portabilità:** L'uso di **nip.io** per gli Ingress elimina la necessità di configurare `/etc/hosts` locali.
      * **Isolamento:** I componenti sono divisi in namespace logici (`kong`, `kafka`, `metrics`).

-----


Questa guida presuppone l'utilizzo di [Minikube](https://minikube.sigs.k8s.io/docs/start/), `kubectl` e [Helm](https://helm.sh/docs/intro/install/).

### 1\. Setup Ambiente

Inizia con un cluster pulito e configura l'ambiente Docker di Minikube (permettendogli di usare le immagini buildate localmente).

```bash
# Pulisci
minikube delete --all
docker system prune -a -f

# Avvia Minikube
minikube start --cpus=2 --memory=4096 --driver=docker

# Connetti la tua shell al daemon Docker di Minikube
eval $(minikube docker-env)
```

### 2\. Creazione Namespace

```bash
kubectl create namespace kong
kubectl create namespace kafka
kubectl create namespace metrics
```

### 3\. Installazione Infrastruttura (Helm)

Installiamo gli "operatori" che gestiranno i nostri servizi.

```bash
# 1. Strimzi (Kafka Operator)
helm repo add strimzi https://strimzi.io/charts/
helm repo update
helm install strimzi-cluster-operator strimzi/strimzi-kafka-operator -n kafka

# 2. MongoDB
helm repo add bitnami https://charts.bitnami.com/bitnami
helm install mongo-mongodb bitnami/mongodb --namespace kafka --version 18.1.1

# 3. Kong (API Gateway)
helm repo add kong https://charts.konghq.com
helm install kong kong/kong -n kong
```

### 4\. Configurazione Infrastruttura

Ora configuriamo i servizi installati.

```bash
# 1. Abilita Kong a vedere gli altri Namespace
helm upgrade kong kong/kong -n kong \
  --set ingressController.watchNamespaces="{kong,kafka,metrics}"

# 2. Deploya il Cluster Kafka, il Topic e gli Utenti SASL
kubectl apply -f K8s/kafka-cluster.yaml
kubectl apply -f K8s/kafka-topic.yaml
kubectl apply -f K8s/users.yaml # Crea gli utenti SASL

# 3. Crea il Secret per la CA di Kafka (necessario per i pod)
# Attendi che il secret `uni-it-cluster-cluster-ca-cert` sia creato da Strimzi
echo "In attesa dei secret di Strimzi..."
sleep 10 
kubectl create secret generic kafka-ca-cert -n kafka \
  --from-literal=ca.crt="$(kubectl get secret uni-it-cluster-cluster-ca-cert -n kafka -o jsonpath='{.data.ca\.crt}' | base64 -d)"
```

### 5\. Configurazione MongoDB (Utente Applicativo)

Creiamo un utente non-root per i nostri microservizi.

```bash
# 1. Ottieni la password di root di Mongo
MONGO_ROOT_PASSWORD=$(kubectl get secret -n kafka mongo-mongodb -o jsonpath='{.data.mongodb-root-password}' | base64 -d)

# 2. Ottieni il nome del pod Mongo
MONGO_POD=$(kubectl get pods -n kafka -l app.kubernetes.io/name=mongodb -o jsonpath='{.items[0].metadata.name}')

# 3. Esegui il comando `createUser` in mongosh
kubectl exec -it -n kafka $MONGO_POD -- bash -c "
mongosh -u root -p $MONGO_ROOT_PASSWORD --authenticationDatabase admin <<EOF
use student_events
db.createUser({
  user: \"appuser\",
  pwd: \"appuserpass\",
  roles: [ { role: \"readWrite\", db: \"student_events\" } ]
})
EOF
"
```

### 6\. Build Immagini Microservizi

Buildiamo le 3 app Python e le carichiamo nel registry Docker interno di Minikube.

```bash
# Assicurati di essere ancora nell'ambiente Docker di Minikube!
# (se necessario, riesegui: eval $(minikube docker-env))

docker build -t producer:latest ./Producer
docker build -t consumer:latest ./Consumer
docker build -t metrics-service:latest ./Metrics-service
```

### 7\. Deploy Microservizi

```bash
# 1. Crea il Secret per l'URI di MongoDB
MONGO_URI="mongodb://appuser:appuserpass@mongo-mongodb.kafka.svc.cluster.local:27017/student_events?authSource=student_events"

kubectl create secret generic mongo-creds -n kafka \
  --from-literal=MONGO_URI="$MONGO_URI"

kubectl create secret generic mongo-creds -n metrics \
  --from-literal=MONGO_URI="$MONGO_URI"

# 2. Deploya i Microservizi (Deployment e Service)
# (Questi YAML usano i Secret e le Probe)
kubectl apply -f K8s/consumer-deployment.yaml
kubectl apply -f K8s/producer-deployment.yaml
kubectl apply -f K8s/metrics-deployment.yaml

# 3. Deploya gli Ingress e il Plugin CORS
# (Questi espongono i servizi tramite Kong)
kubectl apply -f K8s/kong-cors-plugin.yaml # Abilita il CORS
kubectl apply -f K8s/producer-ingress.yaml
kubectl apply -f K8s/metrics-ingress.yaml
```

L'installazione è completa\!

-----


Per interagire con il sistema, devi trovare l'IP e la porta del proxy Kong.

```bash
# 1. Ottieni l'IP di Minikube
MINIKUBE_IP=$(minikube ip)

# 2. Ottieni la porta del proxy Kong
# (Cerca la porta mappata, es. 3XXXX)
KONG_PORT=$(kubectl get svc -n kong kong-kong-proxy -o jsonpath='{.spec.ports[0].nodePort}')

# 3. Esporta gli URL (es. http://producer.192.168.49.2.nip.io:3XXXX)
export PRODUCER_URL="http://producer.$MINIKUBE_IP.nip.io:$KONG_PORT"
export METRICS_URL="http://metrics.$MINIKUBE_IP.nip.io:$KONG_PORT"

echo "Producer URL: $PRODUCER_URL"
echo "Metrics URL: $METRICS_URL"
```

### 1\. Test tramite Frontend

Apri il file `index.html` (dalla directory `Frontend/`) nel tuo browser. Gli URL del producer e del metrics dovrebbero essere già preimpostati (in caso contrario, copiali dal terminale).

  * Clicca "Dati Random" e "Invia Evento" per inviare dati.
  * Clicca i pulsanti "GET" per interrogare le metriche.
  * Il logger del frontend mostrerà le risposte API, incluso il campo `"processed_by"`.

### 2\. Test tramite cURL (CLI)

Puoi usare i comandi da `utils.txt`:

**Inviare Eventi (Producer):**

```bash
# Login
curl -X POST $PRODUCER_URL/event/login -H "Content-Type: application/json" -d '{"user_id": "alice"}'

# Quiz
curl -X POST $PRODUCER_URL/event/quiz -H "Content-Type: application/json" -d '{"user_id": "bob", "quiz_id": "math101", "score": 24, "course_id": "math"}'
```

**Leggere Metriche (Metrics Service):**

```bash
curl $METRICS_URL/metrics/logins
curl $METRICS_URL/metrics/quiz/success-rate
curl $METRICS_URL/metrics/downloads
```

-----


Questa è la parte più importante del progetto: verificare le NFRs.

### 1\. Scalabilità (Load Balancing)

Il `Producer` è un'API stateless perfetta per la scalabilità orizzontale.

1.  **Scala il producer a 3 repliche:**
    ```bash
    kubectl scale deployment producer -n kafka --replicas=3
    ```
2.  **Guarda i log di tutti i producer:**
    (Apri un nuovo terminale)
    ```bash
    kubectl logs -n kafka -l app=producer -f
    ```
3.  **Invia traffico:**
    Usa il frontend o un loop `curl` per inviare 10-15 eventi.
4.  **Osserva i Log:**
    Vedrai i log (`[PRODUCER @ pod-name]...`) provenire da **nomi di pod diversi**, e il frontend mostrerà `"processed_by"` alternarsi. Questo è il load balancing in azione.

### 2\. Fault Tolerance (Self-Healing)

Dimostriamo che il sistema si auto-ripara grazie alle `Liveness Probes`.

1.  **Trova un pod producer:**
    `kubectl get pods -n kafka -l app=producer`
2.  **Uccidi il pod:**
    `kubectl delete pod <nome-pod-producer> -n kafka`
3.  **Osserva:**
    `kubectl get pods -n kafka -w`
    Il pod passerà a `Terminating` e Kubernetes ne creerà uno nuovo *automaticamente* per rimpiazzarlo. Durante questo tempo, le `Readiness Probes` assicurano che Kong non invii traffico al pod morto o a quello in avvio, garantendo **zero downtime** per l'utente.

### 3\. Fault Tolerance (Buffering Kafka)

Dimostriamo che nessun dato viene perso se il `Consumer` è offline.

1.  **Spegni il consumer:**
    ```bash
    kubectl scale deployment consumer -n kafka --replicas=0
    ```
2.  **Invia eventi:**
    Usa il frontend per inviare 5-10 eventi. Le richieste al `Producer` avranno successo (200 OK), ma i log del consumer (che è spento) sono vuoti. Gli eventi sono ora "in coda" su Kafka.
3.  **Riaccendi il consumer:**
    ```bash
    kubectl scale deployment consumer -n kafka --replicas=1
    ```
4.  **Osserva i log del consumer:**
    `kubectl logs -n kafka -l app=consumer -f`
    Appena il pod parte, vedrai **tutti gli eventi** (inviati mentre era offline) processati in rapida successione. Questo dimostra la resilienza e il disaccoppiamento garantiti da Kafka.

-----


  * **Errore: `{"message":"no Route matched with those values"}`**

      * **Causa:** Stai chiamando Kong, ma l'host (`nip.io`) o il path (`/event`) sono sbagliati.
      * **Soluzione:** Controlla l'URL. Assicurati che l'Ingress (`K8s/producer-ingress.yaml`) sia applicato e che `ingressClassName: kong` sia presente.

  * **Errore: `500 Internal Server Error` (da Producer o Metrics)**

      * **Causa:** Il pod non riesce a connettersi a Mongo o Kafka.
      * **Soluzione:** Controlla i log del pod (`kubectl logs ...`). L'errore più comune è `ServerSelectionTimeoutError` (Mongo non raggiungibile) o un errore SASL (Kafka). Assicurati che i `Secrets` siano stati creati *prima* di deployare i pod.

  * **Errore: `Connection refused` (dal frontend/cURL)**

      * **Causa:** Stai usando la porta sbagliata per Kong.
      * **Soluzione:** Riesegui `kubectl get svc -n kong kong-kong-proxy` e usa la porta `NodePort` (es. `3XXXX`).