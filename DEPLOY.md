# Deploying RevenueForge to Azure App Service

One container runs everything (web app + API). GitHub builds the container on every merge to `main`;
Azure App Service runs it. Data (database, uploads, generated documents and videos) lives on the App
Service's persistent `/home` storage.

```
merge to main ──► GitHub Actions builds the image ──► ghcr.io/<owner>/revenueforge ──► Azure App Service
```

Allow about 30–45 minutes the first time. Azure's screens change from time to time, so labels may differ slightly.

---

## 1. Build the first image (GitHub)

1. Merge the release branch into `main` (pull request on GitHub). The **Actions** tab shows a run called
   **Build and deploy**. Wait for the green tick (5–8 minutes the first time). The *deploy* step says
   "Azure not connected yet": that's expected.
2. Make the image public so Azure can download it (it contains no secrets or data; `.dockerignore` keeps
   `backend/.env` and `backend/data` out):
   GitHub → your profile → **Packages** → **revenueforge** → **Package settings** → **Change visibility** → **Public**.

## 2. Create the Web App (Azure portal)

portal.azure.com → **Create a resource** → **Web App**.

| Field | Value |
|---|---|
| Resource group | Create new: `revenueforge-rg` |
| Name | e.g. `revenueforge-demo` → the address becomes `https://revenueforge-demo.azurewebsites.net` (Azure may add a suffix) |
| Publish | **Container** |
| Operating system | **Linux** |
| Region | Central India (or the region closest to your users) |
| Pricing plan | **Basic B2** recommended (B1 works for a few users; video rendering is faster on B2). Check the price in the portal. |

**Container** tab:

| Field | Value |
|---|---|
| Image source | **Other container registries** |
| Access type | **Public** |
| Registry server URL | `https://ghcr.io` |
| Image and tag | `sanjayhprasanna/revenueforge:latest` (your GitHub owner name in lower case) |
| Port | `8000` |

**Review + create** → **Create**.

## 3. Settings (Environment variables)

Web App → **Settings → Environment variables → App settings** → add each, then **Apply**:

| Name | Value | Why |
|---|---|---|
| `WEBSITES_PORT` | `8000` | The port the app listens on |
| `WEBSITES_ENABLE_APP_SERVICE_STORAGE` | `true` | Keeps data in `/home` across restarts and redeploys |
| `LLM_PROVIDER` | `gemini` | Turns the AI on |
| `GEMINI_API_KEY` | your key | Stored only in Azure, never in git |
| `GOOGLE_ALLOWED_DOMAINS` | e.g. `yourcompany.com` | Optional: only company Google accounts can sign in |
| `GEMINI_VIDEO_API_KEY` | second key | Optional: separate quota for video narration |
| `MAAHI_GEMINI_API_KEY` | third key | Optional: separate quota for Maahi, the chat assistant |

While the key is a free one, everyone sees a "test version: sample or dummy documents only" banner.
When you switch to a billed key, add `LLM_PAID=true` and the banner disappears. Set `PUBLIC_NOTICE`
to show your own message instead, or `off` to hide it.

## 4. General settings

Web App → **Settings → Configuration → General settings**:
- **Always On**: **On** (otherwise Azure pauses the app when idle and a deal being processed stops).
- Web App → **Monitoring → Health check** → path `/api/health` → **Save**.

## 5. Google sign-in

Google Cloud console → **Google Auth Platform → Clients** → your web client → **Authorised JavaScript origins**
→ add `https://<your-app>.azurewebsites.net` → **Save**. (Keep `http://localhost:5173` for local use.)
Everyone who signs in with Google must be on the **Audience → Test users** list until the app is published there.

Open `https://<your-app>.azurewebsites.net`. The first start takes 1–2 minutes.

## 6. Automatic deploys (recommended)

So every merge to `main` updates the site:

1. Web App → **Settings → Configuration → General settings** → **SCM Basic Auth Publishing Credentials** → **On** → Save.
2. Web App → **Overview** → **Download publish profile**.
3. GitHub repo → **Settings → Secrets and variables → Actions**:
   - **Secrets** tab → **New repository secret**: name `AZURE_WEBAPP_PUBLISH_PROFILE`, value = the whole content of the downloaded file.
   - **Variables** tab → **New repository variable**: name `AZURE_WEBAPP_NAME`, value = your Web App name.
4. GitHub → **Actions → Build and deploy → Run workflow** to deploy now.

Delete the downloaded publish profile file afterwards: it is a password.

---

## Good to know

- **Data**: the database and files are in `/home/data` on the Web App. To look at or back them up: Web App →
  **Development Tools → Advanced Tools (Kudu)** → **Debug console**. Higher plans (Standard and up) offer scheduled backups.
- **More users**: the built-in database (SQLite) suits a feedback round on a single instance. For wider use, create
  an *Azure Database for PostgreSQL – Flexible Server* and set `DATABASE_URL` to
  `postgresql+psycopg2://USER:PASSWORD@HOST:5432/revenueforge?sslmode=require`. Keep the plan at one instance either way:
  deals and videos are processed inside the app.
- **Video voice**: the server uses the open-source eSpeak voice, which sounds more robotic than Windows' voices.
- **Logs**: Web App → **Monitoring → Log stream**.
- **Restart** after changing settings: Web App → **Overview → Restart**. A restart interrupts any deal being processed; it
  shows as interrupted and can be re-run.
- **Cost control**: **Stop** the Web App when not in use (data is kept); delete the resource group to remove everything.
