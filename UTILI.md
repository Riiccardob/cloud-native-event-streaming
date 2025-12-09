# Comandi Utili per Demo e Gestione Sistema

## 📋 MONITORAGGIO E STATO

### Pods e Deployments
```bash
# Overview completo tutti i namespace
kubectl get pods -A
kubectl get pods -A -o wide  # con IP e nodi

# Pods specifici per componente
kubectl get pods -n kafka
kubectl get pods -n kafka -l app=producer
kubectl get pods -n kafka -l app=consumer
kubectl get pods -n metrics -l app=metrics-service
kubectl get pods -n kong

# Stato dettagliato con età e restart
kubectl get pods -n kafka -o wide --show-labels

# Watch real-time (aggiornamento automatico)
watch -n 2 'kubectl get pods -n kafka'
watch -n 2 'kubectl get hpa -n kafka'

# Descrizione completa (per debug eventi)
kubectl describe pod -n kafka <pod-name>
kubectl describe pod -n kafka -l app=producer | grep -A10 "Events:"

# Verifica readiness/liveness
kubectl describe pod -n kafka -l app=producer | grep -A5 "Readiness"
kubectl describe pod -n kafka -l app=consumer | grep -A5 "Liveness"
```

### Deployments e Repliche
```bash
# Lista deployments
kubectl get deploy -n kafka
kubectl get deploy -n metrics

# Verifica configurazione repliche
kubectl get deploy -n kafka -o wide

# Stato rollout
kubectl rollout status deploy/producer -n kafka
kubectl rollout status deploy/consumer -n kafka
kubectl rollout status deploy/metrics-service -n metrics

# Storia rollout (per vedere versioni precedenti)
kubectl rollout history deploy/producer -n kafka
```

### Services e Networking
```bash
# Lista services
kubectl get svc -A
kubectl get svc -n kafka
kubectl get svc -n kong

# Verifica endpoints (per vedere IPs dei pod dietro al service)
kubectl get endpoints -n kafka
kubectl get endpoints producer-service -n kafka
kubectl get endpoints producer-service -n kafka -o jsonpath='{.subsets[0].addresses[*].ip}' | tr ' ' '\n'

# Verifica porta Kong (NodePort)
kubectl get svc -n kong kong-kong-proxy -o jsonpath='{.spec.ports[0].nodePort}'

# Ingress configuration
kubectl get ingress -n kafka
kubectl get ingress -n metrics
kubectl describe ingress producer-ingress -n kafka
```

### HPA (Horizontal Pod Autoscaler)
```bash
# Lista HPA
kubectl get hpa -n kafka
kubectl get hpa -n metrics
kubectl get hpa -A

# Watch HPA (per vedere scaling in real-time)
watch -n 2 'kubectl get hpa -n kafka'

# Dettagli HPA (metriche correnti)
kubectl describe hpa producer-hpa -n kafka

# Disabilita HPA temporaneamente
kubectl delete hpa --all -n kafka
kubectl delete hpa producer-hpa -n kafka
```

### Risorse Kafka (Strimzi CRDs)
```bash
# Cluster Kafka
kubectl get kafka -n kafka
kubectl describe kafka uni-it-cluster -n kafka

# Topic
kubectl get kafkatopic -n kafka
kubectl describe kafkatopic student-events -n kafka

# Utenti Kafka
kubectl get kafkauser -n kafka
kubectl get kafkauser producer-user -n kafka -o yaml

# Node pools
kubectl get kafkanodepool -n kafka
```

### Kong Resources
```bash
# Plugin Kong
kubectl get kongplugin -n kafka
kubectl get kongplugin -n metrics
kubectl get kongclusterplugin

# Consumer Kong
kubectl get kongconsumer -n kafka

# Descrizione plugin (per debug configurazione)
kubectl describe kongplugin jwt-auth -n kafka
kubectl describe kongplugin rate-limit -n kafka
```

---

## 📊 LOGS E DEBUG

