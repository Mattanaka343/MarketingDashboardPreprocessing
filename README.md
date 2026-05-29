# ETL and Database Migration

This repository contains all necessary codes and files to accurately load and migrate from the old nurai/wexpand social media database into the new schema.

## Setup

The recommended setup in order to use this repository is the following

```{bash}
conda create -n etl-env python=3.12
conda activate etl-env

pip install -r requirements.txt

curl -fsSL https://ollama.com/install.sh | sh

ollama serve
ollama pull your-embedding-model
ollama pull your-llm
```

Alternatively if you prefer venv

```{bash}
python3 -m venv etl-env
source mkt-dash-env/bin/activate
pip install -r requirements.txt

curl -fsSL https://ollama.com/install.sh | sh

ollama serve
ollama pull your-embedding-model
ollama pull your-llm
```

Note that if you are running this on MacOs you need to run `ollama serve` in a separate terminal window and keep it running while running the codes. Additionally you need to setup a `.env` 
file with the following information:
```{}
DATABASE_USER=your_user
MYSQL_PASSWORD=your_password
GMAIL_USER=your_gmail@gmail.com
GMAIL_APP_PASSWORD=your_app_password
NOTIFY_TO=mail_to_notify_to@domain.com
GOOGLE_APPLICATION_CREDENTIALS=path_to_your_credentials
IG_ACCESS_TOKEN=your_ig_access_token
IG_USER_ID=your_ig_user_id
EMBED_MODEL=your_embedding_model (recommended: nomic-embed-text)
LLM_MODEL=your_llm?=_model (recommended: qwen2.5:7b)
```

## Scripts

This repository contains the following scripts:

- `extract.py`: extracts the data from the different sources
- `transform.py`: adds embeddings to the posts data, obtains the key terms based on engagement for each of the brands
- `load.py`: safely upserts the data into the sql schema
- `Migrate.py`: migrates the data from the old schema into the new schema
- `CreateDatabase.sql`: creates the *new* sql schema and fills the small tables with the preknown information
- `Mailer.py`: handles the sending of alerts.
- `main.py`: is the file to be run. It unites the logic of all the other files

Now we'll continue with per file descriptions of what functions they contain and what it is they do.

## Extract

Extracts the data from the excel files, csv files and  (TBD) google analytics + meta api.  The file has the following functions

