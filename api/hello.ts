// api/transcribe.js - Vercel Serverless Function
// This function extracts audio from a YouTube video and transcribes it using OpenAI's Whisper API

import { createReadStream, createWriteStream, unlinkSync } from 'fs';
import { join } from 'path';
import { execSync } from 'child_process';
import { tmpdir } from 'os';
import fetch from 'isomorphic-fetch';
import FormData from 'form-data';
import { randomUUID } from 'crypto';
import ytdl from 'ytdl-core';

// Function to extract YouTube ID from URL
function extractYouTubeId(url) {
  const regex = /(?:youtube\.com\/(?:[^\/\n\s]+\/\S+\/|(?:v|e(?:mbed)?)\/|\S*?[?&]v=)|youtu\.be\/)([a-zA-Z0-9_-]{11})/;
  const match = url.match(regex);
  return match ? match[1] : null;
}

// Function to format seconds as HH:MM:SS
function formatTime(seconds) {
  const hrs = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);
  return `${hrs.toString().padStart(2, '0')}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
}

export default async function handler(req, res) {
  // Only allow GET requests
  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  // Get YouTube video ID directly or from URL
  let videoId = req.query.id;
  const youtubeUrl = req.query.url;
  
  // If no direct ID is provided but URL is, try to extract ID from URL
  if (!videoId && youtubeUrl) {
    videoId = extractYouTubeId(youtubeUrl);
  }
  
  // Check if we have a valid video ID
  if (!videoId) {
    return res.status(400).json({ 
      error: 'Missing or invalid YouTube video ID. Use ?id=VIDEO_ID or ?url=YOUTUBE_URL' 
    });
  }
  
  // Construct a standard YouTube URL from the ID
  const standardUrl = `https://www.youtube.com/watch?v=${videoId}`;

  // Use a unique filename to avoid conflicts
  const uniqueId = randomUUID();
  const outputPath = join(tmpdir(), `youtube-audio-${uniqueId}.mp3`);

  try {
    // First, get video info to show what we're processing
    const videoInfo = await ytdl.getInfo(videoId);
    const videoTitle = videoInfo.videoDetails.title;
    const actualUrl = videoInfo.videoDetails.video_url; // Get the actual URL from the video info
    
    // Download and convert YouTube audio
    console.log(`Downloading audio for: ${videoTitle}`);
    
    // Create a write stream for the output file
    const outputStream = createWriteStream(outputPath);
    
    // Download only audio in mp3 format using ytdl
    ytdl(standardUrl, {
      filter: 'audioonly',
      quality: 'lowestaudio',
    }).pipe(outputStream);
    
    // Wait for download to complete
    await new Promise((resolve, reject) => {
      outputStream.on('finish', resolve);
      outputStream.on('error', reject);
    });
    
    console.log('Audio download complete. Sending to Whisper API...');
    
    // Prepare to send to Whisper API
    const formData = new FormData();
    formData.append('file', createReadStream(outputPath));
    formData.append('model', 'whisper-1');
    formData.append('response_format', 'verbose_json');
    
    // Send to Whisper API
    const whisperResponse = await fetch('https://api.openai.com/v1/audio/transcriptions', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${process.env.OPENAI_API_KEY}`
      },
      body: formData
    });
    
    if (!whisperResponse.ok) {
      const errorText = await whisperResponse.text();
      throw new Error(`Whisper API error: ${whisperResponse.status} - ${errorText}`);
    }
    
    // Get transcription result
    const transcription = await whisperResponse.json();
    
    // Add formatted transcript with timestamps
    let formattedTranscript = '';
    if (transcription.segments) {
      formattedTranscript = transcription.segments.map(segment => {
        return `[${formatTime(segment.start)} - ${formatTime(segment.end)}] ${segment.text}`;
      }).join('\n\n');
    }
    
    // Clean up the temporary file
    try {
      unlinkSync(outputPath);
    } catch (cleanupError) {
      console.error('Error cleaning up temp file:', cleanupError);
    }
    
    // Return the result
    return res.status(200).json({
      success: true,
      video: {
        id: videoId,
        title: videoTitle,
        url: actualUrl || standardUrl
      },
      transcript: {
        full: transcription.text,
        formatted: formattedTranscript,
        segments: transcription.segments
      }
    });
    
  } catch (error) {
    console.error('Error processing request:', error);
    
    // Clean up temp file if it exists
    try {
      unlinkSync(outputPath);
    } catch (cleanupError) {
      // Ignore cleanup errors
    }
    
    return res.status(500).json({
      error: error.message || 'An unknown error occurred'
    });
  }
}
