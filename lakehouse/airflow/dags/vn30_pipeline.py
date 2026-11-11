"""VN30 annual-report pipeline: Raw (MinIO) -> Bronze -> Silver -> Gold (Iceberg) -> quality gate -> Trino check.

  1. vn30_bronze   Spark: s3a://raw/vn30/extract/* -> vn30_bronze.pages_raw / extracted_raw / cafef_raw
  2. vn30_silver   Spark: CafeF cross-check (per ticker), ROE/ROA, text chunks, dimensions -> vn30_silver.*
  3. vn30_gold     Spark SQL: company_year_metrics, data_quality_by_ticker -> vn30_gold.*
  4. vn30_check    Spark: row counts must equal the single-machine baseline, otherwise the run fails
  5. verify_with_trino  Trino: row counts of every table (proves the tables are queryable through Trino)

Trigger by hand (Airflow UI -> vn30_pipeline -> Trigger). Each step runs as its own Kubernetes pod.
Requires spark-master, spark-worker and trino (scripts/ops/mode-full.ps1) and the files uploaded by
scripts/data/upload-vn30.ps1. The Spark jobs are mounted from ConfigMap spark-jobs (scripts/dev/sync-airflow.ps1).
"""
from datetime import timedelta

import pendulum
from airflow import DAG
from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from kubernetes.client import models as k8s

NAMESPACE = "lakehouse"
SPARK_IMAGE = "lakehouse/spark-iceberg:1.0"  # built from spark/Dockerfile (Iceberg runtime + s3a jars inside)
TRINO_IMAGE = "trinodb/trino:475"

VOLUMES = [k8s.V1Volume(name="jobs", config_map=k8s.V1ConfigMapVolumeSource(name="spark-jobs"))]
VOLUME_MOUNTS = [k8s.V1VolumeMount(name="jobs", mount_path="/jobs")]

SPARK_SUBMIT = r"""set -e
/opt/spark/bin/spark-submit \
  --master spark://spark-master:7077 \
  --driver-memory 512m \
  --executor-memory 512m \
  --total-executor-cores 1 \
  --conf spark.driver.host=$(hostname -i) \
  --conf spark.hadoop.fs.s3a.impl=org.apache.hadoop.fs.s3a.S3AFileSystem \
  --conf spark.hadoop.fs.s3a.endpoint=http://minio:9000 \
  --conf spark.hadoop.fs.s3a.access.key=admin \
  --conf spark.hadoop.fs.s3a.secret.key=password123 \
  --conf spark.hadoop.fs.s3a.path.style.access=true \
  --conf spark.hadoop.fs.s3a.connection.ssl.enabled=false \
  --conf spark.sql.extensions=org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions \
  --conf spark.sql.catalog.lakehouse=org.apache.iceberg.spark.SparkCatalog \
  --conf spark.sql.catalog.lakehouse.type=rest \
  --conf spark.sql.catalog.lakehouse.uri=http://iceberg-rest:8181 \
  --conf spark.sql.catalog.lakehouse.warehouse=s3://warehouse/ \
  --conf spark.sql.defaultCatalog=lakehouse \
  --conf spark.sql.catalog.lakehouse.io-impl=org.apache.iceberg.aws.s3.S3FileIO \
  --conf spark.sql.catalog.lakehouse.s3.endpoint=http://minio:9000 \
  --conf spark.sql.catalog.lakehouse.s3.path-style-access=true \
  /jobs/__SCRIPT__
"""

SPARK_ENV = [
    k8s.V1EnvVar(name="AWS_REGION", value="us-east-1"),
    k8s.V1EnvVar(name="AWS_ACCESS_KEY_ID", value="admin"),
    k8s.V1EnvVar(name="AWS_SECRET_ACCESS_KEY", value="password123"),
]

COMMON = dict(
    namespace=NAMESPACE,
    in_cluster=True,
    get_logs=True,
    on_finish_action="delete_succeeded_pod",  # a failed pod is kept for debugging
    startup_timeout_seconds=900,
    retries=1,
    retry_delay=timedelta(minutes=2),
    execution_timeout=timedelta(hours=1),
    labels={"managed-by": "airflow"},
)


def spark_task(task_id, script):
    return KubernetesPodOperator(
        task_id=task_id,
        name=task_id.replace("_", "-"),
        image=SPARK_IMAGE,
        image_pull_policy="Never",  # loaded into the nodes by scripts/dev/build-spark.ps1
        cmds=["/bin/sh", "-c"],
        arguments=[SPARK_SUBMIT.replace("__SCRIPT__", script)],
        volumes=VOLUMES,
        volume_mounts=VOLUME_MOUNTS,
        env_vars=SPARK_ENV,
        container_resources=k8s.V1ResourceRequirements(
            requests={"cpu": "100m", "memory": "512Mi"},
            limits={"memory": "1Gi"},
        ),
        **COMMON,
    )


with DAG(
    dag_id="vn30_pipeline",
    description="VN30 annual reports: Raw -> Bronze -> Silver -> Gold (Iceberg on MinIO), checked through Trino",
    schedule=None,  # manual trigger
    start_date=pendulum.datetime(2026, 11, 1, tz="Asia/Ho_Chi_Minh"),
    catchup=False,
    max_active_runs=1,
    tags=["lakehouse", "vn30"],
) as dag:
    vn30_bronze = spark_task("vn30_bronze", "vn30_bronze.py")
    vn30_silver = spark_task("vn30_silver", "vn30_silver.py")
    vn30_gold = spark_task("vn30_gold", "vn30_gold.py")
    vn30_check = spark_task("vn30_check", "vn30_check.py")
    verify_with_trino = KubernetesPodOperator(
        task_id="verify_with_trino",
        name="verify-with-trino",
        image=TRINO_IMAGE,
        cmds=["trino"],
        arguments=[
            "--server", "http://trino:8080",
            "--execute",
            "SELECT 'bronze.pages_raw' AS table_name, count(*) AS row_count FROM iceberg.vn30_bronze.pages_raw "
            "UNION ALL SELECT 'bronze.extracted_raw', count(*) FROM iceberg.vn30_bronze.extracted_raw "
            "UNION ALL SELECT 'bronze.cafef_raw', count(*) FROM iceberg.vn30_bronze.cafef_raw "
            "UNION ALL SELECT 'silver.financial_indicators', count(*) FROM iceberg.vn30_silver.financial_indicators "
            "UNION ALL SELECT 'silver.text_chunks', count(*) FROM iceberg.vn30_silver.text_chunks "
            "UNION ALL SELECT 'silver.companies', count(*) FROM iceberg.vn30_silver.companies "
            "UNION ALL SELECT 'silver.metric_catalog', count(*) FROM iceberg.vn30_silver.metric_catalog "
            "UNION ALL SELECT 'gold.company_year_metrics', count(*) FROM iceberg.vn30_gold.company_year_metrics "
            "UNION ALL SELECT 'gold.data_quality_by_ticker', count(*) FROM iceberg.vn30_gold.data_quality_by_ticker",
        ],
        container_resources=k8s.V1ResourceRequirements(
            requests={"cpu": "50m", "memory": "128Mi"},
            limits={"memory": "512Mi"},
        ),
        **COMMON,
    )

    vn30_bronze >> vn30_silver >> vn30_gold >> vn30_check >> verify_with_trino
