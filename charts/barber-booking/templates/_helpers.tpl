{{/* Resource name — defaults to the release name; nameOverride replaces it. */}}
{{- define "barber-booking.fullname" -}}
{{- default .Release.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Per-resource names — kind-suffixed so an object's kind is obvious from its name. */}}
{{- define "barber-booking.backendServiceName" -}}{{ include "barber-booking.fullname" . }}-backend-svc{{- end -}}
{{- define "barber-booking.frontendServiceName" -}}{{ include "barber-booking.fullname" . }}-frontend-svc{{- end -}}
{{- define "barber-booking.postgresServiceName" -}}{{ include "barber-booking.fullname" . }}-postgres-svc{{- end -}}
{{- define "barber-booking.backendConfigMapName" -}}{{ include "barber-booking.fullname" . }}-backend-cm{{- end -}}
{{- define "barber-booking.frontendConfigMapName" -}}{{ include "barber-booking.fullname" . }}-frontend-cm{{- end -}}
{{- define "barber-booking.backendDeploymentName" -}}{{ include "barber-booking.fullname" . }}-backend-deploy{{- end -}}
{{- define "barber-booking.frontendDeploymentName" -}}{{ include "barber-booking.fullname" . }}-frontend-deploy{{- end -}}
{{- define "barber-booking.postgresStatefulSetName" -}}{{ include "barber-booking.fullname" . }}-postgres-sts{{- end -}}
{{- define "barber-booking.dataPvcName" -}}{{ include "barber-booking.fullname" . }}-data-pvc{{- end -}}
{{- define "barber-booking.ingressName" -}}{{ include "barber-booking.fullname" . }}-ingress{{- end -}}
{{- define "barber-booking.registrySecretName" -}}{{ include "barber-booking.fullname" . }}-registry-secret{{- end -}}

{{/* Chart name + version, for the standard helm.sh/chart label. */}}
{{- define "barber-booking.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Standard labels — selector labels are separate so they stay immutable. */}}
{{- define "barber-booking.labels" -}}
helm.sh/chart: {{ include "barber-booking.chart" . }}
{{ include "barber-booking.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
{{- end -}}

{{- define "barber-booking.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
The database connection string the backend uses. SQLite needs no secret;
Postgres (built-in or external) is assembled here so it only has to be
figured out once. Built with a $(POSTGRES_PASSWORD) reference that
Kubernetes expands at container start — see the backend Deployment's "env:"
list, which defines POSTGRES_PASSWORD (from the Postgres Secret) right
before DATABASE_URL so the substitution can see it. This only works for
values under "env:", not "envFrom:", which is why DATABASE_URL is set there
directly instead of living in the ConfigMap with the other variables.
*/}}
{{- define "barber-booking.databaseUrl" -}}
{{- if eq .Values.database.type "postgres" -}}
  {{- if .Values.postgresql.enabled -}}
postgresql://{{ .Values.postgresql.username }}:$(POSTGRES_PASSWORD)@{{ include "barber-booking.postgresServiceName" . }}:5432/{{ .Values.postgresql.database }}
  {{- else -}}
{{ required "database.externalUrl is required when database.type=postgres and postgresql.enabled=false" .Values.database.externalUrl }}
  {{- end -}}
{{- else -}}
sqlite:////data/barber.db
{{- end -}}
{{- end -}}

{{/*
CORS allow-list: explicit value, or derived from the ingress host — but only
when Ingress is actually the thing serving traffic. If ingress.enabled is
false, ingress.host describes nothing real (it may still hold its chart
default, or a stale domain from a previous config), so falling back to it
would silently allow-list an origin nobody can reach. Fail instead of
guessing — see corsOrigins' comment in values.yaml for what to set.
*/}}
{{- define "barber-booking.corsOrigins" -}}
{{- if .Values.corsOrigins -}}
{{ .Values.corsOrigins }}
{{- else if .Values.ingress.enabled -}}
https://{{ .Values.ingress.host }}
{{- else -}}
{{ fail "corsOrigins is required when ingress.enabled=false — set it to the origin the browser actually uses (e.g. \"http://<LoadBalancer-IP>:3000\" or a private DNS/VPN name). See values.yaml's corsOrigins comment." }}
{{- end -}}
{{- end -}}

{{- define "barber-booking.tlsSecretName" -}}
{{- if .Values.ingress.tls.secretName -}}
{{ .Values.ingress.tls.secretName }}
{{- else -}}
{{ include "barber-booking.fullname" . }}-tls-secret
{{- end -}}
{{- end -}}

{{/*
Public-facing URLs. reflexApiUrl/frontendUrl default to "https://<ingress
host>", but ONLY when ingress.enabled is true — that default assumes a real
Ingress + TLS + DNS is actually in front of the app. With ingress.enabled=
false, ingress.host doesn't route anywhere (it may just be sitting at its
chart default, or a stale domain from switching off Ingress later), so
falling back to it would point the browser's websocket at a dead/wrong
address instead of wherever the app is really being reached (LoadBalancer
IP, NodePort, port-forward, VPN...). We fail with a concrete pointer to
urls.reflexApiUrl/frontendUrl instead of guessing wrong silently — see
values-local.yaml for a worked no-Ingress example. adminUrl stays empty
(hiding the admin link in the UI) unless ingress.apiHost is set AND Ingress
is enabled — setting apiHost publishes the whole FastAPI app to the
internet, not just /admin, so it's an intentional opt-in (see the long
comment above ingress.apiHost in values.yaml). Each of these can be
overridden independently under .Values.urls regardless of ingress.enabled.
*/}}
{{- define "barber-booking.adminUrl" -}}
{{- if .Values.urls.adminUrl -}}
{{ .Values.urls.adminUrl }}
{{- else if and .Values.ingress.enabled .Values.ingress.apiHost -}}
{{ printf "https://%s/admin" .Values.ingress.apiHost }}
{{- end -}}
{{- end -}}

{{- define "barber-booking.reflexApiUrl" -}}
{{- if .Values.urls.reflexApiUrl -}}
{{ .Values.urls.reflexApiUrl }}
{{- else if .Values.ingress.enabled -}}
{{ printf "https://%s" .Values.ingress.host }}
{{- else -}}
{{ fail "urls.reflexApiUrl is required when ingress.enabled=false — set it to the address the browser actually uses to reach the frontend (e.g. \"http://<LoadBalancer-IP>:3000\"). See values-local.yaml for a worked example." }}
{{- end -}}
{{- end -}}

{{- define "barber-booking.frontendUrl" -}}
{{- if .Values.urls.frontendUrl -}}
{{ .Values.urls.frontendUrl }}
{{- else if .Values.ingress.enabled -}}
{{ printf "https://%s" .Values.ingress.host }}
{{- else -}}
{{ fail "urls.frontendUrl is required when ingress.enabled=false — set it to the address customers use to reach the site (used in password-reset/verification email links). See values-local.yaml for a worked example." }}
{{- end -}}
{{- end -}}

{{/* Name of the Secret holding JWT_SECRET/OWNER_PASSWORD/SMTP_*. */}}
{{- define "barber-booking.backendSecretName" -}}
{{- .Values.existingSecret | default (printf "%s-backend-secret" (include "barber-booking.fullname" .)) -}}
{{- end -}}

{{/* Name of the Secret holding the built-in Postgres's POSTGRES_PASSWORD. */}}
{{- define "barber-booking.postgresSecretName" -}}
{{- .Values.postgresql.existingSecret | default (printf "%s-postgres-secret" (include "barber-booking.fullname" .)) -}}
{{- end -}}

{{/*
imagePullSecrets for the pod spec: whatever's listed explicitly in
.Values.imagePullSecrets, plus a chart-managed one if imageCredentials.password
is set (see image-pull-secret.yaml). Renders nothing if neither is configured.
*/}}
{{- define "barber-booking.imagePullSecrets" -}}
{{- $secrets := .Values.imagePullSecrets -}}
{{- if .Values.imageCredentials.password -}}
{{- $secrets = append $secrets (dict "name" (include "barber-booking.registrySecretName" .)) -}}
{{- end -}}
{{- if $secrets -}}
imagePullSecrets:
{{- range $secrets }}
  - name: {{ .name }}
{{- end }}
{{- end -}}
{{- end -}}
