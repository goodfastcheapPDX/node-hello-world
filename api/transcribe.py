# api/transcribe.py
from http.server import BaseHTTPRequestHandler
import json
import urllib.parse
import requests
import os
import tempfile
import re

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
            
            # Get time segment parameters
            start_time = int(query_params.get('start', ['0'])[0])
            duration = int(query_params.get('duration', ['7200'])[0])  # Default 2 hours (7200 seconds)
            
            # Calculate end time
            end_time = start_time + duration
            
            print(f"Processing video {video_id} from {format_time(start_time)} to {format_time(end_time)}")
            
            # Get video info to include title
            video_title = self.get_video_title(video_id)
            
            # Create a YouTube URL with time parameters
            youtube_url = f"https://www.youtube.com/watch?v={video_id}&t={start_time}s"
            
            # Get audio URL for this time segment
            audio_url = self.get_audio_url_for_segment(video_id, start_time, duration)
            if not audio_url:
                self.send_error(500, "Failed to get audio URL for the specified segment")
                return
            
            print(f"Got audio URL for segment")
            
            # Download the audio
            temp_file_path = self.download_audio(audio_url)
            if not temp_file_path:
                self.send_error(500, "Failed to download audio")
                return
            
            print(f"Downloaded audio: {os.path.getsize(temp_file_path)} bytes")
            
            # Transcribe with Whisper
            try:
                transcript_data = self.transcribe_with_whisper(temp_file_path, video_id)
                
                # Adjust timestamps to account for the segment start time
                adjusted_segments = []
                formatted_segments = []
                
                if 'segments' in transcript_data:
                    for segment in transcript_data['segments']:
                        # Adjust time stamps
                        segment['start'] += start_time
                        segment['end'] += start_time
                        adjusted_segments.append(segment)
                        
                        # Create formatted transcript
                        start_str = format_time(segment['start'])
                        end_str = format_time(segment['end'])
                        formatted_segments.append(f"[{start_str} - {end_str}] {segment['text']}")
                
                # Prepare response
                response_data = {
                    "success": True,
                    "video": {
                        "id": video_id,
                        "title": video_title,
                        "url": f"https://www.youtube.com/watch?v={video_id}",
                        "segment": {
                            "start": start_time,
                            "end": end_time,
                            "duration": duration
                        }
                    },
                    "transcript": {
                        "full": transcript_data.get('text', ''),
                        "formatted": "\n\n".join(formatted_segments),
                        "segments": adjusted_segments,
                        "source": "whisper"
                    }
                }
                
                # Send successful response
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response_data).encode())
                
            except Exception as e:
                self.send_error(500, f"Transcription error: {str(e)}")
            finally:
                # Clean up temp file
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)
                
        except Exception as e:
            print(f"Error: {str(e)}")
            self.send_error(500, f"Error processing request: {str(e)}")
    
    def get_video_title(self, video_id):
        """Get video title from YouTube"""
        try:
            # Use YouTube oEmbed API - doesn't require API key
            url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()
                return data.get('title', 'Unknown Title')
            else:
                return "Unknown Title"
        except:
            return "Unknown Title"
    
    def get_audio_url_for_segment(self, video_id, start_time, duration):
        """Get audio URL for a specific time segment"""
        # Multiple API options to try
        
        # Option 1: YouTube MP3 Converter with timestamp
        try:
            api_url = "https://youtube-mp36.p.rapidapi.com/dl"
            params = {
                "id": video_id,
                "start": start_time,  # Some APIs support start/end params
                "duration": duration
            }
            headers = {
                "X-RapidAPI-Key": os.environ.get("RAPIDAPI_KEY"),
                "X-RapidAPI-Host": "youtube-mp36.p.rapidapi.com"
            }
            
            response = requests.get(api_url, headers=headers, params=params)
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "ok" and "link" in data:
                    return data["link"]
        except Exception as e:
            print(f"Error with first API: {str(e)}")
        
        # Option 2: Alternative API
        try:
            api_url = "https://youtube-mp3-download1.p.rapidapi.com/dl"
            params = {
                "id": video_id
            }
            headers = {
                "X-RapidAPI-Key": os.environ.get("RAPIDAPI_KEY"),
                "X-RapidAPI-Host": "youtube-mp3-download1.p.rapidapi.com"
            }
            
            response = requests.get(api_url, headers=headers, params=params)
            if response.status_code == 200:
                data = response.json()
                if "link" in data:
                    return data["link"]
        except Exception as e:
            print(f"Error with second API: {str(e)}")
        
        # Option 3: Direct extraction approach
        try:
            # Create a YouTube URL with time parameters
            youtube_url = f"https://www.youtube.com/watch?v={video_id}&t={start_time}s"
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9"
            }
            
            response = requests.get(youtube_url, headers=headers)
            if response.status_code != 200:
                return None
                
            html = response.text
            
            # Try to find audio URLs in the page
            # This is a simplified approach - actual extraction would be more complex
            audio_url_match = re.search(r'"url":"(https:\/\/r[0-9]---sn[^"]+)"', html)
            if audio_url_match:
                return audio_url_match.group(1).replace('\\u0026', '&')
        except Exception as e:
            print(f"Error with direct extraction: {str(e)}")
            
        # If all methods fail
        return None
    
    def download_audio(self, audio_url):
        """Download audio file from URL"""
        try:
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
            temp_file_path = temp_file.name
            temp_file.close()
            
            response = requests.get(audio_url, stream=True)
            if response.status_code != 200:
                return None
                
            with open(temp_file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        
            return temp_file_path
        except Exception as e:
            print(f"Error downloading audio: {str(e)}")
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
            return None
    
    def transcribe_with_whisper(self, audio_file_path, video_id):
        """Transcribe audio using Whisper API"""
        openai_api_key = os.environ.get("OPENAI_API_KEY")
        if not openai_api_key:
            raise Exception("Missing OpenAI API key")
        
        whisper_url = "https://api.openai.com/v1/audio/transcriptions"
        
        with open(audio_file_path, 'rb') as audio_file:
            files = {
                'file': (f"{video_id}.mp3", audio_file, 'audio/mp3'),
                'model': (None, 'whisper-1'),
                'response_format': (None, 'verbose_json')
            }
            
            headers = {
                'Authorization': f"Bearer {openai_api_key}"
            }
            
            response = requests.post(whisper_url, headers=headers, files=files)
        
        if response.status_code != 200:
            raise Exception(f"Whisper API error: {response.text}")
            
        return response.json()

def format_time(seconds):
    """Format seconds as HH:MM:SS"""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hrs:02d}:{mins:02d}:{secs:02d}"