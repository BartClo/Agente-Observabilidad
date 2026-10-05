-- Se ejecuta una sola vez, al crear el volumen de datos de postgres (ver
-- docker-compose.yml: se monta en /docker-entrypoint-initdb.d).
CREATE EXTENSION IF NOT EXISTS vector;
