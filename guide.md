# Guida Manuale per Dimostrazione Esame Cloud-Native Architecture

## Pre-requisiti e Setup Iniziale

```bash
# 1. Verifica stato cluster
minikube status
kubectl get pods -A

# 2. Recupera configurazione ambiente
export IP=$(minikube ip)
export PORT=$(kubectl get svc -n kong kong-kong-proxy -o jsonpath='{.spec.ports[0].nodePort}')
export BASE_URL="http://producer.$IP.nip.io:$PORT"
export METRICS_URL="http://metrics.$IP.nip.io:$PORT"

# 3. Genera token JWT
cd JWTtoken
export TOKEN=$(python3 gen_jwt.py | tr -d '\r\n')
echo "Token: ${TOKEN:0:30}..."
cd ..
```

---

## FASE 1: TEST FUNZIONALE (Happy Path)

### 1.1 Reset Database
```bash
# Recupera password MongoDB
PASS=$(kubectl get secret -n kafka mongo-mongodb -o jsonpath="{.data.mongodb-root-password}" | base64 -d)

# Svuota collection
kubectl exec -n kafka deployment/mongo-mongodb -- mongosh -u root -p $PASS \
  --authenticationDatabase admin \
  --eval 'db.getSiblingDB("student_events").events.drop()' \
  --quiet
```

### 1.2 Stabilizzazione Ambiente
```bash
# Forza 1 replica per determinismo
kubectl scale deploy/producer -n kafka --replicas=1
kubectl scale deploy/consumer -n kafka --replicas=1

# Attendi rollout
kubectl rollout status deploy/producer -n kafka --timeout=30s
kubectl rollout status deploy/consumer -n kafka --timeout=30s

# Rimuovi HPA e Rate Limiting
kubectl delete hpa --all -n kafka
kubectl delete kongplugin rate-limit -n kafka
```

### 1.3 Generazione Eventi Test
```bash
# UTENTE 1: Mario (Studente Modello)
curl -X POST "$BASE_URL/event/login" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"mario"}'

curl -X POST "$BASE_URL/event/download" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"mario", "materiale_id":"slide-k8s-pdf", "course_id":"cloud"}'

curl -X POST "$BASE_URL/event/quiz" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"mario", "quiz_id":"quiz-1", "course_id":"cloud", "score": 30}'

# UTENTE 2: Luigi (Studente Pigro)
curl -X POST "$BASE_URL/event/login" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"luigi"}'

curl -X POST "$BASE_URL/event/quiz" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"luigi", "quiz_id":"quiz-1", "course_id":"cloud", "score": 18}'

# UTENTE 3: Peach (Pianificatrice)
curl -X POST "$BASE_URL/event/login" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"peach"}'

curl -X POST "$BASE_URL/event/exam" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"peach", "esame_id":"appello-gennaio", "course_id":"cloud"}'

# Attendi flush consumer
sleep 8
```

### 1.4 Verifica Metriche
```bash
# Totale Login (Atteso: 3)
curl -s "$METRICS_URL/metrics/logins" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# Media Login per Utente (Atteso: 1.0)
curl -s "$METRICS_URL/metrics/logins/average" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# Tasso Successo Quiz (Atteso: 100%)
curl -s "$METRICS_URL/metrics/quiz/success-rate" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# Media Voti (Atteso: 24.0)
curl -s "$METRICS_URL/metrics/quiz/average-score" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# Totale Download (Atteso: 1)
curl -s "$METRICS_URL/metrics/downloads" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# Totale Prenotazioni (Atteso: 1)
curl -s "$METRICS_URL/metrics/exams" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

---

## FASE 2: SICUREZZA

### 2.1 Verifica Crittografia TLS
```bash
# Test connessione SSL al broker Kafka
kubectl exec -it -n kafka uni-it-cluster-broker-0 -- \
  openssl s_client -connect uni-it-cluster-kafka-bootstrap.kafka.svc.cluster.local:9093 \
  -brief </dev/null

# Verifica tipo autenticazione utente Kafka
kubectl get kafkauser producer-user -n kafka \
  -o jsonpath='{.spec.authentication.type}'
