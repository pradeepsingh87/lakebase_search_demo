-- Run as the project owner after the app exists (its service principal role is created by the postgres resource).
-- Replace the client id with: databricks apps get <app> -o json | jq -r .service_principal_client_id
GRANT USAGE ON SCHEMA retail TO "902d5705-84c0-4ade-be91-52eef4f35495";
GRANT SELECT ON ALL TABLES IN SCHEMA retail TO "902d5705-84c0-4ade-be91-52eef4f35495";
-- live writes from the "Add a service note" feature
GRANT INSERT ON retail.service_notes, retail.support_docs TO "902d5705-84c0-4ade-be91-52eef4f35495";
