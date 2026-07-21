# barber-booking Helm chart

One install = one shop. Install it again with a different release name and
values file for another shop on the same cluster.

## GitOps (ArgoCD)

This chart is designed to be referenced directly from your GitOps repo as a
"local"/path source — no chart repository or `helm push` needed, ArgoCD just
renders `charts/barber-booking` out of this git repo at whatever revision you
pin.

Two things ArgoCD does **not** do for you, which stay outside this chart:

1. **Building/pushing images.** Helm/ArgoCD only deploy manifests — your CI
   still needs to build `backend/` and `frontend/` and push them to a
   registry ArgoCD's cluster can pull from. Point `image.*.repository/tag` at
   the result.
2. **Secrets.** Don't put `jwtSecret`, `shop.owner.password`, or SMTP
   credentials in a values file — committed or not (an uncommitted values
   file is still a plaintext file sitting on disk, one accidental overwrite
   away from being gone for good). Instead, create the Secret directly,
   once, out of band, and point `existingSecret` at its name.

   The simplest way — plain `kubectl`, no extra tooling — one Secret with
   all four backend keys:

   ```sh
   kubectl create secret generic ribeiro-backend-secret \
     --namespace ribeiro-barbeiro \
     --from-literal=JWT_SECRET="$(openssl rand -hex 32)" \
     --from-literal=OWNER_PASSWORD='<the owner login password>' \
     --from-literal=SMTP_USERNAME='<smtp username>' \
     --from-literal=SMTP_PASSWORD='<smtp password/app password>'
   ```

   Then in the shop's values file (this part is safe to commit — it's just
   a name, not a secret):

   ```yaml
   existingSecret: "ribeiro-backend-secret"
   ```

   The chart then skips creating its own Secret and reads from yours. Same
   pattern for the built-in Postgres's password:

   ```sh
   kubectl create secret generic ribeiro-postgres-secret \
     --namespace ribeiro-barbeiro \
     --from-literal=POSTGRES_PASSWORD="$(openssl rand -hex 20)"
   ```
   ```yaml
   postgresql:
     existingSecret: "ribeiro-postgres-secret"
   ```

   Two tradeoffs worth knowing about the plain-`kubectl` approach: the
   Secret itself isn't tracked in git (so it won't show up in a GitOps diff,
   and needs to be recreated if the cluster/namespace is ever rebuilt), and
   whoever runs the command needs direct `kubectl` access to the cluster. If
   you want the Secret's *encrypted* form tracked in git too (so ArgoCD
   fully owns it, no out-of-band step to remember), look at Sealed Secrets,
   External Secrets Operator, or SOPS instead — same `existingSecret` wiring
   either way, only how the Secret gets into the cluster changes.

Example `Application`, in your GitOps repo. An `Application` takes **either**
`source` (single) **or** `sources` (multi) — never both — pick whichever
matches where your values file lives:

**Values file in a separate GitOps repo (the common pattern)** — use
multi-source `sources`, with `$values` referencing the second source by its
`ref`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: ribeiro-barbeiro
  namespace: argocd
spec:
  project: default
  sources:
    - repoURL: https://github.com/you/barber-booking.git
      targetRevision: main # or a tag, e.g. v1.0.0
      path: charts/barber-booking
      helm:
        valueFiles:
          - $values/shops/ribeiro/values.yaml
    - repoURL: https://github.com/you/gitops.git
      targetRevision: main
      ref: values
  destination:
    server: https://kubernetes.default.svc
    namespace: ribeiro-barbeiro
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

**No separate values file at all** — inline the overrides directly in the
`Application` via `helm.valuesObject` (structured YAML, nested right in the
manifest — cleaner than `helm.values`, which takes the same content as a raw
YAML string). Nothing else to commit — this manifest *is* the shop's config:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: ribeiro-barbeiro
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/you/barber-booking.git
    targetRevision: main # or a tag, e.g. v1.0.0
    path: charts/barber-booking
    helm:
      valuesObject:
        existingSecret: "ribeiro-backend-secret"
        shop:
          name: "Ribeiro Barbeiro"
          owner:
            name: "Paquito"
            email: "paquito@ribeirobarbeiro.pt"
        image:
          backend:
            repository: ghcr.io/you/barber-booking-backend
            tag: "v1.0.0"
          frontend:
            repository: ghcr.io/you/barber-booking-frontend
            tag: "v1.0.0"
        ingress:
          host: shop.ribeirobarbeiro.pt
        email:
          smtpHost: "smtp.your-provider.com"
          smtpFrom: "no-reply@ribeirobarbeiro.pt"
  destination:
    server: https://kubernetes.default.svc
    namespace: ribeiro-barbeiro
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

This `Application` is safe to commit as-is: nothing above is a secret,
`existingSecret` is just a name pointing at a Secret created out-of-band
(see "Secrets" above). Only reach for a separate values file (the two
examples above) once you're managing enough shops that repeating this block
per shop gets unwieldy, or you want a diffable values file reviewed
separately from the `Application`/destination/sync settings.