### Logs in Real-Time
```bash
# Logs base
kubectl logs -n kafka -l app=producer
kubectl logs -n kafka -l app=consumer
kubectl logs -n metrics -l app=metrics-service

# Follow mode (streaming)
kubectl logs -n kafka -l app=producer -f
kubectl logs -n kafka -l app=consumer -f --tail=50

# Logs specifici pod
POD=$(kubectl get pod -n kafka -l app=producer -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n kafka $POD -f

# Logs Kong (container specifico)
kubectl logs -n kong -l app.kubernetes.io/name=kong -f -c proxy

# Logs MongoDB
kubectl logs -n kafka deployment/mongo-mongodb -c mongodb --tail=100

# Logs di tutti i pod di un deployment
kubectl logs -n kafka deployment/producer --tail=20

# Logs precedenti (se pod ha fatto restart)
kubectl logs -n kafka $POD --previous
```

### Eventi Kubernetes
```bash
# Eventi recenti ordinati per timestamp
kubectl get events -n kafka --sort-by='.lastTimestamp'
kubectl get events -n kafka --sort-by='.lastTimestamp' | tail -20

# Eventi specifici per un pod
kubectl get events -n kafka --field-selector involvedObject.name=<pod-name>

# Watch eventi in real-time
kubectl get events -n kafka --watch

# Eventi di warning/errori
kubectl get events -n kafka --field-selector type=Warning
```

### Exec nei Container
```bash
# Shell interattiva
kubectl exec -it -n kafka <pod-name> -- /bin/bash
kubectl exec -it -n kafka <pod-name> -- sh

# Comando singolo
kubectl exec -n kafka <pod-name> -- env
kubectl exec -n kafka <pod-name> -- cat /etc/hosts
kubectl exec -n kafka <pod-name> -- ps aux

# Verifica connettività
kubectl exec -n kafka <pod-name> -- curl http://producer-service:5000/healthz
kubectl exec -n kafka <pod-name> -- nslookup producer-service.kafka.svc.cluster.local

# Kafka broker
kubectl exec -it -n kafka uni-it-cluster-broker-0 -- bash
```

---

## 🔄 GESTIONE E MODIFICA

### Scaling
```bash
# Scale manuale
kubectl scale deploy/producer -n kafka --replicas=3
kubectl scale deploy/consumer -n kafka --replicas=2
kubectl scale deploy/metrics-service -n metrics --replicas=1

# Scale a zero (shutdown completo)
kubectl scale deploy/consumer -n kafka --replicas=0

# Verifica scaling
kubectl get deploy -n kafka
kubectl get pods -n kafka -l app=producer
```

### Rollout e Restart
```bash
# Restart deployment (senza modificare config)
kubectl rollout restart deploy/producer -n kafka
kubectl rollout restart deploy/consumer -n kafka
kubectl rollout restart deploy/metrics-service -n metrics

# Verifica stato rollout
kubectl rollout status deploy/producer -n kafka --timeout=60s

# Rollback a versione precedente
kubectl rollout undo deploy/producer -n kafka

# Rollback a specifica revision
kubectl rollout history deploy/producer -n kafka
kubectl rollout undo deploy/producer -n kafka --to-revision=2

# Pause/Resume rollout
kubectl rollout pause deploy/producer -n kafka
kubectl rollout resume deploy/producer -n kafka
```

### Applicazione Configurazioni
```bash
# Apply singolo file
kubectl apply -f k8s/02-apps/producer-deployment.yaml
kubectl apply -f k8s/02-apps/hpa.yaml

# Apply ricorsivo directory
kubectl apply -f k8s/00-infrastructure/ -R
kubectl apply -f k8s/01-security/
kubectl apply -f k8s/02-apps/
kubectl apply -f k8s/03-gateway/

# Apply con namespace esplicito
kubectl apply -f deployment.yaml -n kafka

# Dry-run (verifica senza applicare)
kubectl apply -f deployment.yaml --dry-run=client
kubectl apply -f deployment.yaml --dry-run=server

# Delete configurazioni
kubectl delete -f k8s/02-apps/hpa.yaml
kubectl delete -f k8s/03-gateway/rate-limit-plugin.yaml
```

### Modifica Configurazioni
```bash
# Edit diretto (apre editor)
kubectl edit deploy/producer -n kafka
kubectl edit kongplugin rate-limit -n kafka

# Patch rapido
kubectl patch deploy/producer -n kafka -p '{"spec":{"replicas":2}}'

# Set environment variable
kubectl set env deploy/producer -n kafka MAX_LOCAL_QUEUE=1000
kubectl set env deploy/metrics-service -n metrics METRICS_CACHE_TTL=30

# Set image (per aggiornare versione)
kubectl set image deploy/producer -n kafka producer=producer:v2

# Annotazioni (per Kong plugins)
kubectl annotate ingress producer-ingress -n kafka --overwrite \
  konghq.com/plugins="cors-plugin,jwt-auth"

kubectl annotate ingress producer-ingress -n kafka --overwrite \
  konghq.com/plugins="cors-plugin,jwt-auth,rate-limit"
```

