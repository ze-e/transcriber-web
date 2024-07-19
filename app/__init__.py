from flask import Flask, request, render_template, jsonify, send_from_directory, abort
import assemblyai as aai
from moviepy.editor import VideoFileClip
import whisper
import os
from dotenv import load_dotenv
from utils import format_timestamp

load_dotenv()
app = Flask(__name__)
app.config["DEBUG"] = os.environ.get("FLASK_DEBUG")

output_folder = os.path.abspath("output")

@app.route('/', methods=['GET'])
def home():
    return render_template('upload.html')

@app.route('/test', methods=['GET'])
def home():
    return "test"

@app.route('/upload', methods=['POST'])
def upload_file():
    file = request.files['file']
    type = request.args.get('transcriber', 'assembly').lower()
    # Ensure the output directory exists
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    # Delete all files in the output directory
    for filename in os.listdir(output_folder):
        file_path = os.path.join(output_folder, filename)
        if os.path.isfile(file_path):
            os.unlink(file_path)

    file_path = os.path.join(output_folder, file.filename)
    file.save(file_path)

    if file.filename.lower().endswith('.wav') or file.filename.lower().endswith('.mp3') or file.filename.lower().endswith('.m4a'):
        audio_path = file_path
    else:
        video = VideoFileClip(file_path)
        audio_path = file_path.rsplit('.', 1)[0] + '.wav'
        video.audio.write_audiofile(audio_path)

    # transcribe
    transcript_filename = file.filename.rsplit('.', 1)[0] + '_transcript.txt'
    transcript_path = os.path.join(output_folder, transcript_filename)
    if type == 'whisper':
        model = whisper.load_model("medium")
        result = model.transcribe(audio_path)
        with open(transcript_path, 'w') as f:
            with open(transcript_path, 'w') as f:
                for segment in result["segments"]:
                    start_time = segment["start"]
                    text = segment["text"]
                    f.write(f"{format_timestamp(start_time)} - {text}\n")
    
    elif type == 'assembly':
        aai.settings.api_key = os.environ.get("AAI_API_KEY")
        config = aai.TranscriptionConfig(speaker_labels=True)
        transcriber = aai.Transcriber()
        result = transcriber.transcribe(
            audio_path,
            config=config
        )

        with open(transcript_path, 'w') as f:
            for utterance in result.utterances:
                f.write(f"{utterance.speaker.upper()}: {utterance.text}\n")
    else:
        raise Exception("No transcriber type found")
    transcript_url = request.host_url + 'output/' + transcript_filename
    return jsonify({'message': 'File uploaded and processed successfully', 'transcript_url': transcript_url}), 200

@app.route('/output/<filename>')
def download_file(filename):
    file_path = os.path.join(output_folder, filename)
    if not os.path.exists(file_path):
        abort(404)  
    return send_from_directory(output_folder, filename, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True, port=5002)
