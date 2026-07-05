```
# Using ubuntu

1. pip install -r requirements.txt
2. sudo apt install tesseract-ocr
3. uvicorn main:app --workers 2
```

```
# Using docker
2. docker compose up
```

```
# .env

1. set the OLLAMA_URL
1.1 if you run the api via docker set the OLLAMA_URL=http://host.docker.internal:11434
1.1 if you run the api locally set the OLLAMA_URL=http://localhost:11434
```