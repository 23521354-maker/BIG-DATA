# Spark image for the Lakehouse project.
#
# Everything the Spark jobs need is declared in this file or in requirements.txt and is
# installed at BUILD time. Nothing is downloaded when a Spark pod starts.
#
# Base image: Spark 3.5.5 + pandas. It already contains the two Iceberg jars below; we declare
# them again (same version, same file name = overwrite) so the Iceberg runtime is visible here.
FROM tabulario/spark-iceberg:3.5.5_1.8.1

# Iceberg Spark Runtime (Spark 3.5, Scala 2.12) + AWS bundle (S3FileIO for the Iceberg REST catalog)
ADD https://repo1.maven.org/maven2/org/apache/iceberg/iceberg-spark-runtime-3.5_2.12/1.8.1/iceberg-spark-runtime-3.5_2.12-1.8.1.jar /opt/spark/jars/iceberg-spark-runtime-3.5_2.12-1.8.1.jar
ADD https://repo1.maven.org/maven2/org/apache/iceberg/iceberg-aws-bundle/1.8.1/iceberg-aws-bundle-1.8.1.jar /opt/spark/jars/iceberg-aws-bundle-1.8.1.jar

# s3a:// connector so Spark can read/write MinIO (Hadoop 3.3.4 = the version bundled with Spark 3.5.5)
ADD https://repo1.maven.org/maven2/org/apache/hadoop/hadoop-aws/3.3.4/hadoop-aws-3.3.4.jar /opt/spark/jars/hadoop-aws-3.3.4.jar
ADD https://repo1.maven.org/maven2/com/amazonaws/aws-java-sdk-bundle/1.12.262/aws-java-sdk-bundle-1.12.262.jar /opt/spark/jars/aws-java-sdk-bundle-1.12.262.jar
ADD https://repo1.maven.org/maven2/org/wildfly/openssl/wildfly-openssl/1.0.7.Final/wildfly-openssl-1.0.7.Final.jar /opt/spark/jars/wildfly-openssl-1.0.7.Final.jar
RUN chmod 644 /opt/spark/jars/iceberg-spark-runtime-3.5_2.12-1.8.1.jar /opt/spark/jars/iceberg-aws-bundle-1.8.1.jar /opt/spark/jars/hadoop-aws-3.3.4.jar /opt/spark/jars/aws-java-sdk-bundle-1.12.262.jar /opt/spark/jars/wildfly-openssl-1.0.7.Final.jar

# Python libraries for the Spark jobs (kept from the base project; current BCTC jobs do not need them)
COPY requirements.txt /tmp/requirements.txt
RUN python3 -m pip install --no-cache-dir -r /tmp/requirements.txt