One `Application` per shop; each just needs its own values file and its own
`existingSecret`.

## First shop — what to configure

1. **Build and push images** — a GitHub Actions workflow is already included
   (`.github/workflows/build-images.yml`): push a tag like `v1.0.0` and it
   builds+pushes both images to this repo's own GHCR namespace,
   `ghcr.io/<owner>/<repo>-backend:v1.0.0` and `...-frontend:v1.0.0` (image
   names derive from the repo, nothing to edit). GHCR packages are private
   by default **even if the repo is public** — either make them public
   (simplest, no cluster-side auth needed) or set up `imagePullSecrets`; see
   "Private registry access" below for both.
2. **DNS**: point one hostname at your Ingress controller's load balancer —
   the booking website (e.g. `shop.example.com`). That's the only public
   hostname most shops need: Reflex's own backend (websocket state + the
   logo proxy) shares this same port as the page, so the booking API itself
   is never reachable from the internet, and customers can book, verify
   their email, and reset their password entirely through it. Leave
   `ingress.apiHost` unset (the default) unless you specifically want the
   API exposed too — see the note right after this list before turning it on.
3. **TLS**: either have cert-manager issue a cert automatically (uncomment
   the `cert-manager.io/cluster-issuer` annotation in `ingress.annotations`)
   or bring your own cert as a Secret named `ingress.tls.secretName`.
4. **Secrets**: create the backend Secret out-of-band (see GitOps section
   above) with `JWT_SECRET` (generate: `openssl rand -hex 32`),
   `OWNER_PASSWORD` (the owner's login password), and `SMTP_USERNAME`/
   `SMTP_PASSWORD` if your mail provider needs them. Reference it via
   `existingSecret`.
5. **Values file** for the shop — minimum needed (everything else has
   sensible defaults; see `values.yaml` for the full commented list):

   ```yaml
   existingSecret: "ribeiro-backend-secret"

   shop:
     name: "Ribeiro Barbeiro"
     owner:
       name: "Paquito"
       email: "paquito@ribeirobarbeiro.pt"
     # brand/background/headline are optional — the owner can change all
     # three live from the UI after first login anyway.

   image:
     backend:
       repository: ghcr.io/you/barber-booking-backend
       tag: "v1.0.0"
     frontend:
       repository: ghcr.io/you/barber-booking-frontend
       tag: "v1.0.0"

   ingress:
     className: nginx # or whatever your cluster's Ingress controller is
     host: shop.ribeirobarbeiro.pt
     # apiHost: api.ribeirobarbeiro.pt  # only if you want the API public too — see note below

   email:
     smtpHost: "smtp.your-provider.com"
     smtpFrom: "no-reply@ribeirobarbeiro.pt"
     # smtpUsername/smtpPassword come from existingSecret, not here.
   ```

   > **`ingress.apiHost` exposes the *entire* FastAPI app to the internet**
   > — every booking/auth endpoint, not just `/docs` and `/admin` — because
   > its Ingress rule is a catch-all `/` straight to the backend Service.
   > The booking website never needs this (it talks to the API pod-to-pod
   > via `API_URL` regardless of whether `apiHost` is set). The one good
   > reason to set it is wanting the SQLAdmin console (`/admin`) or the
   > interactive API docs (`/docs`) reachable from a plain browser, without
   > a VPN or `kubectl port-forward`. If you do set it: point its DNS at the
   > same load balancer as `host`, it gets its own TLS SAN entry
   > automatically, and the "Abrir a consola de administração" link
   > reappears in the owner UI pointing at `https://<apiHost>/admin`.

6. **Sync** in ArgoCD (or let `syncPolicy.automated` do it). Watch the
   rollout: `kubectl get pods -n ribeiro-barbeiro -w`.
7. **Log in** as the owner at `https://shop.ribeirobarbeiro.pt` with the
   email above and the password from your Secret, and finish setup from the
   UI (logo, brand colours, working hours, services — see the root
   `README.md`'s "How it works").

That's the whole first-shop checklist. Everything else (database choice,
replicas, resource limits, CORS) has a working default — only touch it if
you have a specific reason to (see below).

## Naming & namespace

Resources are named after the release name by default, kind-suffixed so
what's what is obvious at a glance (e.g. release `ribeiro` -> service
`ribeiro-backend-svc`, deployment `ribeiro-backend-deploy`, configmap
`ribeiro-backend-cm`, ...), in whatever namespace the release targets — with
ArgoCD, that's `spec.destination.namespace` on the `Application`. Set
`nameOverride` to use a different resource-name prefix.

## Private registry access

If `image.*.repository` points at a private image (e.g. a GHCR package set
to private), the cluster needs an `imagePullSecret` or pulls will fail with
`ImagePullBackOff`. Note that a **public GitHub repo does not make its GHCR
packages public** — packages are private by default regardless, and there's
no way to change that from the workflow itself.

