$ErrorActionPreference = "Stop"
kubectl -n lakehouse scale deployment trino-coordinator trino-worker --replicas=0
kubectl -n lakehouse scale deployment mysql minio iceberg-rest --replicas=1
kubectl -n lakehouse scale deployment spark-master spark-worker --replicas=1
kubectl -n lakehouse rollout status deployment/mysql --timeout=180s
kubectl -n lakehouse rollout status deployment/minio --timeout=180s
kubectl -n lakehouse rollout status deployment/iceberg-rest --timeout=180s
kubectl -n lakehouse rollout status deployment/spark-master --timeout=180s
kubectl -n lakehouse rollout status deployment/spark-worker --timeout=180s
kubectl -n lakehouse get pods
