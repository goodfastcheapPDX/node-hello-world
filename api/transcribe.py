# api/transcribe.py
from http.server import BaseHTTPRequestHandler
import json
import urllib.parse
import requests
import os
import tempfile
import subprocess

# Function to download audio using yt-dlp (most reliable approach)
def download_youtube_audio(video_id, output_path):
    youtube_url = f"https://www.youtube.com/watch?v={video_id}"
    
    # Construct command to download audio only, optimized for speed
    command = [
        "yt-dlp",
        "--no-check-certificate",  # Skip HTTPS certification validation
        "--no-warnings",           # Reduce output noise
        "--quiet",                 # Even less output
        "-f", "bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio", # Prioritize smaller formats
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "128K", # Lower quality = smaller file = faster upload to Whisper
        "-o", output_path,
        youtube_url
    ]
    
    # Execute the command
    process = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True
    )
    
    if process.returncode != 0:
        raise Exception(f"Error downloading audio: {process.stderr}")
    
    return process.stdout

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            # Parse query parameters
            parsed_path = urllib.parse.urlparse(self.path)
            query_params = urllib.parse.parse_qs(parsed_path.query)
            
            # Get video ID
            video_id = query_params.get('id', [''])[0]
            if not video_id:
                self.send_error(400, "Missing video ID parameter. Use ?id=VIDEO_ID")
                return
            
            # Set up temporary file for audio
            temp_dir = tempfile.gettempdir()
            temp_file_path = os.path.join(temp_dir, f"{video_id}.mp3")
            
            # Download audio using yt-dlp
            try:
                print(f"Downloading audio for {video_id}...")
                download_youtube_audio(video_id, temp_file_path)
                
                if not os.path.exists(temp_file_path):
                    self.send_error(500, "Failed to download audio file")
                    return
                    
                file_size = os.path.getsize(temp_file_path)
                print(f"Download complete: {file_size} bytes")
                
                if file_size == 0:
                    self.send_error(500, "Downloaded audio file is empty")
                    return
            except Exception as e:
                self.send_error(500, f"Error downloading audio: {str(e)}")
                return
            
            # Send to Whisper API
            print("Sending to Whisper API...")
            openai_api_key = os.environ.get("OPENAI_API_KEY")
            if not openai_api_key:
                self.send_error(500, "Missing OpenAI API key in environment variables")
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)  # Clean up
                return
            
            whisper_url = "https://api.openai.com/v1/audio/transcriptions"
            
            try:
                with open(temp_file_path, 'rb') as audio_file:
                    files = {
                        'file': (f"{video_id}.mp3", audio_file, 'audio/mp3'),
                        'model': (None, 'whisper-1'),
                        'response_format': (None, 'verbose_json')
                    }
                    
                    headers = {
                        'Authorization': f"Bearer {openai_api_key}"
                    }
                    
                    whisper_response = requests.post(whisper_url, headers=headers, files=files)
            finally:
                # Clean up the temporary file
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)
            
            if whisper_response.status_code != 200:
                self.send_error(500, f"Whisper API error: {whisper_response.text}")
                return
            
            # Process transcription result
            transcription = whisper_response.json()
            
            # Format transcript with timestamps
            formatted_transcript = ""
            if 'segments' in transcription:
                formatted_segments = []
                for segment in transcription['segments']:
                    start_time = format_time(segment['start'])
                    end_time = format_time(segment['end'])
                    formatted_segments.append(f"[{start_time} - {end_time}] {segment['text']}")
                formatted_transcript = "\n\n".join(formatted_segments)
            
            # Prepare response
            response_data = {
                "success": True,
                "video": {
                    "id": video_id,
                    "url": f"https://www.youtube.com/watch?v={video_id}"
                },
                "transcript": {
                    "full": transcription.get('text', ''),
                    "formatted": formatted_transcript,
                    "segments": transcription.get('segments', []),
                    "source": "whisper"
                }
            }
            
            # Send successful response
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response_data).encode())
            
        except Exception as e:
            print(f"Error: {str(e)}")
            self.send_error(500, f"Error processing request: {str(e)}")

def format_time(seconds):
    """Format seconds as HH:MM:SS"""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hrs:02d}:{mins:02d}:{secs:02d}"