**Option 0 — make the package public (simplest, no cluster auth at all):**
after the first push, GHCR public packages allow anonymous pulls. Do this
once per package (`<repo>-backend` and `<repo>-frontend`):
`https://github.com/users/<you>/packages/container/package/<repo>-backend`
→ **Package settings** → **Danger Zone** → **Change visibility** → **Public**
(type the package name to confirm). With both public, skip everything below
— no `imagePullSecrets`, no `imageCredentials`.

If you'd rather keep the images private, two ways to configure — pick
**one**, not both:

1. **GitOps-friendly (preferred)** — create the pull secret yourself
   out-of-band, so the PAT never lands in a values file:

   ```sh
   kubectl create secret docker-registry ghcr-pull \
     --docker-server=ghcr.io \
     --docker-username=<github-username> \
     --docker-password="<personal access token, read:packages scope>" \
     --namespace ribeiro-barbeiro
   ```

   Then just reference it by name in values — leave `imageCredentials`
   untouched (its `password` is empty by default, so the chart renders no
   Secret of its own; there's nothing extra to "disable"):

   ```yaml
   imagePullSecrets:
     - name: ghcr-pull
   ```

2. **Chart-managed** — let the chart create the secret from a PAT set
   directly in values. Simpler, but the PAT then lives wherever this value
   is set — only use this with a values file that itself stays out of git
   (`--set`, or a GitOps secret tool that injects the value at apply time):

   ```yaml
   imageCredentials:
     registry: ghcr.io
     username: <github-username>
     password: <PAT with read:packages scope>
   ```

A GitHub PAT for GHCR only needs the `read:packages` scope (classic PAT), or
for a fine-grained PAT, "Packages: read-only" on the relevant repo/org.

## Database

SQLite (default) needs nothing extra — a 1Gi PVC is created automatically.
For Postgres, either point at a managed instance:

```yaml
database:
  type: postgres
  externalUrl: "postgresql://<user>:<secret>@<host>:5432/<database>"
```

or use the chart's built-in single-replica Postgres:

```yaml
database:
  type: postgres
postgresql:
  enabled: true
  existingSecret: "ribeiro-postgres-secret" # POSTGRES_PASSWORD key
```

## Advanced / rarely-needed values

These have working defaults for a normal deploy — only touch them if you have
a specific reason to.

- **`corsOrigins`** — the API's CORS allow-list. Defaults to
  `https://<ingress.host>`, which is correct whenever the frontend is reached
  at `ingress.host` (the normal case). Only set this if the booking website
  is also reachable under some other origin.
- **`urls.adminUrl` / `urls.reflexApiUrl` / `urls.frontendUrl`** — override
  the public URLs the app is built with, instead of deriving them from
  `ingress.host`/`apiHost` (which assumes a real Ingress in front, over
  HTTPS). Leave these empty for a normal deploy. They exist for setups
  without that Ingress — e.g. `values-local.yaml`, where the app is reached
  via plain-http `kubectl port-forward` and there's no Ingress splitting
  paths — see "Local testing" below.
- **`frontend.mailInboxUrl`** — dev-only convenience link. When set, a
  "Check Inbox" button appears next to the login/verify/reset forms,
  linking straight to a caught-email tool (e.g. Mailpit's web UI), so you
  can read verification/reset emails during local testing without a real
  SMTP provider. Leave empty in production — see `values-local.yaml`.

## Local testing (optional, no registry)

Not part of the GitOps flow above — just for trying the chart out by hand on
`kind`/`minikube`/`k3d`/Docker Desktop. See the commands at the top of
`values-local.yaml`.

## Reaching the app without an Ingress

Both Services default to `ClusterIP` (only reachable from inside the
cluster) — normal once Ingress is set up. To reach the app directly instead
(e.g. testing from your home network before DNS/Ingress is ready), set the
frontend Service to `LoadBalancer`:

```yaml
frontend:
  service:
    type: LoadBalancer
```

Your cluster needs a load-balancer implementation for this to get a real
external IP (cloud providers do this automatically; bare-metal clusters need
something like MetalLB). Check it with:

```sh
kubectl get svc -n ribeiro-barbeiro ribeiro-frontend-svc
```

Once `EXTERNAL-IP` is assigned, the booking site is reachable at
`http://<that-ip>:3000` — no TLS, no hostname, just for testing. Switch back
to `ClusterIP` (the default) once Ingress is set up for real use.
`backend.service.type` works the same way, for testing `/docs`/`/admin`
directly without the frontend in front — but keep in mind
[the note above](#first-shop--what-to-configure) about `ingress.apiHost`:
the same "now it's fully public" tradeoff applies here too.

## Why backend/frontend replicas stay at 1

- **Backend**: SQLite is a single file (one writer at a time), and the login
  rate limiter counts in memory per pod. Scaling needs Postgres *and* a
  shared rate-limit store (e.g. Redis) — neither is wired up here.
- **Frontend**: Reflex keeps UI state in memory per worker. Scaling needs
  Reflex's Redis-backed state manager — not wired up here either.

Both are fine for a single shop's traffic. See the root `README.md`'s
"Known limitations" section for the full reasoning.
