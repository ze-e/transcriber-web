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
import tempfile

load_dotenv()
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = os.path.abspath("output")
app.config["DEBUG"] = os.getenv("FLASK_DEBUG", "false").lower() == "true"
data_source = os.getenv("DATA_SOURCE", "local").lower()  # Defaults to local storage

output_folder = os.path.abspath("output")

# Set up logging for debugging
logging.basicConfig(level=logging.DEBUG)

# Configure Cloudinary if needed
if data_source == "cloudinary":
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

    if data_source == "local":
        os.makedirs(output_folder, exist_ok=True)
        for filename in os.listdir(output_folder):
            file_path = os.path.join(output_folder, filename)
            if os.path.isfile(file_path):
                os.unlink(file_path)

    # Determine file path for local or Cloudinary storage
    if data_source == "local":
        file_path = os.path.join(output_folder, secure_filename(file.filename))
        file.save(file_path)
        audio_path = file_path
    else:
        temp_audio_path = secure_filename(file.filename)
        audio_bytes = io.BytesIO(file.read())
        audio_path = None  # Set as None initially for cloud case

    # Handle video or audio input
    audio_output = None  # Initialize audio_output for Cloudinary case
    if not file.filename.lower().endswith(('.wav', '.mp3', '.m4a')):
        # For video files, extract audio
        try:
            if data_source == "local":
                video = VideoFileClip(file_path)
                audio_path = file_path.rsplit('.', 1)[0] + '.wav'
                video.audio.write_audiofile(audio_path)
            else:
                video = VideoFileClip(audio_bytes)
                audio_output = io.BytesIO()
                video.audio.write_audiofile(audio_output)
                audio_output.seek(0)
        except Exception as e:
            return jsonify({'error': f"Error processing video file: {e}"}), 500
    else:
        # For audio files
        if data_source == "cloudinary":
            audio_output = audio_bytes

    # Transcription
    transcript_filename = file.filename.rsplit('.', 1)[0] + '_transcript.txt'
    if type == 'whisper':
        try:
            model = whisper.load_model("medium")  # or "large" if more memory is available
            
            # Handle temporary file creation for Cloudinary case
            if data_source == "local":
                audio_data_path = audio_path
            else:
                with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                    audio_data_path = temp_file.name
                    temp_file.write(audio_output.read())

            # Load and transcribe audio
            audio_data = whisper.load_audio(audio_data_path)
            result = model.transcribe(audio_data)
            transcription_text = "".join(
                f"{format_timestamp(segment['start'])} - {segment['text']}\n" for segment in result["segments"]
            )

            # Clean up temporary file if used
            if data_source == "cloudinary":
                os.remove(audio_data_path)

            if data_source == "local":
                transcript_path = os.path.join(output_folder, transcript_filename)
                with open(transcript_path, 'w') as f:
                    f.write(transcription_text)
            else:
                temp_file = io.BytesIO(transcription_text.encode("utf-8"))
                temp_file.name = transcript_filename
                cloudinary_response = cloudinary.uploader.upload(
                    temp_file, resource_type='raw', folder='transcriptions', public_id=transcript_filename
                )
                transcript_url = cloudinary_response['url']
                
        except Exception as e:
            return jsonify({'error': f"Whisper error: {e}"}), 500

    elif type == 'assembly':
        try:
            aai.settings.api_key = os.getenv("AAI_API_KEY")
            config = aai.TranscriptionConfig(speaker_labels=True)

            if data_source == "local":
                with open(audio_path, 'rb') as audio_file:
                    upload_response = aai.upload(audio_file)
                    audio_url = upload_response['upload_url']
            else:
                audio_upload = cloudinary.uploader.upload(
                    audio_output, resource_type='video', folder='audio_files', public_id=temp_audio_path
                )
                audio_url = audio_upload['url']

            transcriber = aai.Transcriber()
            result = transcriber.transcribe(audio_url, config=config)
            transcription_text = "".join(
                f"{utterance.speaker.upper()}: {utterance.text}\n" for utterance in result.utterances
            )

            if data_source == "local":
                transcript_path = os.path.join(output_folder, transcript_filename)
                with open(transcript_path, 'w') as f:
                    f.write(transcription_text)
            else:
                temp_file = io.BytesIO(transcription_text.encode("utf-8"))
                temp_file.name = transcript_filename
                cloudinary_response = cloudinary.uploader.upload(
                    temp_file, resource_type='raw', folder='transcriptions', public_id=transcript_filename
                )
                transcript_url = cloudinary_response['url']
                
        except Exception as e:
            return jsonify({'error': f"AssemblyAI error: {e}"}), 500

    return jsonify({
        'message': 'File uploaded and processed successfully',
        'transcript_url': url_for('uploaded_file', filename=transcript_filename) if data_source == "local" else transcript_url
    })

@app.route('/output/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
