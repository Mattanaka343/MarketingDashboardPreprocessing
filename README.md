# ETL and Database Migration

This repository contains all the scripts needed to extract social media data from multiple sources, enrich it with embeddings and LLM-based classification, and load it into the Nurvai/Wexpand marketing database. It also handles one-time migration from the legacy schema to the current one.

---

## Setup

### Option A — Conda (recommended)

```bash
conda create -n etl-env python=3.12
conda activate etl-env

pip install -r requirements.txt

curl -fsSL https://ollama.com/install.sh | sh

ollama serve
ollama pull <your-embedding-model>   # recommended: nomic-embed-text
ollama pull <your-llm-model>         # recommended: qwen2.5:7b

sudo mysql -u your_user -p < CreateDatabase.sql
```

### Option B — venv

```bash
python3 -m venv etl-env
source etl-env/bin/activate

pip install -r requirements.txt

curl -fsSL https://ollama.com/install.sh | sh

ollama serve
ollama pull <your-embedding-model>
ollama pull <your-llm-model>

sudo mysql -u your_user -p < CreateDatabase.sql
```

> **macOS note:** `ollama serve` must run in a separate terminal window and stay running for the duration of any ETL job.

---

## Environment Variables

Create a `.env` file in the project root with the following keys:

```env
DATABASE_USER=your_db_user
MYSQL_PASSWORD=your_db_password
DATABASE_HOST=your_db_host
GMAIL_USER=your_bot_gmail@gmail.com
GMAIL_APP_PASSWORD=your_gmail_app_password
NOTIFY_TO=recipient@domain.com
GOOGLE_APPLICATION_CREDENTIALS=path/to/credentials.json
IG_ACCESS_TOKEN=your_instagram_access_token
IG_USER_ID=your_instagram_user_id
EMBED_MODEL=nomic-embed-text
LLM_MODEL=qwen2.5:7b
DATA_PATH=relative/path/to/data
```

---

## Daily Data Sync

The pipeline is designed to run autonomously. The only manual step each day is uploading the X (Twitter) and LinkedIn export files to the server:

```bash
cd /local/path/to/data
scp -r *.* server_user@server_ip_or_domain:absolute/path/on/server
```

> **X export files:** the filename must contain the brand name or keyword in lowercase so the extractor can match them to the correct account (e.g. `wexpand_overview.csv`).

If the database was previously set up in the legacy format, run `Migrate.py` once before anything else.

---

## Scripts

| File | Purpose |
|---|---|
| `extract.py` | Pulls raw data from X CSV exports, LinkedIn Excel exports, and the Instagram Graph API |
| `transform.py` | Generates embeddings, runs LLM-based post classification, computes UMAP projections, and extracts top engagement terms |
| `load.py` | Safely upserts DataFrames into MySQL using timestamp-guarded `INSERT … ON DUPLICATE KEY UPDATE` |
| `Migrate.py` | One-time migration from the old schema to the current one |
| `CreateDatabase.sql` | Creates the new schema and seeds lookup tables |
| `Mailer.py` | Sends alert emails via Gmail SMTP |
| `main.py` | Entry point — orchestrates extract → transform → load |