### Secrets e ConfigMaps
```bash
# Lista secrets
kubectl get secrets -n kafka
kubectl get secrets -n metrics

# Dettagli secret (valori base64)
kubectl get secret producer-user -n kafka -o yaml
kubectl get secret mongo-creds -n kafka -o jsonpath='{.data.MONGO_URI}' | base64 -d

# Crea secret da literal
kubectl create secret generic test-secret -n kafka \
  --from-literal=username=admin \
  --from-literal=password=secret123

# Crea secret da file
kubectl create secret generic kafka-ca-cert -n kafka \
  --from-literal=ca.crt="$(cat ca.crt)"

# Delete secret
kubectl delete secret test-secret -n kafka

# ConfigMaps
kubectl get configmap -n kafka
kubectl describe configmap <name> -n kafka
```

---

## 🐳 DOCKER E BUILD

### Build Immagini
```bash
# Setup Docker per Minikube (IMPORTANTE!)
eval $(minikube docker-env)

# Verifica sei nel context corretto
docker images | grep producer

# Build singola immagine
docker build -t producer:latest ./src/producer
docker build -t consumer:latest ./src/consumer
docker build -t metrics-service:latest ./src/metrics

# Build con tag versioning
docker build -t producer:v1.0 ./src/producer
docker build -t producer:v1.1 ./src/producer

# Build senza cache (per forzare rebuild completo)
docker build --no-cache -t producer:latest ./src/producer

# Build con context specifico
docker build -t producer:latest -f ./src/producer/Dockerfile ./src/producer

# Verifica immagini disponibili
docker images
docker images | grep -E 'producer|consumer|metrics'
```

### Pulizia e Manutenzione Docker
```bash
# Rimuovi immagini inutilizzate
docker image prune -a

# Rimuovi container stoppati
docker container prune

# Pulizia completa (ATTENZIONE!)
docker system prune -a --volumes

# Spazio utilizzato
docker system df
```

### Workflow Completo Rebuild
```bash
# 1. Setup environment
eval $(minikube docker-env)

# 2. Build tutte le immagini
docker build -t producer:latest ./src/producer
docker build -t consumer:latest ./src/consumer
docker build -t metrics-service:latest ./src/metrics

# 3. Forza ricreazione pod (o rollout restart)
kubectl delete pod -n kafka -l app=producer
kubectl delete pod -n kafka -l app=consumer
kubectl delete pod -n metrics -l app=metrics-service

# Oppure rollout restart
kubectl rollout restart deploy/producer -n kafka
kubectl rollout restart deploy/consumer -n kafka
kubectl rollout restart deploy/metrics-service -n metrics

# 4. Verifica pod nuovi siano up
kubectl get pods -n kafka
kubectl get pods -n metrics
```

---

## 🌐 CURL E TEST API

### Setup Variabili
```bash
# Configurazione ambiente
export IP=$(minikube ip)
export PORT=$(kubectl get svc -n kong kong-kong-proxy -o jsonpath='{.spec.ports[0].nodePort}')
export BASE_URL="http://producer.$IP.nip.io:$PORT"
export METRICS_URL="http://metrics.$IP.nip.io:$PORT"

# Genera token JWT
cd JWTtoken
export TOKEN=$(python3 gen_jwt.py | tr -d '\r\n')
echo "Token: ${TOKEN:0:30}..."
cd ..

# Verifica variabili
echo "IP: $IP"
echo "PORT: $PORT"
echo "BASE_URL: $BASE_URL"
echo "TOKEN: ${TOKEN:0:30}..."
```

### Producer API - Eventi
```bash
# Login event
curl -X POST "$BASE_URL/event/login" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "alice"}'

# Quiz submission
curl -X POST "$BASE_URL/event/quiz" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "alice", "quiz_id": "math101", "course_id": "math", "score": 28}'

# Download materiale
curl -X POST "$BASE_URL/event/download" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "alice", "materiale_id": "slide-k8s", "course_id": "cloud"}'

# Prenotazione esame
curl -X POST "$BASE_URL/event/exam" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "alice", "esame_id": "appello-gen", "course_id": "cloud"}'

# Health check Producer
curl "$BASE_URL/healthz" \
  -H "Authorization: Bearer $TOKEN"
```

