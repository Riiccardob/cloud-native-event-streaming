

Microservizi containerizzati su Kubernetes con Kong come API Gateway, Kafka come message broker e MongoDB per la persistenza.


Producer → Kafka → Consumer → MongoDB → Metrics Service  
Tutti orchestrati via Kubernetes (Minikube o cluster remoto).

![Architecture Diagram](docs/architecture.png)


```bash
# 1. Install dependencies
helm install strimzi oci://quay.io/strimzi-helm/strimzi-kafka-operator -n kafka
helm install kong kong/kong -n kong
helm install mongo bitnami/mongodb -n kafka

# 2. Deploy microservices
kubectl apply -f K8s/
