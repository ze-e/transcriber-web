# Use the official Python 3.10 image as the base image
FROM python:3.10-slim

# Install system dependencies including ffmpeg and git
RUN apt-get update && \
    apt-get install -y ffmpeg git && \
    apt-get clean

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Create and set the working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Expose port 8080 for Google Cloud Run
EXPOSE 8080

# Command to run the Flask app with Gunicorn
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:8080", "--timeout", "120", "app:app"]
