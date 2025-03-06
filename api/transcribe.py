# api/transcribe.py
from http.server import BaseHTTPRequestHandler
import json
import urllib.parse
import requests
import os
import tempfile

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
            
            # Use a reliable public API to get the audio URL
            # The example below uses yt-api.p.rapidapi.com, but you can replace with any similar service
            print(f"Getting audio URL for video ID: {video_id}")
            
            audio_url, video_title = self.get_audio_url(video_id)
            if not audio_url:
                self.send_error(500, "Failed to get audio URL")
                return
                
            print(f"Got audio URL for '{video_title}'")
            
            # Download the audio file
            print(f"Downloading audio from URL...")
            try:
                audio_response = requests.get(audio_url, stream=True)
                if audio_response.status_code != 200:
                    self.send_error(500, f"Failed to download audio: {audio_response.status_code}")
                    return
                
                # Save to a temporary file
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
                temp_file_path = temp_file.name
                
                # Write the audio data to the temporary file
                for chunk in audio_response.iter_content(chunk_size=8192):
                    if chunk:
                        temp_file.write(chunk)
                temp_file.close()
                
                file_size = os.path.getsize(temp_file_path)
                print(f"Audio downloaded: {file_size} bytes")
                
            except Exception as e:
                self.send_error(500, f"Error downloading audio: {str(e)}")
                return
            
            # Send to Whisper API
            print("Sending to Whisper API...")
            openai_api_key = os.environ.get("OPENAI_API_KEY")
            if not openai_api_key:
                self.send_error(500, "Missing OpenAI API key in environment variables")
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)
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
    
    def get_audio_url(self, video_id):
        """Get audio URL using a public API service"""
        # OPTION 1: RapidAPI YouTube MP3 Converter
        api_url = f"https://youtube-mp36.p.rapidapi.com/dl"
        headers = {
            "X-RapidAPI-Key": os.environ.get("RAPIDAPI_KEY"),
            "X-RapidAPI-Host": "youtube-mp36.p.rapidapi.com"
        }
        
        params = {"id": video_id}
        
        try:
            response = requests.get(api_url, headers=headers, params=params)
            if response.status_code != 200:
                print(f"API call failed: {response.text}")
                return self.fallback_audio_url(video_id)
            
            data = response.json()
            if data.get("status") == "ok" and "link" in data:
                return data["link"], data.get("title", "Unknown")
            else:
                print(f"API returned invalid data: {data}")
                return self.fallback_audio_url(video_id)
                
        except Exception as e:
            print(f"Error with primary API: {str(e)}")
            return self.fallback_audio_url(video_id)
    
    def fallback_audio_url(self, video_id):
        """Fallback method to get audio URL"""
        # OPTION 2: Alternative API
        api_url = f"https://youtube-mp3-download1.p.rapidapi.com/dl"
        headers = {
            "X-RapidAPI-Key": os.environ.get("RAPIDAPI_KEY"),
            "X-RapidAPI-Host": "youtube-mp3-download1.p.rapidapi.com"
        }
        
        params = {"id": video_id}
        
        try:
            response = requests.get(api_url, headers=headers, params=params)
            if response.status_code != 200:
                print(f"Fallback API call failed: {response.text}")
                return None, "Unknown"
            
            data = response.json()
            if "link" in data:
                return data["link"], data.get("title", "Unknown")
            else:
                print(f"Fallback API returned invalid data: {data}")
                return None, "Unknown"
                
        except Exception as e:
            print(f"Error with fallback API: {str(e)}")
            return None, "Unknown"

def format_time(seconds):
    """Format seconds as HH:MM:SS"""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hrs:02d}:{mins:02d}:{secs:02d}"