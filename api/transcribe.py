# api/transcribe.py
from http.server import BaseHTTPRequestHandler
import json
import urllib.parse
import requests
import os
import tempfile
import time
from datetime import datetime

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
            
            # Get optional parameters
            start_time = int(query_params.get('start', ['0'])[0])
            max_duration = int(query_params.get('duration', ['7200'])[0])  # Default: 2 hours
            
            # Use RapidAPI to get audio URL
            print(f"Getting audio URL for video ID: {video_id}")
            
            audio_url, video_title = self.get_audio_url(video_id)
            if not audio_url:
                self.send_error(500, "Failed to get audio URL")
                return
                
            print(f"Got audio URL for '{video_title}'")
            
            # Process the audio in chunks
            total_transcript = ""
            formatted_segments = []
            all_segments = []
            
            # If processing just a segment of the video
            current_start = start_time
            end_time = start_time + max_duration
            
            print(f"Processing audio segment: {format_time(current_start)} to {format_time(end_time)}")
            
            # Download the audio segment
            audio_file_path = self.download_audio_segment(audio_url, video_id, current_start, max_duration)
            if not audio_file_path:
                self.send_error(500, "Failed to download audio segment")
                return
            
            # Get the file size
            file_size = os.path.getsize(audio_file_path)
            print(f"Audio segment downloaded: {file_size} bytes")
            
            # Check if file is too large for Whisper API (25MB limit)
            if file_size > 24 * 1024 * 1024:  # 24MB to be safe
                os.unlink(audio_file_path)
                self.send_error(500, "Audio file too large for Whisper API. Try a shorter duration.")
                return
                
            # Process with Whisper API
            try:
                segment_transcript, segment_formatted, segment_data = self.process_with_whisper(
                    audio_file_path, video_id, current_start
                )
                
                total_transcript += segment_transcript + " "
                formatted_segments.extend(segment_formatted)
                all_segments.extend(segment_data)
            finally:
                # Clean up the temporary file
                if os.path.exists(audio_file_path):
                    os.unlink(audio_file_path)
                
            # Prepare response
            response_data = {
                "success": True,
                "video": {
                    "id": video_id,
                    "title": video_title,
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "processed_segment": {
                        "start": start_time,
                        "duration": max_duration,
                        "end": end_time
                    }
                },
                "transcript": {
                    "full": total_transcript.strip(),
                    "formatted": "\n\n".join(formatted_segments),
                    "segments": all_segments,
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
        # RapidAPI YouTube MP3 Converter
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
        # Alternative API
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
    
    def download_audio_segment(self, audio_url, video_id, start_seconds, duration_seconds):
        """Download a segment of the audio file"""
        try:
            # Create a temporary file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
            temp_file_path = temp_file.name
            temp_file.close()
            
            print(f"Downloading audio from URL...")
            
            # Using FFmpeg-compatible services, we could add parameters to the URL
            # But since we're using a third-party service, we'll download the full file
            audio_response = requests.get(audio_url, stream=True)
            if audio_response.status_code != 200:
                print(f"Failed to download audio: {audio_response.status_code}")
                return None
            
            # Write the audio data to the temporary file
            with open(temp_file_path, 'wb') as f:
                for chunk in audio_response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            return temp_file_path
            
        except Exception as e:
            print(f"Error downloading audio segment: {str(e)}")
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
            return None
    
    def process_with_whisper(self, audio_file_path, video_id, start_offset=0):
        """Process audio file with Whisper API"""
        print("Sending to Whisper API...")
        openai_api_key = os.environ.get("OPENAI_API_KEY")
        if not openai_api_key:
            raise Exception("Missing OpenAI API key in environment variables")
        
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
            
            whisper_response = requests.post(whisper_url, headers=headers, files=files)
        
        if whisper_response.status_code != 200:
            raise Exception(f"Whisper API error: {whisper_response.text}")
        
        # Process transcription result
        transcription = whisper_response.json()
        
        # Format transcript with timestamps adjusted for segment start time
        formatted_segments = []
        all_segments = []
        
        if 'segments' in transcription:
            for segment in transcription['segments']:
                # Adjust timestamps for the segment's position in the full video
                adjusted_start = segment['start'] + start_offset
                adjusted_end = segment['end'] + start_offset
                
                # Create a formatted string with timestamps
                start_time_str = format_time(adjusted_start)
                end_time_str = format_time(adjusted_end)
                formatted_segments.append(f"[{start_time_str} - {end_time_str}] {segment['text']}")
                
                # Add the adjusted segment to the full list
                adjusted_segment = segment.copy()
                adjusted_segment['start'] = adjusted_start
                adjusted_segment['end'] = adjusted_end
                all_segments.append(adjusted_segment)
        
        return transcription.get('text', ''), formatted_segments, all_segments

def format_time(seconds):
    """Format seconds as HH:MM:SS"""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hrs:02d}:{mins:02d}:{secs:02d}"