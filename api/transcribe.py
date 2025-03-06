# api/transcribe.py
from http.server import BaseHTTPRequestHandler
import json
import urllib.parse
import requests
import os
import io
import tempfile
from y2mate_api import Handler, session

# Set up the cf_clearance cookie for y2mate-api
CF_CLEARANCE = os.environ.get("CF_CLEARANCE")
if CF_CLEARANCE:
    session.cookies.update({"cf_clearance": CF_CLEARANCE})

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
            
            # Initialize y2mate Handler with the video ID
            api = Handler(video_id)
            
            # Get the audio URL (mp3 format for better compatibility with Whisper)
            audio_data = None
            for item in api.run(format="mp3"):
                audio_data = item
                break  # Take the first result
            
            if not audio_data or 'dlink' not in audio_data:
                self.send_error(404, "Could not extract audio URL for this video")
                return
            
            video_title = audio_data.get('title', 'Unknown Title')
            audio_url = audio_data.get('dlink')
            
            print(f"Got audio URL for video: {video_title}")
            
            # Download the audio file
            print(f"Downloading audio from URL...")
            audio_response = requests.get(audio_url, stream=True)
            
            if audio_response.status_code != 200:
                self.send_error(500, f"Failed to download audio: {audio_response.status_code}")
                return
            
            # Save to a temporary file
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_file:
                for chunk in audio_response.iter_content(chunk_size=8192):
                    if chunk:
                        temp_file.write(chunk)
                temp_file_path = temp_file.name
            
            print(f"Audio saved to temporary file: {temp_file_path}")
            
            # Send to Whisper API
            print("Sending to Whisper API...")
            openai_api_key = os.environ.get("OPENAI_API_KEY")
            if not openai_api_key:
                self.send_error(500, "Missing OpenAI API key in environment variables")
                os.unlink(temp_file_path)  # Clean up temp file
                return
            
            whisper_url = "https://api.openai.com/v1/audio/transcriptions"
            
            with open(temp_file_path, 'rb') as audio_file:
                files = {
                    'file': (f"{video_id}.mp3", audio_file, 'audio/mpeg'),
                    'model': (None, 'whisper-1'),
                    'response_format': (None, 'verbose_json')
                }
                
                headers = {
                    'Authorization': f"Bearer {openai_api_key}"
                }
                
                whisper_response = requests.post(whisper_url, headers=headers, files=files)
            
            # Clean up temporary file
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
                    "title": video_title,
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
