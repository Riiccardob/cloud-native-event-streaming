#!/bin/bash

# --- CONFIGURAZIONE ---
MINIKUBE_IP=$(minikube ip)
# Trova la porta di Kong (proxy)
KONG_PORT=$(kubectl get svc -n kong kong-kong-proxy -o jsonpath='{.spec.ports[0].nodePort}')

BASE_PRODUCER="http://producer.$MINIKUBE_IP.nip.io:$KONG_PORT"
BASE_METRICS="http://metrics.$MINIKUBE_IP.nip.io:$KONG_PORT"

# IL TUO NUOVO TOKEN (Scadenza 2025)
TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJleGFtLWNsaWVudC1rZXkiLCJzdWIiOiJlbmVhIiwicm9sZSI6ImV4YW0tY2xpZW50IiwiZXhwIjoxNzYzNjU2NjAwfQ.XdORbJLNoePsoVb3VjfTawFeNOL3fO-U3g4PycQT56s"

# Colori per output
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "Target Producer: $BASE_PRODUCER"
echo -e "Target Metrics:  $BASE_METRICS"
echo -e "--------------------------------------------------"

# Funzione helper per le chiamate
call_api() {
    METHOD=$1
    URL=$2
    DATA=$3
    echo -ne "$METHOD $URL ... "
    
    if [ "$METHOD" == "POST" ]; then
        RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$URL" \
            -H "Content-Type: application/json" \
            -H "Authorization: Bearer $TOKEN" \
            -d "$DATA")
    else
        RESPONSE=$(curl -s -X GET "$URL" -H "Authorization: Bearer $TOKEN")
        HTTP_CODE=$(echo "$RESPONSE" | jq -r '.status // 200') # Fallback per metriche raw
    fi

    # Controllo base sul codice HTTP (o presenza dati)
    if [[ "$RESPONSE" == "200" || "$RESPONSE" == *"processed_by"* ]]; then
        echo -e "${GREEN}OK${NC}"
        if [ "$METHOD" == "GET" ]; then echo "   -> $RESPONSE" | cut -c 1-100; fi # Stampa primi 100 char
    else
        echo -e "${RED}FAIL ($RESPONSE)${NC}"
    fi
}

# --- FASE 1: POPOLAMENTO DATI (PRODUCER) ---
echo -e "\n[1] INVIO EVENTI AL PRODUCER..."

call_api "POST" "$BASE_PRODUCER/event/login" '{"user_id": "test-user-1"}'
call_api "POST" "$BASE_PRODUCER/event/login" '{"user_id": "test-user-2"}'
call_api "POST" "$BASE_PRODUCER/event/quiz" '{"user_id": "test-user-1", "quiz_id": "math101", "course_id": "math", "score": 30}'
call_api "POST" "$BASE_PRODUCER/event/quiz" '{"user_id": "test-user-2", "quiz_id": "math101", "course_id": "math", "score": 18}'
call_api "POST" "$BASE_PRODUCER/event/download" '{"user_id": "test-user-1", "materiale_id": "slide1.pdf", "course_id": "math"}'
call_api "POST" "$BASE_PRODUCER/event/exam" '{"user_id": "test-user-1", "esame_id": "final-math", "course_id": "math"}'

echo -e "\n[2] ATTESA PROCESAMENTO (KAFKA -> CONSUMER -> MONGO)..."
for i in {1..5}; do echo -n "."; sleep 1; done
echo ""

# --- FASE 2: VERIFICA METRICHE (METRICS SERVICE) ---
echo -e "\n[3] LETTURA METRICHE AGGREGATE..."

echo "--- Health Check ---"
call_api "GET" "$BASE_METRICS/healthz"

echo "--- Logins Totali ---"
call_api "GET" "$BASE_METRICS/metrics/logins"

echo "--- Media Logins ---"
call_api "GET" "$BASE_METRICS/metrics/logins/average"

echo "--- Successo Quiz ---"
call_api "GET" "$BASE_METRICS/metrics/quiz/success-rate"

echo "--- Attività ultimi 7gg ---"
call_api "GET" "$BASE_METRICS/metrics/activity/last7days"

echo "--- Punteggio Medio per Corso ---"
call_api "GET" "$BASE_METRICS/metrics/quiz/average-score"

echo "--- Downloads per Materiale ---"
call_api "GET" "$BASE_METRICS/metrics/downloads"

echo "--- Prenotazioni Esami ---"
call_api "GET" "$BASE_METRICS/metrics/exams"

echo -e "\n--------------------------------------------------"
echo "Test Completato."