```

### 2.2 Test Autenticazione JWT

**Test A: Senza Token (Deve fallire con 401)**
```bash
curl -i -X POST "$BASE_URL/event/login" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"hacker"}'
```

**Test B: Con Token Valido (Deve passare)**
```bash
curl -i -X POST "$BASE_URL/event/login" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"authorized_user"}'
```

### 2.3 Verifica Protezione Secrets
```bash
# Ispeziona configurazione env del deployment
kubectl get deploy -n kafka producer -o json | \
  python3 -c "import sys, json; print(json.dumps(json.load(sys.stdin)['spec']['template']['spec']['containers'][0]['env'], indent=2))"

# Verifica runtime injection nel pod
POD=$(kubectl get pod -n kafka -l app=producer -o jsonpath="{.items[0].metadata.name}")
kubectl exec -n kafka $POD -- sh -c 'echo SASL_PASSWORD=$SASL_PASSWORD'
```

---

## FASE 3: RESILIENZA & FAULT TOLERANCE

### 3.1 Scenario: Consumer Down (Durabilità Post-Ingestione)

```bash
# Conta documenti iniziali
PASS=$(kubectl get secret -n kafka mongo-mongodb -o jsonpath="{.data.mongodb-root-password}" | base64 -d)
kubectl exec -n kafka deployment/mongo-mongodb -c mongodb -- \
  mongosh -u root -p $PASS --authenticationDatabase admin \
  --eval 'db.getSiblingDB("student_events").events.countDocuments()' \
  --quiet

# Spegni Consumer
kubectl scale deploy/consumer -n kafka --replicas=0
kubectl wait --for=delete pod -l app=consumer -n kafka --timeout=60s

# Invia 5 messaggi (vanno in Kafka backlog)
for i in {1..5}; do
  curl -s -X POST "$BASE_URL/event/login" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"user_id\":\"offline-msg-$i\"}"
done

# Verifica DB ancora vuoto
kubectl exec -n kafka deployment/mongo-mongodb -c mongodb -- \
  mongosh -u root -p $PASS --authenticationDatabase admin \
  --eval 'db.getSiblingDB("student_events").events.countDocuments()' \
  --quiet

# Ripristina Consumer
kubectl scale deploy/consumer -n kafka --replicas=1
sleep 15

# Verifica dati recuperati (Atteso: 5 documenti)
kubectl exec -n kafka deployment/mongo-mongodb -c mongodb -- \
  mongosh -u root -p $PASS --authenticationDatabase admin \
  --eval 'db.getSiblingDB("student_events").events.find({}, {user_id: 1, _id: 0}).toArray()' \
  --quiet
```

### 3.2 Scenario: Producer HA (Zero Downtime)

```bash
# Scala Producer a 2 repliche
kubectl scale deploy/producer -n kafka --replicas=2
kubectl rollout status deploy/producer -n kafka --timeout=60s

# Identifica pod target
POD_NAME=$(kubectl get pods -n kafka -l app=producer -o jsonpath="{.items[0].metadata.name}")
echo "Target pod: $POD_NAME"

# Avvia traffico in background
(
  for i in {1..20}; do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/event/login" \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d "{\"user_id\": \"ha-check-$i\"}")
    echo "[$(date +%T)] Req $i: HTTP $HTTP_CODE"
    sleep 0.2
  done
) &
BG_PID=$!

# Uccidi pod durante il traffico
sleep 2
kubectl delete pod $POD_NAME -n kafka --grace-period=0 --force

# Attendi completamento traffico
wait $BG_PID

# Cleanup
kubectl scale deploy/producer -n kafka --replicas=1
sleep 10
```

### 3.3 Scenario: Kafka Broker Failover

```bash
# Identifica Leader della partizione 0
LEADER_ID=$(kubectl exec -n kafka uni-it-cluster-broker-0 -- \
  bin/kafka-topics.sh --bootstrap-server localhost:9092 \
  --describe --topic student-events | \
  grep "Partition: 0" | \
  sed -E 's/.*Leader: ([0-9]+).*/\1/')

BROKER_POD="uni-it-cluster-broker-$LEADER_ID"
echo "Leader attuale: $BROKER_POD"

# Conta documenti pre-test
BEFORE=$(kubectl exec -n kafka deployment/mongo-mongodb -c mongodb -- \
  mongosh -u root -p $PASS --authenticationDatabase admin \
  --eval 'db.getSiblingDB("student_events").events.countDocuments()' \
  --quiet | tr -d '\r\n ')

# Avvia invio 30 messaggi in background
(
  for i in {1..30}; do
    curl -s -o /dev/null -X POST "$BASE_URL/event/login" \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d "{\"user_id\":\"ha-kafka-$i\"}"
    sleep 0.5
  done
) &
BG_PID=$!

