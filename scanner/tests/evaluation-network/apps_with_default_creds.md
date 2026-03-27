# Apps with Default Creds

## Evaluation Network Apps

### Working Default Creds

- ActiveMQ | working with http auth
- ApacheGuacamole | working
- Casdoor | working
- Filebrowser | works (but needs <=v2.32.0)
- Huginn | works
- Kanboard | works
- Keycloak | works, but default creds are set in env and only some vendors tend to use admin/admin when depoyed
- KibanaOSS | works, but only old versions have this
- MinIO | works
- NexusRepositoryManager | works, but older version
- NginxProxyManager | works, but slightly older version
- NuxeoServer | works
- OpenSearchDashboards | works (older version)
- RabbitMQManagement | works
- Redmine | works
- Rundeck | works
- Seafile | works
- Umami | works
- Yacht | works
- EMQX Dashboard | works
- Superset | works, but creds are set via preconfiguration (-> depends on the deployment)
- Event Store DB | works
- qBittorrent | works
- Stirling-PDF | works
- Airsonic | works
- OpenVAS (GVM) | works, but takes long to init

### Working But No Default Creds

- ApacheTomcat | no default creds
- ApacheTomcatHostManager | also no default creds
- CheckmkRaw | default creds removed in 1.4.0, but dockerhub has only 1.6.0 and higher
- CouchDB | does not have default creds
- Directus | does not have default creds
- Elasticsearch | no auth
- GoCD | no auth
- InfluxDB1x | no default creds
- JBossAS6 | no default creds
- Jenkins | no default creds
- N8N | needs setup
- Nextcloud | no default creds
- PgAdmin | no default creds
- WebSphere | no default creds
- WordPress | no default creds, requires setup
- Cloud-Torrent | no default creds
- Meilisearch | no default creds
- Tautulli | setup
- Adminer | no default creds
- Node-RED | no auth
- ArchiSteamFarm | no auth
- Gophish | requires older version that is not easily available
- Graylog | no default creds
- Hasura | no auth
- Pi-hole | no default creds
- Portainer | setup
- AdGuard Home | setup
- Jellyfin | setup
- Uptime Kuma | setup
- Airflow | default creds not working

### Not Working

- ArtifactoryOSS | DOCKER COMPOSE FAILING
- Odoo | broken and default creds are only because set in preconfigured docker compose files
- DokuWiki
- Matomo
- IBMUrbanCodeDeploy
- JasperReports
- TeamCity9Guest
- UFM Enterprise | broken docker compose

## Test Network Apps

- 4gaBoards
- BabyBuddy
- BookStack
- CalibrWeb
- ClipCascade
- Convertigo
- DataLens
- DockerSSOServer
- Filadex
- Grafana
- Joplin
- MongoExpress
- osTicket
- ownCloud
- PasswordCockpit
- Pyload
- Rainloop
- Readmine
- SonarQube
- Zabbix