### Producer API - Batch Invii
```bash
# Loop semplice (10 utenti)
for i in {1..10}; do
  curl -s -X POST "$BASE_URL/event/login" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"user_id\": \"user-$i\"}"
done

# Loop con output status code
for i in {1..20}; do
  CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "$BASE_URL/event/login" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"user_id\": \"user-$i\"}")
  echo "Request $i: HTTP $CODE"
done

# Parallel requests (load test)
for i in {1..10}; do
  (for j in {1..50}; do
    curl -s -o /dev/null -X POST "$BASE_URL/event/login" \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"user_id":"stress"}'
  done) &
done
wait
```

### Metrics API
```bash
# Health check
curl -s "$METRICS_URL/healthz" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# Totale login
curl -s "$METRICS_URL/metrics/logins" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# Media login per utente
curl -s "$METRICS_URL/metrics/logins/average" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# Success rate quiz
curl -s "$METRICS_URL/metrics/quiz/success-rate" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# Media voti per corso (paginato)
curl -s "$METRICS_URL/metrics/quiz/average-score?page=1&per_page=10" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# Download statistics
curl -s "$METRICS_URL/metrics/downloads?page=1&per_page=50" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# Prenotazioni esami
curl -s "$METRICS_URL/metrics/exams" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# Activity trend ultimi 7 giorni
curl -s "$METRICS_URL/metrics/activity/last7days" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

### CURL Advanced
```bash
# Mostra headers completi (include Kong rate limit info)
curl -i -X POST "$BASE_URL/event/login" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"test"}'

# Verbose output (per debug TLS, DNS, ecc)
curl -v -X POST "$BASE_URL/event/login" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"test"}'

# Solo headers response
curl -s -o /dev/null -w "%{http_code}\n" "$BASE_URL/healthz" \
  -H "Authorization: Bearer $TOKEN"

# Timing della request
curl -w "@-" -o /dev/null -s "$BASE_URL/event/login" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"perf"}' <<'EOF'
    time_namelookup:  %{time_namelookup}\n
       time_connect:  %{time_connect}\n
    time_appconnect:  %{time_appconnect}\n
   time_pretransfer:  %{time_pretransfer}\n
      time_redirect:  %{time_redirect}\n
 time_starttransfer:  %{time_starttransfer}\n
                    ----------\n
         time_total:  %{time_total}\n
EOF

# Test senza autenticazione (deve fallire 401)
curl -i -X POST "$BASE_URL/event/login" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"hacker"}'

# Test con token invalido
curl -i -X POST "$BASE_URL/event/login" \
  -H "Authorization: Bearer invalid-token-here" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"hacker"}'
```

---

## 💾 MONGODB

### Accesso MongoDB
```bash
# Password MongoDB
PASS=$(kubectl get secret -n kafka mongo-mongodb -o jsonpath="{.data.mongodb-root-password}" | base64 -d)
echo "MongoDB Password: $PASS"

# Shell interattiva MongoDB
kubectl exec -it -n kafka deployment/mongo-mongodb -c mongodb -- \
  mongosh -u root -p $PASS --authenticationDatabase admin

# Comandi singoli
kubectl exec -n kafka deployment/mongo-mongodb -c mongodb -- \
  mongosh -u root -p $PASS --authenticationDatabase admin \
  --eval 'db.adminCommand({ping: 1})'
```

### Query MongoDB
```bash
# Conta documenti
kubectl exec -n kafka deployment/mongo-mongodb -c mongodb -- \
  mongosh -u root -p $PASS --authenticationDatabase admin \
  --eval 'db.getSiblingDB("student_events").events.countDocuments()' \
  --quiet

# Lista tutti i documenti (con formato)
kubectl exec -n kafka deployment/mongo-mongodb -c mongodb -- \
  mongosh -u root -p $PASS --authenticationDatabase admin \
  --eval 'db.getSiblingDB("student_events").events.find().toArray()' \
  --quiet | python3 -m json.tool

# Solo user_id
kubectl exec -n kafka deployment/mongo-mongodb -c mongodb -- \
  mongosh -u root -p $PASS --authenticationDatabase admin \
  --eval 'db.getSiblingDB("student_events").events.find({}, {user_id: 1, _id: 0}).toArray()' \
  --quiet

