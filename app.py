from flask import Flask, request, render_template, jsonify, send_from_directory, abort, url_for
import assemblyai as aai
from moviepy.editor import VideoFileClip
import whisper
import os
from dotenv import load_dotenv
from utils import format_timestamp
from werkzeug.utils import secure_filename
import logging
import cloudinary
import cloudinary.uploader
import numpy as np
import torch

load_dotenv()
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = os.path.abspath("output")
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 * 1024  # 16 GB limit
app.config["DEBUG"] = os.environ.get("FLASK_DEBUG")

output_folder = os.path.abspath("output")

# Load Cloudinary configuration
cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET")
)

@app.route('/', methods=['GET'])
def home():
    return render_template('upload.html')

@app.route('/test', methods=['GET'])
def test():
    return "Hello World"

@app.route('/upload', methods=['POST'])
def upload_file():
    file = request.files['file']
    type = request.args.get('transcriber', 'assembly').lower()
    data_source = os.environ.get("data_source", "local")  # Get data source from environment variable

    # Ensure the output directory exists for local storage
    if data_source == "local":
        if not os.path.exists(output_folder):
            os.makedirs(output_folder)

        # Delete all files in the output directory
        for filename in os.listdir(output_folder):
            file_path = os.path.join(output_folder, filename)
            if os.path.isfile(file_path):
                os.unlink(file_path)

    # Save the uploaded file
    file_path = os.path.join(output_folder, secure_filename(file.filename)) if data_source == "local" else None
    if data_source == "local":
        print("file save")
        file.save(file_path)

    # Determine if the uploaded file is audio or video
    if file.filename.lower().endswith('.wav') or file.filename.lower().endswith('.mp3') or file.filename.lower().endswith('.m4a'):
        logging.info("Found audio file")
        print("found audio")
        audio_path = file_path if data_source == "local" else None
    else:
        logging.info("Found video file")
        video = VideoFileClip(file_path)
        audio_path = file_path.rsplit('.', 1)[0] + '.wav' if data_source == "local" else None
        logging.info("Extracting audio...")
        video.audio.write_audiofile(audio_path)

    # If data_source is not local, use the uploaded file directly for transcription
    if data_source != "local":
        # Save the uploaded file temporarily to a path
        temp_audio_path = os.path.join(output_folder, secure_filename(file.filename))
        file.save(temp_audio_path)
        audio_path = temp_audio_path  # Use the saved file path for transcription

    # transcribe
    transcript_filename = file.filename.rsplit('.', 1)[0] + '_transcript.txt'
    transcript_path = os.path.join(output_folder, transcript_filename) if data_source == "local" else None

    if type == 'whisper':
        print("whisper")
        logging.info("Transcribing with whisper...")
        try:
            model = whisper.load_model("medium")
            # Load audio file into a NumPy array
            audio_data = whisper.load_audio(audio_path)  # Load audio data
            result = model.transcribe(audio_data)  # Use audio data directly
            if data_source == "local":
                with open(transcript_path, 'w') as f:
                    print("Writing transcription...")
                    for segment in result["segments"]:
                        start_time = segment["start"]
                        text = segment["text"]
                        f.write(f"{format_timestamp(start_time)} - {text}\n")
                logging.info(f"Transcription saved to {transcript_path}")
            else:
                # Upload to Cloudinary
                print("cloudinary")
                transcription_text = ""
                for segment in result["segments"]:
                    start_time = segment["start"]
                    text = segment["text"]
                    transcription_text += f"{format_timestamp(start_time)} - {text}\n"
                cloudinary_response = cloudinary.uploader.upload(transcription_text, resource_type='raw', folder='transcriptions', public_id=transcript_filename)
                transcript_url = cloudinary_response['url']
                logging.info(f"Transcription uploaded to Cloudinary: {transcript_url}")

        except Exception as e:
            message = f"Whisper error: {e}"
            logging.error(message)
            return jsonify({'error': message}), 500
    
    elif type == 'assembly':
        logging.info("Transcribing with assembly...")
        try:
            aai.settings.api_key = os.environ.get("AAI_API_KEY")
            config = aai.TranscriptionConfig(speaker_labels=True)

            # Initialize audio_url
            audio_url = None

            if data_source == "cloudinairy":
                logging.info("Uploading audio file to AssemblyAI...")
                try:
                    with open(audio_path, 'rb') as audio_file:
                        upload_response = aai.upload(audio_file)
                        logging.info(f"Upload response: {upload_response}")
                        audio_url = upload_response['upload_url']
                except Exception as e:
                    message = f"Failed to upload audio file: {e}"
                    logging.error(message)
                    return jsonify({'error': message}), 500
            else:
                # If local, set audio_url to the local path
                audio_url = audio_path

            # Now transcribe using the audio_url
            transcriber = aai.Transcriber()
            result = transcriber.transcribe(audio_url, config=config)

            if data_source == "local":
                with open(transcript_path, 'w') as f:
                    print("Writing transcription...")
                    for utterance in result.utterances:
                        f.write(f"{utterance.speaker.upper()}: {utterance.text}\n")
                logging.info(f"Transcription saved to {transcript_path}")
            else:
                # Upload to Cloudinary
                transcription_text = ""
                for utterance in result.utterances:
                    transcription_text += f"{utterance.speaker.upper()}: {utterance.text}\n"
                cloudinary_response = cloudinary.uploader.upload(transcription_text, resource_type='raw', folder='transcriptions', public_id=transcript_filename)
                transcript_url = cloudinary_response['url']
                logging.info(f"Transcription uploaded to Cloudinary: {transcript_url}")

        except Exception as e:
            message = f"AssemblyAI error: {e}"
            logging.error(message)
            return jsonify({'error': message}), 500
    else:
        raise Exception("No transcriber type found")

    # Return the appropriate URL based on the data source
    if data_source == "local":
        return jsonify({'message': 'File uploaded and processed successfully', 'transcript_url': url_for('uploaded_file', filename=transcript_filename)})
    else:
        return jsonify({'message': 'File uploaded and processed successfully', 'transcript_url': transcript_url})

@app.route('/output/<filename>')
def uploaded_file(filename):
    logging.info(f'Requesting uploaded file: {filename}')
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

