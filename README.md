# FLEETI OpenAI

## Running the API

To run the API server, use the following command:

```bash
uvicorn api:app --reload
```

Or to specify host and port:

```bash
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```


rasa
cd rasaFleeti
rasa run --enable-api
rasa run actions
