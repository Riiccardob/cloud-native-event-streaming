#!/bin/bash

# --- CONFIGURAZIONE ---
MINIKUBE_IP=$(minikube ip)
KONG_PORT=$(kubectl get svc -n kong kong-kong-proxy -o jsonpath='{.spec.ports[0].nodePort}')

BASE_PRODUCER="http://producer.$MINIKUBE_IP.nip.io:$KONG_PORT"
BASE_METRICS="http://metrics.$MINIKUBE_IP.nip.io:$KONG_PORT"

# --- GENERAZIONE AUTOMATICA TOKEN ---
JWT_SCRIPT="JWTtoken/gen_jwt.py"

if [ ! -f "$JWT_SCRIPT" ]; then
    echo "ERRORE: Non trovo lo script $JWT_SCRIPT"
    echo "Assicurati di essere nella cartella giusta o aggiorna il percorso nello script bash."
    exit 1
fi

echo "Generazione Token JWT in corso..."
# Esegue python, prende l'output e rimuove eventuali spazi/a capo
TOKEN=$(python3 "$JWT_SCRIPT" | tr -d '\r\n')
echo "Token generato: ${TOKEN:0:20}..." # Stampa solo l'inizio per sicurezza

# Colori
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "Target Producer: $BASE_PRODUCER"
echo -e "Target Metrics:  $BASE_METRICS"
echo -e "--------------------------------------------------"

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
    fi

    # Controllo 200 OK o presenza dati JSON
    if [[ "$RESPONSE" == "200" || "$RESPONSE" == *"processed_by"* || "$RESPONSE" == *"status"* ]]; then
        echo -e "${GREEN}OK${NC}"
        if [ "$METHOD" == "GET" ]; then echo "   -> ${RESPONSE:0:100}"; fi
    else
        echo -e "${RED}FAIL ($RESPONSE)${NC}"
    fi
}

# --- TEST ---
echo -e "\n[1] INVIO EVENTI (PRODUCER)..."
call_api "POST" "$BASE_PRODUCER/event/login" '{"user_id": "auto-user-1"}'
call_api "POST" "$BASE_PRODUCER/event/quiz" '{"user_id": "auto-user-1", "quiz_id": "math101", "course_id": "math", "score": 30}'

echo -e "\n[2] ATTESA PROCESAMENTO..."
sleep 3

echo -e "\n[3] LETTURA METRICHE..."
call_api "GET" "$BASE_METRICS/healthz"
call_api "GET" "$BASE_METRICS/metrics/logins"
call_api "GET" "$BASE_METRICS/metrics/quiz/success-rate"