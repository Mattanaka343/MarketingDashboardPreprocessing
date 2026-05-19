# ETL and Database Migration

This repository contains all necessary codes and files to accurately load and migrate from the old nurai/wexpand social media database into the new schema.

## Setup

The recommended setup in order to use this repository is the following

```{bash}
conda create -n etl-env python=3.12
conda activate etl-env

pip install -r requirements.txt

curl -fsSL https://ollama.com/install.sh | sh

ollama pull your-embedding-model
ollama pull your-llm
```