# Filtra per tipo evento
kubectl exec -n kafka deployment/mongo-mongodb -c mongodb -- \
  mongosh -u root -p $PASS --authenticationDatabase admin \
  --eval 'db.getSiblingDB("student_events").events.find({type: "login"}).toArray()' \
  --quiet

# Conta per tipo
kubectl exec -n kafka deployment/mongo-mongodb -c mongodb -- \
  mongosh -u root -p $PASS --authenticationDatabase admin \
  --eval 'db.getSiblingDB("student_events").events.aggregate([{$group: {_id: "$type", count: {$sum: 1}}}])' \
  --quiet

# Drop collection (reset completo)
kubectl exec -n kafka deployment/mongo-mongodb -c mongodb -- \
  mongosh -u root -p $PASS --authenticationDatabase admin \
  --eval 'db.getSiblingDB("student_events").events.drop()' \
  --quiet

# Verifica indici
kubectl exec -n kafka deployment/mongo-mongodb -c mongodb -- \
  mongosh -u root -p $PASS --authenticationDatabase admin \
  --eval 'db.getSiblingDB("student_events").events.getIndexes()' \
  --quiet
```

---

## 🔧 TROUBLESHOOTING E FIX RAPIDI

### Reset Rapido Sistema
```bash
# Reset completo stato iniziale
kubectl scale deploy/producer -n kafka --replicas=1
kubectl scale deploy/consumer -n kafka --replicas=1
kubectl scale deploy/metrics-service -n metrics --replicas=1
kubectl delete hpa --all -n kafka
kubectl delete hpa --all -n metrics
kubectl delete kongplugin rate-limit -n kafka

# Pulisci DB
PASS=$(kubectl get secret -n kafka mongo-mongodb -o jsonpath="{.data.mongodb-root-password}" | base64 -d)
kubectl exec -n kafka deployment/mongo-mongodb -c mongodb -- \
  mongosh -u root -p $PASS --authenticationDatabase admin \
  --eval 'db.getSiblingDB("student_events").events.drop()' \
  --quiet

# Verifica tutto pulito
kubectl get pods -n kafka
kubectl get hpa -n kafka
```

### Fix Pod Crashati
```bash
# Identifica pod problematici
kubectl get pods -n kafka | grep -E 'Error|CrashLoopBackOff'

# Describe per vedere errori
kubectl describe pod -n kafka <pod-name> | tail -30

# Logs del pod crashato (previous container)
kubectl logs -n kafka <pod-name> --previous

# Force delete pod stuck
kubectl delete pod <pod-name> -n kafka --grace-period=0 --force

# Ricrea deployment da zero
kubectl delete deploy/producer -n kafka
kubectl apply -f k8s/02-apps/producer-deployment.yaml
```

### Fix Network Issues
```bash
# Test connettività DNS interna
kubectl run test-dns --image=busybox --rm -it -- \
  nslookup producer-service.kafka.svc.cluster.local

# Test connettività HTTP interna
kubectl run test-http --image=curlimages/curl --rm -it -- \
  curl http://producer-service.kafka.svc.cluster.local:5000/healthz

# Verifica Network Policies
kubectl get networkpolicy -A
kubectl describe networkpolicy allow-mongo-access -n kafka

# Test connettività MongoDB
kubectl run test-mongo --image=mongo:latest --rm -it -- \
  mongosh mongodb://mongo-mongodb.kafka.svc.cluster.local:27017
```

### Fix Kong Issues
```bash
# Restart Kong
kubectl rollout restart deploy/kong-kong -n kong

# Verifica configurazione Kong
kubectl get kongplugin -A
kubectl get kongconsumer -A
kubectl get ingress -A

# Logs Kong dettagliati
kubectl logs -n kong -l app.kubernetes.io/name=kong -c proxy --tail=100

# Test Kong health
curl http://$IP:$PORT/status
```

### Fix Kafka Issues
```bash
# Verifica stato cluster
kubectl get kafka -n kafka
kubectl get kafkanodepool -n kafka

# Logs broker
kubectl logs -n kafka uni-it-cluster-broker-0 --tail=100

# Verifica topic
kubectl exec -n kafka uni-it-cluster-broker-0 -- \
  bin/kafka-topics.sh --bootstrap-server localhost:9092 --list

