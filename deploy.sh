rsync -r \
    --exclude __pycache__ --exclude venv \
    src requirements.txt run.sh mock.sh settings.example.ini logging.ini renksu:renksu/
