{{- define "signalfloor.fullname" -}}
{{- if contains .Chart.Name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "signalfloor.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{- define "signalfloor.selector" -}}
app.kubernetes.io/name: {{ .root.Chart.Name }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "signalfloor.serverImage" -}}
{{ .Values.image.server.repository }}:{{ .Values.image.server.tag }}
{{- end -}}

{{- define "signalfloor.databaseSecret" -}}
{{- .Values.database.existingSecret | default (printf "%s-database" (include "signalfloor.fullname" .)) -}}
{{- end -}}

{{- define "signalfloor.databaseUrl" -}}
{{- if .Values.database.url -}}
{{- .Values.database.url -}}
{{- else if .Values.postgresql.enabled -}}
{{- printf "postgresql+asyncpg://signalfloor:%s@%s-postgres:5432/signalfloor" .Values.postgresql.password (include "signalfloor.fullname" .) -}}
{{- else -}}
{{- fail "Set database.url or database.existingSecret, or turn on postgresql.enabled" -}}
{{- end -}}
{{- end -}}

{{/* Locked down defaults for our own containers. */}}
{{- define "signalfloor.podSecurity" -}}
runAsNonRoot: true
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{- define "signalfloor.containerSecurity" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: ["ALL"]
{{- end -}}

{{- define "signalfloor.serverEnv" -}}
- name: SIGNALFLOOR_DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ include "signalfloor.databaseSecret" . }}
      key: SIGNALFLOOR_DATABASE_URL
{{- end -}}


{{- define "signalfloor.apiKeyEnv" -}}
{{- if .root.Values.auth.apiKeys }}
- name: {{ .name }}
  valueFrom:
    secretKeyRef:
      name: {{ include "signalfloor.fullname" .root }}-api-keys
      key: {{ .name }}
{{- end }}
{{- end -}}