kubectl exec -n kafka uni-it-cluster-broker-0 -- \
  bin/kafka-topics.sh --bootstrap-server localhost:9092 \
  --describe --topic student-events

# Verifica consumer group
kubectl exec -n kafka uni-it-cluster-broker-0 -- \
  bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --list

kubectl exec -n kafka uni-it-cluster-broker-0 -- \
  bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 \
  --describe --group db-consumer-group

# Reset consumer group offset (ATTENZIONE!)
kubectl exec -n kafka uni-it-cluster-broker-0 -- \
  bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 \
  --group db-consumer-group --reset-offsets --to-earliest \
  --topic student-events --execute
```

---

## 🎯 MINIKUBE

### Gestione Cluster
```bash
# Stato Minikube
minikube status

# Start/Stop
minikube start --cpus=4 --memory=6144 --driver=docker
minikube stop
minikube pause
minikube unpause

# IP cluster
minikube ip

# Dashboard Kubernetes
minikube dashboard

# SSH nel nodo
minikube ssh

# Logs Minikube
minikube logs

# Delete cluster
minikube delete
```

### Addons
```bash
# Lista addons
minikube addons list

# Abilita metrics-server (per HPA)
minikube addons enable metrics-server

# Abilita dashboard
minikube addons enable dashboard
```

### Docker Environment
```bash
# Setup docker per usare Minikube registry
eval $(minikube docker-env)

# Verifica
docker ps

# Reset (torna a Docker locale)
eval $(minikube docker-env -u)
```

---

## 📦 NAMESPACE

```bash
# Lista namespace
kubectl get ns

# Crea namespace
kubectl create ns test

# Delete namespace (ATTENZIONE: elimina tutto dentro!)
kubectl delete ns test

# Set default namespace per comandi kubectl
kubectl config set-context --current --namespace=kafka

# Verifica namespace corrente
kubectl config view --minify | grep namespace:
```

---

## 🎨 OUTPUT FORMATTING

```bash
# JSON output
kubectl get pods -n kafka -o json
kubectl get deploy/producer -n kafka -o json | jq .

# YAML output
kubectl get deploy/producer -n kafka -o yaml

# JSONPath (estrazione campi specifici)
kubectl get pods -n kafka -o jsonpath='{.items[*].metadata.name}'
kubectl get pods -n kafka -o jsonpath='{.items[*].status.podIP}'

# Custom columns
kubectl get pods -n kafka -o custom-columns=NAME:.metadata.name,STATUS:.status.phase,IP:.status.podIP

# Wide output
kubectl get pods -n kafka -o wide

# Nome + età
kubectl get pods -n kafka -o custom-columns=NAME:.metadata.name,AGE:.metadata.creationTimestamp

# Sort by
kubectl get pods -n kafka --sort-by=.metadata.creationTimestamp

# Labels
kubectl get pods -n kafka --show-labels
kubectl get pods -n kafka -L app,version
```

---

## 🚀 ONE-LINERS UTILI

```bash
# Restart tutti i pod di un deployment veloce
kubectl delete pod -n kafka -l app=producer

# Conta pod running
kubectl get pods -n kafka --field-selector=status.phase=Running --no-headers | wc -l

# Trova pod con più restart
kubectl get pods -n kafka --sort-by='.status.containerStatuses[0].restartCount'

# Tutti i pod non Running
kubectl get pods -A --field-selector=status.phase!=Running

# IP di tutti i pod Producer
kubectl get pods -n kafka -l app=producer -o jsonpath='{.items[*].status.podIP}'

# Elimina tutti i pod Evicted/Failed
kubectl get pods -n kafka | grep Evicted | awk '{print $1}' | xargs kubectl delete pod -n kafka

# Forza ricreazione di tutti i deployment in un namespace
kubectl get deploy -n kafka -o name | xargs -n 1 kubectl rollout restart -n kafka

# Watch multiplo (in terminal separati)
watch -n 2 'kubectl get pods -n kafka'
watch -n 2 'kubectl get hpa -n kafka'

# Statistiche risorse pod
kubectl top pods -n kafka
kubectl top nodes

# Eventi ultimi 5 minuti
kubectl get events -n kafka --sort-by='.lastTimestamp' | \
  awk -v d="$(date -u -d '5 minutes ago' +%Y-%m-%dT%H:%M:%S)" '$1>=d'
```