sleep 3

# Uccidi broker leader
kubectl delete pod $BROKER_POD -n kafka --grace-period=0 --force
echo ">>> BROKER DOWN! Elezione in corso..."

wait $BG_PID
sleep 15

# Verifica dati
AFTER=$(kubectl exec -n kafka deployment/mongo-mongodb -c mongodb -- \
  mongosh -u root -p $PASS --authenticationDatabase admin \
  --eval 'db.getSiblingDB("student_events").events.countDocuments()' \
  --quiet | tr -d '\r\n ')

DELTA=$((AFTER - BEFORE))
echo "Messaggi attesi: 30"
echo "Messaggi ricevuti: $DELTA"

# Mostra stato cluster
kubectl get pods -n kafka -l app.kubernetes.io/name=kafka
```

---

## FASE 4: SCALABILITÀ & LOAD BALANCING

### 4.1 Test Load Balancing (Round Robin)

```bash
# Disattiva HPA per controllo manuale
kubectl delete hpa --all -n kafka

# Scala a 3 repliche
kubectl scale deploy/producer -n kafka --replicas=3
kubectl rollout status deploy/producer -n kafka --timeout=60s
sleep 2

# Verifica endpoints registrati
kubectl get endpoints producer-service -n kafka \
  -o jsonpath='{.subsets[0].addresses[*].ip}' | tr ' ' '\n' | nl

# Invia 9 richieste e osserva distribuzione
for i in {1..9}; do
  RESPONSE=$(curl -s "$BASE_URL/event/login" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"user_id\":\"lb-test-$i\"}")
  
  POD=$(echo $RESPONSE | grep -o '"processed_by":"[^"]*"' | cut -d'"' -f4)
  echo "Req $i -> Pod: $POD"
  sleep 0.2
done
```

### 4.2 Test Throughput (3 Repliche vs 1 Replica)

**Test A: High Scale (3 Repliche)**
```bash
echo "Inizio benchmark 3 repliche..."
time (
  for i in {1..10}; do
    ( for j in {1..50}; do
        curl -s -o /dev/null -X POST "$BASE_URL/event/login" \
          -H "Authorization: Bearer $TOKEN" \
          -H "Content-Type: application/json" \
          -H "Connection: close" \
          -d '{"user_id":"perf"}'
      done ) &
  done
  wait
)
```

**Test B: Low Scale (1 Replica)**
```bash
# Scala down
kubectl scale deploy/producer -n kafka --replicas=1
kubectl rollout status deploy/producer -n kafka
sleep 15

echo "Inizio benchmark 1 replica..."
time (
  for i in {1..10}; do
    ( for j in {1..50}; do
        curl -s -o /dev/null -X POST "$BASE_URL/event/login" \
          -H "Authorization: Bearer $TOKEN" \
          -H "Content-Type: application/json" \
          -H "Connection: close" \
          -d '{"user_id":"perf"}'
      done ) &
  done
  wait
)
```

---

## FASE 5: GOVERNANCE (RATE LIMITING)

### 5.1 Test CON Rate Limiting

```bash
# Rimuovi policy esistenti
kubectl delete kongplugin rate-limit -n kafka

# Applica policy (3 req/sec)
cat <<EOF | kubectl apply -f -
apiVersion: configuration.konghq.com/v1
kind: KongPlugin
metadata:
  name: rate-limit
  namespace: kafka
plugin: rate-limiting
config:
  second: 3
  policy: local
EOF

# Attiva su Ingress
kubectl annotate ingress producer-ingress -n kafka --overwrite \
  konghq.com/plugins="cors-plugin,jwt-auth,rate-limit"

sleep 5

# Flood test (20 richieste rapide)
echo "Esecuzione flood test..."
for i in {1..20}; do
  CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "$BASE_URL/event/login" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"user_id\":\"flood-$i\"}")
  
  TS=$(date +%T)
  if [ "$CODE" == "429" ]; then
    echo "[$TS] Req $i: BLOCKED (429)"
  else
    echo "[$TS] Req $i: OK ($CODE)"
  fi
done
```

### 5.2 Test SENZA Rate Limiting (Verifica)

```bash
# Rimuovi policy
kubectl annotate ingress producer-ingress -n kafka --overwrite \
  konghq.com/plugins="cors-plugin,jwt-auth"
