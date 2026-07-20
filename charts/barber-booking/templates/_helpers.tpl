{{/*
Chart/release naming — every resource is prefixed "<release>-barber-booking"
so multiple shops can be installed in the same namespace without colliding.
*/}}
{{- define "barber-booking.fullname" -}}
{{- printf "%s-barber-booking" .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "barber-booking.labels" -}}
app.kubernetes.io/name: barber-booking
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
The database connection string the backend uses. SQLite needs no secret;
Postgres (built-in or external) is assembled here so it only has to be
figured out once.
*/}}
{{/*
Built with a $(POSTGRES_PASSWORD) reference that Kubernetes expands at
container start — see the backend Deployment's "env:" list, which defines
POSTGRES_PASSWORD (from the Postgres Secret) right before DATABASE_URL so
the substitution can see it. This only works for values under "env:", not
"envFrom:", which is why DATABASE_URL is set there directly instead of
living in the ConfigMap with the other variables.
*/}}
{{- define "barber-booking.databaseUrl" -}}
{{- if eq .Values.database.type "postgres" -}}
  {{- if .Values.postgresql.enabled -}}
postgresql://{{ .Values.postgresql.username }}:$(POSTGRES_PASSWORD)@{{ include "barber-booking.fullname" . }}-postgres:5432/{{ .Values.postgresql.database }}
  {{- else -}}
{{ required "database.externalUrl is required when database.type=postgres and postgresql.enabled=false" .Values.database.externalUrl }}
  {{- end -}}
{{- else -}}
sqlite:////data/barber.db
{{- end -}}
{{- end -}}

{{/* CORS allow-list: explicit value, or derived from the ingress host. */}}
{{- define "barber-booking.corsOrigins" -}}
{{- if .Values.corsOrigins -}}
{{ .Values.corsOrigins }}
{{- else -}}
https://{{ .Values.ingress.host }}
{{- end -}}
{{- end -}}

{{- define "barber-booking.tlsSecretName" -}}
{{- if .Values.ingress.tls.secretName -}}
{{ .Values.ingress.tls.secretName }}
{{- else -}}
{{ include "barber-booking.fullname" . }}-tls
{{- end -}}
{{- end -}}

{{/*
The four public-facing URLs below all default to "https://<ingress host>",
which is correct once real Ingress + TLS + DNS are in front. Each can be
overridden independently under .Values.urls — used by values-local.yaml,
where there's no Ingress at all and the app is reached via plain-http
`kubectl port-forward` instead.
*/}}
{{- define "barber-booking.publicApiUrl" -}}
{{- .Values.urls.publicApiUrl | default (printf "https://%s" .Values.ingress.apiHost) -}}
{{- end -}}

{{- define "barber-booking.adminUrl" -}}
{{- .Values.urls.adminUrl | default (printf "https://%s/admin" .Values.ingress.apiHost) -}}
{{- end -}}

{{- define "barber-booking.reflexApiUrl" -}}
{{- .Values.urls.reflexApiUrl | default (printf "https://%s" .Values.ingress.host) -}}
{{- end -}}

{{- define "barber-booking.frontendUrl" -}}
{{- .Values.urls.frontendUrl | default (printf "https://%s" .Values.ingress.host) -}}
{{- end -}}

{{/* Name of the Secret holding JWT_SECRET/OWNER_PASSWORD/SMTP_*. */}}
{{- define "barber-booking.backendSecretName" -}}
{{- .Values.existingSecret | default (printf "%s-backend" (include "barber-booking.fullname" .)) -}}
{{- end -}}

{{/* Name of the Secret holding the built-in Postgres's POSTGRES_PASSWORD. */}}
{{- define "barber-booking.postgresSecretName" -}}
{{- .Values.postgresql.existingSecret | default (printf "%s-postgres" (include "barber-booking.fullname" .)) -}}
{{- end -}}

{{/*
imagePullSecrets for the pod spec: whatever's listed explicitly in
.Values.imagePullSecrets, plus a chart-managed one if imageCredentials.password
is set (see image-pull-secret.yaml). Renders nothing if neither is configured.
*/}}
{{- define "barber-booking.imagePullSecrets" -}}
{{- $secrets := .Values.imagePullSecrets -}}
{{- if .Values.imageCredentials.password -}}
{{- $secrets = append $secrets (dict "name" (printf "%s-registry" (include "barber-booking.fullname" .))) -}}
{{- end -}}
{{- if $secrets -}}
imagePullSecrets:
{{- range $secrets }}
  - name: {{ .name }}
{{- end }}
{{- end -}}
{{- end -}}
