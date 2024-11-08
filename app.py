from flask import Flask, request, render_template, jsonify, send_from_directory, url_for
import assemblyai as aai
from moviepy.editor import VideoFileClip
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

# Set AssemblyAI API key
aai.settings.api_key = os.getenv("AAI_API_KEY")

@app.route('/', methods=['GET'])
def home():
    return render_template('upload.html')

@app.route('/test', methods=['GET'])
def test():
    return "Hello World"

@app.route('/upload', methods=['POST'])
def upload_file():
    file = request.files['file']
    filename = secure_filename(file.filename)  # Use filename for file type checks

    # Prepare local or Cloudinary storage
    if data_source == "local":
        os.makedirs(output_folder, exist_ok=True)
        for f in os.listdir(output_folder):
            file_path = os.path.join(output_folder, f)
            if os.path.isfile(file_path):
                os.unlink(file_path)
        file_path = os.path.join(output_folder, filename)
        file.save(file_path)
        audio_path = file_path
    else:
        audio_bytes = io.BytesIO(file.read())
        temp_audio_path = filename

    # Handle video or audio input based on filename (not audio_bytes)
    if not filename.lower().endswith(('.wav', '.mp3', '.m4a')):
        # Process video files by extracting audio
        try:
            if data_source == "local":
                # Local: Extract audio from video file saved on disk
                video = VideoFileClip(file_path)
                audio_path = file_path.rsplit('.', 1)[0] + '.wav'
                video.audio.write_audiofile(audio_path)
                video.close()  # Close the VideoFileClip to release the file
            else:
                # Cloudinary or BytesIO: Save BytesIO video to a temp file for VideoFileClip
                with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as temp_video_file:
                    temp_video_file.write(audio_bytes.getvalue())
                    temp_video_path = temp_video_file.name

                # Load video from the temporary file and extract audio to another temp file
                video = VideoFileClip(temp_video_path)
                with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as temp_audio_file:
                    temp_audio_path = temp_audio_file.name
                video.audio.write_audiofile(temp_audio_path)
                video.close()  # Close the VideoFileClip to release the file

                # Delete the temporary video file
                os.remove(temp_video_path)

                # Set audio_output to read from the saved audio file for uploading
                with open(temp_audio_path, 'rb') as audio_file:
                    audio_output = io.BytesIO(audio_file.read())
                os.remove(temp_audio_path)  # Delete the temporary audio file
                audio_output.seek(0)

                # Generate a simple Cloudinary-compatible public_id
                cloudinary_public_id = os.path.splitext(temp_audio_path)[0].replace("\\", "/").split("/")[-1]
        except Exception as e:
            return jsonify({'error': f"Error processing video file: {e}"}), 500
    else:
        # If it’s an audio file, set audio_output for Cloudinary upload
        if data_source == "cloudinary":
            audio_output = audio_bytes
            cloudinary_public_id = os.path.splitext(filename)[0]

    # Upload audio to AssemblyAI
    try:
        if data_source == "local":
            with open(audio_path, 'rb') as audio_file:
                upload_response = aai.upload(audio_file)
                audio_url = upload_response['upload_url']
        else:
            # Upload the audio to Cloudinary with a compatible public_id
            cloudinary_response = cloudinary.uploader.upload(
                audio_output, resource_type='video', folder='audio_files', public_id=cloudinary_public_id
            )
            audio_url = cloudinary_response['url']

        # Transcription request to AssemblyAI
        transcriber = aai.Transcriber()
        config = aai.TranscriptionConfig(speaker_labels=True)
        result = transcriber.transcribe(audio_url, config=config)
        transcription_text = "".join(
            f"{utterance.speaker.upper()}: {utterance.text}\n" for utterance in result.utterances
        )

        # Store or upload transcription
        transcript_filename = filename.rsplit('.', 1)[0] + '_transcript.txt'
        if data_source == "local":
            transcript_path = os.path.join(output_folder, transcript_filename)
            with open(transcript_path, 'w') as f:
                f.write(transcription_text)
            logging.info(f"Transcription successful! File saved locally at {transcript_path}")
        else:
            temp_file = io.BytesIO(transcription_text.encode("utf-8"))
            temp_file.name = transcript_filename
            cloudinary_response = cloudinary.uploader.upload(
                temp_file, resource_type='raw', folder='transcriptions', public_id=transcript_filename
            )
            transcript_url = cloudinary_response['url']
            logging.info(f"Transcription successful! File uploaded to Cloudinary at {transcript_url}")
                
    except Exception as e:
        return jsonify({'error': f"AssemblyAI error: {e}"}), 500

    return jsonify({
        'message': 'File uploaded and processed successfully',
        'transcript_url': url_for('uploaded_file', filename=transcript_filename) if data_source == "local" else transcript_url
    })

@app.route('/output/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# Ensure the app listens on PORT 8080 for Google Cloud Run
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)), debug=True)