kubectl delete kongplugin rate-limit -n kafka
sleep 5

# Verifica tutte le richieste passano
for i in {1..20}; do
  CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "$BASE_URL/event/login" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"user_id\":\"flood-clean-$i\"}")
  
  echo "Req $i: $CODE"
done
```

---

## FASE 6: SELF-HEALING

### 6.1 Test Readiness Probe (Metrics Service)

```bash
# Stabilizza Metrics
kubectl scale deploy/metrics-service -n metrics --replicas=1
kubectl rollout status deploy/metrics-service -n metrics --timeout=60s

# Cattura pod sano originale
OLD_POD=$(kubectl get pod -n metrics -l app=metrics-service \
  -o jsonpath='{.items[0].metadata.name}')
OLD_IP=$(kubectl get pod -n metrics -l app=metrics-service \
  -o jsonpath='{.items[0].status.podIP}')

echo "Pod stabile: $OLD_POD (IP: $OLD_IP)"

# Mostra endpoints correnti
kubectl get endpoints metrics-service -n metrics

# Deploy versione bacata (MongoDB URI errato)
kubectl set env deployment/metrics-service -n metrics \
  MONGO_URI="mongodb://fake:27017"

sleep 3

# Monitora stato (il nuovo pod deve rimanere 0/1 Ready)
for i in {1..10}; do
  echo "--- Check $i/10 ---"
  kubectl get pods -n metrics -l app=metrics-service \
    -o custom-columns=NAME:.metadata.name,READY:.status.containerStatuses[0].ready,STATUS:.status.phase
  
  kubectl get endpoints metrics-service -n metrics \
    -o jsonpath='{.subsets[*].addresses[*].ip}'
  echo ""
  
  sleep 2
done

# Rollback
kubectl rollout undo deployment/metrics-service -n metrics
kubectl rollout status deploy/metrics-service -n metrics --timeout=60s
```

### 6.2 Test Liveness Probe (Consumer Deadlock Recovery)

```bash
# Setup
kubectl scale deploy/consumer -n kafka --replicas=1
kubectl rollout status deploy/consumer -n kafka --timeout=60s

# Cattura stato iniziale
TARGET_POD=$(kubectl get pod -n kafka -l app=consumer \
  -o jsonpath='{.items[0].metadata.name}')
INIT_RESTARTS=$(kubectl get pod -n kafka $TARGET_POD \
  -o jsonpath='{.status.containerStatuses[0].restartCount}')

echo "Target Pod: $TARGET_POD"
echo "Restarts iniziali: $INIT_RESTARTS"

# Sabotaggio: corrompi heartbeat file
kubectl exec -n kafka $TARGET_POD -- sh -c \
  "rm -rf /tmp/heartbeat && mkdir -p /tmp/heartbeat"

echo "Attesa intervento liveness probe (30-40s)..."

# Monitora restart
START_TIME=$(date +%s)
while true; do
  POD_INFO=$(kubectl get pod -n kafka -l app=consumer \
    -o jsonpath='{.items[0].metadata.name} {.items[0].status.phase} {.items[0].status.containerStatuses[0].restartCount}' \
    2>/dev/null)
  
  read CURR_POD CURR_STATUS CURR_RESTARTS <<< "$POD_INFO"
  
  TS=$(date +%T)
  echo "[$TS] Pod: $CURR_POD | Status: $CURR_STATUS | Restarts: $CURR_RESTARTS"
  
  # Successo se pod ricreato o restart count aumentato
  if [ "$CURR_POD" != "$TARGET_POD" ] || [ "$CURR_RESTARTS" -gt "$INIT_RESTARTS" ]; then
    echo "✅ SUCCESSO: Riavvio rilevato!"
    break
  fi
  
  # Timeout dopo 100s
  ELAPSED=$(($(date +%s) - START_TIME))
  if [ $ELAPSED -gt 100 ]; then
    echo "❌ TIMEOUT: Il pod non si è riavviato"
    break
  fi
  
  sleep 3
done
```

---

## FASE 7: AUTOSCALING (HPA)

```bash
# Cleanup iniziale
kubectl delete hpa --all -n kafka
kubectl annotate ingress producer-ingress -n kafka --overwrite \
  konghq.com/plugins="cors-plugin,jwt-auth"

# Applica HPA
kubectl apply -f k8s/02-apps/hpa.yaml

