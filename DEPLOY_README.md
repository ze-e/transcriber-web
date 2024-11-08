gcloud builds submit --tag gcr.io/[project-id]/transcriber-app


gcloud run deploy transcriber-app \
  --image gcr.io/[project-id]/transcriber-app \
  --platform managed \
  --region us-central1 \
  --memory=2Gi \
  --allow-unauthenticated
