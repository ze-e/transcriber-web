from flask import Flask, request, render_template, jsonify, send_from_directory, url_for
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
import io

load_dotenv()
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = os.path.abspath("output")
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB limit
app.config["DEBUG"] = os.getenv("FLASK_DEBUG", "false").lower() == "true"

output_folder = os.path.abspath("output")

# Set up logging for debugging
logging.basicConfig(level=logging.DEBUG)

# Load Cloudinary configuration
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
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
    data_source = os.getenv("DATA_SOURCE", "local").lower()  # Get data source from environment variable

    # Ensure the output directory exists for local storage
    if data_source == "local":
        os.makedirs(output_folder, exist_ok=True)
        # Delete all files in the output directory
        for filename in os.listdir(output_folder):
            file_path = os.path.join(output_folder, filename)
            if os.path.isfile(file_path):
                os.unlink(file_path)

    # Debug log to check directory status
    logging.debug(f"Output folder exists: {os.path.exists(output_folder)}")
    logging.debug(f"Output folder path: {output_folder}")

    # Determine if the uploaded file is audio or video
    file_path = os.path.join(output_folder, secure_filename(file.filename))
    os.makedirs(os.path.dirname(file_path), exist_ok=True)  # Ensure directory exists
    file.save(file_path)

    if file.filename.lower().endswith(('.wav', '.mp3', '.m4a')):
        audio_path = file_path
    else:
        # For video files, extract audio
        try:
            video = VideoFileClip(file_path)
            audio_path = file_path.rsplit('.', 1)[0] + '.wav'
            video.audio.write_audiofile(audio_path)
        except Exception as e:
            return jsonify({'error': f"Error processing video file: {e}"}), 500

    # Process transcription
    transcript_filename = file.filename.rsplit('.', 1)[0] + '_transcript.txt'
    transcript_path = os.path.join(output_folder, transcript_filename)

    if type == 'whisper':
        try:
            model = whisper.load_model("medium")
            audio_data = whisper.load_audio(audio_path)
            result = model.transcribe(audio_data)
            transcription_text = "".join(
                f"{format_timestamp(segment['start'])} - {segment['text']}\n" for segment in result["segments"]
            )

            with open(transcript_path, 'w') as f:
                f.write(transcription_text)
                
        except Exception as e:
            return jsonify({'error': f"Whisper error: {e}"}), 500

    elif type == 'assembly':
        try:
            aai.settings.api_key = os.getenv("AAI_API_KEY")
            config = aai.TranscriptionConfig(speaker_labels=True)

            audio_url = None
            with open(audio_path, 'rb') as audio_file:
                upload_response = aai.upload(audio_file)
                audio_url = upload_response['upload_url']

            transcriber = aai.Transcriber()
            result = transcriber.transcribe(audio_url, config=config)
            transcription_text = "".join(
                f"{utterance.speaker.upper()}: {utterance.text}\n" for utterance in result.utterances
            )

            with open(transcript_path, 'w') as f:
                f.write(transcription_text)

        except Exception as e:
            return jsonify({'error': f"AssemblyAI error: {e}"}), 500

    return jsonify({
        'message': 'File uploaded and processed successfully',
        'transcript_url': url_for('uploaded_file', filename=transcript_filename)
    })

@app.route('/output/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
