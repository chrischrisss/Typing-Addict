# Typing Addict

Multiplayer typing race with persistent accounts, waiting-room rosters, host controls,
and three server-timed rounds: typing, clicking, then spacebar.

## Run

Backend:

```powershell
cd Backend
python -m pip install -r requirements.txt
python app.py
```

Frontend:

```powershell
cd Frontend
npm install
npm run dev
```

Open the Vite URL to register, or sign in with `admin` / `password`.

## Deploy on Render (SQLite)

This repo includes a [`render.yaml`](render.yaml) blueprint that deploys one Web Service with:

- Flask API + Socket.IO on the same domain as the React build
- SQLite stored on a Render persistent disk at `/data/db.sqlite3`

### Steps

1. Push this repository to GitHub.
2. In [Render](https://dashboard.render.com), choose **New +** → **Blueprint** and connect the repo.
3. Render reads `render.yaml` and creates the web service plus a 1 GB persistent disk.
4. Deploy. Render sets `RENDER`, `DATABASE_URL`, `JWT_SECRET_KEY`, and `SECRET_KEY` for you.
5. Open the service URL (for example `https://typing-addict.onrender.com`).

### Notes

- **Starter plan required** for the persistent disk in `render.yaml`. On the free plan, remove the `disk:` block and accept that SQLite data resets on redeploy, or upgrade later.
- Change the default `admin` / `password` account after the first deploy.
- Local development is unchanged: run the backend and Vite dev server separately (see above).
- Production build copies `Frontend/dist` into `Backend/static` via `Backend/build.sh`.

## Tests

```powershell
cd Backend
python -m unittest -v test_app.py

cd ..\Frontend
npm run lint
npm run build
```
