FROM tabulario/iceberg-rest:1.6.0

USER root
ADD https://repo1.maven.org/maven2/com/mysql/mysql-connector-j/8.4.0/mysql-connector-j-8.4.0.jar /usr/lib/iceberg-rest/lib/mysql-connector-j-8.4.0.jar
RUN chown -R iceberg:iceberg /usr/lib/iceberg-rest/lib

USER iceberg:iceberg
WORKDIR /usr/lib/iceberg-rest
CMD ["java", "-cp", "iceberg-rest-image-all.jar:lib/*", "org.apache.iceberg.rest.RESTCatalogServer"]