# Verifica configurazione
kubectl get hpa -n kafka

echo ">>> IMPORTANTE: Apri un secondo terminale e monitora con:"
echo "watch -n 2 'kubectl get hpa -n kafka'"
echo ""
read -p "Premi INVIO quando pronto..."

# Baseline check
kubectl get pods -n kafka -l app=producer -o wide

# Genera carico (4 processi paralleli)
echo "Avvio stress test CPU..."
for i in {1..4}; do
  (while true; do 
     curl -s -o /dev/null -X POST "$BASE_URL/event/login" \
       -H "Authorization: Bearer $TOKEN" \
       -H "Content-Type: application/json" \
       -d '{"user_id":"stress"}' > /dev/null
  done) &
done

echo "Stress test in esecuzione. Osserva l'HPA nel terminale separato."
echo "Quando vedi TARGETS passare da 1/4 a 2/4 o più, premi INVIO"
read

# Stop carico
kill $(jobs -p)
echo "Carico fermato"

# Reset rapido (senza attendere cooldown 5 minuti)
kubectl delete hpa --all -n kafka
kubectl scale deploy/producer -n kafka --replicas=1
kubectl scale deploy/consumer -n kafka --replicas=1

# Attendi shutdown
while [ "$(kubectl get pods -n kafka -l app=producer --no-headers 2>/dev/null | grep -v "Terminating" | wc -l)" -gt 1 ]; do
  echo -n "."
  sleep 2
done
echo ""

kubectl get pods -n kafka -l app=producer -o wide
```

---

## COMANDI UTILI PER DEBUG

```bash
# Logs in tempo reale
kubectl logs -n kafka -l app=producer -f
kubectl logs -n kafka -l app=consumer -f
kubectl logs -n metrics -l app=metrics-service -f

# Verifica connettività MongoDB
kubectl exec -n kafka deployment/mongo-mongodb -c mongodb -- \
  mongosh -u root -p $PASS --authenticationDatabase admin \
  --eval 'db.adminCommand({ping: 1})'

# Ispeziona eventi Kubernetes (per debug probe failures)
kubectl get events -n kafka --sort-by='.lastTimestamp' | tail -20

# Forza rebuild immagini (se modifichi codice)
eval $(minikube docker-env)
docker build -t producer:latest ./src/producer
docker build -t consumer:latest ./src/consumer
docker build -t metrics-service:latest ./src/metrics

# Forza ricreazione pod
kubectl delete pod -n kafka -l app=producer
kubectl delete pod -n kafka -l app=consumer
kubectl delete pod -n metrics -l app=metrics-service

# Reset completo cluster (ATTENZIONE: distrugge tutto)
kubectl delete ns kafka metrics
kubectl delete -f k8s/03-gateway/
minikube delete && minikube start --cpus=4 --memory=6144
```

---

## NOTE FINALI

### Sequenza Raccomandata per l'Esame

1. **Introduzione (2 min)**: Mostra architettura con `docs/img/architecture.svg`
2. **Test Funzionale (5 min)**: FASE 1 completa
3. **Sicurezza (5 min)**: FASE 2 (TLS + JWT + Secrets)
4. **Resilienza (8 min)**: FASE 3.1 + 3.3 (Consumer Down + Kafka Failover)
5. **Scalabilità (5 min)**: FASE 4.1 (Load Balancing visivo)
6. **Governance (3 min)**: FASE 5.1 (Rate Limiting)
7. **Self-Healing (5 min)**: FASE 6.2 (Liveness Probe)

### Tempi Critici da Rispettare

- Consumer flush: **8-10 secondi** dopo invio eventi
- Propagazione policy Kong: **5 secondi** dopo apply
- HPA reaction time: **60-120 secondi** (avvisa il professore!)
- Liveness probe: **30-40 secondi** per triggering

### Comandi di Emergenza

Se qualcosa va storto durante la demo:
```bash
# Reset rapido stato iniziale
kubectl scale deploy/producer -n kafka --replicas=1
kubectl scale deploy/consumer -n kafka --replicas=1
kubectl delete hpa --all -n kafka
kubectl delete kongplugin rate-limit -n kafka

# Pulisci DB senza riavviare tutto
kubectl exec -n kafka deployment/mongo-mongodb -- \
  mongosh -u root -p $PASS --authenticationDatabase admin \
  --eval 'db.getSiblingDB("student_events").events.drop()' --quiet
```